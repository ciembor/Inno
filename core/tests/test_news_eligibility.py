"""Regresje selekcji: wydawca nie zawsze jest autorem rozwiązania."""

import json
import logging
from unittest.mock import MagicMock

import pytest

from core.models import Idea, Institution
from core.services.institution_news import InstitutionNewsDiscoveryService
from core.services.news_html import fetch_html
from core.services.news_llm import EXTRACTION_SCHEMA, NewsInnovationLLM
from core.services.prompt_store import get_prompt


@pytest.mark.parametrize(
    ("role", "accepted"),
    [("local_reporter", True), ("creator", True), ("co_creator", True),
     ("local_adaptor", True), ("external_reference", False),
     ("routine_implementation", False), ("unknown", False)],
)
@pytest.mark.django_db
def test_roles_and_extraction_audit(role, accepted, caplog):
    client = MagicMock()
    client.responses.create.return_value.output_text = json.dumps({
        "name": "Chwytak", "canonical_name": "Chwytak", "description": "Projekt uczniów.",
        "published_on": None, "institution_role": role,
        "decision_reason": "Autorzy: uczniowie szkoły w regionie; powiat jest wydawcą.",
    })
    with caplog.at_level(logging.INFO):
        result = NewsInnovationLLM(client=client, model="test").extract(
            "Powiat", "Sukces uczniów", "https://example.org/robot", "Projekt uczniów."
        )
    assert bool(result) is accepted
    assert f"role={role}" in caplog.text
    assert "powiat jest wydawcą" in caplog.text
    assert "https://example.org/robot" in caplog.text
    assert "decision_reason" in EXTRACTION_SCHEMA["required"]
    assert "taxonomy" in EXTRACTION_SCHEMA["required"]


@pytest.mark.django_db
def test_selection_logs_both_selected_and_missing_candidates(caplog):
    client = MagicMock()
    client.responses.create.return_value.output_text = json.dumps({
        "selected_articles": [{"url": "https://example.org/a", "published_on": None}]
    })
    with caplog.at_level(logging.INFO):
        selected = NewsInnovationLLM(client=client, model="test").select_links(
            (("Projekt", "https://example.org/a"), ("Rekrutacja", "https://example.org/b")),
            "Projekt i rekrutacja",
        )
    assert len(selected) == 1
    assert "url=https://example.org/a selected=True" in caplog.text
    assert "url=https://example.org/b selected=False" in caplog.text


@pytest.mark.parametrize("mime", ["video/mp4", "application/pdf", "image/png"])
def test_binary_documents_are_rejected_before_reading(monkeypatch, mime):
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers.get_content_type.return_value = mime
    monkeypatch.setattr("core.services.news_html.urllib.request.urlopen", lambda *a, **k: response)
    with pytest.raises(OSError, match="niebędący HTML"):
        fetch_html("https://example.org/download")
    response.read.assert_not_called()


@pytest.mark.django_db
def test_prompts_distinguish_discovery_from_eligibility():
    selection_prompt = get_prompt("news_selection")
    extraction_prompt = get_prompt("news_extraction")
    assert "nie końcowa ocena innowacyjności" in selection_prompt
    assert "Nie wymagaj w zajawce dowodu nowości" in selection_prompt
    assert "Sam adres wydawcy nie potwierdza lokalności projektu" in extraction_prompt
    assert "wydawcy nie przypisuj autorstwa" in extraction_prompt
    assert "konfiguracja gotowej aplikacji" in extraction_prompt


@pytest.mark.django_db
def test_known_article_url_is_skipped_before_fetching_its_article():
    institution = Institution.objects.create(
        name="Szkoła",
        address="Rzeszów",
        news_url="https://example.org/news",
        institution_type="school",
    )
    known_url = "https://example.org/known"
    Idea.objects.create(name="Istniejąca", source_url=known_url, content="Opis")
    pages = {institution.news_url: '<a href="/known">Znany artykuł</a>'}
    client = MagicMock()
    client.responses.create.return_value.output_text = json.dumps(
        {"selected_articles": [{"url": known_url, "published_on": None}]}
    )
    assert InstitutionNewsDiscoveryService(client=client, fetcher=pages.__getitem__).discover(
        institution
    ) == ()
    assert client.responses.create.call_count == 1

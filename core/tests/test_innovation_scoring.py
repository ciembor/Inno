# Mechanical split of the former test_core.py by responsibility.

import json
from datetime import date
from unittest.mock import MagicMock

import pytest
from django.urls import reverse
from openai import APIConnectionError

from config.celery import app as celery_app
from core.models import Idea, InnovationIndicator, Institution
from core.services.innovation_scoring import (
    CRITERIA,
    InnovationScoringConfigurationError,
    InnovationScoringRequestError,
    InnovationScoringService,
    indicator_weights,
    score_innovation,
)
from core.services.institution_innovation_import import (
    InstitutionImportResult,
    InstitutionInnovationImportService,
)
from core.services.institution_news import (
    InstitutionNewsDiscoveryService,
    NewsArticle,
)
from core.services.news_llm import SelectedNewsArticle
from core.tasks import score_idea
from core.tests.support import FakeClient, scoring_response


@pytest.mark.django_db
def test_innovation_scoring_requests_a_single_calibrated_assessment():
    client = FakeClient([scoring_response()])

    result = InnovationScoringService(client=client, model="test-model").score(
        "Tytuł", "Treść inicjatywy"
    )

    assert result.total == 67
    assert [score.value for score in result.criteria] == [80, 70, 60, 50]
    assert [score.rationale for score in result.criteria] == [
        "Pewność oceny: niska. Uzasadnienie 0",
        "Pewność oceny: niska. Uzasadnienie 1",
        "Pewność oceny: niska. Uzasadnienie 2",
        "Pewność oceny: niska. Uzasadnienie 3",
    ]
    assert len(client.responses.calls) == 1
    assert [criterion.name for criterion in CRITERIA] == [
        "Nowatorstwo",
        "Wartość innowacji",
        "Replikowalność",
        "Potencjał oddziaływania",
    ]
    call = client.responses.calls[0]
    assert call["store"] is False
    assert call["reasoning"] == {"effort": "high"}
    assert call["text"]["format"]["type"] == "json_schema"
    from core.services.prompt_store import get_prompt

    assert call["instructions"] == get_prompt("innovation_assessment")
    assert "lokalne wdrożenie powszechnej technologii" in " ".join(call["instructions"].split())
    assert call["input"].startswith("Tytuł pomysłu: Tytuł")
    assert call["input"].endswith(CRITERIA[-1].question)


@pytest.mark.django_db
def test_innovation_scoring_uses_indicator_weights_from_database():
    InnovationIndicator.objects.exclude(key="novelty").update(weight=0)
    InnovationIndicator.objects.filter(key="novelty").update(weight=1)

    result = InnovationScoringService(
        client=FakeClient([scoring_response(values=(80, 70, 60, 50))]), model="test-model"
    ).score("Tytuł", "Treść")

    assert result.total == 80
    InnovationIndicator.objects.filter(key="novelty").update(weight="0.90")
    InnovationIndicator.objects.filter(key="value").update(weight="0.20")
    with pytest.raises(InnovationScoringConfigurationError, match="Suma wag"):
        indicator_weights()
    InnovationIndicator.objects.update(enabled=False)
    with pytest.raises(InnovationScoringConfigurationError, match="Brak aktywnych"):
        indicator_weights()
    with pytest.raises(InnovationScoringConfigurationError, match="Brak aktywnych"):
        InnovationScoringService(
            client=FakeClient([scoring_response(values=(80, 70, 60, 50))]), model="test-model"
        ).score("Tytuł", "Treść")


@pytest.mark.parametrize(
    "required_instruction",
    [
        "Sam brak opisu kosztów, rezultatów lub warunków wdrożenia "
        "nie uzasadnia niskiej punktacji.",
        "Jeżeli brakująca informacja mogłaby zasadniczo zmienić ocenę i nie ma podstaw "
        'do wyboru przedziału, zwróć score=null oraz confidence="low".',
        "Nie zwracaj score=null wyłącznie z powodu braku lokalnego porównania, wyników "
        "wdrożenia lub danych liczbowych.",
        "Nie zwracaj score=null wyłącznie z powodu tych braków.",
        "Dla nowatorstwa wskaż najbliższe porównywalne rozwiązanie tego samego problemu, "
        "również poza miejscem wdrożenia.",
        "Jeśli punkt odniesienia jest założeniem, oznacz to w uzasadnieniu.",
        "Najpierw dopasuj projekt do opisowego przedziału skali, następnie wybierz "
        "punktację w jego granicach.",
        "Nie wybieraj środkowego przedziału jako bezpiecznej odpowiedzi na niepewność.",
        "Brak obecnej produkcji, licznych wdrożeń lub planu promocji nie jest "
        "samodzielną podstawą obniżenia tego kryterium.",
        "ograniczenie bakterii na powierzchni nie oznacza automatycznie ograniczenia zakażeń.",
        "Dla score=null zamiast poziomu skali wskaż, jakiej informacji brakuje "
        "do wyboru przedziału.",
    ],
)
@pytest.mark.django_db
def test_scoring_request_includes_assessment_safeguards(required_instruction):
    client = FakeClient([scoring_response()])

    InnovationScoringService(client=client, model="test-model").score("Pomysł", "Opis")

    instructions = " ".join(client.responses.calls[0]["instructions"].split())
    assert required_instruction in instructions


@pytest.mark.parametrize(
    "output",
    [
        "nie jest JSON",
        json.dumps({"novelty": {"score": 80, "rationale": "Opis"}}),
        scoring_response(values=(101, 70, 60, 50)),
        scoring_response(rationales=("", "Opis", "Opis", "Opis")),
    ],
)
@pytest.mark.django_db
def test_innovation_scoring_rejects_invalid_llm_score(output):
    client = FakeClient([output])

    with pytest.raises(InnovationScoringRequestError):
        InnovationScoringService(client=client).score("Tytuł", "Treść")


@pytest.mark.django_db
def test_incomplete_assessment_has_no_total_instead_of_zero():
    result = score_innovation(
        "Pomysł", "Opis", client=FakeClient([scoring_response(values=(None, 70, 80, 60))])
    )
    assert result.total is None
    assert result.criteria[0].value is None
    assert result.criteria[1].value == 70


@pytest.mark.parametrize(
    "value, confidence", [(True, "low"), (12.5, "low"), (None, "high"), (20, "unknown")]
)
@pytest.mark.django_db
def test_scoring_rejects_invalid_confidence_or_numeric_type(value, confidence):
    payload = json.loads(scoring_response())
    payload["novelty"].update(score=value, confidence=confidence)
    with pytest.raises(InnovationScoringRequestError):
        score_innovation("Pomysł", "Opis", client=FakeClient([json.dumps(payload)]))


@pytest.mark.django_db
def test_incomplete_assessment_is_saved_and_visible(client, monkeypatch):
    idea = Idea.objects.create(name="Potencjalny pomysł", content="Opis")
    result = score_innovation(
        "Pomysł", "Opis", client=FakeClient([scoring_response(values=(None, 70, 80, 60))])
    )
    monkeypatch.setattr("core.tasks.score_innovation", lambda *_: result)
    score_idea(idea.pk, schedule_followups=False)
    idea.refresh_from_db()
    assert idea.innovation_score is None
    assert idea.scored_at is not None
    assert idea.innovation_details["Nowatorstwo"] is None
    detail = client.get(reverse("innovation_detail", args=[idea.pk])).content.decode()
    listing = client.get(reverse("submitted_innovations")).content.decode()
    assert "Brak danych do oceny" in detail
    assert "Pewność oceny: niska" in detail
    assert "Potencjalny pomysł" in listing
    assert "None/100" not in listing + detail


@pytest.mark.django_db
def test_import_deduplicates_project_name_within_institution():
    institution = Institution.objects.create(name="Uczelnia", institution_type="university")
    Idea.objects.create(
        name="Projekt Alfa", institution=institution, source_url="https://example.org/a"
    )
    discovery = MagicMock()
    discovery.discover.return_value = (
        NewsArticle("Projekt Alfa", "https://example.org/b", "Opis"),
    )
    scorer = MagicMock()
    result = InstitutionInnovationImportService(discovery=discovery, scorer=scorer).import_all()
    assert result == InstitutionImportResult(created=0, skipped=1)
    scorer.assert_not_called()


@pytest.mark.django_db
def test_extraction_receives_article_after_long_navigation():
    client = FakeClient(
        [
            json.dumps(
                {
                    "name": "Projekt",
                    "canonical_name": "Projekt",
                    "description": "Opis",
                    "published_on": None,
                    "institution_role": "creator",
                }
            )
        ]
    )
    service = InstitutionNewsDiscoveryService(
        client=client,
        fetcher=lambda _: (
            "<nav>" + "menu " * 3000 + "</nav><p>Unikalny mechanizm na końcu artykułu</p>"
        ),
    )
    service._extract_innovation(
        "Uczelnia", SelectedNewsArticle("Projekt", "https://example.org/a", None)
    )
    assert "Unikalny mechanizm na końcu artykułu" in client.responses.calls[0]["input"]


@pytest.mark.django_db
def test_discovery_selected_articles_excludes_known_urls_and_extracts_one(monkeypatch):
    institution = Institution.objects.create(name="Uczelnia", institution_type="university")
    known = "https://example.org/known"
    Idea.objects.create(name="Istniejący", source_url=known)
    service = InstitutionNewsDiscoveryService(client=FakeClient([]))
    selected = (
        SelectedNewsArticle("Znany", known, None),
        SelectedNewsArticle("Nowy", "https://example.org/new", date(2026, 11, 19)),
    )
    monkeypatch.setattr(service, "_selected_links", lambda _: selected)
    assert service.selected_articles("https://example.org/news") == (selected[1],)
    article = NewsArticle("Projekt", selected[1].url, "Pełny opis")
    monkeypatch.setattr(service, "_extract_innovation", lambda name, link: article)
    assert service.extract_article(institution, selected[1]) == article


@pytest.mark.parametrize("title, content", [("", "Treść"), ("Tytuł", "   ")])
def test_innovation_scoring_requires_title_and_content(title, content):
    with pytest.raises(ValueError, match="wymagane"):
        InnovationScoringService(client=FakeClient([])).score(title, content)


def test_innovation_scoring_requires_api_key(settings):
    settings.OPENAI_API_KEY = ""

    with pytest.raises(InnovationScoringConfigurationError, match="OPENAI_API_KEY"):
        InnovationScoringService()


def test_innovation_scoring_requires_model(settings):
    settings.OPENAI_MODEL = ""

    with pytest.raises(InnovationScoringConfigurationError, match="OPENAI_MODEL"):
        InnovationScoringService(client=FakeClient([]))


def test_innovation_scoring_creates_openai_client_from_configuration(monkeypatch, settings):
    client = FakeClient([])
    settings.OPENAI_API_KEY = "configured-key"
    monkeypatch.setattr("core.services.innovation_scoring.OpenAI", lambda **kwargs: client)

    service = InnovationScoringService()

    assert service.client is client


@pytest.mark.django_db
def test_innovation_scoring_wraps_openai_errors():
    class FailingResponses:
        @staticmethod
        def create(**kwargs):
            raise APIConnectionError(request=None)

    client = type("FailingClient", (), {"responses": FailingResponses()})()

    with pytest.raises(InnovationScoringRequestError, match="Nie udało"):
        InnovationScoringService(client=client).score("Tytuł", "Treść")


@pytest.mark.django_db
def test_score_innovation_uses_function_entry_point():
    result = score_innovation(
        " Tytuł ", " Treść ", client=FakeClient([scoring_response(values=(0, 0, 0, 0))])
    )

    assert result.total == 0


def test_celery_uses_django_configuration(settings):
    assert celery_app.main == "config"
    assert celery_app.conf.broker_url == settings.CELERY_BROKER_URL
    assert celery_app.conf.result_backend == settings.CELERY_RESULT_BACKEND

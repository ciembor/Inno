"""Testy taksonomii oraz wyjaśnialnego podobieństwa inicjatyw."""

import json

import pytest
from django.core.management import call_command
from django.urls import reverse
from openai import APIConnectionError

from core.management.commands import tag_idea_similarity
from core.models import Idea, PromptTemplate, SimilarityTag
from core.services.idea_similarity import (
    IdeaTaxonomyError,
    IdeaTaxonomyService,
    classify_idea,
    normalise_taxonomy,
    save_taxonomy,
    similar_ideas,
)
from core.tasks import classify_idea as classify_idea_task
from core.tests.support import FakeClient


def make_idea(name: str) -> Idea:
    """Tworzy minimalną inicjatywę widoczną na publicznej stronie szczegółu."""
    return Idea.objects.create(
        name=name,
        submitter_name="Anna Kowalska",
        email=f"{name.lower().replace(' ', '-')}@example.org",
        content=f"Opis {name}.",
        innovation_score=60,
    )


def tag(idea: Idea, category: str, key: str) -> SimilarityTag:
    """Przypisuje tag o czytelnej nazwie do testowej inicjatywy."""
    similarity_tag, _ = SimilarityTag.objects.get_or_create(
        category=category, key=key, defaults={"name": key.replace("-", " ")}
    )
    idea.similarity_tags.add(similarity_tag)
    return similarity_tag


@pytest.mark.django_db
def test_taxonomy_service_normalises_response_and_saves_tags():
    PromptTemplate.objects.update_or_create(
        key="similarity_tagging", defaults={"content": "Nadaj tagi."}
    )
    client = FakeClient(
        [
            json.dumps(
                {
                    "problem": ["Wykluczenie cyfrowe", "Wykluczenie cyfrowe", " "],
                    "audience": ["Seniorzy"],
                    "sector": ["Pomoc społeczna"],
                    "mechanism": ["Warsztaty"],
                    "solution_type": ["Program edukacyjny"],
                    "stage": ["Pilotaż"],
                    "territory": ["Lokalny"],
                }
            )
        ]
    )
    idea = make_idea("Cyfrowy sąsiad")

    taxonomy = IdeaTaxonomyService(client=client, model="test-model").classify(
        idea.name, idea.content
    )
    tags = save_taxonomy(idea, taxonomy)

    assert taxonomy["problem"] == ("Wykluczenie cyfrowe",)
    assert {(item.category, item.name) for item in tags} >= {
        ("problem", "Wykluczenie cyfrowe"),
        ("audience", "Seniorzy"),
    }
    assert idea.similarity_tags.count() == 7
    call = client.responses.calls[0]
    assert call["instructions"] == "Nadaj tagi."
    assert call["text"]["format"]["schema"]["required"] == [
        "problem",
        "audience",
        "sector",
        "mechanism",
        "solution_type",
        "stage",
        "territory",
    ]
    assert "Nazwa inicjatywy: Cyfrowy sąsiad" in call["input"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        "nie jest JSON",
        json.dumps(["nie jest obiektem"]),
        json.dumps({"problem": "nie jest listą"}),
    ],
)
def test_taxonomy_service_rejects_invalid_responses(payload):
    PromptTemplate.objects.update_or_create(
        key="similarity_tagging", defaults={"content": "Nadaj tagi."}
    )

    with pytest.raises(IdeaTaxonomyError, match="nieprawidłową"):
        IdeaTaxonomyService(client=FakeClient([payload]), model="test-model").classify(
            "Tytuł", "Opis"
        )


def test_taxonomy_service_requires_configuration(settings):
    settings.OPENAI_MODEL = ""
    with pytest.raises(IdeaTaxonomyError, match="OPENAI_MODEL"):
        IdeaTaxonomyService(client=FakeClient([]))

    settings.OPENAI_MODEL = "test-model"
    settings.OPENAI_API_KEY = ""
    with pytest.raises(IdeaTaxonomyError, match="OPENAI_API_KEY"):
        IdeaTaxonomyService()


def test_taxonomy_service_builds_default_openai_client(settings, monkeypatch):
    client = object()
    settings.OPENAI_MODEL = "test-model"
    settings.OPENAI_API_KEY = "test-key"
    monkeypatch.setattr("core.services.idea_similarity.OpenAI", lambda api_key: client)

    assert IdeaTaxonomyService().client is client


@pytest.mark.django_db
def test_taxonomy_service_handles_connection_failure_and_empty_source():
    PromptTemplate.objects.update_or_create(
        key="similarity_tagging", defaults={"content": "Nadaj tagi."}
    )
    with pytest.raises(IdeaTaxonomyError, match="Nazwa i opis"):
        IdeaTaxonomyService(client=FakeClient([]), model="test-model").classify(" ", "Opis")
    with pytest.raises(IdeaTaxonomyError, match="przypisać tagów"):
        IdeaTaxonomyService(
            client=FakeClient([APIConnectionError(request=object())]), model="test-model"
        ).classify("Tytuł", "Opis")


@pytest.mark.django_db
def test_similarity_ranks_and_explains_all_relationship_types(client):
    current = make_idea("Bieżąca inicjatywa")
    for category, key in (
        ("problem", "wykluczenie-cyfrowe"),
        ("audience", "seniorzy"),
        ("mechanism", "warsztaty"),
        ("solution_type", "program-edukacyjny"),
        ("territory", "lokalny"),
        ("sector", "edukacja"),
    ):
        tag(current, category, key)

    duplicate = make_idea("To samo rozwiązanie")
    adaptation = make_idea("Adaptacja rozwiązania")
    complement = make_idea("Uzupełniające rozwiązanie")
    collaboration = make_idea("Wspólny partner")
    for idea, tags in (
        (
            duplicate,
            (
                ("problem", "wykluczenie-cyfrowe"),
                ("audience", "seniorzy"),
                ("mechanism", "warsztaty"),
                ("solution_type", "program-edukacyjny"),
                ("territory", "lokalny"),
                ("sector", "edukacja"),
            ),
        ),
        (
            adaptation,
            (
                ("problem", "wykluczenie-cyfrowe"),
                ("audience", "seniorzy"),
                ("solution_type", "program-edukacyjny"),
                ("territory", "regionalny"),
            ),
        ),
        (
            complement,
            (
                ("problem", "wykluczenie-cyfrowe"),
                ("audience", "seniorzy"),
                ("solution_type", "punkt-wsparcia"),
            ),
        ),
        (
            collaboration,
            (
                ("audience", "seniorzy"),
                ("territory", "lokalny"),
                ("sector", "edukacja"),
            ),
        ),
    ):
        for category, key in tags:
            tag(idea, category, key)

    matches = similar_ideas(current)

    assert [match.idea for match in matches] == [duplicate, adaptation, complement, collaboration]
    assert [match.relationship for match in matches] == [
        "duplicate",
        "adaptation",
        "complement",
        "collaboration",
    ]
    assert matches[0].score == 100
    assert "Wspólne tagi" in matches[1].rationale
    detail = client.get(reverse("innovation_detail", args=[current.pk]))
    assert detail.status_code == 200
    assert "Podobne rozwiązania" in detail.content.decode()
    assert "Możliwa adaptacja" in detail.content.decode()


@pytest.mark.django_db
def test_similarity_ignores_one_tag_and_can_limit_results():
    current = make_idea("Pierwsza")
    tag(current, "problem", "dostepnosc")
    tag(current, "audience", "dzieci")
    one_common = make_idea("Jedna wspólna cecha")
    tag(one_common, "problem", "dostepnosc")
    enough_common = make_idea("Dwie wspólne cechy")
    tag(enough_common, "problem", "dostepnosc")
    tag(enough_common, "audience", "dzieci")

    assert similar_ideas(current, limit=1)[0].idea == enough_common
    assert normalise_taxonomy(None)["problem"] == ()

    diluted = make_idea("Wiele różnych cech")
    for category, key in (
        ("problem", "problem"),
        ("audience", "odbiorcy"),
        ("sector", "sektor"),
        ("mechanism", "mechanizm"),
        ("solution_type", "typ"),
        ("stage", "etap"),
        ("territory", "obszar"),
    ):
        tag(diluted, category, key)
    weak_match = make_idea("Słabe dopasowanie")
    tag(weak_match, "sector", "sektor")
    tag(weak_match, "stage", "etap")
    assert similar_ideas(diluted) == ()


@pytest.mark.django_db
def test_classify_idea_and_command_only_process_untagged_ideas(monkeypatch, capsys):
    first = make_idea("Pierwsza")
    second = make_idea("Druga")
    tag(first, "problem", "gotowy-tag")
    calls = []
    monkeypatch.setattr(
        tag_idea_similarity,
        "classify_idea",
        lambda idea: calls.append(idea.pk)
        if idea == second
        else (_ for _ in ()).throw(IdeaTaxonomyError("Błąd LLM")),
    )

    call_command("tag_idea_similarity")
    assert calls == [second.pk]
    assert "Otagowano: 1. Błędy: 0." in capsys.readouterr().out

    calls.clear()
    monkeypatch.setattr(
        tag_idea_similarity, "classify_idea", lambda idea: calls.append(idea.pk)
    )
    call_command("tag_idea_similarity", "--all", "--limit", "1")
    assert calls == [first.pk]


@pytest.mark.django_db
def test_tag_command_reports_per_idea_failure(monkeypatch, capsys):
    idea = make_idea("Niedostępna klasyfikacja")
    monkeypatch.setattr(
        tag_idea_similarity,
        "classify_idea",
        lambda _idea: (_ for _ in ()).throw(IdeaTaxonomyError("Błąd LLM")),
    )

    call_command("tag_idea_similarity")

    captured = capsys.readouterr()
    assert f"{idea.pk}: Błąd LLM" in captured.err
    assert "Otagowano: 0. Błędy: 1." in captured.out


@pytest.mark.django_db
def test_classify_idea_uses_service(monkeypatch):
    idea = make_idea("Klasyfikowana")
    monkeypatch.setattr(
        "core.services.idea_similarity.IdeaTaxonomyService.classify",
        lambda self, title, content: {"problem": ("bariera",)},
    )

    tags = classify_idea(idea, client=FakeClient([]))

    assert [(item.category, item.key) for item in tags] == [("problem", "bariera")]


@pytest.mark.django_db
def test_classify_idea_task_delegates_to_similarity_service(monkeypatch):
    idea = make_idea("Zadanie klasyfikacji")
    seen = []
    monkeypatch.setattr("core.tasks.classify_idea_tags", lambda item: seen.append(item.pk))

    assert classify_idea_task.run(idea.pk) is None
    assert seen == [idea.pk]


@pytest.mark.django_db
def test_save_taxonomy_skips_values_without_a_technical_key():
    idea = make_idea("Pusty klucz")

    assert save_taxonomy(idea, {"problem": ("!!!",)}) == ()


@pytest.mark.django_db
def test_similarity_tag_has_a_readable_representation():
    similarity_tag = SimilarityTag.objects.create(
        category="problem", key="brak-dostepnosci", name="Brak dostępności"
    )

    assert str(similarity_tag) == "Problem: Brak dostępności"

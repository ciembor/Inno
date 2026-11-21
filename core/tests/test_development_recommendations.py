"""Testy generowania i publicznej prezentacji rekomendacji rozwoju."""

import json
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from openai import OpenAIError

from core.models import (
    DevelopmentRecommendation,
    Idea,
    IdeaIndicatorScore,
    InnovationIndicator,
    PartnerOrganization,
    PartnerTag,
)
from core.services.development_recommendations import (
    DevelopmentRecommendationError,
    DevelopmentRecommendationService,
    recommend_development,
)
from core.services.partner_matching import recommended_partners
from core.services.partner_needs import add_default_partner_needs
from core.tasks import recommend_idea


class FakeResponses:
    def __init__(self, payload):
        self.payload = payload

    def create(self, **kwargs):
        self.kwargs = kwargs
        return type("Response", (), {"output_text": self.payload})()


class FakeClient:
    def __init__(self, payload):
        self.responses = FakeResponses(payload)


@pytest.mark.django_db
def test_recommendation_service_uses_prompt_scores_and_validates_output(settings):
    settings.OPENAI_MODEL = "test-model"
    idea = Idea.objects.create(
        name="Pomysł", submitter_name="Anna", email="anna@example.org", content="Opis działania"
    )
    indicator = InnovationIndicator.objects.first()
    IdeaIndicatorScore.objects.create(idea=idea, indicator=indicator, score=70, rationale="Dowód")
    payload = json.dumps(
        {
            "stage": "pilot",
            "development_path": "partnership",
            "next_step": "Ustal pilotaż.",
            "rationale": "Opis wskazuje potrzebę testu.",
            "risk": "Nieznane zasoby.",
        }
    )
    client = FakeClient(payload)
    result = DevelopmentRecommendationService(client=client).recommend(idea)
    assert result.stage == "pilot"
    assert "Opis działania" in client.responses.kwargs["input"]
    assert client.responses.kwargs["text"]["format"]["name"] == "development_recommendation"
    with pytest.raises(DevelopmentRecommendationError):
        DevelopmentRecommendationService._parse("{\"stage\": \"pilot\"}")
    with pytest.raises(DevelopmentRecommendationError):
        DevelopmentRecommendationService._parse(
            json.dumps(
                {
                    "stage": "pilot",
                    "development_path": "transfer",
                    "next_step": "Krok",
                    "rationale": "Powód",
                    "risk": " ",
                }
            )
        )


@pytest.mark.django_db
def test_recommendation_service_handles_configuration_and_api_errors(settings, monkeypatch):
    settings.OPENAI_MODEL = ""
    with pytest.raises(DevelopmentRecommendationError, match="OPENAI_MODEL"):
        DevelopmentRecommendationService(client=FakeClient("{}"))

    settings.OPENAI_MODEL = "test-model"
    settings.OPENAI_API_KEY = ""
    with pytest.raises(DevelopmentRecommendationError, match="OPENAI_API_KEY"):
        DevelopmentRecommendationService()

    created = []
    monkeypatch.setattr(
        "core.services.development_recommendations.OpenAI",
        lambda api_key: created.append(api_key) or FakeClient("{}"),
    )
    settings.OPENAI_API_KEY = "key"
    assert isinstance(DevelopmentRecommendationService().client, FakeClient)
    assert created == ["key"]

    idea = Idea.objects.create(
        name="Bez ocen", submitter_name="A", email="a@example.org", content="Opis"
    )
    failing = FakeClient("{}")
    failing.responses.create = lambda **_: (_ for _ in ()).throw(OpenAIError("API"))
    with pytest.raises(DevelopmentRecommendationError, match="wygenerować"):
        DevelopmentRecommendationService(client=failing).recommend(idea)


@pytest.mark.django_db
def test_recommendation_task_persists_and_public_detail_shows_it(monkeypatch, client):
    idea = Idea.objects.create(
        name="Inicjatywa",
        submitter_name="Anna",
        email="anna@example.org",
        content="Opis",
        innovation_score=80,
        scored_at=timezone.now()
    )
    recommendation = type(
        "Recommendation",
        (),
        {
            "stage": "pilot",
            "development_path": "transfer",
            "next_step": "Przygotuj opis wdrożenia.",
            "rationale": "Można przenieść model.",
            "risk": "Różne warunki lokalne.",
        },
    )()
    monkeypatch.setattr("core.tasks.recommend_development", lambda _: recommendation)
    recommend_idea.run(idea.pk)
    saved = DevelopmentRecommendation.objects.get(idea=idea)
    assert saved.development_path == "transfer"
    assert str(saved) == "Inicjatywa: Transfer do innej organizacji"
    assert set(idea.partner_needs.values_list("key", flat=True)) == {"transfer", "wdrozenie"}
    result = recommend_development(idea, client=FakeClient(json.dumps({
        "stage": "pilot", "development_path": "transfer", "next_step": "Krok",
        "rationale": "Powód", "risk": "Ryzyko"
    })))
    assert result.next_step == "Krok"
    detail = client.get(reverse("innovation_detail", args=[idea.pk])).content.decode()
    assert "Rekomendowany dalszy rozwój" in detail
    assert "Przygotuj opis wdrożenia." in detail


@pytest.mark.django_db
def test_recommendation_task_retries_transient_generation_failure(monkeypatch):
    idea = Idea.objects.create(name="Inicjatywa", content="Opis")
    failure = DevelopmentRecommendationError("LLM chwilowo niedostępny")
    monkeypatch.setattr(
        "core.tasks.recommend_development", lambda _: (_ for _ in ()).throw(failure)
    )

    with (
        patch.object(recommend_idea, "retry", side_effect=Retry()) as retry,
        pytest.raises(Retry),
    ):
        recommend_idea(idea.pk)

    assert retry.call_args.kwargs == {"exc": failure, "countdown": 10}
    assert recommend_idea.max_retries is None


@pytest.mark.django_db
def test_recommendation_command_queues_only_scored_ideas_without_recommendations(monkeypatch):
    pending = Idea.objects.create(name="Do uzupełnienia", content="Opis", scored_at=timezone.now())
    completed = Idea.objects.create(name="Gotowa", content="Opis", scored_at=timezone.now())
    DevelopmentRecommendation.objects.create(
        idea=completed,
        stage="pilot",
        development_path="pilot",
        next_step="Krok",
        rationale="Powód",
        risk="Ryzyko",
    )
    queued = []
    monkeypatch.setattr("core.tasks.recommend_idea.delay", queued.append)

    call_command("generate_development_recommendations")

    assert queued == [pending.pk]


@pytest.mark.django_db
def test_default_partner_needs_preserve_administrator_selection():
    idea = Idea.objects.create(name="Inicjatywa", content="Opis")
    selected = PartnerTag.objects.get(key="finansowanie")
    idea.partner_needs.add(selected)

    add_default_partner_needs(idea, "pilot")

    assert list(idea.partner_needs.values_list("key", flat=True)) == ["finansowanie"]


@pytest.mark.django_db
def test_partner_matching_is_tag_based_limited_and_visible_on_the_detail(client):
    idea = Idea.objects.create(
        name="Inicjatywa z potrzebą",
        submitter_name="Anna",
        email="anna@example.org",
        content="Opis",
        innovation_score=80,
        scored_at=timezone.now(),
    )
    pilot = PartnerTag.objects.create(key="pilotaz-test", name="Pilotaż testowy")
    funding = PartnerTag.objects.create(key="funding-test", name="Finansowanie testowe")
    idea.partner_needs.add(pilot, funding)
    first = PartnerOrganization.objects.create(
        name="Partner wdrożeniowy",
        organization_type="implementation",
        description="Testuje rozwiązanie.",
    )
    first.tags.add(pilot, funding)
    inactive = PartnerOrganization.objects.create(
        name="Nieaktywny partner",
        organization_type="funder",
        description="Nie powinien się pojawić.",
        is_active=False,
    )
    inactive.tags.add(pilot)
    matches = recommended_partners(idea, limit=1)
    assert matches[0].organization == first
    assert matches[0].matching_tags == ("Finansowanie testowe", "Pilotaż testowy")
    assert "Wspólne obszary" in matches[0].rationale
    assert recommended_partners(Idea.objects.create(name="Bez potrzeb")) == ()
    detail = client.get(reverse("innovation_detail", args=[idea.pk])).content.decode()
    assert "Partnerzy do dalszego rozwoju" in detail
    assert first.name in detail
    assert inactive.name not in detail

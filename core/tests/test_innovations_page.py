# Mechanical split of the former test_core.py by responsibility.

from datetime import date
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.urls import reverse
from django.utils import timezone

from core.models import Idea, IdeaIndicatorScore, Institution
from core.services.innovation_scoring import (
    CRITERIA,
    CriterionScore,
    InnovationScore,
    InnovationScoringRequestError,
)
from core.tasks import score_idea


@pytest.mark.django_db
def test_score_idea_task_persists_serializable_result(monkeypatch):
    idea = Idea.objects.create(
        name="Tytuł",
        submitter_name="Anna Kowalska",
        email="anna@example.org",
        content="Treść",
        relative_novelty=80,
        relative_value=70,
        relative_replicability=60,
        relative_impact=50,
        relative_score=68,
        relative_scored_at=timezone.now(),
    )
    result = InnovationScore(
        total=71,
        criteria=(CriterionScore(criterion=CRITERIA[0], value=80, rationale="Wyróżnia się."),),
    )
    monkeypatch.setattr("core.tasks.score_innovation", lambda title, content: result)
    queued = []
    monkeypatch.setattr("core.tasks.recommend_idea.delay", queued.append)

    assert score_idea.run(idea.pk) == {
        "total": 71,
        "criteria": {"Nowatorstwo": 80},
        "rationales": {"Nowatorstwo": "Wyróżnia się."},
    }
    idea.refresh_from_db()
    assert idea.innovation_score == 71
    assert idea.innovation_details == {"Nowatorstwo": 80}
    assert idea.innovation_rationales == {"Nowatorstwo": "Wyróżnia się."}
    assert idea.scored_at is not None
    assert idea.relative_novelty is None
    assert idea.relative_value is None
    assert idea.relative_replicability is None
    assert idea.relative_impact is None
    assert idea.relative_score is None
    assert idea.relative_scored_at is None
    assert IdeaIndicatorScore.objects.filter(
        idea=idea,
        indicator__key=CRITERIA[0].key,
        score=80,
        rationale="Wyróżnia się.",
    ).exists()
    assert queued == []  # callback uruchomi się po zatwierdzeniu transakcji produkcyjnej


@pytest.mark.django_db
def test_score_idea_retries_transient_scoring_failure(monkeypatch):
    idea = Idea.objects.create(name="Tytuł", content="Treść")
    failure = InnovationScoringRequestError("LLM chwilowo niedostępny")
    monkeypatch.setattr("core.tasks.score_innovation", lambda *_: (_ for _ in ()).throw(failure))

    with (
        patch.object(score_idea, "retry", side_effect=Retry()) as retry,
        pytest.raises(Retry),
    ):
        score_idea(idea.pk)

    assert retry.call_args.kwargs == {"exc": failure, "countdown": 10}
    assert score_idea.max_retries is None


@pytest.mark.django_db
def test_innovations_page_shows_scores_and_paginates(client):
    for number in range(10):
        Idea.objects.create(
            name=f"Inicjatywa {number}",
            submitter_name="Anna Kowalska",
            email=f"anna{number}@example.org",
            content="Treść",
            source_url=f"https://example.org/inicjatywa-{number}",
            innovation_score=70 + number,
            innovation_details={
                "Nowatorstwo": 80,
                "Wartość innowacji": 80,
                "Replikowalność": 80,
                "Potencjał oddziaływania": number,
            },
        )
    Idea.objects.create(
        name="Nieoceniona inicjatywa",
        submitter_name="Jan Kowalski",
        email="jan@example.org",
        content="Treść",
        source_url="https://example.org/starsza",
    )

    first_page = client.get(reverse("innovations"))
    second_page = client.get(reverse("innovations"), {"page": 2})
    impact_page = client.get(reverse("innovations"), {"sort": "impact"})
    invalid_sort_page = client.get(reverse("innovations"), {"sort": "unknown"})

    assert first_page.status_code == 200
    assert 'aria-current="page">Pobrane innowacje' in first_page.content.decode()
    assert "Nieoceniona inicjatywa" not in first_page.content.decode()
    assert "79.0" in first_page.content.decode()
    assert "79.0/100" not in first_page.content.decode()
    assert "Następna" in first_page.content.decode()
    assert "Dodano:" in first_page.content.decode()
    assert 'class="sort" method="get"' in first_page.content.decode()
    assert ">Sortuj</button>" not in first_page.content.decode()
    assert "Inicjatywa 0" in second_page.content.decode()
    assert "Poprzednia" in second_page.content.decode()
    assert impact_page.context["page"].object_list[0].name == "Inicjatywa 9"
    assert invalid_sort_page.context["sort"] == "score"


@pytest.mark.django_db
def test_innovations_page_sorts_by_article_publication_date(client):
    Idea.objects.create(
        name="Starsza inicjatywa",
        submitter_name="Anna Kowalska",
        email="anna@example.org",
        content="Treść",
        source_url="https://example.org/nowsza",
        innovation_score=50,
        published_at=date(2026, 1, 10),
    )
    newest = Idea.objects.create(
        name="Nowsza inicjatywa",
        submitter_name="Jan Kowalski",
        email="jan@example.org",
        content="Treść",
        source_url="https://example.org/bez-daty",
        innovation_score=60,
        published_at=date(2026, 3, 5),
    )
    Idea.objects.create(
        name="Inicjatywa bez daty publikacji",
        submitter_name="Maria Kowalska",
        email="maria@example.org",
        content="Treść",
        innovation_score=70,
    )

    response = client.get(reverse("innovations"), {"sort": "date"})
    content = response.content.decode()

    assert "Nowsza inicjatywa" in content
    assert "Opublikowano: 05.03.2026" in content
    assert "Data publikacji" in content
    assert response.context["page"].object_list[0] == newest
    assert "published_from" not in content
    assert "published_to" not in content


@pytest.mark.django_db
def test_innovations_page_filters_by_institution_type_and_keeps_filter_in_pagination(client):
    school = Institution.objects.create(
        name="Szkoła testowa", address="Rzeszów", institution_type="school"
    )
    local_government = Institution.objects.create(
        name="Samorząd testowy", address="Rzeszów", institution_type="local_government"
    )
    university = Institution.objects.create(
        name="Uczelnia testowa", address="Rzeszów", institution_type="university"
    )
    other = Institution.objects.create(
        name="Inna instytucja testowa", address="Rzeszów", institution_type="other"
    )
    for number in range(10):
        Idea.objects.create(
            name=f"Szkolna inicjatywa {number}",
            submitter_name="Anna Kowalska",
            email=f"szkola{number}@example.org",
            content="Treść",
            source_url=f"https://example.org/szkolna-{number}",
            institution=school,
            innovation_score=70,
            innovation_details={"Nowatorstwo": 70},
        )
    Idea.objects.create(
        name="Uczelniana inicjatywa",
        submitter_name="Jan Kowalski",
        email="uczelnia@example.org",
        content="Treść",
        source_url="https://example.org/uczelniana",
        institution=university,
        innovation_score=80,
        innovation_details={"Nowatorstwo": 80},
    )
    Idea.objects.create(
        name="Samorządowa inicjatywa",
        submitter_name="Jan Kowalski",
        email="samorzad@example.org",
        content="Treść",
        source_url="https://example.org/samorzadowa",
        institution=local_government,
        innovation_score=80,
        innovation_details={"Nowatorstwo": 80},
    )
    Idea.objects.create(
        name="Inna inicjatywa",
        submitter_name="Jan Kowalski",
        email="inna@example.org",
        content="Treść",
        source_url="https://example.org/inna",
        institution=other,
        innovation_score=80,
        innovation_details={"Nowatorstwo": 80},
    )

    response = client.get(reverse("innovations"), {"type": "school"})
    second_page = client.get(reverse("innovations"), {"type": "school", "page": 2})
    invalid_type = client.get(reverse("innovations"), {"type": "unknown"})

    content = response.content.decode()
    assert "Szkolna inicjatywa" in content
    assert "Uczelniana inicjatywa" not in content
    assert 'value="school" selected' in content
    assert "Typ instytucji" in content
    assert ">Szkoły (10 innowacji)</option>" in content
    assert ">Uczelnie (1 innowacji)</option>" in content
    assert ">Samorządy (1 innowacji)</option>" in content
    assert ">Inne instytucje (1 innowacji)</option>" in content
    assert "type=school" in content
    assert "Szkolna inicjatywa 0" in second_page.content.decode()
    assert invalid_type.context["institution_type"] == ""


@pytest.mark.django_db
def test_innovations_page_counts_and_filters_ideas_without_source_institution(client):
    institution = Institution.objects.create(
        name="Szkoła", address="Rzeszów", institution_type="school"
    )
    Idea.objects.create(
        name="Ze źródłem instytucjonalnym",
        content="Treść",
        source_url="https://example.org/instytucja",
        institution=institution,
        innovation_score=70,
    )
    unassigned = Idea.objects.create(
        name="Bez instytucji źródłowej",
        content="Treść",
        source_url="https://example.org/bez-instytucji",
        innovation_score=80,
    )

    response = client.get(reverse("innovations"))
    filtered = client.get(reverse("innovations"), {"type": "unassigned"})

    assert "Szkoły (1 innowacji)" in response.content.decode()
    assert "NCBR (1 innowacji)" in response.content.decode()
    assert list(filtered.context["page"].object_list) == [unassigned]
    assert 'value="unassigned" selected' in filtered.content.decode()


@pytest.mark.django_db
def test_innovations_page_displays_empty_state(client):
    response = client.get(reverse("innovations"))

    assert "Pobrane innowacje pojawią się tutaj" in response.content.decode()


@pytest.mark.django_db
def test_submitted_innovations_are_shown_in_a_separate_catalog(client):
    submitted = Idea.objects.create(
        name="Zgłoszony pomysł",
        submitter_name="Anna Kowalska",
        email="anna@example.org",
        content="Treść",
        innovation_score=75,
    )
    Idea.objects.create(
        name="Pobrany pomysł",
        submitter_name="Instytucja",
        email="kontakt@example.org",
        content="Treść",
        source_url="https://example.org/pobrany",
        innovation_score=80,
    )

    response = client.get(reverse("submitted_innovations"))
    content = response.content.decode()

    assert "Zgłoszony pomysł" in content
    assert "Pobrany pomysł" not in content
    assert "Zgłoszone innowacje" in content
    assert 'aria-current="page">Zgłoszone innowacje' in content
    assert "Typ instytucji" not in content
    assert client.get(reverse("innovation_detail", args=[submitted.pk])).context["back_page"] == (
        "submitted_innovations"
    )


@pytest.mark.django_db
def test_submitted_innovations_show_and_sort_by_added_date(client):
    older = Idea.objects.create(
        name="Starsze zgłoszenie",
        submitter_name="Anna Kowalska",
        email="anna@example.org",
        content="Treść",
        innovation_score=70,
        published_at=date(2026, 1, 1),
    )
    newer = Idea.objects.create(
        name="Nowsze zgłoszenie",
        submitter_name="Jan Kowalski",
        email="jan@example.org",
        content="Treść",
        innovation_score=70,
        published_at=date(2026, 11, 1),
    )
    Idea.objects.filter(pk=older.pk).update(created_at="2026-02-01T12:00:00+00:00")
    Idea.objects.filter(pk=newer.pk).update(created_at="2026-01-01T12:00:00+00:00")

    response = client.get(reverse("submitted_innovations"), {"sort": "date"})
    content = response.content.decode()

    assert response.context["page"].object_list[0] == older
    assert "Data dodania" in content
    assert "Data publikacji" not in content
    assert "01.02.2026" in content

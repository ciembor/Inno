# Mechanical split of the former test_core.py by responsibility.

from datetime import date
from unittest.mock import MagicMock, call

import pytest
from django.core.management import call_command

from core.management.commands import (
    backfill_publication_dates,
    import_institution_innovations,
)
from core.models import Idea, Institution, InstitutionImportRun
from core.services.innovation_scoring import (
    CRITERIA,
    CriterionScore,
    InnovationScore,
)
from core.services.institution_innovation_import import (
    InstitutionImportResult,
    InstitutionInnovationImportService,
)
from core.services.institution_news import (
    NewsArticle,
)


@pytest.mark.django_db
def test_institution_innovation_import_creates_scored_ideas_without_duplicates():
    institution = Institution.objects.create(
        name="Uczelnia",
        address="Rzeszów",
        news_url="https://uczelnia.example/aktualnosci",
        institution_type="university",
    )
    article = NewsArticle(
        "Innowacja",
        "https://uczelnia.example/innowacja",
        "Opis inicjatywy",
        published_on=date(2026, 11, 17),
        institution_role="co_creator",
        taxonomy={"problem": ("wykluczenie cyfrowe",), "audience": ("seniorzy",)},
    )
    discovery = type("Discovery", (), {"discover": lambda self, selected: (article,)})()
    score = InnovationScore(
        total=75,
        criteria=(CriterionScore(criterion=CRITERIA[0], value=75, rationale="Nowe rozwiązanie."),),
    )
    service = InstitutionInnovationImportService(
        discovery=discovery, scorer=lambda title, body: score
    )

    assert service.import_all() == InstitutionImportResult(created=1, skipped=0)
    assert service.import_all() == InstitutionImportResult(created=0, skipped=1)
    idea = Idea.objects.get(source_url=article.url)
    assert idea.institution == institution
    assert idea.innovation_score == 75
    assert idea.published_at == date(2026, 11, 17)
    assert idea.institution_role == Idea.InstitutionRole.CO_CREATOR
    assert set(idea.similarity_tags.values_list("name", flat=True)) == {
        "wykluczenie cyfrowe",
        "seniorzy",
    }


@pytest.mark.django_db
def test_institution_import_deduplicates_canonical_innovation_across_institutions():
    first = Institution.objects.create(
        name="Pierwsza", address="Rzeszów", institution_type="university"
    )
    second = Institution.objects.create(
        name="Druga", address="Krosno", institution_type="university"
    )
    Idea.objects.create(
        name="Wspólny program", institution=first, source_url="https://example.org/a"
    )
    article = NewsArticle(
        "Lokalna nazwa",
        "https://example.org/b",
        "Opis",
        canonical_name="Wspólny program",
    )
    discovery = type("Discovery", (), {"discover": lambda self, selected: (article,)})()

    result = InstitutionInnovationImportService(discovery=discovery).import_all()

    assert result == InstitutionImportResult(created=0, skipped=2)
    assert not Idea.objects.filter(institution=second).exists()


@pytest.mark.django_db
def test_institution_import_can_resume_after_a_known_institution():
    previous = Institution.objects.create(
        name="A szkoła", address="Rzeszów", institution_type="school"
    )
    following = Institution.objects.create(
        name="B szkoła", address="Rzeszów", institution_type="school"
    )
    article = NewsArticle("Innowacja", "https://uczelnia.example/innowacja", "Opis")
    seen = []
    discovery = type(
        "Discovery", (), {"discover": lambda self, institution: seen.append(institution) or ()}
    )()

    result = InstitutionInnovationImportService(discovery=discovery).import_all(
        "school", start_after_id=previous.pk
    )

    assert result == InstitutionImportResult(created=0, skipped=0)
    assert seen == [following]
    assert article.title == "Innowacja"


@pytest.mark.django_db
def test_import_institution_innovations_command_reports_import_result(monkeypatch):
    Institution.objects.create(
        pk=12, name="Poprzednia szkoła", address="Rzeszów", institution_type="school"
    )
    result = InstitutionImportResult(created=2, skipped=3)
    import_options = []
    service = type(
        "Service",
        (),
        {
            "import_all": lambda self, institution_type, start_after_id=None: (
                import_options.append((institution_type, start_after_id)) or result
            )
        },
    )()
    monkeypatch.setattr(
        import_institution_innovations,
        "InstitutionInnovationImportService",
        lambda: service,
    )

    call_command(
        "import_institution_innovations", "--institution-type", "school", "--start-after-id", "12"
    )
    assert import_options == [("school", 12)]
    run = InstitutionImportRun.objects.get()
    assert run.status == "completed"
    assert run.institution_types == ["school"]
    assert (run.ideas_created, run.ideas_skipped) == (2, 3)
    assert run.finished_at is not None
    assert run.institutions_per_minute is not None


@pytest.mark.django_db
def test_import_command_records_all_types_and_a_failed_run(monkeypatch):
    Institution.objects.create(name="Szkoła", institution_type="school")
    Institution.objects.create(name="Uczelnia", institution_type="university")
    calls = []

    class Service:
        def import_all(self, institution_type, start_after_id=None):
            calls.append((institution_type, start_after_id))
            if institution_type == "school":
                raise RuntimeError("Pobieranie nieudane")
            return InstitutionImportResult(created=0, skipped=0)

    monkeypatch.setattr(
        import_institution_innovations, "InstitutionInnovationImportService", Service
    )

    with pytest.raises(RuntimeError, match="Pobieranie nieudane"):
        call_command("import_institution_innovations", "--all-types")

    run = InstitutionImportRun.objects.get()
    assert calls == [("university", None), ("school", None)]
    assert run.status == "failed"
    assert run.error == "Pobieranie nieudane"
    assert run.finished_at is not None


def test_import_command_rejects_resuming_all_types(capsys):
    call_command("import_institution_innovations", "--all-types", "--start-after-id", "12")

    assert "nie można łączyć" in capsys.readouterr().err


@pytest.mark.django_db
def test_backfill_publication_dates_command_saves_only_dates_found_by_llm(monkeypatch):
    first = Idea.objects.create(
        name="Pierwsza",
        submitter_name="Anna Kowalska",
        email="anna@example.org",
        content="Treść",
        source_url="https://example.org/first",
    )
    second = Idea.objects.create(
        name="Druga",
        submitter_name="Jan Kowalski",
        email="jan@example.org",
        content="Treść",
        source_url="https://example.org/second",
    )
    service = MagicMock()
    service.extract.side_effect = [date(2026, 10, 1), None]
    monkeypatch.setattr(backfill_publication_dates, "PublicationDateService", lambda: service)

    call_command("backfill_publication_dates", "--limit", "1")

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.published_at == date(2026, 10, 1)
    assert second.published_at is None
    assert service.extract.call_args_list == [call("Pierwsza", "https://example.org/first")]

    call_command("backfill_publication_dates")

    assert service.extract.call_args_list[-1].args == ("Druga", "https://example.org/second")

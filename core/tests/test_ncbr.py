"""Testy importu projektów z publicznej wyszukiwarki NCBR."""

import pytest
from django.core.management import call_command

from core.management.commands import import_ncbr_projects
from core.models import Idea, NCBRImportRun
from core.services import ncbr
from core.services.ncbr import (
    NCBR_LABEL,
    NCBRImportResult,
    NCBRImportService,
    NCBRProject,
    _ProjectsParser,
)
from core.tasks import import_ncbr_projects as import_ncbr_projects_task

CATALOG = """
<details><summary>Projekt z Podkarpacia</summary>
  <p>Tytuł projektu</p><p>Projekt z Podkarpacia</p>
  <p>Nazwa Beneficjenta/Beneficjentów</p><p>Instytucja regionalna</p>
  <p>Region:</p><p>województwo podkarpackie</p>
  <p>Słowa Kluczowe:</p><p>edukacja, technologia</p>
  <a href="https://www.gov.pl/web/ncbr/projekt-z-podkarpacia">Dowiedz się więcej</a>
</details>
<details><summary>Projekt spoza regionu</summary>
  <p>Region:</p><p>małopolskie</p>
  <a href="https://www.gov.pl/web/ncbr/projekt-spoza-regionu">Dowiedz się więcej</a>
</details>
<details><summary>Niekompletny projekt podkarpacki</summary>
  <p>Region:</p><p>Podkarpackie</p>
</details>
"""


def test_ncbr_discovery_reads_all_projects_with_source_link():
    projects = ncbr.NCBRDiscoveryService(fetcher=lambda url: CATALOG).discover()

    assert projects == (
        NCBRProject(
            title="Projekt z Podkarpacia",
            content=(
                "Projekt z Podkarpacia\n\nTytuł projektu\n\nProjekt z Podkarpacia\n\n"
                "Nazwa Beneficjenta/Beneficjentów\n\nInstytucja regionalna\n\n"
                "Region:\n\nwojewództwo podkarpackie\n\nSłowa Kluczowe:\n\n"
                "edukacja, technologia\n\nDowiedz się więcej"
            ),
            url="https://www.gov.pl/web/ncbr/projekt-z-podkarpacia",
        ),
        NCBRProject(
            title="Projekt spoza regionu",
            content=(
                "Projekt spoza regionu\n\nRegion:\n\nmałopolskie\n\nDowiedz się więcej"
            ),
            url="https://www.gov.pl/web/ncbr/projekt-spoza-regionu",
        ),
    )


def test_ncbr_parser_keeps_nested_details_in_the_parent_project():
    parser = _ProjectsParser()

    parser.feed("<details>Projekt<details>Uzupełnienie</details>Końcowy opis</details>")

    assert parser.projects == [(["Projekt", "Uzupełnienie", "Końcowy opis"], [])]


@pytest.mark.django_db
def test_ncbr_import_is_idempotent_queues_scoring_and_supports_dry_run(
    django_capture_on_commit_callbacks,
):
    project = NCBRProject("Projekt", "Opis projektu", "https://ncbr.example/projekt")
    queued = []
    service = NCBRImportService(
        discovery=type("Discovery", (), {"discover": lambda self: (project,)})(),
        queue_score=queued.append,
    )

    with django_capture_on_commit_callbacks(execute=True):
        assert service.import_projects() == NCBRImportResult(created=1, skipped=0)
    idea = Idea.objects.get(source_url=project.url)
    assert idea.source_label == NCBR_LABEL
    assert queued == [idea.pk]
    assert service.import_projects() == NCBRImportResult(created=0, skipped=1)

    dry_project = NCBRProject("Nowy", "Opis", "https://ncbr.example/nowy")
    dry_service = NCBRImportService(
        discovery=type("Discovery", (), {"discover": lambda self: (dry_project,)})(),
        queue_score=queued.append,
    )
    assert dry_service.import_projects(dry_run=True) == NCBRImportResult(created=1, skipped=0)
    assert not Idea.objects.filter(source_url=dry_project.url).exists()


def test_ncbr_score_queue_delegates_to_the_existing_celery_task(monkeypatch):
    queued = []
    monkeypatch.setattr("core.tasks.score_idea.delay", queued.append)

    ncbr._queue_score(42)

    assert queued == [42]


@pytest.mark.django_db
def test_ncbr_task_records_a_separate_completed_import_run(monkeypatch):
    project = NCBRProject("Projekt", "Opis", "https://ncbr.example/zadanie")
    calls = []

    class Discovery:
        def discover(self):
            return (project,)

    class Service:
        def import_projects(self, *, projects):
            calls.append(projects)
            return NCBRImportResult(created=1, skipped=0)

    monkeypatch.setattr("core.tasks.NCBRDiscoveryService", Discovery)
    monkeypatch.setattr("core.tasks.NCBRImportService", Service)
    run = NCBRImportRun.objects.create(status="pending")

    import_ncbr_projects_task.run(run.pk)

    run.refresh_from_db()
    assert calls == [(project,)]
    assert run.status == "completed"
    assert (run.projects_total, run.projects_processed, run.ideas_created) == (1, 1, 1)
    assert run.finished_at is not None
    assert run.heartbeat_at is not None
    assert [event.message for event in run.events.all()] == [
        "Zakończono: dodano 1, pominięto 0.",
        "Pobieranie ogólnopolskiego katalogu sukcesów beneficjentów NCBR",
    ]


@pytest.mark.django_db
def test_ncbr_task_ignores_non_pending_runs_and_records_failure(monkeypatch):
    completed = NCBRImportRun.objects.create(status="completed")
    import_ncbr_projects_task.run(completed.pk)
    assert completed.events.count() == 0

    class FailingDiscovery:
        def discover(self):
            raise RuntimeError("NCBR niedostępne")

    monkeypatch.setattr("core.tasks.NCBRDiscoveryService", FailingDiscovery)
    failed = NCBRImportRun.objects.create(status="pending")
    with pytest.raises(RuntimeError, match="niedostępne"):
        import_ncbr_projects_task.run(failed.pk)
    failed.refresh_from_db()
    assert failed.status == "failed"
    assert failed.finished_at is not None
    assert failed.error == "NCBR niedostępne"
    assert failed.events.first().message == "Błąd: NCBR niedostępne"

    class StoppingDiscovery:
        def discover(self):
            NCBRImportRun.objects.filter(pk=stopped.pk).update(status="stopped")
            raise RuntimeError("zatrzymano")

    monkeypatch.setattr("core.tasks.NCBRDiscoveryService", StoppingDiscovery)
    stopped = NCBRImportRun.objects.create(status="pending")
    with pytest.raises(RuntimeError, match="zatrzymano"):
        import_ncbr_projects_task.run(stopped.pk)
    stopped.refresh_from_db()
    assert stopped.status == "stopped"
    assert stopped.events.count() == 1


@pytest.mark.parametrize("dry_run", [False, True])
def test_ncbr_command_reports_import_result(monkeypatch, capsys, dry_run):
    calls = []

    class Service:
        def import_projects(self, *, dry_run):
            calls.append(dry_run)
            return NCBRImportResult(created=2, skipped=3)

    monkeypatch.setattr(import_ncbr_projects, "NCBRImportService", Service)
    arguments = ["--dry-run"] if dry_run else []

    call_command("import_ncbr_projects", *arguments)

    assert calls == [dry_run]
    assert ("Znaleziono" if dry_run else "Dodano") in capsys.readouterr().out

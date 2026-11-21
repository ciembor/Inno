"""Jeden trwały krok importu aktualności instytucji."""

from collections.abc import Callable
from datetime import date

from django.db import models
from django.utils import timezone

from core.models import Institution, InstitutionImportRun
from core.services.institution_innovation_import import InstitutionInnovationImportService
from core.services.news_llm import SelectedNewsArticle

Report = Callable[[str], None]
Schedule = Callable[[int], None]


def advance_import_run(
    run: InstitutionImportRun,
    *,
    report: Report,
    schedule: Schedule,
    service_factory: Callable[[], InstitutionInnovationImportService] = (
        InstitutionInnovationImportService
    ),
) -> None:
    """Przetwarza najwyżej jeden etap i trwałe zapisuje checkpoint następnego kroku."""
    institutions = Institution.objects.filter(
        institution_type__in=run.institution_types
    ).order_by("name", "pk")
    institution = institutions[run.institutions_processed : run.institutions_processed + 1].first()
    if institution is None:
        _complete(run, report)
        return

    service = service_factory()
    service.discovery.reporter = report
    _advance_institution(run, institution, service, report, schedule)


def _complete(run: InstitutionImportRun, report: Report) -> None:
    InstitutionImportRun.objects.filter(pk=run.pk).update(
        status="completed",
        finished_at=timezone.now(),
        current_action="Import zakończony",
        heartbeat_at=timezone.now(),
        retry_after=None,
    )
    report("Import zakończony.")


def _advance_institution(
    run: InstitutionImportRun,
    institution: Institution,
    service: InstitutionInnovationImportService,
    report: Report,
    schedule: Schedule,
) -> None:
    source_urls = service.discovery.source_urls(institution)
    source_index = run.news_source_index
    if source_index >= len(source_urls):
        continue_import_run(
            run,
            schedule=schedule,
            institutions_processed=1,
            source_index=0,
            article_queue=None,
            article_index=0,
        )
        report(f"{institution.name}: zakończono wszystkie źródła aktualności.")
        return

    source_url = source_urls[source_index]
    queue = run.article_queue
    if queue is None:
        report(f"Skanowanie: {institution.name} — źródło {source_index + 1}/{len(source_urls)}")
        queue = [
            serialize_article(link) for link in service.discovery.selected_articles(source_url)
        ]
        continue_import_run(run, schedule=schedule, article_queue=queue, article_index=0)
        return
    if run.article_index >= len(queue):
        continue_import_run(
            run,
            schedule=schedule,
            source_index=source_index + 1,
            article_queue=None,
            article_index=0,
        )
        report(f"{institution.name}: zakończono źródło {source_index + 1}/{len(source_urls)}.")
        return

    link = deserialize_article(queue[run.article_index])
    InstitutionImportRun.objects.filter(pk=run.pk, status="running").update(
        current_institution=institution.name,
        current_action=f"Analiza artykułu {run.article_index + 1}/{len(queue)}",
        heartbeat_at=timezone.now(),
    )
    article = service.discovery.extract_article(institution, link)
    result = service.import_article(institution, article, reporter=report)
    continue_import_run(
        run,
        schedule=schedule,
        article_index=run.article_index + 1,
        ideas_created=result.created,
        ideas_skipped=result.skipped,
    )


def continue_import_run(
    run: InstitutionImportRun,
    *,
    schedule: Schedule,
    institutions_processed: int = 0,
    source_index: int | None = None,
    article_queue: list[dict[str, str | None]] | None | object = models.NOT_PROVIDED,
    article_index: int | None = None,
    ideas_created: int = 0,
    ideas_skipped: int = 0,
) -> None:
    """Zapisuje następną pozycję i planuje ją tylko dla aktywnego importu."""
    changes = {
        "status": "pending",
        "institutions_processed": models.F("institutions_processed") + institutions_processed,
        "ideas_created": models.F("ideas_created") + ideas_created,
        "ideas_skipped": models.F("ideas_skipped") + ideas_skipped,
        "heartbeat_at": timezone.now(),
        "retry_after": None,
    }
    if source_index is not None:
        changes["news_source_index"] = source_index
    if article_queue is not models.NOT_PROVIDED:
        changes["article_queue"] = article_queue
    if article_index is not None:
        changes["article_index"] = article_index
    if InstitutionImportRun.objects.filter(pk=run.pk, status="running").update(**changes):
        schedule(run.pk)


def serialize_article(link: SelectedNewsArticle) -> dict[str, str | None]:
    """Zapisuje wybór LLM, aby timeout nie uruchamiał selekcji drugi raz."""
    return {
        "title": link.title,
        "url": link.url,
        "published_on": link.published_on.isoformat() if link.published_on else None,
    }


def deserialize_article(payload: dict[str, str | None]) -> SelectedNewsArticle:
    """Odtwarza artykuł z kolejki zapisanej na przebiegu importu."""
    published_on = payload["published_on"]
    return SelectedNewsArticle(
        title=payload["title"] or "",
        url=payload["url"] or "",
        published_on=date.fromisoformat(published_on) if published_on else None,
    )

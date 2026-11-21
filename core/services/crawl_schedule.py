"""Planowanie automatycznych, pełnych przebiegów crawlera."""

from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from core.models import CrawlSchedule, Institution, InstitutionImportEvent, InstitutionImportRun


def configured_institution_types(schedule: CrawlSchedule) -> list[str]:
    """Zwraca zapisany zakres, zachowując pełny zakres dla ustawień sprzed migracji."""
    return schedule.institution_types or list(Institution.Type.values)


def configured_institutions(institution_types: list[str], voivodeship_code: str):
    """Buduje stabilny zbiór instytucji objętych konkretnym przebiegiem."""
    institutions = Institution.objects.filter(
        institution_type__in=institution_types, crawl_enabled=True
    )
    if voivodeship_code:
        institutions = institutions.filter(locality__voivodeship_code=voivodeship_code)
    return institutions


def next_crawl_at(schedule: CrawlSchedule, now=None):
    """Zwraca najbliższą przyszłą godzinę uruchomienia w lokalnej strefie czasu."""
    now = now or timezone.now()
    local_now = timezone.localtime(now)
    candidate = timezone.make_aware(
        datetime.combine(local_now.date(), schedule.run_at),
        timezone.get_current_timezone(),
    )
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate


def reschedule_crawl(schedule: CrawlSchedule, now=None) -> CrawlSchedule:
    """Przelicza następny termin po zmianie ustawień w panelu."""
    schedule.next_run_at = next_crawl_at(schedule, now) if schedule.enabled else None
    schedule.save(update_fields=["next_run_at"])
    return schedule


def start_due_crawl(now=None) -> InstitutionImportRun | None:
    """Tworzy jeden pełny przebieg, jeśli termin nadszedł i nic już nie pracuje."""
    now = now or timezone.now()
    with transaction.atomic():
        schedule, _ = CrawlSchedule.objects.select_for_update().get_or_create(
            pk=1,
            defaults={"run_at": time(3)},
        )
        if not schedule.enabled or not schedule.next_run_at or schedule.next_run_at > now:
            return None
        if InstitutionImportRun.objects.filter(status__in=["pending", "running"]).exists():
            return None

        institution_types = configured_institution_types(schedule)
        run = InstitutionImportRun.objects.create(
            status="pending",
            institution_types=institution_types,
            voivodeship_code=schedule.voivodeship_code,
            institutions_total=configured_institutions(
                institution_types, schedule.voivodeship_code
            ).count(),
            current_action="Oczekiwanie na automatyczne uruchomienie zadania",
        )
        InstitutionImportEvent.objects.create(
            run=run,
            message="Automatyczny crawling uruchomiony zgodnie z harmonogramem.",
        )
        schedule.last_started_at = now
        local_now = timezone.localtime(now)
        schedule.next_run_at = timezone.make_aware(
            datetime.combine(
                local_now.date() + timedelta(days=schedule.interval_days), schedule.run_at
            ),
            timezone.get_current_timezone(),
        )
        schedule.save(update_fields=["last_started_at", "next_run_at"])
        return run

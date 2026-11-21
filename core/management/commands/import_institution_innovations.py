"""Importuje i ocenia innowacje znalezione w aktualnościach instytucji."""

from time import monotonic

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from core.models import Institution, InstitutionImportRun
from core.services.institution_innovation_import import InstitutionInnovationImportService


class Command(BaseCommand):
    help = "Pobiera aktualności instytucji wybranego typu i zapisuje ocenione innowacje."

    def add_arguments(self, parser):
        parser.add_argument("--institution-type", default="university")
        parser.add_argument("--start-after-id", type=int)
        parser.add_argument("--all-types", action="store_true")

    def handle(self, *args, **options):
        if options["all_types"] and options["start_after_id"]:
            self.stderr.write("--start-after-id nie można łączyć z --all-types.")
            return
        institution_types = (
            [choice for choice, _label in Institution.Type.choices]
            if options["all_types"]
            else [options["institution_type"]]
        )
        run = InstitutionImportRun.objects.create(institution_types=institution_types)
        started = monotonic()
        created = skipped = 0
        institutions = Institution.objects.filter(institution_type__in=institution_types)
        if options["start_after_id"]:
            previous = Institution.objects.get(
                pk=options["start_after_id"], institution_type=institution_types[0]
            )
            institutions = institutions.filter(
                Q(name__gt=previous.name) | Q(name=previous.name, pk__gt=previous.pk)
            )
        processed = institutions.count()
        try:
            for institution_type in institution_types:
                result = InstitutionInnovationImportService().import_all(
                    institution_type,
                    start_after_id=options["start_after_id"],
                )
                created += result.created
                skipped += result.skipped
        except Exception as error:
            run.status = "failed"
            run.error = str(error)
            raise
        else:
            run.status = "completed"
        finally:
            duration = monotonic() - started
            run.finished_at = timezone.now()
            run.institutions_processed = processed
            run.ideas_created = created
            run.ideas_skipped = skipped
            run.duration_seconds = duration
            run.institutions_per_minute = processed / (duration / 60) if duration else 0
            run.save()
        self.stdout.write(
            self.style.SUCCESS(
                f"Typy: {', '.join(institution_types)}. Dodano {created} innowacji, "
                f"pominięto {skipped}. Czas: {duration:.1f}s; tempo: "
                f"{run.institutions_per_minute:.1f} instytucji/min."
            )
        )

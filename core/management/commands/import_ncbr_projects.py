"""Importuje projekty z całej Polski z publicznej wyszukiwarki NCBR."""

from django.core.management.base import BaseCommand

from core.services.ncbr import NCBRImportService


class Command(BaseCommand):
    help = "Importuje projekty z całej Polski z wyszukiwarki sukcesów beneficjentów NCBR."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Pokaż liczbę projektów bez zapisu i oceny."
        )

    def handle(self, *args, **options):
        result = NCBRImportService().import_projects(dry_run=options["dry_run"])
        action = "Znaleziono" if options["dry_run"] else "Dodano"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {result.created} projektów NCBR; pominięto {result.skipped}."
            )
        )

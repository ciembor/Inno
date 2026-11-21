"""Importuje szkoły z przygotowanego pliku CSV."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.services.school_csv import import_schools_csv


class Command(BaseCommand):
    help = "Importuje szkoły jako instytucje typu school."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)

    def handle(self, *args, **options):
        path = options["file"]
        if not path.is_file():
            raise CommandError(f"Nie znaleziono pliku: {path}")
        try:
            with path.open(encoding="utf-8-sig", newline="") as file:
                count = import_schools_csv(file)
        except UnicodeDecodeError as error:
            raise CommandError("Plik musi mieć kodowanie UTF-8.") from error
        self.stdout.write(self.style.SUCCESS(f"Zapisano {count} szkół."))

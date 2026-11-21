"""Importuje wskazane NGO i ich strony aktualności do crawlera."""

from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from core.management.commands.import_podkarpackie_localities import download_simc
from core.models import Locality
from core.services.ngo_csv import LOCALITY_COORDINATES, import_ngo_sources, read_ngo_sources
from core.services.teryt import parse_localities


class Command(BaseCommand):
    help = "Importuje NGO z CSV oraz brakujące miejscowości z rejestru SIMC GUS."

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path)
        parser.add_argument(
            "--simc-archive",
            type=Path,
            help="Lokalne archiwum SIMC GUS; domyślnie pobierany jest aktualny rejestr.",
        )

    def handle(self, *args, **options):
        path = options["file"]
        if not path.is_file():
            raise CommandError(f"Nie znaleziono pliku: {path}")
        try:
            with path.open(encoding="utf-8-sig", newline="") as file:
                sources = read_ngo_sources(file)
        except (UnicodeDecodeError, ValidationError) as error:
            raise CommandError(str(error)) from error

        archive_path = options["simc_archive"]
        if archive_path is not None and not archive_path.is_file():
            raise CommandError(f"Nie znaleziono archiwum SIMC: {archive_path}")
        archive = archive_path.read_bytes() if archive_path else download_simc()
        expected_codes = {source.locality_simc for source in sources}
        localities = parse_localities(archive, expected_codes)
        found_codes = {locality.simc_code for locality in localities}
        missing = expected_codes - found_codes
        if missing:
            raise CommandError("Brak kodów SIMC w rejestrze: " + ", ".join(sorted(missing)))
        for locality in localities:
            locality.latitude, locality.longitude = LOCALITY_COORDINATES[locality.simc_code]
        Locality.objects.bulk_create(
            localities,
            batch_size=100,
            update_conflicts=True,
            update_fields=[
                "name",
                "county_code",
                "municipality_code",
                "municipality_type_code",
                "locality_type_code",
                "registry_date",
                "latitude",
                "longitude",
            ],
            unique_fields=["simc_code"],
        )
        count = import_ngo_sources(sources)
        self.stdout.write(self.style.SUCCESS(f"Zapisano {count} organizacji i ich źródeł."))

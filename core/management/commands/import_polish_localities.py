"""Importuje wszystkie miejscowości z urzędowego rejestru SIMC GUS."""

from itertools import batched

from django.core.management.base import BaseCommand

from core.management.commands.import_podkarpackie_localities import download_simc
from core.models import Locality
from core.services.teryt import iter_localities


class Command(BaseCommand):
    help = "Importuje wszystkie miejscowości w Polsce z rejestru SIMC GUS."

    def handle(self, *args, **options):
        imported = 0
        for batch in batched(iter_localities(download_simc()), 500, strict=False):
            Locality.objects.bulk_create(
                batch,
                batch_size=500,
                update_conflicts=True,
                update_fields=[
                    "name",
                    "voivodeship_code",
                    "county_code",
                    "municipality_code",
                    "municipality_type_code",
                    "locality_type_code",
                    "registry_date",
                ],
                unique_fields=["simc_code"],
            )
            imported += len(batch)
        self.stdout.write(self.style.SUCCESS(f"Zaimportowano {imported} miejscowości."))

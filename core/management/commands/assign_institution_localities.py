"""Uzupełnia lokalizacje instytucji i ich importowanych inicjatyw."""

import time

from django.core.management.base import BaseCommand, CommandError

from core.management.commands.assign_random_localities import GeocodingError, geocode_locality
from core.models import Idea, Institution, Locality


class Command(BaseCommand):
    help = "Przypisuje instytucjom miejscowości i uzupełnia współrzędne mapy."

    geocoding_attempts = 3

    def _geocode(self, locality):
        for attempt in range(1, self.geocoding_attempts + 1):
            try:
                return geocode_locality(locality)
            except GeocodingError as error:
                if attempt == self.geocoding_attempts:
                    self.stderr.write(
                        self.style.WARNING(
                            f"{locality.name}: pominięto współrzędne po "
                            f"{self.geocoding_attempts} próbach ({error})."
                        )
                    )
                    return None
                time.sleep(attempt)

    def handle(self, *args, **options):
        for institution in Institution.objects.select_related("locality"):
            locality = institution.locality
            if locality is None:
                candidates = Locality.objects.filter(
                    name__iexact=institution.address, locality_type_code="96"
                )
                if candidates.count() != 1:
                    raise CommandError(f"Wybierz miejscowość ręcznie dla: {institution.name}")
                locality = candidates.get()
            if locality.latitude is None or locality.longitude is None:
                coordinates = self._geocode(locality)
                if coordinates is None:
                    continue
                locality.latitude, locality.longitude = coordinates
                locality.save(update_fields=["latitude", "longitude"])
            institution.locality = locality
            institution.save(update_fields=["locality"])
            updated = (
                Idea.objects.filter(institution=institution)
                .exclude(source_url__isnull=True)
                .exclude(source_url="")
                .update(locality=locality)
            )
            self.stdout.write(f"{institution.name}: {locality.name}, inicjatywy: {updated}")

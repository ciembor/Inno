"""Przypisuje istniejącym inicjatywom losowe miejscowości i ich współrzędne."""

import json
import random
import urllib.error
import urllib.parse
import urllib.request

from django.core.management.base import BaseCommand

from core.models import Idea, Locality

COORDINATE_OVERRIDES = {
    # Open-Meteo has no result for this official SIMC name. The centroid comes
    # from the matching municipality boundary in OpenStreetMap.
    "0818692": (50.1164449, 21.5116928),
}


class GeocodingError(RuntimeError):
    """The public geocoder could not resolve a locality."""


def geocode_locality(locality: Locality) -> tuple[float, float]:
    """Pobiera współrzędne wybranej miejscowości z geokodera."""
    if coordinates := COORDINATE_OVERRIDES.get(locality.simc_code):
        return coordinates
    query = urllib.parse.urlencode(
        {
            "name": locality.name,
            "count": 10,
            "language": "pl",
            "format": "json",
        }
    )
    try:
        response = urllib.request.urlopen(
            f"https://geocoding-api.open-meteo.com/v1/search?{query}", timeout=30
        )
        results = json.loads(response.read()).get("results", [])
        result = next(
            item for item in results if item.get("admin1") == "województwo podkarpackie"
        )
    except (
        json.JSONDecodeError,
        KeyError,
        StopIteration,
        TimeoutError,
        urllib.error.HTTPError,
        urllib.error.URLError,
    ) as error:
        raise GeocodingError(f"Nie znaleziono współrzędnych dla: {locality.name}") from error
    return float(result["latitude"]), float(result["longitude"])


class Command(BaseCommand):
    help = "Przypisuje inicjatywom losowe miejscowości z Podkarpacia."

    def handle(self, *args, **options):
        ideas = list(Idea.objects.order_by("pk"))
        assignments = []
        for locality in random.sample(list(Locality.objects.all()), Locality.objects.count()):
            try:
                latitude, longitude = geocode_locality(locality)
            except (KeyError, StopIteration):
                continue
            assignments.append((locality, latitude, longitude))
            if len(assignments) == len(ideas):
                break
        for idea, (locality, latitude, longitude) in zip(ideas, assignments, strict=True):
            locality.latitude = latitude
            locality.longitude = longitude
            locality.save(update_fields=["latitude", "longitude"])
            idea.locality = locality
        Idea.objects.bulk_update(ideas, ["locality"])
        message = f"Przypisano miejscowości do {len(assignments)} inicjatyw."
        self.stdout.write(self.style.SUCCESS(message))

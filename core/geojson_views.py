"""Lokalne źródła urzędowych danych GeoJSON dla mapy."""

import json
from functools import lru_cache
from pathlib import Path

from django.http import JsonResponse

DATA_DIR = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=1)
def load_podkarpackie_boundary():
    """Wczytuje pobraną urzędową granicę bez zewnętrznego API."""
    with (DATA_DIR / "podkarpackie-boundary.geojson").open(encoding="utf-8") as source:
        return json.load(source)


@lru_cache(maxsize=1)
def load_poland_boundary():
    """Wczytuje lokalną migawkę granicy lądowej Polski wraz z linią brzegową."""
    with (DATA_DIR / "poland-boundary.geojson").open(encoding="utf-8") as source:
        return json.load(source)


@lru_cache(maxsize=1)
def load_podkarpackie_counties():
    """Wczytuje uproszczone granice powiatów województwa podkarpackiego."""
    with (DATA_DIR / "podkarpackie-counties.geojson").open(encoding="utf-8") as source:
        return json.load(source)


@lru_cache(maxsize=1)
def podkarpackie_county_names():
    """Mapuje dwucyfrowy kod powiatu SIMC na jego urzędową nazwę."""
    return {
        feature["properties"]["kod"][-2:]: feature["properties"]["nazwaJednostki"]
        for feature in load_podkarpackie_counties()["features"]
    }


def podkarpackie_boundary(request):
    return JsonResponse(load_podkarpackie_boundary())


def poland_boundary(request):
    return JsonResponse(load_poland_boundary())


def podkarpackie_counties(request):
    return JsonResponse(load_podkarpackie_counties())

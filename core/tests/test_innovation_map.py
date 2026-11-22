# Mechanical split of the former test_core.py by responsibility.


import pytest
from django.urls import reverse

from core.models import Idea, Locality


@pytest.mark.django_db
def test_innovation_map_page_and_data_display_geolocated_ideas(client):
    locality = Locality.objects.create(
        simc_code="0654321",
        name="Rzeszów",
        county_code="63",
        municipality_code="01",
        municipality_type_code="1",
        locality_type_code="96",
        registry_date="2026-01-01",
        latitude=50.0133,
        longitude=22.0162,
    )
    map_idea = Idea.objects.create(
        name="Mapa pomysłu",
        submitter_name="Anna Kowalska",
        email="anna@example.org",
        locality=locality,
        content="Treść",
        innovation_score=71,
    )
    Idea.objects.create(
        name="Nieoceniony pomysł",
        submitter_name="Jan Kowalski",
        email="jan@example.org",
        locality=locality,
        content="Treść",
    )

    page = client.get(reverse("innovation_map"))
    data = client.get(reverse("innovation_map_data"))
    boundary = client.get(reverse("poland_boundary"))
    regional_boundary = client.get(reverse("podkarpackie_boundary"))
    counties = client.get(reverse("podkarpackie_counties"))

    assert page.status_code == 200
    assert "core/js/innovation_map.js" in page.content.decode()
    assert 'aria-current="page">Mapa' in page.content.decode()
    assert boundary.json()["features"][0]["id"] == "POL"
    assert boundary.json()["features"][0]["geometry"]["type"] == "MultiPolygon"
    assert boundary.json()["features"][0]["properties"]["source"] == (
        "GADM 4.1 — granica lądowa Polski"
    )
    assert regional_boundary.json()["properties"]["kod"] == "18"
    assert len(counties.json()["features"]) == 25
    assert data.json()["innovations"] == [
        {
                "id": map_idea.pk,
                "name": "Mapa pomysłu",
                "url": reverse("innovation_detail", args=[map_idea.pk]),
            "score": 71,
            "locality": "Rzeszów",
            "latitude": 50.0133,
            "longitude": 22.0162,
        }
    ]
    assert "Nieoceniony pomysł" not in page.content.decode()
    assert data.headers["Cache-Control"] == (
        "max-age=0, no-cache, no-store, must-revalidate, private"
    )

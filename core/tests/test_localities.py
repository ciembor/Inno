# Mechanical split of the former test_core.py by responsibility.

from unittest.mock import MagicMock
from urllib.error import URLError

import pytest
from django.core.management import call_command

from core.management.commands import (
    assign_random_localities,
    import_podkarpackie_localities,
    import_polish_localities,
)
from core.management.commands.assign_random_localities import GeocodingError
from core.models import Idea, Locality
from core.tests.support import simc_archive


@pytest.mark.django_db
def test_simc_import_downloads_and_saves_only_podkarpackie_localities(monkeypatch):
    archive = simc_archive()
    opener = MagicMock()
    opener.open.side_effect = [
        type("Response", (), {"read": lambda self: b'<input name="__VIEWSTATE" value="state">'})(),
        type("Response", (), {"read": lambda self: archive})(),
    ]
    monkeypatch.setattr(
        import_podkarpackie_localities.urllib.request,
        "build_opener",
        lambda *args: opener,
    )
    Locality.objects.create(
        simc_code="0654321",
        name="Stara nazwa",
        county_code="00",
        municipality_code="00",
        municipality_type_code="0",
        locality_type_code="00",
        registry_date="2025-01-01",
    )

    call_command("import_podkarpackie_localities")

    locality = Locality.objects.get()
    assert str(locality) == "Rzeszów"
    assert locality.registry_date.isoformat() == "2026-01-01"
    assert opener.open.call_count == 2


@pytest.mark.django_db
def test_polish_simc_import_saves_localities_from_every_voivodeship(monkeypatch):
    monkeypatch.setattr(import_polish_localities, "download_simc", simc_archive)

    call_command("import_polish_localities")

    assert list(
        Locality.objects.order_by("simc_code").values_list("name", "voivodeship_code")
    ) == [("Rzeszów", "18"), ("Warszawa", "14")]


def test_geocode_locality_uses_geocoder_response(monkeypatch):
    locality = Locality(simc_code="0654321", name="Rzeszów")
    response = type(
        "Response",
        (),
        {
            "read": lambda self: (
                b'{"results": [{"admin1": "wojew\\u00f3dztwo podkarpackie", '
                b'"latitude": 50.0, "longitude": 22.0}]}'
            ),
        },
    )()
    monkeypatch.setattr(
        assign_random_localities.urllib.request,
        "urlopen",
        lambda *args, **kwargs: response,
    )

    assert assign_random_localities.geocode_locality(locality) == (50.0, 22.0)


def test_geocode_locality_wraps_unavailable_geocoder(monkeypatch):
    locality = Locality(simc_code="0654321", name="Rzeszów")
    monkeypatch.setattr(
        assign_random_localities.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")),
    )

    with pytest.raises(GeocodingError, match="Rzeszów"):
        assign_random_localities.geocode_locality(locality)


def test_geocode_locality_uses_verified_override_without_a_network_request(monkeypatch):
    locality = Locality(simc_code="0818692", name="Pustków-Osiedle")
    geocoder = MagicMock()
    monkeypatch.setattr(assign_random_localities.urllib.request, "urlopen", geocoder)

    assert assign_random_localities.geocode_locality(locality) == (50.1164449, 21.5116928)
    geocoder.assert_not_called()


@pytest.mark.django_db
def test_assign_random_localities_saves_locations_and_coordinates(monkeypatch):
    localities = [
        Locality.objects.create(
            simc_code=f"065432{number}",
            name=f"Miejscowość {number}",
            county_code="63",
            municipality_code="01",
            municipality_type_code="1",
            locality_type_code="96",
            registry_date="2026-01-01",
        )
        for number in range(3)
    ]
    ideas = [
        Idea.objects.create(
            name=f"Pomysł {number}",
            submitter_name="Anna Kowalska",
            email=f"anna{number}@example.org",
            content="Treść",
        )
        for number in range(2)
    ]
    monkeypatch.setattr(assign_random_localities.random, "sample", lambda values, count: localities)
    monkeypatch.setattr(
        assign_random_localities,
        "geocode_locality",
        lambda locality: (
            (50.0, 22.0) if locality != localities[0] else (_ for _ in ()).throw(KeyError)
        ),
    )

    call_command("assign_random_localities")

    assert list(Idea.objects.order_by("pk").values_list("locality_id", flat=True)) == [
        locality.pk for locality in localities[1:]
    ]
    assert list(Locality.objects.order_by("simc_code").values_list("latitude", "longitude")) == [
        (None, None),
        (50.0, 22.0),
        (50.0, 22.0),
    ]
    assert len(ideas) == 2


@pytest.mark.django_db
def test_assign_random_localities_rejects_ungeocodable_sample(monkeypatch):
    locality = Locality.objects.create(
        simc_code="0654321",
        name="Nieznana miejscowość",
        county_code="63",
        municipality_code="01",
        municipality_type_code="1",
        locality_type_code="96",
        registry_date="2026-01-01",
    )
    Idea.objects.create(
        name="Pomysł bez współrzędnych",
        submitter_name="Anna Kowalska",
        email="anna@example.org",
        content="Treść",
    )
    monkeypatch.setattr(assign_random_localities.random, "sample", lambda values, count: [locality])
    monkeypatch.setattr(
        assign_random_localities,
        "geocode_locality",
        lambda selected: (_ for _ in ()).throw(KeyError),
    )

    with pytest.raises(ValueError, match="zip"):
        call_command("assign_random_localities")

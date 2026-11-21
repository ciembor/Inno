from unittest.mock import MagicMock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from core.management.commands.assign_institution_localities import Command
from core.management.commands.assign_random_localities import GeocodingError
from core.models import Idea, Institution, Locality
from core.services.institution_innovation_import import InstitutionInnovationImportService
from core.services.institution_news import NewsArticle
from core.tests.test_integration import create_locality


@pytest.mark.django_db
def test_assign_locations_and_inherit_for_new_imports(monkeypatch, client):
    locality = create_locality()
    locality.latitude = None
    locality.save()
    institution = Institution.objects.create(name="Uczelnia", address="Rzeszów")
    imported = Idea.objects.create(
        name="Projekt", institution=institution, source_url="https://example.org/project"
    )
    manual = Idea.objects.create(name="Zgłoszenie", institution=institution)
    geocode = MagicMock(return_value=(50.0133, 22.0162))
    monkeypatch.setattr(
        "core.management.commands.assign_institution_localities.geocode_locality", geocode
    )
    call_command("assign_institution_localities")
    call_command("assign_institution_localities")
    geocode.assert_called_once()
    institution.refresh_from_db()
    imported.refresh_from_db()
    manual.refresh_from_db()
    assert institution.locality == locality
    assert imported.locality == locality
    assert manual.locality is None
    score = MagicMock(total=30, criteria=())
    new = InstitutionInnovationImportService(
        discovery=MagicMock(), scorer=lambda *_: score
    )._create_idea(institution, NewsArticle("Nowy", "https://example.org/new", "Opis"))
    assert new.locality == locality
    response = client.get(reverse("innovation_map_data")).json()
    assert {row["id"] for row in response["innovations"]} == {new.pk}


@pytest.mark.django_db
def test_unknown_institution_city_requires_explicit_assignment():
    Institution.objects.create(name="Nieznana", address="Nieznane miasto")
    with pytest.raises(CommandError, match="ręcznie"):
        call_command("assign_institution_localities")


@pytest.mark.django_db
def test_assign_locations_continues_after_ungeocodable_locality(monkeypatch):
    first = Institution.objects.create(name="A", address="A")
    second = Institution.objects.create(name="B", address="B")
    first.locality = Locality.objects.create(
        simc_code="0654001",
        name="A",
        county_code="63",
        municipality_code="01",
        municipality_type_code="1",
        locality_type_code="96",
        registry_date="2026-01-01",
    )
    second.locality = Locality.objects.create(
        simc_code="0654002",
        name="B",
        county_code="63",
        municipality_code="01",
        municipality_type_code="1",
        locality_type_code="96",
        registry_date="2026-01-01",
    )
    first.save(update_fields=["locality"])
    second.save(update_fields=["locality"])
    monkeypatch.setattr(
        "core.management.commands.assign_institution_localities.geocode_locality",
        lambda locality: (
            (_ for _ in ()).throw(GeocodingError("brak"))
            if locality == first.locality
            else (50.0, 22.0)
        ),
    )
    monkeypatch.setattr(
        "core.management.commands.assign_institution_localities.time.sleep", lambda _: None
    )

    call_command("assign_institution_localities")

    first.locality.refresh_from_db()
    second.locality.refresh_from_db()
    assert first.locality.latitude is None
    assert second.locality.latitude == 50.0


def test_assign_locations_skips_geocoding_when_attempts_are_disabled():
    command = Command()
    command.geocoding_attempts = 0

    assert command._geocode(Locality(name="Rzeszów")) is None

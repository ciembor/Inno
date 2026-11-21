# Mechanical split of the former test_core.py by responsibility.


import pytest
from django.core.management import call_command

from core.management.commands import (
    seed_institutions,
)
from core.models import Idea, Institution, InstitutionNewsSource
from core.services.institution_news import (
    InstitutionNewsDiscoveryService,
)
from core.tests.support import FakeClient


@pytest.mark.django_db
def test_idea_string_representation():
    idea = Idea.objects.create(
        name="Miejska czytelnia",
        submitter_name="Jan Nowak",
        email="jan@example.org",
        content="<p>Opis</p>",
    )

    assert str(idea) == "Miejska czytelnia"


@pytest.mark.django_db
def test_institution_persists_contact_and_type_data():
    institution = Institution.objects.create(
        name="Biblioteka Publiczna",
        address="ul. Czytelnicza 1, 35-001 Rzeszów",
        news_url="https://biblioteka.example.org/aktualnosci/",
        institution_type="biblioteka",
    )

    assert Institution.objects.get(pk=institution.pk).news_url.endswith("/aktualnosci/")


@pytest.mark.django_db
def test_seed_institutions_adds_the_podkarpackie_universities():
    call_command("seed_institutions")

    assert Institution.objects.count() == len(seed_institutions.INSTITUTIONS)
    assert set(Institution.objects.values_list("institution_type", flat=True)) == {"university"}
    assert Institution.objects.get(name="Uniwersytet Rzeszowski").address == "Rzeszów"
    assert (
        Institution.objects.get(
            name="Wyższa Szkoła Gospodarki i Zarządzania", address="Mielec"
        ).news_url
        == "https://wsgiz.mielec.pl/aktualnosci-lista.html"
    )
    assert InstitutionNewsSource.objects.count() == (
        len(seed_institutions.INSTITUTIONS) + len(seed_institutions.ADDITIONAL_NEWS_SOURCES)
    )


@pytest.mark.django_db
def test_institution_news_sources_override_the_legacy_primary_url():
    institution = Institution.objects.create(
        name="Uczelnia",
        address="Rzeszów",
        news_url="https://uczelnia.example/aktualnosci",
        institution_type="university",
    )
    InstitutionNewsSource.objects.create(
        institution=institution, url="https://badania.uczelnia.example/aktualnosci"
    )

    assert InstitutionNewsDiscoveryService._source_urls(institution) == (
        institution.news_url,
        "https://badania.uczelnia.example/aktualnosci",
    )
    assert InstitutionNewsDiscoveryService(client=FakeClient([])).source_urls(institution) == (
        institution.news_url,
        "https://badania.uczelnia.example/aktualnosci",
    )
    institution.news_url = ""
    assert InstitutionNewsDiscoveryService._source_urls(institution) == (
        "https://badania.uczelnia.example/aktualnosci",
    )

"""Import NGO, oficjalnych lokalizacji SIMC i stron aktualności."""

from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError

from core.management.commands import import_ngo_sources as ngo_command
from core.models import Institution, Locality
from core.services.ngo_csv import NGOArticleSource, import_ngo_sources, read_ngo_sources
from core.services.teryt import parse_localities
from core.tests.support import simc_archive


def locality(code="0918123", name="Warszawa"):
    return Locality(
        simc_code=code,
        name=name,
        county_code="65",
        municipality_code="01",
        municipality_type_code="1",
        locality_type_code="96",
        registry_date=date(2026, 1, 1),
    )


def test_read_ngo_sources_validates_columns_and_known_localities():
    with pytest.raises(ValidationError, match="Aktualności URL"):
        read_ngo_sources(StringIO("Nazwa,Lokalizacja,URL\nFundacja,Warszawa,https://example.org\n"))
    with pytest.raises(ValidationError, match="zweryfikowanego kodu SIMC"):
        read_ngo_sources(
            StringIO(
                "Nazwa,Lokalizacja,URL,Aktualności URL\n"
                "Fundacja,Nieznana,https://example.org/a,https://example.org/news\n"
            )
        )
    with pytest.raises(ValidationError, match="uzupełnij"):
        read_ngo_sources(
            StringIO(
                "Nazwa,Lokalizacja,URL,Aktualności URL\n"
                "Fundacja,Warszawa,https://example.org/a,\n"
            )
        )

    sources = read_ngo_sources(
        StringIO(
            "Nazwa,Lokalizacja,URL,Aktualności URL\n"
            "Fundacja,Warszawa,https://example.org/a,https://example.org/news\n"
        )
    )

    assert sources == (
        NGOArticleSource("Fundacja", "Warszawa", "0918123", "https://example.org/news"),
    )


@pytest.mark.django_db
def test_import_ngo_sources_saves_other_institution_with_its_news_listing():
    Locality.objects.bulk_create([locality()])
    source = NGOArticleSource("Fundacja", "Warszawa", "0918123", "https://example.org/news")

    assert import_ngo_sources((source,)) == 1
    institution = Institution.objects.get(name="Fundacja")
    assert institution.institution_type == Institution.Type.OTHER
    assert institution.locality_id == "0918123"
    assert institution.news_url == source.news_url
    assert list(institution.news_sources.values_list("url", flat=True)) == [source.news_url]

    with pytest.raises(ValidationError, match="Brak miejscowości SIMC"):
        import_ngo_sources((NGOArticleSource("Brak", "X", "0000000", "https://x.example"),))


def test_parse_localities_returns_only_requested_simc_records():
    records = parse_localities(simc_archive(), {"0654321", "missing"})

    assert [(item.simc_code, item.name) for item in records] == [("0654321", "Rzeszów")]


@pytest.mark.django_db
def test_ngo_command_imports_teryt_locality_coordinates_and_listing(tmp_path):
    path = Path(tmp_path) / "ngo.csv"
    path.write_text(
        "Nazwa,Lokalizacja,URL,Aktualności URL\n"
        "Fundacja,Warszawa,https://example.org/a,https://example.org/news\n",
        encoding="utf-8",
    )
    source = NGOArticleSource("Fundacja", "Warszawa", "0918123", "https://example.org/news")
    saved_locality = locality()
    with (
        patch.object(ngo_command, "download_simc", return_value=b"archive"),
        patch.object(ngo_command, "parse_localities", return_value=(saved_locality,)),
        patch.object(ngo_command, "read_ngo_sources", return_value=(source,)),
    ):
        call_command("import_ngo_sources", path)

    saved_locality = Locality.objects.get(pk="0918123")
    assert (saved_locality.latitude, saved_locality.longitude) == (52.22977, 21.01178)
    assert Institution.objects.get(name="Fundacja").news_url == "https://example.org/news"


@pytest.mark.django_db
def test_ngo_command_rejects_missing_file_and_incomplete_teryt_data(tmp_path):
    with pytest.raises(CommandError, match="Nie znaleziono"):
        call_command("import_ngo_sources", Path(tmp_path) / "missing.csv")

    path = Path(tmp_path) / "ngo.csv"
    path.write_text(
        "Nazwa,Lokalizacja,URL,Aktualności URL\n"
        "Fundacja,Warszawa,https://example.org/a,https://example.org/news\n",
        encoding="utf-8",
    )
    invalid_path = Path(tmp_path) / "invalid.csv"
    invalid_path.write_text("Nazwa\nFundacja\n", encoding="utf-8")
    with pytest.raises(CommandError, match="Wymagane kolumny"):
        call_command("import_ngo_sources", invalid_path)
    with pytest.raises(CommandError, match="Nie znaleziono archiwum SIMC"):
        call_command("import_ngo_sources", path, simc_archive=Path(tmp_path) / "missing.zip")
    with (
        pytest.raises(CommandError, match="Brak kodów SIMC"),
        patch.object(ngo_command, "download_simc", return_value=b"archive"),
        patch.object(ngo_command, "parse_localities", return_value=()),
    ):
        call_command("import_ngo_sources", path)

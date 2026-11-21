"""Import wskazanych organizacji pozarządowych i ich stron aktualności."""

import csv
from dataclasses import dataclass
from io import TextIOBase, TextIOWrapper

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import Institution, InstitutionNewsSource, Locality

# Zweryfikowane identyfikatory miejscowości w państwowym rejestrze SIMC.
LOCALITY_SIMC_CODES = {
    "Białystok": "0922410",
    "Bogumiłów": "0550829",
    "Bolszewo": "0176437",
    "Buda Ruska": "0760679",
    "Chorzów": "0938887",
    "Ełk": "0977670",
    "Gdańsk": "0933016",
    "Giżycko": "0977692",
    "Gliwice": "0940000",
    "Golub-Dobrzyń": "0983155",
    "Kajetany": "0005339",
    "Katowice": "0937474",
    "Kraków": "0950463",
    "Leszno": "0954225",
    "Lesznowola": "0004802",
    "Miłków": "0192086",
    "Opole": "0965016",
    "Poznań": "0969400",
    "Szczecin": "0977976",
    "Toruń": "0982724",
    "Warszawa": "0918123",
    "Wrocław": "0986283",
    "Zabrze": "0945380",
}
REQUIRED_COLUMNS = frozenset({"Nazwa", "Lokalizacja", "URL", "Aktualności URL"})

# Współrzędne centralne zweryfikowanych miejscowości; identyfikator SIMC pozostaje
# źródłem prawdy dla przypisania administracyjnego.
LOCALITY_COORDINATES = {
    "0922410": (53.13333, 23.16433),
    "0550829": (51.26416, 19.22121),
    "0176437": (54.61801, 18.17585),
    "0760679": (54.06037, 23.19542),
    "0938887": (50.30582, 18.97420),
    "0977670": (53.82824, 22.36469),
    "0933016": (54.35227, 18.64912),
    "0977692": (54.03811, 21.76441),
    "0940000": (50.29761, 18.67658),
    "0983155": (53.11087, 19.05381),
    "0005339": (52.09270, 20.81410),
    "0937474": (50.25970, 19.02173),
    "0950463": (50.06143, 19.93658),
    "0954225": (51.84034, 16.57494),
    "0004802": (52.09095, 20.93479),
    "0192086": (50.80479, 15.75850),
    "0965016": (50.67119, 17.92604),
    "0969400": (52.40692, 16.92993),
    "0977976": (53.42894, 14.55302),
    "0982724": (53.01375, 18.59814),
    "0918123": (52.22977, 21.01178),
    "0986283": (51.10286, 17.03006),
    "0945380": (50.32492, 18.78576),
}


@dataclass(frozen=True)
class NGOArticleSource:
    name: str
    locality_name: str
    locality_simc: str
    news_url: str


def read_ngo_sources(file: TextIOBase | TextIOWrapper) -> tuple[NGOArticleSource, ...]:
    """Waliduje referencyjny CSV i wiąże jego miejscowości z identyfikatorami SIMC."""
    reader = csv.DictReader(file)
    if not REQUIRED_COLUMNS.issubset(reader.fieldnames or []):
        raise ValidationError("Wymagane kolumny: Nazwa, Lokalizacja, URL, Aktualności URL.")
    sources = []
    for number, row in enumerate(reader, 2):
        name = (row.get("Nazwa") or "").strip()
        locality_name = (row.get("Lokalizacja") or "").strip()
        news_url = (row.get("Aktualności URL") or "").strip()
        if not name or not locality_name or not news_url:
            raise ValidationError(
                f"Wiersz {number}: uzupełnij Nazwa, Lokalizacja i Aktualności URL."
            )
        try:
            locality_simc = LOCALITY_SIMC_CODES[locality_name]
        except KeyError as error:
            raise ValidationError(
                f"Wiersz {number}: brak zweryfikowanego kodu SIMC dla {locality_name}."
            ) from error
        sources.append(NGOArticleSource(name, locality_name, locality_simc, news_url))
    return tuple(sources)


@transaction.atomic
def import_ngo_sources(sources: tuple[NGOArticleSource, ...]) -> int:
    """Dodaje organizacje jako inne instytucje i ich strony aktualności."""
    localities = Locality.objects.in_bulk({source.locality_simc for source in sources})
    missing = sorted({source.locality_simc for source in sources} - set(localities))
    if missing:
        raise ValidationError("Brak miejscowości SIMC: " + ", ".join(missing))

    for source in sources:
        locality = localities[source.locality_simc]
        institution, _ = Institution.objects.update_or_create(
            name=source.name,
            address=source.locality_name,
            defaults={
                "institution_type": Institution.Type.OTHER,
                "locality": locality,
                "news_url": source.news_url,
            },
        )
        InstitutionNewsSource.objects.update_or_create(
            institution=institution,
            url=source.news_url,
        )
    return len(sources)

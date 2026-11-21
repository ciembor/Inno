"""Narzędzia do odczytu urzędowego rejestru miejscowości SIMC GUS."""

import xml.etree.ElementTree as element_tree
from datetime import date
from io import BytesIO
from zipfile import ZipFile

from core.models import Locality

VOIVODESHIP_NAMES = {
    "02": "dolnośląskie",
    "04": "kujawsko-pomorskie",
    "06": "lubelskie",
    "08": "lubuskie",
    "10": "łódzkie",
    "12": "małopolskie",
    "14": "mazowieckie",
    "16": "opolskie",
    "18": "podkarpackie",
    "20": "podlaskie",
    "22": "pomorskie",
    "24": "śląskie",
    "26": "świętokrzyskie",
    "28": "warmińsko-mazurskie",
    "30": "wielkopolskie",
    "32": "zachodniopomorskie",
}


def iter_localities(archive: bytes):
    """Iteruje po wszystkich miejscowościach z archiwum SIMC."""
    with ZipFile(BytesIO(archive)) as zip_file:
        xml_name = next(name for name in zip_file.namelist() if name.startswith("SIMC_Urzedowy"))
        with zip_file.open(xml_name) as xml_file:
            for _, element in element_tree.iterparse(xml_file, events=("end",)):
                if element.tag == "row":
                    fields = {child.tag: child.text or "" for child in element}
                    yield Locality(
                        simc_code=fields["SYM"],
                        name=fields["NAZWA"],
                        voivodeship_code=fields["WOJ"],
                        county_code=fields["POW"],
                        municipality_code=fields["GMI"],
                        municipality_type_code=fields["RODZ_GMI"],
                        locality_type_code=fields["RM"],
                        registry_date=date.fromisoformat(fields["STAN_NA"]),
                    )
                    element.clear()


def parse_localities(archive: bytes, simc_codes: set[str]) -> tuple[Locality, ...]:
    """Zwraca tylko wskazane oficjalne rekordy SIMC, bez importu całej Polski."""
    return tuple(
        locality for locality in iter_localities(archive) if locality.simc_code in simc_codes
    )

"""Importuje podkarpackie miejscowości z pełnego pliku SIMC GUS."""

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as element_tree
from datetime import date
from http.cookiejar import CookieJar
from io import BytesIO
from zipfile import ZipFile

from django.core.management.base import BaseCommand

from core.models import Locality

SIMC_DOWNLOAD_URL = (
    "https://eteryt.stat.gov.pl/eTeryt/rejestr_teryt/udostepnianie_danych/baza_teryt/"
    "uzytkownicy_indywidualni/pobieranie/pliki_pelne.aspx?contrast=default"
)
PODKARPACKIE_CODE = "18"


def download_simc() -> bytes:
    """Pobiera aktualny, urzędowy plik SIMC bez potrzeby logowania."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    page = opener.open(SIMC_DOWNLOAD_URL, timeout=60).read().decode("utf-8")
    viewstate = re.search(r'name="__VIEWSTATE"[^>]*value="([^"]+)', page).group(1)
    payload = urllib.parse.urlencode(
        {
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": "8C427999",
            "__EVENTTARGET": "ctl00$body$BSIMCUrzedowyPobierz",
        }
    ).encode()
    return opener.open(SIMC_DOWNLOAD_URL, data=payload, timeout=60).read()


def parse_podkarpackie_localities(archive: bytes):
    """Wydobywa wiersze województwa podkarpackiego z archiwum SIMC."""
    with ZipFile(BytesIO(archive)) as zip_file:
        xml_name = next(name for name in zip_file.namelist() if name.startswith("SIMC_Urzedowy"))
        with zip_file.open(xml_name) as xml_file:
            for _, element in element_tree.iterparse(xml_file, events=("end",)):
                if element.tag == "row":
                    fields = {child.tag: child.text or "" for child in element}
                    if fields["WOJ"] == PODKARPACKIE_CODE:
                        yield Locality(
                            simc_code=fields["SYM"],
                            name=fields["NAZWA"],
                            county_code=fields["POW"],
                            municipality_code=fields["GMI"],
                            municipality_type_code=fields["RODZ_GMI"],
                            locality_type_code=fields["RM"],
                            registry_date=date.fromisoformat(fields["STAN_NA"]),
                        )
                    element.clear()


class Command(BaseCommand):
    help = "Importuje wszystkie miejscowości województwa podkarpackiego z rejestru SIMC GUS."

    def handle(self, *args, **options):
        localities = list(parse_podkarpackie_localities(download_simc()))
        Locality.objects.bulk_create(
            localities,
            batch_size=500,
            update_conflicts=True,
            update_fields=[
                "name",
                "county_code",
                "municipality_code",
                "municipality_type_code",
                "locality_type_code",
                "registry_date",
            ],
            unique_fields=["simc_code"],
        )
        self.stdout.write(self.style.SUCCESS(f"Zaimportowano {len(localities)} miejscowości."))

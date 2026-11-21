"""Minimalne narzędzia do odczytu wskazanych miejscowości z archiwum SIMC GUS."""

import xml.etree.ElementTree as element_tree
from datetime import date
from io import BytesIO
from zipfile import ZipFile

from core.models import Locality


def parse_localities(archive: bytes, simc_codes: set[str]) -> tuple[Locality, ...]:
    """Zwraca tylko wskazane oficjalne rekordy SIMC, bez importu całej Polski."""
    found = []
    with ZipFile(BytesIO(archive)) as zip_file:
        xml_name = next(name for name in zip_file.namelist() if name.startswith("SIMC_Urzedowy"))
        with zip_file.open(xml_name) as xml_file:
            for _, element in element_tree.iterparse(xml_file, events=("end",)):
                if element.tag == "row":
                    fields = {child.tag: child.text or "" for child in element}
                    if fields["SYM"] in simc_codes:
                        found.append(
                            Locality(
                                simc_code=fields["SYM"],
                                name=fields["NAZWA"],
                                county_code=fields["POW"],
                                municipality_code=fields["GMI"],
                                municipality_type_code=fields["RODZ_GMI"],
                                locality_type_code=fields["RM"],
                                registry_date=date.fromisoformat(fields["STAN_NA"]),
                            )
                        )
                    element.clear()
    return tuple(found)

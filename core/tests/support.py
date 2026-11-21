"""Wspólne duble testowe i dane wejściowe dla testów aplikacji."""

import json
from io import BytesIO
from zipfile import ZipFile

from core.innovation_catalog import CRITERIA


class FakeResponses:
    """Minimalny odpowiednik Responses API zwracający kolejne odpowiedzi."""

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return type("Response", (), {"output_text": output})()


class FakeClient:
    """Klient OpenAI z kontrolowaną kolejką odpowiedzi."""

    def __init__(self, outputs):
        self.responses = FakeResponses(outputs)


def simc_archive():
    """Tworzy minimalne archiwum SIMC z Podkarpaciem i rekordem spoza regionu."""
    xml = """<?xml version="1.0" encoding="utf-8"?>
<SIMC><catalog>
<row><WOJ>18</WOJ><POW>63</POW><GMI>01</GMI><RODZ_GMI>1</RODZ_GMI><RM>96</RM><NAZWA>Rzeszów</NAZWA><SYM>0654321</SYM><STAN_NA>2026-01-01</STAN_NA></row>
<row><WOJ>14</WOJ><POW>01</POW><GMI>01</GMI><RODZ_GMI>1</RODZ_GMI><RM>96</RM><NAZWA>Warszawa</NAZWA><SYM>0918123</SYM><STAN_NA>2026-01-01</STAN_NA></row>
</catalog></SIMC>"""
    archive = BytesIO()
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr("SIMC_Urzedowy_2026-11-15.xml", xml)
    return archive.getvalue()


def scoring_response(values=(80, 70, 60, 50), rationales=None):
    """Tworzy prawidłową odpowiedź JSON oceniacza dla czterech kryteriów."""
    rationales = rationales or [f"Uzasadnienie {number}" for number in range(len(CRITERIA))]
    return json.dumps(
        {
            criterion.key: {"score": value, "confidence": "low", "rationale": rationale}
            for criterion, value, rationale in zip(CRITERIA, values, rationales, strict=True)
        }
    )

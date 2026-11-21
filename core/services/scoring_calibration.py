"""Opcjonalne przykłady kalibracyjne przechowywane w bazie danych."""

import json

from django.core.exceptions import ImproperlyConfigured

from core.innovation_catalog import active_criteria
from core.models import ScoringCalibration

EXAMPLE_FIELDS = {"title", "description", "score", "rationale"}
CALIBRATION_INSTRUCTIONS = """
Przykłady poniżej kalibrują wyłącznie wskazane kryterium, nie wynik łączny.
Są punktami odniesienia, nie sztywnymi kategoriami ani granicami skali.
Oceniaj mechanizm, korzyści i wymagania, nie podobieństwo tematyczne lub nazwę.
Możesz ocenić projekt wyżej lub niżej niż przykłady, jeśli uzasadnia to opis.
Nie wymuszaj rozkładu ocen. Brak przykładu z danego przedziału nie wyklucza jego użycia.
Bazuj na dostarczonym opisie, bez wymagania weryfikacji online. Konkretne wyniki
traktuj jako informacje ze źródła (według opisu), nie jako niezależnie zweryfikowane
fakty. Nie dopowiadaj efektów. Brak niezależnej weryfikacji sam nie obniża punktacji.
Przykłady nie zastępują reguł confidence i score=null ani formatu odpowiedzi.
"""


def _validate_example(example: object) -> None:
    if not isinstance(example, dict) or set(example) != EXAMPLE_FIELDS:
        raise ValueError("Przykład wymaga pól title, description, score, rationale.")
    if type(example["score"]) is not int or not 0 <= example["score"] <= 100:
        raise ValueError("score musi być liczbą całkowitą od 0 do 100.")
    for field in ("title", "description", "rationale"):
        if not isinstance(example[field], str) or not example[field].strip():
            raise ValueError(f"{field} musi być niepustym tekstem.")


def calibration_prompt() -> str:
    """Zwraca aktywną kalibrację; wyłączona nie zmienia promptu oceny."""
    calibration = ScoringCalibration.objects.prefetch_related("examples").first()
    if calibration is None or not calibration.enabled:
        return ""

    criteria = active_criteria()
    payload = {
        criterion.key: [
            {
                "title": example.title,
                "description": example.description,
                "score": example.score,
                "rationale": example.rationale,
            }
            for example in calibration.examples.filter(criterion=criterion.key)
        ]
        for criterion in criteria
    }
    try:
        if any(not examples for examples in payload.values()):
            raise ValueError("Każde kryterium wymaga co najmniej jednego przykładu.")
        for examples in payload.values():
            for example in examples:
                _validate_example(example)
    except ValueError as error:
        raise ImproperlyConfigured(f"Błędna kalibracja w bazie: {error}") from error
    return CALIBRATION_INSTRUCTIONS + "\nPrzykłady kalibracyjne (JSON):\n" + json.dumps(
        payload, ensure_ascii=False, indent=2
    )

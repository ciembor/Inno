"""Ujednolicona ocena potencjału innowacyjnego zgłoszonych inicjatyw."""

import json
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from openai import OpenAI, OpenAIError

from core.innovation_catalog import CRITERIA as LEGACY_CRITERIA
from core.innovation_catalog import InnovationCriterion, active_criteria
from core.models import InnovationIndicator
from core.services.llm import request_structured_response
from core.services.prompt_store import get_prompt
from core.services.scoring_calibration import calibration_prompt

# Tymczasowy eksport dla narzędzi badawczych i zgodności wstecznej;
# produkcyjny oceniacz używa wyłącznie active_criteria().
CRITERIA = LEGACY_CRITERIA


@dataclass(frozen=True)
class CriterionScore:
    """Punktacja pojedynczego kryterium w skali 0–100."""

    criterion: InnovationCriterion
    value: int | None
    rationale: str


@dataclass(frozen=True)
class InnovationScore:
    """Komplet ocen i wynik ważony inicjatywy."""

    criteria: tuple[CriterionScore, ...]
    total: float | None


def score_schema(criteria: tuple[InnovationCriterion, ...]) -> dict:
    """Buduje schemat odpowiedzi zgodny z aktywnymi wskaźnikami."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            criterion.key: {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "score": {"type": ["integer", "null"], "minimum": 0, "maximum": 100},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "rationale": {"type": "string"},
                },
                "required": ["score", "confidence", "rationale"],
            }
            for criterion in criteria
        },
        "required": [criterion.key for criterion in criteria],
    }


class InnovationScoringConfigurationError(RuntimeError):
    """Brakuje konfiguracji wymaganej do wywołania LLM."""


class InnovationScoringRequestError(RuntimeError):
    """Usługa LLM nie zwróciła poprawnej odpowiedzi."""


class InnovationScoringService:
    """Wysyła jedną skalibrowaną ocenę wszystkich kryteriów."""

    def __init__(self, client: OpenAI | None = None, model: str | None = None) -> None:
        self.model = model or settings.OPENAI_MODEL
        if not self.model:
            raise InnovationScoringConfigurationError("Brak zmiennej OPENAI_MODEL.")
        if client is not None:
            self.client = client
        elif not settings.OPENAI_API_KEY:
            raise InnovationScoringConfigurationError("Brak zmiennej OPENAI_API_KEY.")
        else:
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def score(self, title: str, content: str) -> InnovationScore:
        """Zwraca oceny aktywnych wskaźników i ich wynik ważony w skali 0–100."""
        title, content = self._validate_submission(title, content)
        criteria = active_criteria()
        if not criteria:
            raise InnovationScoringConfigurationError("Brak aktywnych wskaźników innowacyjności.")
        scores = self._request_scores(title, content, criteria)
        total = weighted_total(scores)
        return InnovationScore(criteria=scores, total=total)

    @staticmethod
    def _validate_submission(title: str, content: str) -> tuple[str, str]:
        title = title.strip()
        content = content.strip()
        if not title or not content:
            raise ValueError("Tytuł i treść pomysłu są wymagane.")
        return title, content

    def _request_scores(
        self, title: str, content: str, criteria: tuple[InnovationCriterion, ...]
    ) -> tuple[CriterionScore, ...]:
        calibration = calibration_prompt()
        try:
            response = request_structured_response(
                self.client,
                model=self.model,
                instructions="\n\n".join(
                    part for part in (get_prompt("innovation_assessment"), calibration) if part
                ),
                input=(
                    f"Tytuł pomysłu: {title}\n\nTreść pomysłu:\n{content}\n\nKryteria:\n"
                    + "\n".join(
                        f"- {criterion.name}: {criterion.question}" for criterion in criteria
                    )
                ),
                reasoning={"effort": "high"},
                schema_name="innovation_assessment",
                schema=score_schema(criteria),
            )
        except OpenAIError as error:
            raise InnovationScoringRequestError("Nie udało się uzyskać oceny od LLM.") from error
        return self._parse_scores(response.output_text, criteria)

    @staticmethod
    def _parse_scores(
        output: str, criteria: tuple[InnovationCriterion, ...]
    ) -> tuple[CriterionScore, ...]:
        try:
            payload = json.loads(output)
            scores = tuple(
                CriterionScore(
                    criterion=criterion,
                    value=payload[criterion.key]["score"],
                    rationale=InnovationScoringService._rationale(payload[criterion.key]),
                )
                for criterion in criteria
            )
        except (AttributeError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise InnovationScoringRequestError(
                "LLM nie zwrócił poprawnej struktury oceny."
            ) from error
        if any(
            score.value is not None
            and (type(score.value) is not int or score.value not in range(101))
            for score in scores
        ):
            raise InnovationScoringRequestError("LLM nie zwrócił punktacji od 0 do 100.")
        return scores

    @staticmethod
    def _rationale(item: dict) -> str:
        labels = {"low": "niska", "medium": "średnia", "high": "wysoka"}
        confidence = labels[item["confidence"]]
        rationale = item["rationale"].strip()
        if not rationale or (item["score"] is None and item["confidence"] != "low"):
            raise InnovationScoringRequestError("Nieprawidłowe uzasadnienie lub pewność oceny.")
        return f"Pewność oceny: {confidence}. {rationale}"


def score_innovation(title: str, content: str, client: OpenAI | None = None) -> InnovationScore:
    """Wygodny punkt wejścia do oceny zgłoszenia."""
    return InnovationScoringService(client=client).score(title, content)


def indicator_weights() -> dict[str, Decimal]:
    """Zwraca wagi wskaźników skonfigurowane przez administratora."""
    weights = dict(InnovationIndicator.objects.filter(enabled=True).values_list("key", "weight"))
    if not weights:
        raise InnovationScoringConfigurationError("Brak aktywnych wskaźników innowacyjności.")
    if sum(weights.values()) != Decimal("1.00"):
        raise InnovationScoringConfigurationError(
            "Suma wag wskaźników musi wynosić dokładnie 1,00."
        )
    return weights


def weighted_total(scores: tuple[CriterionScore, ...]) -> float | None:
    """Liczy wynik 0–100 z wagami skonfigurowanymi przez administratora."""
    if any(score.value is None for score in scores):
        return None
    weights = indicator_weights()
    total = sum(Decimal(score.value) * weights[score.criterion.key] for score in scores)
    return round(float(total), 1)

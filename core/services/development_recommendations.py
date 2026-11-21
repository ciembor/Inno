"""Generowanie ustrukturyzowanej rekomendacji dalszego rozwoju inicjatywy."""

import json
from dataclasses import dataclass

from django.conf import settings
from openai import OpenAI, OpenAIError

from core.models import DevelopmentRecommendation, Idea
from core.services.llm import request_structured_response
from core.services.prompt_store import get_prompt

RECOMMENDATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "stage": {"type": "string", "enum": list(DevelopmentRecommendation.Stage.values)},
        "development_path": {
            "type": "string",
            "enum": list(DevelopmentRecommendation.Path.values),
        },
        "next_step": {"type": "string"},
        "rationale": {"type": "string"},
        "risk": {"type": "string"},
    },
    "required": ["stage", "development_path", "next_step", "rationale", "risk"],
}


class DevelopmentRecommendationError(RuntimeError):
    """Nie udało się otrzymać użytecznej rekomendacji."""


@dataclass(frozen=True)
class RecommendedDevelopment:
    stage: str
    development_path: str
    next_step: str
    rationale: str
    risk: str


class DevelopmentRecommendationService:
    """Zamienia opis i ocenę inicjatywy w możliwy do wykonania następny krok."""

    def __init__(self, client: OpenAI | None = None, model: str | None = None):
        self.model = model or settings.OPENAI_MODEL
        if not self.model:
            raise DevelopmentRecommendationError("Brak zmiennej OPENAI_MODEL.")
        if client is not None:
            self.client = client
        elif not settings.OPENAI_API_KEY:
            raise DevelopmentRecommendationError("Brak zmiennej OPENAI_API_KEY.")
        else:
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def recommend(self, idea: Idea) -> RecommendedDevelopment:
        assessments = "\n".join(
            f"- {row.indicator.name}: {row.score if row.score is not None else 'brak danych'}. "
            f"{row.rationale}"
            for row in idea.indicator_scores.select_related("indicator").all()
        )
        if not assessments:
            assessments = "Brak szczegółowych ocen; oprzyj rekomendację na opisie."
        try:
            response = request_structured_response(
                self.client,
                model=self.model,
                instructions=get_prompt("development_recommendation"),
                input=(
                    f"Nazwa inicjatywy: {idea.name}\n\nOpis:\n{idea.content}\n\n"
                    f"Ocena i uzasadnienia:\n{assessments}"
                ),
                reasoning={"effort": "high"},
                schema_name="development_recommendation",
                schema=RECOMMENDATION_SCHEMA,
            )
        except OpenAIError as error:
            raise DevelopmentRecommendationError(
                "Nie udało się wygenerować rekomendacji."
            ) from error
        return self._parse(response.output_text)

    @staticmethod
    def _parse(output: str) -> RecommendedDevelopment:
        try:
            payload = json.loads(output)
            result = RecommendedDevelopment(**payload)
        except (TypeError, json.JSONDecodeError) as error:
            raise DevelopmentRecommendationError(
                "LLM nie zwrócił poprawnej rekomendacji."
            ) from error
        if any(not getattr(result, field).strip() for field in ("next_step", "rationale", "risk")):
            raise DevelopmentRecommendationError("LLM zwrócił niepełną rekomendację.")
        return result


def recommend_development(idea: Idea, client: OpenAI | None = None) -> RecommendedDevelopment:
    """Wygodny punkt wejścia dla zadania w tle i testów."""
    return DevelopmentRecommendationService(client=client).recommend(idea)

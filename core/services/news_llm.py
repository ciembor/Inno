"""Operacje LLM używane podczas wyszukiwania innowacji w aktualnościach."""

import json
import logging
import time
from dataclasses import dataclass
from datetime import date

from django.conf import settings
from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, OpenAIError

from core.services.llm import request_structured_response
from core.services.prompt_store import get_prompt

logger = logging.getLogger(__name__)

SELECTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "selected_articles": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "url": {"type": "string"},
                    "published_on": {
                        "anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]
                    },
                },
                "required": ["url", "published_on"],
            },
        }
    },
    "required": ["selected_articles"],
}
EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "canonical_name": {"type": "string"},
        "description": {"type": "string"},
        "decision_reason": {"type": "string"},
        "published_on": {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]},
        "institution_role": {
            "type": "string",
            "enum": [
                "creator",
                "co_creator",
                "local_adaptor",
                "local_reporter",
                "external_reference",
                "routine_implementation",
                "unknown",
            ],
        },
        "taxonomy": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "problem": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "audience": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "sector": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "mechanism": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "solution_type": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "stage": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "territory": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            },
            "required": [
                "problem", "audience", "sector", "mechanism", "solution_type", "stage", "territory"
            ],
        },
    },
    "required": [
        "name", "canonical_name", "description", "published_on",
        "institution_role", "decision_reason", "taxonomy",
    ],
}
PUBLICATION_DATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "published_on": {
            "anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]
        }
    },
    "required": ["published_on"],
}

ACCEPTED_INSTITUTION_ROLES = frozenset({"creator", "co_creator", "local_adaptor", "local_reporter"})


@dataclass(frozen=True)
class ExtractedInnovation:
    name: str
    canonical_name: str
    description: str
    published_on: date | None
    institution_role: str
    taxonomy: dict[str, tuple[str, ...]] | None = None


@dataclass(frozen=True)
class SelectedNewsArticle:
    """Artykuł wskazany na indeksie aktualności wraz z datą z tego indeksu."""

    title: str
    url: str
    published_on: date | None


class NewsInnovationLLM:
    """Wybiera artykuły i wydobywa z nich opis innowacji z retry połączenia."""

    def __init__(self, client=None, model: str | None = None, sleeper=time.sleep):
        self.client = client or OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = model or settings.OPENAI_MODEL
        self.sleeper = sleeper

    def select_links(
        self, links: tuple[tuple[str, str], ...], visible_text: str
    ) -> tuple[SelectedNewsArticle, ...]:
        candidates = [{"title": title, "url": url} for title, url in links]
        try:
            response = self._request(
                instructions=(
                    f"{get_prompt('innovation_radar_system')}\n\n"
                    f"{get_prompt('news_selection')}"
                ),
                input=(
                    f"Widoczna treść strony aktualności:\n{visible_text}\n\n"
                    f"Kandydaci JSON:\n{json.dumps(candidates, ensure_ascii=False)}"
                ),
                schema_name="news_selection",
                schema=SELECTION_SCHEMA,
            )
            if response is None:
                return ()
            selected_articles = json.loads(response.output_text)["selected_articles"]
            published_on_by_url = {
                item["url"]: date.fromisoformat(item["published_on"])
                if item["published_on"]
                else None
                for item in selected_articles
            }
        except OpenAIError as error:
            logger.warning(
                "Pomijam stronę aktualności %s po błędzie LLM: %s", visible_text[:80], error
            )
            return ()
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("Nie udało się wybrać artykułów przez LLM.") from error
        for title, url in links:
            logger.info(
                "news_selection model=%s url=%s selected=%s title=%s",
                self.model, url, url in published_on_by_url, title,
            )
        return tuple(
            SelectedNewsArticle(title, url, published_on_by_url[url])
            for title, url in links
            if url in published_on_by_url
        )

    def extract(
        self, institution_name: str, title: str, url: str, visible_text: str
    ) -> ExtractedInnovation | None:
        try:
            response = self._request(
                instructions=(
                    f"{get_prompt('innovation_radar_system')}\n\n"
                    f"{get_prompt('news_extraction')}"
                ),
                input=(
                    f"Instytucja publikująca artykuł: {institution_name}\n"
                    f"Tytuł: {title}\nAdres: {url}\n\nWidoczna treść strony:\n{visible_text}"
                ),
                schema_name="innovation_description",
                schema=EXTRACTION_SCHEMA,
            )
            if response is None:
                return None
            innovation = json.loads(response.output_text)
            name = innovation["name"].strip()
            canonical_name = innovation["canonical_name"].strip()
            description = innovation["description"].strip()
            published_on = innovation["published_on"]
            published_on = date.fromisoformat(published_on) if published_on else None
            institution_role = innovation["institution_role"]
            taxonomy = innovation.get("taxonomy")
            logger.info(
                "news_extraction model=%s url=%s role=%s complete=%s reason=%s",
                self.model, url, institution_role, bool(name and canonical_name and description),
                innovation.get("decision_reason", "Brak uzasadnienia w odpowiedzi"),
            )
        except OpenAIError as error:
            logger.warning("Pomijam artykuł %s po błędzie LLM: %s", url, error)
            return None
        except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError) as error:
            raise RuntimeError("Nie udało się wyodrębnić opisu innowacji przez LLM.") from error
        if institution_role not in ACCEPTED_INSTITUTION_ROLES:
            return None
        return (
            ExtractedInnovation(
                name, canonical_name, description, published_on, institution_role, taxonomy
            )
            if name and canonical_name and description
            else None
        )

    def publication_date(self, title: str, url: str, visible_text: str) -> date | None:
        """Zwraca wyłącznie jednoznaczną datę publikacji artykułu."""
        try:
            response = self._request(
                instructions=(
                    f"{get_prompt('innovation_radar_system')}\n\n"
                    f"{get_prompt('publication_date')}"
                ),
                input=f"Tytuł: {title}\nAdres: {url}\n\nWidoczna treść strony:\n{visible_text}",
                schema_name="publication_date",
                schema=PUBLICATION_DATE_SCHEMA,
            )
            if response is None:
                return None
            published_on = json.loads(response.output_text)["published_on"]
            return date.fromisoformat(published_on) if published_on else None
        except OpenAIError as error:
            logger.warning("Pomijam datę publikacji artykułu %s po błędzie LLM: %s", url, error)
            return None
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("Nie udało się wyodrębnić daty publikacji przez LLM.") from error

    def _request(self, *, instructions: str, input: str, schema_name: str, schema: dict):
        for delay in (0, 1, 2):
            if delay:
                self.sleeper(delay)
            try:
                return request_structured_response(
                    self.client,
                    model=self.model,
                    instructions=instructions,
                    input=input,
                    schema_name=schema_name,
                    schema=schema,
                )
            except (APIConnectionError, APITimeoutError, InternalServerError) as error:
                logger.warning("Błąd połączenia z LLM (kolejna próba): %s", error)
        logger.error("Nie udało się połączyć z LLM po trzech próbach.")
        return None

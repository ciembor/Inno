"""Taksonomia LLM i wyjaśnialne podobieństwo między inicjatywami."""

import json
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Count, Q
from django.utils.text import slugify
from openai import OpenAI, OpenAIError

from core.models import Idea, SimilarityTag
from core.services.llm import request_structured_response
from core.services.prompt_store import get_prompt

CATEGORIES = tuple(SimilarityTag.Category.values)
CATEGORY_WEIGHTS = {
    SimilarityTag.Category.PROBLEM: 4,
    SimilarityTag.Category.MECHANISM: 3,
    SimilarityTag.Category.SOLUTION_TYPE: 3,
    SimilarityTag.Category.AUDIENCE: 2,
    SimilarityTag.Category.SECTOR: 1,
    SimilarityTag.Category.STAGE: 1,
    SimilarityTag.Category.TERRITORY: 1,
}
TAXONOMY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        category: {"type": "array", "items": {"type": "string"}, "maxItems": 4}
        for category in CATEGORIES
    },
    "required": list(CATEGORIES),
}


class IdeaTaxonomyError(RuntimeError):
    """Nie udało się przypisać taksonomii inicjatywy."""


@dataclass(frozen=True)
class SimilarIdea:
    """Jedna podobna inicjatywa wraz z wyjaśnieniem relacji."""

    idea: Idea
    score: int
    relationship: str
    matching_tags: tuple[SimilarityTag, ...]

    @property
    def relationship_label(self) -> str:
        return {
            "duplicate": "Możliwe dublowanie",
            "adaptation": "Możliwa adaptacja",
            "complement": "Możliwe uzupełnienie",
            "collaboration": "Możliwa współpraca",
        }[self.relationship]

    @property
    def rationale(self) -> str:
        labels = ", ".join(tag.name for tag in self.matching_tags)
        messages = {
            "duplicate": (
                "Wspólny problem, mechanizm i typ rozwiązania wskazują na możliwe dublowanie."
            ),
            "adaptation": (
                "Wspólny problem i typ rozwiązania wskazują, że rozwiązanie może być adaptacją."
            ),
            "complement": (
                "Inicjatywy dotyczą podobnej potrzeby, lecz wykorzystują odmienne mechanizmy."
            ),
            "collaboration": (
                "Wspólne obszary sugerują możliwość wymiany doświadczeń lub współpracy."
            ),
        }
        return f"{messages[self.relationship]} Wspólne tagi: {labels}."


class IdeaTaxonomyService:
    """Wydobywa krótkie tagi opisujące inicjatywę z jej źródłowego opisu."""

    def __init__(self, client: OpenAI | None = None, model: str | None = None):
        self.model = model or settings.OPENAI_MODEL
        if not self.model:
            raise IdeaTaxonomyError("Brak zmiennej OPENAI_MODEL.")
        if client is not None:
            self.client = client
        elif not settings.OPENAI_API_KEY:
            raise IdeaTaxonomyError("Brak zmiennej OPENAI_API_KEY.")
        else:
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def classify(self, title: str, content: str) -> dict[str, tuple[str, ...]]:
        if not title.strip() or not content.strip():
            raise IdeaTaxonomyError("Nazwa i opis inicjatywy są wymagane.")
        try:
            response = request_structured_response(
                self.client,
                model=self.model,
                instructions=get_prompt("similarity_tagging"),
                input=f"Nazwa inicjatywy: {title}\n\nOpis inicjatywy:\n{content}",
                schema_name="similarity_tagging",
                schema=TAXONOMY_SCHEMA,
            )
        except OpenAIError as error:
            raise IdeaTaxonomyError("Nie udało się przypisać tagów podobieństwa.") from error
        try:
            return normalise_taxonomy(json.loads(response.output_text))
        except (json.JSONDecodeError, TypeError, IdeaTaxonomyError) as error:
            raise IdeaTaxonomyError("LLM zwrócił nieprawidłową taksonomię.") from error


def normalise_taxonomy(payload: dict | None) -> dict[str, tuple[str, ...]]:
    """Normalizuje odpowiedź modelu bez tworzenia pustych lub zdublowanych tagów."""
    payload = payload or {}
    if not isinstance(payload, dict):
        raise IdeaTaxonomyError("LLM zwrócił nieprawidłową taksonomię.")
    taxonomy = {}
    for category in CATEGORIES:
        values = payload.get(category, [])
        if not isinstance(values, (list, tuple)):
            raise IdeaTaxonomyError("LLM zwrócił nieprawidłową taksonomię.")
        cleaned = tuple(dict.fromkeys(_clean_tag_values(values)))
        taxonomy[category] = cleaned[:4]
    return taxonomy


def save_taxonomy(idea: Idea, taxonomy: dict[str, tuple[str, ...]]) -> tuple[SimilarityTag, ...]:
    """Utrwala taksonomię inicjatywy i zastępuje jej poprzednie tagi."""
    tags = []
    for category, names in normalise_taxonomy(taxonomy).items():
        for name in names:
            key = slugify(name)[:64]
            if not key:
                continue
            tag, _ = SimilarityTag.objects.get_or_create(
                category=category, key=key, defaults={"name": name[:100]}
            )
            tags.append(tag)
    idea.similarity_tags.set(tags)
    return tuple(tags)


def classify_idea(idea: Idea, client: OpenAI | None = None) -> tuple[SimilarityTag, ...]:
    """Klasyfikuje istniejącą inicjatywę i trwałe zapisuje jej tagi."""
    taxonomy = IdeaTaxonomyService(client=client).classify(idea.name, idea.content)
    return save_taxonomy(idea, taxonomy)


def similar_ideas(idea: Idea, limit: int = 5) -> tuple[SimilarIdea, ...]:
    """Zwraca najbliższe inicjatywy na podstawie ważonego nakładania tagów."""
    own_tags = tuple(idea.similarity_tags.all())
    if not own_tags:
        return ()
    own_ids = {tag.pk for tag in own_tags}
    candidates = (
        Idea.objects.exclude(pk=idea.pk)
        .filter(similarity_tags__in=own_ids)
        .annotate(common_count=Count("similarity_tags", filter=Q(similarity_tags__in=own_ids)))
        .filter(common_count__gte=2)
        .prefetch_related("similarity_tags")
    )
    matches = []
    for candidate in candidates:
        matching_tags = tuple(tag for tag in candidate.similarity_tags.all() if tag.pk in own_ids)
        score = _similarity_score(own_tags, candidate.similarity_tags.all(), matching_tags)
        if score >= 25:
            matches.append(
                SimilarIdea(
                    candidate,
                    score,
                    _relationship(own_tags, candidate.similarity_tags.all(), matching_tags),
                    matching_tags,
                )
            )
    return tuple(sorted(matches, key=lambda item: (-item.score, item.idea.name))[:limit])


def _similarity_score(own_tags, candidate_tags, matching_tags) -> int:
    shared = sum(CATEGORY_WEIGHTS[tag.category] for tag in matching_tags)
    all_tags = {tag.pk: tag for tag in (*own_tags, *candidate_tags)}
    total = sum(CATEGORY_WEIGHTS[tag.category] for tag in all_tags.values())
    return round(100 * shared / total) if total else 0


def _relationship(own_tags, candidate_tags, matching_tags) -> str:
    shared_categories = {tag.category for tag in matching_tags}
    own_categories = {
        category: {tag.key for tag in own_tags if tag.category == category}
        for category in CATEGORIES
    }
    candidate_categories = {
        category: {tag.key for tag in candidate_tags if tag.category == category}
        for category in CATEGORIES
    }
    core = {
        SimilarityTag.Category.PROBLEM,
        SimilarityTag.Category.MECHANISM,
        SimilarityTag.Category.SOLUTION_TYPE,
    }
    if core <= shared_categories:
        return "duplicate"
    is_adaptation = {
        SimilarityTag.Category.PROBLEM,
        SimilarityTag.Category.SOLUTION_TYPE,
    } <= shared_categories and (
        own_categories.get(SimilarityTag.Category.TERRITORY)
        != candidate_categories.get(SimilarityTag.Category.TERRITORY)
    )
    if is_adaptation:
        return "adaptation"
    is_complement = (
        SimilarityTag.Category.PROBLEM in shared_categories
        and SimilarityTag.Category.MECHANISM not in shared_categories
    )
    if is_complement:
        return "complement"
    return "collaboration"


def _clean_tag_values(values: list[object] | tuple[object, ...]) -> tuple[str, ...]:
    return tuple(value.strip() for value in values if isinstance(value, str) and value.strip())

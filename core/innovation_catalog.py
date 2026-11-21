"""Wspólna definicja kryteriów i sortowania ocen innowacji."""

from dataclasses import dataclass

from django.db.models import IntegerField, QuerySet
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast

from core.models import InnovationIndicator


@dataclass(frozen=True)
class InnovationCriterion:
    """Kryterium prezentowane użytkownikowi i przekazywane do oceny LLM."""

    key: str
    name: str
    question: str
    annotation: str


CRITERIA = (
    InnovationCriterion(
        key="novelty",
        name="Nowatorstwo",
        question=(
            "W jakim stopniu projekt wprowadza nowe lub nietypowe podejście w porównaniu "
            "z rozwiązaniami już stosowanymi do tego samego problemu?"
        ),
        annotation="novelty",
    ),
    InnovationCriterion(
        key="value",
        name="Wartość innowacji",
        question=(
            "Jak dużą poprawę względem dotychczasowych rozwiązań może przynieść projekt "
            "w obszarze, którego dotyczy?"
        ),
        annotation="innovation_value",
    ),
    InnovationCriterion(
        key="replicability",
        name="Replikowalność",
        question=(
            "W jakim stopniu rozwiązanie może zostać wykorzystane przez inne szkoły, "
            "uczelnie, samorządy lub instytucje?"
        ),
        annotation="replicability",
    ),
    InnovationCriterion(
        key="impact",
        name="Potencjał oddziaływania",
        question=(
            "Jak dużą zmianę w skali ponadlokalnej może wywołać projekt, zakładając jego "
            "skuteczne rozpowszechnienie?"
        ),
        annotation="impact",
    ),
)

INNOVATION_SORTS = {
    "score": ("-innovation_score", "-created_at"),
    "date": ("-published_at", "-created_at"),
    **{
        criterion.key: (f"-{criterion.annotation}", "-created_at")
        for criterion in CRITERIA
    },
}


def active_criteria() -> tuple[InnovationCriterion, ...]:
    """Zwraca aktywne kryteria skonfigurowane w panelu administracyjnym."""
    return tuple(
        InnovationCriterion(
            key=indicator.key,
            name=indicator.name,
            question=indicator.question,
            annotation=f"indicator_{indicator.pk}",
        )
        for indicator in InnovationIndicator.objects.filter(enabled=True)
    )


def annotate_criteria(queryset: QuerySet) -> QuerySet:
    """Dodaje pola potrzebne do sortowania wartości z JSONField."""
    return queryset.annotate(
        **{
            criterion.annotation: Cast(
                KeyTextTransform(criterion.name, "innovation_details"), IntegerField()
            )
            for criterion in CRITERIA
        }
    )


def assessment_rows(details: dict, rationales: dict) -> tuple[dict[str, str | int], ...]:
    """Zwraca oceny w jednej, zdefiniowanej kolejności kryteriów."""
    return tuple(
        {
            "criterion": criterion.name,
            "score": details[criterion.name],
            "rationale": rationales.get(criterion.name, ""),
        }
        for criterion in CRITERIA
        if criterion.name in details
    )

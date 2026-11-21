"""Wznawialny Timsort z trwałym komparatorem i względnymi rangami."""

import json
from functools import cmp_to_key

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.innovation_catalog import CRITERIA
from core.models import Idea, RankingRun
from core.services.innovation_scoring import InnovationScoringService, indicator_weights
from core.services.llm import request_structured_response
from core.services.prompt_store import get_prompt

OUTCOMES = ("A", "B", "tie", "unknown_a", "unknown_b", "unknown_both")


class MissingComparison(Exception):
    """Przerwanie odtwarzania sortowania w miejscu następnego wywołania API."""

    def __init__(self, key, criterion, left, right):
        self.key, self.criterion, self.left, self.right = key, criterion, left, right


def create_run():
    """Zamraża opisy i kolejność początkową; nie wykonuje płatnych wywołań."""
    return RankingRun.objects.create(
        model=settings.OPENAI_MODEL,
        prompt=get_prompt("pairwise_ranking"),
        snapshot=list(Idea.objects.filter(scored_at__isnull=False).order_by("pk").values(
            "id", "name", "content", "innovation_details"
        )),
    )


def compare(run, criterion, left, right):
    """Kanoniczna kolejność pary zapewnia ponowne użycie również odwrotnego porównania."""
    a, b = sorted((left, right), key=lambda item: item["id"])
    key = f"{criterion.key}:{a['id']}:{b['id']}"
    if key not in run.comparisons:
        raise MissingComparison(key, criterion, a, b)
    outcome = run.comparisons[key]["outcome"]
    value = {"A": -1, "B": 1, "tie": 0}[outcome]
    return value if left == a else -value


def excluded_ids(run, criterion):
    """Nieznane kryterium wyłącza projekt tylko z rankingu tego kryterium."""
    excluded = set()
    for key, result in run.comparisons.items():
        kind, a, b = key.split(":")
        if kind != criterion.key:
            continue
        if result["outcome"] in ("unknown_a", "unknown_both"):
            excluded.add(int(a))
        if result["outcome"] in ("unknown_b", "unknown_both"):
            excluded.add(int(b))
    return excluded


def rank_criterion(run, criterion):
    """Timsort wykorzystuje istniejące uporządkowanie; remisy dostają średnią rangę."""
    excluded = excluded_ids(run, criterion)
    initial = sorted(
        (item for item in run.snapshot if item["id"] not in excluded),
        key=lambda item: -(item["innovation_details"].get(criterion.name) or 0),
    )
    def comparator(left, right):
        return compare(run, criterion, left, right)

    ordered = sorted(initial, key=cmp_to_key(comparator))
    return _scores_for_order(run.snapshot, ordered, comparator)


def _scores_for_order(snapshot, ordered, comparator):
    """Wspólne miejsce w tabeli odpowiada średniej pozycji grupy remisu."""
    groups = []
    for item in ordered:
        if groups and comparator(groups[-1][-1], item) == 0:
            groups[-1].append(item)
        else:
            groups.append([item])
    result = {str(item["id"]): None for item in snapshot}
    offset = 0
    for group in groups:
        score = (
            round(100 * (1 - (offset + (len(group) - 1) / 2) / (len(ordered) - 1)), 1)
            if len(ordered) > 1 else None
        )
        result.update({str(item["id"]): score for item in group})
        offset += len(group)
    return result


def request_comparison(run, missing, client=None):
    """Jedno wywołanie, bez przekazywania poprzednich punktacji do modelu."""
    service = InnovationScoringService(client=client, model=run.model)
    response = request_structured_response(
        service.client,
        model=run.model,
        instructions=run.prompt,
        reasoning={"effort": "high"},
        input=json.dumps({
            "criterion": missing.criterion.question,
            "A": {key: missing.left[key] for key in ("name", "content")},
            "B": {key: missing.right[key] for key in ("name", "content")},
        }, ensure_ascii=False),
        schema_name="pairwise_comparison",
        schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "outcome": {"type": "string", "enum": list(OUTCOMES)},
                "rationale": {"type": "string"},
            },
            "required": ["outcome", "rationale"],
        },
    )
    result = json.loads(response.output_text)
    if (not isinstance(result, dict) or result.get("outcome") not in OUTCOMES
            or not isinstance(result.get("rationale"), str) or not result["rationale"].strip()):
        raise ValueError("Niepoprawna odpowiedź porównania LLM.")
    return result


@transaction.atomic
def publish(run):
    """Publikuje cały przebieg atomowo, wyłącznie jeśli opisy nadal są aktualne."""
    if RankingRun.objects.filter(pk__gt=run.pk).exists():
        raise ValueError("Istnieje nowszy przebieg; nie nadpisano wyników.")
    weights = indicator_weights()
    for item in run.snapshot:
        scores = {f"relative_{c.key}": run.results[c.key][str(item["id"])] for c in CRITERIA}
        total = (
            None
            if None in scores.values()
            else round(
                sum(scores[f"relative_{c.key}"] * float(weights[c.key]) for c in CRITERIA), 1
            )
        )
        updated = Idea.objects.filter(
            pk=item["id"], name=item["name"], content=item["content"],
            innovation_details=item["innovation_details"], scored_at__isnull=False,
        ).update(**scores, relative_score=total, relative_scored_at=timezone.now())
        if not updated:
            raise ValueError("Pula zmieniła się podczas rankingu; utwórz nowy przebieg.")
    run.status = "completed"
    run.save(update_fields=["status", "results"])


def advance_run(run, client=None):
    """Odtwarza deterministyczne sortowanie, wykonując najwyżej jedno nowe porównanie."""
    try:
        for criterion in CRITERIA:
            run.results[criterion.key] = rank_criterion(run, criterion)
    except MissingComparison as missing:
        run.comparisons[missing.key] = request_comparison(run, missing, client)
        run.status = "pending"
        run.save(update_fields=["comparisons", "results", "status"])
        return False
    publish(run)
    return True

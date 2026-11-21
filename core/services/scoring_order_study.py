"""Ograniczone, odtwarzalne badanie zgodności kolejności ocen wstępnych."""

import json
import random
from collections import Counter
from itertools import combinations

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from openai import OpenAI

from core.innovation_catalog import CRITERIA
from core.models import Idea, RankingRun, ScoringOrderPair, ScoringOrderStudy
from core.services.llm import request_structured_response
from core.services.prompt_store import get_prompt

SAMPLE_PER_STRATUM = 15
SEED = 20261118
STRATA = ("tie", "close", "medium", "far")
OUTCOMES = ("A", "B", "tie", "unclear")

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "outcome": {"type": "string", "enum": list(OUTCOMES)},
        "rationale": {"type": "string"},
    },
    "required": ["outcome", "rationale"],
}


def stratum_for_gap(gap):
    """Zamrożone granice zakresów badania."""
    if gap == 0:
        return "tie"
    if gap <= 5:
        return "close"
    if gap <= 15:
        return "medium"
    return "far"


def previous_pair_keys():
    """Wyklucza adaptacyjnie dobrane pary z wcześniejszego sortowania."""
    return {
        (criterion, int(a), int(b))
        for comparisons in RankingRun.objects.values_list("comparisons", flat=True)
        for key in comparisons
        for criterion, a, b in (key.split(":"),)
    }


def candidate_pools(items, criterion, excluded):
    """Tworzy populację par o znanych, zamrożonych ocenach."""
    scored = [
        item for item in items
        if type(item["innovation_details"].get(criterion.name)) is int
    ]
    pools = {name: [] for name in STRATA}
    for left, right in combinations(scored, 2):
        if (criterion.key, left["id"], right["id"]) in excluded:
            continue
        gap = abs(
            left["innovation_details"][criterion.name]
            - right["innovation_details"][criterion.name]
        )
        pools[stratum_for_gap(gap)].append((left, right))
    return pools


def select_pairs(pools, criterion, rng, count):
    """Prosta próba losowa par bez powtórzeń w każdej warstwie."""
    selected = []
    for stratum in STRATA:
        if len(pools[stratum]) < count:
            raise ValueError(f"Za mało par: {criterion.key}/{stratum}.")
        chosen = rng.sample(pools[stratum], count)
        selected.extend(orient_pairs(chosen, criterion, stratum, rng))
    rng.shuffle(selected)
    return selected


def orient_pairs(chosen, criterion, stratum, rng):
    """Zrównoważona pozycja A/B wcześniejszego lidera bez ujawniania jej modelowi."""
    rng.shuffle(chosen)
    result = []
    for index, (left, right) in enumerate(chosen):
        score_left = left["innovation_details"][criterion.name]
        score_right = right["innovation_details"][criterion.name]
        if score_left == score_right:
            swap = bool(rng.getrandbits(1))
        else:
            swap = (score_left < score_right) == (index % 2 == 0)
        if swap:
            left, right = right, left
            score_left, score_right = score_right, score_left
        result.append({
            "criterion": criterion.key,
            "stratum": stratum,
            "left_idea_id": left["id"],
            "right_idea_id": right["id"],
            "left_name": left["name"],
            "right_name": right["name"],
            "left_content": left["content"],
            "right_content": right["content"],
            "left_score": score_left,
            "right_score": score_right,
        })
    return result


@transaction.atomic
def create_study(seed=SEED, sample_per_stratum=SAMPLE_PER_STRATUM):
    """Zapisuje całą próbę przed pierwszym wywołaniem API; limit jest twardy."""
    if not 1 <= sample_per_stratum <= SAMPLE_PER_STRATUM:
        raise ValueError("Wielkość próby musi wynosić od 1 do 15 par na warstwę.")
    rng = random.Random(seed)
    items = list(Idea.objects.filter(scored_at__isnull=False).order_by("pk").values(
        "id", "name", "content", "innovation_details"
    ))
    excluded = previous_pair_keys()
    selections = {}
    populations = {}
    for criterion in CRITERIA:
        pools = candidate_pools(items, criterion, excluded)
        populations[criterion.key] = {name: len(pools[name]) for name in STRATA}
        selections[criterion.key] = select_pairs(pools, criterion, rng, sample_per_stratum)
    study = ScoringOrderStudy.objects.create(
        seed=seed, sample_per_stratum=sample_per_stratum,
        model=settings.OPENAI_MODEL,
        prompt=get_prompt("scoring_order_study"),
        population_counts=populations,
    )
    plan = [
        selections[criterion.key][index]
        for index in range(sample_per_stratum * len(STRATA))
        for criterion in CRITERIA
    ]
    ScoringOrderPair.objects.bulk_create([
        ScoringOrderPair(study=study, position=index, **pair)
        for index, pair in enumerate(plan)
    ])
    return study


def compare_study_pair(study, pair, client=None):
    """Jedna zaślepiona ocena pary; wynik jest kategorią, nie punktacją."""
    if client is None:
        if not settings.OPENAI_API_KEY:
            raise ValueError("Brak OPENAI_API_KEY.")
        client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=90, max_retries=0)
    criterion = next(item for item in CRITERIA if item.key == pair.criterion)
    response = request_structured_response(
        client,
        model=study.model,
        instructions=study.prompt,
        input=json.dumps({
            "criterion": criterion.question,
            "A": {"title": pair.left_name, "description": pair.left_content},
            "B": {"title": pair.right_name, "description": pair.right_content},
        }, ensure_ascii=False),
        reasoning={"effort": "high"},
        schema_name="scoring_order_comparison",
        schema=RESPONSE_SCHEMA,
    )
    if response.status != "completed":
        raise ValueError("LLM nie ukończył odpowiedzi.")
    result = json.loads(response.output_text)
    if (not isinstance(result, dict) or result.get("outcome") not in OUTCOMES
            or not isinstance(result.get("rationale"), str) or not result["rationale"].strip()):
        raise ValueError("Niepoprawna odpowiedź LLM.")
    return result


def classify_pair(pair):
    """Zgodność kierunku bez udawania, że porównanie LLM jest prawdą wzorcową."""
    if not pair.outcome:
        return "pending"
    if pair.outcome == "unclear":
        return "unclear"
    if pair.left_score == pair.right_score:
        return "tie_preserved" if pair.outcome == "tie" else "tie_split"
    if pair.outcome == "tie":
        return "new_tie"
    prior = "A" if pair.left_score > pair.right_score else "B"
    return "concordant" if pair.outcome == prior else "discordant"


def study_summary(study):
    """Raport warstwowy; nie łączy warstw o różnych prawdopodobieństwach doboru."""
    summary = {criterion.key: {stratum: Counter() for stratum in STRATA} for criterion in CRITERIA}
    for pair in study.pairs.all():
        summary[pair.criterion][pair.stratum][classify_pair(pair)] += 1
    return {
        criterion: {stratum: dict(counts) for stratum, counts in strata.items()}
        for criterion, strata in summary.items()
    }


def save_result(pair, result):
    """Trwały checkpoint po każdym płatnym porównaniu."""
    pair.outcome = result["outcome"]
    pair.rationale = result["rationale"]
    pair.completed_at = timezone.now()
    pair.save(update_fields=["outcome", "rationale", "completed_at"])

"""Odtwarzalne badanie zgodności kolejności końcowych ocen innowacji."""

import json
import random
from collections import Counter
from itertools import combinations

from django.conf import settings
from django.db import transaction
from openai import OpenAI

from core.models import Idea, OverallOrderPair, OverallOrderStudy
from core.services.llm import request_structured_response
from core.services.prompt_store import get_prompt
from core.services.scoring_order_study import OUTCOMES, RESPONSE_SCHEMA

SEED = 20261118
SAMPLE_PER_STRATUM = 60
REPEAT_COUNT = 20
STRATA = ("close", "medium", "far")

def stratum_for_gap(gap):
    """Zakresy różnic końcowego wyniku, zapisane przed rozpoczęciem badania."""
    if gap == 0:
        return None
    if gap <= 5:
        return "close"
    if gap <= 15:
        return "medium"
    return "far"


def candidate_pools(items):
    """Wszystkie pary o różnych, istniejących końcowych ocenach."""
    pools = {stratum: [] for stratum in STRATA}
    for left, right in combinations(items, 2):
        stratum = stratum_for_gap(abs(left["innovation_score"] - right["innovation_score"]))
        if stratum is not None:
            pools[stratum].append((left, right))
    return pools


def orient_pairs(chosen, stratum, rng):
    """Równoważy pozycję wcześniejszego lidera bez ujawnienia ocen modelowi."""
    rng.shuffle(chosen)
    rows = []
    for index, (left, right) in enumerate(chosen):
        if (left["innovation_score"] < right["innovation_score"]) == (index % 2 == 0):
            left, right = right, left
        rows.append({
            "stratum": stratum,
            "left_idea_id": left["id"], "right_idea_id": right["id"],
            "left_name": left["name"], "right_name": right["name"],
            "left_content": left["content"], "right_content": right["content"],
            "left_score": left["innovation_score"],
            "right_score": right["innovation_score"],
        })
    return rows


@transaction.atomic
def create_study(seed=SEED, sample_per_stratum=SAMPLE_PER_STRATUM, repeat_count=REPEAT_COUNT):
    """Zapisuje 180 różnych par i 20 odwróconych powtórek przed wywołaniami API."""
    if not 1 <= sample_per_stratum <= SAMPLE_PER_STRATUM:
        raise ValueError("Liczba par na warstwę musi wynosić od 1 do 60.")
    if not 0 <= repeat_count <= min(REPEAT_COUNT, sample_per_stratum * len(STRATA)):
        raise ValueError("Liczba powtórek przekracza limit 20 lub liczbę par.")
    rng = random.Random(seed)
    items = list(Idea.objects.filter(innovation_score__isnull=False).order_by("pk").values(
        "id", "name", "content", "innovation_score"
    ))
    pools = candidate_pools(items)
    if any(len(pools[stratum]) < sample_per_stratum for stratum in STRATA):
        raise ValueError("Za mało par w co najmniej jednej warstwie.")
    study = OverallOrderStudy.objects.create(
        seed=seed, sample_per_stratum=sample_per_stratum,
        repeat_count=repeat_count, model=settings.OPENAI_MODEL,
        prompt=get_prompt("overall_order_study"),
        population_counts={stratum: len(pools[stratum]) for stratum in STRATA},
    )
    bases = {
        stratum: orient_pairs(rng.sample(pools[stratum], sample_per_stratum), stratum, rng)
        for stratum in STRATA
    }
    plan = [row for stratum in STRATA for row in bases[stratum]]
    rng.shuffle(plan)
    original_pairs = OverallOrderPair.objects.bulk_create([
        OverallOrderPair(study=study, position=index, **row)
        for index, row in enumerate(plan)
    ])
    quotient, remainder = divmod(repeat_count, len(STRATA))
    repeats = [
        pair for index, stratum in enumerate(STRATA)
        for pair in rng.sample(
            [item for item in original_pairs if item.stratum == stratum],
            quotient + (index < remainder),
        )
    ]
    rng.shuffle(repeats)
    OverallOrderPair.objects.bulk_create([
        OverallOrderPair(
            study=study, repeat_of=pair, position=len(plan) + index,
            stratum=pair.stratum,
            left_idea_id=pair.right_idea_id, right_idea_id=pair.left_idea_id,
            left_name=pair.right_name, right_name=pair.left_name,
            left_content=pair.right_content, right_content=pair.left_content,
            left_score=pair.right_score, right_score=pair.left_score,
        )
        for index, pair in enumerate(repeats)
    ])
    return study


def compare_pair(study, pair, client=None):
    """Jedno zaślepione porównanie, bez punktacji w żądaniu API."""
    if client is None:
        if not settings.OPENAI_API_KEY:
            raise ValueError("Brak OPENAI_API_KEY.")
        client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=90, max_retries=0)
    response = request_structured_response(
        client,
        model=study.model,
        instructions=study.prompt,
        input=json.dumps({
            "A": {"title": pair.left_name, "description": pair.left_content},
            "B": {"title": pair.right_name, "description": pair.right_content},
        }, ensure_ascii=False),
        reasoning={"effort": "high"},
        schema_name="overall_order_comparison",
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
    """Zgodność względem wcześniejszej punktacji, nie etykieta prawdy."""
    if not pair.outcome:
        return "pending"
    if pair.outcome in ("unclear", "tie"):
        return pair.outcome
    prior = "A" if pair.left_score > pair.right_score else "B"
    return "concordant" if pair.outcome == prior else "discordant"


def repeat_agreement(pair):
    """Zgodność z odwróconą odpowiedzią na oryginalną parę."""
    if not pair.outcome or not pair.repeat_of.outcome:
        return "pending"
    expected = {"A": "B", "B": "A", "tie": "tie", "unclear": "unclear"}
    return "stable" if pair.outcome == expected[pair.repeat_of.outcome] else "unstable"


def study_summary(study):
    """Raportuje warstwy i stabilność osobno; nie miesza powtórek z próbą."""
    pairs = list(study.pairs.select_related("repeat_of"))
    return {
        "strata": {
            stratum: dict(Counter(classify_pair(pair) for pair in pairs
                                  if pair.repeat_of_id is None and pair.stratum == stratum))
            for stratum in STRATA
        },
        "repeats": dict(Counter(repeat_agreement(pair) for pair in pairs
                                if pair.repeat_of_id is not None)),
    }

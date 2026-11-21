"""Próba warstwowa, zaślepienie, limity i wznowienie badania."""

import json
import random
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from celery.exceptions import Retry
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from openai import APITimeoutError

from core.innovation_catalog import CRITERIA
from core.models import Idea, RankingRun, ScoringOrderStudy
from core.services import scoring_order_study as study_service
from core.tasks import run_scoring_order_study

pytestmark = pytest.mark.django_db


def scored_ideas(count=40):
    scores = (0, 0, 3, 3, 10, 10, 30, 30)
    return [
        Idea.objects.create(
            name=f"Projekt {index}", content=f"Opis projektu {index}",
            scored_at=timezone.now(),
            innovation_details={
                criterion.name: scores[index % len(scores)] for criterion in CRITERIA
            },
        )
        for index in range(count)
    ]


def make_study():
    scored_ideas()
    return study_service.create_study(sample_per_stratum=1)


@pytest.mark.parametrize(("gap", "expected"), [
    (0, "tie"), (1, "close"), (5, "close"), (6, "medium"),
    (15, "medium"), (16, "far"),
])
def test_gap_boundaries(gap, expected):
    assert study_service.stratum_for_gap(gap) == expected


def test_study_is_fixed_reproducible_and_excludes_adaptive_pairs():
    entries = scored_ideas()
    a, b = entries[:2]
    RankingRun.objects.create(
        model="test-model", prompt="test", snapshot=[],
        comparisons={f"novelty:{a.pk}:{b.pk}": {"outcome": "tie"}},
    )
    assert ("novelty", a.pk, b.pk) in study_service.previous_pair_keys()
    first = study_service.create_study(seed=123, sample_per_stratum=2)
    second = study_service.create_study(seed=123, sample_per_stratum=2)
    fields = ("criterion", "stratum", "left_idea_id", "right_idea_id", "left_score", "right_score")
    assert list(first.pairs.values_list(*fields)) == list(second.pairs.values_list(*fields))
    assert first.pairs.count() == 32
    for criterion in CRITERIA:
        pairs = list(first.pairs.filter(criterion=criterion.key))
        ids = [tuple(sorted((pair.left_idea_id, pair.right_idea_id))) for pair in pairs]
        assert len(ids) == len(set(ids)) == 8
        assert {stratum: sum(pair.stratum == stratum for pair in pairs)
                for stratum in study_service.STRATA} == dict.fromkeys(study_service.STRATA, 2)
        assert first.population_counts[criterion.key]["tie"] > 0
    assert not first.pairs.filter(criterion="novelty", left_idea_id=a.pk,
                                  right_idea_id=b.pk).exists()


def test_sampling_balance_and_insufficient_pools():
    entries = scored_ideas(16)
    items = list(Idea.objects.order_by("pk").values("id", "name", "content", "innovation_details"))
    pools = study_service.candidate_pools(items, CRITERIA[0], set())
    assert sum(len(pool) for pool in pools.values()) == 120
    with pytest.raises(ValueError, match="Za mało"):
        study_service.select_pairs(pools, CRITERIA[0], random.Random(7), 121)
    a, b = items[:2]
    oriented = study_service.orient_pairs([(a, b), (b, a)], CRITERIA[0], "tie",
                                          random.Random(4))
    assert all(row["left_score"] == row["right_score"] for row in oriented)
    assert len(entries) == 16


@pytest.mark.parametrize("sample", [0, 16])
def test_sample_limit(sample):
    with pytest.raises(ValueError, match="od 1 do 15"):
        study_service.create_study(sample_per_stratum=sample)
    assert not ScoringOrderStudy.objects.exists()


def test_missing_scores_are_excluded_from_pair_population():
    scored_ideas(8)
    Idea.objects.create(
        name="Nieoceniony", content="Opis", scored_at=timezone.now(),
        innovation_details={criterion.name: None for criterion in CRITERIA},
    )
    items = list(Idea.objects.values("id", "name", "content", "innovation_details"))
    pools = study_service.candidate_pools(items, CRITERIA[0], set())
    assert sum(map(len, pools.values())) == 28


@pytest.mark.parametrize(("status", "payload", "error"), [
    ("completed", {"outcome": "A", "rationale": "A ma silniejszy dowód"}, None),
    ("incomplete", {"outcome": "A", "rationale": "Opis"}, "nie ukończył"),
    ("completed", [], "Niepoprawna"),
    ("completed", {"outcome": "wrong", "rationale": "Opis"}, "Niepoprawna"),
    ("completed", {"outcome": "B", "rationale": 3}, "Niepoprawna"),
    ("completed", {"outcome": "tie", "rationale": " "}, "Niepoprawna"),
])
def test_blinded_llm_response(status, payload, error):
    study = make_study()
    pair = study.pairs.first()
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        status=status, output_text=json.dumps(payload)
    )
    if error:
        with pytest.raises(ValueError, match=error):
            study_service.compare_study_pair(study, pair, client)
    else:
        assert study_service.compare_study_pair(study, pair, client) == payload
    request = client.responses.create.call_args.kwargs
    assert "score" not in request["input"].lower()
    assert str(pair.left_score) not in json.loads(request["input"])["A"]["title"]
    assert request["text"]["format"]["strict"]


def test_missing_api_key_fails_before_network(settings):
    study = make_study()
    settings.OPENAI_API_KEY = ""
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        study_service.compare_study_pair(study, study.pairs.first())


def test_configured_client_has_bounded_timeout(settings):
    study = make_study()
    settings.OPENAI_API_KEY = "test-only"
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        status="completed", output_text=json.dumps({
            "outcome": "tie", "rationale": "Porównywalne rozwiązania",
        })
    )
    with patch.object(study_service, "OpenAI", return_value=client) as constructor:
        result = study_service.compare_study_pair(study, study.pairs.first())
    assert result["outcome"] == "tie"
    constructor.assert_called_once_with(api_key="test-only", timeout=90, max_retries=0)


@pytest.mark.parametrize(("left", "right", "outcome", "expected"), [
    (4, 4, "", "pending"), (4, 4, "unclear", "unclear"),
    (4, 4, "tie", "tie_preserved"), (4, 4, "A", "tie_split"),
    (8, 4, "tie", "new_tie"), (8, 4, "A", "concordant"),
    (8, 4, "B", "discordant"), (4, 8, "B", "concordant"),
    (4, 8, "A", "discordant"),
])
def test_pair_classification(left, right, outcome, expected):
    pair = SimpleNamespace(left_score=left, right_score=right, outcome=outcome)
    assert study_service.classify_pair(pair) == expected


def test_checkpoint_summary_and_pause_prevent_next_call():
    study = make_study()
    study.error = "Poprzedni timeout"
    study.save(update_fields=["error"])
    pair = study.pairs.first()
    with patch("core.tasks.compare_study_pair", return_value={
        "outcome": "A", "rationale": "Wskazano konkretne różnice",
    }), patch.object(run_scoring_order_study, "delay") as delay:
        run_scoring_order_study(study.pk)
        delay.assert_called_once_with(study.pk)
        pair.refresh_from_db()
        assert pair.completed_at
        assert pair.outcome == "A"
        assert ScoringOrderStudy.objects.get(pk=study.pk).error == ""
        assert study_service.study_summary(study)[pair.criterion][pair.stratum]
        ScoringOrderStudy.objects.filter(pk=study.pk).update(status="paused")
        run_scoring_order_study(study.pk)
        assert delay.call_count == 1
    assert study.pairs.exclude(outcome="").count() == 1


def test_job_completes_after_fixed_sample():
    study = make_study()
    study.pairs.update(outcome="tie")
    run_scoring_order_study(study.pk)
    study.refresh_from_db()
    assert study.status == "completed"
    assert study.pairs.count() == 16


def test_job_failure_and_pause_during_request():
    study = make_study()
    with (
        patch("core.tasks.compare_study_pair", side_effect=RuntimeError("API down")),
        pytest.raises(RuntimeError, match="API down"),
    ):
        run_scoring_order_study(study.pk)
    study.refresh_from_db()
    assert study.status == "failed"
    assert study.error == "API down"
    study.status = "pending"
    study.save(update_fields=["status"])

    def pause_while_comparing(*args):
        ScoringOrderStudy.objects.filter(pk=study.pk).update(status="paused")
        return {"outcome": "unclear", "rationale": "Za mało danych"}

    with patch("core.tasks.compare_study_pair", side_effect=pause_while_comparing), \
            patch.object(run_scoring_order_study, "delay") as delay:
        run_scoring_order_study(study.pk)
        delay.assert_not_called()
    study.refresh_from_db()
    assert study.status == "paused"


def test_timeout_retries_scoring_order_without_losing_checkpoint():
    study = make_study()
    timeout = APITimeoutError(httpx.Request("POST", "https://api.openai.com/v1/responses"))
    with (
        patch("core.tasks.compare_study_pair", side_effect=timeout),
        patch.object(run_scoring_order_study, "retry", side_effect=Retry()) as retry,
        pytest.raises(Retry),
    ):
        run_scoring_order_study(study.pk)
    study.refresh_from_db()
    assert study.status == "pending"
    assert study.pairs.exclude(outcome="").count() == 0
    assert retry.call_args.kwargs["countdown"] == 10
    assert run_scoring_order_study.max_retries is None


def test_command_controls_and_report():
    scored_ideas()
    output = StringIO()
    with patch.object(run_scoring_order_study, "delay") as delay:
        call_command("study_scoring_order", sample_per_stratum=1, stdout=output)
        study = ScoringOrderStudy.objects.get()
        delay.assert_called_once_with(study.pk)
        assert "16 par" in output.getvalue()
        with pytest.raises(CommandError, match="już działa"):
            call_command("study_scoring_order", sample_per_stratum=1)
        with pytest.raises(CommandError, match="jedną akcję"):
            call_command("study_scoring_order", status=study.pk, pause=study.pk)
        with pytest.raises(CommandError, match="Nie znaleziono"):
            call_command("study_scoring_order", status=9999)
        output = StringIO()
        call_command("study_scoring_order", status=study.pk, stdout=output)
        assert json.loads(output.getvalue())["total"] == 16
        call_command("study_scoring_order", pause=study.pk)
        with pytest.raises(CommandError, match="nieaktywnego"):
            call_command("study_scoring_order", pause=study.pk)
        call_command("study_scoring_order", resume=study.pk)
        assert delay.call_count == 2
        with pytest.raises(CommandError, match="wstrzymane"):
            call_command("study_scoring_order", resume=study.pk)


def test_command_invalid_sample_and_failed_resume():
    with pytest.raises(CommandError, match="od 1 do 15"):
        call_command("study_scoring_order", sample_per_stratum=0)
    study = make_study()
    study.status, study.error = "failed", "Poprzedni błąd"
    study.save(update_fields=["status", "error"])
    with patch.object(run_scoring_order_study, "delay"):
        call_command("study_scoring_order", resume=study.pk)
    study.refresh_from_db()
    assert study.status == "pending"
    assert study.error == ""

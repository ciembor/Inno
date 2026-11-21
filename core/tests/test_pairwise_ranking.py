"""Ranking względny: algorytm, checkpointy, publikacja i orkiestracja."""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from core.innovation_catalog import CRITERIA
from core.models import Idea, RankingRun
from core.services import pairwise_ranking as ranking
from core.tasks import rank_innovations

pytestmark = pytest.mark.django_db


def ideas(count=3):
    return [Idea.objects.create(name=f"Projekt {i}", content=f"Opis {i}",
                                innovation_details={c.name: i for c in CRITERIA},
                                scored_at=timezone.now())
            for i in range(count)]


def finish(run, outcome="B"):
    with patch.object(ranking, "request_comparison", return_value={
        "outcome": outcome, "rationale": "Porównanie opisów",
    }) as request:
        while not ranking.advance_run(run):
            run.refresh_from_db()
    return request.call_count


def test_ranking_keeps_original_scores_and_reuses_cache():
    entries = ideas()
    run = ranking.create_run()
    assert finish(run) == 8  # n-1 comparisons for each already sorted criterion
    assert run.status == "completed"
    assert finish(run) == 0
    for entry, score in zip(entries, (0, 50, 100), strict=True):
        entry.refresh_from_db()
        assert entry.relative_score == score
        assert entry.relative_novelty == score
        assert entry.innovation_score is None
        assert entry.relative_scored_at


@pytest.mark.parametrize("count,outcome,expected", [
    (0, "tie", []), (1, "tie", [None]), (3, "tie", [50, 50, 50]),
    (3, "unknown_a", [None, None, None]),
    (3, "unknown_b", [None, None, None]),
    (3, "unknown_both", [None, None, None]),
])
def test_ties_unknown_and_small_pools(count, outcome, expected):
    entries = ideas(count)
    finish(ranking.create_run(), outcome)
    assert list(Idea.objects.order_by("pk").values_list("relative_score", flat=True)) == expected
    assert len(entries) == count


def test_unknown_is_criterion_specific_and_ties_use_average_rank():
    entries = ideas(4)
    run = ranking.create_run()
    a, b, c, d = [item["id"] for item in run.snapshot]
    run.comparisons = {
        f"novelty:{a}:{b}": {"outcome": "unknown_a"},
        f"value:{a}:{b}": {"outcome": "unknown_both"},
        f"novelty:{b}:{c}": {"outcome": "tie"},
        f"novelty:{b}:{d}": {"outcome": "B"},
        f"novelty:{c}:{d}": {"outcome": "B"},
    }
    assert ranking.rank_criterion(run, CRITERIA[0]) == {
        str(entries[0].pk): None, str(b): 25, str(c): 25, str(d): 100,
    }
    assert ranking.compare(run, CRITERIA[0], run.snapshot[1], run.snapshot[3]) == 1


def test_unsorted_inputs():
    ideas(4)
    run = ranking.create_run()
    finish(run, "A")
    assert list(Idea.objects.order_by("pk").values_list("relative_score", flat=True)) == [
        100, Decimal("66.7"), Decimal("33.3"), 0,
    ]


@pytest.mark.parametrize("mutation", ["edit", "delete", "new_run", "rescore"])
def test_publish_refuses_stale_results_atomically(mutation):
    entries = ideas(2)
    run = ranking.create_run()
    run.results = {c.key: {str(i.pk): 50 for i in entries} for c in CRITERIA}
    if mutation == "edit":
        Idea.objects.filter(pk=entries[-1].pk).update(content="Zmiana")
    elif mutation == "delete":
        entries[-1].delete()
    elif mutation == "rescore":
        Idea.objects.filter(pk=entries[-1].pk).update(innovation_details={"Nowatorstwo": 90})
    else:
        ranking.create_run()
    with pytest.raises(ValueError):
        ranking.publish(run)
    assert not Idea.objects.exclude(relative_score=None).exists()


@pytest.mark.parametrize("payload", [
    {"outcome": "A", "rationale": "Lepszy efekt"},
    [], {"outcome": "invalid"}, {"outcome": "A", "rationale": 5},
    {"outcome": "A", "rationale": " "},
])
def test_request_schema_validation_and_no_old_scores(payload):
    ideas(2)
    run = ranking.create_run()
    missing = ranking.MissingComparison("key", CRITERIA[0], *run.snapshot)
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(output_text=json.dumps(payload))
    if payload == {"outcome": "A", "rationale": "Lepszy efekt"}:
        assert ranking.request_comparison(run, missing, client) == payload
    else:
        with pytest.raises(ValueError):
            ranking.request_comparison(run, missing, client)
    kwargs = client.responses.create.call_args.kwargs
    assert "innovation_details" not in kwargs["input"]
    assert kwargs["instructions"] == run.prompt
    assert kwargs["text"]["format"]["strict"]


def test_job_checkpoints_and_duplicate_delivery():
    ideas(2)
    run = ranking.create_run()
    with patch.object(ranking, "request_comparison", return_value={
        "outcome": "B", "rationale": "Efekty",
    }), patch.object(rank_innovations, "delay") as delay:
        rank_innovations(run.pk)
        delay.assert_called_once_with(run.pk)
        run.refresh_from_db()
        assert len(run.comparisons) == 1
        assert run.status == "pending"
        RankingRun.objects.filter(pk=run.pk).update(status="running")
        rank_innovations(run.pk)
        assert delay.call_count == 1
    empty = ranking.create_run()
    empty.snapshot = []
    empty.save()
    rank_innovations(empty.pk)
    empty.refresh_from_db()
    assert empty.status == "completed"


def test_failed_job_can_resume_without_repeating_paid_comparisons():
    ideas(2)
    run = ranking.create_run()
    with (
        patch.object(ranking, "request_comparison", side_effect=RuntimeError("API error")),
        pytest.raises(RuntimeError, match="API error"),
    ):
        rank_innovations(run.pk)
    run.refresh_from_db()
    assert run.status == "failed"
    assert run.error == "API error"
    with patch.object(rank_innovations, "delay") as delay:
        call_command("rank_innovations", resume=run.pk)
        delay.assert_called_once_with(run.pk)
    run.refresh_from_db()
    assert run.status == "pending"
    assert run.error == ""


def test_command_start_and_invalid_resume():
    ideas()
    with patch.object(rank_innovations, "delay") as delay:
        call_command("rank_innovations")
        run = RankingRun.objects.get()
        delay.assert_called_once_with(run.pk)
        with pytest.raises(CommandError, match="już trwa"):
            call_command("rank_innovations")
        call_command("rank_innovations", resume=run.pk)
        with pytest.raises(CommandError, match="wznowić"):
            call_command("rank_innovations", resume=9999)
        run.status = "completed"
        run.save()
        with pytest.raises(CommandError, match="wznowić"):
            call_command("rank_innovations", resume=run.pk)


def test_run_excludes_unassessed_ideas():
    ideas(2)
    Idea.objects.create(name="Nowy pomysł", content="W kolejce")
    assert len(ranking.create_run().snapshot) == 2

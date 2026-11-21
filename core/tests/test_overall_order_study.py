"""Badanie końcowej kolejności: próba, zaślepienie i wznowienie."""

import json
import random
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from celery.exceptions import Retry
from django.core.management import call_command
from django.core.management.base import CommandError
from openai import APITimeoutError

from core.models import Idea, OverallOrderStudy
from core.services import overall_order_study as service
from core.tasks import retry_study_timeout, run_overall_order_study

pytestmark = pytest.mark.django_db


def scored_ideas(count=24):
    scores = (0, 0, 3, 3, 10, 10, 30, 30)
    return [
        Idea.objects.create(
            name=f"Projekt {index}", content=f"Opis projektu {index}",
            innovation_score=scores[index % len(scores)],
        )
        for index in range(count)
    ]


def make_study():
    scored_ideas()
    return service.create_study(sample_per_stratum=2, repeat_count=2)


@pytest.mark.parametrize(("gap", "expected"), [
    (0, None), (Decimal("0.1"), "close"), (5, "close"),
    (Decimal("5.1"), "medium"), (15, "medium"), (Decimal("15.1"), "far"),
])
def test_gap_boundaries(gap, expected):
    assert service.stratum_for_gap(gap) == expected


def test_sample_is_fixed_balanced_and_repeats_are_reversed():
    scored_ideas()
    first = service.create_study(seed=7, sample_per_stratum=3, repeat_count=3)
    second = service.create_study(seed=7, sample_per_stratum=3, repeat_count=3)
    columns = ("stratum", "left_idea_id", "right_idea_id", "left_score", "right_score")
    assert list(first.pairs.values_list(*columns)) == list(second.pairs.values_list(*columns))
    originals = list(first.pairs.filter(repeat_of__isnull=True))
    repeats = list(first.pairs.filter(repeat_of__isnull=False).select_related("repeat_of"))
    assert len(originals) == 9
    assert len(repeats) == 3
    assert {stratum: sum(pair.stratum == stratum for pair in originals)
            for stratum in service.STRATA} == dict.fromkeys(service.STRATA, 3)
    assert {stratum: sum(pair.stratum == stratum for pair in repeats)
            for stratum in service.STRATA} == dict.fromkeys(service.STRATA, 1)
    assert len({tuple(sorted((p.left_idea_id, p.right_idea_id))) for p in originals}) == 9
    for pair in repeats:
        assert pair.left_idea_id == pair.repeat_of.right_idea_id
        assert pair.right_idea_id == pair.repeat_of.left_idea_id
        assert pair.left_score == pair.repeat_of.right_score
        assert pair.right_content == pair.repeat_of.left_content
    for stratum in service.STRATA:
        subset = [p for p in originals if p.stratum == stratum]
        assert abs(sum(p.left_score > p.right_score for p in subset)
                   - sum(p.left_score < p.right_score for p in subset)) <= 1
        assert first.population_counts[stratum] >= 3


def test_pool_excludes_null_scores_and_ties():
    scored_ideas(8)
    Idea.objects.create(name="Bez wyniku", content="Opis")
    items = list(Idea.objects.filter(innovation_score__isnull=False).values(
        "id", "name", "content", "innovation_score"
    ))
    pools = service.candidate_pools(items)
    assert sum(map(len, pools.values())) == 24
    with pytest.raises(ValueError, match="Za mało par"):
        service.create_study(sample_per_stratum=60, repeat_count=0)
    assert not OverallOrderStudy.objects.exists()


@pytest.mark.parametrize(("sample", "repeats", "message"), [
    (0, 0, "od 1 do 60"), (61, 0, "od 1 do 60"),
    (1, 4, "przekracza"), (1, 21, "przekracza"),
])
def test_hard_limits(sample, repeats, message):
    with pytest.raises(ValueError, match=message):
        service.create_study(sample_per_stratum=sample, repeat_count=repeats)


def test_orient_pairs_swaps_and_empty_repeats():
    scored_ideas()
    items = list(Idea.objects.values("id", "name", "content", "innovation_score"))
    pairs = service.orient_pairs([(items[0], items[6]), (items[6], items[0])],
                                 "far", random.Random(7))
    assert len(pairs) == 2
    assert {p["left_score"] > p["right_score"] for p in pairs} == {True, False}
    study = service.create_study(sample_per_stratum=1, repeat_count=0)
    assert study.pairs.count() == 3


@pytest.mark.parametrize(("status", "payload", "error"), [
    ("completed", {"outcome": "A", "rationale": "A ma większy potencjał"}, None),
    ("incomplete", {"outcome": "A", "rationale": "Opis"}, "nie ukończył"),
    ("completed", [], "Niepoprawna"),
    ("completed", {"outcome": "wrong", "rationale": "Opis"}, "Niepoprawna"),
    ("completed", {"outcome": "B", "rationale": 4}, "Niepoprawna"),
    ("completed", {"outcome": "tie", "rationale": " "}, "Niepoprawna"),
])
def test_llm_response_is_blinded(status, payload, error):
    study = make_study()
    pair = study.pairs.first()
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        status=status, output_text=json.dumps(payload)
    )
    if error:
        with pytest.raises(ValueError, match=error):
            service.compare_pair(study, pair, client)
    else:
        assert service.compare_pair(study, pair, client) == payload
    request = client.responses.create.call_args.kwargs
    assert "score" not in request["input"].lower()
    assert request["text"]["format"]["strict"]
    assert "30%" in request["instructions"]


def test_missing_api_key_and_configured_client(settings):
    study = make_study()
    settings.OPENAI_API_KEY = ""
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        service.compare_pair(study, study.pairs.first())
    settings.OPENAI_API_KEY = "test-only"
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        status="completed", output_text=json.dumps({"outcome": "tie", "rationale": "Podobne"})
    )
    with patch.object(service, "OpenAI", return_value=client) as constructor:
        assert service.compare_pair(study, study.pairs.first())["outcome"] == "tie"
    constructor.assert_called_once_with(api_key="test-only", timeout=90, max_retries=0)


@pytest.mark.parametrize(("left", "right", "outcome", "expected"), [
    (8, 4, "", "pending"), (8, 4, "unclear", "unclear"),
    (8, 4, "tie", "tie"), (8, 4, "A", "concordant"),
    (8, 4, "B", "discordant"), (4, 8, "B", "concordant"),
    (4, 8, "A", "discordant"),
])
def test_classify_pair(left, right, outcome, expected):
    pair = SimpleNamespace(left_score=left, right_score=right, outcome=outcome)
    assert service.classify_pair(pair) == expected


@pytest.mark.parametrize(("original", "repeat", "expected"), [
    ("A", "B", "stable"), ("B", "A", "stable"),
    ("tie", "tie", "stable"), ("unclear", "unclear", "stable"),
    ("A", "A", "unstable"), ("", "B", "pending"), ("A", "", "pending"),
])
def test_repeat_agreement(original, repeat, expected):
    pair = SimpleNamespace(outcome=repeat, repeat_of=SimpleNamespace(outcome=original))
    assert service.repeat_agreement(pair) == expected


def test_checkpoint_summary_and_pause():
    study = make_study()
    study.error = "Poprzedni timeout"
    study.save(update_fields=["error"])
    first = study.pairs.first()
    with patch("core.tasks.compare_overall_pair", return_value={
        "outcome": "A", "rationale": "Pierwszy ma silniejszy potencjał",
    }), patch.object(run_overall_order_study, "delay") as delay:
        run_overall_order_study(study.pk)
        delay.assert_called_once_with(study.pk)
        first.refresh_from_db()
        assert first.completed_at
        assert first.outcome == "A"
        assert OverallOrderStudy.objects.get(pk=study.pk).error == ""
        assert service.study_summary(study)["strata"][first.stratum]
        OverallOrderStudy.objects.filter(pk=study.pk).update(status="paused")
        run_overall_order_study(study.pk)
        assert delay.call_count == 1


def test_job_completes_and_failure_can_be_resumed():
    study = make_study()
    study.pairs.update(outcome="tie")
    run_overall_order_study(study.pk)
    study.refresh_from_db()
    assert study.status == "completed"
    assert service.study_summary(study)["repeats"] == {"stable": 2}
    study.status = "pending"
    study.save(update_fields=["status"])
    pair = study.pairs.first()
    pair.outcome = ""
    pair.save(update_fields=["outcome"])
    with patch("core.tasks.compare_overall_pair", side_effect=RuntimeError("API down")), \
            pytest.raises(RuntimeError, match="API down"):
        run_overall_order_study(study.pk)
    study.refresh_from_db()
    assert study.status == "failed"
    assert study.error == "API down"
    with patch.object(run_overall_order_study, "delay"):
        call_command("study_overall_order", resume=study.pk)
    study.refresh_from_db()
    assert study.status == "pending"
    assert study.error == ""


def test_job_respects_pause_during_api_request():
    study = make_study()

    def pause_while_comparing(*args):
        OverallOrderStudy.objects.filter(pk=study.pk).update(status="paused")
        return {"outcome": "unclear", "rationale": "Za mało danych"}

    with patch("core.tasks.compare_overall_pair", side_effect=pause_while_comparing), \
            patch.object(run_overall_order_study, "delay") as delay:
        run_overall_order_study(study.pk)
        delay.assert_not_called()
    assert OverallOrderStudy.objects.get(pk=study.pk).status == "paused"


@pytest.mark.parametrize("error", [
    APITimeoutError(httpx.Request("POST", "https://api.openai.com/v1/responses")),
    SoftTimeLimitExceeded(),
])
def test_timeout_retries_same_pair_without_limit(error):
    study = make_study()
    first = study.pairs.first()
    with (
        patch("core.tasks.compare_overall_pair", side_effect=error),
        patch.object(run_overall_order_study, "retry", side_effect=Retry()) as retry,
        pytest.raises(Retry),
    ):
        run_overall_order_study(study.pk)
    study.refresh_from_db()
    assert study.status == "pending"
    assert "ponowienie za 10 s" in study.error
    assert first.outcome == ""
    assert retry.call_args.kwargs["countdown"] == 10
    assert run_overall_order_study.max_retries is None


def test_retry_timeout_backoff_cap_and_pause():
    study = make_study()
    study.status = "running"
    study.save(update_fields=["status"])
    task = SimpleNamespace(
        request=SimpleNamespace(retries=9), retry=Mock(side_effect=Retry())
    )
    with pytest.raises(Retry):
        retry_study_timeout(task, OverallOrderStudy, study.pk, RuntimeError("timeout"))
    assert task.retry.call_args.kwargs["countdown"] == 300
    study.status = "paused"
    study.save(update_fields=["status"])
    task.retry.reset_mock()
    retry_study_timeout(task, OverallOrderStudy, study.pk, RuntimeError("timeout"))
    task.retry.assert_not_called()


def test_command_start_status_pause_resume_and_errors():
    scored_ideas()
    output = StringIO()
    with patch.object(run_overall_order_study, "delay") as delay:
        call_command("study_overall_order", sample_per_stratum=2, repeat_count=2,
                     stdout=output)
        study = OverallOrderStudy.objects.get()
        assert "8 porównań" in output.getvalue()
        delay.assert_called_once_with(study.pk)
        with pytest.raises(CommandError, match="już działa"):
            call_command("study_overall_order", sample_per_stratum=1, repeat_count=0)
        with pytest.raises(CommandError, match="jedną akcję"):
            call_command("study_overall_order", status=study.pk, pause=study.pk)
        with pytest.raises(CommandError, match="Nie znaleziono"):
            call_command("study_overall_order", status=99999)
        output = StringIO()
        call_command("study_overall_order", status=study.pk, stdout=output)
        assert json.loads(output.getvalue())["total"] == 8
        call_command("study_overall_order", pause=study.pk)
        with pytest.raises(CommandError, match="nieaktywnego"):
            call_command("study_overall_order", pause=study.pk)
        call_command("study_overall_order", resume=study.pk)
        assert delay.call_count == 2
        with pytest.raises(CommandError, match="wstrzymane"):
            call_command("study_overall_order", resume=study.pk)


def test_command_rejects_invalid_sample():
    with pytest.raises(CommandError, match="od 1 do 60"):
        call_command("study_overall_order", sample_per_stratum=0)

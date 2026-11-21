"""Testy kalibracji ocen przechowywanej w bazie danych."""

import json

import pytest
from django.core.exceptions import ImproperlyConfigured

from core.models import ScoringCalibration, ScoringCalibrationExample
from core.services import scoring_calibration
from core.services.scoring_calibration import calibration_prompt


def create_example(calibration, criterion="novelty", score=50):
    return ScoringCalibrationExample.objects.create(
        calibration=calibration,
        criterion=criterion,
        title="Projekt",
        description="Opis",
        score=score,
        rationale="Powód",
    )


@pytest.fixture
def calibration():
    ScoringCalibration.objects.all().delete()
    return ScoringCalibration.objects.create(enabled=False)


@pytest.mark.django_db
def test_disabled_calibration_does_not_change_assessment_prompt(calibration):
    create_example(calibration)
    assert calibration_prompt() == ""


@pytest.mark.django_db
def test_enabled_calibration_is_loaded_from_database_without_restart(calibration):
    calibration.enabled = True
    calibration.save()
    for criterion in ("novelty", "value", "replicability", "impact"):
        create_example(calibration, criterion=criterion)

    first = calibration_prompt()
    example = calibration.examples.get(criterion="novelty")
    example.score = 90
    example.save()
    second = calibration_prompt()

    data = json.loads(second.split("Przykłady kalibracyjne (JSON):\n")[1])
    assert set(data) == {"novelty", "value", "replicability", "impact"}
    assert first != second
    assert data["novelty"][0]["score"] == 90


@pytest.mark.django_db
def test_enabled_calibration_requires_example_for_every_criterion(calibration):
    calibration.enabled = True
    calibration.save()
    create_example(calibration)

    with pytest.raises(ImproperlyConfigured, match="Każde kryterium"):
        calibration_prompt()


@pytest.mark.django_db
@pytest.mark.parametrize("score", [101])
def test_enabled_calibration_rejects_invalid_example_score(calibration, score):
    calibration.enabled = True
    calibration.save()
    for criterion in ("novelty", "value", "replicability", "impact"):
        create_example(calibration, criterion=criterion)
    example = calibration.examples.get(criterion="impact")
    ScoringCalibrationExample.objects.filter(pk=example.pk).update(score=score)

    with pytest.raises(ImproperlyConfigured, match="liczbą całkowitą"):
        calibration_prompt()


def test_calibration_example_validator_rejects_missing_or_empty_fields():
    with pytest.raises(ValueError, match="wymaga pól"):
        scoring_calibration._validate_example({})
    with pytest.raises(ValueError, match="niepustym tekstem"):
        scoring_calibration._validate_example(
            {"title": "", "description": "Opis", "score": 50, "rationale": "Powód"}
        )

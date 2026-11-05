"""Experiment event payloads and the catalog (slice 6, plan XP-A task 2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.events.catalog import default_catalog
from factory.hypotheses.design import design_version
from factory.model.experiments import (
    AUTOMATIC_DEVIATIONS,
    ExperimentAmended,
    ExperimentDesigned,
    ExperimentDeviationRecorded,
    ExperimentFrozen,
    ExperimentUnlocked,
)
from factory.modules.contract import PolicyKind
from tests.experiment_helpers import design

EXP = "exp_01JZ9Q3K5M7N8P0R2S4T6V8W0X"
OTHER_EXP = "exp_01JZ9Q3K5M7N8P0R2S4T6V8W0Y"


def test_design_event_roundtrip() -> None:
    d = design()
    payload = ExperimentDesigned(experiment_id=EXP, design=d, e_version=design_version(d))
    again = ExperimentDesigned.model_validate_json(payload.model_dump_json())
    assert again == payload and again.design == d
    assert default_catalog().get("experiment.designed").payload is ExperimentDesigned
    with pytest.raises(ValidationError):
        ExperimentDesigned(experiment_id=EXP, design=d, e_version=design_version(d), supersedes=EXP)
    with pytest.raises(ValidationError):
        ExperimentDesigned(experiment_id=EXP, design=d, e_version="E@xyz")


def test_amended_frozen_unlocked_roundtrip() -> None:
    d = design()
    version = design_version(d)
    amended = ExperimentAmended(
        experiment_id=EXP, design=d, e_version=version, reason="more seeds", semantic=False
    )
    frozen = ExperimentFrozen(
        experiment_id=EXP,
        e_version=version,
        policy=PolicyKind.HUMAN,
        autonomy="human",
        test_access_limit=1,
    )
    unlocked = ExperimentUnlocked(
        experiment_id=EXP,
        e_version=version,
        nonce="0123456789abcdef0123456789abcdef",
        policy=PolicyKind.HUMAN,
        autonomy="human",
    )
    for payload in (amended, frozen, unlocked):
        assert type(payload).model_validate_json(payload.model_dump_json()) == payload
    with pytest.raises(ValidationError):  # a short nonce is not one
        ExperimentUnlocked(
            experiment_id=EXP,
            e_version=version,
            nonce="abc",
            policy=PolicyKind.HUMAN,
            autonomy="human",
        )
    with pytest.raises(ValidationError):  # the access limit is at least one
        ExperimentFrozen(
            experiment_id=EXP,
            e_version=version,
            policy=PolicyKind.HUMAN,
            autonomy="human",
            test_access_limit=0,
        )


def test_deviation_kinds() -> None:
    ExperimentDeviationRecorded(
        experiment_id=EXP, kind="test-reuse", text="again", semantic=False, after_unlock=True
    )
    with pytest.raises(ValidationError):
        ExperimentDeviationRecorded(
            experiment_id=EXP, kind="whim", text="again", semantic=False, after_unlock=True
        )
    with pytest.raises(ValidationError):
        ExperimentDeviationRecorded(
            experiment_id=EXP, kind="other", text="  ", semantic=False, after_unlock=False
        )
    assert {"budget-overrun", "test-reuse"} == AUTOMATIC_DEVIATIONS


def test_input_models_carry_no_computed_field() -> None:
    body = design().model_dump(mode="json")
    for computed in ("experiment_id", "e_version", "state", "nonce", "config"):
        with pytest.raises(ValidationError):
            type(design()).model_validate({**body, computed: "x"})

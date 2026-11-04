"""Stage on events, full-text decision anchors and the optional full-text protocol plan.

Existing events and existing protocol versions must be unchanged by this slice: every new field
has a default, and a protocol without a full-text plan hashes exactly as before.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from factory.model.chase import SampleExtended
from factory.model.protocol import (
    ProtocolSpec,
    ScreeningPlan,
    ScreeningStage,
    protocol_version,
    section_digest,
)
from factory.model.screening import (
    AuditLabelled,
    AuditSampled,
    CalibrationDrawn,
    CalibrationLabelled,
    DecisionRecorded,
    DisagreementResolved,
    PassJoined,
    PassOpened,
    ScreeningItem,
)
from factory.services.protocol_rules import other_changes
from tests.helpers import pilot_protocol_spec

TA = ScreeningStage.TITLE_ABSTRACT
FT = ScreeningStage.FULL_TEXT
EITHER = ScreeningStage.EITHER
DECISION = "dec_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
AUDIT = "aud_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
TASK = "tsk_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
CONVERSION = "cnv_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
WID = "rf:w1-0000aaaa"
PILOT_VERSION = "P@1e7c316e"
"""The version of `pilot_protocol_spec("Q@aaaaaaaa", "prb_1")`, computed before this slice."""


def _decision(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "decision_id": DECISION,
        "work_id": "rf:1",
        "pass_label": "A",
        "phase": "screening",
        "stage": "title-abstract",
        "verdict": "exclude",
        "criterion": "P@1a2b3c4d:EX03",
        "quote": "q",
        "rationale": "r",
        "protocol_id": "P@1a2b3c4d",
        "task_id": TASK,
        "supersedes": None,
    }
    base.update(overrides)
    return base


def _plan(**overrides: Any) -> ScreeningPlan:
    base: dict[str, Any] = {
        "passes": 1,
        "dual_sample": 0.5,
        "reviewers": [{"role": "reviewer-of-record", "actor": "obd", "kind": "human"}],
    }
    base.update(overrides)
    return ScreeningPlan.model_validate(base)


# --- Old events default to title-abstract ---


def test_old_events_default_to_title_abstract() -> None:
    cases: list[tuple[type[Any], dict[str, Any]]] = [
        (
            PassOpened,
            {
                "pass_label": "A",
                "framing": "inclusion",
                "criterion_order": "protocol",
                "random_seed": 7,
                "sample": None,
            },
        ),
        (PassJoined, {"pass_label": "A", "session": "s", "model": "m"}),
        (
            SampleExtended,
            {"pass_label": "B", "random_seed": 7, "considered": [WID], "added": [WID]},
        ),
        (CalibrationDrawn, {"work_ids": ["rf:1"], "random_seed": 7}),
        (
            CalibrationLabelled,
            {"work_id": "rf:1", "verdict": "include", "channel": "cli"},
        ),
        (
            DisagreementResolved,
            {"work_id": "rf:1", "verdict": "include", "reason": "why", "channel": "mcp"},
        ),
        (
            AuditSampled,
            {
                "audit_id": AUDIT,
                "work_ids": ["rf:1"],
                "random_seed": 7,
                "population": 1,
                "exclusions": 0,
                "inclusions": 1,
            },
        ),
        (
            AuditLabelled,
            {"audit_id": AUDIT, "work_id": "rf:1", "verdict": "include", "channel": "cli"},
        ),
    ]
    for model, payload in cases:
        parsed = model.model_validate(payload)
        assert parsed.stage == TA, model.__name__
        assert model.model_validate({**payload, "stage": "full-text"}).stage == FT


def test_screening_item_anchor_defaults_to_none() -> None:
    item = ScreeningItem(work_id="rf:1", verdict="include", quote="q")
    assert item.anchor is None


# --- Stage is a run stage, never EITHER ---


@pytest.mark.parametrize(
    "model,payload",
    [
        (
            PassOpened,
            {
                "pass_label": "A",
                "framing": "inclusion",
                "criterion_order": "protocol",
                "random_seed": 7,
                "sample": None,
            },
        ),
        (PassJoined, {"pass_label": "A", "session": "s", "model": "m"}),
        (SampleExtended, {"pass_label": "B", "random_seed": 7, "considered": [], "added": []}),
        (CalibrationDrawn, {"work_ids": ["rf:1"], "random_seed": 7}),
        (CalibrationLabelled, {"work_id": "rf:1", "verdict": "include", "channel": "cli"}),
        (
            DisagreementResolved,
            {"work_id": "rf:1", "verdict": "include", "reason": "x", "channel": "mcp"},
        ),
        (
            AuditSampled,
            {
                "audit_id": AUDIT,
                "work_ids": [],
                "random_seed": 7,
                "population": 0,
                "exclusions": 0,
                "inclusions": 0,
            },
        ),
        (
            AuditLabelled,
            {"audit_id": AUDIT, "work_id": "rf:1", "verdict": "include", "channel": "cli"},
        ),
    ],
)
def test_either_is_not_a_run_stage(model: type[Any], payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload, "stage": "either"})
    with pytest.raises(ValidationError):
        model.model_validate({**payload, "stage": EITHER})


def test_decision_stage_rejects_either() -> None:
    with pytest.raises(ValidationError):
        DecisionRecorded.model_validate(_decision(stage="either"))


# --- Decision anchors ---


def test_full_text_decision_needs_anchor_and_conversion() -> None:
    payload = _decision(stage="full-text", criterion="P@1a2b3c4d:EX03")
    with pytest.raises(ValidationError):
        DecisionRecorded.model_validate(payload)
    with pytest.raises(ValidationError):
        DecisionRecorded.model_validate({**payload, "anchor": "s1.p2"})
    with pytest.raises(ValidationError):
        DecisionRecorded.model_validate({**payload, "conversion_id": CONVERSION})
    ok = DecisionRecorded.model_validate(
        {**payload, "anchor": "s1.p2", "conversion_id": CONVERSION}
    )
    assert (ok.anchor, ok.conversion_id) == ("s1.p2", CONVERSION)


@pytest.mark.parametrize("anchor", ["s1.p2", "p3", "t2", "t2.r5.c3", "f1.cap", "e4", "s2.1"])
def test_full_text_anchor_accepts_document_and_cell_forms(anchor: str) -> None:
    payload = _decision(stage="full-text", anchor=anchor, conversion_id=CONVERSION)
    assert DecisionRecorded.model_validate(payload).anchor == anchor


@pytest.mark.parametrize("anchor", ["", "x1", "s1.p2.q3", "t2.r5", "t2.r5.c3.x", "S1", "s1 "])
def test_malformed_anchor_is_rejected(anchor: str) -> None:
    payload = _decision(stage="full-text", anchor=anchor, conversion_id=CONVERSION)
    with pytest.raises(ValidationError):
        DecisionRecorded.model_validate(payload)
    with pytest.raises(ValidationError):
        ScreeningItem(work_id="rf:1", verdict="include", quote="q", anchor=anchor)


def test_malformed_conversion_id_is_rejected() -> None:
    payload = _decision(stage="full-text", anchor="s1.p2", conversion_id="cnv_bad")
    with pytest.raises(ValidationError):
        DecisionRecorded.model_validate(payload)


def test_title_abstract_decision_forbids_them() -> None:
    with pytest.raises(ValidationError):
        DecisionRecorded.model_validate(_decision(anchor="s1.p2"))
    with pytest.raises(ValidationError):
        DecisionRecorded.model_validate(_decision(conversion_id=CONVERSION))
    with pytest.raises(ValidationError):
        DecisionRecorded.model_validate(_decision(anchor="s1.p2", conversion_id=CONVERSION))
    assert DecisionRecorded.model_validate(_decision()).anchor is None


# --- The protocol's full-text plan ---


def test_protocol_version_unchanged_when_full_text_plan_absent() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    assert spec.full_text_screening is None
    assert protocol_version(spec) == PILOT_VERSION


def test_protocol_version_changes_when_plan_present() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    with_plan = spec.model_copy(update={"full_text_screening": _plan()})
    assert protocol_version(with_plan) != PILOT_VERSION
    other = spec.model_copy(update={"full_text_screening": _plan(passes=2)})
    assert protocol_version(other) != protocol_version(with_plan)


def test_full_text_plan_validates_like_screening_plan() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1").model_dump(mode="json")
    spec["full_text_screening"] = {
        "passes": 1,
        "dual_sample": 0.5,
        "reviewers": [{"role": "reviewer-of-record", "actor": "obd", "kind": "human"}],
    }
    assert ProtocolSpec.model_validate(spec).full_text_screening is not None
    for bad in (0, 1.5):
        spec["full_text_screening"]["dual_sample"] = bad
        with pytest.raises(ValidationError):
            ProtocolSpec.model_validate(spec)


def test_amendment_reports_full_text_screening_in_other_changes() -> None:
    old = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    new = old.model_copy(update={"full_text_screening": _plan()})
    assert "full_text_screening" in other_changes(old, new)
    assert "full_text_screening" not in other_changes(old, old)
    assert section_digest(old, "full_text_screening") != section_digest(new, "full_text_screening")

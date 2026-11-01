from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.events.catalog import default_catalog
from factory.model.protocol import ScreeningStage
from factory.model.screening import (
    AUDIT_ID_RE,
    DECISION_ID_RE,
    AuditLabelled,
    AuditSampled,
    CalibrationDrawn,
    CalibrationLabelled,
    Channel,
    DecisionRecorded,
    DisagreementResolved,
    Framing,
    PassJoined,
    PassLabel,
    PassOpened,
    ScreeningItem,
    ScreeningPhase,
    Verdict,
)

DECISION = "dec_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
AUDIT = "aud_01HZX3K4M5N6P7Q8R9S0TVWXYZ"


def test_promotes() -> None:
    assert Verdict.INCLUDE.promotes is True
    assert Verdict.CANNOT_ASSESS.promotes is True
    assert Verdict.EXCLUDE.promotes is False
    assert Verdict.UNSURE.promotes is False


def test_exclude_item_needs_criterion_and_rationale() -> None:
    with pytest.raises(ValidationError):
        ScreeningItem(
            work_id="rf:1", verdict=Verdict.EXCLUDE, criterion=None, quote="q", rationale="r"
        )
    with pytest.raises(ValidationError):
        ScreeningItem(
            work_id="rf:1", verdict=Verdict.EXCLUDE, criterion="EX03", quote="q", rationale=""
        )
    item = ScreeningItem(
        work_id="rf:1", verdict=Verdict.EXCLUDE, criterion="EX03", quote="q", rationale="r"
    )
    assert item.criterion == "EX03"


def test_cannot_assess_needs_criterion() -> None:
    with pytest.raises(ValidationError):
        ScreeningItem(work_id="rf:1", verdict=Verdict.CANNOT_ASSESS, criterion=None, quote="q")
    item = ScreeningItem(work_id="rf:1", verdict=Verdict.CANNOT_ASSESS, criterion="IN01", quote="q")
    assert item.criterion == "IN01"


def test_unsure_needs_rationale() -> None:
    with pytest.raises(ValidationError):
        ScreeningItem(work_id="rf:1", verdict=Verdict.UNSURE, quote="q", rationale="")
    item = ScreeningItem(work_id="rf:1", verdict=Verdict.UNSURE, quote="q", rationale="ambiguous")
    assert item.rationale == "ambiguous"


def test_include_cannot_carry_exclusion_criterion() -> None:
    with pytest.raises(ValidationError):
        ScreeningItem(work_id="rf:1", verdict=Verdict.INCLUDE, criterion="EX03", quote="q")
    item = ScreeningItem(work_id="rf:1", verdict=Verdict.INCLUDE, criterion="IN02", quote="q")
    assert item.criterion == "IN02"


def test_decision_criterion_is_version_qualified() -> None:
    base = {
        "decision_id": DECISION,
        "work_id": "rf:1",
        "pass_label": PassLabel.A,
        "phase": ScreeningPhase.SCREENING,
        "stage": ScreeningStage.TITLE_ABSTRACT,
        "verdict": Verdict.EXCLUDE,
        "quote": "q",
        "rationale": "r",
        "protocol_id": "P@1a2b3c4d",
        "task_id": "tsk_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
        "supersedes": None,
    }
    with pytest.raises(ValidationError):
        DecisionRecorded(**base, criterion="EX03")
    event = DecisionRecorded(**base, criterion="P@1a2b3c4d:EX03")
    assert event.criterion == "P@1a2b3c4d:EX03"


def test_decision_id_patterns() -> None:
    import re

    assert re.fullmatch(DECISION_ID_RE, DECISION)
    assert not re.fullmatch(DECISION_ID_RE, AUDIT)
    assert re.fullmatch(AUDIT_ID_RE, AUDIT)


def test_pass_and_channel_values() -> None:
    assert PassLabel("A") is PassLabel.A
    assert Framing.INCLUSION.value == "inclusion"
    assert Framing.EXCLUSION.value == "exclusion"
    assert ScreeningPhase.CALIBRATION.value == "calibration"
    assert Channel.MCP.value == "mcp"


def test_payloads_construct() -> None:
    PassOpened(
        pass_label=PassLabel.B,
        framing=Framing.EXCLUSION,
        criterion_order="reversed",
        random_seed=7,
        sample=None,
    )
    PassJoined(pass_label=PassLabel.A, session="sess-1", model="model-a")
    CalibrationDrawn(protocol_id=None, work_ids=("rf:1",), random_seed=7)
    CalibrationLabelled(work_id="rf:1", verdict="include", criterion=None, channel=Channel.CLI)
    DisagreementResolved(
        work_id="rf:1",
        verdict="exclude",
        criterion="P@1a2b3c4d:EX01",
        reason="off-topic",
        channel=Channel.MCP,
    )
    AuditSampled(
        audit_id=AUDIT,
        work_ids=("rf:1",),
        random_seed=7,
        population=10,
        exclusions=4,
        inclusions=6,
    )
    AuditLabelled(
        audit_id=AUDIT, work_id="rf:1", verdict="include", criterion=None, channel=Channel.CLI
    )


def test_payloads_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PassJoined(pass_label=PassLabel.A, session="s", model="m", extra="x")  # type: ignore[call-arg]


def test_payloads_registered() -> None:
    names = set(default_catalog().names())
    expected = {
        "screening.pass_opened",
        "screening.pass_joined",
        "screening.decision_recorded",
        "calibration.drawn",
        "calibration.labelled",
        "screening.disagreement_resolved",
        "audit.sampled",
        "audit.labelled",
    }
    assert expected <= names

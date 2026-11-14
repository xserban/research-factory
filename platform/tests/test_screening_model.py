from __future__ import annotations

import re

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
    with pytest.raises(ValidationError):
        ScreeningItem(
            work_id="rf:1", verdict=Verdict.EXCLUDE, criterion="EX03", quote="q", rationale="  "
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
    with pytest.raises(ValidationError):
        ScreeningItem(work_id="rf:1", verdict=Verdict.UNSURE, quote="q", rationale="  \t ")
    item = ScreeningItem(work_id="rf:1", verdict=Verdict.UNSURE, quote="q", rationale="ambiguous")
    assert item.rationale == "ambiguous"


def test_blank_quote_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ScreeningItem(work_id="rf:1", verdict=Verdict.INCLUDE, quote="   ")


def test_include_cannot_carry_exclusion_criterion() -> None:
    with pytest.raises(ValidationError):
        ScreeningItem(work_id="rf:1", verdict=Verdict.INCLUDE, criterion="EX03", quote="q")
    item = ScreeningItem(work_id="rf:1", verdict=Verdict.INCLUDE, criterion="IN02", quote="q")
    assert item.criterion == "IN02"


def _decision(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "decision_id": DECISION,
        "work_id": "rf:1",
        "pass_label": PassLabel.A,
        "phase": ScreeningPhase.SCREENING,
        "stage": ScreeningStage.TITLE_ABSTRACT,
        "verdict": Verdict.EXCLUDE,
        "criterion": "P@1a2b3c4d:EX03",
        "quote": "q",
        "rationale": "r",
        "protocol_id": "P@1a2b3c4d",
        "task_id": "tsk_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
        "supersedes": None,
    }
    base.update(overrides)
    return base


def test_decision_criterion_is_version_qualified() -> None:
    with pytest.raises(ValidationError):
        DecisionRecorded(**_decision(criterion="EX03"))
    event = DecisionRecorded(**_decision())
    assert event.criterion == "P@1a2b3c4d:EX03"


def test_decision_exclude_needs_criterion() -> None:
    with pytest.raises(ValidationError):
        DecisionRecorded(**_decision(criterion=None))


def test_calibration_label_rejects_unnamed_exclusion_and_exclusion_include() -> None:
    with pytest.raises(ValidationError):
        CalibrationLabelled(work_id="rf:1", verdict="exclude", criterion=None, channel=Channel.CLI)
    with pytest.raises(ValidationError):
        CalibrationLabelled(
            work_id="rf:1", verdict="include", criterion="P@1a2b3c4d:EX01", channel=Channel.CLI
        )


def test_disagreement_resolution_rejects_unnamed_exclusion_and_exclusion_include() -> None:
    with pytest.raises(ValidationError):
        DisagreementResolved(
            work_id="rf:1", verdict="exclude", criterion=None, reason="r", channel=Channel.MCP
        )
    with pytest.raises(ValidationError):
        DisagreementResolved(
            work_id="rf:1",
            verdict="include",
            criterion="P@1a2b3c4d:EX01",
            reason="r",
            channel=Channel.MCP,
        )
    with pytest.raises(ValidationError):
        DisagreementResolved(
            work_id="rf:1",
            verdict="exclude",
            criterion="P@1a2b3c4d:EX01",
            reason="  ",
            channel=Channel.MCP,
        )


def test_audit_label_rejects_unnamed_exclusion_and_exclusion_include() -> None:
    with pytest.raises(ValidationError):
        AuditLabelled(
            audit_id=AUDIT, work_id="rf:1", verdict="exclude", criterion=None, channel=Channel.CLI
        )
    with pytest.raises(ValidationError):
        AuditLabelled(
            audit_id=AUDIT,
            work_id="rf:1",
            verdict="include",
            criterion="P@1a2b3c4d:EX01",
            channel=Channel.CLI,
        )


def test_decision_id_patterns() -> None:
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
    opened = PassOpened(
        pass_label=PassLabel.B,
        framing=Framing.EXCLUSION,
        criterion_order="reversed",
        random_seed=7,
        sample=None,
    )
    joined = PassJoined(pass_label=PassLabel.A, session="sess-1", model="model-a")
    drawn = CalibrationDrawn(protocol_id=None, work_ids=("rf:1",), random_seed=7)
    labelled = CalibrationLabelled(
        work_id="rf:1", verdict="exclude", criterion="P@1a2b3c4d:EX01", channel=Channel.CLI
    )
    resolved = DisagreementResolved(
        work_id="rf:1",
        verdict="exclude",
        criterion="P@1a2b3c4d:EX01",
        reason="off-topic",
        channel=Channel.MCP,
    )
    sampled = AuditSampled(
        audit_id=AUDIT,
        work_ids=("rf:1",),
        random_seed=7,
        population=10,
        exclusions=0,
        inclusions=1,
    )
    audit_labelled = AuditLabelled(
        audit_id=AUDIT, work_id="rf:1", verdict="include", criterion=None, channel=Channel.CLI
    )
    assert (opened.pass_label, opened.criterion_order) == (PassLabel.B, "reversed")
    assert (joined.session, joined.model) == ("sess-1", "model-a")
    assert drawn.work_ids == ("rf:1",) and drawn.protocol_id is None
    assert (labelled.verdict, labelled.channel) == ("exclude", Channel.CLI)
    assert (resolved.reason, resolved.channel) == ("off-topic", Channel.MCP)
    assert (sampled.population, sampled.exclusions + sampled.inclusions) == (10, 1)
    assert (audit_labelled.verdict, audit_labelled.criterion) == ("include", None)


def test_payloads_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PassJoined(pass_label=PassLabel.A, session="s", model="m", extra="x")  # type: ignore[call-arg]


def test_payloads_registered() -> None:
    from factory.model import screening

    expected = {
        "screening.pass_opened": screening.PassOpened,
        "screening.pass_joined": screening.PassJoined,
        "screening.decision_recorded": screening.DecisionRecorded,
        "calibration.drawn": screening.CalibrationDrawn,
        "calibration.labelled": screening.CalibrationLabelled,
        "screening.disagreement_resolved": screening.DisagreementResolved,
        "audit.sampled": screening.AuditSampled,
        "audit.labelled": screening.AuditLabelled,
    }
    catalog = default_catalog()
    for name, payload in expected.items():
        assert name in catalog
        assert catalog.get(name).payload is payload


def test_cell_anchor_with_trailing_newline_rejected() -> None:
    """The anchor form is a full match: a trailing newline is not a cell anchor (Task 1 minor)."""
    item = dict(work_id="w", verdict="include", quote="q", rationale="r")
    ScreeningItem.model_validate({**item, "anchor": "t2.r5.c3"})
    for bad in ("t2.r5.c3\n", "s1.p1\n"):
        with pytest.raises(ValidationError):
            ScreeningItem.model_validate({**item, "anchor": bad})


def test_score_is_one_to_ten_and_absent_by_default() -> None:
    item = ScreeningItem(work_id="rf:1", verdict=Verdict.INCLUDE, quote="q", rationale="", score=10)
    assert item.model_dump(mode="json")["score"] == 10
    for bad in (0, 11, -1):
        with pytest.raises(ValidationError):
            ScreeningItem(work_id="rf:1", verdict=Verdict.INCLUDE, quote="q", score=bad)
    plain = ScreeningItem(work_id="rf:1", verdict=Verdict.INCLUDE, quote="q")
    assert "score" not in plain.model_dump(mode="json")


def test_decision_without_a_score_dumps_as_before() -> None:
    plain = DecisionRecorded(**_decision())
    assert plain.score is None and "score" not in plain.model_dump(mode="json")
    scored = DecisionRecorded(**_decision(score=7))
    assert scored.model_dump(mode="json")["score"] == 7
    with pytest.raises(ValidationError):
        DecisionRecorded(**_decision(score=11))


def _sampled_body(**over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "audit_id": AUDIT,
        "work_ids": ("rf:1", "rf:2"),
        "random_seed": 1,
        "population": 5,
        "exclusions": 1,
        "inclusions": 1,
    }
    body.update(over)
    return body


def test_audit_sampled_counts_must_match_the_sample() -> None:
    AuditSampled(**_sampled_body())  # type: ignore[arg-type]
    for over in (
        {"exclusions": 2},  # counts do not add up to the sample
        {"population": 1},  # sample larger than the population
        {"work_ids": ("rf:1", "rf:1")},  # a work sampled twice
    ):
        with pytest.raises(ValidationError):
            AuditSampled(**_sampled_body(**over))  # type: ignore[arg-type]

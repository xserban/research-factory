"""Projection of the stage of a screening run: title/abstract and full text keep separate state.

The slice-1 log carries no `stage` in its payloads; it must project as `title-abstract` rows with
the same values as before. Events are recorded directly, as the index tests do; the services are
not needed to show what the projector writes.
"""

from typing import Any

from sqlalchemy import text

from factory.canonical import population_digest
from factory.events.envelope import Event
from factory.model.protocol import ScreeningStage
from factory.model.screening import (
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
    ScreeningPhase,
    Verdict,
)
from factory.services.context import Project
from tests.helpers import SESSION

PROTOCOL = "P@1a2b3c4d"
W1 = "rf:jones2021-sparse-1e2f3a4b"
W2 = "rf:lee2020-linear-2c3d4e5f"
MODEL = "claude-opus-5-5"
STAGE_TA = "title-abstract"
STAGE_KEY = ("stage",)


def _record(
    project: Project, type_: str, payload: Any, *, drop: tuple[str, ...] = (), slice1: bool = False
) -> Event:
    """Record one event. With `slice1`, the payload omits the keys in `drop`, as slice-1 logs did:
    `stage` on passes, joins, calibration and audit events; `anchor` and `conversion_id` on
    decisions (decisions already carried `stage`)."""
    event = project.events.make(type_, payload, project.system_actor())
    if slice1:
        kept = {k: v for k, v in event.payload.items() if k not in drop}
        event = event.model_copy(update={"payload": kept})
    project.record([event])
    return event


def _rows(project: Project, sql: str) -> list[tuple[Any, ...]]:
    with project.index.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql)).all()]


def _decision(
    project: Project,
    work_id: str,
    verdict: Verdict,
    criterion: str | None,
    *,
    stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT,
    supersedes: str | None = None,
    anchor: str | None = None,
    conversion_id: str | None = None,
    slice1: bool = False,
) -> tuple[str, Event]:
    decision_id = project.ids.new("dec")
    payload = DecisionRecorded(
        decision_id=decision_id,
        work_id=work_id,
        pass_label=PassLabel.A,
        phase=ScreeningPhase.SCREENING,
        stage=stage,
        verdict=verdict,
        criterion=criterion,
        quote="Paper",
        rationale="rationale",
        protocol_id=PROTOCOL,
        task_id="tsk_test",
        supersedes=supersedes,
        anchor=anchor,
        conversion_id=conversion_id,
    )
    return decision_id, _record(
        project,
        "screening.decision_recorded",
        payload,
        drop=("anchor", "conversion_id"),
        slice1=slice1,
    )


def _slice1_log(project: Project) -> dict[str, Any]:
    """A slice-1 shaped screening log; returns the ids and event ids the expected rows cite."""
    opened = _record(
        project,
        "screening.pass_opened",
        PassOpened(
            pass_label=PassLabel.A,
            framing=Framing.INCLUSION,
            criterion_order="protocol",
            random_seed=1,
            sample=None,
        ),
        drop=STAGE_KEY,
        slice1=True,
    )
    joined = _record(
        project,
        "screening.pass_joined",
        PassJoined(pass_label=PassLabel.A, session=SESSION, model=MODEL),
        drop=STAGE_KEY,
        slice1=True,
    )
    d1, e1 = _decision(project, W1, Verdict.INCLUDE, None, slice1=True)
    d2, e2 = _decision(
        project,
        W1,
        Verdict.EXCLUDE,
        f"{PROTOCOL}:EX01",
        supersedes=d1,
        slice1=True,
    )
    drawn = _record(
        project,
        "calibration.drawn",
        CalibrationDrawn(protocol_id=PROTOCOL, work_ids=(W1, W2), random_seed=11),
        drop=STAGE_KEY,
        slice1=True,
    )
    label = _record(
        project,
        "calibration.labelled",
        CalibrationLabelled(work_id=W1, verdict="include", criterion=None, channel=Channel.CLI),
        drop=STAGE_KEY,
        slice1=True,
    )
    resolved = _record(
        project,
        "screening.disagreement_resolved",
        DisagreementResolved(
            work_id=W2, verdict="include", criterion=None, reason="re-read", channel=Channel.CLI
        ),
        drop=STAGE_KEY,
        slice1=True,
    )
    aud = project.ids.new("aud")
    sampled = _record(
        project,
        "audit.sampled",
        AuditSampled(
            audit_id=aud,
            work_ids=(W1,),
            random_seed=3,
            population=2,
            exclusions=1,
            inclusions=0,
        ),
        drop=STAGE_KEY,
        slice1=True,
    )
    audited = _record(
        project,
        "audit.labelled",
        AuditLabelled(
            audit_id=aud, work_id=W1, verdict="include", criterion=None, channel=Channel.CLI
        ),
        drop=STAGE_KEY,
        slice1=True,
    )
    return {
        "opened": opened,
        "joined": joined,
        "d1": (d1, e1),
        "d2": (d2, e2),
        "drawn": drawn,
        "label": label,
        "resolved": resolved,
        "aud": aud,
        "sampled": sampled,
        "audited": audited,
    }


def test_slice1_log_rebuilds_identically(project: Project) -> None:
    log = _slice1_log(project)
    d1, d2 = log["d1"][0], log["d2"][0]
    aud = log["aud"]
    expected: dict[str, list[tuple[Any, ...]]] = {
        "SELECT pass_label, framing, criterion_order, random_seed, sample FROM passes": [
            ("A", Framing.INCLUSION.value, "protocol", 1, None)
        ],
        "SELECT session, pass_label, model FROM pass_sessions": [(SESSION, "A", MODEL)],
        "SELECT decision_id, work_id, pass_label, phase, verdict, criterion, superseded_by,"
        " supersedes, event_id, anchor, conversion_id FROM decisions ORDER BY event_id": [
            (d1, W1, "A", "screening", "include", None, d2, None, log["d1"][1].id, None, None),
            (
                d2,
                W1,
                "A",
                "screening",
                "exclude",
                f"{PROTOCOL}:EX01",
                None,
                d1,
                log["d2"][1].id,
                None,
                None,
            ),
        ],
        "SELECT work_id, protocol_id_drawn FROM calibration_items": [
            (W1, PROTOCOL),
            (W2, PROTOCOL),
        ],
        "SELECT work_id, verdict, criterion, channel, event_id FROM calibration_labels": [
            (W1, "include", None, "cli", log["label"].id)
        ],
        "SELECT work_id, verdict, criterion, reason, channel, event_id FROM resolutions": [
            (W2, "include", None, "re-read", "cli", log["resolved"].id)
        ],
        "SELECT audit_id, random_seed, population, exclusions, inclusions, population_digest,"
        " pop_exclusions, pop_inclusions FROM audits": [
            (aud, 3, 2, 1, 0, population_digest([]), 0, 0)
        ],
        "SELECT audit_id, work_id, agreed_verdict, agreed_criteria, human_verdict, criterion"
        " FROM audit_items": [(aud, W1, None, None, "include", None)],
    }
    for sql, rows in expected.items():
        assert _rows(project, sql) == rows, sql

    stage_tables = (
        "passes",
        "pass_sessions",
        "decisions",
        "calibration_items",
        "calibration_labels",
        "resolutions",
        "audits",
    )
    for table in stage_tables:
        stages = _rows(project, f"SELECT DISTINCT stage FROM {table}")
        assert stages == [(STAGE_TA,)], table

    before = project.index.state_hash()
    assert project.index.rebuild() == before
    for sql, rows in expected.items():
        assert _rows(project, sql) == rows, sql


def test_two_stages_do_not_collide(project: Project) -> None:
    for stage, framing in (
        (ScreeningStage.TITLE_ABSTRACT, Framing.INCLUSION),
        (ScreeningStage.FULL_TEXT, Framing.EXCLUSION),
    ):
        _record(
            project,
            "screening.pass_opened",
            PassOpened(
                pass_label=PassLabel.A,
                framing=framing,
                criterion_order="protocol",
                random_seed=1,
                sample=None,
                stage=stage,
            ),
        )
        _record(
            project,
            "screening.pass_joined",
            PassJoined(pass_label=PassLabel.A, session=SESSION, model=MODEL, stage=stage),
        )
        _record(
            project,
            "calibration.drawn",
            CalibrationDrawn(protocol_id=PROTOCOL, work_ids=(W1,), random_seed=11, stage=stage),
        )
        _record(
            project,
            "calibration.labelled",
            CalibrationLabelled(
                work_id=W1,
                verdict="include" if stage is ScreeningStage.TITLE_ABSTRACT else "exclude",
                criterion=None if stage is ScreeningStage.TITLE_ABSTRACT else f"{PROTOCOL}:EX01",
                channel=Channel.CLI,
                stage=stage,
            ),
        )
        _record(
            project,
            "screening.disagreement_resolved",
            DisagreementResolved(
                work_id=W1,
                verdict="include" if stage is ScreeningStage.TITLE_ABSTRACT else "exclude",
                criterion=None if stage is ScreeningStage.TITLE_ABSTRACT else f"{PROTOCOL}:EX01",
                reason="re-read",
                channel=Channel.CLI,
                stage=stage,
            ),
        )

    assert _rows(project, "SELECT stage, pass_label, framing FROM passes ORDER BY stage") == [
        ("full-text", "A", Framing.EXCLUSION.value),
        ("title-abstract", "A", Framing.INCLUSION.value),
    ]
    assert _rows(
        project, "SELECT stage, session, pass_label FROM pass_sessions ORDER BY stage"
    ) == [
        ("full-text", SESSION, "A"),
        ("title-abstract", SESSION, "A"),
    ]
    assert _rows(project, "SELECT stage, work_id FROM calibration_items ORDER BY stage") == [
        ("full-text", W1),
        ("title-abstract", W1),
    ]
    assert _rows(project, "SELECT stage, verdict FROM calibration_labels ORDER BY stage") == [
        ("full-text", "exclude"),
        ("title-abstract", "include"),
    ]
    assert _rows(project, "SELECT stage, verdict FROM resolutions ORDER BY stage") == [
        ("full-text", "exclude"),
        ("title-abstract", "include"),
    ]


def test_decision_anchor_projected(project: Project) -> None:
    conversion = project.ids.new("cnv")
    _, title_event = _decision(project, W1, Verdict.INCLUDE, None)
    decision_id, full_event = _decision(
        project,
        W1,
        Verdict.INCLUDE,
        None,
        stage=ScreeningStage.FULL_TEXT,
        anchor="s2.p3",
        conversion_id=conversion,
    )
    rows = _rows(
        project,
        "SELECT decision_id, stage, anchor, conversion_id FROM decisions ORDER BY event_id",
    )
    assert rows == [
        (rows[0][0], STAGE_TA, None, None),
        (decision_id, ScreeningStage.FULL_TEXT.value, "s2.p3", conversion),
    ]
    assert rows[0][0] != decision_id
    assert title_event.id != full_event.id


def test_rebuild_state_hash_stable(project: Project) -> None:
    _slice1_log(project)
    _decision(
        project,
        W2,
        Verdict.INCLUDE,
        None,
        stage=ScreeningStage.FULL_TEXT,
        anchor="t2.r1.c1",
        conversion_id=project.ids.new("cnv"),
    )
    before = project.index.state_hash()
    assert project.index.rebuild() == before
    assert project.index.rebuild() == before

"""Projection of screening and calibration: passes, sessions, decisions, human labels and audits.

Every run of a screening stage carries a `stage` (`title-abstract` or `full-text`). `passes`,
`pass_sessions`, `calibration_items`, `calibration_labels`, `resolutions` are keyed by stage as
well as by their own key, so the two stages never share a row; `audits` keeps the stage of its
sample. Slice-1 rows have stage `title-abstract`.

`passes` keeps each opened pass (its framing, criterion order, recorded seed and sample; the sample
is canonical JSON, or NULL). `pass_sessions` keeps the session that joined each pass, once, with
who it is: `actor_kind` (`agent` for a line that does not say), `user` (the event's `actor.user`)
and `model` (NULL for a human).
`decisions` keeps every recorded verdict, with the `anchor` and `conversion_id` of a full-text
decision (NULL at title/abstract); a decision that a later one supersedes gets `superseded_by`
set, so a live decision is one with `superseded_by` NULL.

`calibration_items` holds the drawn calibration set (one draw per project and stage);
`calibration_draws` holds one row per stage that has had a draw, even an empty one.
`calibration_labels` and `resolutions` and `audit_items.human_verdict` keep the latest human label
per key. `audits` and `audit_items` hold each audit sample; `agreed_verdict` is computed when the
sample is written from the live screening decisions of the audit's stage, of the two passes under
the protocol then current: `include` when both promote, `exclude` when both do not and neither is
`unsure`, NULL otherwise. Each sample also keeps `population_digest`, the digest of the whole agreed
set of its stage at that time, which the audit service compares to refuse a second open audit.
`label_sessions` keeps every session that relayed a human label over MCP, at either stage; a pass
at either stage may not be joined from one of them. `stage_judges` keeps each user who labelled a
calibration or audit item or resolved a disagreement at a stage, so a judge of a hosted stage does
not join its passes afterwards.

Handlers are total: an event naming an unknown work or pass is stored, not refused. A second
pass, join or sample with the same key changes nothing (first write wins); a second label or
resolution replaces the earlier one (last write wins).

The rules of slice 5 ruling 15 hold on rebuild too, each at its point of the log. A hand-written
event that fails one changes nothing:
- `join_refusal` is the one statement of who may join a pass; the service asks it as well. A pass
  is all human or all agent. On a hosted project the two passes share no user, and a stage's
  judges join neither. Anywhere, one person does not screen both passes in person, and a human
  join needs a role holding `pass:join-human` (an unhosted project with no grant cannot be asked:
  the fold does not know `Settings.user`, so that check is the service's).
- A human join is written by that human, in that session.
- A human decision comes from the session that joined that pass as a human.
- A decision without a quote is a human's, and is not an exclusion in `systematic` (R-110).
- A decision supersedes only a decision of its own pass.
- On a hosted project a member of either pass of a stage does not label, resolve or draw an audit
  at that stage.
"""

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Column, Integer, MetaData, String, Table, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json, population_digest
from factory.events.envelope import Event
from factory.index.human_channel import sign_off_counts
from factory.index.members import MEMBER_TABLES, any_grant, live_roles
from factory.index.project import latest_host
from factory.index.projection import Handler
from factory.model.members import HUMAN_PASS_ROLES
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolAmended, ScreeningStage
from factory.model.screening import (
    AuditLabelled,
    AuditSampled,
    CalibrationDrawn,
    CalibrationLabelled,
    Channel,
    DecisionRecorded,
    DisagreementResolved,
    PassJoined,
    PassOpened,
    Verdict,
)
from factory.model.screening_check import CheckDrawn, CheckLabelled
from factory.model.staleness import DecisionRef, stale_decisions


@dataclass(frozen=True)
class ScreeningTables:
    passes: Table
    pass_sessions: Table
    decisions: Table
    calibration_items: Table
    calibration_draws: Table
    calibration_labels: Table
    resolutions: Table
    audits: Table
    audit_items: Table
    label_sessions: Table
    audit_top_ups: Table
    audit_events: Table
    stage_judges: Table
    check_draws: Table
    check_items: Table
    check_labels: Table


TITLE_ABSTRACT = ScreeningStage.TITLE_ABSTRACT.value


def _stage(*, key: bool) -> Column[str]:
    """The `stage` column of a stage-bearing table; a primary-key part when `key`."""
    return Column("stage", String, primary_key=key, nullable=False, server_default=TITLE_ABSTRACT)


def screening_tables(metadata: MetaData) -> ScreeningTables:
    passes = Table(
        "passes",
        metadata,
        _stage(key=True),
        Column("pass_label", String, primary_key=True),
        Column("framing", String, nullable=False),
        Column("criterion_order", String, nullable=False),
        Column("random_seed", Integer, nullable=False),
        Column("sample", String),
    )
    pass_sessions = Table(
        "pass_sessions",
        metadata,
        _stage(key=True),
        Column("session", String, primary_key=True),
        Column("pass_label", String, nullable=False),
        Column("model", String),
        Column("actor_kind", String, nullable=False, server_default="agent"),
        Column("user", String),
    )
    decisions = Table(
        "decisions",
        metadata,
        Column("decision_id", String, primary_key=True),
        Column("work_id", String, nullable=False),
        Column("pass_label", String, nullable=False),
        Column("phase", String, nullable=False),
        Column("stage", String, nullable=False),
        Column("verdict", String, nullable=False),
        Column("criterion", String),
        Column("quote", String, nullable=False),
        Column("rationale", String, nullable=False),
        Column("protocol_id", String, nullable=False),
        Column("task_id", String, nullable=False),
        Column("supersedes", String),
        Column("superseded_by", String),
        Column("anchor", String),
        Column("conversion_id", String),
        Column("score", Integer),
        Column("event_id", String, nullable=False),
    )
    calibration_items = Table(
        "calibration_items",
        metadata,
        _stage(key=True),
        Column("work_id", String, primary_key=True),
        Column("protocol_id_drawn", String),
    )
    calibration_draws = Table(
        "calibration_draws",
        metadata,
        _stage(key=True),
    )
    calibration_labels = Table(
        "calibration_labels",
        metadata,
        _stage(key=True),
        Column("work_id", String, primary_key=True),
        Column("verdict", String, nullable=False),
        Column("criterion", String),
        Column("channel", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    resolutions = Table(
        "resolutions",
        metadata,
        _stage(key=True),
        Column("work_id", String, primary_key=True),
        Column("verdict", String, nullable=False),
        Column("criterion", String),
        Column("reason", String, nullable=False),
        Column("channel", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    audits = Table(
        "audits",
        metadata,
        Column("audit_id", String, primary_key=True),
        _stage(key=False),
        Column("random_seed", Integer, nullable=False),
        Column("population", Integer, nullable=False),
        Column("exclusions", Integer, nullable=False),
        Column("inclusions", Integer, nullable=False),
        Column("population_digest", String, nullable=False),
        Column("pop_exclusions", Integer, nullable=False),
        Column("pop_inclusions", Integer, nullable=False),
    )
    audit_items = Table(
        "audit_items",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Column("agreed_verdict", String),
        Column("agreed_criteria", String),
        Column("human_verdict", String),
        Column("criterion", String),
    )
    label_sessions = Table(
        "label_sessions",
        metadata,
        Column("session", String, primary_key=True),
    )
    audit_top_ups = Table(
        "audit_top_ups",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("top_up_of", String, nullable=False),
    )
    # The event that recorded each audit: derived from the events table (not part of the hash).
    audit_events = Table(
        "audit_events",
        metadata,
        Column("audit_id", String, primary_key=True),
        Column("event_id", String, nullable=False),
    )
    stage_judges = Table(
        "stage_judges",
        metadata,
        _stage(key=True),
        Column("user", String, primary_key=True),
    )
    # Band checks, tuning and measurement batches (`model/screening_check.py`): one row per draw
    # (with its event, the order of draws), its records, and the latest human label per record.
    check_draws = Table(
        "check_draws",
        metadata,
        Column("draw_id", String, primary_key=True),
        Column("kind", String, nullable=False),
        _stage(key=False),
        Column("pass_label", String, nullable=False),
        Column("last_example_change", String),
        Column("payload", String, nullable=False),
        Column("event_id", String, nullable=False),
    )
    check_items = Table(
        "check_items",
        metadata,
        Column("draw_id", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Column("band", String, nullable=False),
    )
    check_labels = Table(
        "check_labels",
        metadata,
        Column("draw_id", String, primary_key=True),
        Column("work_id", String, primary_key=True),
        Column("verdict", String, nullable=False),
    )
    return ScreeningTables(
        passes=passes,
        pass_sessions=pass_sessions,
        decisions=decisions,
        calibration_items=calibration_items,
        calibration_draws=calibration_draws,
        calibration_labels=calibration_labels,
        resolutions=resolutions,
        audits=audits,
        audit_items=audit_items,
        label_sessions=label_sessions,
        audit_top_ups=audit_top_ups,
        audit_events=audit_events,
        stage_judges=stage_judges,
        check_draws=check_draws,
        check_items=check_items,
        check_labels=check_labels,
    )


def screening_handlers(t: ScreeningTables) -> dict[str, Handler]:
    return {
        "screening.pass_opened": _pass_opened(t),
        "screening.pass_joined": _pass_joined(t),
        "screening.decision_recorded": _decision(t),
        "screening.disagreement_resolved": _resolution(t),
        "calibration.drawn": _calibration_drawn(t),
        "calibration.labelled": _calibration_labelled(t),
        "audit.sampled": _audit_sampled(t),
        "audit.labelled": _audit_labelled(t),
        "check.drawn": _check_drawn(t),
        "check.labelled": _check_labelled(t),
    }


def _pass_opened(t: ScreeningTables) -> Handler:
    def pass_opened(conn: Connection, event: Event) -> None:
        payload = PassOpened.model_validate(event.payload)
        sample = None
        if payload.sample is not None:
            sample = canonical_json(list(payload.sample)).decode()
        conn.execute(
            sqlite_insert(t.passes)
            .values(
                pass_label=payload.pass_label.value,
                framing=payload.framing.value,
                criterion_order=payload.criterion_order,
                random_seed=payload.random_seed,
                sample=sample,
                stage=payload.stage.value,
            )
            .on_conflict_do_nothing(index_elements=["stage", "pass_label"])
        )

    return pass_opened


def _pass_joined(t: ScreeningTables) -> Handler:
    def pass_joined(conn: Connection, event: Event) -> None:
        try:
            payload = PassJoined.model_validate(event.payload)
        except ValidationError:
            return
        actor = event.actor
        if payload.user is not None and payload.user != actor.user:
            return
        if (payload.actor_kind == "human") != (actor.kind == "human"):
            return
        if payload.actor_kind == "human" and payload.session != actor.session:
            return
        refusal = join_refusal(
            conn,
            label=payload.pass_label.value,
            stage=payload.stage.value,
            kind=payload.actor_kind,
            user=actor.user,
        )
        if refusal is not None:
            return
        conn.execute(
            sqlite_insert(t.pass_sessions)
            .values(
                session=payload.session,
                pass_label=payload.pass_label.value,
                model=payload.model,
                stage=payload.stage.value,
                actor_kind=payload.actor_kind,
                user=actor.user,
            )
            .on_conflict_do_nothing(index_elements=["stage", "session"])
        )

    return pass_joined


def _other(label: str) -> str:
    return "B" if label == "A" else "A"


def pass_users(conn: Connection, label: str, stage: str) -> frozenset[str]:
    """U(P): the humans of pass `label` at `stage` and the principals of its agents."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT user FROM pass_sessions WHERE pass_label = :label AND stage = :stage "
            "AND user IS NOT NULL"
        ),
        {"label": label, "stage": stage},
    ).all()
    return frozenset(str(row[0]) for row in rows)


def pass_kinds(conn: Connection, label: str, stage: str) -> frozenset[str]:
    """Who screens pass `label` at `stage`: `agent`, `human`, or nothing yet. One kind at most,
    save on a log written before the rule."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT actor_kind FROM pass_sessions "
            "WHERE pass_label = :label AND stage = :stage"
        ),
        {"label": label, "stage": stage},
    ).all()
    return frozenset(str(row[0]) for row in rows)


def is_stage_judge(conn: Connection, user: str, stage: str) -> bool:
    """Whether `user` has labelled or resolved at `stage`."""
    row = conn.execute(
        text("SELECT 1 FROM stage_judges WHERE stage = :stage AND user = :user"),
        {"stage": stage, "user": user},
    ).first()
    return row is not None


def _may_join_human(conn: Connection, user: str, *, hosted: bool) -> bool:
    if any_grant(conn, MEMBER_TABLES):
        return bool(live_roles(conn, MEMBER_TABLES, user) & HUMAN_PASS_ROLES)
    return not hosted


def join_refusal(
    conn: Connection, *, label: str, stage: str, kind: str, user: str
) -> tuple[str, str] | None:
    """Why `user`, as `kind`, may not join pass `label` of `stage`, as (field, reason); None when
    they may. Reads the log as folded so far, so a rebuild rules as the service did."""
    kinds = pass_kinds(conn, label, stage)
    if kinds and kind not in kinds:
        return "pass", f"pass {label} is screened by {sorted(kinds)[0]}s; a pass is not mixed"
    if kind == "human" and user in pass_users(conn, label, stage):
        return "pass", f"this person already screens pass {label}"
    hosted = latest_host(conn) is not None
    other = _other(label)
    if user in pass_users(conn, other, stage) and (
        hosted or (kind == "human" and "human" in pass_kinds(conn, other, stage))
    ):
        return "user", f"this person already screens pass {other}"
    if hosted and is_stage_judge(conn, user, stage):
        return "user", f"this person labelled or resolved at {stage} and cannot screen it"
    if kind == "human" and not _may_join_human(conn, user, hosted=hosted):
        return "permission", "pass:join-human not held"
    return None


def _pass_member(conn: Connection, user: str, stage: str) -> bool:
    return user in pass_users(conn, "A", stage) | pass_users(conn, "B", stage)


def _hosted_member(conn: Connection, event: Event, stage: str) -> bool:
    """Whether a label or resolution comes from a member of a pass of `stage`, on a hosted project.
    Such an act is refused by `passes.require_outside_passes`, so the fold ignores it."""
    return latest_host(conn) is not None and _pass_member(conn, event.actor.user, stage)


def _note_judge(conn: Connection, t: ScreeningTables, event: Event, stage: str) -> None:
    conn.execute(
        sqlite_insert(t.stage_judges)
        .values(stage=stage, user=event.actor.user)
        .on_conflict_do_nothing(index_elements=["stage", "user"])
    )


def _decision_counts(conn: Connection, event: Event, payload: DecisionRecorded) -> bool:
    """Whether a decision folds: the guards a human decision and a quoteless one must meet. An
    agent decision with a quote is not asked, as it never was."""
    actor = event.actor
    if actor.kind == "human":
        row = conn.execute(
            text(
                "SELECT pass_label, actor_kind FROM pass_sessions "
                "WHERE session = :session AND stage = :stage"
            ),
            {"session": actor.session, "stage": payload.stage.value},
        ).first()
        if row is None or (str(row[0]), str(row[1])) != (payload.pass_label.value, "human"):
            return False
    if payload.quote:
        return True
    if actor.kind != "human":
        return False
    mode = conn.execute(text("SELECT rigor_mode FROM project LIMIT 1")).scalar_one_or_none()
    return not (payload.verdict is Verdict.EXCLUDE and mode == RigorMode.SYSTEMATIC.value)


def _decision(t: ScreeningTables) -> Handler:
    def decision(conn: Connection, event: Event) -> None:
        payload = DecisionRecorded.model_validate(event.payload)
        if not _decision_counts(conn, event, payload):
            return
        conn.execute(
            sqlite_insert(t.decisions)
            .values(
                decision_id=payload.decision_id,
                work_id=payload.work_id,
                pass_label=payload.pass_label.value,
                phase=payload.phase.value,
                stage=payload.stage.value,
                verdict=payload.verdict.value,
                criterion=payload.criterion,
                quote=payload.quote,
                rationale=payload.rationale,
                protocol_id=payload.protocol_id,
                task_id=payload.task_id,
                supersedes=payload.supersedes,
                superseded_by=None,
                anchor=payload.anchor,
                conversion_id=payload.conversion_id,
                score=payload.score,
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["decision_id"])
        )
        if payload.supersedes is not None:
            conn.execute(
                update(t.decisions)
                .where(t.decisions.c.decision_id == payload.supersedes)
                .where(t.decisions.c.pass_label == payload.pass_label.value)
                .where(t.decisions.c.superseded_by.is_(None))
                .values(superseded_by=payload.decision_id)
            )

    return decision


def _resolution(t: ScreeningTables) -> Handler:
    def resolution(conn: Connection, event: Event) -> None:
        payload = DisagreementResolved.model_validate(event.payload)
        if _hosted_member(conn, event, payload.stage.value):
            return
        values = {
            "stage": payload.stage.value,
            "work_id": payload.work_id,
            "verdict": payload.verdict,
            "criterion": payload.criterion,
            "reason": payload.reason,
            "channel": payload.channel.value,
            "event_id": event.id,
        }
        conn.execute(
            sqlite_insert(t.resolutions)
            .values(**values)
            .on_conflict_do_update(index_elements=["stage", "work_id"], set_=values)
        )
        _note_judge(conn, t, event, payload.stage.value)

    return resolution


def _calibration_drawn(t: ScreeningTables) -> Handler:
    def calibration_drawn(conn: Connection, event: Event) -> None:
        payload = CalibrationDrawn.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.calibration_draws)
            .values(stage=payload.stage.value)
            .on_conflict_do_nothing(index_elements=["stage"])
        )
        for work_id in payload.work_ids:
            conn.execute(
                sqlite_insert(t.calibration_items)
                .values(
                    stage=payload.stage.value,
                    work_id=work_id,
                    protocol_id_drawn=payload.protocol_id,
                )
                .on_conflict_do_nothing(index_elements=["stage", "work_id"])
            )

    return calibration_drawn


def _calibration_labelled(t: ScreeningTables) -> Handler:
    def calibration_labelled(conn: Connection, event: Event) -> None:
        payload = CalibrationLabelled.model_validate(event.payload)
        if _hosted_member(conn, event, payload.stage.value) or not sign_off_counts(
            conn, event.actor, payload.channel
        ):
            return
        values = {
            "stage": payload.stage.value,
            "work_id": payload.work_id,
            "verdict": payload.verdict,
            "criterion": payload.criterion,
            "channel": payload.channel.value,
            "event_id": event.id,
        }
        conn.execute(
            sqlite_insert(t.calibration_labels)
            .values(**values)
            .on_conflict_do_update(index_elements=["stage", "work_id"], set_=values)
        )
        _note_label_session(conn, t, event, payload.channel)
        _note_judge(conn, t, event, payload.stage.value)

    return calibration_labelled


def _audit_sampled(t: ScreeningTables) -> Handler:
    def audit_sampled(conn: Connection, event: Event) -> None:
        payload = AuditSampled.model_validate(event.payload)
        if _hosted_member(conn, event, payload.stage.value):
            return
        agreed = _agreed_by_work(conn, t, _current_protocol_id(conn), payload.stage.value)
        verdicts = [(work, verdict) for work, (verdict, _) in agreed.items()]
        conn.execute(
            sqlite_insert(t.audits)
            .values(
                audit_id=payload.audit_id,
                stage=payload.stage.value,
                random_seed=payload.random_seed,
                population=payload.population,
                exclusions=payload.exclusions,
                inclusions=payload.inclusions,
                population_digest=population_digest(verdicts),
                pop_exclusions=sum(1 for _, v in verdicts if v == "exclude"),
                pop_inclusions=sum(1 for _, v in verdicts if v == "include"),
            )
            .on_conflict_do_nothing(index_elements=["audit_id"])
        )
        conn.execute(
            sqlite_insert(t.audit_events)
            .values(audit_id=payload.audit_id, event_id=event.id)
            .on_conflict_do_nothing(index_elements=["audit_id"])
        )
        if payload.top_up_of is not None:
            conn.execute(
                sqlite_insert(t.audit_top_ups)
                .values(audit_id=payload.audit_id, top_up_of=payload.top_up_of)
                .on_conflict_do_nothing(index_elements=["audit_id"])
            )
        for work_id in payload.work_ids:
            agreed_verdict, agreed_criteria = agreed.get(work_id, (None, None))
            conn.execute(
                sqlite_insert(t.audit_items)
                .values(
                    audit_id=payload.audit_id,
                    work_id=work_id,
                    agreed_verdict=agreed_verdict,
                    agreed_criteria=agreed_criteria,
                    human_verdict=None,
                    criterion=None,
                )
                .on_conflict_do_nothing(index_elements=["audit_id", "work_id"])
            )

    return audit_sampled


def _audit_labelled(t: ScreeningTables) -> Handler:
    def audit_labelled(conn: Connection, event: Event) -> None:
        payload = AuditLabelled.model_validate(event.payload)
        drawn_at = conn.execute(
            select(t.audits.c.stage).where(t.audits.c.audit_id == payload.audit_id)
        ).scalar_one_or_none()
        stage = payload.stage.value if drawn_at is None else str(drawn_at)
        if _hosted_member(conn, event, stage) or not sign_off_counts(
            conn, event.actor, payload.channel
        ):
            return
        conn.execute(
            update(t.audit_items)
            .where(t.audit_items.c.audit_id == payload.audit_id)
            .where(t.audit_items.c.work_id == payload.work_id)
            .values(human_verdict=payload.verdict, criterion=payload.criterion)
        )
        _note_label_session(conn, t, event, payload.channel)
        _note_judge(conn, t, event, stage)

    return audit_labelled


def _check_drawn(t: ScreeningTables) -> Handler:
    def check_drawn(conn: Connection, event: Event) -> None:
        payload = CheckDrawn.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.check_draws)
            .values(
                draw_id=payload.draw_id,
                kind=payload.kind.value,
                stage=payload.stage.value,
                pass_label=payload.pass_label.value,
                last_example_change=payload.last_example_change,
                payload=canonical_json(payload.model_dump(mode="json")).decode(),
                event_id=event.id,
            )
            .on_conflict_do_nothing(index_elements=["draw_id"])
        )
        for item in payload.items:
            conn.execute(
                sqlite_insert(t.check_items)
                .values(draw_id=payload.draw_id, work_id=item.work_id, band=item.band)
                .on_conflict_do_nothing(index_elements=["draw_id", "work_id"])
            )

    return check_drawn


def _check_labelled(t: ScreeningTables) -> Handler:
    def check_labelled(conn: Connection, event: Event) -> None:
        payload = CheckLabelled.model_validate(event.payload)
        if event.actor.kind != "human" or not sign_off_counts(conn, event.actor, payload.channel):
            return
        values = {
            "draw_id": payload.draw_id,
            "work_id": payload.work_id,
            "verdict": payload.verdict,
        }
        conn.execute(
            sqlite_insert(t.check_labels)
            .values(**values)
            .on_conflict_do_update(index_elements=["draw_id", "work_id"], set_=values)
        )
        _note_label_session(conn, t, event, payload.channel)

    return check_labelled


def _note_label_session(
    conn: Connection, t: ScreeningTables, event: Event, channel: Channel
) -> None:
    """Record the session of an MCP-relayed human label, so that session cannot join a pass."""
    if not channel.remote:
        return
    conn.execute(
        sqlite_insert(t.label_sessions)
        .values(session=event.actor.session)
        .on_conflict_do_nothing(index_elements=["session"])
    )


def _current_protocol_id(conn: Connection) -> str | None:
    row = conn.execute(
        text("SELECT protocol_id FROM protocols ORDER BY event_id DESC LIMIT 1")
    ).one_or_none()
    return None if row is None else str(row[0])


def _lineage_through(conn: Connection, protocol_id: str) -> list[str]:
    """The protocol versions recorded up to the latest recording of `protocol_id`; the
    projector's twin of `protocol.lineage_through`."""
    rows = [
        str(row[0])
        for row in conn.execute(text("SELECT protocol_id FROM protocols ORDER BY event_id"))
    ]
    if protocol_id not in rows:
        return []
    last = len(rows) - 1 - rows[::-1].index(protocol_id)
    return sorted(set(rows[: last + 1]))


def _stale_ids(conn: Connection, t: ScreeningTables, stage: str) -> set[str]:
    """The live decisions of `stage` that the amendments recorded so far make stale; the same
    rules and order as `screening.stale_screening_decisions`."""
    amended = [
        (str(event), ProtocolAmended.model_validate_json(str(payload)))
        for event, payload in conn.execute(
            text("SELECT event_id, payload FROM amendments ORDER BY event_id")
        )
    ]
    if not any(amendment.stale_rules for _, amendment in amended):
        return set()
    seen: dict[str, None] = {}
    for (version,) in conn.execute(text("SELECT protocol_id FROM protocols ORDER BY event_id")):
        seen.setdefault(str(version), None)
    rows = conn.execute(
        select(
            t.decisions.c.decision_id,
            t.decisions.c.verdict,
            t.decisions.c.criterion,
            t.decisions.c.protocol_id,
            t.decisions.c.event_id,
        )
        .where(t.decisions.c.stage == stage)
        .where(t.decisions.c.superseded_by.is_(None))
    ).all()
    refs = [
        DecisionRef(
            decision_id=str(decision),
            verdict=str(verdict),
            criterion=None if criterion is None else str(criterion),
            protocol_id=str(version),
            stage=ScreeningStage(stage),
            at=str(event),
        )
        for decision, verdict, criterion, version, event in rows
    ]
    return set(
        stale_decisions(
            [amendment for _, amendment in amended],
            list(seen),
            refs,
            amended_at=[event for event, _ in amended],
        )
    )


def _agreed_by_work(
    conn: Connection, t: ScreeningTables, protocol_id: str | None, stage: str
) -> dict[str, tuple[str, str | None]]:
    """The agreed set of `stage` under `protocol_id` (decision 50: decisions of every protocol
    version recorded up to and including it count): for each work both passes screened, its
    agreed outcome (`include` when both live screening decisions promote, `exclude` when neither
    does) and, for an exclusion, the bare criteria either pass cited, sorted and comma-joined. A
    work with an `unsure` verdict, or whose passes disagree, is not agreed and is absent. Matches
    `agreement.agreed_works` for the same stage."""
    if protocol_id is None:
        return {}
    rows = conn.execute(
        select(
            t.decisions.c.decision_id,
            t.decisions.c.pass_label,
            t.decisions.c.work_id,
            t.decisions.c.verdict,
            t.decisions.c.criterion,
        )
        .where(t.decisions.c.phase == "screening")
        .where(t.decisions.c.stage == stage)
        .where(t.decisions.c.protocol_id.in_(_lineage_through(conn, protocol_id)))
        .where(t.decisions.c.superseded_by.is_(None))
        .order_by(t.decisions.c.event_id)
    ).all()
    stale = _stale_ids(conn, t, stage)
    decided: dict[str, dict[str, tuple[Verdict, str | None]]] = {}
    for decision_id, pass_label, work_id, verdict, criterion in rows:
        if decision_id in stale:
            continue
        bare = None if criterion is None else str(criterion).rsplit(":", 1)[-1]
        decided.setdefault(str(work_id), {})[str(pass_label)] = (Verdict(str(verdict)), bare)
    agreed: dict[str, tuple[str, str | None]] = {}
    for work_id, by_pass in decided.items():
        if set(by_pass) != {"A", "B"}:
            continue
        (a, a_criterion), (b, b_criterion) = by_pass["A"], by_pass["B"]
        if Verdict.UNSURE in (a, b) or a.promotes != b.promotes:
            continue
        if a.promotes:
            agreed[work_id] = ("include", None)
            continue
        cited = sorted({c for c in (a_criterion, b_criterion) if c is not None})
        agreed[work_id] = ("exclude", ",".join(cited))
    return agreed

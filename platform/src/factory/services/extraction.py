"""Extraction passes, their sessions, and the tasks an agent extracts (R-13, decision 37).

Pass A extracts every work that full-text screening included; pass B extracts the dual sample
(`ExtractionSchema.dual_extract_sample`, None = every work) with the fields in reverse order. Each
pass is opened once, with a seed; B's seed orders the sample. One task holds one work of one pass
and pins the document and conversion read: both passes of a work share the pin of its first task
(`unit_pin`), so a later conversion never changes a queued or served task.

A session joins one extraction pass. It is refused from the other pass, from a model that already
serves the other pass, from a session that joined any screening pass, and from a session that
relayed a human label over MCP (it could read an answer key). A refusal raises
FactoryValidationError and writes nothing.

Invariants:
- Nothing is queued until the protocol is ready and declares an extraction schema of a known pack
  and a full-text screening plan (R-13).
- `extraction_population` is exactly the works whose full-text outcome is INCLUDED, sorted.
- A task is created at most once per (work, pass); `extract_next` is idempotent while the session
  holds a live claim.
- `in_dual_sample` is pure and monotone in `fraction`: the works sampled at a smaller fraction are
  sampled at every larger one.
- Pass events, the join and the new tasks are written in one append.
- `extract_record` writes a row only after it is verified against the task's pinned conversion,
  and a claim only from pass A, with its quote verified in its anchor; a correction supersedes a
  live row (or claim) of the same work and pass, and both stay in the log.
- A unit closes only when no item of the closing call is rejected, and a unit with no live row
  and no live claim closes only with a reason; its counts are computed, never supplied.
"""

import hashlib
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

from pydantic import JsonValue, ValidationError
from sqlalchemy import text

from factory.clock import format_ts
from factory.document.anchors import Manifest
from factory.document.quotes import quote_in_element
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.extraction.verify import ANCHOR_UNKNOWN, QUOTE_NOT_IN_ANCHOR
from factory.model.base import StrictModel
from factory.model.extraction import (
    VERIFIER_VERSION,
    ClaimInput,
    ClaimRecorded,
    ClaimType,
    EvidenceType,
    ExtractedRowInput,
    ExtractionClosed,
    ExtractionPassJoined,
    ExtractionPassOpened,
    ExtractionRecorded,
    ReportedIn,
    StoredField,
    Strength,
)
from factory.model.protocol import ExtractionSchema, ProtocolStatus, ScreeningStage
from factory.model.screening import Channel, PassLabel
from factory.model.task import Task, TaskCompleted, TaskStatus
from factory.packs import FieldKind, Pack, get_pack
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.document_read import default_conversion
from factory.services.extraction_verify import VALUE_FIELD, verify_row_in
from factory.services.protocol import ProtocolVersion, current_protocol
from factory.services.results import BatchResult, ItemError
from factory.services.screening import _is_label_session
from factory.services.search import list_works
from factory.services.stages import EXTRACT_KINDS, screening_plan
from factory.services.tasks import (
    TaskSpec,
    build_task_events,
    claim_next,
    get_task,
    require_holder,
    task_content,
)

__all__ = [
    "EXTRACT_KINDS",
    "ClaimRow",
    "ExtractBatch",
    "ExtractBatchContent",
    "ExtractNext",
    "ExtractResult",
    "ExtractionRow",
    "PassConfig",
    "extract_next",
    "extract_record",
    "extraction_population",
    "in_dual_sample",
    "is_extraction_session",
    "join_extraction_pass",
    "live_claims",
    "live_rows",
    "pass_config",
    "require_schema",
    "unit_pin",
]

FT = ScreeningStage.FULL_TEXT

INSTRUCTIONS = (
    "Extract only what the pinned document states. Read it with document_read. For every field "
    "give the value as printed, the verbatim quote that contains it and its anchor (a table "
    "cell for a table value), and the unit, when the field has one, in `unit`. Declare "
    "`reported_in = cited` for a value the paper copies from other work. Never compute, round "
    "or convert a value, and leave out a field the document does not state."
)
CLAIMS_INSTRUCTIONS = (
    " Also record the claims the paper makes, each with a verbatim quote and its anchor."
)


class ExtractBatchContent(StrictModel):
    """What one extraction task asks of an agent. This is the task's content and its input blob."""

    pass_label: PassLabel
    instructions: str
    protocol_id: str
    schema_ref: str
    fields: list[dict[str, str | list[str] | None]]
    required: list[str]
    claims: bool
    records: list[dict[str, str]]


class ExtractBatch(ExtractBatchContent):
    """A task as served to a session: its content and the task that holds it."""

    task_id: str


class ExtractNext(StrictModel):
    """`batch` is None when nothing is served; `blocked` says why; `remaining` counts the works of
    this pass whose task is not yet completed."""

    batch: ExtractBatch | None
    blocked: list[str]
    remaining: int


@dataclass(frozen=True)
class PassConfig:
    """What an opened pass recorded."""

    seed: int
    field_order: str


# --- Preconditions ---


def require_schema(project: Project) -> tuple[ProtocolVersion, ExtractionSchema, Pack]:
    """The ready protocol, its extraction schema and the schema's pack. Raises on field
    `protocol` when no ready protocol exists, `extraction_schema` when none is declared (R-13) and
    `extraction_schema.pack` for an unknown pack."""
    protocol = current_protocol(project)
    if protocol is None or protocol.status is not ProtocolStatus.READY:
        raise FactoryValidationError(
            [ValidationIssue("protocol", "the protocol is not ready; record it ready first")]
        )
    schema = protocol.spec.extraction_schema
    if schema is None:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "extraction_schema",
                    "declare the extraction schema in the protocol first (R-13)",
                )
            ]
        )
    pack = get_pack(schema.pack, schema.pack_version)
    if pack is None:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "extraction_schema.pack",
                    f"unknown pack {schema.pack} version {schema.pack_version}",
                )
            ]
        )
    return protocol, schema, pack


def extraction_population(project: Project) -> list[str]:
    """The works whose full-text screening outcome is INCLUDED, sorted. Raises on field
    `full_text_screening` when the protocol declares no full-text plan."""
    project.index.sync()
    protocol = current_protocol(project)
    if protocol is None:
        raise FactoryValidationError([ValidationIssue("protocol", "record a protocol first")])
    screening_plan(protocol, FT)
    return sorted(w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED)


def in_dual_sample(seed: int, work_id: str, fraction: float | None) -> bool:
    """Whether `work_id` is in the dual-extraction sample of `fraction` under `seed`.

    Each work gets a fixed position, the full sha256 digest of the seed and the work as a fraction
    of 2**256, and is in the sample when the position is below `fraction` (compared exactly); so a
    larger fraction only adds works. None means every work (ruling 1)."""
    if fraction is None:
        return True
    digest = hashlib.sha256(f"{seed}:{work_id}".encode()).digest()
    return Fraction(int.from_bytes(digest, "big"), 2**256) < Fraction(fraction)


# --- Reads ---


def pass_config(project: Project, label: PassLabel) -> PassConfig | None:
    """The seed and field order recorded when pass `label` opened; None when it has not."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT random_seed, field_order FROM extraction_passes WHERE pass_label = :l"),
            {"l": label.value},
        ).one_or_none()
    return None if row is None else PassConfig(seed=int(row[0]), field_order=str(row[1]))


def is_extraction_session(project: Project, session: str) -> bool:
    """Whether the session has joined an extraction pass."""
    project.index.sync()
    return _joined_pass(project, session) is not None


def unit_pin(project: Project, work_id: str) -> tuple[str, str] | None:
    """The (document, conversion) the extraction of `work_id` is pinned to: the pin of its first
    task, of either pass, by task id; None when no task of the work exists."""
    return _pins(project).get(work_id)


def _pins(project: Project) -> dict[str, tuple[str, str]]:
    """The pin of every work that has an extraction task: that of its first task by task id."""
    pins: dict[str, tuple[str, str]] = {}
    for _, _, content in _kind_tasks(project, *EXTRACT_KINDS.values()):
        for record in content.records:
            pins.setdefault(record["work_id"], (record["document_id"], record["conversion_id"]))
    return pins


def _kind_tasks(project: Project, *kinds: str) -> list[tuple[str, str, ExtractBatchContent]]:
    """Every task of the kinds as (task id, status, content), in task-ID order."""
    marks = ", ".join(f":k{i}" for i in range(len(kinds)))
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT task_id, status, content_blob FROM tasks WHERE kind IN ({marks}) "
                "ORDER BY task_id"
            ),
            {f"k{i}": kind for i, kind in enumerate(kinds)},
        ).all()
    return [
        (
            str(task_id),
            str(status),
            ExtractBatchContent.model_validate(project.blobs.get_json(str(blob))),
        )
        for task_id, status, blob in rows
    ]


def _joined_pass(project: Project, session: str) -> PassLabel | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT pass_label FROM extraction_sessions WHERE session = :s"), {"s": session}
        ).one_or_none()
    return None if row is None else PassLabel(str(row[0]))


def _pass_models(project: Project, label: PassLabel) -> set[str]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT model FROM extraction_sessions WHERE pass_label = :l"),
            {"l": label.value},
        ).all()
    return {str(row[0]) for row in rows}


def _screening_session(project: Project, session: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM pass_sessions WHERE session = :s"), {"s": session}
        ).first()
    return row is not None


def _relayed_extraction_label(project: Project, session: str) -> bool:
    """Whether `session` relayed an extraction resolution or audit label over MCP. Read from the
    log, as the projection keeps no session for these events."""
    kinds = {"extraction.resolved", "extraction.audit_labelled"}
    return any(
        event.type in kinds
        and event.actor.session == session
        and event.payload.get("channel") == Channel.MCP.value
        for event in read_all(project.paths.events_dir, project.catalog)
    )


def _other(label: PassLabel) -> PassLabel:
    return PassLabel.B if label is PassLabel.A else PassLabel.A


# --- Joining ---


def join_extraction_pass(project: Project, actor: Actor, label: PassLabel) -> None:
    """Bind the session to extraction pass `label`. Refused, with nothing written, when the actor
    is not an agent, when the session relayed a human label or joined a screening pass, or when
    it or its model already serves the other pass. Joining the same pass again writes nothing."""
    with project.index.exclusive():
        project.index.sync()
        if _check_join(project, actor, label):
            project.record([_join_event(project, actor, label)])


def _check_join(project: Project, actor: Actor, label: PassLabel) -> bool:
    """True when a join must be written; raises on a refusal."""
    if actor.kind != "agent" or actor.model is None:
        raise FactoryValidationError(
            [ValidationIssue("actor", "only an agent extractor joins a pass")]
        )
    joined = _joined_pass(project, actor.session)
    if joined is label:
        return False
    if _is_label_session(project, actor.session) or _relayed_extraction_label(
        project, actor.session
    ):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session relayed a human label and cannot extract")]
        )
    if _screening_session(project, actor.session):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session joined a screening pass and cannot extract")]
        )
    if joined is not None:
        raise FactoryValidationError(
            [ValidationIssue("pass", f"this session already extracts pass {joined.value}")]
        )
    if actor.model in _pass_models(project, _other(label)):
        raise FactoryValidationError(
            [ValidationIssue("model", f"pass {_other(label).value} already uses this model")]
        )
    return True


def _input(project: Project, actor: Actor, label: PassLabel) -> str | None:
    value: dict[str, JsonValue] = {"pass_label": label.value}
    return project.blobs.put_json(value) if actor.kind == "agent" else None


def _join_event(project: Project, actor: Actor, label: PassLabel) -> Event:
    model = actor.model
    if model is None:
        raise FactoryValidationError(
            [ValidationIssue("actor", "only an agent extractor joins a pass")]
        )
    payload = ExtractionPassJoined(pass_label=label, session=actor.session, model=model)
    return project.events.make(
        "extraction.pass_joined", payload, actor, input_blob=_input(project, actor, label)
    )


# --- Serving ---


def extract_next(project: Project, actor: Actor, label: PassLabel) -> ExtractNext:
    """Serve the next task of extraction pass `label` to the session, or say why none is served.

    Refused (nothing written) for a non-agent, for a join the rules forbid, and until the protocol
    is ready with an extraction schema and a full-text screening plan. Otherwise the session
    joins, the pass opens once, a task is queued for each work of the pass lacking one, and the
    next claimable task is claimed. A session that already holds a live claim is served that task
    again. `ExtractionSchema.dual_extract_sample=None` means every work, so pass B then queues the
    whole population. `blocked` carries content-free reasons: how many works have no converted
    document, and that no work falls in the dual sample."""
    with project.index.exclusive():
        project.index.sync()
        protocol, schema, pack = require_schema(project)
        population = extraction_population(project)
        if actor.kind != "agent" or actor.model is None:
            raise FactoryValidationError(
                [ValidationIssue("actor", "only an agent extractor joins a pass")]
            )
        needs_join = _check_join(project, actor, label)
        events: list[Event] = []
        config = pass_config(project, label)
        if config is None:
            seed = secrets.randbits(32)
            order: Literal["schema", "reversed"] = "schema" if label is PassLabel.A else "reversed"
            config = PassConfig(seed=seed, field_order=order)
            events.append(
                project.events.make(
                    "extraction.pass_opened",
                    ExtractionPassOpened(pass_label=label, random_seed=seed, field_order=order),
                    actor,
                    input_blob=_input(project, actor, label),
                )
            )
        if needs_join:
            events.append(_join_event(project, actor, label))
        queue = _queue(label, population, config.seed, schema)
        queued, remaining, unconverted = _enqueue(
            project, actor, label, protocol, schema, pack, config, queue
        )
        blocked: list[str] = []
        if unconverted:
            blocked.append(f"{unconverted} works have no converted document")
        if label is PassLabel.B and population and not queue:
            blocked.append("no work falls in the dual sample")
        project.record([*events, *queued])
        task = _held(project, actor, label) or claim_next(project, actor, EXTRACT_KINDS[label])
        batch = None if task is None else _batch(project, task)
        return ExtractNext(batch=batch, blocked=blocked, remaining=remaining)


def _queue(
    label: PassLabel, population: list[str], seed: int, schema: ExtractionSchema
) -> list[str]:
    """The works of the pass: all of them for A, the dual sample for B."""
    if label is PassLabel.A:
        return population
    return [w for w in population if in_dual_sample(seed, w, schema.dual_extract_sample)]


def _enqueue(
    project: Project,
    actor: Actor,
    label: PassLabel,
    protocol: ProtocolVersion,
    schema: ExtractionSchema,
    pack: Pack,
    config: PassConfig,
    queue: list[str],
) -> tuple[list[Event], int, int]:
    """The `task.created` events for the works of `queue` lacking a task of this pass, not yet
    recorded; how many works of the queue still await a completed task; and how many have no
    converted document (never servable, so not counted as remaining)."""
    kind = EXTRACT_KINDS[label]
    tasks = _kind_tasks(project, kind)
    queued = {str(record["work_id"]) for _, _, content in tasks for record in content.records}
    done = {
        str(record["work_id"])
        for _, status, content in tasks
        if status == TaskStatus.COMPLETED.value
        for record in content.records
    }
    titles = {work.id: work.title for work in list_works(project)}
    fields = _fields(pack, schema, config.field_order)
    pins = _pins(project)
    specs: list[TaskSpec] = []
    unconverted = 0
    for work_id in queue:
        if work_id in queued:
            continue
        pin = pins.get(work_id)
        if pin is None:
            chosen = default_conversion(project, work_id)
            if chosen is None:
                unconverted += 1  # not retrieved or not converted: nothing to extract from
                continue
            pin = (chosen.document_id, chosen.conversion_id)
        content = ExtractBatchContent(
            pass_label=label,
            instructions=INSTRUCTIONS + (CLAIMS_INSTRUCTIONS if schema.claims else ""),
            protocol_id=protocol.protocol_id,
            schema_ref=f"{schema.pack}@{schema.pack_version}",
            fields=fields,
            required=list(pack.required),
            claims=schema.claims,
            records=[
                {
                    "work_id": work_id,
                    "title": titles.get(work_id, ""),
                    "document_id": pin[0],
                    "conversion_id": pin[1],
                }
            ],
        )
        specs.append(TaskSpec(kind=kind, content=content.model_dump(mode="json")))
    events, result = build_task_events(project, actor, specs)
    if result.rejected:
        raise FactoryValidationError([issue for item in result.rejected for issue in item.issues])
    return events, len(set(queue) - done) - unconverted, unconverted


def _fields(
    pack: Pack, schema: ExtractionSchema, field_order: str
) -> list[dict[str, str | list[str] | None]]:
    """The declared fields in schema order, or reversed for pass B."""
    names = list(schema.fields)
    if field_order == "reversed":
        names.reverse()
    out: list[dict[str, str | list[str] | None]] = []
    for name in names:
        definition = pack.field(name)
        if definition is None:
            raise FactoryValidationError(
                [ValidationIssue("extraction_schema.fields", f"not a field of the pack: {name}")]
            )
        out.append(
            {
                "name": definition.name,
                "group": definition.group,
                "kind": definition.kind.value,
                "unit_family": definition.unit_family.value,
                "units": list(definition.units),
                "check": definition.check.value,
            }
        )
    return out


def _held(project: Project, actor: Actor, label: PassLabel) -> Task | None:
    """The live claim this session holds on a task of the pass, if any."""
    now = format_ts(project.clock.now())
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT task_id FROM tasks WHERE kind = :kind AND status = :claimed "
                "AND claim_session = :s AND lease_until > :now ORDER BY task_id LIMIT 1"
            ),
            {
                "kind": EXTRACT_KINDS[label],
                "claimed": TaskStatus.CLAIMED.value,
                "s": actor.session,
                "now": now,
            },
        ).one_or_none()
    if row is None:
        return None
    return get_task(project, str(row[0]))


def _batch(project: Project, task: Task) -> ExtractBatch:
    content = task_content(project, task)
    fields = dict(content) if isinstance(content, dict) else {}
    return ExtractBatch.model_validate({**fields, "task_id": task.task_id})


# --- Recording ---

DUPLICATE_ROW = "a row for this location is already recorded; supersede it"
"""Why a row whose row_key a live row (or an earlier row of the call) of its unit holds is
rejected. Duplicate claims are not refused: a claim has no location key."""


class ExtractionRow(StrictModel):
    """A live recorded row as the projection holds it.

    Warning: field values are stored as text (booleans are restored by the field's kind), so the
    original int or float of a value is lost. Compare `canonical` for number fields and the
    pack's normaliser for text fields, never `.value`."""

    extraction_id: str
    work_id: str
    pass_label: PassLabel
    task_id: str
    protocol_id: str
    conversion_id: str
    document_id: str
    row_key: str
    fields: dict[str, StoredField]
    event_id: str


class ClaimRow(StrictModel):
    """A live recorded claim as the projection holds it."""

    claim_id: str
    work_id: str
    pass_label: PassLabel
    claim_type: ClaimType
    evidence_type: EvidenceType
    strength: Strength
    statement: str
    anchor: str
    quote: str
    conversion_id: str
    event_id: str


class ExtractResult(StrictModel):
    """What one `extract_record` call wrote and rejected, and whether it completed the task."""

    rows: BatchResult[str]
    claims: BatchResult[str]
    completed: bool


@dataclass(frozen=True)
class _Unit:
    """The work, pass and pin of the task being recorded."""

    task_id: str
    content: ExtractBatchContent
    work_id: str
    document_id: str
    conversion_id: str

    @property
    def label(self) -> PassLabel:
        return self.content.pass_label


@dataclass(frozen=True)
class _Row:
    index: int
    fields: dict[str, StoredField]
    row_key: str


def extract_record(
    project: Project,
    actor: Actor,
    task_id: str,
    rows: Sequence[ExtractedRowInput],
    claims: Sequence[ClaimInput] = (),
    *,
    finish: bool = False,
    reason: str | None = None,
    supersedes: Mapping[int, str] | None = None,
    claim_supersedes: Mapping[int, str] | None = None,
) -> ExtractResult:
    """Record the rows and claims an agent extracted for a held task, and close it on `finish`.

    Refused, with nothing written, when the actor is not an agent (`actor`); the task is unknown,
    not held by this session or not an extraction task (`task_id`); the session does not extract
    the task's pass (`pass`); the current schema's pack, version or declared fields differ from
    what the task served (`task_id`, ruling 12; any other amendment is accepted and the events
    carry the current protocol id); a key of `supersedes` or `claim_supersedes` is not an index
    of the call (that name); or `finish` would close a unit with no live row and no live claim
    without a non-blank `reason` (`reason`).

    Otherwise each row is verified alone against the task's pinned conversion and each claim's
    quote is verified in its anchor's element like a field quote; an invalid item is an
    `ItemError` (issues located within the item, its index locating it) and is not written.
    Claims are rejected (`claims`) unless the schema enables them and the task is of pass A.
    `supersedes` maps a row index to the id of a live row of the same work and pass that the row
    corrects; any other target, or one target an accepted row already corrects, rejects that row
    (`supersedes`). A row whose row_key a live row of the unit holds (other than its own target),
    or an earlier accepted row of the call, is rejected (`fields.value`, `DUPLICATE_ROW`). Claims
    are superseded likewise with `claim_supersedes`; duplicate claims are not refused.

    `finish` closes the unit only when no item of the call is rejected: `extraction.closed`, with
    counts computed as the live items minus the superseded targets plus the accepted items, and
    `task.completed`, with those row ids then claim ids (each sorted) as results. The rows,
    claims, closure and completion are appended in one write; each extraction event carries the
    whole call's input as its input blob, stored only when something is appended.
    """
    with project.index.exclusive():
        project.index.sync()
        if actor.kind != "agent" or actor.model is None:
            raise FactoryValidationError(
                [ValidationIssue("actor", "only an agent extractor records an extraction")]
            )
        task = require_holder(project, actor, task_id)
        unit = _unit_of(project, task)
        if _joined_pass(project, actor.session) is not unit.label:
            raise FactoryValidationError(
                [ValidationIssue("pass", f"this session does not extract pass {unit.label}")]
            )
        protocol, schema, pack = require_schema(project)
        _require_same_schema(project, unit, schema, pack)
        row_targets = _targets(supersedes, len(rows), "supersedes")
        claim_targets = _targets(claim_supersedes, len(claims), "claim_supersedes")
        manifest = conversion_manifest(project, unit.conversion_id)
        corpus = {work.id for work in list_works(project)}

        live_keys = {
            r.extraction_id: r.row_key for r in live_rows(project, unit.label, work_id=unit.work_id)
        }
        used: set[str] = set()
        accepted_keys: set[str] = set()
        row_errors: list[ItemError] = []
        accepted_rows: list[_Row] = []
        for index, row in enumerate(rows):
            target = row_targets.get(index)
            issues, verified = _row_issues(pack, schema, row, unit, manifest, corpus)
            issues += _target_issues("supersedes", target, set(live_keys), used, "row")
            if not issues and verified is not None:
                occupied = accepted_keys | {
                    key for ident, key in live_keys.items() if ident not in used and ident != target
                }
                if verified[1] in occupied:
                    issues.append(ValidationIssue(f"fields.{VALUE_FIELD}", DUPLICATE_ROW))
            if issues or verified is None:
                row_errors.append(ItemError(index=index, issues=issues))
                continue
            if target is not None:
                used.add(target)
            accepted_keys.add(verified[1])
            accepted_rows.append(_Row(index, *verified))

        live_c = {c.claim_id for c in live_claims(project, unit.label, work_id=unit.work_id)}
        used_c: set[str] = set()
        claim_errors: list[ItemError] = []
        accepted_claims: list[tuple[int, ClaimInput]] = []
        for index, claim in enumerate(claims):
            target = claim_targets.get(index)
            issues = _claim_issues(schema, unit, claim, manifest)
            if not issues:
                issues = _target_issues("claim_supersedes", target, live_c, used_c, "claim")
            if issues:
                claim_errors.append(ItemError(index=index, issues=issues))
                continue
            if target is not None:
                used_c.add(target)
            accepted_claims.append((index, claim))

        closing = finish and not row_errors and not claim_errors
        reason = reason.strip() if reason is not None and reason.strip() else None
        # Live after this call: live before, minus the targets superseded, plus the new items.
        remaining_rows = sorted(set(live_keys) - used)
        remaining_claims = sorted(live_c - used_c)
        if (
            closing
            and reason is None
            and not (remaining_rows or accepted_rows or remaining_claims or accepted_claims)
        ):
            raise FactoryValidationError(
                [ValidationIssue("reason", "closing a unit with no row or claim needs a reason")]
            )
        if not (accepted_rows or accepted_claims or closing):
            return ExtractResult(
                rows=BatchResult[str](written=[], rejected=row_errors),
                claims=BatchResult[str](written=[], rejected=claim_errors),
                completed=False,
            )

        blob = project.blobs.put_json(
            {
                "task_id": task_id,
                "rows": [row.model_dump(mode="json") for row in rows],
                "claims": [claim.model_dump(mode="json") for claim in claims],
                "supersedes": {str(k): v for k, v in row_targets.items()},
                "claim_supersedes": {str(k): v for k, v in claim_targets.items()},
                "finish": finish,
                "reason": reason,
            }
        )
        events: list[Event] = []
        row_ids: list[str] = []
        for accepted in accepted_rows:
            extraction_id = project.ids.new("ext")
            payload = ExtractionRecorded(
                extraction_id=extraction_id,
                work_id=unit.work_id,
                pass_label=unit.label,
                task_id=task_id,
                protocol_id=protocol.protocol_id,
                schema_ref=unit.content.schema_ref,
                document_id=unit.document_id,
                conversion_id=unit.conversion_id,
                row_key=accepted.row_key,
                fields=accepted.fields,
                supersedes=row_targets.get(accepted.index),
                verifier=VERIFIER_VERSION,
            )
            events.append(
                project.events.make(
                    "extraction.recorded", payload, actor, refs=(extraction_id,), input_blob=blob
                )
            )
            row_ids.append(extraction_id)
        claim_ids: list[str] = []
        for index, claim in accepted_claims:
            claim_id = project.ids.new("clm")
            claim_payload = ClaimRecorded(
                claim_id=claim_id,
                work_id=unit.work_id,
                pass_label=unit.label,
                task_id=task_id,
                protocol_id=protocol.protocol_id,
                document_id=unit.document_id,
                conversion_id=unit.conversion_id,
                statement=claim.statement,
                claim_type=claim.claim_type,
                evidence_type=claim.evidence_type,
                strength=claim.strength,
                anchor=claim.anchor,
                quote=claim.quote,
                supersedes=claim_targets.get(index),
            )
            events.append(
                project.events.make(
                    "extraction.claim_recorded",
                    claim_payload,
                    actor,
                    refs=(claim_id,),
                    input_blob=blob,
                )
            )
            claim_ids.append(claim_id)
        if closing:
            events += _closing_events(
                project,
                actor,
                task,
                unit,
                reason,
                blob,
                sorted([*remaining_rows, *row_ids]),
                sorted([*remaining_claims, *claim_ids]),
            )
        project.record(events)
        if closing:
            done = get_task(project, task_id)
            if done is None or done.status is not TaskStatus.COMPLETED:
                raise FactoryValidationError(
                    [ValidationIssue("task_id", "lease expired before the event was recorded")]
                )
        return ExtractResult(
            rows=BatchResult[str](written=row_ids, rejected=row_errors),
            claims=BatchResult[str](written=claim_ids, rejected=claim_errors),
            completed=closing,
        )


def _unit_of(project: Project, task: Task) -> _Unit:
    """The extraction unit a task holds. Raises on `task_id` for any other task."""
    refusal = FactoryValidationError([ValidationIssue("task_id", "is not an extraction task")])
    if task.kind not in EXTRACT_KINDS.values():
        raise refusal
    try:
        content = ExtractBatchContent.model_validate(task_content(project, task))
    except ValidationError as exc:
        raise refusal from exc
    if task.kind != EXTRACT_KINDS[content.pass_label] or len(content.records) != 1:
        raise refusal
    record = content.records[0]
    if not {"work_id", "document_id", "conversion_id"} <= record.keys():
        raise refusal
    return _Unit(
        task_id=task.task_id,
        content=content,
        work_id=record["work_id"],
        document_id=record["document_id"],
        conversion_id=record["conversion_id"],
    )


def _targets(given: Mapping[int, str] | None, count: int, name: str) -> dict[int, str]:
    """The supersession map; refused (nothing written) when a key is not an index of the call."""
    targets = dict(given or {})
    if any(isinstance(k, bool) or not isinstance(k, int) or not 0 <= k < count for k in targets):
        raise FactoryValidationError(
            [ValidationIssue(name, "every key must be the index of an item of this call")]
        )
    return targets


def _target_issues(
    name: str, target: str | None, live: set[str], used: set[str], what: str
) -> list[ValidationIssue]:
    """Why a correction may not supersede `target`: it must be a live item of the same work and
    pass, not already corrected by an accepted item of this call. The caller marks a target used
    only when its item is accepted."""
    if target is None:
        return []
    if target in used:
        return [ValidationIssue(name, f"this {what} is already corrected in this call")]
    if target not in live:
        return [ValidationIssue(name, f"is not a live {what} of this work and pass")]
    return []


def _row_issues(
    pack: Pack,
    schema: ExtractionSchema,
    row: ExtractedRowInput,
    unit: _Unit,
    manifest: Manifest,
    corpus: set[str],
) -> tuple[list[ValidationIssue], tuple[dict[str, StoredField], str] | None]:
    """The issues of one row (re-validated, then verified), else its stored fields and key."""
    try:
        checked = ExtractedRowInput.model_validate(row.model_dump(mode="python"))
    except ValidationError as exc:
        return _loc_issues(exc), None
    verdict = verify_row_in(
        pack, schema.fields, checked.fields, unit.conversion_id, manifest, corpus
    )
    if verdict.issues or verdict.fields is None or verdict.row_key is None:
        return list(verdict.issues), None
    return [], (verdict.fields, verdict.row_key)


def _claim_issues(
    schema: ExtractionSchema, unit: _Unit, claim: ClaimInput, manifest: Manifest
) -> list[ValidationIssue]:
    """Why a claim may not be written: claims disabled or not pass A, invalid input, or a quote
    not verbatim in its anchor's element (as a field quote). Reasons never carry document text."""
    if not schema.claims:
        return [ValidationIssue("claims", "the extraction schema does not record claims")]
    if unit.label is not PassLabel.A:
        return [ValidationIssue("claims", "claims are recorded by pass A only")]
    try:
        checked = ClaimInput.model_validate(claim.model_dump(mode="python"))
    except ValidationError as exc:
        return _loc_issues(exc)
    anchor = manifest.get(checked.anchor)
    if anchor is None:
        return [ValidationIssue("anchor", ANCHOR_UNKNOWN)]
    if not quote_in_element(anchor.text, checked.quote):
        return [ValidationIssue("quote", QUOTE_NOT_IN_ANCHOR)]
    return []


def _loc_issues(exc: ValidationError) -> list[ValidationIssue]:
    return [
        ValidationIssue(".".join(map(str, err["loc"])) or "item", str(err["msg"]))
        for err in exc.errors()
    ]


def _closing_events(
    project: Project,
    actor: Actor,
    task: Task,
    unit: _Unit,
    reason: str | None,
    blob: str,
    row_ids: list[str],
    claim_ids: list[str],
) -> list[Event]:
    """`extraction.closed` with the computed live counts, and the task's completion with the live
    row ids then claim ids as its results (the payload and input blob `complete_task` writes)."""
    closed = ExtractionClosed(
        work_id=unit.work_id,
        pass_label=unit.label,
        task_id=unit.task_id,
        rows=len(row_ids),
        claims=len(claim_ids),
        reason=reason,
    )
    completed = TaskCompleted(task_id=unit.task_id, result_refs=(*row_ids, *claim_ids))
    return [
        project.events.make(
            "extraction.closed", closed, actor, refs=(unit.task_id,), input_blob=blob
        ),
        project.events.make(
            "task.completed",
            completed,
            actor,
            refs=(unit.task_id,),
            input_blob=task.content_blob,
        ),
    ]


def _require_same_schema(
    project: Project, unit: _Unit, schema: ExtractionSchema, pack: Pack
) -> None:
    """Refuse a stale task (ruling 12): the current schema's pack, version or declared fields
    differ from what the task served. Any other amendment leaves the task valid."""
    config = pass_config(project, unit.label)
    order = "reversed" if unit.label is PassLabel.B else "schema"
    if config is not None:
        order = config.field_order
    same_ref = unit.content.schema_ref == f"{schema.pack}@{schema.pack_version}"
    if not same_ref or _fields(pack, schema, order) != unit.content.fields:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "task_id",
                    "the extraction schema changed since this task was served; release the "
                    "task and call extract_next for a task under the current schema",
                )
            ]
        )


# --- Reading recorded rows and claims ---


def live_rows(
    project: Project, pass_label: PassLabel | None = None, *, work_id: str | None = None
) -> list[ExtractionRow]:
    """The rows no later row supersedes, optionally of one pass and one work, by extraction id."""
    project.index.sync()
    where, params = _filters(pass_label, work_id)
    with project.index.connect() as conn:
        heads = (
            conn.execute(
                text(
                    "SELECT extraction_id, work_id, pass_label, task_id, protocol_id, "
                    "conversion_id, document_id, row_key, schema_ref, event_id "
                    f"FROM extraction_rows WHERE superseded_by IS NULL{where} "
                    "ORDER BY extraction_id"
                ),
                params,
            )
            .mappings()
            .all()
        )
        cells: dict[str, list[Mapping[str, Any]]] = {str(h["extraction_id"]): [] for h in heads}
        if cells:
            marks = ", ".join(f":e{i}" for i in range(len(cells)))
            found = (
                conn.execute(
                    text(f"SELECT * FROM extraction_fields WHERE extraction_id IN ({marks})"),
                    {f"e{i}": ident for i, ident in enumerate(cells)},
                )
                .mappings()
                .all()
            )
            for cell in found:
                cells[str(cell["extraction_id"])].append(dict(cell))
    out: list[ExtractionRow] = []
    for head in heads:
        pack = _pack_of(str(head["schema_ref"]))
        ident = str(head["extraction_id"])
        out.append(
            ExtractionRow(
                extraction_id=ident,
                work_id=str(head["work_id"]),
                pass_label=PassLabel(str(head["pass_label"])),
                task_id=str(head["task_id"]),
                protocol_id=str(head["protocol_id"]),
                conversion_id=str(head["conversion_id"]),
                document_id=str(head["document_id"]),
                row_key=str(head["row_key"]),
                fields={str(c["field"]): _stored_field(pack, c) for c in cells[ident]},
                event_id=str(head["event_id"]),
            )
        )
    return out


def live_claims(
    project: Project, pass_label: PassLabel | None = None, *, work_id: str | None = None
) -> list[ClaimRow]:
    """The claims no later claim supersedes, optionally of one pass and one work, by claim id."""
    project.index.sync()
    where, params = _filters(pass_label, work_id)
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT claim_id, work_id, pass_label, claim_type, evidence_type, strength, "
                    "statement, anchor, quote, conversion_id, event_id FROM extraction_claims "
                    f"WHERE superseded_by IS NULL{where} ORDER BY claim_id"
                ),
                params,
            )
            .mappings()
            .all()
        )
    return [ClaimRow.model_validate(dict(row)) for row in rows]


def _filters(pass_label: PassLabel | None, work_id: str | None) -> tuple[str, dict[str, str]]:
    where = ""
    params: dict[str, str] = {}
    if pass_label is not None:
        where += " AND pass_label = :label"
        params["label"] = pass_label.value
    if work_id is not None:
        where += " AND work_id = :work"
        params["work"] = work_id
    return where, params


def _pack_of(schema_ref: str) -> Pack | None:
    name, _, version = schema_ref.rpartition("@")
    return get_pack(name, int(version)) if version.isdigit() else None


def _stored_field(pack: Pack | None, cell: Mapping[str, Any]) -> StoredField:
    """A stored field from its projected row: the value as text, or a boolean for a BOOL field."""
    definition = None if pack is None else pack.field(str(cell["field"]))
    raw = str(cell["value"])
    value: str | bool = raw
    if definition is not None and definition.kind is FieldKind.BOOL and raw in ("True", "False"):
        value = raw == "True"
    return StoredField(
        value=value,
        unit=cell["unit"],
        anchor=cell["anchor"],
        cell=cell["cell"],
        quote=cell["quote"],
        reported_in=ReportedIn(cell["reported_in"]),
        reproduced=bool(cell["reproduced"]),
        cited_work=cell["cited_work"],
        canonical=cell["canonical"],
        copy_marker=bool(cell["copy_marker"]),
    )

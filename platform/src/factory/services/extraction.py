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
"""

import hashlib
import secrets
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from pydantic import JsonValue
from sqlalchemy import text

from factory.clock import format_ts
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.base import StrictModel
from factory.model.extraction import ExtractionPassJoined, ExtractionPassOpened
from factory.model.protocol import ExtractionSchema, ProtocolStatus, ScreeningStage
from factory.model.screening import Channel, PassLabel
from factory.model.task import Task, TaskStatus
from factory.packs import Pack, get_pack
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.protocol import ProtocolVersion, current_protocol
from factory.services.screening import _is_label_session
from factory.services.search import list_works
from factory.services.stages import EXTRACT_KINDS, screening_plan
from factory.services.tasks import TaskSpec, build_task_events, claim_next, get_task, task_content

__all__ = [
    "EXTRACT_KINDS",
    "ExtractBatch",
    "ExtractBatchContent",
    "ExtractNext",
    "PassConfig",
    "extract_next",
    "extraction_population",
    "in_dual_sample",
    "is_extraction_session",
    "join_extraction_pass",
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

"""Extraction passes, their sessions, and the tasks an agent extracts (R-13, decision 37).

Pass A extracts every work that full-text screening included; pass B extracts the dual sample
(`ExtractionSchema.dual_extract_sample`, None = every work) with the fields in reverse order. Each
pass is opened once, with a seed; B's seed orders the sample. One task holds one work of one pass
and pins the document and conversion read: both passes of a work share the pin of its latest task
while that task's document is the work's current one (`unit_pin`, ruling 5), so a later
conversion of the same document never changes a queued or served task.

A unit (one work in one pass) is stale when an amendment recorded after its closing stales one of
its live rows or all rows (`ProtocolAmended.extraction_stale`, ruling 12), or when its latest
task pins a document that is no longer the work's current one; a served task is stale when the
schema it served differs from the current one. A stale unit gets a new task under the current
schema and pin; the stale task is never served again and nothing in the log is edited.

A session joins one extraction pass. It is refused from the other pass, from a model that already
serves the other pass, from a session that joined any screening pass, and from a session that
relayed a human label over MCP (it could read an answer key). A refusal raises
FactoryValidationError and writes nothing.

Every pass, task, row, closing and read belongs to one scope (slice 3b ruling 6): `evidence`
(`extraction_schema`, tasks `extract_a`/`extract_b`) or `contribution` (`contribution_schema`,
tasks `contrib_a`/`contrib_b`, population G1's `included_works`). Each scope keeps its own passes,
seeds, units, pins and staleness; every read defaults to evidence, and a session joins at most one
pass across both scopes (ruling 2); a model is independent only within a scope, since agreement
compares A with B inside one scope (decision 37). Evidence events leave `pack` null (their
payloads now hold `"pack": null`, and rows `"cited": null`, which replay as before); contribution
events carry `pack = contribution`. A contribution row is also stale when it cites a reference
extraction that is no longer its work's current G1 extraction; its unit is stale (reason
`references`) when that extraction was replaced after the task that closed the unit was created.

Invariants:
- Nothing is queued until the protocol is ready and declares an extraction schema of a known pack
  and a full-text screening plan (R-13).
- `extraction_population` is exactly the works whose full-text outcome is INCLUDED, sorted.
- A unit gets a new task only when it has none or its latest task is stale; only the latest task
  of a unit of the population, when not stale, is served; `extract_next` is idempotent while the
  session holds a live claim on such a task.
- A row is stale when an amendment recorded after it stales it (by recording order, decision 50,
  as `model.staleness`), or when it pins a document other than the work's current one. Stale
  rows stay live and readable but count neither as duplicates nor in a closing.
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
import json
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Literal

from pydantic import Field, JsonValue, ValidationError
from sqlalchemy import RowMapping, text

from factory.clock import format_ts
from factory.document.anchors import Manifest
from factory.document.quotes import quote_in_element
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.extraction.verify import ANCHOR_UNKNOWN, QUOTE_NOT_IN_ANCHOR
from factory.model.base import StrictModel
from factory.model.extraction import (
    CONTRIBUTION_SCOPE_NAME,
    VERIFIER_VERSION,
    CitedEntry,
    ClaimInput,
    ClaimRecorded,
    ClaimType,
    EvidenceType,
    ExtractedRowInput,
    ExtractionClosed,
    ExtractionPassJoined,
    ExtractionPassOpened,
    ExtractionRecorded,
    ExtractionRejected,
    MinerScope,
    ReportedIn,
    Scope,
    ScopeKey,
    StoredField,
    Strength,
    UnitReferences,
    pack_tag,
    scope_from_value,
    scope_of_pack,
    scope_of_schema_ref,
)
from factory.model.mine_imports import MINE_IMPORT_PREFIX
from factory.model.notices import WorkNoticeState
from factory.model.protocol import ExtractionSchema, ProtocolAmended, ProtocolStatus, ScreeningStage
from factory.model.screening import PassLabel
from factory.model.staleness import (
    RowRef,
    notice_stale_rows,
    scope_rule,
    stale_rows,
    touches,
)
from factory.model.task import ReportedUsage, Task, TaskCompleted, TaskStatus
from factory.packs import FieldKind, Pack, get_pack
from factory.services import passes
from factory.services.agreement import Outcome, final_outcomes
from factory.services.budgets import budget_issue, require_for, spent_for, task_unit
from factory.services.call_memo import memoised
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.document_read import ConversionRef, default_conversion
from factory.services.extraction_verify import VALUE_FIELD, verify_row_in
from factory.services.notices import work_states
from factory.services.protocol import ProtocolVersion, amendments_with_events, current_protocol
from factory.services.references import current_extraction, included_works
from factory.services.results import BatchResult, ItemError
from factory.services.screening import _is_label_session, relayed_extraction_label
from factory.services.search import list_works
from factory.services.stages import (
    EXTRACT_KINDS,
    is_mine_kind,
    kinds_for,
    scope_of_kind,
    screening_plan,
)
from factory.services.tasks import (
    TaskSpec,
    build_task_events,
    claim_next,
    get_task,
    holds_live_claim,
    require_holder,
    session_in_layer,
    task_content,
)

__all__ = [
    "DUPLICATE_ITEM",
    "DUPLICATE_ROW",
    "EXTRACT_KINDS",
    "ClaimRow",
    "CloseCheck",
    "ContentHook",
    "ContributionBatch",
    "ContributionBatchContent",
    "ExtraCheck",
    "ExtraVerdict",
    "ExtractBatch",
    "ExtractBatchContent",
    "ExtractNext",
    "ExtractResult",
    "ExtractionRow",
    "ImportItem",
    "PassConfig",
    "UnitPin",
    "UnitState",
    "extract_next",
    "extract_record",
    "extraction_population",
    "filled_imports",
    "import_items",
    "imported_rows",
    "imports_policy",
    "in_dual_sample",
    "is_extraction_session",
    "join_extraction_pass",
    "live_claims",
    "live_rows",
    "mined_works",
    "next_unit",
    "pass_config",
    "record_unit",
    "recorded_row",
    "require_schema",
    "scope_population",
    "scope_rows",
    "screening_session",
    "session_scope",
    "stale_claims",
    "stale_documents",
    "stale_extractions",
    "unit_pin",
    "unit_states",
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
CONTRIBUTION_INSTRUCTIONS = (
    "Record the contribution items the pinned document states. Read it with document_read. "
    "Give each item its item_kind and the fields that kind requires, each text field with the "
    "verbatim quote that contains it and its anchor. Never paraphrase a quote or infer an item "
    "the document does not state; record an absent base idea or limitation as not-stated."
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


class ContributionBatchContent(ExtractBatchContent):
    """Content of a contribution task: the batch plus the unit's reference list and the pack's
    conditional rules as fixed sentences. Lives here, not in `model`, because it extends
    `ExtractBatchContent`."""

    references: UnitReferences
    item_rules: list[str]


class MineBatchContent(ExtractBatchContent):
    """Content of a registered miner's task: the batch plus the miner's identity and the anchors
    its selector selects in the pinned conversion (ids only, never document text). Lives here
    because it extends `ExtractBatchContent`; `calibration_id` names the calibration the task
    belongs to (M-D)."""

    miner: str
    version: int
    digest: str
    anchors: tuple[str, ...]
    calibration_id: str | None = None
    field_kinds: dict[str, str] = Field(default_factory=dict)
    descriptions: dict[str, str] = Field(default_factory=dict)


class ExtractBatch(ExtractBatchContent):
    """A task as served to a session: its content and the task that holds it."""

    task_id: str


class MineBatch(MineBatchContent):
    """A miner task as served: its content (with miner, digest and anchors) and the task."""

    task_id: str


class ContributionBatch(ContributionBatchContent):
    """A contribution task as served: its content (with references and item rules) and task."""

    task_id: str


class ExtractNext(StrictModel):
    """`batch` is None when nothing is served; `blocked` says why; `remaining` counts the works of
    this pass whose task is not yet completed. A contribution task is a `ContributionBatch`."""

    batch: ExtractBatch | ContributionBatch | MineBatch | None
    blocked: list[str]
    remaining: int


ContentHook = Callable[[Project, ExtractBatchContent], ExtractBatchContent]
"""Builds a task's stored content from the plan-D content when the task is created. It must keep
the records, pass, schema and fields; a contribution task's content is a
`ContributionBatchContent`."""


@dataclass(frozen=True)
class PassConfig:
    """What an opened pass recorded."""

    seed: int
    field_order: str


# --- Preconditions ---


_SECTIONS: dict[Scope, tuple[str, str]] = {
    Scope.EVIDENCE: ("extraction_schema", "extraction schema"),
    Scope.CONTRIBUTION: ("contribution_schema", "contribution schema"),
}


def require_schema(
    project: Project, *, scope: ScopeKey = Scope.EVIDENCE
) -> tuple[ProtocolVersion, ExtractionSchema, Pack]:
    """The ready protocol, the schema of `scope` and the schema's pack. Raises on field
    `protocol` when no ready protocol exists; on the scope's section (`extraction_schema` or
    `contribution_schema`) when none is declared (R-13); and on `<section>.pack` for an unknown
    pack or a pack of the other scope (the name `contribution` is reserved for its section)."""
    if isinstance(scope, MinerScope):
        from factory.services.mining import miner_schema  # mining imports this module

        return miner_schema(project, scope.name)
    protocol = current_protocol(project)
    if protocol is None or protocol.status is not ProtocolStatus.READY:
        raise FactoryValidationError(
            [ValidationIssue("protocol", "the protocol is not ready; record it ready first")]
        )
    section, title = _SECTIONS[scope]
    schema = (
        protocol.spec.contribution_schema
        if scope is Scope.CONTRIBUTION
        else protocol.spec.extraction_schema
    )
    if schema is None:
        raise FactoryValidationError(
            [ValidationIssue(section, f"declare the {title} in the protocol first (R-13)")]
        )
    if scope_of_pack(schema.pack) != scope:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    f"{section}.pack",
                    f"pack {schema.pack} does not belong in {section}; "
                    f"pack {CONTRIBUTION_SCOPE_NAME} is reserved for contribution_schema",
                )
            ]
        )
    pack = get_pack(schema.pack, schema.pack_version)
    if pack is None:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    f"{section}.pack",
                    f"unknown pack {schema.pack} version {schema.pack_version}",
                )
            ]
        )
    return protocol, schema, pack


@memoised
def extraction_population(project: Project) -> list[str]:
    """The works whose full-text screening outcome is INCLUDED, sorted. Raises on field
    `full_text_screening` when the protocol declares no full-text plan."""
    project.index.sync()
    protocol = current_protocol(project)
    if protocol is None:
        raise FactoryValidationError([ValidationIssue("protocol", "record a protocol first")])
    screening_plan(protocol, FT)
    return sorted(w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED)


def scope_population(project: Project, scope: ScopeKey) -> list[str]:
    """The works a scope extracts, sorted: `extraction_population` for evidence; G1's
    `included_works` for contribution (slice 3b ruling 9: a work without a current G1 extraction
    is included)."""
    if isinstance(scope, MinerScope):
        from factory.services.mining import miner_population  # mining imports this module

        return miner_population(project, scope.name)
    if scope is Scope.EVIDENCE:
        return extraction_population(project)
    project.index.sync()
    return included_works(project)


def calibration_sessions_of(project: Project, scope: ScopeKey) -> set[str]:
    """The sessions that served calibration tasks of a miner scope; empty for another scope."""
    if not isinstance(scope, MinerScope):
        return set()
    from factory.services.miner_independence import calibration_sessions  # imports mining

    return calibration_sessions(project, scope.name)


def calibration_first_closed(
    project: Project, scope: ScopeKey, calibration_id: str
) -> dict[str, str]:
    """For each work of a calibration with a completed calibration task, the id of its first one
    (task ids are time-ordered). A calibration is scored from these tasks only: it reads the
    calibration's own tasks, never the schema the miner's scope is listed under now, so a
    version's result depends neither on which version is listed nor on later staleness, and a
    unit mined again after it closed does not change it."""
    first: dict[str, str] = {}
    for task_id, status, content in _kind_tasks(project, scope, calibration_id):
        work = content.records[0]["work_id"]
        if status == TaskStatus.COMPLETED.value and (work not in first or task_id < first[work]):
            first[work] = task_id
    return first


def calibration_closed_works(project: Project, scope: ScopeKey, calibration_id: str) -> set[str]:
    """The works of a calibration that have a completed calibration task."""
    return set(calibration_first_closed(project, scope, calibration_id))


def calibration_works(project: Project, calibration_id: str) -> list[str]:
    """The works of a drawn calibration's sample, sorted. Read-only; the caller syncs the index."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT work_id FROM miner_calibration_units WHERE calibration_id = :c "
                "ORDER BY work_id"
            ),
            {"c": calibration_id},
        ).all()
    return [str(row[0]) for row in rows]


def calibration_task_ids(
    project: Project, scope: ScopeKey, calibration_id: str | None = None
) -> frozenset[str]:
    """The ids of the calibration tasks of a miner scope (those of one calibration when
    `calibration_id` is given, else of any); empty for another scope and, without reading a blob,
    for a miner that was never calibrated. Read-only; the caller syncs the index."""
    if not isinstance(scope, MinerScope):
        return frozenset()
    with project.index.connect() as conn:
        drawn = conn.execute(
            text("SELECT 1 FROM miner_calibrations WHERE name = :n LIMIT 1"), {"n": scope.name}
        ).first()
    if drawn is None:
        return frozenset()
    kinds = list(kinds_for(scope).values())
    marks = ", ".join(f":k{i}" for i in range(len(kinds)))
    with project.index.connect() as conn:
        rows = conn.execute(
            text(f"SELECT task_id, content_blob FROM tasks WHERE kind IN ({marks})"),
            {f"k{i}": kind for i, kind in enumerate(kinds)},
        ).all()
    found: set[str] = set()
    for task_id, blob in rows:
        content = project.blobs.get_json(str(blob))
        if (
            isinstance(content, dict)
            and content.get("miner") == scope.name
            and content.get("calibration_id") is not None
            and (calibration_id is None or content.get("calibration_id") == calibration_id)
        ):
            found.add(str(task_id))
    return frozenset(found)


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


def pass_config(
    project: Project, label: PassLabel, *, scope: ScopeKey = Scope.EVIDENCE
) -> PassConfig | None:
    """The seed and field order recorded when pass `label` of `scope` opened; None when it has
    not."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT random_seed, field_order FROM extraction_passes "
                "WHERE scope = :scope AND pass_label = :l"
            ),
            {"scope": scope.value, "l": label.value},
        ).one_or_none()
    return None if row is None else PassConfig(seed=int(row[0]), field_order=str(row[1]))


def is_extraction_session(project: Project, session: str) -> bool:
    """Whether the session has joined an extraction pass of either scope."""
    return passes.is_pass_session(project, session, module="extraction")


def session_scope(project: Project, session: str) -> ScopeKey | None:
    """The scope of the extraction pass the session joined; None when it joined none."""
    project.index.sync()
    joined = _joined(project, session)
    return None if joined is None else joined[0]


def unit_pin(
    project: Project, work_id: str, *, scope: ScopeKey = Scope.EVIDENCE
) -> tuple[str, str] | None:
    """The (document, conversion) the extraction of `work_id` in `scope` is pinned to, for both
    passes: the pin of its latest task of either pass of the scope, by task id, while that
    document is the work's current one (or the work has none); else the work's default conversion
    (ruling 5). None when no task of the work exists in the scope."""
    project.index.sync()
    ledger = _ledger(project, scope)
    if ledger.latest(work_id) is None:
        return None
    return ledger.pin(work_id)


def _content_model(scope: ScopeKey) -> type[ExtractBatchContent]:
    if isinstance(scope, MinerScope):
        return MineBatchContent
    return ContributionBatchContent if scope is Scope.CONTRIBUTION else ExtractBatchContent


def _kind_tasks(
    project: Project, scope: ScopeKey, calibration_id: str | None = None
) -> list[tuple[str, str, ExtractBatchContent]]:
    """Every task of the scope's kinds as (task id, status, content), in task-ID order. A miner's
    tasks are split by `calibration_id`: the production tasks (None) or one calibration's."""
    kinds = list(kinds_for(scope).values())
    marks = ", ".join(f":k{i}" for i in range(len(kinds)))
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT task_id, status, content_blob FROM tasks WHERE kind IN ({marks}) "
                "ORDER BY task_id"
            ),
            {f"k{i}": kind for i, kind in enumerate(kinds)},
        ).all()
    model = _content_model(scope)
    found = [
        (str(task_id), str(status), model.model_validate(project.blobs.get_json(str(blob))))
        for task_id, status, blob in rows
    ]
    if isinstance(scope, MinerScope):  # every miner shares the mine kinds: keep this miner's
        found = [
            t
            for t in found
            if isinstance(t[2], MineBatchContent)
            and t[2].miner == scope.name
            and t[2].calibration_id == calibration_id
        ]
    return found


def _joined(project: Project, session: str) -> tuple[ScopeKey, PassLabel] | None:
    """The (scope, pass) the session joined, if any (one per session, ruling 2)."""
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT scope, pass_label FROM extraction_sessions WHERE session = :s"),
            {"s": session},
        ).one_or_none()
    return None if row is None else (scope_from_value(str(row[0])), PassLabel(str(row[1])))


def _pass_models(project: Project, label: PassLabel, scope: ScopeKey) -> set[str]:
    """The models of the sessions of the pass; a miner's calibration sessions are not of its
    production passes and are left out (their independence is `miner_independence`'s)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT session, model FROM extraction_sessions "
                "WHERE scope = :scope AND pass_label = :l"
            ),
            {"scope": scope.value, "l": label.value},
        ).all()
    apart = calibration_sessions_of(project, scope)
    return {str(model) for session, model in rows if str(session) not in apart}


def screening_session(project: Project, session: str) -> bool:
    """Whether `session` joined a screening pass at any stage."""
    return passes.is_pass_session(project, session, module="screening")


def _other(label: PassLabel) -> PassLabel:
    return PassLabel.B if label is PassLabel.A else PassLabel.A


# --- Joining ---


def join_extraction_pass(
    project: Project, actor: Actor, label: PassLabel, *, scope: ScopeKey = Scope.EVIDENCE
) -> None:
    """Bind the session to extraction pass `label` of `scope`. Refused, with nothing written, when
    the actor is not an agent, when the session relayed a human label or joined a screening pass,
    when it already serves any other pass of either scope (field `pass`, ruling 2), or when its
    model already serves the other pass of the same scope. Joining the same pass again writes
    nothing."""
    with project.index.exclusive():
        project.index.sync()
        if _check_join(project, actor, label, scope):
            project.record([_join_event(project, actor, label, scope)])


def _scoped_name(scope: ScopeKey, label: PassLabel) -> str:
    if isinstance(scope, MinerScope):
        return f"miner {scope.name} pass {label.value}"
    prefix = "contribution " if scope is Scope.CONTRIBUTION else ""
    return f"{prefix}pass {label.value}"


def _check_join(
    project: Project, actor: Actor, label: PassLabel, scope: ScopeKey, *, calibration: bool = False
) -> bool:
    """True when a join must be written; raises on a refusal. A calibration session is exempt
    from the other-pass model rule: its model is not a production pass's (M-D ruling 2)."""
    if actor.kind != "agent" or actor.model is None:
        raise FactoryValidationError(
            [ValidationIssue("actor", "only an agent extractor joins a pass")]
        )
    joined = _joined(project, actor.session)
    if joined == (scope, label):
        return False
    if _is_label_session(project, actor.session) or relayed_extraction_label(
        project, actor.session
    ):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session relayed a human label and cannot extract")]
        )
    if screening_session(project, actor.session):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session joined a screening pass and cannot extract")]
        )
    if session_in_layer(project, actor.session):
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "session", "this session worked for the intuition layer and cannot extract"
                )
            ]
        )
    if joined is not None:
        raise FactoryValidationError(
            [ValidationIssue("pass", f"this session already extracts {_scoped_name(*joined)}")]
        )
    other = _other(label)
    if not calibration and actor.model in _pass_models(project, other, scope):
        raise FactoryValidationError(
            [ValidationIssue("model", f"{_scoped_name(scope, other)} already uses this model")]
        )
    return True


def _pack_tag(scope: ScopeKey) -> str | None:
    """The `pack` an event of `scope` carries: null for evidence, which projects as before G2."""
    return pack_tag(scope)


def _input(project: Project, actor: Actor, label: PassLabel, scope: ScopeKey) -> str | None:
    value: dict[str, JsonValue] = {"pass_label": label.value}
    if scope != Scope.EVIDENCE:
        value["scope"] = scope.value
    return project.blobs.put_json(value) if actor.kind == "agent" else None


def _join_event(project: Project, actor: Actor, label: PassLabel, scope: ScopeKey) -> Event:
    model = actor.model
    if model is None:
        raise FactoryValidationError(
            [ValidationIssue("actor", "only an agent extractor joins a pass")]
        )
    payload = ExtractionPassJoined(
        pass_label=label, session=actor.session, model=model, pack=_pack_tag(scope)
    )
    return project.events.make(
        "extraction.pass_joined", payload, actor, input_blob=_input(project, actor, label, scope)
    )


# --- Serving ---


def extract_next(project: Project, actor: Actor, label: PassLabel) -> ExtractNext:
    """Serve the next task of evidence extraction pass `label`: `next_unit` with scope
    evidence."""
    return next_unit(project, actor, label, scope=Scope.EVIDENCE)


def next_unit(
    project: Project,
    actor: Actor,
    label: PassLabel,
    *,
    scope: ScopeKey,
    content: ContentHook | None = None,
    calibration_id: str | None = None,
    reopened: frozenset[str] = frozenset(),
) -> ExtractNext:
    """Serve the next task of extraction pass `label` of `scope` to the session, or say why none
    is served.

    Refused (nothing written) for a non-agent, for a join the rules forbid, and until the protocol
    is ready with the scope's schema (and, for evidence, a full-text screening plan). Otherwise
    the session joins, the pass opens once, a task is queued for each unit of the pass that has
    none or whose latest task is stale (`unit_states`), and the next claimable task that is the
    latest, not stale, task of its unit is claimed. A session that already holds a live claim on
    such a task is served that task again; a stale task is never served. `remaining` counts the
    units of the pass that are not current. `ExtractionSchema.dual_extract_sample=None` means
    every work, so pass B then queues the whole population. `blocked` carries content-free
    reasons: how many works have no converted document, and that no work falls in the dual
    sample.

    `content`, when given, builds each new task's stored content from the plan-D content; a
    contribution task needs one returning a `ContributionBatchContent` (TypeError otherwise: a
    programming error, not input) and is served as a `ContributionBatch`.

    `calibration_id` (a miner scope's pass A only) restricts the pass to the units of that drawn
    calibration: its tasks are a ledger of their own, apart from the production tasks.

    `reopened` names works an import fills that are to be mined again: they are queued, and their
    first claimed task shadows the imported rows."""
    with project.index.exclusive():
        project.index.sync()
        protocol, schema, pack = require_schema(project, scope=scope)
        if calibration_id is not None and (label is not PassLabel.A or content is None):
            raise TypeError("a calibration pass is pass A of a miner with a content hook")
        population = (
            scope_population(project, scope)
            if calibration_id is None
            else calibration_works(project, calibration_id)
        )
        if scope != Scope.EVIDENCE and content is None:
            raise TypeError(f"a task of scope {scope.value} needs a content hook")
        if actor.kind != "agent" or actor.model is None:
            raise FactoryValidationError(
                [ValidationIssue("actor", "only an agent extractor joins a pass")]
            )
        needs_join = _check_join(
            project, actor, label, scope, calibration=calibration_id is not None
        )
        unit_kind = kinds_for(scope)[label]
        if not holds_live_claim(project, actor, unit_kind):
            require_for(project, actor, task_unit(unit_kind))
        events: list[Event] = []
        config = pass_config(project, label, scope=scope)
        if config is None:
            seed = secrets.randbits(32)
            order: Literal["schema", "reversed"] = "schema" if label is PassLabel.A else "reversed"
            config = PassConfig(seed=seed, field_order=order)
            events.append(
                project.events.make(
                    "extraction.pass_opened",
                    ExtractionPassOpened(
                        pass_label=label,
                        random_seed=seed,
                        field_order=order,
                        pack=_pack_tag(scope),
                    ),
                    actor,
                    input_blob=_input(project, actor, label, scope),
                )
            )
        if needs_join:
            events.append(_join_event(project, actor, label, scope))
        if (
            calibration_id is not None
        ):  # a unit closed once is never mined for the calibration again
            closed = calibration_closed_works(project, scope, calibration_id)
            population = [w for w in population if w not in closed]
        queue = _queue(label, population, config.seed, schema)
        queued, remaining, unconverted = _enqueue(
            project,
            actor,
            label,
            (protocol, schema, pack),
            config,
            queue,
            _ledger(project, scope, calibration_id, reopened),
            content,
        )
        blocked: list[str] = []
        if unconverted:
            blocked.append(f"{unconverted} works have no converted document")
        if label is PassLabel.B and population and not queue:
            blocked.append("no work falls in the dual sample")
        project.record([*events, *queued])
        ledger = _ledger(project, scope, calibration_id, reopened)
        servable = _servable(ledger, label, queue, schema, pack)
        task = _held(project, actor, unit_kind, servable)
        # A claim held on a stale task let the call through above; it pays for no new claim.
        spent = None if task is not None else spent_for(project, actor, task_unit(unit_kind))
        if spent is not None:
            blocked.append(budget_issue(spent).reason)
        elif task is None:
            task = claim_next(project, actor, unit_kind, task_ids=servable)
        batch = None if task is None else _batch(project, task, scope)
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
    declared: tuple[ProtocolVersion, ExtractionSchema, Pack],
    config: PassConfig,
    queue: list[str],
    ledger: "_Ledger",
    hook: ContentHook | None,
) -> tuple[list[Event], int, int]:
    """The `task.created` events for the units of `queue` lacking a current unit (no task, or a
    stale latest task), not yet recorded; how many units of the queue are not current; and how
    many of those have no converted document (never servable, so not counted as remaining).
    `hook` turns each task's plan-D content into its stored content (`_hooked`)."""
    protocol, schema, pack = declared
    scope = ledger.scope
    kind = kinds_for(scope)[label]
    instructions = (
        CONTRIBUTION_INSTRUCTIONS
        if scope is Scope.CONTRIBUTION
        else INSTRUCTIONS + (CLAIMS_INSTRUCTIONS if schema.claims else "")
    )
    titles = {work.id: work.title for work in list_works(project)}
    fields = _fields(pack, schema, config.field_order)
    specs: list[TaskSpec] = []
    unconverted = 0
    pending = 0
    for work_id in queue:
        state = ledger.state(work_id, label, schema, pack)
        if state.state == "current":
            continue
        pending += 1
        if state.state != "stale" and ledger.tasks.get((work_id, label)):
            continue  # its latest task waits or is served
        pin = ledger.pin(work_id)
        if pin is None:
            unconverted += 1  # not retrieved or not converted: nothing to extract from
            continue
        content = ExtractBatchContent(
            pass_label=label,
            instructions=instructions,
            protocol_id=protocol.protocol_id,
            schema_ref=_schema_ref(schema),
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
        if hook is not None:
            content = _hooked(project, hook, content, scope)
        specs.append(TaskSpec(kind=kind, content=content.model_dump(mode="json")))
    events, result = build_task_events(project, actor, specs)
    if result.rejected:
        raise FactoryValidationError([issue for item in result.rejected for issue in item.issues])
    return events, pending - unconverted, unconverted


def _hooked(
    project: Project, hook: ContentHook, base: ExtractBatchContent, scope: ScopeKey
) -> ExtractBatchContent:
    """The hook's content for `base`. It must keep what the ledger reads (pass, schema, fields,
    records) and, for a contribution task, be a `ContributionBatchContent`; anything else is a
    programming error (TypeError), never stored."""
    content = hook(project, base)
    if not isinstance(content, _content_model(scope)):
        raise TypeError(f"the content hook must return {_content_model(scope).__name__}")
    kept = ("pass_label", "protocol_id", "schema_ref", "fields", "required", "records")
    if any(getattr(content, name) != getattr(base, name) for name in kept):
        raise TypeError("the content hook must keep the task's pass, schema, fields and records")
    return content


def _servable(
    ledger: "_Ledger", label: PassLabel, queue: list[str], schema: ExtractionSchema, pack: Pack
) -> set[str]:
    """The tasks of the pass that may be served: for each unit of `queue`, its latest task when
    that task is neither completed nor stale."""
    out: set[str] = set()
    for work_id in queue:
        tasks = ledger.tasks.get((work_id, label))
        if not tasks or tasks[-1].status == TaskStatus.COMPLETED.value:
            continue
        if ledger.issue(work_id, label, tasks[-1], schema, pack) is None:
            out.add(tasks[-1].task_id)
    return out


def _schema_ref(schema: ExtractionSchema) -> str:
    return f"{schema.pack}@{schema.pack_version}"


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


def _held(project: Project, actor: Actor, kind: str, servable: set[str]) -> Task | None:
    """The live claim this session holds on a servable task of the pass (task `kind`), if any."""
    now = format_ts(project.clock.now())
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT task_id FROM tasks WHERE kind = :kind AND status = :claimed "
                "AND claim_session = :s AND lease_until > :now ORDER BY task_id"
            ),
            {
                "kind": kind,
                "claimed": TaskStatus.CLAIMED.value,
                "s": actor.session,
                "now": now,
            },
        ).all()
    held = [str(row[0]) for row in rows if str(row[0]) in servable]
    return get_task(project, held[0]) if held else None


def _batch(
    project: Project, task: Task, scope: ScopeKey
) -> ExtractBatch | ContributionBatch | MineBatch:
    content = task_content(project, task)
    fields = dict(content) if isinstance(content, dict) else {}
    model: type[ExtractBatch | ContributionBatch | MineBatch]
    if isinstance(scope, MinerScope):
        model = MineBatch
    else:
        model = ContributionBatch if scope is Scope.CONTRIBUTION else ExtractBatch
    return model.model_validate({**fields, "task_id": task.task_id})


# --- Recording ---

DUPLICATE_ROW = "a row for this location is already recorded; supersede it"
"""Why a row whose row_key a live row (or an earlier row of the call) of its unit holds is
rejected. Duplicate claims are not refused: a claim has no location key."""

DUPLICATE_ITEM = (
    "an item of this kind, name and metric is already recorded at this anchor; supersede it, "
    "or, for a distinct item, cite a finer anchor (the sentence or the table cell)"
)
"""The duplicate refusal for contribution items (passed as `record_unit(duplicate_reason=)`):
two results of one metric quoted from one paragraph share a row key (G2-A ruling 4)."""


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
    cited: CitedEntry | None = None

    @property
    def origin(self) -> Literal["local", "imported"]:
        """`imported` for a row of a `mine.imported` event, whose `task_id` is the import's id."""
        return "imported" if self.task_id.startswith(MINE_IMPORT_PREFIX) else "local"


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
    document_id: str
    conversion_id: str
    event_id: str


class ExtractResult(StrictModel):
    """What one `extract_record` call wrote and rejected, and whether it completed the task."""

    rows: BatchResult[str]
    claims: BatchResult[str]
    completed: bool


@dataclass(frozen=True)
class UnitPin:
    """The unit a recording hook judges: its task, work, pass, scope and pinned conversion."""

    task_id: str
    work_id: str
    pass_label: PassLabel
    scope: ScopeKey
    document_id: str
    conversion_id: str


@dataclass(frozen=True)
class ExtraVerdict:
    """A hook's verdict on one verified row: issues reject it; `cited` is stored on its event."""

    cited: CitedEntry | None
    issues: list[ValidationIssue]


ExtraCheck = Callable[
    [Project, UnitPin, Mapping[str, StoredField], Sequence[ExtractionRow]], ExtraVerdict
]
"""A scope-specific check of one verified row: the unit, the row's stored fields, and `seen`: the
unit's live, not stale rows (less those an accepted row of the call supersedes) plus the rows
accepted earlier in the same call. `seen` includes the row's own supersede target, which is still
live while its correction is judged; rows accepted earlier in the call have `event_id` "", since
they are not yet recorded."""

CloseCheck = Callable[
    [Project, UnitPin, Sequence[ExtractionRow], str | None], list[ValidationIssue]
]
"""A scope-specific closing rule: the unit, its rows live after the call, and the closing reason.
Any issue refuses the call, with nothing written."""


@dataclass(frozen=True)
class _Unit:
    """The work, pass, scope and pin of the task being recorded."""

    task_id: str
    content: ExtractBatchContent
    work_id: str
    document_id: str
    conversion_id: str
    scope: ScopeKey
    calibration_id: str | None = None

    @property
    def label(self) -> PassLabel:
        return self.content.pass_label

    def pin(self) -> UnitPin:
        return UnitPin(
            task_id=self.task_id,
            work_id=self.work_id,
            pass_label=self.label,
            scope=self.scope,
            document_id=self.document_id,
            conversion_id=self.conversion_id,
        )


@dataclass(frozen=True)
class _Row:
    index: int
    fields: dict[str, StoredField]
    row_key: str
    extraction_id: str
    cited: CitedEntry | None


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
    reported_usage: ReportedUsage | None = None,
) -> ExtractResult:
    """Record an evidence task: `record_unit` without hooks. A contribution task is refused on
    `task_id` (its items go through `contribution_record`, which supplies the hooks).
    `reported_usage` goes on the task's completion, shown and never enforced."""
    return _record(
        project,
        actor,
        task_id,
        rows,
        claims,
        _Options(
            finish,
            reason,
            supersedes,
            claim_supersedes,
            None,
            None,
            DUPLICATE_ROW,
            reported_usage,
        ),
        evidence_only=True,
    )


def record_unit(
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
    extra_check: ExtraCheck | None = None,
    close_check: CloseCheck | None = None,
    duplicate_reason: str = DUPLICATE_ROW,
) -> ExtractResult:
    """Record the rows and claims an agent extracted for a held task of either scope, and close
    it on `finish`.

    Refused, with nothing written, when the actor is not an agent (`actor`); the task is unknown,
    not held by this session or not an extraction task, or its schema reference is not of its
    kind's scope (`task_id`); the session does not extract the task's pass in the task's scope
    (`pass`); the current schema of the scope differs in pack, version or declared fields from
    what the task served (`task_id`, ruling 12; any other amendment is accepted and the events
    carry the current protocol id); the task is not the latest task of its unit, pins a document
    that is no longer the work's current one, or holds a work its scope's population no longer
    includes (`task_id`); a key of `supersedes` or `claim_supersedes` is not an index of the
    call (that name); `finish` would close a unit with no live row and no live claim without a
    non-blank `reason` (`reason`); or `close_check` returns an issue for a closing call.

    Otherwise each row is verified alone against the task's pinned conversion, then, when given,
    judged by `extra_check` (its issues reject the row like verification issues; its `cited` is
    stored on the row's event); each claim's quote is verified in its anchor's element like a
    field quote. An invalid item is an `ItemError` (issues located within the item, its index
    locating it) and is not written. Claims are rejected (`claims`) unless the schema enables
    them and the task is of pass A. `supersedes` maps a row index to the id of a live row of the
    same work and pass that the row corrects; any other target, or one target an accepted row
    already corrects, rejects that row (`supersedes`). A row whose row_key a live row of the unit
    holds (other than its own target), or an earlier accepted row of the call, is rejected
    (`fields.value`, `duplicate_reason`; contribution callers pass `DUPLICATE_ITEM`). Claims are
    superseded likewise with `claim_supersedes`; duplicate claims are not refused.

    `finish` closes the unit only when no item of the call is rejected: `extraction.closed`, with
    counts computed as the live items minus the superseded targets plus the accepted items, and
    `task.completed`, with those row ids then claim ids (each sorted) as results. Stale rows
    (`stale_extractions`) and stale claims (`stale_claims`) are neither duplicates, nor targets,
    nor counted, nor enough to close without a reason: a re-served unit starts afresh. The rows,
    claims, closure and completion are appended in one write; each extraction event carries the
    whole call's input as its input blob, stored only when something is appended.
    """
    return _record(
        project,
        actor,
        task_id,
        rows,
        claims,
        _Options(
            finish,
            reason,
            supersedes,
            claim_supersedes,
            extra_check,
            close_check,
            duplicate_reason,
        ),
        evidence_only=False,
    )


@dataclass(frozen=True)
class _Options:
    finish: bool
    reason: str | None
    supersedes: Mapping[int, str] | None
    claim_supersedes: Mapping[int, str] | None
    extra_check: ExtraCheck | None
    close_check: CloseCheck | None
    duplicate_reason: str
    reported_usage: ReportedUsage | None = None


def _record(
    project: Project,
    actor: Actor,
    task_id: str,
    rows: Sequence[ExtractedRowInput],
    claims: Sequence[ClaimInput],
    options: _Options,
    *,
    evidence_only: bool,
) -> ExtractResult:
    """`record_unit`; with `evidence_only`, a contribution task is refused on `task_id`."""
    finish = options.finish
    with project.index.exclusive():
        project.index.sync()
        if actor.kind != "agent" or actor.model is None:
            raise FactoryValidationError(
                [ValidationIssue("actor", "only an agent extractor records an extraction")]
            )
        task = require_holder(project, actor, task_id)
        unit = _unit_of(project, task)
        if evidence_only and unit.scope != Scope.EVIDENCE:
            miner = isinstance(unit.scope, MinerScope)
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "task_id",
                        "this is a miner task; use mine_record"
                        if miner
                        else "this is a contribution task; use contribution_record",
                    )
                ]
            )
        if _joined(project, actor.session) != (unit.scope, unit.label):
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "pass",
                        f"this session does not extract {_scoped_name(unit.scope, unit.label)}",
                    )
                ]
            )
        protocol, schema, pack = require_schema(project, scope=unit.scope)
        _require_same_schema(project, unit, schema, pack)
        ledger = _ledger(project, unit.scope, unit.calibration_id)
        _require_current_task(project, ledger, unit, schema, pack)
        stale = ledger.stale_rows()
        row_targets = _targets(options.supersedes, len(rows), "supersedes")
        claim_targets = _targets(options.claim_supersedes, len(claims), "claim_supersedes")
        manifest = conversion_manifest(project, unit.conversion_id)
        corpus = {work.id for work in list_works(project)}
        pin = unit.pin()

        live = {
            r.extraction_id: r
            for r in ledger.rows.get((unit.work_id, unit.label), [])
            if r.extraction_id not in stale
        }
        used: set[str] = set()
        row_errors: list[ItemError] = []
        accepted_rows: list[_Row] = []
        for index, row in enumerate(rows):
            target = row_targets.get(index)
            issues, verified = _row_issues(pack, schema, row, unit, manifest, corpus)
            cited: CitedEntry | None = None
            if not issues and verified is not None and options.extra_check is not None:
                seen = [r for ident, r in live.items() if ident not in used]
                seen += [_accepted_row(unit, protocol, a) for a in accepted_rows]
                verdict = options.extra_check(project, pin, verified[0], seen)
                issues += verdict.issues
                cited = verdict.cited
            issues += _target_issues("supersedes", target, set(live), used, "row")
            if not issues and verified is not None:
                occupied = {a.row_key for a in accepted_rows} | {
                    r.row_key for ident, r in live.items() if ident not in used and ident != target
                }
                if verified[1] in occupied:
                    issues.append(
                        ValidationIssue(f"fields.{VALUE_FIELD}", options.duplicate_reason)
                    )
            if issues or verified is None:
                row_errors.append(ItemError(index=index, issues=issues))
                continue
            if target is not None:
                used.add(target)
            accepted_rows.append(_Row(index, *verified, project.ids.new("ext"), cited))

        stale_c = ledger.stale_claims()
        live_c = {
            c.claim_id
            for c in ledger.claims.get((unit.work_id, unit.label), [])
            if c.claim_id not in stale_c
        }
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
        reason = options.reason
        reason = reason.strip() if reason is not None and reason.strip() else None
        # Live after this call: live before, minus the targets superseded, plus the new items.
        remaining_rows = sorted(set(live) - used)
        remaining_claims = sorted(live_c - used_c)
        if (
            closing
            and reason is None
            and not (remaining_rows or accepted_rows or remaining_claims or accepted_claims)
        ):
            raise FactoryValidationError(
                [ValidationIssue("reason", "closing a unit with no row or claim needs a reason")]
            )
        if closing and options.close_check is not None:
            after = [live[i] for i in remaining_rows]
            after += [_accepted_row(unit, protocol, a) for a in accepted_rows]
            refusals = options.close_check(project, pin, after, reason)
            if refusals:
                raise FactoryValidationError(refusals)
        if not (accepted_rows or accepted_claims or closing):
            _note_rejected_call(project, actor, task, task_id, rows)
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
            payload = ExtractionRecorded(
                extraction_id=accepted.extraction_id,
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
                cited=accepted.cited,
            )
            events.append(
                project.events.make(
                    "extraction.recorded",
                    payload,
                    actor,
                    refs=(accepted.extraction_id,),
                    input_blob=blob,
                )
            )
            row_ids.append(accepted.extraction_id)
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
                options.reported_usage,
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


def _note_rejected_call(
    project: Project,
    actor: Actor,
    task: Task,
    task_id: str,
    rows: Sequence[ExtractedRowInput],
) -> None:
    """Keep the submitted rows of a calibration call that recorded nothing, for its rate."""
    raw = task_content(project, task)
    if not rows or not isinstance(raw, dict) or raw.get("calibration_id") is None:
        return
    blob = project.blobs.put_json(
        {"task_id": task_id, "rows": [row.model_dump(mode="json") for row in rows]}
    )
    project.record(
        [
            project.events.make(
                "extraction.rejected",
                ExtractionRejected(task_id=task_id),
                actor,
                refs=(task_id,),
                input_blob=blob,
            )
        ]
    )


def _unit_of(project: Project, task: Task) -> _Unit:
    """The extraction unit a task holds, in the scope of its kind. Raises on `task_id` for any
    other task, and for one whose schema reference names a pack of the other scope."""
    refusal = FactoryValidationError([ValidationIssue("task_id", "is not an extraction task")])
    scope: ScopeKey | None = scope_of_kind(task.kind)
    raw = task_content(project, task)
    if scope is None and is_mine_kind(task.kind) and isinstance(raw, dict):
        miner = raw.get("miner")
        scope = MinerScope(miner) if isinstance(miner, str) else None
    if scope is None:
        raise refusal
    try:
        content = _content_model(scope).model_validate(raw)
    except ValidationError as exc:
        raise refusal from exc
    if task.kind != kinds_for(scope)[content.pass_label] or len(content.records) != 1:
        raise refusal
    if scope_of_schema_ref(content.schema_ref) != scope:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "task_id",
                    f"the task's schema {content.schema_ref} is not of its pass's scope "
                    f"({scope.value})",
                )
            ]
        )
    record = content.records[0]
    if not {"work_id", "document_id", "conversion_id"} <= record.keys():
        raise refusal
    return _Unit(
        task_id=task.task_id,
        content=content,
        work_id=record["work_id"],
        document_id=record["document_id"],
        conversion_id=record["conversion_id"],
        scope=scope,
        calibration_id=getattr(content, "calibration_id", None),
    )


def _accepted_row(unit: _Unit, protocol: ProtocolVersion, row: _Row) -> ExtractionRow:
    """A row accepted earlier in the call, as a hook sees it (not yet recorded: no event id)."""
    return ExtractionRow(
        extraction_id=row.extraction_id,
        work_id=unit.work_id,
        pass_label=unit.label,
        task_id=unit.task_id,
        protocol_id=protocol.protocol_id,
        conversion_id=unit.conversion_id,
        document_id=unit.document_id,
        row_key=row.row_key,
        fields=row.fields,
        event_id="",
        cited=row.cited,
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
    reported_usage: ReportedUsage | None,
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
        pack=_pack_tag(unit.scope),
    )
    completed = TaskCompleted(
        task_id=unit.task_id, result_refs=(*row_ids, *claim_ids), reported_usage=reported_usage
    )
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
    config = pass_config(project, unit.label, scope=unit.scope)
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


def _unit_population(project: Project, unit: _Unit) -> list[str]:
    """The works the unit's pass may extract: its calibration's sample, else its scope's."""
    if unit.calibration_id is not None:
        return calibration_works(project, unit.calibration_id)
    return scope_population(project, unit.scope)


def _require_current_task(
    project: Project, ledger: "_Ledger", unit: _Unit, schema: ExtractionSchema, pack: Pack
) -> None:
    """Refuse a task that is no longer its unit's current task: a later task replaced it, its
    document is no longer the work's current one, or the work left the population."""
    tasks = ledger.tasks.get((unit.work_id, unit.label), [])
    if (
        not tasks
        or tasks[-1].task_id != unit.task_id
        or ledger.issue(unit.work_id, unit.label, tasks[-1], schema, pack) is not None
        or unit.work_id not in _unit_population(project, unit)
    ):
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "task_id",
                    "this task is no longer current (a newer task or document replaced it, or "
                    "the work is no longer included); release the task and call extract_next",
                )
            ]
        )


# --- Units and staleness ---


class UnitState(StrictModel):
    """One extraction unit: an included work in one pass in use, and whether its extraction is
    current. `queued`: no task yet, or its latest task waits unclaimed; `open`: its latest task
    is claimed; `current`: its latest task completed and is not stale; `stale`: its latest task
    is stale, `reason` saying why (`schema`, `document-version`, or, for a contribution unit,
    `references`: a live row cites a reference extraction that is no longer its work's current G1
    extraction, slice 3b ruling 12). `reason` is otherwise None."""

    work_id: str
    pass_label: PassLabel
    state: Literal["open", "current", "stale", "queued"]
    reason: str | None


@dataclass(frozen=True)
class _UnitTask:
    task_id: str
    status: str
    content: ExtractBatchContent

    @property
    def work_id(self) -> str:
        return self.content.records[0]["work_id"]

    @property
    def pin(self) -> tuple[str, str]:
        record = self.content.records[0]
        return record["document_id"], record["conversion_id"]


@dataclass
class _Ledger:
    """What staleness is judged from, read once (the caller has synced the index).

    `tasks` holds each unit's extraction tasks in task-ID order; `closed_at` the event ID of each
    task's `extraction.closed`; `rows` the live rows of each unit; `amendments` every amendment
    with its event ID, in recording order; `orders` each pass's field order. Everything is of one
    `scope`, whose amendment rule (`scope_rule`) alone stales its rows."""

    project: Project
    scope: ScopeKey
    tasks: dict[tuple[str, PassLabel], list[_UnitTask]]
    closed_at: dict[str, str]
    rows: dict[tuple[str, PassLabel], list[ExtractionRow]]
    amendments: list[tuple[str, ProtocolAmended]]
    orders: dict[PassLabel, str]
    claims: dict[tuple[str, PassLabel], list["ClaimRow"]]
    notice_states: Mapping[str, WorkNoticeState] = field(default_factory=dict)
    """Per-work notice states (living-C); only an `affects` assessment's marks stale a row."""
    documents: dict[str, ConversionRef | None] = field(default_factory=dict)
    references: dict[str, str | None] = field(default_factory=dict)
    created: dict[str, str] = field(default_factory=dict)
    imported: dict[str, list[ExtractionRow]] = field(default_factory=dict)
    """Each work's live imported rows (M-E), kept apart from `rows`: they have no task and no pass
    here, so a mined row neither collides with one nor supersedes one. Empty when the protocol
    declines imports, and for a calibration."""
    reopened: frozenset[str] = frozenset()
    """Imported works to queue again: their source was corrected (`mine_next`). They stay filled
    (their rows in use) until a local row or claimed task shadows them."""
    _filled: set[str] | None = None

    def filled(self) -> set[str]:
        """The works an import fills: a unit counts as current through its imported rows, so it is
        not queued, while no local row or claimed task shadows them and none of them is stale (a
        queued, unserved task shadows nothing). A reopened work stays filled, so its imported rows
        stand and its source flag stays live, until its first task is claimed."""
        if self._filled is None:
            local = {
                work
                for (work, _), tasks in self.tasks.items()
                if any(t.status != TaskStatus.OPEN.value for t in tasks)
            } | {work for work, _ in self.rows}
            stale = self.stale_rows() if self.imported else set()
            self._filled = {
                work
                for work, rows in self.imported.items()
                if work not in local and not any(row.extraction_id in stale for row in rows)
            }
        return self._filled

    def reference_extraction(self, work_id: str) -> str | None:
        """The work's current G1 reference extraction (`current_extraction`), read once."""
        if work_id not in self.references:
            self.references[work_id] = current_extraction(self.project, work_id)
        return self.references[work_id]

    def cites_old_references(self, row: ExtractionRow) -> bool:
        """Whether `row` cites a reference extraction other than its work's current one."""
        return (
            row.cited is not None
            and row.cited.reference_extraction_id != self.reference_extraction(row.work_id)
        )

    def current(self, work_id: str) -> ConversionRef | None:
        """The work's default conversion; its document is the work's current document."""
        if work_id not in self.documents:
            self.documents[work_id] = default_conversion(self.project, work_id)
        return self.documents[work_id]

    def latest(self, work_id: str) -> _UnitTask | None:
        """The latest task of the work in either pass, by task id."""
        found = [t for label in PassLabel for t in self.tasks.get((work_id, label), [])]
        return max(found, key=lambda t: t.task_id) if found else None

    def pin(self, work_id: str) -> tuple[str, str] | None:
        """The pin a new task of the work gets (ruling 5): the latest task's while its document
        is current (or the work has no current document), else the default conversion."""
        latest = self.latest(work_id)
        current = self.current(work_id)
        if latest is not None and (current is None or latest.pin[0] == current.document_id):
            return latest.pin
        return None if current is None else (current.document_id, current.conversion_id)

    def issue(
        self,
        work_id: str,
        label: PassLabel,
        task: _UnitTask,
        schema: ExtractionSchema,
        pack: Pack,
    ) -> str | None:
        """Why `task` of the unit is stale, or None. `document-version`: it pins a document
        other than the work's current one. `schema`: for a task not completed, the current
        schema's reference or fields differ from what it served; for a completed one, an
        amendment recorded after its closing position (`closed_at`) stales all rows or a live
        row of the unit that was not already stale at that position (pinned to a replaced
        document, or staled by an amendment recorded between the row and the closing).
        `references`: a completed task's carried row cites a reference extraction replaced after
        that task was created, so no agent of the task saw the replacement. A row whose citation
        was replaced before the task was created stays live and stale but never re-queues the
        unit, as it cannot be superseded."""
        current = self.current(work_id)
        if current is not None and task.pin[0] != current.document_id:
            return "document-version"
        if task.status != TaskStatus.COMPLETED.value:
            served = task.content.schema_ref, task.content.fields
            if served != (_schema_ref(schema), _fields(pack, schema, self.orders[label])):
                return "schema"
            return None
        closed = self.closed_at.get(task.task_id, "")
        carried = [
            row
            for row in self.rows.get((work_id, label), [])
            if (current is None or row.document_id == current.document_id)
            and not self._stale_by(row, closed)
        ]
        for when, amendment in self.amendments:
            rule = scope_rule(amendment, self.scope)
            if rule is None or when <= closed:
                continue
            if rule.all_records or any(touches(rule, tuple(r.fields)) for r in carried):
                return "schema"
        state = self.notice_states.get(work_id)
        if state is not None and any(
            mark.assessed_at > closed and set(mark.fields) & set(r.fields)
            for mark in state.stale_marks
            for r in carried
        ):
            return "notice"
        # Deliberate: a task created after the replacement may close the unit current with a
        # reason alone; its agent saw the new list, and the old row stays in `stale_extractions`.
        if any(self._replaced_after(row, task.task_id) for row in carried):
            return "references"
        return None

    def _created_at(self, task_id: str) -> str:
        """The event ID of the task's `task.created`. Read from the log, as the projection keeps
        none, once per ledger and only when a row cites a replaced extraction."""
        if not self.created:
            wanted = {t.task_id for unit in self.tasks.values() for t in unit}
            for event in read_all(self.project.paths.events_dir, self.project.catalog):
                if event.type == "task.created" and event.payload.get("task_id") in wanted:
                    self.created[str(event.payload["task_id"])] = event.id
        return self.created[task_id]

    def _replaced_after(self, row: ExtractionRow, task_id: str) -> bool:
        """Whether the reference extraction `row` cites is not current and the next extraction of
        its work was recorded after `task_id` was created. With no later extraction (a new
        conversion or parser left the work without a current one) the row is stale but the unit
        waits: a new task could cite nothing newer, and the re-extraction that follows re-queues
        it."""
        if row.cited is None or not self.cites_old_references(row):
            return False
        with self.project.index.connect() as conn:
            replaced = conn.execute(
                text(
                    "SELECT MIN(later.event_id) FROM reference_extractions later "
                    "JOIN reference_extractions cited ON cited.extraction_id = :cited "
                    "WHERE later.work_id = cited.work_id AND later.event_id > cited.event_id"
                ),
                {"cited": row.cited.reference_extraction_id},
            ).scalar_one()
        return replaced is not None and str(replaced) > self._created_at(task_id)

    def _stale_by(self, row: ExtractionRow, position: str) -> bool:
        """Whether an amendment recorded after `row` and no later than `position` stales it."""
        for when, amendment in self.amendments:
            rule = scope_rule(amendment, self.scope)
            if (
                rule is not None
                and row.event_id < when <= position
                and touches(rule, tuple(row.fields))
            ):
                return True
        state = self.notice_states.get(row.work_id)
        return state is not None and any(
            row.event_id < mark.assessed_at <= position and set(mark.fields) & set(row.fields)
            for mark in state.stale_marks
        )

    def stale_claims(self) -> set[str]:
        """The live claims pinned to a document other than the work's current one. Schema
        amendments never stale a claim."""
        stale: set[str] = set()
        for claims in self.claims.values():
            for claim in claims:
                current = self.current(claim.work_id)
                if current is not None and claim.document_id != current.document_id:
                    stale.add(claim.claim_id)
        return stale

    def state(
        self, work_id: str, label: PassLabel, schema: ExtractionSchema, pack: Pack
    ) -> UnitState:
        tasks = self.tasks.get((work_id, label))
        if not tasks:
            empty: Literal["current", "queued"] = (
                "current" if work_id in self.filled() and work_id not in self.reopened else "queued"
            )
            return UnitState(work_id=work_id, pass_label=label, state=empty, reason=None)
        latest = tasks[-1]
        reason = self.issue(work_id, label, latest, schema, pack)
        if reason is not None:
            return UnitState(work_id=work_id, pass_label=label, state="stale", reason=reason)
        status: Literal["open", "current", "queued"] = "queued"
        if latest.status == TaskStatus.COMPLETED.value:
            status = "current"
        elif latest.status == TaskStatus.CLAIMED.value:
            status = "open"
        return UnitState(work_id=work_id, pass_label=label, state=status, reason=None)

    def stale_rows(self) -> set[str]:
        """The live rows an amendment recorded after them stales, or that pin a document other
        than the work's current one."""
        live = [row for rows in (*self.rows.values(), *self.imported.values()) for row in rows]
        refs = [RowRef(row_id=r.extraction_id, fields=tuple(r.fields), at=r.event_id) for r in live]
        stale = set(
            stale_rows(
                [a for _, a in self.amendments],
                [w for w, _ in self.amendments],
                refs,
                scope=self.scope,
            )
        )
        stale.update(
            notice_stale_rows(
                self.notice_states,
                [(r.work_id, r.extraction_id, ref) for r, ref in zip(live, refs, strict=True)],
            )
        )
        for row in live:
            current = self.current(row.work_id)
            replaced = current is not None and row.document_id != current.document_id
            if replaced or self.cites_old_references(row):
                stale.add(row.extraction_id)
        return stale


def _ledger(
    project: Project,
    scope: ScopeKey = Scope.EVIDENCE,
    calibration_id: str | None = None,
    reopened: frozenset[str] = frozenset(),
) -> _Ledger:
    """Read the ledger of `scope`, or of one calibration of a miner scope; the caller has synced
    the index."""
    tasks: dict[tuple[str, PassLabel], list[_UnitTask]] = {}
    for task_id, status, content in _kind_tasks(project, scope, calibration_id):
        if len(content.records) != 1:
            continue
        task = _UnitTask(task_id, status, content)
        tasks.setdefault((task.work_id, content.pass_label), []).append(task)
    with project.index.connect() as conn:
        closed_at = {
            str(task_id): str(event_id)
            for task_id, event_id in conn.execute(
                text("SELECT task_id, event_id FROM extraction_closures WHERE scope = :scope"),
                {"scope": scope.value},
            )
        }
    unclosed = {
        t.task_id
        for unit in tasks.values()
        for t in unit
        if t.status == TaskStatus.COMPLETED.value and t.task_id not in closed_at
    }
    closed_at.update(_completion_positions(project, unclosed))
    rows: dict[tuple[str, PassLabel], list[ExtractionRow]] = {}
    own = {t.task_id for unit in tasks.values() for t in unit}
    for row in live_rows(project, scope=scope, calibration=calibration_id is not None):
        if calibration_id is None or row.task_id in own:
            rows.setdefault((row.work_id, row.pass_label), []).append(row)
    claims: dict[tuple[str, PassLabel], list[ClaimRow]] = {}
    if scope is Scope.EVIDENCE:  # contribution items carry no claims
        for claim in live_claims(project):
            claims.setdefault((claim.work_id, claim.pass_label), []).append(claim)
    orders: dict[PassLabel, str] = {}
    for label in PassLabel:
        config = pass_config(project, label, scope=scope)
        default = "schema" if label is PassLabel.A else "reversed"
        orders[label] = default if config is None else config.field_order
    imported: dict[str, list[ExtractionRow]] = {}
    if calibration_id is None:
        found = imported_rows(project, scope)
        if found and imports_policy(project, scope) != "deny":
            for row in found:
                imported.setdefault(row.work_id, []).append(row)
    return _Ledger(
        project,
        scope,
        tasks,
        closed_at,
        rows,
        amendments_with_events(project),
        orders,
        claims,
        notice_states=work_states(project),
        imported=imported,
        reopened=reopened,
    )


def _completion_positions(project: Project, task_ids: set[str]) -> dict[str, str]:
    """The closing position of completed tasks without `extraction.closed`: the event ID of the
    first `task.completed` naming the task, else of its `task.created`. Read from the log (the
    projection keeps neither), and only when such a task exists."""
    if not task_ids:
        return {}
    completed: dict[str, str] = {}
    created: dict[str, str] = {}
    for event in read_all(project.paths.events_dir, project.catalog):
        task_id = event.payload.get("task_id")
        if task_id not in task_ids:
            continue
        if event.type == "task.completed":
            completed.setdefault(str(task_id), event.id)
        elif event.type == "task.created":
            created.setdefault(str(task_id), event.id)
    return {t: completed.get(t, created.get(t, "")) for t in task_ids}


def stale_extractions(
    project: Project, *, scope: ScopeKey = Scope.EVIDENCE, calibration_id: str | None = None
) -> set[str]:
    """The live rows of `scope` that are stale: made stale by an amendment of the scope's section
    recorded after the row (ruling 12, compared by event ID as `model.staleness` does, so a
    reverted amendment keeps recording order), pinned to a document that is no longer the work's
    current one, or (contribution) citing a reference extraction that is no longer the work's
    current G1 extraction. It ignores the population: rows of works no longer included are
    filtered downstream. Read-only."""
    project.index.sync()
    return _ledger(project, scope, calibration_id).stale_rows()


def all_scopes(project: Project) -> list[ScopeKey]:
    """Every scope with rows or passes: evidence, contribution and each registered miner whose
    pass opened. Read-only; the caller has synced the index."""
    with project.index.connect() as conn:
        opened = conn.execute(text("SELECT DISTINCT scope FROM extraction_passes")).all()
    found = {scope_from_value(str(row[0])) for row in opened}
    miners = sorted((s for s in found if isinstance(s, MinerScope)), key=lambda s: s.name)
    return [Scope.EVIDENCE, Scope.CONTRIBUTION, *miners]


def abandoned_task_ids(project: Project) -> set[str]:
    """The extraction tasks that are open or claimed (lease live or lapsed) and replaced by a
    newer task of their (work, pass) unit. The ledger serves only a unit's latest task, so an
    abandoned task is never served again, though it stays open in the log. Read-only."""
    project.index.sync()
    return {
        task.task_id
        for scope in all_scopes(project)
        for unit in _ledger(project, scope).tasks.values()
        for task in unit[:-1]
        if task.status != TaskStatus.COMPLETED.value
    }


def started_works(project: Project, *, scope: ScopeKey = Scope.EVIDENCE) -> set[str]:
    """The works of `scope` an agent has taken up: a task of either pass was claimed or
    completed (a queued task nobody served does not count), or a row exists. Read-only."""
    project.index.sync()
    ledger = _ledger(project, scope)
    started = {
        work
        for (work, _), tasks in ledger.tasks.items()
        if any(t.status != TaskStatus.OPEN.value for t in tasks)
    }
    return started | {work for work, _ in ledger.rows} | ledger.filled()


def mined_works(project: Project, scope: ScopeKey) -> set[str]:
    """The works of `scope` this project has a claimed or completed task or a mined row of: an
    import of one would be shadowed by the local units, so it is refused. A queued task nobody
    served does not count, so a re-import stays possible. Read-only."""
    project.index.sync()
    ledger = _ledger(project, scope)
    return {
        work
        for (work, _), tasks in ledger.tasks.items()
        if any(t.status != TaskStatus.OPEN.value for t in tasks)
    } | {work for work, _ in ledger.rows}


def stale_claims(project: Project) -> set[str]:
    """The live claims pinned to a document that is no longer the work's current one. Schema
    amendments never stale a claim. Like `stale_extractions`, it ignores the population: claims
    of works no longer included are filtered downstream. Read-only."""
    project.index.sync()
    return _ledger(project).stale_claims()


def stale_documents(project: Project, *, scope: ScopeKey = Scope.EVIDENCE) -> list[str]:
    """The works, sorted, whose live rows of `scope` pin a conversion other than the work's
    default while their document is the current one: a newer conversion only warns, it stales
    nothing."""
    project.index.sync()
    ledger = _ledger(project, scope)
    out: set[str] = set()
    for rows in ledger.rows.values():
        for row in rows:
            current = ledger.current(row.work_id)
            if (
                current is not None
                and row.document_id == current.document_id
                and row.conversion_id != current.conversion_id
            ):
                out.add(row.work_id)
    return sorted(out)


def unit_states(
    project: Project, *, scope: ScopeKey = Scope.EVIDENCE, calibration_id: str | None = None
) -> list[UnitState]:
    """One state per unit of `scope`, by work then pass: every work of `scope_population` in pass
    A, and in pass B the works of its dual sample once pass B has opened (every work before then
    when the declared sample takes every work). Empty, with no refusal, when there is no ready
    protocol with a known schema of the scope or (evidence) no full-text screening plan.
    Read-only."""
    project.index.sync()
    try:
        _, schema, pack = require_schema(project, scope=scope)
        population = (
            scope_population(project, scope)
            if calibration_id is None
            else calibration_works(project, calibration_id)
        )
    except FactoryValidationError:
        return []
    config = pass_config(project, PassLabel.B, scope=scope)
    if calibration_id is not None:
        sample: set[str] = set()  # a calibration is one pass
    elif config is not None:
        sample = set(_queue(PassLabel.B, population, config.seed, schema))
    elif schema.dual_extract_sample is None or schema.dual_extract_sample >= 1:
        sample = set(population)
    else:
        sample = set()
    ledger = _ledger(project, scope, calibration_id)
    out: list[UnitState] = []
    for work_id in population:
        out.append(ledger.state(work_id, PassLabel.A, schema, pack))
        if work_id in sample:
            out.append(ledger.state(work_id, PassLabel.B, schema, pack))
    return out


# --- Reading recorded rows and claims ---


_MINED = f"substr(task_id, 1, {len(MINE_IMPORT_PREFIX)}) != '{MINE_IMPORT_PREFIX}'"
"""SQL: the row was mined here, not imported (an imported row's `task_id` is its import's id)."""


def live_rows(
    project: Project,
    pass_label: PassLabel | None = None,
    *,
    work_id: str | None = None,
    scope: ScopeKey = Scope.EVIDENCE,
    calibration: bool = False,
) -> list[ExtractionRow]:
    """The rows of `scope` no later row supersedes, optionally of one pass and one work, by
    extraction id. The default scope is evidence: no evidence read sees a contribution row.

    A miner's calibration rows (those of its calibration tasks) are a separate population:
    `calibration=False` leaves them out, `calibration=True` returns only them (and nothing for
    another scope).

    Rows imported from another project are not here: they have no task, pass or unit of this
    project (`imported_rows`)."""
    where, params = _filters(pass_label, work_id)
    where += f" AND superseded_by IS NULL AND scope = :scope AND {_MINED}"
    params["scope"] = scope.value
    rows = [row for row, _ in _read_rows(project, where, params)]
    if not isinstance(scope, MinerScope):
        return [] if calibration else rows
    apart = calibration_task_ids(project, scope)
    if not apart and not calibration:
        return rows
    return [row for row in rows if (row.task_id in apart) == calibration]


def recorded_row(
    project: Project, extraction_id: str, *, scope: ScopeKey = Scope.EVIDENCE
) -> tuple[ExtractionRow, bool] | None:
    """The row `extraction_id` of `scope`, live or superseded, with whether it is live; None for
    an unknown id or a row of the other scope."""
    found = _read_rows(
        project,
        " AND scope = :scope AND extraction_id = :ident",
        {"scope": scope.value, "ident": extraction_id},
    )
    return found[0] if found else None


def imported_rows(project: Project, scope: ScopeKey) -> list[ExtractionRow]:
    """The live rows of `scope` imported from another project, by extraction id. Only a registered
    miner's scope holds any."""
    if not isinstance(scope, MinerScope):
        return []
    where = f" AND superseded_by IS NULL AND scope = :scope AND NOT ({_MINED})"
    return [row for row, _ in _read_rows(project, where, {"scope": scope.value})]


def imports_policy(project: Project, scope: ScopeKey) -> Literal["allow", "deny", "audit"]:
    """What the current protocol says of records imported into `scope`: its `MinerUse.imports`, or
    `deny` for a scope no use lists. A forged import under `deny` therefore never counts, and a
    protocol that declines imports later stops counting those it had (ruling 19)."""
    protocol = current_protocol(project)
    if protocol is None or not isinstance(scope, MinerScope):
        return "deny"
    use = next((u for u in protocol.spec.miners or () if u.name == scope.name), None)
    return "deny" if use is None else use.imports


def filled_imports(project: Project, scope: ScopeKey) -> dict[str, list[ExtractionRow]]:
    """The imported rows in use, by work: of the units an import fills (`_Ledger.filled`), so never
    a stale row, a row shadowed by local mining, or one the protocol declines. Read-only."""
    project.index.sync()
    if not imported_rows(project, scope):
        return {}
    ledger = _ledger(project, scope)
    return {work: ledger.imported[work] for work in sorted(ledger.filled())}


@dataclass(frozen=True)
class ImportItem:
    """Where one imported row came from, as `mine_import_items` holds it."""

    extraction_id: str
    import_id: str
    source_project: str
    miner: str
    version: int
    digest: str
    dual: bool
    source_conversion_id: str
    source_row_key: str
    source_extraction_ids: tuple[str, ...] = ()


def import_items(project: Project) -> dict[str, ImportItem]:
    """Every imported row's provenance, by its extraction id. Read-only."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT i.extraction_id, i.import_id, m.source_project, m.miner, m.version, "
                "m.digest, i.dual, i.source_conversion_id, i.source_row_key, "
                "i.source_extraction_ids "
                "FROM mine_import_items i JOIN mine_imports m ON m.import_id = i.import_id"
            )
        ).all()
    return {
        str(r[0]): ImportItem(
            str(r[0]),
            str(r[1]),
            str(r[2]),
            str(r[3]),
            int(r[4]),
            str(r[5]),
            bool(r[6]),
            str(r[7]),
            str(r[8]),
            tuple(str(i) for i in json.loads(str(r[9]))),
        )
        for r in rows
    }


def scope_rows(project: Project, scope: ScopeKey) -> list[tuple[ExtractionRow, bool]]:
    """Every row of `scope` mined here, live or superseded, by extraction id, each with whether it
    is live: what a source project offers the shared store (M-E). A miner's calibration rows are
    left out, as calibration does not travel, and imported rows too: an import is not re-exported,
    so a record's source is always the project that mined it."""
    rows = _read_rows(project, f" AND scope = :scope AND {_MINED}", {"scope": scope.value})
    if not isinstance(scope, MinerScope):
        return rows
    apart = calibration_task_ids(project, scope)
    return [(row, live) for row, live in rows if row.task_id not in apart]


_FIELD_BATCH = 5000


def _read_rows(
    project: Project, where: str, params: Mapping[str, str]
) -> list[tuple[ExtractionRow, bool]]:
    """The rows matching `where` (an `AND ...` clause on `extraction_rows`) with their fields, by
    extraction id, each with whether no later row supersedes it."""
    project.index.sync()
    with project.index.connect() as conn:
        heads = (
            conn.execute(
                text(
                    "SELECT extraction_id, work_id, pass_label, task_id, protocol_id, "
                    "conversion_id, document_id, row_key, schema_ref, event_id, superseded_by, "
                    "cited_extraction_id, cited_ordinal, cited_marker "
                    f"FROM extraction_rows WHERE 1 = 1{where} ORDER BY extraction_id"
                ),
                params,
            )
            .mappings()
            .all()
        )
        cells: dict[str, list[Mapping[str, Any]]] = {str(h["extraction_id"]): [] for h in heads}
        idents = list(cells)
        for start in range(0, len(idents), _FIELD_BATCH):  # one statement binds one variable
            found = (  # per batch, not per row: SQLite refuses more than 32,766 variables
                conn.execute(
                    text(
                        "SELECT * FROM extraction_fields WHERE extraction_id IN "
                        "(SELECT value FROM json_each(:ids))"
                    ),
                    {"ids": json.dumps(idents[start : start + _FIELD_BATCH])},
                )
                .mappings()
                .all()
            )
            for cell in found:
                cells[str(cell["extraction_id"])].append(dict(cell))
    out: list[tuple[ExtractionRow, bool]] = []
    for head in heads:
        pack = _pack_of(str(head["schema_ref"]))
        ident = str(head["extraction_id"])
        row = ExtractionRow(
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
            cited=_cited(head),
        )
        out.append((row, head["superseded_by"] is None))
    return out


def _cited(head: RowMapping) -> CitedEntry | None:
    if head["cited_extraction_id"] is None:
        return None
    return CitedEntry(
        reference_extraction_id=str(head["cited_extraction_id"]),
        ordinal=int(head["cited_ordinal"]),
        marker=head["cited_marker"],
    )


def live_claims(
    project: Project, pass_label: PassLabel | None = None, *, work_id: str | None = None
) -> list[ClaimRow]:
    """The claims no later claim supersedes, optionally of one pass and one work, by claim id.
    Claims are evidence only: contribution items carry none."""
    project.index.sync()
    where, params = _filters(pass_label, work_id)
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT claim_id, work_id, pass_label, claim_type, evidence_type, strength, "
                    "statement, anchor, quote, document_id, conversion_id, event_id "
                    "FROM extraction_claims "
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

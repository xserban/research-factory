"""The human audit of agreed extraction values (decision 37, acceptance 10).

After dual extraction agrees, `extraction_audit_sample` draws a uniform random sample of the agreed
values (a field of an aligned dual row that the passes agreed on, or that a human resolved to one
pass's value) sized by the schema's `audit_fraction` and `audit_minimum`. A human labels each
sampled value correct or incorrect against the document (`extraction_audit_record`, shown the
cited element by `audit_evidence`); `extraction_audit_report` reads the error rate.

Invariants:
- Sampling and labelling are human acts. A session that joined an extraction pass cannot sample
  (the agreement refuses it) and cannot relay a label over MCP; nor can one that joined a
  screening pass.
- Sampling is refused until `extraction_agreement` succeeds and no disagreement is unresolved.
  One audit is open at a time: a new sample waits until the agreed set (values and the extraction
  they came from) differs from the last audit's population.
- Refusals raise FactoryValidationError and write nothing. Counts and rates are computed from the
  log-derived tables, never supplied. The ceiling is advisory in a pilot and enforced in a
  systematic review.
"""

from __future__ import annotations

import random
import secrets
from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy import text

from factory.canonical import population_digest
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.extraction import (
    AuditItemRef,
    ExtractionAuditLabelled,
    ExtractionAuditSampled,
)
from factory.model.project import RigorMode
from factory.model.screening import Channel
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.extraction import (
    _screening_session,
    is_extraction_session,
    require_schema,
)
from factory.services.extraction_agreement import extraction_agreement, final_rows
from factory.services.screening_stats import audit_size
from factory.services.seeds import _rigor_mode

__all__ = [
    "EXTRACTION_ERROR_CEILING",
    "AuditEvidence",
    "ExtractionAuditReport",
    "agreed_values",
    "audit_evidence",
    "extraction_audit_outstanding",
    "extraction_audit_record",
    "extraction_audit_report",
    "extraction_audit_sample",
]

EXTRACTION_ERROR_CEILING = 0.05
"""Error rate of agreed values above which the audit flags the extraction (decision 37)."""


class AuditEvidence(StrictModel):
    """One sampled value with the document element it cites, for the human to check."""

    item: AuditItemRef
    value: str | bool
    unit: str | None
    quote: str | None
    anchor: str | None
    cell: str | None
    element_text: str
    """The text of the cited cell, else of the cited anchor, in the row's pinned conversion."""
    extraction_id: str


class ExtractionAuditReport(StrictModel):
    audit_id: str
    sample_size: int
    labelled: int
    incorrect: int
    error_rate: float | None
    ceiling: float
    above_ceiling: bool
    enforced: bool
    by_group: dict[str, float | None]
    """Error rate per pack field group over the labelled items; None when a group has none."""


def _sort_key(item: AuditItemRef) -> tuple[str, str, str]:
    return (item.work_id, item.row_key, item.field)


def _population(project: Project) -> list[tuple[AuditItemRef, str]]:
    """The agreed values with the extraction each came from, sorted. Single-extraction rows are
    not audited here; a field a human dropped (`neither`) is not a value."""
    out = [
        (AuditItemRef(work_id=row.work_id, row_key=row.row_key, field=name), f.extraction_id)
        for row in final_rows(project)
        if row.status in ("agreed", "resolved")
        for name, f in row.fields.items()
    ]
    return sorted(out, key=lambda pair: _sort_key(pair[0]))


def _digest(population: Sequence[tuple[AuditItemRef, str]]) -> str:
    return population_digest(
        ("\x1f".join(_sort_key(item)), extraction_id) for item, extraction_id in population
    )


def _draw(items: Sequence[AuditItemRef], size: int, seed: int) -> list[AuditItemRef]:
    """`size` items of `items` (sorted), uniformly at random from `seed`; the result is sorted."""
    return sorted(random.Random(seed).sample(sorted(items, key=_sort_key), size), key=_sort_key)


def agreed_values(project: Project) -> list[AuditItemRef]:
    """The agreed or resolved field values of aligned dual rows, sorted. Read-only."""
    project.index.sync()
    return [item for item, _ in _population(project)]


def extraction_audit_sample(
    project: Project, actor: Actor, *, random_seed: int | None = None
) -> ExtractionAuditSampled:
    """Draw and record an audit sample of the agreed values; return the event payload.

    Refused, with nothing written: for an actor that is not human (`actor`); a seed outside
    0..2**32-1 (`random_seed`); the refusals of `extraction_agreement` (a session that extracts,
    unfinished or unopened passes, a missing schema); an unresolved disagreement (`passes`); no
    agreed value (`passes`); an audit of the current agreed set already open (`passes`).
    """
    seed = secrets.randbits(32) if random_seed is None else random_seed
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        if actor.kind != "human":
            issues.append(ValidationIssue("actor", "audit samples are drawn by a human"))
        if not 0 <= seed < 2**32:
            issues.append(ValidationIssue("random_seed", "must be an integer from 0 to 2**32 - 1"))
        if issues:
            raise FactoryValidationError(issues)
        protocol, schema, _ = require_schema(project)
        agreement = extraction_agreement(project, actor)
        if agreement.disagreements:
            raise _refuse(
                f"{len(agreement.disagreements)} disagreement(s) are unresolved; "
                "resolve them before the audit"
            )
        population = _population(project)
        if not population:
            raise _refuse("there are no agreed values to audit")
        digest = _digest(population)
        if _last_digest(project) == digest:
            raise _refuse("an audit of this agreed set is open; a new one waits for a change to it")
        size = audit_size(len(population), schema.audit_fraction, schema.audit_minimum)
        payload = ExtractionAuditSampled(
            audit_id=project.ids.new("xau"),
            items=tuple(_draw([item for item, _ in population], size, seed)),
            random_seed=seed,
            population=len(population),
            population_digest=digest,
            protocol_id=protocol.protocol_id,
        )
        project.record([project.events.make("extraction.audit_sampled", payload, actor)])
    return payload


def audit_evidence(project: Project, audit_id: str) -> list[AuditEvidence]:
    """The sampled values of an audit with their cited elements, sorted. An item whose value is no
    longer in the agreed set is left out. Refused on `audit_id` for an unknown audit."""
    project.index.sync()
    if not _audit_exists(project, audit_id):
        raise FactoryValidationError([ValidationIssue("audit_id", "unknown audit")])
    rows = {(r.work_id, r.row_key): r for r in final_rows(project)}
    manifests: dict[str, dict[str, str]] = {}
    out: list[AuditEvidence] = []
    for item in _items(project, audit_id):
        row = rows.get((item.work_id, item.row_key))
        found = None if row is None else row.fields.get(item.field)
        if row is None or found is None:
            continue
        if row.conversion_id not in manifests:
            manifest = conversion_manifest(project, row.conversion_id)
            manifests[row.conversion_id] = {a.id: a.text for a in manifest.anchors}
        elements = manifests[row.conversion_id]
        target = found.cell or found.anchor
        out.append(
            AuditEvidence(
                item=item,
                value=found.value,
                unit=found.unit,
                quote=found.quote,
                anchor=found.anchor,
                cell=found.cell,
                element_text=elements.get(target, "") if target else "",
                extraction_id=found.extraction_id,
            )
        )
    return out


def extraction_audit_record(
    project: Project,
    actor: Actor,
    audit_id: str,
    work_id: str,
    row_key: str,
    field: str,
    correct: bool,
    note: str,
    channel: Channel,
) -> str:
    """Record a human's label on one sampled value and return the event id. Relabelling replaces
    the earlier label (last write wins).

    Refused, with nothing written: for an actor that is not human (`actor`); an unknown audit
    (`audit_id`); a value outside the sample (`field`); an MCP-relayed label from a session that
    joined an extraction or screening pass (`channel`).
    """
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        if actor.kind != "human":
            issues.append(ValidationIssue("actor", "audit labels are human acts"))
        if not _audit_exists(project, audit_id):
            issues.append(ValidationIssue("audit_id", "unknown audit"))
        elif not any(
            (i.work_id, i.row_key, i.field) == (work_id, row_key, field)
            for i in _items(project, audit_id)
        ):
            issues.append(ValidationIssue("field", "not in this audit sample"))
        if channel is Channel.MCP and (
            is_extraction_session(project, actor.session)
            or _screening_session(project, actor.session)
        ):
            issues.append(ValidationIssue("channel", "this session has joined a pass"))
        if issues:
            raise FactoryValidationError(issues)
        try:
            payload = ExtractionAuditLabelled(
                audit_id=audit_id,
                work_id=work_id,
                row_key=row_key,
                field=field,
                correct=correct,
                note=note,
                channel=channel,
            )
        except ValidationError as exc:
            raise FactoryValidationError(
                [
                    ValidationIssue(".".join(str(p) for p in e["loc"]) or "label", str(e["msg"]))
                    for e in exc.errors()
                ]
            ) from exc
        event = project.events.make("extraction.audit_labelled", payload, actor)
        project.record([event])
    return event.id


def extraction_audit_report(project: Project) -> ExtractionAuditReport | None:
    """The latest audit's counts and error rate; None when no audit has been sampled. Items not
    yet labelled count in the sample size only. Read-only; never raises."""
    project.index.sync()
    with project.index.connect() as conn:
        latest = conn.execute(
            text("SELECT audit_id FROM extraction_audits ORDER BY audit_id DESC LIMIT 1")
        ).one_or_none()
        if latest is None:
            return None
        audit_id = str(latest[0])
        rows = conn.execute(
            text(
                "SELECT field, correct FROM extraction_audit_items "
                "WHERE audit_id = :a ORDER BY work_id, row_key, field"
            ),
            {"a": audit_id},
        ).all()
    try:
        _, _, pack = require_schema(project)
    except FactoryValidationError:
        pack = None
    tally: dict[str, list[int]] = {}
    labelled = incorrect = 0
    for name, correct in rows:
        found = None if pack is None else pack.field(str(name))
        counts = tally.setdefault(found.group if found else "other", [0, 0])
        if correct is None:
            continue
        counts[0] += 1
        counts[1] += not correct
        labelled += 1
        incorrect += not correct
    rate = incorrect / labelled if labelled else None
    return ExtractionAuditReport(
        audit_id=audit_id,
        sample_size=len(rows),
        labelled=labelled,
        incorrect=incorrect,
        error_rate=rate,
        ceiling=EXTRACTION_ERROR_CEILING,
        above_ceiling=rate is not None and rate > EXTRACTION_ERROR_CEILING,
        enforced=_rigor_mode(project) is RigorMode.SYSTEMATIC,
        by_group={g: (bad / n if n else None) for g, (n, bad) in sorted(tally.items())},
    )


def extraction_audit_outstanding(project: Project) -> bool:
    """Whether there are agreed values and no audit has sampled the current agreed set. False when
    there is nothing to audit. Read-only; never raises."""
    project.index.sync()
    try:
        population = _population(project)
    except FactoryValidationError:
        return False
    if not population:
        return False
    return _last_digest(project) != _digest(population)


# --- Reading the audit tables ---


def _last_digest(project: Project) -> str | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT population_digest FROM extraction_audits ORDER BY audit_id DESC LIMIT 1")
        ).one_or_none()
    return None if row is None else str(row[0])


def _audit_exists(project: Project, audit_id: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM extraction_audits WHERE audit_id = :a"), {"a": audit_id}
        ).one_or_none()
    return row is not None


def _items(project: Project, audit_id: str) -> list[AuditItemRef]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT work_id, row_key, field FROM extraction_audit_items "
                "WHERE audit_id = :a ORDER BY work_id, row_key, field"
            ),
            {"a": audit_id},
        ).all()
    return [AuditItemRef(work_id=str(w), row_key=str(r), field=str(f)) for w, r, f in rows]


def _refuse(reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue("passes", reason)])

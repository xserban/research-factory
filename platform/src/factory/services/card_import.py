"""Importing a method card or problem description from another project (plan XL task 2).

Invariants:
- A human act reached from the CLI only. The source project is opened as a reader and never
  written (see `services/region_adoption.py`).
- Nothing is stated on the source's word. An imported assertion is `stated` only when its basis
  re-verifies here: the same conversion is present and the quote is verbatim in the anchored
  element and carries the value, or the final evidence row says the value. Every other imported
  assertion is `imported-unverified` and stays out of the default views until a human confirms it.
- The card is new here: a subject that already has a card of the kind is refused, not merged.
  A subject must be known here (a work this corpus holds, a confirmed idea, the current question
  or a task name); an assertion whose property is not approved here, does not apply to the card's
  kind or whose value fails the local definition is skipped and reported.
- Nothing is written when no assertion can be imported. Rejected and superseded source assertions
  are never read.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.hypotheses.values import check_value, value_in_quote
from factory.model.base import StrictModel
from factory.model.cards import (
    BasisKind,
    CardAsserted,
    CardCreated,
    CardImported,
    InferredBasis,
    PropertyDef,
    QuoteBasis,
    RowBasis,
)
from factory.model.screening import Channel
from factory.services.cards import (
    AssertionStatus,
    _Ctx,
    _method_subject,
    _problem_subject,
    _quote_issues,
    _row_reason,
)
from factory.services.context import Project
from factory.services.gates import gate_issues
from factory.services.human_channel import require_human_channel
from factory.services.properties import vocabulary_version
from factory.services.region_adoption import open_source

__all__ = ["CardImportResult", "import_card"]


class CardImportResult(StrictModel):
    card_id: str
    imported: list[tuple[str, str, AssertionStatus]]
    """(source assertion id, new assertion id, status here) for each assertion written."""
    skipped: list[tuple[str, str]]
    """(source assertion id, reason) for each assertion left out."""


def _refuse(field_name: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_name, reason)])


def _basis_of(kind: str, raw: str | None) -> QuoteBasis | RowBasis | InferredBasis | None:
    if raw is None:
        return None
    models: dict[str, type[BaseModel]] = {
        "quote": QuoteBasis,
        "row": RowBasis,
        "inferred": InferredBasis,
    }
    model = models.get(kind)
    if model is None:
        return None
    parsed = model.model_validate_json(raw)
    assert isinstance(parsed, QuoteBasis | RowBasis | InferredBasis)
    return parsed


def _verified(
    ctx: _Ctx,
    defn: PropertyDef,
    basis: QuoteBasis | RowBasis | InferredBasis | None,
    value: str | tuple[str, ...] | bool,
    unit: str | None,
    canonical: str | None,
) -> bool:
    """Whether the basis re-verifies in this project (module docstring)."""
    if isinstance(basis, QuoteBasis):
        return not _quote_issues(ctx, basis, "basis") and value_in_quote(
            defn, value, basis.quote, unit=unit
        )
    if isinstance(basis, RowBasis):
        row = ctx.rows().get((basis.work_id, basis.row_key))
        return _row_reason(defn, row, basis.field, value, canonical) is None
    return False


def import_card(
    project: Project,
    actor: Actor,
    source_root: Path,
    source_card_id: str,
    channel: Channel = Channel.CLI,
) -> CardImportResult:
    """Import the card `source_card_id` of the project at `source_root` as a new card here, with
    recorded provenance (`card.imported`). Refused with nothing written (fields `actor`,
    `source`, `card_id`, `subject`, `assertions`): not a human, an unreadable or identical
    source, an unknown source card, a subject unknown here or already carded, or no assertion that
    can be imported."""
    issues = gate_issues(project, actor, "cards.import")
    if actor.kind != "human" and not issues:
        issues.append(ValidationIssue("actor", "only a human imports a card"))
    if issues:
        raise FactoryValidationError(issues)
    source = open_source(project, source_root)
    source.index.sync()
    with source.index.connect() as conn:
        card = (
            conn.execute(
                text("SELECT kind, subject, owner, event_id FROM cards WHERE card_id = :c"),
                {"c": source_card_id},
            )
            .mappings()
            .first()
        )
        rows = (
            conn.execute(
                text(
                    "SELECT assertion_id, property, value_json, unit, canonical, basis_kind, "
                    "basis_json, event_id FROM card_assertions WHERE card_id = :c "
                    "AND superseded_by IS NULL AND folded = 1 AND COALESCE(decision, '') != "
                    "'reject' ORDER BY property, event_id"
                ),
                {"c": source_card_id},
            )
            .mappings()
            .all()
        )
    if card is None:
        raise _refuse("card_id", "unknown")
    kind = str(card["kind"])
    with project.writing():
        require_human_channel(project, actor, channel, "sign-off")
        subject, subject_issues = (
            _method_subject(project, str(card["subject"]))
            if kind == "method"
            else _problem_subject(project, str(card["subject"]))
        )
        if subject_issues:
            raise FactoryValidationError(subject_issues)
        with project.index.connect() as conn:
            taken = conn.execute(
                text("SELECT 1 FROM cards WHERE kind = :k AND subject = :s"),
                {"k": kind, "s": subject},
            ).first()
        if taken is not None:
            raise _refuse("subject", "card-exists")
        ctx = _Ctx(project)
        version = vocabulary_version(project)
        card_id = project.ids.new("mcd" if kind == "method" else "pbd")
        origin = f"{source.paths.slug}:{source_card_id}"
        events: list[Event] = []
        imported: list[tuple[str, str, AssertionStatus]] = []
        skipped: list[tuple[str, str]] = []
        source_events = [str(card["event_id"])]
        for row in rows:
            source_id = str(row["assertion_id"])
            reason = _import_reason(ctx, kind, str(row["basis_kind"]), str(row["property"]))
            defn = ctx.definition(str(row["property"]))
            if reason is not None or defn is None:
                skipped.append((source_id, reason or "property-unknown"))
                continue
            raw = json.loads(str(row["value_json"]))
            value: str | tuple[str, ...] | bool = tuple(raw) if isinstance(raw, list) else raw
            unit = None if row["unit"] is None else str(row["unit"])
            verdict = check_value(defn, value, unit)
            if not verdict.ok:
                skipped.append((source_id, verdict.reason or "value-not-allowed"))
                continue
            try:
                basis = _basis_of(str(row["basis_kind"]), row["basis_json"])
            except ValidationError:
                skipped.append((source_id, "basis-unreadable"))
                continue
            status: AssertionStatus = (
                "stated"
                if _verified(ctx, defn, basis, value, unit, verdict.canonical)
                else "imported-unverified"
            )
            assertion_id = project.ids.new("pas")
            payload = CardAsserted(
                assertion_id=assertion_id,
                card_id=card_id,
                property=str(row["property"]),
                value=verdict.value_norm if isinstance(value, tuple) else value,
                unit=unit,
                canonical=verdict.canonical,
                basis_kind=BasisKind.IMPORTED,
                basis=basis,
                status=status,
                vocabulary_version=version,
                imported_from=f"{origin}#{source_id}",
            )
            events.append(
                project.events.make(
                    "card.asserted", payload, actor, [assertion_id, card_id, payload.property]
                )
            )
            imported.append((source_id, assertion_id, status))
            source_events.append(str(row["event_id"]))
        if not imported:
            raise _refuse("assertions", "nothing-importable")
        created = project.events.make(
            "card.created",
            CardCreated(card_id=card_id, kind=kind, subject=subject, owner=str(card["owner"])),
            actor,
            refs=[card_id, subject],
        )
        marker = project.events.make(
            "card.imported",
            CardImported(
                card_id=card_id,
                source_project=source.paths.slug,
                source_card_id=source_card_id,
                source_event_ids=tuple(source_events),
            ),
            actor,
            refs=[card_id, source_card_id],
        )
        project.record([created, *events, marker])
    return CardImportResult(card_id=card_id, imported=imported, skipped=skipped)


def _import_reason(ctx: _Ctx, card_kind: str, basis_kind: str, property_key: str) -> str | None:
    """Why a source assertion is left out before its value is looked at, or None."""
    if basis_kind == BasisKind.IMPORTED.value:
        return "source-imported"
    defn = ctx.definition(property_key)
    if defn is None:
        return "property-unknown"
    if defn.applies_to not in (card_kind, "both"):
        return "not-applicable"
    return None

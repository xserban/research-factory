"""Method cards, problem descriptions and verified property assertions (slice 6, plan H-A).

A card is a header (`card.created`) and a set of assertions. This module is a hand-written miner
(slice-M kind `miner`: single pass, human confirmation, audit sample); it moves behind the miner
contract when slice M is built, without changing its events.

Invariants:
- The agent states a property, a value and one basis; the platform computes the status. A `quote`
  basis is `stated` only when the conversion belongs to the work, the anchor resolves, the quote is
  verbatim in the anchored element and the value is carried by the quote (rulings 3 and 4); a
  `row` basis only when the evidence row is final and its field equals the value; a `researcher`
  basis is a human statement; an `inferred` basis waits for a human. Anything else is rejected,
  item by item, and the rest of a batch is still written. Rejections carry reason codes, never
  document text.
- Only a human confirms or rejects an assertion, never from the session that wrote it, and a
  confirmation applies to inferred and `imported-unverified` assertions only. No MCP tool does it.
- A later assertion of the same (card, property) supersedes the earlier one. A method card's
  subject is a confirmed, live lineage idea or a known work; a problem description's subject is
  the current `Q@` or a task name under it. A subject has at most one card per kind: a second
  `create_card` returns the first.
- Staleness is computed on read, never stored: `definition-changed`, `property-rejected`,
  `row-changed`, `document-superseded`, `idea-not-live`. A stale assertion is hidden from the
  default views until it is asserted again.
- Default views show stated and confirmed assertions only. Reads page in SQL; none loads every
  card. Quotes are the only document text in events.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import text

from factory.document.anchors import Manifest
from factory.document.quotes import quote_in_element
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.extraction.numbers import normalise_text
from factory.model.base import StrictModel
from factory.model.cards import (
    ASSERTION_ID_RE,
    MAX_RATIONALE,
    AssertionDecided,
    BasisKind,
    CardAsserted,
    CardCreated,
    CardKind,
    InferredBasis,
    PropertyDef,
    PropertyKey,
    PropertyKind,
    QuoteBasis,
    RowBasis,
)
from factory.model.extraction import AuditItemRef
from factory.model.lineage import IDEA_ID_RE
from factory.model.question import QUESTION_ID_RE
from factory.model.work_ids import WORK_ID_RE
from factory.services.context import Project
from factory.services.conversions import conversion_manifest, conversion_work
from factory.services.document_read import default_conversion, promoted_works
from factory.services.extraction_agreement import FinalRow, final_rows
from factory.services.extraction_audit import AuditEvidence
from factory.services.ideas import idea_view, resolve_idea
from factory.services.properties import resolve_property, resolved_key, vocabulary_version
from factory.services.question import current_question
from factory.services.relations import known_work

from factory.hypotheses.values import check_value, value_in_quote  # isort: skip

import re

AssertionStatus = Literal["stated", "inferred", "imported-unverified"]
Effective = Literal["stated", "confirmed", "inferred", "imported-unverified", "stale", "rejected"]
STALE_ORDER = (
    "definition-changed",
    "property-rejected",
    "row-changed",
    "document-superseded",
    "idea-not-live",
)
PAGE = 500
_IDEA = re.compile(IDEA_ID_RE)
_WORK = re.compile(WORK_ID_RE)
_QUESTION = re.compile(QUESTION_ID_RE)
_ASSERTION = re.compile(ASSERTION_ID_RE)


class AssertionInput(StrictModel):
    """One assertion as the agent (or a human) states it. It has no status, id or version: the
    platform computes them, and an unknown field is refused."""

    property: PropertyKey
    value: str | tuple[str, ...] | bool
    unit: str | None = None
    basis_kind: Literal["quote", "row", "researcher", "inferred"]
    basis: QuoteBasis | RowBasis | InferredBasis | None = None


class AssertResult(StrictModel):
    accepted: list[tuple[int, str, AssertionStatus]]
    """(item index, assertion id, computed status) for each item written."""
    rejected: list[tuple[int, list[ValidationIssue]]]
    """(item index, issues) for each item refused; nothing of it was written."""


class AssertionView(StrictModel):
    assertion_id: str
    property: str
    value: str | tuple[str, ...] | bool
    unit: str | None
    basis_kind: str
    status: str
    effective: Effective
    stale_reasons: tuple[str, ...]
    event_id: str


class CardView(StrictModel):
    card_id: str
    kind: str
    subject: str
    owner: str
    assertions: list[AssertionView]
    hidden_counts: dict[str, int]
    """Live assertions not shown by the view's filter, by effective status."""


class CardSummary(StrictModel):
    card_id: str
    kind: str
    subject: str
    owner: str
    assertions: int
    event_id: str


class CardPropRow(StrictModel):
    card_id: str
    card_kind: str
    subject: str
    property_key: str
    value_norm: str
    number_canonical: str | None
    effective: str


def _refuse(field_name: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_name, reason)])


def _model_issues(exc: ValidationError) -> list[ValidationIssue]:
    return [
        ValidationIssue(".".join(str(p) for p in e["loc"]) or "input", str(e["msg"]))
        for e in exc.errors()
    ]


# --- Cards ---


def _existing_card(project: Project, kind: str, subject: str) -> str | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT card_id FROM cards WHERE kind = :k AND subject = :s "
                "ORDER BY event_id LIMIT 1"
            ),
            {"k": kind, "s": subject},
        ).first()
    return None if row is None else str(row[0])


def _method_subject(project: Project, subject: str) -> tuple[str, list[ValidationIssue]]:
    if _IDEA.fullmatch(subject):
        resolved = resolve_idea(project, subject)
        view = idea_view(project, resolved)
        if view is None:
            return subject, [ValidationIssue("subject", "subject-unknown")]
        if view.state != "confirmed":
            return subject, [ValidationIssue("subject", "idea-not-confirmed")]
        return resolved, []
    if _WORK.fullmatch(subject) and known_work(project, subject):
        return subject, []
    return subject, [ValidationIssue("subject", "subject-unknown")]


def _problem_subject(project: Project, subject: str) -> tuple[str, list[ValidationIssue]]:
    question = current_question(project)
    if question is None:
        return subject, [ValidationIssue("subject", "subject-unknown")]
    if _QUESTION.fullmatch(subject):
        if subject != question.question_id:
            return subject, [ValidationIssue("subject", "subject-unknown")]
        return subject, []
    return " ".join(subject.split()), []


def create_card(project: Project, actor: Actor, kind: CardKind, subject: str, owner: str) -> str:
    """Create the card of `subject` (agent or human) and return its id; when the subject has a
    card of this kind already, return that one and write nothing. Refused, with nothing written:
    another actor kind (`actor`); a method subject that is neither a known work nor a lineage
    idea (`subject`: `subject-unknown`) or an idea not confirmed and live (`subject`:
    `idea-not-confirmed`); a problem subject that is not the current `Q@` or a task name under a
    recorded question (`subject`: `subject-unknown`); a blank or over-long subject or owner."""
    if actor.kind not in ("agent", "human"):
        raise _refuse("actor", "only an agent or a human creates a card")
    with project.index.exclusive():
        project.index.sync()
        if kind == "method":
            resolved, issues = _method_subject(project, subject)
        else:
            resolved, issues = _problem_subject(project, subject)
        if issues:
            raise FactoryValidationError(issues)
        existing = _existing_card(project, kind, resolved)
        if existing is not None:
            return existing
        card_id = project.ids.new("mcd" if kind == "method" else "pbd")
        try:
            payload = CardCreated(card_id=card_id, kind=kind, subject=resolved, owner=owner)
        except ValidationError as exc:
            raise FactoryValidationError(_model_issues(exc)) from exc
        input_blob = (
            project.blobs.put_json({"kind": kind, "subject": resolved, "owner": owner})
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "card.created", payload, actor, refs=[card_id, resolved], input_blob=input_blob
                )
            ]
        )
    return card_id


# --- Assertions ---


def _load_final_rows(project: Project) -> dict[str, FinalRow]:
    """The final evidence rows by row key (the seam tests patch). Read once per call that needs a
    row basis, never otherwise."""
    return {r.row_key: r for r in final_rows(project)}


@dataclass
class _Ctx:
    """Per-call caches: nothing is read twice, and nothing is read unless an item needs it."""

    project: Project
    _rows: dict[str, FinalRow] | None = None
    _promoted: frozenset[str] | None = None
    manifests: dict[str, Manifest | None] = field(default_factory=dict)
    defaults: dict[str, str | None] = field(default_factory=dict)
    ideas: dict[str, bool] = field(default_factory=dict)
    changes: dict[str, str | None] = field(default_factory=dict)
    rejected_keys: dict[str, bool] = field(default_factory=dict)

    def rows(self) -> dict[str, FinalRow]:
        if self._rows is None:
            self._rows = _load_final_rows(self.project)
        return self._rows

    def promoted(self) -> frozenset[str]:
        if self._promoted is None:
            self._promoted = promoted_works(self.project)
        return self._promoted

    def manifest(self, conversion_id: str) -> Manifest | None:
        if conversion_id not in self.manifests:
            try:
                self.manifests[conversion_id] = conversion_manifest(self.project, conversion_id)
            except FactoryValidationError:
                self.manifests[conversion_id] = None
        return self.manifests[conversion_id]

    def default_conversion(self, work_id: str) -> str | None:
        if work_id not in self.defaults:
            ref = default_conversion(self.project, work_id)
            self.defaults[work_id] = None if ref is None else ref.conversion_id
        return self.defaults[work_id]


def _quote_issues(ctx: _Ctx, basis: QuoteBasis, prefix: str) -> list[ValidationIssue]:
    """Whether the quote is verbatim in the anchored element of a conversion of the work."""
    if basis.work_id not in ctx.promoted():
        return [ValidationIssue(f"{prefix}.work_id", "work-not-promoted")]
    owner = conversion_work(ctx.project, basis.conversion_id)
    if owner is None:
        return [ValidationIssue(f"{prefix}.conversion_id", "conversion-unknown")]
    if owner != basis.work_id:
        return [ValidationIssue(f"{prefix}.conversion_id", "conversion-other-work")]
    manifest = ctx.manifest(basis.conversion_id)
    if manifest is None:
        return [ValidationIssue(f"{prefix}.conversion_id", "conversion-unreadable")]
    anchor = manifest.get(basis.anchor)
    if anchor is None:
        return [ValidationIssue(f"{prefix}.anchor", "anchor-unknown")]
    if not quote_in_element(anchor.text, basis.quote):
        return [ValidationIssue(f"{prefix}.quote", "quote-not-verbatim")]
    return []


def _row_reason(
    defn: PropertyDef,
    row: FinalRow | None,
    field_name: str,
    value: str | tuple[str, ...] | bool,
    canon: str | None,
) -> str | None:
    """Why the final row does not say `value` in `field_name`, or None when it does."""
    if row is None:
        return "row-unknown"
    found = row.fields.get(field_name)
    if found is None:
        return "field-unknown"
    if defn.kind is PropertyKind.NUMBER:
        same = canon is not None and found.canonical == canon
    elif defn.kind is PropertyKind.BOOL:
        same = isinstance(found.value, bool) and found.value is value
    elif defn.kind is PropertyKind.ENUM:
        same = (
            isinstance(found.value, str)
            and isinstance(value, str)
            and normalise_text(found.value) == normalise_text(value)
        )
    else:
        same = False
    return None if same else "value-differs"


def _item_issues(
    ctx: _Ctx, actor: Actor, card_kind: str, item: AssertionInput
) -> tuple[list[ValidationIssue], PropertyDef | None, str | None]:
    """Every issue of one item, its property definition and the number's canonical value."""
    defn = resolve_property(ctx.project, item.property)
    if defn is None:
        return [ValidationIssue("property", "unknown")], None, None
    if defn.applies_to not in (card_kind, "both"):
        return [ValidationIssue("property", "not-applicable")], defn, None
    verdict = check_value(defn, item.value, item.unit)
    if not verdict.ok:
        return [ValidationIssue("value", verdict.reason or "value-not-allowed")], defn, None
    kind, basis = item.basis_kind, item.basis
    if kind == "researcher":
        if actor.kind != "human":
            return [ValidationIssue("basis_kind", "human-only")], defn, verdict.canonical
        issues = [] if basis is None else [ValidationIssue("basis", "basis-unexpected")]
        return issues, defn, verdict.canonical
    wanted = {"quote": QuoteBasis, "row": RowBasis, "inferred": InferredBasis}[kind]
    if not isinstance(basis, wanted):
        return [ValidationIssue("basis", "basis-required")], defn, verdict.canonical
    if isinstance(basis, QuoteBasis):
        issues = _quote_issues(ctx, basis, "basis")
        if not issues and not value_in_quote(defn, item.value, basis.quote, unit=item.unit):
            issues = [ValidationIssue("value", "value-not-in-quote")]
    elif isinstance(basis, RowBasis):
        reason = _row_reason(
            defn, ctx.rows().get(basis.row_key), basis.field, item.value, verdict.canonical
        )
        issues = [] if reason is None else [ValidationIssue("basis.row_key", reason)]
        if reason == "value-differs":
            issues = [ValidationIssue("value", reason)]
        elif reason == "field-unknown":
            issues = [ValidationIssue("basis.field", reason)]
    else:
        issues = []
        for i, support in enumerate(basis.supports):
            issues += _quote_issues(ctx, support, f"basis.supports[{i}]")
    return issues, defn, verdict.canonical


def _live_assertion(project: Project, card_id: str, property_key: str) -> str | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT assertion_id FROM card_assertions WHERE card_id = :c AND property = :p "
                "AND superseded_by IS NULL ORDER BY event_id DESC LIMIT 1"
            ),
            {"c": card_id, "p": property_key},
        ).first()
    return None if row is None else str(row[0])


def _status_of(item: AssertionInput) -> AssertionStatus:
    return "inferred" if item.basis_kind == "inferred" else "stated"


def assert_properties(
    project: Project, actor: Actor, card_id: str, items: Sequence[AssertionInput]
) -> AssertResult:
    """Record property assertions on a card and return what was written and what was refused.
    Each item stands alone (partial acceptance): its property must be approved and applicable to
    the card's kind, its value well formed and carried by its basis (module docstring). A live
    assertion of the same (card, property) is superseded. Refused as a whole, with nothing
    written: another actor kind (`actor`), an unknown card (`card_id`: `unknown`)."""
    if actor.kind not in ("agent", "human"):
        raise _refuse("actor", "only an agent or a human asserts a property")
    with project.index.exclusive():
        project.index.sync()
        with project.index.connect() as conn:
            card = conn.execute(
                text("SELECT kind FROM cards WHERE card_id = :c"), {"c": card_id}
            ).first()
        if card is None:
            raise _refuse("card_id", "unknown")
        ctx = _Ctx(project)
        version = vocabulary_version(project)
        events = []
        accepted: list[tuple[int, str, AssertionStatus]] = []
        rejected: list[tuple[int, list[ValidationIssue]]] = []
        live: dict[str, str] = {}
        for index, item in enumerate(items):
            issues, defn, canon = _item_issues(ctx, actor, str(card[0]), item)
            if issues or defn is None:
                rejected.append((index, issues))
                continue
            verdict = check_value(defn, item.value, item.unit)
            stored: str | tuple[str, ...] | bool = item.value
            if isinstance(item.value, tuple | list):
                stored = verdict.value_norm
            previous = live.get(item.property) or _live_assertion(project, card_id, item.property)
            assertion_id = project.ids.new("pas")
            status = _status_of(item)
            payload = CardAsserted(
                assertion_id=assertion_id,
                card_id=card_id,
                property=item.property,
                value=stored,
                unit=item.unit,
                canonical=canon,
                basis_kind=BasisKind(item.basis_kind),
                basis=item.basis,
                status=status,
                vocabulary_version=version,
                supersedes=previous,
            )
            input_blob = (
                project.blobs.put_json({"card_id": card_id, "item": item.model_dump(mode="json")})
                if actor.kind == "agent"
                else None
            )
            refs = [assertion_id, card_id, item.property]
            if isinstance(item.basis, QuoteBasis):
                refs.append(item.basis.work_id)
            events.append(
                project.events.make("card.asserted", payload, actor, refs, input_blob=input_blob)
            )
            live[item.property] = assertion_id
            accepted.append((index, assertion_id, status))
        if events:
            project.record(events)
    return AssertResult(accepted=accepted, rejected=rejected)


def assert_properties_raw(
    project: Project, actor: Actor, card_id: str, raw_items: Sequence[Mapping[str, Any]]
) -> AssertResult:
    """As `assert_properties`, for items as a tool receives them: an item that does not parse
    (an unknown or forbidden field such as `status`, a bad shape) is rejected on its own, with
    the parse issues, and the others are still written."""
    parsed: list[tuple[int, AssertionInput]] = []
    rejected: list[tuple[int, list[ValidationIssue]]] = []
    for index, raw in enumerate(raw_items):
        try:
            parsed.append((index, AssertionInput.model_validate(raw)))
        except ValidationError as exc:
            rejected.append((index, _model_issues(exc)))
    result = assert_properties(project, actor, card_id, [item for _, item in parsed])
    accepted = [(parsed[i][0], ident, status) for i, ident, status in result.accepted]
    rejected += [(parsed[i][0], issues) for i, issues in result.rejected]
    return AssertResult(accepted=accepted, rejected=sorted(rejected, key=lambda pair: pair[0]))


def parse_cli_value(project: Project, property_key: str, raw: str) -> str | tuple[str, ...] | bool:
    """A command-line value in the form of its property: `true` / `false` for a bool, a
    comma-separated list for a set, the text otherwise. Raises on field `property` for a key with
    no approved definition."""
    project.index.sync()
    defn = resolve_property(project, property_key)
    if defn is None:
        raise _refuse("property", "unknown")
    if defn.kind is PropertyKind.BOOL:
        if raw.lower() not in ("true", "false"):
            raise _refuse("value", "value-not-allowed")
        return raw.lower() == "true"
    if defn.kind is PropertyKind.SET:
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    return raw


def decide_assertion(
    project: Project,
    actor: Actor,
    assertion_id: str,
    decision: Literal["confirm", "reject"],
    rationale: str,
) -> str:
    """Record a human decision on a live assertion and return the event id. A confirmation
    applies to inferred and `imported-unverified` assertions only; a rejection to any live one.
    Refused, with nothing written: a non-human actor (`actor`: `human-only`) or the session that
    wrote the assertion (`actor`: `proposer-session`); an unknown or superseded assertion
    (`assertion_id`); a confirmation of a stated assertion (`decision`: `not-inferred`); a blank or
    long rationale (`rationale`)."""
    if actor.kind != "human":  # gate hypotheses.assertion_confirm (slice-M gate, floor human)
        raise _refuse("actor", "human-only")
    with project.index.exclusive():
        project.index.sync()
        with project.index.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT a.status, a.superseded_by, e.session FROM card_assertions a "
                    "JOIN events e ON e.id = a.event_id WHERE a.assertion_id = :a"
                ),
                {"a": assertion_id},
            ).first()
        issues: list[ValidationIssue] = []
        if row is None:
            issues.append(ValidationIssue("assertion_id", "unknown"))
        else:
            if row[1] is not None:
                issues.append(ValidationIssue("assertion_id", "superseded"))
            if str(row[2]) == actor.session:
                issues.append(ValidationIssue("actor", "proposer-session"))
            if decision == "confirm" and str(row[0]) == "stated":
                issues.append(ValidationIssue("decision", "not-inferred"))
        if not rationale.strip():
            issues.append(ValidationIssue("rationale", "state the reason for the decision"))
        elif len(rationale) > MAX_RATIONALE:
            issues.append(ValidationIssue("rationale", f"at most {MAX_RATIONALE} characters"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "card.assertion_decided",
            AssertionDecided(assertion_id=assertion_id, decision=decision, rationale=rationale),
            actor,
            refs=[assertion_id],
        )
        project.record([event])
        return event.id


# --- Staleness ---


def _latest_definition_change(ctx: _Ctx, key: str) -> str | None:
    """The latest event that approved a definition of `key` or of the key it resolves to."""
    if key not in ctx.changes:
        resolved = resolved_key(ctx.project, key)
        with ctx.project.index.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT max(decision_event_id) FROM properties "
                    "WHERE key IN (:k, :r) AND state IN ('approved', 'superseded')"
                ),
                {"k": key, "r": resolved},
            ).first()
        ctx.changes[key] = None if row is None or row[0] is None else str(row[0])
    return ctx.changes[key]


def _property_rejected(ctx: _Ctx, key: str) -> bool:
    if key not in ctx.rejected_keys:
        ctx.rejected_keys[key] = resolve_property(ctx.project, key) is None
    return ctx.rejected_keys[key]


def _idea_live(ctx: _Ctx, subject: str) -> bool:
    if subject not in ctx.ideas:
        view = idea_view(ctx.project, resolve_idea(ctx.project, subject))
        ctx.ideas[subject] = view is not None and view.state == "confirmed"
    return ctx.ideas[subject]


def _stale_reasons(ctx: _Ctx, row: Any) -> tuple[str, ...]:
    """The reasons a live assertion is stale now (`STALE_ORDER`); empty when it is not."""
    reasons: set[str] = set()
    key = str(row["property"])
    changed = _latest_definition_change(ctx, key)
    if changed is not None and changed > str(row["event_id"]):
        reasons.add("definition-changed")
    if _property_rejected(ctx, key):
        reasons.add("property-rejected")
    basis = None if row["basis_json"] is None else json.loads(str(row["basis_json"]))
    kind = str(row["basis_kind"])
    if kind == "row" and basis is not None:
        defn = resolve_property(ctx.project, key)
        value = json.loads(str(row["value_json"]))
        if isinstance(value, list):
            value = tuple(value)
        found = ctx.rows().get(str(basis["row_key"]))
        if defn is None or _row_reason(defn, found, str(basis["field"]), value, row["canonical"]):
            reasons.add("row-changed")
    if kind == "quote" and basis is not None:
        current = ctx.default_conversion(str(basis["work_id"]))
        if current is not None and current != basis["conversion_id"]:
            reasons.add("document-superseded")
    subject = str(row["subject"])
    if (
        str(row["card_kind"]) == "method"
        and _IDEA.fullmatch(subject)
        and not _idea_live(ctx, subject)
    ):
        reasons.add("idea-not-live")
    return tuple(r for r in STALE_ORDER if r in reasons)


def _effective(status: str, decision: str | None, stale: Sequence[str]) -> Effective:
    if decision == "reject":
        return "rejected"
    if stale:
        return "stale"
    if decision == "confirm":
        return "confirmed"
    return status  # type: ignore[return-value]


# --- Reads ---

_ASSERTION_SQL = (
    "SELECT a.assertion_id, a.card_id, a.property, a.value_json, a.unit, a.canonical, "
    "a.basis_kind, a.basis_json, a.status, a.decision, a.event_id, c.kind AS card_kind, "
    "c.subject FROM card_assertions a JOIN cards c ON c.card_id = a.card_id "
)


def _value(raw: str) -> str | tuple[str, ...] | bool:
    value = json.loads(raw)
    return tuple(value) if isinstance(value, list) else value


def card_view(
    project: Project,
    card_id: str,
    *,
    include_inferred: bool = False,
    include_stale: bool = False,
) -> CardView | None:
    """A card with its live assertions, by property; None for an unknown card. The default view
    shows stated and confirmed assertions; `include_inferred` adds inferred and
    `imported-unverified` ones, `include_stale` adds stale ones, each labelled by `effective`.
    Rejected assertions are never shown. `hidden_counts` counts what the filter left out."""
    project.index.sync()
    with project.index.connect() as conn:
        card = conn.execute(
            text("SELECT kind, subject, owner FROM cards WHERE card_id = :c"), {"c": card_id}
        ).first()
        rows = (
            conn.execute(
                text(
                    _ASSERTION_SQL
                    + "WHERE a.card_id = :c AND a.superseded_by IS NULL ORDER BY a.property, "
                    "a.event_id"
                ),
                {"c": card_id},
            )
            .mappings()
            .all()
        )
    if card is None:
        return None
    ctx = _Ctx(project)
    shown = {"stated", "confirmed"}
    if include_inferred:
        shown |= {"inferred", "imported-unverified"}
    if include_stale:
        shown.add("stale")
    views: list[AssertionView] = []
    hidden: dict[str, int] = {}
    for row in rows:
        stale = _stale_reasons(ctx, row)
        effective = _effective(str(row["status"]), row["decision"], stale)
        if effective not in shown:
            hidden[effective] = hidden.get(effective, 0) + 1
            continue
        views.append(
            AssertionView(
                assertion_id=str(row["assertion_id"]),
                property=str(row["property"]),
                value=_value(str(row["value_json"])),
                unit=row["unit"],
                basis_kind=str(row["basis_kind"]),
                status=str(row["status"]),
                effective=effective,
                stale_reasons=stale,
                event_id=str(row["event_id"]),
            )
        )
    return CardView(
        card_id=card_id,
        kind=str(card[0]),
        subject=str(card[1]),
        owner=str(card[2]),
        assertions=views,
        hidden_counts=hidden,
    )


def list_cards(
    project: Project, kind: CardKind | None = None, *, limit: int = PAGE, offset: int = 0
) -> list[CardSummary]:
    """Cards by id, one page from `offset`, with their live assertion counts."""
    project.index.sync()
    where = "" if kind is None else "WHERE c.kind = :k "
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.card_id, c.kind, c.subject, c.owner, c.event_id, "
                "(SELECT count(*) FROM card_assertions a WHERE a.card_id = c.card_id "
                "AND a.superseded_by IS NULL) FROM cards c "
                + where
                + "ORDER BY c.card_id LIMIT :n OFFSET :o"
            ),
            {"k": kind, "n": limit, "o": offset},
        ).all()
    return [
        CardSummary(
            card_id=str(r[0]),
            kind=str(r[1]),
            subject=str(r[2]),
            owner=str(r[3]),
            event_id=str(r[4]),
            assertions=int(r[5]),
        )
        for r in rows
    ]


def _family(project: Project, keys: Collection[str]) -> set[str]:
    """`keys` and every key that resolves, through merges, to one of them."""
    wanted = {resolved_key(project, k) for k in keys}
    with project.index.connect() as conn:
        sources = [
            str(r[0]) for r in conn.execute(text("SELECT DISTINCT from_key FROM property_merges"))
        ]
    return wanted | {s for s in sources if resolved_key(project, s) in wanted} | set(keys)


def effective_card_props(
    project: Project, property_keys: Collection[str], statuses: Collection[str]
) -> Iterator[CardPropRow]:
    """Stream the live `card_props` of the given properties (merged keys included, reported under
    the key they resolve to) whose effective status, staleness applied, is in `statuses`, ordered
    by assertion then value. Pages through SQL; consumed by matching (H-B)."""
    project.index.sync()
    family = sorted(_family(project, property_keys))
    if not family:
        return
    ctx = _Ctx(project)
    marks = ", ".join(f":k{i}" for i in range(len(family)))
    params: dict[str, Any] = {f"k{i}": k for i, k in enumerate(family)}
    after = ("", "")
    while True:
        with project.index.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT p.assertion_id, p.value_norm, p.number_canonical, "
                        "a.card_id, a.property, a.value_json, a.unit, a.canonical, a.basis_kind, "
                        "a.basis_json, a.status, a.decision, a.event_id, c.kind AS card_kind, "
                        "c.subject FROM card_props p "
                        "JOIN card_assertions a ON a.assertion_id = p.assertion_id "
                        "JOIN cards c ON c.card_id = a.card_id "
                        f"WHERE p.property_key IN ({marks}) "
                        "AND (p.assertion_id > :aa "
                        "OR (p.assertion_id = :aa AND p.value_norm > :av)) "
                        "ORDER BY p.assertion_id, p.value_norm LIMIT :n"
                    ),
                    {**params, "aa": after[0], "av": after[1], "n": PAGE},
                )
                .mappings()
                .all()
            )
        for row in rows:
            stale = _stale_reasons(ctx, row)
            effective = _effective(str(row["status"]), row["decision"], stale)
            if effective in statuses:
                yield CardPropRow(
                    card_id=str(row["card_id"]),
                    card_kind=str(row["card_kind"]),
                    subject=str(row["subject"]),
                    property_key=resolved_key(project, str(row["property"])),
                    value_norm=str(row["value_norm"]),
                    number_canonical=row["number_canonical"],
                    effective=effective,
                )
        if len(rows) < PAGE:
            return
        after = (str(rows[-1]["assertion_id"]), str(rows[-1]["value_norm"]))


# --- Audit of stated quote assertions (ruling 6) ---


def _audit_row_key(assertion_id: str) -> str:
    return "rk_" + hashlib.sha256(assertion_id.encode()).hexdigest()[:12]


def card_audit_population(project: Project) -> list[tuple[AuditItemRef, str]]:
    """The values an audit of cards draws from: live, undecided-or-confirmed, not stale, `stated`
    `quote` assertions, as (reference, assertion id) sorted by location. The reference names the
    quoted work, a row key derived from the assertion id and the property key; the assertion id
    plays the part of the extraction the value came from, so a superseded assertion is outdated."""
    ctx = _Ctx(project)
    out: list[tuple[AuditItemRef, str]] = []
    after = ""
    while True:
        with project.index.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        _ASSERTION_SQL + "WHERE a.superseded_by IS NULL AND a.status = 'stated' "
                        "AND a.basis_kind = 'quote' "
                        "AND (a.decision IS NULL OR a.decision != 'reject') "
                        "AND a.assertion_id > :after ORDER BY a.assertion_id LIMIT :n"
                    ),
                    {"after": after, "n": PAGE},
                )
                .mappings()
                .all()
            )
        for row in rows:
            if _stale_reasons(ctx, row):
                continue
            basis = json.loads(str(row["basis_json"]))
            ident = str(row["assertion_id"])
            item = AuditItemRef(
                work_id=str(basis["work_id"]),
                row_key=_audit_row_key(ident),
                field=str(row["property"]),
                extraction_id=ident,
            )
            out.append((item, ident))
        if len(rows) < PAGE:
            break
        after = str(rows[-1]["assertion_id"])
    return sorted(out, key=lambda pair: (pair[0].work_id, pair[0].row_key, pair[0].field))


def card_audit_evidence(project: Project, items: Sequence[AuditItemRef]) -> list[AuditEvidence]:
    """The sampled assertions of a card audit with their anchored elements, sorted; an item whose
    assertion is no longer in the population is left out."""
    current = {
        (i.work_id, i.row_key, i.field): ident for i, ident in card_audit_population(project)
    }
    out: list[AuditEvidence] = []
    for item in items:
        ident = current.get((item.work_id, item.row_key, item.field))
        if ident is None or (item.extraction_id is not None and ident != item.extraction_id):
            continue
        with project.index.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT value_json, unit, basis_json FROM card_assertions "
                    "WHERE assertion_id = :a"
                ),
                {"a": ident},
            ).first()
        if row is None:
            continue
        basis = QuoteBasis.model_validate_json(str(row[2]))
        manifest = conversion_manifest(project, basis.conversion_id)
        anchor = manifest.get(basis.anchor)
        value = _value(str(row[0]))
        out.append(
            AuditEvidence(
                item=item,
                value=value if isinstance(value, str | bool) else ", ".join(value),
                unit=row[1],
                quote=basis.quote,
                anchor=basis.anchor,
                cell=None,
                element_text="" if anchor is None else anchor.text,
                extraction_id=ident,
            )
        )
    return out

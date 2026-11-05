"""Contribution items: the checks and closing rule on top of plan D's machinery (slice 3b, G2-B).

A thin parameterisation of `services.extraction`: this module supplies the hooks that
`next_unit` and `record_unit` take for `Scope.CONTRIBUTION`, and nothing else records or serves.

Invariants of the checks (`contribution_check`, applied to each verified item alone):
- `cited_entry = n` needs a current G1 extraction of the work pinned to the unit's conversion and
  an entry `n` in it, else the item is rejected. The marker check is then stored on the row as
  `cited`: `matched`, `mismatch` (flagged, stored) or `absent` (the entry is the agent's
  declaration; flagged, stored).
- `result_row` must be the row key of a live, not stale evidence row of the same work; its values
  are never copied.
- A `not-stated` item carries no anchor, cell or quote on any field; within a unit a live
  `not-stated` of kind K and a live item of kind K contradict, in either order of recording.
- Reasons come from a fixed vocabulary and never contain document text.

Invariants of the closing rule (`contribution_close_check`, applied when a call closes a unit):
`base-idea` and `limitation` are each covered (an item or `not-stated`) and at least one
`addition` is recorded; a unit with no `result` closes only with a reason. A unit with no live
item at all closes with a reason alone (the recorded escape of plan D for a document that states
no contribution).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from factory.errors import ValidationIssue
from factory.lineage.cited import item_evidence, marker_check
from factory.lineage.refs import ReferenceView
from factory.model.extraction import CitedEntry, StoredField
from factory.services.context import Project
from factory.services.extraction import (
    ExtraCheck,
    ExtractionRow,
    ExtraVerdict,
    UnitPin,
    live_rows,
    stale_extractions,
)
from factory.services.reference_view import reference_view_of
from factory.services.references import current_extraction

__all__ = [
    "BASE_NOT_COVERED",
    "CONTRADICTS",
    "ENTRY_UNKNOWN",
    "LIMITATION_NOT_COVERED",
    "NOT_STATED_QUOTE",
    "NO_ADDITION",
    "NO_REFERENCES",
    "NO_RESULT_NEEDS_REASON",
    "OTHER_CONVERSION",
    "RESULT_ROW_UNKNOWN",
    "checker_superseding",
    "contribution_check",
    "contribution_close_check",
]

NO_REFERENCES = "no-reference-extraction"
OTHER_CONVERSION = "reference-extraction-other-conversion"
ENTRY_UNKNOWN = "entry-unknown"
RESULT_ROW_UNKNOWN = "result-row-unknown"
NOT_STATED_QUOTE = "not-stated-has-no-quote"
CONTRADICTS = "contradicts-recorded-item"
BASE_NOT_COVERED = "base-idea-not-covered"
LIMITATION_NOT_COVERED = "limitation-not-covered"
NO_ADDITION = "no-addition"
NO_RESULT_NEEDS_REASON = "no-result-needs-reason"

_KIND = "item_kind"
_ABSENT = "absent_kind"
_NOT_STATED = "not-stated"


def _text(fields: Mapping[str, StoredField], name: str) -> str | None:
    stored = fields.get(name)
    return None if stored is None else str(stored.value)


def _kind_of(fields: Mapping[str, StoredField]) -> str:
    return _text(fields, _KIND) or ""


def _contradiction(
    fields: Mapping[str, StoredField], rows: Sequence[ExtractionRow], skip: Collection[str]
) -> bool:
    """Whether the item contradicts a live row of the unit: a `not-stated` of kind K against an
    item of kind K, or the reverse. Rows in `skip` (superseded in this call) do not count."""
    kind = _kind_of(fields)
    absent = _text(fields, _ABSENT)
    for row in rows:
        if row.extraction_id in skip:
            continue
        other = _kind_of(row.fields)
        if kind == _NOT_STATED and other == absent:
            return True
        if kind != _NOT_STATED and other == _NOT_STATED and _text(row.fields, _ABSENT) == kind:
            return True
    return False


class _Checker:
    """One call's checks. G1 and the evidence row keys are read once per unit (the index does
    not change during the call), so a batch of items reads each once."""

    def __init__(self, skip: Collection[str]) -> None:
        self._skip = frozenset(skip)
        self._views: dict[UnitPin, tuple[str, ReferenceView | None]] = {}
        self._result_rows: dict[str, frozenset[str]] = {}

    def __call__(
        self,
        project: Project,
        pin: UnitPin,
        fields: Mapping[str, StoredField],
        seen: Sequence[ExtractionRow],
    ) -> ExtraVerdict:
        issues: list[ValidationIssue] = []
        kind = _kind_of(fields)
        if kind == _NOT_STATED:
            for name, stored in fields.items():
                if stored.quote is not None or stored.anchor is not None or stored.cell is not None:
                    issues.append(ValidationIssue(f"fields.{name}.quote", NOT_STATED_QUOTE))
        if _contradiction(fields, seen, self._skip):
            issues.append(ValidationIssue(f"fields.{_KIND}.value", CONTRADICTS))
        row = fields.get("result_row")
        if row is not None and str(row.value) not in self._rows_of(project, pin.work_id):
            issues.append(ValidationIssue("fields.result_row.value", RESULT_ROW_UNKNOWN))
        cited, refusal = self._cited(project, pin, fields)
        if refusal is not None:
            issues.append(ValidationIssue("fields.cited_entry.value", refusal))
        return ExtraVerdict(cited=cited, issues=issues)

    def _rows_of(self, project: Project, work_id: str) -> frozenset[str]:
        if work_id not in self._result_rows:
            stale = stale_extractions(project)
            self._result_rows[work_id] = frozenset(
                r.row_key
                for r in live_rows(project, work_id=work_id)
                if r.extraction_id not in stale
            )
        return self._result_rows[work_id]

    def _view(self, project: Project, pin: UnitPin) -> tuple[str, ReferenceView | None]:
        """`("ok", view)`, or the refusal reason and None."""
        if pin not in self._views:
            extraction = current_extraction(project, pin.work_id)
            view = None if extraction is None else reference_view_of(project, extraction)
            if view is None:
                self._views[pin] = (NO_REFERENCES, None)
            elif view.conversion_id != pin.conversion_id:
                self._views[pin] = (OTHER_CONVERSION, None)
            else:
                self._views[pin] = ("ok", view)
        return self._views[pin]

    def _cited(
        self, project: Project, pin: UnitPin, fields: Mapping[str, StoredField]
    ) -> tuple[CitedEntry | None, str | None]:
        given = fields.get("cited_entry")
        if given is None:
            return None, None
        status, view = self._view(project, pin)
        if view is None:
            return None, status
        ordinal = int(given.value)
        if view.entry(ordinal) is None:
            return None, ENTRY_UNKNOWN
        evidence = item_evidence(fields)
        marker = (
            "absent"
            if evidence is None
            else marker_check(evidence[1], evidence[0], ordinal, view.contexts)
        )
        return CitedEntry(
            reference_extraction_id=view.extraction_id, ordinal=ordinal, marker=marker
        ), None


def contribution_check(
    project: Project,
    pin: UnitPin,
    fields: Mapping[str, StoredField],
    seen: Sequence[ExtractionRow],
) -> ExtraVerdict:
    """The `ExtraCheck` of contribution items (rulings 2-4); see the module docstring."""
    return _Checker(frozenset())(project, pin, fields, seen)


def checker_superseding(superseded: Collection[str]) -> ExtraCheck:
    """`contribution_check` for a call that supersedes the rows `superseded`: those rows, still
    live while their corrections are judged, take no part in the contradiction rule."""
    return _Checker(superseded)


def contribution_close_check(
    project: Project, pin: UnitPin, rows: Sequence[ExtractionRow], reason: str | None
) -> list[ValidationIssue]:
    """The `CloseCheck` of contribution units (ruling 5): issues on `finish` and `reason`."""
    del project, pin
    if not rows:
        return []  # plan D already requires the reason of a unit with nothing in it
    stated = {_kind_of(r.fields) for r in rows} - {_NOT_STATED}
    declared = {_text(r.fields, _ABSENT) for r in rows if _kind_of(r.fields) == _NOT_STATED}
    issues: list[ValidationIssue] = []
    if stated & declared:
        issues.append(ValidationIssue("finish", CONTRADICTS))
    if "base-idea" not in stated | declared:
        issues.append(ValidationIssue("finish", BASE_NOT_COVERED))
    if "limitation" not in stated | declared:
        issues.append(ValidationIssue("finish", LIMITATION_NOT_COVERED))
    if "addition" not in stated:
        issues.append(ValidationIssue("finish", NO_ADDITION))
    if "result" not in stated and not (reason or "").strip():
        issues.append(ValidationIssue("reason", NO_RESULT_NEEDS_REASON))
    return issues

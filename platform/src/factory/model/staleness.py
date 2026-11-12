"""Which earlier decisions and extraction rows an amendment's stale rules make doubtful (R-15).

Pure: the services and the index projector both evaluate the rules here, so they agree.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from factory.model.base import StrictModel
from factory.model.extraction import MinerScope, Scope, ScopeKey
from factory.model.notices import WorkNoticeState
from factory.model.protocol import ExtractionStale, ProtocolAmended, ScreeningStage, StaleRule


class DecisionRef(StrictModel):
    """A screening decision as the stale rules see it. `criterion` is version-qualified
    (`P@1a2b3c4d:EX03`); `protocol_id` is the version the decision was recorded under."""

    decision_id: str
    verdict: str
    criterion: str | None
    protocol_id: str
    stage: ScreeningStage
    at: str | None = None
    """The recording position (event ID) of the decision; with `amended_at` it fixes which
    amendments came after it."""


def stale_decisions(
    amendments: Sequence[ProtocolAmended],
    lineage: Sequence[str],
    decisions: Sequence[DecisionRef],
    *,
    amended_at: Sequence[str] | None = None,
) -> list[str]:
    """The ids of decisions an amendment's stale rules make doubtful, sorted and unique.

    An amendment judges the decisions recorded before it. With `amended_at` (the event ID of
    each amendment, parallel to `amendments`) and `DecisionRef.at` that is a comparison of
    recording order, so in a reverted amendment (A to B, then B to A) a decision recorded before
    A to B is judged by both A to B and B to A, and one recorded between them by B to A only.
    Without them a decision is in scope of amendment A only when its version comes before
    `A.to_version` in `lineage` (first occurrence). Stages match when they
    are equal or either side is `either`."""
    position: dict[str, int] = {}
    for index, version in enumerate(lineage):
        position.setdefault(version, index)

    stale: set[str] = set()
    for index, amendment in enumerate(amendments):
        if not amendment.stale_rules:
            continue
        when = None if amended_at is None else amended_at[index]
        target = position.get(amendment.to_version)
        for decision in decisions:
            if when is not None and decision.at is not None:
                if decision.at >= when:
                    continue
            else:
                origin = position.get(decision.protocol_id)
                if target is None or origin is None or origin >= target:
                    continue
            if any(_stales(rule, decision) for rule in amendment.stale_rules):
                stale.add(decision.decision_id)
    return sorted(stale)


def _stales(rule: StaleRule, decision: DecisionRef) -> bool:
    if rule.stage is not ScreeningStage.EITHER and decision.stage not in (
        rule.stage,
        ScreeningStage.EITHER,
    ):
        return False
    if rule.stales == "untested":
        return True
    if rule.stales == "inclusions":
        return decision.verdict == "include"
    return decision.verdict == "exclude" and _cid(decision.criterion) == rule.criterion


def _cid(criterion: str | None) -> str | None:
    return None if criterion is None else criterion.rsplit(":", 1)[-1]


class RowRef(StrictModel):
    """An extraction row as the extraction stale rule sees it: its id, the fields it carries and
    its recording position (event ID)."""

    row_id: str
    fields: tuple[str, ...]
    at: str
    values: Mapping[str, str] = {}
    """The row's stored value of each field (canonical when the platform computed one, else the
    stored text), read only by a value-level rule (`ExtractionStale.values`). Empty is allowed:
    such a row is never value-staled."""


def touches(
    rule: ExtractionStale, fields: Sequence[str], values: Mapping[str, str] | None = None
) -> bool:
    """Whether `rule` stales a row carrying `fields` (ruling 12): every row, one carrying a
    removed field, or, for a value-level rule, one whose stored value of a named field is among
    the rule's values for it. `values` maps a row's field to its stored value; without it a
    value-level rule stales nothing."""
    if rule.all_records or set(rule.fields) & set(fields):
        return True
    if rule.values and values:
        return any(values.get(name) in wanted for name, wanted in rule.values.items())
    return False


def stored_values(fields: Mapping[str, object]) -> dict[str, str]:
    """The comparable value of each stored field: its `canonical` when set, else its `value` as
    text. Takes a row's `fields` (`StoredField` by name); anything without a `value` is skipped."""
    out: dict[str, str] = {}
    for name, stored in fields.items():
        value = getattr(stored, "value", None)
        if value is None:
            continue
        canonical = getattr(stored, "canonical", None)
        out[name] = canonical if isinstance(canonical, str) else str(value)
    return out


def scope_rule(amendment: ProtocolAmended, scope: ScopeKey) -> ExtractionStale | None:
    """The amendment's stale rule for rows of `scope`: `extraction_stale` for evidence,
    `contribution_stale` for contribution, the miner's own entry of `miner_stale` for a registered
    miner. A rule never crosses scopes."""
    if isinstance(scope, MinerScope):
        return next((m.rule for m in amendment.miner_stale if m.name == scope.name), None)
    if scope is Scope.CONTRIBUTION:
        return amendment.contribution_stale
    return amendment.extraction_stale


def stale_rows(
    amendments: Sequence[ProtocolAmended],
    amended_at: Sequence[str],
    rows: Sequence[RowRef],
    *,
    scope: ScopeKey = Scope.EVIDENCE,
) -> list[str]:
    """The ids of rows of `scope` an amendment's rule for that scope (`scope_rule`) makes stale,
    sorted and unique.

    As for decisions (decision 50), an amendment judges only the rows recorded before it, by
    recording order (`amended_at` is parallel to `amendments`), never by protocol version: after a
    reverted amendment (A to B, then B to A) a row recorded before A to B is judged by both."""
    stale: set[str] = set()
    for amendment, when in zip(amendments, amended_at, strict=True):
        rule = scope_rule(amendment, scope)
        if rule is None:
            continue
        stale.update(
            row.row_id for row in rows if row.at < when and touches(rule, row.fields, row.values)
        )
    return sorted(stale)


def notice_stale_rows(
    states: Mapping[str, WorkNoticeState], rows: Sequence[tuple[str, str, RowRef]]
) -> list[str]:
    """The ids of rows a correction's `affects` assessment makes stale, sorted and unique.

    `rows` are (work id, row id, ref). A row is stale when an assessment of its own work, recorded
    after the row, names a field the row carries; no other work's rows and no other field are
    touched (R-104, spec ruling 13)."""
    stale: set[str] = set()
    for work_id, row_id, ref in rows:
        state = states.get(work_id)
        if state is None:
            continue
        for mark in state.stale_marks:
            if ref.at < mark.assessed_at and set(mark.fields) & set(ref.fields):
                stale.add(row_id)
                break
    return sorted(stale)

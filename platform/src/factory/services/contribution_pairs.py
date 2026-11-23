"""Candidate pairs of unmatched contribution rows (IDEA-140): a read, never a write.

Row keys of the two passes differ when they cite different paragraphs, so the agreement leaves
such rows unmatched. `contribution_pairs` takes the unmatched rows of the agreement (the
unresolved row disagreements held by one pass only), scores A against B by `extraction.pairing`
and returns proposals with their reasons. Nothing is written: a human who accepts a pair resolves
the two rows with the existing `contributions resolve` (whole row, `--choice a` or `b` on the
row to keep, `--choice neither` on its twin); an agent never does.
"""

from __future__ import annotations

from collections.abc import Mapping

from factory.events.envelope import Actor
from factory.extraction.pairing import DEFAULT_MIN_SCORE, PairRow, propose_pairs
from factory.model.base import StrictModel
from factory.model.extraction import Scope, StoredField
from factory.model.screening import PassLabel
from factory.packs.contribution import CONTRIBUTION_V1
from factory.services.context import Project
from factory.services.contributions import contribution_agreement
from factory.services.extraction import ExtractionRow, live_rows

__all__ = ["ContributionPairs", "PairProposal", "PairedRow", "UnpairedRow", "contribution_pairs"]


class PairedRow(StrictModel):
    """One side of a proposal, as the human needs to judge it."""

    row_key: str
    item_kind: str
    name: str | None
    cited_entry: int | None
    anchor: str | None
    quote: str | None


class PairProposal(StrictModel):
    work_id: str
    score: float
    reasons: list[str]
    a: PairedRow
    b: PairedRow


class UnpairedRow(StrictModel):
    work_id: str
    pass_label: PassLabel
    row: PairedRow


class ContributionPairs(StrictModel):
    """Proposals, best first, and the unmatched rows without a candidate. Counts are computed."""

    pairs: list[PairProposal]
    without_candidate: list[UnpairedRow]
    unmatched_a: int
    unmatched_b: int
    min_score: float


def _text(fields: Mapping[str, StoredField], name: str) -> str | None:
    f = fields.get(name)
    return None if f is None else str(f.value)


def _anchor_and_quote(fields: Mapping[str, StoredField]) -> tuple[str | None, str | None]:
    for name in CONTRIBUTION_V1.row_anchor_fields:
        f = fields.get(name)
        if f is not None and f.anchor is not None:
            return f.anchor, f.quote
    return None, None


def _view(row: ExtractionRow) -> tuple[PairRow, PairedRow]:
    fields = row.fields
    kind = _text(fields, "item_kind") or ""
    name, metric = _text(fields, "name"), _text(fields, "metric")
    entry = fields.get("cited_entry")
    value = fields.get("value")
    anchor, quote = _anchor_and_quote(fields)
    cited = None if entry is None else int(str(entry.value))
    pair_row = PairRow(
        work_id=row.work_id,
        row_key=row.row_key,
        item_kind=kind,
        absent_kind=_text(fields, "absent_kind"),
        text=name or metric,
        cited_entry=cited,
        value=None if value is None else (value.canonical or str(value.value)),
        anchor=anchor,
    )
    return pair_row, PairedRow(
        row_key=row.row_key,
        item_kind=kind,
        name=name or metric,
        cited_entry=cited,
        anchor=anchor,
        quote=quote,
    )


def contribution_pairs(
    project: Project,
    actor: Actor,
    *,
    work_id: str | None = None,
    min_score: float = DEFAULT_MIN_SCORE,
) -> ContributionPairs:
    """Proposals over the unresolved one-pass rows of the contribution agreement, optionally of
    one work. Derived on each call; no event, no cache."""
    agreement = contribution_agreement(project, actor)
    held: dict[tuple[str, str], tuple[bool, bool]] = {}
    for d in agreement.disagreements:
        if d.kind == "row" and (work_id is None or d.work_id == work_id):
            held[(d.work_id, d.row_key)] = (d.a is not None, d.b is not None)
    views: dict[tuple[PassLabel, str, str], tuple[PairRow, PairedRow]] = {}
    for work in sorted({w for w, _ in held}):
        for row in live_rows(project, work_id=work, scope=Scope.CONTRIBUTION):
            if (row.work_id, row.row_key) in held and "item_kind" in row.fields:
                views[(row.pass_label, row.work_id, row.row_key)] = _view(row)
    a_rows = [
        v for (p, w, k), v in views.items() if p is PassLabel.A and held[(w, k)] == (True, False)
    ]
    b_rows = [
        v for (p, w, k), v in views.items() if p is PassLabel.B and held[(w, k)] == (False, True)
    ]
    proposal = propose_pairs((p for p, _ in a_rows), (p for p, _ in b_rows), min_score)
    shown = {(label, work, key): shown_row for (label, work, key), (_, shown_row) in views.items()}
    pairs = [
        PairProposal(
            work_id=c.work_id,
            score=c.score,
            reasons=list(c.reasons),
            a=shown[(PassLabel.A, c.work_id, c.a_key)],
            b=shown[(PassLabel.B, c.work_id, c.b_key)],
        )
        for c in proposal.pairs
    ]
    without = [
        UnpairedRow(work_id=w, pass_label=label, row=shown[(label, w, k)])
        for label, keys in ((PassLabel.A, proposal.a_without), (PassLabel.B, proposal.b_without))
        for w, k in keys
    ]
    return ContributionPairs(
        pairs=pairs,
        without_candidate=without,
        unmatched_a=len(a_rows),
        unmatched_b=len(b_rows),
        min_score=min_score,
    )

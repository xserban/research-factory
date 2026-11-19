"""The claims digest: every paper of a selection with its m-claims rows, for Claude to read whole
(plan chat T6, section 5; the 2026-11-18 matching test).

The digest is material, not a judgement: nothing here ranks or drops a paper. Claude reads it in
the chat session and proposes candidates, which `chat_candidates` then checks.

Invariants:
- Read-only: nothing is written. The index is synced before reading. The selection is the cached
  resolution (`resolve_selection_cached`).
- One entry per work of the resolved selection, ordered by work id, and nothing else: no work
  outside the selection, none left out. The code of an entry is `P` and its 1-based position,
  zero-padded to two digits (more when the selection has over 99 works); for one selection
  digest the codes are therefore stable.
- Rows are those of the named miner at its listed version (`listed_miner_versions`), read with
  `load_miner_work_rows`: final rows, else the live pass A rows (`pass-a-only`), else for a work in
  a calibration sample of that version the researcher's gold rows (`gold`), else the calibration
  session's rows (`calibration`); never mixed for one work. A work with no row of the listed
  version from any source, not reviewed to empty, is served the rows of the newest older version
  that has some (`load_miner_work_rows`): its `served_version` is that version, its heading is
  tagged `(m-claims v1)` and the digest header counts such papers ("served from an older version:
  n"). Never mixed versions for one paper. A miner that is not listed in the
  protocol is refused on field `miner`.
- Rows of a paper are ordered limitation, negative-result, failure-analysis, finding, mechanism,
  no-limitation-stated, then any other claim type; ties by row key.
- `gap` is `reviewed-empty` when pass B has reviewed the work and left no final row (its pass A
  rows are then not served); `newer-version-only` when the only rows of the work are of a
  version newer than the listed one (not shown); `no-rows` when the work has no row of the miner,
  and `absence-only` when every one of its rows is `no-limitation-stated`; those rows are still
  listed. Otherwise `gap` is None.
- Held-out scrub: the title and every value and quote pass `withhold` of the held-out tokens
  (`held_out_tokens(include_work_ids=False)`); work ids are not scrubbed.
- `size` is computed from the rendered text: characters, and estimated tokens at four characters
  per token (rounded up); counts of papers, claims and gaps are computed, never typed.
- `render_claims_digest` is deterministic and pure.
"""

from __future__ import annotations

from dataclasses import dataclass

from factory.errors import FactoryValidationError, ValidationIssue
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.paper_profile import (
    PROFILE_CHARS_PER_TOKEN,
    RawMinerRow,
    listed_miner_versions,
    load_miner_work_report,
)
from factory.services.search import get_work
from factory.services.selection import Selection, SelectionSpec, resolve_selection_cached
from factory.services.withholding import held_out_tokens, withhold

__all__ = [
    "ABSENCE_TYPE",
    "CLAIM_ORDER",
    "ClaimRow",
    "ClaimsDigest",
    "DigestPaper",
    "DigestSize",
    "claims_digest",
    "render_claims_digest",
]

ABSENCE_TYPE = "no-limitation-stated"
CLAIM_ORDER = (
    "limitation",
    "negative-result",
    "failure-analysis",
    "finding",
    "mechanism",
    ABSENCE_TYPE,
)
"""The order of claim types within a paper; unlisted types follow."""


@dataclass(frozen=True)
class ClaimRow:
    """One m-claims row. A quote is the quoted text, its anchor the element it is in (None when
    the row has no such field or no anchor)."""

    row_key: str
    status: str
    version: int
    claim_type: str
    about: str
    direction: str
    evidence_type: str
    strength: str
    claim_quote: str
    claim_anchor: str | None
    conditions: str
    conditions_anchor: str | None


@dataclass(frozen=True)
class DigestPaper:
    """One paper of the selection: its code, work id, title, rows and `gap` (see the module
    invariants)."""

    code: str
    work_id: str
    title: str
    rows: tuple[ClaimRow, ...]
    gap: str | None
    served_version: int | None = None
    """The older miner version the rows come from; None when they are of the listed version (or
    the paper has no rows)."""


@dataclass(frozen=True)
class DigestSize:
    """Characters and estimated tokens of the rendered digest."""

    chars: int
    est_tokens: int


@dataclass(frozen=True)
class ClaimsDigest:
    """The digest of one selection: `selection_digest` ties it to the pinned conversions."""

    miner: str
    version: int
    selection_digest: str
    papers: tuple[DigestPaper, ...]

    @property
    def claims(self) -> int:
        """Rows over all papers, absence rows included."""
        return sum(len(p.rows) for p in self.papers)

    @property
    def gaps(self) -> tuple[tuple[str, str], ...]:
        """`(code, gap)` of every paper with a gap, in paper order."""
        return tuple((p.code, p.gap) for p in self.papers if p.gap)

    @property
    def older_served(self) -> int:
        """The papers whose rows come from an older version than the listed one."""
        return sum(1 for p in self.papers if p.served_version is not None)

    @property
    def size(self) -> DigestSize:
        text = render_claims_digest(self)
        return DigestSize(len(text), -(-len(text) // PROFILE_CHARS_PER_TOKEN))


def _text(
    row: RawMinerRow, name: str, tokens: set[str], *, quoted: bool = False
) -> tuple[str, str | None]:
    """The scrubbed text of a field and its anchor: the value, or for a quote field the quote."""
    entry = row.fields.get(name)
    if entry is None:
        return "", None
    value, _unit, anchor, quote = entry
    shown = quote if quoted and quote else str(value)
    return " ".join(str(withhold(shown, tokens)).split()), anchor


def _claim(row: RawMinerRow, tokens: set[str]) -> ClaimRow:
    def plain(name: str) -> str:
        return _text(row, name, tokens)[0]

    quote, quote_anchor = _text(row, "claim_quote", tokens, quoted=True)
    conditions, conditions_anchor = _text(row, "conditions", tokens, quoted=True)
    return ClaimRow(
        row_key=row.row_key,
        status=row.status,
        version=row.version,
        claim_type=plain("claim_type"),
        about=plain("about"),
        direction=plain("direction"),
        evidence_type=plain("evidence_type"),
        strength=plain("strength"),
        claim_quote=quote,
        claim_anchor=quote_anchor,
        conditions=conditions,
        conditions_anchor=conditions_anchor,
    )


def _rank(row: ClaimRow) -> tuple[int, str]:
    kind = row.claim_type
    return (CLAIM_ORDER.index(kind) if kind in CLAIM_ORDER else len(CLAIM_ORDER), row.row_key)


def claims_digest(
    project: Project, spec: SelectionSpec, *, miner: str = "m-claims"
) -> ClaimsDigest:
    """The digest of the works of `spec` (see the module invariants). Raises
    `FactoryValidationError` on field `miner` when it is not listed in the protocol, and on the
    selection's own fields as `resolve_selection` does."""
    project.index.sync()
    # resolved before the snapshot: a cache miss runs its own reads and must not hold the lock
    selection = resolve_selection_cached(project, spec)
    with project.index.snapshot(), entering():  # one read view: no re-sync per reader
        return _claims_digest(project, selection, miner)


def _claims_digest(project: Project, selection: Selection, miner: str) -> ClaimsDigest:
    version = dict(listed_miner_versions(project)).get(miner)
    if version is None:
        raise FactoryValidationError(
            [ValidationIssue("miner", f"{miner}: not listed in the protocol")]
        )
    work_ids = [w.work_id for w in selection.works]
    raw, emptied, newer = load_miner_work_report(project, miner, version, work_ids)
    tokens = held_out_tokens(project, include_work_ids=False)
    width = max(2, len(str(len(work_ids))))
    papers: list[DigestPaper] = []
    for position, work_id in enumerate(work_ids, start=1):
        record = get_work(project, work_id)
        title = "" if record is None else str(withhold(record.title, tokens))
        rows = tuple(sorted((_claim(r, tokens) for r in raw[work_id]), key=_rank))
        gap = (
            "reviewed-empty"
            if work_id in emptied
            else "newer-version-only"
            if work_id in newer
            else "no-rows"
            if not rows
            else "absence-only"
            if all(r.claim_type == ABSENCE_TYPE for r in rows)
            else None
        )
        served = next((r.version for r in rows if r.version < version), None)
        papers.append(DigestPaper(f"P{position:0{width}d}", work_id, title, rows, gap, served))
    return ClaimsDigest(miner, version, selection.digest, tuple(papers))


def _line(row: ClaimRow) -> str:
    anchor = f" [{row.claim_anchor}]" if row.claim_anchor else ""
    line = (
        f"- {row.claim_type} | {row.about} | {row.direction} | {row.evidence_type} | "
        f'{row.strength}: "{row.claim_quote}"{anchor}'
    )
    if row.conditions:
        where = f" [{row.conditions_anchor}]" if row.conditions_anchor else ""
        line += f' [conditions: "{row.conditions}"{where}]'
    if row.status != "final":
        line += f" ({row.status})"
    return line


def render_claims_digest(digest: ClaimsDigest) -> str:
    """The digest as Markdown: a heading `## Pxx work_id` (with `(miner vN)` for a paper served
    from an older version, counted in the first line), the title, then one line per claim
    `- type | about | direction | evidence | strength: "quote" [anchor] [conditions: "..."]`
    (`(pass-a-only)` appended for a row without final status), and a stated gap line for a paper
    with `gap`. Pure and deterministic."""
    head = f"# Claims digest: {digest.miner} v{digest.version}"
    summary = f"{head}, selection {digest.selection_digest[:12]}"
    if digest.older_served:
        summary += f", served from an older version: {digest.older_served}"
    blocks = [summary]
    for paper in digest.papers:
        tag = (
            f" ({digest.miner} v{paper.served_version})" if paper.served_version is not None else ""
        )
        lines = [f"## {paper.code} {paper.work_id}{tag}", paper.title]
        lines.extend(_line(r) for r in paper.rows)
        if paper.gap == "no-rows":
            lines.append(f"GAP: no {digest.miner} rows for this paper")
        elif paper.gap == "reviewed-empty":
            lines.append(
                f"GAP: pass B reviewed this paper and left no final {digest.miner} row; "
                "its pass A rows are not shown"
            )
        elif paper.gap == "newer-version-only":
            lines.append(
                f"GAP: only rows of a newer version than {digest.miner} v{digest.version} exist "
                "for this paper; they are not shown"
            )
        elif paper.gap == "absence-only":
            lines.append(
                "GAP: only no-limitation-stated; the paper states no limitation or other claim"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"

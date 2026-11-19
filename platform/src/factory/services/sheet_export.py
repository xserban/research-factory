"""Markdown briefs of a sheet and of an answer (spar night N8, ruling 8).

Read-only: nothing here writes an event. The brief puts the researcher's balance first, or says
plainly that none is written; it never synthesises one. Agent text (claims, sentences, strengths)
is labelled as proposed by the agent; a rating is the researcher's, and an argument without one is
marked unrated. Quotes and paragraphs come from the pinned conversion, as `view_sheet` and
`view_answer` serve them. References are every cited work once, numbered in order of first
citation, built from the canonical work records `export_bibliography` reads.

Invariants:
- Every piece of free text is escaped (`escape`) so a quote with `*`, `_`, `#` or `|` cannot
  break the document; the output is deterministic for a given log, selection and clock.
- Unknown ids are refused (`FactoryValidationError`) before any text is produced.
- No PDF: the platform has no Markdown-to-PDF path without a new dependency.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import text

from factory.clock import format_ts
from factory.errors import FactoryValidationError
from factory.model.work import Work
from factory.services import answers as answers_service
from factory.services import sheets as sheets_service
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.exports import _iter_pairs
from factory.services.selection import resolve_selection_cached

__all__ = ["escape", "export_answer", "export_sheet"]

PROPOSED = "proposed by agent"
UNRATED = "Not rated by the researcher."
NO_BALANCE = "No balance written by the researcher yet."
_SPECIAL = re.compile(r"([\\`*_{}\[\]<>#|])")


def escape(value: str) -> str:
    """`value` on one line with Markdown punctuation backslash-escaped."""
    return _SPECIAL.sub(r"\\\1", " ".join(value.split()))


def _quote_block(value: str) -> list[str]:
    """A blockquote of `value`, one line per source line, each escaped."""
    lines = [ln for ln in value.splitlines() if ln.strip()] or [""]
    return [f"> {escape(ln)}" for ln in lines]


def _paragraph(project: Project, cache: dict[str, object], conversion_id: str, anchor: str) -> str:
    if conversion_id not in cache:
        try:
            cache[conversion_id] = conversion_manifest(project, conversion_id)
        except FactoryValidationError:
            cache[conversion_id] = None
    manifest = cache[conversion_id]
    found = None if manifest is None else manifest.get(anchor)  # type: ignore[attr-defined]
    return "" if found is None else str(found.text)


def _reference(n: int, work: Work) -> str:
    names = [a.name for a in work.authors]
    who = escape("; ".join(names)) if names else "Anonymous"
    year = work.dates.year
    parts = [f"{n}. {who} ({year if year else 'n.d.'}). {escape(work.title)}."]
    if work.venue and work.venue.name:
        venue = escape(work.venue.name)
        for label, val in (("vol. ", work.venue.volume), ("no. ", work.venue.issue)):
            if val:
                venue += f", {label}{escape(val)}"
        if work.venue.pages:
            venue += f", pp. {escape(work.venue.pages)}"
        parts.append(f"{venue}.")
    ids = work.identifiers
    if ids.doi:
        parts.append(f"doi:{escape(ids.doi)}")
    elif ids.arxiv:
        parts.append(f"arXiv:{escape(ids.arxiv)}")
    elif ids.url:
        parts.append(escape(ids.url))
    return " ".join(parts)


def _references(project: Project, work_ids: Iterable[str]) -> tuple[dict[str, int], list[str]]:
    order = list(dict.fromkeys(work_ids))
    numbers = {wid: i for i, wid in enumerate(order, 1)}
    found = dict(_iter_pairs(project, order))
    lines = []
    for wid in order:
        work = found.get(wid)
        lines.append(
            _reference(numbers[wid], work)
            if work
            else f"{numbers[wid]}. `{wid}` (record not found)."
        )
    return numbers, lines


def _agent_events(project: Project, ref: str) -> list[tuple[str, str]]:
    """The distinct (model, skill) pairs of the agent events that refer to `ref`."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT e.model, e.skill FROM events e "
                "JOIN event_refs r ON r.event_id = e.id "
                "WHERE r.ref = :r AND e.actor_kind = 'agent' ORDER BY e.model, e.skill"
            ),
            {"r": ref},
        ).all()
    return [(m or "unknown model", s or "unknown skill") for m, s in rows]


def _footer(
    project: Project, ident: str, digest: str, stale: bool, selection: dict[str, object]
) -> list[str]:
    out = ["## Provenance", "", f"- Identifier: `{ident}`"]
    pairs = _agent_events(project, ident)
    agents = "; ".join(f"{escape(m)}, skill {escape(s)}" for m, s in pairs) or "none recorded"
    out.append(f"- Agent events (model, skill version): {agents}")
    out.append(f"- Selection digest: {digest}")
    out.append(f"- Exported: {format_ts(project.clock.now())}")
    if stale:
        out.append(
            "- Stale: the selection has changed since this was written; "
            "the corpus now differs from the one the arguments were drawn from."
        )
    return out


def _is_stale(project: Project, selection: dict[str, object], digest: str) -> bool:
    return resolve_selection_cached(project, sheets_service._spec_of(selection)).digest != digest


def _rating_lines(rating: str | None, note: str | None) -> list[str]:
    if rating is None:
        return [f"- {UNRATED}"]
    line = f"- Rating (researcher): {escape(rating)}"
    return [line + (f" — {escape(note)}" if note else "")]


def export_sheet(project: Project, sheet_id: str) -> str:
    """The sheet as a Markdown brief: balance first, then the case against and the case for, then
    the references and the provenance footer."""
    view = sheets_service.view_sheet(project, sheet_id)
    info, cov = view.info, view.coverage
    numbers, refs = _references(project, (a.work_id for a in view.arguments))
    cache: dict[str, object] = {}
    out = [
        f"# {escape(info.hypothesis)}",
        "",
        f"Mode: {escape(info.mode)}. Sheet `{info.sheet_id}`, opened {escape(info.ts)}.",
        "",
        f"Selection: {cov.total} candidate works (tier 1/2/3: {cov.by_tier[1]}/{cov.by_tier[2]}/"
        f"{cov.by_tier[3]}); {cov.arguments['against']} argument(s) against, "
        f"{cov.arguments['for']} for; {cov.unrated} unrated.",
        "",
        "## The researcher's balance",
        "",
    ]
    if view.balance is None:
        out.append(NO_BALANCE)
    else:
        b = view.balance
        lean = f" Lean: {escape(b.lean)}." if b.lean else ""
        out += [escape(b.text), "", f"By {escape(b.actor)}, {escape(b.ts)}.{lean}"]
        if b.note:
            out.append(f"Further evidence needed: {escape(b.note)}")
    for stance, heading in (("against", "Case against"), ("for", "Case for")):
        out += ["", f"## {heading}", ""]
        mine = [a for a in view.arguments if a.stance == stance]
        if not mine:
            out += ["No arguments.", ""]
        for i, a in enumerate(mine, 1):
            out += [
                f"### {heading} {i}",
                "",
                f"- Claim ({PROPOSED}): {escape(a.claim)}",
                f"- Stance: {escape(a.stance)}. Strength ({PROPOSED}): {escape(a.strength)}.",
                f"- Source: [{numbers[a.work_id]}], anchor {escape(a.anchor)}.",
                *_rating_lines(a.rating, a.rating_note),
                "",
                "Verified quote:",
                "",
                *_quote_block(a.quote),
                "",
            ]
            para = _paragraph(project, cache, a.conversion_id, a.anchor)
            out += [
                "Source paragraph:",
                "",
                *(_quote_block(para) if para else ["> (not available)"]),
                "",
            ]
            if a.linked_claim:
                k = a.linked_claim
                out += [
                    f"Linked claim `{a.claim_row_key}` "
                    f"({escape(k.claim_type)}, {escape(k.about)}): {escape(k.quote)}",
                    "",
                ]
    out += ["## References", "", *refs, ""]
    out += _footer(
        project,
        info.sheet_id,
        info.selection_digest,
        _is_stale(project, view.selection, info.selection_digest),
        view.selection,
    )
    return "\n".join(out) + "\n"


def export_answer(project: Project, answer_id: str) -> str:
    """The answer as a Markdown brief: question, each sentence with its quote, paragraph and
    rating, what is unanswered, the references and the provenance footer."""
    view = answers_service.view_answer(project, answer_id)
    info = view.info
    numbers, refs = _references(project, (s.work_id for s in view.sentences))
    out = [
        f"# {escape(info.question)}",
        "",
        f"Answer `{info.answer_id}`, recorded {escape(info.ts)}. {view.counts.sentences} "
        f"sentence(s) from {view.counts.works} work(s); {view.counts.unrated} unrated.",
        "",
        "## Whole answer",
        "",
        *_rating_lines(view.rating, view.rating_note),
        "",
        "## Answer",
        "",
    ]
    for s in view.sentences:
        out += [
            f"### {s.index}. {escape(s.text)}",
            "",
            f"- Sentence ({PROPOSED}). Source: [{numbers[s.work_id]}], anchor {escape(s.anchor)}.",
            *_rating_lines(s.rating, s.rating_note),
            "",
            "Verified quote:",
            "",
            *_quote_block(s.quote),
            "",
            "Source paragraph:",
            "",
            *(_quote_block(s.paragraph) if s.paragraph else ["> (not available)"]),
            "",
        ]
    if view.unanswered:
        out += ["## Not answered by the papers", "", f"{escape(view.unanswered)} ({PROPOSED})", ""]
    out += ["## References", "", *refs, ""]
    stale = _is_stale(project, view.selection, info.selection_digest)
    out += _footer(project, info.answer_id, info.selection_digest, stale, view.selection)
    return "\n".join(out) + "\n"

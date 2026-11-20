"""Markdown briefs of a sheet and of an answer (spar night N8, ruling 8).

Read-only: nothing here writes an event. The brief puts the researcher's balance first, or says
plainly that none is written; it never synthesises one. Agent text (claims, sentences, strengths)
is labelled as proposed by the agent; a rating is the researcher's, and an argument without one is
marked unrated. Quotes and paragraphs come from the pinned conversion, as `view_sheet` and
`view_answer` serve them. References are every cited work once, numbered in order of first
citation, built from the canonical work records `export_bibliography` reads.

Invariants:
- Every piece of free text is escaped (`escape`) so a quote with `*`, `_`, `#` or `|` cannot
  break the document; the output is deterministic for a given log and selection under a fixed
  clock (the footer prints the export time).
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
_LEAD = re.compile(r"^([-+=]|\d+[.)]|~{3,}|:)")


def escape(value: str) -> str:
    """`value` on one line with Markdown punctuation backslash-escaped."""
    flat = _SPECIAL.sub(r"\\\1", " ".join(value.split()))
    return _LEAD.sub(r"\\\1", flat)  # a leading list, rule or setext marker is not structure


def _quote_block(value: str) -> list[str]:
    """A blockquote of `value`, one line per source line, each escaped."""
    lines = [ln for ln in value.splitlines() if ln.strip()] or [""]
    return [f"> {escape(ln)}" for ln in lines]


def _text_block(value: str) -> list[str]:
    """A blockquote of `value` that keeps its paragraph breaks; every line is escaped."""
    out: list[str] = []
    for ln in value.splitlines():
        if ln.strip():
            out.append(f"> {escape(ln)}")
        elif out and out[-1] != ">":
            out.append(">")
    while out and out[-1] == ">":
        out.pop()
    return out or ["> "]


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


def _agent_events(project: Project, ref: str) -> list[tuple[str, str, int]]:
    """The distinct (model, skill) pairs of the agent events that refer to `ref`, with the number
    of events of each pair."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT e.model, e.skill, COUNT(DISTINCT e.id) FROM events e "
                "JOIN event_refs r ON r.event_id = e.id "
                "WHERE r.ref = :r AND e.actor_kind = 'agent' "
                "GROUP BY e.model, e.skill ORDER BY e.model, e.skill"
            ),
            {"r": ref},
        ).all()
    return [(m or "unknown model", s or "unknown skill", int(n)) for m, s, n in rows]


def _footer(
    project: Project, ident: str, digest: str, stale: bool | None, selection: dict[str, object]
) -> list[str]:
    out = ["## Provenance", "", f"- Identifier: `{ident}`"]
    pairs = _agent_events(project, ident)
    agents = (
        "; ".join(
            f"{escape(m)}, skill {escape(s)} ({n} event{'' if n == 1 else 's'})"
            for m, s, n in pairs
        )
        or "none recorded"
    )
    out.append(f"- Agent events (model, skill version): {agents}")
    out.append(f"- Selection digest: {digest}")
    out.append(f"- Exported: {format_ts(project.clock.now())}")
    if stale is None:
        out.append("- Stale: the selection can no longer be resolved.")
    elif stale:
        out.append(
            "- Stale: the selection has changed since this was written; "
            "the corpus now differs from the one the arguments were drawn from."
        )
    return out


def _is_stale(project: Project, selection: dict[str, object], digest: str) -> bool | None:
    """Whether the selection now resolves to another digest; None if it cannot be resolved."""
    try:
        spec = sheets_service._spec_of(selection)
        return resolve_selection_cached(project, spec).digest != digest
    except FactoryValidationError:
        return None


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
    ordered = [a for st in ("against", "for") for a in view.arguments if a.stance == st]
    numbers, refs = _references(project, (a.work_id for a in ordered))
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
        out += [*_text_block(b.text), "", f"By {escape(b.actor)}, {escape(b.ts)}.{lean}"]
        if b.note:
            out += ["", "Further evidence needed:", "", *_text_block(b.note)]
        if view.balance_history > 1:
            out += ["", f"Superseded balances: {view.balance_history - 1}"]
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
                note = sheets_service.claim_link_note(k)
                flag = f" ({note})" if note else ""
                detail = (
                    ""
                    if k.missing
                    else f" ({escape(k.claim_type)}, {escape(k.about)}): {escape(k.quote)}"
                )
                out += [f"Linked claim `{a.claim_row_key}`{detail}{flag}", ""]
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
    out += ["## Not answered by the papers", ""]
    if view.unanswered:
        out += [*_text_block(view.unanswered), "", f"({PROPOSED})", ""]
    else:
        out += ["No gaps declared by the agent.", ""]
    out += ["## References", "", *refs, ""]
    stale = _is_stale(project, view.selection, info.selection_digest)
    out += _footer(project, info.answer_id, info.selection_digest, stale, view.selection)
    return "\n".join(out) + "\n"

"""The review and clean renderings of a draft (slice 7b, plan W-B, ruling 7; spec ruling 14). Pure.

Declares: `render_review`, `render_clean`, `render_closing`, `with_note`, `RENDER_VERSION`.

Invariants:
- Everything here is read from what it is given: no log, no index, no clock, so a rendering is a
  function of its inputs.
- In a clean rendering a `claim` or `synthesis` sentence that is not `supported`, and any stale
  sentence, is wrapped in `[[UNSUPPORTED: <status>; <reason>]] ... [[/]]`, an interpretive one in
  `[[INTERPRETATION]] ... [[/]]`. A rendering with no marker is possible only for a draft in which
  every claim-bearing sentence is `supported`. Nothing else in the output uses the `[[` form.
- Citation keys follow the sentence as `[@key1; @key2]`, in support order, de-duplicated; a writer
  never types one (spec ruling 11).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from factory.model.drafts import DraftAuditReport

if TYPE_CHECKING:
    from factory.services.drafts import DraftView, RenderedSentence, StatusRow

RENDER_VERSION = 1
_NEEDS_RESOLVING = ("unchecked", "flagged", "stale")


def _by_id(statuses: Sequence[StatusRow]) -> dict[str, StatusRow]:
    return {s.sentence_id: s for s in statuses}


def _counts_line(statuses: Sequence[StatusRow]) -> str:
    counts: dict[str, int] = {}
    for row in statuses:
        counts[row.status] = counts.get(row.status, 0) + 1
    if not counts:
        return "No sentences."
    return "Sentences by status: " + ", ".join(f"{k} {counts[k]}" for k in sorted(counts)) + "."


def render_review(
    draft: DraftView, statuses: Sequence[StatusRow], spans: Mapping[str, Sequence[str]]
) -> str:
    """Every sentence with its status tag, flags, supports and their quotes; `spans` maps a support
    in grammar form to what it says (read from events, never from the library)."""
    rows = _by_id(statuses)
    lines = [f"# {draft.title} (review)", "", _counts_line(statuses)]
    for section in draft.sections:
        if not section.sentences:
            continue
        lines += ["", f"## {section.heading}"]
        for sentence in section.sentences:
            row = rows[sentence.sentence_id]
            reason = f"; {row.reason}" if row.reason else ""
            lines += ["", f"{{{row.status}{reason}}} {sentence.sentence_id} ({row.cls.value})"]
            lines.append(sentence.text)
            if row.flags:
                lines.append("flags: " + ", ".join(row.flags))
            for support in sentence.supports:
                lines.append(f"- {support}")
                lines.extend(f"  > {quote}" for quote in spans.get(support, ()))
    return "\n".join(lines) + "\n"


def _cited(sentence: RenderedSentence, keys: Mapping[str, str]) -> str:
    found = list(dict.fromkeys(keys[w] for w in sentence.works if w in keys))
    if not found:
        return sentence.text
    return f"{sentence.text} [" + "; ".join(f"@{k}" for k in found) + "]"


def _marked(sentence: RenderedSentence, row: StatusRow, keys: Mapping[str, str]) -> str:
    body = _cited(sentence, keys)
    if row.status in _NEEDS_RESOLVING:
        reason = row.reason or "no-verdict"
        return f"[[UNSUPPORTED: {row.status}; {reason}]] {body} [[/]]"
    if row.status == "interpretive":
        return f"[[INTERPRETATION]] {body} [[/]]"
    return body


def render_clean(draft: DraftView, statuses: Sequence[StatusRow], keys: Mapping[str, str]) -> str:
    """The prose with citations and markers, the counts by status under the title, and an appendix
    listing what is unchecked, flagged or stale; `keys` maps a work id to its citation key."""
    rows = _by_id(statuses)
    lines = [f"# {draft.title}", "", _counts_line(statuses)]
    for section in draft.sections:
        if not section.sentences:
            continue
        said = (_marked(s, rows[s.sentence_id], keys) for s in section.sentences)
        lines += ["", f"## {section.heading}", "", " ".join(said)]
    open_rows = [s for s in statuses if s.status in _NEEDS_RESOLVING]
    if open_rows:
        lines += ["", "## Appendix: sentences not supported", ""]
        lines += [f"- {r.sentence_id}: {r.status} ({r.reason or 'no-verdict'})" for r in open_rows]
    return "\n".join(lines) + "\n"


def with_note(body: str, note: str) -> str:
    """The rendering with `note` as its own paragraph under the title."""
    title, _, rest = body.partition("\n")
    return f"{title}\n\n{note}\n{rest}"


def render_closing(
    draft_id: str,
    statuses: Sequence[StatusRow],
    audit: DraftAuditReport,
    same_model: int,
) -> str:
    """The bibliography note and the methods paragraph of a clean rendering; every figure derived.
    The agent variant of `audit` carries no result, so none is stated."""
    if audit.drawn == 0 and audit.all_drawn == 0:
        summary = "No audit of the supported verdicts was drawn."
    elif audit.incorrect is None:
        summary = "The audit of the supported verdicts is reported to the researcher."
    else:
        summary = (
            f"A human audit labelled {audit.labelled} of {audit.drawn} sampled supported "
            f"verdicts and found {audit.incorrect} incorrect"
        )
        summary += "." if audit.rate is None else f" (error rate {audit.rate:.3f})."
    if audit.all_rate is not None:
        summary += (
            f" Every sample, revised sentences included: {audit.all_incorrect} of "
            f"{audit.all_labelled} labelled verdicts incorrect (error rate {audit.all_rate:.3f})."
        )
    lines = [
        "## Bibliography",
        "",
        f"Export the cited works with `factory export bibtex --scope draft:{draft_id}`.",
        "",
        "## Methods",
        "",
        f"{_counts_line(statuses)} {summary} "
        f"Verdicts by the writer's model: {same_model}. Rendering version {RENDER_VERSION}.",
    ]
    return "\n".join(lines) + "\n"

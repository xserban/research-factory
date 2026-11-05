"""The briefing as Markdown (slice 7b, plan V-C, task 4).

Declares: `briefing_markdown`. Pure formatting of a `Briefing`: no count, status or order is
computed here, so two renders of the same briefing are byte-identical. Every section heading is
always printed; an empty section says so. The output names `as_of` and the notices.
"""

from __future__ import annotations

import json

from factory.model.views import Briefing, GateBrief, PathEntry, PendingBrief, WorkBrief

_NONE = "None."


def briefing_markdown(b: Briefing) -> str:
    """The reading path as a numbered list, amendments as a table, and each pending decision with
    the command that resolves it."""
    parts = [
        f"# Project briefing: {b.meta.project}",
        f"As of {b.meta.as_of or 'the start of the log'}.",
        *_notices(b),
        _question(b),
        _protocol(b),
        _gates(b),
        _corpus(b),
        _reading_path(b),
        _evidence(b),
        _issues(b),
        _pending(b),
        _drafts(b),
    ]
    return "\n\n".join(parts) + "\n"


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _notices(b: Briefing) -> list[str]:
    if not b.meta.notices:
        return []
    return ["\n".join(f"- {n.text}" for n in b.meta.notices)]


def _question(b: Briefing) -> str:
    q = b.question
    lines = ["## Question"]
    if q.raw_goal is not None:
        lines.append(f"Goal: {q.raw_goal}")
    if q.question_id is None:
        return "\n\n".join([*lines, "No question is recorded."])
    lines.append(f"{q.question_id}: {q.primary_question}")
    elements = [
        f"- {e.name}: {e.value}"
        if e.value is not None
        else f"- {e.name}: open ({e.open}; resolved in {e.resolve_in})"
        for e in q.elements
    ]
    lines.append("Elements:\n" + "\n".join(elements))
    if q.non_goals:
        lines.append("Non-goals:\n" + "\n".join(f"- {g.id}: {g.text}" for g in q.non_goals))
    return "\n\n".join(lines)


def _protocol(b: Briefing) -> str:
    p = b.protocol
    lines = ["## Protocol"]
    if p.protocol_id is None:
        return "\n\n".join([*lines, f"No protocol is recorded. Rigour mode: {p.rigor_mode}."])
    lines.append(f"{p.protocol_id}; rigour mode {p.rigor_mode}; method profile {p.method_profile}.")
    if p.amendments:
        rows = [
            f"| {a.amendment_id} | {a.date} | {'yes' if a.semantic else 'no'} | {_cell(a.reason)} |"
            for a in p.amendments
        ]
        header = "| Amendment | Date | Semantic | Reason |\n| --- | --- | --- | --- |\n"
        lines.append(header + "\n".join(rows))
    else:
        lines.append("No amendments.")
    if p.deviations:
        lines.append(
            "Deviations:\n"
            + "\n".join(
                f"- {d.deviation_id} ({d.date}): {_cell(d.description)}. {_cell(d.reason)}"
                for d in p.deviations
            )
        )
    return "\n\n".join(lines)


def _state(g: GateBrief) -> str:
    if g.passed is None:
        return "labelled-complete" if g.labelled_complete else "labels outstanding"
    state = "passed" if g.passed else "not passed"
    return f"{state}, above ceiling" if g.figures.get("above_ceiling") is True else state


def _gate(g: GateBrief) -> str:
    scope = "" if g.scope is None else f" ({g.scope})"
    state = _state(g)
    day = "" if g.date is None else f", {g.date}"
    figures = "" if not g.figures else f": {json.dumps(g.figures, sort_keys=True)}"
    return f"- {g.gate}{scope}: {state}{day}{figures}"


def _gates(b: Briefing) -> str:
    body = "\n".join(_gate(g) for g in b.gates) or _NONE
    note = (
        "An audit is passed when its sample is fully labelled and its rate is not above a ceiling "
        "enforced in this rigour mode."
    )
    return f"## Gates\n\n{body}\n\n{note}"


def _corpus(b: Briefing) -> str:
    flow = json.dumps(b.corpus.prisma, sort_keys=True, indent=2)
    searches = "\n".join(f"- {s}: {d}" for s, d in b.corpus.last_search.items()) or _NONE
    return f"## Corpus\n\nPRISMA flow:\n\n```json\n{flow}\n```\n\nLast search:\n\n{searches}"


def _work(w: WorkBrief) -> str:
    year = "undated" if w.year is None else str(w.year)
    return f"{w.title} ({year}) [{w.key}]"


def _entry(number: int, e: PathEntry) -> str:
    lines = [f"{number}. {e.name} ({e.idea_id}). Origin: {_work(e.origin)}"]
    if e.members:
        lines.append(f"   Most recent of {e.members_total} member(s):")
        lines += [f"   - {_work(w)}" for w in e.members]
    lines += [f"   Path: {' -> '.join(p)}" for p in e.paths]
    return "\n".join(lines)


def _reading_path(b: Briefing) -> str:
    body = "\n".join(_entry(i, e) for i, e in enumerate(b.reading_path, start=1)) or _NONE
    return f"## Reading path\n\n{body}"


def _evidence(b: Briefing) -> str:
    rows = [
        f"- {g.group_id} ({', '.join(f'{k}={v}' for k, v in g.key)}): {g.works} work(s)"
        for g in b.evidence
    ]
    return "## Evidence groups\n\n" + ("\n".join(rows) or _NONE)


def _issues(b: Briefing) -> str:
    rows = [f"- {code}: {count}" for code, count in b.issues.items()]
    return "## Open issues\n\n" + ("\n".join(rows) or _NONE)


def _pending_row(p: PendingBrief) -> str:
    stage = "" if p.stage is None else f" ({p.stage})"
    ids = "" if not p.ids else f": {', '.join(p.ids)}"
    return f"- {p.kind}{stage}: {p.count}{ids}\n  `{p.command}`"


def _pending(b: Briefing) -> str:
    return "## Pending human decisions\n\n" + (
        "\n".join(_pending_row(p) for p in b.pending) or _NONE
    )


def _drafts(b: Briefing) -> str:
    rows = [
        f"- {d.draft_id}, {d.title}, released {d.released}: "
        + ", ".join(f"{status} {count}" for status, count in d.counts.items())
        for d in b.drafts
    ]
    return "## Released drafts\n\n" + ("\n".join(rows) or _NONE)

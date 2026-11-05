"""Deterministic renderings of a digest (living-D): Markdown for people, canonical JSON for tools.

Pure. The same `Digest` always renders to the same bytes: JSON keys are sorted and lists keep the
order the builder gave; the Markdown follows a fixed layout. Nothing here adds a word of judgement:
only labels, ids, titles and computed counts appear.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from factory.clock import format_ts

if TYPE_CHECKING:
    from factory.services.digest import Digest, DigestProject


def to_json(d: Digest) -> str:
    """The digest as canonical JSON (sorted keys, two-space indent, trailing newline)."""
    data = d.model_dump(mode="json")
    data["generated_at"] = format_ts(d.generated_at)
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def to_markdown(d: Digest) -> str:
    """The digest as Markdown."""
    lines = [
        f"# Digest {d.digest_id or '(not recorded)'}",
        "",
        f"Generated {format_ts(d.generated_at)}.",
    ]
    for part in d.projects:
        lines += _project(part)
    return "\n".join(lines) + "\n"


def _project(p: DigestProject) -> list[str]:
    window = f"after {p.since_event}" if p.since_event else "from the start of the log"
    lines = ["", f"## {p.slug} ({p.status})", "", f"Window: {window} up to {p.cutoff_event}."]
    lines += ["", "### Cycles", ""]
    if not p.cycles:
        lines.append("None.")
    for cycle in p.cycles:
        lines.append(f"- {cycle.cycle_id} {cycle.status.value} started {cycle.started_at}")
        for k in cycle.counts:
            lines.append(
                f"  - {k.source}: {k.complete_runs}/{k.runs} runs complete, "
                f"{k.retrieved} retrieved, {k.new_works} new, {k.duplicates_in_cycle} duplicates"
            )
    lines += ["", f"### New candidates ({len(p.new_candidates.items) + p.new_candidates.more})", ""]
    for row in p.new_candidates.items:
        queries = ", ".join(row.query_ids) or "no query"
        lines.append(f"- {row.work_id} {row.title} [{row.route}; {queries}]")
    lines += _more(p.new_candidates.more)
    lines += ["", "### Open decisions", ""]
    lines += [f"- {key}: {p.open_decisions[key]}" for key in sorted(p.open_decisions)]
    lines += ["", f"### Notices ({len(p.notices.items) + p.notices.more})", ""]
    for n in p.notices.items:
        when = n.notice_date or "date unknown"
        state = "assessed" if n.assessed else "not assessed"
        lines.append(f"- {n.notice_id} {n.kind} of {n.work_id}, {when}, {n.source}, {state}")
    lines += _more(p.notices.more)
    lines += ["", f"### Versions ({len(p.versions.items) + p.versions.more})", ""]
    lines += [f"- {v.work_id} {v.kind}: {v.detail}" for v in p.versions.items]
    lines += _more(p.versions.more)
    lines += ["", "### Conclusions", ""]
    if not p.conclusions:
        lines.append("None registered.")
    for c in p.conclusions:
        lines.append(f"- {c.conclusion_id} {c.state}")
        lines += [f"  - affected: {a}" for a in c.affected]
        if c.facts is not None:
            for g in c.facts.groups:
                lines.append(f"  - group {g.group_id}: rows {g.rows_delta:+d}")
                if g.best_changed is not None:
                    before, after = g.best_changed
                    lines.append(f"    - best row {_rows(before)} -> {_rows(after)}")
                for key, rows in sorted(g.frontier_added.items()):
                    lines.append(f"    - frontier {key} gained {_rows(rows)}")
                for key, rows in sorted(g.frontier_removed.items()):
                    lines.append(f"    - frontier {key} lost {_rows(rows)}")
    lines += ["", "### Failures and overdue watches", ""]
    lines += [f"- failure: {f}" for f in p.failures] or ["- no failures"]
    lines += [f"- overdue: {o}" for o in p.overdue]
    if p.update_flow is not None:
        flow = p.update_flow
        lines += [
            "",
            "### Update flow",
            "",
            f"- previously included: {flow.previous_included}",
            f"- screened: {flow.screened}; pending: {flow.pending}; included: {flow.included}",
            f"- total included: {flow.total_included}",
        ]
    return lines


def _more(more: int) -> list[str]:
    return [f"- and {more} more"] if more else []


def _rows(rows: tuple[str, ...] | None) -> str:
    return "none" if not rows else ", ".join(rows)

"""Render one level of the develop stage as a formal Markdown document (slice 8, plan A9).

The levels are goal, questions, plan, seeds, probe and protocol. A level document is drawn from
the decision events of that level: for each suggestion set the step and why, the items with their
status (Validated, Rejected, Added, Proposed) and grounds, the scientist's note and the
supersession history; for the questions and protocol levels it also gives the spec currently
recorded.

Invariants:
- The Markdown is a pure function of the events: no render time, no version number and no random
  element appears in it, so the same events give the same bytes.
- Recording `document.rendered` is the platform's act (system actor). A render that equals the
  level's latest one writes nothing and returns that render; otherwise the version is one more
  than the latest of the level. Nothing else depends on the event.
- The Markdown stored in the blob is the full view. An agent-facing surface scrubs it
  (`agent_view.scrubbed_text`) before showing it; the stored text is never altered.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.events.reader import read_all
from factory.model.base import StrictModel
from factory.model.decisions import DecisionLevel
from factory.model.develop import DocumentRendered
from factory.model.protocol import ProtocolSpec
from factory.model.question import QuestionSpec
from factory.services import decisions as decisions_service
from factory.services import protocol as protocol_service
from factory.services import question as question_service
from factory.services.context import Project

LEVEL_TITLES: dict[DecisionLevel, str] = {
    DecisionLevel.GOAL: "Goal",
    DecisionLevel.QUESTIONS: "Research questions",
    DecisionLevel.PLAN: "Research plan",
    DecisionLevel.SEEDS: "Seeds",
    DecisionLevel.PROBE: "Probe",
    DecisionLevel.PROTOCOL: "Review protocol",
}

_STATUS = {
    "proposed": "Proposed",
    "validated": "Validated",
    "rejected": "Rejected",
    "added": "Added",
}

_STATE = {"open": "awaiting selection", "selected": "selected", "superseded": "superseded"}


class RenderResult(StrictModel):
    """`event_id` is the `document.rendered` event of this version; `unchanged` is true when the
    level's latest render already held exactly this Markdown and nothing was written."""

    level: str
    version: int
    event_id: str
    blob: str
    sources: tuple[str, ...]
    unchanged: bool
    markdown: str


def _cell(value: str) -> str:
    """One line of Markdown table text: no newline and no pipe."""
    return " ".join(value.split()).replace("|", "\\|")


def _decision_lines(view: decisions_service.DecisionView, heading: str) -> list[str]:
    lines = [f"{heading} {view.subject} ({view.decision_id})", ""]
    state = _STATE[view.state]
    lines.append(f"State: {state}. Suggested {view.suggested_at} by {view.actor}.")
    if view.supersedes:
        lines.append(f"Replaces {view.supersedes}.")
    if view.superseded_by:
        lines.append(f"Replaced by {view.superseded_by}.")
    lines += ["", "Step and reason.", "", view.explanation.strip(), "", "Items.", ""]
    for item in view.items:
        grounds = "; ".join(item.grounds) if item.grounds else "none stated"
        extra = ""
        if item.origin == "added":
            extra = " Added by the scientist."
        elif item.recommended:
            extra = " Recommended by the agent (technical subject)."
        lines.append(
            f"- {item.item_id} [{_STATUS[item.status]}] {item.text.strip()} "
            f"Grounds: {grounds}.{extra}"
        )
    sel = view.selection
    if sel is not None:
        kind = " (reconstructed from an earlier record)" if sel.reconstructed else ""
        lines += ["", f"Selection by {sel.actor} at {sel.ts} via {sel.channel}{kind}."]
        if sel.note:
            lines.append(f"Note of the scientist: {sel.note}")
    lines.append("")
    return lines


def _question_lines(project: Project) -> list[str]:
    found = question_service.question_view(project)
    lines = ["## Recorded question", ""]
    if found.spec is None or found.question_id is None:
        return [*lines, "No question is recorded.", ""]
    spec: QuestionSpec = found.spec
    lines += [f"Version: {found.question_id}.", "", f"Main question: {spec.primary_question}", ""]
    if found.raw_goal:
        lines += [f"Goal as stated: {found.raw_goal.strip()}", ""]
    lines += [f"Scheme: {spec.scheme}.", ""]
    lines += ["| Slot | Value | Open until |", "|---|---|---|"]
    for slot in sorted(spec.slots, key=lambda s: s.name):
        value = slot.value if slot.value is not None else f"open: {slot.open}"
        lines.append(f"| {_cell(slot.name)} | {_cell(value)} | {_cell(slot.resolve_in or '')} |")
    lines.append("")
    if spec.sub_questions:
        lines += ["Sub-questions.", ""]
        for sub in sorted(spec.sub_questions, key=lambda s: s.id):
            serves = f" Serves: {sub.serves}." if sub.serves else ""
            lines.append(f"- {sub.id}: {sub.text}{serves}")
        lines.append("")
    if spec.non_goals:
        lines += ["Non-goals.", ""]
        lines += [f"- {n.id}: {n.text}" for n in sorted(spec.non_goals, key=lambda n: n.id)]
        lines.append("")
    if spec.objectives:
        lines += [f"Objectives: {spec.objectives.strip()}", ""]
    if spec.rationale:
        lines += [f"Rationale: {spec.rationale.strip()}", ""]
    return lines


def _protocol_lines(project: Project) -> list[str]:
    found = protocol_service.protocol_view(project)
    lines = ["## Recorded protocol", ""]
    if found.spec is None or found.protocol_id is None:
        return [*lines, "No protocol is recorded.", ""]
    spec: ProtocolSpec = found.spec
    lines += [
        f"Version: {found.protocol_id}; status {found.status}; "
        f"question {spec.question_id}; method profile {spec.method_profile.value}; "
        f"{len(found.amendments)} amendment(s).",
        "",
        "Criteria.",
        "",
        "| Id | Statement | Rule | Applies at | Priority |",
        "|---|---|---|---|---|",
    ]
    for c in spec.criteria:
        priority = "" if c.priority is None else str(c.priority)
        lines.append(
            f"| {c.id} | {_cell(c.statement)} | {_cell(c.rule)} | {c.applies_at.value} "
            f"| {priority} |"
        )
    lines += ["", "Sources.", ""]
    for s in spec.sources:
        state = "searched" if s.included else "not searched"
        why = f" {s.why}" if s.why else ""
        lines.append(f"- {s.name}: {state}.{why}")
    lines += ["", f"Planned queries: {len(spec.queries)}."]
    for limit in spec.limits:
        lines.append(f"Limit {limit.field}: {limit.value}.")
    plan = spec.screening
    stop = plan.stop_after_consecutive_excludes
    lines.append(
        f"Screening: {plan.passes} pass(es); calibration {plan.calibration_size}; "
        f"audit {plan.audit_fraction} (minimum {plan.audit_minimum}); stop rule "
        + ("none." if stop is None else f"{stop} consecutive exclusions.")
    )
    snow = spec.snowball_plan
    if snow is not None:
        lines.append(
            f"Snowballing: up to {snow.max_backward_rounds} backward and "
            f"{snow.max_forward_rounds} forward round(s); stop when no new inclusion: "
            f"{'yes' if snow.stop_when_no_new_included else 'no'}."
        )
    ext = spec.extraction_schema
    if ext is not None:
        lines.append(
            f"Extraction: pack {ext.pack} v{ext.pack_version}; fields {', '.join(ext.fields)}."
        )
    lines.append("")
    return lines


def render_markdown(project: Project, level: DecisionLevel) -> tuple[str, tuple[str, ...]]:
    """The level's document and the ids of the events it is drawn from (sorted)."""
    rows = decisions_service.list_decisions(project, level)
    views = [decisions_service.view_decision(project, r.decision_id) for r in rows]
    lines = [f"# {LEVEL_TITLES[level]}", ""]
    if not views:
        lines += ["No decision is recorded for this level.", ""]
    current = [v for v in views if v.state != "superseded"]
    old = [v for v in views if v.state == "superseded"]
    if current:
        lines += ["## Decisions", ""]
        for v in current:
            lines += _decision_lines(v, "###")
    if old:
        lines += ["## Superseded decisions", ""]
        for v in old:
            lines += _decision_lines(v, "###")
    if level is DecisionLevel.QUESTIONS:
        lines += _question_lines(project)
    elif level is DecisionLevel.PROTOCOL:
        lines += _protocol_lines(project)
    ids = {v.decision_id for v in views}
    sources = sorted(
        e.id
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type in ("decision.suggested", "decision.selected")
        and e.payload.get("decision_id") in ids
    )
    return "\n".join(lines).rstrip("\n") + "\n", tuple(sources)


def _latest(project: Project, level: DecisionLevel) -> tuple[int, str, str] | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT version, blob, event_id FROM document_renders WHERE level = :l "
                "ORDER BY version DESC LIMIT 1"
            ),
            {"l": level.value},
        ).first()
    return None if row is None else (int(row[0]), str(row[1]), str(row[2]))


def render_level(project: Project, level: DecisionLevel) -> RenderResult:
    """Render the level, record `document.rendered` (unless nothing changed) and return it."""
    with project.writing():
        project.index.sync()
        markdown, sources = render_markdown(project, level)
        blob = project.blobs.put(markdown.encode("utf-8"))
        latest = _latest(project, level)
        if latest is not None and latest[1] == blob:
            return RenderResult(
                level=level.value,
                version=latest[0],
                event_id=latest[2],
                blob=blob,
                sources=sources,
                unchanged=True,
                markdown=markdown,
            )
        payload = DocumentRendered(
            level=level,
            version=1 if latest is None else latest[0] + 1,
            sources=sources,
            blob=blob,
        )
        event = project.events.make("document.rendered", payload, project.system_actor())
        project.record([event])
    return RenderResult(
        level=level.value,
        version=payload.version,
        event_id=event.id,
        blob=blob,
        sources=sources,
        unchanged=False,
        markdown=markdown,
    )


def renders(project: Project, level: DecisionLevel | None = None) -> list[dict[str, str | int]]:
    """The recorded renders, oldest first: level, version, event id and blob."""
    project.index.sync()
    sql = "SELECT level, version, event_id, blob FROM document_renders"
    params: dict[str, str] = {}
    if level is not None:
        sql += " WHERE level = :l"
        params["l"] = level.value
    with project.index.connect() as conn:
        rows = conn.execute(text(sql + " ORDER BY event_id"), params).all()
    return [
        {"level": str(r[0]), "version": int(r[1]), "event_id": str(r[2]), "blob": str(r[3])}
        for r in rows
    ]


__all__ = ["LEVEL_TITLES", "RenderResult", "render_level", "render_markdown", "renders"]

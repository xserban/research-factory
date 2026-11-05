"""Interpretations: serving targets, recording, review, listing and history (slice 3c, G3-A).

An interpretation says why an idea or a paper works, in at most 600 characters, bound to 1 to 5
verified sources. It is not evidence: nothing in this module is imported by an evidence service,
and its rows live in the layer's own tables (plan ruling A1).

Invariants:
- Scripts never judge: the platform serves targets and inputs, verifies sources and records what
  an agent or a human wrote; it never writes interpretation text, and no review state is typed.
- An agent records only against a task it holds, whose target is the interpretation's target; a
  human records without a task (`author = human`). The input the writer saw is stored as the
  event's `input_blob` (ruling A2).
- Every refusal writes nothing and reports all its issues together (fields `text`, `target`,
  `sources`, `sources[i].<attr>`, `supersedes`, `task_id`, `actor`), with fixed reasons that carry
  no document text.
- A target is a confirmed, unmerged idea or a corpus paper; a layer id is never a target.
- Proposer != evaluator: the session that wrote an interpretation never reviews or supersedes it
  (relay included), and a human review of a human-written one by its author is refused when more
  than one human has acted in the project (ruling A7).
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Sequence
from typing import Any, Literal

from pydantic import ConfigDict, Field, JsonValue
from sqlalchemy import text

from factory.clock import format_ts
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.intuition.labels import LAYER_CLASS, interpretation_visible, layer_label
from factory.intuition.validate import shape_issues
from factory.lineage.graph import GraphFilter
from factory.model.base import StrictModel
from factory.model.extraction import Scope
from factory.model.intuition import (
    Author,
    ConceptBrief,
    HistoryEntry,
    InterpretationHidden,
    InterpretationInput,
    InterpretationRecorded,
    InterpretationReviewed,
    ReviewState,
    SourceInput,
    StoredSource,
)
from factory.model.screening import Channel
from factory.model.task import INTUITION_TASK_KIND, TaskCompleted, TaskStatus
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.contributions import final_item
from factory.services.extraction import live_rows
from factory.services.ideas import idea_view, list_ideas, resolve_idea
from factory.services.intuition_sources import stale_sources, verify_sources
from factory.services.layer_view import layer_counts as layer_counts
from factory.services.layer_view import layer_graph as layer_graph
from factory.services.lineage import graph_node
from factory.services.search import works_by_ids
from factory.services.tasks import (
    TaskSpec,
    build_task_events,
    claim_next,
    get_task,
    require_holder,
    task_content,
)

INTUITION_KIND = INTUITION_TASK_KIND
MAX_SERVED_ITEMS = 60
"""Items served with one target, by work then item id; a target with more is served the first."""
PAGE = 500
LIVE_STATES = (ReviewState.UNREVIEWED.value, ReviewState.REVIEWED.value)
_LAYER_PREFIXES = ("int_", "cpt_", "cul_")

INSTRUCTIONS = (
    "Explain why this idea or paper works, in at most 600 characters, from the served items and "
    "their quotes. Cite 1 to 5 sources: a verbatim quote of a paper (work, conversion, anchor, "
    "quote) or a citation (a reference entry or a corpus work). Mark a source background when it "
    "is context, not support. An interpretation is not evidence. Write nothing you cannot "
    "ground; record the thought in the session instead."
)


class ServedItem(StrictModel):
    work_id: str
    extraction_id: str
    item_kind: str
    name: str | None
    statement: str | None
    anchor: str | None
    quote: str | None
    conversion_id: str


class IntuitionBatch(StrictModel):
    task_id: str
    instructions: str
    target: str
    target_kind: str
    target_name: str | None
    members: list[str]
    items: list[ServedItem]
    max_chars: int
    max_sources: int
    concepts: list[ConceptBrief] = Field(default_factory=list)
    """The visible background concepts (first page), so the writer can link and cite them."""
    concepts_total: int = 0
    truncated: bool = False
    """True when the target has more final items than `MAX_SERVED_ITEMS`; the first are served."""


class TargetSkip(StrictModel):
    target: str
    reason: str


class IntuitionNext(StrictModel):
    batch: IntuitionBatch | None
    skipped: list[TargetSkip]
    remaining: int


def _kind_of(target: str) -> str:
    return "idea" if target.startswith("ida_") else "paper"


# --- Targets ---


def target_issue(project: Project, target: str) -> ValidationIssue | None:
    """Why `target` cannot be interpreted, or None. An idea must be confirmed and not merged
    away; a paper must be a corpus node; a layer id is never a target."""
    project.index.sync()
    if target.startswith(_LAYER_PREFIXES):
        return ValidationIssue("target", "not-an-evidence-node")
    if target.startswith("ida_"):
        view = idea_view(project, target)
        if view is None:
            return ValidationIssue("target", "node-unknown")
        if view.state == "merged":
            return ValidationIssue("target", f"idea-merged:{resolve_idea(project, target)}")
        if view.state == "confirmed":
            return None
        return ValidationIssue(
            "target", "idea-not-confirmed" if view.state == "proposed" else f"idea-{view.state}"
        )
    node = graph_node(project, target, GraphFilter(include_inferred=True, include_stale=True))
    if node is None:
        return ValidationIssue("target", "node-unknown")
    if node.node_id != target:
        return ValidationIssue("target", f"node-merged:{node.node_id}")
    # A work only a G1 lookup stored counts as `corpus` in the graph; a target must be a work of
    # the corpus proper (a non-probe query found it), as `list_works` has it.
    if node.scope != "corpus" or not works_by_ids(project, [target]):
        return ValidationIssue("target", "node-external")
    return None


def _skip_reason(issue: ValidationIssue) -> str:
    reason = issue.reason
    if reason.startswith("idea-merged") or reason.startswith("node-merged"):
        return "merged"
    if reason == "node-external":
        return "external"
    if reason in ("node-unknown", "not-an-evidence-node"):
        return "unknown"
    return "not-confirmed"


def _has_live_interpretation(project: Project, target: str) -> bool:
    with project.index.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT 1 FROM interpretations WHERE target = :t "
                    f"AND review_state IN {LIVE_STATES!r} LIMIT 1"
                ),
                {"t": target},
            ).first()
            is not None
        )


def _open_task_targets(project: Project) -> set[str]:
    """Targets named by an intuition task that is not completed (open, claimed or lapsed)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT j.value FROM tasks t, json_each(t.refs) j "
                "WHERE t.kind = :k AND t.status != :done"
            ),
            {"k": INTUITION_KIND, "done": TaskStatus.COMPLETED.value},
        ).all()
    return {str(r[0]) for r in rows}


def _items_of(project: Project, members: Sequence[str]) -> tuple[list[ServedItem], bool]:
    """The live, non-stale final contribution items of `members` (at most `MAX_SERVED_ITEMS`),
    from `final_item` so a resolved field shows its final value, and whether more were left out."""
    served: dict[str, ServedItem] = {}
    truncated = False
    with entering():
        for work in sorted(members):
            for row in live_rows(project, work_id=work, scope=Scope.CONTRIBUTION):
                item = final_item(project, row.extraction_id)
                if item is None or not item.live or item.stale or item.extraction_id in served:
                    continue
                if len(served) >= MAX_SERVED_ITEMS:
                    truncated = True
                    break
                served[item.extraction_id] = ServedItem(
                    work_id=item.work_id,
                    extraction_id=item.extraction_id,
                    item_kind=item.item_kind,
                    name=item.name,
                    statement=item.statement,
                    anchor=item.anchor,
                    quote=item.quote,
                    conversion_id=item.conversion_id,
                )
            if truncated:
                break
    return sorted(served.values(), key=lambda i: (i.work_id, i.extraction_id)), truncated


def _content(project: Project, target: str) -> dict[str, JsonValue]:
    if target.startswith("ida_"):
        view = idea_view(project, target)
        assert view is not None
        members = list(view.effective_members)
        name: str | None = view.name
    else:
        members = [target]
        name = None
    items, truncated = _items_of(project, members)
    return {
        "target": target,
        "target_kind": _kind_of(target),
        "target_name": name,
        "members": list(members),
        "items": [i.model_dump(mode="json") for i in items],
        "truncated": truncated,
    }


def _with_concepts(project: Project, batch: IntuitionBatch) -> IntuitionBatch:
    # concepts imports this module (target_issue), so it is imported at call time
    from factory.services.concepts import visible_concept_count, visible_concepts

    return batch.model_copy(
        update={
            "concepts": visible_concepts(project),
            "concepts_total": visible_concept_count(project),
        }
    )


def _batch(task_id: str, content: dict[str, Any]) -> IntuitionBatch:
    return IntuitionBatch(
        task_id=task_id,
        instructions=INSTRUCTIONS,
        target=content["target"],
        target_kind=content["target_kind"],
        target_name=content["target_name"],
        members=list(content["members"]),
        items=[ServedItem.model_validate(i) for i in content["items"]],
        max_chars=600,
        max_sources=5,
        truncated=bool(content.get("truncated", False)),
    )


def _default_targets(project: Project) -> Iterable[str]:
    offset = 0
    while True:
        page = list_ideas(project, limit=PAGE, offset=offset)
        for view in page:
            yield view.idea_id
        if len(page) < PAGE:
            return
        offset += PAGE


def _free_count(project: Project, occupied: set[str]) -> int:
    """Confirmed, unmerged ideas with no live interpretation and no open task."""
    with project.index.connect() as conn:
        total = conn.execute(
            text(
                "SELECT COUNT(*) FROM ideas i WHERE i.superseded_by IS NULL "
                "AND i.merged_into IS NULL AND i.decision = 'confirm' AND NOT EXISTS "
                "(SELECT 1 FROM interpretations x WHERE x.target = i.idea_id "
                f"AND x.review_state IN {LIVE_STATES!r})"
            )
        ).scalar_one()
        busy = 0
        if occupied:
            busy = conn.execute(
                text(
                    "SELECT COUNT(*) FROM ideas i WHERE i.superseded_by IS NULL "
                    "AND i.merged_into IS NULL AND i.decision = 'confirm' "
                    "AND i.idea_id IN (SELECT value FROM json_each(:o)) AND NOT EXISTS "
                    "(SELECT 1 FROM interpretations x WHERE x.target = i.idea_id "
                    f"AND x.review_state IN {LIVE_STATES!r})"
                ),
                {"o": _json_list(occupied)},
            ).scalar_one()
    return int(total) - int(busy)


def _json_list(values: set[str]) -> str:
    return json.dumps(sorted(values))


def intuition_next(
    project: Project, actor: Actor, *, targets: Sequence[str] | None = None
) -> IntuitionNext:
    """Serve the next target to interpret as a task claimed by `actor` (agents only).

    Without `targets`: the confirmed ideas, in id order (ruling A3); with them, those named, in
    the order given (papers only when named). A target that has a live interpretation, is held by
    an open task, or is not eligible is skipped (the skips of named targets are reported). A task
    this session already holds, or one left open or lapsed, is served again before a new one is
    made."""
    if actor.kind != "agent":
        raise FactoryValidationError([ValidationIssue("actor", "only an agent is served a task")])
    wanted = None if targets is None else list(dict.fromkeys(targets))
    with project.index.exclusive():
        project.index.sync()
        skipped: list[TargetSkip] = []
        if wanted is not None:
            for t in wanted:
                issue = target_issue(project, t)
                if issue is not None:
                    skipped.append(TargetSkip(target=t, reason=_skip_reason(issue)))

        def acceptable(content: Any) -> bool:
            target = str(content["target"]) if isinstance(content, dict) else ""
            if wanted is not None and target not in wanted:
                return False
            return target_issue(project, target) is None and not _has_live_interpretation(
                project, target
            )

        claimed = claim_next(project, actor, INTUITION_KIND, accept=acceptable)
        if claimed is None:
            claimed = _own_live_claim(project, actor, acceptable)
        if claimed is not None:
            content = task_content(project, claimed)
            assert isinstance(content, dict)
            return IntuitionNext(
                batch=_with_concepts(project, _batch(claimed.task_id, content)),
                skipped=_named_only(skipped, wanted),
                remaining=_remaining(project, wanted, skipped, str(content["target"])),
            )
        occupied = _open_task_targets(project)
        candidates = wanted if wanted is not None else _default_targets(project)
        for target in candidates:
            if any(s.target == target for s in skipped):
                continue
            if _has_live_interpretation(project, target):
                skipped.append(TargetSkip(target=target, reason="has-live-interpretation"))
                continue
            if target in occupied:
                skipped.append(TargetSkip(target=target, reason="task-open"))
                continue
            content = _content(project, target)
            events, result = build_task_events(
                project, actor, [TaskSpec(INTUITION_KIND, content, refs=(target,))]
            )
            project.record(events)
            [task_id] = result.written
            task = claim_next(project, actor, INTUITION_KIND, task_ids={task_id})
            if task is None:
                skipped.append(TargetSkip(target=target, reason="task-open"))
                continue
            return IntuitionNext(
                batch=_with_concepts(project, _batch(task_id, content)),
                skipped=_named_only(skipped, wanted),
                remaining=_remaining(project, wanted, skipped, target),
            )
        return IntuitionNext(batch=None, skipped=_named_only(skipped, wanted), remaining=0)


def _named_only(skipped: list[TargetSkip], wanted: list[str] | None) -> list[TargetSkip]:
    """Skips are reported for named targets; the default sweep reports none (it is a scan)."""
    return skipped if wanted is not None else []


def _own_live_claim(project: Project, actor: Actor, accept: Any) -> Any:
    """A task of this kind this session holds with a live lease, served again."""
    now = format_ts(project.clock.now())
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT task_id, content_blob FROM tasks WHERE kind = :k AND status = 'claimed' "
                "AND claim_session = :s AND lease_until > :now ORDER BY task_id"
            ),
            {"k": INTUITION_KIND, "s": actor.session, "now": now},
        ).all()
    for task_id, blob in rows:
        if accept(project.blobs.get_json(str(blob))):
            return get_task(project, str(task_id))
    return None


def _remaining(
    project: Project, wanted: list[str] | None, skipped: list[TargetSkip], served: str
) -> int:
    """Targets still to serve after `served` (whose task is open): the free confirmed ideas, or
    the named targets that are eligible, unoccupied and without a live interpretation."""
    occupied = _open_task_targets(project)
    if wanted is None:
        return _free_count(project, occupied)
    gone = {s.target for s in skipped}
    return sum(
        1
        for t in wanted
        if t != served
        and t not in gone
        and t not in occupied
        and not _has_live_interpretation(project, t)
    )


# --- Recording ---


def _row(project: Project, interpretation_id: str) -> Any | None:
    with project.index.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT interpretation_id, target, target_kind, author, author_user, "
                    "writer_session, review_state, superseded_by FROM interpretations "
                    "WHERE interpretation_id = :i"
                ),
                {"i": interpretation_id},
            )
            .mappings()
            .first()
        )


def _supersedes_issues(
    project: Project, actor: Actor, entry: InterpretationInput
) -> list[ValidationIssue]:
    if entry.supersedes is None:
        return []
    prior = _row(project, entry.supersedes)
    if prior is None:
        return [ValidationIssue("supersedes", "interpretation-unknown")]
    if prior["superseded_by"] is not None:
        return [ValidationIssue("supersedes", "interpretation-superseded")]
    if prior["target"] != entry.target:
        return [ValidationIssue("supersedes", "target-differs")]
    if actor.kind == "agent" and (
        prior["author"] != Author.AGENT.value
        or prior["review_state"] not in (ReviewState.UNREVIEWED.value, ReviewState.WRONG.value)
    ):
        return [ValidationIssue("supersedes", "human-act")]
    if prior["author"] == Author.AGENT.value and prior["writer_session"] == actor.session:
        return [ValidationIssue("supersedes", "writer-session")]
    return []


def record_interpretation(
    project: Project, actor: Actor, entry: InterpretationInput, *, task_id: str | None = None
) -> str:
    """Record an interpretation and return its `int_` id. Refused, with nothing written and every
    issue reported, for a wrong actor or task (`actor`, `task_id`), a text or sources outside the
    bounds (`text`, `sources`), an ineligible target (`target`), an unverifiable source
    (`sources[i].<attr>`) and a `supersedes` that the actor may not name (`supersedes`, ruling A6).
    An agent's call also completes its task, in the same append."""
    if actor.kind not in ("agent", "human"):
        raise FactoryValidationError(
            [ValidationIssue("actor", "only an agent or a human records an interpretation")]
        )
    with project.index.exclusive():
        project.index.sync()
        issues = shape_issues(entry)
        target_problem = target_issue(project, entry.target)
        if target_problem is not None:
            issues.append(target_problem)
        issues += _supersedes_issues(project, actor, entry)
        task_blob: str | None = None
        if actor.kind == "agent":
            issues += _task_issues(project, actor, entry, task_id)
            task = get_task(project, task_id) if task_id else None
            task_blob = None if task is None else task.content_blob
        elif task_id is not None:
            issues.append(ValidationIssue("task_id", "a human records without a task"))
        verdict = verify_sources(project, entry.sources)
        issues += verdict.issues
        if issues:
            raise FactoryValidationError(issues)
        interpretation_id = f"int_{project.ids.ulid()}"
        call = entry.model_dump(mode="json")
        payload = InterpretationRecorded(
            interpretation_id=interpretation_id,
            target=entry.target,
            target_kind="idea" if entry.target.startswith("ida_") else "paper",
            text=entry.text,
            sources=verdict.stored,
            author=Author(actor.kind),
            supersedes=entry.supersedes,
            task_id=task_id,
        )
        refs = [interpretation_id, entry.target]
        if entry.supersedes is not None:
            refs.append(entry.supersedes)
        if task_id is not None:
            refs.append(task_id)
        input_blob = project.blobs.put_json(
            {"task_input": task_blob, "call": call} if task_blob is not None else {"call": call}
        )
        events: list[Event] = [
            project.events.make(
                "interpretation.recorded", payload, actor, refs=refs, input_blob=input_blob
            )
        ]
        if task_id is not None and task_blob is not None:
            events.append(
                project.events.make(
                    "task.completed",
                    TaskCompleted(task_id=task_id, result_refs=(interpretation_id,)),
                    actor,
                    refs=(task_id,),
                    input_blob=task_blob,
                )
            )
        project.record(events)
        return interpretation_id


def _task_issues(
    project: Project, actor: Actor, entry: InterpretationInput, task_id: str | None
) -> list[ValidationIssue]:
    if task_id is None:
        return [ValidationIssue("task_id", "an agent records against a task it holds")]
    try:
        task = require_holder(project, actor, task_id)
    except FactoryValidationError as exc:
        return exc.issues
    if task.kind != INTUITION_KIND:
        return [ValidationIssue("task_id", "not an intuition task")]
    content = task_content(project, task)
    if not isinstance(content, dict) or content.get("target") != entry.target:
        return [ValidationIssue("task_id", "the task is for another target")]
    return []


# --- Review ---


def _human_users(project: Project) -> int:
    """How many distinct human users have acted in the project (a count in SQL)."""
    with project.index.connect() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(DISTINCT user) FROM events WHERE actor_kind = 'human'")
            ).scalar_one()
        )


def review_interpretation(
    project: Project,
    actor: Actor,
    interpretation_id: str,
    state: Literal["reviewed", "wrong"],
    note: str,
    channel: Channel,
) -> str:
    """Record a human review (`reviewed` or `wrong`) and return its event id; a later review
    supersedes the earlier. Refused, with nothing written, for a non-human actor or the session
    that wrote an agent-written interpretation, relay included (`actor`), an
    MCP channel (`channel`: no tool relays a review), an unknown or superseded interpretation
    (`interpretation_id`), a `wrong` without a note (`note`), and the author of a human-written
    interpretation when more than one human has acted in the project (`reviewer`, ruling A7);
    with a single human the review is recorded `self_reviewed`."""
    if actor.kind != "human":
        raise FactoryValidationError([ValidationIssue("actor", "only a human reviews")])
    with project.index.exclusive():
        project.index.sync()
        row = _row(project, interpretation_id)
        if row is None:
            raise FactoryValidationError(
                [ValidationIssue("interpretation_id", "unknown-interpretation")]
            )
        issues: list[ValidationIssue] = []
        if row["review_state"] == ReviewState.SUPERSEDED.value:
            issues.append(ValidationIssue("interpretation_id", "superseded"))
        if row["author"] == Author.AGENT.value and row["writer_session"] == actor.session:
            issues.append(
                ValidationIssue(
                    "actor", "the session that wrote an interpretation cannot review it"
                )
            )
        if channel is Channel.MCP:
            issues.append(ValidationIssue("channel", "no MCP tool reviews; use the command line"))
        if state == "wrong" and not note.strip():
            issues.append(ValidationIssue("note", "state why the interpretation is wrong"))
        self_reviewed = row["author"] == Author.HUMAN.value and row["author_user"] == actor.user
        if self_reviewed and _human_users(project) > 1:
            issues.append(ValidationIssue("reviewer", "another human reviews this interpretation"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "interpretation.reviewed",
            InterpretationReviewed(
                interpretation_id=interpretation_id,
                state=state,
                note=note,
                self_reviewed=self_reviewed,
                channel=channel,
            ),
            actor,
            refs=[interpretation_id],
        )
        project.record([event])
        return event.id


def supersede_interpretation(
    project: Project,
    actor: Actor,
    interpretation_id: str,
    text_: str,
    sources: Sequence[SourceInput],
) -> str:
    """A human writes a replacement for any live interpretation, of the same target, naming the
    earlier one, which becomes `superseded`; returns the new id. Refusals as
    `record_interpretation`, and `actor` for a non-human, `interpretation_id` for an unknown one."""
    if actor.kind != "human":
        raise FactoryValidationError([ValidationIssue("actor", "only a human supersedes")])
    project.index.sync()
    prior = _row(project, interpretation_id)
    if prior is None:
        raise FactoryValidationError(
            [ValidationIssue("interpretation_id", "unknown-interpretation")]
        )
    entry = InterpretationInput(
        target=str(prior["target"]),
        text=text_,
        sources=tuple(sources),
        supersedes=interpretation_id,
    )
    return record_interpretation(project, actor, entry)


# --- Reads ---


class InterpretationView(StrictModel):
    """An interpretation as the reviewer sees it, labelled; `source_stale` lists the superseded
    documents of its quote sources (never a change of state). Serialise with `by_alias=True` for
    the key `class`."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    interpretation_id: str
    class_: str = Field(serialization_alias="class")
    label: str
    target: str
    target_kind: str
    text: str
    sources: list[StoredSource]
    author: str
    writer: str
    review_state: str
    self_reviewed: bool
    source_stale: list[str]
    input_blob: str | None


class InterpretationList(StrictModel):
    items: list[InterpretationView]
    hidden: InterpretationHidden
    next_cursor: str | None


LIST_PAGE = 50
_VIEW_SQL = (
    "SELECT i.interpretation_id, i.target, i.target_kind, i.text, i.author, i.review_state, "
    "i.self_reviewed, i.input_blob, e.actor_id, e.model FROM interpretations i "
    "JOIN events e ON e.id = i.event_id "
)


def _writer(actor_id: str, model: str | None) -> str:
    return actor_id if model is None else f"{actor_id} ({model})"


def _visible_states() -> list[ReviewState]:
    return [s for s in ReviewState if interpretation_visible(s)]


def list_interpretations(
    project: Project,
    *,
    target: str | None = None,
    states: Collection[ReviewState] | None = None,
    cursor: str | None = None,
    limit: int = LIST_PAGE,
    interpretation_id: str | None = None,
) -> InterpretationList:
    """One page of interpretations by id, labelled. Default states are the visible ones
    (`unreviewed`, `reviewed`; ruling 7); the hidden counts (`wrong`, `superseded`) are always
    reported, over the same target filter. `next_cursor` continues the listing."""
    wanted = [s.value for s in (states if states is not None else _visible_states())]
    project.index.sync()
    where = "i.review_state IN (SELECT value FROM json_each(:states))"
    params: dict[str, Any] = {"states": json.dumps(sorted(wanted)), "n": limit + 1}
    hidden_where = "review_state IN ('wrong', 'superseded')"
    hidden_params: dict[str, Any] = {}
    if target is not None:
        where += " AND i.target = :t"
        params["t"] = target
        hidden_where += " AND target = :t"
        hidden_params["t"] = target
    if cursor is not None:
        where += " AND i.interpretation_id > :c"
        params["c"] = cursor
    if interpretation_id is not None:  # one item, whatever its state (the caller sets `states`)
        where += " AND i.interpretation_id = :iid"
        params["iid"] = interpretation_id
    with project.index.connect() as conn:
        found = (
            conn.execute(
                text(f"{_VIEW_SQL} WHERE {where} ORDER BY i.interpretation_id LIMIT :n"), params
            )
            .mappings()
            .all()
        )
        counts: dict[Any, Any] = dict(
            conn.execute(
                text(
                    "SELECT review_state, COUNT(*) FROM interpretations "
                    f"WHERE {hidden_where} GROUP BY review_state"
                ),
                hidden_params,
            ).all()
        )
        page = found[:limit]
        ids = [str(r["interpretation_id"]) for r in page]
        sources = _sources_of(conn, ids)
    stale = stale_sources(project, only=ids)
    items = [
        InterpretationView(
            interpretation_id=str(r["interpretation_id"]),
            class_=LAYER_CLASS,
            label=layer_label(str(r["review_state"])),
            target=str(r["target"]),
            target_kind=str(r["target_kind"]),
            text=str(r["text"]),
            sources=sources.get(str(r["interpretation_id"]), []),
            author=str(r["author"]),
            writer=_writer(str(r["actor_id"]), r["model"]),
            review_state=str(r["review_state"]),
            self_reviewed=bool(r["self_reviewed"]),
            source_stale=list(stale.get(str(r["interpretation_id"]), ())),
            input_blob=r["input_blob"],
        )
        for r in page
    ]
    return InterpretationList(
        items=items,
        hidden=InterpretationHidden(
            wrong=int(counts.get("wrong", 0)), superseded=int(counts.get("superseded", 0))
        ),
        next_cursor=ids[-1] if len(found) > limit else None,
    )


def _sources_of(conn: Any, ids: list[str]) -> dict[str, list[StoredSource]]:
    if not ids:
        return {}
    rows = (
        conn.execute(
            text(
                "SELECT interpretation_id, role, kind, work_id, conversion_id, document_id, "
                "anchor, quote, reference, link_state, resolved_work "
                "FROM interpretation_sources WHERE interpretation_id IN "
                "(SELECT value FROM json_each(:ids)) ORDER BY interpretation_id, position"
            ),
            {"ids": json.dumps(ids)},
        )
        .mappings()
        .all()
    )
    out: dict[str, list[StoredSource]] = {}
    for r in rows:
        out.setdefault(str(r["interpretation_id"]), []).append(
            StoredSource(
                kind=r["kind"],
                role=r["role"],
                work_id=r["work_id"],
                conversion_id=r["conversion_id"],
                anchor=r["anchor"],
                quote=r["quote"],
                reference=r["reference"],
                document_id=r["document_id"],
                link_state=r["link_state"],
                resolved_work=r["resolved_work"],
            )
        )
    return out


def interpretation_history(project: Project, interpretation_id: str) -> list[HistoryEntry]:
    """Every step of an interpretation in event order: its recording, each review (`reviewed`
    or `wrong`, with note and self-review flag) and the recording that superseded it. Empty for
    an unknown id."""
    project.index.sync()
    with project.index.connect() as conn:
        head = conn.execute(
            text(
                "SELECT i.event_id, e.actor_id, i.superseded_by FROM interpretations i "
                "JOIN events e ON e.id = i.event_id WHERE i.interpretation_id = :i"
            ),
            {"i": interpretation_id},
        ).first()
        if head is None:
            return []
        reviews = conn.execute(
            text(
                "SELECT r.event_id, r.state, r.note, r.self_reviewed, e.actor_id, r.folded "
                "FROM interpretation_reviews r JOIN events e ON e.id = r.event_id "
                "WHERE r.interpretation_id = :i ORDER BY r.event_id"
            ),
            {"i": interpretation_id},
        ).all()
        successor = (
            None
            if head[2] is None
            else conn.execute(
                text(
                    "SELECT i.event_id, e.actor_id FROM interpretations i "
                    "JOIN events e ON e.id = i.event_id WHERE i.interpretation_id = :i"
                ),
                {"i": str(head[2])},
            ).first()
        )
    history = [
        HistoryEntry(
            event_id=str(head[0]),
            kind="recorded",
            state=None,
            actor=str(head[1]),
            note="",
            self_reviewed=False,
        )
    ]
    history += [
        HistoryEntry(
            event_id=str(r[0]),
            kind="reviewed",
            state=str(r[1]),
            actor=str(r[4]),
            note=str(r[2]),
            self_reviewed=bool(r[3]),
            folded=bool(r[5]),
        )
        for r in reviews
    ]
    if successor is not None:
        history.append(
            HistoryEntry(
                event_id=str(successor[0]),
                kind="superseded-by",
                state=ReviewState.SUPERSEDED.value,
                actor=str(successor[1]),
                note="",
                self_reviewed=False,
            )
        )
    return sorted(history, key=lambda h: h.event_id)


def review_counts(project: Project) -> dict[ReviewState, int]:
    """Interpretations by live review state, counted in SQL (every state present)."""
    project.index.sync()
    with project.index.connect() as conn:
        found: dict[Any, Any] = dict(
            conn.execute(
                text("SELECT review_state, COUNT(*) FROM interpretations GROUP BY review_state")
            ).all()
        )
    return {s: int(found.get(s.value, 0)) for s in ReviewState}

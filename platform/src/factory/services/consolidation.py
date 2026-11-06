"""Consolidation: deterministic candidate clusters, agent proposals and human merge decisions
(slice 3d rulings 14 and 15, plan Regions-C).

The platform computes candidate synonym clusters per kind (label keys, ideas, concepts) with
`factory.consolidation`; an agent proposes a merge, keep or split for a cluster it is served as a
task; the researcher decides. Merges reuse the existing reversible events: `label.merged`,
`idea.merged` and `concept.merged`, each carrying the proposal it carries out.

Invariants:
- A pass is a recorded set of clusters (a blob) and the constants that produced them; one pass is
  open at a time. Its clusters become `consolidate` tasks in the same append.
- Only a human decides (gate `consolidation.decide`). A decision and the merge events it produced
  are recorded in one append, so a decision never exists without its merges or the reverse. A
  cluster is decided once; merges are undone by the kind's own unmerge.
- A pass completes when every cluster has a decision (`merge`, `keep`, `split`, `skip`); then the
  due counters (`consolidation_due`) start again from zero.
- The cluster an agent reads names members, aliases and signals, never a score, a threshold or
  document text.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import JsonValue
from sqlalchemy import text

from factory.consolidation.clusters import CLUSTER_MAX, clusters, merge_pairs
from factory.consolidation.signals import (
    ACRONYM_MIN_WORDS,
    BLOCK_MAX,
    MIN_SHARED_TRIGRAMS,
    POSTING_MAX,
    SYNONYM_OVERLAP,
    SYNONYM_RATIO,
    Item,
    Pair,
    acronym_pairs,
    inverted_index,
    overlap_pairs,
    string_pairs,
)
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.cards import QuoteBasis
from factory.model.labels import (
    ConsolidationDecided,
    ConsolidationPassCompleted,
    ConsolidationPassStarted,
    ConsolidationProposed,
)
from factory.model.task import CONSOLIDATE_TASK_KIND
from factory.regions.concept_use import concept_users
from factory.services.budgets import require_for, task_unit
from factory.services.concepts import build_concept_merge, merge_group_issues, visible_concepts
from factory.services.consolidation_due import (
    CONSOLIDATION_DUE_LABELS,
    CONSOLIDATION_DUE_NODES,
    DueState,
    consolidation_due,
)
from factory.services.context import Project
from factory.services.gates import gate_issues
from factory.services.ideas import build_idea_merge, list_ideas
from factory.services.labels import build_label_merge, quote_issues
from factory.services.tasks import (
    TaskSpec,
    build_task_events,
    claim_next,
    complete_task,
    require_holder,
    task_content,
)

KINDS = ("label", "idea", "concept")
Decision = Literal["merge", "keep", "split", "skip"]
Action = Literal["merge", "keep", "split"]
_PAGE = 500

CONSTANTS: dict[str, float | int] = {
    "SYNONYM_RATIO": SYNONYM_RATIO,
    "SYNONYM_OVERLAP": SYNONYM_OVERLAP,
    "ACRONYM_MIN_WORDS": ACRONYM_MIN_WORDS,
    "CLUSTER_MAX": CLUSTER_MAX,
    "BLOCK_MAX": BLOCK_MAX,
    "POSTING_MAX": POSTING_MAX,
    "MIN_SHARED_TRIGRAMS": MIN_SHARED_TRIGRAMS,
}


def _refuse(*issues: ValidationIssue) -> FactoryValidationError:
    return FactoryValidationError(list(issues))


# --- Candidates ---


@dataclass(frozen=True)
class Cluster:
    kind: str
    members: tuple[str, ...]
    pairs: tuple[Pair, ...]


def _label_items(project: Project, *, agent: bool = False) -> list[Item]:
    """The label items. For an agent (`agent=True`) every application from an import's tag is
    left out, whatever the record's part, and a key only a tag gives is not an item: the tag is
    withheld, never the work (decision 43)."""
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT live_key, key, target_type, target FROM labels "
                "WHERE withdrawn = 0 AND COALESCE(decision, '') != 'reject' "
                "AND (:a = 0 OR origin != 'import-tag') "
                "ORDER BY live_key, key, target_type, target"
            ),
            {"a": int(agent)},
        ).all()
    names: dict[str, set[str]] = {}
    targets: dict[str, set[str]] = {}
    for live, key, kind, target in found:
        names.setdefault(str(live), set()).add(str(key))
        targets.setdefault(str(live), set()).add(f"{kind}:{target}")
    return [
        Item("label", live, tuple(sorted(names[live])), frozenset(targets[live]))
        for live in sorted(names)
        if not agent or live in names[live]
    ]


def _idea_items(project: Project) -> list[Item]:
    items: list[Item] = []
    offset = 0
    while True:
        page = list_ideas(project, limit=_PAGE, offset=offset)
        items += [Item("idea", v.idea_id, (v.name,), frozenset(v.effective_members)) for v in page]
        if len(page) < _PAGE:
            return items
        offset += _PAGE


def _concept_items(project: Project) -> list[Item]:
    items: list[Item] = []
    cursor: str | None = None
    with project.index.connect() as conn:
        while True:
            page = visible_concepts(project, limit=_PAGE, cursor=cursor)
            for brief in page:
                users = frozenset(concept_users(conn, brief.concept_id))
                items.append(Item("concept", brief.concept_id, (brief.name, *brief.aliases), users))
            if len(page) < _PAGE:
                return items
            cursor = page[-1].concept_id


def _clusters_of(items: Sequence[Item]) -> list[Cluster]:
    pairs = merge_pairs(
        [*string_pairs(items), *acronym_pairs(items), *overlap_pairs(items, inverted_index(items))]
    )
    found: list[Cluster] = []
    for members in clusters(pairs):
        inside = set(members)
        found.append(
            Cluster(
                items[0].kind,
                members,
                tuple(p for p in pairs if p.a in inside and p.b in inside),
            )
        )
    return found


def candidate_clusters(project: Project) -> list[Cluster]:
    """The candidate synonym clusters of the project now, ordered by kind (label, idea, concept)
    and smallest member. Deterministic; reads the index only."""
    project.index.sync()
    out: list[Cluster] = []
    for build in (_label_items, _idea_items, _concept_items):
        items = build(project)
        if items:
            out += _clusters_of(items)
    return out


# --- Passes ---


def open_pass_id(project: Project) -> str | None:
    """The id of the open pass (started, not completed), or None."""
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT pass_id FROM consolidation_passes WHERE completed_event IS NULL "
                "ORDER BY pass_id LIMIT 1"
            )
        ).scalar_one_or_none()
    return None if found is None else str(found)


def _members_brief(project: Project, cluster: Cluster) -> list[dict[str, Any]]:
    """Names, aliases and counts of the members: no document text, no score. Label members come
    from the agent-visible items (no import tag), so a task carries no tag key."""
    briefs: list[dict[str, Any]] = []
    if cluster.kind == "label":
        with project.index.connect() as conn:
            for live in cluster.members:
                keys = [
                    str(r[0])
                    for r in conn.execute(
                        text(
                            "SELECT DISTINCT key FROM labels WHERE live_key = :k "
                            "AND withdrawn = 0 AND origin != 'import-tag' "
                            "AND COALESCE(decision, '') != 'reject' ORDER BY key"
                        ),
                        {"k": live},
                    )
                ]
                briefs.append({"id": live, "name": live, "aliases": [k for k in keys if k != live]})
        return briefs
    if cluster.kind == "idea":
        views = {v.idea_id: v for v in list_ideas(project, limit=10_000)}
        return [
            {
                "id": m,
                "name": views[m].name,
                "aliases": [],
                "members": len(views[m].effective_members),
            }
            for m in cluster.members
        ]
    by_id = {c.concept_id: c for c in visible_concepts(project, limit=10_000)}
    return [
        {"id": m, "name": by_id[m].name, "aliases": list(by_id[m].aliases)} for m in cluster.members
    ]


def _agent_label_pairs(project: Project) -> list[Pair]:
    """The candidate pairs among labels as an agent may see them (no import-tag application)."""
    items = _label_items(project, agent=True)
    return merge_pairs(
        [*string_pairs(items), *acronym_pairs(items), *overlap_pairs(items, inverted_index(items))]
    )


def _agent_label_view(cluster: Cluster, agent_pairs: Sequence[Pair]) -> Cluster | None:
    """The part of a label cluster an agent is served: the members that exist without a tag and
    the pairs among them; None when fewer than two members or no pair is left."""
    visible = {m for p in agent_pairs for m in (p.a, p.b)} & set(cluster.members)
    pairs = tuple(p for p in agent_pairs if p.a in visible and p.b in visible)
    if len(visible) < 2 or not pairs:
        return None
    return Cluster("label", tuple(sorted(visible)), pairs)


def start_pass(project: Project, actor: Actor) -> str:
    """Compute the candidate clusters, record the pass and one `consolidate` task per cluster in
    one append, and return the pass id (`cns_...`). Human only; refused (fields `actor`,
    `pass_id`: `pass-open`) while another pass is open."""
    with project.index.exclusive():
        project.index.sync()
        issues = gate_issues(project, actor, "consolidation.decide")
        if actor.kind != "human":
            issues = issues or [ValidationIssue("actor", "only a human starts a pass")]
        if open_pass_id(project) is not None:
            issues.append(ValidationIssue("pass_id", "pass-open"))
        if issues:
            raise _refuse(*issues)
        found = candidate_clusters(project)
        pass_id = f"cns_{project.ids.ulid()}"
        listing = [
            {
                "index": n,
                "kind": c.kind,
                "members": list(c.members),
                "pairs": [
                    {"a": p.a, "b": p.b, "signals": list(p.signals), "score": round(p.score, 4)}
                    for p in c.pairs
                ],
            }
            for n, c in enumerate(found)
        ]
        blob = project.blobs.put_json(cast(JsonValue, listing))
        counts = {k: sum(1 for c in found if c.kind == k) for k in KINDS}
        agent_pairs = _agent_label_pairs(project)
        specs = []
        for n, c in enumerate(found):
            view = c if c.kind != "label" else _agent_label_view(c, agent_pairs)
            if view is None:
                continue  # nothing of the cluster is visible to an agent without a tag key
            specs.append(
                TaskSpec(
                    CONSOLIDATE_TASK_KIND,
                    cast(
                        JsonValue,
                        {
                            "pass_id": pass_id,
                            "cluster_index": n,
                            "kind": view.kind,
                            "members": _members_brief(project, view),
                            "signals": [
                                {"a": p.a, "b": p.b, "signals": list(p.signals)} for p in view.pairs
                            ],
                        },
                    ),
                    refs=(pass_id,),
                )
            )
        tasks, _ = build_task_events(project, actor, specs)
        started = project.events.make(
            "consolidation.pass_started",
            ConsolidationPassStarted(
                pass_id=pass_id, clusters_blob=blob, constants=dict(CONSTANTS), counts=counts
            ),
            actor,
            refs=[pass_id],
        )
        project.record([started, *tasks])
        return pass_id


class ClusterRow(StrictModel):
    index: int
    kind: str
    members: tuple[str, ...]
    signals: tuple[tuple[str, str, tuple[str, ...]], ...]
    decision: str | None
    proposal_ids: list[str]


def _pass_row(project: Project, pass_id: str) -> Any | None:
    with project.index.connect() as conn:
        return conn.execute(
            text(
                "SELECT pass_id, clusters_blob, completed_event FROM consolidation_passes "
                "WHERE pass_id = :p"
            ),
            {"p": pass_id},
        ).first()


def _pass_clusters(project: Project, row: Any) -> list[dict[str, Any]]:
    listing = project.blobs.get_json(str(row[1]))
    assert isinstance(listing, list)
    return [c for c in listing if isinstance(c, dict)]


def list_clusters(project: Project, pass_id: str) -> list[ClusterRow]:
    """The clusters of a pass with the decision (if any) and the proposals recorded for each."""
    project.index.sync()
    row = _pass_row(project, pass_id)
    if row is None:
        raise _refuse(ValidationIssue("pass_id", "pass-unknown"))
    with project.index.connect() as conn:
        decisions = {
            int(i): str(d)
            for i, d in conn.execute(
                text(
                    "SELECT cluster_index, decision FROM consolidation_decisions "
                    "WHERE pass_id = :p ORDER BY event_id"
                ),
                {"p": pass_id},
            )
        }
        proposals: dict[int, list[str]] = {}
        for i, pid in conn.execute(
            text(
                "SELECT cluster_index, proposal_id FROM consolidation_proposals "
                "WHERE pass_id = :p ORDER BY event_id"
            ),
            {"p": pass_id},
        ):
            proposals.setdefault(int(i), []).append(str(pid))
    return [
        ClusterRow(
            index=int(c["index"]),
            kind=str(c["kind"]),
            members=tuple(c["members"]),
            signals=tuple((p["a"], p["b"], tuple(p["signals"])) for p in c["pairs"]),
            decision=decisions.get(int(c["index"])),
            proposal_ids=proposals.get(int(c["index"]), []),
        )
        for c in _pass_clusters(project, row)
    ]


# --- Proposals ---


class ClusterTask(StrictModel):
    """One cluster as an agent is served it."""

    task_id: str
    pass_id: str
    cluster_index: int
    kind: str
    members: list[dict[str, Any]]
    signals: list[dict[str, Any]]


def _still_open(project: Project, content: JsonValue) -> bool:
    """Whether the cluster a task serves is undecided in a pass not yet completed."""
    assert isinstance(content, dict)
    pass_id, index = str(content["pass_id"]), int(str(content["cluster_index"]))
    row = _pass_row(project, pass_id)
    if row is None or row[2] is not None:
        return False
    with project.index.connect() as conn:
        decided = conn.execute(
            text("SELECT 1 FROM consolidation_decisions WHERE pass_id = :p AND cluster_index = :i"),
            {"p": pass_id, "i": index},
        ).first()
    return decided is None


def consolidation_next(project: Project, actor: Actor) -> ClusterTask | None:
    """Claim the next open cluster task (a lease, 00-system section 8), or None."""
    with project.writing():
        require_for(project, actor, task_unit(CONSOLIDATE_TASK_KIND))
        task = claim_next(
            project, actor, CONSOLIDATE_TASK_KIND, accept=lambda c: _still_open(project, c)
        )
    if task is None:
        return None
    content = task_content(project, task)
    assert isinstance(content, dict)
    return ClusterTask(
        task_id=task.task_id,
        pass_id=str(content["pass_id"]),
        cluster_index=int(str(content["cluster_index"])),
        kind=str(content["kind"]),
        members=list(content["members"]),  # type: ignore[arg-type]
        signals=list(content["signals"]),  # type: ignore[arg-type]
    )


def propose(
    project: Project,
    actor: Actor,
    task_id: str,
    *,
    action: Action,
    into: str | None = None,
    members: Sequence[str] = (),
    reason: str,
    quotes: Sequence[QuoteBasis] = (),
) -> str:
    """Record an agent's proposal for the cluster of a claimed task and complete the task; return
    the proposal id (`cnp_...`). `members` are drawn from the cluster; a merge names `into`, one
    of them. Refused (fields `actor`, `task_id`, `members`, `into`, `reason`, `quotes...`) for a
    non-agent, a task not held by this session, an unknown member, a blank or long reason or a
    non-verbatim quote; nothing is written then."""
    if actor.kind != "agent":
        raise _refuse(ValidationIssue("actor", "only an agent proposes a consolidation"))
    project.index.sync()
    task = require_holder(project, actor, task_id)
    if task.kind != CONSOLIDATE_TASK_KIND:
        raise _refuse(ValidationIssue("task_id", "not a consolidation task"))
    content = task_content(project, task)
    assert isinstance(content, dict)
    cluster = {str(m["id"]) for m in cast(list[dict[str, Any]], content["members"])}
    issues: list[ValidationIssue] = []
    if not _still_open(project, content):
        issues.append(ValidationIssue("task_id", "cluster-decided"))
    unknown = sorted(set(members) - cluster)
    if unknown or not members:
        issues.append(ValidationIssue("members", "not-in-cluster" if unknown else "none-named"))
    if action == "merge" and (into is None or into not in members):
        issues.append(ValidationIssue("into", "into-not-a-member"))
    if action != "merge" and into is not None:
        issues.append(ValidationIssue("into", "only-a-merge-names-into"))
    if not reason.strip() or len(reason) > 600:
        issues.append(ValidationIssue("reason", "1 to 600 characters"))
    for i, quote in enumerate(quotes):
        issues += quote_issues(project, quote, f"quotes[{i}]")
    if issues:
        raise _refuse(*issues)
    with project.writing():
        proposal_id = f"cnp_{project.ids.ulid()}"
        event = project.events.make(
            "consolidation.proposed",
            ConsolidationProposed(
                proposal_id=proposal_id,
                pass_id=str(content["pass_id"]),
                cluster_index=int(str(content["cluster_index"])),
                action=action,
                into=into,
                members=tuple(members),
                reason=reason,
                quotes=tuple(quotes),
            ),
            actor,
            refs=[proposal_id, str(content["pass_id"]), task_id],
            input_blob=task.content_blob,
        )
        project.record([event])
        complete_task(project, actor, task_id, [proposal_id])
    return proposal_id


# --- Decisions ---


def _proposal(project: Project, pass_id: str, index: int, proposal_id: str | None) -> Any | None:
    with project.index.connect() as conn:
        if proposal_id is not None:
            return conn.execute(
                text(
                    "SELECT proposal_id, proposer_session FROM consolidation_proposals "
                    "WHERE proposal_id = :p AND pass_id = :s AND cluster_index = :i"
                ),
                {"p": proposal_id, "s": pass_id, "i": index},
            ).first()
    return None


def decide_cluster(
    project: Project,
    actor: Actor,
    pass_id: str,
    cluster_index: int,
    decision: Decision,
    *,
    into: str | None = None,
    merge_from: Sequence[str] | None = None,
    reason: str,
    proposal_id: str | None = None,
) -> str:
    """Decide one cluster (human; gate `consolidation.decide`) and return the decision event id.
    A `merge` merges every member in `merge_from` (default: all but `into`) into `into`, through
    the kind's own merge event, in the same append as the decision. Refused, with nothing
    written (fields `actor`, `session`, `pass_id`, `cluster_index`, `into`, `merge_from`,
    `reason`, `proposal_id`, and the merge's own fields): see the module docstring."""
    with project.index.exclusive():
        project.index.sync()
        row = _pass_row(project, pass_id)
        issues: list[ValidationIssue] = []
        found: dict[str, Any] | None = None
        if row is None:
            issues.append(ValidationIssue("pass_id", "pass-unknown"))
        else:
            if row[2] is not None:
                issues.append(ValidationIssue("pass_id", "pass-completed"))
            found = next(
                (c for c in _pass_clusters(project, row) if int(c["index"]) == cluster_index),
                None,
            )
            if found is None:
                issues.append(ValidationIssue("cluster_index", "cluster-unknown"))
        proposal = _proposal(project, pass_id, cluster_index, proposal_id)
        if proposal_id is not None and proposal is None:
            issues.append(ValidationIssue("proposal_id", "proposal-unknown"))
        issues = [
            *gate_issues(
                project,
                actor,
                "consolidation.decide",
                proposer_session=None if proposal is None else str(proposal[1]),
            ),
            *issues,
        ]
        if actor.kind != "human" and not any(i.field == "actor" for i in issues):
            issues.append(ValidationIssue("actor", "only a human decides a cluster"))
        if not reason.strip() or len(reason) > 600:
            issues.append(ValidationIssue("reason", "1 to 600 characters"))
        if found is not None:
            with project.index.connect() as conn:
                decided = conn.execute(
                    text(
                        "SELECT 1 FROM consolidation_decisions WHERE pass_id = :p "
                        "AND cluster_index = :i"
                    ),
                    {"p": pass_id, "i": cluster_index},
                ).first()
            if decided is not None:
                issues.append(ValidationIssue("cluster_index", "already-decided"))
        merges: list[Event] = []
        if decision == "merge" and found is not None and not issues:
            members = [str(m) for m in found["members"]]
            if into is None or into not in members:
                issues.append(ValidationIssue("into", "into-not-a-member"))
            sources = [m for m in members if m != into] if merge_from is None else list(merge_from)
            if (
                not set(sources) <= set(members)
                or into in sources
                or not sources
                or len(set(sources)) != len(sources)
            ):
                issues.append(ValidationIssue("merge_from", "not-members-of-the-cluster"))
            if not issues and found["kind"] == "concept":
                assert into is not None
                issues += merge_group_issues(project, into, sources)
            if not issues:
                assert into is not None
                merges = [
                    _build_merge(
                        project, actor, str(found["kind"]), into, source, reason, proposal_id
                    )
                    for source in sources
                ]
        elif decision != "merge" and (into is not None or merge_from is not None):
            issues.append(ValidationIssue("into", "only-a-merge-names-into"))
        if issues:
            raise _refuse(*issues)
        decided_event = project.events.make(
            "consolidation.decided",
            ConsolidationDecided(
                pass_id=pass_id,
                cluster_index=cluster_index,
                decision=decision,
                merge_events=tuple(e.id for e in merges),
                reason=reason,
                proposal_id=proposal_id,
            ),
            actor,
            refs=[pass_id, *([proposal_id] if proposal_id else [])],
        )
        project.record([*merges, decided_event])
        return decided_event.id


def _build_merge(
    project: Project,
    actor: Actor,
    kind: str,
    into: str,
    source: str,
    reason: str,
    proposal_id: str | None,
) -> Event:
    if kind == "label":
        return build_label_merge(project, actor, into, source, reason, proposal_id)
    if kind == "idea":
        return build_idea_merge(project, actor, source, into, reason, proposal_id)
    return build_concept_merge(project, actor, into, source, reason, proposal_id)


def complete_pass(project: Project, actor: Actor, pass_id: str) -> str:
    """Complete a pass whose every cluster has a decision (human); returns the event id. Refused
    (field `pass_id`: `pass-unknown`, `pass-completed`, `undecided:<n>`)."""
    with project.index.exclusive():
        project.index.sync()
        issues = gate_issues(project, actor, "consolidation.decide")
        if actor.kind != "human":
            issues = issues or [ValidationIssue("actor", "only a human completes a pass")]
        row = _pass_row(project, pass_id)
        if row is None:
            issues.append(ValidationIssue("pass_id", "pass-unknown"))
        elif row[2] is not None:
            issues.append(ValidationIssue("pass_id", "pass-completed"))
        else:
            undecided = sum(1 for c in list_clusters(project, pass_id) if c.decision is None)
            if undecided:
                issues.append(ValidationIssue("pass_id", f"undecided:{undecided}"))
        if issues:
            raise _refuse(*issues)
        event = project.events.make(
            "consolidation.pass_completed",
            ConsolidationPassCompleted(pass_id=pass_id),
            actor,
            refs=[pass_id],
        )
        project.record([event])
        return event.id


__all__ = [
    "CONSOLIDATION_DUE_LABELS",
    "CONSOLIDATION_DUE_NODES",
    "Cluster",
    "ClusterRow",
    "ClusterTask",
    "DueState",
    "candidate_clusters",
    "complete_pass",
    "consolidation_due",
    "consolidation_next",
    "decide_cluster",
    "list_clusters",
    "open_pass_id",
    "propose",
    "start_pass",
]

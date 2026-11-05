"""The outline of verified material a draft is written against (slice 7b, plan W-A, task 4).

Declares: `OutlineScope`, `build_outline`, `outline_json`. A deterministic builder over the index;
it writes nothing and writes no prose.

Invariants:
- The outline holds ids and fixed codes only: no quote, no statement, no title. Two builds from the
  same log give the same JSON and the same `OL@` id.
- Sections, in this order: (1) one per confirmed idea in lineage order (an idea after the ideas it
  builds on, ties by the origin work's publication date, then id; a cycle, which stated edges
  cannot make, is broken by that same key); (2) one per comparability group with at least two
  works; (3) one per claim type for live claims of included works that no section above covers;
  (4) the limits: evidence-report limit codes and the works with no stated base.
- Method disagreement is a slot, never an average: a group section lists each disagreement as a
  list of cells (R-42).
- `agent=True` (default, and the only form a draft pins) builds from the agent variant of the
  evidence report, which withholds label-derived audit facts (decision 37.14); `agent=False` is the
  researcher's complete form, shown at the command line.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from pydantic import JsonValue

from factory.model.drafts import Outline, OutlineSection, outline_id_of
from factory.model.extraction import ClaimType
from factory.model.lineage import EdgeType
from factory.model.screening import PassLabel
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.contributions import final_items
from factory.services.evidence_report import (
    EvidenceReport,
    GroupReport,
    agent_evidence,
    evidence_report,
)
from factory.services.extraction import live_claims, stale_claims
from factory.services.ideas import IdeaView, confirmed_ideas
from factory.services.lineage import index_neighbours, no_stated_base
from factory.services.references import included_works
from factory.services.relations import list_relations
from factory.services.search import get_work
from factory.services.views import to_json

IDEA_ITEM_KINDS = frozenset({"base-idea", "addition", "limitation"})
_LINEAGE = frozenset({EdgeType.BUILDS_ON, EdgeType.IMPROVES_ON})


@dataclass(frozen=True)
class OutlineScope:
    """`works` restricts members, claims and groups' works; `ideas` and `groups` restrict the
    sections to the ids named (None: all)."""

    works: str | tuple[str, ...] = "included"
    ideas: tuple[str, ...] | None = None
    groups: tuple[str, ...] | None = None

    def as_json(self) -> dict[str, JsonValue]:
        works: JsonValue = self.works if isinstance(self.works, str) else list(sorted(self.works))
        ideas: JsonValue = None if self.ideas is None else list(sorted(self.ideas))
        groups: JsonValue = None if self.groups is None else list(sorted(self.groups))
        return {"works": works, "ideas": ideas, "groups": groups}


DEFAULT_SCOPE = OutlineScope()


def build_outline(
    project: Project, scope: OutlineScope = DEFAULT_SCOPE, *, agent: bool = True
) -> Outline:
    """The outline for `scope` as the log stands now."""
    with entering():
        project.index.sync()
        as_of = project.index.head()
        population = set(included_works(project))
        if not isinstance(scope.works, str):
            population &= set(scope.works)
        report = evidence_report(project)
        if agent:
            report = agent_evidence(report)
        sections: list[OutlineSection] = []
        sections += _idea_sections(project, scope, population)
        sections += _group_sections(report, scope, population, _claims_by_work(project, population))
        covered = {w for s in sections for w in s.works}
        sections += _claim_sections(project, population, covered)
        sections.append(_limits_section(project, report))
        scope_json = scope.as_json()
        return Outline(
            outline_id=outline_id_of(scope_json, sections),
            scope=scope_json,
            as_of=as_of,
            sections=sections,
        )


def outline_json(outline: Outline) -> str:
    """The canonical JSON of the outline (the form stored as the draft's blob)."""
    return to_json(outline)


# --- ideas ---


def _origin_date(project: Project, idea: IdeaView) -> str:
    work = get_work(project, idea.origin)
    published = None if work is None else work.dates.published
    return (published if isinstance(published, date) else date.max).isoformat()


def _lineage_order(project: Project, ideas: Sequence[IdeaView]) -> list[IdeaView]:
    """Bases before the ideas that build on them; ties by origin date then id."""
    by_id = {i.idea_id: i for i in ideas}
    neighbours = index_neighbours(project)
    needs: dict[str, set[str]] = {i: set() for i in by_id}
    for idea_id in by_id:
        for edge in neighbours(idea_id, "out", _LINEAGE):
            if edge.target in by_id and edge.target != idea_id:
                needs[idea_id].add(edge.target)
    key = {i: (_origin_date(project, v), i) for i, v in by_id.items()}
    ordered: list[IdeaView] = []
    remaining = set(by_id)
    while remaining:
        ready = [i for i in remaining if not (needs[i] & remaining)]
        pool = ready or sorted(remaining, key=lambda i: key[i])[:1]  # a cycle: break by key
        nxt = min(pool, key=lambda i: key[i])
        ordered.append(by_id[nxt])
        remaining.discard(nxt)
    return ordered


def _idea_sections(
    project: Project, scope: OutlineScope, population: set[str]
) -> list[OutlineSection]:
    ideas = [i for i in confirmed_ideas(project) if scope.ideas is None or i.idea_id in scope.ideas]
    if not ideas:
        return []
    items_by_work: dict[str, list[str]] = {}
    for item in final_items(project):
        if item.item_kind in IDEA_ITEM_KINDS and not item.stale:
            items_by_work.setdefault(item.work_id, []).append(f"item:{item.extraction_id}")
    claims_by_work = _claims_by_work(project, population)
    sections: list[OutlineSection] = []
    for idea in _lineage_order(project, ideas):
        members = sorted(w for w in idea.effective_members if w in population)
        origin_first = ([idea.origin] if idea.origin in members else []) + [
            w for w in members if w != idea.origin
        ]
        supports: list[str] = []
        for w in origin_first:
            supports += sorted(items_by_work.get(w, []))
        edges = _stated_edges(project, set(members))
        supports += edges
        for w in origin_first:
            supports += claims_by_work.get(w, [])
        sections.append(
            OutlineSection(
                section_ref=f"idea:{idea.idea_id}",
                kind="idea",
                title_ref=idea.idea_id,
                works=origin_first,
                supports=supports,
                conflicts=[],
                notes=[] if members else ["no-included-member"],
            )
        )
    return sections


def _stated_edges(project: Project, members: set[str]) -> list[str]:
    found: set[str] = set()
    for work in sorted(members):
        for rel in list_relations(project, work_id=work):
            if rel.source_work in members and EdgeType(rel.edge_type) in _LINEAGE:
                found.add(f"edge:{rel.relation_id}")
    return sorted(found)


# --- groups ---


def _group_sections(
    report: EvidenceReport,
    scope: OutlineScope,
    population: set[str],
    claims_by_work: dict[str, list[str]],
) -> list[OutlineSection]:
    sections: list[OutlineSection] = []
    for group in sorted(report.groups, key=lambda g: g.group_id):
        if scope.groups is not None and group.group_id not in scope.groups:
            continue
        works = sorted({r.work_id for r in group.rows if r.work_id in population})
        if len(works) < 2:
            continue
        sections.append(_group_section(group, works, claims_by_work))
    return sections


def _group_section(
    group: GroupReport, works: list[str], claims_by_work: dict[str, list[str]]
) -> OutlineSection:
    frontier = sorted(
        {
            f"cell:{p.trace_id}"
            for axis in group.frontiers
            for part in axis.partitions
            for p in part.points
            if p.on_frontier
        }
    )
    conflicts = [sorted(f"cell:{k}/value" for k in c.rows) for c in group.method_conflicts]
    return OutlineSection(
        section_ref=f"group:{group.group_id}",
        kind="group",
        title_ref=group.group_id,
        works=works,
        supports=[
            f"group:{group.group_id}",
            *frontier,
            *(c for w in works for c in claims_by_work.get(w, [])),
        ],
        conflicts=conflicts,
        notes=sorted({s.code for s in group.statements}),
    )


# --- claims ---


def _claims_by_work(project: Project, population: set[str]) -> dict[str, list[str]]:
    stale = stale_claims(project)
    out: dict[str, list[str]] = {}
    for c in live_claims(project, PassLabel.A):
        if c.work_id in population and c.claim_id not in stale:
            out.setdefault(c.work_id, []).append(f"claim:{c.claim_id}")
    return out


def _claim_sections(
    project: Project, population: set[str], covered: set[str]
) -> list[OutlineSection]:
    stale = stale_claims(project)
    by_type: dict[str, list[tuple[str, str]]] = {t.value: [] for t in ClaimType}
    for c in live_claims(project, PassLabel.A):
        if c.work_id in population and c.work_id not in covered and c.claim_id not in stale:
            by_type[c.claim_type.value].append((c.work_id, c.claim_id))
    return [
        OutlineSection(
            section_ref=f"claims:{claim_type.value}",
            kind="claims",
            title_ref=claim_type.value,
            works=sorted({w for w, _ in found}),
            supports=[f"claim:{cid}" for _, cid in sorted(found)],
            conflicts=[],
            notes=[],
        )
        for claim_type in ClaimType
        if (found := by_type[claim_type.value])
    ]


# --- limits ---


def _limits_section(project: Project, report: EvidenceReport) -> OutlineSection:
    base = no_stated_base(project)
    notes = sorted({lim.code for lim in report.limits})
    for name, works in (
        ("unextracted", base.unextracted),
        ("not-stated", base.not_stated),
        ("target-outside-corpus", base.target_outside_corpus),
        ("no-relation", base.no_relation),
    ):
        if works:
            notes.append(f"no-stated-base:{name}")
    return OutlineSection(
        section_ref="limits",
        kind="limits",
        title_ref="limits",
        works=[],
        supports=["stat:included-works", "stat:not-stated-count"],
        conflicts=[],
        notes=notes,
    )

"""Deterministic, bounded evaluation of region rules over the index (slice 3d, Regions-A).

A rule is evaluated to a temporary table of `(member_type, member)`; rules are combined by set
algebra in SQL: `(union of include and human adds) intersect within, minus (union of exclude and
human removes)`. The result does not depend on the order of rules.

Invariants:
- Read-only on the index: only connection-local temporary tables are written, and all are dropped.
- Bounded: a rule result or a region larger than `REGION_MAX_MEMBERS`, and a lineage traversal the
  bound truncates, refuse with a `FactoryValidationError` naming the rule (`rules.include[i]`,
  `rules.exclude[i]`, `rules.within`) and the reason `over-bound:<count>`; nothing is partial.
- No full-graph load: lineage expands a frontier through the indexed neighbour lookup.
- Work members are canonical ids (absorbed ids resolved through active merges); idea and concept
  members are live (merge-resolved) ids. A pinned `R@` is read from its snapshot blob, so a
  region's later snapshot never changes a rule that names an earlier one.
- No rule reads a seed or a screening-pass table (I8); a rule over corpus outcomes goes through
  `final_outcomes`.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from factory.errors import FactoryValidationError, ValidationIssue
from factory.extraction.numbers import normalise_text
from factory.lineage.graph import GraphFilter
from factory.lineage.paths import LINEAGE_TYPES, ancestors, descendants
from factory.model.lineage import EdgeType
from factory.regions.concept_use import concept_live, concept_survivor, concept_users
from factory.regions.rules import (
    CitesRule,
    ConceptRule,
    CorpusRule,
    IdeaRule,
    ImportRule,
    LineageRule,
    MemberType,
    RegionRule,
    Rule,
    RuleSet,
    RunRule,
    TermRule,
    TextRule,
)
from factory.regions.term_use import term_row, term_targets
from factory.regions.version import member_lines
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.ideas import _EFFECTIVE_MEMBERS
from factory.services.lineage import index_neighbours, require_node

REGION_MAX_MEMBERS = 200_000
IDEA_PREFIX = "ida_"
CONCEPT_PREFIX = "cpt_"
_CHUNK = 5_000

Member = tuple[MemberType, str]


@dataclass(frozen=True)
class Evaluation:
    """`members` sorted by (type, id); `basis[member]` lists the positions of the include rules
    that selected it (empty for a member only a human added)."""

    members: tuple[Member, ...]
    basis: Mapping[Member, tuple[int, ...]]
    counts: Mapping[MemberType, int]


def read_members_blob(blob: bytes) -> list[Member]:
    """The members of a snapshot's member blob, in blob order."""
    members: list[Member] = []
    for line in member_lines(blob):
        kind, member = line.split("\t", 1)
        members.append((MemberType(kind), member))
    return members


def pinned_members(conn: Connection, project: Project, version: str) -> list[Member] | None:
    """The members of the snapshot pinned as `version`, or None when no snapshot has it."""
    blob = conn.execute(
        text(
            "SELECT members_blob FROM region_snapshots WHERE version = :v "
            "ORDER BY event_id DESC LIMIT 1"
        ),
        {"v": version},
    ).scalar_one_or_none()
    if blob is None:
        return None
    return read_members_blob(project.blobs.get(str(blob)))


def _chunks(items: Iterable[Any], size: int = _CHUNK) -> Iterator[list[Any]]:
    iterator = iter(items)
    while batch := list(itertools.islice(iterator, size)):
        yield batch


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


class _Eval:
    """One evaluation: the connection, the temporary tables and the lazy shared lookups."""

    def __init__(self, conn: Connection, project: Project) -> None:
        self.conn = conn
        self.project = project
        self.tables: list[str] = []
        self._corpus: str | None = None
        self._counter = 0
        self.canon = self.new_table("canon", "work_id TEXT PRIMARY KEY, primary_id TEXT NOT NULL")
        conn.execute(
            text(
                f'INSERT INTO {self.canon} SELECT mm.work_id, m."primary" FROM merge_members mm '
                "JOIN merges m ON m.merge_id = mm.merge_id "
                "WHERE m.status = 'active' AND mm.work_id != m.\"primary\""
            )
        )

    def new_table(self, stem: str, columns: str) -> str:
        self._counter += 1
        name = f"_rg_{stem}_{self._counter}"
        self.conn.execute(text(f"CREATE TEMP TABLE {name} ({columns})"))
        self.tables.append(name)
        return name

    def new_members(self, stem: str = "rm") -> str:
        return self.new_table(
            stem, "member_type TEXT, member TEXT, PRIMARY KEY (member_type, member)"
        )

    def drop_all(self) -> None:
        """Drop the temporary tables and end the transaction, so the drops are not rolled back
        when the pooled connection is returned (the temp schema is connection-local)."""
        for name in reversed(self.tables):
            self.conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
        self.tables.clear()
        self.conn.commit()

    def stage(self, ids: Iterable[str]) -> str:
        """A temporary one-column table holding `ids`."""
        name = self.new_table("st", "id TEXT PRIMARY KEY")
        for batch in _chunks((i,) for i in ids):
            self.conn.execute(
                text(f"INSERT OR IGNORE INTO {name} (id) VALUES (:i)"), [{"i": b[0]} for b in batch]
            )
        return name

    def add_works(
        self, target: str, select_sql: str, params: Mapping[str, object] | None = None
    ) -> None:
        """Insert the work ids `select_sql` yields (column `id`), mapped to canonical ids."""
        self.conn.execute(
            text(
                f"INSERT OR IGNORE INTO {target} (member_type, member) "
                f"SELECT 'work', COALESCE(c.primary_id, s.id) FROM ({select_sql}) s "
                f"LEFT JOIN {self.canon} c ON c.work_id = s.id"
            ),
            dict(params or {}),
        )

    def live_idea(self, idea_id: str) -> str:
        """The idea `idea_id` stands for after merges (itself when unmerged or unknown)."""
        current, seen = idea_id, set()
        while current not in seen:
            seen.add(current)
            into = self.conn.execute(
                text("SELECT merged_into FROM ideas WHERE idea_id = :i"), {"i": current}
            ).scalar_one_or_none()
            if into is None:
                break
            current = str(into)
        return current

    def add_nodes(self, target: str, ids: Iterable[str]) -> None:
        """Insert graph node ids by kind: ideas and concepts as their live (merge-resolved) ids,
        everything else as canonical works."""
        ideas: set[str] = set()
        concepts: set[str] = set()
        works: list[str] = []
        for node in ids:
            if node.startswith(IDEA_PREFIX):
                ideas.add(self.live_idea(node))
            elif node.startswith(CONCEPT_PREFIX):
                concepts.add(concept_live(self.conn, node))
            else:
                works.append(node)
        self.add_works(target, f"SELECT id FROM {self.stage(works)}")
        self.add_members(target, [(MemberType.IDEA, i) for i in sorted(ideas)], resolved=True)
        self.add_members(target, [(MemberType.CONCEPT, c) for c in sorted(concepts)], resolved=True)

    def add_members(
        self, target: str, members: Iterable[Member], *, resolved: bool = False
    ) -> None:
        """Insert members; work ids are mapped to canonical ids and idea and concept ids to live
        ids (a decision or a pinned set may predate a merge) unless `resolved`."""
        kept: list[Member] = []
        works: list[str] = []
        for kind, member in members:
            if resolved:
                kept.append((kind, member))
            elif kind is MemberType.WORK:
                works.append(member)
            elif kind is MemberType.IDEA:
                kept.append((kind, self.live_idea(member)))
            else:
                kept.append((kind, concept_live(self.conn, member)))
        if works:
            self.add_works(target, f"SELECT id FROM {self.stage(works)}")
        for batch in _chunks(kept):
            self.conn.execute(
                text(f"INSERT OR IGNORE INTO {target} VALUES (:t, :m)"),
                [{"t": t.value, "m": m} for t, m in batch],
            )

    def corpus(self) -> str:
        """The corpus work ids (probe-only works excluded), staged once."""
        if self._corpus is None:
            self._corpus = self.stage(final_outcomes(self.project).keys())
        return self._corpus

    def count(self, table: str) -> int:
        return int(self.conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())

    def checked(self, table: str, field: str) -> None:
        reached = self.count(table)
        if reached > REGION_MAX_MEMBERS:
            raise _refuse(field, f"over-bound:{reached}")


# --- One evaluator per rule kind: (evaluation, rule, target table, field) -> None ---


def _corpus(ev: _Eval, rule: CorpusRule, target: str, field: str) -> None:
    outcomes = final_outcomes(ev.project, stage=rule.stage)
    if rule.outcome == "included":
        ids = [w for w, o in outcomes.items() if o is Outcome.INCLUDED]
    elif rule.outcome == "screened":
        ids = [w for w, o in outcomes.items() if o is not Outcome.PENDING]
    else:
        ids = list(outcomes)
    staged = ev.stage(ids)
    ev.add_works(target, f"SELECT id FROM {staged}")


def _run(ev: _Eval, rule: RunRule, target: str, field: str) -> None:
    column = "run_id" if rule.run_id is not None else "query_id"
    value = rule.run_id if rule.run_id is not None else rule.query_id
    ev.add_works(
        target,
        f"SELECT p.work_id AS id FROM provenance p JOIN {ev.corpus()} c ON c.id = p.work_id "
        f"WHERE p.{column} = :v",
        {"v": value},
    )


def _import(ev: _Eval, rule: ImportRule, target: str, field: str) -> None:
    known = ev.conn.execute(
        text("SELECT 1 FROM imports WHERE import_id = :i"), {"i": rule.import_id}
    ).first()
    if known is None:
        raise _refuse(f"{field}.import_id", "import-unknown")
    parts = "" if rule.part == "all" else " AND part IN ('development', 'unsplit')"
    ev.add_works(
        target,
        "SELECT work_id AS id FROM import_records WHERE import_id = :i "
        f"AND link_state = 'resolved' AND work_id IS NOT NULL{parts}",
        {"i": rule.import_id},
    )


def _lineage(ev: _Eval, rule: LineageRule, target: str, field: str) -> None:
    flt = GraphFilter(include_inferred=rule.include_inferred)
    require_node(ev.project, rule.node, f"{field}.node", flt)
    allowed = frozenset(EdgeType(t) for t in rule.edge_types) & LINEAGE_TYPES
    neighbours = index_neighbours(ev.project, flt)
    walk = ancestors if rule.direction == "ancestors" else descendants
    result = walk(
        lambda n, d, types: neighbours(n, d, types & allowed),
        rule.node,
        rule.depth,
        limit=REGION_MAX_MEMBERS,
    )
    if result.truncated:
        raise _refuse(field, f"over-bound:{len(result.nodes)}")
    ev.add_nodes(target, result.nodes)


def _pinned(ev: _Eval, version: str, field: str) -> list[Member]:
    members = pinned_members(ev.conn, ev.project, version)
    if members is None:
        raise _refuse(field, "unknown-version")
    return members


def _cites(ev: _Eval, rule: CitesRule, target: str, field: str) -> None:
    pinned = _pinned(ev, rule.base, f"{field}.base")
    base = ev.stage(m for t, m in pinned if t is MemberType.WORK)
    # The base read as canonical works, then widened with the ids merged into them, so the join
    # below stays on the edge indexes while both ends of each edge are grouped as canonical works.
    canonical = ev.new_table("cb", "id TEXT PRIMARY KEY")
    ev.conn.execute(
        text(
            f"INSERT OR IGNORE INTO {canonical} SELECT COALESCE(c.primary_id, b.id) "
            f"FROM {base} b LEFT JOIN {ev.canon} c ON c.work_id = b.id"
        )
    )
    expanded = ev.new_table("bx", "id TEXT PRIMARY KEY")
    ev.conn.execute(
        text(
            f"INSERT OR IGNORE INTO {expanded} SELECT id FROM {canonical} UNION "
            f"SELECT c.work_id FROM {ev.canon} c JOIN {canonical} b ON b.id = c.primary_id"
        )
    )
    # A stated or confirmed link of a live extraction; a human rejection removes it.
    live = (
        "e.edge_type = 'cites' AND e.live = 1 AND e.base_status IN ('stated', 'confirmed') "
        "AND COALESCE(e.decision, '') != 'reject'"
    )
    cs = "COALESCE(cs.primary_id, e.source)"
    ct = "COALESCE(ct.primary_id, e.target)"
    joins = (
        f"LEFT JOIN {ev.canon} cs ON cs.work_id = e.source "
        f"LEFT JOIN {ev.canon} ct ON ct.work_id = e.target"
    )
    # A resolved link may name a work no corpus query found: such a target joins no region.
    corpus = ev.corpus()
    if rule.direction == "citing":
        sql = (
            f"SELECT {cs} AS id FROM graph_edges e JOIN {expanded} b ON b.id = e.target {joins} "
            f"WHERE {live} AND {cs} IN (SELECT id FROM {corpus}) "
            f"GROUP BY {cs} HAVING COUNT(DISTINCT {ct}) >= :k"
        )
    else:
        sql = (
            f"SELECT {ct} AS id FROM graph_edges e JOIN {expanded} b ON b.id = e.source {joins} "
            f"WHERE {live} AND {ct} IN (SELECT id FROM {corpus}) "
            f"GROUP BY {ct} HAVING COUNT(DISTINCT {cs}) >= :k"
        )
    ev.add_works(target, sql, {"k": rule.min_k})


def _idea(ev: _Eval, rule: IdeaRule, target: str, field: str) -> None:
    current = rule.idea_id
    seen: set[str] = set()
    while current not in seen:
        seen.add(current)
        row = ev.conn.execute(
            text("SELECT superseded_by, decision, merged_into FROM ideas WHERE idea_id = :i"),
            {"i": current},
        ).first()
        if row is None or row[0] is not None or row[1] != "confirm":
            raise _refuse(f"{field}.idea_id", "idea-not-confirmed")
        if row[2] is None:
            break
        current = str(row[2])
    members = [str(r[0]) for r in ev.conn.execute(text(_EFFECTIVE_MEMBERS), {"i": current}).all()]
    ev.add_nodes(target, [current, *members])


def _concept(ev: _Eval, rule: ConceptRule, target: str, field: str) -> None:
    survivor = concept_survivor(ev.conn, rule.concept_id)
    if survivor is None:
        raise _refuse(f"{field}.concept_id", "concept-not-visible")
    ev.add_nodes(target, concept_users(ev.conn, survivor))


def _term(ev: _Eval, rule: TermRule, target: str, field: str) -> None:
    """Targets with a stated or confirmed application of the term; inferred ones never select
    (R-91). A retired or unknown term refuses."""
    row = term_row(ev.conn, rule.term_id)
    if row is None:
        raise _refuse(f"{field}.term_id", "term-unknown")
    if row.retired:
        raise _refuse(f"{field}.term_id", "term-retired")
    ev.add_members(
        target, [(MemberType(kind), member) for kind, member in term_targets(ev.conn, rule.term_id)]
    )


def _region(ev: _Eval, rule: RegionRule, target: str, field: str) -> None:
    ev.add_members(target, _pinned(ev, rule.version, f"{field}.version"))


def _text(ev: _Eval, rule: TextRule, target: str, field: str) -> None:
    hits: list[str] = []
    rows = ev.conn.execute(
        text(f"SELECT w.work_id, w.data FROM works w JOIN {ev.corpus()} c ON c.id = w.work_id")
    )
    for work_id, data in rows:
        record = json.loads(str(data))
        haystack = normalise_text(f"{record.get('title') or ''} {record.get('abstract') or ''}")
        if all(any(term in haystack for term in block) for block in rule.blocks):
            hits.append(str(work_id))
    ev.add_works(target, f"SELECT id FROM {ev.stage(hits)}")


_EVALUATORS: dict[str, Callable[[_Eval, Any, str, str], None]] = {
    "corpus": _corpus,
    "run": _run,
    "import": _import,
    "lineage": _lineage,
    "cites": _cites,
    "idea": _idea,
    "concept": _concept,
    "term": _term,
    "region": _region,
    "text": _text,
}


def _rule_table(ev: _Eval, rule: Rule, field: str) -> str:
    table = ev.new_members()
    _EVALUATORS[rule.kind](ev, rule, table, field)
    ev.checked(table, field)
    return table


def evaluate(
    conn: Connection,
    project: Project,
    rules: RuleSet,
    *,
    adds: Sequence[Member] = (),
    removes: Sequence[Member] = (),
) -> Evaluation:
    """Evaluate `rules` over the index. `adds` and `removes` are the human member decisions in
    effect. Call outside any open index read of the same thread's service work only through
    `project.index.connect()` (the evaluators sync nothing themselves)."""
    ev = _Eval(conn, project)
    try:
        included = [
            _rule_table(ev, rule, f"rules.include[{i}]") for i, rule in enumerate(rules.include)
        ]
        excluded = [
            _rule_table(ev, rule, f"rules.exclude[{i}]") for i, rule in enumerate(rules.exclude)
        ]
        within = None if rules.within is None else _rule_table(ev, rules.within, "rules.within")
        union = ev.new_members("union")
        for table in included:
            conn.execute(text(f"INSERT OR IGNORE INTO {union} SELECT * FROM {table}"))
        ev.add_members(union, adds)
        if within is not None:
            conn.execute(
                text(
                    f"DELETE FROM {union} WHERE (member_type, member) NOT IN "
                    f"(SELECT member_type, member FROM {within})"
                )
            )
        for table in excluded:
            conn.execute(
                text(
                    f"DELETE FROM {union} WHERE (member_type, member) IN "
                    f"(SELECT member_type, member FROM {table})"
                )
            )
        removed = ev.new_members("removes")
        ev.add_members(removed, removes)
        conn.execute(
            text(
                f"DELETE FROM {union} WHERE (member_type, member) IN "
                f"(SELECT member_type, member FROM {removed})"
            )
        )
        ev.checked(union, "rules")
        members = tuple(
            (MemberType(str(t)), str(m))
            for t, m in conn.execute(
                text(f"SELECT member_type, member FROM {union} ORDER BY member_type, member")
            )
        )
        basis: dict[Member, list[int]] = {}
        for index, table in enumerate(included):
            for t, m in conn.execute(
                text(
                    f"SELECT r.member_type, r.member FROM {table} r JOIN {union} u "
                    "ON u.member_type = r.member_type AND u.member = r.member"
                )
            ):
                basis.setdefault((MemberType(str(t)), str(m)), []).append(index)
        counts = {kind: sum(1 for t, _ in members if t is kind) for kind in MemberType}
        return Evaluation(
            members=members,
            basis={member: tuple(basis.get(member, ())) for member in members},
            counts={k: v for k, v in counts.items() if v},
        )
    finally:
        ev.drop_all()

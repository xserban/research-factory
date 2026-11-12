"""Shared setup for the region tests (slice 3d, plan Regions-A).

`region_project` is the screened full-text world (real corpus, real screening outcomes) with a
small graph written straight into the index tables, as the lineage scale test does: `cites` links,
`builds-on` relations, a confirmed idea and an approved concept with uses. The rows are written
without events, so a test that rebuilds the index must not rely on them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from sqlalchemy import text

from factory.regions.rules import MemberType
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.search import list_works
from tests.contribution_helpers import screened  # noqa: F401

Member = tuple[MemberType, str]


@dataclass
class RWorld:
    project: Project
    included: list[str]
    corpus: list[str]
    idea: str
    concept: str
    outside: str
    """A work id outside the corpus that the graph names."""
    extra: str
    """A corpus work that is not full-text included (a valid target for a human add)."""

    def works(self, *ids: str) -> list[Member]:
        return [(MemberType.WORK, i) for i in ids]


def _edge(i: int, kind: str, source: str, target: str) -> dict[str, object]:
    return {"id": f"cit:rex_{i:026d}:1", "s": source, "t": target, "k": kind}


@pytest.fixture
def region_project(project: Project, screened: list[str]) -> RWorld:  # noqa: F811
    project.index.sync()
    included = sorted(screened)
    assert len(included) >= 4, included
    corpus = sorted(w.id for w in list_works(project))
    a, b, c, d = included[:4]
    outside = "rf:outside-00000001"
    idea = "ida_01JZ9Q3K5M7N8P0R2S4T6V8W1I"
    concept = "cpt_01JZ9Q3K5M7N8P0R2S4T6V8W1K"
    cites = [(a, b), (a, c), (d, b), (outside, b), (outside, c)]
    lineage = [(b, a), (c, b), (d, c)]  # source builds on target
    nodes = [*included, outside]
    with project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO graph_nodes (node_id, node_type, event_id) "
                "VALUES (:n, 'paper', 'ev')"
            ),
            [{"n": n} for n in nodes],
        )
        conn.execute(
            text(
                "INSERT INTO graph_edges (edge_id, edge_type, source, target, base_status, live, "
                "flags, event_id) VALUES (:id, 'cites', :s, :t, 'stated', 1, '[]', 'ev')"
            ),
            [{"id": f"cit:rex_{i:026d}:1", "s": s, "t": t} for i, (s, t) in enumerate(cites)],
        )
        for i, (s, t) in enumerate(lineage):
            rid = f"rel_{i:026d}"
            conn.execute(
                text(
                    "INSERT INTO relations (relation_id, source_work, target, edge_type, "
                    "status, flags, decision, event_id) VALUES "
                    "(:id, :s, :t, 'builds-on', 'inferred', '[]', 'confirm', 'ev')"
                ),
                {"id": rid, "s": s, "t": t},
            )
            conn.execute(
                text(
                    "INSERT INTO graph_edges (edge_id, edge_type, source, target, base_status, "
                    "live, decision, flags, event_id) VALUES "
                    "(:id, 'builds-on', :s, :t, 'inferred', 1, 'confirm', '[]', 'ev')"
                ),
                {"id": rid, "s": s, "t": t},
            )
        conn.execute(
            text(
                "INSERT INTO ideas (idea_id, name, name_item, origin, decision, event_id) "
                "VALUES (:i, 'kernel trick', 'itm_x', :o, 'confirm', 'ev')"
            ),
            {"i": idea, "o": a},
        )
        conn.execute(
            text("INSERT INTO idea_members (idea_id, work_id) VALUES (:i, :w)"),
            [{"i": idea, "w": w} for w in (a, c)],
        )
        conn.execute(
            text(
                "INSERT INTO graph_nodes (node_id, node_type, event_id) VALUES (:i, 'idea', 'ev')"
            ),
            {"i": idea},
        )
        conn.execute(
            text(
                "INSERT INTO concepts (concept_id, name, name_folded, author, author_user, "
                "writer_session, definition_event, source_state, review_state, self_reviewed, "
                "event_id) VALUES (:c, 'Kernel', 'kernel', 'human', 'obd', 's', 'ev', 'approved', "
                "'reviewed', 0, 'ev')"
            ),
            {"c": concept},
        )
        conn.execute(
            text(
                "INSERT INTO concept_uses (link_id, from_node, from_kind, concept_id, basis_kind, "
                "basis_digest, proposed_status, status, status_reason, proposer_kind, "
                "proposer_session, event_id) VALUES (:l, :n, :k, :c, 'quote', 'd', :st, :st, "
                "'x', 'human', 's', 'ev')"
            ),
            [
                {"l": "lnk_1", "n": b, "k": "paper", "c": concept, "st": "stated"},
                {"l": "lnk_2", "n": idea, "k": "idea", "c": concept, "st": "confirmed"},
                {"l": "lnk_3", "n": d, "k": "paper", "c": concept, "st": "inferred"},
            ],
        )
        conn.commit()
    outcomes = final_outcomes(project)
    assert Outcome.INCLUDED in outcomes.values()
    extra = next(w for w in corpus if w not in included)
    return RWorld(project, included, corpus, idea, concept, outside, extra)


MERGE_ID = "mrg_01HZX3K4M5N6P7Q8R9S0TVWXY1"
"""A well-formed merge id: the readers validate rows as `DedupMerged`, whose id is a ULID."""


def merge_works(project: Project, primary: str, *absorbed: str, merge_id: str = MERGE_ID) -> None:
    """An active dedup merge written straight into the index (the evaluator reads the lookups)."""
    members = [primary, *absorbed]
    with project.index.connect() as conn:
        conn.execute(
            text(
                'INSERT INTO merges (merge_id, "primary", absorbed, rule, records, status) '
                "VALUES (:m, :p, :a, 'x', :n, 'active')"
            ),
            {"m": merge_id, "p": primary, "a": json.dumps(list(absorbed)), "n": len(members)},
        )
        conn.execute(
            text("INSERT INTO merge_members (merge_id, work_id) VALUES (:m, :w)"),
            [{"m": merge_id, "w": w} for w in members],
        )
        conn.commit()


def cite(project: Project, source: str, target: str, key: str) -> None:
    """A live stated `cites` edge written straight into the index."""
    with project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO graph_edges (edge_id, edge_type, source, target, base_status, live, "
                "flags, event_id) VALUES (:id, 'cites', :s, :t, 'stated', 1, '[]', 'ev')"
            ),
            {"id": f"cit:rex_{key:0>26}:1", "s": source, "t": target},
        )
        conn.commit()


def snapshot_event(
    project: Project, version: str, region: str, definition_event: str, members: list[Member]
) -> None:
    """Record a `region.snapshot_taken` for `version` under a given definition event, without
    evaluating (the guards read the definition a version was pinned under)."""
    from factory.model.regions import RegionSnapshotTaken
    from factory.regions.version import compress, members_text

    payload = RegionSnapshotTaken(
        region_id=region,
        version=version,
        definition_event=definition_event,
        rules_hash="0" * 64,
        members_blob=project.blobs.put(compress(members_text(members))),
        members_hash="1" * 64,
        basis_blob=project.blobs.put_json({}),
        counts={MemberType.WORK: len(members)},
        as_of=definition_event,
    )
    project.record([project.events.make("region.snapshot_taken", payload, project.system_actor())])


def definition_event_of(project: Project, region: str) -> str:
    with project.index.connect() as conn:
        return str(
            conn.execute(
                text(
                    "SELECT event_id FROM region_definitions WHERE region_id = :r "
                    "ORDER BY event_id DESC LIMIT 1"
                ),
                {"r": region},
            ).scalar_one()
        )


def add_queries(project: Project, purposes: dict[str, str]) -> None:
    """Queries (and one finished run each, `run_<query>`) of the given purposes, written straight
    into the index."""
    with project.index.connect() as conn:
        for query, purpose in purposes.items():
            conn.execute(
                text(
                    "INSERT INTO queries (query_id, source, kind, text, purpose, filters, "
                    "interface, registered_at, actor_id) VALUES (:q, 's', 'k', 't', :p, '{}', "
                    "'i', 'now', 'a')"
                ),
                {"q": query, "p": purpose},
            )
            conn.execute(
                text(
                    "INSERT INTO runs (run_id, query_id, source, status, started_at, pages) "
                    "VALUES (:r, :q, 's', 'finished', 'now', 0)"
                ),
                {"r": f"run_{query}", "q": query},
            )
        conn.commit()

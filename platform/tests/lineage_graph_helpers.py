"""Writes the constructed graph `fixtures/lineage/graph_small.json` as events (slice 3b, G2-D).

Every status is made the way the platform makes it: `stated` and `confirmed` cites edges are G1
links (matcher-resolved, or unconfirmed and then confirmed by a human); a stated relation rests
on a resolved link of the same source and target, a stale one on an entry that no link resolves,
a confirmed or rejected relation is an inferred one a human decided, ideas are proposed and
decided. Invented ids only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from factory.events.envelope import Actor, Event
from factory.services.context import Project
from tests.lineage_payloads import ITEM, inferred, stated
from tests.test_references_index import _extract, _resolve
from tests.test_references_model import BLOB, resolution

GRAPH_SMALL = Path(__file__).parent / "fixtures" / "lineage" / "graph_small.json"


def record(project: Project, type_: str, payload: Any, actor: Actor) -> Event:
    model = project.catalog.get(type_).payload.model_validate(payload)
    blob = project.blobs.put_json(payload) if actor.kind == "agent" else None
    event = project.events.make(type_, model, actor, input_blob=blob)
    project.record([event])
    return event


def _rex_of(edge_id: str) -> tuple[str, int]:
    _, rex, ordinal = edge_id.split(":")
    return rex, int(ordinal)


def write_fixture(project: Project, agent: Actor, path: Path = GRAPH_SMALL) -> None:
    doc = json.loads(path.read_text())
    human = project.human_actor()
    cites = [e for e in doc["edges"] if e["type"] == "cites"]
    relations = [e for e in doc["edges"] if e["id"].startswith("rel_")]
    ideas = [n for n in doc["nodes"] if n["type"] == "idea"]
    link_of = {(e["source"], e["target"]): _rex_of(e["id"]) for e in cites}
    # One G1 extraction per source work; entries 1..max ordinal (a stale relation names entry 1).
    sources: dict[str, tuple[str, int]] = {}
    for e in cites:
        rex, ordinal = _rex_of(e["id"])
        sources[e["source"]] = (rex, max(ordinal, sources.get(e["source"], (rex, 0))[1]))
    stale_rex = {
        e["source"]: "rex_01HZX3K4M5N6P7Q8R9S0" + f"{900 + i:06d}"
        for i, e in enumerate(x for x in relations if x["status"] == "stale")
    }
    for source, (rex, n) in sorted(sources.items()):
        _extract(project, rex, n=n, work_id=source)
        mine = sorted((_rex_of(e["id"])[1], e) for e in cites if e["source"] == source)
        _resolve(
            project,
            [
                resolution(o, work_id=e["target"])
                if e["status"] == "stated"
                else resolution(
                    o,
                    state="unconfirmed",
                    work_id=e["target"],
                    method="source-title",
                    confidence="title-fuzzy",
                    score=0.91,
                    candidates=[{"work_id": e["target"], "score": 0.91}],
                    source_blob=BLOB,
                )
                for o, e in mine
            ],
            rex,
        )
        for o, e in mine:
            if e["status"] == "confirmed":
                record(
                    project,
                    "reference.resolution_decided",
                    {
                        "extraction_id": rex,
                        "ordinal": o,
                        "decision": "confirm",
                        "work_id": e["target"],
                        "rationale": "invented rationale",
                        "quotes": [],
                        "confirmed_by": "human",
                    },
                    human,
                )
    for source, rex in stale_rex.items():
        _extract(project, rex, n=1, work_id=source)
    for n in ideas:
        record(
            project,
            "idea.proposed",
            {
                "idea_id": n["id"],
                "name": n["name"],
                "name_item": ITEM,
                "origin": n["members"][0],
                "members": n["members"],
                "supersedes": None,
            },
            agent,
        )
        record(
            project,
            "idea.decided",
            {"idea_id": n["id"], "decision": "confirm", "rationale": "checked"},
            human,
        )
    for e in relations:
        common = {
            "relation_id": e["id"],
            "source_work": e["source"],
            "target": e["target"],
            "edge_type": e["type"],
            "basis_item": ITEM,
        }
        if e["status"] in ("stated", "stale"):
            if e["status"] == "stated":
                rex, ordinal = link_of[(e["source"], e["target"])]
            else:
                rex, ordinal = stale_rex[e["source"]], 1
            payload = stated(
                **common,
                reference_extraction_id=rex,
                cited_entry=ordinal,
                resolved_target=e["target"],
            )
        else:
            payload = inferred(**common, status_reason="no-cited-entry", resolved_target=None)
            payload["reference_extraction_id"] = None
            payload["cited_entry"] = None
        record(project, "relation.proposed", payload, agent)
        if e["status"] in ("confirmed", "rejected"):
            decision = "confirm" if e["status"] == "confirmed" else "reject"
            record(
                project,
                "relation.decided",
                {"relation_id": e["id"], "decision": decision, "rationale": "checked"},
                human,
            )


def stand_in_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixture's relations name one stand-in basis item that is no real contribution item, so
    the final-view basis check (G2-C) would mark every relation stale. Neutralise that check; the
    other staleness reasons (link, extraction) stay real. Basis staleness is tested in G2-C."""

    def neutral(project: object) -> dict[str, str]:
        return {"stale": "[]", "retracted": "[]", "unresolved": "[]", "cited": "{}"}

    monkeypatch.setattr("factory.services.relations._basis_params", neutral)
    monkeypatch.setattr("factory.services.lineage._basis_params", neutral)

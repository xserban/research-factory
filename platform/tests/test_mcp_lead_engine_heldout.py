"""The lead engine MCP replies with a real held-out seed in every text field of a candidate:
no stated identifier or seed id of the seed survives (R-20; decisions 37 item 9, 81, 123).

The services are replaced by fakes that carry the seed's identifiers; the seed, its tokens and
the scrubbing are the real ones. The seed's work id is not masked (a work is corpus, decision 37
item 9): the test records that too."""

# ruff: noqa: F811
from __future__ import annotations

import json
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.mcp import server as mcp_server
from factory.model.lead_engine import (
    BasisRow,
    Candidate,
    CandidateQuote,
    Candidates,
    CandidateTrigger,
    CandidateWork,
    Measures,
    Queue,
    QueueItem,
    Verification,
)
from factory.services.context import Project
from factory.services.seeds import SeedRole, all_seeds
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.helpers import open_session


def _candidate(ids: list[str], work_id: str) -> Candidate:
    text = " ".join(ids)
    return Candidate(
        candidate_id=f"technique-gap:{ids[0]}",
        source="technique-gap",
        observation=f"Observation about {text}",
        approaches=(f"approach {ids[0]}",),
        works=(CandidateWork(work_id=work_id, title=f"A title naming {text}"),),
        works_total=1,
        quotes=(
            CandidateQuote(
                role="a",
                work_id=work_id,
                extraction_id=f"ext_{ids[0]}",
                quote=f"the paper cites {text} verbatim",
                anchor="s3.p1",
            ),
        ),
        triggers=(
            CandidateTrigger(kind="item", ref=f"ext_{ids[0]}"),
            CandidateTrigger(kind="work", ref=work_id),
        ),
        basis=(BasisRow(extraction_id=f"ext_{ids[0]}", work_id=work_id, role="a"),),
        trigger_note=f"note {text}",
        miners=("m-x v1",),
    )


def _measures() -> Measures:
    return Measures(
        support=1,
        independence=1,
        verification=Verification(verified=1, total=1, share=1.0),
        supportive_share=None,
        overlap=None,
        diversity=1.0,
        diversity_vs=None,
        prior_hits=0,
        narrow_prior_hits=0,
        closed_direction_hit=False,
        score=0.0,
        score_flag=None,
        basis="live",
    )


@pytest.mark.anyio
async def test_a_held_out_seeds_identifiers_are_gone_from_every_field_of_both_replies(
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    ids = [i for i in (held.seed_id, held.doi, held.arxiv, held.openalex) if i]
    assert held.seed_id in ids and held.doi in ids
    work_id = held.work_id or "rf:keepme"
    cand = _candidate(ids, work_id)
    item = QueueItem(
        kind="candidate",
        entry_id=cand.candidate_id,
        source="technique-gap",
        rank=1,
        measures=_measures(),
        prior=(),
        flags=(),
        candidate=cand,
    )
    monkeypatch.setattr(
        mcp_server,
        "lead_candidates_service",
        lambda *a, **k: Candidates(parameters={}, totals={}, candidates=(cand,)),
    )
    monkeypatch.setattr(
        mcp_server,
        "lead_queue_service",
        lambda *a, **k: Queue(
            order_by=("support",),
            order_rule="r",
            comparability="c",
            parameters={},
            items=(item,),
            leads=(),
            total_candidates=1,
        ),
    )
    async with open_session(settings, clock) as client:
        outs: list[dict[str, Any]] = [
            await client.call("lead_candidates", project="demo"),
            await client.call("lead_queue", project="demo"),
        ]
    for out in outs:
        assert out["ok"] is True, out
        text = json.dumps(out)
        for ident in ids:
            assert ident not in text, ident
        assert "[withheld]" in text
        assert work_id in text  # a work id is corpus, never masked (decision 37 item 9)

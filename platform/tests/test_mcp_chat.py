"""The chat MCP tools: thin wrappers, agent views, located refusals (plan chat T4b, T6)."""

# ruff: noqa: F811
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.screening import PassLabel
from factory.services.context import Project
from tests.claims_helpers import QUOTES, claim_row, claims_spec
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.helpers import open_session
from tests.miner_helpers import SESSION_M1, list_miner, mine_pass, miner_actor

A = PassLabel.A


async def _call(settings: Settings, clock: FixedClock, tool: str, **args: Any) -> dict[str, Any]:
    async with open_session(settings, clock) as client:
        return await client.call(tool, project="demo", **args)


@pytest.mark.anyio
async def test_selection_sections_verify_and_profiles(
    settings: Settings, project: Project, clock: FixedClock, world: list[str]
) -> None:
    out = await _call(settings, clock, "selection_resolve", exclude=[world[0]])
    assert out["ok"] is True, out
    data = out["data"]
    assert [w["work_id"] for w in data["works"]] == sorted(world)[1:]
    assert [r for _, r in data["excluded"]] == ["excluded"] and len(data["digest"]) == 64

    work = sorted(world)[1]
    sections = await _call(settings, clock, "chat_sections", work_id=work)
    assert sections["ok"] is True and sections["data"]["sections"]

    verified = await _call(
        settings,
        clock,
        "chat_verify",
        items=[
            {"work_id": work, "anchor": "s3.p1", "quote": "Lorem ipsum"},
            {"work_id": work, "anchor": "s3.p1", "quote": "nothing like it"},
        ],
    )
    assert [r["status"] for r in verified["data"]["results"]] == [
        "accepted",
        "quote-not-in-anchor",
    ]
    bad = await _call(settings, clock, "chat_verify", items=[{"work_id": work, "anchor": "s3.p1"}])
    assert bad["ok"] is False
    assert bad["errors"][0]["field"] == "items[0].quote"

    profiles = await _call(settings, clock, "paper_profiles", work_ids=[work])
    assert profiles["ok"] is True
    assert profiles["data"]["profiles"][0]["text"].startswith(work)
    assert profiles["data"]["size"]["chars"] > 0
    unknown = await _call(settings, clock, "paper_profiles", work_ids=["rf:nope"])
    assert unknown["ok"] is False


@pytest.mark.anyio
async def test_corpus_search_tool(
    settings: Settings, project: Project, clock: FixedClock, world: list[str]
) -> None:
    out = await _call(settings, clock, "corpus_search", queries=["lorem"], limit=3)
    assert out["ok"] is True, out
    assert len(out["data"]["hits"]) <= 3 and "digest" in out["data"]
    refused = await _call(settings, clock, "corpus_search", queries=["x"], kinds=["nonsense"])
    assert refused["ok"] is False and refused["errors"][0]["field"] == "kinds"


@pytest.mark.anyio
async def test_claims_digest_and_candidates_tools(
    settings: Settings, project: Project, agent: Actor, clock: FixedClock, world: list[str]
) -> None:
    list_miner(project, agent, claims_spec())
    order = sorted(world)
    mine_pass(
        project,
        miner_actor(SESSION_M1, "claude-opus-5-5"),
        A,
        lambda w: [claim_row("limitation", QUOTES[0])] if w != order[0] else [],
        name="m-claims",
    )
    out = await _call(settings, clock, "claims_digest")
    assert out["ok"] is True, out
    data = out["data"]
    assert data["papers"] == len(order) and data["claims"] == len(order) - 1
    assert data["gaps"] == [{"code": "P01", "work_id": order[0], "gap": "no-rows"}]
    assert data["markdown"].startswith("# Claims digest") and "## P02 " in data["markdown"]
    assert data["size"]["chars"] == len(data["markdown"])

    good = {"work_id": order[1], "source": "claims", "stance": "against"}
    quote = {"anchor": "s3.p1", "quote": "Lorem ipsum"}
    cands = await _call(
        settings,
        clock,
        "chat_candidates",
        proposals=[
            {**good, **quote},
            {**good, "source": "researcher", "stance": "for"},
        ],
    )
    assert cands["ok"] is True, cands
    by = {c["work_id"]: c for c in cands["data"]["candidates"]}
    assert by[order[1]]["tier"] == 1 and cands["data"]["total"] == len(order)
    assert cands["data"]["by_tier"]["1"] == 1

    refused = await _call(settings, clock, "chat_candidates", proposals=[good])
    assert refused["ok"] is False and refused["errors"][0]["field"] == "proposals[0].quote"
    odd = await _call(settings, clock, "chat_candidates", proposals=[{**good, "colour": "red"}])
    assert odd["errors"][0]["field"] == "proposals[0].colour"
    missing = await claims_missing(settings, clock)
    assert missing["ok"] is False and missing["errors"][0]["field"] == "miner"


async def claims_missing(settings: Settings, clock: FixedClock) -> dict[str, Any]:
    return await _call(settings, clock, "claims_digest", miner="m-nothing")

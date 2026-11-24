# ruff: noqa: F401, F811
"""The `contribution_items` MCP tool: the live items with their ids for the lineage proposer,
read-only, paged, refused to a pass session, and without pass, agreement or audit data."""

from __future__ import annotations

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.services.context import Project
from tests.contribution_helpers import ctr_a, ctr_b, screened, world
from tests.helpers import open_session
from tests.lineage_helpers import Lineage, disputed, lin
from tests.test_mcp_cards import _session

READER = "01JZ9Q3K5M7N8P0R2S4T6V8W9Z"
FIELDS = {
    "id",
    "work",
    "item_kind",
    "name",
    "statement",
    "quote",
    "anchor",
    "cited_entry",
    "disputed",
}


@pytest.mark.anyio
async def test_lists_the_final_items_with_ids_and_evidence(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    lin: Lineage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session(monkeypatch, READER)
    async with open_session(settings, clock) as client:
        out = await client.call("contribution_items", project="demo")
    assert out["ok"] is True, out
    items = out["data"]["items"]
    assert len(items) == 4 and out["data"]["next_cursor"] is None
    base = {i["id"]: i for i in items}[lin.base]
    assert base["item_kind"] == "base-idea" and base["work"] == lin.source
    assert base["name"] == "linear attention" and base["cited_entry"] == 5
    assert base["quote"] and base["anchor"] and base["disputed"] is False
    assert {i["item_kind"] for i in items} == {"base-idea", "addition", "limitation"}


@pytest.mark.anyio
async def test_filters_by_work_and_kind(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    lin: Lineage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session(monkeypatch, READER)
    async with open_session(settings, clock) as client:
        bases = await client.call("contribution_items", project="demo", kind="base-idea")
        mine = await client.call("contribution_items", project="demo", work=lin.source)
        other = await client.call("contribution_items", project="demo", work=lin.target5)
        bad = await client.call("contribution_items", project="demo", kind="limitation")
    assert {i["id"] for i in bases["data"]["items"]} == {lin.base, lin.uncited_base}
    assert len(mine["data"]["items"]) == 4
    assert other["data"]["items"] == [] and "notice" in other["data"]
    assert bad["ok"] is False and bad["errors"][0]["field"] == "kind"


@pytest.mark.anyio
async def test_pages_with_a_cursor(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    lin: Lineage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session(monkeypatch, READER)
    async with open_session(settings, clock) as client:
        first = await client.call("contribution_items", project="demo", limit=3)
        rest = await client.call(
            "contribution_items", project="demo", limit=3, cursor=first["data"]["next_cursor"]
        )
        bad = await client.call("contribution_items", project="demo", cursor="x")
    assert len(first["data"]["items"]) == 3 and first["data"]["next_cursor"] == "3"
    assert len(rest["data"]["items"]) == 1 and rest["data"]["next_cursor"] is None
    ids = [i["id"] for i in first["data"]["items"] + rest["data"]["items"]]
    assert len(set(ids)) == 4
    assert bad["ok"] is False and bad["errors"][0]["field"] == "cursor"


@pytest.mark.anyio
async def test_a_disputed_item_is_flagged(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    disputed: Lineage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session(monkeypatch, READER)
    async with open_session(settings, clock) as client:
        out = await client.call("contribution_items", project="demo")
    items = out["data"]["items"]
    flagged = [i for i in items if i["disputed"]]
    assert flagged and {i["item_kind"] for i in flagged} == {"base-idea"}
    assert disputed.addition in {i["id"] for i in items if not i["disputed"]}


@pytest.mark.anyio
async def test_no_pass_label_agreement_or_audit_is_shown(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    disputed: Lineage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session(monkeypatch, READER)
    async with open_session(settings, clock) as client:
        out = await client.call("contribution_items", project="demo")
    assert all(set(item) == FIELDS for item in out["data"]["items"])
    assert set(out["data"]) <= {"items", "next_cursor", "notice"}


@pytest.mark.anyio
async def test_refused_to_a_pass_session(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    lin: Lineage,
    ctr_a: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session(monkeypatch, ctr_a.session)
    async with open_session(settings, clock) as client:
        out = await client.call("contribution_items", project="demo")
    assert out["ok"] is False and out["errors"][0]["field"] == "session", out

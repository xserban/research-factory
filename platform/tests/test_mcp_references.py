"""The reference and snowball MCP tools: pass sessions refused, agents only propose, dry run by
default, nothing about held-out seeds or the seed route (slice 3a, ruling 3; R-20)."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from mcp import Client
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp.server import build_server
from factory.model.work_ids import work_id
from factory.services.context import Project
from factory.services.seeds import SeedRole, all_seeds
from tests.document_helpers import fetched_document, make_registry, promoted_works, run_convert
from tests.helpers import SourcesFor, _leaks, _setup, open_session
from tests.references_service_helpers import Lookups, bib_html, oa_item
from tests.test_screening_next import _draw
from tests.test_snowball_round import BODY_A, BODY_B, ENTRIES_A, ENTRIES_B, PLAN, _amend, _lookups

AGENT = {"role": "referencer", "model": "claude-sonnet-5-5", "skill": "rf-screen"}
NEW_TOOLS = [
    "references_extract",
    "references_status",
    "references_list",
    "reference_decide",
    "snowball_round",
    "snowball_compare",
]


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _fields(body: dict[str, Any]) -> list[str]:
    assert body["ok"] is False, body
    return [error["field"] for error in body["errors"]]


@pytest.fixture
def converted(project: Project, corpus: None) -> tuple[str, str]:
    """Two included works with converted documents and no reference extraction yet."""
    work_a, work_b = promoted_works(project)[:2]
    fetched_document(project, work_a, bib_html(ENTRIES_A, BODY_A))
    fetched_document(project, work_b, bib_html(ENTRIES_B, BODY_B))
    run_convert(project, make_registry())
    return work_a, work_b


async def _extracted(session: Any) -> dict[str, Any]:
    body: dict[str, Any] = await session.call("references_extract", project="demo", **AGENT)
    assert body["ok"] is True, body
    return body


@pytest.mark.anyio
async def test_tools_registered_and_named_area_verb(settings: Settings, clock: FixedClock) -> None:
    server = build_server(settings, clock=clock)
    async with Client(server) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    assert names[-len(NEW_TOOLS) :] == NEW_TOOLS
    assert "seed_check" not in names
    assert all(name.split("_")[0] in {"references", "reference", "snowball"} for name in NEW_TOOLS)


@pytest.mark.anyio
async def test_references_extract_partial_success(
    settings: Settings, project: Project, clock: FixedClock, converted: tuple[str, str]
) -> None:
    work_a, _ = converted
    stranger = work_id(title="Not in this corpus", authors=["Nobody"], year=1999)
    async with open_session(settings, clock, _lookups().sources()) as session:
        body = await session.call(
            "references_extract", project="demo", work_ids=[work_a, stranger], **AGENT
        )
        assert body["ok"] is True, body
        [done] = body["data"]["extractions"]
        assert done["work_id"] == work_a and done["entries"] == len(ENTRIES_A)
        assert body["data"]["skipped"] == [{"work_id": stranger, "reason": "not-included"}]
        malformed = await session.call(
            "references_extract", project="demo", work_ids=["nope"], **AGENT
        )
        assert _fields(malformed) == ["work_ids"]
        status = await session.call("references_status", project="demo")
    counts = status["data"]
    assert counts["entries"] == len(ENTRIES_A)
    states = ("resolved", "unconfirmed", "ambiguous", "unresolved")
    assert sum(counts[s] for s in states) == counts["entries"]
    events = read_all(project.paths.events_dir, project.catalog)
    [recorded] = [e for e in events if e.type == "reference.extracted"]
    assert recorded.actor.kind == "agent" and recorded.actor.model == AGENT["model"]
    assert recorded.actor.skill is not None


@pytest.mark.anyio
async def test_references_list_pages_and_filters(
    settings: Settings, project: Project, clock: FixedClock, converted: tuple[str, str]
) -> None:
    async with open_session(settings, clock, _lookups().sources()) as session:
        await _extracted(session)
        first = await session.call("references_list", project="demo", limit=3)
        assert len(first["data"]["items"]) == 3 and first["data"]["next_after"] == 3
        rest = await session.call("references_list", project="demo", after=3, limit=100)
        assert first["data"]["total"] == len(rest["data"]["items"]) + 3
        too_big = await session.call("references_list", project="demo", limit=101)
        assert _fields(too_big) == ["limit"]
        bad = await session.call("references_list", project="demo", state="maybe")
        assert _fields(bad) == ["state"]
        only = await session.call("references_list", project="demo", state="unconfirmed")
        assert all(i["state"] == "unconfirmed" for i in only["data"]["items"])


@pytest.mark.anyio
async def test_reference_decide_agent_confirm_refused(
    settings: Settings, project: Project, clock: FixedClock, corpus: None
) -> None:
    lookups = Lookups(openalex=[oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501")])
    fetched_document(
        project,
        promoted_works(project)[0],
        bib_html(["B. Lee. Efficient reed transformers v2. Reed Conference, 2021."], ["x"]),
    )
    run_convert(project, make_registry())
    async with open_session(settings, clock, lookups.sources()) as session:
        await _extracted(session)
        listed = await session.call("references_list", project="demo", state="unconfirmed")
        [item, *_] = listed["data"]["items"]
        args = {
            "extraction_id": item["extraction_id"],
            "ordinal": item["ordinal"],
            "rationale": "same title and year",
            "quotes": ["Efficient reed transformers v2", "Efficient Reed Transformers"],
            **AGENT,
        }
        before = _count(project)
        refused = await session.call("reference_decide", project="demo", decision="confirm", **args)
        assert _fields(refused) == ["decision"]
        wrong = await session.call("reference_decide", project="demo", decision="maybe", **args)
        assert _fields(wrong) == ["decision"]
        one_quote = {**args, "quotes": ["Efficient reed transformers v2"]}
        short = await session.call(
            "reference_decide", project="demo", decision="propose-confirm", **one_quote
        )
        assert _fields(short) == ["quotes"]
        assert _count(project) == before
        proposed = await session.call(
            "reference_decide", project="demo", decision="propose-confirm", **args
        )
        assert proposed["ok"] is True, proposed
    assert _count(project) == before + 1


@pytest.mark.anyio
async def test_snowball_round_defaults_to_dry_run_and_writes_nothing(
    settings: Settings,
    project: Project,
    agent: Actor,
    clock: FixedClock,
    converted: tuple[str, str],
) -> None:
    _amend(project, agent, PLAN)
    async with open_session(settings, clock, _lookups().sources()) as session:
        await _extracted(session)
        before = _count(project)
        dry = await session.call("snowball_round", project="demo", direction="backward", **AGENT)
        assert dry["ok"] is True, dry
        assert dry["data"]["dry_run"] is True and dry["data"]["round_id"] is None
        assert dry["data"]["candidates"] and dry["data"]["state"]["allowed"] is True
        assert _count(project) == before
        bad = await session.call("snowball_round", project="demo", direction="sideways", **AGENT)
        assert _fields(bad) == ["direction"]
        real = await session.call(
            "snowball_round", project="demo", direction="backward", dry_run=False, **AGENT
        )
        assert real["ok"] is True and real["data"]["round_id"] is not None, real
        compared = await session.call(
            "snowball_compare", project="demo", round_id=real["data"]["round_id"]
        )
        assert compared["ok"] is True, compared
        assert set(compared["data"]) >= {"document_only", "metadata_only", "both"}
        unknown = await session.call("snowball_compare", project="demo", round_id="snw_nope")
        assert unknown["ok"] is False


@pytest.mark.anyio
@pytest.mark.parametrize("tool", NEW_TOOLS)
async def test_pass_session_refused_for_each_tool(
    tool: str,
    settings: Settings,
    project: Project,
    agent: Actor,
    human: Actor,
    clock: FixedClock,
    mock_sources: SourcesFor,
) -> None:
    _setup(project, agent, human, mock_sources)
    _draw(project)
    args: dict[str, Any] = {
        "references_extract": {**AGENT},
        "references_status": {},
        "references_list": {},
        "reference_decide": {
            "extraction_id": "rex_01JZ9Q3K5M7N8P0R2S4T6V8W1Z",
            "ordinal": 1,
            "decision": "propose-confirm",
            "rationale": "r",
            "quotes": ["a", "b"],
            **AGENT,
        },
        "snowball_round": {"direction": "backward", **AGENT},
        "snowball_compare": {"round_id": "snw_01JZ9Q3K5M7N8P0R2S4T6V8W1Z"},
    }[tool]
    async with open_session(settings, clock, {}) as screener:
        joined = await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
        assert joined["ok"] is True, joined
        joined_events = _count(project)
        body = await screener.call(tool, project="demo", **args)
    assert _fields(body) == ["session"]
    assert _count(project) == joined_events


@pytest.mark.anyio
async def test_mcp_views_hide_seed_route_and_held_out(
    settings: Settings, project: Project, agent: Actor, clock: FixedClock, corpus: None
) -> None:
    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held.work_id is not None and held.doi is not None
    work_a = promoted_works(project)[0]
    entries = [f"A. Zhou. A held paper. Journal of Tests, 2020. doi:{held.doi}.", *ENTRIES_A[1:]]
    fetched_document(project, work_a, bib_html(entries, BODY_A))
    run_convert(project, make_registry())
    _amend(project, agent, PLAN)
    forms = {held.seed_id, held.work_id, held.doi}
    async with open_session(settings, clock, _lookups().sources()) as session:
        bodies = [await _extracted(session)]
        bodies.append(await session.call("references_status", project="demo"))
        bodies.append(await session.call("references_list", project="demo", limit=100))
        bodies.append(
            await session.call("snowball_round", project="demo", direction="backward", **AGENT)
        )
    text = json.dumps(bodies)
    assert _leaks(text, forms) == []
    assert "found_by" not in text


@pytest.mark.anyio
async def test_held_out_work_matched_by_search_is_absent_from_every_view(
    settings: Settings,
    project: Project,
    agent: Actor,
    clock: FixedClock,
    corpus: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-20 with `seed.work_id` unset: the held-out seed is matched to its corpus work by DOI
    only. The work is cited (by DOI) from one document and has a document of its own."""
    from factory.services import seeds as seeds_service
    from factory.services.search import get_work

    real = seeds_service._load_seeds
    monkeypatch.setattr(
        seeds_service,
        "_load_seeds",
        lambda p: [s.model_copy(update={"work_id": None}) for s in real(p)],
    )
    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held.work_id is None and held.doi is not None
    [target] = seeds_service.held_out_work_ids(project)
    work = get_work(project, target)
    assert work is not None
    others = [w for w in promoted_works(project) if w != target]
    entries = [f"A. Zhou. A held paper. Journal of Tests, 2020. doi:{held.doi}.", *ENTRIES_A[1:]]
    fetched_document(project, others[0], bib_html(entries, BODY_A))
    fetched_document(project, target, bib_html(ENTRIES_B, BODY_B))
    run_convert(project, make_registry())
    _amend(project, agent, PLAN)
    async with open_session(settings, clock, _lookups().sources()) as session:
        bodies = [await _extracted(session)]
        bodies.append(await session.call("references_status", project="demo"))
        listed = await session.call("references_list", project="demo", limit=100)
        bodies.append(listed)
        bodies.append(
            await session.call("snowball_round", project="demo", direction="backward", **AGENT)
        )
        real_round = await session.call(
            "snowball_round", project="demo", direction="backward", dry_run=False, **AGENT
        )
        assert real_round["ok"] is True, real_round
        bodies.append(real_round)
        bodies.append(
            await session.call(
                "snowball_compare", project="demo", round_id=real_round["data"]["round_id"]
            )
        )
    text = json.dumps(bodies)
    assert _leaks(text, {target, held.doi, held.seed_id}) == []
    at = text.find("[withheld]")
    assert at < 0, text[max(at - 300, 0) : at + 100]
    at = text.find(work.title)
    assert at < 0, (work.title, text[max(at - 200, 0) : at + 100])
    assert all(i["work_id"] != target for i in listed["data"]["items"])
    masked = [
        i for i in listed["data"]["items"] if i["ordinal"] == 1 and i["citing_work"] == others[0]
    ]
    assert [(i["state"], i["work_id"], i["doi"]) for i in masked] == [("unresolved", None, None)]


# --- The held-out mask (final review 2 and 8) ---

BARE_ENTRY = "Zhou, 2020."
"""An entry from which nothing but a year parses: a genuine `no-identifier-no-title` link."""


@pytest.fixture
def masked_world(
    project: Project, agent: Actor, corpus: None, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str, str]:
    """(citing work, held-out corpus work, held DOI): the first entry cites the held-out work by
    DOI and the last is the genuine bare entry. The held-out work has a document of its own."""
    from factory.services import seeds as seeds_service

    real = seeds_service._load_seeds
    monkeypatch.setattr(
        seeds_service,
        "_load_seeds",
        lambda p: [s.model_copy(update={"work_id": None}) for s in real(p)],
    )
    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held.doi is not None
    [target] = seeds_service.held_out_work_ids(project)
    citing = next(w for w in promoted_works(project) if w != target)
    entries = [
        f"A. Zhou. A held paper. Journal of Tests, 2020. doi:{held.doi}.",
        *ENTRIES_A[1:],
        BARE_ENTRY,
    ]
    fetched_document(project, citing, bib_html(entries, BODY_A))
    fetched_document(project, target, bib_html(ENTRIES_B, BODY_B))
    run_convert(project, make_registry())
    _amend(project, agent, PLAN)
    return citing, target, held.doi


def _shape(item: dict[str, Any]) -> dict[str, Any]:
    """What a reader can tell about a link: every field but the entry's position and the fields
    the document shows anyway, nulls as nulls."""
    kept = set(item) - {"extraction_id", "citing_work", "ordinal", "anchor", "label"}
    return {key: item[key] for key in kept - {"first_author", "year"}}


@pytest.mark.anyio
async def test_masked_entry_reads_as_a_genuine_unresolved_link(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    masked_world: tuple[str, str, str],
) -> None:
    citing, _, _ = masked_world
    async with open_session(settings, clock, _lookups().sources()) as session:
        await _extracted(session)
        listed = await session.call("references_list", project="demo", work_id=citing, limit=100)
    items = listed["data"]["items"]
    masked, genuine = items[0], items[-1]
    assert genuine["reason"] == "no-identifier-no-title"
    assert _shape(masked) == _shape(genuine)


@pytest.mark.anyio
async def test_agent_trace_applies_the_mask_on_both_paths(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    masked_world: tuple[str, str, str],
) -> None:
    from factory.services.search import get_work

    citing, target, _ = masked_world
    work = get_work(project, target)
    assert work is not None
    async with open_session(settings, clock, _lookups().sources()) as session:
        await _extracted(session)
        listed = await session.call("references_list", project="demo", work_id=citing, limit=100)
        rex = listed["data"]["items"][0]["extraction_id"]
        forward = await session.call("trace", project="demo", ref=rex, direction="forward")
        conversion = _conversion_of(project, rex)
        entry = await session.call(
            "trace", project="demo", ref=f"{conversion}/b1", direction="forward"
        )
        cited = await session.call("trace", project="demo", ref=target, direction="back")
    assert forward["ok"] and entry["ok"] and cited["ok"]
    for body in (forward, entry):
        text = json.dumps(body)
        assert _leaks(text, {target}) == [] and work.title not in text
    assert f"{conversion}/b1" not in json.dumps(forward)
    assert f"{conversion}/b2" in json.dumps(forward)  # a link the list shows stays traced
    assert f"{conversion}/b1" not in json.dumps(cited)


def _conversion_of(project: Project, rex: str) -> str:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT conversion_id FROM reference_extractions WHERE extraction_id = :x"),
            {"x": rex},
        ).scalar_one()
    return str(row)


@pytest.mark.anyio
async def test_agent_extract_states_agree_with_the_list(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    masked_world: tuple[str, str, str],
) -> None:
    citing, _, _ = masked_world
    async with open_session(settings, clock, _lookups().sources()) as session:
        extracted = await _extracted(session)
        listed = await session.call("references_list", project="demo", work_id=citing, limit=100)
    [states] = [e["states"] for e in extracted["data"]["extractions"] if e["work_id"] == citing]
    shown: dict[str, int] = {}
    for item in listed["data"]["items"]:
        shown[item["state"]] = shown.get(item["state"], 0) + 1
    assert {k: v for k, v in states.items() if v} == shown


@pytest.mark.anyio
async def test_document_read_keeps_the_scrub_until_decision_78_is_settled(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    masked_world: tuple[str, str, str],
) -> None:
    """Decided entry 37 item 9 has tools withhold seed identifiers, so the scrub stays; the
    placeholder this leaves in document text is the open question of decision 78."""
    citing, _, doi = masked_world
    async with open_session(settings, clock, _lookups().sources()) as session:
        body = await session.call("document_read", project="demo", work_id=citing, anchor="b1")
    assert body["ok"] is True, body
    assert _leaks(json.dumps(body), {doi}) == []
    assert "[withheld]" in body["data"]["segments"][0]["text"]


# --- Probing a masked entry by ordinal (re-review 1) ---


def _ordinal_free(body: dict[str, Any], ordinal: int, anchor: str) -> str:
    """The exact response with only the ordinal or anchor the caller named taken out."""
    text_ = json.dumps(body, sort_keys=True)
    return re.sub(rf"(:{ordinal}\b|\b{anchor}\b)", "<entry>", text_)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "decision", ["propose-confirm", "propose-reject", "confirm", "reject", "clear"]
)
async def test_a_masked_entry_refuses_a_decision_as_a_genuine_unresolved_one(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    masked_world: tuple[str, str, str],
    decision: str,
) -> None:
    citing, _, _ = masked_world
    async with open_session(settings, clock, _lookups().sources()) as session:
        await _extracted(session)
        listed = await session.call("references_list", project="demo", work_id=citing, limit=100)
        items = listed["data"]["items"]
        masked, genuine = items[0], items[-1]
        rex = masked["extraction_id"]
        before = _count(project)
        bodies = [
            await session.call(
                "reference_decide",
                project="demo",
                extraction_id=rex,
                ordinal=item["ordinal"],
                decision=decision,
                rationale="Same paper.",
                quotes=["x", "y"],
                **AGENT,
            )
            for item in (masked, genuine)
        ]
    assert bodies[0]["ok"] is False and _count(project) == before
    assert _ordinal_free(bodies[0], masked["ordinal"], "b1") == _ordinal_free(
        bodies[1], genuine["ordinal"], genuine["anchor"]
    )


@pytest.mark.anyio
async def test_naming_a_held_out_work_in_a_decision_marks_nothing(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    masked_world: tuple[str, str, str],
) -> None:
    """The refusal does not echo the work, so the scrub cannot flag it as held out."""
    citing, target, _ = masked_world
    async with open_session(settings, clock, _lookups().sources()) as session:
        await _extracted(session)
        listed = await session.call("references_list", project="demo", work_id=citing, limit=100)
        item = listed["data"]["items"][-1]
        body = await session.call(
            "reference_decide",
            project="demo",
            extraction_id=item["extraction_id"],
            ordinal=item["ordinal"],
            decision="propose-confirm",
            rationale="Same paper.",
            quotes=["x", "y"],
            work_id=target,
            **AGENT,
        )
    assert body["ok"] is False and "[withheld]" not in json.dumps(body)


@pytest.mark.anyio
@pytest.mark.parametrize("direction", ["forward", "back"])
async def test_a_masked_anchor_traces_as_a_genuine_unresolved_one(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    masked_world: tuple[str, str, str],
    direction: str,
) -> None:
    citing, _, _ = masked_world
    async with open_session(settings, clock, _lookups().sources()) as session:
        await _extracted(session)
        listed = await session.call("references_list", project="demo", work_id=citing, limit=100)
        items = listed["data"]["items"]
        rex = items[0]["extraction_id"]
        conversion = _conversion_of(project, rex)
        masked = await session.call(
            "trace", project="demo", ref=f"{conversion}/b1", direction=direction
        )
        genuine = await session.call(
            "trace", project="demo", ref=f"{conversion}/{items[-1]['anchor']}", direction=direction
        )
        entries = [
            await session.call("trace", project="demo", ref=f"{rex}:{i['ordinal']}")
            for i in (items[0], items[-1])
        ]
    assert masked["ok"] is True
    assert _ordinal_free(masked, 0, "b1") == _ordinal_free(genuine, 0, items[-1]["anchor"])
    assert entries[0] == entries[1]

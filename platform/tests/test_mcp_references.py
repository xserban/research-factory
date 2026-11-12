"""The reference and snowball MCP tools: pass sessions refused, agents only propose, dry run by
default, no seed id, stated identifier or seed route, and a held-out seed's work read as any
corpus work (slice 3a, ruling 3; R-20; decisions 37 item 9 and 81)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from mcp import Client
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp.conventions import WITHHELD
from factory.mcp.server import _held_out_tokens, build_server
from factory.model.work_ids import work_id
from factory.services.context import Project
from factory.services.prisma_update import prisma_update
from factory.services.seeds import SeedRole, all_seeds
from tests.document_helpers import fetched_document, make_registry, promoted_works, run_convert
from tests.helpers import SourcesFor, _leaks, _setup, open_session
from tests.references_service_helpers import Lookups, bib_html, oa_item
from tests.screening_helpers import _draw
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
LAYER_TOOLS = ["reference_layer_next", "reference_layer_record", "reference_layer_status"]


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
    start = names.index(NEW_TOOLS[0])  # tools of later plans register after these
    # The reference-layer plan (1962194) registers its three tools after references_status.
    block = [*NEW_TOOLS[:2], *LAYER_TOOLS, *NEW_TOOLS[2:]]
    assert names[start : start + len(block)] == block
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
async def test_mcp_views_hide_seed_route_and_seed_identifiers(
    settings: Settings, project: Project, agent: Actor, clock: FixedClock, corpus: None
) -> None:
    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held.work_id is not None and held.doi is not None
    work_a = promoted_works(project)[0]
    entries = [f"A. Zhou. A held paper. Journal of Tests, 2020. doi:{held.doi}.", *ENTRIES_A[1:]]
    fetched_document(project, work_a, bib_html(entries, BODY_A))
    run_convert(project, make_registry())
    _amend(project, agent, PLAN)
    forms = {held.seed_id, held.doi}
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


# --- A held-out seed's work reads as any corpus work (decisions 37 item 9, 43 and 81) ---


@dataclass(frozen=True)
class SeededWorld:
    """`citing`'s list cites `target`, a held-out seed's work matched by search alone, by DOI
    (`b1`) and `ordinary`, any other corpus work, by DOI (`b2`). `target` has a document of its
    own."""

    citing: str
    target: str
    ordinary: str
    seed_id: str
    doi: str
    title: str


@pytest.fixture
def seeded_world(
    project: Project, agent: Actor, corpus: None, monkeypatch: pytest.MonkeyPatch
) -> SeededWorld:
    from factory.services import seeds as seeds_service
    from factory.services.search import get_work

    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held.work_id is not None and held.doi is not None
    target = held.work_id
    real = seeds_service._load_seeds
    monkeypatch.setattr(
        seeds_service,
        "_load_seeds",
        lambda p: [s.model_copy(update={"work_id": None}) for s in real(p)],
    )
    citing, ordinary = [w for w in promoted_works(project) if w != target][:2]
    held_work, other = get_work(project, target), get_work(project, ordinary)
    assert held_work is not None and other is not None
    entries = [
        f"A. Zhou. A cited paper. Journal of Tests, 2020. doi:{held.doi}.",
        f"A. Zhou. A cited paper. Journal of Tests, 2020. doi:{other.identifiers.doi}.",
        *ENTRIES_A[1:],
    ]
    fetched_document(project, citing, bib_html(entries, BODY_A))
    fetched_document(project, target, bib_html(ENTRIES_B, BODY_B))
    run_convert(project, make_registry())
    _amend(project, agent, PLAN)
    return SeededWorld(citing, target, ordinary, held.seed_id, held.doi, held_work.title)


def _shape(item: dict[str, Any]) -> dict[str, Any]:
    """What a reader can tell about a link apart from which entry and which work it is."""
    named = {"extraction_id", "citing_work", "ordinal", "anchor", "work_id", "base_work_id", "doi"}
    return {key: value for key, value in item.items() if key not in named}


def _conversion_of(project: Project, rex: str) -> str:
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT conversion_id FROM reference_extractions WHERE extraction_id = :x"),
            {"x": rex},
        ).scalar_one()
    return str(row)


def _ordinal_free(body: dict[str, Any], ordinal: int, anchor: str) -> str:
    """The exact response with only the ordinal or anchor the caller named taken out."""
    text_ = json.dumps(body, sort_keys=True)
    return re.sub(rf"(:{ordinal}\b|\b{anchor}\b)", "<entry>", text_)


@pytest.mark.anyio
async def test_a_held_out_work_reads_as_any_work_in_every_reference_view(
    settings: Settings, project: Project, clock: FixedClock, seeded_world: SeededWorld
) -> None:
    world = seeded_world
    async with open_session(settings, clock, _lookups().sources()) as session:
        extracted = await _extracted(session)
        status = await session.call("references_status", project="demo")
        listed = await session.call("references_list", project="demo", limit=100)
        dry = await session.call("snowball_round", project="demo", direction="backward", **AGENT)
        real = await session.call(
            "snowball_round", project="demo", direction="backward", dry_run=False, **AGENT
        )
        assert real["ok"] is True, real
        compared = await session.call(
            "snowball_compare", project="demo", round_id=real["data"]["round_id"]
        )
    items = listed["data"]["items"]
    # Its own extraction is counted and listed like the others.
    assert world.target in {e["work_id"] for e in extracted["data"]["extractions"]}
    assert world.target in {i["citing_work"] for i in items}
    assert status["data"]["extractions"] == len(extracted["data"]["extractions"])
    assert status["data"]["entries"] == listed["data"]["total"] == len(items)
    for state in ("resolved", "unconfirmed", "ambiguous", "unresolved"):
        assert status["data"][state] == sum(i["state"] == state for i in items)
    # The link to it is a link like the one to any other corpus work.
    cited = [i for i in items if i["citing_work"] == world.citing]
    assert (cited[0]["work_id"], cited[1]["work_id"]) == (world.target, world.ordinary)
    assert _shape(cited[0]) == _shape(cited[1])
    # A round takes it as a source, and a comparison counts the link to it.
    assert world.target in dry["data"]["sources"] and world.target in real["data"]["sources"]
    assert world.target in compared["data"]["document_only"] + compared["data"]["both"]
    bodies = json.dumps([extracted, status, listed, dry, real, compared])
    assert _leaks(bodies, {world.seed_id, world.doi}) == []
    assert "found_by" not in bodies


@pytest.mark.anyio
async def test_seed_identifiers_stay_withheld_where_an_entry_states_them(
    settings: Settings, project: Project, clock: FixedClock, seeded_world: SeededWorld
) -> None:
    """The stated DOI is scrubbed, as decision 37 item 9 asks. The placeholder beside the link to
    the work is the residual marking of decisions 78 and 81; this pins it until they are ruled."""
    world = seeded_world
    async with open_session(settings, clock, _lookups().sources()) as session:
        await _extracted(session)
        listed = await session.call(
            "references_list", project="demo", work_id=world.citing, limit=100
        )
    assert listed["data"]["items"][0]["doi"] == WITHHELD
    assert listed["data"]["items"][1]["doi"] != WITHHELD


@pytest.mark.anyio
async def test_agent_trace_walks_a_held_out_link_as_any_link(
    settings: Settings, project: Project, clock: FixedClock, seeded_world: SeededWorld
) -> None:
    world = seeded_world
    async with open_session(settings, clock, _lookups().sources()) as session:
        await _extracted(session)
        listed = await session.call(
            "references_list", project="demo", work_id=world.citing, limit=100
        )
        rex = listed["data"]["items"][0]["extraction_id"]
        conversion = _conversion_of(project, rex)
        forward = await session.call("trace", project="demo", ref=rex, direction="forward")
        held = await session.call(
            "trace", project="demo", ref=f"{conversion}/b1", direction="forward"
        )
        ordinary = await session.call(
            "trace", project="demo", ref=f"{conversion}/b2", direction="forward"
        )
        cited = await session.call("trace", project="demo", ref=world.target, direction="back")
    assert forward["ok"] and held["ok"] and ordinary["ok"] and cited["ok"]
    assert f"{conversion}/b1" in json.dumps(forward)
    assert f"{conversion}/b2" in json.dumps(forward)
    assert world.target in json.dumps(held) and world.title in json.dumps(held)
    assert world.ordinary in json.dumps(ordinary)
    assert f"{conversion}/b1" in json.dumps(cited)
    assert _leaks(json.dumps([forward, held, cited]), {world.seed_id, world.doi}) == []


@pytest.mark.anyio
async def test_agent_extract_states_agree_with_the_list(
    settings: Settings, project: Project, clock: FixedClock, seeded_world: SeededWorld
) -> None:
    citing = seeded_world.citing
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
    settings: Settings, project: Project, clock: FixedClock, seeded_world: SeededWorld
) -> None:
    """Decided entry 37 item 9 has tools withhold seed identifiers, so the scrub stays; the
    placeholder this leaves in document text is the open question of decision 78."""
    world = seeded_world
    async with open_session(settings, clock, _lookups().sources()) as session:
        body = await session.call(
            "document_read", project="demo", work_id=world.citing, anchor="b1"
        )
    assert body["ok"] is True, body
    assert _leaks(json.dumps(body), {world.doi}) == []
    assert WITHHELD in body["data"]["segments"][0]["text"]


@pytest.mark.anyio
async def test_document_read_names_a_seed_work_by_its_id(
    settings: Settings, project: Project, clock: FixedClock, corpus: None
) -> None:
    """`seed.work_id` set, the common case: 37 item 9 does not withhold the `rf:` id."""
    held = _held(project)
    fetched_document(project, held.work_id, bib_html(ENTRIES_B, BODY_B))
    run_convert(project, make_registry())
    async with open_session(settings, clock, _lookups().sources()) as session:
        body = await session.call("document_read", project="demo", work_id=held.work_id)
    assert body["ok"] is True, body
    assert body["data"]["work_id"] == held.work_id


@pytest.mark.anyio
@pytest.mark.parametrize(
    "decision", ["propose-confirm", "propose-reject", "confirm", "reject", "clear"]
)
async def test_a_decision_on_a_held_out_link_refuses_as_on_any_link(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    seeded_world: SeededWorld,
    decision: str,
) -> None:
    citing = seeded_world.citing
    async with open_session(settings, clock, _lookups().sources()) as session:
        await _extracted(session)
        listed = await session.call("references_list", project="demo", work_id=citing, limit=100)
        items = listed["data"]["items"]
        before = _count(project)
        bodies = [
            await session.call(
                "reference_decide",
                project="demo",
                extraction_id=item["extraction_id"],
                ordinal=item["ordinal"],
                decision=decision,
                rationale="Same paper.",
                quotes=["x", "y"],
                **AGENT,
            )
            for item in items[:2]
        ]
    assert bodies[0]["ok"] is False and _count(project) == before
    assert _ordinal_free(bodies[0], 1, "b1") == _ordinal_free(bodies[1], 2, "b2")


@pytest.mark.anyio
async def test_naming_a_held_out_work_in_a_decision_marks_nothing(
    settings: Settings, project: Project, clock: FixedClock, seeded_world: SeededWorld
) -> None:
    world = seeded_world
    async with open_session(settings, clock, _lookups().sources()) as session:
        await _extracted(session)
        listed = await session.call(
            "references_list", project="demo", work_id=world.citing, limit=100
        )
        item = listed["data"]["items"][-1]
        bodies = [
            await session.call(
                "reference_decide",
                project="demo",
                extraction_id=item["extraction_id"],
                ordinal=item["ordinal"],
                decision="propose-confirm",
                rationale="Same paper.",
                quotes=["x", "y"],
                work_id=work,
                **AGENT,
            )
            for work in (world.target, world.ordinary)
        ]
    assert bodies[0] == bodies[1] and bodies[0]["ok"] is False
    assert WITHHELD not in json.dumps(bodies)


def _held(project: Project) -> Any:
    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held.work_id is not None and held.doi is not None
    return held


def test_the_scrub_holds_seed_ids_and_identifiers_and_at_most_the_seeds_own_work(
    project: Project, corpus: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`include_work_ids` adds `seed.work_id` alone; a work matched by search is never a token."""
    from factory.services import seeds as seeds_service

    held = _held(project)
    plain = _held_out_tokens(project, include_work_ids=False)
    assert {held.seed_id, held.doi} <= plain and held.work_id not in plain
    assert _held_out_tokens(project, include_work_ids=True) == plain | {
        s.work_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT and s.work_id
    }
    real = seeds_service._load_seeds
    monkeypatch.setattr(
        seeds_service,
        "_load_seeds",
        lambda p: [s.model_copy(update={"work_id": None}) for s in real(p)],
    )
    assert held.work_id not in _held_out_tokens(project, include_work_ids=True)


@pytest.mark.anyio
async def test_status_tools_name_a_held_out_work_as_any_work(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    corpus: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `[withheld]` in place of one `rf:` id among the others would mark the seed."""
    from factory.mcp import server as mcp_server
    from factory.services import prisma_update as prisma_update_service

    target = _held(project).work_id
    flow = prisma_update(project).model_copy(update={"changed_previous": (target,)})
    # report_prisma reads the update through services/agent_view.py since a23f2eb.
    monkeypatch.setattr(prisma_update_service, "prisma_update", lambda *_, **__: flow)
    monkeypatch.setattr(
        mcp_server.coverage_service,
        "agent_coverage",
        lambda *_: SimpleNamespace(model_dump=lambda mode: {"excluded": [target]}),
    )
    monkeypatch.setattr(
        mcp_server.inbox_service,
        "resolve_links",
        lambda *_, **__: [
            SimpleNamespace(item_id="i", status=None, work_id=target, run_id=None, issues=[])
        ],
    )
    async with open_session(settings, clock, _lookups().sources()) as session:
        bodies = {
            "fulltext_status": await session.call("fulltext_status", project="demo"),
            "report_prisma": await session.call("report_prisma", project="demo", update="last"),
            "import_coverage": await session.call(
                "import_coverage", project="demo", import_id="imp_x"
            ),
            "inbox_resolve": await session.call("inbox_resolve", project="demo"),
        }
    for tool, body in bodies.items():
        assert body["ok"] is True, (tool, body)
        assert target in json.dumps(body), tool

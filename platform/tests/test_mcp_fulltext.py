"""The full-text MCP tools: `fulltext_fetch` (an agent act) and `fulltext_status` (read-only).

Routes are stubs supplied through `build_server(fulltext_routes=...)`, so no test touches the
network. A refused call writes nothing: the event log is compared before and after.
"""

import json
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from factory.clock import FixedClock
from factory.config import Settings
from factory.mcp.server import build_server
from factory.model.fulltext import AttemptOutcome, Route
from factory.services.context import Project
from factory.sources.fulltext.base import RouteResult, not_retrieved

# The `corpus` fixture (promoted works) is registered by importing its module's fixture.
from tests.fulltext_helpers import _events, _promoted, corpus  # noqa: F401
from tests.helpers import _of_type
from tests.route_helpers import StubRoute, always, retrieved

AGENT = {"role": "screener-a", "model": "claude-opus-5-5", "skill": "rf-screen"}
# by_route counts every Route; lab-library is the lab library route (c52130a).
ROUTE_NAMES = [
    "arxiv-html",
    "arxiv-source",
    "pmc-jats",
    "oa-pdf",
    "researcher-supplied",
    "lab-library",
]


def _stubs(retrieve: str) -> dict[Route, StubRoute]:
    """arXiv HTML retrieves for the work `retrieve`; the other routes never retrieve."""

    def html(work: Any) -> RouteResult:
        if work.id == retrieve:
            return retrieved(Route.ARXIV_HTML, b"the retrieved work")
        return not_retrieved(Route.ARXIV_HTML, AttemptOutcome.NOT_AVAILABLE, "no html")

    return {
        Route.ARXIV_HTML: StubRoute(Route.ARXIV_HTML, html),
        Route.ARXIV_SOURCE: StubRoute(
            Route.ARXIV_SOURCE,
            always(not_retrieved(Route.ARXIV_SOURCE, AttemptOutcome.NOT_AVAILABLE, "no src")),
        ),
        Route.OA_PDF: StubRoute(
            Route.OA_PDF, always(not_retrieved(Route.OA_PDF, AttemptOutcome.FAILED, "no pdf"))
        ),
    }


async def _calls(
    settings: Settings,
    clock: FixedClock,
    routes: dict[Route, StubRoute],
    *calls: tuple[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Each call's structured body, in order, from one server session."""
    server = build_server(settings, clock=clock, fulltext_routes=lambda: routes)
    bodies: list[dict[str, Any]] = []
    async with Client(server) as client:
        for name, args in calls:
            res = await client.call_tool(name, args)
            bodies.append(_body(res))
    return bodies


def _body(res: CallToolResult) -> dict[str, Any]:
    block = res.content[0]
    assert isinstance(block, TextContent)
    body: dict[str, Any] = json.loads(block.text)
    return body


def _fetch_args(**extra: Any) -> dict[str, Any]:
    return {"project": "demo", **AGENT, **extra}


@pytest.mark.usefixtures("corpus")
@pytest.mark.anyio
async def test_mcp_fetch_is_an_agent_act_with_an_input_blob(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    work = _promoted(project)[0]
    routes = _stubs(work)

    [body] = await _calls(
        settings,
        clock,
        routes,
        ("fulltext_fetch", _fetch_args(work_ids=[work], routes=["arxiv-html"])),
    )

    assert body["ok"] is True, body
    [fetched] = body["data"]["works"]
    assert set(fetched) == {"work_id", "attempts", "documents", "status"}
    assert fetched["work_id"] == work and fetched["status"] == "retrieved"
    assert len(fetched["documents"]) == 1
    assert routes[Route.ARXIV_HTML].calls == [work]
    assert routes[Route.ARXIV_SOURCE].calls == []
    [started] = _of_type(project, "fulltext.fetch_started")
    assert started.actor.kind == "agent"
    assert started.actor.id == "screener-a"
    assert started.actor.model == "claude-opus-5-5"
    assert started.input_blob is not None
    assert started.payload["routes"] == ["arxiv-html"]


@pytest.mark.usefixtures("corpus")
@pytest.mark.anyio
async def test_mcp_fetch_validation_errors_write_nothing(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    unpromoted = "rf:nope-00000000"
    bad_calls: list[tuple[dict[str, Any], str]] = [
        (_fetch_args(limit=0), "limit"),
        (_fetch_args(work_ids=[unpromoted]), "work_ids"),
        (_fetch_args(model=""), "model"),
        (_fetch_args(skill="no-such-skill"), "skill"),
        (_fetch_args(routes=["oa-pdf", "bogus"]), "routes.1"),
    ]
    before = len(_events(project))
    routes = _stubs(_promoted(project)[0])

    bodies = await _calls(
        settings, clock, routes, *(("fulltext_fetch", args) for args, _ in bad_calls)
    )

    for body, (_, field) in zip(bodies, bad_calls, strict=True):
        assert body["ok"] is False, body
        assert field in [error["field"] for error in body["errors"]], body
    assert len(_events(project)) == before
    assert all(stub.calls == [] for stub in routes.values())


@pytest.mark.usefixtures("corpus")
@pytest.mark.anyio
async def test_mcp_unknown_route_rejected(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    before = len(_events(project))
    routes = _stubs(_promoted(project)[0])

    unknown, supplied = await _calls(
        settings,
        clock,
        routes,
        ("fulltext_fetch", _fetch_args(routes=["arxiv-htm"])),
        ("fulltext_fetch", _fetch_args(routes=["researcher-supplied"])),
    )

    assert unknown == {
        "ok": False,
        "errors": [
            {
                "field": "routes.0",
                "reason": "must be one of: arxiv-html, arxiv-source, pmc-jats, oa-pdf",
            }
        ],
    }
    assert supplied == {
        "ok": False,
        "errors": [
            {
                "field": "routes.0",
                "reason": "a researcher-supplied route is imported, not fetched",
            }
        ],
    }
    assert len(_events(project)) == before


@pytest.mark.usefixtures("corpus")
@pytest.mark.anyio
async def test_mcp_status_shape(settings: Settings, project: Project, clock: FixedClock) -> None:
    promoted = _promoted(project)
    retrieved_work = promoted[0]
    routes = _stubs(retrieved_work)

    fetched, status, named = await _calls(
        settings,
        clock,
        routes,
        ("fulltext_fetch", _fetch_args(work_ids=[retrieved_work])),
        ("fulltext_status", {"project": "demo"}),
        ("fulltext_status", {"project": "demo", "work_ids": [promoted[1]]}),
    )

    assert fetched["ok"] is True, fetched
    assert status["ok"] is True
    data = status["data"]
    assert set(data) == {
        "promoted",
        "unsought",
        "retrieved",
        "not_retrieved",
        "by_route",
        "works",
        "changed_sources",
    }
    assert data["promoted"] == len(promoted)
    assert data["retrieved"] == 1
    assert set(data["by_route"]) == set(ROUTE_NAMES)
    assert data["by_route"]["arxiv-html"] == 1
    for entry in data["works"]:
        assert set(entry) == {"work_id", "state", "documents", "reasons"}
    by_id = {entry["work_id"]: entry for entry in data["works"]}
    assert by_id[retrieved_work]["state"] == "retrieved"
    assert by_id[promoted[1]]["state"] == "unsought"

    assert named["ok"] is True
    assert [entry["work_id"] for entry in named["data"]["works"]] == [promoted[1]]


@pytest.mark.usefixtures("corpus")
@pytest.mark.anyio
async def test_mcp_status_refuses_an_unpromoted_work(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    [body] = await _calls(
        settings,
        clock,
        _stubs(_promoted(project)[0]),
        ("fulltext_status", {"project": "demo", "work_ids": ["rf:nope-00000000"]}),
    )
    assert body == {
        "ok": False,
        "errors": [
            {
                "field": "work_ids",
                "reason": "rf:nope-00000000: not promoted at title/abstract",
            }
        ],
    }

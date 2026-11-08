"""The live dashboard: state builder, page, server and export (slice 8, I1; not yet run)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.decisions import DecisionItem, DecisionLevel
from factory.services import dashboard as dashboard_service
from factory.services import dashboard_server
from factory.services import decisions as decisions_service
from factory.services.context import Project
from factory.services.dashboard_page import render_page
from factory.services.seeds import SeedRole, all_seeds
from tests.helpers import SourcesFor, _setup
from tests.screening_helpers import _calibrate, _partial_corpus, _screen_ordinary

PANELS = (
    "meta",
    "decisions",
    "protocol",
    "question",
    "press",
    "probes",
    "search",
    "dedup",
    "screening",
    "screening_live",
    "extraction",
    "cost",
    "progress",
)


def _suggest(project: Project, agent: Actor, **over: object) -> str:
    args: dict[str, object] = {
        "level": DecisionLevel.PROTOCOL,
        "subject": "exclusions",
        "explanation": "The exclusions set what leaves the corpus.",
        "items": (
            DecisionItem(item_id="I01", text="Exclude preprints", grounds=("prb_1",)),
            DecisionItem(item_id="I02", text="Keep preprints"),
        ),
    }
    args.update(over)
    return decisions_service.suggest(project, agent, **args)  # type: ignore[arg-type]


def _events(project: Project) -> int:
    return len(list(read_all(project.paths.events_dir, project.catalog)))


def test_empty_project_gives_every_panel_and_is_json(project: Project) -> None:
    state = dashboard_service.dashboard_state(project)
    json.dumps(state)
    assert all(panel in state for panel in PANELS)
    assert state["decisions"] == []
    assert state["press"] == [] and state["probes"] == []
    meta = state["meta"]
    assert isinstance(meta, dict) and meta["slug"] == "demo" and meta["generated_at"]
    assert meta["last_event_id"] is not None


def test_decisions_carry_section_status_and_selection(project: Project, agent: Actor) -> None:
    first = _suggest(project, agent)
    _suggest(project, agent, level=DecisionLevel.GOAL, subject="objective")
    before = _events(project)
    state = dashboard_service.dashboard_state(project)
    assert _events(project) == before
    rows = state["decisions"]
    assert isinstance(rows, list) and len(rows) == 2
    by_id = {r["decision_id"]: r for r in rows if isinstance(r, dict)}
    assert by_id[first]["section"] == "criteria" or by_id[first]["section"].startswith("other:")
    assert by_id[first]["state"] == "open"
    goal = next(r for r in rows if isinstance(r, dict) and r["level"] == "goal")
    assert isinstance(goal, dict) and goal["section"] == "background"


def test_held_out_seed_identifiers_are_withheld(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, random_works=0)
    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held.doi is not None
    _suggest(
        project,
        agent,
        explanation=f"Because of {held.doi}",
        items=(DecisionItem(item_id="I01", text=f"Seed {held.doi}", grounds=(held.seed_id,)),),
    )
    text = json.dumps(dashboard_service.dashboard_state(project))
    assert held.doi.lower() not in text.lower()
    assert held.seed_id not in text


def test_page_is_self_contained_and_snapshot_embeds_state(project: Project) -> None:
    page = render_page()
    assert "http://" not in page and "https://" not in page
    assert "/api/state" in page and "#0B0C16" in page
    snapshot = render_page(dashboard_service.dashboard_state(project))
    assert '"slug": "demo"' in snapshot and "STATE" not in snapshot.split("const STATIC=")[1][:12]


def test_server_binds_loopback_serves_state_and_refuses_writes(
    project: Project, agent: Actor
) -> None:
    _suggest(project, agent)
    before = _events(project)
    httpd = dashboard_server.make_server(project, 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        assert httpd.server_address[0] == "127.0.0.1"
        base = f"http://127.0.0.1:{httpd.server_port}"
        with urllib.request.urlopen(base + "/") as page:
            assert b"Factory dashboard" in page.read()
        with urllib.request.urlopen(base + "/api/state") as api:
            data = json.loads(api.read())
        assert len(data["decisions"]) == 1
        for method in ("POST", "PUT", "DELETE"):
            request = urllib.request.Request(base + "/api/state", method=method, data=b"{}")
            try:
                urllib.request.urlopen(request)
            except urllib.error.HTTPError as exc:
                assert exc.code == 405
            else:
                raise AssertionError("a write method was accepted")
        bad = urllib.request.Request(base + "/", headers={"Host": "evil.example"})
        try:
            urllib.request.urlopen(bad)
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert _events(project) == before


def test_export_writes_one_file_and_no_event(project: Project, tmp_path: Path) -> None:
    before = _events(project)
    out = dashboard_server.export_snapshot(project, tmp_path / "dash.html")
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert _events(project) == before


def _screened(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> None:
    protocol_id = _partial_corpus(project, agent, human, mock_sources)
    _calibrate(project, agent, human, protocol_id)
    _screen_ordinary(project, agent, protocol_id, pass_a="exclude")


def test_screening_live_on_empty_project(project: Project) -> None:
    live = dashboard_service.screening_live(project)
    json.dumps(live)
    assert not live.get("recent") and not live.get("sessions")


def test_screening_live_lists_recent_sessions_and_totals(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _screened(project, agent, human, mock_sources)
    live = dashboard_service.screening_live(project)
    recent = live["recent"]
    assert isinstance(recent, list) and 0 < len(recent) <= 50
    assert all(r["pass"] in ("A", "B") for r in recent)  # type: ignore[index]
    assert set(recent[0]) >= {"ts", "session", "title", "verdict", "score", "criterion", "quote"}  # type: ignore[arg-type]
    totals = live["totals"]
    assert isinstance(totals, dict) and "exclude" in totals["A"]  # type: ignore[operator]
    assert isinstance(live["sessions"], list) and live["sessions"]


def test_screening_live_withholds_held_out_identifiers(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _screened(project, agent, human, mock_sources)
    [held, *_] = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held.doi is not None
    text = json.dumps(dashboard_service.screening_live(project)) + json.dumps(
        dashboard_service.dashboard_state(project)["screening_live"]
    )
    assert held.doi.lower() not in text.lower() and held.seed_id not in text


def test_screening_endpoint_returns_json(project: Project) -> None:
    httpd = dashboard_server.make_server(project, 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_port}"
        with urllib.request.urlopen(base + "/api/screening") as api:
            data = json.loads(api.read())
        assert isinstance(data, dict)
        with urllib.request.urlopen(base + "/") as page:
            assert b"/api/screening" in page.read()
    finally:
        httpd.shutdown()
        httpd.server_close()

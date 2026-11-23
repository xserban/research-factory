"""Hub v2 routes (plan hub-ui, step 13): pages, versioned assets, cached payloads with ETag, the
trace route and the one write act, served at `/p/<slug>/ui/` through the existing seam."""

from __future__ import annotations

import gzip
import http.client
import json
import os
import re
import sys
import threading
import time
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.reader import read_all
from factory.model.screening import Channel
from factory.model.search import QueryKind, QuerySpec
from factory.services import hub_build as hb
from factory.services import hub_serve, hub_ui, site_server, work_layers
from factory.services import inbox as inbox_service
from factory.services.context import Project, list_projects, open_project
from factory.services.search import list_works, register_query, run_query
from tests.helpers import SESSION

UI = "/p/demo/ui"


def _req(
    port: int,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    sent = dict(headers or {})
    if body is not None:
        sent["Content-Type"] = "application/json"
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=sent)
    response = conn.getresponse()
    data = response.read()
    head = {k.lower(): v for k, v in response.getheaders()}
    conn.close()
    return response.status, head, data


def _events(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _inprocess(project: Project, names: Any, out: Any, poll: Any = None) -> tuple[int, str]:
    """Stand-in for the child process: the same build, run in this process so the tests can stub
    `hb.BUILDERS`. (`test_the_builder_runs_in_a_child_process` uses the real spawn.)"""
    try:
        report = hb.build_static(project, out, only=list(names), payloads_only=True)
    except ValueError as exc:
        return 2, str(exc)
    return (1 if report.errors else 0), "\n".join(f"{n}: {e}" for n, e in report.errors.items())


@pytest.fixture(autouse=True)
def inprocess_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hub_serve, "spawn_builder", _inprocess)
    monkeypatch.setattr(hub_serve, "BATCH_WINDOW", 0.1)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the payload builders by cheap ones that count their calls."""
    seen: list[str] = []

    def make(name: str) -> Any:
        def build(ctx: hb.HubContext) -> dict[str, Any]:
            seen.append(name)
            return {"name": name, "n": len(seen)}

        return build

    for name in list(hb.BUILDERS):
        monkeypatch.setitem(hb.BUILDERS, name, make(name))
    monkeypatch.setattr(hub_serve, "LINGER", 0.0)
    return seen


@pytest.fixture
def served(
    settings: Settings, clock: FixedClock, project: Project, calls: list[str]
) -> Iterator[tuple[int, Project]]:
    hub = site_server.MainHub(
        settings.root,
        lambda: list_projects(settings),
        lambda slug: open_project(settings, slug, session=SESSION, clock=clock),
        min_gap=300.0,
        background=False,
    )
    httpd: ThreadingHTTPServer = site_server.make_main_server(hub, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], project
    httpd.shutdown()
    httpd.server_close()


def _payload(
    port: int, name: str, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, str], bytes]:
    deadline = time.monotonic() + 20
    while True:
        found = _req(port, "GET", f"{UI}/data/{name}.json", headers=headers)
        waiting = found[0] == 503 or "x-hub-stale" in found[1]
        if not waiting or time.monotonic() > deadline:
            return found
        time.sleep(0.05)


def _token(port: int) -> str:
    page = _req(port, "GET", f"{UI}/corpus.html")[2].decode()
    match = re.search(r"name='factory-token' content='([^']+)'", page)
    assert match is not None
    return match.group(1)


# ---------------------------------------------------------------- pages and assets


def test_overview_and_every_page_are_served_in_fetch_mode(served: tuple[int, Project]) -> None:
    port, _ = served
    status, head, body = _req(port, "GET", f"{UI}/")
    assert status == 200 and head["content-type"].startswith("text/html")
    # A project with nothing past setup opens on Learn, otherwise on Overview (decision 155).
    assert "overview.js" in body.decode() or "learn.js" in body.decode()
    for page in hub_ui.PAGES:
        status, head, body = _req(port, "GET", f"{UI}/{page}.html")
        text = body.decode()
        assert status == 200 and head["content-type"].startswith("text/html")
        assert (
            "data/" not in re.sub(r"[^\"']*data/\S*\.json", "", text)
            or '<script src="data/' not in text
        )
        assert 'src="data/' not in text, "fetch mode preloads no data script"
        assert f"assets/{hub_ui.PAGES[page].script}" in text
        assert "name='factory-token'" in text and "name='factory-served'" in text


def test_ui_without_slash_redirects(served: tuple[int, Project]) -> None:
    port, _ = served
    status, head, _ = _req(port, "GET", UI)
    assert status in (301, 302) and head["location"] == f"{UI}/"


def test_every_asset_is_served_and_the_matching_version_is_immutable(
    served: tuple[int, Project],
) -> None:
    port, _ = served
    version = hub_ui.asset_version()
    for name, (_, kind) in hub_ui.ASSETS.items():
        status, head, body = _req(port, "GET", f"{UI}/assets/{name}?v={version}")
        assert status == 200 and head["content-type"] == kind
        assert body == hub_ui.asset_bytes(name)
        assert head["cache-control"] == "public, max-age=31536000, immutable"
    _, head, _ = _req(port, "GET", f"{UI}/assets/kit.css?v=other")
    assert head["cache-control"] == "no-cache"
    _, head, _ = _req(port, "GET", f"{UI}/assets/kit.css")
    assert head["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    "path",
    [
        "/p/nope/ui/",
        "/p/demo/ui/nothing.html",
        "/p/demo/ui/assets/nothing.js",
        "/p/demo/ui/assets/../../etc/passwd",
        "/p/demo/ui/data/nothing.json",
        "/p/demo/ui/data/..%2Fx.json",
        "/p/demo/ui/other",
    ],
)
def test_unknown_slug_page_asset_or_payload_is_404(served: tuple[int, Project], path: str) -> None:
    port, _ = served
    assert _payload(port, "x")[0] == 404
    assert _req(port, "GET", path)[0] == 404


# ---------------------------------------------------------------- payloads


def test_a_payload_is_built_once_cached_and_revalidated_with_its_etag(
    served: tuple[int, Project], calls: list[str]
) -> None:
    port, _ = served
    status, head, body = _payload(port, "overview")
    assert status == 200 and head["content-type"].startswith("application/json")
    assert json.loads(body)["name"] == "overview"
    assert head["cache-control"] == "private, no-cache"
    etag = head["etag"]
    assert etag.startswith('"') and etag.endswith('"')
    status, head, body = _req(port, "GET", f"{UI}/data/overview.json")
    assert status == 200 and head["etag"] == etag and calls.count("overview") == 1
    status, head, body = _req(
        port, "GET", f"{UI}/data/overview.json", headers={"If-None-Match": etag}
    )
    assert status == 304 and body == b"" and head["etag"] == etag
    assert calls.count("overview") == 1


def test_a_new_event_changes_the_fingerprint_and_rebuilds(
    served: tuple[int, Project], calls: list[str]
) -> None:
    port, project = served
    _, head, _ = _payload(port, "overview")
    first = head["etag"]
    inbox_service.add_links(
        project, project.human_actor(), [inbox_service.LinkInput("10.1234/new")], Channel.CLI
    )
    status, head, _ = _payload(port, "overview", headers={"If-None-Match": first})
    assert status == 200 and head["etag"] != first
    assert calls.count("overview") == 2


def test_building_answers_503_with_progress_then_200(
    served: tuple[int, Project], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, _ = served
    gate = threading.Event()

    def slow(ctx: hb.HubContext) -> dict[str, Any]:
        gate.wait(20)
        return {"slow": True}

    monkeypatch.setitem(hb.BUILDERS, "overview", slow)
    status, head, body = _req(port, "GET", f"{UI}/data/overview.json")
    assert status == 503 and head["retry-after"] == "2"
    answer = json.loads(body)
    assert answer["building"] is True and "progress" in answer
    gate.set()
    status, _, body = _payload(port, "overview")
    assert status == 200 and json.loads(body) == {"slow": True}


def test_a_failing_payload_is_500_and_not_retried_at_the_same_fingerprint(
    served: tuple[int, Project], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, _ = served
    seen: list[int] = []

    def broken(ctx: hb.HubContext) -> dict[str, Any]:
        seen.append(1)
        raise RuntimeError("boom")

    monkeypatch.setitem(hb.BUILDERS, "overview", broken)
    status, _, body = _payload(port, "overview")
    assert status == 500 and "boom" not in body.decode()
    assert json.loads(body) == {"error": "build failed", "payload": "overview"}
    assert _req(port, "GET", f"{UI}/data/overview.json")[0] == 500
    assert seen == [1]


def test_a_failed_payload_is_tried_again_after_the_retry_window(
    project: Project, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    now = [1000.0]
    service = hub_serve.PayloadService(project, clock=lambda: now[0])
    monkeypatch.setattr(hub_serve, "LINGER", 0.0)
    seen: list[int] = []

    def flaky(ctx: hb.HubContext) -> dict[str, Any]:
        seen.append(1)
        if len(seen) == 1:
            raise RuntimeError("boom")
        return {"ok": True}

    monkeypatch.setitem(hb.BUILDERS, "overview", flaky)

    def settle() -> hub_serve.Answer:
        # While a build is registered the hub answers Building or, with a file on disk from the
        # same name, Stale (served meanwhile); the test waits for the final answer.
        deadline = time.monotonic() + 20
        while True:
            answer = service.get("overview")
            waiting = isinstance(answer, hub_serve.Building | hub_serve.Stale)
            if not waiting or time.monotonic() > deadline:
                return answer
            time.sleep(0.02)

    first = settle()
    assert isinstance(first, hub_serve.Failed) and first.name == "overview"
    assert "boom" in caplog.text  # the detail is logged, not served
    now[0] += hub_serve.FAILED_RETRY_SECONDS - 1
    assert isinstance(service.get("overview"), hub_serve.Failed) and seen == [1]
    now[0] += 2
    assert isinstance(settle(), hub_serve.Ready) and seen == [1, 1]


def test_one_context_serves_every_payload_of_a_build(
    served: tuple[int, Project], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, _ = served
    contexts: list[int] = []

    def tag(ctx: hb.HubContext) -> dict[str, Any]:
        contexts.append(id(ctx))
        time.sleep(0.05)
        return {}

    for name in ("shell", "flow", "screening"):
        monkeypatch.setitem(hb.BUILDERS, name, tag)
    for name in ("shell", "flow", "screening"):
        _req(port, "GET", f"{UI}/data/{name}.json")
    for name in ("shell", "flow", "screening"):
        assert _payload(port, name)[0] == 200
    assert len(contexts) == 3 and len(set(contexts)) == 1


# ---------------------------------------------------------------- prewarm and stale


def _idle(service: hub_serve.PayloadService) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        with service._cond:
            if not service._queue and service._current is None:
                return
        time.sleep(0.02)
    raise AssertionError("the build did not finish")


@pytest.fixture
def prewarm_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FACTORY_HUB_PREWARM", "1")
    monkeypatch.setattr(hub_serve, "WATCH_SECONDS", 3600.0)


def test_prewarm_queues_every_payload_once_per_fingerprint(
    project: Project, calls: list[str], prewarm_on: None
) -> None:
    service = hub_serve.PayloadService(project)
    service.prewarm()
    _idle(service)
    service.stop()
    expected = [n for n in hub_serve.PREWARM_ORDER if n in hb.BUILDERS]
    assert calls == expected and set(calls) == set(hb.BUILDERS)
    assert service.prewarm_check() is False  # same fingerprint: nothing more
    assert calls == expected
    inbox_service.add_links(
        project, project.human_actor(), [inbox_service.LinkInput("10.1234/warm")], Channel.CLI
    )
    assert service.prewarm_check() is True  # a new event: the payloads that read it, again
    _idle(service)
    again = [n for n in expected if hb.reads(n, "inbox.link_added")]
    assert "costs" not in again and "corpus" in again
    assert calls == expected + again


def test_a_request_jumps_the_prewarm_queue_and_starts_no_second_builder(
    project: Project, calls: list[str], prewarm_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = threading.Event()
    running: list[int] = []
    peak: list[int] = []

    def slow(ctx: hb.HubContext) -> dict[str, Any]:
        running.append(1)
        peak.append(len(running))
        gate.wait(20)
        running.pop()
        return {"slow": True}

    monkeypatch.setitem(hb.BUILDERS, "shell", slow)
    service = hub_serve.PayloadService(project)
    service.prewarm()
    service.stop()
    assert isinstance(service.get("journeys"), hub_serve.Building)
    queued = service._progress()["queued"]
    assert queued[0] == "journeys" and queued.count("journeys") == 1
    gate.set()
    _idle(service)
    assert calls.index("journeys") < calls.index("overview") and max(peak) == 1


def test_a_payload_of_an_older_fingerprint_is_served_stale_while_it_rebuilds(
    served: tuple[int, Project], calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, project = served
    assert _payload(port, "overview")[0] == 200
    gate = threading.Event()

    def slow(ctx: hb.HubContext) -> dict[str, Any]:
        gate.wait(20)
        return {"name": "fresh"}

    monkeypatch.setitem(hb.BUILDERS, "overview", slow)
    inbox_service.add_links(
        project, project.human_actor(), [inbox_service.LinkInput("10.1234/stale")], Channel.CLI
    )
    status, head, body = _req(port, "GET", f"{UI}/data/overview.json")
    assert status == 200 and head["x-hub-stale"] == "1" and json.loads(body)["name"] == "overview"
    assert head["cache-control"] == "private, no-cache" and head["etag"].startswith('"')
    fresh = json.loads(_req(port, "GET", f"{UI}/fresh?name=overview")[2])
    assert fresh == {"fresh": False}
    gate.set()
    status, head, body = _payload(port, "overview")
    assert status == 200 and "x-hub-stale" not in head and json.loads(body)["name"] == "fresh"
    assert json.loads(_req(port, "GET", f"{UI}/fresh?name=overview")[2]) == {"fresh": True}


def test_prewarm_is_off_when_the_env_switch_says_so(
    project: Project, calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FACTORY_HUB_PREWARM", "0")
    service = hub_serve.PayloadService(project)
    service.prewarm()
    time.sleep(0.2)
    assert calls == [] and service._worker is None and service._watcher is None


# ---------------------------------------------------------------- child, keys, caching, gzip


def test_the_builder_runs_in_a_child_process(
    project: Project, calls: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    marker = tmp_path / "child.json"
    script = (
        "import json, os, sys, pathlib\n"
        "out = pathlib.Path(sys.argv[1]) / 'data'\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'overview.json').write_text(json.dumps({'pid': os.getpid()}) + '\\n')\n"
        f"pathlib.Path({str(marker)!r}).write_text(' '.join(sys.argv[2:]))\n"
    )
    monkeypatch.setattr(hub_serve, "spawn_builder", hub_serve._spawn_subprocess)
    monkeypatch.setattr(
        hub_serve,
        "child_command",
        lambda project, names, out: [sys.executable, "-c", script, str(out), *names],
    )
    service = hub_serve.PayloadService(project)
    deadline = time.monotonic() + 20
    answer = service.get("overview")
    while not isinstance(answer, hub_serve.Ready) and time.monotonic() < deadline:
        time.sleep(0.05)
        answer = service.get("overview")
    assert isinstance(answer, hub_serve.Ready)
    pid = json.loads(answer.body)["pid"]
    assert isinstance(pid, int) and pid != os.getpid()
    assert calls == [] and marker.read_text() == "overview"  # no builder ran in this process


def test_a_failing_child_is_logged_with_its_stderr_tail_and_answers_500(
    project: Project, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    script = "import sys; print('Traceback: kaboom', file=sys.stderr); sys.exit(3)"
    monkeypatch.setattr(hub_serve, "spawn_builder", hub_serve._spawn_subprocess)
    monkeypatch.setattr(
        hub_serve, "child_command", lambda project, names, out: [sys.executable, "-c", script]
    )
    service = hub_serve.PayloadService(project)
    deadline = time.monotonic() + 20
    answer = service.get("overview")
    while isinstance(answer, hub_serve.Building) and time.monotonic() < deadline:
        time.sleep(0.05)
        answer = service.get("overview")
    assert isinstance(answer, hub_serve.Failed)
    assert "kaboom" in caplog.text and "3" in caplog.text


def test_the_child_command_is_niced_and_builds_only_the_batch(
    project: Project, tmp_path: Any
) -> None:
    cmd = hub_serve.child_command(project, ["corpus", "grid"], tmp_path)
    assert cmd[:3] == ["nice", "-n", str(hub_serve.BUILD_NICE)] and cmd[3] == sys.executable
    assert cmd[cmd.index("--only") + 1] == "corpus,grid" and "--payloads-only" in cmd
    assert cmd[cmd.index("--out") + 1] == str(tmp_path)
    assert str(project.settings.root) == cmd[cmd.index("--root") + 1]


def test_an_event_a_payload_does_not_read_leaves_it_fresh_while_others_go_stale(
    project: Project, calls: list[str]
) -> None:
    service = hub_serve.PayloadService(project)
    for name in ("costs", "corpus"):
        service.get(name)
    _idle(service)
    assert service.status()["costs"]["fresh"] and service.status()["corpus"]["fresh"]
    inbox_service.add_links(
        project, project.human_actor(), [inbox_service.LinkInput("10.1234/quiet")], Channel.CLI
    )
    status = service.status()
    assert status["costs"]["fresh"] is True and status["corpus"]["fresh"] is False
    assert service.is_fresh("costs") and not service.is_fresh("corpus")
    assert not hb.reads("costs", "inbox.link_added") and hb.reads("corpus", "inbox.link_added")
    assert hb.reads("pipeline", "runner.finished")  # an unlisted payload reads every event


def test_a_stale_payload_has_an_etag_and_is_revalidated_with_304(
    served: tuple[int, Project], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, project = served
    _, head, _ = _payload(port, "overview")
    built_for = head["etag"]
    gate = threading.Event()
    monkeypatch.setitem(hb.BUILDERS, "overview", lambda ctx: (gate.wait(20), {"n": 2})[1])
    inbox_service.add_links(
        project, project.human_actor(), [inbox_service.LinkInput("10.1234/stale2")], Channel.CLI
    )
    status, head, body = _req(port, "GET", f"{UI}/data/overview.json")
    assert status == 200 and head["x-hub-stale"] == "1"
    assert head["etag"] == built_for  # the fingerprint the file was built for
    assert head["cache-control"] == "private, no-cache"
    status, head, body = _req(
        port, "GET", f"{UI}/data/overview.json", headers={"If-None-Match": built_for}
    )
    assert status == 304 and body == b"" and head["x-hub-stale"] == "1"
    assert head["etag"] == built_for and head["cache-control"] == "private, no-cache"
    gate.set()
    status, head, _ = _payload(port, "overview", headers={"If-None-Match": built_for})
    assert status == 200 and head["etag"] != built_for and "x-hub-stale" not in head


def test_a_payload_is_served_gzipped_when_asked_and_decodes_to_the_same_json(
    served: tuple[int, Project],
) -> None:
    port, _ = served
    status, plain_head, plain = _payload(port, "overview")
    assert "content-encoding" not in plain_head and plain_head["vary"] == "Accept-Encoding"
    status, head, body = _req(
        port, "GET", f"{UI}/data/overview.json", headers={"Accept-Encoding": "gzip, br"}
    )
    assert (
        status == 200 and head["content-encoding"] == "gzip" and head["vary"] == "Accept-Encoding"
    )
    assert head["etag"] == plain_head["etag"] and gzip.decompress(body) == plain
    status, head, body = _req(
        port,
        "GET",
        f"{UI}/data/overview.json",
        headers={"Accept-Encoding": "gzip", "If-None-Match": plain_head["etag"]},
    )
    assert status == 304
    cached = hub_serve.PayloadService(served[1])._dir / "overview.json.gz"
    assert cached.is_file()  # compressed once, by the build


def test_assets_are_served_gzipped_when_asked(served: tuple[int, Project]) -> None:
    port, _ = served
    version = hub_ui.asset_version()
    path = f"{UI}/assets/shell.js?v={version}"
    status, head, plain = _req(port, "GET", path)
    assert status == 200 and "content-encoding" not in head and head["vary"] == "Accept-Encoding"
    status, head, body = _req(port, "GET", path, headers={"Accept-Encoding": "gzip"})
    assert head["content-encoding"] == "gzip" and gzip.decompress(body) == plain
    assert len(body) < len(plain) and "immutable" in head["cache-control"]


# ---------------------------------------------------------------- trace


def test_trace_route_answers_the_adapter_and_refuses_bad_requests(
    served: tuple[int, Project], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, _ = served
    got: list[tuple[str, int, int]] = []

    def fake(project: Project, figure: str, *, offset: int = 0, limit: int = 50) -> Any:
        got.append((figure, offset, limit))
        return SimpleNamespace(to_payload=lambda: {"figure_id": figure, "entries": []})

    with monkeypatch.context() as patch:
        patch.setattr(hub_serve, "trace_figure", fake)
        status, _, body = _req(port, "GET", f"{UI}/trace?figure=prisma.included&offset=2&limit=5")
        assert status == 200 and json.loads(body)["figure_id"] == "prisma.included"
        assert got == [("prisma.included", 2, 5)]
    for query in ("", "figure=", "figure=x&offset=a", "figure=x&limit=0", "figure=x&offset=-1"):
        status, _, body = _req(port, "GET", f"{UI}/trace?{query}")
        assert status == 400, query
        assert json.loads(body)["issues"]


def test_read_routes_write_nothing(served: tuple[int, Project]) -> None:
    port, project = served
    before = _events(project)
    for path in (f"{UI}/", f"{UI}/corpus.html", f"{UI}/assets/kit.css", f"{UI}/trace?figure=x"):
        _req(port, "GET", path)
    _payload(port, "overview")
    _payload(port, "overview")
    assert _events(project) == before


# ---------------------------------------------------------------- the snowball act


def _link_events(project: Project) -> list[Any]:
    return [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "inbox.link_added"
    ]


@pytest.fixture
def outside(monkeypatch: pytest.MonkeyPatch) -> str:
    """One stored outside work with a DOI (the real store is not needed for the act)."""
    wid = "rf:smith2020-outside-work-0a1b2c3d"
    found = SimpleNamespace(
        id=wid,
        identifiers=SimpleNamespace(
            doi="10.1234/outside", arxiv=None, openalex=None, pmid=None, pmcid=None
        ),
    )
    monkeypatch.setattr(hub_serve, "get_work", lambda p, w: found if w == wid else None)
    monkeypatch.setattr(hub_serve, "corpus_ids", lambda p: frozenset({"rf:in-corpus-00000000"}))
    return wid


SNOW = f"{UI}/act/snowball-add"


def test_snowball_needs_the_token(served: tuple[int, Project], outside: str) -> None:
    port, project = served
    assert _req(port, "POST", SNOW, {"work_id": outside})[0] == 403
    bad = {"X-Factory-Token": "nope"}
    assert _req(port, "POST", SNOW, {"work_id": outside}, bad)[0] == 403
    foreign = {"X-Factory-Token": _token(port), "Origin": "http://evil.example"}
    assert _req(port, "POST", SNOW, {"work_id": outside}, foreign)[0] == 403
    assert _link_events(project) == []


def test_snowball_refuses_a_bad_work_and_writes_nothing(
    served: tuple[int, Project], outside: str
) -> None:
    port, project = served
    auth = {"X-Factory-Token": _token(port)}
    before = _events(project)
    for body in (
        {},
        {"work_id": 3},
        {"work_id": ""},
        {"work_id": "not an id"},
        {"work_id": "rf:unknown-work-0a1b2c3d"},
        {"work_id": "rf:in-corpus-00000000"},
    ):
        status, _, data = _req(port, "POST", SNOW, body, auth)
        assert status == 400, body
        assert json.loads(data)["issues"]
    assert _events(project) == before


def test_snowball_refuses_a_real_corpus_work_with_a_doi(
    explore_project: Project,
    fake_sources: Any,
    settings: Settings,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = fake_sources(
        [[{"title": "In corpus", "authors": ["Ada Zhou"], "year": 2024, "doi": "10.5555/incorpus"}]]
    )
    qid = register_query(
        explore_project,
        explore_project.human_actor(),
        QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="x"),
        sources=sources,
    )
    run_query(explore_project, qid, sources=sources)
    (work,) = list_works(explore_project)
    assert work.identifiers.doi
    monkeypatch.setattr(hub_serve, "LINGER", 0.0)
    hub = site_server.MainHub(
        settings.root,
        lambda: list_projects(settings),
        lambda slug: open_project(settings, slug, session=SESSION, clock=clock),
        min_gap=300.0,
        background=False,
    )
    httpd: ThreadingHTTPServer = site_server.make_main_server(hub, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        port = httpd.server_address[1]
        before = _events(explore_project)
        status, _, data = _req(
            port, "POST", SNOW, {"work_id": work.id}, {"X-Factory-Token": _token(port)}
        )
        assert status == 400 and "already in the corpus" in data.decode()
        assert _events(explore_project) == before
        assert _link_events(explore_project) == []
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_snowball_records_the_researchers_inbox_link_once(
    served: tuple[int, Project], outside: str
) -> None:
    port, project = served
    auth = {"X-Factory-Token": _token(port)}
    status, _, data = _req(port, "POST", SNOW, {"work_id": outside}, auth)
    assert status == 200, data
    answer = json.loads(data)
    assert answer["ok"] is True and answer["duplicate"] is False and answer["item_id"]
    events = _link_events(project)
    assert len(events) == 1 and events[0].actor.kind == "human"
    assert events[0].payload["identifier_value"] == "10.1234/outside"
    again = json.loads(_req(port, "POST", SNOW, {"work_id": outside}, auth)[2])
    assert again["duplicate"] is True and again["item_id"] == answer["item_id"]
    assert len(_link_events(project)) == 1


def test_snowball_without_an_identifier_is_refused(
    served: tuple[int, Project], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, project = served
    wid = "rf:smith2020-no-identifier-0a1b2c3d"
    bare = SimpleNamespace(
        id=wid,
        identifiers=SimpleNamespace(doi=None, arxiv=None, openalex=None, pmid=None, pmcid=None),
    )
    monkeypatch.setattr(hub_serve, "get_work", lambda p, w: bare)
    monkeypatch.setattr(hub_serve, "corpus_ids", lambda p: frozenset())
    status, _, data = _req(port, "POST", SNOW, {"work_id": wid}, {"X-Factory-Token": _token(port)})
    assert status == 400 and "identifier" in data.decode()
    assert _link_events(project) == []


def test_other_ui_paths_do_not_accept_posts(served: tuple[int, Project]) -> None:
    port, _ = served
    auth = {"X-Factory-Token": _token(port)}
    assert _req(port, "POST", f"{UI}/act/other", {}, auth)[0] == 404
    assert _req(port, "POST", f"{UI}/data/overview.json", {}, auth)[0] == 404
    assert _req(port, "PUT", SNOW, {}, auth)[0] == 405


# ---------------------------------------------------------------- the existing acts the pages use


def test_the_pages_reach_the_existing_mine_and_export_routes(
    served: tuple[int, Project], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, _ = served
    auth = {"X-Factory-Token": _token(port), "Origin": f"http://127.0.0.1:{port}"}
    seen: list[Any] = []

    def fake_request(p: Any, a: Any, **kw: Any) -> str:
        seen.append(kw)
        return "req-1"

    monkeypatch.setattr(work_layers, "request_mining", fake_request)
    status, _, data = _req(
        port, "POST", "/p/demo/api/mine/work", {"work_id": "rf:a-00000000"}, auth
    )
    assert status == 200 and json.loads(data)["request_id"] == "req-1"
    assert seen == [{"works": ("rf:a-00000000",), "reason": None}]
    status, _, data = _req(port, "POST", "/p/demo/api/export/works", {"work_ids": 3}, auth)
    assert status == 400


def test_the_page_scripts_call_those_routes_only_when_served() -> None:
    corpus = hub_ui.asset_bytes("pages/corpus.js").decode()
    for route in ("api/export/works", "api/mine/work", "api/mine/layer", "api/layers/move"):
        assert route in corpus
    assert "HUB.served" in corpus
    graph = hub_ui.asset_bytes("pages/graph.js").decode()
    assert "/ui/act/snowball-add" in graph and "HUB.served" in graph
    shell = hub_ui.asset_bytes("shell.js").decode()
    assert "Retry-After" in shell and "Updating" in shell


NEW_PAGES = ("protocol", "levels", "pipeline", "sources", "method", "costs", "write", "platform")


def test_the_seven_new_pages_and_payloads_are_served(served: tuple[int, Project]) -> None:
    port, _ = served
    for name in NEW_PAGES:
        status, _, body = _req(port, "GET", f"{UI}/{name}.html")
        assert status == 200 and f"assets/pages/{name}.js" in body.decode()
        status, _, data = _payload(port, name)
        assert status == 200 and json.loads(data)["name"] == name
        status, _, _ = _req(port, "GET", f"{UI}/assets/pages/{name}.js")
        assert status == 200


def test_the_switcher_and_the_hub_token_exist_only_when_served(served: tuple[int, Project]) -> None:
    port, _ = served
    page = _req(port, "GET", f"{UI}/protocol.html")[2].decode()
    assert "name='factory-served'" in page
    shell = _req(port, "GET", f"{UI}/assets/shell.js")[2].decode()
    assert "if (HUB.served) projectSwitcher" in shell
    assert "/api/projects" in shell


def test_the_static_build_page_carries_no_served_marker_so_no_switcher() -> None:
    html = hub_ui.page_html(
        "protocol", "Protocol", ["pages/protocol.js"], ("shell", "protocol"), "v"
    )
    assert "factory-served" not in html and "factory-hub-token" not in html


# ---------------------------------------------------------------- read-only file routes (port)

DOC = "doc_01ARZ3NDEKTSV4RRFFQ69G5FAV"
WORK = "rf:test-0123abcd"


@pytest.fixture
def one_document(project: Project, monkeypatch: pytest.MonkeyPatch) -> str:
    """A converted document (an HTML original and its Markdown) known to the inspector."""
    from factory.services import hub_sources
    from factory.services.site_inspector import Doc

    raw = project.library.put(
        b"<html><body><p>alpha beta gamma delta epsilon zeta eta</p></body></html>"
    )
    md = project.library.put(b"alpha beta gamma delta epsilon zeta eta")
    doc = Doc(DOC, WORK, "latexml-html", "text/html", raw, md, "T", None, None, None, None)
    monkeypatch.setattr(hub_sources, "inspector_documents", lambda p, r: [doc])
    return DOC


def test_status_json_reports_each_payload_and_writes_nothing(served: tuple[int, Project]) -> None:
    port, project = served
    before = _events(project)
    status, head, body = _req(port, "GET", f"{UI}/status.json")
    assert status == 200 and "no-store" in head["cache-control"]
    rows = json.loads(body)
    assert set(rows) == set(hb.BUILDERS)
    assert all({"fresh", "built_at"} <= set(r) for r in rows.values())
    _payload(port, "overview")
    assert json.loads(_req(port, "GET", f"{UI}/status.json")[2])["overview"]["fresh"] is True
    assert _events(project) == before


def test_screening_api_answers_the_live_panel(served: tuple[int, Project]) -> None:
    port, project = served
    before = _events(project)
    status, _, body = _req(port, "GET", "/p/demo/api/screening")
    assert status == 200 and isinstance(json.loads(body), dict)
    assert _events(project) == before


def test_source_document_payload_and_files(served: tuple[int, Project], one_document: str) -> None:
    port, project = served
    before = _events(project)
    status, _, body = _req(port, "GET", f"{UI}/data/sources-doc-{one_document}.json")
    detail = json.loads(body)
    assert status == 200 and detail["document_id"] == DOC
    assert detail["markdown"].startswith("alpha beta")
    assert detail["files"]["original"] == f"file/original/{DOC}"
    s1, h1, b1 = _req(port, "GET", f"{UI}/file/original/{DOC}")
    assert s1 == 200 and h1["content-type"].startswith("text/plain") and b"<html>" in b1
    s2, h2, b2 = _req(port, "GET", f"{UI}/file/markdown/{DOC}")
    assert s2 == 200 and h2["content-type"].startswith("text/markdown") and b2.startswith(b"alpha")
    by_work = _req(port, "GET", f"{UI}/file/original/{WORK}")  # a work id finds its document
    assert by_work[0] == 200 and by_work[2] == b1
    assert _events(project) == before


@pytest.mark.parametrize(
    "path",
    [
        "data/sources-doc-doc_01ARZ3NDEKTSV4RRFFQ69G5FAW.json",
        "data/sources-doc-..%2f..%2fetc.json",
        "data/sources-doc-.json",
        "file/original/doc_01ARZ3NDEKTSV4RRFFQ69G5FAW",
        "file/original/..%2f..%2fevents",
        "file/original/",
        "file/other/doc_01ARZ3NDEKTSV4RRFFQ69G5FAV",
    ],
)
def test_unknown_documents_are_404(
    served: tuple[int, Project], one_document: str, path: str
) -> None:
    assert _req(served[0], "GET", f"{UI}/{path}")[0] == 404


def test_ops_files_are_read_only_and_contained(served: tuple[int, Project], tmp_path: Any) -> None:
    port, project = served
    ops = project.paths.dir / "ops"
    (ops / "logs").mkdir(parents=True, exist_ok=True)
    (ops / "logs" / "a.log").write_text("line one\n", encoding="utf-8")
    (ops / "data.json").write_text("{}", encoding="utf-8")
    (ops / "big.txt").write_text("x" * 10, encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    (ops / "link.txt").symlink_to(secret)
    (ops / "linkdir").symlink_to(tmp_path, target_is_directory=True)
    (project.paths.dir / "outside.txt").write_text("no", encoding="utf-8")
    before = _events(project)
    ok = _req(port, "GET", f"{UI}/ops/logs/a.log")
    assert (
        ok[0] == 200 and ok[1]["content-type"].startswith("text/plain") and ok[2] == b"line one\n"
    )
    assert _req(port, "GET", f"{UI}/ops/data.json")[1]["content-type"].startswith(
        "application/json"
    )
    for bad in (
        "ops/../outside.txt",
        "ops/%2e%2e/outside.txt",
        "ops/..%2foutside.txt",
        "ops//etc/passwd",
        "ops/logs",  # a directory
        "ops/",
        "ops/missing.txt",
        "ops/link.txt",  # a symlink
        "ops/linkdir/secret.txt",  # through a symlinked folder
        "ops/logs/../../outside.txt",
        "ops/%00",
    ):
        assert _req(port, "GET", f"{UI}/{bad}")[0] == 404, bad
    assert _events(project) == before


def test_ops_file_cap_refuses_a_large_file(
    served: tuple[int, Project], monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services import hub_costs

    port, project = served
    (project.paths.dir / "ops").mkdir(exist_ok=True)
    (project.paths.dir / "ops" / "big.txt").write_text("x" * 50, encoding="utf-8")
    monkeypatch.setattr(hub_costs, "OPS_FILE_CAP", 10)
    assert _req(port, "GET", f"{UI}/ops/big.txt")[0] == 404


def test_wiki_zip_is_built_once_per_fingerprint(
    served: tuple[int, Project], monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import zipfile

    from factory.services import site as site_service

    port, project = served
    built: list[int] = []

    def fake(p: Project, out: Any) -> None:
        built.append(1)
        (out / "index.md").write_text("# vault", encoding="utf-8")

    monkeypatch.setattr(site_service, "_build_wiki", fake)
    before = _events(project)
    status, head, body = _req(port, "GET", f"{UI}/download/wiki.zip")
    assert status == 200 and head["content-type"] == "application/zip"
    assert "attachment" in head["content-disposition"]
    assert zipfile.ZipFile(io.BytesIO(body)).namelist() == ["index.md"]
    assert _req(port, "GET", f"{UI}/download/wiki.zip")[2] == body
    assert len(built) == 1
    assert _events(project) == before


def test_new_ui_routes_refuse_a_non_loopback_host(served: tuple[int, Project]) -> None:
    port, _ = served
    for path in ("status.json", "ops/x", f"file/original/{DOC}", "download/wiki.zip"):
        status, _, _ = _req(port, "GET", f"{UI}/{path}", headers={"Host": "evil.example"})
        assert status == 403


def test_a_project_page_carries_no_hub_token(served: tuple[int, Project]) -> None:
    port, _ = served
    for name in ("overview", "living", "corpus"):
        page = _req(port, "GET", f"{UI}/{name}.html")[2].decode()
        assert "factory-hub-token" not in page
        shell = _req(port, "GET", f"{UI}/assets/shell.js")[2].decode()
        assert "factory-hub-token" not in shell and "/api/projects/create" not in shell


INBOX = "/p/demo/api/inbox/add"


def test_project_inbox_add_writes_to_the_slots_project_only(served: tuple[int, Project]) -> None:
    port, project = served
    token = {"X-Factory-Token": _token(port)}
    before = len(_link_events(project))
    status, _, data = _req(port, "POST", INBOX, {"value": "10.1234/abc", "note": "n"}, token)
    assert status == 200 and json.loads(data)["duplicate"] is False
    assert len(_link_events(project)) == before + 1
    # no token: refused; a project field: refused and nothing written
    assert _req(port, "POST", INBOX, {"value": "10.1234/def"})[0] == 403
    status, _, _ = _req(port, "POST", INBOX, {"value": "10.1234/def", "project": "other"}, token)
    assert status == 400 and len(_link_events(project)) == before + 1


def test_project_feed_routes_are_reachable_with_the_project_token(
    served: tuple[int, Project],
) -> None:
    port, _ = served
    token = {"X-Factory-Token": _token(port)}
    for route in ("run", "refetch"):
        path = f"/p/demo/api/feed/{route}"
        assert _req(port, "POST", path, {})[0] == 403
        # the runner is off in this fixture: 503 (not 403/404) shows the route was reached
        assert _req(port, "POST", path, {}, token)[0] in (202, 409, 503)


def test_hub_routes_refuse_a_project_token(served: tuple[int, Project]) -> None:
    port, project = served
    token = {"X-Factory-Token": _token(port)}
    before = len(_link_events(project))
    body = {"project": "demo", "value": "10.1234/xyz"}
    assert _req(port, "POST", "/api/inbox/add", body, token)[0] == 403
    assert _req(port, "POST", "/api/feed/run", {}, token)[0] == 403
    assert _req(port, "POST", "/api/projects/create", {"slug": "zz"}, token)[0] == 403
    assert len(_link_events(project)) == before


def _register(project: Project, rel: str, content: bytes, title: str | None = None) -> str:
    from factory.services.study_files import register_file

    target = project.paths.dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return register_file(
        project, rel, "study-document", title, project.human_actor()
    ).registration.event_id


def test_study_file_is_served_by_registered_id_only(served: tuple[int, Project]) -> None:
    port, project = served
    md = _register(project, "docs/plan.md", b"# Plan\n", "Plan")
    blob = _register(project, "docs/data.bin", b"\x00\x01")
    html = _register(project, "docs/page.html", b"<script>x()</script>")
    before = _events(project)
    ok = _req(port, "GET", f"{UI}/study/{md}")
    assert ok[0] == 200 and ok[2] == b"# Plan\n"
    assert ok[1]["content-type"].startswith("text/plain")
    assert "attachment" not in ok[1].get("content-disposition", "")
    # the stored version stays readable after the file changes on disk
    (project.paths.dir / "docs/plan.md").write_bytes(b"# Plan v2\n")
    assert _req(port, "GET", f"{UI}/study/{md}")[2] == b"# Plan\n"
    other = _req(port, "GET", f"{UI}/study/{blob}")
    assert other[0] == 200 and other[1]["content-disposition"].startswith("attachment")
    page = _req(port, "GET", f"{UI}/study/{html}")  # a page is never served as a page
    assert page[1]["content-type"].startswith("text/plain")
    assert _events(project) == before


def test_study_file_refuses_unknown_ids_paths_and_large_files(
    served: tuple[int, Project], monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services import hub_sources

    port, project = served
    reg = _register(project, "docs/plan.md", b"x" * 50)
    for bad in (
        "study/nope",
        "study/",
        "study/docs/plan.md",  # a path is not an id
        "study/../outside.txt",
        "study/%2e%2e/outside.txt",
        "study/..%2fdocs%2fplan.md",
        "study/%00",
    ):
        assert _req(port, "GET", f"{UI}/{bad}")[0] == 404, bad
    assert _req(port, "GET", f"{UI}/study/{reg}")[0] == 200
    monkeypatch.setattr(hub_sources, "STUDY_FILE_CAP", 10)
    assert _req(port, "GET", f"{UI}/study/{reg}")[0] == 404


def test_wiki_zip_copies_inside_symlinks_and_lists_outside_ones(
    served: tuple[int, Project], monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    import io
    import zipfile

    from factory.services import site as site_service

    port, project = served
    inside = project.paths.dir / "library-file.pdf"
    inside.write_bytes(b"original bytes")
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"secret")

    def fake(p: Project, out: Any) -> None:
        (out / "docs").mkdir()
        (out / "docs" / "a.pdf").symlink_to(inside)
        (out / "docs" / "b.pdf").symlink_to(outside)
        (out / "docs" / "dangling.pdf").symlink_to(tmp_path / "gone.pdf")
        (out / "index.md").write_text("# vault", encoding="utf-8")

    monkeypatch.setattr(site_service, "_build_wiki", fake)
    status, _, body = _req(port, "GET", f"{UI}/download/wiki.zip")
    assert status == 200
    zf = zipfile.ZipFile(io.BytesIO(body))
    assert zf.read("docs/a.pdf") == b"original bytes"
    assert "docs/b.pdf" not in zf.namelist() and "docs/dangling.pdf" not in zf.namelist()
    note = zf.read("SKIPPED-LINKS.txt").decode()
    assert "docs/b.pdf" in note and "docs/dangling.pdf" in note and "secret" not in note
    assert "docs/a.pdf" not in note

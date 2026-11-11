"""The surfaces of resume (plan restart-and-costs, R3): `factory resume`, the hub's resume act and
Interrupted panel, and the dashboard's interrupted line. The service rules are in
`test_resume.py` and `test_resume_find.py`; these check the commands, the write-path checks of the
hub and the escaping of the page. `resume` is replaced by a recorder where a real run would start
a runner, so nothing here starts a process.
"""

from __future__ import annotations

import http.client
import json
import re
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryError
from factory.services import dashboard as dashboard_service
from factory.services import resume as resume_service
from factory.services import site_queue, site_server
from factory.services.context import Project
from factory.services.project import init_project
from factory.services.resume import (
    AutomaticLeft,
    ExpiredLeases,
    Interrupted,
    InterruptedRun,
    ResumePlan,
    ResumeResult,
    RunResume,
)
from factory.services.site import site_dir
from tests.helpers import SESSION, T0

runner = CliRunner()
SLUG = "alpha"
ResumeFake = Callable[..., ResumePlan | ResumeResult]


def _env(root: Path) -> dict[str, str | None]:
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}


def _init(root: Path, slug: str) -> None:
    init_project(
        Settings(root=root, user="obd"), slug, "pilot", session=SESSION, clock=FixedClock(T0)
    )


def _plan() -> ResumePlan:
    return ResumePlan(
        reconcile=["run_0"],
        leases=[ExpiredLeases(kind="screen", count=2, task_ids=["t1", "t2"])],
        pipeline=None,
        run=RunResume(resumes="run_1", stage="screen", model="haiku"),
        queued=[],
        stale_passes=[],
        automatic=AutomaticLeft(),
    )


def _events(root: Path, slug: str) -> dict[str, bytes]:
    folder = root / "projects" / slug / "events"
    return {p.name: p.read_bytes() for p in sorted(folder.glob("*.jsonl"))}


def _recording(calls: list[dict[str, Any]]) -> Callable[..., ResumePlan]:
    """A stand-in for `resume` that records its keyword arguments and returns the plan."""

    def fake(project: Project, **kwargs: Any) -> ResumePlan:
        calls.append(kwargs)
        return _plan()

    return fake


def _clean() -> Interrupted:
    return Interrupted(runs=[], pipelines=[], leases=[], passes=[], automatic=AutomaticLeft())


# --- factory resume -------------------------------------------------------------------------


def test_dry_run_prints_the_plan_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init(tmp_path, SLUG)
    calls: list[tuple[str, bool, int | None]] = []

    def fake(
        project: Project, *, dry_run: bool = False, unit_cap: int | None = None, **_: Any
    ) -> ResumePlan:
        calls.append((project.paths.slug, dry_run, unit_cap))
        return _plan()

    monkeypatch.setattr(resume_service, "resume", fake)
    before = _events(tmp_path, SLUG)
    result = runner.invoke(app, ["resume", "--project", SLUG, "--dry-run"], env=_env(tmp_path))
    assert result.exit_code == 0, result.output
    assert calls == [(SLUG, True, None)]
    assert "reconciled (process gone): run_0" in result.output
    assert "leases lapsed, released by expiry: screen x2" in result.output
    assert "run run_1 resumed: stage screen with model haiku" in result.output
    assert "dry run: nothing written" in result.output
    assert _events(tmp_path, SLUG) == before


def test_real_run_prints_what_started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init(tmp_path, SLUG)
    outcome = ResumeResult(plan=_plan(), reconciled=[], run_id="run_9")
    monkeypatch.setattr(resume_service, "resume", lambda project, **_: outcome)
    result = runner.invoke(app, ["resume", "--project", SLUG, "--cap", "4"], env=_env(tmp_path))
    assert result.exit_code == 0, result.output
    assert "started run run_9" in result.output


def test_a_refusal_exits_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init(tmp_path, SLUG)
    outcome = ResumeResult(plan=_plan(), reconciled=[], refused=["unit_cap: too high"])
    monkeypatch.setattr(resume_service, "resume", lambda project, **_: outcome)
    result = runner.invoke(app, ["resume", "--project", SLUG], env=_env(tmp_path))
    assert result.exit_code == 1
    assert "unit_cap: too high" in result.output


def test_nothing_to_do_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init(tmp_path, SLUG)
    empty = ResumePlan(
        reconcile=[],
        leases=[],
        pipeline=None,
        run=None,
        queued=[],
        stale_passes=[],
        automatic=AutomaticLeft(),
    )
    monkeypatch.setattr(
        resume_service, "resume", lambda project, **_: ResumeResult(plan=empty, reconciled=[])
    )
    result = runner.invoke(app, ["resume", "--project", SLUG], env=_env(tmp_path))
    assert result.exit_code == 0, result.output
    assert "nothing interrupted" in result.output


def test_a_cap_below_one_is_invalid_input(tmp_path: Path) -> None:
    _init(tmp_path, SLUG)
    result = runner.invoke(app, ["resume", "--project", SLUG, "--cap", "0"], env=_env(tmp_path))
    assert result.exit_code == 2
    assert "cap: must be at least 1" in result.output


def test_all_authorises_each_project_and_goes_on_past_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.cli import resume as resume_cli

    _init(tmp_path, "alpha")
    _init(tmp_path, "beta")
    checked: list[tuple[str, str]] = []

    def fake_authorize(project: Project, principal: object, tool: str) -> None:
        checked.append((project.paths.slug, tool))
        if project.paths.slug == "beta":
            raise FactoryError("no access to beta")

    planned: list[str] = []

    def fake_resume(project: Project, **_: Any) -> ResumePlan:
        planned.append(project.paths.slug)
        return _plan()

    monkeypatch.setattr(resume_cli, "authorize_command", fake_authorize)
    monkeypatch.setattr(resume_service, "resume", fake_resume)
    result = runner.invoke(app, ["resume", "--all", "--dry-run"], env=_env(tmp_path))
    assert checked == [("alpha", "cli:resume"), ("beta", "cli:resume")]
    assert planned == ["alpha"]
    assert "no access to beta" in result.output
    assert "project alpha" in result.output
    assert result.exit_code == 1


# --- the hub: POST /api/queue/resume and GET /api/queue/interrupted -------------------------


def _request(
    port: int,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    sent = {"Content-Type": "application/json", **(headers or {})}
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=sent)
    response = conn.getresponse()
    text = response.read().decode()
    conn.close()
    return response.status, text


@pytest.fixture
def hub(project: Project) -> Iterator[tuple[int, str]]:
    queue_dir = site_dir(project) / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "index.html").write_text(
        "<!doctype html><html><head></head><body>queue</body></html>", encoding="utf-8"
    )
    httpd, _ = site_server.make_server(project, 0, background=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    status, body = _request(port, "GET", "/queue/")
    assert status == 200
    match = re.search(r"name='factory-token' content='([^']+)'", body)
    assert match is not None
    yield port, match.group(1)
    httpd.shutdown()
    httpd.server_close()


def _own(port: int, token: str) -> dict[str, str]:
    return {"X-Factory-Token": token, "Origin": f"http://127.0.0.1:{port}"}


def test_post_without_the_token_is_refused_and_plans_nothing(
    hub: tuple[int, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, _ = hub
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(resume_service, "resume", _recording(calls))
    status, _ = _request(port, "POST", "/api/queue/resume", {"dry_run": True})
    assert status == 403
    assert calls == []


def test_a_foreign_origin_is_refused(hub: tuple[int, str], monkeypatch: pytest.MonkeyPatch) -> None:
    port, token = hub
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(resume_service, "resume", _recording(calls))
    foreign = {"X-Factory-Token": token, "Origin": "http://evil.example"}
    status, _ = _request(port, "POST", "/api/queue/resume", {"dry_run": True}, foreign)
    assert status == 403
    assert calls == []


def test_a_dry_run_post_returns_the_plan(
    hub: tuple[int, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, token = hub
    seen: list[dict[str, Any]] = []

    def fake(project: Project, **kwargs: Any) -> ResumePlan:
        seen.append(kwargs)
        return _plan()

    monkeypatch.setattr(resume_service, "resume", fake)
    status, text = _request(port, "POST", "/api/queue/resume", {"dry_run": True}, _own(port, token))
    assert status == 200, text
    payload = json.loads(text)
    assert payload["dry_run"] is True
    assert payload["plan"]["reconcile"] == ["run_0"]
    assert seen == [{"dry_run": True}]


def test_a_bad_body_is_400(hub: tuple[int, str], monkeypatch: pytest.MonkeyPatch) -> None:
    port, token = hub
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(resume_service, "resume", _recording(calls))
    status, text = _request(
        port, "POST", "/api/queue/resume", {"dry_run": "yes", "unit_cap": 0}, _own(port, token)
    )
    assert status == 400
    assert json.loads(text)["ok"] is False
    assert calls == []


def test_a_real_resume_is_started_and_its_outcome_kept(
    hub: tuple[int, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, token = hub
    seen: list[dict[str, Any]] = []

    def fake(project: Project, **kwargs: Any) -> ResumeResult:
        seen.append(kwargs)
        return ResumeResult(plan=_plan(), reconciled=[], run_id="run_9")

    monkeypatch.setattr(resume_service, "resume", fake)
    monkeypatch.setattr(resume_service, "interrupted", lambda project, **_: _clean())
    status, text = _request(port, "POST", "/api/queue/resume", {"unit_cap": 5}, _own(port, token))
    assert status == 202, text
    deadline = time.monotonic() + 5
    last = None
    while time.monotonic() < deadline:
        _, body = _request(port, "GET", "/api/queue/interrupted")
        last = json.loads(body)["last_resume"]
        if last is not None:
            break
        time.sleep(0.05)
    assert last is not None
    assert last["run_id"] == "run_9"
    assert seen == [{"unit_cap": 5}]


def test_interrupted_get_returns_json_and_is_clean_on_a_fresh_project(hub: tuple[int, str]) -> None:
    port, _ = hub
    status, text = _request(port, "GET", "/api/queue/interrupted")
    assert status == 200, text
    payload = json.loads(text)
    assert payload["is_clean"] is True
    assert payload["runs"] == []
    assert payload["last_resume"] is None


# --- the queue page -------------------------------------------------------------------------


def test_queue_page_shows_the_panel_and_escapes_text(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = Interrupted(
        runs=[
            InterruptedRun(
                run_id="<script>x</script>",
                stage="screen",
                model="haiku",
                prompt_blob="b",
                started_at="t",
                kind="lost",
                stage_pending=True,
            )
        ],
        pipelines=[],
        leases=[],
        passes=[],
        automatic=AutomaticLeft(),
    )
    monkeypatch.setattr(site_queue, "interrupted", lambda p, **_: found)
    out = tmp_path / "queue"
    out.mkdir()
    site_queue.build_queue(project, out)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "<h2>Interrupted</h2>" in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "<script>x" not in html
    assert "id=resume-preview" in html
    assert "id=resume-go disabled" in html


def test_queue_page_says_unavailable_when_the_read_fails(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(p: Project, **_: Any) -> Interrupted:
        raise RuntimeError("index unreadable")

    monkeypatch.setattr(site_queue, "interrupted", boom)
    out = tmp_path / "queue"
    out.mkdir()
    site_queue.build_queue(project, out)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "<li>unavailable</li>" in html


# --- the dashboard line ---------------------------------------------------------------------


def test_dashboard_counts_the_interrupted_work(project: Project) -> None:
    counts = dashboard_service._interrupted(project)
    assert counts == {
        "clean": True,
        "runs": 0,
        "pipelines": 0,
        "leases": 0,
        "passes": 0,
        "resolve": 0,
        "fetch": 0,
        "convert": 0,
    }


def test_dashboard_reads_that_fail_show_unavailable(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(p: Project, **_: Any) -> Interrupted:
        raise RuntimeError("index unreadable")

    monkeypatch.setattr(resume_service, "interrupted", boom)
    assert dashboard_service._interrupted(project) == "unavailable"


def test_dashboard_page_has_the_interrupted_line() -> None:
    from factory.services import dashboard_page

    page = dashboard_page.render_page({"feed": {"interrupted": {"clean": True}}})
    assert "Interrupted (factory resume --dry-run shows the plan)" in page

"""The verification and release tools and the `factory draft` commands (plan W-B, task 7).

No tool audits. A pass session is refused every tool, role-blind before a pass opens. The agent's
`draft_status` and `draft_render` carry no audit result; the researcher's commands do.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.model.drafts import AuditLabel, DraftKind, Verdict
from factory.services.context import Project
from factory.services.draft_audit import draw_audit, open_audit_items, record_audit
from factory.services.draft_verify import verify_next
from factory.services.drafts import create_draft, write_sentences
from factory.services.project import init_project
from factory.services.tasks import task_counts
from tests.cli_helpers import _env
from tests.draft_b_helpers import (
    LOREM,
    QUOTE,
    SYNTH,
    V1,
    W1,
    Written,
    ctr_a,
    ctr_b,
    ext_a,
    ext_b,
    screened,
    sent,
    verdict_on,
    verifier,
    verify_all,
    verify_one,
    wd,
    writer,
    ww,
)
from tests.extraction_helpers import SESSION_A
from tests.helpers import install_skill, open_session
from tests.test_mcp_cards import _session
from tests.writing_helpers import WWorld

READER = "01JZ9Q3K5M7N8P0R2S4T6V8W31"
AS = {"role": "verifier", "model": "claude-opus-5-5", "skill": "rf-verify"}
runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def labelled(project: Project, draft: str, wrong: int = 0) -> None:
    audit = draw_audit(project, draft)
    for i, (_, verdict) in enumerate(open_audit_items(project, draft)):
        chosen = AuditLabel.INCORRECT if i < wrong else AuditLabel.CORRECT
        record_audit(project, audit, verdict, chosen, None, actor=project.human_actor())


@pytest.mark.anyio
async def test_verify_status_render_release_flow(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    wd: Written,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-verify")
    _session(monkeypatch, V1)
    async with open_session(settings, clock) as client:
        for _ in range(2):
            served = await client.call("draft_verify_next", project="demo", draft_id=wd.draft, **AS)
            unit = served["data"]["unit"]
            support = unit["supports"][0]
            recorded = await client.call(
                "draft_verify_record",
                project="demo",
                task_id=unit["task_id"],
                verdict="supported",
                support_spans=[{"ref": support["ref"], "substring": QUOTE}],
                **AS,
            )
            assert recorded["ok"] is True, recorded
        done = await client.call("draft_verify_next", project="demo", draft_id=wd.draft, **AS)
        assert done["data"]["unit"] is None
    # a session that verified the draft may not read its status or rendering (70b3d98): another does
    _session(monkeypatch, READER)
    async with open_session(settings, clock) as client:
        status = await client.call("draft_status", project="demo", draft_id=wd.draft)
        assert [s["status"] for s in status["data"]["sentences"]] == [
            "supported",
            "structural",
            "supported",
        ]
        refused = await client.call("draft_release", project="demo", draft_id=wd.draft, **AS)
        assert refused["ok"] is False
        labelled(project, wd.draft, wrong=1)
        status = await client.call("draft_status", project="demo", draft_id=wd.draft)
        assert status["data"]["audit"] == {
            "drawn": 2,
            "labelled": 2,
            "incorrect": None,
            "rate": None,
            "above_ceiling": None,
            "outdated": False,
            "all_drawn": 2,
            "all_labelled": 2,
            "all_incorrect": None,
            "all_rate": None,
        }
        assert "flagged" not in repr(status["data"]["sentences"])  # the label stays withheld
        clean = await client.call("draft_render", project="demo", draft_id=wd.draft, mode="clean")
        assert "error rate" not in clean["data"]["text"] and LOREM in clean["data"]["text"]
        review = await client.call("draft_render", project="demo", draft_id=wd.draft)
        assert QUOTE in review["data"]["text"]
        bad = await client.call("draft_render", project="demo", draft_id=wd.draft, mode="x")
        assert bad["ok"] is False
        released = await client.call("draft_release", project="demo", draft_id=wd.draft, **AS)
        assert released["ok"] is True


@pytest.mark.anyio
async def test_a_bad_verdict_is_refused_with_nothing_written(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    wd: Written,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-verify")
    _session(monkeypatch, V1)
    before = None
    async with open_session(settings, clock) as client:
        served = await client.call("draft_verify_next", project="demo", draft_id=wd.draft, **AS)
        task = served["data"]["unit"]["task_id"]
        before = project.index.head()
        for args in (
            {"verdict": "maybe"},
            {"verdict": "supported", "support_spans": [{"ref": "x"}]},
            {"verdict": "supported"},
        ):
            out = await client.call(
                "draft_verify_record", project="demo", task_id=task, **args, **AS
            )
            assert out["ok"] is False
    assert project.index.head() == before


@pytest.mark.anyio
async def test_a_writer_session_is_refused(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    wd: Written,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-verify")
    _session(monkeypatch, W1)
    async with open_session(settings, clock) as client:
        out = await client.call("draft_verify_next", project="demo", draft_id=wd.draft, **AS)
    assert out["ok"] is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("draft_verify_next", {"draft_id": "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99", **AS}),
        (
            "draft_verify_record",
            {"task_id": "tsk_01JZ9Q3K5M7N8P0R2S4T6V8W99", "verdict": "supported", **AS},
        ),
        ("draft_render", {"draft_id": "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99"}),
        ("draft_release", {"draft_id": "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99", **AS}),
    ],
)
async def test_pass_sessions_are_refused(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    wd: Written,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    args: dict[str, Any],
) -> None:
    install_skill(settings, "rf-verify")
    _session(monkeypatch, SESSION_A)  # the session of extraction pass A
    async with open_session(settings, clock) as client:
        out = await client.call(tool, project="demo", **args)
    assert out["ok"] is False
    assert out["errors"][0]["field"] == "session"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("draft_verify_next", {"draft_id": "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99", **AS}),
        (
            "draft_verify_record",
            {"task_id": "tsk_01JZ9Q3K5M7N8P0R2S4T6V8W99", "verdict": "supported", **AS},
        ),
        ("draft_render", {"draft_id": "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99"}),
        ("draft_release", {"draft_id": "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99", **AS}),
    ],
)
async def test_refused_before_a_pass_opens(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    tool: str,
    args: dict[str, Any],
) -> None:
    install_skill(settings, "rf-verify")
    async with open_session(settings, clock) as client:
        out = await client.call(tool, project="demo", **args)
    assert out["ok"] is False
    assert out["errors"][0]["reason"] == "not available yet"  # role-blind, saying nothing of seeds


@pytest.mark.anyio
async def test_release_is_refused_over_mcp_in_systematic(
    settings: Settings, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = init_project(settings, "strict", "systematic", session=W1, clock=clock)
    draft = create_draft(project, title="N", kind=DraftKind.OTHER, actor=project.human_actor())
    monkeypatch.setattr(mcp_server, "_require_pass_opened", lambda *_a: None)
    install_skill(settings, "rf-verify")
    async with open_session(settings, clock) as client:
        out = await client.call("draft_release", project="strict", draft_id=draft, **AS)
    assert out["ok"] is False
    assert out["errors"][0]["reason"] == "in this mode a draft is released at the terminal"


def test_cli_status_audit_label_release(settings: Settings, project: Project, wd: Written) -> None:
    root = settings.root
    code, out, _ = _run(root, "draft", "status", wd.draft)
    assert code == 0 and "unchecked 2" in out and "audit: none drawn" in out
    verify_all(project, wd.draft)
    code, out, _ = _run(root, "draft", "audit", wd.draft, "--draw")
    assert code == 0 and "drew dau_" in out and "0/2 labelled" in out and "unlabelled" in out
    code, _, err = _run(root, "draft", "release", wd.draft)
    assert code != 0 and "unlabelled" in err
    items = open_audit_items(project, wd.draft)
    audit = items[0][0]
    code, _, _ = _run(root, "draft", "label", audit, items[0][1], "--incorrect", "--note", "no")
    assert code == 0
    code, _, _ = _run(root, "draft", "label", audit, items[1][1], "--correct")
    assert code == 0
    code, _, err = _run(root, "draft", "label", audit, items[1][1])
    assert code != 0 and "label" in err
    code, out, _ = _run(root, "draft", "status", wd.draft)
    assert "rate 0.500" in out and "above the ceiling" in out and "audit-incorrect" in out
    code, out, _ = _run(root, "draft", "release", wd.draft)
    assert code == 0 and "released" in out
    assert _run(root, "draft", "status", "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99")[0] != 0


def test_cli_render_review_clean_and_out(
    settings: Settings, project: Project, wd: Written, tmp_path: Path
) -> None:
    root = settings.root
    verify_one(project, wd.draft, Verdict.OVERSTATED)
    code, out, _ = _run(root, "draft", "render", wd.draft)
    assert code == 0 and QUOTE in out and "{flagged; overstated}" in out
    code, out, _ = _run(root, "draft", "render", wd.draft, "--clean")
    assert code == 0 and "[[UNSUPPORTED: flagged; overstated]]" in out
    target = tmp_path / "elsewhere.md"
    assert _run(root, "draft", "render", wd.draft, "--out", str(target))[0] == 0
    assert QUOTE in target.read_text("utf-8")


def test_cli_render_refuses_a_path_under_the_project(
    settings: Settings, project: Project, wd: Written
) -> None:
    inside = project.paths.dir / "draft.md"
    code, _, err = _run(settings.root, "draft", "render", wd.draft, "--out", str(inside))
    assert code != 0 and "under the project" in err and not inside.exists()


def test_cli_bibtex_of_a_draft(settings: Settings, project: Project, wd: Written) -> None:
    code, out, _ = _run(settings.root, "export", "bibtex", "--scope", f"draft:{wd.draft}")
    assert code == 0 and out.count("@") == 2


def test_cli_human_verifies_an_agents_sentence(
    settings: Settings, project: Project, wd: Written
) -> None:
    root = settings.root
    args = (
        "draft",
        "verify",
        wd.draft,
        "--verdict",
        "unsupported",
        "--sentence-span",
        "Lorem is described",
    )
    code, out, _ = _run(root, *args)
    assert code == 0 and LOREM in out and "recorded svd_" in out
    verdicts = [
        e for e in read_all(project.paths.events_dir, project.catalog) if e.type == "draft.verified"
    ]
    assert [e.actor.kind for e in verdicts] == ["human"]
    code, _, err = _run(
        root,
        "draft",
        "write",
        wd.draft,
        "--section",
        wd.section,
        "--class",
        "structural",
        "--text",
        "Scope follows",
    )
    assert code != 0 and "session" in err  # the human is a verifier of this draft now


def test_cli_verify_refusals(settings: Settings, project: Project, wd: Written) -> None:
    root = settings.root
    # the spans are asked for after the unit is shown (bf5c7d0): pass them, or no refusal is reached
    both = ("--sentence-span", "Lorem is described", "--support-span", "x=Lorem ipsum")
    code, _, err = _run(root, "draft", "verify", wd.draft, "--verdict", "maybe", *both)
    assert code != 0 and "verdict" in err
    code, _, err = _run(
        root,
        "draft",
        "verify",
        wd.draft,
        "--verdict",
        "partial",
        "--sentence-span",
        "",
        "--support-span",
        "x=Lorem ipsum",
    )
    assert code != 0 and "sentence_span" in err


def test_cli_verify_says_when_none_is_left(settings: Settings, project: Project) -> None:
    draft = create_draft(project, title="N", kind=DraftKind.OTHER, actor=project.human_actor())
    code, out, _ = _run(settings.root, "draft", "verify", draft)
    assert code == 0 and "none left" in out


def test_cli_on_a_fresh_project(settings: Settings, project: Project) -> None:
    draft = create_draft(project, title="N", kind=DraftKind.OTHER, actor=project.human_actor())
    code, out, _ = _run(settings.root, "draft", "status", draft)
    assert code == 0 and "no sentences" in out
    code, out, _ = _run(settings.root, "draft", "render", draft, "--clean")
    assert code == 0 and "No sentences." in out
    code, _, err = _run(settings.root, "draft", "audit", draft, "--draw")
    assert code != 0 and "audit" in err

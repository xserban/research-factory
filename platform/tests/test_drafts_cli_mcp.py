"""The writing MCP tools, the `factory draft` / `factory outline` commands and the architecture
rule (slice 7b, plan W-A, task 6).

An agent reads the outline, creates a draft, pulls slots and writes sentences; the verification
and release tools are plan W-B's. None of them sets a status, a flag, a stat value or a citation
key. Every tool is refused to a pass session and role-blind before a pass opens.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from mcp import Client
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.mcp.server import build_server
from factory.model.drafts import DraftKind, SentenceClass
from factory.services.context import Project
from factory.services.drafts import (
    SentenceInput,
    create_draft,
    list_drafts,
    live_sentences,
    write_sentences,
)
from factory.services.outline import build_outline, outline_json
from factory.services.seeds import SeedRole, all_seeds
from tests.cli_helpers import _env
from tests.contribution_helpers import ctr_a, ctr_b, ext_a, screened
from tests.extraction_helpers import SESSION_A
from tests.helpers import install_skill, open_session
from tests.intuition_separation import imports_of, package_dirs, package_modules
from tests.test_mcp_cards import _session
from tests.views_b_helpers import ext_b
from tests.writing_helpers import WWorld, audit_above_ceiling, ww

TOOLS = (
    "writing_outline",
    "draft_create",
    "draft_next",
    "draft_write",
    "draft_status",
    "draft_verify_next",
    "draft_verify_record",
    "draft_render",
    "draft_release",
    "draft_list",  # read-only list (b299847, PROJECT_READ in services/access.py)
    "draft_repin",  # c0504e1, WORK_RUN
    "draft_reorder",  # c0504e1, WORK_RUN
)
WRITER = "01JZ9Q3K5M7N8P0R2S4T6V8W1W"
AS = {"role": "writer", "model": "claude-sonnet-5-5", "skill": "rf-write"}
LOREM = "Lorem is described in the method section"
runner = CliRunner()


def _of(project: Project, *kinds: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in kinds]


@pytest.mark.anyio
async def test_tool_list_pins_the_writing_tools(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    async with Client(build_server(settings, clock=clock)) as client:
        names = [t.name for t in (await client.list_tools()).tools]
    related = [n for n in names if n.startswith(("writing_", "draft_"))]
    assert sorted(related) == sorted(TOOLS)
    for name in related:  # no tool audits (spec: the audit is the researcher's)
        assert not any(w in name for w in ("audit", "label", "withdraw"))


@pytest.mark.anyio
async def test_outline_create_next_write_status_flow(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    ww: WWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-write")
    _session(monkeypatch, WRITER)
    async with open_session(settings, clock) as client:
        outline = await client.call("writing_outline", project="demo")
        created = await client.call(
            "draft_create", project="demo", title="Related work", kind="related-work", **AS
        )
        draft = created["data"]["draft_id"]
        slot = await client.call("draft_next", project="demo", draft_id=draft, **AS)
        body = slot["data"]["slot"]
        written = await client.call(
            "draft_write",
            project="demo",
            draft_id=draft,
            task_id=body["task_id"],
            sentences=[
                {
                    "section_id": body["section_id"],
                    "class": "claim",
                    "text": LOREM,
                    "supports": [ww.claim(0)],
                },
                {  # an inferred edge: refused alone
                    "section_id": body["section_id"],
                    "class": "claim",
                    "text": "It builds on the earlier work",
                    "supports": [ww.claim(1), f"edge:{ww.inferred_edge}"],
                },
                {"section_id": body["section_id"], "class": "poem", "text": "x"},
                {"section_id": body["section_id"], "class": "claim", "text": "y", "extra": 1},
            ],
            **AS,
        )
        status = await client.call("draft_status", project="demo", draft_id=draft)
        unknown = await client.call("draft_status", project="demo", draft_id="drf_nope")
        bad_kind = await client.call("draft_create", project="demo", title="t", kind="novel", **AS)
    assert outline["ok"] is True and outline["data"]["outline_id"].startswith("OL@")
    assert created["ok"] is True and slot["ok"] is True
    assert any(  # the slot shows the verified quote of a support, as a task for the writer
        "Lorem ipsum dolor sit amet." in s["quotes"] for s in body["content"]["supports"]
    )
    assert written["ok"] is True and len(written["data"]["written"]) == 1
    rejected = {r["index"]: r["issues"] for r in written["data"]["rejected"]}
    assert sorted(rejected) == [1, 2, 3]
    assert rejected[1] == [{"field": "supports[1]", "reason": "inferred"}]
    assert rejected[2][0]["field"] == "sentences.2.cls"
    assert rejected[3][0]["field"] == "sentences.3.extra"
    [row] = status["data"]["sentences"]
    assert row["class"] == "claim" and row["status"] == "unchecked" and row["text"] == LOREM
    assert unknown["ok"] is False and unknown["errors"][0]["field"] == "draft_id"
    assert bad_kind["ok"] is False and bad_kind["errors"][0]["field"] == "kind"
    for event in _of(project, "draft.created", "draft.sentence_recorded"):
        assert event.actor.kind == "agent" and event.input_blob is not None
        assert event.actor.skill is not None and event.actor.skill.startswith("rf-write@")


@pytest.mark.anyio
async def test_a_refusal_carries_no_document_text(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    ww: WWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-write")
    _session(monkeypatch, WRITER)
    async with open_session(settings, clock) as client:
        draft = (await client.call("draft_create", project="demo", title="t", kind="other", **AS))[
            "data"
        ]["draft_id"]
        out = await client.call(
            "draft_write",
            project="demo",
            draft_id=draft,
            sentences=[
                {
                    "section_id": "sec_01",
                    "class": "claim",
                    "text": "Lorem ipsum dolor sit amet reaches 77. A second sentence",
                    "supports": [ww.claim(0)],
                }
            ],
            **AS,
        )
    text = json.dumps(out)
    assert "Lorem ipsum" not in text and "77" not in text
    assert {i["reason"] for r in out["data"]["rejected"] for i in r["issues"]} >= {
        "number-unsupported",
        "more-than-one-sentence",
    }


@pytest.mark.anyio
async def test_pass_session_is_refused(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    ww: WWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-write")
    _session(monkeypatch, SESSION_A)  # an extraction-pass session of the evidence world
    async with open_session(settings, clock) as client:
        outs = [
            await client.call("writing_outline", project="demo"),
            await client.call("draft_create", project="demo", title="t", kind="other", **AS),
            await client.call("draft_next", project="demo", draft_id="drf_x", **AS),
            await client.call("draft_write", project="demo", draft_id="drf_x", sentences=[], **AS),
            await client.call("draft_status", project="demo", draft_id="drf_x"),
        ]
    for out in outs:
        assert out["ok"] is False and out["errors"][0]["field"] == "session", out
    assert _of(project, "draft.created") == []


@pytest.mark.anyio
async def test_tools_are_role_blind_before_a_pass_opens(
    settings: Settings, project: Project, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_skill(settings, "rf-write")
    _session(monkeypatch, WRITER)
    async with open_session(settings, clock) as client:
        outs = [
            await client.call("writing_outline", project="demo"),
            await client.call("draft_create", project="demo", title="t", kind="other", **AS),
            await client.call("draft_next", project="demo", draft_id="drf_x", **AS),
            await client.call("draft_write", project="demo", draft_id="drf_x", sentences=[], **AS),
            await client.call("draft_status", project="demo", draft_id="drf_x"),
        ]
    assert {(o["ok"], o["errors"][0]["reason"]) for o in outs} == {(False, "not available yet")}


@pytest.mark.anyio
async def test_writing_outline_is_the_agent_variant(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    ww: WWorld,
    other_session_human: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_above_ceiling(project, other_session_human)
    full = outline_json(build_outline(project, agent=False))
    assert "audit-above-ceiling" in full  # the control: the researcher's variant says it
    _session(monkeypatch, WRITER)
    async with open_session(settings, clock) as client:
        out = await client.call("writing_outline", project="demo")
    assert out["ok"] is True
    assert "audit-above-ceiling" not in json.dumps(out)
    assert "audit-reported-to-researcher" in json.dumps(out)


@pytest.mark.anyio
async def test_a_held_out_seed_token_does_not_reach_an_agent(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    ww: WWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = next(s.seed_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT)
    me = project.human_actor()
    draft = create_draft(project, title="t", kind=DraftKind.OTHER, actor=me)
    sentence = SentenceInput(
        section_id="sec_01", cls=SentenceClass.STRUCTURAL, text=f"The scope names {token} here"
    )
    assert write_sentences(project, draft, [sentence], actor=me).written
    install_skill(settings, "rf-write")
    _session(monkeypatch, WRITER)
    async with open_session(settings, clock) as client:
        outline = await client.call("writing_outline", project="demo", scope_works=[token])
        slot = await client.call(
            "draft_next", project="demo", draft_id=draft, section_id="sec_01", **AS
        )
        status = await client.call("draft_status", project="demo", draft_id=draft)
    for out in (outline, slot, status):
        assert out["ok"] is True, out
        assert token not in json.dumps(out)
    assert "[withheld]" in json.dumps(status)  # the writer's own sentence, scrubbed


# --- CLI ---


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_cli_outline_on_a_fresh_project(settings: Settings, project: Project) -> None:
    code, out, _ = _run(settings.root, "outline")
    assert code == 0 and "limits" in out and "no-extraction" in out
    code, out, _ = _run(settings.root, "outline", "--json")
    assert code == 0 and json.loads(out)["outline_id"].startswith("OL@")
    code, out, _ = _run(settings.root, "draft", "list")
    assert code == 0 and out.strip() == "no drafts"


def test_cli_outline_is_the_researchers_complete_variant(
    settings: Settings, project: Project, ww: WWorld
) -> None:
    code, out, _ = _run(settings.root, "outline", "--json")
    assert code == 0
    assert out == outline_json(build_outline(project, agent=False))


def test_cli_draft_flow_human_author(settings: Settings, project: Project, ww: WWorld) -> None:
    root = settings.root
    code, out, _ = _run(root, "draft", "create", "--title", "Notes", "--kind", "review")
    assert code == 0 and out.startswith("created drf_")
    draft = out.split()[1]
    assert _run(root, "draft", "create", "--title", "x", "--kind", "novel")[0] == 1
    code, out, _ = _run(
        root, "draft", "write", draft, "--section", "sec_01", "--class", "claim",
        "--text", LOREM, "--support", ww.claim(0),
    )  # fmt: skip
    assert code == 0 and out.startswith("wrote snt_")
    sentence = out.split()[1]
    code, out, err = _run(
        root, "draft", "write", draft, "--section", "sec_01", "--class", "claim",
        "--text", "It scores 99 here", "--support", ww.claim(0),
    )  # fmt: skip
    assert code == 1 and "text.numbers[0]: number-unsupported" in err
    code, out, _ = _run(root, "draft", "show", draft)
    assert code == 0 and LOREM in out and "claim  unchecked  (human)" in out
    assert ww.claim(0) in out and "Lorem ipsum" not in out
    (row,) = live_sentences(project, draft)
    assert (row.author, row.model) == ("human", None)
    assert _run(root, "draft", "show", "drf_01JZ9Q3K5M7N8P0R2S4T6V8W99")[0] == 1
    code, out, _ = _run(root, "draft", "withdraw", sentence, "--reason", "not needed")
    assert code == 0 and live_sentences(project, draft) == []
    assert _run(root, "draft", "withdraw", sentence, "--reason", "again")[0] == 1
    code, out, _ = _run(root, "draft", "list")
    assert draft in out and "review" in out


# --- Architecture ---

WRITING_MODULES = frozenset({"factory.services.drafts", "factory.services.supports"})
WRITING_IMPORTERS = frozenset(
    {
        "factory.services.drafts",
        "factory.services.supports",
        "factory.services.draft_verify",
        "factory.services.draft_release",
        "factory.services.exports",  # the bibliography scope `draft:<drf_...>` (plan W-B)
        "factory.services.check",  # the draft findings (plan W-B)
        "factory.writing.checks",  # a type-only import of ResolvedSupport
        "factory.writing.render",  # a type-only import of DraftView and StatusRow
        # Not evidence outputs (slice 3c acceptance 3 lists them; slice 7b makes briefings
        # builders): the briefing lists draft status (d486034), and trace refuses a verifying
        # session the drafts it would walk (5941c14).
        "factory.services.briefing",
        "factory.services.trace",
        "factory.mcp.server",
        "factory.cli.main",
        "factory.cli.render",
    }
)


def writing_offenders(modules: dict[str, ast.Module]) -> list[tuple[str, str]]:
    return sorted(
        (importer, imported)
        for importer, imported in imports_of(modules, packages=package_dirs())
        if imported in WRITING_MODULES and importer not in WRITING_IMPORTERS
    )


def test_no_evidence_output_imports_the_writing_services() -> None:
    assert writing_offenders(package_modules()) == []


def test_the_architecture_rule_fails_when_an_evidence_service_imports_drafts() -> None:
    modules = package_modules()
    modules["factory.services.evidence_report"] = ast.parse(
        "from factory.services import drafts\n"
        "from factory.services.supports import resolve_supports"
    )
    assert writing_offenders(modules) == [
        ("factory.services.evidence_report", "factory.services.drafts"),
        ("factory.services.evidence_report", "factory.services.supports"),
    ]

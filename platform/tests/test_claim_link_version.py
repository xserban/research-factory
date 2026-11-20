"""Claim-link version flag: a sheet argument shows today's claim row and flags a changed or
missing row (no events, no projection change)."""

# ruff: noqa: F811
import re
from dataclasses import replace
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.events.envelope import Actor
from factory.model.screening import PassLabel
from factory.services import hub_chat
from factory.services import sheet_export as ex
from factory.services import sheets as sh
from factory.services.chat_candidates import CandidateInput as C
from factory.services.context import Project
from factory.services.selection import SelectionSpec
from tests.claims_helpers import QUOTES, claim_row, claims_spec
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)
from tests.miner_helpers import list_miner, mine_pass, miner_actor

ANCHOR, QUOTE = "s3.p1", "Lorem ipsum"


def _setup(project: Project, agent: Actor, world: list[str]) -> tuple[str, str]:
    from factory.model.extraction import MinerScope
    from factory.services.extraction import live_rows

    list_miner(project, agent, claims_spec())
    mina = miner_actor("01JZ9Q3K5M7N8P0R2S4T6V8W1E", "claude-opus-5-5")
    mine_pass(
        project, mina, PassLabel.A, lambda w: [claim_row("finding", QUOTES[0])], name="m-claims"
    )
    work = sorted(world)[0]
    sheet = sh.open_sheet(
        project,
        agent,
        "Reflection helps",
        SelectionSpec(),
        [C(work, "claims", "against", ANCHOR, QUOTE)],
        mode="explore",
    ).sheet_id
    key = next(
        r.row_key for r in live_rows(project, scope=MinerScope("m-claims")) if r.work_id == work
    )
    sh.record_arguments(
        project,
        agent,
        sheet,
        [
            sh.ArgumentInput(
                "against", work, ANCHOR, QUOTE, "it fails", "moderate", claim_row_key=key
            )
        ],
    )
    return sheet, work


def _serve(monkeypatch: pytest.MonkeyPatch, *, version: int | None) -> None:
    """Serve the claims rows today at `version` (None: the rows are gone)."""
    real = sh.load_miner_work_rows

    def fake(*a: Any, **kw: Any) -> Any:
        rows, rest = real(*a, **kw)
        if version is None:
            return {w: [] for w in rows}, rest
        return {w: [replace(r, version=version) for r in rs] for w, rs in rows.items()}, rest

    monkeypatch.setattr(sh, "load_miner_work_rows", fake)


def test_same_version_no_flag(project: Project, agent: Actor, world: list[str]) -> None:
    sheet, _ = _setup(project, agent, world)
    k = sh.view_sheet(project, sheet).arguments[0].linked_claim
    assert k is not None and k.recorded_version == k.version == 1
    assert not k.version_changed and not k.missing
    assert sh.claim_link_note(k) is None


def test_changed_version_flags_both(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet, _ = _setup(project, agent, world)
    _serve(monkeypatch, version=2)
    k = sh.view_sheet(project, sheet).arguments[0].linked_claim
    assert k is not None and k.version == 2 and k.recorded_version == 1
    assert k.version_changed and not k.missing and k.quote
    assert sh.claim_link_note(k) == "claim row changed: recorded v1, served v2"


def test_row_gone_is_missing(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet, _ = _setup(project, agent, world)
    _serve(monkeypatch, version=None)
    k = sh.view_sheet(project, sheet).arguments[0].linked_claim
    assert k is not None and k.missing and k.recorded_version == 1
    assert sh.claim_link_note(k) == "claim row no longer served"


def test_cli_show_prints_note(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.cli import main as cli_main

    sheet, _ = _setup(project, agent, world)
    monkeypatch.setattr(cli_main, "_resolve_project", lambda state: project)
    out = CliRunner().invoke(cli_main.app, ["sheets", "show", sheet]).output
    assert "claim row changed" not in out and "no longer served" not in out
    _serve(monkeypatch, version=2)
    out = CliRunner().invoke(cli_main.app, ["sheets", "show", sheet]).output
    assert "(claim row changed: recorded v1, served v2)" in out
    _serve(monkeypatch, version=None)
    out = CliRunner().invoke(cli_main.app, ["sheets", "show", sheet]).output
    assert "(claim row no longer served)" in out


def test_hub_payload_and_export(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet, _ = _setup(project, agent, world)
    assert hub_chat.sheet_view(project, sheet)["arguments"][0]["linked_claim"]["note"] is None
    _serve(monkeypatch, version=2)
    claim = hub_chat.sheet_view(project, sheet)["arguments"][0]["linked_claim"]
    assert claim["note"] == "claim row changed: recorded v1, served v2"
    assert claim["version_changed"] is True and claim["recorded_version"] == 1
    md = ex.export_sheet(project, sheet)
    assert re.search(r"claim row changed: recorded v1, served v2", md)
    _serve(monkeypatch, version=None)
    claim = hub_chat.sheet_view(project, sheet)["arguments"][0]["linked_claim"]
    assert claim["missing"] is True and claim["note"] == "claim row no longer served"
    assert "claim row no longer served" in ex.export_sheet(project, sheet)

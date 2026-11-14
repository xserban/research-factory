"""The inputs IDEA-66 missed take the composed spelling of a work id too (review 2026-11-14).

The world is the Korean-work world of `test_work_ids_nfc_inputs`. Where an input sits behind a
world too heavy to build here (miner calibration, extraction audit), the test spies on the
resolver and checks the call refuses at the step after it, not on the work id.
"""

# ruff: noqa: F811
from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mcp.server import build_server
from factory.model.screening import Channel
from factory.services import core_works, extraction_audit, miner_gold, work_ref
from factory.services import extraction_agreement as extraction_agreement_service
from factory.services.context import Project
from factory.services.fulltext_status import fulltext_status
from factory.services.lab_library import adoptable
from tests.test_work_ids_nfc_inputs import _composed, _payloads, stored  # noqa: F401


def _issue_fields(raised: pytest.ExceptionInfo[FactoryValidationError]) -> list[str]:
    return [i.field for i in raised.value.issues]


def test_core_mark_takes_the_composed_spelling(
    project: Project,
    human: Actor,
    stored: str,
) -> None:
    core_works.mark_core(project, human, _composed(stored), None)
    (payload,) = _payloads(project, "work.marked_core")
    assert payload["work_id"] == stored
    with pytest.raises(FactoryValidationError) as again:
        core_works.mark_core(project, human, _composed(stored), None)
    assert _issue_fields(again) == ["work_id"]  # already-core, found by the stored spelling


def test_core_unmark_takes_the_composed_spelling(
    project: Project,
    human: Actor,
    stored: str,
) -> None:
    core_works.mark_core(project, human, stored, None)
    core_works.unmark_core(project, human, _composed(stored), None)
    (payload,) = _payloads(project, "work.unmarked_core")
    assert payload["work_id"] == stored


def test_core_mark_still_refuses_an_unknown_work(
    project: Project,
    human: Actor,
    stored: str,
) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        core_works.mark_core(project, human, stored + "x", None)
    assert _issue_fields(raised) == ["work_id"]


def test_adoptable_takes_the_composed_spelling(project: Project, stored: str) -> None:
    assert adoptable(project, _composed(stored)) == []  # promoted, no other project holds it


def test_fulltext_status_takes_the_composed_spelling(
    project: Project,
    stored: str,
) -> None:
    report = fulltext_status(project, work_ids=[_composed(stored)])
    assert [w.work_id for w in report.works] == [stored]


def _spy(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    real = work_ref.resolve_work_id

    def spy(project: Project, work_id: str, *, field: str = "work_id") -> str:
        resolved = real(project, work_id, field=field)
        seen.append((work_id, resolved))
        return resolved

    monkeypatch.setattr(module, "resolve_work_id", spy)
    return seen


def test_miner_calibration_label_resolves_before_its_lookups(
    project: Project,
    human: Actor,
    stored: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _spy(monkeypatch, miner_gold)
    with pytest.raises(FactoryValidationError) as raised:
        miner_gold.label_miner_calibration(
            project, human, "mcal_none", _composed(stored), [], empty=True, channel=Channel.CLI
        )
    assert _issue_fields(raised) == ["calibration_id"]
    assert seen == [(_composed(stored), stored)]


def test_extraction_audit_record_resolves_before_its_lookups(
    project: Project,
    human: Actor,
    stored: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _spy(monkeypatch, extraction_audit)
    with pytest.raises(FactoryValidationError) as raised:
        extraction_audit.extraction_audit_record(
            project, human, "xau_none", _composed(stored), "rk", "value", True, "", Channel.CLI
        )
    assert "audit_id" in _issue_fields(raised)
    assert seen == [(_composed(stored), stored)]


def _body(res: CallToolResult) -> dict[str, Any]:
    block = res.content[0]
    assert isinstance(block, TextContent)
    body: dict[str, Any] = json.loads(block.text)
    return body


@pytest.mark.anyio
async def test_mine_resolve_passes_the_stored_spelling(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    stored: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    got: list[str] = []

    def fake(_project: Project, _actor: Actor, work_id: str, *_rest: Any, **_kw: Any) -> str:
        got.append(work_id)
        return "evt"

    monkeypatch.setattr(extraction_agreement_service, "resolve_extraction", fake)
    monkeypatch.setattr("factory.mcp.server._require_pass_opened", lambda *_a, **_k: None)
    server = build_server(settings, clock=clock)
    args = {
        "project": "demo",
        "miner": "m",
        "work_id": _composed(stored),
        "row_key": "rk",
        "choice": "a",
        "reason": "r",
        "role": "x",
        "model": "claude-sonnet-5-5",
        "skill": "rf-screen",
    }
    async with Client(server) as client:
        body = _body(await client.call_tool("mine_resolve", args))
    assert body["ok"] is True, body
    assert got == [stored]

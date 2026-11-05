"""The `report_evidence` MCP tool (plan E, task 8): parse, call a service, reply; read-only."""

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.model.project import RigorMode
from factory.services import check as check_service
from factory.services import evidence_report as evidence_report_service
from factory.services.check import CheckReport, Finding
from factory.services.context import Project
from factory.services.evidence_report import EvidenceReport, assemble_report
from factory.services.extraction_audit import ExtractionAuditReport
from tests.evidence_helpers import pilot_inputs
from tests.extraction_helpers import SESSION_A, _both, _r, ext_a, ext_b, screened, world  # noqa: F401
from tests.helpers import SESSION, open_session

FRESH = "01JZ9Q3K5M7N8P0R2S4T6V8W1C"


def _session(monkeypatch: pytest.MonkeyPatch, session: str) -> None:
    class Ids:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return session

    monkeypatch.setattr(mcp_server, "IdGenerator", Ids)


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _full() -> EvidenceReport:
    report = assemble_report(pilot_inputs())
    quality = report.quality.model_copy(
        update={"audit_error_rate": 0.25, "audit_above_ceiling": True}
    )
    return report.model_copy(update={"quality": quality})


@pytest.mark.anyio
async def test_refused_to_screening_and_extraction_pass_sessions(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    ext_a: Actor,  # noqa: F811
    ext_b: Actor,  # noqa: F811
    world: list[str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _both(project, ext_a, ext_b)
    for session in (SESSION, SESSION_A):
        _session(monkeypatch, session)
        async with open_session(settings, clock) as client:
            out = await client.call("report_evidence", project="demo")
        assert out["ok"] is False
        assert out["errors"][0]["field"] == "session"
    _session(monkeypatch, FRESH)
    async with open_session(settings, clock) as client:
        out = await client.call("report_evidence", project="demo")
    assert out["ok"] is True, out


@pytest.mark.anyio
async def test_agent_view_has_no_audit_rate(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evidence_report_service, "evidence_report", lambda _p, expect=(): _full())
    async with open_session(settings, clock) as client:
        out = await client.call("report_evidence", project="demo")
    assert out["ok"] is True, out
    assert out["data"]["quality"]["audit_error_rate"] is None
    assert out["data"]["quality"]["audit_above_ceiling"] is None


@pytest.mark.anyio
async def test_expect_returns_results_and_nothing_is_written(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    before = _count(project)
    async with open_session(settings, clock) as client:
        out = await client.call("report_evidence", project="demo", expect=[{"dataset": "coco"}])
    assert out["ok"] is True, out
    data = out["data"]
    assert data["expectations"][0]["expect"] == {"dataset": "coco"}
    assert data["expectations"][0]["group_ids"] == []
    assert any(lim["code"] == "expectation-empty" for lim in data["limits"])
    assert _count(project) == before


@pytest.mark.anyio
async def test_held_out_identifiers_are_withheld(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evidence_report_service, "evidence_report", lambda _p, expect=(): _full())
    # A held-out seed's DOI or identifier can reach the report only through a work title (work ids
    # stay visible by design, as in screening), so the scrub is exercised on a title token.
    monkeypatch.setattr(mcp_server, "_held_out_tokens", lambda _p, _w=True: {"Title 1"})
    async with open_session(settings, clock) as client:
        out = await client.call("report_evidence", project="demo")
    assert out["ok"] is True, out
    assert "Title 1" not in str(out)
    assert "[withheld]" in str(out)


@pytest.mark.anyio
async def test_malformed_expect_is_a_structured_error_and_writes_nothing(
    settings: Settings, project: Project, clock: FixedClock
) -> None:
    before = _count(project)
    async with open_session(settings, clock) as client:
        out = await client.call("report_evidence", project="demo", expect=[{"dataset": 3}])
    assert out["ok"] is False
    assert out["errors"][0]["field"] == "expect.0"
    assert _count(project) == before


@pytest.mark.anyio
@pytest.mark.parametrize("bad", [{}, {"dataset": ""}, {"dataset": "  "}])
async def test_empty_map_and_blank_value_are_refused(
    settings: Settings, project: Project, clock: FixedClock, bad: dict[str, str]
) -> None:
    async with open_session(settings, clock) as client:
        out = await client.call("report_evidence", project="demo", expect=[bad])
    assert out["ok"] is False
    assert out["errors"][0]["field"] == "expect.0"


@pytest.mark.anyio
@pytest.mark.parametrize("above", [True, False])
async def test_mcp_check_states_a_labelled_audit_without_its_flag(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
    above: bool,
) -> None:
    findings = (
        [Finding(code="extraction-error-high", severity="error", refs=["xau_1"], message="x")]
        if above
        else []
    )
    audit = ExtractionAuditReport(
        audit_id="xau_1",
        sample_size=40,
        labelled=40,
        incorrect=3 if above else 0,
        error_rate=0.075 if above else 0.0,
        ceiling=0.05,
        above_ceiling=above,
        enforced=True,
        by_group={},
    )
    report = CheckReport(mode=RigorMode.PILOT, evaluated_as=RigorMode.PILOT, findings=findings)
    monkeypatch.setattr(check_service, "check", lambda _p, promote_to=None: report)
    monkeypatch.setattr(check_service, "extraction_audit_report", lambda _p: audit)
    async with open_session(settings, clock) as client:
        out = await client.call("check", project="demo")
    assert out["ok"] is True, out
    data = out["data"]
    assert [f["code"] for f in data["findings"]] == ["extraction-audit-reported"]
    assert data["ok"] is True

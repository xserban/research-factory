"""The evidence note of a brief (lane L9): counts computed, quotes verified, label present."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.extraction import ExtractedRowInput, FieldInput
from factory.model.levels import Tier
from factory.model.screening import PassLabel
from factory.services import brief_note as note_module
from factory.services.brief_note import (
    NO_FINDINGS,
    brief_note,
    render_brief_note,
)
from factory.services.chat_read import VerifyItem, VerifyResult
from factory.services.context import Project
from factory.services.prisma import prisma_flow
from factory.services.project import init_project
from factory.sources.registry import SourceFactory
from factory.tiers import report_label
from tests.evidence_helpers import claim_input, run_pass
from tests.extraction_helpers import FIELDS, SESSION_A, SESSION_B, _declare, _extractor, _r
from tests.fulltext_helpers import _screened_full_text_world
from tests.helpers import SESSION

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _rows() -> list[ExtractedRowInput]:
    row = _r()
    row.fields["params"] = FieldInput(value="2", anchor="t1", cell="t1.r3.c3", quote="2")
    return [row]


@pytest.fixture
def world(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> Project:
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    _declare(project, agent, fields=(*FIELDS, "params"))
    ext_a = _extractor(SESSION_A, "claude-opus-5-5")
    ext_b = _extractor(SESSION_B, "claude-sonnet-5-5")
    run_pass(project, ext_a, PassLabel.A, lambda _w: _rows(), lambda _w: [claim_input()])
    run_pass(project, ext_b, PassLabel.B, lambda _w: _rows())
    return project


def test_counts_equal_the_prisma_flow(world: Project) -> None:
    note = brief_note(world)
    flow = prisma_flow(world)
    assert note.flow == flow
    text = render_brief_note(note)
    assert f"- screened: {flow.screened}" in text
    assert f"- included at title and abstract: {flow.included}" in text
    assert f"- duplicates removed: {flow.duplicates_removed}" in text
    assert note.works


def test_verified_quote_is_a_finding(world: Project) -> None:
    note = brief_note(world)
    assert note.verified_claims
    assert not note.unverified_claims
    text = render_brief_note(note)
    assert "## Findings with verified quotes" in text
    assert "Lorem ipsum dolor sit amet." in text
    assert NO_FINDINGS not in text


def test_unverified_quote_is_flagged_never_a_finding(
    world: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(project: Project, items: Sequence[VerifyItem]) -> list[VerifyResult]:
        return [VerifyResult(i, "quote-not-in-anchor", None, None) for i in items]

    monkeypatch.setattr(note_module, "chat_verify", reject)
    note = brief_note(world)
    assert not note.verified_claims
    assert note.unverified_claims
    text = render_brief_note(note)
    _, _, rest = text.partition("## Findings with verified quotes")
    section, _, after = rest.partition("## Unverified claims")
    assert NO_FINDINGS in section
    assert "Lorem ipsum dolor sit amet." not in section
    assert "UNVERIFIED" in after
    assert "quote-not-in-anchor" in after


def test_label_and_level_statement_are_present(settings: Settings, clock: FixedClock) -> None:
    project = init_project(settings, "demo", None, session=SESSION, clock=clock, tier="brief")
    text = render_brief_note(brief_note(project))
    assert report_label(Tier.BRIEF) in text
    assert "## Level" in text
    assert "tier: brief" in text
    assert "autonomy level: attended" in text
    assert "not a systematic review" in text


def test_empty_project_renders_an_honest_note(settings: Settings, clock: FixedClock) -> None:
    project = init_project(settings, "demo", None, session=SESSION, clock=clock, tier="brief")
    note = brief_note(project)
    assert note.empty
    text = render_brief_note(note)
    assert "No question recorded." in text
    assert "No included work has a final extracted row." in text
    assert NO_FINDINGS in text
    assert "None recorded." in text
    assert "- cap papers: 30" in text


def test_cli_note_is_read_only_and_prints_the_note(tmp_path: Path) -> None:
    env: dict[str, str | None] = {
        "FACTORY_ROOT": str(tmp_path),
        "FACTORY_USER": "obd",
        "FACTORY_PROJECT": None,
    }
    runner = CliRunner()
    made = runner.invoke(app, ["brief", "new", "Does it scale?", "--slug", "sc"], env=env)
    assert made.exit_code == 0, made.output
    result = runner.invoke(app, ["brief", "note", "sc"], env=env)
    assert result.exit_code == 0, result.output
    assert "# Evidence note" in result.output
    assert "Does it scale?" in result.output
    as_json = runner.invoke(app, ["brief", "note", "sc", "--format", "json"], env=env)
    assert as_json.exit_code == 0, as_json.output
    assert '"project":"sc"' in as_json.output

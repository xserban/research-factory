"""Rendering a level of the develop stage (slice 8, plan A9)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.decisions import DecisionItem, DecisionLevel
from factory.model.screening import Channel
from factory.services import decisions as decisions_service
from factory.services import develop_render as svc
from factory.services.context import Project
from tests.cli_helpers import _env

runner = CliRunner()

ITEMS = (
    DecisionItem(item_id="I01", text="Exclude preprints", grounds=("prb_1",)),
    DecisionItem(item_id="I02", text="Keep preprints"),
)


def _suggest(project: Project, agent: Actor, **over: object) -> str:
    args: dict[str, object] = {
        "level": DecisionLevel.GOAL,
        "subject": "objective",
        "explanation": "The objective fixes what the review is for.",
        "items": ITEMS,
    }
    args.update(over)
    return decisions_service.suggest(project, agent, **args)  # type: ignore[arg-type]


def _types(project: Project) -> list[str]:
    return [e.type for e in read_all(project.paths.events_dir, project.catalog)]


def test_empty_level_renders_and_records_version_one(project: Project) -> None:
    result = svc.render_level(project, DecisionLevel.GOAL)
    assert result.version == 1 and not result.unchanged
    assert "No decision is recorded for this level." in result.markdown
    assert _types(project).count("document.rendered") == 1
    assert [r["version"] for r in svc.renders(project)] == [1]


def test_items_status_note_and_supersession(project: Project, agent: Actor, human: Actor) -> None:
    first = _suggest(project, agent)
    decisions_service.select(project, human, first, ["I01"], ["Own item"], "My reason", Channel.CLI)
    second = _suggest(project, agent, supersedes=first)
    md, sources = svc.render_markdown(project, DecisionLevel.GOAL)
    assert "[Validated] Exclude preprints" in md
    assert "[Rejected] Keep preprints" in md
    assert "[Added] Own item" in md
    assert "Note of the scientist: My reason" in md
    assert "Grounds: none stated" in md
    assert f"Replaced by {second}." in md and f"Replaces {first}." in md
    assert md.index("## Decisions") < md.index("## Superseded decisions")
    assert "[Proposed] Exclude preprints" in md
    assert len(sources) == 3  # two suggestions and one selection
    assert list(sources) == sorted(sources)


def test_other_levels_are_not_mixed_in(project: Project, agent: Actor) -> None:
    _suggest(project, agent, level=DecisionLevel.PLAN, subject="review-method")
    md, sources = svc.render_markdown(project, DecisionLevel.GOAL)
    assert "review-method" not in md and sources == ()


def test_output_is_deterministic_and_an_unchanged_render_writes_nothing(
    project: Project, agent: Actor
) -> None:
    _suggest(project, agent)
    first = svc.render_level(project, DecisionLevel.GOAL)
    again = svc.render_level(project, DecisionLevel.GOAL)
    assert again.unchanged and again.version == 1 and again.event_id == first.event_id
    assert again.markdown == first.markdown and again.blob == first.blob
    assert _types(project).count("document.rendered") == 1
    _suggest(project, agent, subject="scope")
    changed = svc.render_level(project, DecisionLevel.GOAL)
    assert changed.version == 2 and not changed.unchanged
    other = svc.render_level(project, DecisionLevel.PLAN)
    assert other.version == 1


def test_blob_holds_the_markdown_and_rebuild_keeps_the_table(
    project: Project, agent: Actor
) -> None:
    _suggest(project, agent)
    result = svc.render_level(project, DecisionLevel.GOAL)
    assert project.blobs.get(result.blob).decode() == result.markdown
    before = project.index.state_hash()
    assert project.index.rebuild() == before
    assert len(svc.renders(project, DecisionLevel.GOAL)) == 1


def test_a_render_from_an_agent_or_with_a_skipped_version_changes_nothing(
    project: Project, agent: Actor
) -> None:
    from factory.model.develop import DocumentRendered

    result = svc.render_level(project, DecisionLevel.GOAL)
    base = DocumentRendered(level=DecisionLevel.GOAL, version=2, sources=(), blob=result.blob)
    forged = project.events.make("document.rendered", base, agent)
    skipped = project.events.make(
        "document.rendered", base.model_copy(update={"version": 5}), project.system_actor()
    )
    with project.writing():
        project.record([forged, skipped])
    assert [r["version"] for r in svc.renders(project)] == [1]


def test_a_malformed_render_payload_changes_nothing_and_rebuild_agrees(
    project: Project, agent: Actor
) -> None:
    from factory.model.develop import DocumentRendered

    result = svc.render_level(project, DecisionLevel.GOAL)
    bad = DocumentRendered.model_construct(
        level=DecisionLevel.GOAL, version=0, sources=(), blob=result.blob
    )
    event = project.events.make("document.rendered", bad, project.system_actor())
    before = project.index.state_hash()
    with project.writing():
        project.record([event])
    assert project.index.state_hash() == before
    assert project.index.rebuild() == before


def test_questions_level_shows_the_recorded_question(project: Project, agent: Actor) -> None:
    _suggest(project, agent, level=DecisionLevel.QUESTIONS, subject="main-question")
    md, _ = svc.render_markdown(project, DecisionLevel.QUESTIONS)
    assert "## Recorded question" in md and "No question is recorded." in md


def test_protocol_level_shows_the_recorded_protocol(project: Project, agent: Actor) -> None:
    md, _ = svc.render_markdown(project, DecisionLevel.PROTOCOL)
    assert "## Recorded protocol" in md and "No protocol is recorded." in md


def test_cli_render_prints_and_writes(
    settings: Settings, project: Project, agent: Actor, tmp_path: Path
) -> None:
    _suggest(project, agent)
    result = runner.invoke(app, ["develop", "render", "--level", "goal"], env=_env(settings.root))
    assert result.exit_code == 0 and "# Goal" in result.stdout
    out = tmp_path / "goal.md"
    result = runner.invoke(
        app,
        ["develop", "render", "--level", "goal", "--out", str(out)],
        env=_env(settings.root),
    )
    assert result.exit_code == 0 and "unchanged" in result.stdout
    assert out.read_text(encoding="utf-8").startswith("# Goal")
    bad = runner.invoke(app, ["develop", "render", "--level", "nope"], env=_env(settings.root))
    assert bad.exit_code == 1

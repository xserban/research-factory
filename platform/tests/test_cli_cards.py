"""The `factory vocabulary` and `factory cards` commands (slice 6, plan H-A, task 5): human acts."""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.services.cards import AssertionInput, assert_properties, create_card
from factory.services.context import Project
from factory.services.properties import decide_property, propose_property
from factory.services.question import current_question
from tests.card_helpers import CardWorld, cw, prop, quote_basis
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world
from tests.test_cli import _env

runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _of(project: Project, kind: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == kind]


def test_vocabulary_approve_writes_a_human_decision(
    settings: Settings, project: Project, agent: Actor
) -> None:
    propose_property(project, agent, prop("pr:sampling"))
    code, out, err = _run(settings.root, "vocabulary", "list")
    assert code == 0, err
    assert "vocabulary V@00000000" in out and "pr:sampling" not in out
    code, out, _ = _run(settings.root, "vocabulary", "list", "--all")
    assert "pr:sampling" in out and "proposed" in out
    code, _, err = _run(
        settings.root, "vocabulary", "approve", "pr:sampling", "--rationale", "fits the question"
    )
    assert code == 0, err
    [decided] = _of(project, "vocabulary.property_decided")
    assert decided.actor.kind == "human" and decided.payload["decision"] == "approve"
    code, out, _ = _run(settings.root, "vocabulary", "list")
    assert "pr:sampling" in out and "approved" in out and "V@00000000" not in out
    code, _, err = _run(settings.root, "vocabulary", "approve", "pr:nothing", "--rationale", "x")
    assert code == 1 and "nothing-to-decide" in err


def test_vocabulary_reject_merge_and_unmerge(
    settings: Settings, project: Project, agent: Actor, other_session_human: Actor
) -> None:
    for key in ("pr:sampling", "pr:sampling-2"):
        propose_property(project, agent, prop(key))
        decide_property(project, other_session_human, key, "approve", "ok")
    code, _, err = _run(
        settings.root, "vocabulary", "merge", "pr:sampling-2", "pr:sampling", "--reason", "same"
    )
    assert code == 0, err
    code, out, _ = _run(settings.root, "vocabulary", "list")
    assert "into pr:sampling" in out
    code, _, err = _run(
        settings.root, "vocabulary", "unmerge", "pr:sampling-2", "--reason", "split"
    )
    assert code == 0, err
    code, _, err = _run(
        settings.root, "vocabulary", "reject", "pr:sampling", "--rationale", "dropped"
    )
    assert code == 0, err
    assert [e.payload["decision"] for e in _of(project, "vocabulary.property_decided")][
        -1
    ] == "reject"


def test_cards_show_labels_inferred_and_stale_rows(
    settings: Settings,
    project: Project,
    agent: Actor,
    other_session_human: Actor,
    cw: CardWorld,
) -> None:
    card = create_card(project, agent, "method", cw.source, "obd")
    inferred = AssertionInput.model_validate(
        {
            "property": "pr:long-sequences",
            "value": True,
            "basis_kind": "inferred",
            "basis": {"note": "reasoned"},
        }
    )
    stated = AssertionInput(
        property="pr:attention-kind",
        value="linear",
        basis_kind="quote",
        basis=quote_basis(cw, "s1.p1", "linear attention"),
    )
    result = assert_properties(project, agent, card, [inferred, stated])
    assert len(result.accepted) == 2
    code, out, err = _run(settings.root, "cards", "list")
    assert code == 0, err
    assert card in out and "assertions 2" in out
    code, out, _ = _run(settings.root, "cards", "list", "--kind", "problem")
    assert out.strip() == "no cards"
    code, out, _ = _run(settings.root, "cards", "show", card)
    assert "pr:attention-kind = linear" in out and "stated" in out
    assert "pr:long-sequences" not in out and "not shown: 1 inferred" in out
    code, out, _ = _run(settings.root, "cards", "show", card, "--inferred")
    assert "pr:long-sequences = true" in out and "inferred" in out
    # a changed definition stales the stated assertion; the command shows it and says why
    changed = prop(
        "pr:attention-kind",
        allowed=["linear", "softmax", "hybrid"],
        applies_to="method",
        value_aliases={"linear": ["linear attention"]},
    )
    propose_property(project, agent, changed, supersedes="pr:attention-kind")
    decide_property(project, other_session_human, "pr:attention-kind", "approve", "adds hybrid")
    code, out, _ = _run(settings.root, "cards", "show", card)
    assert "stale" in out and "definition-changed" in out
    code, _, err = _run(settings.root, "cards", "show", "mcd_01JZ9Q3K5M7N8P0R2S4T6V8W1Z")
    assert code == 1 and "unknown card" in err


def test_cards_confirm_and_reject_write_human_events(
    settings: Settings, project: Project, agent: Actor, cw: CardWorld
) -> None:
    card = create_card(project, agent, "method", cw.source, "obd")
    inferred = AssertionInput.model_validate(
        {
            "property": "pr:long-sequences",
            "value": True,
            "basis_kind": "inferred",
            "basis": {"note": "reasoned"},
        }
    )
    [(_, pas, _)] = assert_properties(project, agent, card, [inferred]).accepted
    code, _, err = _run(settings.root, "cards", "confirm", pas, "--rationale", "checked")
    assert code == 0, err
    [decided] = _of(project, "card.assertion_decided")
    assert decided.actor.kind == "human" and decided.payload["decision"] == "confirm"
    code, out, _ = _run(settings.root, "cards", "show", card)
    assert "pr:long-sequences = true" in out and "confirmed (inferred)" in out
    code, _, err = _run(settings.root, "cards", "reject", pas, "--rationale", "wrong")
    assert code == 0, err
    code, _, err = _run(
        settings.root, "cards", "confirm", "pas_01JZ9Q3K5M7N8P0R2S4T6V8W1Z", "--rationale", "x"
    )
    assert code == 1 and "unknown" in err


def test_cards_assert_is_a_researcher_statement(
    settings: Settings, project: Project, agent: Actor, cw: CardWorld
) -> None:
    question = current_question(project)
    assert question is not None
    problem = create_card(project, agent, "problem", question.question_id, "obd")
    code, _, err = _run(
        settings.root,
        "cards",
        "assert",
        problem,
        "--property",
        "pr:dense-prediction",
        "--value",
        "true",
    )
    assert code == 2 and "--researcher" in err
    code, out, err = _run(
        settings.root,
        "cards",
        "assert",
        problem,
        "--property",
        "pr:dense-prediction",
        "--value",
        "true",
        "--researcher",
    )
    assert code == 0, err
    assert "stated" in out
    [event] = [e for e in _of(project, "card.asserted") if e.actor.kind == "human"]
    assert event.payload["basis_kind"] == "researcher" and event.payload["value"] is True
    code, out, _ = _run(settings.root, "cards", "show", problem)
    assert "pr:dense-prediction = true" in out
    code, _, err = _run(
        settings.root,
        "cards",
        "assert",
        problem,
        "--property",
        "pr:attention-kind",
        "--value",
        "linear",
        "--researcher",
    )
    assert code == 1 and "not-applicable" in err

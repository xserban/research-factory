"""The `factory interpretations`, `concepts` and `concept-links` commands and the layer options of
`factory graph` and `factory trace` (slice 3c, plan G3-C, task 5). Behaviour is the services';
these tests cover parsing, refusals, exit codes and what is printed."""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.reader import read_all
from factory.intuition.export import LAYER_NOTICE
from factory.model.intuition import ConceptInput, UseBasisInput
from factory.model.screening import Channel
from factory.services.concepts import (
    decide_concept_source,
    define_concept,
    propose_concept_link,
)
from factory.services.context import Project
from factory.services.interpretations import (
    intuition_next,
    record_interpretation,
    review_interpretation,
)
from tests.intuition_helpers import (
    WRITER_MODEL,
    IWorld,
    ctr_a,
    ctr_b,
    iw,
    lin,
    screened,
    world,
)
from tests.intuition_separation import populate_layer
from tests.test_cli import _env

runner = CliRunner()


def run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def events(project: Project) -> list[Any]:
    return read_all(project.paths.events_dir, project.catalog)


def layer_events(project: Project) -> list[Any]:
    return [e for e in events(project) if e.type.startswith(("interpretation.", "concept."))]


def agent_interpretation(project: Project, iw: IWorld, target: str | None = None) -> str:
    batch = intuition_next(project, iw.writer, targets=[target or iw.idea1]).batch
    assert batch is not None
    return record_interpretation(
        project, iw.writer, iw.entry(target or iw.idea1), task_id=batch.task_id
    )


def source_json(iw: IWorld, quote: str = "very long sequences degrade") -> str:
    return json.dumps(iw.quote(quote=quote))


TEXTBOOK = {"kind": "textbook", "citation": "Textbook, chapter 3"}


def agent_concept(project: Project, iw: IWorld, name: str = "softmax attention") -> str:
    return define_concept(
        project, iw.writer, ConceptInput.model_validate({"name": name, "source": TEXTBOOK})
    )


# --- interpretations ---


def test_review_wrong_without_note_fails_and_writes_nothing(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    """Review Focus 3."""
    ident = agent_interpretation(project, iw)
    before = len(events(project))
    code, _, err = run(settings.root, "interpretations", "review", ident, "--wrong")
    assert code != 0 and "note" in err
    assert len(events(project)) == before


def test_review_needs_exactly_one_verdict(settings: Settings, project: Project, iw: IWorld) -> None:
    ident = agent_interpretation(project, iw)
    before = len(events(project))
    assert run(settings.root, "interpretations", "review", ident)[0] != 0
    assert run(settings.root, "interpretations", "review", ident, "--reviewed", "--wrong")[0] != 0
    assert len(events(project)) == before


def test_review_records_a_human_event_on_the_cli_channel(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    ident = agent_interpretation(project, iw)
    code, out, err = run(
        settings.root, "interpretations", "review", ident, "--reviewed", "--note", "checked"
    )
    assert code == 0, err
    [event] = [e for e in events(project) if e.type == "interpretation.reviewed"]
    assert event.actor.kind == "human" and event.payload["channel"] == "cli"
    assert event.payload["state"] == "reviewed" and event.payload["note"] == "checked"
    assert ident in out and "reviewed" in out


def test_review_of_a_superseded_id_prints_the_reason(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    first = agent_interpretation(project, iw)
    code, _, err = run(
        settings.root,
        "interpretations",
        "supersede",
        first,
        "--text",
        "A human replacement.",
        "--source",
        source_json(iw),
    )
    assert code == 0, err
    code, _, err = run(settings.root, "interpretations", "review", first, "--reviewed")
    assert code != 0 and "superseded" in err


def test_list_hides_wrong_by_default_and_prints_the_hidden_count(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    populate_layer(project, iw)
    code, out, err = run(settings.root, "interpretations", "list")
    assert code == 0, err
    assert "interpretation · " in out and "hidden: wrong 1, superseded 1" in out
    code, wide, _ = run(
        settings.root, "interpretations", "list", "--state", "wrong", "--state", "superseded"
    )
    assert code == 0 and "interpretation · wrong" in wide and "interpretation · superseded" in wide
    assert run(settings.root, "interpretations", "list", "--state", "bogus")[0] != 0


def test_list_filters_by_target(settings: Settings, project: Project, iw: IWorld) -> None:
    populate_layer(project, iw)
    _, out, _ = run(settings.root, "interpretations", "list", "--target", iw.other)
    assert iw.other in out and iw.idea1 not in out


def test_show_prints_the_stored_quote_anchor_and_the_writer(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    ident = agent_interpretation(project, iw)
    code, out, err = run(settings.root, "interpretations", "show", ident)
    assert code == 0, err
    assert "very long sequences degrade" in out and "s1.p4" in out
    assert WRITER_MODEL in out and "interpretation · unreviewed" in out
    assert "input_blob" in out and "Long sequences are the stated limit" in out
    assert run(settings.root, "interpretations", "show", "int_01HZX3K4M5N6P7Q8R9S0T1V2WA")[0] != 0


def test_history_lists_each_step(settings: Settings, project: Project, iw: IWorld) -> None:
    ident = agent_interpretation(project, iw)
    review_interpretation(project, iw.human, ident, "reviewed", "checked", Channel.CLI)
    code, out, _ = run(settings.root, "interpretations", "history", ident)
    assert code == 0 and "recorded" in out and "reviewed" in out and "checked" in out


def test_write_is_human_authored_and_validates_sources(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    code, _out, err = run(
        settings.root,
        "interpretations",
        "write",
        "--target",
        iw.idea2,
        "--text",
        "Written by the researcher.",
        "--source",
        source_json(iw),
    )
    assert code == 0, err
    [event] = [e for e in events(project) if e.type == "interpretation.recorded"]
    assert event.actor.kind == "human" and event.payload["author"] == "human"
    before = len(events(project))
    code, _, err = run(
        settings.root,
        "interpretations",
        "write",
        "--target",
        iw.idea2,
        "--text",
        "Misquoted.",
        "--source",
        source_json(iw, "very long sequences improve"),
    )
    assert code != 0 and "quote-not-in-anchor" in err and "improve" not in err
    code, _, err = run(
        settings.root,
        "interpretations",
        "write",
        "--target",
        iw.idea2,
        "--text",
        "Bad JSON.",
        "--source",
        "{not json",
    )
    assert code != 0 and "source" in err
    assert len(events(project)) == before


# --- concepts ---


def test_concepts_define_approve_writes_two_events(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    code, _out, err = run(
        settings.root,
        "concepts",
        "define",
        "random-feature approximation",
        "--alias",
        "RFF",
        "--text",
        "A random map whose inner product approximates a kernel.",
        "--source-kind",
        "textbook",
        "--citation",
        "Textbook, chapter 3",
        "--approve",
    )
    assert code == 0, err
    types = [e.type for e in layer_events(project)]
    assert types == ["concept.defined", "concept.source_decided"]
    assert all(e.actor.kind == "human" for e in layer_events(project))


def test_concepts_approve_makes_the_concept_visible_labelled_unreviewed(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    cid = agent_concept(project, iw)
    _, before, _ = run(settings.root, "concepts", "list")
    assert cid not in before and "unapproved 1" in before
    code, _, err = run(settings.root, "concepts", "approve", cid)
    assert code == 0, err
    _, after, _ = run(settings.root, "concepts", "list")
    assert cid in after and "interpretation · unreviewed" in after
    _, everything, _ = run(settings.root, "concepts", "list", "--all")
    assert cid in everything


def test_concepts_review_and_the_wrong_note_rule(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    cid = agent_concept(project, iw)
    decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    before = len(events(project))
    code, _, err = run(settings.root, "concepts", "review", cid, "--wrong")
    assert code != 0 and "note" in err and len(events(project)) == before
    code, _, err = run(settings.root, "concepts", "review", cid, "--reviewed")
    assert code == 0, err
    [event] = [e for e in events(project) if e.type == "concept.reviewed"]
    assert event.actor.kind == "human" and event.payload["state"] == "reviewed"
    assert event.payload["channel"] == "cli"


def test_concepts_source_redefines_with_a_new_approved_source(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    cid = agent_concept(project, iw)
    code, _, err = run(
        settings.root,
        "concepts",
        "source",
        cid,
        "--source-kind",
        "survey",
        "--citation",
        "A survey, 2020",
    )
    assert code == 0, err
    _, out, _ = run(settings.root, "concepts", "show", cid)
    assert "A survey, 2020" in out and "approved" in out


def test_concepts_reject_source_needs_a_note(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    cid = agent_concept(project, iw)
    before = len(events(project))
    code, _, err = run(settings.root, "concepts", "reject-source", cid)
    assert code != 0 and len(events(project)) == before
    code, _, err = run(settings.root, "concepts", "reject-source", cid, "--note", "not a source")
    assert code == 0, err


def test_concepts_show_and_history(settings: Settings, project: Project, iw: IWorld) -> None:
    cid = agent_concept(project, iw)
    decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    code, out, _ = run(settings.root, "concepts", "show", cid)
    assert code == 0 and "softmax attention" in out and "Textbook, chapter 3" in out
    assert "interpretation · unreviewed" in out and "unverifiable-source" in out
    code, hist, _ = run(settings.root, "concepts", "history", cid)
    assert code == 0 and "recorded" in hist and "source-decided" in hist


def test_merge_then_unmerge_round_trips(settings: Settings, project: Project, iw: IWorld) -> None:
    keep = agent_concept(project, iw, "alpha")
    gone = agent_concept(project, iw, "beta")
    for cid in (keep, gone):
        decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    code, _, err = run(settings.root, "concepts", "merge", keep, gone, "--reason", "same idea")
    assert code == 0, err
    _, merged, _ = run(settings.root, "concepts", "list")
    assert gone not in merged and "merged 1" in merged
    code, _, err = run(settings.root, "concepts", "unmerge", keep, gone, "--reason", "they differ")
    assert code == 0, err
    _, restored, _ = run(settings.root, "concepts", "list")
    assert gone in restored
    assert run(settings.root, "concepts", "merge", keep, gone)[0] != 0  # a reason is required


# --- concept links ---


def test_concept_links_list_confirm_and_reject(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    cid = agent_concept(project, iw)
    decide_concept_source(project, iw.human, cid, "approve", "", Channel.CLI)
    inferred = propose_concept_link(project, iw.writer, iw.idea1, cid, UseBasisInput(), note="x")
    stated = propose_concept_link(
        project,
        iw.writer,
        iw.source,
        cid,
        UseBasisInput(quote=iw.quote("s1.p2", "Unlike softmax attention")),
    )
    assert inferred.status == "inferred" and stated.status == "stated"
    _, default, _ = run(settings.root, "concept-links", "list")
    assert stated.link_id in default and inferred.link_id not in default
    _, wide, _ = run(settings.root, "concept-links", "list", "--status", "inferred")
    assert inferred.link_id in wide and "interpretation · inferred" in wide
    before = len(events(project))
    code, _, err = run(
        settings.root, "concept-links", "confirm", stated.link_id, "--rationale", "yes"
    )
    assert code != 0 and "not-inferred" in err and len(events(project)) == before
    assert run(settings.root, "concept-links", "confirm", inferred.link_id)[0] != 0
    code, _, err = run(
        settings.root,
        "concept-links",
        "confirm",
        inferred.link_id,
        "--rationale",
        "the paper says so",
    )
    assert code == 0, err
    code, _, err = run(
        settings.root, "concept-links", "reject", stated.link_id, "--rationale", "wrong paper"
    )
    assert code == 0, err
    [confirm, reject] = [e for e in events(project) if e.type == "concept.link_decided"]
    assert confirm.actor.kind == "human" and confirm.payload["decision"] == "confirm"
    assert reject.payload["decision"] == "reject"


# --- graph and trace ---


def test_graph_export_with_interpretation_starts_with_the_notice(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    populate_layer(project, iw)
    code, out, err = run(
        settings.root, "graph", "export", "--format", "dot", "--with-interpretation"
    )
    assert code == 0, err
    assert out.splitlines()[0] == f"// {LAYER_NOTICE}" and "cluster_interpretation" in out
    code, plain, _ = run(settings.root, "graph", "export", "--format", "dot")
    assert code == 0 and LAYER_NOTICE not in plain and "interpretation" not in plain
    code, as_json, _ = run(settings.root, "graph", "export", "--with-interpretation")
    assert json.loads(as_json)["notice"] == LAYER_NOTICE


def test_graph_export_to_a_file_streams_the_layer(
    settings: Settings, project: Project, iw: IWorld, tmp_path: Path
) -> None:
    populate_layer(project, iw)
    target = tmp_path / "out.dot"
    code, _, err = run(
        settings.root,
        "graph",
        "export",
        "--format",
        "dot",
        "--with-interpretation",
        "--out",
        str(target),
    )
    assert code == 0, err
    assert target.read_text().startswith(f"// {LAYER_NOTICE}")


def test_graph_status_and_query_with_interpretation(
    settings: Settings, project: Project, iw: IWorld
) -> None:
    populate_layer(project, iw)
    code, plain, _ = run(settings.root, "graph", "status")
    assert "interpretation layer" not in plain
    code, out, err = run(settings.root, "graph", "status", "--with-interpretation")
    assert code == 0, err
    assert "interpretation layer (not evidence)" in out and "wrong 1" in out
    assert "total" not in out
    code, out, err = run(
        settings.root,
        "graph",
        "query",
        "descendants",
        "--node",
        iw.source,
        "--with-interpretation",
    )
    assert code == 0, err
    assert "interpretation layer (not evidence)" in out and "interpretation · " in out


def test_trace_with_interpretation(settings: Settings, project: Project, iw: IWorld) -> None:
    ident = agent_interpretation(project, iw)
    anchor = f"{iw.cnv}/s1.p4"
    _, plain, _ = run(settings.root, "trace", anchor, "--forward")
    assert ident not in plain
    code, out, err = run(settings.root, "trace", anchor, "--forward", "--with-interpretation")
    assert code == 0, err
    assert ident in out and "interpretation · unreviewed" in out
    code, back, _ = run(settings.root, "trace", ident)
    assert code == 0 and "question" in back

"""Acceptance for full-text screening (plan 2C): acceptance 4 and 13, and the decision-50 rule that
declaring the full-text plan after title/abstract screening keeps the title/abstract outcomes.

The slice-1 acceptance modules are unchanged and run in the full suite, which is the check that
slice-1 behaviour still holds (no duplicate here). Offline throughout: the works come from the
slice-1 mock sources, the documents from the stub routes and the LaTeXML fixture, and the
screeners are scripted sessions over MCP. Passes A and B are separate MCP sessions with different
models; the human labels over MCP and resolves the disagreement with the CLI.
"""

import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.document.quotes import quote_in_element
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.fulltext import AttemptOutcome, Route
from factory.model.protocol import Criterion, ScreeningPlan, ScreeningStage
from factory.model.screening import Channel, PassLabel, ScreeningItem, Verdict
from factory.services.agreement import Outcome, final_outcomes
from factory.services.calibration import calibration_items, draw_calibration, label_calibration
from factory.services.context import Project, open_project
from factory.services.document_read import resolve_anchor
from factory.services.fulltext import fetch_fulltext
from factory.services.fulltext_screening import fulltext_queue
from factory.services.prisma import prisma_flow
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.screening import live_decisions, open_pass, screen_next, screen_record
from factory.sources.fulltext.base import not_retrieved
from factory.sources.registry import SourceFactory
from tests.document_helpers import (
    ARTICLE,
    StubConverter,
    fetched_document,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.helpers import SESSION, _setup, open_session
from tests.test_fulltext_service import StubRoute, _include_all, always
from tests.test_screening_next import _draw
from tests.world_cache import snapshot_world

pytestmark = pytest.mark.slow  # acceptance suite: dev runs deselect with -m "not slow"

FT = ScreeningStage.FULL_TEXT
TA = ScreeningStage.TITLE_ABSTRACT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
Script = Callable[[dict[str, Any], str], dict[str, Any]]

PARAGRAPH_ANCHOR = "s3.p1"
PARAGRAPH_QUOTE = "Lorem ipsum dolor sit amet."
PASS_A = {"role": "screener-a", "model": "claude-sonnet-5-5", "skill": "rf-screen"}
PASS_B = {"role": "screener-b", "model": "claude-haiku-5-5", "skill": "rf-screen"}


# --- Worlds ---


@snapshot_world
def _declare_and_screen_title_abstract(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    """Title/abstract screening to the end under a declared full-text plan, with EX04 (full text
    only). Both passes include every ordinary work; the human labels the title/abstract set."""
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=6)
    current = current_protocol(project)
    assert current is not None
    plan = ScreeningPlan(
        passes=2,
        dual_sample=1.0,
        kappa_floor=0.7,
        calibration_size=3,
        reviewers=current.spec.screening.reviewers,
    )
    criterion = Criterion(
        id="EX04",
        parent="NG03",
        statement="The full text is outside the question.",
        rule="exclude it",
        applies_at=FT,
        priority=4,
    )
    spec = current.spec.model_copy(
        update={
            "full_text_screening": plan,
            "criteria": (*current.spec.criteria, criterion),
        }
    )
    amend_protocol(project, agent, spec, reason="declare full text", semantic=True, effects={})
    amended = current_protocol(project)
    assert amended is not None
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _include_all(project, agent, human, amended.protocol_id)


def _prepare_documents(project: Project) -> str:
    """Every promoted work but the last gets a converted document; the last one's routes all fail,
    so it is not retrieved. Returns the failed work's id."""
    *converted, failed = sorted(promoted_works(project))
    for work in converted:
        fetched_document(project, work, ARTICLE)
    run_convert(project, make_registry(StubConverter()))
    failing = {
        route: StubRoute(route, always(not_retrieved(route, AttemptOutcome.NOT_AVAILABLE, why)))
        for route, why in (
            (Route.ARXIV_HTML, "no html"),
            (Route.ARXIV_SOURCE, "no src"),
            (Route.OA_PDF, "paywalled"),
        )
    }
    fetch_fulltext(project, routes=failing, work_ids=[failed])
    return failed


@snapshot_world
def _ready_for_full_text(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> str:
    """Title/abstract done, documents prepared, full-text calibration not yet drawn."""
    _declare_and_screen_title_abstract(project, agent, human, mock_sources)
    return _prepare_documents(project)


def _eligible_ids(project: Project) -> list[str]:
    return sorted(entry.work_id for entry in fulltext_queue(project).eligible)


def _label_calibration_as_include(project: Project, human: Actor) -> list[str]:
    """Service-level full-text calibration: the drawn set, all labelled include."""
    draw_calibration(project, project.system_actor(), random_seed=3, stage=FT)
    items = calibration_items(project, stage=FT)
    for item in items:
        label_calibration(project, human, item, "include", None, Channel.CLI, stage=FT)
    return items


@dataclass(frozen=True)
class Coding:
    """Which works the scripted screeners exclude under EX04 (every other work is included).

    `calibration_excluded` is the human's exclusion in the calibration set; pass B alone also
    excludes `b_only`, the disagreement."""

    calibration_excluded: frozenset[str]
    both_excluded: frozenset[str]
    b_only: frozenset[str]


def _verdict_item(record: Mapping[str, Any], verdict: str, criterion: str | None) -> dict[str, Any]:
    return {
        "work_id": record["work_id"],
        "verdict": verdict,
        "criterion": criterion,
        "quote": PARAGRAPH_QUOTE,
        "rationale": "fits" if verdict == "include" else "outside the question",
        "anchor": PARAGRAPH_ANCHOR,
    }


def _coded_script(coding: Coding) -> Script:
    def script(record: dict[str, Any], label: str) -> dict[str, Any]:
        work = str(record["work_id"])
        excluded = work in coding.calibration_excluded or work in coding.both_excluded
        if label == "B" and work in coding.b_only:
            excluded = True
        if excluded:
            return _verdict_item(record, "exclude", "EX04")
        return _verdict_item(record, "include", None)

    return script


async def _screen_to_end(
    session: Any,
    identity: dict[str, str],
    label: str,
    script: Script,
    transcript: list[Any],
) -> set[str]:
    """Screen a pass at full text to the end through one MCP session; returns the works served."""
    served: set[str] = set()
    while True:
        last = await session.call(
            "screen_next", project="demo", pass_label=label, stage="full-text", **identity
        )
        transcript.append(last)
        assert last["ok"] is True, last
        batch = last["data"]["batch"]
        if batch is None:
            break
        served.update(str(record["work_id"]) for record in batch["records"])
        items = [script(record, label) for record in batch["records"]]
        written = await session.call(
            "screen_record", project="demo", task_id=batch["task_id"], items=items, **identity
        )
        transcript.append(written)
        assert written["ok"] is True and written["data"]["rejected"] == [], written
    assert last["data"]["blocked"] == [] and last["data"]["remaining"] == 0, last
    return served


def _service_screen_to_end(
    project: Project, actor: Actor, label: PassLabel, verdict_for: Callable[[str], str | None]
) -> None:
    """Screen a full-text pass to the end at service level. `verdict_for` gives the EX04 exclusion
    of a work, or None to include it."""
    while True:
        batch = screen_next(project, actor, label, stage=FT).batch
        if batch is None:
            return
        items: list[ScreeningItem] = []
        for record in batch.records:
            work = str(record["work_id"])
            excluded = verdict_for(work) is not None
            items.append(
                ScreeningItem(
                    work_id=work,
                    verdict=Verdict.EXCLUDE if excluded else Verdict.INCLUDE,
                    criterion="EX04" if excluded else None,
                    quote=PARAGRAPH_QUOTE,
                    rationale="fits" if not excluded else "outside the question",
                    anchor=PARAGRAPH_ANCHOR,
                )
            )
        result = screen_record(project, actor, batch.task_id, items)
        assert result.rejected == [], result.rejected


@snapshot_world
def _screened_full_text_world(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> tuple[list[str], set[str]]:
    """Full text screened to the end by both passes, every eligible work dual-coded, both passes
    agreeing. Returns the ordinary eligible works and the two EX04 exclusions (both passes)."""
    failed = _ready_for_full_text(project, agent, human, mock_sources)
    assert failed not in _eligible_ids(project)
    calibration = set(_label_calibration_as_include(project, human))
    ordinary = [w for w in _eligible_ids(project) if w not in calibration]
    assert len(ordinary) >= 4
    excluded = {ordinary[0], ordinary[1]}

    def verdict_for(work: str) -> str | None:
        return "EX04" if work in excluded else None

    _service_screen_to_end(project, agent, PassLabel.A, verdict_for)
    # Pass B is another session and another model (pass A is the opus fixture).
    other_model = agent_other.model_copy(update={"model": "claude-sonnet-5-5"})
    _service_screen_to_end(project, other_model, PassLabel.B, verdict_for)
    return ordinary, excluded


# --- Acceptance 4 and the two-pass agreement path ---


@pytest.mark.anyio
async def test_two_passes_to_agreement_at_full_text(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _ready_for_full_text(project, agent, human, mock_sources)
    transcript: list[Any] = []
    cli = CliRunner()
    env = {"FACTORY_ROOT": str(settings.root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}

    # The human draws and labels the full-text calibration set over MCP: one exclusion.
    labelled: dict[str, str] = {}
    async with open_session(settings, clock) as reviewer:
        while True:
            pending = await reviewer.call("calibration_label", project="demo", stage="full-text")
            transcript.append(pending)
            record = pending["data"]["record"]
            if record is None:
                break
            verdict, criterion = ("exclude", "EX04") if not labelled else ("include", None)
            written = await reviewer.call(
                "calibration_label",
                project="demo",
                stage="full-text",
                work_id=record["work_id"],
                verdict=verdict,
                criterion=criterion,
            )
            transcript.append(written)
            assert written["ok"] is True, written
            labelled[record["work_id"]] = verdict
        assert pending["data"]["labelled"] == pending["data"]["drawn"] == len(labelled) >= 3

    eligible = _eligible_ids(project)
    calibration_set = set(labelled)
    assert calibration_set <= set(eligible)
    ordinary = [w for w in eligible if w not in calibration_set]
    assert len(ordinary) >= 4
    coding = Coding(
        calibration_excluded=frozenset(w for w, v in labelled.items() if v == "exclude"),
        both_excluded=frozenset(ordinary[:2]),
        b_only=frozenset({ordinary[2]}),
    )
    disputed = ordinary[2]

    # Pass A and pass B each screen every eligible work, each in its own session.
    async with open_session(settings, clock) as screener_a:
        served_a = await _screen_to_end(screener_a, PASS_A, "A", _coded_script(coding), transcript)
    async with open_session(settings, clock) as screener_b:
        served_b = await _screen_to_end(screener_b, PASS_B, "B", _coded_script(coding), transcript)
    assert served_a == served_b == set(eligible)

    async with open_session(settings, clock) as reviewer:
        agreed = await reviewer.call("screen_agreement", project="demo", stage="full-text")
        transcript.append(agreed)
    assert agreed["ok"] is True, agreed
    data = agreed["data"]
    assert data["kappa"] is not None and data["n_dual"] > 0
    assert [config["models"] for config in data["passes"]] == [
        ["claude-sonnet-5-5"],
        ["claude-haiku-5-5"],
    ]
    sessions = [set(config["sessions"]) for config in data["passes"]]
    assert all(len(s) == 1 for s in sessions) and sessions[0].isdisjoint(sessions[1])
    assert [d["work_id"] for d in data["disagreements"]] == [disputed]

    # The human resolves the one disagreement with the CLI; the listing is then empty.
    resolved = cli.invoke(
        app,
        [
            "screen",
            "resolve",
            disputed,
            "include",
            "--reason",
            "the full text fits the question",
            "--stage",
            "full-text",
        ],
        env=env,
    )
    assert resolved.exit_code == 0, resolved.stderr
    listing = cli.invoke(app, ["screen", "disagreements", "--stage", "full-text"], env=env)
    assert listing.stdout.strip() == "no unresolved disagreements"
    outcomes = final_outcomes(project, stage=FT)
    assert outcomes[disputed] is Outcome.INCLUDED
    assert outcomes[ordinary[0]] is Outcome.EXCLUDED

    # The audit sample is drawn at full text, each item with its document and conversion.
    async with open_session(settings, clock) as reviewer:
        sample = await reviewer.call("audit_sample", project="demo", stage="full-text")
        transcript.append(sample)
    assert sample["ok"] is True, sample
    items = sample["data"]["items"]
    assert len(items) == sample["data"]["population"] > 0
    assert {item["work_id"] for item in items} <= set(eligible)
    for item in items:
        assert item["document_id"].startswith("doc_")
        assert item["conversion_id"].startswith("cnv_")

    # Every live full-text decision cites an anchor of its pinned conversion, and its quote is
    # verbatim in that anchor (acceptance 4, verified against the pinned conversion).
    for label in (PassLabel.A, PassLabel.B):
        decisions = live_decisions(project, label, stage=FT)
        assert len(decisions) == len(eligible)
        for decision in decisions:
            assert decision.anchor == PARAGRAPH_ANCHOR
            assert decision.conversion_id is not None
            anchor = resolve_anchor(project, decision.conversion_id, decision.anchor)
            assert quote_in_element(anchor.text, decision.quote)

    # The MCP surfaces leak no held-out seed and no document text beyond the quotes.
    assert "Consectetur" not in json.dumps(transcript)


@pytest.mark.anyio
async def test_unverifiable_quote_rejected_valid_written(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _ready_for_full_text(project, agent, human, mock_sources)
    _label_calibration_as_include(project, human)

    async with open_session(settings, clock) as screener:
        served = await screener.call(
            "screen_next", project="demo", pass_label="A", stage="full-text", **PASS_A
        )
        assert served["ok"] is True, served
        batch = served["data"]["batch"]
        records = batch["records"]
        assert len(records) >= 3
        valid, invented, wrong_anchor = (str(r["work_id"]) for r in records[:3])
        items = [
            _verdict_item(records[0], "include", None),
            {**_verdict_item(records[1], "include", None), "quote": "An invented sentence."},
            {**_verdict_item(records[2], "include", None), "anchor": "s1.p1"},
        ]
        assert valid == str(records[0]["work_id"])
        body = await screener.call(
            "screen_record",
            project="demo",
            task_id=batch["task_id"],
            items=items,
            **PASS_A,
        )

    assert body["ok"] is True, body
    assert len(body["data"]["written"]) == 1
    assert sorted(e["index"] for e in body["data"]["rejected"]) == [1, 2]
    fields = {
        e["index"]: [issue["field"] for issue in e["issues"]] for e in body["data"]["rejected"]
    }
    assert fields == {1: ["items.1.quote"], 2: ["items.2.quote"]}
    reasons = [issue["reason"] for e in body["data"]["rejected"] for issue in e["issues"]]
    assert reasons == ["is not in the cited anchor", "is not in the cited anchor"]

    live = {d.work_id for d in live_decisions(project, PassLabel.A, stage=FT)}
    assert live == {valid}
    assert invented not in live and wrong_anchor not in live
    events = read_all(project.paths.events_dir, project.catalog)
    assert "An invented sentence." not in json.dumps([event.payload for event in events])


# --- Acceptance 13: the full-text PRISMA boxes, derived from events ---


def test_prisma_full_text_boxes_from_events(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> None:
    ordinary, excluded = _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    promoted = promoted_works(project)
    eligible = _eligible_ids(project)
    flow = prisma_flow(project)
    boxes = flow.full_text
    outcomes = final_outcomes(project, stage=FT)

    # Sought: every promoted work. Not retrieved: the one whose routes all failed, with its reason.
    assert boxes.stage_run is True
    assert boxes.sought == len(promoted)
    assert boxes.not_retrieved == 1 == len(fulltext_queue(project).not_retrieved)
    assert boxes.not_retrieved_reasons == {"oa-pdf: paywalled": 1}
    assert boxes.eligible == len(eligible)

    # Assessed, excluded with reasons, included; every eligible work is decided.
    assert boxes.assessed == boxes.eligible and boxes.pending == 0 and boxes.provisional is False
    assert boxes.excluded == {"EX04": len(excluded)}
    assert boxes.included == len(eligible) - len(excluded)
    assert boxes.included == sum(1 for w in eligible if outcomes[w] is Outcome.INCLUDED)
    assert boxes.sought == boxes.not_retrieved + boxes.eligible
    assert boxes.eligible == boxes.assessed + boxes.pending
    assert boxes.assessed == boxes.included + sum(boxes.excluded.values())

    # The title/abstract flow keeps its slice-1 meaning; the review's inclusion is the full text.
    assert flow.included == len(promoted)
    assert flow.included_in_review == boxes.included
    assert excluded <= set(ordinary) <= set(eligible)


# --- Rebuild ---


def test_rebuild_matches(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    settings: Settings,
    clock: FixedClock,
) -> None:
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    before_hash = project.index.state_hash()
    before_flow = prisma_flow(project).model_dump(mode="json")
    before_live = sorted(d.decision_id for d in live_decisions(project, PassLabel.A, stage=FT))

    shutil.rmtree(project.paths.dir / ".index")
    fresh = open_project(settings, "demo", session=SESSION, clock=clock)
    assert fresh.index.rebuild() == before_hash
    assert prisma_flow(fresh).model_dump(mode="json") == before_flow
    assert json.dumps(prisma_flow(fresh).model_dump(mode="json"), sort_keys=True) == json.dumps(
        before_flow, sort_keys=True
    )
    after_live = sorted(d.decision_id for d in live_decisions(fresh, PassLabel.A, stage=FT))
    assert after_live == before_live


# --- Decision 50: declaring the plan after title/abstract keeps the title/abstract outcomes ---


def test_amendment_after_title_abstract_keeps_outcomes(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=6)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    before_id = current_protocol(project)
    assert before_id is not None
    _include_all(project, agent, human, before_id.protocol_id)
    before = final_outcomes(project)
    assert Outcome.INCLUDED in before.values()

    current = current_protocol(project)
    assert current is not None
    plan = ScreeningPlan(
        passes=2,
        dual_sample=1.0,
        kappa_floor=0.7,
        calibration_size=0,
        reviewers=current.spec.screening.reviewers,
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"full_text_screening": plan}),
        reason="declare full text after title/abstract",
        semantic=True,
        effects={},
    )
    amended = current_protocol(project)
    assert amended is not None and amended.protocol_id != before_id.protocol_id

    assert final_outcomes(project) == before
    assert final_outcomes(project, stage=TA) == before
    included = {w for w, o in before.items() if o is Outcome.INCLUDED}
    assert (
        included
        and {w for w, o in final_outcomes(project).items() if o is Outcome.INCLUDED} == included
    )


# --- A full-text calibration draw needs eligible works ---


def test_full_text_draw_refused_while_nothing_is_converted(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    from factory.errors import FactoryValidationError
    from factory.services.calibration import calibration_drawn

    _declare_and_screen_title_abstract(project, agent, human, mock_sources)
    assert _eligible_ids(project) == []
    events_before = len(read_all(project.paths.events_dir, project.catalog))

    with pytest.raises(FactoryValidationError) as caught:
        draw_calibration(project, project.system_actor(), random_seed=3, stage=FT)

    assert [(i.field, i.reason) for i in caught.value.issues] == [
        (
            "stage",
            "no works are eligible at full text yet; fetch and convert documents first",
        )
    ]
    assert len(read_all(project.paths.events_dir, project.catalog)) == events_before
    assert calibration_drawn(project, stage=FT) is False

    _prepare_documents(project)  # the draw can be redone once documents are converted
    items = draw_calibration(project, project.system_actor(), random_seed=3, stage=FT)
    assert items and set(items) <= set(_eligible_ids(project))

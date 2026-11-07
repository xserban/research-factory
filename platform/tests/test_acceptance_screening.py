"""Slice-1 acceptance for screening, agreement and audit (criteria 1, 8, 17, 18).

One pilot project of 40 works. Screener A and screener B are two MCP sessions with different
models; a human session labels over MCP; the CLI resolves disagreements and reports the audit.
Scripted verdicts quote each record's title verbatim. Nothing touches the network: the OpenAlex
search answers from a mock transport.
"""

import json
from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.model.decisions import DecisionLevel
from factory.model.protocol import PressElement, PressFinding
from factory.model.search import QueryKind, QuerySpec
from factory.model.seed import SeedKind, SeedSpec
from factory.services.audit import audit_report
from factory.services.context import Project
from factory.services.probe import run_probe
from factory.services.protocol import confirm_press, press_review, record_protocol
from factory.services.search import list_works
from factory.services.seeds import SeedRole, add_seeds, all_seeds
from factory.sources.registry import SourceFactory
from tests.helpers import (
    Session,
    _leaks,
    _seed_item,
    bind_ids,
    open_session,
    openalex_item,
    pilot_protocol_spec,
    record_pilot_question,
)

pytestmark = pytest.mark.slow  # acceptance suite: dev runs deselect with -m "not slow"

PASS_A = {"role": "screener-a", "model": "claude-sonnet-5-5", "skill": "rf-screen"}
PASS_B = {"role": "screener-b", "model": "claude-haiku-5-5", "skill": "rf-screen"}
Script = Callable[[dict[str, Any], str], dict[str, Any]]


def _works() -> list[dict[str, Any]]:
    items = [_seed_item(n) for n in (1, 2, 3)]
    items += [
        openalex_item(
            title=f"Study {n:02d}: linear attention on vision",
            author="Ada Zhou",
            published="2021-01-01",
            openalex_id=f"W{n}",
            doi=f"10.1000/s{n}",
        )
        for n in range(4, 41)
    ]
    return items


def _number(title: str) -> int:
    """The number of a study title, or 0 for a seed."""
    parts = title.split()
    return int(parts[1].rstrip(":")) if parts[0] == "Study" else 0


def _item(record: dict[str, Any], verdict: str, criterion: str | None, why: str) -> dict[str, Any]:
    return {
        "work_id": record["work_id"],
        "verdict": verdict,
        "criterion": criterion,
        "quote": record["title"],
        "rationale": why,
    }


def _script_a(record: dict[str, Any], phase: str) -> dict[str, Any]:
    """Pass A: excludes the works numbered in multiples of seven; one cannot-assess."""
    n = _number(record["title"])
    if phase == "screening" and n and n % 7 == 0:
        return _item(record, "exclude", "EX01", "off topic")
    if n == 5:
        return _item(record, "cannot-assess", "IN01", "scope unclear")
    return _item(record, "include", None, "fits")


def _script_b(record: dict[str, Any], phase: str) -> dict[str, Any]:
    """Pass B: excludes multiples of four and of seven, but only outside the calibration set."""
    n = _number(record["title"])
    if phase == "screening" and n and (n % 4 == 0 or n % 7 == 0):
        return _item(record, "exclude", "EX01", "off topic")
    return _item(record, "include", None, "fits")


async def _screen(
    session: Session,
    identity: dict[str, str],
    label: str,
    script: Script,
    transcript: list[Any],
) -> set[str]:
    """Screen a pass to the end through one session; returns the works the session was served."""
    served: set[str] = set()
    while True:
        last = await session.call("screen_next", project="demo", pass_label=label, **identity)
        transcript.append(last)
        assert last["ok"] is True, last
        batch = last["data"]["batch"]
        if batch is None:
            break
        served.update(record["work_id"] for record in batch["records"])
        items = [script(record, batch["phase"]) for record in batch["records"]]
        written = await session.call(
            "screen_record", project="demo", task_id=batch["task_id"], items=items, **identity
        )
        transcript.append(written)
        assert written["ok"] is True and written["data"]["rejected"] == [], written
    assert last["data"]["blocked"] == [] and last["data"]["remaining"] == 0
    return served


def _ready_pilot(
    project: Project, agent: Any, human: Any, mock_sources: Callable[..., dict[str, SourceFactory]]
) -> None:
    """A ready pilot protocol: three positive seeds, dual-coding of every work, eight calibration
    works."""
    question_id = record_pilot_question(project, agent)
    for n in (1, 2, 3):
        seed = SeedSpec(kind=SeedKind.POSITIVE, cite=f"Paper {n}", doi=f"10.1000/p{n}")
        add_seeds(
            project,
            agent,
            [seed],
            sources=mock_sources(openalex=[_seed_item(n)]),
            decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
        )
    probe = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    report = run_probe(
        project,
        agent,
        [probe],
        sources=mock_sources(openalex=[_seed_item(1)]),
        decision_ids=bind_ids(project, agent, DecisionLevel.PROBE),
    )
    spec = pilot_protocol_spec(question_id, report.probe_id, reviewer=human.id)
    screening = spec.screening.model_copy(update={"dual_sample": 1.0, "calibration_size": 8})
    spec = spec.model_copy(update={"screening": screening})
    protocol_id = record_protocol(
        project,
        agent,
        spec,
        ready=True,
        decision_ids=bind_ids(project, agent, DecisionLevel.PROTOCOL),
    ).protocol_id
    finding = PressFinding(
        element=PressElement.TEXT_WORDS, finding="Add a synonym.", severity="minor"
    )
    review_id = press_review(project, agent, protocol_id, (finding,))
    confirm_press(project, human, review_id, ("Accepted.",))


@pytest.mark.anyio
async def test_screening_agreement_and_audit_over_two_sessions(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: Callable[..., dict[str, SourceFactory]],
    agent: Any,
    human: Any,
) -> None:
    _ready_pilot(project, agent, human, mock_sources)
    transcript: list[Any] = []
    cli = CliRunner()
    env = {"FACTORY_ROOT": str(settings.root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}

    # The corpus comes from a search over MCP, through a session that screens nothing.
    async with open_session(settings, clock, mock_sources(openalex=_works())) as searcher:
        found = await searcher.call(
            "search_run", project="demo", source="openalex", query="attention", **PASS_A
        )
    assert found["ok"] is True, found
    assert len(list_works(project)) == 40

    # The human labels the calibration set; the first work is excluded, the rest included.
    async with open_session(settings, clock) as reviewer:
        labelled = 0
        while True:
            pending = await reviewer.call("calibration_label", project="demo")
            transcript.append(pending)
            record = pending["data"]["record"]
            if record is None:
                break
            verdict, criterion = ("exclude", "EX01") if labelled == 0 else ("include", None)
            written = await reviewer.call(
                "calibration_label",
                project="demo",
                work_id=record["work_id"],
                verdict=verdict,
                criterion=criterion,
            )
            transcript.append(written)
            assert written["ok"] is True, written
            labelled += 1
        assert pending["data"]["labelled"] == pending["data"]["drawn"] == labelled == 8

    # Both passes screen to the end, each in its own session.
    async with open_session(settings, clock) as screener_a:
        served_a = await _screen(screener_a, PASS_A, "A", _script_a, transcript)
    async with open_session(settings, clock) as screener_b:
        served_b = await _screen(screener_b, PASS_B, "B", _script_b, transcript)
    assert served_a == served_b == {w.id for w in list_works(project)}

    titles = {work.id: work.title for work in list_works(project)}
    async with open_session(settings, clock) as reviewer:
        agreed = await reviewer.call("screen_agreement", project="demo")
        transcript.append(agreed)
    assert agreed["ok"] is True, agreed
    data = agreed["data"]
    assert data["kappa"] is not None and data["n_dual"] > 0
    models = [sorted(config["models"]) for config in data["passes"]]
    assert models == [["claude-sonnet-5-5"], ["claude-haiku-5-5"]]
    sessions = [set(config["sessions"]) for config in data["passes"]]
    assert all(len(s) == 1 for s in sessions) and sessions[0].isdisjoint(sessions[1])
    disagreed = sorted(d["work_id"] for d in data["disagreements"])
    assert disagreed
    for work_id in disagreed:
        number = _number(titles[work_id])
        assert number % 4 == 0 and number % 7 != 0

    # The CLI resolves each disagreement, and the listing is then empty.
    for work_id in disagreed:
        resolved = cli.invoke(
            app,
            ["screen", "resolve", work_id, "include", "--reason", "the title fits the question"],
            env=env,
        )
        assert resolved.exit_code == 0, resolved.stderr
    listing = cli.invoke(app, ["screen", "disagreements"], env=env)
    assert listing.stdout.strip() == "no unresolved disagreements"

    # The human draws the audit sample. Every agreed work is drawn, since fewer than 50 agree.
    async with open_session(settings, clock) as reviewer:
        sample = await reviewer.call("audit_sample", project="demo")
        transcript.append(sample)
        assert sample["ok"] is True, sample
        audit_id = sample["data"]["audit_id"]
        items = sample["data"]["items"]
        assert len(items) == sample["data"]["population"] > 0
        overturned = False
        for item in items:
            work_id = item["work_id"]
            if item["agreed_verdict"] == "exclude" and not overturned:
                verdict, criterion = "include", None
                overturned = True
            elif item["agreed_verdict"] == "exclude":
                verdict, criterion = "exclude", "EX01"
            else:
                verdict, criterion = "include", None
            labelled_item = await reviewer.call(
                "audit_record",
                project="demo",
                audit_id=audit_id,
                work_id=work_id,
                verdict=verdict,
                criterion=criterion,
            )
            transcript.append(labelled_item)
            assert labelled_item["ok"] is True, labelled_item
    assert overturned, "the fixture must agree on at least one exclusion"

    report = audit_report(project)
    assert report is not None and report.labelled == len(items)
    assert report.rates.false_exclusion is not None and report.rates.false_exclusion > 0
    shown = cli.invoke(app, ["audit", "report"], env=env)
    assert shown.exit_code == 0 and f"labelled {len(items)}" in shown.stdout

    # Held-out seeds: screened, yet never named by any screening or audit response (R-20).
    held = [s for s in all_seeds(project) if s.role is SeedRole.HELD_OUT]
    assert held and all(s.work_id in served_a for s in held)
    tokens = {t for s in held for t in (s.seed_id, s.doi, s.arxiv, s.openalex) if t}
    assert _leaks(json.dumps(transcript), tokens) == []

    # Rebuild determinism: the same state hash with and without the index.
    before = cli.invoke(app, ["rebuild"], env=env)
    assert before.exit_code == 0, before.stderr
    project.paths.index_path.unlink()
    after = cli.invoke(app, ["rebuild"], env=env)
    assert after.stdout == before.stdout

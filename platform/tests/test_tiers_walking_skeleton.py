"""Walking skeleton of the tiers (plan 2026-11-20-tiers-and-autonomy, lane L13).

One small world, end to end, across the lanes: a `brief` project is created, the conductor walks
its plan with a scripted FAKE runner whose steps do what each stage's agent would do by calling the
real services as agent actors (one fresh session per role), and the invariants of the plan's
section 6 are asserted on the log it leaves. A second scenario runs a `supervised` project: a gate
that allows `agent_audit` is closed by an independent agent session, drawn by the platform,
labelled by a third session and overturned by a human in the deferred queue.

No process is started and no model is called: the runner is a function of this file. Every title,
author and quote is invented (the quotes are the fixtures' own).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all, read_typed
from factory.model.levels import AutonomyLevel, Tier
from factory.model.protocol import Criterion, PlannedQuery, ScreeningPlan, ScreeningStage
from factory.model.references import Decision, LinkState
from factory.model.screening import Channel, PassLabel, ScreeningItem, Verdict
from factory.model.search import QueryKind, QuerySpec
from factory.services import brief_note as note_module
from factory.services import conductor, deferred_review, gate_trust, gates, runner
from factory.services.brief_note import NO_FINDINGS, brief_note, render_brief_note
from factory.services.chat_read import VerifyResult
from factory.services.context import Project
from factory.services.dedup import dedup_run
from factory.services.extraction import extract_next, extract_record
from factory.services.human_queue import Gate, human_queue
from factory.services.import_resolve import decide_import, record_states, resolve_import
from factory.services.level_statement import level_statement, render_level_statement
from factory.services.prisma import prisma_flow
from factory.services.project import init_project, project_levels
from factory.services.protocol import record_protocol
from factory.services.question import record_question, state_goal
from factory.services.screening import screen_next, screen_record
from factory.services.search import register_query, run_query
from factory.services.withholding import held_out_tokens
from factory.sources.registry import SourceFactory
from factory.tiers import plan_for, report_label, skipped_steps
from tests.document_helpers import (
    ARTICLE,
    StubConverter,
    fetched_document,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.evidence_helpers import claim_input
from tests.extraction_helpers import _r
from tests.fulltext_helpers import _service_screen_to_end
from tests.helpers import SESSION, arxiv_atom, openalex_item, pilot_question_spec
from tests.import_helpers import bib_entry, import_bib
from tests.references_service_helpers import Lookups, oa_item

SourcesFor = Callable[..., Mapping[str, SourceFactory]]

SKILL = "rf-brief@1a2b3c4d"
MECHANICAL_HUMAN_ATTRIBUTED = {"document.converted", "document.conversion_failed"}
STEPS = ("frame", "gather", "screen", "acquire", "extract", "write")
HUMAN_GATES = {
    "protocol.ready",
    "protocol.press_confirm",
    "import.resolution_confirm",
    "manuscript.citation_confirm",
}
"""The gates the conductor keeps for a person at `attended` (`conductor.STEP_GATES` minus the ones
the exploratory presets already leave to an agent)."""

TITLES = (
    "Linear attention for vision transformers",
    "Sparse routing in vision models",
    "Kernelised softmax approximations",
    "Convolutional stems for small image models",
)
ARXIV = ("2401.00001v1", "Efficient transformers for image tasks", 2024, "Cai Wu")
EXCLUDED = "Convolutional stems for small image models"
"""The one work of the world the single screening pass excludes (under EX01)."""

LOOKUP_TITLE = "Efficient Reed Transformers"
WHY = "Same paper; the export adds a version suffix."


def agent_actor(n: int, *, model: str = "claude-sonnet-5-5") -> Actor:
    """An agent whose session is its own: `n` makes the 26-character session id unique."""
    return Actor(
        kind="agent",
        id=f"role-{n:02d}",
        user="obd",
        session=f"01JZ9Q3K5M7N8P0R2S4T6V8W{n:02d}",
        model=model,
        skill=SKILL,
    )


def _criteria() -> tuple[Criterion, ...]:
    return (
        Criterion(
            id="IN01",
            statement="studies of vision transformers",
            rule="include studies of vision transformers",
            applies_at=ScreeningStage.TITLE_ABSTRACT,
        ),
        Criterion(
            id="EX01",
            statement="not a vision study",
            rule="exclude studies with no vision task",
            applies_at=ScreeningStage.TITLE_ABSTRACT,
            priority=1,
        ),
        Criterion(
            id="EX04",
            statement="The full text is outside the question.",
            rule="exclude it",
            applies_at=ScreeningStage.FULL_TEXT,
            priority=4,
        ),
    )


@dataclass
class Scripted:
    """The fake runner. `start_run` performs the stage's effects with the real services as agent
    actors, each role in a session of its own, and returns a run id; every run is complete at
    once (`runner.run_outcome` is patched). `sessions` records the sessions each run used."""

    project: Project
    sources: Mapping[str, SourceFactory]
    runs: list[tuple[str, str]] = field(default_factory=list)
    sessions: dict[str, set[str]] = field(default_factory=dict)
    done: set[str] = field(default_factory=set)
    note: str = ""
    _next: int = 0

    def actor(self, run_id: str, *, model: str = "claude-sonnet-5-5") -> Actor:
        self._next += 1
        actor = agent_actor(self._next, model=model)
        self.sessions.setdefault(run_id, set()).add(actor.session)
        return actor

    def pending(self, _project: Project, stage: str) -> dict[str, int]:
        return {stage: 0 if stage in self.done else 1}

    def start_run(self, project: Project, stage: str, *, unit_cap: int) -> str:
        assert unit_cap >= 1 and project is self.project
        run_id = project.ids.new("rnr")
        self.runs.append((stage, run_id))
        getattr(self, f"_{stage}")(run_id)
        self.done.add(stage)
        return run_id

    # --- the stages' effects -------------------------------------------------------------

    def _frame(self, run: str) -> None:
        agent = self.actor(run)
        question = record_question(self.project, agent, pilot_question_spec()).question_id
        template = plan_for(Tier.BRIEF).protocol_template
        assert template is not None
        queries = tuple(
            PlannedQuery(source=s, kind=QueryKind.KEYWORD, text="linear attention")
            for s in template.sources
        )
        spec = template.instantiate(question, criteria=_criteria(), queries=queries, reviewer="obd")
        # The engine extracts only from a work that passed full text (a plan must be declared):
        # the template names none, so the frame step adds a one-pass plan (reported as a gap).
        full_text = ScreeningPlan(passes=1, calibration_size=0, reviewers=spec.screening.reviewers)
        spec = spec.model_copy(update={"full_text_screening": full_text})
        record_protocol(self.project, agent, spec, ready=True)

    def _gather(self, run: str) -> None:
        agent = self.actor(run)
        for source in ("openalex", "arxiv"):
            spec = QuerySpec(source=source, kind=QueryKind.KEYWORD, text="linear attention")
            query_id = register_query(self.project, agent, spec, sources=self.sources)
            run_query(self.project, query_id, sources=self.sources, actor=agent)
        dedup_run(self.project)

    def _screen(self, run: str) -> None:
        agent = self.actor(run)
        while (batch := screen_next(self.project, agent, PassLabel.A).batch) is not None:
            items = []
            for record in batch.records:
                title = str(record["title"])
                out = title == EXCLUDED
                items.append(
                    ScreeningItem(
                        work_id=str(record["work_id"]),
                        verdict=Verdict.EXCLUDE if out else Verdict.INCLUDE,
                        criterion="EX01" if out else None,
                        quote=title,
                        rationale="outside the question" if out else "fits the question",
                    )
                )
            result = screen_record(self.project, agent, batch.task_id, items)
            assert result.rejected == [], result.rejected

    def _acquire(self, run: str) -> None:
        self.actor(run)  # the acquiring agent's session; fetching and converting are the platform's
        for work in promoted_works(self.project):
            fetched_document(self.project, work, ARTICLE)
        run_convert(self.project, make_registry(StubConverter()))

    def _extract(self, run: str) -> None:
        # Full-text screening to the end in one session, then extraction pass A in a second and
        # pass B (a second model: it opens the pass; only the dual sample is served) in a third.
        _service_screen_to_end(self.project, self.actor(run), PassLabel.A, lambda _w: None)
        for label, model in ((PassLabel.A, "claude-opus-5-5"), (PassLabel.B, "claude-sonnet-5-5")):
            extractor = self.actor(run, model=model)
            for _ in range(20):
                batch = extract_next(self.project, extractor, label).batch
                if batch is None:
                    break
                claims = [claim_input()] if label is PassLabel.A else []
                result = extract_record(
                    self.project, extractor, batch.task_id, [_r()], claims, finish=True
                )
                assert result.completed, (result.rows.rejected, result.claims.rejected)
            else:
                raise AssertionError("too many tasks")

    def _write(self, run: str) -> None:
        self.actor(run)
        self.note = render_brief_note(brief_note(self.project))


@dataclass
class Skeleton:
    project: Project
    runner: Scripted
    waits: list[tuple[str, str, int]]
    """Each wait of the conductor: stage, gate and the runs started so far."""
    statuses: list[conductor.ConductorStatus]


def _sources(mock_sources: SourcesFor) -> Mapping[str, SourceFactory]:
    items = [
        openalex_item(
            title=title,
            author="Ada Zhou",
            published="2023-01-01",
            openalex_id=f"W{n}",
            doi=f"10.1000/b{n}",
        )
        for n, title in enumerate(TITLES, start=1)
    ]
    return mock_sources(openalex=items, arxiv=arxiv_atom([ARXIV]))


@pytest.fixture
def skeleton(
    settings: Settings,
    clock: FixedClock,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> Skeleton:
    """A brief project created as `factory brief new` does (goal stated by the researcher), then
    the conductor walked to its end by the scripted runner; the researcher closes each human gate
    the conductor waits at, outside it."""
    monkeypatch.setattr(runner, "run_outcome", lambda _project, _run: "complete")
    project = init_project(
        settings, "brief-demo", "exploratory", session=SESSION, clock=clock, tier="brief"
    )
    state_goal(project, project.human_actor(), "Does linear attention match softmax on vision?")
    scripted = Scripted(project, _sources(mock_sources))
    conductor.begin_conductor(project, plan_for(Tier.BRIEF))  # type: ignore[arg-type]
    closed: set[tuple[str, str]] = set()
    waits: list[tuple[str, str, int]] = []
    statuses: list[conductor.ConductorStatus] = []
    for _ in range(80):
        status = conductor.advance(
            project,
            start_run=scripted.start_run,
            pending=scripted.pending,
            gate_closed=lambda _p, stage, gate: (stage, gate) in closed,
            escalate=lambda *_a: None,
        )
        statuses.append(status)
        if status.state == "finished":
            return Skeleton(project, scripted, waits, statuses)
        if status.state == "waiting":
            assert status.stage_id is not None and status.gate_id is not None
            waits.append((status.stage_id, status.gate_id, len(scripted.runs)))
            closed.add((status.stage_id, status.gate_id))  # a person acts; the conductor does not
        else:
            assert status.state == "running", status.lines
    raise AssertionError("the conductor did not finish")


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


# ------------------------------------------------------------------------------ the brief


def test_the_conductor_runs_every_step_and_writes_system_events_only(skeleton: Skeleton) -> None:
    project, scripted = skeleton.project, skeleton.runner
    assert [stage for stage, _ in scripted.runs] == list(STEPS)
    assert skeleton.statuses[-1].state == "finished"
    events = _events(project)
    ours = [e for e in events if e.type.startswith("conductor.")]
    assert {e.actor.kind for e in ours} == {"system"}
    by_type = [e.type for e in ours]
    assert by_type.count("conductor.started") == 1
    assert by_type.count("conductor.step_started") == len(STEPS)
    assert by_type.count("conductor.step_finished") == len(STEPS)
    assert by_type.count("conductor.finished") == 1
    # No human act inside the conductor's window: the conductor never confirms anything.
    started = next(e for e in events if e.type == "conductor.started")
    # (`document.converted` is the one mechanical event the platform records under the researcher's
    # actor, `document_convert.py`: a finding of this skeleton, listed in the lane report.)
    human = {e.type for e in events if e.id > started.id and e.actor.kind == "human"}
    assert human <= MECHANICAL_HUMAN_ATTRIBUTED, human
    # What the agents wrote carries provenance (model, skill, input blob).
    agent_events = [e for e in events if e.actor.kind == "agent"]
    assert agent_events
    assert all(e.actor.model and e.actor.skill for e in agent_events)


def test_every_run_has_sessions_of_its_own(skeleton: Skeleton) -> None:
    project, scripted = skeleton.project, skeleton.runner
    assert len(scripted.sessions) == len(STEPS)
    used = [s for sessions in scripted.sessions.values() for s in sessions]
    assert len(used) == len(set(used))  # no session served two runs, nor two roles
    assert SESSION not in used  # the researcher's and the platform's session is none of them
    seen = {e.actor.session for e in _events(project) if e.actor.kind == "agent"}
    assert seen <= set(used)
    assert len(seen) >= 4
    started = [e.payload["run_id"] for e in _events(project) if e.type == "conductor.step_started"]
    assert started == [run for _, run in scripted.runs]


def test_a_human_only_gate_made_the_conductor_wait(skeleton: Skeleton) -> None:
    project = skeleton.project
    first = skeleton.waits[0]
    assert first[0] == "frame" and first[1] in {"protocol.ready", "protocol.press_confirm"}
    assert first[2] == 1  # only the frame run had started: no run for a human gate, none after it
    assert {gate for _, gate, _ in skeleton.waits} <= HUMAN_GATES
    assert {stage for stage, _, _ in skeleton.waits} <= {"frame", "gather", "write"}
    paused = [e for e in _events(project) if e.type == "conductor.paused"]
    assert len(paused) == len(skeleton.waits)
    assert {e.payload["reason"] for e in paused} == {"human-gate"}
    assert {e.actor.kind for e in paused} == {"system"}


def test_levels_come_from_the_event_and_a_legacy_project_is_unchanged(
    skeleton: Skeleton, settings: Settings, clock: FixedClock
) -> None:
    levels = project_levels(skeleton.project)
    assert (levels.tier, levels.autonomy_level) == (Tier.BRIEF, AutonomyLevel.ATTENDED)
    created = next(e for e in _events(skeleton.project) if e.type == "project.created")
    assert created.payload["tier"] == "brief"
    assert "autonomy_level" not in created.payload  # a default is left out of the payload
    legacy = init_project(settings, "legacy-demo", "pilot", session=SESSION, clock=clock)
    old = next(e for e in _events(legacy) if e.type == "project.created")
    assert "tier" not in old.payload and "autonomy_level" not in old.payload
    assert project_levels(legacy).tier is None
    assert level_statement(legacy).tier is None
    # The state hash of an old log is checked once by tests/test_old_log_replay.py (see the report).


def test_note_counts_equal_the_flow_and_an_unverified_quote_is_no_finding(
    skeleton: Skeleton, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = skeleton.project
    note = brief_note(project)
    flow = prisma_flow(project)
    assert note.flow == flow
    assert flow.included == len(TITLES)  # four open-alex works and one arXiv work, one excluded
    assert flow.included_in_review == len(note.works) > 0
    text = render_brief_note(note)
    assert f"- screened: {flow.screened}" in text
    assert f"- included at title and abstract: {flow.included}" in text
    assert f"- duplicates removed: {flow.duplicates_removed}" in text
    assert skeleton.runner.note == text  # what the write step produced is the computed note
    assert note.verified_claims and not note.unverified_claims
    assert "## Findings with verified quotes" in text and NO_FINDINGS not in text
    assert report_label(Tier.BRIEF) in text
    # The held-out rule is untouched: nothing held out exists here, and none is named.
    assert not [t for t in held_out_tokens(project) if t in text]

    def reject(_project: Project, items: Any) -> list[VerifyResult]:
        return [VerifyResult(i, "quote-not-in-anchor", None, None) for i in items]

    monkeypatch.setattr(note_module, "chat_verify", reject)
    flagged = brief_note(project)
    assert not flagged.verified_claims and flagged.unverified_claims
    section = render_brief_note(flagged).partition("## Findings with verified quotes")[2]
    section = section.partition("## Unverified claims")[0]
    assert NO_FINDINGS in section and "Lorem ipsum dolor sit amet." not in section
    assert flagged.flow == flow  # the counts do not move with a quote check


def test_the_level_statement_says_what_was_skipped_and_what_nobody_confirmed(
    skeleton: Skeleton,
) -> None:
    project = skeleton.project
    statement = level_statement(project)
    text = render_level_statement(statement)
    assert statement.tier is Tier.BRIEF and statement.autonomy_level is AutonomyLevel.ATTENDED
    assert "tier: brief" in text and "autonomy level: attended" in text
    assert statement.steps_skipped == skipped_steps(Tier.BRIEF) != ()
    assert "skipped compared with a systematic review: " in text
    assert "understand: skipped" in text
    # The statement never says more than the log: agent-closed acts and the human flag agree.
    assert statement.human_confirmed == (not statement.agent_closed)
    assert ("not human-confirmed" in text) == (not statement.human_confirmed)
    # The brief note carries the same lines.
    note_text = render_brief_note(brief_note(project))
    assert all(line in note_text for line in statement.lines)


def test_ledger_and_deferred_queue_read_under_attended(skeleton: Skeleton) -> None:
    project = skeleton.project
    ledger = gate_trust.trust_ledger(project)
    assert all(row.state == "ok" for row in ledger)
    assert deferred_review.deferred_items(project) == ()  # attended: nothing is deferred
    assert all(item.gate is not Gate.DEFERRED_REVIEW for item in human_queue(project).items)


# ------------------------------------------------------------------------------ supervised


def test_a_supervised_gate_is_closed_by_an_independent_session_and_audited(
    settings: Settings,
    clock: FixedClock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = "import.resolution_confirm"
    monkeypatch.setattr(runner, "run_outcome", lambda _project, _run: "complete")
    project = init_project(
        settings,
        "supervised-demo",
        "exploratory",
        session=SESSION,
        clock=clock,
        tier="brief",
        autonomy_level="supervised",
    )
    assert project_levels(project).autonomy_level is AutonomyLevel.SUPERVISED
    assert gates.effective_policy(project, gate).kind.value == "agent_audit"
    lookups = Lookups(openalex=[oa_item(LOOKUP_TITLE, "Bo Lee", 2021, "W501")])
    imp = import_bib(
        project,
        tmp_path,
        [bib_entry("a", f"{LOOKUP_TITLE} v2", year=2021, author="Lee, Bo")],
    )
    resolve_import(project, imp, sources=lookups.sources())
    assert record_states(project, imp) == {1: LinkState.UNCONFIRMED}

    proposer, closer, auditor = agent_actor(1), agent_actor(2), agent_actor(3)
    decide_import(project, proposer, imp, 1, Decision.PROPOSE_CONFIRM, rationale=WHY)
    with pytest.raises(FactoryValidationError):  # the proposer cannot close its own proposal
        decide_import(project, proposer, imp, 1, Decision.CONFIRM, rationale=WHY)
    decide_import(project, closer, imp, 1, Decision.CONFIRM, rationale=WHY)
    assert record_states(project, imp) == {1: LinkState.RESOLVED}
    [act] = [a for a in gates.gate_acts(project, gate) if a.actor_kind == "agent"]
    assert act.session == closer.session != proposer.session

    drawn = gates.gate_audit_sample_platform(project, gate)  # the platform draws, not an agent
    assert drawn.act_event_ids == (act.event_id,)
    [sampled] = read_typed(project.paths.events_dir, project.catalog, ("gate.audit_sampled",))
    assert sampled.actor.kind == "system"
    with pytest.raises(FactoryValidationError):  # the session that closed it cannot label it
        gates.gate_audit_record_agent(project, closer, drawn.audit_id, act.event_id, True, None)
    gates.gate_audit_record_agent(project, auditor, drawn.audit_id, act.event_id, False, "wrong")

    [row] = gate_trust.trust_ledger(project)
    assert (row.gate_id, row.closed_by_agent) == (gate, 1)
    assert (row.audited, row.overturned, row.state) == (0, 0, "ok")  # human labels only
    assert (row.agent_audited, row.agent_overturned) == (1, 1)
    [item] = deferred_review.deferred_items(project)
    assert (item.gate_id, item.act_event_id) == (gate, act.event_id)
    assert [i for i in human_queue(project).items if i.gate is Gate.DEFERRED_REVIEW]
    statement = level_statement(project)
    assert not statement.human_confirmed
    assert gate in [c.gate_id for c in statement.agent_closed]
    assert "not human-confirmed" in render_level_statement(statement)

    for actor in (auditor, project.system_actor()):  # only a person decides a deferred item
        with pytest.raises(FactoryValidationError):
            deferred_review.decide_deferred(
                project, actor, drawn.audit_id, act.event_id, "overturn", None, Channel.CLI
            )
    deferred_review.decide_deferred(
        project, project.human_actor(), drawn.audit_id, act.event_id, "overturn", "no", Channel.CLI
    )
    [row] = gate_trust.trust_ledger(project)
    assert (row.audited, row.overturned, row.overturn_rate, row.state) == (1, 1, 1.0, "pause")
    assert deferred_review.deferred_items(project) == ()

    # A gate in `pause` stops the conductor before any run is started.
    started: list[str] = []

    def never(_project: Project, stage: str, *, unit_cap: int) -> str:
        started.append(stage)
        return "rnr_never"

    conductor.begin_conductor(project, plan_for(Tier.BRIEF))  # type: ignore[arg-type]
    status = conductor.advance(
        project,
        start_run=never,
        pending=lambda _p, stage: {stage: 1},
        gate_closed=lambda *_a: True,
        escalate=lambda *_a: None,
    )
    assert status.state == "paused" and status.reason == "trust-pause" and status.gate_id == gate
    assert started == []

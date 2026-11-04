"""The stage dimension in the slice-1 services: title/abstract and full text keep separate state.

The default stage is title/abstract, so every slice-1 call is unchanged. A two-stage world is
built from direct events (the decisions are written as events, as the slice-1 tests do).

Designed roles in the world (ordinary works `o` of the title/abstract stage, sorted):
- `o[0]` agreed include at title/abstract, agreed exclude (EX04) at full text;
- `o[1]` agreed exclude at title/abstract, so it is not a full-text work;
- `o[2]` a disagreement at both stages, resolved include, then resolved exclude;
- the rest agreed include at both.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import MetaData, text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.index.screening import _agreed_by_work, screening_tables
from factory.model.protocol import (
    Criterion,
    CriterionEffect,
    ScreeningPlan,
    ScreeningStage,
)
from factory.model.screening import (
    Channel,
    DecisionRecorded,
    PassJoined,
    PassLabel,
    ScreeningPhase,
    Verdict,
)
from factory.services.agreement import (
    agreed_works,
    agreement_summary,
    exclusion_criteria,
    final_outcomes,
    pass_progress,
    resolve_disagreement,
    screen_agreement,
    single_pass_works,
)
from factory.services.audit import audit_outstanding, audit_record, audit_report, audit_sample
from factory.services.calibration import (
    calibration_drawn,
    calibration_items,
    calibration_labels,
    calibration_status,
    draw_calibration,
    is_pass_session,
    label_calibration,
)
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.screening import (
    join_pass,
    live_decisions,
    open_pass,
    pass_b_sample,
    screen_next,
    stale_screening_decisions,
)
from factory.services.search import list_works
from factory.services.stages import stage_of_kind, task_kind
from tests.helpers import SESSION, _of_type, _setup
from tests.test_screening_next import SourcesFor, _decide, _draw, _events

TA = ScreeningStage.TITLE_ABSTRACT
FT = ScreeningStage.FULL_TEXT
EITHER = ScreeningStage.EITHER
S_X = "01JZ9Q3K5M7N8P0R2S4T6V8W0X"
S_Y = "01JZ9Q3K5M7N8P0R2S4T6V8W0Y"


def _criterion(
    cid: str, stage: ScreeningStage, priority: int, rule: str = "exclude it"
) -> Criterion:
    return Criterion(
        id=cid,
        parent="NG03",
        statement=f"statement {cid}",
        rule=rule,
        applies_at=stage,
        priority=priority,
    )


def _declare_full_text(project: Project, agent: Actor, *, plan: bool = True) -> str:
    """Amend the ready protocol: a small, single-coverage plan at both stages, a full-text-only
    criterion EX04 and an `either` criterion EX05. Returns the new version id."""
    current = current_protocol(project)
    assert current is not None
    reviewers = current.spec.screening.reviewers
    ta_plan = ScreeningPlan(
        passes=2, dual_sample=1.0, kappa_floor=0.7, calibration_size=0, reviewers=reviewers
    )
    spec = current.spec.model_copy(
        update={
            "criteria": (
                *current.spec.criteria,
                _criterion("EX04", FT, 4),
                _criterion("EX05", EITHER, 5),
            ),
            "screening": ta_plan,
            "full_text_screening": ta_plan if plan else None,
        }
    )
    amend_protocol(project, agent, spec, reason="declare full text", semantic=True, effects={})
    result = current_protocol(project)
    assert result is not None
    return result.protocol_id


def _loosen(project: Project, agent: Actor, cid: str) -> str:
    current = current_protocol(project)
    assert current is not None
    criteria = tuple(
        c.model_copy(update={"rule": "a looser rule"}) if c.id == cid else c
        for c in current.spec.criteria
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"criteria": criteria}),
        reason=f"loosen {cid}",
        semantic=True,
        effects={cid: CriterionEffect.LOOSENED},
    )
    result = current_protocol(project)
    assert result is not None
    return result.protocol_id


def _decide_at(
    project: Project,
    agent: Actor,
    stage: ScreeningStage,
    work: str,
    label: str,
    verdict: str,
    criterion: str | None,
    protocol_id: str,
    phase: str = "screening",
) -> str:
    """Write one decision event at `stage`; a full-text one carries an anchor and a conversion."""
    if stage is TA:
        return _decide(project, agent, work, label, phase, verdict, criterion, protocol_id)
    decision_id = f"dec_{project.ids.ulid()}"
    payload = DecisionRecorded(
        decision_id=decision_id,
        work_id=work,
        pass_label=PassLabel(label),
        phase=ScreeningPhase(phase),
        stage=stage,
        verdict=Verdict(verdict),
        criterion=None if criterion is None else f"{protocol_id}:{criterion}",
        quote="a quote",
        rationale="rationale",
        protocol_id=protocol_id,
        task_id="tsk_test",
        supersedes=None,
        anchor="p1",
        conversion_id=f"cnv_{project.ids.ulid()}",
    )
    blob = project.blobs.put_json({"work_id": work, "verdict": verdict})
    project.record(
        [
            project.events.make(
                "screening.decision_recorded", payload, agent, refs=(decision_id,), input_blob=blob
            )
        ]
    )
    return decision_id


def _both(
    project: Project,
    agent: Actor,
    stage: ScreeningStage,
    work: str,
    a: tuple[str, str | None],
    b: tuple[str, str | None],
    protocol_id: str,
) -> None:
    _decide_at(project, agent, stage, work, "A", a[0], a[1], protocol_id)
    _decide_at(project, agent, stage, work, "B", b[0], b[1], protocol_id)


@dataclass
class World:
    protocol_id: str
    ta_ordinary: list[str]
    ft_ordinary: list[str]
    x: str
    gone: str
    dis: str


def _world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> World:
    """Both stages screened and agreed, the disagreement resolved at each stage."""
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    pid = _declare_full_text(project, agent)
    _draw(project)
    for item in calibration_items(project):
        label_calibration(project, human, item, "include", None, Channel.CLI)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    cal = set(calibration_items(project))
    ordinary = sorted(w.id for w in list_works(project) if w.id not in cal)
    assert len(ordinary) >= 4
    x, gone, dis, *rest = ordinary
    _both(project, agent, TA, x, ("include", None), ("include", None), pid)
    _both(project, agent, TA, gone, ("exclude", "EX01"), ("exclude", "EX01"), pid)
    _both(project, agent, TA, dis, ("include", None), ("exclude", "EX01"), pid)
    for work in rest:
        _both(project, agent, TA, work, ("include", None), ("include", None), pid)
    resolve_disagreement(project, human, dis, "include", None, "adjudicated", Channel.CLI)

    ft_items = draw_calibration(project, project.system_actor(), random_seed=5, stage=FT)
    for item in ft_items:
        label_calibration(project, human, item, "include", None, Channel.CLI, stage=FT)
    open_pass(project, agent, PassLabel.A, stage=FT)
    open_pass(project, agent, PassLabel.B, stage=FT)
    ft_ordinary = sorted(w for w, o in final_outcomes(project).items() if o.value == "included")
    ft_ordinary = [w for w in ft_ordinary if w not in set(ft_items)]
    assert {x, dis, *rest} == set(ft_ordinary)
    _both(project, agent, FT, x, ("exclude", "EX04"), ("exclude", "EX04"), pid)
    _both(project, agent, FT, dis, ("include", None), ("exclude", "EX04"), pid)
    for work in rest:
        _both(project, agent, FT, work, ("include", None), ("include", None), pid)
    resolve_disagreement(
        project, human, dis, "exclude", "EX04", "adjudicated", Channel.CLI, stage=FT
    )
    return World(pid, ordinary, ft_ordinary, x, gone, dis)


def _fields(exc: pytest.ExceptionInfo[FactoryValidationError]) -> list[str]:
    return [issue.field for issue in exc.value.issues]


# --- Defaults ---


def test_stage_defaults_leave_slice1_unchanged(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = _world(project, agent, human, mock_sources)
    sampled = audit_sample(project, human, random_seed=3)
    audit_record(
        project, human, sampled.audit_id, sampled.work_ids[0], "include", None, Channel.CLI
    )
    pairs: list[tuple[Any, Any]] = [
        (calibration_items(project), calibration_items(project, stage=TA)),
        (calibration_labels(project), calibration_labels(project, stage=TA)),
        (calibration_drawn(project), calibration_drawn(project, stage=TA)),
        (
            calibration_status(project).model_dump(),
            calibration_status(project, stage=TA).model_dump(),
        ),
        (live_decisions(project, PassLabel.A), live_decisions(project, PassLabel.A, stage=TA)),
        (live_decisions(project), live_decisions(project, stage=TA)),
        (pass_b_sample(project), pass_b_sample(project, stage=TA)),
        (agreed_works(project), agreed_works(project, stage=TA)),
        (final_outcomes(project), final_outcomes(project, stage=TA)),
        (exclusion_criteria(project), exclusion_criteria(project, stage=TA)),
        (single_pass_works(project), single_pass_works(project, stage=TA)),
        (pass_progress(project), pass_progress(project, stage=TA)),
        (agreement_summary(project), agreement_summary(project, stage=TA)),
        (
            screen_agreement(project, human).model_dump(),
            screen_agreement(project, human, stage=TA).model_dump(),
        ),
        (audit_report(project), audit_report(project, stage=TA)),
        (audit_outstanding(project), audit_outstanding(project, stage=TA)),
        (is_pass_session(project, SESSION), is_pass_session(project, SESSION, stage=TA)),
    ]
    for default, explicit in pairs:
        assert default == explicit
    assert task_kind(TA, PassLabel.A) == "screen_a"
    assert task_kind(TA, PassLabel.B) == "screen_b"
    assert task_kind(FT, PassLabel.A) == "screen_ft_a"
    assert task_kind(FT, PassLabel.B) == "screen_ft_b"
    assert stage_of_kind("screen_ft_b") is FT and stage_of_kind("screen_a") is TA
    assert stage_of_kind("other") is None
    assert world.gone not in {w for w, o in final_outcomes(project).items() if o.value == "pending"}


# --- Separate state ---


def test_full_text_pass_state_is_separate(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    pid = _declare_full_text(project, agent)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    ordinary = [w.id for w in list_works(project) if w.id not in set(calibration_items(project))]
    _decide(project, agent, ordinary[0], "A", "screening", "include", None, pid)
    before = pass_progress(project)

    assert pass_progress(project, stage=FT)["A"].queued is None
    open_pass(project, agent, PassLabel.A, stage=FT)

    assert pass_progress(project) == before
    assert pass_progress(project, stage=FT)["A"].queued is not None
    assert pass_progress(project, stage=FT)["A"].decided == 0
    assert calibration_items(project, stage=FT) == []
    assert calibration_items(project) != []
    opened = [e for e in _of_type(project, "screening.pass_opened")]
    assert [e.payload.get("stage", "title-abstract") for e in opened] == [
        "title-abstract",
        "full-text",
    ]
    open_pass(project, agent, PassLabel.A, stage=FT)  # idempotent
    assert len(_of_type(project, "screening.pass_opened")) == 2


# --- Sessions ---


def test_session_may_join_both_stages_but_not_both_passes_of_one_stage(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _declare_full_text(project, agent)
    join_pass(project, agent, PassLabel.A)
    join_pass(project, agent, PassLabel.A, stage=FT)
    assert is_pass_session(project, agent.session, stage=TA)
    assert is_pass_session(project, agent.session, stage=FT)
    before = len(_events(project))

    for stage in (TA, FT):
        with pytest.raises(FactoryValidationError) as exc:
            join_pass(project, agent, PassLabel.B, stage=stage)
        assert _fields(exc) == ["pass"]
    assert len(_events(project)) == before
    joins = _of_type(project, "screening.pass_joined")
    assert [e.payload.get("stage", "title-abstract") for e in joins] == [
        "title-abstract",
        "full-text",
    ]
    join_pass(project, agent, PassLabel.A, stage=FT)  # again: nothing written
    assert len(_events(project)) == before


def test_model_independence_holds_per_stage(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _declare_full_text(project, agent)
    join_pass(project, agent, PassLabel.A)
    with pytest.raises(FactoryValidationError) as exc:
        join_pass(project, agent_other, PassLabel.B)  # same model as pass A at title/abstract
    assert _fields(exc) == ["model"]
    join_pass(project, agent_other, PassLabel.B, stage=FT)  # pass A at full text has no model yet


def _join(
    project: Project, session: str, label: PassLabel, model: str, stage: ScreeningStage
) -> None:
    payload = PassJoined(pass_label=label, session=session, model=model, stage=stage)
    project.record([project.events.make("screening.pass_joined", payload, project.system_actor())])


def test_agreement_refuses_shared_session_within_stage(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _declare_full_text(project, agent)
    _draw(project)
    for stage in (TA, FT):
        if stage is FT:
            draw_calibration(project, project.system_actor(), random_seed=5, stage=FT)
        open_pass(project, agent, PassLabel.A, stage=stage)
        open_pass(project, agent, PassLabel.B, stage=stage)

    def refused_for_session(stage: ScreeningStage) -> bool:
        try:
            screen_agreement(project, human, stage=stage)
        except FactoryValidationError as exc:
            return any("session" in issue.reason for issue in exc.issues)
        return False

    # One session in pass A at title/abstract and pass B at full text: allowed.
    _join(project, S_X, PassLabel.A, "m1", TA)
    _join(project, S_X, PassLabel.B, "m2", FT)
    assert not refused_for_session(TA) and not refused_for_session(FT)

    # A session in both passes of the full-text stage: refused there, and only there.
    _join(project, S_Y, PassLabel.A, "m3", FT)
    _join(project, S_Y, PassLabel.B, "m4", FT)
    with pytest.raises(FactoryValidationError) as exc:
        screen_agreement(project, human, stage=FT)
    assert _fields(exc) == ["passes"]
    assert "session" in exc.value.issues[0].reason
    assert not refused_for_session(TA)


# --- Amendments ---


def test_full_text_amendment_stales_only_full_text_decisions(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    pid = _declare_full_text(project, agent)
    works = sorted(w.id for w in list_works(project))[:4]
    ft_04 = _decide_at(project, agent, FT, works[0], "A", "exclude", "EX04", pid)
    ft_01 = _decide_at(project, agent, FT, works[1], "A", "exclude", "EX01", pid)
    ta_04 = _decide_at(project, agent, TA, works[2], "A", "exclude", "EX04", pid)
    ta_01 = _decide_at(project, agent, TA, works[3], "A", "exclude", "EX01", pid)
    ft_05 = _decide_at(project, agent, FT, works[2], "B", "exclude", "EX05", pid)
    ta_05 = _decide_at(project, agent, TA, works[3], "B", "exclude", "EX05", pid)
    assert stale_screening_decisions(project) == set()

    _loosen(project, agent, "EX04")  # applies only at full text
    assert stale_screening_decisions(project) == {ft_04}

    _loosen(project, agent, "EX05")  # applies at either stage
    assert stale_screening_decisions(project) == {ft_04, ft_05, ta_05}
    assert not {ta_01, ft_01, ta_04} & stale_screening_decisions(project)
    assert stale_screening_decisions(project, stage=FT) == {ft_04, ft_05}
    assert stale_screening_decisions(project, stage=TA) == {ta_05}


# --- Refusals ---


def test_full_text_refused_without_declared_plan(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _declare_full_text(project, agent, plan=False)
    _draw(project)
    calls: list[Callable[[], object]] = [
        lambda: open_pass(project, agent, PassLabel.A, stage=FT),
        lambda: screen_next(project, agent, PassLabel.A, stage=FT),
        lambda: draw_calibration(project, human, random_seed=1, stage=FT),
        lambda: screen_agreement(project, human, stage=FT),
        lambda: audit_sample(project, human, stage=FT),
        lambda: final_outcomes(project, stage=FT),
    ]
    before = len(_events(project))
    for call in calls:
        with pytest.raises(FactoryValidationError) as exc:
            call()
        assert _fields(exc) == ["full_text_screening"]
        assert "full-text screening plan" in exc.value.issues[0].reason
    assert len(_events(project)) == before


def test_either_stage_rejected(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _declare_full_text(project, agent)
    calls: list[Callable[[], object]] = [
        lambda: open_pass(project, agent, PassLabel.A, stage=EITHER),
        lambda: join_pass(project, agent, PassLabel.A, stage=EITHER),
        lambda: screen_next(project, agent, PassLabel.A, stage=EITHER),
        lambda: live_decisions(project, stage=EITHER),
        lambda: pass_b_sample(project, stage=EITHER),
        lambda: calibration_items(project, stage=EITHER),
        lambda: calibration_labels(project, stage=EITHER),
        lambda: calibration_status(project, stage=EITHER),
        lambda: calibration_drawn(project, stage=EITHER),
        lambda: draw_calibration(project, human, stage=EITHER),
        lambda: label_calibration(project, human, "w", "include", None, Channel.CLI, stage=EITHER),
        lambda: screen_agreement(project, human, stage=EITHER),
        lambda: resolve_disagreement(
            project, human, "w", "include", None, "r", Channel.CLI, stage=EITHER
        ),
        lambda: agreed_works(project, stage=EITHER),
        lambda: final_outcomes(project, stage=EITHER),
        lambda: pass_progress(project, stage=EITHER),
        lambda: audit_sample(project, human, stage=EITHER),
        lambda: audit_report(project, stage=EITHER),
        lambda: audit_outstanding(project, stage=EITHER),
        lambda: task_kind(EITHER, PassLabel.A),
    ]
    before = len(_events(project))
    for call in calls:
        with pytest.raises(FactoryValidationError) as exc:
            call()
        assert _fields(exc) == ["stage"]
    assert len(_events(project)) == before


# --- Per-stage results ---


def test_audit_population_per_stage(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = _world(project, agent, human, mock_sources)
    ta_agreed = agreed_works(project)
    ft_agreed = agreed_works(project, stage=FT)
    assert world.dis not in ta_agreed and world.dis not in ft_agreed
    assert ta_agreed[world.gone].verdict == "exclude"
    assert ft_agreed[world.x].verdict == "exclude"
    assert world.gone not in ft_agreed

    assert audit_outstanding(project) and audit_outstanding(project, stage=FT)
    ta = audit_sample(project, human, random_seed=1)
    assert not audit_outstanding(project)
    assert audit_outstanding(project, stage=FT)  # the title/abstract audit does not close it
    ft = audit_sample(project, human, random_seed=1, stage=FT)
    assert not audit_outstanding(project, stage=FT)
    assert ta.stage is TA and ft.stage is FT
    with pytest.raises(FactoryValidationError):
        audit_sample(project, human, random_seed=2, stage=FT)  # still open at full text

    with project.index.connect() as conn:
        rows = {
            str(r[0]): (str(r[1]), int(r[2]), int(r[3]), int(r[4]))
            for r in conn.execute(
                text(
                    "SELECT audit_id, stage, population, pop_exclusions, pop_inclusions FROM audits"
                )
            ).all()
        }
    assert rows[ta.audit_id] == (
        "title-abstract",
        len(ta_agreed),
        sum(1 for a in ta_agreed.values() if a.verdict == "exclude"),
        sum(1 for a in ta_agreed.values() if a.verdict == "include"),
    )
    assert rows[ft.audit_id] == (
        "full-text",
        len(ft_agreed),
        sum(1 for a in ft_agreed.values() if a.verdict == "exclude"),
        sum(1 for a in ft_agreed.values() if a.verdict == "include"),
    )
    assert rows[ta.audit_id][1] != rows[ft.audit_id][1]

    audit_record(project, human, ft.audit_id, world.x, "include", None, Channel.CLI)
    labelled = _of_type(project, "audit.labelled")[-1]
    assert labelled.payload["stage"] == "full-text"
    report_ft = audit_report(project, stage=FT)
    report_ta = audit_report(project)
    assert report_ft is not None and report_ta is not None
    assert report_ft.audit_id == ft.audit_id and report_ta.audit_id == ta.audit_id
    assert report_ft.labelled == 1 and report_ta.labelled == 0


def test_same_work_in_both_stages_does_not_collide(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = _world(project, agent, human, mock_sources)
    ta_live = {d.work_id: d for d in live_decisions(project, PassLabel.A)}
    ft_live = {d.work_id: d for d in live_decisions(project, PassLabel.A, stage=FT)}
    assert world.x in ta_live and world.x in ft_live
    assert ta_live[world.x].verdict is Verdict.INCLUDE
    assert ft_live[world.x].verdict is Verdict.EXCLUDE
    assert {d.stage for d in ta_live.values()} == {TA}
    assert {d.stage for d in ft_live.values()} == {FT}

    # Resolutions: one per stage for the same work.
    assert final_outcomes(project)[world.dis].value == "included"
    assert final_outcomes(project, stage=FT)[world.dis].value == "excluded"
    assert exclusion_criteria(project, stage=FT)[world.dis] == "EX04"
    assert world.dis not in exclusion_criteria(project)
    with project.index.connect() as conn:
        resolutions = conn.execute(
            text("SELECT stage, verdict FROM resolutions WHERE work_id = :w ORDER BY stage"),
            {"w": world.dis},
        ).all()
    assert [tuple(r) for r in resolutions] == [
        ("full-text", "exclude"),
        ("title-abstract", "include"),
    ]

    # Audits: the same work is an item of both audits with its stage's agreed verdict.
    ta = audit_sample(project, human, random_seed=1)
    ft = audit_sample(project, human, random_seed=1, stage=FT)
    assert world.x in ta.work_ids and world.x in ft.work_ids
    with project.index.connect() as conn:
        verdicts = {
            str(a): str(v)
            for a, v in conn.execute(
                text("SELECT audit_id, agreed_verdict FROM audit_items WHERE work_id = :w"),
                {"w": world.x},
            ).all()
        }
    assert verdicts == {ta.audit_id: "include", ft.audit_id: "exclude"}

    # Calibration: a work labelled at one stage is not labelled at the other.
    ft_cal = calibration_items(project, stage=FT)
    assert ft_cal and set(ft_cal) <= set(calibration_items(project))
    assert calibration_labels(project, stage=FT).keys() == set(ft_cal)


def test_agreed_works_matches_projector_per_stage(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = _world(project, agent, human, mock_sources)
    protocol_id = current_protocol(project)
    assert protocol_id is not None
    tables = screening_tables(MetaData())
    for stage in (TA, FT):
        service = {
            w: (a.verdict, ",".join(a.criteria) if a.verdict == "exclude" else None)
            for w, a in agreed_works(project, stage=stage).items()
        }
        with project.index.connect() as conn:
            projected = _agreed_by_work(conn, tables, protocol_id.protocol_id, stage.value)
        assert service == projected
        assert service  # the comparison is not vacuous
    assert agreed_works(project)[world.x].verdict == "include"
    assert agreed_works(project, stage=FT)[world.x].criteria == ["EX04"]


def _flatten(node: Any) -> list[tuple[str, str, str]]:
    """(kind, id, label) of every node of a trace tree."""
    found = [(node.kind, node.id, node.label)]
    for child in node.children:
        found += _flatten(child)
    return found


def test_trace_resolution_keys_are_per_stage(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    from factory.services.trace import dangling_refs, trace

    world = _world(project, agent, human, mock_sources)
    ta_key, ft_key = f"res:{world.dis}", f"res:full-text:{world.dis}"
    ta_nodes = _flatten(trace(project, ta_key))
    ft_nodes = _flatten(trace(project, ft_key))
    assert (("resolution", ta_key) == ta_nodes[0][:2]) and ("include" in ta_nodes[0][2])
    assert (("resolution", ft_key) == ft_nodes[0][:2]) and ("exclude" in ft_nodes[0][2])
    ta_decisions = {i for k, i, _ in ta_nodes if k == "decision"}
    ft_decisions = {i for k, i, _ in ft_nodes if k == "decision"}
    assert ta_decisions and ft_decisions and not ta_decisions & ft_decisions
    assert dangling_refs(project, [ta_key, ft_key, f"res:full-text:{world.gone}"]) == [
        f"res:full-text:{world.gone}"
    ]
    forward = _flatten(trace(project, world.dis, direction="forward"))
    assert {i for k, i, _ in forward if k == "resolution"} == {ta_key, ft_key}


def test_full_text_screen_next_serves_its_own_task_kind(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    world = _world(project, agent, human, mock_sources)
    del world
    result = screen_next(project, agent, PassLabel.A, stage=FT)
    # The full-text calibration set is labelled but not yet decided: ordinary batches wait.
    assert result.batch is not None
    kinds = {e.payload["kind"] for e in _of_type(project, "task.created") if e.payload.get("kind")}
    assert "screen_ft_a" in kinds
    assert is_pass_session(project, agent.session, stage=FT)

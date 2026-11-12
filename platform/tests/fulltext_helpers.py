"""Shared full-text test helpers: worlds screened to full text, conversions, PDFs, corpora."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.fulltext import (
    AttemptOutcome,
    Route,
)
from factory.model.protocol import (
    Criterion,
    CriterionEffect,
    ScreeningPlan,
    ScreeningStage,
)
from factory.model.screening import (
    Channel,
    DecisionRecorded,
    PassLabel,
    ScreeningItem,
    ScreeningPhase,
    Verdict,
)
from factory.services.agreement import (
    Outcome,
    final_outcomes,
    resolve_disagreement,
)
from factory.services.calibration import (
    calibration_items,
    draw_calibration,
    label_calibration,
)
from factory.services.context import Project
from factory.services.fulltext import fetch_fulltext
from factory.services.fulltext_screening import fulltext_queue
from factory.services.protocol import (
    amend_protocol,
    current_protocol,
)
from factory.services.screening import (
    open_pass,
    screen_next,
    screen_record,
)
from factory.services.search import list_works
from factory.sources.fulltext.base import RouteResult, not_retrieved
from tests.document_helpers import (
    ARTICLE,
    StubConverter,
    fetched_document,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.helpers import SourcesFor, _setup
from tests.route_helpers import StubRoute, always, retrieved
from tests.screening_helpers import _decide, _draw
from tests.world_cache import snapshot_world


def _include_all(
    project: Project, agent: Actor, human: Actor, protocol_id: str, *, leave: str | None = None
) -> None:
    """Both passes include every ordinary work and the human labels every calibration work."""
    calibration = set(calibration_items(project))
    for work in sorted(w.id for w in list_works(project)):
        if work == leave:
            continue
        if work in calibration:
            label_calibration(project, human, work, "include", None, Channel.CLI)
            continue
        _decide(project, agent, work, "A", "screening", "include", None, protocol_id)
        _decide(project, agent, work, "B", "screening", "include", None, protocol_id)


@snapshot_world
def _promoted_corpus(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    leave_one: bool = False,
) -> tuple[str, str | None]:
    """A corpus with both passes opened and every ordinary work included; with `leave_one`, the
    first ordinary work is left undecided, so it is not promoted. Returns the protocol id and
    the work left undecided."""
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    leave = _ordinary_pending(project) if leave_one else None
    _include_all(project, agent, human, protocol_id, leave=leave)
    return protocol_id, leave


def _ordinary_pending(project: Project) -> str:
    """An ordinary (non-calibration) corpus work, to be left undecided."""
    calibration = set(calibration_items(project))
    return sorted(w.id for w in list_works(project) if w.id not in calibration)[0]


FT = ScreeningStage.FULL_TEXT


PARAGRAPH_ANCHOR = "s3.p1"


PARAGRAPH_QUOTE = "Lorem ipsum dolor sit amet."


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


def _pdf(path: Path, *lines: str) -> Path:
    """A one-page PDF whose page 1 shows each line in Helvetica (extractable text)."""
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    resources = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    shown = " ".join(f"({line}) Tj 0 -16 Td" for line in lines)
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td {shown} ET".encode())
    page = writer.pages[0]
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _world(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    *,
    dual_sample: float = 1.0,
    calibration: int = 0,
    extra_items: Sequence[dict[str, Any]] = (),
) -> None:
    """The `corpus` fixture with a full-text plan declared first: the plan is a semantic
    amendment, so it precedes the title/abstract decisions that must stay current.
    `extra_items` are further OpenAlex results added to the corpus."""
    _setup(
        project,
        agent,
        human,
        mock_sources,
        dual_sample=0.5,
        random_works=0,
        extra_items=extra_items,
    )
    current = current_protocol(project)
    assert current is not None
    plan = ScreeningPlan(
        passes=2,
        dual_sample=dual_sample,
        kappa_floor=0.7,
        calibration_size=calibration,
        reviewers=current.spec.screening.reviewers,
    )
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"full_text_screening": plan}),
        reason="declare full text",
        semantic=True,
        effects={},
    )
    amended = current_protocol(project)
    assert amended is not None
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _include_all(project, agent, human, amended.protocol_id)


def _convert(project: Project, works: list[str], version: str = "1.0+a") -> None:
    for work in works:
        fetched_document(project, work, ARTICLE)
    run_convert(project, make_registry(StubConverter(version=version)))


CONTENT = b"LITERATURE-MARKER full text of a promoted work"


def _build(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> None:
    """Both passes include every ordinary work, so the corpus is promoted, and calibration is
    labelled by the human."""
    protocol_id = _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=0)
    _draw(project)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    _include_all(project, agent, human, protocol_id)


def _promoted(project: Project) -> list[str]:
    return sorted(
        w for w, outcome in final_outcomes(project).items() if outcome is Outcome.INCLUDED
    )


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _stub(route: Route, retrieve: set[str], content: bytes = CONTENT) -> StubRoute:
    """A route that retrieves for the works in `retrieve` (the set may change between passes)
    and otherwise gives its own fixed reason. The fixed reason is the route's name."""

    def answer(work: Any) -> RouteResult:
        if work.id in retrieve:
            media = "application/pdf" if route is Route.OA_PDF else "text/html"
            return retrieved(route, content, media_type=media)
        return not_retrieved(route, AttemptOutcome.NOT_AVAILABLE, f"no {route.value}")

    return StubRoute(route, answer)


def _routes(
    html: set[str] | None = None, source: set[str] | None = None, pdf: set[str] | None = None
) -> dict[Route, StubRoute]:
    return {
        Route.ARXIV_HTML: _stub(Route.ARXIV_HTML, html or set()),
        Route.ARXIV_SOURCE: _stub(Route.ARXIV_SOURCE, source or set()),
        Route.OA_PDF: _stub(Route.OA_PDF, pdf or set()),
    }


@pytest.fixture
def corpus(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> list[str]:
    _build(project, agent, human, mock_sources)
    return _promoted(project)


TA = ScreeningStage.TITLE_ABSTRACT


EITHER = ScreeningStage.EITHER


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


def _staged_world(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> World:
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

    # Full text screens promoted works that have a converted document (plan 2C task 4).
    for work in sorted(w for w, o in final_outcomes(project).items() if o.value == "included"):
        fetched_document(project, work, ARTICLE)
    run_convert(project, make_registry())

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


@dataclass
class FullTextWorld:
    protocol_id: str
    eligible: list[str]
    failed: str
    fetched_only: str
    unsought: str


def _failing_routes() -> dict[Route, StubRoute]:
    return {
        route: StubRoute(route, always(not_retrieved(route, AttemptOutcome.NOT_AVAILABLE, why)))
        for route, why in (
            (Route.ARXIV_HTML, "no html"),
            (Route.ARXIV_SOURCE, "no src"),
            (Route.OA_PDF, "paywalled"),
        )
    }


def _ta_world(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> FullTextWorld:
    """Title/abstract screening done and promoted; documents prepared; no full-text decision."""
    _setup(project, agent, human, mock_sources, dual_sample=0.5, random_works=6)
    pid = _declare_full_text(project, agent)
    _draw(project)
    for item in calibration_items(project):
        label_calibration(project, human, item, "include", None, Channel.CLI)
    open_pass(project, agent, PassLabel.A)
    open_pass(project, agent, PassLabel.B)
    cal = set(calibration_items(project))
    for work in sorted(w.id for w in list_works(project) if w.id not in cal):
        _both(project, agent, TA, work, ("include", None), ("include", None), pid)
    promoted = promoted_works(project)
    assert len(promoted) >= 8
    *rest, failed, fetched_only, unsought = promoted
    for work in rest:
        fetched_document(project, work, ARTICLE)
    run_convert(project, make_registry(StubConverter()))
    fetch_fulltext(project, routes=_failing_routes(), work_ids=[failed])
    fetched_document(project, fetched_only, ARTICLE)  # live document, never converted
    return FullTextWorld(pid, rest, failed, fetched_only, unsought)


def _ft_world(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> FullTextWorld:
    """Add full-text screening: one exclusion under EX04, one under EX05, one pending, rest in."""
    world = _ta_world(project, agent, human, mock_sources)
    draw_calibration(project, project.system_actor(), random_seed=5, stage=FT)
    open_pass(project, agent, PassLabel.A, stage=FT)
    open_pass(project, agent, PassLabel.B, stage=FT)
    first, second, third, *rest = world.eligible
    pid = world.protocol_id
    _both(project, agent, FT, first, ("exclude", "EX04"), ("exclude", "EX04"), pid)
    _both(project, agent, FT, second, ("exclude", "EX05"), ("exclude", "EX05"), pid)
    _decide_at(project, agent, FT, third, "A", "include", None, pid)  # B missing: pending
    for work in rest:
        _both(project, agent, FT, work, ("include", None), ("include", None), pid)
    return world

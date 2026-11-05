"""Read-time effects of notices and of a preferred document on extraction rows (living-C).

These run over the full-text extraction world of plan D (slow): included works with converted
documents, a declared schema and recorded rows. A fixture row set is written for two works so that
the effect of an act on one work can be compared with the other's, unit by unit.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pytest

from factory.events.envelope import Actor
from factory.model.fulltext import Route
from factory.model.notices import AssessmentDecision, NoticeKind, NoticeObserved
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.services.agreement import Outcome, final_outcomes
from factory.services.calibration import calibration_items
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.extraction import (
    ExtractBatch,
    extract_next,
    extract_record,
    stale_extractions,
    unit_states,
)
from factory.services.fulltext import fetch_fulltext
from factory.services.notices import assess_notice, dependent_works
from factory.services.protocol import current_protocol
from factory.services.screening import live_decisions
from factory.services.tasks import complete_task
from factory.services.versions import prefer_document
from factory.sources.registry import SourceFactory
from tests.document_helpers import ARTICLE, make_registry, run_convert
from tests.extraction_helpers import _declare_latency, _extractor, _row
from tests.fulltext_helpers import _screened_full_text_world
from tests.route_helpers import StubRoute, always, retrieved
from tests.screening_helpers import decide

pytestmark = pytest.mark.slow  # over ~60 s per file: dev runs deselect with -m "not slow"

FT = ScreeningStage.FULL_TEXT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
SESSION_A = "01JZ9Q3K5M7N8P0R2S4T6V8W1A"


@pytest.fixture
def ext_a() -> Actor:
    return _extractor(SESSION_A, "claude-opus-5-5")


@pytest.fixture
def world(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> list[str]:
    """The included works of the full-text world, extraction declared (every work dual)."""
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    _declare_latency(project, agent, 1.0)
    return sorted(w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED)


def _extract_work(project: Project, actor: Actor, work: str) -> tuple[str, str]:
    """Serve pass-A tasks until `work`'s, close it with two rows; (plain, latency) row ids."""
    for _ in range(60):
        batch: ExtractBatch | None = extract_next(project, actor, PassLabel.A).batch
        assert batch is not None, f"no task of {work}"
        if batch.records[0]["work_id"] != work:
            complete_task(project, actor, batch.task_id)
            continue
        res = extract_record(
            project,
            actor,
            batch.task_id,
            [_row(), _row("2", "t1.r3.c3", latency=_latency())],
            finish=True,
        )
        assert res.completed and not res.rows.rejected, res.rows.rejected
        plain, with_latency = res.rows.written
        return plain, with_latency
    raise AssertionError("too many tasks")


def _latency():  # type: ignore[no-untyped-def]
    from factory.model.extraction import FieldInput

    return FieldInput(value="1", anchor="t1", cell="t1.r3.c2", quote="1")


def _second_document(project: Project, work: str) -> str:
    """A second live document of `work` (arXiv source, HTML bytes) with a conversion."""
    body = ARTICLE + b"<!-- source copy -->"
    route = StubRoute(Route.ARXIV_SOURCE, always(retrieved(Route.ARXIV_SOURCE, body)))
    fetch_fulltext(
        project, routes={Route.ARXIV_SOURCE: route}, work_ids=[work], only=[Route.ARXIV_SOURCE]
    )
    run_convert(project, make_registry())
    from sqlalchemy import text

    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT document_id FROM fulltext_documents "
                "WHERE work_id = :w AND route = 'arxiv-source' AND superseded_by IS NULL"
            ),
            {"w": work},
        ).one()
    return str(row[0])


def _observe(project: Project, work: str, kind: NoticeKind, doi: str) -> str:
    """Record a notice of `work` as the notice check would (system actor); returns its id."""
    payload = NoticeObserved(
        notice_id=project.ids.new("ntc"),
        work_id=work,
        kind=kind,
        notice_date=None,
        notice_doi=doi,
        source="crossref",
        run_id=project.ids.new("run"),
        raw_blob="sha256:" + "b" * 64,
    )
    project.record(
        [
            project.events.make(
                "notice.observed", payload, project.system_actor(), refs=(payload.notice_id, work)
            )
        ]
    )
    return payload.notice_id


def _states(project: Project) -> dict[tuple[str, PassLabel], tuple[str, str | None]]:
    return {(s.work_id, s.pass_label): (s.state, s.reason) for s in unit_states(project)}


def test_affects_stales_only_named_fields_of_that_work(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    first, second = world[0], world[1]
    plain1, latency1 = _extract_work(project, ext_a, first)
    plain2, latency2 = _extract_work(project, ext_a, second)
    assert stale_extractions(project) == set()
    before = _states(project)

    notice = _observe(project, first, NoticeKind.CORRECTION, "10.2000/corr")
    assert stale_extractions(project) == set()  # observing stales nothing: a human decides
    assert _states(project) == before
    assess_notice(
        project,
        project.human_actor(),
        notice,
        AssessmentDecision.AFFECTS,
        fields=("latency",),
        rationale="the latency figure was corrected",
    )
    # Exactly the rows of that work carrying that field.
    assert stale_extractions(project) == {latency1}
    assert not {plain1, plain2, latency2} & stale_extractions(project)
    after = _states(project)
    assert {k for k in after if after[k] != before[k]} == {(first, PassLabel.A)}
    assert after[(first, PassLabel.A)] == ("stale", "notice")


def test_reextraction_queued_for_affected_units_only(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    first, second = world[0], world[1]
    _extract_work(project, ext_a, first)
    _extract_work(project, ext_a, second)
    notice = _observe(project, first, NoticeKind.CORRECTION, "10.2000/corr")
    assess_notice(
        project,
        project.human_actor(),
        notice,
        AssessmentDecision.AFFECTS,
        fields=("latency",),
        rationale="corrected",
    )
    served: list[str] = []
    fresh_task = None
    for _ in range(len(world) * 2 + 2):
        batch = extract_next(project, ext_a, PassLabel.A).batch
        if batch is None:
            break
        work = batch.records[0]["work_id"]
        served.append(work)
        if work == first:
            fresh_task = batch.task_id
            res = extract_record(
                project,
                ext_a,
                batch.task_id,
                [_row("2", "t1.r3.c3", latency=_latency())],
                finish=True,
            )
            assert res.completed and not res.rows.rejected
            new_row = res.rows.written[0]
        else:
            complete_task(project, ext_a, batch.task_id)
    # The corrected unit is served again; the unaffected unit of the other work never is.
    assert fresh_task is not None and first in served and second not in served
    # Re-recording after the assessment is not stale: the new row postdates the act.
    assert new_row not in stale_extractions(project)
    assert _states(project)[(first, PassLabel.A)][0] == "current"


def _serve_unit(project: Project, actor: Actor, work: str) -> str:
    for _ in range(60):
        batch = extract_next(project, actor, PassLabel.A).batch
        assert batch is not None, f"no task of {work}"
        if batch.records[0]["work_id"] == work:
            return batch.task_id
        complete_task(project, actor, batch.task_id)
    raise AssertionError("too many tasks")


def test_no_screening_outcome_changes(project: Project, ext_a: Actor, world: list[str]) -> None:
    first = world[0]
    _extract_work(project, ext_a, first)
    ta = {k: v.value for k, v in final_outcomes(project).items()}
    ft = {k: v.value for k, v in final_outcomes(project, stage=FT).items()}
    retraction = _observe(project, first, NoticeKind.RETRACTION, "10.2000/ret")
    assess_notice(
        project,
        project.human_actor(),
        retraction,
        AssessmentDecision.EXCLUDE,
        rationale="retracted",
    )
    assert {k: v.value for k, v in final_outcomes(project).items()} == ta
    assert {k: v.value for k, v in final_outcomes(project, stage=FT).items()} == ft


def test_dependents_include_extracted_not_included(
    project: Project, agent: Actor, ext_a: Actor, world: list[str]
) -> None:
    calibration = set(calibration_items(project))
    first = next(w for w in world if w not in calibration)  # a calibration label would decide
    _extract_work(project, ext_a, first)
    assert set(world) <= set(dependent_works(project))
    # Exclude the extracted work at title/abstract: it is no longer included at either stage.
    protocol = current_protocol(project)
    assert protocol is not None
    for label in PassLabel:
        for decision in live_decisions(project, label):
            if decision.work_id == first:
                decide(
                    project,
                    agent,
                    first,
                    protocol.protocol_id,
                    "exclude",
                    pass_label=label,
                    criterion="EX01",
                    supersedes=decision.decision_id,
                )
    assert final_outcomes(project)[first] is not Outcome.INCLUDED
    assert first in dependent_works(project)  # its live rows keep it a dependent
    assert dependent_works(project) == sorted(
        {*[w for w, o in final_outcomes(project).items() if o is Outcome.INCLUDED], first}
        | {w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED}
    )


def test_preference_stales_one_work(project: Project, ext_a: Actor, world: list[str]) -> None:
    first, second = world[0], world[1]
    first_rows = set(_extract_work(project, ext_a, first))
    second_rows = set(_extract_work(project, ext_a, second))
    assert stale_extractions(project) == set()
    before = {(s.work_id, s.pass_label): (s.state, s.reason) for s in unit_states(project)}

    preferred = _second_document(project, first)
    default = default_conversion(project, first)
    assert default is not None and default.document_id != preferred
    prefer_document(project, project.human_actor(), first, preferred, "complete source copy")

    assert stale_extractions(project) == first_rows  # that work's rows, and only those
    assert not stale_extractions(project) & second_rows
    after = {(s.work_id, s.pass_label): (s.state, s.reason) for s in unit_states(project)}
    changed = {k for k in after if after[k] != before[k]}
    assert changed == {(first, PassLabel.A)}
    assert after[(first, PassLabel.A)] == ("stale", "document-version")


# The lineage effect of a retraction is tested in tests/test_lineage_check.py
# (`test_retracted_basis_leaves_default_views`), where the lineage world is built.

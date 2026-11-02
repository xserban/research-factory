"""PRISMA 2020 flow and PRISMA-S search report, computed from events (plan 5b, task 1).

Every count comes from the corpus, the provenance rows and the live decisions; no test sets a
number. Both identities are asserted on every flow the tests read (plan ruling 2).
"""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from factory.events.envelope import Actor
from factory.model.chase import ChaseDirection
from factory.model.protocol import CriterionEffect, PressElement, PressFinding, ProtocolSpec
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.services.calibration import calibration_items
from factory.services.chase import search_chase
from factory.services.context import Project
from factory.services.dedup import active_merges, dedup_run, revert_merge
from factory.services.prisma import PrismaFlow, prisma_flow, search_report
from factory.services.probe import run_probe
from factory.services.protocol import amend_protocol, current_protocol, press_review
from factory.services.search import list_works, register_query, run_query
from factory.sources.registry import INTERFACES, SourceFactory
from tests.helpers import _positive_item, _protocol, _seed_item, openalex_item
from tests.test_chase_service import _citing, _corpus, _ordinary, _settle
from tests.test_screening_next import _decide

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
FULL_TEXT = "not assessed in this review stage"
MERGE_TITLE = "Linear attention in transformers"


def _assert_identities(flow: PrismaFlow) -> None:
    """The two PRISMA identities (plan ruling 2)."""
    identified = sum(flow.identified_databases.values()) + sum(flow.identified_other.values())
    assert identified - flow.duplicates_removed == flow.screened
    assert sum(flow.excluded.values()) + flow.pending + flow.included == flow.screened


def _merge_items() -> list[dict[str, Any]]:
    """Two records of one paper: one with a DOI, one without. The cascade merges them by title,
    first author and year."""
    return [
        openalex_item(
            title=MERGE_TITLE,
            author="Ada Zhou",
            published="2021-06-01",
            openalex_id="W500",
            doi="10.1000/merge",
        ),
        openalex_item(
            title=MERGE_TITLE, author="Ada Zhou", published="2021-06-01", openalex_id="W501"
        ),
    ]


def test_prisma_identities_hold(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)

    flow = prisma_flow(project)

    _assert_identities(flow)
    # Nine search records (six positives, three negatives); probe lookups of the same works
    # are not records (see test_probe_runs_never_counted).
    assert flow.identified_databases == {"openalex": 9}
    assert flow.identified_other == {"citation-chase": 0, "seed-admission": 0, "hand-search": 0}
    assert (flow.duplicates_removed, flow.screened) == (0, 9)
    assert (flow.included, flow.excluded, flow.pending) == (9, {}, 0)
    assert flow.provisional is False
    assert flow.protocol_id == protocol_id


def test_prisma_counts_chase_under_other_methods(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    dedup_run(project)
    citing = [_citing(n) for n in range(900, 910)]
    search_chase(project, human, [ChaseDirection.BACKWARD], sources=mock_sources(openalex=citing))
    dedup_run(project)

    flow = prisma_flow(project)

    _assert_identities(flow)
    assert flow.identified_other["citation-chase"] == 10
    assert flow.identified_databases == {"openalex": 9}
    # The ten chased works are undecided, so they are pending and the report is provisional.
    assert (flow.screened, flow.pending, flow.included) == (19, 10, 9)
    assert flow.provisional is True


def test_work_found_by_database_and_chase_counts_once_under_databases(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    [first] = [w for w in list_works(project) if w.id == _ordinary(project)[0]]
    duplicate = openalex_item(
        title=first.title,
        author="Ada Zhou",
        published="2020-01-01",
        openalex_id="W9999",
        doi=first.identifiers.doi,
    )
    search_chase(
        project,
        human,
        [ChaseDirection.BACKWARD],
        sources=mock_sources(openalex=[duplicate, _citing(901)]),
    )
    dedup_run(project)

    flow = prisma_flow(project)

    _assert_identities(flow)
    # The database work also has a chase row. It counts under databases only; the one chase-only
    # work is the sole citation-chase entry, and the duplicate removes nothing.
    assert flow.identified_other["citation-chase"] == 1
    assert flow.identified_databases == {"openalex": 9}
    assert (flow.duplicates_removed, flow.screened) == (0, 10)


def test_prisma_follows_reverted_merge(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources, extra=_merge_items())
    _settle(project, agent, human, protocol_id)
    dedup_run(project)

    merged = prisma_flow(project)

    _assert_identities(merged)
    # Eleven records; the two records of one paper are one canonical work.
    assert (merged.duplicates_removed, merged.screened, merged.included) == (1, 10, 10)
    [merge] = active_merges(project)
    revert_merge(project, human, merge.merge_id, "Distinct papers; the preprint is another work.")

    reverted = prisma_flow(project)

    _assert_identities(reverted)
    assert (reverted.duplicates_removed, reverted.screened, reverted.included) == (0, 11, 11)


def test_stale_decisions_count_as_pending(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id, verdict="exclude")
    before = prisma_flow(project)
    _assert_identities(before)
    assert before.excluded == {"EX01": 9}

    # Loosening EX01 makes the decisions that cite it doubtful: they are no longer live under
    # the current protocol, so their works are pending until they are decided again.
    current = current_protocol(project)
    assert current is not None
    dumped = current.spec.model_dump(mode="json")
    dumped["criteria"][1]["rule"] = "exclude topic 1 only in full-text studies"
    amend_protocol(
        project,
        human,
        ProtocolSpec.model_validate(dumped),
        reason="Narrow the exclusion",
        semantic=True,
        effects={"EX01": CriterionEffect.LOOSENED},
    )
    new = current_protocol(project)
    assert new is not None and new.protocol_id != protocol_id
    calibration = set(calibration_items(project))
    ordinary = [w for w in sorted(w.id for w in list_works(project)) if w not in calibration]
    _decide(project, agent, ordinary[0], "A", "screening", "include", None, new.protocol_id)
    _decide(project, agent, ordinary[0], "B", "screening", "include", None, new.protocol_id)

    after = prisma_flow(project)

    _assert_identities(after)
    # The calibration works keep their human labels; the ordinary works not re-decided are
    # pending, and nothing cites the stale exclusion any more.
    assert after.excluded == {"EX01": len(calibration)}
    assert after.included == 1
    assert after.pending == 9 - len(calibration) - 1
    assert after.provisional is True


def test_full_text_not_reported_as_zero(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)

    flow = prisma_flow(project)

    assert flow.full_text == FULL_TEXT
    assert flow.model_dump(mode="json")["full_text"] == FULL_TEXT


def test_probe_runs_never_counted(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    before = prisma_flow(project)
    # A probe finds a work no search found. It is stored, but it is not in the corpus and not
    # a record of any search.
    probe = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    run_probe(project, agent, [probe], sources=mock_sources(openalex=[_seed_item(999)]))

    after = prisma_flow(project)

    _assert_identities(after)
    assert after == before
    assert [row.purpose for row in search_report(project).rows] == [QueryPurpose.SEARCH]


def test_excluded_counted_by_cited_criterion(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id, verdict="exclude")

    flow = prisma_flow(project)

    _assert_identities(flow)
    assert flow.excluded == {"EX01": 9}
    assert (flow.included, flow.pending) == (0, 0)


def test_search_report_has_prisma_s_fields(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _corpus(project, agent, human, mock_sources)

    report = search_report(project)

    [row] = report.rows
    assert row.source == "openalex"
    assert row.interface == INTERFACES["openalex"]
    assert row.kind is QueryKind.KEYWORD
    assert row.text == "attention"
    assert row.filters == {}
    assert row.purpose is QueryPurpose.SEARCH
    assert isinstance(row.registered_at, datetime) and row.registered_at.tzinfo is not None
    assert (row.reported, row.retrieved, row.shortfall_reason) == (9, 9, None)
    assert row.deviation_id is None
    [run] = row.runs
    assert run.status is RunStatus.COMPLETE
    assert (run.reported_count, run.retrieved_count) == (9, 9)


def test_search_report_shortfall_carries_run_note(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _protocol(project, agent, human, mock_sources)
    items = [_positive_item(n) for n in (1, 2, 3)]
    sources = mock_sources(openalex=items, openalex_count=len(items) + 2)
    query = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    run_query(project, register_query(project, human, query, sources=sources), sources=sources)

    [row] = search_report(project).rows

    assert (row.reported, row.retrieved) == (5, 3)
    [run] = row.runs
    assert run.note is not None
    assert row.shortfall_reason == run.note


def test_flow_refuses_inconsistent_counts() -> None:
    """The model refuses a flow whose identities fail, so no caller can store one."""
    consistent: dict[str, Any] = {
        "identified_databases": {"openalex": 3},
        "identified_other": {"citation-chase": 0, "seed-admission": 0, "hand-search": 0},
        "duplicates_removed": 1,
        "screened": 2,
        "excluded": {},
        "pending": 0,
        "included": 2,
        "provisional": False,
        "protocol_id": None,
    }
    assert PrismaFlow(**consistent).screened == 2
    with pytest.raises(ValidationError):
        PrismaFlow(**{**consistent, "duplicates_removed": 0})
    with pytest.raises(ValidationError):
        PrismaFlow(**{**consistent, "included": 1})
    with pytest.raises(ValidationError):
        PrismaFlow(**{**consistent, "pending": 1, "included": 1})


def test_empty_project_reports_nothing(project: Project) -> None:
    flow = prisma_flow(project)

    _assert_identities(flow)
    assert (flow.screened, flow.included, flow.pending, flow.excluded) == (0, 0, 0, {})
    assert (flow.provisional, flow.protocol_id) == (False, None)
    report = search_report(project)
    assert report.rows == [] and report.press_review_id is None and report.limits == []


def test_unconfirmed_press_review_is_reported_as_unconfirmed(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _protocol(project, agent, human, mock_sources, ready=False)
    finding = PressFinding(
        element=PressElement.TEXT_WORDS, finding="Add a synonym.", severity="minor"
    )
    review_id = press_review(project, agent, protocol_id, (finding,))

    report = search_report(project)

    assert (report.press_review_id, report.press_confirmed) == (review_id, False)

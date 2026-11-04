"""PRISMA 2020 flow and PRISMA-S search report, computed from events (plan 5b, task 1).

Every count comes from the corpus, the provenance rows and the live decisions; no test sets a
number. Both identities are asserted on every flow the tests read (plan ruling 2).
"""

import json
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from factory.cli.render import prisma_markdown
from factory.events.envelope import Actor
from factory.model.chase import ChaseDirection
from factory.model.protocol import CriterionEffect, PressElement, PressFinding, ProtocolSpec
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.seed import SeedKind, SeedSpec
from factory.model.work import Author, Dates, Identifiers, Provenance, ProvenanceMethod, Work
from factory.services.calibration import calibration_items
from factory.services.chase import search_chase
from factory.services.context import Project
from factory.services.dedup import active_merges, dedup_run, revert_merge
from factory.services.methods import methods_report, render_methods
from factory.services.prisma import PrismaFlow, prisma_flow, search_report
from factory.services.probe import run_probe
from factory.services.protocol import (
    amend_protocol,
    current_protocol,
    press_review,
    record_deviation,
)
from factory.services.search import list_works, register_query, run_query
from factory.services.seeds import add_seeds, admit_seed, explain_seed_miss
from factory.sources.base import RawPage, SearchResult
from factory.sources.registry import INTERFACES, SourceFactory
from tests.helpers import T0, _positive_item, _protocol, _seed_item, openalex_item
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

    # Plan 2C: the full-text box is derived. Before any full-text decision it is provisional and
    # carries no outcome, never a zero that reads as "assessed and nothing found".
    assert flow.full_text.stage_run is False
    assert flow.full_text.assessed == 0 and flow.full_text.included == 0
    assert flow.included_in_review is None
    assert flow.model_dump(mode="json")["full_text"]["stage_run"] is False
    markdown = prisma_markdown(flow)
    assert "not assessed in this review stage" in markdown
    assert "assessed for eligibility" not in markdown and "included at full text" not in markdown
    methods = render_methods(methods_report(project))
    assert (
        "full-text stage has not run" in methods
        and "assessed" not in methods.split("Full-text screening.")[1].split("\n")[0]
    )


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


HAND_TITLE = "A manually retrieved report"
SEED_DOI = "10.1000/p7"


class _HandSearch:
    """A hand-search source: one manually retrieved record, with `hand-search` provenance.

    No service writes hand-search provenance yet (the method exists so that check can list it),
    so this adapter stands in for one: it archives its page and returns a record whose provenance
    row carries `hand-search`, which is what the projector stores for a parsed record."""

    name = "hand"
    kinds = frozenset({QueryKind.KEYWORD})

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: Callable[[RawPage], str],
        resume_from: str | None = None,
    ) -> SearchResult:
        ref = archive(
            RawPage(
                ordinal=0,
                body=json.dumps({"title": HAND_TITLE}),
                url="hand://manual",
                fetched_at=T0,
            )
        )
        work = Work.build(
            title=HAND_TITLE,
            authors=[Author(name="Ben Li")],
            dates=Dates(published=date(2019, 1, 1)),
            identifiers=Identifiers(doi="10.1000/hand"),
            provenance=[
                Provenance(
                    source="hand",
                    run_id=run_id,
                    query_id=query_id,
                    at=T0,
                    raw_blob=ref,
                    method=ProvenanceMethod.HAND_SEARCH,
                )
            ],
        )
        return SearchResult(
            source="hand",
            query_sent=spec.text,
            reported_count=1,
            works=[work],
            pages=1,
            status=RunStatus.COMPLETE,
        )


def _admit_seed_seven(project: Project, human: Actor, mock_sources: SourcesFor) -> None:
    """Admit the positive seed `Paper 7` (DOI 10.1000/p7), missing from the corpus, by lookup."""
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Paper 7", doi=SEED_DOI)
    [outcome] = add_seeds(project, human, [spec], sources=mock_sources()).written
    explain_seed_miss(
        project, human, outcome.seed_id, "not indexed", ProvenanceMethod.SEED_ADMISSION
    )
    deviation = record_deviation(project, human, description="Seed lookup", reason="Admission.")
    found = openalex_item(
        title="Paper 7", author="Ada Zhou", published="2020-01-01", openalex_id="W7", doi=SEED_DOI
    )
    admit_seed(
        project,
        human,
        outcome.seed_id,
        sources=mock_sources(openalex=[found]),
        deviation_id=deviation,
    )


def test_seed_admission_counts_under_its_method(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _admit_seed_seven(project, human, mock_sources)
    _settle(project, agent, human, protocol_id)

    flow = prisma_flow(project)

    _assert_identities(flow)
    assert flow.identified_other == {"citation-chase": 0, "seed-admission": 1, "hand-search": 0}
    assert flow.identified_databases == {"openalex": 9}
    assert (flow.duplicates_removed, flow.screened, flow.included) == (0, 10, 10)


def test_hand_search_counts_under_its_method(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    sources = {"hand": SourceFactory(_HandSearch.kinds, lambda _s, _c: _HandSearch())}
    deviation = record_deviation(
        project, human, description="Manual entry", reason="Hand-searched journal."
    )
    query = QuerySpec(source="hand", kind=QueryKind.KEYWORD, text="manual entry")
    query_id = register_query(project, human, query, sources=sources, deviation_id=deviation)
    run_query(project, query_id, sources=sources)
    _settle(project, agent, human, protocol_id)

    flow = prisma_flow(project)

    _assert_identities(flow)
    assert flow.identified_other == {"citation-chase": 0, "seed-admission": 0, "hand-search": 1}
    assert flow.identified_databases == {"openalex": 9}
    assert (flow.duplicates_removed, flow.screened, flow.included) == (0, 10, 10)


def test_chase_outranks_seed_admission(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _admit_seed_seven(project, human, mock_sources)
    _settle(project, agent, human, protocol_id)
    # The chase finds the admitted work again (same DOI), so it carries both methods.
    duplicate = openalex_item(
        title="Paper 7",
        author="Ada Zhou",
        published="2020-01-01",
        openalex_id="W9998",
        doi=SEED_DOI,
    )
    search_chase(
        project,
        human,
        [ChaseDirection.BACKWARD],
        sources=mock_sources(openalex=[duplicate, _citing(910)]),
    )
    dedup_run(project)

    flow = prisma_flow(project)

    _assert_identities(flow)
    # The admitted work counts once, under citation-chase (precedence over seed-admission); the
    # newly cited work is the other chase entry.
    assert flow.identified_other == {"citation-chase": 2, "seed-admission": 0, "hand-search": 0}
    assert (flow.duplicates_removed, flow.screened) == (0, 11)
    assert (flow.pending, flow.included) == (1, 10)


def test_excluded_total_is_the_sum_of_the_breakdown_and_not_serialised() -> None:
    flow = PrismaFlow.model_validate(
        {
            "identified_databases": {"openalex": 5},
            "identified_other": {},
            "duplicates_removed": 0,
            "screened": 5,
            "excluded": {"EX01": 2, "EX02": 1},
            "pending": 0,
            "included": 2,
            "provisional": False,
            "protocol_id": "P@00000000",
        }
    )

    assert flow.excluded_total == 3
    assert "excluded_total" not in flow.model_dump()

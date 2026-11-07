"""Admission of imported records as screened candidates (Import-B task 4).

Every record, work and identifier is invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.decisions import DecisionLevel
from factory.model.imports import ImportRole
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.model.seed import SeedKind, SeedSpec
from factory.model.work import ProvenanceMethod
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.dedup import canonical_works, dedup_run
from factory.services.import_admit import admit_import, plan_admission
from factory.services.import_resolve import resolve_import
from factory.services.search import corpus_size, list_works, register_query, run_query
from factory.services.seeds import _found_by, add_seeds, seed_check, seed_recall, split_seeds
from tests.document_helpers import events_of_type
from tests.helpers import SourcesFor, _seed_item, bind_ids
from tests.import_helpers import (
    admission_records,
    admit_lookups,
    bib_entry,
    declare_library,
    import_bib,
)
from tests.references_service_helpers import Lookups, oa_item


@dataclass
class Admission:
    project: Project
    import_id: str
    lookups: Lookups
    corpus_doi: str


def _corpus_doi(project: Project) -> str:
    doi = next(w.identifiers.doi for w in canonical_works(project) if w.identifiers.doi)
    assert doi is not None
    return doi


@pytest.fixture
def admission(project: Project, corpus: None, agent: Actor, tmp_path: Path) -> Admission:
    """A pilot project with promoted works, a declared library and a resolved corpus import."""
    declare_library(project, agent)
    doi = _corpus_doi(project)
    imp = import_bib(project, tmp_path, admission_records(doi))
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    return Admission(project, imp, lookups, doi)


def events_of_type_in_order(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _event_types(project: Project) -> list[str]:
    return [e.type for e in events_of_type_in_order(project)]


def test_plan_names_queries_by_source(admission: Admission) -> None:
    specs = plan_admission(admission.project, admission.import_id)
    assert [(s.source, s.kind, s.purpose) for s in specs] == [
        ("openalex", QueryKind.FILTER, QueryPurpose.IMPORT),
        ("importlist", QueryKind.ID_LIST, QueryPurpose.IMPORT),
    ]
    assert specs[0].text == "openalex:W504"
    assert specs[1].text == f"{admission.import_id}:2"  # the titled record without identifiers


def test_admission_plan_written_before_queries(admission: Admission) -> None:
    project = admission.project
    summary = admit_import(project, admission.import_id, sources=admission.lookups.sources())
    types = _event_types(project)
    planned = types.index("import.admission_planned")
    assert types.count("import.admission_planned") == 1
    assert "query.registered" not in types[planned:planned] and (
        types[planned + 1 :].index("query.registered") >= 0
    )
    first_import_query = next(
        i
        for i, e in enumerate(events_of_type_in_order(project))
        if e.type == "query.registered" and e.payload["spec"]["purpose"] == "import"  # type: ignore[index]
    )
    assert planned < first_import_query
    registered = [
        e
        for e in events_of_type(project, "query.registered")
        if e.payload["spec"]["purpose"] == "import"  # type: ignore[index]
    ]
    assert len(registered) == len(summary.runs) == 2
    [plan] = events_of_type(project, "import.admission_planned")
    assert [q["text"] for q in plan.payload["queries"]] == [  # type: ignore[attr-defined]
        e.payload["spec"]["text"]
        for e in registered  # type: ignore[index]
    ]
    # each import query names the import in its refs
    assert all(admission.import_id in e.refs for e in registered)


def test_reference_role_refused(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    declare_library(project, agent)
    imp = import_bib(
        project, tmp_path, admission_records(_corpus_doi(project)), role=ImportRole.REFERENCE
    )
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    before = len(_event_types(project))
    with pytest.raises(FactoryValidationError) as err:
        admit_import(project, imp, sources=lookups.sources())
    assert "reference" in str(err.value)
    assert len(_event_types(project)) == before


def test_pilot_needs_library_sources(project: Project, corpus: None, tmp_path: Path) -> None:
    imp = import_bib(project, tmp_path, admission_records(_corpus_doi(project)))
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    before = len(_event_types(project))
    with pytest.raises(FactoryValidationError) as err:
        admit_import(project, imp, sources=lookups.sources())
    assert any(i.field == "library_sources" for i in err.value.issues)
    assert len(_event_types(project)) == before
    assert "import.admission_planned" not in _event_types(project)


def test_exploratory_admits_with_gap(explore_project: Project, tmp_path: Path) -> None:
    project = explore_project
    imp = import_bib(project, tmp_path, admission_records("10.1000/none"))
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    summary = admit_import(project, imp, sources=lookups.sources())
    assert [g.field for g in summary.gaps] == ["library_sources"]
    assert summary.new_works > 0 and summary.failed_runs == 0


def test_unresolved_import_is_refused(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    declare_library(project, agent)
    imp = import_bib(project, tmp_path, admission_records(_corpus_doi(project)))
    with pytest.raises(FactoryValidationError) as err:
        admit_import(project, imp, sources=admit_lookups().sources())
    assert "resolve" in str(err.value)


def test_unconfirmed_records_block_admission(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    from tests.references_service_helpers import oa_item

    declare_library(project, agent)
    from tests.import_helpers import bib_entry

    imp = import_bib(
        project,
        tmp_path,
        [bib_entry("a", "Efficient Reed Transformers v2", year=2021, author="Lee, Bo")],
    )
    lookups = Lookups(openalex=[oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501")])
    resolve_import(project, imp, sources=lookups.sources())
    before = len(_event_types(project))
    with pytest.raises(FactoryValidationError) as err:
        admit_import(project, imp, sources=lookups.sources())
    message = str(err.value)
    assert "1 record" in message and "unconfirmed" in message
    assert len(_event_types(project)) == before


def test_admitted_works_are_pending_with_library_import_provenance(admission: Admission) -> None:
    project = admission.project
    before = corpus_size(project)[0]
    summary = admit_import(project, admission.import_id, sources=admission.lookups.sources())
    assert summary.new_works == 2 and corpus_size(project)[0] == before + 2
    assert summary.already_in_corpus == 1 and summary.failed_runs == 0
    imported = [
        w
        for w in list_works(project)
        if any(e.method is ProvenanceMethod.LIBRARY_IMPORT for e in w.provenance)
    ]
    assert len(imported) == 2
    assert {e.source for w in imported for e in w.provenance} == {"openalex", "importlist"}
    outcomes = final_outcomes(project)
    assert all(outcomes[w.id] is Outcome.PENDING for w in imported)


def test_second_admission_after_success_is_refused(admission: Admission) -> None:
    admit_import(admission.project, admission.import_id, sources=admission.lookups.sources())
    before = len(_event_types(admission.project))
    with pytest.raises(FactoryValidationError):
        admit_import(admission.project, admission.import_id, sources=admission.lookups.sources())
    assert len(_event_types(admission.project)) == before


def test_failed_admission_can_be_retried(admission: Admission) -> None:
    project = admission.project
    admission.lookups.fail_openalex = True
    first = admit_import(project, admission.import_id, sources=admission.lookups.sources())
    assert first.failed_runs == 1  # the openalex query; the offline importlist query succeeded
    # one run succeeded, so the import is admitted: a retry would double-admit
    with pytest.raises(FactoryValidationError):
        admit_import(project, admission.import_id, sources=admission.lookups.sources())


def test_all_failed_admission_can_be_retried(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    from tests.import_helpers import bib_entry

    declare_library(project, agent)
    imp = import_bib(
        project,
        tmp_path,
        [
            bib_entry(
                "a", "Sedge Mapping Methods", year=2015, author="Kim, A", doi="10.9999/sedge.1"
            )
        ],
    )
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    lookups.fail_openalex = True
    first = admit_import(project, imp, sources=lookups.sources())
    assert first.failed_runs == 1 and first.new_works == 0
    lookups.fail_openalex = False
    second = admit_import(project, imp, sources=lookups.sources())
    assert second.failed_runs == 0 and second.new_works == 1
    assert len(events_of_type(project, "import.admission_planned")) == 2


def test_dedup_links_import_to_searched_work(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    from tests.import_helpers import bib_entry
    from tests.references_service_helpers import oa_item

    declare_library(project, agent)
    twin = next(w for w in canonical_works(project) if w.identifiers.doi)
    author = twin.authors[0].name
    lookups = Lookups(
        openalex=[
            oa_item(twin.title, author, twin.dates.year or 2020, "W700", doi="10.9999/twin.1")
        ]
    )
    imp = import_bib(
        project,
        tmp_path,
        [
            bib_entry(
                "a",
                twin.title,
                year=twin.dates.year or 2020,
                author="Zhou, Ada",
                doi="10.9999/twin.1",
            )
        ],
    )
    resolve_import(project, imp, sources=lookups.sources())
    admit_import(project, imp, sources=lookups.sources())
    summary = dedup_run(project)
    assert len(summary.created) == 1  # the imported work joins its searched twin
    assert summary.canonical == summary.works - 1


def test_pass_b_sample_extended_for_admitted(admission: Admission, agent: Actor) -> None:
    from factory.model.screening import PassLabel
    from factory.services.screening import screen_next

    project = admission.project
    admit_import(project, admission.import_id, sources=admission.lookups.sources())
    before = len(events_of_type(project, "screening.sample_extended"))
    screen_next(project, agent, PassLabel.B)
    extensions = events_of_type(project, "screening.sample_extended")
    assert len(extensions) == before + 1
    imported = {
        w.id
        for w in list_works(project)
        if any(e.method is ProvenanceMethod.LIBRARY_IMPORT for e in w.provenance)
    }
    assert imported <= set(extensions[-1].payload["considered"])  # type: ignore[arg-type]


def test_library_import_only_seed_is_not_a_search_find() -> None:
    from datetime import UTC, datetime

    from factory.model.work import Provenance, Work

    def work(method: ProvenanceMethod) -> Work:
        return Work.build(
            title="Made-Up Pears",
            provenance=[
                Provenance(
                    source="importlist",
                    run_id="run_01JZ9Q3K5M7N8P0R2S4T6V8W1C",
                    query_id="qry_01JZ9Q3K5M7N8P0R2S4T6V8W1D",
                    at=datetime(2026, 11, 5, tzinfo=UTC),
                    raw_blob="sha256:" + "a" * 64,
                    method=method,
                )
            ],
        )

    assert _found_by([work(ProvenanceMethod.LIBRARY_IMPORT)], set()) == "admission"
    assert _found_by([work(ProvenanceMethod.DATABASE)], set()) == "search"


def test_held_out_seed_found_only_by_import_does_not_raise_recall(
    explore_project: Project, human: Actor, mock_sources: SourcesFor, tmp_path: Path
) -> None:
    """Decision 54: a library import is not a search find, so held-out recall stays put."""
    project = explore_project
    for n in (1, 2, 3):
        spec = SeedSpec(kind=SeedKind.POSITIVE, cite=f"Paper {n}", doi=f"10.1000/p{n}")
        add_seeds(
            project,
            human,
            [spec],
            sources=mock_sources(openalex=[_seed_item(n)]),
            decision_ids=bind_ids(project, human, DecisionLevel.SEEDS),
        )
    split = split_seeds(project, random_seed=7)
    [held_out] = split.held_out
    sources = mock_sources(
        openalex=[_seed_item(int(s.removeprefix("SEED"))) for s in split.development]
    )
    query = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    run_query(project, register_query(project, human, query, sources=sources), sources=sources)
    assert seed_recall(project).held_out == 0.0

    n = int(held_out.removeprefix("SEED"))
    lookups = Lookups(
        openalex=[oa_item(f"Paper {n}", "Ada Zhou", 2020, f"W{n}", doi=f"10.1000/p{n}")]
    )
    imp = import_bib(
        project,
        tmp_path,
        [bib_entry("a", f"Paper {n}", year=2020, author="Zhou, Ada", doi=f"10.1000/p{n}")],
    )
    resolve_import(project, imp, sources=lookups.sources())
    admit_import(project, imp, sources=lookups.sources())

    check = next(c for c in seed_check(project) if c.seed_id == held_out)
    assert (check.status, check.found_by_search, check.found_by) == (
        "retrieved",
        False,
        "admission",
    )
    recall = seed_recall(project)
    assert recall.held_out == 0.0 and recall.development == 1.0
    assert recall.held_out_admitted == 1

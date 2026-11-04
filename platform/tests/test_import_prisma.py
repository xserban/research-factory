"""PRISMA counts and the search report with imports (Import-B task 4, review focus 2 and 3).

Every record and work is invented.
"""

from __future__ import annotations

import json
from pathlib import Path

from factory.events.envelope import Actor
from factory.imports.model import ImportFormat
from factory.model.imports import ImportRole
from factory.model.search import QueryKind, QuerySpec
from factory.services.context import Project
from factory.services.import_admit import admit_import
from factory.services.import_resolve import resolve_import
from factory.services.prisma import prisma_flow, search_report
from factory.services.search import register_query, run_query
from tests.helpers import SourcesFor, openalex_item
from tests.import_helpers import (
    admission_records,
    admit_lookups,
    bib_entry,
    declare_library,
    import_bib,
)
from tests.test_import_admit import _corpus_doi

FLOW_KEYS = [
    "identified_databases",
    "identified_other",
    "identified_other_detail",
    "duplicates_removed",
    "screened",
    "excluded",
    "pending",
    "included",
    "full_text",
    "included_in_review",
    "provisional",
    "protocol_id",
]
OTHER_KEYS = ["citation-chase", "seed-admission", "hand-search", "supplied"]
ROW_KEYS = [
    "query_id",
    "source",
    "interface",
    "kind",
    "text",
    "filters",
    "purpose",
    "registered_at",
    "runs",
    "reported",
    "retrieved",
    "shortfall_reason",
    "deviation_id",
    "round_id",
    "direction",
    "via",
    "round_no",
    "new_after_dedup",
    "included",
]


def test_prisma_unchanged_without_imports(project: Project, corpus: None) -> None:
    """No import queries: the flow and the report carry exactly the keys they had before."""
    flow = json.loads(prisma_flow(project).model_dump_json())
    assert list(flow) == FLOW_KEYS
    assert list(flow["identified_other"]) == OTHER_KEYS
    report = json.loads(search_report(project).model_dump_json())
    assert report["rows"] and all(list(row) == ROW_KEYS for row in report["rows"])


def test_unadmitted_imports_change_nothing(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    before = (prisma_flow(project).model_dump_json(), search_report(project).model_dump_json())
    declare_library(project, agent)
    for role in (ImportRole.REFERENCE, ImportRole.CORPUS):
        imp = import_bib(
            project,
            tmp_path,
            admission_records(_corpus_doi(project)),
            role=role,
            name=f"{role.value}.bib",
        )
        resolve_import(project, imp, sources=admit_lookups().sources())
    flow = json.loads(prisma_flow(project).model_dump_json())
    assert list(flow["identified_other"]) == OTHER_KEYS
    assert list(json.loads(search_report(project).model_dump_json())["rows"][0]) == ROW_KEYS
    assert json.loads(before[0])["screened"] == flow["screened"]


def test_admitted_works_count_under_library_import(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    declare_library(project, agent)
    before = prisma_flow(project)
    imp = import_bib(project, tmp_path, admission_records(_corpus_doi(project)))
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    admit_import(project, imp, sources=lookups.sources())
    flow = prisma_flow(project)  # the model's own identities hold on construction
    assert flow.identified_other["library-import"] == 2
    assert list(flow.identified_other)[-1] == "library-import"
    assert flow.screened == before.screened + 2
    assert flow.pending == before.pending + 2
    assert flow.identified_databases == before.identified_databases
    assert flow.duplicates_removed == before.duplicates_removed


def test_database_precedence_over_import_found_first(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    """An imported record of a work a database search found adds nothing to other methods."""
    declare_library(project, agent)
    before = prisma_flow(project)
    imp = import_bib(
        project,
        tmp_path,
        [bib_entry("c", "Paper 2", year=2020, author="Zhou, Ada", doi=_corpus_doi(project))],
    )
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    admit_import(project, imp, sources=lookups.sources())
    flow = prisma_flow(project)
    assert flow.screened == before.screened
    assert flow.identified_other.get("library-import", 0) == 0
    assert flow.identified_databases == before.identified_databases


def test_database_precedence_over_import(
    project: Project,
    corpus: None,
    agent: Actor,
    human: Actor,
    tmp_path: Path,
    mock_sources: SourcesFor,
) -> None:
    """Imported first, then found by a search: the work counts as database, once."""
    declare_library(project, agent)
    imp = import_bib(project, tmp_path, admission_records(_corpus_doi(project)))
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    admit_import(project, imp, sources=lookups.sources())
    imported = prisma_flow(project)
    assert imported.identified_other["library-import"] == 2

    item = openalex_item(
        title="Sedge Mapping Methods",
        author="Ana Kim",
        published="2015-01-01",
        openalex_id="W504",
        doi="10.9999/sedge.1",
    )
    sources = mock_sources(openalex=[item])
    query = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    run_query(project, register_query(project, human, query, sources=sources), sources=sources)

    flow = prisma_flow(project)
    assert flow.identified_other["library-import"] == 1
    assert (
        sum(flow.identified_databases.values()) == sum(imported.identified_databases.values()) + 1
    )
    assert flow.screened == imported.screened
    assert flow.duplicates_removed == imported.duplicates_removed


def test_search_report_lists_import_queries(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    declare_library(project, agent)
    imp = import_bib(project, tmp_path, admission_records(_corpus_doi(project)))
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    admit_import(project, imp, sources=lookups.sources())
    report = search_report(project)
    rows = [r for r in report.rows if r.purpose.value == "import"]
    assert len(rows) == 2
    for row in rows:
        assert row.import_id == imp
        assert row.import_format is ImportFormat.BIBTEX
        assert row.import_file_hash and row.import_file_hash.startswith("sha256:")
        assert row.import_parser_version
    others = [r for r in report.rows if r.purpose.value != "import"]
    assert all(r.import_id is None for r in others)
    assert all("import_id" not in json.loads(r.model_dump_json()) for r in others)

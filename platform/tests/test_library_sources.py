"""The protocol's `library_sources` section and the gate on `import` queries (Import-B task 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from factory.errors import ValidationIssue
from factory.events.envelope import Actor
from factory.imports.model import ImportFormat
from factory.model.imports import ImportAdmissionPlanned, ImportRole, PlannedImportQuery
from factory.model.protocol import (
    AMENDABLE_FIELDS,
    LibrarySource,
    ProtocolSpec,
    protocol_version,
)
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.model.work import Provenance, ProvenanceMethod, Work
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol, search_authorization
from tests.extraction_helpers import PINNED_P_ID
from tests.helpers import T0, SourcesFor, pilot_protocol_spec, ready_protocol
from tests.import_helpers import bib_entry, import_bib

LIB = LibrarySource(name="default", format=ImportFormat.BIBTEX, role=ImportRole.CORPUS)
IMPORT_Q = QuerySpec(
    source="openalex",
    kind=QueryKind.FILTER,
    text="doi:10.9999/x.1",
    purpose=QueryPurpose.IMPORT,
)


def _fields(issues: list[ValidationIssue]) -> set[str]:
    return {issue.field for issue in issues}


def _plan(project: Project, import_id: str, *queries: QuerySpec) -> None:
    payload = ImportAdmissionPlanned(
        import_id=import_id,
        queries=tuple(
            PlannedImportQuery(source=q.source, kind=q.kind, text=q.text, record_keys=())
            for q in queries
        ),
    )
    project.record(
        [project.events.make("import.admission_planned", payload, project.human_actor())]
    )


def test_p_id_unchanged_without_library_sources() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    assert spec.library_sources is None
    assert protocol_version(spec) == PINNED_P_ID


def test_library_sources_are_hashed_and_order_free() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    other = LibrarySource(name="Pears", format=ImportFormat.CSL, role=ImportRole.REFERENCE)
    one = spec.model_copy(update={"library_sources": (LIB, other)})
    two = spec.model_copy(update={"library_sources": (other, LIB)})
    assert protocol_version(one) != PINNED_P_ID
    assert protocol_version(one) == protocol_version(two)
    assert protocol_version(
        spec.model_copy(update={"library_sources": (LIB,)})
    ) != protocol_version(one)
    assert "library_sources" in AMENDABLE_FIELDS


def test_duplicate_library_source_is_refused() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1").model_dump(mode="json")
    entry = {"name": "default", "format": "bibtex", "role": "corpus"}
    spec["library_sources"] = [entry, dict(entry, role="reference")]
    with pytest.raises(ValidationError):
        ProtocolSpec.model_validate(spec)
    spec["library_sources"] = [dict(entry, name=" ")]
    with pytest.raises(ValidationError):
        ProtocolSpec.model_validate(spec)


def test_library_sources_amendable_and_hashed(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources, press=False)
    old = current_protocol(project)
    assert old is not None
    new = old.spec.model_copy(update={"library_sources": (LIB,)})
    amend_protocol(project, agent, new, reason="declare the library", semantic=True, effects={})
    current = current_protocol(project)
    assert current is not None and current.spec.library_sources == (LIB,)
    assert current.protocol_id != old.protocol_id


def test_import_query_refused_without_import_id(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    assert _fields(search_authorization(project, IMPORT_Q, deviation_id=None)) >= {"import_id"}


def test_import_query_refused_without_import_id_when_exploratory(explore_project: Project) -> None:
    issues = search_authorization(explore_project, IMPORT_Q, deviation_id=None)
    assert _fields(issues) == {"import_id"}


def test_import_query_authorised_only_by_the_admission_that_planned_it(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, tmp_path: Path
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    imp = import_bib(project, tmp_path, [bib_entry("a", "Made-Up Pears", year=2019, author="Q, A")])
    other = import_bib(
        project,
        tmp_path,
        [bib_entry("b", "Made-Up Figs", year=2019, author="Q, A")],
        name="other.bib",
    )
    # nothing planned yet: the query is not authorised, even with an import named
    issues = search_authorization(project, IMPORT_Q, deviation_id=None, import_id=imp)
    assert _fields(issues) == {"import_id", "query"}
    _plan(project, imp, IMPORT_Q)
    assert search_authorization(project, IMPORT_Q, deviation_id=None, import_id=imp) == []
    # another import did not plan it; an unplanned text is not covered either
    issues = search_authorization(project, IMPORT_Q, deviation_id=None, import_id=other)
    assert "import_id" in _fields(issues)
    unplanned = IMPORT_Q.model_copy(update={"text": "doi:10.9999/other"})
    issues = search_authorization(project, unplanned, deviation_id=None, import_id=imp)
    assert "import_id" in _fields(issues)


def test_import_plan_keeps_other_gates(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, tmp_path: Path
) -> None:
    ready_protocol(project, agent, human, mock_sources, press=False)
    imp = import_bib(project, tmp_path, [bib_entry("a", "Made-Up Pears", year=2019, author="Q, A")])
    _plan(project, imp, IMPORT_Q)
    issues = search_authorization(project, IMPORT_Q, deviation_id=None, import_id=imp)
    assert _fields(issues) == {"press"}


def test_provenance_method_round_trip() -> None:
    assert ProvenanceMethod("library-import") is ProvenanceMethod.LIBRARY_IMPORT
    assert list(ProvenanceMethod)[-1] is ProvenanceMethod.LIBRARY_IMPORT
    assert QueryPurpose("import") is QueryPurpose.IMPORT
    work = Work.build(
        title="Made-Up Pears",
        provenance=[
            Provenance(
                source="importlist",
                run_id="run_01JZ9Q3K5M7N8P0R2S4T6V8W1C",
                query_id="qry_01JZ9Q3K5M7N8P0R2S4T6V8W1D",
                at=T0,
                raw_blob="sha256:" + "a" * 64,
                raw_ref="imp_01JZ9Q3K5M7N8P0R2S4T6V8W1E:1",
                method=ProvenanceMethod.LIBRARY_IMPORT,
            )
        ],
    )
    again = Work.model_validate_json(work.model_dump_json())
    assert again.provenance[0].method is ProvenanceMethod.LIBRARY_IMPORT


def test_library_source_gaps_match_collection_format_and_role() -> None:
    from factory.services.protocol_rules import library_source_gaps

    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    assert library_source_gaps(spec, None, ImportFormat.BIBTEX)[0].field == "library_sources"
    declared = spec.model_copy(
        update={
            "library_sources": (
                LIB,
                LibrarySource(name="Refs", format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE),
            )
        }
    )
    assert library_source_gaps(declared, None, ImportFormat.BIBTEX) == []
    assert library_source_gaps(declared, "default", ImportFormat.BIBTEX) == []
    assert library_source_gaps(declared, None, ImportFormat.CSL) != []  # another format
    assert library_source_gaps(declared, "Refs", ImportFormat.BIBTEX) != []  # a reference entry
    assert library_source_gaps(declared, "Other", ImportFormat.BIBTEX) != []

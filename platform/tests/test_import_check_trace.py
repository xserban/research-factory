"""Import findings in `check` and the import kinds in `trace` (Import-C task 4).

Every record, work and file is invented.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.imports.model import ImportFormat
from factory.model.imports import ImportRole
from factory.model.project import RigorMode
from factory.model.references import Decision
from factory.services.check import Finding, agent_check, check
from factory.services.context import Project
from factory.services.import_admit import admit_import
from factory.services.import_attach import attach_import
from factory.services.import_resolve import decide_import, resolve_import
from factory.services.imports import list_import_records, record_import
from factory.services.trace import TraceNode, agent_trace, trace
from tests.helpers import SourcesFor, ready_protocol
from tests.import_helpers import (
    admission_records,
    admit_lookups,
    bib_entry,
    declare_library,
    import_bib,
)
from tests.references_service_helpers import Lookups, oa_item
from tests.test_fulltext_import import _pdf
from tests.test_import_admit import _corpus_doi

CODES = (
    "import-unresolved",
    "import-unconfirmed",
    "import-attachment-missing",
    "import-identity-unchecked",
    "import-undeclared",
    "import-coverage-optimistic",
)
UNRESOLVED = "@misc{z, year={2001}}\n"


def _import_findings(findings: list[Finding]) -> dict[str, Finding]:
    return {f.code: f for f in findings if f.code in CODES}


def _of(project: Project, **kwargs: object) -> dict[str, Finding]:
    return _import_findings(check(project, **kwargs).findings)  # type: ignore[arg-type]


def test_no_import_no_finding(project: Project, corpus: None) -> None:
    assert _of(project) == {}


def test_import_unresolved(project: Project, corpus: None, agent: Actor, tmp_path: Path) -> None:
    declare_library(project, agent)
    imp = import_bib(project, tmp_path, [UNRESOLVED, UNRESOLVED])
    resolve_import(project, imp, sources=Lookups().sources())
    finding = _of(project)["import-unresolved"]
    assert finding.severity == "warning" and finding.refs == [imp]
    assert "2 record(s)" in finding.message


def test_import_unconfirmed(project: Project, corpus: None, agent: Actor, tmp_path: Path) -> None:
    declare_library(project, agent)
    imp = import_bib(
        project,
        tmp_path,
        [bib_entry("a", "Efficient Reed Transformers v2", year=2021, author="Lee, Bo")],
    )
    lookups = Lookups(openalex=[oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501")])
    resolve_import(project, imp, sources=lookups.sources())
    finding = _of(project)["import-unconfirmed"]
    assert finding.refs == [imp] and "1 record(s)" in finding.message
    assert "import-unresolved" not in _of(project)


def test_import_attachment_missing(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    declare_library(project, agent)
    entry = (
        "@article{c, title={Missing File Study}, author={Zhou, Ada}, year={2020}, "
        "doi={10.1000/p9}, file={PDF:files/gone.pdf:application/pdf}}\n"
    )
    imp = import_bib(project, tmp_path, [entry])
    finding = _of(project)["import-attachment-missing"]
    assert finding.refs == [imp] and "1 record(s)" in finding.message


def _pdf_folder(project: Project, tmp_path: Path) -> str:
    folder = tmp_path / "pdfs"
    folder.mkdir()
    _pdf(folder / "10.1000_p2.pdf", "Paper 2 ZEBRAXQ")
    _pdf(folder / "10.1000_p3.pdf", "A different first page")
    imp = record_import(
        project, folder, format=ImportFormat.PDFS, role=ImportRole.REFERENCE, split=False
    ).import_id
    resolve_import(project, imp, sources=Lookups().sources())
    return imp


def test_import_identity_unchecked(project: Project, corpus: None, tmp_path: Path) -> None:
    imp = _pdf_folder(project, tmp_path)
    finding = _of(project)["import-identity-unchecked"]
    assert finding.refs == [imp] and "2 PDF record(s)" in finding.message
    attach_import(project, imp)  # record 1 shows its title and is attached; record 2 is not
    assert "1 PDF record(s)" in _of(project)["import-identity-unchecked"].message
    decide_import(
        project, project.human_actor(), imp, 2, Decision.CONFIRM, rationale="Same paper, checked."
    )
    assert "import-identity-unchecked" not in _of(project)


def test_import_undeclared(project: Project, corpus: None, agent: Actor, tmp_path: Path) -> None:
    imp = import_bib(project, tmp_path, [bib_entry("a", "Some Title", year=2020, author="A, B")])
    finding = _of(project)["import-undeclared"]
    assert finding.severity == "error" and finding.refs == [imp]  # pilot: an error
    assert not check(project).ok
    ref_only = import_bib(
        project,
        tmp_path,
        [bib_entry("b", "Other Title", year=2020, author="A, B")],
        role=ImportRole.REFERENCE,
        name="ref.bib",
    )
    assert _of(project)["import-undeclared"].refs == [imp] and ref_only not in str(
        _of(project)["import-undeclared"]
    )
    declare_library(project, agent)
    assert "import-undeclared" not in _of(project)


def test_import_undeclared_is_a_promotion_gap_in_exploratory(
    explore_project: Project, tmp_path: Path
) -> None:
    project = explore_project
    import_bib(project, tmp_path, [bib_entry("a", "Some Title", year=2020, author="A, B")])
    assert _of(project)["import-undeclared"].severity == "warning"
    promoted = _of(project, promote_to=RigorMode.PILOT)
    assert promoted["import-undeclared"].severity == "error"


@pytest.fixture
def pre_search(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> Project:
    ready_protocol(project, agent, human, mock_sources)
    return project


def test_import_coverage_optimistic(pre_search: Project, tmp_path: Path) -> None:
    imp = import_bib(pre_search, tmp_path, [bib_entry("a", "T", year=2020, author="A, B")])
    finding = _of(pre_search)["import-coverage-optimistic"]
    assert finding.severity == "warning" and finding.refs == [imp]
    drawn = import_bib(
        pre_search, tmp_path, [bib_entry("a", "T", year=2020, author="A, B")], split=True, name="s"
    )
    assert _of(pre_search)["import-coverage-optimistic"].refs == [imp]
    assert drawn not in _of(pre_search)["import-coverage-optimistic"].refs


def test_findings_carry_no_text(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    title = "Distinctive Xylophone Title"
    imp = import_bib(
        project,
        tmp_path,
        [UNRESOLVED, bib_entry("a", title, year=2020, author="Zed, Q"), UNRESOLVED],
    )
    resolve_import(project, imp, sources=Lookups().sources())
    for finding in _import_findings(check(project).findings).values():
        assert title not in json.dumps(finding.model_dump())
        assert all(re.fullmatch(r"imp_[0-9A-Z]{26}", ref) for ref in finding.refs)
        assert not re.search(r"ordinal|\bimp_\w+:\d+", finding.message)


def test_agent_check_counts_the_development_part_only(pre_search: Project, tmp_path: Path) -> None:
    entries = [UNRESOLVED.replace("z,", f"z{k},") for k in range(1, 13)]
    path = tmp_path / "split.bib"
    path.write_text("".join(entries))
    imp = record_import(
        pre_search, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=7
    ).import_id
    resolve_import(pre_search, imp, sources=Lookups().sources())
    held = len(list_import_records(pre_search, imp, view="held-out"))
    assert 0 < held < 12
    full = _of(pre_search)["import-unresolved"]
    agent_view = _import_findings(agent_check(pre_search).findings)["import-unresolved"]
    assert f"{12} record(s)" in full.message
    assert f"{12 - held} record(s)" in agent_view.message


# --- trace ---


@pytest.fixture
def admitted(project: Project, corpus: None, agent: Actor, tmp_path: Path) -> tuple[str, Lookups]:
    declare_library(project, agent)
    imp = import_bib(project, tmp_path, admission_records(_corpus_doi(project)))
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    admit_import(project, imp, sources=lookups.sources())
    return imp, lookups


def _walk(node: TraceNode) -> list[TraceNode]:
    return [node, *(n for child in node.children for n in _walk(child))]


def _kinds(node: TraceNode) -> dict[str, list[TraceNode]]:
    out: dict[str, list[TraceNode]] = {}
    for n in _walk(node):
        out.setdefault(n.kind, []).append(n)
    return out


def test_trace_record_to_work_and_back(project: Project, admitted: tuple[str, Lookups]) -> None:
    imp, _ = admitted
    forward = _kinds(trace(project, f"{imp}:1", direction="forward"))
    [record] = forward["import_record"]
    assert record.id == f"{imp}:1" and "lookup-identifier" in record.label
    [work] = forward["work"]  # the record's resolved work
    back_from_record = _kinds(trace(project, f"{imp}:1", direction="back"))
    [import_node] = back_from_record["import"]
    assert import_node.id == imp
    assert "sha256:" in import_node.label or re.search(r"[0-9a-f]{64}", import_node.label)
    assert "bibtexparser" in import_node.label.lower() or "parser" in import_node.label
    back_from_work = _kinds(trace(project, work.id, direction="back"))
    assert [n.id for n in back_from_work["import_record"]] == [f"{imp}:1"]
    assert [n.id for n in back_from_work["import"]] == [imp]
    assert back_from_work["query"]  # the admission query
    forward_import = _kinds(trace(project, imp, direction="forward"))
    assert forward_import["query"] and forward_import["run"]
    assert any(n.label.startswith("status") for n in forward_import["run"])


def test_trace_unknown_record_is_refused(project: Project, admitted: tuple[str, Lookups]) -> None:
    imp, _ = admitted
    with pytest.raises(FactoryValidationError):
        trace(project, f"{imp}:999")


def test_agent_trace_shows_no_import_node(project: Project, admitted: tuple[str, Lookups]) -> None:
    imp, _ = admitted
    work = _kinds(trace(project, f"{imp}:1", direction="forward"))["work"][0]
    tree = agent_trace(project, work.id)
    kinds = _kinds(tree)
    assert "import" not in kinds and "import_record" not in kinds
    assert imp not in json.dumps(tree.model_dump())
    for ref in (imp, f"{imp}:1"):
        with pytest.raises(FactoryValidationError):
            agent_trace(project, ref)

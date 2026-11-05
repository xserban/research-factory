"""Plan Import-C acceptance (slice 3d, criteria 11-17, the import part), on synthetic fixtures:
invented records, scripted lookup sources, no network and no literature text.

One test per criterion, in the order of the spec; `test_import_scale` last.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.imports.csl import parse_csl
from factory.imports.model import ImportFormat, ParseOutcome
from factory.imports.registry import parse
from factory.model.imports import ImportRole
from factory.model.references import LinkState
from factory.model.screening import PassLabel
from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.model.work import Author, Dates, Identifiers, Provenance, ProvenanceMethod, Work
from factory.services import coverage
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.coverage import Bucket, coverage_report, record_coverage
from factory.services.dedup import dedup_run
from factory.services.import_admit import admit_import
from factory.services.import_attach import attach_import
from factory.services.import_resolve import (
    ImportResolvable,
    record_states,
    resolvables,
    resolve_import,
)
from factory.services.imports import (
    import_row,
    list_import_records,
    record_import,
)
from factory.services.prisma import prisma_flow, search_report
from factory.services.reference_resolve import load_corpus, resolve_entries
from factory.services.screening import open_pass
from factory.services.search import corpus_size, list_works, register_query, run_query
from factory.services.trace import trace
from factory.sources.base import PageSink, RawPage, SearchResult
from factory.sources.registry import SourceFactory
from tests.coverage_helpers import found_database, miss_item, query_miss, set_limits
from tests.document_helpers import events_of_type
from tests.helpers import T0, SourcesFor, _seed_item, open_session, ready_protocol
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

pytestmark = pytest.mark.slow

FIXTURES = Path(__file__).parent / "fixtures" / "imports"
PRIVATE = ["my private note", "annote", "files/1", "files/2", "quill2019.pdf", "fennel.pdf"]
UNRESOLVED = "@misc{z, year={2001}}\n"


def _events(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _store_text(project: Project) -> str:
    """Everything the project wrote under events/ and blobs/, as text."""
    parts = []
    for root in (project.paths.events_dir, project.paths.blobs_dir):
        for path in sorted(root.rglob("*")):
            if path.is_file():
                parts.append(path.read_bytes().decode("utf-8", "replace"))
    return "\n".join(parts)


# --- 11 Parsing ---


def test_c11_parsing_archive_and_privacy(project: Project, tmp_path: Path) -> None:
    bib = FIXTURES / "zotero.bib"
    assert "Synthetic fixture" in bib.read_text()  # no literature text in git
    summary = record_import(
        project, bib, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, split=False
    )
    assert {o.value: n for o, n in summary.counts.items()} == {
        "parsed": 2,
        "no-title-no-identifier": 1,
        "malformed": 1,
    }
    row = import_row(project, summary.import_id)
    assert project.library.get(row.file_hash) == bib.read_bytes()  # R-03: verbatim archive
    parsed = parse(ImportFormat.BIBTEX, bib)
    first = parsed.records[0].fields
    assert first is not None
    assert first.title == "On the Quiet Growth of Pear Trees"  # LaTeX braces, @string venue
    assert first.venue == "Journal of Imaginary Orchards Letters"
    assert first.tags == ["pears", "orchards"]

    csl = tmp_path / "lib.json"
    csl.write_text(
        json.dumps(
            [
                {
                    "title": "Made-Up Study Of Dunes",
                    "author": [{"family": "Roe", "given": "Sam"}],
                    "issued": {"date-parts": [[2017]]},
                    "DOI": "10.9999/dunes.1",
                    "note": "my private note",
                }
            ]
        )
    )
    csl_parsed = parse_csl(csl.read_bytes(), tmp_path)
    [record] = csl_parsed.records
    assert record.fields is not None and record.fields.year == 2017
    record_import(project, csl, format=ImportFormat.CSL, role=ImportRole.REFERENCE, split=False)

    folder = tmp_path / "pdfs"
    folder.mkdir()
    _pdf(folder / "2101.00042.pdf", "A made-up first page")
    pdfs = record_import(
        project, folder, format=ImportFormat.PDFS, role=ImportRole.REFERENCE, split=False
    )
    assert pdfs.counts[ParseOutcome.PARSED] == 1

    stored = _store_text(project)
    assert not [needle for needle in PRIVATE if needle in stored]
    assert str(tmp_path) not in stored  # no local path reaches the log


# --- 12 Resolution ---


def test_c12_resolution_parity_fuzzy_and_unresolved(
    project: Project, corpus: None, tmp_path: Path
) -> None:
    lookups = Lookups(
        openalex=[
            oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501"),
            oa_item("Sedge Mapping Methods", "Ana Kim", 2015, "W504", doi="10.9999/sedge.1"),
        ]
    )
    imp = import_bib(
        project,
        tmp_path,
        [
            bib_entry("a", "Efficient Reed Transformers v2", year=2021, author="Lee, Bo"),
            bib_entry(
                "c", "Sedge Mapping Methods", year=2015, author="Kim, A", doi="10.9999/sedge.1"
            ),
            bib_entry("u", "Wholly unknown matters here", year=2001, author="Nobody, Cora"),
            UNRESOLVED,
        ],
    )
    entries = resolvables(project, imp)

    @dataclass(frozen=True)
    class AsReference:  # the same fields, given as a reference entry would give them
        ordinal: int
        doi: str | None
        arxiv: str | None
        url: str | None
        year: int | None
        first_author: str | None
        title: str | None
        venue: str | None

    as_references = [AsReference(**vars(e)) for e in entries if isinstance(e, ImportResolvable)]
    sources = lookups.sources()
    by_reference = resolve_entries(
        project, project.human_actor(), as_references, corpus=load_corpus(project), sources=sources
    )
    resolve_import(project, imp, sources=sources)
    states = record_states(project, imp)
    assert {r.ordinal: r.state for r in by_reference.resolutions} == states
    assert states == {
        1: LinkState.UNCONFIRMED,  # a fuzzy match waits for confirmation
        2: LinkState.RESOLVED,
        3: LinkState.UNRESOLVED,
        4: LinkState.UNRESOLVED,  # no title and no identifier: listed, not dropped
    }
    assert len(list_import_records(project, imp)) == 4


# --- 13 Split and visibility ---


@pytest.mark.anyio
async def test_c13_split_and_mcp_visibility(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    tmp_path: Path,
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    entries = [
        bib_entry(
            f"z{k}", f"Zebra Moss Study {k}", year=2018, author="Kim, Ana", doi=f"10.7777/z.{k}"
        )
        for k in range(1, 13)
    ]
    path = tmp_path / "split.bib"
    path.write_text("".join(entries))
    summary = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=11
    )
    assert summary.split == "drawn"
    [drawn] = events_of_type(project, "import.split_drawn")
    assert drawn.payload["mode"] == "drawn" and drawn.payload["random_seed"] == 11
    lookups = Lookups(
        openalex=[
            oa_item(f"Zebra Moss Study {k}", "Ana Kim", 2018, f"W7{k:02d}", doi=f"10.7777/z.{k}")
            for k in range(1, 13)
        ]
    )
    resolve_import(project, summary.import_id, sources=lookups.sources())
    held_titles = [
        r.title for r in list_import_records(project, summary.import_id, view="held-out")
    ]
    assert held_titles
    async with open_session(settings, clock, {}) as session:
        before = await session.call("import_coverage", project="demo", import_id=summary.import_id)
        assert [p["part"] for p in before["data"]["parts"]] == ["development"]
        open_pass(project, agent, PassLabel.A)
        after = await session.call("import_coverage", project="demo", import_id=summary.import_id)
        assert [p["part"] for p in after["data"]["parts"]] == ["development", "held-out"]
        text = json.dumps([before, after])
        assert not [t for t in held_titles if t and t in text]

    # after the first search run an import has no split and is labelled
    sources = mock_sources(openalex=[_seed_item(1)])
    query = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="attention")
    run_query(project, register_query(project, human, query, sources=sources), sources=sources)
    later = import_bib(project, tmp_path, [UNRESOLVED], name="later.bib")
    assert coverage_report(project, later).label == "post-search"


# --- 14 Admission and PRISMA ---


def test_c14_admission_gate_and_prisma(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    without = prisma_flow(project).model_dump_json()
    imp = import_bib(project, tmp_path, admission_records(_corpus_doi(project)))
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    before = _events(project)
    with pytest.raises(FactoryValidationError) as refused:
        admit_import(project, imp, sources=lookups.sources())
    assert any(i.field == "library_sources" for i in refused.value.issues)
    assert _events(project) == before  # nothing written
    assert prisma_flow(project).model_dump_json() == without  # an unadmitted import changes nothing

    declare_library(project, agent)
    admit_import(project, imp, sources=lookups.sources())
    imported = [
        w
        for w in list_works(project)
        if any(p.method is ProvenanceMethod.LIBRARY_IMPORT for p in w.provenance)
    ]
    assert len(imported) == 2
    outcomes = final_outcomes(project)
    assert all(outcomes[w.id] is Outcome.PENDING for w in imported)
    dedup_run(project)
    flow = prisma_flow(project)
    assert flow.identified_other["library-import"] == 2
    assert search_report(project).rows  # the import's queries are reported
    assert corpus_size(project)[0] >= 2


# --- 15 Attachments ---


def test_c15_attachments_after_promotion(
    project: Project, corpus_leaving: str, agent: Actor, tmp_path: Path
) -> None:
    files = tmp_path / "files"
    files.mkdir()
    _pdf(files / "a.pdf", "A made-up first page")
    entry = (
        "@article{a, title={Paper 2}, author={Zhou, Ada}, year={2020}, doi={10.1000/p2}, "
        "file={PDF:files/a.pdf:application/pdf}}\n"
        "@article{m, title={Gone Paper}, author={Zhou, Ada}, year={2020}, doi={10.1000/p9}, "
        "file={PDF:files/gone.pdf:application/pdf}}\n"
    )
    imp = import_bib(project, tmp_path, [entry])
    resolve_import(project, imp, sources=Lookups().sources())
    report = attach_import(project, imp)
    assert report.attachment_missing == [2]  # listed, not dropped
    documents = events_of_type(project, "fulltext.document_added")
    # recorded only for the promoted work that resolved
    assert len(documents) == len(report.attached) <= 1
    for _, work, _ in report.attached:
        assert final_outcomes(project)[work] is Outcome.INCLUDED


# --- 16 Coverage ---


def test_c16_buckets_figures_suggestions(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    from factory.model.protocol import Limit

    set_limits(project, agent, Limit(field="year", value="2010-2025"))
    lookups = Lookups(
        openalex=[
            miss_item(1),
            miss_item(2),
            miss_item(3, year=1990),
            oa_item("Missed Study 4 Of Reeds", "Ana Kim", 2018, "W94", doi="10.7777/miss.4"),
        ]
    )
    entries = [
        found_database(1),
        found_database(2),
        query_miss(1),
        query_miss(2),
        query_miss(3, year=1990),
        query_miss(4),
        UNRESOLVED,
    ]
    imp = import_bib(project, tmp_path, entries)
    resolve_import(project, imp, sources=lookups.sources())
    rows = record_coverage(project, imp)
    assert len({r.ordinal for r in rows}) == len(rows) == 6  # one bucket each
    report = coverage_report(project, imp)
    [part] = report.parts
    assert sum(part.counts.values()) == part.resolved == 6
    assert part.counts[Bucket.FOUND_DATABASE] == 2 and part.counts[Bucket.OUTSIDE_LIMITS] == 1
    assert part.counts[Bucket.QUERY_MISS] == 3
    assert part.unresolved == 1
    assert part.sensitivity is not None
    assert (part.sensitivity.numerator, part.sensitivity.denominator) == (2, 5)
    assert part.coverage is not None
    assert (part.coverage.numerator, part.coverage.denominator) == (2, 6)
    assert report.suggestions  # the missed titles share "reeds"
    assert not any("verdict" in name for name in type(part).model_fields)


# --- 17 Rebuild and trace ---


def test_c17_rebuild_and_trace(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    declare_library(project, agent)
    imp = import_bib(project, tmp_path, admission_records(_corpus_doi(project)))
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    admit_import(project, imp, sources=lookups.sources())
    before = coverage_report(project, imp).model_dump_json()
    state_hash = project.index.state_hash()
    assert project.index.rebuild() == state_hash
    assert coverage_report(project, imp).model_dump_json() == before

    forward = trace(project, f"{imp}:1", direction="forward")
    [work] = [n for n in _walk(forward) if n.kind == "work"][:1]
    back = trace(project, work.id)
    kinds = {n.kind for n in _walk(back)}
    assert {"import_record", "import", "query"} <= kinds
    [import_node] = [n for n in _walk(back) if n.kind == "import"]
    assert import_row(project, imp).file_hash in import_node.label  # record, import, file hash


def _walk(node: Any) -> Iterator[Any]:
    yield node
    for child in node.children:
        yield from _walk(child)


# --- Scale ---

SCALE = 50_000
SCALE_KNOWN = 40_000
SCALE_SECONDS = 600
"""Bound for parse, record, resolve and bucket of 50,000 records offline: measured at about 180 s
(75 s parse and record, 100 s resolve, 5 s coverage) on the development machine."""
CHUNK = 2_000


class _ScaleSource:
    """A scripted OpenAlex that knows the first `SCALE_KNOWN` DOIs, without scanning a list."""

    name = "openalex"
    kinds = frozenset({QueryKind.FILTER})

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
        resume_from: str | None = None,
    ) -> SearchResult:
        dois = spec.text.removeprefix("doi:").split("|")
        works: list[Work] = []
        body = json.dumps(dois)
        ref = archive(RawPage(ordinal=0, body=body, url="fake://scale", fetched_at=T0))
        for doi in dois:
            n = int(doi.rsplit(".", 1)[1])
            if n > SCALE_KNOWN:
                continue
            works.append(
                Work.build(
                    title=f"Scale Study {n} Of Reeds",
                    authors=[Author(name="Ana Kim")],
                    identifiers=Identifiers(doi=doi),
                    dates=Dates(published=date(2018, 1, 1)),
                    provenance=[
                        Provenance(
                            source="openalex",
                            run_id=run_id,
                            query_id=query_id,
                            at=T0,
                            raw_blob=ref,
                        )
                    ],
                )
            )
        return SearchResult(
            source="openalex",
            query_sent=spec.text,
            reported_count=len(works),
            works=works,
            pages=1,
            status=RunStatus.COMPLETE,
            skipped=0,
            note=None,
        )


def test_import_scale(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    started = time.monotonic()

    lines = [
        f"@article{{s{n}, title={{Scale Study {n} Of Reeds}}, author={{Kim, Ana}}, "
        f"year={{2018}}, doi={{10.8888/scale.{n}}}}}\n"
        for n in range(1, SCALE + 1)
    ]
    path = tmp_path / "scale.bib"
    path.write_text("".join(lines))
    summary = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=3
    )
    assert summary.counts[ParseOutcome.PARSED] == SCALE
    factory = SourceFactory(frozenset({QueryKind.FILTER}), lambda _s, _c: _ScaleSource())
    resolve_import(project, summary.import_id, sources={"openalex": factory})
    assert sum(1 for s in record_states(project, summary.import_id).values()) == SCALE

    chunks: list[int] = []
    real = coverage._chunks

    def spy(project_: Project, import_id: str) -> Iterator[list[Any]]:
        for chunk in real(project_, import_id):
            chunks.append(len(chunk))
            yield chunk

    monkeypatch.setattr(coverage, "_chunks", spy)
    report = coverage_report(project, summary.import_id)
    elapsed = time.monotonic() - started
    assert max(chunks) <= coverage.CHUNK and len(chunks) >= SCALE // coverage.CHUNK
    assert report.label == "held-out"
    assert sum(p.resolved for p in report.parts) == SCALE
    misses = sum(p.counts[Bucket.QUERY_MISS] for p in report.parts)
    assert misses == SCALE_KNOWN  # known to OpenAlex, found by no search
    assert elapsed < SCALE_SECONDS, f"{elapsed:.0f}s"

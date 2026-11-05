"""Coverage buckets of an import's resolved records (Import-C task 1).

Every record, work and identifier is invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.events.envelope import Actor
from factory.imports.limits import outside_limits
from factory.imports.model import ImportFields
from factory.model.protocol import Limit
from factory.model.search import QueryPurpose
from factory.services.context import Project
from factory.services.coverage import Bucket, RecordCoverage, record_coverage
from factory.services.dedup import active_merges, dedup_run
from factory.services.import_admit import admit_import
from tests.coverage_helpers import (
    build,
    found_database,
    miss_item,
    not_in_sources,
    query_miss,
    run_other_purpose,
    set_limits,
    unchecked,
)
from tests.import_helpers import bib_entry, declare_library
from tests.references_service_helpers import Lookups, oa_item

UNRESOLVED = "@misc{z, year={2001}}\n"


def _by_ordinal(rows: list[RecordCoverage]) -> dict[int, RecordCoverage]:
    return {r.ordinal: r for r in rows}


def test_buckets_partition_resolved(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    lookups = Lookups(openalex=[miss_item(1), miss_item(2, year=1990)])
    set_limits(project, agent, Limit(field="year", value="2010-2025"))
    entries = [
        found_database(1),
        query_miss(1),
        query_miss(2, year=1990),
        not_in_sources(1),
        unchecked(1),
        UNRESOLVED,
    ]
    cov = build(project, tmp_path, entries, lookups)
    rows = record_coverage(project, cov.import_id)
    assert [r.ordinal for r in rows] == [1, 2, 3, 4, 5]  # the unresolved record is omitted
    assert [r.bucket for r in rows] == [
        Bucket.FOUND_DATABASE,
        Bucket.QUERY_MISS,
        Bucket.OUTSIDE_LIMITS,
        Bucket.NOT_IN_SOURCES,
        Bucket.SOURCE_UNCHECKED,
    ]
    assert len({r.ordinal for r in rows}) == len(rows)  # one bucket each
    assert rows[2].limits_violated == ["year"]


def test_found_database_requires_search_purpose(
    project: Project, corpus: None, tmp_path: Path
) -> None:
    """The record's work carries probe provenance (the resolver's lookup) and is not found."""
    lookups = Lookups(openalex=[miss_item(1)])
    cov = build(project, tmp_path, [found_database(1), query_miss(1)], lookups)
    first, second = record_coverage(project, cov.import_id)
    assert first.bucket is Bucket.FOUND_DATABASE
    assert first.sources_found  # found by the search of a declared source
    assert second.bucket is Bucket.QUERY_MISS  # database-method provenance, but probe purpose
    assert second.sources_found == ["openalex"]


def test_found_supplementary_via_chase(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    lookups = Lookups(citing=[miss_item(1)], openalex=[miss_item(1)])
    run_other_purpose(project, agent, lookups, QueryPurpose.CHASE, "cites:W1")
    cov = build(project, tmp_path, [query_miss(1)], lookups)
    [row] = record_coverage(project, cov.import_id)
    assert row.bucket is Bucket.FOUND_SUPPLEMENTARY


def test_supplied_only_is_not_found(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    lookups = Lookups(openalex=[miss_item(1)])
    run_other_purpose(project, agent, lookups, QueryPurpose.SUPPLIED, "doi:10.7777/miss.1")
    cov = build(project, tmp_path, [query_miss(1)], lookups)
    [row] = record_coverage(project, cov.import_id)
    assert row.bucket is Bucket.QUERY_MISS


def test_import_provenance_not_found(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    """Admitting the import puts its works in the corpus through `library-import`; they stay
    unfound by the search."""
    declare_library(project, agent)
    lookups = Lookups(openalex=[miss_item(1)])
    cov = build(project, tmp_path, [found_database(1), query_miss(1)], lookups)
    before = [r.bucket for r in record_coverage(project, cov.import_id)]
    admit_import(project, cov.import_id, sources=lookups.sources())
    after = [r.bucket for r in record_coverage(project, cov.import_id)]
    assert before == after == [Bucket.FOUND_DATABASE, Bucket.QUERY_MISS]


def test_outside_limits_year(project: Project, corpus: None, agent: Actor, tmp_path: Path) -> None:
    set_limits(project, agent, Limit(field="year", value="2015-2025"))
    lookups = Lookups(openalex=[miss_item(1, year=2010)])
    cov = build(project, tmp_path, [query_miss(1, year=2010)], lookups)
    [row] = record_coverage(project, cov.import_id)
    assert (row.bucket, row.limits_violated) == (Bucket.OUTSIDE_LIMITS, ["year"])


def test_unknown_field_within_limits(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    set_limits(project, agent, Limit(field="year", value="2015-2025"))
    entry = "@article{y, title={Yearless Study Of Sedge}, author={Roe, Sam}, doi={10.7777/y.1}}\n"
    lookups = Lookups(
        openalex=[oa_item("Yearless Study Of Sedge", "Sam Roe", 2020, "W71", doi="10.7777/y.1")]
    )
    cov = build(project, tmp_path, [entry], lookups)
    [row] = record_coverage(project, cov.import_id)
    assert row.bucket is Bucket.QUERY_MISS and row.limits_violated == []


def test_not_in_sources_needs_lookup(project: Project, corpus: None, tmp_path: Path) -> None:
    cov = build(project, tmp_path, [not_in_sources(1)], Lookups())
    [row] = record_coverage(project, cov.import_id)
    assert row.bucket is Bucket.NOT_IN_SOURCES
    assert cov.lookups.asked  # the declared source was asked


def test_source_unchecked(project: Project, corpus: None, tmp_path: Path) -> None:
    """An arXiv-only record under an OpenAlex-only protocol: OpenAlex was never asked."""
    cov = build(project, tmp_path, [unchecked(1)], Lookups())
    [row] = record_coverage(project, cov.import_id)
    assert row.bucket is Bucket.SOURCE_UNCHECKED
    assert all(not a.startswith("openalex") for a in cov.lookups.asked)


def test_query_miss(project: Project, corpus: None, tmp_path: Path) -> None:
    cov = build(project, tmp_path, [query_miss(1)], Lookups(openalex=[miss_item(1)]))
    [row] = record_coverage(project, cov.import_id)
    assert row.bucket is Bucket.QUERY_MISS
    assert row.outcome is None and row.excluded_by == []


def test_duplicate_records_count_once(project: Project, corpus: None, tmp_path: Path) -> None:
    lookups = Lookups(openalex=[miss_item(1)])
    cov = build(project, tmp_path, [query_miss(1), found_database(2), query_miss(1)], lookups)
    rows = record_coverage(project, cov.import_id)
    assert [r.ordinal for r in rows] == [1, 2]  # the lowest ordinal of the repeated work


def test_absorbed_id_resolves(project: Project, corpus: None, agent: Actor, tmp_path: Path) -> None:
    """A record resolved to a work that dedup then absorbed reports the merge group's primary."""
    variant = oa_item("Paper 1", "Ada Zhou", 2020, "W8001", doi="10.1000/p1.preprint")
    lookups = Lookups(openalex=[variant])
    run_other_purpose(project, agent, lookups, QueryPurpose.SEARCH, "doi:10.1000/p1.preprint")
    entry = bib_entry("v", "Paper 1", year=2020, author="Zhou, Ada", doi="10.1000/p1.preprint")
    cov = build(project, tmp_path, [entry], lookups)
    [before] = record_coverage(project, cov.import_id)
    assert dedup_run(project).created
    [after] = record_coverage(project, cov.import_id)
    absorbed = {a for m in active_merges(project) for a in m.absorbed}
    primaries = {m.primary for m in active_merges(project)}
    assert before.work_id in absorbed | primaries
    assert after.work_id in primaries and after.work_id not in absorbed
    assert after.bucket is Bucket.FOUND_DATABASE


@pytest.mark.parametrize(
    ("limit", "year", "kind", "outside"),
    [
        (Limit(field="year", value="2015-2025"), 2014, "article", True),
        (Limit(field="year", value="2015-2025"), 2025, "article", False),
        (Limit(field="year", value="2015-"), 2030, "article", False),
        (Limit(field="year", value="-2015"), 2016, "article", True),
        (Limit(field="Year", value="2015"), 2016, "article", True),
        (Limit(field="year", value="soon"), 1900, "article", False),
        (Limit(field="type", value="journal-article, preprint"), 2020, "inproceedings", True),
        (Limit(field="type", value="journal-article, preprint"), 2020, "preprint", False),
        (Limit(field="type", value="preprint"), 2020, "other", False),
        (Limit(field="language", value="en"), 2020, "article", False),
        (Limit(field="topic", value="x"), 2020, "article", False),
    ],
)
def test_limits_function(limit: Limit, year: int, kind: str, outside: bool) -> None:
    fields = ImportFields(year=year, type=kind)  # type: ignore[arg-type]
    assert bool(outside_limits(fields, [limit])) is outside

"""Coverage report: figures, parts, suggestions and the methods sentence (Import-C task 2).

Every record, work and identifier is invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.events.envelope import Actor
from factory.imports.model import ImportFormat
from factory.model.imports import ImportRole
from factory.model.search import QueryPurpose
from factory.services.agreement import Outcome
from factory.services.context import Project
from factory.services.coverage import (
    Bucket,
    CoverageReport,
    Ratio,
    coverage_report,
    record_coverage,
)
from factory.services.import_resolve import resolve_import
from factory.services.imports import list_import_records, record_import
from factory.services.methods import methods_report, render_methods
from factory.services.protocol import current_protocol
from factory.services.search import get_work
from tests.coverage_helpers import (
    build,
    found_database,
    miss_item,
    query_miss,
    run_other_purpose,
)
from tests.helpers import SourcesFor, ready_protocol
from tests.import_helpers import bib_entry
from tests.references_service_helpers import Lookups, oa_item
from tests.screening_helpers import _decide


def _counts(report: CoverageReport) -> dict[str, int]:
    return {b.value: n for b, n in report.parts[0].counts.items()}


def test_figures_hand_computed(
    project: Project, corpus: None, agent: Actor, tmp_path: Path
) -> None:
    """3 found-database, 1 found-supplementary, 2 query-miss: sensitivity 3/6, coverage 4/6."""
    lookups = Lookups(citing=[miss_item(1)], openalex=[miss_item(1), miss_item(2), miss_item(3)])
    run_other_purpose(project, agent, lookups, QueryPurpose.CHASE, "cites:W1")
    entries = [found_database(n) for n in (1, 2, 3)] + [query_miss(n) for n in (1, 2, 3)]
    cov = build(project, tmp_path, entries, lookups)
    report = coverage_report(project, cov.import_id)
    [part] = report.parts
    assert part.part == "unsplit" and report.label == "post-search"
    assert _counts(report) == {
        "found-database": 3,
        "found-supplementary": 1,
        "outside-limits": 0,
        "not-in-sources": 0,
        "source-unchecked": 0,
        "query-miss": 2,
    }
    assert part.resolved == 6
    assert part.sensitivity == Ratio(numerator=3, denominator=6, value=0.5)
    assert part.coverage == Ratio(numerator=4, denominator=6, value=4 / 6)
    assert part.outcomes == {"included": 3, "excluded": 0, "pending": 1}


def test_zero_denominator_none(project: Project, corpus: None, tmp_path: Path) -> None:
    cov = build(project, tmp_path, ["@misc{z, year={2001}}\n"], Lookups())
    [part] = coverage_report(project, cov.import_id).parts
    assert part.resolved == 0 and part.unresolved == 1
    assert part.sensitivity is None and part.coverage is None


@pytest.fixture
def pre_search(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> Project:
    """A ready protocol and no search yet, so an import draws a split."""
    ready_protocol(project, agent, human, mock_sources)
    return project


def _split_import(project: Project, tmp_path: Path, n: int = 12) -> tuple[str, Lookups]:
    entries = [
        bib_entry(
            f"z{k}",
            f"Zebra Moss Mapping Study {k}",
            year=2018,
            author="Kim, Ana",
            doi=f"10.7777/z.{k}",
        )
        for k in range(1, n + 1)
    ]
    path = tmp_path / "split.bib"
    path.write_text("".join(entries))
    summary = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=7
    )
    lookups = Lookups(
        openalex=[
            oa_item(
                f"Zebra Moss Mapping Study {k}", "Ana Kim", 2018, f"W7{k:02d}", doi=f"10.7777/z.{k}"
            )
            for k in range(1, n + 1)
        ]
    )
    resolve_import(project, summary.import_id, sources=lookups.sources())
    return summary.import_id, lookups


def test_parts_reported_separately(pre_search: Project, tmp_path: Path) -> None:
    import_id, _ = _split_import(pre_search, tmp_path)
    report = coverage_report(pre_search, import_id)
    assert report.label == "held-out"
    assert [p.part for p in report.parts] == ["development", "held-out"]
    held = len(list_import_records(pre_search, import_id, view="held-out"))
    assert report.parts[1].resolved == held > 0
    assert sum(p.resolved for p in report.parts) == 12
    assert all(p.counts[Bucket.QUERY_MISS] == p.resolved for p in report.parts)


def test_suggestions_from_development_only(pre_search: Project, tmp_path: Path) -> None:
    import_id, _ = _split_import(pre_search, tmp_path)
    report = coverage_report(pre_search, import_id)
    assert any("zebra" in s.term for s in report.suggestions)
    assert list_import_records(pre_search, import_id, view="held-out")  # held-out records exist
    dev_works = {
        r.work_id for r in record_coverage(pre_search, import_id) if r.part == "development"
    }
    for suggestion in report.suggestions:
        assert set(suggestion.holders) <= dev_works


def test_excluded_list_has_no_verdict_field(
    project: Project, corpus_leaving: str, agent: Actor, tmp_path: Path
) -> None:
    left = corpus_leaving
    protocol = current_protocol(project)
    assert protocol is not None
    for label in ("A", "B"):
        _decide(project, agent, left, label, "screening", "exclude", "EX01", protocol.protocol_id)
    work = get_work(project, left)
    assert work is not None and work.identifiers.doi is not None
    entry = bib_entry("x", work.title, year=2020, author="Zhou, Ada", doi=work.identifiers.doi)
    cov = build(project, tmp_path, [entry], Lookups())
    report = coverage_report(project, cov.import_id)
    [part] = report.parts
    assert part.excluded == [left]
    assert part.outcomes["excluded"] == 1
    assert not any("verdict" in name for name in type(part).model_fields)
    assert all(isinstance(w, str) for w in part.excluded)


def test_included_not_in_library_count(project: Project, corpus: None, tmp_path: Path) -> None:
    included = 9  # the corpus fixture includes every one of its nine works
    cov = build(project, tmp_path, [found_database(1), found_database(2)], Lookups())
    assert coverage_report(project, cov.import_id).included_not_in_library == included - 2


def test_methods_sentence(project: Project, corpus: None, tmp_path: Path) -> None:
    before = render_methods(methods_report(project))
    assert "Library import" not in before
    lookups = Lookups(openalex=[miss_item(1)])
    cov = build(project, tmp_path, [found_database(1), found_database(2), query_miss(1)], lookups)
    text = render_methods(methods_report(project))
    [sentence] = [p for p in text.split("\n\n") if p.startswith("Library import")]
    assert cov.import_id in sentence
    assert "post-search" in sentence
    assert "sensitivity 2/3" in sentence and "coverage 2/3" in sentence
    assert Outcome.INCLUDED.value  # outcomes are counted, not typed


def test_suggestions_leave_out_a_held_out_seed_work(
    pre_search: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A held-out seed's terms must not steer the queries, which would bias R-24 upward. The
    filter is here alone: the seed's work still counts in the part's figures (decision 81)."""
    from factory.services import seeds as seeds_module

    import_id, _ = _split_import(pre_search, tmp_path)
    before = coverage_report(pre_search, import_id)
    target = sorted(h for s in before.suggestions for h in s.holders)[0]
    work = get_work(pre_search, target)
    assert work is not None and work.identifiers.doi is not None
    real = seeds_module._load_seeds
    held = {
        s.seed_id
        for s in seeds_module.all_seeds(pre_search)
        if s.role is seeds_module.SeedRole.HELD_OUT
    }
    spec = {"doi": work.identifiers.doi}
    monkeypatch.setattr(
        seeds_module,
        "_load_seeds",
        lambda p: [
            s.model_copy(update={"work_id": None, "spec": s.spec.model_copy(update=spec)})
            if s.seed_id in held
            else s
            for s in real(p)
        ],
    )
    monkeypatch.setattr(seeds_module, "_admitted", lambda project: {})
    after = coverage_report(pre_search, import_id)
    assert after.suggestions  # the other misses still suggest
    assert all(target not in s.holders for s in after.suggestions)
    assert after.parts == before.parts


def test_agent_view_counts_a_held_out_seed_work_as_any_work(
    project: Project, corpus: None, tmp_path: Path
) -> None:
    """Decision 81: a count that drops a corpus work is an oracle, since an agent can compare it
    with the works it sees elsewhere. Only the held-out PART of an import is withheld."""
    from factory.services.coverage import agent_coverage
    from factory.services.seeds import SeedRole, all_seeds

    held = {s.work_id for s in all_seeds(project) if s.role is SeedRole.HELD_OUT and s.work_id}
    assert held
    entries = [found_database(n) for n in range(1, 7)]
    cov = build(project, tmp_path, entries, Lookups())
    full = coverage_report(project, cov.import_id)
    agent_view = agent_coverage(project, cov.import_id)
    listed = {r.work_id for r in record_coverage(project, cov.import_id)}
    assert listed & held
    assert agent_view.parts == full.parts
    assert agent_view.suggestions == full.suggestions


@pytest.mark.parametrize("started", [False, True])
def test_agent_methods_withholds_held_out_until_pass(
    pre_search: Project, agent: Actor, tmp_path: Path, started: bool
) -> None:
    from factory.model.screening import PassLabel
    from factory.services.methods import agent_methods
    from factory.services.screening import open_pass

    import_id, _ = _split_import(pre_search, tmp_path)
    if started:
        open_pass(pre_search, agent, PassLabel.A)
    report, withheld = agent_methods(pre_search, methods_report(pre_search))
    text = render_methods(report, withheld=withheld)
    [paragraph] = [p for p in text.split("\n\n") if p.startswith("Library import")]
    assert import_id in paragraph
    if started:
        assert "withheld" not in paragraph and "Held-out part: " in paragraph
    else:
        assert "Held-out part: withheld until screening has started." in paragraph
        assert "Held-out part: 0" not in paragraph and "resolved records" in paragraph
        assert paragraph.count("resolved records") == 1  # the development part only


def test_suggestions_read_a_bounded_pool(
    pre_search: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services import coverage

    monkeypatch.setattr(coverage, "SUGGESTION_POOL", 2)
    import_id, _ = _split_import(pre_search, tmp_path)
    report = coverage_report(pre_search, import_id)
    holders = {h for s in report.suggestions for h in s.holders}
    assert report.suggestions and len(holders) <= 2


def test_development_duplicate_of_a_held_out_work_counts_in_development(
    pre_search: Project, tmp_path: Path
) -> None:
    n = 16
    entries = [
        bib_entry(
            f"d{i}{c}", f"Dup Study {i} Of Moss", year=2018, author="Kim, Ana", doi=f"10.7777/d.{i}"
        )
        for i in range(1, n + 1)
        for c in "ab"
    ]
    path = tmp_path / "dup.bib"
    path.write_text("".join(entries))
    imp = record_import(
        pre_search, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=9
    ).import_id
    lookups = Lookups(
        openalex=[
            oa_item(f"Dup Study {i} Of Moss", "Ana Kim", 2018, f"W5{i:02d}", doi=f"10.7777/d.{i}")
            for i in range(1, n + 1)
        ]
    )
    resolve_import(pre_search, imp, sources=lookups.sources())
    part_of = {r.ordinal: r.part for r in list_import_records(pre_search, imp, view="all")}
    mixed = [
        i
        for i in range(n)
        if {part_of[2 * i + 1], part_of[2 * i + 2]} == {"development", "held-out"}
    ]
    assert mixed
    report = coverage_report(pre_search, imp)
    dev = report.parts[0].resolved
    expected_dev = sum(
        1 for i in range(n) if "development" in (part_of[2 * i + 1], part_of[2 * i + 2])
    )
    assert dev == expected_dev

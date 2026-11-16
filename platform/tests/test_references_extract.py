"""Reference extraction orchestration (slice 3a, rulings 8, 14, 15). Every entry is invented."""

from __future__ import annotations

import gzip
import re
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.blobs import BlobNotFoundError
from factory.events.envelope import Actor
from factory.model.fulltext import AttemptOutcome, Route
from factory.model.references import MAX_TITLE, LinkState, ReferenceExtracted
from factory.model.work_ids import work_id
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.fulltext import fetch_fulltext
from factory.services.reference_resolve import entry_digest
from factory.services.references import (
    current_extraction,
    extract_references,
    included_works,
    list_references,
    reference_counts,
)
from factory.sources.fulltext.base import not_retrieved
from tests.document_helpers import (
    StubConverter,
    events_of_type,
    make_registry,
    promoted_works,
    run_convert,
)
from tests.references_service_helpers import Lookups, converted_work, corpus_works, oa_item
from tests.route_helpers import StubRoute, always, retrieved

ENTRIES = [
    "A. Zhou. Paper 2. Journal of Tests, 2020. doi:10.1000/p2.",
    "A. Quillfeather. A lattice is worth sixteen tokens. arXiv:2010.99999v2, 2020.",
    "Personal communication.",
]
BODY = ["Prior work {cite:1} and {cite:2}; see also {cite:3} and {cite:1}."]
LATTICE = ("A lattice is worth sixteen tokens", 2020, "Ana Quillfeather")


@pytest.fixture
def lookups() -> Lookups:
    return Lookups(arxiv={"2010.99999": LATTICE})


def _extract(project: Project, actor: Actor, lookups: Lookups, **kw: Any) -> Any:
    return extract_references(project, actor, kw.pop("work_ids", None), sources=lookups.sources())


def test_extract_records_events_and_counts(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    work = converted_work(project, ENTRIES, BODY)
    before = corpus_works(project)
    summary = _extract(project, agent, lookups)
    assert summary.skipped == []
    [result] = summary.extractions
    assert result.work_id == work and result.entries == 3 and result.markers == 3
    assert sum(result.states.values()) == result.entries
    assert result.states[LinkState.RESOLVED] == 2
    assert result.states[LinkState.UNRESOLVED] == 1

    [extracted] = events_of_type(project, "reference.extracted")
    [contexts] = events_of_type(project, "citation.contexts_recorded")
    [resolved] = events_of_type(project, "reference.resolved")
    for event in (extracted, contexts, resolved):
        assert event.actor == agent and event.input_blob is not None
    payload = ReferenceExtracted.model_validate(extracted.payload)
    assert payload.parser == "refparse" and payload.entry_anchors == "b"
    assert payload.bbl.status == "absent"
    assert payload.entries[0].doi == "10.1000/p2"
    assert "text" not in extracted.payload["entries"][0]  # type: ignore[operator]
    conversion = default_conversion(project, work)
    assert conversion is not None and payload.conversion_id == conversion.conversion_id
    assert len(contexts.payload["contexts"]) == 4  # type: ignore[arg-type]
    resolutions = resolved.payload["resolutions"]
    assert [r["method"] for r in resolutions] == [  # type: ignore[union-attr, index]
        "corpus-identifier",
        "lookup-identifier",
        None,
    ]
    assert resolutions[1]["source_blob"] is not None  # type: ignore[index]
    assert resolutions[2]["reason"] == "no-identifier-no-title"  # type: ignore[index]
    assert len(resolved.payload["lookup_runs"]) == 1  # type: ignore[arg-type]
    # the agent's input names the request and the hashes, never the entry text
    blob = project.blobs.get(str(extracted.input_blob)).decode()
    assert "Quillfeather" not in blob and "Personal communication" not in blob

    counts = reference_counts(project)
    assert counts.entries == 3 and counts.extractions == 1
    assert counts.resolved + counts.unconfirmed + counts.ambiguous + counts.unresolved == 3
    assert counts.unresolved == 1 and counts.in_corpus == 1 and counts.new_candidates == 1
    assert current_extraction(project, work) == result.extraction_id
    assert corpus_works(project) == before


def test_probe_lookups_leave_corpus_unchanged(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    converted_work(project, ENTRIES, BODY)
    before = corpus_works(project)
    _extract(project, agent, lookups)
    assert corpus_works(project) == before
    assert lookups.asked == ["arxiv 2010.99999"]


def test_entry_hash_is_of_the_whitespace_normalised_text(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    converted_work(project, ENTRIES, BODY)
    _extract(project, agent, lookups)
    [extracted] = events_of_type(project, "reference.extracted")
    entries = extracted.payload["entries"]
    assert entries[2]["entry_sha256"] == entry_digest("Personal communication.")  # type: ignore[index]


def test_doi_equal_to_arxiv_datacite_resolves_to_existing_work(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    entries = [
        "A. Quillfeather. A lattice is worth sixteen tokens. arXiv:2010.99999, 2020.",
        "A. Quillfeather. A lattice is worth sixteen tokens. 2020. doi:10.48550/arXiv.2010.99999.",
        "A. Zhou. Paper 3. Journal of Tests, 2020. https://doi.org/10.1000/P3.",
    ]
    converted_work(project, entries, ["x"])
    before = corpus_works(project)
    [result] = _extract(project, agent, lookups).extractions
    assert result.states[LinkState.RESOLVED] == 3
    [resolved] = events_of_type(project, "reference.resolved")
    ids = [r["work_id"] for r in resolved.payload["resolutions"]]  # type: ignore[union-attr, index]
    assert ids[0] == ids[1]
    assert corpus_works(project) == before
    assert lookups.asked == ["arxiv 2010.99999"]


def test_identifier_not_found_with_title_year_is_no_source_record_candidate(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    entries = [
        "R. Thornbury. Sparse kernels for tidal data. Imaginary Methods, 2019. doi:10.5555/jim.4."
    ]
    converted_work(project, entries, ["x"])
    [result] = _extract(project, agent, lookups).extractions
    assert result.states[LinkState.RESOLVED] == 1
    [resolved] = events_of_type(project, "reference.resolved")
    [r] = resolved.payload["resolutions"]  # type: ignore[misc]
    assert r["no_source_record"] is True and r["method"] == "no-source-record"  # type: ignore[index]
    assert r["work_id"] == work_id(  # type: ignore[index]
        title="Sparse kernels for tidal data",
        authors=["Thornbury"],
        year=2019,
        doi="10.5555/jim.4",
    )
    assert lookups.asked == ["crossref doi:10.5555/jim.4"]
    assert reference_counts(project).new_candidates == 1


def test_identifier_not_found_without_title_is_unresolved(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    converted_work(project, ["doi:10.5555/gone.1"], ["x"])
    [result] = _extract(project, agent, lookups).extractions
    assert result.states[LinkState.UNRESOLVED] == 1
    [resolved] = events_of_type(project, "reference.resolved")
    assert resolved.payload["resolutions"][0]["reason"] == "not-found"  # type: ignore[index]


def test_source_error_affects_only_its_entries(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    lookups.fail_arxiv = True
    entries = [ENTRIES[0], ENTRIES[1]]
    converted_work(project, entries, ["x"])
    [result] = _extract(project, agent, lookups).extractions
    assert result.states[LinkState.RESOLVED] == 1
    [resolved] = events_of_type(project, "reference.resolved")
    reasons = [r["reason"] for r in resolved.payload["resolutions"]]  # type: ignore[union-attr, index]
    assert reasons == [None, "source-error"]


def test_title_lookup_fuzzy_and_ambiguous(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    lookups.openalex = [
        _oa("Efficient Reed Transformers", "Bo Lee", 2021, "W501"),
        _oa("Moss growth under filtered light", "Pia Ostrander", 2008, "W502"),
        _oa("Moss growth under filtered lights", "Pia Ostrander", 2008, "W503"),
    ]
    entries = [
        "B. Lee. Efficient reed transformers v2. Reed Conference, 2021.",
        "P. Ostrander. Moss growth under filtered light v2. Bryology Today, 2008.",
        "C. Nobody. Wholly unknown matters here. Nowhere Press, 2001.",
    ]
    converted_work(project, entries, ["x"])
    [result] = _extract(project, agent, lookups).extractions
    assert result.states == {
        LinkState.RESOLVED: 0,
        LinkState.UNCONFIRMED: 1,
        LinkState.AMBIGUOUS: 1,
        LinkState.UNRESOLVED: 1,
    }
    assert len([q for q in lookups.asked if q.startswith("crossref title.search:")]) == 3
    [resolved] = events_of_type(project, "reference.resolved")
    rs = resolved.payload["resolutions"]
    assert rs[0]["method"] == "lookup-title" and rs[0]["source_blob"]  # type: ignore[index]
    assert rs[2]["reason"] == "not-found"  # type: ignore[index]
    assert len(resolved.payload["lookup_runs"]) == 3  # type: ignore[arg-type]


def test_title_exact_against_corpus_needs_no_lookup(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    converted_work(project, ["A. Zhou. Paper 4. Journal of Tests, 2020."], ["x"])
    [result] = _extract(project, agent, lookups).extractions
    assert result.states[LinkState.RESOLVED] == 1
    [resolved] = events_of_type(project, "reference.resolved")
    [r] = resolved.payload["resolutions"]  # type: ignore[misc]
    assert r["method"] == "corpus-title" and r["confidence"] == "title-exact"  # type: ignore[index]
    assert lookups.asked == []


def test_over_long_title_is_truncated_and_flagged(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    long_title = " ".join(["Reed"] * 120)
    converted_work(project, [f"Z. Long. {long_title}. Press, 2001."], ["x"])
    [result] = _extract(project, agent, lookups).extractions
    assert "field-truncated" in result.flags
    [extracted] = events_of_type(project, "reference.extracted")
    title = extracted.payload["entries"][0]["title"]  # type: ignore[index]
    assert isinstance(title, str) and len(title) <= MAX_TITLE


def test_unresolved_entries_are_listed(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    work = converted_work(project, ENTRIES, BODY)
    _extract(project, agent, lookups)
    page = list_references(project, state=LinkState.UNRESOLVED, work_id=None, after=0, limit=10)
    assert [(e.citing_work, e.ordinal, e.state) for e in page.items] == [
        (work, 3, LinkState.UNRESOLVED)
    ]
    assert page.total == 1 and page.next_after is None
    everything = list_references(project, state=None, work_id=work, after=0, limit=2)
    assert [e.ordinal for e in everything.items] == [1, 2] and everything.next_after == 2
    rest = list_references(project, state=None, work_id=work, after=2, limit=2)
    assert [e.ordinal for e in rest.items] == [3] and rest.next_after is None
    with pytest.raises(FactoryValidationError):
        list_references(project, state=None, work_id=None, after=0, limit=0)
    with pytest.raises(FactoryValidationError):
        list_references(project, state=None, work_id=None, after=-1, limit=10)


def test_default_population_skips_current_extractions(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    converted_work(project, ENTRIES, BODY)
    assert len(_extract(project, agent, lookups).extractions) == 1
    again = _extract(project, agent, lookups)
    assert again.extractions == [] and again.skipped == []


def test_new_document_version_supersedes_extraction(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    work = converted_work(project, ENTRIES, BODY)
    [first] = _extract(project, agent, lookups).extractions
    run_convert(project, make_registry(StubConverter(version="2.0+stub")))
    assert current_extraction(project, work) is None
    [second] = _extract(project, agent, lookups).extractions
    assert second.extraction_id != first.extraction_id
    assert current_extraction(project, work) == second.extraction_id
    counts = reference_counts(project)
    assert counts.extractions == 1 and counts.entries == 3


def test_extraction_refused_for_not_included_or_no_conversion(
    project: Project, corpus_leaving: str, agent: Actor, lookups: Lookups
) -> None:
    converted = converted_work(project, ENTRIES, BODY)
    no_conversion = next(w for w in promoted_works(project) if w != converted)
    summary = _extract(project, agent, lookups, work_ids=[corpus_leaving, no_conversion, converted])
    assert [(s.work_id, s.reason) for s in summary.skipped] == [
        (corpus_leaving, "not-included"),
        (no_conversion, "no-conversion"),
    ]
    assert [r.work_id for r in summary.extractions] == [converted]
    assert corpus_leaving not in included_works(project)


def test_malformed_work_id_writes_nothing(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    converted_work(project, ENTRIES, BODY)
    with pytest.raises(FactoryValidationError):
        _extract(project, agent, lookups, work_ids=["not a work"])
    assert events_of_type(project, "reference.extracted") == []
    assert lookups.asked == []


def test_document_without_bibliography_is_recorded(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    from tests.document_helpers import ARTICLE, fetched_document

    work = promoted_works(project)[0]
    bare = re.sub(rb'<section class="ltx_bibliography">.*?</section>', b"", ARTICLE, flags=re.S)
    fetched_document(project, work, bare)
    run_convert(project, make_registry())
    [result] = _extract(project, agent, lookups).extractions
    assert result.entries == 0 and "no-bibliography" in result.flags


def test_human_extraction_has_no_input_blob(
    project: Project, corpus: None, human: Actor, lookups: Lookups
) -> None:
    converted_work(project, ENTRIES, BODY)
    _extract(project, human, lookups)
    [extracted] = events_of_type(project, "reference.extracted")
    assert extracted.actor == human and extracted.input_blob is None


def _oa(title: str, author: str, year: int, oa_id: str) -> dict[str, Any]:
    from tests.references_service_helpers import oa_item

    return oa_item(title, author, year, oa_id)


def _with_source(project: Project, entries: list[str], archive: bytes) -> str:
    """The first promoted work with an HTML document (converted) and an arXiv source archive."""
    work = converted_work(project, entries, ["x"])
    source = StubRoute(
        Route.ARXIV_SOURCE,
        always(retrieved(Route.ARXIV_SOURCE, archive, media_type="application/gzip")),
    )
    routes = {
        Route.ARXIV_HTML: StubRoute(
            Route.ARXIV_HTML,
            always(not_retrieved(Route.ARXIV_HTML, AttemptOutcome.NOT_AVAILABLE, "none")),
        ),
        Route.ARXIV_SOURCE: source,
        Route.OA_PDF: StubRoute(
            Route.OA_PDF, always(not_retrieved(Route.OA_PDF, AttemptOutcome.FAILED, "no pdf"))
        ),
    }
    fetch_fulltext(project, routes=routes, work_ids=[work], only=[Route.ARXIV_SOURCE])
    assert source.calls == [work]
    return work


def _bbl(items: list[str]) -> bytes:
    body = "".join(f"\\bibitem{{k{i}}}\n{t}\n" for i, t in enumerate(items, start=1))
    tex = f"\\begin{{thebibliography}}{{9}}\n{body}\\end{{thebibliography}}\n"
    return gzip.compress(tex.encode("utf-8"))


BBL_MD = [
    "B. Lee. Efficient reed transformers. Reed Conference, 2021.",
    "A. Zhou. Paper 5. Journal of Tests, 2020.",
]


def test_bbl_aligned_recovers_identifiers(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    bbl = _bbl(
        [
            "B.~Lee. Efficient reed transformers. Reed Conference, 2021. \\doi{10.5555/reed.21}",
            "A.~Zhou. Paper 5. Journal of Tests, 2020. \\doi{10.1000/p5}",
        ]
    )
    _with_source(project, BBL_MD, bbl)
    [result] = _extract(project, agent, lookups).extractions
    [extracted] = events_of_type(project, "reference.extracted")
    payload = ReferenceExtracted.model_validate(extracted.payload)
    assert payload.bbl.status == "aligned" and payload.bbl.bbl_count == 2
    assert payload.bbl.archive_blob is not None
    assert [e.doi for e in payload.entries] == ["10.5555/reed.21", "10.1000/p5"]
    assert result.states[LinkState.RESOLVED] == 2  # one no-source-record, one in the corpus


def test_bbl_count_mismatch_is_flagged(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    _with_source(project, BBL_MD, _bbl(["A. One. 2001.", "B. Two. 2002.", "C. Three. 2003."]))
    [result] = _extract(project, agent, lookups).extractions
    assert "bbl-count-mismatch" in result.flags
    [extracted] = events_of_type(project, "reference.extracted")
    payload = ReferenceExtracted.model_validate(extracted.payload)
    assert payload.bbl.status == "count-mismatch" and payload.bbl.bbl_count == 3
    assert payload.entries[0].doi is None


def test_bbl_archive_missing_is_flagged(
    project: Project,
    corpus: None,
    agent: Actor,
    lookups: Lookups,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_source(project, BBL_MD, _bbl(["A. One. 2001.", "B. Two. 2002."]))
    real_get = project.library.get

    def get(ref: str) -> bytes:
        data = real_get(ref)
        if data.startswith(b"\x1f\x8b"):
            raise BlobNotFoundError(ref)
        return data

    monkeypatch.setattr(project.library, "get", get)
    [result] = _extract(project, agent, lookups).extractions
    assert "bbl-archive-missing" in result.flags


def test_arxiv_miss_falls_back_to_the_doi(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    lookups.openalex = [oa_item("Tidal lattices", "Ana Quill", 2021, "W601", "10.5555/tidal.1")]
    converted_work(
        project, ["A. Quill. Tidal lattices. arXiv:2101.00002, 2021. doi:10.5555/tidal.1."], ["x"]
    )
    [result] = _extract(project, agent, lookups).extractions
    assert result.states[LinkState.RESOLVED] == 1
    [resolved] = events_of_type(project, "reference.resolved")
    [r] = resolved.payload["resolutions"]  # type: ignore[misc]
    assert r["method"] == "lookup-identifier"  # type: ignore[index]
    assert r["no_source_record"] is False  # type: ignore[index]
    assert lookups.asked == ["arxiv 2101.00002", "crossref doi:10.5555/tidal.1"]


def test_unqueryable_doi_is_not_a_source_error(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    entries = [
        "R. Thornbury. Sparse kernels for tidal data. Imaginary Methods, 2019. doi:10.5555/a,b.",
        "doi:10.5555/c|d",
    ]
    converted_work(project, entries, ["x"])
    _extract(project, agent, lookups)
    [resolved] = events_of_type(project, "reference.resolved")
    rs = resolved.payload["resolutions"]
    assert rs[0]["no_source_record"] is True  # type: ignore[index]
    assert rs[1]["reason"] == "not-found"  # type: ignore[index]
    assert lookups.asked == []


def test_identifier_lookups_are_chunked_at_fifty(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    converted_work(project, [f"doi:10.5555/bulk.{i}" for i in range(1, 56)], ["x"])
    [result] = _extract(project, agent, lookups).extractions
    assert result.states[LinkState.UNRESOLVED] == 55
    asked = [q for q in lookups.asked if q.startswith("crossref doi:")]
    assert sorted(q.count("|") + 1 for q in asked) == [5, 50]
    assert len(result.lookup_runs) == 2


def test_no_entry_text_in_events_or_blobs(
    project: Project, corpus: None, agent: Actor, lookups: Lookups
) -> None:
    planted = "Zanzibarquokka"
    entries = [
        f"B. Lee. Efficient reed transformers v2. Reed Conference, 2021. {planted} remark one.",
        f"A. Zhou. Paper 2. Journal of Tests, 2020. {planted} remark two. doi:10.1000/p2.",
        f"A. Quillfeather. A lattice is worth sixteen tokens. 2020. {planted} three. "
        "arXiv:2010.99999.",
    ]
    converted_work(project, entries, ["x"])
    _extract(project, agent, lookups)
    assert events_of_type(project, "reference.extracted")
    assert any(q.startswith("crossref title.search:") for q in lookups.asked)
    scanned = 0
    for root in (project.paths.events_dir, project.paths.blobs_dir):
        for path in root.rglob("*"):
            if path.is_file():
                scanned += 1
                assert planted.encode() not in path.read_bytes(), path
    assert scanned > 0


def _plan_flag(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    from types import SimpleNamespace

    from factory.model.protocol import SnowballPlan
    from factory.services import references

    plan = SnowballPlan(max_backward_rounds=2, max_forward_rounds=1, background_sources=on)
    protocol = SimpleNamespace(spec=SimpleNamespace(snowball_plan=plan, full_text_screening=None))
    monkeypatch.setattr(references, "current_protocol", lambda p: protocol)


@pytest.mark.parametrize("on", [False, True])
def test_background_works_are_extracted_only_under_the_plan_flag(
    project: Project,
    corpus: None,
    agent: Actor,
    lookups: Lookups,
    monkeypatch: pytest.MonkeyPatch,
    on: bool,
) -> None:
    from factory.services import references, snowball

    work = converted_work(project, ENTRIES, BODY)
    monkeypatch.setattr(references, "included_works", lambda p: [])
    monkeypatch.setattr(references, "background_works", lambda p: {work: "EX02"})
    monkeypatch.setattr(snowball, "background_works", lambda p: {work: "EX02"})
    monkeypatch.setattr(snowball, "included_works", lambda p: [])
    _plan_flag(monkeypatch, on)
    summary = _extract(project, agent, lookups, work_ids=[work])
    if on:
        assert [r.work_id for r in summary.extractions] == [work] and not summary.skipped
        sources, _, _ = snowball._scope(project, background=True)
        assert sources == [work]
    else:
        assert [(s.work_id, s.reason) for s in summary.skipped] == [(work, "not-included")]
        assert not summary.extractions

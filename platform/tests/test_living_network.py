"""Live checks of the notice lookups. Network; skipped by default (`-m "not network"`).

Run once with `FACTORY_MAILTO` set. The DOIs below are off-topic and none is a pilot work.
"""

from __future__ import annotations

import pytest

from factory.clock import SystemClock
from factory.config import Settings
from factory.model.notices import NoticeKind
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.sources.base import RawPage, SearchResult
from factory.sources.crossref import CrossrefSource
from factory.sources.http import default_http
from factory.sources.openalex import OpenAlexSource
from tests.helpers import SESSION

pytestmark = pytest.mark.network

# Off-topic, widely documented: a retracted 1998 paper in The Lancet and its retraction notice.
RETRACTED_DOI = "10.1016/s0140-6736(97)11096-0"


def _archive(page: RawPage) -> str:
    return f"sha256:{page.ordinal + 1:064x}"


def _run(source: CrossrefSource | OpenAlexSource, spec: QuerySpec) -> SearchResult:
    return source.run(spec, run_id=f"run_{SESSION}", query_id=f"qry_{SESSION}", archive=_archive)


def _crossref(tmp_path: object) -> CrossrefSource:
    settings = Settings(root=tmp_path, user="obd")  # type: ignore[arg-type]
    return CrossrefSource(default_http(settings), clock=SystemClock(), mailto=settings.mailto)


def _status(text: str, source: str = "crossref") -> QuerySpec:
    return QuerySpec(source=source, kind=QueryKind.FILTER, text=text, purpose=QueryPurpose.STATUS)


def test_crossref_updates_filter_live(tmp_path: object) -> None:
    result = _run(_crossref(tmp_path), _status(f"updates:{RETRACTED_DOI}"))
    assert result.status is RunStatus.COMPLETE, result.note
    kinds = {r.notice_kind for r in result.status_records}
    assert NoticeKind.RETRACTION in kinds
    assert all(r.target.doi == RETRACTED_DOI for r in result.status_records)


def test_crossref_repeated_updates_filter_semantics(tmp_path: object) -> None:
    """Records whether repeated `updates:` filters are OR-ed or AND-ed; the result selects the
    batching of ruling 3. Observed 2026-11-05 (live run): repeated `updates:` filters are OR-ed,
    so one Crossref query carries up to `CHASE_CHUNK` DOIs (`updates:a,updates:b,...`). If this
    test ever fails, the filters have become AND-ed and the service must query one DOI at a
    time."""
    other = "10.1371/journal.pone.0000000"  # not a retraction target: contributes nothing
    result = _run(_crossref(tmp_path), _status(f"updates:{RETRACTED_DOI},updates:{other}"))
    assert result.status is RunStatus.COMPLETE, result.note
    assert any(r.target.doi == RETRACTED_DOI for r in result.status_records), (
        "repeated updates: filters are AND-ed: query one DOI at a time"
    )


def test_openalex_is_retracted_live(tmp_path: object) -> None:
    settings = Settings(root=tmp_path, user="obd")  # type: ignore[arg-type]
    source = OpenAlexSource(default_http(settings), clock=SystemClock(), mailto=settings.mailto)
    result = _run(source, _status(f"doi:{RETRACTED_DOI}", "openalex"))
    assert result.status is RunStatus.COMPLETE, result.note
    assert any(r.notice_kind is NoticeKind.RETRACTION for r in result.status_records)

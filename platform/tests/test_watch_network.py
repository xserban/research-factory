"""Live checks of the window filters. Network; skipped by default (`-m "not network"`)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from factory.clock import SystemClock
from factory.config import Settings
from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.sources.arxiv import ArxivSource
from factory.sources.http import default_http
from factory.sources.openalex import OpenAlexSource
from tests.helpers import SESSION

pytestmark = pytest.mark.network


def _since() -> str:
    return (date.today() - timedelta(days=14)).isoformat()


def _archive(_page: object) -> str:
    return "sha256:" + "a" * 64


def test_openalex_from_created_date_accepted_without_key(tmp_path: object) -> None:
    """Ruling 2 verification. A 200 with results means `OpenAlexSource.window_filter` may be set
    True; anything else documents the failure and leaves window mode disabled for OpenAlex."""
    settings = Settings(root=tmp_path, user="obd")  # type: ignore[arg-type]
    source = OpenAlexSource(default_http(settings), clock=SystemClock(), mailto=settings.mailto)
    spec = QuerySpec(
        source="openalex",
        kind=QueryKind.KEYWORD,
        text="attention",
        filters={"listed_since": _since()},
        limit=5,
    )
    result = source.run(spec, run_id=f"run_{SESSION}", query_id=f"qry_{SESSION}", archive=_archive)
    assert result.status is not RunStatus.FAILED, result.note
    assert result.works, "from_created_date returned nothing: keep window_filter False"


def test_arxiv_submitted_date_window(tmp_path: object) -> None:
    settings = Settings(root=tmp_path, user="obd")  # type: ignore[arg-type]
    source = ArxivSource(default_http(settings), clock=SystemClock(), mailto=settings.mailto)
    spec = QuerySpec(
        source="arxiv",
        kind=QueryKind.KEYWORD,
        text="all:transformer",
        filters={"listed_since": _since()},
        limit=5,
    )
    result = source.run(spec, run_id=f"run_{SESSION}", query_id=f"qry_{SESSION}", archive=_archive)
    assert result.status is not RunStatus.FAILED, result.note
    assert result.works
    cutoff = date.fromisoformat(_since())
    assert all(w.dates.published is not None and w.dates.published >= cutoff for w in result.works)

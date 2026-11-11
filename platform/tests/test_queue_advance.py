"""Tests for `work_queue.advance` (plan 2026-11-11-feed-hub, step H6). Every service it calls is
monkeypatched; no index, network or converter runs. Written in TDD order, not yet run (testing is
paused by the researcher)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.model.inbox import ResolveStatus
from factory.services import work_queue
from factory.services.inbox import ResolveOutcome
from factory.services.work_queue import QueueItem


class _StubProject:
    """Only what `advance` reads from a project: the human actor."""

    def human_actor(self) -> object:
        return object()


def _paper(
    n: int,
    stage: str,
    *,
    work_id: str | None = None,
    stopped: bool = False,
) -> QueueItem:
    return QueueItem(
        entry_id=f"e{n}",
        title=f"paper {n}",
        inbox_item_id=f"item{n}",
        sent_at="2026-11-11T00:00:00Z",
        work_id=work_id,
        stage=stage,  # type: ignore[arg-type]
        stopped=stopped,
        detail="",
    )


def _fetch_summary(status: str) -> SimpleNamespace:
    return SimpleNamespace(works=[SimpleNamespace(status=status)])


def _convert_summary(converted: int, outcomes: list[Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(converted=converted, outcomes=outcomes or [])


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Records of each patched service, in call order."""
    log: dict[str, list[Any]] = {"resolve": [], "fetch": [], "convert": []}
    registry = object()

    def fake_resolve(project: Any, actor: Any, *, sources: Any, item_ids: Any) -> list[Any]:
        log["resolve"].append(list(item_ids))
        return [ResolveOutcome(item_id=item_ids[0], status=ResolveStatus.NEW, work_id="w-new")]

    def fake_fetch(project: Any, *, routes: Any, work_ids: Any, limit: int, actor: Any) -> Any:
        log["fetch"].append(list(work_ids))
        return _fetch_summary("retrieved")

    def fake_convert(project: Any, reg: Any, *, work_ids: Any) -> Any:
        log["convert"].append((list(work_ids), reg is registry))
        return _convert_summary(1)

    monkeypatch.setattr(work_queue, "resolve_links", fake_resolve)
    monkeypatch.setattr(work_queue, "fetch_fulltext", fake_fetch)
    monkeypatch.setattr(work_queue, "convert_documents", fake_convert)
    monkeypatch.setattr(work_queue, "default_converters", lambda: registry)
    return log


def _run(
    monkeypatch: pytest.MonkeyPatch, papers: list[QueueItem], **kwargs: Any
) -> work_queue.AdvanceResult:
    monkeypatch.setattr(work_queue, "added_papers", lambda project: list(papers))
    return work_queue.advance(
        _StubProject(),  # type: ignore[arg-type]
        sources={},
        fetchers={},
        **kwargs,
    )


def test_open_item_never_looked_up_is_resolved(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]]
) -> None:
    result = _run(monkeypatch, [_paper(1, "added")])
    assert calls["resolve"] == [["item1"]]
    assert result.resolve_attempted == 1
    assert result.resolved == 1
    assert result.errors == []


def test_lookup_failed_item_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]]
) -> None:
    result = _run(monkeypatch, [_paper(1, "lookup-failed", stopped=True)])
    assert calls["resolve"] == []
    assert result.resolve_attempted == 0


def test_withdrawn_item_is_not_resolved(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]]
) -> None:
    _run(monkeypatch, [_paper(1, "added", stopped=True)])
    assert calls["resolve"] == []


def test_refused_resolve_is_an_error_for_that_paper(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]]
) -> None:
    def refused(project: Any, actor: Any, *, sources: Any, item_ids: Any) -> list[Any]:
        return [ResolveOutcome(item_id=item_ids[0], status=None, issues=[])]

    monkeypatch.setattr(work_queue, "resolve_links", refused)
    result = _run(monkeypatch, [_paper(1, "added")], convert=False)
    assert result.resolved == 0
    assert [e.step for e in result.errors] == ["resolve"]
    assert result.errors[0].item_id == "item1"


def test_screened_in_paper_is_fetched(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]]
) -> None:
    result = _run(monkeypatch, [_paper(1, "screened-in", work_id="w1")], convert=False)
    assert calls["fetch"] == [["w1"]]
    assert result.fetch_attempted == 1
    assert result.fetched == 1


def test_fetch_without_retrieval_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]]
) -> None:
    monkeypatch.setattr(
        work_queue,
        "fetch_fulltext",
        lambda project, **kwargs: _fetch_summary("not-retrieved"),
    )
    result = _run(monkeypatch, [_paper(1, "screened-in", work_id="w1")], convert=False)
    assert result.fetched == 0
    assert result.errors == []


def test_full_text_paper_is_converted_with_the_default_converters(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]]
) -> None:
    result = _run(monkeypatch, [_paper(1, "full-text", work_id="w2")])
    assert calls["convert"] == [(["w2"], True)]
    assert result.convert_attempted == 1
    assert result.converted == 1
    assert result.convert_skipped is False


def test_failed_conversion_document_is_an_error(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]]
) -> None:
    outcome = SimpleNamespace(status="failed", reason="timeout", document_id="d1")
    monkeypatch.setattr(
        work_queue,
        "convert_documents",
        lambda project, reg, *, work_ids: _convert_summary(0, [outcome]),
    )
    result = _run(monkeypatch, [_paper(1, "full-text", work_id="w2")])
    assert result.converted == 0
    assert [(e.step, e.work_id) for e in result.errors] == [("convert", "w2")]
    assert "d1: timeout" in result.errors[0].reason


def test_one_paper_error_does_not_stop_the_next(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]]
) -> None:
    def fetch(project: Any, *, routes: Any, work_ids: Any, limit: int, actor: Any) -> Any:
        calls["fetch"].append(list(work_ids))
        if work_ids == ["w1"]:
            raise RuntimeError("route exploded")
        return _fetch_summary("retrieved")

    monkeypatch.setattr(work_queue, "fetch_fulltext", fetch)
    papers = [_paper(1, "screened-in", work_id="w1"), _paper(2, "screened-in", work_id="w2")]
    result = _run(monkeypatch, papers, convert=False)
    assert calls["fetch"] == [["w1"], ["w2"]]
    assert result.fetched == 1
    assert [(e.step, e.work_id) for e in result.errors] == [("fetch", "w1")]


def test_no_convert_skips_conversion_only(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]]
) -> None:
    papers = [
        _paper(1, "added"),
        _paper(2, "screened-in", work_id="w1"),
        _paper(3, "full-text", work_id="w2"),
    ]
    result = _run(monkeypatch, papers, convert=False)
    assert calls["resolve"] == [["item1"]]
    assert calls["fetch"] == [["w1"]]
    assert calls["convert"] == []
    assert result.convert_skipped is True
    assert result.convert_attempted == 0


def test_limit_caps_each_step(monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]]) -> None:
    papers = [_paper(n, "screened-in", work_id=f"w{n}") for n in range(3)]
    result = _run(monkeypatch, papers, convert=False, limit=1)
    assert calls["fetch"] == [["w0"]]
    assert result.fetch_attempted == 1


@pytest.mark.parametrize("bad", [0, 201])
def test_limit_outside_range_is_refused_before_anything_runs(
    monkeypatch: pytest.MonkeyPatch, calls: dict[str, list[Any]], bad: int
) -> None:
    monkeypatch.setattr(work_queue, "added_papers", lambda project: [_paper(1, "added")])
    with pytest.raises(FactoryValidationError):
        work_queue.advance(
            _StubProject(),  # type: ignore[arg-type]
            sources={},
            fetchers={},
            limit=bad,
        )
    assert calls == {"resolve": [], "fetch": [], "convert": []}

"""The gap finder (slice 6, plan H-B, task 5; acceptance 7).

Evidence world: twelve included works, pass A and B both extract (dual sample 1.0):

    w0, w1  method lorem, task classification      w3  lorem / detection
    w2      method low, task detection             w4  lorem / segmentation
    w5      method low, task classification, but a cited (copied) value
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from sqlalchemy import Engine, event

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.extraction import ExtractedRowInput, FieldInput, ReportedIn
from factory.model.screening import PassLabel
from factory.packs import ML_BENCHMARK_V1
from factory.services import finders
from factory.services.cards import decide_assertion
from factory.services.context import Project
from factory.services.extraction_agreement import final_rows
from factory.services.finders import GapReport, find_gaps
from factory.sources.registry import SourceFactory
from tests.card_helpers import cw
from tests.evidence_helpers import run_pass
from tests.finder_helpers import MatchWorld, mw
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world
from tests.test_acceptance_fulltext_screening import _screened_full_text_world
from tests.test_extraction_agreement import _declare, _r
from tests.test_extraction_next import SESSION_A, SESSION_B, _extractor

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
STATEMENT = (
    "Not found in this corpus (protocol {p}, {n} included works, last search {d}); "
    "absence here is not absence in the literature."
)


def _method(name: str, anchor: str) -> dict[str, FieldInput]:
    return {"method_name": FieldInput(value=name, anchor=anchor, quote=name)}


@pytest.fixture
def gw(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    mock_sources: SourcesFor,
) -> list[str]:
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    _declare(project, agent)
    from factory.services.extraction import extraction_population

    works = extraction_population(project)
    spec: dict[str, tuple[str, str, bool]] = {
        works[0]: ("Lorem", "classification", False),
        works[1]: ("Lorem", "classification", False),
        works[2]: ("Low", "detection", False),
        works[3]: ("Lorem", "detection", False),
        works[4]: ("Lorem", "segmentation", False),
        works[5]: ("Low", "classification", True),
    }
    anchors = {"Lorem": "t1.r3.c1", "Low": "t1.r2.c2"}

    def rows_for(work: str) -> list[ExtractedRowInput]:
        if work not in spec:
            return []
        name, task, cited = spec[work]
        return [
            _r(
                task=task,
                reported_in=ReportedIn.CITED if cited else ReportedIn.OWN,
                **_method(name, anchors[name]),
            )
        ]

    run_pass(project, _extractor(SESSION_A, "claude-opus-5-5"), PassLabel.A, rows_for)
    run_pass(project, _extractor(SESSION_B, "claude-sonnet-5-5"), PassLabel.B, rows_for)
    return works


def test_empty_cells_with_corpus_definition(
    project: Project, gw: list[str]
) -> None:  # acceptance 7
    report = find_gaps(project, rows_axis="method", columns_axis="task")
    assert report.cells == 6 and report.filled == 4
    assert [(c.row, c.column, c.count) for c in report.empty] == [
        ("low", "classification", 0),
        ("low", "segmentation", 0),
    ]
    assert report.corpus.included_works == len(gw)
    assert report.corpus.protocol_id.startswith("P@")
    assert report.statement == STATEMENT.format(
        p=report.corpus.protocol_id, n=len(gw), d=report.corpus.last_search
    )
    assert report.rows_axis == "method" and report.columns_axis == "task"


def test_counts_equal_python_count_over_final_rows(project: Project, gw: list[str]) -> None:
    report = find_gaps(project, rows_axis="method", columns_axis="task")
    counted: Counter[tuple[str, str]] = Counter()
    for row in final_rows(project):
        if row.independent:
            counted[(row.fields["method_name"].value.lower(), row.fields["task"].value)] += 1
    assert report.filled == len(counted)
    assert counted == Counter(
        {
            ("lorem", "classification"): 2,
            ("lorem", "detection"): 1,
            ("lorem", "segmentation"): 1,
            ("low", "detection"): 1,
        }
    )
    cells = {(c.row, c.column) for c in report.empty}
    assert cells.isdisjoint(counted)


def test_filters_narrow_the_grid(project: Project, gw: list[str]) -> None:
    report = find_gaps(project, rows_axis="method", columns_axis="task", filters={"split": "val"})
    assert report.cells == 6 and report.filters == {"split": "val"}
    none = find_gaps(project, rows_axis="method", columns_axis="task", filters={"split": "test"})
    assert none.cells == 0 and none.empty == []


def test_grid_too_large_refused_before_query(
    project: Project, gw: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:  # Review Focus 3; acceptance 7
    monkeypatch.setattr(finders, "GAP_MAX_CELLS", 5)

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("rows were read before the grid size was checked")

    monkeypatch.setattr(finders, "final_rows", boom)
    seen: list[str] = []

    def spy(conn: Any, cursor: Any, statement: str, *_rest: Any) -> None:
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", spy)
    try:
        with pytest.raises(FactoryValidationError) as e:
            find_gaps(project, rows_axis="method", columns_axis="task")
    finally:
        event.remove(Engine, "before_cursor_execute", spy)
    issue = e.value.issues[0]
    assert issue.field == "filters" and issue.reason.startswith("grid-too-large")
    assert "6" in issue.reason and "5" in issue.reason
    assert any("COUNT(DISTINCT" in s.upper() for s in seen)
    assert not any("GROUP BY" in s.upper() for s in seen)


def test_unknown_axis_refused(project: Project, gw: list[str]) -> None:
    for kwargs, field in (
        ({"rows_axis": "method", "columns_axis": "nonsense"}, "columns_axis"),
        ({"rows_axis": "method", "columns_axis": "pr:memory-scaling"}, "columns_axis"),
        ({"rows_axis": "idea", "columns_axis": "task"}, "rows_axis"),
        ({"rows_axis": "method", "columns_axis": "task", "filters": {"nonsense": "x"}}, "filters"),
    ):
        with pytest.raises(FactoryValidationError) as e:
            find_gaps(project, **kwargs)  # type: ignore[arg-type]
        assert e.value.issues[0].field == field, kwargs


def test_card_axis_uses_effective_assertions(
    project: Project, mw: MatchWorld, other_session_human: Actor
) -> None:
    report = find_gaps(project, rows_axis="card", columns_axis="pr:memory-scaling")
    assert report.cells == 12 and report.filled == 4
    empty = {(c.row, c.column) for c in report.empty}
    assert (mw.inferred, "linear") in empty and (mw.inferred, "quadratic") in empty
    assert (mw.ok, "linear") not in empty and (mw.ok, "quadratic") in empty
    assert (mw.conflict, "quadratic") not in empty
    decide_assertion(
        project, other_session_human, mw.assertions[mw.ok]["pr:memory-scaling"], "reject", "no"
    )
    later = find_gaps(project, rows_axis="card", columns_axis="pr:memory-scaling")
    assert later.filled == 3 and (mw.ok, "linear") in {(c.row, c.column) for c in later.empty}
    assert later.corpus.included_works >= 0


def test_gap_key_deterministic(project: Project, gw: list[str]) -> None:
    a = find_gaps(project, rows_axis="method", columns_axis="task")
    b = find_gaps(project, rows_axis="method", columns_axis="task")
    assert a.gap_key == b.gap_key and len(a.gap_key) == 16
    c = find_gaps(project, rows_axis="method", columns_axis="task", filters={"split": "test"})
    assert c.gap_key != a.gap_key

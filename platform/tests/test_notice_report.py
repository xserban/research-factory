"""Notice effects on the evidence report: exclusion, labels, frontiers (pure assembly)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from factory.model.notices import AssessmentDecision, NoticeKind, NoticeObserved, notice_state
from factory.services.evidence_report import EvidenceReport, assemble_report
from factory.services.extraction_agreement import FinalRow
from tests.evidence_helpers import POPULATION, ff, frow, pilot_inputs, pilot_rows
from tests.test_notice_state import _ntc, assessed

W1, W2, W3 = "rf:w1", "rf:w2", "rf:w3"


def observed(n: int, work: str, kind: NoticeKind) -> NoticeObserved:
    """A notice of a synthetic work id (`rf:w1`, which is not a corpus work id pattern)."""
    return NoticeObserved.model_construct(
        notice_id=_ntc(n),
        work_id=work,
        kind=kind,
        notice_date=None,
        notice_doi=f"10.1000/n{n}",
        source="crossref",
        run_id="run_x",
        raw_blob="sha256:" + "a" * 64,
    )


def _states(*notices: Any, decisions: Any = ()) -> dict[str, Any]:
    return notice_state(list(notices), list(decisions))


def _dump(report: EvidenceReport, *, drop: set[str] = frozenset()) -> dict[str, Any]:  # type: ignore[assignment]
    return report.model_dump(mode="json", exclude=set(drop))


def _cost(n: str) -> Any:
    return ff(n, unit="count", canon=n)


def test_report_excludes_retracted_by_default() -> None:
    states = _states(observed(1, W1, NoticeKind.RETRACTION))
    rows = pilot_rows()
    with_notice = assemble_report(replace(pilot_inputs(rows), notice_states=states))
    without_w1 = assemble_report(
        pilot_inputs(
            [r for r in rows if r.work_id != W1], population=[w for w in POPULATION if w != W1]
        )
    )
    assert _dump(with_notice, drop={"excluded"}) == _dump(without_w1, drop={"excluded"})
    [entry] = [e for e in with_notice.excluded if e.reason == "retracted"]
    assert (entry.count, entry.works) == (2, [W1])  # w1's two final rows
    # The work does not reappear as a work without a final row.
    assert all(W1 not in e.works for e in with_notice.excluded if e.reason != "retracted")
    assert [e for e in without_w1.excluded if e.reason == "retracted"] == []


def test_include_notice_affected_flag_restores_rows() -> None:
    states = _states(observed(1, W1, NoticeKind.RETRACTION))
    base = assemble_report(pilot_inputs())
    wide = assemble_report(
        replace(pilot_inputs(), notice_states=states), include_notice_affected=True
    )
    assert wide.excluded == base.excluded
    assert [g.group_id for g in wide.groups] == [g.group_id for g in base.groups]
    labelled = [r for g in wide.groups for r in g.rows if r.work_id == W1]
    assert labelled and {r.notice for r in labelled} == {"retracted"}
    assert {r.notice for g in wide.groups for r in g.rows if r.work_id != W1} == {None}
    # Without the label the report is the unaffected one.
    unlabelled = wide.model_copy(
        update={
            "groups": [
                g.model_copy(
                    update={"rows": [r.model_copy(update={"notice": None}) for r in g.rows]}
                )
                for g in wide.groups
            ],
            "ungrouped": [r.model_copy(update={"notice": None}) for r in wide.ungrouped],
        }
    )
    assert _dump(unlabelled) == _dump(base)


def test_keep_flagged_returns_rows_labelled() -> None:
    notice = observed(1, W1, NoticeKind.RETRACTION)
    states = _states(notice, decisions=[assessed(1, "ev_2", AssessmentDecision.KEEP_FLAGGED)])
    report = assemble_report(replace(pilot_inputs(), notice_states=states))
    assert [e for e in report.excluded if e.reason == "retracted"] == []
    assert {r.notice for g in report.groups for r in g.rows if r.work_id == W1} == {"retracted"}


def _three() -> list[FinalRow]:
    return [
        frow(W1, "rk_000000000101", "A", "80.0", params=_cost("20000000")),
        frow(W2, "rk_000000000201", "B", "79.0", params=_cost("30000000")),
        frow(W3, "rk_000000000301", "C", "82.0", params=_cost("40000000")),
    ]


def _frontier_keys(report: EvidenceReport) -> set[str]:
    [group] = report.groups
    return {p.row_key for axis in group.frontiers for part in axis.partitions for p in part.points}


def test_correction_pending_leaves_frontier_only() -> None:
    base = assemble_report(pilot_inputs(_three()))
    states = _states(observed(1, W2, NoticeKind.CORRECTION))
    report = assemble_report(replace(pilot_inputs(_three()), notice_states=states))
    assert "rk_000000000201" in _frontier_keys(base)
    assert "rk_000000000201" not in _frontier_keys(report)
    # The row stays in its group, labelled; the group's counts are those of the full group.
    [group] = report.groups
    assert {r.row_key: r.notice for r in group.rows}["rk_000000000201"] == "correction-pending"
    assert group.counts == base.groups[0].counts
    [entry] = [e for e in report.excluded if e.reason == "correction-pending"]
    assert (entry.count, entry.works) == (1, [W2])
    # After a no-effect assessment the row rejoins the frontier and the entry disappears.
    cleared = _states(
        observed(1, W2, NoticeKind.CORRECTION),
        decisions=[assessed(1, "ev_2", AssessmentDecision.NO_EFFECT)],
    )
    back = assemble_report(replace(pilot_inputs(_three()), notice_states=cleared))
    assert _frontier_keys(back) == _frontier_keys(base)
    assert [e for e in back.excluded if e.reason == "correction-pending"] == []


def test_unlabelled_rows_serialise_without_a_notice_key() -> None:
    report = assemble_report(pilot_inputs())
    assert all("notice" not in row for g in report.model_dump()["groups"] for row in g["rows"])

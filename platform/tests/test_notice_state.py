"""The pure read-time function: notice observations and assessments to per-work states."""

from __future__ import annotations

from datetime import date

from factory.model.notices import (
    AssessmentDecision,
    NoticeAssessed,
    NoticeKind,
    NoticeObserved,
    notice_state,
)
from factory.model.staleness import RowRef, notice_stale_rows

W1 = "rf:work-one-aaaaaaaa"
W2 = "rf:work-two-bbbbbbbb"
RUN = "run_01JZ9Q3K5M7N8P0R2S4T6V8W0X"
BLOB = "sha256:" + "a" * 64


def _ntc(n: int) -> str:
    return f"ntc_01JZ9Q3K5M7N8P0R2S4T6V8W{n:02d}"


def observed(
    n: int, work: str, kind: NoticeKind, *, source: str = "crossref", when: date | None = None
) -> NoticeObserved:
    return NoticeObserved(
        notice_id=_ntc(n),
        work_id=work,
        kind=kind,
        notice_date=when,
        notice_doi=f"10.1000/n{n}" if source == "crossref" else None,
        source=source,
        run_id=RUN,
        raw_blob=BLOB,
    )


def assessed(
    n: int, event: str, decision: AssessmentDecision, fields: tuple[str, ...] = ()
) -> tuple[str, NoticeAssessed]:
    return event, NoticeAssessed(
        notice_id=_ntc(n), decision=decision, fields=fields, rationale="checked"
    )


def test_state_table_retraction() -> None:
    notices = [observed(1, W1, NoticeKind.RETRACTION), observed(2, W2, NoticeKind.WITHDRAWAL)]
    states = notice_state(notices, [])
    assert set(states) == {W1, W2}
    for work in (W1, W2):
        state = states[work]
        assert (state.flag, state.synthesis, state.assessed) == ("retracted", "excluded", False)
    kept = notice_state(notices, [assessed(1, "ev_2", AssessmentDecision.KEEP_FLAGGED)])
    assert (kept[W1].flag, kept[W1].synthesis, kept[W1].assessed) == ("retracted", "labelled", True)
    out = notice_state(notices, [assessed(1, "ev_2", AssessmentDecision.EXCLUDE)])
    assert (out[W1].flag, out[W1].synthesis, out[W1].assessed) == ("retracted", "excluded", True)
    assert out[W2].assessed is False  # the other work's notice is untouched


def test_state_table_correction_before_and_after_assessment() -> None:
    notices = [observed(1, W1, NoticeKind.CORRECTION)]
    before = notice_state(notices, [])[W1]
    assert (before.flag, before.synthesis, before.assessed) == (
        "correction-pending",
        "labelled",
        False,
    )
    assert before.stale_fields == ()
    no_effect = notice_state(notices, [assessed(1, "ev_2", AssessmentDecision.NO_EFFECT)])[W1]
    assert (no_effect.flag, no_effect.synthesis, no_effect.stale_fields) == ("none", "normal", ())
    affects = notice_state(
        notices, [assessed(1, "ev_2", AssessmentDecision.AFFECTS, ("value", "metric"))]
    )[W1]
    assert affects.flag == "none" and affects.stale_fields == ("metric", "value")
    assert affects.assessed is True


def test_expression_of_concern_labels_and_can_exclude() -> None:
    notices = [observed(1, W1, NoticeKind.EXPRESSION_OF_CONCERN)]
    state = notice_state(notices, [])[W1]
    assert (state.flag, state.synthesis) == ("concern", "labelled")
    out = notice_state(notices, [assessed(1, "ev_2", AssessmentDecision.EXCLUDE)])[W1]
    assert (out.flag, out.synthesis) == ("concern", "excluded")


def test_latest_assessment_wins() -> None:
    notices = [observed(1, W1, NoticeKind.RETRACTION)]
    pairs = [
        assessed(1, "ev_5", AssessmentDecision.EXCLUDE),
        assessed(1, "ev_3", AssessmentDecision.KEEP_FLAGGED),
    ]
    assert notice_state(notices, pairs)[W1].synthesis == "excluded"  # ev_5 is the later event
    assert notice_state(notices, pairs[::-1])[W1].synthesis == "excluded"


def test_reinstatement_restores() -> None:
    retraction = observed(1, W1, NoticeKind.RETRACTION)
    reinstated = observed(2, W1, NoticeKind.REINSTATEMENT)
    states = notice_state([retraction, reinstated], [])
    assert (states[W1].flag, states[W1].synthesis, states[W1].assessed) == ("none", "normal", True)
    assert states[W1].notices == (_ntc(1), _ntc(2))
    # A retraction observed after the reinstatement applies again.
    again = observed(3, W1, NoticeKind.RETRACTION)
    assert notice_state([retraction, reinstated, again], [])[W1].flag == "retracted"
    # An earlier correction survives a reinstatement of a retraction.
    correction = observed(4, W1, NoticeKind.CORRECTION)
    mixed = notice_state([correction, retraction, reinstated], [])[W1]
    assert mixed.flag == "correction-pending"


def test_keep_flagged_returns_rows() -> None:
    notices = [observed(1, W1, NoticeKind.RETRACTION)]
    state = notice_state(notices, [assessed(1, "ev_2", AssessmentDecision.KEEP_FLAGGED)])[W1]
    assert state.synthesis == "labelled"  # not excluded: the rows return, labelled


def test_worst_notice_of_a_work_decides() -> None:
    notices = [
        observed(1, W1, NoticeKind.CORRECTION),
        observed(2, W1, NoticeKind.RETRACTION),
    ]
    state = notice_state(notices, [assessed(2, "ev_9", AssessmentDecision.KEEP_FLAGGED)])[W1]
    assert (state.flag, state.synthesis, state.assessed) == ("retracted", "labelled", False)


def test_notice_stale_rows_is_bounded_to_the_work_fields_and_time() -> None:
    notices = [observed(1, W1, NoticeKind.CORRECTION)]
    states = notice_state(notices, [assessed(1, "ev_50", AssessmentDecision.AFFECTS, ("value",))])
    rows = [
        (W1, "ext_a", RowRef(row_id="ext_a", fields=("value", "task"), at="ev_10")),
        (W1, "ext_b", RowRef(row_id="ext_b", fields=("task",), at="ev_10")),
        (W2, "ext_c", RowRef(row_id="ext_c", fields=("value",), at="ev_10")),
        (W1, "ext_d", RowRef(row_id="ext_d", fields=("value",), at="ev_60")),  # after the act
    ]
    assert notice_stale_rows(states, rows) == ["ext_a"]
    assert notice_stale_rows({}, rows) == []

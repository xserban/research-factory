"""The Updates page from a view: no snapshot, escaping, disabled buttons (written, not run)."""

from __future__ import annotations

from datetime import UTC, datetime

from factory.services.site_updates import render_updates
from factory.services.updates import (
    AdditionRow,
    BaselineView,
    GrowthPoint,
    OpenPeriod,
    UpdatesView,
    WatchSourceView,
    WatchView,
)

NO_WATCH = WatchView(has_plan=False, until=None, snapshot_every=None, open_cycle=None, sources=())
WHEN = datetime(2026, 11, 1, tzinfo=UTC)


def _row(title: str) -> AdditionRow:
    return AdditionRow(
        work_id="w1",
        title=title,
        year=2026,
        added_at=WHEN,
        route="inbox",
        note="<b>note</b>",
        ta_outcome="included",
        ft_state=None,
        ft_outcome=None,
        layer=None,
        mined=(),
    )


def _view(title: str = "A paper") -> UpdatesView:
    watch = WatchView(
        has_plan=True,
        until=None,
        snapshot_every=1,
        open_cycle=None,
        sources=(
            WatchSourceView(
                source="arxiv",
                mode="window",
                interval_days=7,
                overlap_days=7,
                full_replay_every=None,
                last_cycle=None,
                last_finished_at=None,
                next_due=None,
                due=True,
                last_full_replay=None,
                windows_since_full_replay=3,
            ),
        ),
    )
    return UpdatesView(
        baseline=BaselineView(
            snapshot_id="snp_1",
            cutoff_event="ev_1",
            recorded_at=WHEN,
            included_count=365,
            trigger="human",
        ),
        open_period=OpenPeriod(since_snapshot="snp_1", new_works=1, included_at_title_abstract=1),
        additions=(_row(title),),
        growth=(
            GrowthPoint(
                snapshot_id="snp_1",
                recorded_at=WHEN,
                included_count=365,
                identified=None,
                screened=None,
                included=None,
                identified_databases=None,
                identified_other=None,
            ),
        ),
        watch=watch,
    )


def test_renders_without_a_snapshot() -> None:
    view = UpdatesView(baseline=None, open_period=None, additions=(), growth=(), watch=NO_WATCH)
    html = render_updates(view, "demo", ("arxiv",))
    assert "No snapshot yet" in html
    assert "not configured" in html


def test_escapes_titles_notes_and_slug() -> None:
    html = render_updates(_view("<script>alert(1)</script>"), "x<y", ("arxiv",))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<b>note</b>" not in html
    assert "x<y" not in html


def test_buttons_start_disabled_and_no_external_resources() -> None:
    html = render_updates(_view(), "demo", ("arxiv", "openalex"))
    buttons = [b for b in html.split("<button")[1:] if "data-act=" in b.split(">")[0]]
    assert len(buttons) == 3
    assert all("disabled" in b.split(">")[0] for b in buttons)
    assert "http://" not in html.replace("http://www.w3.org", "")
    assert "https://" not in html


def test_full_rerun_is_never_a_button() -> None:
    html = render_updates(_view(), "demo", ("arxiv",))
    assert "A full re-run never happens automatically" in html
    assert "watch run --full-replay" in html
    assert "data-act=replay" not in html

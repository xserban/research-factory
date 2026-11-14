"""The warmer reads the feed views once at start and again on its interval, survives a failing
read, and stops with the hub."""

from __future__ import annotations

import threading
from pathlib import Path

from factory.services.site_server import MainHub


def _hub(tmp_path: Path) -> MainHub:
    return MainHub(
        tmp_path,
        lambda: [],
        lambda slug: (_ for _ in ()).throw(KeyError(slug)),
        min_gap=0.0,
        background=False,
    )


def test_reads_at_start_then_on_the_interval_and_stops(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    calls: list[int] = []
    again = threading.Event()

    def fake() -> list[object]:
        calls.append(1)
        if len(calls) >= 3:
            again.set()
        return []

    hub.feed_views = fake  # type: ignore[method-assign]
    hub._warm_every = 0.01
    hub.start_warmer()
    assert again.wait(5)
    hub.stop()
    n = len(calls)
    threading.Event().wait(0.1)
    assert len(calls) <= n + 1


def test_a_failing_read_does_not_stop_the_warmer(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    calls: list[int] = []
    done = threading.Event()

    def boom() -> list[object]:
        calls.append(1)
        if len(calls) >= 3:
            done.set()
        raise RuntimeError("read failed")

    hub.feed_views = boom  # type: ignore[method-assign]
    hub._warm_every = 0.01
    hub.start_warmer()
    assert done.wait(5)
    hub.stop()

"""Feed payload models (slice 4c, plan F1)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from factory.events.catalog import default_catalog
from factory.model.feed import FeedConfigured, FeedFetched, FeedRanked, FeedReacted, FeedSent

ULID = "01HZX3J8K9M2N4P5Q6R7S8T9V0"
BLOB = "sha256:" + "a" * 64
HEX = "b" * 64

CONFIG: dict[str, Any] = {"config_id": f"fdc_{ULID}", "categories": ["cs.LG", "stat.ML"]}
FETCH: dict[str, Any] = {
    "fetch_id": f"fdf_{ULID}",
    "categories": ["cs.LG"],
    "window_from": "2026-11-01",
    "window_to": "2026-11-02",
    "raw_blobs": [BLOB],
    "entries_blob": BLOB,
    "count": 10,
    "held_count": 1,
    "complete": True,
}
RANKED: dict[str, Any] = {
    "ranking_id": f"fdr_{ULID}",
    "fetch_ids": [f"fdf_{ULID}"],
    "reference_hash": HEX,
    "reference_count": 3,
    "model": "specter2",
    "weights_hash": HEX,
    "software": "torch 2.0",
    "parameters": {"shown_per_cycle": 30, "exploration_share": 0.1, "references": "core"},
    "exploration_seed": 7,
    "order_blob": BLOB,
    "shown": [
        {
            "entry_id": "2411.01234",
            "rank": 1,
            "score": 0.9,
            "explore": False,
            "nearest_reference": None,
        },
        {
            "entry_id": "hep-th/9901001",
            "rank": 2,
            "score": 0.1,
            "explore": True,
            "nearest_reference": None,
        },
    ],
}
REACTED: dict[str, Any] = {
    "entry_id": "2411.01234",
    "reaction": "like",
    "ranking_id": f"fdr_{ULID}",
    "rank_shown": 1,
    "score_shown": 0.9,
}
SENT: dict[str, Any] = {
    "entry_id": "2411.01234",
    "ranking_id": f"fdr_{ULID}",
    "inbox_item_id": f"inb_{ULID}",
    "note": "in scope",
}


@pytest.mark.parametrize(
    ("name", "model", "data"),
    [
        ("feed.configured", FeedConfigured, CONFIG),
        ("feed.fetched", FeedFetched, FETCH),
        ("feed.ranked", FeedRanked, RANKED),
        ("feed.reacted", FeedReacted, REACTED),
        ("feed.sent", FeedSent, SENT),
    ],
)
def test_round_trip_through_catalog(name: str, model: type, data: dict[str, Any]) -> None:
    event_type = default_catalog().get(name)
    assert event_type.payload is model
    assert event_type.schema == 1
    payload = event_type.payload.model_validate(data)
    again = event_type.payload.model_validate_json(payload.model_dump_json())
    assert again == payload


@pytest.mark.parametrize(
    "change",
    [
        {"categories": ["CS.lg!"]},
        {"categories": []},
        {"categories": ["cs.LG", "cs.LG"]},
        {"exploration_share": 1.0},
        {"shown_per_cycle": 0},
    ],
)
def test_invalid_config_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        FeedConfigured.model_validate({**CONFIG, **change})


def test_config_defaults() -> None:
    config = FeedConfigured.model_validate(CONFIG)
    assert (config.shown_per_cycle, config.exploration_share, config.interval_days) == (30, 0.1, 1)


def test_held_count_above_count_refused() -> None:
    with pytest.raises(ValidationError):
        FeedFetched.model_validate({**FETCH, "held_count": 11})


def test_window_reversed_refused() -> None:
    with pytest.raises(ValidationError):
        FeedFetched.model_validate({**FETCH, "window_from": "2026-11-03"})


def test_bad_entry_id_refused() -> None:
    with pytest.raises(ValidationError):
        FeedReacted.model_validate({**REACTED, "entry_id": "2411.01234v2"})

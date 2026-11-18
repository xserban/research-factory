"""The backward selection options of `SnowballPlan` (decision 135): bounds, and a plan that
leaves them unset dumps, and so hashes, as it did before they existed."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from factory.model.protocol import SnowballPlan

BASE = {"max_backward_rounds": 1, "max_forward_rounds": 1}


def test_unset_options_are_left_out_of_the_dump() -> None:
    plan = SnowballPlan(**BASE)
    assert plan.model_dump(mode="json") == {**BASE, "stop_when_no_new_included": True}


def test_set_options_are_dumped() -> None:
    plan = SnowballPlan(
        **BASE,
        backward_min_cited_by=2,
        backward_min_similarity=0.92,
        backward_published_from=date(2025, 1, 1),
    )
    dumped = plan.model_dump(mode="json")
    assert dumped["backward_min_cited_by"] == 2
    assert dumped["backward_min_similarity"] == 0.92
    assert dumped["backward_published_from"] == "2025-01-01"
    assert SnowballPlan.model_validate(dumped) == plan


@pytest.mark.parametrize(
    "bad",
    [
        {"backward_min_cited_by": 0},
        {"backward_min_similarity": 0},
        {"backward_min_similarity": 1.1},
    ],
)
def test_options_are_bounded(bad: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        SnowballPlan(**BASE, **bad)

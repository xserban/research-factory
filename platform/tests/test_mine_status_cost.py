"""`mine_status` reads the index once per call: one sync, then a read-only snapshot, inside one
memo scope (the pilot paid ~1,750 syncs and repeated folds per call)."""

# ruff: noqa: F811
from typing import Any

import pytest

from factory.events.envelope import Actor
from factory.index.index import Index
from factory.model.screening import PassLabel
from factory.services import agreement as agreement_service
from factory.services.context import Project
from factory.services.mining import mine_status
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_helpers import (
    SESSION_M1,
    SESSION_M2,
    list_miner,
    method_vision,
    mine_pass,
    mine_row,
    miner_actor,
)

A, B = PassLabel.A, PassLabel.B


@pytest.fixture
def mined(project: Project, agent: Actor, world: list[str]) -> Project:
    # No anchor field in the row key: the shared helper spec predates that validation rule.
    list_miner(project, agent, method_vision(row_anchor_fields=()))
    mine_pass(project, miner_actor(SESSION_M1, "claude-opus-5-5"), A, lambda w: [mine_row()])
    mine_pass(project, miner_actor(SESSION_M2, "claude-sonnet-5-5"), B, lambda w: [mine_row()])
    assert mine_status(project)[0].closed > 0  # the fixture mines: the reads below have work
    return project


def _counting(monkeypatch: pytest.MonkeyPatch, owner: Any, name: str) -> list[str]:
    """Patch `owner.name` to record each call (its keyword arguments, as text)."""
    calls: list[str] = []
    real = getattr(owner, name)

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append(repr(sorted(kwargs.items())))
        return real(*args, **kwargs)

    monkeypatch.setattr(owner, name, counted)
    return calls


def test_mine_status_syncs_the_index_once(mined: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = mine_status(mined)
    syncs = _counting(monkeypatch, Index, "_sync")
    assert mine_status(mined) == expected
    assert len(syncs) == 1


def test_mine_status_folds_each_stage_outcomes_once(
    mined: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = mine_status(mined)
    folds = _counting(monkeypatch, agreement_service.final_outcomes, "__wrapped__")
    assert mine_status(mined) == expected
    assert folds and len(folds) == len(set(folds))  # each stage's outcomes folded once


def test_mine_status_inside_a_write_hold_still_answers(mined: Project) -> None:
    expected = mine_status(mined)
    with mined.index.exclusive():
        assert mine_status(mined) == expected

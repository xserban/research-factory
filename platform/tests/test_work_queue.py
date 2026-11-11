"""The work queue (plan 2026-11-11-feed-hub, H4): the stage of each added paper, the pending counts
per task kind, and the empty queue.

Events are recorded directly, as the feed tests do. The stage reads (title/abstract outcomes,
full-text status, conversion, extraction, the stopping rule) are replaced by stubs held in one
dict, so each test states the state of its work and nothing else. The pending count is read from
real open tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.services import work_queue
from factory.services.agreement import Outcome
from factory.services.context import Project
from factory.services.fulltext_status import WorkFulltext
from factory.services.stages import task_kind
from factory.services.tasks import TaskSpec, create_tasks
from factory.services.work_queue import QueueItem, WorkQueue, queue
from tests.test_feed_index import _record
from tests.test_feed_read import FIRST, RANKING, SECOND, _fetch, _ranked
from tests.test_inbox_model import ITEM, WORK, added, resolved

SECOND_ITEM = "inb_01HZX3K4M5N6P7Q8R9S0TVWXY2"
OTHER_WORK = "rf:zhou2022-other-paper-5e6f7a8b"


@dataclass
class Reads:
    """The stubbed stage reads. Each test sets the state of its works here."""

    outcomes: dict[str, Outcome] = field(default_factory=dict)
    criteria: dict[str, str | None] = field(default_factory=dict)
    fulltext: list[WorkFulltext] = field(default_factory=list)
    eligible: list[str] = field(default_factory=list)
    extracted: list[str] = field(default_factory=list)
    stopped: set[str] = field(default_factory=set)


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> Reads:
    state = Reads()

    def final_outcomes(project: Project, **_: Any) -> dict[str, Outcome]:
        return dict(state.outcomes)

    def exclusion_criteria(project: Project, **_: Any) -> dict[str, str | None]:
        return dict(state.criteria)

    def fulltext_status(project: Project, **_: Any) -> Any:
        return type("Status", (), {"works": list(state.fulltext)})()

    def fulltext_queue(project: Project) -> Any:
        return type(
            "Queue",
            (),
            {"eligible": [type("E", (), {"work_id": w})() for w in state.eligible]},
        )()

    def unit_states(project: Project, **_: Any) -> list[Any]:
        return [
            type("U", (), {"work_id": w, "pass_label": PassLabel.A, "state": "current"})()
            for w in state.extracted
        ]

    def stop_unscreened(project: Project) -> set[str]:
        return set(state.stopped)

    monkeypatch.setattr(work_queue, "final_outcomes", final_outcomes)
    monkeypatch.setattr(work_queue, "exclusion_criteria", exclusion_criteria)
    monkeypatch.setattr(work_queue, "fulltext_status", fulltext_status)
    monkeypatch.setattr(work_queue, "fulltext_queue", fulltext_queue)
    monkeypatch.setattr(work_queue, "unit_states", unit_states)
    monkeypatch.setattr(work_queue, "stop_unscreened", stop_unscreened)
    return state


def _send(project: Project, entry: str, item: str) -> None:
    """Capture an inbox item for `entry` and record the feed send of it (a human's action)."""
    _record(project, "inbox.link_added", added(item_id=item), project.human_actor())
    payload = {"entry_id": entry, "ranking_id": RANKING, "inbox_item_id": item}
    _record(project, "feed.sent", payload, project.human_actor())


def _resolve(project: Project, item: str, status: str, work: str | None) -> None:
    payload = resolved(item_id=item, status=status, work_id=work)
    _record(project, "inbox.link_resolved", payload, project.system_actor())


@pytest.fixture
def world(project: Project) -> Project:
    _fetch(project)
    _ranked(project)
    return project


def _only(project: Project) -> QueueItem:
    [item] = queue(project).items
    return item


def test_empty_queue_has_no_items_and_no_pending_work(project: Project) -> None:
    work = queue(project)
    assert isinstance(work, WorkQueue)
    assert work.items == []
    assert all(count == 0 for count in work.pending.values())


def test_open_item_is_added_and_not_stopped(world: Project) -> None:
    _send(world, FIRST, ITEM)
    item = _only(world)
    assert item.stage == "added"
    assert item.stopped is False
    assert item.work_id is None
    assert item.title == "First paper"
    assert item.inbox_item_id == ITEM
    assert item.sent_at != ""


def test_failed_lookup_is_lookup_failed_and_stopped(world: Project) -> None:
    _send(world, FIRST, ITEM)
    _resolve(world, ITEM, "failed", None)
    item = _only(world)
    assert item.stage == "lookup-failed"
    assert item.stopped is True


def test_resolved_pending_work_is_in_corpus(world: Project, reads: Reads) -> None:
    _send(world, FIRST, ITEM)
    _resolve(world, ITEM, "new", WORK)
    reads.outcomes = {WORK: Outcome.PENDING}
    item = _only(world)
    assert item.stage == "in-corpus"
    assert item.work_id == WORK
    assert item.stopped is False


def test_pending_work_left_by_the_stopping_rule_is_stopped(world: Project, reads: Reads) -> None:
    _send(world, FIRST, ITEM)
    _resolve(world, ITEM, "new", WORK)
    reads.outcomes = {WORK: Outcome.PENDING}
    reads.stopped = {WORK}
    item = _only(world)
    assert item.stage == "in-corpus"
    assert item.stopped is True


def test_excluded_work_is_screened_out_with_its_criterion(world: Project, reads: Reads) -> None:
    _send(world, FIRST, ITEM)
    _resolve(world, ITEM, "in-corpus", WORK)
    reads.outcomes = {WORK: Outcome.EXCLUDED}
    reads.criteria = {WORK: "C2"}
    item = _only(world)
    assert item.stage == "screened-out"
    assert item.stopped is True
    assert "C2" in item.detail


def test_promoted_work_walks_the_full_text_stages(world: Project, reads: Reads) -> None:
    _send(world, FIRST, ITEM)
    _resolve(world, ITEM, "new", WORK)
    reads.outcomes = {WORK: Outcome.INCLUDED}
    reads.fulltext = [WorkFulltext(work_id=WORK, state="unsought", documents=[], reasons={})]
    assert _only(world).stage == "screened-in"

    reads.fulltext = [WorkFulltext(work_id=WORK, state="not-retrieved", documents=[], reasons={})]
    item = _only(world)
    assert item.stage == "no-document"
    assert item.stopped is True

    reads.fulltext = [WorkFulltext(work_id=WORK, state="retrieved", documents=["doc"], reasons={})]
    assert _only(world).stage == "full-text"

    reads.eligible = [WORK]
    assert _only(world).stage == "converted"

    reads.extracted = [WORK]
    assert _only(world).stage == "extracted"


def test_items_are_listed_newest_first(world: Project) -> None:
    _send(world, FIRST, ITEM)
    _send(world, SECOND, SECOND_ITEM)
    assert [item.entry_id for item in queue(world).items] == [SECOND, FIRST]


def test_pending_work_counts_open_tasks_per_kind(project: Project) -> None:
    kind = task_kind(ScreeningStage.TITLE_ABSTRACT, PassLabel.A)
    create_tasks(project, project.system_actor(), [TaskSpec(kind, {"n": 1})])
    create_tasks(project, project.system_actor(), [TaskSpec(kind, {"n": 2})])
    pending = queue(project).pending
    assert pending[kind] == 2
    assert all(count == 0 for key, count in pending.items() if key != kind)


def test_other_work_ids_are_not_confused_with_the_resolved_one(
    world: Project, reads: Reads
) -> None:
    _send(world, FIRST, ITEM)
    _send(world, SECOND, SECOND_ITEM)
    _resolve(world, ITEM, "new", WORK)
    _resolve(world, SECOND_ITEM, "new", OTHER_WORK)
    reads.outcomes = {WORK: Outcome.EXCLUDED, OTHER_WORK: Outcome.PENDING}
    reads.criteria = {WORK: "C1"}
    stages = {item.entry_id: item.stage for item in queue(world).items}
    assert stages == {FIRST: "screened-out", SECOND: "in-corpus"}


def test_withdrawn_item_is_added_and_stopped(world: Project) -> None:
    _send(world, FIRST, ITEM)
    _record(
        world, "inbox.link_withdrawn", {"item_id": ITEM, "reason": "duplicate"}, world.human_actor()
    )
    item = _only(world)
    assert item.stage == "added"
    assert item.stopped is True

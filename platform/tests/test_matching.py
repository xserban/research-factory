"""The matching builder with the transfer flag (slice 6, plan H-B, task 2; acceptance 5)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, event

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.services.cards import AssertionInput, assert_properties, create_card, decide_assertion
from factory.services.context import Project
from factory.services.matching import match
from factory.services.properties import decide_property, propose_property
from tests.card_helpers import approve, cw, prop
from tests.finder_helpers import MatchWorld, full_items, item, mw
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world


def test_expected_sets_and_order(project: Project, mw: MatchWorld) -> None:  # acceptance 5
    page = match(project, mw.problem)
    assert [r.card_id for r in page.rows] == [mw.ok, mw.transfer, mw.unknown, mw.conflict]
    by_card = {r.card_id: r for r in page.rows}
    assert by_card[mw.conflict].conflicting == ["pr:memory-scaling"]
    assert sorted(by_card[mw.conflict].satisfied) == ["pr:dense", "pr:params", "pr:tasks"]
    assert by_card[mw.unknown].unknown == ["pr:dense"]
    assert by_card[mw.unknown].conflicting == []
    assert by_card[mw.ok].satisfied == ["pr:dense", "pr:memory-scaling", "pr:params", "pr:tasks"]
    assert page.statuses == ["stated", "confirmed"]
    assert page.problem_id == mw.problem
    assert page.candidates == 4
    assert mw.noprop not in by_card
    assert page.vocabulary_version.startswith("V@")


def test_inferred_excluded_by_default(project: Project, mw: MatchWorld) -> None:
    assert mw.inferred not in [r.card_id for r in match(project, mw.problem).rows]
    page = match(project, mw.problem, include_inferred=True)
    assert mw.inferred in [r.card_id for r in page.rows]
    assert page.statuses == ["stated", "confirmed", "inferred"]


def test_confirmed_inferred_feeds_default(
    project: Project, mw: MatchWorld, other_session_human: Actor
) -> None:
    for aid in mw.assertions[mw.inferred].values():
        decide_assertion(project, other_session_human, aid, "confirm", "checked")
    assert mw.inferred in [r.card_id for r in match(project, mw.problem).rows]


def test_rejected_and_stale_assertions_do_not_feed(
    project: Project,
    agent: Actor,
    mw: MatchWorld,
    other_session_human: Actor,
) -> None:
    decide_assertion(
        project, other_session_human, mw.assertions[mw.ok]["pr:dense"], "reject", "wrong"
    )
    first = {r.card_id: r for r in match(project, mw.problem).rows}
    assert first[mw.ok].unknown == ["pr:dense"]
    # A superseding definition of pr:params makes every assertion on it stale.
    changed = prop(
        "pr:params",
        kind="number",
        allowed=[],
        unit_family="count",
        match="at-most",
        applies_to="both",
        value_aliases={},
        aliases=["parameters"],
    )
    propose_property(project, agent, changed, supersedes="pr:params")
    decide_property(project, other_session_human, "pr:params", "approve", "alias added")
    second = {r.card_id: r for r in match(project, mw.problem).rows}
    assert "pr:params" not in second[mw.ok].satisfied
    assert "pr:params" not in second[mw.ok].unknown + second[mw.ok].conflicting
    # the problem's own stale params assertion is no longer required either
    assert second[mw.ok].satisfied == ["pr:memory-scaling", "pr:tasks"]


def test_transfer_flag_from_included_members(project: Project, mw: MatchWorld) -> None:
    by_card = {r.card_id: r for r in match(project, mw.problem).rows}
    assert by_card[mw.ok].transfer is False
    assert by_card[mw.ok].members_included == [by_card[mw.ok].subject]
    assert by_card[mw.transfer].transfer is True
    assert by_card[mw.transfer].members_included == []
    only = match(project, mw.problem, transfer_only=True)
    assert [r.card_id for r in only.rows] == [mw.transfer]


def test_idea_card_transfer_follows_effective_members(
    project: Project, agent: Actor, human: Actor, mw: MatchWorld
) -> None:
    card = create_card(project, agent, "method", mw.cw.idea, "obd")
    result = assert_properties(project, human, card, full_items())
    assert result.rejected == []
    row = next(r for r in match(project, mw.problem).rows if r.card_id == card)
    assert row.transfer is False  # the idea's member is the included source work
    assert mw.cw.source in row.members_included


def test_match_key_changes_when_assertion_superseded(
    project: Project, human: Actor, mw: MatchWorld
) -> None:
    before = match(project, mw.problem)
    assert match(project, mw.problem).match_key == before.match_key
    assert_properties(project, human, mw.ok, [item("pr:params", "60", "M")])
    after = match(project, mw.problem)
    assert after.match_key != before.match_key
    keys = {r.row_key for r in before.rows} & {r.row_key for r in after.rows}
    assert keys == set()


def test_query_touches_only_candidates(project: Project, mw: MatchWorld) -> None:  # Review Focus 1
    seen: list[str] = []

    def spy(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: Any
    ) -> None:
        seen.append(f"{statement} {parameters}")

    event.listen(Engine, "before_cursor_execute", spy)
    try:
        page = match(project, mw.problem)
    finally:
        event.remove(Engine, "before_cursor_execute", spy)
    assert len(page.rows) == 4
    joined = "\n".join(seen)
    assert mw.noprop not in joined  # a card with no required assertion is never named
    # assertions are read only for a batch of named candidate cards or for the problem
    assert all("card_assertions" not in s or "p.card_id IN" in s for s in seen)


def test_paging_is_stable(project: Project, mw: MatchWorld) -> None:
    full = [r.card_id for r in match(project, mw.problem).rows]
    pages: list[list[str]] = []
    after = None
    while True:
        page = match(project, mw.problem, limit=2, after=after)
        pages.append([r.card_id for r in page.rows])
        assert page.match_key == match(project, mw.problem).match_key
        if page.next_after is None:
            break
        after = page.next_after
    assert [c for p in pages for c in p] == full
    assert [len(p) for p in pages] == [2, 2]


def test_unknown_cursor_refused(project: Project, mw: MatchWorld) -> None:
    with pytest.raises(FactoryValidationError) as e:
        match(project, mw.problem, after="mcd_nope")
    assert e.value.issues[0].field == "after"


def test_problem_card_required(project: Project, mw: MatchWorld) -> None:
    for bad in (mw.ok, "pbd_00000000000000000000000000"):
        with pytest.raises(FactoryValidationError) as e:
            match(project, bad)
        assert e.value.issues[0].field == "problem_id"

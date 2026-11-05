"""Ideas: proposal, definition, decision, reversible merge and candidates (plan G2-C, task 5)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.lineage import LineageDecision, RelationProposal
from factory.services import seeds
from factory.services.context import Project
from factory.services.ideas import (
    IdeaCandidate,
    decide_idea,
    idea_candidates,
    idea_view,
    list_ideas,
    merge_ideas,
    propose_idea,
    resolve_idea,
    unmerge_idea,
)
from factory.services.relations import decide_relation, propose_relation
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world

NAME = "Linear attention"


@pytest.fixture
def decider(other_session_human: Actor) -> Actor:
    return other_session_human


def _events(project: Project) -> list[Any]:
    return read_all(project.paths.events_dir, project.catalog)


def _refused(project: Project, field: str, reason: str, call: Callable[[], object]) -> None:
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        call()
    assert (e.value.issues[0].field, e.value.issues[0].reason) == (field, reason)
    assert len(_events(project)) == before


def _two_ideas(project: Project, agent: Actor, lin: Lineage, world: list[str]) -> tuple[str, str]:
    other = next(w for w in world if w != lin.source)
    a = propose_idea(project, agent, NAME, lin.source, lin.base, [lin.source])
    b = propose_idea(project, agent, "linear attention", lin.source, lin.base, [lin.source, other])
    return a, b


def test_agent_proposes_idea_with_sorted_members(
    project: Project, agent: Actor, lin: Lineage, world: list[str]
) -> None:
    other = next(w for w in world if w != lin.source)
    idea = propose_idea(project, agent, NAME, lin.source, lin.base, [other, lin.source])
    view = idea_view(project, idea)
    assert view is not None
    assert view.members == tuple(sorted([lin.source, other])) and view.state == "proposed"
    [event] = [e for e in _events(project) if e.type == "idea.proposed"]
    assert event.actor.model and event.input_blob


def test_name_must_be_in_verified_quote(project: Project, agent: Actor, lin: Lineage) -> None:
    _refused(
        project,
        "name",
        "name-not-in-quote",
        lambda: propose_idea(
            project, agent, "Gated Linear Attention", lin.source, lin.base, [lin.source]
        ),
    )


def test_human_define_needs_quote_too(project: Project, human: Actor, lin: Lineage) -> None:
    _refused(
        project,
        "name",
        "name-not-in-quote",
        lambda: propose_idea(project, human, "Gated", lin.source, lin.base, [lin.source]),
    )
    assert propose_idea(project, human, NAME, lin.source, lin.base, [lin.source])


def test_name_item_must_be_a_live_final_item_of_the_origin(
    project: Project, agent: Actor, lin: Lineage, world: list[str]
) -> None:
    other = next(w for w in world if w != lin.source)
    _refused(
        project,
        "name_item",
        "name-item-unknown",
        lambda: propose_idea(
            project, agent, NAME, lin.source, "ext_01M68X9EG06809NC9ZQF9CAZZ0", [lin.source]
        ),
    )
    _refused(
        project,
        "name_item",
        "name-item-other-work",
        lambda: propose_idea(project, agent, NAME, other, lin.base, [other]),
    )


def test_members_validated(project: Project, agent: Actor, lin: Lineage) -> None:
    _refused(
        project,
        "members",
        "must-include-origin",
        lambda: propose_idea(project, agent, NAME, lin.source, lin.base, [lin.target5]),
    )
    _refused(
        project,
        "members",
        "duplicate-member",
        lambda: propose_idea(
            project, agent, NAME, lin.source, lin.base, [lin.source, lin.source, lin.target5]
        ),
    )
    _refused(
        project,
        "members",
        "unknown-work",
        lambda: propose_idea(
            project, agent, NAME, lin.source, lin.base, [lin.source, "rf:nobody-00000000"]
        ),
    )
    ok = propose_idea(project, agent, NAME, lin.source, lin.base, [lin.source, lin.target5])
    assert ok


def test_unconfirmed_idea_not_listed_by_default(
    project: Project, agent: Actor, decider: Actor, lin: Lineage
) -> None:
    idea = propose_idea(project, agent, NAME, lin.source, lin.base, [lin.source])
    assert list_ideas(project) == []
    assert [i.idea_id for i in list_ideas(project, include_unconfirmed=True)] == [idea]
    decide_idea(project, decider, idea, LineageDecision.CONFIRM, "the method is named there")
    [view] = list_ideas(project)
    assert (view.idea_id, view.state) == (idea, "confirmed")
    decide_idea(project, decider, idea, LineageDecision.REJECT, "changed my mind")
    assert list_ideas(project) == [] and list_ideas(project, include_unconfirmed=True) == []
    rejected = idea_view(project, idea)
    assert rejected is not None and rejected.state == "rejected"


def test_agent_cannot_confirm_merge_or_unmerge(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, lin: Lineage, world: list[str]
) -> None:
    a, b = _two_ideas(project, agent, lin, world)
    for call in (
        lambda: decide_idea(project, agent_other, a, LineageDecision.CONFIRM, "x"),
        lambda: merge_ideas(project, agent_other, a, b, "same"),
        lambda: unmerge_idea(project, agent_other, a, "x"),
    ):
        _refused(project, "actor", "only a human decides an idea", call)


def test_proposing_session_cannot_decide_even_as_human(
    project: Project, agent: Actor, human: Actor, lin: Lineage
) -> None:
    idea = propose_idea(project, agent, NAME, lin.source, lin.base, [lin.source])
    assert human.session == agent.session
    _refused(
        project,
        "actor",
        "the session that proposed an idea cannot decide it",
        lambda: decide_idea(project, human, idea, LineageDecision.CONFIRM, "x"),
    )


def test_merge_and_unmerge_restore_views_exactly(
    project: Project, agent: Actor, decider: Actor, lin: Lineage, world: list[str]
) -> None:
    a, b = _two_ideas(project, agent, lin, world)
    for i in (a, b):
        decide_idea(project, decider, i, LineageDecision.CONFIRM, "ok")
    before = list_ideas(project)
    view_b = idea_view(project, b)
    merge_ideas(project, decider, a, b, "same method, two names")
    assert [i.idea_id for i in list_ideas(project)] == [b]
    merged_b = idea_view(project, b)
    assert merged_b is not None and view_b is not None
    assert set(merged_b.effective_members) == set(merged_b.members) | set(
        (idea_view(project, a) or merged_b).members
    )
    a_view = idea_view(project, a)
    assert a_view is not None and (a_view.state, a_view.merged_into) == ("merged", b)
    unmerge_idea(project, decider, a, "split again")
    assert list_ideas(project) == before


def test_chained_merge_and_cycle(  # Review Focus 4
    project: Project, agent: Actor, decider: Actor, lin: Lineage, world: list[str]
) -> None:
    others = [w for w in world if w != lin.source]
    ideas = [
        propose_idea(project, agent, NAME, lin.source, lin.base, sorted([lin.source, w]))
        for w in others[:3]
    ]
    a, b, c = ideas
    merge_ideas(project, decider, a, b, "one")
    merge_ideas(project, decider, b, c, "two")
    assert resolve_idea(project, a) == c and resolve_idea(project, c) == c
    effective = idea_view(project, c)
    assert effective is not None
    every = set().union(*(set(idea_view(project, i).members) for i in ideas))  # type: ignore[union-attr]
    assert set(effective.effective_members) == every
    unmerge_idea(project, decider, a, "undo")
    assert resolve_idea(project, a) == a and resolve_idea(project, b) == c
    c_view = idea_view(project, c)
    assert c_view is not None
    unique_a = set(idea_view(project, a).members) - {lin.source}  # type: ignore[union-attr]
    assert unique_a and not unique_a & set(c_view.effective_members)  # A's members left with A
    assert {w for w in idea_view(project, b).members} <= set(c_view.effective_members)  # type: ignore[union-attr]
    merge_ideas(project, decider, c, a, "other way")
    _refused(
        project,
        "into",
        "merge-cycle",
        lambda: merge_ideas(project, decider, a, c, "cycle"),
    )


def test_merge_refusals(
    project: Project, agent: Actor, decider: Actor, lin: Lineage, world: list[str]
) -> None:
    a, b = _two_ideas(project, agent, lin, world)
    _refused(
        project,
        "from_idea",
        "unknown-idea",
        lambda: merge_ideas(project, decider, "ida_01M68X9EG06809NC9ZQF9CAZZ0", b, "x"),
    )
    _refused(
        project, "reason", "state the reason", lambda: merge_ideas(project, decider, a, b, " ")
    )
    decide_idea(project, decider, b, LineageDecision.REJECT, "no")
    _refused(project, "into", "idea-not-live", lambda: merge_ideas(project, decider, a, b, "x"))
    _refused(project, "from_idea", "not-merged", lambda: unmerge_idea(project, decider, a, "x"))
    c = propose_idea(project, agent, NAME, lin.source, lin.base, [lin.source, lin.target5])
    merge_ideas(project, decider, a, c, "ok")
    _refused(
        project, "from_idea", "already-merged", lambda: merge_ideas(project, decider, a, c, "again")
    )


def test_superseding_proposal_replaces_members(
    project: Project, agent: Actor, decider: Actor, lin: Lineage
) -> None:
    first = propose_idea(project, agent, NAME, lin.source, lin.base, [lin.source])
    decide_idea(project, decider, first, LineageDecision.CONFIRM, "ok")
    second = propose_idea(
        project, agent, NAME, lin.source, lin.base, [lin.source, lin.target5], supersedes=first
    )
    old = idea_view(project, first)
    assert old is not None and old.state == "superseded"
    new = idea_view(project, second)
    assert new is not None and new.members == tuple(sorted([lin.source, lin.target5]))
    assert new.state == "proposed"  # the decision does not carry over
    _refused(
        project,
        "supersedes",
        "idea-not-live",
        lambda: propose_idea(
            project, agent, NAME, lin.source, lin.base, [lin.source], supersedes=first
        ),
    )


def test_candidates_from_names_and_builds_on(
    project: Project, agent: Actor, lin: Lineage, world: list[str]
) -> None:
    # The source work's items name "linear attention"; a stated builds-on relation names the origin.
    other = next(w for w in world if w != lin.source)
    rel = propose_relation(
        project,
        agent,
        RelationProposal(
            source_work=lin.source, target=lin.target5, edge_type="builds-on", basis_item=lin.base
        ),
    )
    assert rel.status == "stated"
    got = idea_candidates(project, lin.target5, "Linear Attention")
    assert [c for c in got if c.work_id == lin.source] == [
        IdeaCandidate(work_id=lin.source, reasons=("builds-on-origin", "name-in-item"))
    ]
    assert other not in {c.work_id for c in got}
    assert [c.work_id for c in got] == sorted(c.work_id for c in got)


def test_merge_target_cannot_be_rejected_or_superseded_while_the_merge_stands(
    project: Project, agent: Actor, decider: Actor, lin: Lineage, world: list[str]
) -> None:
    a, b = _two_ideas(project, agent, lin, world)
    for i in (a, b):
        decide_idea(project, decider, i, LineageDecision.CONFIRM, "ok")
    merge_ideas(project, decider, a, b, "same")
    _refused(
        project,
        "idea_id",
        "merge-target",
        lambda: decide_idea(project, decider, b, LineageDecision.REJECT, "no"),
    )
    _refused(
        project,
        "supersedes",
        "merge-target",
        lambda: propose_idea(
            project, agent, NAME, lin.source, lin.base, [lin.source], supersedes=b
        ),
    )
    decide_idea(project, decider, b, LineageDecision.CONFIRM, "still fine")  # not hidden
    unmerge_idea(project, decider, a, "undo")
    decide_idea(project, decider, b, LineageDecision.REJECT, "no")
    assert [i.idea_id for i in list_ideas(project)] == [a]

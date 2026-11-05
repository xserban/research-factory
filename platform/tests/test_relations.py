"""Relation proposals, classification and human decisions (slice 3b, plan G2-C, task 3)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.lineage import IdeaProposed, LineageDecision, RelationProposal
from factory.model.seed import HeldOut
from factory.services import seeds
from factory.services.context import Project
from factory.services.relations import decide_relation, propose_relation
from tests.lineage_helpers import Lineage, ctr_a, lin, screened, world
from tests.lineage_payloads import IDA


def prop(
    lin: Lineage,
    target: str,
    *,
    basis: str | None,
    edge: str = "builds-on",
    note: str | None = None,
    source: str | None = None,
) -> RelationProposal:
    return RelationProposal(
        source_work=source or lin.source,
        target=target,
        edge_type=edge,  # type: ignore[arg-type]
        basis_item=basis,
        note=note,
    )


def _events(project: Project) -> list[Any]:
    return read_all(project.paths.events_dir, project.catalog)


def _types(project: Project) -> list[str]:
    return [e.type for e in _events(project)]


def _refused(project: Project, field: str, reason: str, call: Callable[[], object]) -> None:
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        call()
    assert (e.value.issues[0].field, e.value.issues[0].reason) == (field, reason)
    assert len(_events(project)) == before


def _other(project: Project, world: list[str], lin: Lineage) -> str:
    """An included work other than the source that an agent may see (not a held-out seed)."""
    hidden = seeds.held_out(project).work_ids
    return next(w for w in world if w != lin.source and w not in hidden)


@pytest.fixture
def decider(other_session_human: Actor) -> Actor:
    return other_session_human


def test_stated_when_cited_entry_resolves_to_target(  # acceptance 8
    project: Project, agent: Actor, lin: Lineage
) -> None:
    r = propose_relation(project, agent, prop(lin, lin.target5, basis=lin.base))
    assert (r.status, r.status_reason, r.written) == ("stated", None, True)
    [event] = [e for e in _events(project) if e.type == "relation.proposed"]
    assert event.payload["reference_extraction_id"] == lin.rex
    assert event.payload["cited_entry"] == 5 and event.payload["classifier"] == "1"


def test_inferred_when_target_differs_link_unresolved_or_no_basis(
    project: Project, agent: Actor, lin: Lineage
) -> None:
    differs = propose_relation(project, agent, prop(lin, lin.target3, basis=lin.base))
    assert (differs.status, differs.status_reason) == ("inferred", "target-differs")
    no_cite = propose_relation(project, agent, prop(lin, lin.target5, basis=lin.uncited_base))
    assert (no_cite.status, no_cite.status_reason) == ("inferred", "no-cited-entry")
    no_basis = propose_relation(project, agent, prop(lin, lin.target5, basis=None, note="abstract"))
    assert (no_basis.status, no_basis.status_reason) == ("inferred", "no-basis")


def test_improves_on_from_addition_is_stated(project: Project, agent: Actor, lin: Lineage) -> None:
    r = propose_relation(
        project, agent, prop(lin, lin.target3, basis=lin.addition, edge="improves-on")
    )
    assert r.status == "stated"


def test_uncited_base_flag(project: Project, agent: Actor, lin: Lineage, world: list[str]) -> None:
    other = _other(project, world, lin)
    r = propose_relation(project, agent, prop(lin, other, basis=lin.base))
    assert (r.status, r.status_reason, r.flags) == ("inferred", "target-differs", ("uncited-base",))
    _refused(
        project,
        "target",
        "target-unknown",
        lambda: propose_relation(
            project, agent, prop(lin, "rf:nobody2001-unrelated-00000000", basis=lin.base)
        ),
    )
    cited = propose_relation(project, agent, prop(lin, lin.target5, basis=lin.base))
    assert cited.flags == ()


def test_no_basis_needs_note(project: Project, agent: Actor, lin: Lineage) -> None:
    _refused(
        project,
        "note",
        "note-required-without-basis",
        lambda: propose_relation(project, agent, prop(lin, lin.target5, basis=None)),
    )
    _refused(
        project,
        "note",
        "note-required-without-basis",
        lambda: propose_relation(project, agent, prop(lin, lin.target5, basis=None, note="  ")),
    )


def test_idea_target_needs_live_basis_and_is_inferred(
    project: Project, agent: Actor, lin: Lineage, decider: Actor
) -> None:  # ruling 2
    idea = "ida_01M68X9EG06809NC9ZQF9CAZZ0"
    payload = IdeaProposed(
        idea_id=idea, name="linear attention", name_item=lin.base, origin=lin.source,
        members=(lin.source,),
    )  # fmt: skip
    project.record([project.events.make("idea.proposed", payload, project.human_actor())])
    _refused(
        project,
        "basis_item",
        "basis-required-for-idea",
        lambda: propose_relation(project, agent, prop(lin, idea, basis=None, note="n")),
    )
    r = propose_relation(project, agent, prop(lin, idea, basis=lin.base))
    assert (r.status, r.status_reason) == ("inferred", "target-differs")


def test_unknown_idea_target_refused(project: Project, agent: Actor, lin: Lineage) -> None:
    _refused(
        project,
        "target",
        "target-unknown",
        lambda: propose_relation(project, agent, prop(lin, IDA, basis=lin.base)),
    )


def test_basis_must_be_live_base_or_addition_of_source(
    project: Project, agent: Actor, lin: Lineage, world: list[str]
) -> None:
    def refuse(basis: str, reason: str) -> None:
        _refused(
            project,
            "basis_item",
            reason,
            lambda: propose_relation(project, agent, prop(lin, lin.target5, basis=basis)),
        )

    refuse("ext_01M68X9EG06809NC9ZQF9CAZZ0", "basis-unknown")
    refuse(lin.limitation, "basis-kind")
    other_source = _other(project, world, lin)
    _refused(
        project,
        "source_work",
        "not-in-population",
        lambda: propose_relation(
            project, agent, prop(lin, lin.target5, basis=lin.base, source="rf:nobody-00000000")
        ),
    )
    _refused(
        project,
        "basis_item",
        "basis-other-work",
        lambda: propose_relation(
            project, agent, prop(lin, lin.target5, basis=lin.base, source=other_source)
        ),
    )


def test_idempotent_same_basis(project: Project, agent: Actor, lin: Lineage) -> None:
    first = propose_relation(project, agent, prop(lin, lin.target5, basis=lin.base))
    before = len(_events(project))
    again = propose_relation(project, agent, prop(lin, lin.target5, basis=lin.base))
    assert again.relation_id == first.relation_id and not again.written
    assert len(_events(project)) == before


def test_new_basis_supersedes_and_drops_decision(
    project: Project, agent: Actor, lin: Lineage, decider: Actor
) -> None:
    first = propose_relation(project, agent, prop(lin, lin.target3, basis=lin.base))  # inferred
    decide_relation(project, decider, first.relation_id, LineageDecision.CONFIRM, "ok")
    second = propose_relation(project, agent, prop(lin, lin.target3, basis=lin.addition))
    assert second.written and second.relation_id != first.relation_id
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT relation_id, superseded_by, decision FROM relations ORDER BY event_id")
        ).all()
    assert [tuple(r) for r in rows] == [
        (first.relation_id, second.relation_id, "confirm"),
        (second.relation_id, None, None),
    ]


def test_rejected_triple_cannot_be_reproposed(  # Review Focus 2
    project: Project, agent: Actor, lin: Lineage, decider: Actor
) -> None:
    first = propose_relation(project, agent, prop(lin, lin.target3, basis=lin.base))
    decide_relation(project, decider, first.relation_id, LineageDecision.REJECT, "wrong")
    _refused(
        project,
        "target",
        "rejected-by-human",
        lambda: propose_relation(project, agent, prop(lin, lin.target3, basis=lin.addition)),
    )


def test_agent_cannot_decide(  # acceptance 9
    project: Project, agent: Actor, agent_other: Actor, lin: Lineage
) -> None:
    rid = propose_relation(project, agent, prop(lin, lin.target3, basis=lin.base)).relation_id
    _refused(
        project,
        "actor",
        "only a human decides a relation",
        lambda: decide_relation(project, agent_other, rid, LineageDecision.CONFIRM, "x"),
    )


def test_proposing_session_cannot_decide_even_as_human(
    project: Project, agent: Actor, human: Actor, lin: Lineage
) -> None:  # proposer != evaluator, relay included
    rid = propose_relation(project, agent, prop(lin, lin.target3, basis=lin.base)).relation_id
    assert human.session == agent.session
    _refused(
        project,
        "actor",
        "the session that proposed a relation cannot decide it",
        lambda: decide_relation(project, human, rid, LineageDecision.CONFIRM, "x"),
    )


def test_confirm_only_inferred_reject_any(
    project: Project, agent: Actor, lin: Lineage, decider: Actor
) -> None:
    stated = propose_relation(project, agent, prop(lin, lin.target5, basis=lin.base))
    _refused(
        project,
        "decision",
        "only an inferred relation is confirmed",
        lambda: decide_relation(project, decider, stated.relation_id, LineageDecision.CONFIRM, "x"),
    )
    decide_relation(project, decider, stated.relation_id, LineageDecision.REJECT, "no")
    _refused(
        project,
        "relation_id",
        "unknown-relation",
        lambda: decide_relation(
            project, decider, "rel_01M68X9EG06809NC9ZQF9CAZZ0", LineageDecision.REJECT, "x"
        ),
    )
    _refused(
        project,
        "rationale",
        "state the reason for the decision",
        lambda: decide_relation(project, decider, stated.relation_id, LineageDecision.REJECT, " "),
    )


def test_reject_after_confirm_supersedes(
    project: Project, agent: Actor, lin: Lineage, decider: Actor
) -> None:
    rid = propose_relation(project, agent, prop(lin, lin.target3, basis=lin.base)).relation_id
    decide_relation(project, decider, rid, LineageDecision.CONFIRM, "ok")
    last = decide_relation(project, decider, rid, LineageDecision.REJECT, "changed my mind")
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(text("SELECT decision, decision_event_id FROM relations")).one()
    assert tuple(row) == ("reject", last)


def test_cannot_decide_superseded_relation(
    project: Project, agent: Actor, lin: Lineage, decider: Actor
) -> None:
    first = propose_relation(project, agent, prop(lin, lin.target3, basis=lin.base))
    propose_relation(project, agent, prop(lin, lin.target3, basis=lin.addition))
    _refused(
        project,
        "relation_id",
        "superseded-relation",
        lambda: decide_relation(project, decider, first.relation_id, LineageDecision.CONFIRM, "x"),
    )


def test_event_provenance(project: Project, agent: Actor, lin: Lineage, decider: Actor) -> None:
    r = propose_relation(project, agent, prop(lin, lin.target3, basis=lin.base))
    decide_relation(project, decider, r.relation_id, LineageDecision.CONFIRM, "ok")
    proposed, decided = [e for e in _events(project) if e.type.startswith("relation.")]
    assert proposed.actor.model and proposed.actor.skill and proposed.input_blob
    assert decided.actor.kind == "human" and decided.input_blob is None
    assert proposed.payload["classifier"] == "1"


def test_held_out_target_looks_unknown_to_an_agent(
    project: Project, agent: Actor, lin: Lineage, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services import relations

    monkeypatch.setattr(
        relations.seeds, "held_out", lambda _p: HeldOut(work_ids=frozenset({lin.target5}))
    )
    _refused(
        project,
        "target",
        "target-unknown",
        lambda: propose_relation(project, agent, prop(lin, lin.target5, basis=lin.base)),
    )

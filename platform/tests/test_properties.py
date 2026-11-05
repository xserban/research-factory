"""The property vocabulary service and `V@` (slice 6, plan H-A, task 2)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.services.context import Project
from factory.services.properties import (
    decide_property,
    list_properties,
    merge_properties,
    propose_property,
    resolve_property,
    unmerge_property,
    vocabulary_version,
)
from tests.card_helpers import approve, prop


def _events(project: Project) -> list[Any]:
    return read_all(project.paths.events_dir, project.catalog)


def _refused(project: Project, field: str, reason: str, call: Callable[[], object]) -> None:
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        call()
    assert (e.value.issues[0].field, e.value.issues[0].reason) == (field, reason)
    assert len(_events(project)) == before


def test_agent_proposal_is_unapproved(project: Project, agent: Actor) -> None:
    key = propose_property(project, agent, prop())
    assert key == "pr:sampling"
    assert resolve_property(project, key) is None
    assert list_properties(project) == []
    [view] = list_properties(project, include_proposed=True)
    assert view.state == "proposed"
    [event] = [e for e in _events(project) if e.type == "vocabulary.property_proposed"]
    assert event.actor.model and event.input_blob  # provenance (R-04)
    assert vocabulary_version(project) == "V@00000000"


def test_human_only_decides(
    project: Project, agent: Actor, agent_other: Actor, other_session_human: Actor
) -> None:
    propose_property(project, agent, prop())
    _refused(
        project,
        "actor",
        "human-only",
        lambda: decide_property(project, agent_other, "pr:sampling", "approve", "ok"),
    )
    # proposer != evaluator: the proposing session cannot decide, even as a human
    same_session = Actor(kind="human", id="obd", user="obd", session=agent.session)
    _refused(
        project,
        "actor",
        "proposer-session",
        lambda: decide_property(project, same_session, "pr:sampling", "approve", "ok"),
    )
    decide_property(project, other_session_human, "pr:sampling", "approve", "ok")
    assert resolve_property(project, "pr:sampling") == prop()


def test_decide_unknown_and_blank_rationale(
    project: Project, agent: Actor, other_session_human: Actor
) -> None:
    _refused(
        project,
        "key",
        "nothing-to-decide",
        lambda: decide_property(project, other_session_human, "pr:sampling", "approve", "ok"),
    )
    propose_property(project, agent, prop())
    _refused(
        project,
        "rationale",
        "state the reason for the decision",
        lambda: decide_property(project, other_session_human, "pr:sampling", "approve", " "),
    )


def test_v_hash_ignores_description(
    project: Project, agent: Actor, other_session_human: Actor
) -> None:  # acceptance 1
    approve(project, agent, other_session_human, prop(description="first wording"))
    first = vocabulary_version(project)
    assert first.startswith("V@") and first != "V@00000000"
    propose_property(project, agent, prop(description="reworded"), supersedes="pr:sampling")
    decide_property(project, other_session_human, "pr:sampling", "approve", "reworded only")
    assert vocabulary_version(project) == first


def test_v_hash_changes_with_allowed(
    project: Project, agent: Actor, other_session_human: Actor
) -> None:
    approve(project, agent, other_session_human, prop())
    first = vocabulary_version(project)
    changed = prop(allowed=["regular", "irregular", "gridded"])
    propose_property(project, agent, changed, supersedes="pr:sampling")
    assert vocabulary_version(project) == first  # unapproved proposals are not live
    decide_property(project, other_session_human, "pr:sampling", "approve", "adds gridded")
    assert vocabulary_version(project) != first
    assert resolve_property(project, "pr:sampling") == changed


def test_empty_vocabulary_hash(project: Project) -> None:
    assert vocabulary_version(project) == "V@00000000"


def test_key_exists_unless_superseded(
    project: Project, agent: Actor, other_session_human: Actor
) -> None:
    approve(project, agent, other_session_human, prop())
    _refused(project, "key", "exists", lambda: propose_property(project, agent, prop()))
    _refused(
        project,
        "supersedes",
        "unknown",
        lambda: propose_property(project, agent, prop("pr:other-key"), supersedes="pr:other-key"),
    )
    propose_property(project, agent, prop(), supersedes="pr:sampling")
    _refused(
        project,
        "key",
        "pending",
        lambda: propose_property(project, agent, prop(), supersedes="pr:sampling"),
    )


def test_superseding_definition_replaces_live(
    project: Project, agent: Actor, other_session_human: Actor
) -> None:
    approve(project, agent, other_session_human, prop())
    new = prop(match="equal", allowed=["a", "b"], value_aliases={})
    propose_property(project, agent, new, supersedes="pr:sampling")
    assert resolve_property(project, "pr:sampling") == prop()  # old stays live until approved
    decide_property(project, other_session_human, "pr:sampling", "approve", "narrower")
    assert resolve_property(project, "pr:sampling") == new
    states = sorted(v.state for v in list_properties(project, include_rejected=True))
    assert [v.state for v in list_properties(project)] == ["approved"]
    assert states == ["approved", "superseded"]


def test_rejection_withdraws_live_definition(
    project: Project, agent: Actor, other_session_human: Actor
) -> None:
    approve(project, agent, other_session_human, prop())
    decide_property(project, other_session_human, "pr:sampling", "reject", "no longer wanted")
    assert resolve_property(project, "pr:sampling") is None
    assert vocabulary_version(project) == "V@00000000"


def test_merge_requires_same_kind(
    project: Project, agent: Actor, other_session_human: Actor
) -> None:
    approve(project, agent, other_session_human, prop())
    approve(
        project,
        agent,
        other_session_human,
        prop("pr:dense", kind="bool", allowed=[], value_aliases={}),
    )
    _refused(
        project,
        "into",
        "kind-differs",
        lambda: merge_properties(project, other_session_human, "pr:dense", "pr:sampling", "same"),
    )
    _refused(
        project,
        "actor",
        "human-only",
        lambda: merge_properties(project, agent, "pr:dense", "pr:sampling", "same"),
    )
    _refused(
        project,
        "from_key",
        "unknown",
        lambda: merge_properties(project, other_session_human, "pr:nope-nope", "pr:sampling", "x"),
    )


def test_merge_and_unmerge_restore_resolution(
    project: Project, agent: Actor, other_session_human: Actor
) -> None:  # acceptance 1
    approve(project, agent, other_session_human, prop())
    approve(project, agent, other_session_human, prop("pr:sampling-2"))
    before = vocabulary_version(project)
    merge_properties(project, other_session_human, "pr:sampling-2", "pr:sampling", "duplicate")
    assert resolve_property(project, "pr:sampling-2") == prop()
    assert vocabulary_version(project) != before
    _refused(
        project,
        "into",
        "merge-cycle",
        lambda: merge_properties(
            project, other_session_human, "pr:sampling", "pr:sampling-2", "back"
        ),
    )
    _refused(
        project,
        "from_key",
        "already-merged",
        lambda: merge_properties(
            project, other_session_human, "pr:sampling-2", "pr:sampling", "again"
        ),
    )
    unmerge_property(project, other_session_human, "pr:sampling-2", "split again")
    assert resolve_property(project, "pr:sampling-2") == prop("pr:sampling-2")
    assert vocabulary_version(project) == before
    _refused(
        project,
        "from_key",
        "not-merged",
        lambda: unmerge_property(project, other_session_human, "pr:sampling-2", "x"),
    )

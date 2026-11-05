"""The protocol's `supplied_links` section and the gate on `supplied` lookups (slice 4a, r. 7)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from factory.errors import ValidationIssue
from factory.events.envelope import Actor
from factory.model.protocol import (
    AMENDABLE_FIELDS,
    ProtocolSpec,
    SuppliedLinksPlan,
    protocol_version,
)
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.services.context import Project
from factory.services.protocol import (
    amend_protocol,
    current_protocol,
    list_amendments,
    record_deviation,
    search_authorization,
)
from tests.extraction_helpers import PINNED_P_ID
from tests.helpers import SourcesFor, pilot_protocol_spec, ready_protocol

SUPPLIED_Q = QuerySpec(
    source="openalex",
    kind=QueryKind.FILTER,
    text="doi:10.1109/iccv48922.2021.00986",
    purpose=QueryPurpose.SUPPLIED,
)
HUMAN_ONLY = SuppliedLinksPlan(accept_from=("human",))


def _fields(issues: list[ValidationIssue]) -> set[str]:
    return {issue.field for issue in issues}


def _accept(project: Project, agent: Actor, plan: SuppliedLinksPlan) -> None:
    old = current_protocol(project)
    assert old is not None
    new = old.spec.model_copy(update={"supplied_links": plan})
    amend_protocol(project, agent, new, reason="accept supplied links", semantic=True, effects={})


def test_p_id_unchanged_without_supplied_links() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    assert spec.supplied_links is None
    assert protocol_version(spec) == PINNED_P_ID


def test_p_id_changes_with_supplied_links() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    human = spec.model_copy(update={"supplied_links": HUMAN_ONLY})
    both = spec.model_copy(
        update={"supplied_links": SuppliedLinksPlan(accept_from=("human", "agent"))}
    )
    assert protocol_version(human) != PINNED_P_ID
    assert protocol_version(both) != protocol_version(human)
    assert "supplied_links" in AMENDABLE_FIELDS


def test_accept_from_order_does_not_change_the_hash() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    one = SuppliedLinksPlan(accept_from=("human", "agent"))
    other = SuppliedLinksPlan(accept_from=("agent", "human"))
    assert one == other
    assert protocol_version(spec.model_copy(update={"supplied_links": one})) == protocol_version(
        spec.model_copy(update={"supplied_links": other})
    )


@pytest.mark.parametrize(
    "accept_from",
    [(), ("human", "human"), ("system",), ("reviewer",)],
)
def test_accept_from_validation(accept_from: tuple[Any, ...]) -> None:
    with pytest.raises(ValidationError) as caught:
        SuppliedLinksPlan.model_validate({"accept_from": accept_from})
    assert all(err["loc"][0] == "accept_from" for err in caught.value.errors())
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1").model_dump(mode="json")
    spec["supplied_links"] = {"accept_from": list(accept_from)}
    with pytest.raises(ValidationError) as nested:
        ProtocolSpec.model_validate(spec)
    assert all(err["loc"][:2] == ("supplied_links", "accept_from") for err in nested.value.errors())


def test_gate_needs_plan_or_deviation_in_pilot(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    for supplied_by in ("human", "agent", None):
        issues = search_authorization(
            project, SUPPLIED_Q, deviation_id=None, supplied_by=supplied_by
        )
        assert _fields(issues) == {"query"}
    deviation = record_deviation(project, human, description="Supplied link", reason="Colleague.")
    assert search_authorization(project, SUPPLIED_Q, deviation_id=deviation) == []


def test_gate_waives_accepted_kind(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    _accept(project, agent, HUMAN_ONLY)
    assert search_authorization(project, SUPPLIED_Q, deviation_id=None, supplied_by="human") == []
    agent_issues = search_authorization(project, SUPPLIED_Q, deviation_id=None, supplied_by="agent")
    assert _fields(agent_issues) == {"query"}
    # No submitter named: never waived.
    assert _fields(search_authorization(project, SUPPLIED_Q, deviation_id=None)) == {"query"}


def test_waiver_applies_to_supplied_purpose_only(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    _accept(project, agent, HUMAN_ONLY)
    unplanned = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="unplanned words")
    issues = search_authorization(project, unplanned, deviation_id=None, supplied_by="human")
    assert _fields(issues) == {"query"}


def test_waiver_keeps_other_gates(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources, press=False)
    _accept(project, agent, HUMAN_ONLY)
    issues = search_authorization(project, SUPPLIED_Q, deviation_id=None, supplied_by="human")
    assert _fields(issues) == {"press"}


def test_exploratory_ungated(explore_project: Project) -> None:
    assert search_authorization(explore_project, SUPPLIED_Q, deviation_id=None) == []
    assert (
        search_authorization(explore_project, SUPPLIED_Q, deviation_id=None, supplied_by="agent")
        == []
    )


def test_amend_adds_section_without_staling_decisions(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources, press=False)
    _accept(project, agent, HUMAN_ONLY)
    amendment = list_amendments(project)[-1]
    assert amendment.other_changes == ("supplied_links",)
    assert amendment.stale_rules == ()
    assert amendment.changes == ()
    current = current_protocol(project)
    assert current is not None and current.spec.supplied_links == HUMAN_ONLY

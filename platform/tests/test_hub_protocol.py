"""The `protocol` hub payload: wraps the dashboard panels, versions with diffs, deviations."""

from __future__ import annotations

from typing import Any

from factory.events.envelope import Actor
from factory.services import dashboard, hub_protocol
from factory.services import hub_build as hb
from factory.services.context import Project
from factory.services.protocol import (
    amend_protocol,
    current_protocol,
    list_amendments,
    record_deviation,
)
from tests.test_hub_build import world  # noqa: F401  (fixture)


def _payload(project: Project) -> dict[str, Any]:
    return hub_protocol.build(hb.HubContext(project))


def test_payload_wraps_the_dashboard_panels(world: Project) -> None:  # noqa: F811
    out = _payload(world)
    assert out["ready"] is True and out["errors"] == {}
    assert out["protocol"] == dashboard._protocol(world)
    assert out["decisions"] == dashboard._decisions(world)
    assert out["press"] == dashboard._press(world)
    assert out["probes"] == dashboard._probes(world)
    assert out["question"] == dashboard._question(world)
    assert set(out["methods"]) >= {"plan", "criteria", "versions", "decisions", "press", "probes"}
    assert sum(out["decision_sections"].values()) == len(out["decisions"])


def test_criteria_excluded_counts_match_the_reasons_wall(world: Project) -> None:  # noqa: F811
    out = _payload(world)["criteria_excluded"]
    ids = {c.id for c in current_protocol(world).spec.criteria}  # type: ignore[union-attr]
    assert out and set(out) <= ids | {"unspecified"}
    assert all(n > 0 for per in out.values() for n in per.values())


def test_first_version_is_the_registered_protocol(world: Project) -> None:  # noqa: F811
    versions = _payload(world)["versions"]
    current = current_protocol(world)
    assert current is not None
    assert versions[0]["kind"] == "initial"
    assert len(versions) == 1 + len(list_amendments(world))
    assert all(len(f) == 8 for f in versions[0]["fingerprints"].values())


def test_prose_amendment_is_a_version_with_no_changed_section(
    world: Project,  # noqa: F811
    agent: Actor,
) -> None:
    current = current_protocol(world)
    assert current is not None
    before = _payload(world)["versions"]
    prose = current.spec.model_copy(update={"rationale": "Reworded again for the record."})
    amend_protocol(world, agent, prose, reason="prose", semantic=False, effects={})
    versions = _payload(world)["versions"]
    assert len(versions) == len(before) + 1
    last = versions[-1]
    assert last["kind"] == "amendment" and last["semantic"] is False
    assert last["protocol_id"] == current.protocol_id
    assert last["changed"] == ["rationale"]
    assert last["diff"]["rationale"]["after"] == "Reworded again for the record."
    assert last["fingerprints"]["criteria"] == versions[-2]["fingerprints"]["criteria"]


def test_deviations_are_listed_in_recording_order(world: Project, agent: Actor) -> None:  # noqa: F811
    record_deviation(world, agent, description="first", reason="r1", affects=("W1",))
    record_deviation(world, agent, description="second", reason="r2")
    rows = _payload(world)["deviations"]
    assert [r["description"] for r in rows][-2:] == ["first", "second"]


def test_section_diff_lists_keyed_item_changes() -> None:
    out = hub_protocol.section_diff(
        [{"id": "EX01", "rule": "a"}, {"id": "EX02", "rule": "b"}],
        [{"id": "EX02", "rule": "c"}, {"id": "EX03", "rule": "d"}],
    )
    assert [(i["key"], i["change"]) for i in out["items"]] == [
        ("EX01", "removed"),
        ("EX02", "changed"),
        ("EX03", "added"),
    ]
    assert hub_protocol.section_diff({"a": 1}, {"a": 2})["items"] is None


def test_decision_chains_follow_supersedes_links() -> None:
    rows = [
        {"decision_id": "a", "supersedes": None, "superseded_by": "b"},
        {"decision_id": "b", "supersedes": "a", "superseded_by": "c"},
        {"decision_id": "c", "supersedes": "b", "superseded_by": None},
        {"decision_id": "d", "supersedes": None, "superseded_by": None},
    ]
    assert hub_protocol.decision_chains(rows) == [["a", "b", "c"]]
    assert hub_protocol.fingerprint({"b": 1, "a": 2}) == hub_protocol.fingerprint({"a": 2, "b": 1})

"""The "How it works" run map of the `platform` payload: declared text that must stay consistent
with the capability catalog (stage ids, loops, tool names)."""

from __future__ import annotations

import json

from factory.services import hub_build as hb
from factory.services import hub_platform as hpl
from factory.services import site_catalog as sc
from factory.services.context import Project
from tests.test_hub_build import world  # noqa: F401  (fixture)
from tests.test_hub_payloads_flow import listed_miners  # noqa: F401  (fixture)

RM = hpl.RUN_MAP


def test_stages_are_the_lifecycle_stages_in_order() -> None:
    assert [s["id"] for s in RM["stages"]] == [i for i in sc.STAGE_IDS if i != "cross"]


def test_loops_join_two_declared_stages_and_point_back() -> None:
    order = [s["id"] for s in RM["stages"]]
    for loop in RM["loops"]:
        assert order.index(loop["to"]) < order.index(loop["from"]), loop


def test_every_named_tool_is_registered_and_payload_carries_the_map(world: Project) -> None:  # noqa: F811
    payload = hpl.build(hb.HubContext(world))
    json.dumps(payload, allow_nan=False)
    assert payload["run_map"] == RM
    catalog = payload["catalog"]
    assert isinstance(catalog, dict), payload["catalog_error"]
    names = {t["n"] for t in catalog["tools"]}
    named = {t for s in RM["stages"] for t in s["tools"]}
    assert named - names == set()
    assert {c["who"] for c in RM["call"]} <= {"claude", "platform", "human"}

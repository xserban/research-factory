"""The `levels` hub payload and page (plan tiers-and-autonomy, lane L7): read-only, computed from
services, guarded per section, conductor optional."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from factory.clock import FixedClock
from factory.config import Settings
from factory.model.levels import AutonomyLevel
from factory.modules.contract import GatePolicy, PolicyKind
from factory.services import hub_build, hub_levels, hub_ui
from factory.services.context import Project
from factory.services.gates import effective_policy
from factory.services.project import init_project
from tests.helpers import SESSION

SECTIONS = {
    "levels",
    "statement",
    "plan",
    "gates",
    "trust",
    "deferred",
    "conductor",
    "methods",
}


def _project(settings: Settings, clock: FixedClock, tier: str | None, level: str | None) -> Project:
    return init_project(
        settings, "demo", None, session=SESSION, clock=clock, tier=tier, autonomy_level=level
    )


def fake_conductor(project: Project) -> dict[str, Any]:
    return {
        "conductor_id": "c1",
        "state": "paused",
        "steps": ["frame", "gather"],
        "steps_done": 1,
        "stage_id": "gather",
        "role": "proposer",
        "runs": 2,
        "minutes": 3.5,
        "reason": "trust-pause",
        "lines": ["conductor c1: brief at autonomous"],
    }


def test_the_page_is_registered_everywhere() -> None:
    spec = hub_ui.PAGES["levels"]
    assert spec.title == "How this study runs"
    assert spec.payloads == ("shell", "levels") and spec.script in hub_ui.ASSETS
    assert hub_build.BUILDERS["levels"] is hub_levels.build
    from factory.services import hub_pipeline, hub_serve

    assert "levels" in hub_serve.PREWARM_ORDER
    assert any(c["id"] == "levels" and c["blurb"] for c in hub_pipeline.page_cards())
    script = resources.files("factory.hub_ui").joinpath("pages/levels.js").read_text("utf-8")
    assert "HUB.load(['shell', 'levels'])" in script and ".mount(" in script


def test_legacy_attended_project_has_no_plan_and_nothing_waits(
    settings: Settings, clock: FixedClock
) -> None:
    project = _project(settings, clock, None, None)
    payload = hub_levels.levels_payload(project, conductor=fake_conductor)
    assert set(payload) == SECTIONS
    json.dumps(payload, allow_nan=False)
    assert payload["levels"]["tier"] is None
    assert payload["levels"]["autonomy_level"] == "attended"
    assert payload["plan"] == {"declared": False, "stages": [], "skipped": [], "limits": None}
    assert payload["statement"]["human_confirmed"] is True
    assert payload["deferred"]["count"] == 0 and payload["deferred"]["items"] == []
    assert payload["trust"]["rows"] == []


def test_a_brief_shows_its_plan_and_its_skipped_steps(
    settings: Settings, clock: FixedClock
) -> None:
    from factory.tiers.resolve import skipped_steps

    project = _project(settings, clock, "brief", None)
    payload = hub_levels.levels_payload(project, conductor=fake_conductor)
    plan = payload["plan"]
    assert plan["declared"] is True
    assert plan["skipped"] == list(skipped_steps(project_tier(project)))
    assert plan["limits"] is not None
    assert [s["stage_id"] for s in plan["stages"]]
    assert payload["levels"]["rigor_mode"] == "exploratory"


def project_tier(project: Project) -> Any:
    from factory.services.project import project_levels

    tier = project_levels(project).tier
    assert tier is not None
    return tier


def test_gate_rows_equal_the_effective_policy(settings: Settings, clock: FixedClock) -> None:
    project = _project(settings, clock, "pilot", "supervised")
    rows = hub_levels.levels_payload(project, conductor=fake_conductor)["gates"]
    assert rows
    for row in rows:
        policy = effective_policy(project, row["gate_id"])
        assert row["policy"]["kind"] == policy.kind.value
        assert row["agent_may_close"] is (policy.kind is not PolicyKind.HUMAN)
        assert row["differs_from_preset"] is (row["policy"] != row["preset"])
        if row["agent_may_close"]:
            assert "differ from the proposing one" in row["who"]
        else:
            assert row["who"] == "A person only."


def test_who_may_close_by_policy_and_level() -> None:
    audit = GatePolicy(PolicyKind.AGENT_AUDIT, 0.2, 5)
    assert hub_levels.who_may_close(GatePolicy(PolicyKind.HUMAN), AutonomyLevel.AUTONOMOUS) == (
        "A person only."
    )
    text = hub_levels.who_may_close(audit, AutonomyLevel.ATTENDED)
    assert "20%" in text and "at least 5" in text and "differ" not in text
    assert "differ" in hub_levels.who_may_close(
        GatePolicy(PolicyKind.AGENT), AutonomyLevel.SUPERVISED
    )


def test_an_autonomous_project_is_labelled_not_human_confirmed(
    settings: Settings, clock: FixedClock
) -> None:
    project = _project(settings, clock, "brief", "autonomous")
    payload = hub_levels.levels_payload(project, conductor=fake_conductor)
    assert payload["levels"]["autonomy_level"] == "autonomous"
    assert payload["statement"]["human_confirmed"] is False
    assert any("not human-confirmed" in x for x in payload["statement"]["lines"])


def test_the_conductor_section_uses_the_reader_or_says_it_is_absent(
    settings: Settings, clock: FixedClock
) -> None:
    project = _project(settings, clock, "brief", "autonomous")
    got = hub_levels.levels_payload(project, conductor=fake_conductor)["conductor"]
    assert got == {"present": True, "status": fake_conductor(project)}


def test_the_conductor_section_reads_the_real_status_without_a_fallback(
    settings: Settings, clock: FixedClock
) -> None:
    project = _project(settings, clock, "brief", None)
    section = hub_levels.levels_payload(project)["conductor"]
    assert section["present"] is True and section["status"]["state"] == "none"


def test_a_failing_section_is_an_error_and_the_rest_survive(
    settings: Settings, clock: FixedClock
) -> None:
    project = _project(settings, clock, "brief", None)

    def broken(_p: Project) -> dict[str, Any]:
        raise RuntimeError("boom")

    payload = hub_levels.levels_payload(project, conductor=broken)
    assert payload["conductor"]["error"].startswith("RuntimeError")
    assert payload["levels"]["tier"] == "brief" and payload["plan"]["declared"] is True


def test_the_trust_help_states_the_computed_thresholds(
    settings: Settings, clock: FixedClock
) -> None:
    from factory.services import gate_trust

    project = _project(settings, clock, None, None)
    text = hub_levels.levels_payload(project)["methods"]["trust"]
    assert f"{gate_trust.PAUSE_RATE:.0%}" in text and str(gate_trust.WATCH_MIN_AUDITED) in text


def test_the_payload_is_deterministic(settings: Settings, clock: FixedClock) -> None:
    project = _project(settings, clock, "brief", "supervised")
    a = hub_levels.levels_payload(project, conductor=fake_conductor)
    b = hub_levels.levels_payload(project, conductor=fake_conductor)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

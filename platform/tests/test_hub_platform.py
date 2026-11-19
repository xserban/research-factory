"""The `platform` hub payload: capabilities by stage, flags, markers, and the backlog board.
Every figure is checked against the services it wraps."""

from __future__ import annotations

import json

import pytest

from factory.services import hub_build as hb
from factory.services import hub_platform as hpl
from factory.services import site_backlog as sb
from factory.services.context import Project
from tests.test_hub_build import world  # noqa: F401  (fixture)


@pytest.fixture
def payload(world: Project) -> dict[str, object]:  # noqa: F811
    return hpl.build(hb.HubContext(world))


def test_payload_is_json_and_has_both_halves(payload: dict[str, object]) -> None:
    json.dumps(payload, allow_nan=False)
    assert payload["ready"] is True
    assert payload["catalog_error"] is None
    assert payload["backlog_error"] is None
    assert set(hpl.METHODS) <= set(payload["methods"])  # type: ignore[arg-type]


def test_summary_counts_are_the_catalog_counts(world: Project) -> None:  # noqa: F811
    from factory.services import site_catalog as sc

    cat = sc.build_catalog(world.settings)
    cp = hpl.catalog_payload(world.settings)
    assert cp["summary"]["tools_registered"] == cat.count_check.registered
    assert cp["summary"]["skills"] == len(cat.skills)
    assert cp["summary"]["flags"] == len(cat.flags) == len(cp["flags"])
    assert cp["summary"]["prompts"] == cat.prompts
    assert len(cp["tools"]) == len(cat.tools)
    assert cp["skipped"] == dict(sorted(cat.skipped.items()))


def test_matrix_rows_add_up_to_the_tool_list(world: Project) -> None:  # noqa: F811
    cp = hpl.catalog_payload(world.settings)
    assert sum(r["n_tools"] for r in cp["stages"]) == len(cp["tools"])
    for r in cp["stages"]:
        assert len(r["tools"]) == r["n_tools"]
        assert sum(r["access"].values()) == r["n_tools"]
        assert sum(r["markers"].values()) <= r["n_tools"]
    assert [r["id"] for r in cp["stages"][:10]] == [
        "frame",
        "gather",
        "screen",
        "acquire",
        "extract",
        "understand",
        "develop",
        "write",
        "maintain",
        "cross",
    ]


def test_marked_tools_carry_kind_and_reason(world: Project) -> None:  # noqa: F811
    cp = hpl.catalog_payload(world.settings)
    assert len(cp["marked"]) == cp["summary"]["marked"]
    for m in cp["marked"]:
        assert m["why"] and m["kind"] in {"read-only", "human-only", "scheduled"}


def test_backlog_states_are_computed_and_counted() -> None:
    source = (
        "## Area A\n\nNote about A.\n\n"
        "### IDEA-01 — First\nStatus: built · Added: 2026-01-01 · Slice: s1\n\n**What:** a\n\n"
        "### IDEA-02 — Second\nStatus: new · Depends on: IDEA-01\n\n"
        "### IDEA-03 — Third\nStatus: new · Depends on: IDEA-04\n\n"
        "### IDEA-04 — Fourth\nStatus: parked\n"
    )
    ideas = sb.classify(sb.parse_backlog(source))
    states = {i["id"]: i["state"] for i in ideas}
    assert states == {
        "IDEA-01": "done",
        "IDEA-02": "ready",
        "IDEA-03": "blocked",
        "IDEA-04": "parked",
    }


def test_backlog_payload_counts_match_ideas(world: Project) -> None:  # noqa: F811
    bp = hpl.backlog_payload()
    if not bp["found"]:
        pytest.skip("no backlog document in this checkout")
    assert sum(bp["by_state"].values()) == len(bp["ideas"])
    for area, row in bp["by_area"].items():
        assert sum(row.values()) == sum(1 for i in bp["ideas"] if i["area"] == area)
    assert all(i["state"] in hpl.STATES for i in bp["ideas"])


def test_backlog_missing_is_reported_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sb, "backlog_path", lambda: None)
    bp = hpl.backlog_payload()
    assert bp["found"] is False and bp["ideas"] == []


def test_one_half_failing_keeps_the_other(
    world: Project,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_: object) -> dict[str, object]:
        raise RuntimeError("no server")

    monkeypatch.setattr(hpl, "catalog_payload", boom)
    out = hpl.build(hb.HubContext(world))
    assert out["catalog"] is None and "no server" in out["catalog_error"]
    assert out["backlog_error"] is None

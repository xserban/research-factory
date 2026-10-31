import pytest
from pydantic import JsonValue

from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.mcp.conventions import (
    PAGE_LIMIT,
    fail,
    guarded,
    make_agent_actor,
    ok,
    paginate,
)
from tests.helpers import SESSION


def test_paginate_walks_all_items_with_cursor() -> None:
    items = list(range(120))
    p1 = paginate(items, None)
    p2 = paginate(items, p1.next_cursor)
    p3 = paginate(items, p2.next_cursor)
    assert p1.items + p2.items + p3.items == items
    assert p3.next_cursor is None
    assert len(p1.items) == PAGE_LIMIT


def test_paginate_last_page_has_no_cursor() -> None:
    page = paginate(list(range(3)), None)
    assert page.items == [0, 1, 2]
    assert page.next_cursor is None


def test_paginate_clamps_limit() -> None:
    assert len(paginate(list(range(500)), None, limit=10_000).items) == PAGE_LIMIT
    assert len(paginate(list(range(500)), None, limit=0).items) == 1


@pytest.mark.parametrize("cursor", ["abc", "-1", "1.5", "", "\u0663"])
def test_paginate_rejects_bad_cursor(cursor: str) -> None:
    with pytest.raises(FactoryValidationError) as err:
        paginate([1], cursor)
    assert err.value.issues[0].field == "cursor"


def test_make_agent_actor_builds_agent(settings: Settings) -> None:
    actor = make_agent_actor(
        settings, SESSION, "screener-a", model="claude-opus-5-5", skill="rf-screen@1a2b3c4d"
    )
    assert actor.kind == "agent"
    assert actor.id == "screener-a"
    assert actor.user == "obd"
    assert actor.session == SESSION


def test_make_agent_actor_reports_fields(settings: Settings) -> None:
    with pytest.raises(FactoryValidationError) as err:
        make_agent_actor(settings, SESSION, "screener-a", model="", skill="rf-screen@1a2b3c4d")
    assert err.value.issues[0].field == "model"


def test_make_agent_actor_reports_role_and_skill(settings: Settings) -> None:
    with pytest.raises(FactoryValidationError) as role_err:
        make_agent_actor(
            settings, SESSION, "Bad Role", model="claude-opus-5-5", skill="rf-screen@1a2b3c4d"
        )
    assert role_err.value.issues[0].field == "role"
    with pytest.raises(FactoryValidationError) as skill_err:
        make_agent_actor(settings, SESSION, "screener-a", model="claude-opus-5-5", skill="nope")
    assert skill_err.value.issues[0].field == "skill"


def test_ok_and_fail_shapes() -> None:
    assert ok({"a": 1}) == {"ok": True, "data": {"a": 1}}
    assert fail([ValidationIssue("x", "bad")]) == {
        "ok": False,
        "errors": [{"field": "x", "reason": "bad"}],
    }


def test_guarded_maps_validation_errors() -> None:
    def boom() -> dict[str, JsonValue]:
        raise FactoryValidationError([ValidationIssue("x", "bad")])

    assert guarded(boom) == {"ok": False, "errors": [{"field": "x", "reason": "bad"}]}


def test_guarded_maps_unknown_project() -> None:
    def missing() -> dict[str, JsonValue]:
        raise ProjectNotFoundError("no project")

    assert guarded(missing) == {
        "ok": False,
        "errors": [{"field": "project", "reason": "unknown project"}],
    }


def test_guarded_wraps_success() -> None:
    assert guarded(lambda: {"n": 2}) == {"ok": True, "data": {"n": 2}}


def test_guarded_does_not_swallow_other_errors() -> None:
    def broken() -> dict[str, JsonValue]:
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        guarded(broken)

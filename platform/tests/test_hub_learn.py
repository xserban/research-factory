"""The Learn page payload: tutorial text plus computed progress; the fresh-project landing."""

from __future__ import annotations

import json

from factory.learn.model import RefKind, cli, page
from factory.learn.stages import STAGES
from factory.services import hub_learn
from factory.services.context import Project


def test_payload_is_json_and_has_every_stage_with_progress(project: Project) -> None:
    payload = hub_learn.learn_payload(project)
    json.dumps(payload, allow_nan=False)
    assert [s["id"] for s in payload["stages"]] == [s.id for s in STAGES]
    assert {s["progress"]["state"] for s in payload["stages"]} == {"not-started"}
    assert payload["fresh"] is True
    assert payload["concepts"] and payload["glossary"]
    assert payload["how_it_works"] == "platform.html#tab=how"


def test_a_fresh_project_lands_on_learn(project: Project) -> None:
    assert hub_learn.landing_page(project) == "learn"


def test_later_events_end_the_fresh_state() -> None:
    assert hub_learn.fresh({"project.created": (1, "a"), "seed.added": (3, "b")})
    assert not hub_learn.fresh({"project.created": (1, "a"), "screening.pass_opened": (1, "c")})


def test_ref_view_labels_commands_and_links_pages() -> None:
    assert hub_learn.ref_view(cli("decide select"))["label"] == "factory decide select"
    view = hub_learn.ref_view(page("flow"))
    assert view["href"] == "flow.html" and view["kind"] == RefKind.PAGE.value

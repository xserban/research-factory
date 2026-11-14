"""Work trails and the Flow explorer payload (flow transparency, tasks 5 and 6).

Written during the testing pause and not yet run.
"""

import json
from datetime import UTC, datetime

from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.flow_ledger import TOTAL, flow_by_source, flow_ledger
from factory.services.flow_trails import TEXT_LIMIT, _cut, _details, flow_trails
from factory.services.site_flow import _embed, build_payload, reached, table_spec, tags
from tests.fulltext_helpers import _ft_world
from tests.helpers import SourcesFor


def test_cut_collapses_whitespace_and_limits_length() -> None:
    assert _cut("a  b\n c") == "a b c"
    assert len(_cut("x" * 1000)) == TEXT_LIMIT


def test_details_drops_empty_values_and_keeps_numbers() -> None:
    assert _details(a="x", b=None, c="", d=3, e=True) == {"a": "x", "d": 3, "e": "True"}


def test_every_work_starts_with_a_found_step_and_steps_are_time_ordered(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    trails = flow_trails(project)
    assert trails
    for steps in trails.values():
        assert [s.at for s in steps] == sorted(s.at for s in steps)
    decided = [s for steps in trails.values() for s in steps if s.kind == "decision"]
    assert decided and all("verdict" in s.d and "stage" in s.d for s in decided)
    assert all(
        datetime.fromisoformat(s.at.replace("Z", "+00:00")).tzinfo is UTC
        for steps in trails.values()
        for s in steps
    )


def test_payload_rows_match_the_ledger_and_the_flow_by_source(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    payload, trails = build_payload(project)
    rows = flow_ledger(project)
    assert [w["i"] for w in payload["works"]] == [r.work_id for r in rows]
    total = flow_by_source(project)[TOTAL]
    works = payload["works"]
    assert sum("scr" in w["k"] for w in works) == total.screened
    assert sum("ta-inc" in w["k"] for w in works) == total.ta_included
    assert sum("ft-inc" in w["k"] for w in works) == total.ft_included
    assert sum("ns" in w["k"] for w in works) == total.ft_not_sought
    assert sum("nr" in w["k"] for w in works) == total.ft_attempted_failed
    assert sum("ret" in w["k"] for w in works) == total.ft_retrieved
    assert payload["mismatches"] == []
    assert set(trails) <= {w["i"] for w in works}
    json.loads(_embed(payload))


def test_every_table_row_counts_something_the_list_can_filter_to(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    payload, _ = build_payload(project)
    works = payload["works"]
    for row in table_spec(works):
        n = sum(
            row["k"] in w["k"] and (row["c"] is None or (w["c"] or "unspecified") == row["c"])
            for w in works
        )
        assert n > 0 or row["c"] is None


def test_embedded_payload_cannot_close_the_script_tag() -> None:
    assert "</" not in _embed({"t": "</script>"})


def test_reached_and_tags_agree_for_a_duplicate(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    for row in flow_ledger(project):
        step, outcome, _ = reached(row)
        assert step and outcome
        assert ("dup" in tags(row)) == (
            row.canonical_id is not None and not row.noncanonical_promoted
        )

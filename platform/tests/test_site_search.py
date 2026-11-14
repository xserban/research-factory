"""The Search and deduplication payload (hub records, task R1).

Written during the testing pause and not yet run.
"""

import json
from typing import Any

from factory.events.envelope import Actor
from factory.services.context import Project
from factory.services.dedup import list_merges
from factory.services.prisma import search_report
from factory.services.site_flow import _embed
from factory.services.site_search import MERGED_AFTER_NOTE, _counts, build_payload
from factory.services.site_search_page import DATA_MARKER, PAGE
from tests.fulltext_helpers import _ft_world
from tests.helpers import SourcesFor
from tests.screening_helpers import OPENALEX_COPY, PREPRINT, PUBLISHED, _ingest


def test_counts_split_each_rule_by_status() -> None:
    merges: list[dict[str, Any]] = [
        {"rule": "doi", "status": "active"},
        {"rule": "doi", "status": "reverted"},
        {"rule": "title", "status": "active"},
        {"rule": "doi", "status": "active"},
    ]
    assert _counts(merges) == {"doi": {"active": 2, "reverted": 1}, "title": {"active": 1}}


def test_payload_matches_the_search_report_and_the_merges(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ft_world(project, agent, human, mock_sources)
    payload = build_payload(project)
    report = search_report(project)
    assert [q["id"] for q in payload["queries"]] == [r.query_id for r in report.rows]
    for q, r in zip(payload["queries"], report.rows, strict=True):
        assert [run["id"] for run in q["runs"]] == [run.run_id for run in r.runs]
        assert q["retrieved"] == r.retrieved
    merges = list_merges(project)
    assert [m["id"] for m in payload["merges"]] == [m.merge_id for m in merges]
    assert {m["status"] for m in payload["merges"]} <= {"active", "reverted"}
    assert sum(sum(c.values()) for c in payload["rule_counts"].values()) == len(merges)
    assert payload["after_note"] == MERGED_AFTER_NOTE


def test_embedded_payload_cannot_close_the_script_tag() -> None:
    text = _embed({"t": "</script><!-- x"})
    assert "</" not in text and "<!--" not in text
    assert json.loads(text.replace("<\\/", "</").replace("<\\u0021--", "<!--"))["t"].startswith(
        "</"
    )
    assert DATA_MARKER in PAGE


def test_every_reverted_merge_is_counted_with_its_reason_and_time(
    explore_project: Project, fake_sources: SourcesFor
) -> None:
    from factory.services.dedup_incremental import dedup_new
    from factory.services.search import list_works

    def ingest(records: list[dict[str, Any]]) -> list[str]:
        before = {w.id for w in list_works(explore_project)}
        _ingest(explore_project, fake_sources, [records])
        return [w.id for w in list_works(explore_project) if w.id not in before]

    dedup_new(explore_project, ingest([PUBLISHED, PREPRINT]))
    dedup_new(explore_project, ingest([OPENALEX_COPY]))  # supersedes the first merge
    merges = list_merges(explore_project)
    reverted = [m for m in merges if m.status.value == "reverted"]
    assert reverted
    payload = build_payload(explore_project)
    shown = [m for m in payload["merges"] if m["status"] == "reverted"]
    assert [m["id"] for m in shown] == [m.merge_id for m in reverted]
    assert sum(c.get("reverted", 0) for c in payload["rule_counts"].values()) == len(reverted)
    assert all(m["reason"] and m["rat"] for m in shown)
    assert all(m["rat"] is None for m in payload["merges"] if m["status"] == "active")

"""Renderers of the evidence report (plan E task 5): formatting only."""

import csv
import io

import pytest

from factory.cli import evidence_render
from factory.cli.evidence_render import evidence_markdown, points_csv, rows_csv
from factory.model.extraction import ClaimType
from factory.services.evidence_report import EvidenceReport, assemble_report
from tests.evidence_helpers import claim, pilot_inputs

POINTS_HEADER = (
    "group_id,axis,unit,resolution,row_key,work_id,method,cost,metric,on_frontier,dominated_by"
)
ROWS_HEADER = (
    "group_id,row_key,work_id,method,variant,value,unit,canonical,independent,status,"
    "params,flops,macs,anchor,cell,extraction_id"
)


def report() -> EvidenceReport:
    return assemble_report(
        pilot_inputs(claims=[claim("c1", "rf:w1", ClaimType.FINDING, "Stated finding.")])
    )


def test_markdown_has_one_section_per_group_and_no_cross_group_text() -> None:
    r = report()
    md = evidence_markdown(r)
    assert len(r.groups) > 1
    for g in r.groups:
        assert md.count(f"### Group {g.group_id}") == 1
    low = md.lower()
    for banned in ("best overall", "overall best", "winner", "ranking", "rank "):
        assert banned not in low


def test_markdown_group_section_shows_counts_flags_frontier_and_provenance_ids() -> None:
    r = report()
    md = evidence_markdown(r)
    g = r.groups[0]
    assert "P@3" in md and r.pack is not None and r.pack in md
    assert f"independent {g.counts.independent}" in md
    assert f"copied {g.counts.copied}" in md
    for row in g.rows:
        assert row.row_key in md
        assert row.value.extraction_id in md
        assert row.value.trace_id in md
    assert "copied" in md


def test_markdown_lists_limits_expectations_excluded_and_provisional_banner() -> None:
    r = report()
    md = evidence_markdown(r)
    assert not r.provisional and "PROVISIONAL" not in md
    prov = assemble_report(pilot_inputs(blocking=True))
    assert prov.provisional and "PROVISIONAL" in evidence_markdown(prov)
    for limit in r.limits:
        assert limit.text in md
    assert "## Excluded" in md
    for e in r.excluded:
        assert e.reason in md
    assert "## Quality" in md
    assert "Stated finding." in md and "## Claims by type" in md


def test_speed_section_is_the_only_place_speed_appears(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        evidence_render,
        "_speed_section",
        lambda _r: ["## Within-paper speed ratios", "", "baseline X on A100: 2x img/s"],
    )
    md = evidence_markdown(report())
    head, speed = md.split("## Within-paper speed ratios")
    assert "img/s" not in head and "A100" in speed


def test_default_speed_hook_adds_nothing() -> None:
    assert evidence_render._speed_section(report()) == []


def test_csv_points_have_no_speed_columns_and_are_stable() -> None:
    r = report()
    out = points_csv(r)
    assert out.splitlines()[0] == POINTS_HEADER
    assert "\r" not in out
    assert out == points_csv(r)
    assert "speed" not in out.splitlines()[0]
    parsed = list(csv.DictReader(io.StringIO(out)))
    expected = sum(len(p.points) for g in r.groups for a in g.frontiers for p in a.partitions)
    assert len(parsed) == expected


def test_csv_rows_follow_report_order() -> None:
    r = report()
    out = rows_csv(r)
    assert out.splitlines()[0] == ROWS_HEADER
    parsed = list(csv.DictReader(io.StringIO(out)))
    assert [p["row_key"] for p in parsed] == [row.row_key for g in r.groups for row in g.rows]
    assert out == rows_csv(r)


def test_audit_rate_hidden_when_show_audit_false() -> None:
    r = report()
    q = r.quality.model_copy(
        update={"audit_n": 12, "audit_error_rate": 0.0625, "audit_above_ceiling": False}
    )
    r = r.model_copy(update={"quality": q})
    assert "0.0625" in evidence_markdown(r)
    hidden = evidence_markdown(r, show_audit=False)
    assert "0.0625" not in hidden
    assert "audit" not in hidden.split("## Quality")[1].lower()


def test_render_is_deterministic() -> None:
    assert evidence_markdown(report()) == evidence_markdown(report())

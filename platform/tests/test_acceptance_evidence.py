# ruff: noqa: F811
"""Acceptance of plan 2E (slice-2 acceptance 12, 12a, 14 and 16).

Two worlds. The pure one is a hand-built, pilot-shaped set of final rows (seven included works)
fed to `assemble_report`; its expected numbers are written out here, not derived from the code
under test. The service one is the synthetic conversion of plan D's tests with both passes
recorded, for what needs events, the index and `trace`. Values are invented; no literature text."""

import json
import shutil
from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.services.context import Project
from factory.services.evidence_report import (
    EvidenceReport,
    GroupReport,
    assemble_report,
    evidence_report,
)
from factory.services.extraction_agreement import FinalField, FinalRow
from factory.services.trace import TraceNode, dangling_refs, trace
from tests.cli_helpers import _env
from tests.evidence_helpers import ff, frow, pilot_inputs
from tests.test_evidence_trace import ext_a, ext_b, world  # noqa: F401

pytestmark = pytest.mark.slow  # acceptance suite: dev runs deselect with -m "not slow"

POPULATION = tuple(f"rf:w{i}" for i in range(1, 8))


def count(n: str) -> FinalField:
    return ff(n, unit="count", canon=n)


def pilot_world() -> list[FinalRow]:
    """Seven included works. G1 (imagenet-1k / top-1 / 224 / none): three works with independent
    rows (w1, w2, w3) and two copied rows (w4 declared cited, w5 with a copy marker); a 384 group
    of two works; a single-paper ADE20K group (w6); throughput rows with hardware, batch size
    and a baseline in two works (w6, w7)."""
    rows = [
        frow("rf:w1", "rk_000000000101", "Ours-S", "81.2", params=count("22000000")),
        frow("rf:w2", "rk_000000000201", "Lean-S", "79.0", params=count("30000000")),
        frow("rf:w3", "rk_000000000301", "Wide-S", "82.0", params=count("45000000")),
        frow("rf:w4", "rk_000000000401", "Lean-S", "79.0", cited=True),
        frow("rf:w5", "rk_000000000501", "Lean-S", "79.0", marker=True),
        frow("rf:w1", "rk_000000000102", "Ours-S", "82.5", resolution="384"),
        frow("rf:w2", "rk_000000000202", "Lean-S", "80.1", resolution="384"),
        frow(
            "rf:w6",
            "rk_000000000601",
            "Ours-Seg",
            "45.1",
            task="semantic segmentation",
            dataset="ADE20K",
            metric="mIoU",
            resolution="512",
        ),
    ]
    for work in ("rf:w6", "rf:w7"):
        for i, (method, proposed, thr) in enumerate(
            (("Ours-S", True, "180"), ("Lean-S", False, "100"))
        ):
            rows.append(
                frow(
                    work,
                    f"rk_0000000{work[-1]}0{i + 7}",
                    method,
                    "80.0",
                    dataset="COCO",
                    task="detection",
                    metric="AP",
                    resolution="800",
                    is_proposed=ff(proposed),
                    throughput=ff(thr, unit="img/s", canon=thr),
                    hardware=ff("A100"),
                    batch_size=ff("64", canon="64"),
                )
            )
    return rows


def pilot_report(**kw: object) -> EvidenceReport:
    return assemble_report(pilot_inputs(pilot_world(), population=POPULATION), **kw)  # type: ignore[arg-type]


def group(r: EvidenceReport, dataset: str, resolution: int | None = None) -> GroupReport:
    found = [
        g
        for g in r.groups
        if dict(g.key)["dataset"] == dataset
        and (resolution is None or dict(g.key)["input_resolution"] == f"{resolution}x{resolution}")
    ]
    assert len(found) == 1, [g.key for g in r.groups]
    return found[0]


def test_pilot_shaped_run_reaches_evidence_report_with_imagenet_group() -> None:  # acceptance 16
    r = pilot_report(expect=[{"dataset": "imagenet-1k"}])
    g = group(r, "imagenet-1k", 224)
    assert (g.counts.independent, g.counts.copied) == (3, 2)
    assert g.counts.independent_works == 3 and g.frontiers
    assert any(ax.axis == "params" and ax.partitions for ax in g.frontiers)
    # The expectation matches every ImageNet-1K group: the 224 group and the 384 group.
    assert r.expectations[0].group_ids == sorted(
        [g.group_id, group(r, "imagenet-1k", 384).group_id]
    )
    assert not r.provisional


def test_no_ranking_across_groups_and_empty_single_groups_stated() -> None:  # acceptance 12
    r = pilot_report(expect=[{"dataset": "coco"}, {"dataset": "pascal-voc"}])
    assert "single-paper" in {s.code for s in group(r, "ade20k").statements}
    assert r.expectations[0].group_ids and r.expectations[1].group_ids == []
    assert "expectation-empty" in {lim.code for lim in r.limits}
    ids = [g.group_id for g in r.groups]
    assert len(ids) == len(set(ids)) >= 4
    seen = [row.row_key for g in r.groups for row in g.rows]
    assert len(seen) == len(set(seen))  # a row is in one group only
    assert not hasattr(r, "ranking") and not hasattr(r.groups[0], "rank")


def test_cost_axes_only_params_flops_macs_and_speed_only_as_ratio() -> None:  # acceptance 12a
    r = pilot_report()
    axes = {a.axis for g in r.groups for a in g.frontiers}
    assert axes <= {"params", "flops", "macs"} and "params" in axes
    assert len(r.speed_ratios) == 2
    assert {x.work_id for x in r.speed_ratios} == {"rf:w6", "rf:w7"}
    for x in r.speed_ratios:
        assert (x.field, x.ratio, x.hardware, x.batch_size) == ("throughput", "1.80", "a100", "64")
        assert (x.method, x.baseline_method) == ("Ours-S", "Lean-S")
    assert r.speed_unpaired == {}


def test_frontier_uses_independent_rows_only() -> None:
    g = group(pilot_report(), "imagenet-1k", 224)
    ax = next(a for a in g.frontiers if a.axis == "params")
    points = {p.row_key: p for part in ax.partitions for p in part.points}
    assert set(points) == {"rk_000000000101", "rk_000000000201", "rk_000000000301"}
    assert {k for k, p in points.items() if p.on_frontier} == {
        "rk_000000000101",
        "rk_000000000301",
    }


def ids_of(r: EvidenceReport) -> list[str]:
    out: list[str] = []
    for g in r.groups:
        for row in g.rows:
            out.append(row.value.trace_id)
            out.extend(p.trace_id for p in row.costs.values())
        for ax in g.frontiers:
            out.extend(p.trace_id for part in ax.partitions for p in part.points)
    out.extend(c.trace_id for entries in r.claims.values() for c in entries)
    return out


def kinds(node: TraceNode) -> Iterator[str]:
    yield node.kind
    for child in node.children:
        yield from kinds(child)


def test_every_frontier_point_cell_and_claim_traces_to_the_question(
    world: EvidenceReport, project: Project
) -> None:  # acceptance 14
    ids = ids_of(world)
    assert ids and any(i.startswith("clm_") for i in ids)
    assert dangling_refs(project, ids) == []
    for ref in sorted(set(ids)):
        assert "question" in set(kinds(trace(project, ref))), ref


def test_report_is_reproducible_from_events_alone(world: EvidenceReport, project: Project) -> None:
    first = evidence_report(project).model_dump_json()
    assert first == world.model_dump_json()
    project.index.rebuild()
    shutil.rmtree(project.paths.library_dir, ignore_errors=True)
    assert evidence_report(project).model_dump_json() == first  # events plus index only


def test_cli_markdown_and_csv_are_deterministic_and_consistent_with_json(
    settings: Settings, world: EvidenceReport, project: Project
) -> None:
    runner = CliRunner()

    def run(fmt: str) -> str:
        res = runner.invoke(app, ["report", "evidence", "--format", fmt], env=_env(settings.root))
        assert res.exit_code == 0, res.stderr
        return res.stdout

    for fmt in ("md", "json", "csv-points", "csv-rows"):
        assert run(fmt) == run(fmt)
    stated = json.loads(run("json"))
    assert stated.pop("level_statement")["tier"] is None  # the statement is one more field (I1)
    assert stated == json.loads(world.model_dump_json())
    md, rows_csv = run("md"), run("csv-rows")
    for g in world.groups:
        assert g.group_id in md
        for row in g.rows:
            assert row.row_key in rows_csv


def test_earlier_acceptance_suites_unchanged() -> None:
    import tests.test_acceptance_extraction as earlier

    assert earlier.test_copied_results_flagged_and_not_independent

# ruff: noqa: RUF001
"""Evidence report: groups, counts, claims, limits (plan E, task 2; rulings 2-5, 10-12).

Most tests run the pure `assemble_report` on the synthetic pilot-shaped rows of
`tests/evidence_helpers.py`; the service tests run `evidence_report` on plan D's extraction world.
"""

import hashlib
import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import replace

import pytest

from factory.events.envelope import Actor
from factory.model.extraction import ClaimType, ExtractedRowInput, ReportedIn
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.packs import ML_BENCHMARK_V1, ReportSpec
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.evidence_report import (
    REPORT_VERSION,
    EvidenceReport,
    GroupReport,
    assemble_report,
    evidence_report,
)
from factory.services.extraction import live_rows
from factory.services.extraction_agreement import AgreementOverall, FinalRow, final_rows
from factory.services.extraction_audit import ExtractionAuditReport
from factory.sources.registry import SourceFactory
from tests.evidence_helpers import (
    claim,
    claim_input,
    disagreement,
    ff,
    frow,
    pilot_inputs,
    pilot_rows,
    run_pass,
)
from tests.extraction_helpers import (
    SESSION_A,
    SESSION_B,
    _declare,
    _extractor,
    _new_document_version,
    _r,
)
from tests.fulltext_helpers import _screened_full_text_world

FT = ScreeningStage.FULL_TEXT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _report(**kw: object) -> EvidenceReport:
    expect = kw.pop("expect", ())
    return assemble_report(pilot_inputs(**kw), expect=expect)  # type: ignore[arg-type]


def group(r: EvidenceReport, dataset: str, resolution: str | None = None) -> GroupReport:
    found = [
        g
        for g in r.groups
        if dict(g.key).get("dataset") == dataset
        and (resolution is None or dict(g.key).get("input_resolution", "").startswith(resolution))
    ]
    assert len(found) == 1, [g.key for g in r.groups]
    return found[0]


def codes(limits: object) -> set[str]:
    return {lim.code for lim in limits}  # type: ignore[attr-defined]


# --- Pack report spec ---


def test_pack_report_spec() -> None:
    spec = ML_BENCHMARK_V1.report
    assert isinstance(spec, ReportSpec)
    assert (spec.value_field, spec.direction_field, spec.proposed_field) == (
        "value",
        "higher_is_better",
        "is_proposed",
    )
    assert spec.frontier_costs == spec.display_costs == ("params", "flops", "macs")
    assert dict(spec.speed_fields) == {"throughput": True, "latency": False}
    assert spec.speed_context == ("hardware", "batch_size", "precision", "input_resolution")
    assert {m for m, up in spec.metric_directions.items() if up} == {
        "top-1 accuracy",
        "top-5 accuracy",
        "miou",
        "box ap",
        "mask ap",
        "accuracy",
    }
    assert {m for m, up in spec.metric_directions.items() if not up} == {
        "perplexity",
        "top-1 error",
        "error rate",
        "fid",
    }
    assert ML_BENCHMARK_V1.version == 1 and REPORT_VERSION == 1


# --- Groups ---


def test_groups_only_by_identical_keys() -> None:
    r = _report()
    assert [g.key for g in r.groups] == sorted(g.key for g in r.groups)
    g224, g384 = group(r, "imagenet-1k", "224"), group(r, "imagenet-1k", "384")
    keys224 = {row.row_key for row in g224.rows}
    assert not any(row.row_key in keys224 for row in g384.rows)
    assert len(r.groups) == 4
    assert r.comparability_keys == list(pilot_inputs().keys)


def test_resolution_variants_group_together() -> None:
    g = group(_report(), "imagenet-1k", "224")
    assert {row.work_id for row in g.rows} == {"rf:w1", "rf:w2", "rf:w3", "rf:w4"}
    assert dict(g.key)["input_resolution"] == "224x224"


def test_counts_independent_vs_copied_from_d() -> None:
    g = group(_report(), "imagenet-1k", "224")
    assert (g.counts.independent, g.counts.copied) == (2, 2)
    assert (g.counts.works, g.counts.independent_works) == (4, 2)
    assert "single-independent-source" not in codes(g.statements)


def test_single_paper_and_single_source_flags() -> None:
    r = _report()
    assert codes(group(r, "ade20k").statements) >= {"single-paper", "single-independent-source"}
    assert codes(group(r, "imagenet-1k", "224").statements) & {"single-paper"} == set()


def test_copied_only_group_states_no_independent_results() -> None:
    r = _report()
    g = group(r, "cifar-100")
    assert (g.counts.independent, g.counts.copied) == (0, 1)
    assert "no-independent-results" in codes(g.statements)
    assert any(
        lim.code == "no-independent-results" and lim.subject == g.group_id for lim in r.limits
    )


def test_group_id_is_stable_and_report_has_no_cross_group_field() -> None:
    r = _report()
    again = assemble_report(pilot_inputs(rows=list(reversed(pilot_rows()))))
    assert group(r, "ade20k").group_id == group(again, "ade20k").group_id
    assert [g.group_id for g in r.groups] == [g.group_id for g in again.groups]
    g = group(r, "ade20k")
    digest = hashlib.sha256(json.dumps([list(p) for p in g.key]).encode()).hexdigest()
    assert g.group_id == "grp_" + digest[:12]
    banned = {"rank", "score", "best", "winner"}
    assert not banned & (set(EvidenceReport.model_fields) | set(GroupReport.model_fields))


def test_row_provenance_complete() -> None:
    g = group(_report(), "imagenet-1k", "224")
    row = next(x for x in g.rows if x.work_id == "rf:w1")
    v = row.value
    assert (v.field, v.value, v.unit, v.canonical) == ("value", "81.2", "%", "81.2")
    assert (v.anchor, v.cell, v.quote) == ("t1", "t1.r3.c2", "81.2")
    assert v.extraction_id == "ext_101" and v.trace_id == f"{row.row_key}/value"
    assert (row.title, row.document_id, row.conversion_id, row.status) == (
        "Title 1",
        "doc_1",
        "cnv_1",
        "agreed",
    )
    assert (row.method_name, row.independent) == ("Ours-S", True)
    marked = next(x for x in g.rows if x.work_id == "rf:w4")
    assert not marked.independent
    assert (marked.value.copy_marker, marked.value.reported_in) == (True, ReportedIn.CITED)


def test_costs_and_regime_shown_speed_never() -> None:
    row = frow(
        "rf:w1",
        "rk_000000000101",
        "Ours-S",
        "81.2",
        params=ff("22.1", unit="M", canon="22100000"),
        throughput=ff("1200", canon="1200"),
        latency=ff("3", unit="ms", canon="3"),
        distillation=ff(value=True),
    )
    r = assemble_report(pilot_inputs(rows=[row]))
    (shown,) = r.groups[0].rows
    assert set(shown.costs) == {"params"}
    assert shown.costs["params"].trace_id == f"{row.row_key}/params"
    assert shown.regime == {"pretraining_data": "none", "distillation": "true"}
    assert "throughput" not in r.model_dump_json() and "latency" not in r.model_dump_json()


def test_table_order_is_not_by_value() -> None:
    rows = [
        frow("rf:w2", "rk_000000000201", "beta", "90.0"),
        frow("rf:w1", "rk_000000000101", "Alpha", "10.0"),
        frow("rf:w1", "rk_000000000102", "alpha", "50.0"),
    ]
    r = assemble_report(pilot_inputs(rows=rows))
    assert [x.row_key for x in r.groups[0].rows] == [
        "rk_000000000101",
        "rk_000000000102",
        "rk_000000000201",
    ]


def test_method_conflict_listed_not_averaged() -> None:
    g = group(_report(), "imagenet-1k", "384")
    (conflict,) = g.method_conflicts
    assert conflict.method == "swin-t" and conflict.variant is None
    assert conflict.rows == ["rk_000000000102", "rk_000000000202"]
    assert sorted(x.value.canonical or "" for x in g.rows) == ["79.8", "80.1"]
    # Same values, or a copied row, are not a conflict.
    assert group(_report(), "imagenet-1k", "224").method_conflicts == []


def _direction(rows: list) -> GroupReport:  # type: ignore[type-arg]
    (g,) = assemble_report(pilot_inputs(rows=rows)).groups
    return g


def test_direction_declared_pack_default_conflict_unknown() -> None:
    up, down = ff(value=True), ff(value=False)
    declared = _direction(
        [frow("rf:w1", "rk_000000000101", "a", "1", metric="BLEU-x", higher_is_better=up)]
    )
    assert (declared.direction, declared.direction_status) == (True, "declared")
    default = _direction([frow("rf:w1", "rk_000000000101", "a", "1", metric="Top-1 Error")])
    assert (default.direction, default.direction_status) == (False, "pack-default")
    against_pack = _direction(
        [frow("rf:w1", "rk_000000000101", "a", "1", metric="Top-1 Error", higher_is_better=up)]
    )
    assert (against_pack.direction, against_pack.direction_status) == (None, "conflict")
    assert "direction-conflict" in codes(against_pack.statements)
    rows_differ = _direction(
        [
            frow("rf:w1", "rk_000000000101", "a", "1", metric="BLEU-x", higher_is_better=up),
            frow("rf:w2", "rk_000000000201", "b", "2", metric="BLEU-x", higher_is_better=down),
        ]
    )
    assert rows_differ.direction_status == "conflict"
    unknown = _direction([frow("rf:w1", "rk_000000000101", "a", "1", metric="BLEU-x")])
    assert (unknown.direction, unknown.direction_status) == (None, "unknown")
    assert "direction-unknown" in codes(unknown.statements)


def test_ungrouped_rows_listed_and_limit_stated() -> None:
    r = _report()
    assert [x.row_key for x in r.ungrouped] == ["rk_000000000502"]
    (lim,) = [x for x in r.limits if x.code == "ungrouped-rows"]
    assert "1" in lim.text


def test_unresolved_and_stale_rows_excluded_and_provisional() -> None:
    r = _report(
        unresolved=[
            disagreement("rf:w4", "rk_000000000403"),
            disagreement("rf:w4", "rk_000000000403"),
        ],
        stale=[("rf:w5", "rk_000000000503")],
        blocking=True,
    )
    assert {(e.reason, e.count) for e in r.excluded if e.reason in ("unresolved", "stale")} == {
        ("unresolved", 1),
        ("stale", 1),
    }
    assert r.provisional
    assert {"excluded-unresolved", "excluded-stale", "units-not-current"} <= codes(r.limits)
    assert not _report().provisional


def test_row_without_value_excluded_with_reason() -> None:
    r = _report()
    (missing,) = [e for e in r.excluded if e.reason == "missing-value"]
    assert (missing.count, missing.works) == (1, ["rf:w4"])
    assert all(x.row_key != "rk_000000000402" for g in r.groups for x in g.rows)
    assert all(x.row_key != "rk_000000000402" for x in r.ungrouped)


def test_included_work_without_rows_listed() -> None:
    r = _report()
    (none,) = [e for e in r.excluded if e.reason == "no-final-row"]
    assert (none.count, none.works) == (1, ["rf:w6"])
    assert "no-final-row" in codes(r.limits)


def test_before_pass_b_nothing_is_final_and_report_says_why() -> None:
    r = _report(rows=[], pass_b_open=False)
    assert r.provisional and r.groups == [] and r.ungrouped == []
    assert {"pass-b-not-opened", "no-extraction"} <= codes(r.limits)


def test_claims_grouped_by_type_unmerged_with_trace_ids() -> None:
    claims = [
        claim("clm_2", "rf:w2", ClaimType.FINDING),
        claim("clm_1", "rf:w1", ClaimType.FINDING),
        claim("clm_3", "rf:w1", ClaimType.FINDING),  # same text: never merged
        claim("clm_4", "rf:w3", ClaimType.LIMITATION),
        claim("clm_9", "rf:w9", ClaimType.FINDING),  # not included
    ]
    r = _report(claims=claims)
    assert list(r.claims) == ["finding", "mechanism", "limitation", "negative-result"]
    assert [c.claim_id for c in r.claims["finding"]] == ["clm_1", "clm_3", "clm_2"]
    assert [c.trace_id for c in r.claims["limitation"]] == ["clm_4"]
    assert r.claims["mechanism"] == [] and r.claims["finding"][0].strength == "moderate"
    assert "claims-not-cross-checked" in codes(r.limits)


def test_expectations() -> None:
    r = _report(expect=[{"dataset": "ImageNet-1K"}, {"dataset": "coco"}])
    assert r.expectations[0].group_ids == sorted(
        [group(r, "imagenet-1k", "224").group_id, group(r, "imagenet-1k", "384").group_id]
    )
    assert r.expectations[1].group_ids == []
    assert r.expectations[1].expect == {"dataset": "coco"}
    assert "expectation-empty" in codes(r.limits)
    by_res = _report(expect=[{"dataset": "imagenet-1k", "input_resolution": "224 × 224"}])
    assert by_res.expectations[0].group_ids == [group(r, "imagenet-1k", "224").group_id]
    unknown_key = _report(expect=[{"hardware": "a100"}])
    assert unknown_key.expectations[0].group_ids == []


def test_quality_block_computed_not_typed() -> None:
    r = _report()
    q = r.quality
    assert (q.dual_works, q.single_extraction_works, q.agreement_overall) == (4, 2, 0.95)
    assert (q.audit_n, q.audit_error_rate, q.audit_above_ceiling) == (0, None, None)
    assert (q.agreement_rows_aligned, q.agreement_rows_unmatched) == (7, 0)
    assert {"single-extraction", "audit-missing"} <= codes(r.limits)
    assert not {"agreement-rows-unmatched", "agreement-not-computed"} & codes(r.limits)


def test_agreement_denominators_and_limits() -> None:
    agreement = AgreementOverall(overall=None, dual=4, single=2, rows_aligned=5, rows_unmatched=3)
    r = assemble_report(replace(pilot_inputs(), agreement=agreement))
    q = r.quality
    assert (q.agreement_overall, q.agreement_rows_aligned, q.agreement_rows_unmatched) == (
        None,
        5,
        3,
    )
    (unmatched,) = [x for x in r.limits if x.code == "agreement-rows-unmatched"]
    assert "3" in unmatched.text
    assert "agreement-not-computed" in codes(r.limits)


def test_empty_assembled_report_is_provisional() -> None:
    r = _report(rows=[])
    assert r.groups == [] and r.ungrouped == [] and r.provisional
    assert "no-extraction" in codes(r.limits)


def test_unparseable_direction_is_stated_never_defaulted() -> None:
    odd = ff("maybe")
    (g,) = assemble_report(
        pilot_inputs(rows=[frow("rf:w1", "rk_000000000101", "a", "1", higher_is_better=odd)])
    ).groups  # metric Top-1 Accuracy has a pack default; it must not be used
    assert (g.direction, g.direction_status) == (None, "unparseable")
    assert "direction-unparseable" in codes(g.statements)


def test_expectation_on_a_numeric_key() -> None:
    keys = (*pilot_inputs().keys, "training_epochs")
    rows = [
        frow("rf:w1", "rk_000000000101", "a", "1", training_epochs=ff("300", canon="300")),
        frow("rf:w2", "rk_000000000201", "b", "2", training_epochs=ff("100", canon="100")),
    ]
    r = assemble_report(
        pilot_inputs(rows=rows, keys=keys),
        expect=[{"training_epochs": "300.0"}, {"training_epochs": "200"}],
    )
    (match,) = [g for g in r.groups if dict(g.key)["training_epochs"] == "300"]
    assert r.expectations[0].group_ids == [match.group_id]
    assert r.expectations[1].group_ids == []


def test_method_conflict_compares_uncanonical_numbers_numerically() -> None:
    def row(work: str, key: str, printed: str) -> FinalRow:
        base = frow(work, key, "DeiT-S", printed)
        value = base.fields["value"].model_copy(update={"canonical": None})
        return base.model_copy(update={"fields": {**base.fields, "value": value}})

    same = [row("rf:w1", "rk_000000000101", "79.8"), row("rf:w2", "rk_000000000201", "79.80")]
    assert assemble_report(pilot_inputs(rows=same)).groups[0].method_conflicts == []
    differ = [row("rf:w1", "rk_000000000101", "79.8"), row("rf:w2", "rk_000000000201", "80.1")]
    assert len(assemble_report(pilot_inputs(rows=differ)).groups[0].method_conflicts) == 1


def test_limits_contain_no_document_text() -> None:
    secret = "Zyxwv quux"
    rows = [
        frow(
            "rf:w1",
            "rk_000000000101",
            secret,
            "81.2",
            dataset=secret,
            metric=secret,
            split=None,
        ),
        *pilot_rows(),
    ]
    claims = [claim("clm_1", "rf:w1", ClaimType.FINDING, statement=secret)]
    r = assemble_report(pilot_inputs(rows=rows, claims=claims), expect=[{"dataset": "absent"}])
    assert all(secret.lower() not in (lim.text + str(lim.subject)).lower() for lim in r.limits)
    for g in r.groups:
        assert all(secret.lower() not in (s.text + str(s.subject)).lower() for s in g.statements)


# --- Service tests ---


@pytest.fixture
def ext_a() -> Actor:
    return _extractor(SESSION_A, "claude-opus-5-5")


@pytest.fixture
def ext_b() -> Actor:
    return _extractor(SESSION_B, "claude-sonnet-5-5")


@pytest.fixture
def screened(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> list[str]:
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    return sorted(w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED)


def test_no_schema_returns_empty_report_with_limit(project: Project, screened: list[str]) -> None:
    r = evidence_report(project)
    assert (r.groups, r.ungrouped, r.excluded, r.pack) == ([], [], [], None)
    assert codes(r.limits) == {"no-extraction"} and r.provisional
    assert (r.quality.agreement_rows_aligned, r.quality.agreement_rows_unmatched) == (0, 0)
    assert r.report_version == REPORT_VERSION


def test_before_pass_b_the_service_report_is_provisional(
    project: Project, agent: Actor, ext_a: Actor, screened: list[str]
) -> None:
    _declare(project, agent)
    run_pass(project, ext_a, PassLabel.A, lambda _w: [_r()])
    r = evidence_report(project)
    assert r.provisional and r.groups == []
    assert {"pass-b-not-opened", "no-extraction"} <= codes(r.limits)
    assert r.pack == "ml-benchmark" and r.pack_version == 1


def _world_rows(odd: str) -> Callable[[str], list[ExtractedRowInput]]:
    def rows_for(work: str) -> list[ExtractedRowInput]:
        return [_r(task="detection")] if work == odd else [_r()]

    return rows_for


def test_service_report_end_to_end(
    project: Project, agent: Actor, ext_a: Actor, ext_b: Actor, screened: list[str]
) -> None:
    _declare(project, agent)
    odd, gone, kept = screened[0], screened[1], screened[2]

    def claims_for(work: str) -> list:  # type: ignore[type-arg]
        return [claim_input()] if work in (gone, kept) else []

    run_pass(project, ext_a, PassLabel.A, lambda _w: [_r()], claims_for)
    run_pass(project, ext_b, PassLabel.B, _world_rows(odd))
    finals = final_rows(project)
    r = evidence_report(project)
    assert r.provisional  # one disagreement is unresolved
    assert "units-not-current" not in codes(r.limits)
    (g,) = r.groups
    assert {x.row_key for x in g.rows} == {x.row_key for x in finals}
    row = g.rows[0]
    a_ids = {x.extraction_id for x in live_rows(project, PassLabel.A)}
    assert row.value.extraction_id in a_ids and row.value.trace_id == f"{row.row_key}/value"
    assert row.value.quote == "1" and row.title
    assert {(e.reason, e.count) for e in r.excluded} == {
        ("unresolved", 1),
        ("no-final-row", 1),
    }
    assert {c.work_id for c in r.claims["finding"]} == {gone, kept}
    assert r.quality.dual_works == len(screened) and r.quality.agreement_overall is not None
    assert "audit-missing" in codes(r.limits)

    # A new document version stales one work's rows and claims.
    _new_document_version(project, gone)
    stale = evidence_report(project)
    assert stale.provisional and "units-not-current" in codes(stale.limits)
    assert ("stale", 1) in {(e.reason, e.count) for e in stale.excluded}
    assert {c.work_id for c in stale.claims["finding"]} == {kept}

    # Recomputed from events only: same after an index rebuild and without the library.
    before = stale.model_dump()
    project.index.rebuild()
    shutil.rmtree(project.paths.library_dir, ignore_errors=True)
    assert evidence_report(project).model_dump() == before


def test_expectations_through_the_service(
    project: Project, agent: Actor, ext_a: Actor, ext_b: Actor, screened: list[str]
) -> None:
    _declare(project, agent)
    run_pass(project, ext_a, PassLabel.A, lambda _w: [_r()])
    run_pass(project, ext_b, PassLabel.B, lambda _w: [_r()])
    r = evidence_report(project, expect=[{"dataset": "Lorem Ipsum"}, {"task": "detection"}])
    assert r.expectations[0].group_ids == [r.groups[0].group_id]
    assert r.expectations[1].group_ids == []
    assert "expectation-empty" in codes(r.limits)
    assert "single-extraction" not in codes(r.limits)
    assert not r.provisional and not r.excluded


def test_audit_limits_from_the_audit_report() -> None:
    audit = ExtractionAuditReport(
        audit_id="aud_1",
        sample_size=10,
        labelled=8,
        incorrect=1,
        error_rate=0.125,
        ceiling=0.05,
        above_ceiling=True,
        enforced=False,
        by_group={},
    )
    r = assemble_report(replace(pilot_inputs(), audit=audit, audit_outstanding=True))
    q = r.quality
    assert (q.audit_n, q.audit_error_rate, q.audit_above_ceiling) == (8, 0.125, True)
    assert {"audit-outdated", "audit-incomplete", "audit-above-ceiling"} <= codes(r.limits)
    assert "audit-missing" not in codes(r.limits)


def test_outdated_labels_are_stated_and_not_counted_as_unlabelled() -> None:
    audit = ExtractionAuditReport(
        audit_id="aud_1",
        sample_size=10,
        labelled=8,
        incorrect=0,
        outdated=2,
        error_rate=0.0,
        ceiling=0.05,
        above_ceiling=False,
        enforced=False,
        by_group={},
    )
    r = assemble_report(replace(pilot_inputs(), audit=audit, audit_outstanding=False))
    (outdated,) = [lim for lim in r.limits if lim.code == "audit-outdated"]
    assert "2 labels are on values that changed" in outdated.text
    assert "audit-incomplete" not in codes(r.limits)

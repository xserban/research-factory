"""`check` findings, methods statement and agent view of the evidence report (plan E, task 7).

The report is synthetic (`pilot_inputs`) and injected where the service would compute it; the
absent cases run on a project without an extraction schema.
"""

from collections.abc import Callable, Mapping

import pytest

from factory.events.envelope import Actor
from factory.model.project import RigorMode
from factory.model.protocol import ScreeningStage
from factory.services import check as check_module
from factory.services import methods as methods_module
from factory.services.agreement import Outcome, final_outcomes
from factory.services.check import Finding, _findings_as, check
from factory.services.context import Project
from factory.services.evidence_report import (
    EvidenceReport,
    Limit,
    assemble_report,
    evidence_report,
)
from factory.services.methods import methods_report, render_methods
from factory.sources.registry import SourceFactory
from tests.evidence_helpers import disagreement, frow, pilot_inputs, pilot_rows
from tests.test_acceptance_fulltext_screening import _screened_full_text_world
from tests.test_extraction_agreement import _declare

FT = ScreeningStage.FULL_TEXT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
CODES = ("evidence-excluded-rows", "evidence-ungrouped", "evidence-direction")
MODES = (RigorMode.EXPLORATORY, RigorMode.PILOT, RigorMode.SYSTEMATIC)


def _inject(monkeypatch: pytest.MonkeyPatch, report: EvidenceReport) -> None:
    monkeypatch.setattr(check_module, "evidence_report", lambda _p: report)
    monkeypatch.setattr(methods_module, "evidence_report", lambda _p: report)


def _hit(project: Project, code: str, mode: RigorMode = RigorMode.PILOT) -> Finding | None:
    found = [f for f in _findings_as(project, mode) if f.code == code]
    assert len(found) <= 1
    return found[0] if found else None


def _clean() -> EvidenceReport:
    rows = [
        r
        for r in pilot_rows()
        if r.row_key not in ("rk_000000000502", "rk_000000000402")  # ungrouped, no value
    ]
    return assemble_report(pilot_inputs(rows))


@pytest.fixture
def world(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> list[str]:
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    _declare(project, agent)
    return sorted(w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED)


# --- check ---


def test_no_evidence_findings_without_schema(project: Project) -> None:
    assert not any(f.code in CODES for f in _findings_as(project, RigorMode.PILOT))


def test_evidence_excluded_rows_positive(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    report = assemble_report(
        pilot_inputs(
            unresolved=[disagreement("rf:w1", "rk_000000000101")], stale=[("rf:w2", "rk_x")]
        )
    )
    _inject(monkeypatch, report)
    for mode in MODES:
        hit = _hit(project, "evidence-excluded-rows", mode)
        assert hit is not None and hit.severity == "warning"
    hit = _hit(project, "evidence-excluded-rows")
    assert hit is not None
    assert "rf:w1" in hit.refs and "rf:w2" in hit.refs


def test_evidence_excluded_rows_absent(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    _inject(monkeypatch, _clean())
    assert _hit(project, "evidence-excluded-rows") is None


def test_evidence_ungrouped_positive(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    _inject(monkeypatch, assemble_report(pilot_inputs()))
    for mode in MODES:
        hit = _hit(project, "evidence-ungrouped", mode)
        assert hit is not None and hit.severity == "warning"
    hit = _hit(project, "evidence-ungrouped")
    assert hit is not None and "1 row(s)" in hit.message


def test_evidence_ungrouped_absent(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    _inject(monkeypatch, _clean())
    assert _hit(project, "evidence-ungrouped") is None


def test_evidence_direction_positive(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        *_clean_rows(),
        frow("rf:w5", "rk_000000000503", "X", "1.0", dataset="Obscure", metric="Weirdness"),
    ]
    report = assemble_report(pilot_inputs(rows))
    bad = [g.group_id for g in report.groups if g.direction_status in ("unknown", "conflict")]
    assert bad
    _inject(monkeypatch, report)
    for mode in MODES:
        hit = _hit(project, "evidence-direction", mode)
        assert hit is not None and hit.severity == "warning"
    hit = _hit(project, "evidence-direction")
    assert hit is not None and hit.refs == sorted(bad)


def _clean_rows() -> list:  # type: ignore[type-arg]
    return [r for r in pilot_rows() if r.row_key not in ("rk_000000000502", "rk_000000000402")]


def test_evidence_direction_absent(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    _inject(monkeypatch, _clean())
    assert _hit(project, "evidence-direction") is None


def test_check_findings_name_no_document_text(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        *pilot_rows(),
        frow("rf:w5", "rk_000000000503", "X", "1.0", dataset="Obscure", metric="Weirdness"),
    ]
    report = assemble_report(
        pilot_inputs(rows, unresolved=[disagreement("rf:w1", "rk_000000000101")])
    )
    _inject(monkeypatch, report)
    texts = [
        f.message + " ".join(f.refs)
        for f in _findings_as(project, RigorMode.PILOT)
        if f.code in CODES
    ]
    assert len(texts) == 3
    banned = ("ImageNet", "DeiT", "Swin", "Top-1", "Ours", "Title", "81.2", "79.8")
    for t in texts:
        assert not any(b in t for b in banned), t
    assert "rank" not in " ".join(texts).lower()


def test_evidence_report_called_once_per_check(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    report = _clean()

    def fake(_p: Project) -> EvidenceReport:
        calls.append(1)
        return report

    monkeypatch.setattr(check_module, "evidence_report", fake)
    monkeypatch.setattr(methods_module, "evidence_report", lambda _p: report)
    check(project)
    assert len(calls) == 1


# --- methods ---


def test_methods_without_schema_unchanged(project: Project) -> None:
    report = methods_report(project)
    assert report.evidence_groups == 0 and report.evidence_rows == 0
    assert report.evidence_comparability_keys == [] and report.evidence_frontier_costs == []
    assert "Evidence" not in render_methods(report)


def test_methods_counts_equal_report_counts(
    project: Project, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _clean()
    _inject(monkeypatch, report)
    m = methods_report(project)
    assert m.evidence_groups == len(report.groups)
    assert m.evidence_rows == sum(len(g.rows) for g in report.groups)
    assert m.evidence_independent == sum(g.counts.independent for g in report.groups)
    assert m.evidence_copied == sum(g.counts.copied for g in report.groups)
    assert m.evidence_multi_source_groups == sum(
        1 for g in report.groups if g.counts.independent_works > 1
    )
    assert m.evidence_comparability_keys == report.comparability_keys
    assert m.evidence_independent + m.evidence_copied == m.evidence_rows
    assert m.evidence_groups > 0 and m.evidence_copied > 0
    assert f"{m.evidence_groups} group" in render_methods(m)


def test_methods_text_states_cost_axes_and_no_ranking(
    project: Project, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _inject(monkeypatch, _clean())
    text = render_methods(methods_report(project))
    assert "never ranked across groups" in text
    assert "not counted as independent" in text
    assert "params, FLOPs and MACs" in text
    assert "within-paper ratios" in text


def test_methods_evidence_real_service_on_world(project: Project, world: list[str]) -> None:
    m = methods_report(project)
    r = evidence_report(project)
    assert m.evidence_groups == len(r.groups)


# --- agent view ---


def _audited() -> EvidenceReport:
    report = _clean()
    quality = report.quality.model_copy(
        update={"audit_error_rate": 0.25, "audit_above_ceiling": True, "audit_n": 8}
    )
    limit = Limit(
        code="audit-above-ceiling", text="The audit error rate is above the ceiling.", subject="a1"
    )
    return report.model_copy(update={"quality": quality, "limits": [*report.limits, limit]})


def test_agent_view_hides_audit_rate_and_flag() -> None:
    from factory.services.evidence_report import agent_evidence

    view = agent_evidence(_audited())
    assert view.quality.audit_error_rate is None
    assert view.quality.audit_above_ceiling is None
    assert view.quality.audit_n == 8
    codes = [lim.code for lim in view.limits]
    assert "audit-above-ceiling" not in codes
    assert "audit-reported-to-researcher" in codes
    assert "0.25" not in view.model_dump_json()
    assert len(view.limits) == len(_audited().limits)


def test_cli_view_shows_audit_rate() -> None:
    report = _audited()
    assert report.quality.audit_error_rate == 0.25
    assert report.quality.audit_above_ceiling is True
    assert "audit-above-ceiling" in [lim.code for lim in report.limits]

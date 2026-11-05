"""`check` findings, `trace` nodes and the methods statement of extraction (plan D, task 10).

Findings carry identifiers, counts and fixed text only, never a field value or a quote. The audit
findings (`extraction-audit-missing`, `extraction-error-high`) and the audit figures of the methods
statement are wired to the audit service (task 9).
"""

from collections.abc import Callable, Mapping

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.extraction import AuditItemRef, ReportedIn
from factory.model.project import RigorMode
from factory.model.protocol import ScreeningStage
from factory.model.screening import Channel, PassLabel
from factory.services import check as check_module
from factory.services import extraction_audit as ea
from factory.services.agreement import Outcome, final_outcomes
from factory.services.check import (
    LEVELS,
    CheckReport,
    Finding,
    _findings_as,
    agent_check,
    agent_view,
    check,
)
from factory.services.context import Project
from factory.services.document_read import default_conversion
from factory.services.extraction import (
    ExtractionRow,
    extract_next,
    extract_record,
    live_rows,
    pass_config,
)
from factory.services.extraction_agreement import extraction_agreement, resolve_extraction
from factory.services.extraction_audit import (
    extraction_audit_record,
    extraction_audit_sample,
)
from factory.services.methods import agent_methods, methods_report, render_methods
from factory.services.trace import TraceNode, trace
from factory.sources.registry import SourceFactory
from tests.document_helpers import StubConverter, make_registry, run_convert
from tests.extraction_helpers import (
    SESSION_A,
    SESSION_B,
    _amend_schema,
    _both,
    _claim,
    _declare,
    _extractor,
    _r,
    _run,
    _same_rows,
)
from tests.test_acceptance_fulltext_screening import _screened_full_text_world

pytestmark = pytest.mark.slow  # over ~60 s per file: dev runs deselect with -m "not slow"

FT = ScreeningStage.FULL_TEXT
SourcesFor = Callable[..., Mapping[str, SourceFactory]]
MODES = (RigorMode.EXPLORATORY, RigorMode.PILOT, RigorMode.SYSTEMATIC)


@pytest.fixture
def ext_a() -> Actor:
    return _extractor(SESSION_A, "claude-opus-5-5")


@pytest.fixture
def ext_b() -> Actor:
    return _extractor(SESSION_B, "claude-sonnet-5-5")


@pytest.fixture
def world(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> list[str]:
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    _declare(project, agent)
    return sorted(w for w, o in final_outcomes(project, stage=FT).items() if o is Outcome.INCLUDED)


def _hit(project: Project, code: str, mode: RigorMode = RigorMode.SYSTEMATIC) -> Finding | None:
    found = [f for f in _findings_as(project, mode) if f.code == code]
    assert len(found) <= 1
    return found[0] if found else None


def _severities(project: Project, code: str) -> list[str | None]:
    out: list[str | None] = []
    for mode in MODES:
        found = _hit(project, code, mode)
        out.append(None if found is None else found.severity)
    return out


# --- check ---


def test_pending_present_then_absent(
    project: Project, agent: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    found = _hit(project, "extraction-pending")
    assert found is not None and found.refs == world
    assert _severities(project, "extraction-pending") == ["warning"] * 3
    _both(project, ext_a, ext_b)
    assert _hit(project, "extraction-pending") is None
    fields = ("method_name", "task", "dataset", "split", "metric", "value", "hardware")
    _amend_schema(project, agent, fields=fields)
    stale = _hit(project, "extraction-pending")
    assert stale is not None and stale.refs == world  # stale units are pending again


def test_no_extraction_findings_without_schema(
    project: Project, agent: Actor, agent_other: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    assert [f.code for f in check(project).findings if f.code.startswith("extraction-")] == []


def test_single_lists_works_outside_the_dual_sample(
    project: Project, agent: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    assert _hit(project, "extraction-single") is None  # every work is dual
    _declare(project, agent, fraction=1e-9)
    _both(project, ext_a, ext_b)
    assert pass_config(project, PassLabel.B) is not None
    found = _hit(project, "extraction-single")
    assert found is not None and found.refs == world
    assert _severities(project, "extraction-single") == [None, "warning", "error"]


def test_unresolved_present_then_resolved(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _run(project, ext_a, PassLabel.A, _same_rows)
    _run(project, ext_b, PassLabel.B, lambda w: [_r("2", "t1.r3.c3") if w == odd else _r()])
    found = _hit(project, "extraction-unresolved")
    assert found is not None and found.refs == [odd]
    assert _severities(project, "extraction-unresolved") == [None, "warning", "error"]
    for d in extraction_agreement(project, human).disagreements:
        assert d.work_id == odd
        resolve_extraction(project, human, odd, d.row_key, None, "neither", "dup", Channel.CLI)
    assert _hit(project, "extraction-unresolved") is None


def test_schema_stale_lists_stale_rows(
    project: Project, agent: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    assert _hit(project, "extraction-schema-stale") is None
    fields = ("method_name", "task", "dataset", "split", "metric", "value", "hardware")
    _amend_schema(project, agent, fields=fields)
    found = _hit(project, "extraction-schema-stale")
    assert found is not None
    assert found.refs == sorted(r.extraction_id for r in live_rows(project))
    assert _severities(project, "extraction-schema-stale") == ["warning"] * 3


def test_library_missing_names_the_pinned_conversion(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    assert _hit(project, "extraction-library-missing") is None
    pinned = default_conversion(project, world[0])
    assert pinned is not None
    with project.index.connect() as conn:
        markdown = conn.execute(
            text("SELECT markdown_hash FROM document_conversions WHERE conversion_id = :c"),
            {"c": pinned.conversion_id},
        ).scalar_one()
    project.library.path(str(markdown)).unlink()
    found = _hit(project, "extraction-library-missing")
    assert found is not None and pinned.conversion_id in found.refs
    assert _severities(project, "extraction-library-missing") == ["warning"] * 3


def test_document_stale_on_a_newer_conversion(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    assert _hit(project, "extraction-document-stale") is None
    run_convert(project, make_registry(StubConverter(version="9.9+later")))
    found = _hit(project, "extraction-document-stale")
    assert found is not None and found.refs == world
    assert _hit(project, "extraction-schema-stale") is None  # a newer conversion only warns
    assert _severities(project, "extraction-document-stale") == ["warning"] * 3


def test_copy_flag_when_a_marker_contradicts_own(
    project: Project, monkeypatch: pytest.MonkeyPatch, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    assert _hit(project, "extraction-copy-flag") is None
    real = live_rows

    def marked(project: Project) -> list[ExtractionRow]:
        out = real(project)
        first = out[0]
        fields = {
            name: f.model_copy(update={"copy_marker": True}) for name, f in first.fields.items()
        }
        return [first.model_copy(update={"fields": fields}), *out[1:]]

    monkeypatch.setattr(check_module, "live_rows", marked)
    found = _hit(project, "extraction-copy-flag")
    assert found is not None and len(found.refs) == 1
    assert _severities(project, "extraction-copy-flag") == ["warning"] * 3

    def cited(project: Project) -> list[ExtractionRow]:
        out = real(project)
        first = out[0]
        fields = {
            name: f.model_copy(update={"copy_marker": True, "reported_in": ReportedIn.CITED})
            for name, f in first.fields.items()
        }
        return [first.model_copy(update={"fields": fields}), *out[1:]]

    monkeypatch.setattr(check_module, "live_rows", cited)
    assert _hit(project, "extraction-copy-flag") is None  # a declared citation is no contradiction


def test_copy_flag_ignores_a_stale_row(
    project: Project,
    monkeypatch: pytest.MonkeyPatch,
    agent: Actor,
    ext_a: Actor,
    ext_b: Actor,
    world: list[str],
) -> None:
    _both(project, ext_a, ext_b)
    fields = ("method_name", "task", "dataset", "split", "metric", "value", "hardware")
    _amend_schema(project, agent, fields=fields)  # every row is now stale
    real = live_rows

    def marked(project: Project) -> list[ExtractionRow]:
        out = real(project)
        first = out[0]
        marks = {
            name: f.model_copy(update={"copy_marker": True}) for name, f in first.fields.items()
        }
        return [first.model_copy(update={"fields": marks}), *out[1:]]

    monkeypatch.setattr(check_module, "live_rows", marked)
    assert _hit(project, "extraction-copy-flag") is None


def test_agent_view_hides_error_rate() -> None:
    finding = Finding(
        code="extraction-error-high",
        severity="error",
        refs=["xau_01"],
        message="error rate 0.123 is above the ceiling 0.05",
    )
    report = CheckReport(mode=RigorMode.PILOT, evaluated_as=RigorMode.PILOT, findings=[finding])
    # The flag itself is withheld (decision 52): presence would reveal it.
    assert agent_view(report).findings == []
    assert agent_view(report).ok


def test_agent_view_states_a_labelled_audit_neutrally() -> None:
    finding = Finding(code="extraction-error-high", severity="error", refs=["xau_01"], message="x")
    above = CheckReport(mode=RigorMode.PILOT, evaluated_as=RigorMode.PILOT, findings=[finding])
    below = CheckReport(mode=RigorMode.PILOT, evaluated_as=RigorMode.PILOT, findings=[])
    shown_above = agent_view(above, labelled_audit="xau_01").findings
    shown_below = agent_view(below, labelled_audit="xau_01").findings
    assert shown_above == shown_below
    (neutral,) = shown_above
    assert (neutral.code, neutral.severity, neutral.refs) == (
        "extraction-audit-reported",
        "warning",
        ["xau_01"],
    )
    assert not any(ch.isdigit() for ch in neutral.message)


def _label_all(project: Project, human: Actor, monkeypatch: pytest.MonkeyPatch, wrong: int) -> str:
    items = [
        AuditItemRef(work_id="rf:w1", row_key="rk_0123456789ab", field=f"f{i:04d}")
        for i in range(40)
    ]
    monkeypatch.setattr(ea, "_population", lambda project: [(i, f"ext_{i.field}") for i in items])
    sampled = extraction_audit_sample(project, human, random_seed=5)
    for i, item in enumerate(sampled.items):
        extraction_audit_record(
            project,
            human,
            sampled.audit_id,
            item.work_id,
            item.row_key,
            item.field,
            i >= wrong,
            "",
            Channel.CLI,
        )
    return sampled.audit_id


def test_audit_missing_until_drawn(
    project: Project,
    human: Actor,
    monkeypatch: pytest.MonkeyPatch,
    ext_a: Actor,
    ext_b: Actor,
    world: list[str],
) -> None:
    _both(project, ext_a, ext_b)
    found = _hit(project, "extraction-audit-missing")
    assert found is not None and found.refs == []
    assert found.message == "extraction audit not drawn for the current agreed values"
    assert _severities(project, "extraction-audit-missing") == [None, "warning", "error"]
    _label_all(project, human, monkeypatch, 0)
    assert _hit(project, "extraction-audit-missing") is None


def test_error_high_severity_and_agent_view(
    project: Project,
    human: Actor,
    monkeypatch: pytest.MonkeyPatch,
    ext_a: Actor,
    ext_b: Actor,
    world: list[str],
) -> None:
    _both(project, ext_a, ext_b)
    audit_id = _label_all(project, human, monkeypatch, 3)  # 3 of 40 = 0.075 > 0.05
    found = _hit(project, "extraction-error-high")
    assert found is not None and found.refs == [audit_id]
    assert "0.075" not in found.message and "0.05" not in found.message
    assert _severities(project, "extraction-error-high") == [None, "warning", "error"]
    # The fixture project is a pilot: not an error under its own mode.
    report = check(project)
    assert [f.severity for f in report.findings if f.code == "extraction-error-high"] == ["warning"]
    assert not any(ch.isdigit() for ch in found.message)
    codes = [f.code for f in agent_check(project).findings]
    assert "extraction-error-high" not in codes
    assert codes.count("extraction-audit-reported") == 1
    assert "0.075" not in agent_check(project).model_dump_json()
    text = render_methods(methods_report(project))
    assert "0.075 over 40 labelled values" in text
    assert methods_report(project).extraction_audit_n == 40


def test_error_high_absent_below_ceiling(
    project: Project,
    human: Actor,
    monkeypatch: pytest.MonkeyPatch,
    ext_a: Actor,
    ext_b: Actor,
    world: list[str],
) -> None:
    _both(project, ext_a, ext_b)
    _label_all(project, human, monkeypatch, 1)  # 0.025
    assert _hit(project, "extraction-error-high") is None
    codes = [f.code for f in agent_check(project).findings]
    assert codes.count("extraction-audit-reported") == 1


def test_agent_check_findings_do_not_depend_on_the_ceiling_flag(
    project: Project,
    human: Actor,
    monkeypatch: pytest.MonkeyPatch,
    ext_a: Actor,
    ext_b: Actor,
    world: list[str],
) -> None:
    _both(project, ext_a, ext_b)
    before = [f.code for f in agent_check(project).findings]
    assert "extraction-audit-reported" not in before  # no labelled audit yet
    _label_all(project, human, monkeypatch, 3)  # above the ceiling
    above = agent_check(project)
    below = agent_check(project).model_copy(
        update={
            "findings": [f for f in check(project).findings if f.code != "extraction-error-high"]
        }
    )
    assert [f.code for f in above.findings] == [
        f.code for f in agent_view(below, labelled_audit=above.findings[-1].refs[0]).findings
    ]
    assert above.ok == agent_view(below, labelled_audit=above.findings[-1].refs[0]).ok
    for mode in MODES:
        promoted = agent_check(project, promote_to=mode)
        assert "extraction-error-high" not in [f.code for f in promoted.findings]


def test_audit_levels_are_declared() -> None:
    assert LEVELS["extraction-audit-missing"] == (None, "warning", "error")
    assert LEVELS["extraction-error-high"] == (None, "warning", "error")


def test_findings_never_carry_document_text(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    _run(project, ext_a, PassLabel.A, _same_rows)
    for f in check(project).findings:
        if f.code.startswith("extraction-"):
            assert "Lorem" not in f.message


# --- trace ---


def _walk(node: TraceNode) -> dict[str, str]:
    out = {node.id: node.kind}
    for child in node.children:
        out.update(_walk(child))
    return out


def test_trace_extraction_back_reaches_question(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    row = live_rows(project, PassLabel.A, work_id=world[0])[0]
    tree = trace(project, row.extraction_id)
    assert tree.kind == "extraction"
    ids = _walk(tree)
    assert {
        "anchor",
        "conversion",
        "document",
        "attempt",
        "work",
        "decision",
        "protocol",
        "question",
    } <= set(ids.values())
    assert ids[f"{row.conversion_id}/t1"] == "anchor"


def test_trace_cell_forward_lists_extractions(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    rows = live_rows(project, work_id=world[0])
    tree = trace(project, f"{rows[0].conversion_id}/t1.r3.c2", direction="forward")
    assert tree.kind == "anchor"
    assert {c.id for c in tree.children if c.kind == "extraction"} == {
        r.extraction_id for r in rows
    }


def test_trace_claim_back_and_label_holds_no_text(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    batch = extract_next(project, ext_a, PassLabel.A).batch
    assert batch is not None
    res = extract_record(project, ext_a, batch.task_id, [_r()], [_claim()], finish=True)
    (claim_id,) = res.claims.written
    tree = trace(project, claim_id)
    assert tree.kind == "claim" and "method section" not in tree.label
    assert {"work", "protocol", "anchor", "question"} <= set(_walk(tree).values())


def test_trace_superseded_row_links_prior(project: Project, ext_a: Actor, world: list[str]) -> None:
    batch = extract_next(project, ext_a, PassLabel.A).batch
    assert batch is not None
    first = extract_record(project, ext_a, batch.task_id, [_r("1")])
    (old,) = first.rows.written
    second = extract_record(
        project, ext_a, batch.task_id, [_r("2", "t1.r3.c3")], finish=True, supersedes={0: old}
    )
    (new,) = second.rows.written
    assert old in _walk(trace(project, new))
    assert "(superseded)" in trace(project, old).label
    assert new in _walk(trace(project, old, direction="forward"))


# --- methods ---


def test_methods_without_schema_has_no_extraction_paragraph(project: Project) -> None:
    report = methods_report(project)
    assert report.extraction_pack is None and report.extraction_sessions == 0
    assert report.extraction_agreement is None and report.extraction_audit_n == 0
    assert "Extraction." not in render_methods(report)


def test_methods_states_extraction_plan_and_sessions(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    report = methods_report(project)
    assert report.extraction_pack == "ml-benchmark@1"
    assert "value" in report.extraction_fields
    assert (report.extraction_passes, report.extraction_sessions) == (2, 2)
    assert report.extraction_models == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert report.extraction_agreement == 1.0
    text = render_methods(report)
    assert "compared field values of aligned rows" in text
    assert "unmatched rows are reported separately" in text
    assert "Extraction. Data were extracted with the pack ml-benchmark@1" in text
    for limit in ("at most five author surnames", "79.8 ± 0.2", "`reproduced` is recorded"):
        assert limit in text
    shown, withheld = agent_methods(project, report)
    assert "extraction_error_rate" in withheld and shown.extraction_error_rate is None


def test_methods_agreement_none_while_tasks_open(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    assert extract_next(project, ext_a, PassLabel.A).batch is not None
    report = methods_report(project)
    assert report.extraction_agreement is None
    assert "Overall agreement of the passes: not computed" in render_methods(report)


def test_check_computes_each_shared_input_once(
    world: list[str], project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections import Counter

    from factory.services import agreement
    from factory.services.check import agent_check, check

    calls: Counter[str] = Counter()
    original = agreement.final_outcomes.__wrapped__  # type: ignore[attr-defined]

    def counting(proj: Project, *, stage: ScreeningStage = ScreeningStage.TITLE_ABSTRACT):  # type: ignore[no-untyped-def]
        calls[stage.value] += 1
        return original(proj, stage=stage)

    monkeypatch.setattr(agreement.final_outcomes, "__wrapped__", counting)
    expected = check(project)
    assert calls and max(calls.values()) == 1
    calls.clear()
    agent_check(project)
    assert calls and max(calls.values()) == 1
    # Nothing is cached across calls: a second check recomputes, with identical findings.
    calls.clear()
    assert check(project) == expected
    assert max(calls.values()) == 1

# ruff: noqa: F811
"""Acceptance of plan 2D at the service level (slice-2 acceptance 5-11 and 14 in part).

The world is that of `test_extraction_agreement`: the full-text screened corpus with a declared
ml-benchmark schema, whose pinned conversion has table `t1` (row `Lorem | 1 | 2`)."""

import subprocess
import sys
from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.extraction import ExtractedRowInput, FieldInput, ReportedIn
from factory.model.screening import Channel, PassLabel
from factory.services import extraction
from factory.services.context import Project
from factory.services.extraction import (
    extract_next,
    extract_record,
    in_dual_sample,
    live_rows,
    pass_config,
    stale_extractions,
)
from factory.services.extraction_agreement import (
    extraction_agreement,
    final_rows,
    grouped_rows,
    independence_counts,
    resolve_extraction,
)
from factory.services.extraction_audit import (
    EXTRACTION_ERROR_CEILING,
    agreed_values,
    extraction_audit_record,
    extraction_audit_report,
    extraction_audit_sample,
)
from factory.services.trace import TraceNode, trace
from tests.test_extraction_agreement import (  # noqa: F401
    FIELDS,
    _both,
    _declare,
    _r,
    _run,
    ext_a,
    ext_b,
    screened,
    world,
)

CH = Channel.CLI
TESTS = Path(__file__).parent


# --- 5: schema before extraction ---


def test_extraction_refused_without_schema_then_allowed(
    project: Project, agent: Actor, ext_a: Actor, screened: list[str]
) -> None:
    before = len(read_all(project.paths.events_dir, project.catalog))
    with pytest.raises(FactoryValidationError):
        extract_next(project, ext_a, PassLabel.A)
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
    _declare(project, agent)
    batch = extract_next(project, ext_a, PassLabel.A).batch
    assert batch is not None
    undeclared = {"hardware": FieldInput(value="GPU")}
    res = extract_record(project, ext_a, batch.task_id, [_r(**undeclared), _r()])
    assert [e.index for e in res.rows.rejected] == [0]
    assert res.rows.rejected[0].issues[0].field == "fields.hardware"
    assert len(res.rows.written) == 1


def test_schema_amendment_stales_affected_extractions(
    project: Project, agent: Actor, ext_a: Actor, world: list[str]
) -> None:
    _run(project, ext_a, PassLabel.A, lambda w: [_r()])
    assert stale_extractions(project) == set()
    live = {r.extraction_id for r in live_rows(project, PassLabel.A)}
    assert len(live) == len(world)
    _declare(project, agent, fields=(*FIELDS, "hardware"))
    assert stale_extractions(project) == live
    assert final_rows(project) == []  # stale rows never reach the final rows
    again = extract_next(project, ext_a, PassLabel.A).batch  # stale units are served again
    assert again is not None and "hardware" in [f["name"] for f in again.fields]


# --- 6, 7: number and cell checks ---


def test_number_check_rejects_and_batch_survives(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    batch = extract_next(project, ext_a, PassLabel.A).batch
    assert batch is not None
    res = extract_record(project, ext_a, batch.task_id, [_r("79.8"), _r("1"), _r("2", "t1.r3.c3")])
    assert [e.index for e in res.rows.rejected] == [0]
    assert res.rows.rejected[0].issues[0].field.startswith("fields.value")
    assert len(res.rows.written) == 2
    assert {r.fields["value"].value for r in live_rows(project, PassLabel.A)} == {"1", "2"}


def test_cell_anchor_resolves_to_one_cell_and_text_checked(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    batch = extract_next(project, ext_a, PassLabel.A).batch
    assert batch is not None
    res = extract_record(
        project,
        ext_a,
        batch.task_id,
        [_r("1", "t1.r9.c9"), _r("1", "t1.r3.c3"), _r("2", "t1.r3.c3")],
    )
    assert sorted(e.index for e in res.rows.rejected) == [0, 1]  # unknown cell; wrong cell text
    (row,) = live_rows(project, PassLabel.A)
    assert row.fields["value"].cell == "t1.r3.c3" and row.fields["value"].value == "2"


# --- 8: copied results ---


def test_copied_results_flagged_and_not_independent(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    cited = world[0]

    def rows_for(work: str) -> list[ExtractedRowInput]:
        return [_r(reported_in=ReportedIn.CITED)] if work == cited else [_r()]

    _both(project, ext_a, ext_b, a=rows_for, b=rows_for)
    finals = final_rows(project)
    assert {r.work_id for r in finals if not r.independent} == {cited}
    counts = independence_counts(finals)
    assert (counts.independent, counts.copied) == (len(world) - 1, 1)


# --- 9: dual extraction ---


def test_dual_sample_seed_recorded_and_disagreements_listed(
    project: Project,
    human: Actor,
    agent: Actor,
    ext_a: Actor,
    ext_b: Actor,
    screened: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = next(
        s
        for s in range(1000)
        if 0 < sum(in_dual_sample(s, w, 0.5) for w in screened) < len(screened)
    )
    monkeypatch.setattr(extraction.secrets, "randbits", lambda _bits: seed)
    _declare(project, agent, 0.5)
    dual = sorted(w for w in screened if in_dual_sample(seed, w, 0.5))
    odd = dual[0]
    _both(project, ext_a, ext_b, b=lambda w: [_r(task="detection")] if w == odd else [_r()])
    config = pass_config(project, PassLabel.B)
    assert config is not None and config.seed == seed
    ag = extraction_agreement(project, human)
    assert ag.dual_works == len(dual)
    assert [d.work_id for d in ag.disagreements] == [odd]
    assert ag.disagreements[0].field == "task" and ag.resolved == 0
    assert odd not in {r.work_id for r in final_rows(project)}  # never auto-resolved
    assert grouped_rows(project).unresolved == ag.disagreements


# --- 10: audit ---


def test_audit_size_rule_and_error_rate(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    n = len(agreed_values(project))
    expected = min(n, max(-(-n * 2 // 100), 50))  # pilot defaults: fraction 0.02, minimum 50
    sampled = extraction_audit_sample(project, human, random_seed=3)
    assert sampled.population == n and len(sampled.items) == expected
    for i, item in enumerate(sampled.items):
        extraction_audit_record(
            project,
            human,
            sampled.audit_id,
            item.work_id,
            item.row_key,
            item.field,
            i != 0,
            "" if i else "wrong",
            CH,
        )
    report = extraction_audit_report(project)
    assert report is not None
    assert (report.sample_size, report.labelled, report.incorrect) == (expected, expected, 1)
    assert report.error_rate == 1 / expected
    assert report.ceiling == EXTRACTION_ERROR_CEILING == 0.05
    assert report.enforced is False  # a pilot: advisory


# --- 11: corrections supersede ---


def test_corrections_supersede_both_in_log(
    project: Project, ext_a: Actor, world: list[str]
) -> None:
    batch = extract_next(project, ext_a, PassLabel.A).batch
    assert batch is not None
    (old,) = extract_record(project, ext_a, batch.task_id, [_r()]).rows.written
    (new,) = extract_record(
        project, ext_a, batch.task_id, [_r("2", "t1.r3.c3")], supersedes={0: old}
    ).rows.written
    assert [r.extraction_id for r in live_rows(project, PassLabel.A)] == [new]
    by_ref = {r: e for e in read_all(project.paths.events_dir, project.catalog) for r in e.refs}
    assert old in by_ref and new in by_ref  # both remain in the log
    assert by_ref[new].payload["supersedes"] == old


# --- 14: trace ---


def _kinds(node: TraceNode) -> set[str]:
    return {node.kind}.union(*(_kinds(c) for c in node.children))


def test_trace_from_row_reaches_question(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    row = live_rows(project, PassLabel.A, work_id=world[0])[0]
    tree = trace(project, row.extraction_id)
    assert tree.kind == "extraction"
    chain = {"anchor", "conversion", "document", "attempt", "work", "decision", "protocol"}
    assert chain <= _kinds(tree)
    assert "question" in _kinds(tree)


# --- projection and earlier suites ---


def test_rebuild_matches(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _both(project, ext_a, ext_b, b=lambda w: [_r(unit="%")] if w == odd else [_r()])
    (d,) = extraction_agreement(project, human).disagreements
    resolve_extraction(project, human, odd, d.row_key, "value", "b", "b is right", CH)
    sampled = extraction_audit_sample(project, human, random_seed=3)
    item = sampled.items[0]
    extraction_audit_record(
        project, human, sampled.audit_id, item.work_id, item.row_key, item.field, True, "", CH
    )
    state = project.index.state_hash()
    finals, grouped = final_rows(project), grouped_rows(project)
    assert project.index.rebuild() == state
    assert project.index.state_hash() == state
    assert final_rows(project) == finals
    assert grouped_rows(project) == grouped


EARLIER = (
    "test_acceptance_slice1.py",
    "test_acceptance_protocol.py",
    "test_acceptance_screening.py",
    "test_acceptance_supplementary.py",
    "test_acceptance_rebuild.py",
    "test_acceptance_acquisition.py",
    "test_acceptance_fulltext.py",
    "test_acceptance_document.py",
    "test_acceptance_fulltext_screening.py",
)


def test_earlier_acceptance_suites_unchanged() -> None:
    paths = [str(TESTS / n) for n in EARLIER]
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *paths],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout[-2000:]

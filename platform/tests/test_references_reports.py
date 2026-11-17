"""PRISMA other-methods detail, search-report round rows, methods, check, trace and seed route
for references and snowballing (slice 3a, acceptance 12-14; plan G1 task 8).

Every entry and work is invented; the fixtures are those of `test_snowball_round`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.chase import ChaseDirection
from factory.model.decisions import DecisionLevel
from factory.model.project import RigorMode
from factory.model.protocol import SnowballPlan
from factory.model.references import Direction, Via
from factory.model.seed import SeedKind, SeedSpec
from factory.model.work import Provenance, ProvenanceMethod, Work
from factory.services import check as check_service
from factory.services import references as references_service
from factory.services import seeds as seeds_service
from factory.services.agreement import Outcome
from factory.services.chase import search_chase
from factory.services.check import LEVELS, _findings_as
from factory.services.context import Project
from factory.services.methods import methods_report, render_methods
from factory.services.prisma import prisma_flow, search_report
from factory.services.seeds import add_seeds, agent_seeds, seed_check
from factory.services.snowball import round_yield, snowball_round
from factory.services.trace import KINDS, TraceNode, trace
from tests import test_snowball_round as rounds
from tests.cli_helpers import _env
from tests.document_helpers import fetched_document, make_registry, promoted_works, run_convert
from tests.helpers import bind_ids
from tests.references_service_helpers import bib_html
from tests.test_snowball_compare import CHASED, CITING, REED, _backward, _pending, _screen
from tests.test_snowball_round import ENTRIES_A, _amend, _lookups, _sources

world = rounds.world
planned = rounds.planned

ALL_REFERENCE_CODES = [
    "references-missing-extraction",
    "references-stale-extraction",
    "references-parse-incomplete",
    "references-unresolved-ceiling",
    "references-library-missing",
    "snowball-plan-missing",
    "snowball-over-plan",
    "snowball-unscreened",
]
EXPECTED_LEVELS = {
    "references-missing-extraction": (None, "warning", "error"),
    "references-stale-extraction": ("warning", "warning", "warning"),
    "references-parse-incomplete": ("warning", "warning", "warning"),
    "references-unresolved-ceiling": ("warning", "warning", "warning"),
    "references-library-missing": ("warning", "warning", "warning"),
    "references-decision-lost": ("warning", "warning", "error"),
    "snowball-plan-missing": (None, "warning", "error"),
    "snowball-over-plan": ("warning", "warning", "warning"),
    "snowball-unscreened": ("error", "error", "error"),
}
ENTRY_WORDS = ("lattice", "quillfeather", "thornbury", "tidal", "reed", "journal of tests", "fog")
"""Words of the invented bibliography: none may appear in a finding's message (refs are
identifiers, and a work id carries title words by design)."""
UNKNOWN_ENTRY = "Q. Nobody. An unfindable treatise on fog. Nowhere Press, 1999."


def _carries_entry_text(message: str) -> bool:
    return any(re.search(rf"\b{word}\b", message, re.IGNORECASE) for word in ENTRY_WORDS)


def _include_pending(project: Project, agent: Actor) -> None:
    _screen(project, agent, dict.fromkeys(_pending(project), "include"))


def _chase_sources(**kw: Any) -> Any:
    return _lookups(**kw).sources()


# --- PRISMA ---


def test_identified_other_unchanged_without_rounds(
    project: Project, agent: Actor, world: tuple[str, str]
) -> None:
    flow = prisma_flow(project)
    assert flow.identified_other == {
        "citation-chase": 0,
        "seed-admission": 0,
        "hand-search": 0,
        "supplied": 0,
    }
    assert flow.identified_other_detail == {}
    # a plain chase keeps its slice-1 count; the detail names the mechanism
    search_chase(project, agent, [ChaseDirection.BACKWARD], sources=_chase_sources(cited=[CHASED]))
    flow = prisma_flow(project)
    assert flow.identified_other == {
        "citation-chase": 1,
        "seed-admission": 0,
        "hand-search": 0,
        "supplied": 0,
    }
    assert flow.identified_other_detail == {
        "chase-backward": 1,
        "chase-forward": 0,
        "snowball-backward": 0,
    }


def test_detail_breakdown_sums(project: Project, agent: Actor, planned: tuple[str, str]) -> None:
    _backward(project, agent)
    _include_pending(project, agent)
    # REED is found again by the chase: it counts once, under its earliest run (the round)
    search_chase(
        project, agent, [ChaseDirection.BACKWARD], sources=_chase_sources(cited=[REED, CHASED])
    )
    _include_pending(project, agent)
    flow = prisma_flow(project)
    assert sum(flow.identified_other_detail.values()) == flow.identified_other["citation-chase"]
    assert flow.identified_other_detail == {
        "chase-backward": 1,
        "chase-forward": 0,
        "snowball-backward": 3,
    }


def test_forward_snowball_counts_as_chase_forward(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    _backward(project, agent)
    _include_pending(project, agent)
    forward = snowball_round(
        project, agent, Direction.FORWARD, sources=_chase_sources(citing=[CITING]), dry_run=False
    )
    assert forward.round_id is not None
    flow = prisma_flow(project)
    assert flow.identified_other_detail == {
        "chase-backward": 0,
        "chase-forward": 1,
        "snowball-backward": 3,
    }
    assert sum(flow.identified_other_detail.values()) == flow.identified_other["citation-chase"]


def test_search_report_has_round_rows_with_yield(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    result, _ = _backward(project, agent)
    assert result.round_id is not None
    rows = [r for r in search_report(project).rows if r.round_id == result.round_id]
    assert len(rows) == 3
    assert all(r.via is Via.DOCUMENT_REFERENCE_LIST for r in rows)
    assert all(r.round_no == 1 and r.direction is Direction.BACKWARD for r in rows)
    yielded = round_yield(project, result.round_id)
    assert sum(r.new_after_dedup or 0 for r in rows) == yielded.new_after_dedup == 3
    assert any(r.included is None for r in rows)  # pending
    _include_pending(project, agent)
    rows = [r for r in search_report(project).rows if r.round_id == result.round_id]
    assert sum(r.included or 0 for r in rows) == round_yield(project, result.round_id).included
    forward = snowball_round(
        project, agent, Direction.FORWARD, sources=_chase_sources(citing=[CITING]), dry_run=False
    )
    report = search_report(project)
    fwd = [r for r in report.rows if r.round_id == forward.round_id]
    assert fwd and all(r.via is Via.SOURCE_METADATA and r.round_no == 1 for r in fwd)
    assert sum(r.new_after_dedup or 0 for r in fwd) == 1
    plain = [r for r in report.rows if r.round_id is None]
    assert plain and all(r.via is None and r.new_after_dedup is None for r in plain)


def test_run_counts_agree_with_the_round_yield(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    """The candidates were stored by probe lookups: new to the corpus all the same (R-23)."""
    result, _ = _backward(project, agent)
    assert result.round_id is not None
    assert result.new_works == 3
    assert [r.new_works for r in result.runs] == [1, 1, 1]
    yielded = round_yield(project, result.round_id)
    rows = [r for r in search_report(project).rows if r.round_id == result.round_id]
    assert sum(run.new_works for row in rows for run in row.runs) == yielded.new_after_dedup == 3
    for row in rows:
        assert sum(run.new_works for run in row.runs) == row.new_after_dedup


def test_chase_missing_is_silent_where_the_snowball_plan_covers_chasing(
    project: Project, agent: Actor, world: tuple[str, str]
) -> None:
    assert "chase-missing" in {f.code for f in _findings_as(project, RigorMode.PILOT)}
    _amend(project, agent, rounds.PLAN)
    _backward(project, agent)
    _include_pending(project, agent)
    assert "chase-missing" not in {f.code for f in _findings_as(project, RigorMode.PILOT)}


def test_chase_missing_still_fires_under_a_plan_of_no_rounds(
    project: Project, agent: Actor, world: tuple[str, str]
) -> None:
    _amend(project, agent, SnowballPlan(max_backward_rounds=0, max_forward_rounds=0))
    assert "chase-missing" in {f.code for f in _findings_as(project, RigorMode.PILOT)}


def test_over_plan_sees_a_standalone_forward_chase(
    project: Project, agent: Actor, world: tuple[str, str]
) -> None:
    summary = search_chase(project, agent, [ChaseDirection.FORWARD], sources=_sources())
    _amend(project, agent, SnowballPlan(max_backward_rounds=2, max_forward_rounds=0))
    [finding] = [
        f for f in _findings_as(project, RigorMode.PILOT) if f.code == "snowball-over-plan"
    ]
    assert tuple(finding.refs) == (summary.round_id,)


# --- Methods ---


def test_methods_states_mechanisms_rule_and_versions(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    _backward(project, agent)
    report = methods_report(project)
    assert report.snowball_rounds == {"backward": 1, "forward": 0}
    assert report.snowball_rule == (
        "at most 2 backward and 1 forward round(s); stop when a round yields no newly included work"
    )
    assert report.reference_parser == "refparse 2" and report.reference_matcher == "1"
    text = render_methods(report)
    assert "Reference lists" in text and "refparse 2" in text


def test_methods_unchanged_without_references(project: Project, corpus: None) -> None:
    report = methods_report(project)
    assert report.snowball_rounds == {} and report.reference_parser is None
    assert "Reference lists" not in render_methods(report)


# --- Check ---


def _parse_incomplete(project: Project, agent: Actor) -> None:
    work = promoted_works(project)[2]
    fetched_document(project, work, bib_html(ENTRIES_A[:1], ["See {cite:1} and {cite:3}."]))
    run_convert(project, make_registry())
    references_service.extract_references(project, agent, [work], sources=_sources())


def _unresolved_document(project: Project, agent: Actor) -> None:
    """A third included work whose only entry no source knows: 100% unresolved."""
    work = promoted_works(project)[3]
    fetched_document(project, work, bib_html([UNKNOWN_ENTRY], ["See {cite:1}."]))
    run_convert(project, make_registry())
    references_service.extract_references(project, agent, [work], sources=_sources())


def _construct(code: str, project: Project, agent: Actor, monkeypatch: pytest.MonkeyPatch) -> None:
    """A project state that raises `code` (the `world` fixture is already built)."""
    if code == "references-missing-extraction":
        work = promoted_works(project)[2]
        fetched_document(project, work, bib_html(ENTRIES_A[:1], ["See {cite:1}."]))
        run_convert(project, make_registry())
    elif code == "references-stale-extraction":
        monkeypatch.setattr(references_service, "PARSER_VERSION", "999")
    elif code == "references-parse-incomplete":
        _parse_incomplete(project, agent)
    elif code == "references-unresolved-ceiling":
        _unresolved_document(project, agent)
    elif code == "references-library-missing":
        _drop_markdown(project)
    elif code == "snowball-plan-missing":
        pass  # pilot, no plan declared
    elif code == "snowball-over-plan":
        _amend(project, agent, rounds.PLAN)
        snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
        _amend(project, agent, SnowballPlan(max_backward_rounds=0, max_forward_rounds=0))
    elif code == "snowball-unscreened":
        _amend(project, agent, rounds.PLAN)
        snowball_round(project, agent, Direction.BACKWARD, sources=_sources(), dry_run=False)
        real = check_service.final_outcomes

        def included(p: Project, **kw: Any) -> dict[str, Outcome]:
            return {w: Outcome.INCLUDED for w in real(p, **kw)}

        monkeypatch.setattr(check_service, "final_outcomes", included)


def _drop_markdown(project: Project) -> None:
    """Remove the Markdown of the conversion the first live extraction is pinned to."""
    with project.index.connect() as conn:
        markdown = conn.execute(
            text(
                "SELECT c.markdown_hash FROM document_conversions c JOIN reference_extractions x "
                "ON x.conversion_id = c.conversion_id WHERE x.live = 1 ORDER BY x.extraction_id"
            )
        ).first()
    assert markdown is not None
    project.library.path(str(markdown[0])).unlink()


@pytest.mark.parametrize("code", ALL_REFERENCE_CODES)
def test_each_finding_appears_in_constructed_case(
    project: Project,
    agent: Actor,
    world: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    if code != "snowball-plan-missing":
        assert code not in {f.code for f in _findings_as(project, RigorMode.SYSTEMATIC)}
    _construct(code, project, agent, monkeypatch)
    findings = [f for f in _findings_as(project, RigorMode.SYSTEMATIC) if f.code == code]
    assert findings, code
    for finding in findings:
        assert not _carries_entry_text(finding.message)
        assert all(" " not in ref for ref in finding.refs)


def test_severity_by_mode(project: Project, world: tuple[str, str]) -> None:
    for code, levels in EXPECTED_LEVELS.items():
        assert LEVELS[code] == levels, code
    for mode, expected in (
        (RigorMode.EXPLORATORY, None),
        (RigorMode.PILOT, "warning"),
        (RigorMode.SYSTEMATIC, "error"),
    ):
        found = [
            f.severity for f in _findings_as(project, mode) if f.code == "snowball-plan-missing"
        ]
        assert found == ([] if expected is None else [expected])


def test_findings_carry_no_document_text(
    project: Project, agent: Actor, world: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _parse_incomplete(project, agent)
    _unresolved_document(project, agent)
    monkeypatch.setattr(references_service, "PARSER_VERSION", "999")
    findings = _findings_as(project, RigorMode.SYSTEMATIC)
    codes = {f.code for f in findings}
    assert {"references-stale-extraction", "references-unresolved-ceiling"} <= codes
    for finding in findings:
        assert not _carries_entry_text(finding.message), finding
        assert all(" " not in ref for ref in finding.refs), finding


# --- Trace ---


def _nodes(node: TraceNode) -> list[TraceNode]:
    return [node, *(n for child in node.children for n in _nodes(child))]


def _path_to(node: TraceNode, kind: str) -> list[str] | None:
    if node.kind == kind:
        return [node.kind]
    for child in node.children:
        found = _path_to(child, kind)
        if found is not None:
            return [node.kind, *found]
    return None


def test_trace_from_round_and_candidate(
    project: Project, agent: Actor, planned: tuple[str, str]
) -> None:
    assert KINDS.index("reference_extraction") == KINDS.index("chase_round") + 1
    assert KINDS.index("snowball_round") == KINDS.index("chase_round") + 2
    result, reed = _backward(project, agent)
    assert result.round_id is not None
    _include_pending(project, agent)

    tree = trace(project, reed)
    kinds = {n.kind for n in _nodes(tree)}
    assert {
        "anchor",
        "reference_extraction",
        "conversion",
        "document",
        "attempt",
        "decision",
        "protocol",
        "question",
        "snowball_round",
    } <= kinds
    # candidate -> citing anchor -> extraction -> ... -> question
    anchor = next(n for n in tree.children if n.kind == "anchor")
    assert anchor.id.split("/", 1)[1].startswith("b")
    assert _path_to(anchor, "question") is not None
    assert _path_to(anchor, "reference_extraction") == ["anchor", "reference_extraction"]

    round_node = trace(project, result.round_id)
    assert round_node.kind == "snowball_round" and "backward round 1" in round_node.label
    assert {n.kind for n in _nodes(round_node)} >= {"reference_extraction", "work", "question"}
    forward = trace(project, result.round_id, direction="forward")
    assert "query" in {c.kind for c in forward.children}

    rex = next(n for n in _nodes(round_node) if n.kind == "reference_extraction")
    entry = trace(project, f"{rex.id}:1")
    assert entry.kind == "reference_extraction" and entry.id == rex.id


# --- Seed route ---


def test_seed_found_by_snowball_labelled_in_cli_only(
    project: Project, agent: Actor, planned: tuple[str, str], settings: Settings
) -> None:
    _, reed = _backward(project, agent)
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Reed", openalex="W501")
    [outcome] = add_seeds(
        project,
        agent,
        [spec],
        sources=_sources(),
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    ).written
    [row] = [c for c in seed_check(project) if c.seed_id == outcome.seed_id]
    assert row.matched_work == reed and row.found_by == "snowball"
    others = [c for c in seed_check(project) if c.seed_id != outcome.seed_id]
    assert all(c.found_by in (None, "search") for c in others)

    result = CliRunner().invoke(app, ["seeds"], env=_env(settings.root))
    assert result.exit_code == 0, result.stderr
    [line] = [x for x in result.stdout.splitlines() if x.startswith(outcome.seed_id)]
    assert "retrieved (snowball)" in line
    assert all("found_by" not in s.model_dump() for s in agent_seeds(project))


# --- Seed route under decision 54 (fix round 1) ---

_ULIDS = iter(f"01HZX3K4M5N6P7Q8R9S0TVWX{n:02d}" for n in range(10, 99))


def _work(work_id: str, *methods: ProvenanceMethod) -> Work:
    return Work(
        id=work_id,
        title="Invented",
        provenance=[
            Provenance(
                source="openalex",
                run_id=f"run_{next(_ULIDS)}",
                query_id=f"qry_{next(_ULIDS)}",
                at=datetime(2026, 1, 1, tzinfo=UTC),
                raw_blob="sha256:" + "a" * 64,
                method=method,
            )
            for method in methods
        ],
    )


def test_hand_search_only_seed_is_found_by_search() -> None:
    work = _work("rf:a2020-x-00000001", ProvenanceMethod.HAND_SEARCH)
    assert seeds_service._found_by([work], set()) == "search"


def test_admission_only_work_with_merged_database_work_is_found_by_search(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _work("rf:a2020-x-00000002", ProvenanceMethod.SEED_ADMISSION)
    absorbed = _work("rf:a2020-x-00000003", ProvenanceMethod.DATABASE)
    merge = SimpleNamespace(primary=primary.id, absorbed=(absorbed.id,))
    monkeypatch.setattr(seeds_service, "active_merges", lambda _p: [merge])
    groups = seeds_service._merge_groups(project)
    assert set(groups[primary.id]) == set(groups[absorbed.id]) == {primary.id, absorbed.id}
    group = [w for w in (primary, absorbed) if w.id in groups[primary.id]]
    assert seeds_service._found_by(group, set()) == "search"


def test_admission_only_seed_stays_admission() -> None:
    work = _work("rf:a2020-x-00000004", ProvenanceMethod.SEED_ADMISSION)
    assert seeds_service._found_by([work], set()) == "admission"
    assert seeds_service._found_by([], set()) is None

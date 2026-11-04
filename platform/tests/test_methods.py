"""The methods statement generated from events (plan 5b, task 2).

The render takes its figures from `methods_report` alone; these tests check the wording, the
order of the paragraphs (search, deduplication, screening, agreement and audit, full text, seed
recall, deviations), the agent-reported disclosure, and that no seed is named.
"""

import re
from collections.abc import Callable, Mapping

from factory.events.envelope import Actor
from factory.services.agreement import agreement_summary, screen_agreement
from factory.services.context import Project
from factory.services.methods import MethodsReport, methods_report, render_methods
from factory.services.prisma import PrismaFlow, prisma_flow
from factory.services.seeds import SeedRole, all_seeds
from factory.sources.registry import SourceFactory
from tests.helpers import _protocol
from tests.test_chase_service import _corpus, _ordinary, _settle
from tests.test_screening_next import _decide

SourcesFor = Callable[..., Mapping[str, SourceFactory]]


def _flow() -> PrismaFlow:
    base: dict[str, object] = {
        "identified_databases": {"openalex": 9},
        "identified_other": {"citation-chase": 0, "seed-admission": 0, "hand-search": 0},
        "duplicates_removed": 0,
        "screened": 9,
        "excluded": {},
        "pending": 0,
        "included": 9,
        "provisional": False,
        "protocol_id": "prot_01",
    }
    return PrismaFlow.model_validate(base)


def _report(**changes: object) -> MethodsReport:
    """A report with every figure computed, unless overridden."""
    base: dict[str, object] = {
        "rigor_mode": "pilot",
        "method_profile": "systematic-review",
        "protocol_id": "prot_01",
        "amendments": 1,
        "deviations": 2,
        "sources": ["openalex"],
        "models": ["claude-opus-5-5"],
        "skills": ["rf-screen@1a2b3c4d"],
        "passes": 2,
        "dual_sample": 0.5,
        "kappa": 0.8,
        "kappa_by_criterion": {"EX01": 0.75},
        "calibration_sensitivity": {"A": 0.95, "B": 0.97},
        "audit_false_exclusion_rate": 0.0,
        "audit_n": 50,
        "recall_held_out": 0.5,
        "recall_development": 1.0,
        "chase_rounds": 1,
        "admitted_seeds": 2,
        "prisma": _flow(),
    }
    return MethodsReport.model_validate(base | changes)


def _paragraph(text: str, start: str) -> str:
    """The paragraph of the render that begins with `start`."""
    [found] = [p for p in text.split("\n\n") if p.startswith(start)]
    return found


def _count(paragraph: str, label: str) -> int:
    match = re.search(rf"(\d+) {label}\b", paragraph)
    assert match is not None, f"no count before {label!r} in {paragraph!r}"
    return int(match.group(1))


def test_methods_reports_held_out_before_development() -> None:
    text = render_methods(_report(recall_held_out=0.5, recall_development=1.0))

    held_out = text.index("Held-out seed recall: 0.500")
    development = text.index("Development seed recall: 1.000 (optimistic")
    assert held_out < development


def test_methods_discloses_models_as_agent_reported(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _protocol(project, agent, human, mock_sources)

    report = methods_report(project)
    text = render_methods(report)

    assert report.models == ["claude-opus-5-5"]
    assert report.skills == ["rf-screen@1a2b3c4d"]
    assert (
        "Screening decisions were made by Claude models (as reported by the agent: "
        "claude-opus-5-5) following the skills rf-screen@1a2b3c4d; the platform made no model "
        "calls." in text
    )


def test_methods_none_renders_not_computed() -> None:
    text = render_methods(
        _report(
            kappa=None,
            kappa_by_criterion={},
            calibration_sensitivity={"A": None, "B": None},
            audit_false_exclusion_rate=None,
            audit_n=0,
            recall_held_out=None,
            recall_development=None,
            dual_sample=None,
            method_profile=None,
        )
    )

    assert "not computed" in text
    assert "None" not in text


def test_methods_names_no_seed(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _protocol(project, agent, human, mock_sources)
    seeds = all_seeds(project)
    assert any(record.role is SeedRole.HELD_OUT for record in seeds)

    text = render_methods(methods_report(project))

    for record in seeds:
        assert record.seed_id not in text
        assert record.cite not in text
        if record.doi is not None:
            assert record.doi not in text
        if record.arxiv is not None:
            assert record.arxiv not in text
    assert "10.1000/" not in text


def test_methods_numbers_match_prisma(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id, leave=_ordinary(project)[0])
    leftover = _ordinary(project)[0]
    _decide(project, agent, leftover, "A", "screening", "exclude", "EX01", protocol_id)
    _decide(project, agent, leftover, "B", "screening", "exclude", "EX01", protocol_id)

    flow = prisma_flow(project)
    report = methods_report(project)
    text = render_methods(report)
    screening = _paragraph(text, "Screening of ")

    assert report.prisma == flow
    assert _count(screening, "works") == flow.screened
    assert _count(screening, "included") == flow.included
    assert _count(screening, "excluded") == sum(flow.excluded.values())
    assert _count(screening, "pending") == flow.pending
    assert (
        dict((criterion, int(n)) for criterion, n in re.findall(r"(\S+) \((\d+)\)", screening))
        == flow.excluded
    )
    assert flow.excluded == {"EX01": 1}


def test_methods_before_protocol_renders_not_computed(project: Project) -> None:
    report = methods_report(project)
    text = render_methods(report)

    assert (report.protocol_id, report.method_profile, report.kappa) == (None, None, None)
    assert report.passes == 0 and report.kappa_by_criterion == {}
    assert "not computed" in text and "None" not in text


def test_agreement_summary_none_until_every_dual_work_is_decided(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    leftover = _ordinary(project)[0]
    _settle(project, agent, human, protocol_id, leave=leftover)
    assert agreement_summary(project) is None

    _decide(project, agent, leftover, "A", "screening", "include", None, protocol_id)
    _decide(project, agent, leftover, "B", "screening", "include", None, protocol_id)
    assert agreement_summary(project) is not None


def test_agreement_summary_matches_screen_agreement(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    protocol_id = _corpus(project, agent, human, mock_sources)
    _settle(project, agent, human, protocol_id)

    assert agreement_summary(project) == screen_agreement(project, human)


def test_methods_zero_passes_and_zero_audit_render_not_computed() -> None:
    """No protocol or no audit gives passes 0 and audit_n 0 in the model; the text says so."""
    text = render_methods(_report(passes=0, audit_false_exclusion_rate=None, audit_n=0))

    assert "Screening passes: not computed;" in text
    assert "Audit false-exclusion rate: not computed (no audit labels)." in text
    assert "passes: 0" not in text and "over 0 labelled" not in text
    computed = render_methods(_report())
    assert "Screening passes: 2;" in computed and "over 50 labelled works" in computed

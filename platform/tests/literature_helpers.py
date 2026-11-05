"""A real evidence world for literature hypotheses (slice 6, plan XP-B, review fixes): works that
each report both methods in one group, through the true extraction passes. The group's metric is
`low`, the metric cell of the fixture document, so `LOW` is the hypothesis metric that matches."""


from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from factory.events.envelope import Actor
from factory.model.extraction import ExtractedRowInput, FieldInput
from factory.model.hypotheses import Trigger, TriggerKind
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.extraction import extraction_population
from factory.services.hypotheses import draft_hypothesis, register_hypothesis
from factory.services.hypothesis_review import record_review, review_next
from factory.sources.registry import SourceFactory
from tests.evidence_helpers import run_pass
from tests.extraction_helpers import SESSION_A, SESSION_B, _declare, _extractor, _r
from tests.fulltext_helpers import _screened_full_text_world
from tests.hypothesis_helpers import CRITIC, DRAFTER, make_spec, promoted_lead
from tests.test_hypothesis_review import verdict

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
LOW = {"name": "Low", "direction": "higher", "unit_family": "score", "unit": "points"}
"""The hypothesis metric the world's groups report."""


def _method(name: str, anchor: str) -> dict[str, FieldInput]:
    return {"method_name": FieldInput(value=name, anchor=anchor, quote=name)}


def literature_world(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    plan: Sequence[str | None],
) -> list[str]:
    """Each work of `plan` reports `Lorem` and `Low` in the classification group: `t` favours the
    treatment (2 against 1), `b` the baseline, `x` neither, None no row at all."""
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    _declare(project, agent)
    works = extraction_population(project)

    def rows_for(work: str) -> list[ExtractedRowInput]:
        i = works.index(work)
        if i >= len(plan) or plan[i] is None:
            return []
        kind = plan[i]
        high, low = ("2", "t1.r3.c3"), ("1", "t1.r3.c2")
        treatment, baseline = (high, low) if kind == "t" else (low, high)
        if kind == "x":
            treatment, baseline = low, low
        return [
            _r(*treatment, task="classification", **_method("Lorem", "t1.r3.c1")),
            _r(*baseline, task="classification", **_method("Low", "t1.r2.c2")),
        ]

    run_pass(project, _extractor(SESSION_A, "claude-opus-5-5"), PassLabel.A, rows_for)
    run_pass(project, _extractor(SESSION_B, "claude-sonnet-5-5"), PassLabel.B, rows_for)
    return works


def literature_hypothesis(project: Project, human: Actor, works: list[str], **over: Any) -> str:
    """A registered literature hypothesis on the world's classification group."""
    lead = promoted_lead(project, human, Trigger(kind=TriggerKind.WORK, ref=works[0]))
    body: dict[str, Any] = {
        "kind": "literature",
        "lead": lead,
        "rationale": "literature",
        "statement": "Lorem beats Low in later literature on classification.",
        "decision_rule": {"rule": "literature-direction", "n_min": 2, "q": "0.75"},
        "test": {"kind": "literature", "window_start": "1990-01-01"},
        "conditions": {"task": "classification"},
        "metric": LOW,
        "treatment": {"name": "Lorem"},
        "baseline": {"name": "Low"},
    }
    body.update(over)
    hid, _ = draft_hypothesis(project, DRAFTER, make_spec(**body))
    served = review_next(project, CRITIC)
    assert served is not None
    record_review(project, CRITIC, served.task_id, verdict("register"))
    register_hypothesis(project, human, hid)
    return hid

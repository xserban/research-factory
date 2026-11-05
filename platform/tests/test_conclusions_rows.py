"""Conclusion basis over extraction rows: resolution and staleness (living-D, task 2).

These run over the full-text extraction world of plan D (slow), as the notice effects do.
"""

from __future__ import annotations

import pytest

from factory.events.envelope import Actor
from factory.model.conclusions import BasisRef
from factory.model.notices import AssessmentDecision, NoticeKind
from factory.services.conclusions import basis_state, conclusions, register_conclusion
from factory.services.context import Project
from factory.services.extraction import live_rows
from factory.services.notices import assess_notice
from tests.test_notice_effects import _extract_work, _observe, ext_a, world  # noqa: F401

pytestmark = pytest.mark.slow  # over ~60 s per file: dev runs deselect with -m "not slow"


def _row_key(project: Project, extraction_id: str) -> str:
    return next(r.row_key for r in live_rows(project) if r.extraction_id == extraction_id)


def test_row_and_cell_basis_resolve_and_go_stale(
    project: Project,
    ext_a: Actor,  # noqa: F811
    world: list[str],  # noqa: F811
) -> None:
    work = world[0]
    plain, latency = _extract_work(project, ext_a, work)
    plain_key, latency_key = _row_key(project, plain), _row_key(project, latency)
    basis = [BasisRef(kind="row", ref=plain_key), BasisRef(kind="cell", ref=f"{latency_key}/value")]
    cid = register_conclusion(project, project.human_actor(), "Statement.", basis, None)
    assert [c.conclusion_id for c in conclusions(project)] == [cid]
    assert not any(": stale" in a or "superseded" in a for a in basis_state(project, basis))

    notice = _observe(project, work, NoticeKind.CORRECTION, "10.2000/corr")
    assess_notice(
        project,
        project.human_actor(),
        notice,
        AssessmentDecision.AFFECTS,
        fields=("latency",),
        rationale="the latency figure was corrected",
    )
    state = basis_state(project, basis)
    assert f"cell:{latency_key}/value: stale" in state
    assert f"row:{plain_key}: stale" not in state

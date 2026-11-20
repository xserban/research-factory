"""Scale of rule evaluation (slice 3d, plan Regions-A, task 6; G2-D scale ruling).

The synthetic projection of `test_lineage_scale` (50,000 works, 500,000 `cites`, 20,000 lineage
edges) is written straight into the index tables. A `lineage` rule at `MAX_DEPTH` and a `cites`
rule with `min_k = 2` over a 1,000-member base each evaluate within 5 s, and the Python heap stays
below 200 MB.
"""

from __future__ import annotations

import time
import tracemalloc

import pytest

from factory.lineage.paths import MAX_DEPTH
from factory.model.regions import RegionSnapshotTaken
from factory.regions import evaluate as evaluate_module
from factory.regions.evaluate import Evaluation, evaluate
from factory.regions.rules import CitesRule, LineageRule, MemberType, RuleSet
from factory.regions.version import compress, members_text
from factory.services.agreement import Outcome
from factory.services.context import Project
from tests.test_lineage_scale import CHAIN, PAPERS, _paper, _populate

pytestmark = pytest.mark.slow

LIMIT_SECONDS = 5.0
LIMIT_BYTES = 200 * 1024 * 1024
BASE = 1_000
VERSION = "R@" + "5" * 8


def _pin_base(project: Project) -> None:
    members = [(MemberType.WORK, _paper(i)) for i in range(BASE)]
    event = project.events.make(
        "region.snapshot_taken",
        RegionSnapshotTaken(
            region_id="reg_01JZ9Q3K5M7N8P0R2S4T6V8W1B",
            version=VERSION,
            definition_event="ev_01JZ9Q3K5M7N8P0R2S4T6V8W1D",
            rules_hash="0" * 64,
            members_blob=project.blobs.put(compress(members_text(members))),
            members_hash="1" * 64,
            basis_blob=project.blobs.put_json({}),
            counts={MemberType.WORK: BASE},
            as_of="ev_01JZ9Q3K5M7N8P0R2S4T6V8W1D",
        ),
        project.system_actor(),
    )
    project.record([event])


def _timed(project: Project, rules: RuleSet) -> tuple[Evaluation, float]:
    start = time.perf_counter()
    with project.index.connect() as conn:
        result = evaluate(conn, project, rules)
    return result, time.perf_counter() - start


def test_region_scale(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    project.index.sync()
    _populate(project)
    # A cites rule keeps only corpus works (0405e75c); the synthetic papers have no screening
    # events, so the corpus is supplied in place of the screening service, every paper included.
    corpus = {_paper(i): Outcome.INCLUDED for i in range(PAPERS)}
    monkeypatch.setattr(evaluate_module, "final_outcomes", lambda project: corpus)
    _pin_base(project)  # an incremental fold: nothing is rebuilt, the synthetic rows stay
    tracemalloc.start()
    try:
        lineage = LineageRule(node=_paper(CHAIN), direction="ancestors", depth=MAX_DEPTH)
        deep, t_lineage = _timed(project, RuleSet(include=(lineage,)))
        assert len(deep.members) >= MAX_DEPTH and t_lineage < LIMIT_SECONDS
        cites = CitesRule(base=VERSION, direction="citing", min_k=2)
        citing, t_cites = _timed(project, RuleSet(include=(cites,)))
        assert 0 < len(citing.members) < 50_000 and t_cites < LIMIT_SECONDS
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < LIMIT_BYTES

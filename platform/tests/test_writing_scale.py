"""Scale of the outline and the write path on real stored rows (slice 7b, plan W-A, ruling 26).

As `tests/test_coverage_scale.py`: real passes give every included work agreed rows, the stored rows
are multiplied in the index tables, and everything downstream is the real path (ledger, staleness,
agreement, final rows, report, support resolution). The figures are printed; the bound is the
measured order of magnitude of decision 92 item 11, not acceptance 17's 5 s, which that decision
leaves open.
"""

# ruff: noqa: F811

from __future__ import annotations

import re
import time

import pytest

from factory.events.envelope import Actor
from factory.model.drafts import DraftKind, SentenceClass
from factory.model.extraction import ROW_KEY_RE
from factory.services.context import Project
from factory.services.drafts import SentenceInput, create_draft, write_sentences
from factory.services.extraction_agreement import final_rows
from factory.services.outline import build_outline
from tests.contribution_helpers import ctr_a, ctr_b, ext_a  # noqa: F401
from tests.extraction_helpers import screened  # noqa: F401
from tests.test_coverage_scale import _multiply
from tests.views_b_helpers import acc, declared, ext_b, run_both  # noqa: F401

pytestmark = pytest.mark.slow

COPIES = 400  # per stored row: 12 works x 2 passes x 400 = 9,600 live rows
LIMIT_SECONDS = 120.0


def test_real_path_cost(project: Project, ext_a: Actor, ext_b: Actor, declared: list[str]) -> None:
    run_both(project, ext_a, ext_b, lambda _w: [acc("2")])
    row = next(r for r in final_rows(project) if re.fullmatch(ROW_KEY_RE, r.row_key))
    rows = _multiply(project, COPIES)
    started = time.perf_counter()
    outline = build_outline(project)
    t_outline = time.perf_counter() - started
    me = project.human_actor()
    draft = create_draft(project, title="Scale", kind=DraftKind.OTHER, actor=me)
    sentence = SentenceInput(
        section_id="sec_01",
        cls=SentenceClass.CLAIM,
        text="Lorem reaches 2 on the benchmark",
        supports=[f"cell:{row.row_key}/value"],
    )
    started = time.perf_counter()
    result = write_sentences(project, draft, [sentence], actor=me)
    t_write = time.perf_counter() - started
    assert outline.sections and result.written, result.rejected
    print(f"SCALE rows={rows} outline={t_outline:.2f}s write={t_write:.2f}s")
    assert max(t_outline, t_write) < LIMIT_SECONDS

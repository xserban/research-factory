"""The statistics live in `factory.quality.stats`; the services keep their old names."""

import pytest

from factory.model.extraction import AuditItemRef
from factory.quality import stats
from factory.services import extraction_audit, screening_stats

MOVED = [
    "EXCLUSION_SHARE",
    "AuditRates",
    "Rates",
    "audit_error_rates",
    "audit_size",
    "cohen_kappa",
    "draw_audit",
    "draw_uniform",
    "kappa_by_criterion",
    "sensitivity_specificity",
]


@pytest.mark.parametrize("name", MOVED)
def test_reexports_are_identical(name: str) -> None:
    assert getattr(screening_stats, name) is getattr(stats, name)


def test_draw_uniform_matches_extraction_draw() -> None:
    items = [
        AuditItemRef(work_id=f"w{i % 7}", row_key=f"rk_{i:012x}", field=f"f{i % 3}")
        for i in range(40)
    ]
    for seed in range(20):
        assert stats.draw_uniform(
            items, 9, seed, key=extraction_audit._sort_key
        ) == extraction_audit._draw(items, 9, seed)

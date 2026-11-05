"""The onion view is the same bytes after the index is rebuilt (plan V-A, task 3)."""

# ruff: noqa: F811

from __future__ import annotations

from factory.services.context import Project
from factory.services.onion import onion_view
from factory.services.views import to_json
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world  # noqa: F401


def test_deterministic_across_rebuilds(project: Project, lin: Lineage) -> None:
    """Event-sourced: real references and links, both variants, identical bytes after a rebuild."""
    before = (to_json(onion_view(project)), to_json(onion_view(project, agent=True)))
    assert onion_view(project).rings[1].total > 0  # the links of the source are real edges
    project.index.rebuild()
    after = (to_json(onion_view(project)), to_json(onion_view(project, agent=True)))
    assert after == before

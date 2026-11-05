"""Shared setup for the relation and idea tests (slice 3b, plan G2-C).

`lin` is the G2-B world with a source work whose bibliography entry 5 (`Linear attention with
kernels`) and entry 3 (`Attention is a kernel`) resolve exactly in G1 and entry 4 only by a fuzzy
title match (unconfirmed). The source holds, in pass A, a `base-idea` item citing entry 5 (marker
check passes), an `addition` item citing entry 3, a `base-idea` item without a cited entry, and a
`limitation` item (not a legal basis).
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from dataclasses import dataclass

import pytest

from factory.events.envelope import Actor
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.contributions import contribution_next, contribution_record
from factory.services.extraction import ContributionBatch
from factory.services.reference_view import reference_view
from tests.contribution_helpers import (
    ENTRIES,
    P1,
    P2,
    P4,
    P5,
    ctr_a,
    ctr_b,
    field,
    item,
    screened,
    with_references,
    world,
)
from tests.references_service_helpers import Lookups, oa_item

OTHER_ENTRIES = list(ENTRIES)


@dataclass
class Lineage:
    source: str
    rex: str
    base: str
    """base-idea item citing entry 5."""
    addition: str
    """addition item citing entry 3."""
    uncited_base: str
    """base-idea item with no cited entry."""
    limitation: str
    target5: str
    target3: str
    fuzzy4: str | None


def build_lineage(project: Project, agent: Actor, ctr_a: Actor, world: list[str]) -> Lineage:
    lookups = Lookups(
        openalex=[
            oa_item("Linear attention with kernels", "E. Epsilon", 2020, "W5"),
            oa_item("Attention is a kernel", "C. Gamma", 2019, "W3"),
        ]
    )
    source = world[0]
    rex = with_references(project, agent, source, sources=lookups.sources())
    view = reference_view(project, source)
    assert view is not None
    five, three, four = view.entry(5), view.entry(3), view.entry(4)
    assert five is not None and three is not None and four is not None
    assert five.link_work is not None and three.link_work is not None
    batch = contribution_next(project, ctr_a, PassLabel.A).batch
    assert isinstance(batch, ContributionBatch)
    res = contribution_record(
        project,
        ctr_a,
        batch.task_id,
        [
            item("base-idea", P1, name="linear attention", cited_entry=field(5)),
            item("addition", P2, name="softmax attention", cited_entry=field(3)),
            item("base-idea", P5, name="Plain text"),
            item("limitation", P4, name="long sequences", statement="very long sequences degrade"),
        ],
    )
    assert len(res.rows.written) == 4, res.rows.rejected
    base, addition, uncited, limitation = res.rows.written
    return Lineage(
        source=source,
        rex=rex,
        base=base,
        addition=addition,
        uncited_base=uncited,
        limitation=limitation,
        target5=five.link_work,
        target3=three.link_work,
        fuzzy4=four.link_work,
    )


@pytest.fixture
def lin(project: Project, agent: Actor, ctr_a: Actor, world: list[str]) -> Lineage:
    return build_lineage(project, agent, ctr_a, world)

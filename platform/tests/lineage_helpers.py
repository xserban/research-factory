"""Shared setup for the relation and idea tests (slice 3b, plan G2-C).

`lin` is the G2-B world with a source work whose bibliography entry 5 (`Linear attention with
kernels`) and entry 3 (`Attention is a kernel`) resolve exactly in G1 and entry 4 only by a fuzzy
title match (unconfirmed). Both passes record, and close, the same four items of the source
(`ITEMS`): a `base-idea` citing entry 5, an `addition` citing entry 3, a `base-idea` without a
cited entry and a `limitation`; every item is therefore agreed, i.e. final.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from factory.events.envelope import Actor
from factory.model.extraction import ExtractedRowInput
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


ITEMS = [
    item("base-idea", P1, name="linear attention", cited_entry=field(5)),
    item("addition", P2, name="softmax attention", cited_entry=field(3)),
    item("base-idea", P5, name="Plain text"),
    item("limitation", P4, name="long sequences", statement="very long sequences degrade"),
]


@dataclass
class Lineage:
    source: str
    rex: str
    base: str
    """base-idea item citing entry 5 (pass A row id)."""
    addition: str
    """addition item citing entry 3."""
    uncited_base: str
    """base-idea item with no cited entry."""
    limitation: str
    target5: str
    target3: str
    ids_b: list[str]
    """Pass B's rows, in the order of `ITEMS`."""
    lookups: Lookups


def record_both(
    project: Project,
    ctr_a: Actor,
    ctr_b: Actor,
    source: str,
    items: list[ExtractedRowInput],
    *,
    supersedes_a: Mapping[int, str] | None = None,
    supersedes_b: Mapping[int, str] | None = None,
    items_b: list[ExtractedRowInput] | None = None,
) -> tuple[list[str], list[str]]:
    """Both passes read `source`, record `items` (so every item is agreed) and close. Other
    units served on the way are parked. Returns the row ids of pass A and of pass B."""
    ids: list[list[str]] = []
    for actor, label, sup, rows in (
        (ctr_a, PassLabel.A, supersedes_a, items),
        (ctr_b, PassLabel.B, supersedes_b, items if items_b is None else items_b),
    ):
        served = contribution_next(project, actor, label).batch
        assert isinstance(served, ContributionBatch)
        while served.records[0]["work_id"] != source:
            contribution_record(project, actor, served.task_id, [], finish=True, reason="parked")
            served = contribution_next(project, actor, label).batch
            assert isinstance(served, ContributionBatch)
        res = contribution_record(
            project, actor, served.task_id, rows, finish=True, reason="no results", supersedes=sup
        )
        assert len(res.rows.written) == len(rows), res.rows.rejected
        ids.append(res.rows.written)
    return ids[0], ids[1]


def build_lineage(
    project: Project,
    agent: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    world: list[str],
    items_b: list[ExtractedRowInput] | None = None,
) -> Lineage:
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
    five, three = view.entry(5), view.entry(3)
    assert five is not None and three is not None
    assert five.link_work is not None and three.link_work is not None
    if items_b is None:
        ids_a, ids_b = record_both(project, ctr_a, ctr_b, source, ITEMS)
    else:  # the passes differ
        ids_a, _ = record_both(project, ctr_a, ctr_b, source, ITEMS, items_b=items_b)
        ids_b = []
    base, addition, uncited, limitation = ids_a
    return Lineage(
        source=source,
        rex=rex,
        base=base,
        addition=addition,
        uncited_base=uncited,
        limitation=limitation,
        target5=five.link_work,
        target3=three.link_work,
        ids_b=ids_b,
        lookups=lookups,
    )


@pytest.fixture
def lin(project: Project, agent: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]) -> Lineage:
    return build_lineage(project, agent, ctr_a, ctr_b, world)


@pytest.fixture
def disputed(
    project: Project, agent: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]
) -> Lineage:
    """Pass B reads the base idea as citing entry 3: the base item is an open disagreement."""
    rows_b = [item("base-idea", P1, name="linear attention", cited_entry=field(3)), *ITEMS[1:]]
    built = build_lineage(project, agent, ctr_a, ctr_b, world, items_b=rows_b)
    for actor, label in ((ctr_a, PassLabel.A), (ctr_b, PassLabel.B)):  # agreement needs all units
        served = contribution_next(project, actor, label).batch
        while isinstance(served, ContributionBatch):
            contribution_record(project, actor, served.task_id, [], finish=True, reason="parked")
            served = contribution_next(project, actor, label).batch
    return built

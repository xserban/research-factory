"""Shared builders of the miner tests: a `VISION_RESULT_V1` spec, a world that lists it, rows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from factory.document.anchors import AnchorKind
from factory.events.envelope import Actor
from factory.mining.spec import (
    EnumKind,
    EvidenceRule,
    MinerField,
    MinerRegime,
    MinerSpec,
    NumberKind,
    Population,
    QuoteKind,
    Selector,
    spec_to_json,
)
from factory.model.extraction import ExtractedRowInput, FieldInput
from factory.model.miners import MinerUse
from factory.model.screening import PassLabel
from factory.packs.model import UnitFamily
from factory.services.context import Project
from factory.services.mining import mine_next, mine_record, register_miner
from factory.services.protocol import amend_protocol, current_protocol
from tests.extraction_helpers import _extractor

VISION_NAME = "m-vision-result"
SESSION_M1 = "01JZ9Q3K5M7N8P0R2S4T6V8W1E"
SESSION_M2 = "01JZ9Q3K5M7N8P0R2S4T6V8W1F"


def vision_result(**over: Any) -> MinerSpec:
    """A small registered miner: a metric, its number and an evidence quote, per result."""
    spec = MinerSpec(
        name=VISION_NAME,
        version=1,
        selector=Selector(
            Population.INCLUDED_FT,
            elements=(AnchorKind.PARAGRAPH, AnchorKind.TABLE),
            heading_patterns=("results",),
            max_units=20,
        ),
        fields=(
            MinerField("metric", "result", QuoteKind(), required=True),
            MinerField(
                "value",
                "result",
                NumberKind(UnitFamily.SCORE, ("%", "fraction", "")),
                required=True,
            ),
            MinerField("direction", "result", EnumKind(("higher", "lower"))),
            MinerField("evidence", "evidence", QuoteKind(), compared=False),
        ),
        row_key_fields=("metric",),
        row_anchor_fields=("metric",),
        conditionals=(),
        evidence=EvidenceRule(1, True),
        procedure="rf-extract",
        regime=MinerRegime(2, 10, 0.8, 0.9),
        rationale="Report the headline metric of each result.",
    )
    return replace(spec, **over) if over else spec


def method_vision(**over: Any) -> MinerSpec:
    """`vision_result` selecting the fixture document's Method section (paragraph and table)."""
    spec = vision_result()
    return replace(spec, selector=replace(spec.selector, heading_patterns=("method",)), **over)


def mine_row(direction: str = "higher") -> ExtractedRowInput:
    """A row of `vision_result` in the fixture document: the table row `Lorem | 1 | 2`."""
    return ExtractedRowInput(
        fields={
            "metric": FieldInput(value="Lorem", anchor="t1.r3.c1", quote="Lorem"),
            "value": FieldInput(value="1", anchor="t1", cell="t1.r3.c2", quote="1"),
            "direction": FieldInput(value=direction, anchor="s3.p1", quote="Lorem ipsum"),
            "evidence": FieldInput(
                value="Lorem ipsum dolor sit amet.",
                anchor="s3.p1",
                quote="Lorem ipsum dolor sit amet.",
            ),
        }
    )


def use(spec: MinerSpec | None = None, **over: Any) -> MinerUse:
    chosen = spec or vision_result()
    base: dict[str, Any] = {
        "name": chosen.name,
        "version": chosen.version,
        "dual_extract_sample": 1.0,
        "audit_fraction": 0.05,
        "audit_minimum": 50,
    }
    base.update(over)
    return MinerUse.model_validate(base)


def list_miner(project: Project, agent: Actor, spec: MinerSpec | None = None) -> MinerSpec:
    """Register `spec` and amend the protocol to list it (every work mined twice)."""
    chosen = spec or method_vision()
    register_miner(project, agent, spec_to_json(chosen))
    current = current_protocol(project)
    assert current is not None
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"miners": (*(current.spec.miners or ()), use(chosen))}),
        reason="list the miner",
        semantic=True,
        effects={},
    )
    return chosen


def miner_actor(session: str, model: str) -> Actor:
    return _extractor(session, model)


RowsFor = Callable[[str], list[ExtractedRowInput]]


def mine_pass(
    project: Project,
    actor: Actor,
    label: PassLabel,
    rows_for: RowsFor,
    *,
    name: str = VISION_NAME,
    version: int = 1,
) -> list[str]:
    """Serve every task of the pass and record `rows_for(work)` in it, closing each unit; returns
    the works mined."""
    done: list[str] = []
    for _ in range(100):
        batch = mine_next(project, actor, name, version, label).batch
        if batch is None:
            return done
        work = batch.records[0]["work_id"]
        rows = rows_for(work)
        result = mine_record(
            project, actor, batch.task_id, rows, finish=True, reason=None if rows else "no result"
        )
        assert result.completed, result.rows.rejected
        done.append(work)
    raise AssertionError("too many tasks")

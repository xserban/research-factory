"""Which earlier decisions an amendment's stale rules make doubtful (R-15).

Pure: the services and the index projector both evaluate the rules here, so they agree.
"""

from __future__ import annotations

from collections.abc import Sequence

from factory.model.base import StrictModel
from factory.model.protocol import ProtocolAmended, ScreeningStage, StaleRule


class DecisionRef(StrictModel):
    """A screening decision as the stale rules see it. `criterion` is version-qualified
    (`P@1a2b3c4d:EX03`); `protocol_id` is the version the decision was recorded under."""

    decision_id: str
    verdict: str
    criterion: str | None
    protocol_id: str
    stage: ScreeningStage
    at: str | None = None
    """The recording position (event ID) of the decision; with `amended_at` it fixes which
    amendments came after it."""


def stale_decisions(
    amendments: Sequence[ProtocolAmended],
    lineage: Sequence[str],
    decisions: Sequence[DecisionRef],
    *,
    amended_at: Sequence[str] | None = None,
) -> list[str]:
    """The ids of decisions an amendment's stale rules make doubtful, sorted and unique.

    An amendment judges the decisions recorded before it. With `amended_at` (the event ID of
    each amendment, parallel to `amendments`) and `DecisionRef.at` that is a comparison of
    recording order, so in a reverted amendment (A to B, then B to A) a decision recorded before
    A to B is judged by both A to B and B to A, and one recorded between them by B to A only.
    Without them a decision is in scope of amendment A only when its version comes before
    `A.to_version` in `lineage` (first occurrence). Stages match when they
    are equal or either side is `either`."""
    position: dict[str, int] = {}
    for index, version in enumerate(lineage):
        position.setdefault(version, index)

    stale: set[str] = set()
    for index, amendment in enumerate(amendments):
        if not amendment.stale_rules:
            continue
        when = None if amended_at is None else amended_at[index]
        target = position.get(amendment.to_version)
        for decision in decisions:
            if when is not None and decision.at is not None:
                if decision.at >= when:
                    continue
            else:
                origin = position.get(decision.protocol_id)
                if target is None or origin is None or origin >= target:
                    continue
            if any(_stales(rule, decision) for rule in amendment.stale_rules):
                stale.add(decision.decision_id)
    return sorted(stale)


def _stales(rule: StaleRule, decision: DecisionRef) -> bool:
    if rule.stage is not ScreeningStage.EITHER and decision.stage not in (
        rule.stage,
        ScreeningStage.EITHER,
    ):
        return False
    if rule.stales == "untested":
        return True
    if rule.stales == "inclusions":
        return decision.verdict == "include"
    return decision.verdict == "exclude" and _cid(decision.criterion) == rule.criterion


def _cid(criterion: str | None) -> str | None:
    return None if criterion is None else criterion.rsplit(":", 1)[-1]

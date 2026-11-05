"""Shared builders for the card tests (slice 6, plan H-A)."""

from __future__ import annotations

from typing import Any

from factory.events.envelope import Actor
from factory.model.cards import PropertyDef
from factory.services.context import Project
from factory.services.properties import decide_property, propose_property


def prop(key: str = "pr:sampling", **over: Any) -> PropertyDef:
    """An enum property by default; keyword overrides replace fields."""
    base: dict[str, Any] = {
        "key": key,
        "kind": "enum",
        "allowed": ["regular", "irregular"],
        "match": "equal",
        "applies_to": "both",
        "value_aliases": {"irregular": ["irregularly sampled"]},
    }
    base.update(over)
    return PropertyDef.model_validate(base)


def approve(project: Project, proposer: Actor, decider: Actor, definition: PropertyDef) -> None:
    """Propose `definition` as `proposer` and approve it as `decider` (another session)."""
    propose_property(project, proposer, definition)
    decide_property(project, decider, definition.key, "approve", "fits the question")

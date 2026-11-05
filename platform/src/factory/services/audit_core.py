"""The audit lifecycle that screening and extraction share (slice M ruling 21, decisions 37, 51).

Both audits draw a random sample of an agreed set, bind it to a digest of that set, refuse a new
sample while an audit of the same set is open, take labels only from a human (relayed only by a
session that joined no pass), and compare an error rate with a ceiling. This module holds those
parts once; the services keep what differs (the population, the draw strata, the stored events).

Invariants:
- Everything here is deterministic except `validate_seed(None)`, which draws a seed from the
  operating system.
- No function writes an event or reads the log; refusals are `FactoryValidationError`s or issue
  lists the caller merges, so a refused call writes nothing.
- Texts and field names are those the two services used before they were merged.
"""

import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from factory.canonical import population_digest
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.screening import Channel
from factory.services import passes
from factory.services.context import Project

GateNoun = Literal["sample", "screening-label", "extraction-label", "gate-label", "draft-label"]

_ACTOR_TEXT: dict[str, str] = {
    "sample": "audit samples are drawn by a human",
    "screening-label": "audit labels are human acts",
    "extraction-label": "audit labels and evidence are for a human",
    "gate-label": "gate audit labels are human acts",
    "draft-label": "verdict audit labels are human acts",
}


@dataclass(frozen=True)
class AuditPopulation:
    """The agreed set an audit samples, as sorted `(key, provenance)` pairs.

    `keys[i]` identifies an item (a work, or a work/row/field location) and `provenance[i]` what
    its agreement rested on (a verdict, or the extraction id). The digest is order-independent."""

    keys: tuple[str, ...]
    provenance: tuple[str, ...]

    @classmethod
    def of(cls, pairs: Iterable[tuple[str, str]]) -> "AuditPopulation":
        ordered = sorted(pairs)
        return cls(tuple(k for k, _ in ordered), tuple(p for _, p in ordered))

    @property
    def digest(self) -> str:
        return population_digest(zip(self.keys, self.provenance, strict=True))

    def __len__(self) -> int:
        return len(self.keys)


def human_gate(
    project: Project,
    actor: Actor,
    channel: Channel,
    *,
    noun: GateNoun,
    gate_id: str | None = None,
) -> list[ValidationIssue]:
    """Issues for an audit act: a non-human `actor` (text by `noun`), and, for a label or an
    evidence read, an MCP relay from a session in a pass of any module (`channel`). A label names
    its decision gate, whose effective policy decides the actor check (`gates.gate_issues`)."""
    if gate_id is not None:
        from factory.services.gates import gate_issues  # gates imports this module

        return gate_issues(project, actor, gate_id, channel=channel, agent_text=_ACTOR_TEXT[noun])
    issues: list[ValidationIssue] = []
    if actor.kind != "human":
        issues.append(ValidationIssue("actor", _ACTOR_TEXT[noun]))
    if noun != "sample":
        issues.extend(passes.require_not_pass_session(project, actor, channel))
    return issues


def refuse_reopen(last_digest: str | None, population: AuditPopulation) -> None:
    """Raise (field `passes`) when the latest audit was drawn from this very set."""
    if last_digest == population.digest:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "passes",
                    "an audit of this agreed set is open; a new one waits for a change to it",
                )
            ]
        )


def validate_seed(random_seed: int | None) -> tuple[int, list[ValidationIssue]]:
    """The seed to draw with and the issues with it: a fresh 32-bit seed when None, else the
    given one, refused (field `random_seed`) outside 0..2**32-1."""
    seed = secrets.randbits(32) if random_seed is None else random_seed
    issues: list[ValidationIssue] = []
    if not 0 <= seed < 2**32:
        issues.append(ValidationIssue("random_seed", "must be an integer from 0 to 2**32 - 1"))
    return seed, issues


@dataclass(frozen=True)
class CeilingVerdict:
    """An error rate against its ceiling. `above` is False for an undefined rate."""

    rate: float | None
    ceiling: float
    above: bool
    enforced: bool


def ceiling_verdict(rate: float | None, ceiling: float, *, enforced: bool) -> CeilingVerdict:
    return CeilingVerdict(
        rate=rate, ceiling=ceiling, above=rate is not None and rate > ceiling, enforced=enforced
    )

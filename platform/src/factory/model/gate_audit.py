"""Events of the gate audit (slice M, M-B): a human's sample and labels over the agent acts at an
`agent_audit` gate. Written by `factory.services.gates`, folded by `factory.index.gates`."""

from __future__ import annotations

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.gates import GATE_ID_RE
from factory.model.identity import ULID_RE
from factory.model.screening import Channel

GATE_AUDIT_ID_RE = rf"^gau_{ULID_RE}$"


class GateAuditSampled(StrictModel):
    audit_id: str = Field(pattern=GATE_AUDIT_ID_RE)
    gate_id: str = Field(pattern=GATE_ID_RE)
    act_event_ids: tuple[str, ...]
    random_seed: int = Field(ge=0, lt=2**32)
    population: int = Field(ge=0)
    population_digest: str
    protocol_id: str | None = None


class GateAuditLabelled(StrictModel):
    audit_id: str = Field(pattern=GATE_AUDIT_ID_RE)
    act_event_id: str
    correct: bool
    note: str | None = None
    channel: Channel

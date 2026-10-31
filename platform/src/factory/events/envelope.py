from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
    model_validator,
)

from factory.canonical import canonical_json
from factory.events.blobs import BLOB_REF_RE
from factory.model.base import StrictModel
from factory.model.identity import ACTOR_ID_RE, SLUG_RE, ULID_RE, ulid_time

ActorKind = Literal["human", "agent", "system"]

SKILL_RE = r"^[a-z0-9][a-z0-9-]*@[0-9a-f]{8,64}$"
EVENT_ID_RE = rf"^ev_{ULID_RE}$"
_TS_FORMAT = "%Y-%m-%dT%H:%M:%S."
_ZERO = timedelta(0)


class Actor(StrictModel):
    kind: ActorKind
    id: str = Field(pattern=ACTOR_ID_RE)
    user: str = Field(pattern=ACTOR_ID_RE)
    session: str = Field(pattern=rf"^{ULID_RE}$")
    model: str | None = None
    skill: str | None = Field(default=None, pattern=SKILL_RE)

    @model_validator(mode="after")
    def _model_and_skill_follow_kind(self) -> Self:
        if self.kind == "agent":
            if self.model is None or self.skill is None:
                raise ValueError("agent actors must set both model and skill")
        elif self.model is not None or self.skill is not None:
            raise ValueError(f"{self.kind} actors must not set model or skill")
        return self


class Event(StrictModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(pattern=EVENT_ID_RE)
    ts: datetime
    project: str = Field(pattern=SLUG_RE)
    type: str
    schema_version: int = Field(alias="schema", ge=1)
    actor: Actor
    refs: tuple[str, ...] = ()
    input_blob: str | None = Field(default=None, pattern=BLOB_REF_RE)
    payload: dict[str, JsonValue]

    @field_validator("ts")
    @classmethod
    def _ts_is_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != _ZERO:
            raise ValueError("ts must be a UTC timestamp")
        return value

    @field_validator("refs")
    @classmethod
    def _refs_are_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not ref for ref in value):
            raise ValueError("refs must be non-empty strings")
        return value

    @model_validator(mode="after")
    def _ts_matches_id_and_agents_have_input(self) -> Self:
        if self.ts != ulid_time(self.id[len("ev_") :]):
            raise ValueError("ts must equal the timestamp encoded in id")
        if self.actor.kind == "agent" and self.input_blob is None:
            raise ValueError("agent events must reference an input_blob")
        return self

    @field_serializer("ts", when_used="json")
    def _serialize_ts(self, value: datetime) -> str:
        return value.strftime(_TS_FORMAT) + f"{value.microsecond // 1000:03d}Z"

    def to_line(self) -> bytes:
        data: dict[str, JsonValue] = self.model_dump(mode="json", by_alias=True)
        return canonical_json(data) + b"\n"

    @classmethod
    def from_line(cls, line: bytes) -> Self:
        return cls.model_validate_json(line)

import re
from datetime import timedelta

import pytest
from pydantic import ValidationError

from factory.clock import FixedClock
from factory.model.base import StrictModel
from factory.model.identity import ULID_RE, IdGenerator, is_prefixed_id, ulid_time
from tests.helpers import T0


def test_ulids_are_strictly_increasing_within_one_millisecond(clock: FixedClock) -> None:
    gen = IdGenerator(clock)
    ids = [gen.ulid() for _ in range(1000)]
    assert ids == sorted(ids) and len(set(ids)) == 1000


def test_ulids_stay_increasing_when_clock_goes_backwards(clock: FixedClock) -> None:
    gen = IdGenerator(clock)
    a = gen.ulid()
    clock.advance(timedelta(seconds=-5))
    assert gen.ulid() > a


def test_ulid_time_round_trips_to_the_millisecond(clock: FixedClock) -> None:
    clock.advance(timedelta(microseconds=123_456))
    gen = IdGenerator(clock)
    assert ulid_time(gen.ulid()) == T0 + timedelta(milliseconds=123)


def test_prefixed_ids(clock: FixedClock) -> None:
    tid = IdGenerator(clock).new("tsk")
    assert re.fullmatch(r"tsk_" + ULID_RE, tid)
    assert is_prefixed_id(tid, "tsk") and not is_prefixed_id(tid, "ev")
    assert not is_prefixed_id("tsk_short", "tsk")


def test_strict_model_rejects_unknown_fields_and_mutation() -> None:
    class M(StrictModel):
        a: int

    with pytest.raises(ValidationError):
        M(a=1, b=2)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        M(a=1).a = 2  # type: ignore[misc]

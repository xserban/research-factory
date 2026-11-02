from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from factory.events.catalog import default_catalog
from factory.model.chase import (
    CHASE_CHUNK,
    CHASE_ROUND_ID_RE,
    ChaseDirection,
    ChaseRoundStarted,
    SampleExtended,
    SeedAdmitted,
)
from factory.model.screening import PassLabel

ROUND = "chs_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
RUN = "run_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
SEED = "SEED01"
W1 = "rf:jones2021-sparse-1e2f3a4b"
W2 = "rf:smith2020-attention-0a1b2c3d"


def round_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "round_id": ROUND,
        "directions": (ChaseDirection.BACKWARD, ChaseDirection.FORWARD),
        "from_works": (W1, W2),
        "unchasable": (),
        "queries": ("cited_by:W1|W2", "cites:W1|W2"),
    }
    base.update(overrides)
    return base


def test_chase_chunk_and_round_prefix() -> None:
    assert CHASE_CHUNK == 50
    assert re.fullmatch(CHASE_ROUND_ID_RE, ROUND)
    assert not re.fullmatch(CHASE_ROUND_ID_RE, RUN)


def test_round_accepts_both_directions() -> None:
    round_ = ChaseRoundStarted.model_validate(round_kwargs())
    assert round_.directions == (ChaseDirection.BACKWARD, ChaseDirection.FORWARD)


def test_round_requires_source_works() -> None:
    with pytest.raises(ValidationError):
        ChaseRoundStarted.model_validate(round_kwargs(from_works=(), queries=()))


def test_round_source_works_sorted_and_unique() -> None:
    with pytest.raises(ValidationError):
        ChaseRoundStarted.model_validate(round_kwargs(from_works=(W2, W1)))
    with pytest.raises(ValidationError):
        ChaseRoundStarted.model_validate(round_kwargs(from_works=(W1, W1)))


def test_round_directions_unique() -> None:
    with pytest.raises(ValidationError):
        ChaseRoundStarted.model_validate(
            round_kwargs(directions=(ChaseDirection.BACKWARD, ChaseDirection.BACKWARD))
        )


def test_round_directions_nonempty() -> None:
    with pytest.raises(ValidationError):
        ChaseRoundStarted.model_validate(round_kwargs(directions=()))


def test_round_id_must_be_chs_prefixed() -> None:
    with pytest.raises(ValidationError):
        ChaseRoundStarted.model_validate(round_kwargs(round_id=RUN))


def test_sample_extension_added_subset() -> None:
    with pytest.raises(ValidationError):
        SampleExtended(pass_label=PassLabel.B, random_seed=7, considered=(W1,), added=(W1, W2))


def test_sample_extension_accepts_subset() -> None:
    extended = SampleExtended(
        pass_label=PassLabel.B, random_seed=7, considered=(W1, W2), added=(W2,)
    )
    assert extended.added == (W2,)


def test_sample_extension_pass_a_rejected() -> None:
    with pytest.raises(ValidationError):
        SampleExtended(pass_label=PassLabel.A, random_seed=7, considered=(W1,), added=())


def test_sample_extension_seed_in_range() -> None:
    with pytest.raises(ValidationError):
        SampleExtended(pass_label=PassLabel.B, random_seed=-1, considered=(), added=())
    with pytest.raises(ValidationError):
        SampleExtended(pass_label=PassLabel.B, random_seed=2**32, considered=(), added=())


def test_seed_admitted_fields() -> None:
    admitted = SeedAdmitted(seed_id=SEED, run_id=RUN, work_id=None)
    assert admitted.work_id is None
    with pytest.raises(ValidationError):
        SeedAdmitted(seed_id="NEG01", run_id=RUN, work_id=None)
    with pytest.raises(ValidationError):
        SeedAdmitted(seed_id=SEED, run_id="run_bad", work_id=None)


def test_catalog_registers_chase_events_at_schema_one() -> None:
    catalog = default_catalog()
    for name in ("chase.round_started", "screening.sample_extended", "seed.admitted"):
        assert name in catalog
        assert catalog.get(name).schema == 1
    assert catalog.get("chase.round_started").payload is ChaseRoundStarted
    assert catalog.get("screening.sample_extended").payload is SampleExtended
    assert catalog.get("seed.admitted").payload is SeedAdmitted

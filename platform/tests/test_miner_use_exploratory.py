"""`MinerUse.exploratory`: declared by a protocol amendment, omitted when false (IDEA-69)."""

import pytest
from pydantic import ValidationError

from factory.model.miners import MinerUse

BASE = {"name": "m-vision-result", "version": 1}


def test_false_is_omitted_so_existing_hashes_are_unchanged() -> None:
    use = MinerUse.model_validate(BASE)
    assert use.exploratory is False
    assert "exploratory" not in use.model_dump(mode="json")
    explicit = MinerUse.model_validate({**BASE, "exploratory": False})
    assert use.model_dump_json() == explicit.model_dump_json()


def test_true_is_dumped_and_read_back() -> None:
    use = MinerUse.model_validate({**BASE, "exploratory": True})
    dumped = use.model_dump(mode="json")
    assert dumped["exploratory"] is True
    assert MinerUse.model_validate(dumped) == use


def test_exploratory_with_evidence_is_refused() -> None:
    with pytest.raises(ValidationError, match="exploratory"):
        MinerUse.model_validate({**BASE, "exploratory": True, "evidence": True})

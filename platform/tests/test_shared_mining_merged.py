"""A shared-mining unit whose conversion belongs to a work merged into another is judged under the
canonical work: the importer's mined and calibration sets hold canonical ids (IDEA-82)."""

from types import SimpleNamespace
from typing import Any

import pytest

from factory.services import shared_mining
from factory.services.shared_mining import _Importer, _SourceUnit, _unit_items


def _importer(*, mined: set[str], calibration: set[str]) -> _Importer:
    return _Importer(
        project=None,  # type: ignore[arg-type]
        spec=None,  # type: ignore[arg-type]
        held={"h": "c-1"},
        corpus=frozenset(),
        mined=frozenset(mined),
        calibration=frozenset(calibration),
        canonical={"w-absorbed": "w-primary"},
    )


def _unit() -> _SourceUnit:
    return _SourceUnit(
        work_id="w-src",
        conversion_id="c-src",
        hashed="h",
        final=True,
        rows=(object(),),  # type: ignore[arg-type]
    )


@pytest.fixture(autouse=True)
def _conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(project: Any, conversion_id: str) -> Any:
        return SimpleNamespace(work_id="w-absorbed", conversion_id=conversion_id)

    monkeypatch.setattr(shared_mining, "conversion_of", fake)


def test_absorbed_owner_of_a_mined_work_is_refused() -> None:
    items, issues = _unit_items(_importer(mined={"w-primary"}, calibration=set()), _unit(), "mim-1")
    assert items == []
    assert [i.reason for i in issues] == [shared_mining._MINED_HERE]


def test_absorbed_owner_of_a_calibration_work_is_refused() -> None:
    items, issues = _unit_items(_importer(mined=set(), calibration={"w-primary"}), _unit(), "mim-1")
    assert items == []
    assert [i.reason for i in issues] == [shared_mining._CALIBRATION]

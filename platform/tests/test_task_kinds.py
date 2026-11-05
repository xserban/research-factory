"""Task kinds come from the module registry; their strings are unchanged (decision 55)."""

import re
from pathlib import Path

import pytest

from factory.model.extraction import Scope
from factory.model.protocol import ScreeningStage
from factory.model.screening import PassLabel
from factory.model.task import INTUITION_TASK_KIND
from factory.services import stages
from factory.services.modules import default_task_kinds

SERVICES = Path(__file__).parent.parent / "src" / "factory" / "services"
A, B = PassLabel.A, PassLabel.B
TA, FT = ScreeningStage.TITLE_ABSTRACT, ScreeningStage.FULL_TEXT


def test_kinds_unchanged() -> None:
    assert stages.task_kind(TA, A) == "screen_a"
    assert stages.task_kind(TA, B) == "screen_b"
    assert stages.task_kind(FT, A) == "screen_ft_a"
    assert stages.task_kind(FT, B) == "screen_ft_b"
    assert stages.EXTRACT_KINDS == {A: "extract_a", B: "extract_b"}
    assert stages.CONTRIB_KINDS == {A: "contrib_a", B: "contrib_b"}
    assert stages.kinds_for(Scope.EVIDENCE) == {A: "extract_a", B: "extract_b"}
    assert stages.kinds_for(Scope.CONTRIBUTION) == {A: "contrib_a", B: "contrib_b"}
    assert default_task_kinds().kinds() == (
        "screen_a",
        "screen_b",
        "screen_ft_a",
        "screen_ft_b",
        "extract_a",
        "extract_b",
        "contrib_a",
        "contrib_b",
        INTUITION_TASK_KIND,
    )


def test_stage_of_kind_inverse() -> None:
    for stage in (TA, FT):
        for label in (A, B):
            assert stages.stage_of_kind(stages.task_kind(stage, label)) is stage
    for scope in Scope:
        for label in (A, B):
            assert stages.scope_of_kind(stages.kinds_for(scope)[label]) is scope
    assert stages.stage_of_kind("extract_a") is None
    assert stages.scope_of_kind("screen_a") is None
    assert stages.stage_of_kind("nonsense") is None
    assert stages.scope_of_kind("intuition") is None


def test_either_is_not_a_stage() -> None:
    with pytest.raises(Exception, match="not either"):
        stages.task_kind(ScreeningStage.EITHER, A)


def test_registry_describes_each_kind() -> None:
    registry = default_task_kinds()
    info = registry.describe("extract_b")
    assert info is not None
    assert (info.module, info.stage, info.label, info.scope) == ("extraction", None, B, "evidence")
    info = registry.describe("contrib_a")
    assert info is not None and info.module == "contributions" and info.scope == "contribution"
    info = registry.describe("screen_ft_a")
    assert info is not None and info.stage == "full-text" and info.module == "screening"


def test_no_kind_literals_outside_registry() -> None:
    pattern = re.compile(r"[\"'](screen_(?:ft_)?[ab]|extract_[ab]|contrib_[ab])[\"']")
    hits = {
        path.name: pattern.findall(path.read_text())
        for path in sorted(SERVICES.rglob("*.py"))
        if "modules" not in path.relative_to(SERVICES).parts and pattern.search(path.read_text())
    }
    assert hits == {}

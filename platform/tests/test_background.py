"""Exclusions kept as background (IDEA-47): the protocol flag, the derivation, the PRISMA subset
view and the snowball sources. Fixtures only; the protocol is patched in memory, never amended."""

import xml.etree.ElementTree as ET
from types import SimpleNamespace
from typing import cast

import pytest

from factory.cli.render import prisma_markdown
from factory.events.envelope import Actor
from factory.exports.prisma_svg import prisma_svg
from factory.model.protocol import (
    CriterionKind,
    ScreeningStage,
    SnowballPlan,
    protocol_version,
)
from factory.model.references import Direction
from factory.services import screening, snowball
from factory.services.agreement import Outcome, final_outcomes
from factory.services.context import Project
from factory.services.prisma import prisma_flow
from factory.services.protocol import ProtocolVersion, current_protocol
from factory.services.snowball import BACKGROUND_NOT_EXTRACTED, NOT_EXTRACTED, plan_round
from tests.helpers import SourcesFor
from tests.screening_helpers import _decide
from tests.test_agreement import _b_queue, _ordinary, _ready
from tests.test_protocol_model import _criterion, _spec

NS = "{http://www.w3.org/2000/svg}"

# Hashes of the same specs on main before the flag existed (captured at 3609f4e).
MAIN_PLAIN = "P@ac674dc2"
MAIN_WITH_SNOWBALL_PLAN = "P@6c9dccf6"


def test_inclusion_cannot_be_background() -> None:
    with pytest.raises(ValueError, match="an inclusion cannot be background"):
        _criterion("IN01", background=True)
    assert _criterion("EX01", background=True).kind is CriterionKind.EXCLUSION


def test_flag_is_omitted_while_false_and_hashed_when_true() -> None:
    plain = _criterion("EX01")
    assert "background" not in plain.model_dump(mode="json")
    assert "background" not in _criterion("EX01", background=False).model_dump(mode="json")
    flagged = _criterion("EX01", background=True)
    assert flagged.model_dump(mode="json")["background"] is True
    assert protocol_version(_spec()) == MAIN_PLAIN
    explicit_false = _spec(criteria=(_criterion("IN01"), _criterion("EX01", background=False)))
    assert protocol_version(explicit_false) == MAIN_PLAIN
    flagged_spec = _spec(criteria=(_criterion("IN01"), _criterion("EX01", background=True)))
    assert protocol_version(flagged_spec) != MAIN_PLAIN


def test_snowball_flag_is_omitted_while_false() -> None:
    plan = SnowballPlan(max_backward_rounds=2, max_forward_rounds=1)
    assert "background_sources" not in plan.model_dump(mode="json")
    assert protocol_version(_spec(snowball_plan=plan)) == MAIN_WITH_SNOWBALL_PLAN
    on = plan.model_copy(update={"background_sources": True})
    assert on.model_dump(mode="json")["background_sources"] is True
    assert protocol_version(_spec(snowball_plan=on)) != MAIN_WITH_SNOWBALL_PLAN


def _background(monkeypatch: pytest.MonkeyPatch, criterion: str) -> None:
    """Read the project's current protocol as if `criterion` carried `background: true`."""
    real = current_protocol

    def patched(project: Project) -> ProtocolVersion | None:
        protocol = real(project)
        if protocol is None:
            return None
        criteria = tuple(
            c.model_copy(update={"background": True}) if c.id == criterion else c
            for c in protocol.spec.criteria
        )
        spec = protocol.spec.model_copy(update={"criteria": criteria})
        return protocol.model_copy(update={"spec": spec})

    monkeypatch.setattr(screening, "current_protocol", patched)


def _exclude_agreed(project: Project, agent: Actor, protocol_id: str) -> tuple[str, str, str]:
    """The first ordinary works: agreed exclusion under EX01, under EX02, and an agreed include."""
    w1, w2, w3, *rest = _ordinary(project)
    for work, verdict, criterion in ((w1, "exclude", "EX01"), (w2, "exclude", "EX02")):
        _decide(project, agent, work, "A", "screening", verdict, criterion, protocol_id)
        _decide(project, agent, work, "B", "screening", verdict, criterion, protocol_id)
    for work in [w3, *rest]:
        _decide(project, agent, work, "A", "screening", "include", None, protocol_id)
        if work in _b_queue(project):
            _decide(project, agent, work, "B", "screening", "include", None, protocol_id)
    return w1, w2, w3


def test_background_works_and_flow_identities(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol_id = _ready(project, agent, human, mock_sources, dual_sample=1.0)
    w1, w2, w3 = _exclude_agreed(project, agent, protocol_id)

    assert screening.background_works(project) == {}
    before = prisma_flow(project)
    assert before.background == {} and "background" not in before.model_dump(mode="json")

    _background(monkeypatch, "EX02")
    kept = screening.background_works(project)
    assert kept == {w2: "EX02"}
    assert screening.background_works(project, stage=ScreeningStage.FULL_TEXT) == {}
    assert final_outcomes(project)[w2] is Outcome.EXCLUDED  # never a verdict

    flow = prisma_flow(project)
    assert flow.background == {"EX02": 1}
    assert flow.excluded == before.excluded  # a subset view: nothing moved
    assert flow.included == before.included and flow.included >= 1
    assert flow.excluded_total + flow.pending + flow.included == flow.screened
    assert w3 not in kept and w1 not in kept
    assert flow.model_dump(mode="json")["background"] == {"EX02": 1}
    assert "  - of which kept as background: 1 (EX02)" in prisma_markdown(flow)
    words = " ".join(t.text or "" for t in ET.fromstring(prisma_svg(flow)).iter(f"{NS}text"))
    assert "of which kept as background: 1 (EX02)" in words


def test_background_cannot_exceed_excluded() -> None:
    from factory.services.prisma import NOT_RUN_BOXES, FullTextBoxes

    with pytest.raises(ValueError, match="subset of the excluded"):
        FullTextBoxes.model_validate({**NOT_RUN_BOXES.model_dump(), "background": {"EX02": 1}})


def _scope_inputs(
    monkeypatch: pytest.MonkeyPatch, extracted: dict[str, str], documents: set[str]
) -> None:
    monkeypatch.setattr(snowball, "included_works", lambda project: ["w-in"])
    monkeypatch.setattr(snowball, "background_works", lambda project: dict.fromkeys(BG, "EX02"))
    monkeypatch.setattr(snowball, "current_extraction", lambda p, w: extracted.get(w))
    monkeypatch.setattr(
        snowball, "default_conversion", lambda p, w: "cnv" if w in documents else None
    )
    monkeypatch.setattr(snowball, "_has_document", lambda p, w: w in documents)
    monkeypatch.setattr(snowball, "_promoted_pending", lambda project: [])


BG = ["w-bg-ext", "w-bg-doc", "w-bg-none"]


def test_scope_takes_background_only_when_asked(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scope_inputs(
        monkeypatch,
        {"w-in": "rex1", "w-bg-ext": "rex2"},
        {"w-in", "w-bg-ext", "w-bg-doc"},
    )
    sources, ids, unextracted = snowball._scope(project)
    assert sources == ["w-in"] and ids == ["rex1"] and unextracted == []

    sources, ids, unextracted = snowball._scope(project, background=True)
    assert sources == ["w-in", "w-bg-ext"] and ids == ["rex1", "rex2"]
    assert unextracted == [("w-bg-doc", BACKGROUND_NOT_EXTRACTED)]  # w-bg-none has no document


def test_plan_round_background_never_blocks(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scope_inputs(
        monkeypatch,
        {"w-in": "rex1", "w-bg-ext": "rex2"},
        {"w-in", "w-bg-ext", "w-bg-doc"},
    )
    rule = SnowballPlan(max_backward_rounds=2, max_forward_rounds=1)
    for on in (False, True):
        plan = rule.model_copy(update={"background_sources": on})
        protocol = cast(ProtocolVersion, SimpleNamespace(spec=_spec(snowball_plan=plan)))
        monkeypatch.setattr(snowball, "current_protocol", lambda p, _v=protocol: _v)
        result = plan_round(project, Direction.BACKWARD)
        assert ("w-bg-ext" in result.sources) is on
        assert (("w-bg-doc", BACKGROUND_NOT_EXTRACTED) in result.unextracted) is on
        assert not any(reason == NOT_EXTRACTED for _, reason in result.unextracted)
        assert all(issue.field != "unextracted" for issue in result.state.refusals)
    forward = plan_round(project, Direction.FORWARD)
    assert "w-bg-ext" not in forward.sources and not forward.unextracted

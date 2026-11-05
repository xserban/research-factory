"""Relation and idea event payloads: shapes and the stated/inferred consistency rules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from factory.model.lineage import (
    IdeaMerged,
    IdeaProposed,
    IdeaUnmerged,
    RelationDecided,
    RelationProposal,
    RelationProposed,
)
from tests.lineage_payloads import (
    IDA,
    OTHER,
    SRC,
    TGT,
    decided,
    idea,
    inferred,
    merge,
    stated,
)


def test_agent_cannot_send_status() -> None:
    with pytest.raises(ValidationError):
        RelationProposal.model_validate(
            {"source_work": SRC, "target": TGT, "edge_type": "builds-on", "status": "stated"}
        )


def test_proposal_accepts_work_and_idea_targets() -> None:
    for target in (TGT, IDA):
        assert RelationProposal(source_work=SRC, target=target, edge_type="improves-on")
    with pytest.raises(ValidationError):
        RelationProposal(source_work=SRC, target="not-an-id", edge_type="builds-on")
    with pytest.raises(ValidationError):
        RelationProposal(source_work=SRC, target=TGT, edge_type="cites")  # type: ignore[arg-type]


def test_stated_round_trips() -> None:
    assert RelationProposed.model_validate(stated()).status == "stated"


@pytest.mark.parametrize(
    "overrides",
    [
        {"basis_item": None},
        {"reference_extraction_id": None},
        {"cited_entry": None},
        {"resolved_target": OTHER},
        {"status_reason": "target-differs"},
    ],
)
def test_stated_requires_basis_and_matching_target(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RelationProposed.model_validate(stated(**overrides))


def test_inferred_requires_reason() -> None:
    assert RelationProposed.model_validate(inferred()).status_reason is not None
    with pytest.raises(ValidationError):
        RelationProposed.model_validate(inferred(status_reason=None))


def test_no_basis_requires_note() -> None:
    base = inferred(basis_item=None, status_reason="no-basis", reference_extraction_id=None)
    with pytest.raises(ValidationError):
        RelationProposed.model_validate({**base, "note": None})
    with pytest.raises(ValidationError):
        RelationProposed.model_validate({**base, "note": "  "})
    assert RelationProposed.model_validate({**base, "note": "from the abstract"})
    with pytest.raises(ValidationError):  # no basis must be reason no-basis
        RelationProposed.model_validate({**base, "note": "n", "status_reason": "target-differs"})
    with pytest.raises(ValidationError):  # a basis cannot be no-basis
        RelationProposed.model_validate(inferred(status_reason="no-basis"))


def test_note_limit() -> None:
    with pytest.raises(ValidationError):
        RelationProposed.model_validate(inferred(note="x" * 501))


def test_decision_needs_rationale() -> None:
    assert RelationDecided.model_validate(decided())
    with pytest.raises(ValidationError):
        RelationDecided.model_validate(decided(rationale=" "))


def test_idea_members_contain_origin_sorted_unique() -> None:
    assert IdeaProposed.model_validate(idea()).origin == TGT
    for members in ([SRC], [SRC, TGT], [TGT, TGT, SRC]):
        with pytest.raises(ValidationError):
            IdeaProposed.model_validate(idea(members=members))


def test_idea_name_bounds() -> None:
    for name in ("", "  ", "x" * 201):
        with pytest.raises(ValidationError):
            IdeaProposed.model_validate(idea(name=name))


def test_merge_into_self_rejected() -> None:
    with pytest.raises(ValidationError):
        IdeaMerged.model_validate(merge(IDA, IDA))
    with pytest.raises(ValidationError):
        IdeaUnmerged.model_validate(merge(IDA, IDA))
    assert IdeaUnmerged.model_validate(merge())

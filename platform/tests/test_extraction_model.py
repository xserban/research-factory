"""Extraction payload models and their catalog registration."""

import pytest
from pydantic import ValidationError

from factory.events.catalog import default_catalog
from factory.events.envelope import Actor
from factory.model.extraction import (
    AuditItemRef,
    ClaimInput,
    ExtractedRowInput,
    ExtractionAuditLabelled,
    ExtractionRecorded,
    ExtractionResolved,
    FieldInput,
    StoredField,
)
from factory.services.context import Project

EXT = "ext_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
TASK = "tsk_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
DOC = "doc_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
CNV = "cnv_01HZX3K4M5N6P7Q8R9S0TVWXYZ"


def test_field_input_rejects_unknown_key() -> None:
    with pytest.raises(ValidationError):
        FieldInput.model_validate({"value": "x", "bogus": 1})
    with pytest.raises(ValidationError):
        ExtractedRowInput.model_validate({"fields": {}})


@pytest.mark.parametrize("name", ["", "   ", "*"])
def test_field_name_must_be_non_blank_and_not_whole_row_marker(name: str) -> None:
    with pytest.raises(ValidationError):
        ExtractedRowInput.model_validate({"fields": {name: {"value": 1}}})
    with pytest.raises(ValidationError):
        ExtractionResolved.model_validate(
            {
                "work_id": "rf:w",
                "row_key": "rk_0123456789ab",
                "field": name,
                "choice": "a",
                "reason": "r",
                "channel": "cli",
                "protocol_id": "P@1a2b3c4d",
            }
        )
    with pytest.raises(ValidationError):
        AuditItemRef(work_id="rf:w", row_key="rk_0123456789ab", field=name)
    with pytest.raises(ValidationError):
        ExtractionAuditLabelled(
            audit_id="xau_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
            work_id="rf:w",
            row_key="rk_0123456789ab",
            field=name,
            correct=True,
            channel="cli",
        )


def test_resolution_may_name_no_field_for_whole_row() -> None:
    resolved = ExtractionResolved.model_validate(
        {
            "work_id": "rf:w",
            "row_key": "rk_0123456789ab",
            "field": None,
            "choice": "neither",
            "reason": "r",
            "channel": "cli",
            "protocol_id": "P@1a2b3c4d",
        }
    )
    assert resolved.field is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_are_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        FieldInput(value=value)
    with pytest.raises(ValidationError):
        StoredField(value=value, canonical=None, copy_marker=False)
    assert FieldInput(value=1.5).value == 1.5


def test_verifier_must_be_at_least_one() -> None:
    base = _recorded_kwargs()
    assert ExtractionRecorded(**{**base, "verifier": 1}).verifier == 1
    with pytest.raises(ValidationError):
        ExtractionRecorded(**{**base, "verifier": 0})


def _recorded_kwargs() -> dict[str, object]:
    return {
        "extraction_id": EXT,
        "work_id": "rf:jones2021-sparse-1e2f3a4b",
        "pass_label": "A",
        "task_id": TASK,
        "protocol_id": "P@1a2b3c4d",
        "schema_ref": "ml-benchmark@1",
        "document_id": DOC,
        "conversion_id": CNV,
        "row_key": "rk_0123456789ab",
        "fields": {"value": StoredField(value=1, canonical="1", copy_marker=False)},
        "supersedes": None,
        "verifier": 1,
    }


def test_cell_form_is_checked() -> None:
    assert FieldInput(value=1, cell="t2.r5.c3").cell == "t2.r5.c3"
    with pytest.raises(ValidationError):
        FieldInput(value=1, cell="t2.r5")


def test_agent_event_needs_input_blob(project: Project) -> None:
    payload = ExtractionRecorded(
        extraction_id=EXT,
        work_id="rf:jones2021-sparse-1e2f3a4b",
        pass_label="A",
        task_id=TASK,
        protocol_id="P@1a2b3c4d",
        schema_ref="ml-benchmark@1",
        document_id=DOC,
        conversion_id=CNV,
        row_key="rk_0123456789ab",
        fields={"value": StoredField(value=1, canonical="1", copy_marker=False)},
        supersedes=None,
        verifier=1,
    )
    agent = Actor(
        kind="agent",
        id="extractor",
        user="obd",
        session=project.session,
        model="claude-opus-5-5",
        skill="rf-extract@1a2b3c4d",
    )
    with pytest.raises(ValidationError):
        project.events.make("extraction.recorded", payload, agent)
    blob = project.blobs.put(b"instruction")
    assert project.events.make("extraction.recorded", payload, agent, input_blob=blob).input_blob


def test_unknown_claim_type_rejected() -> None:
    base = {
        "statement": "s",
        "claim_type": "finding",
        "evidence_type": "experiment",
        "strength": "strong",
        "anchor": "t2.r5.c3",
        "quote": "q",
    }
    assert ClaimInput.model_validate(base).statement == "s"
    with pytest.raises(ValidationError):
        ClaimInput.model_validate({**base, "claim_type": "opinion"})
    with pytest.raises(ValidationError):
        ClaimInput.model_validate({**base, "quote": "  "})


def test_stored_field_requires_copy_marker() -> None:
    with pytest.raises(ValidationError):
        StoredField.model_validate({"value": 1, "canonical": "1"})
    assert StoredField(value=1, canonical="1", copy_marker=False).copy_marker is False


def test_event_types_registered() -> None:
    names = default_catalog().names()
    for suffix in (
        "pass_opened",
        "pass_joined",
        "recorded",
        "claim_recorded",
        "closed",
        "resolved",
        "audit_sampled",
        "audit_labelled",
    ):
        assert f"extraction.{suffix}" in names

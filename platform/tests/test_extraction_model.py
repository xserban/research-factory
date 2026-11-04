"""Extraction payload models and their catalog registration."""

import pytest
from pydantic import ValidationError

from factory.events.catalog import default_catalog
from factory.events.envelope import Actor
from factory.model.extraction import (
    ClaimInput,
    ExtractedRowInput,
    ExtractionRecorded,
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
        fields={},
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

"""Scope on extraction events and in the projection (G2-A task 3).

A missing `pack` means evidence (every event written before G2); `contribution` rows live in
their own scope so passes, resolutions and audits never collide with evidence ones.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from factory.index.default import PROJECTION_VERSION
from factory.model.extraction import (
    CitedEntry,
    ExtractionAuditLabelled,
    ExtractionAuditSampled,
    ExtractionClosed,
    ExtractionPassJoined,
    ExtractionPassOpened,
    ExtractionRecorded,
    ExtractionResolved,
    Scope,
    StoredField,
    scope_of_pack,
    scope_of_schema_ref,
)
from factory.model.screening import Channel, PassLabel
from factory.services.context import Project
from tests.extraction_helpers import CNV, DOC, PROTOCOL, ROW, TASK, WORK, _record, _rows

REX = "rex_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
AUD = "xau_01HZX3K4M5N6P7Q8R9S0TVWXYZ"


def _opened(project: Project, pack: str | None, seed: int = 1) -> None:
    _record(
        project,
        "extraction.pass_opened",
        ExtractionPassOpened(
            pass_label=PassLabel.A, random_seed=seed, field_order="schema", pack=pack
        ),
    )


def _row(project: Project, ext: str, schema_ref: str, cited: CitedEntry | None = None) -> None:
    payload = ExtractionRecorded(
        extraction_id=ext,
        work_id=WORK,
        pass_label=PassLabel.A,
        task_id=TASK,
        protocol_id=PROTOCOL,
        schema_ref=schema_ref,
        document_id=DOC,
        conversion_id=CNV,
        row_key=ROW,
        fields={"v": StoredField(value="1", copy_marker=False)},
        supersedes=None,
        verifier=1,
        cited=cited,
    )
    _record(project, "extraction.recorded", payload, agent=True)


def _resolved(project: Project, pack: str | None, choice: Any) -> None:
    _record(
        project,
        "extraction.resolved",
        ExtractionResolved(
            work_id=WORK,
            row_key=ROW,
            field="v",
            choice=choice,
            reason="r",
            channel=Channel.CLI,
            protocol_id=PROTOCOL,
            pack=pack,
        ),
    )


def _sampled(project: Project, pack: str | None) -> None:
    _record(
        project,
        "extraction.audit_sampled",
        ExtractionAuditSampled.model_validate(
            {
                "audit_id": AUD,
                "items": [{"work_id": WORK, "row_key": ROW, "field": "v"}],
                "random_seed": 1,
                "population": 1,
                "population_digest": "d",
                "protocol_id": PROTOCOL,
                "pack": pack,
            }
        ),
    )


def test_scope_helpers() -> None:
    assert scope_of_pack(None) is Scope.EVIDENCE
    assert scope_of_pack("contribution") is Scope.CONTRIBUTION
    assert scope_of_schema_ref("ml-benchmark@1") is Scope.EVIDENCE
    assert scope_of_schema_ref("contribution@1") is Scope.CONTRIBUTION


def test_legacy_log_projects_to_evidence(project: Project) -> None:
    _opened(project, None)
    _record(
        project,
        "extraction.pass_joined",
        ExtractionPassJoined(pass_label=PassLabel.A, session="s1", model="m"),
    )
    _row(project, "ext_01HZX3K4M5N6P7Q8R9S0TVWXYA", "ml-benchmark@1")
    _record(
        project,
        "extraction.closed",
        ExtractionClosed(
            work_id=WORK, pass_label=PassLabel.A, task_id=TASK, rows=1, claims=0, reason=None
        ),
    )
    _resolved(project, None, "a")
    _sampled(project, None)
    for table in (
        "extraction_passes",
        "extraction_sessions",
        "extraction_rows",
        "extraction_closures",
        "extraction_resolutions",
        "extraction_audits",
        "extraction_audit_items",
    ):
        assert _rows(project, f"SELECT DISTINCT scope FROM {table}") == [("evidence",)], table
    assert _rows(
        project,
        "SELECT pack, cited_extraction_id, cited_ordinal, cited_marker FROM extraction_rows",
    ) == [(None, None, None, None)]


def test_two_scopes_have_independent_passes(project: Project) -> None:
    _opened(project, None, 1)
    _opened(project, "contribution", 2)
    assert _rows(project, "SELECT scope, random_seed FROM extraction_passes ORDER BY scope") == [
        ("contribution", 2),
        ("evidence", 1),
    ]


def test_session_joins_keep_scope(project: Project) -> None:
    _record(
        project,
        "extraction.pass_joined",
        ExtractionPassJoined(pass_label=PassLabel.A, session="s1", model="m", pack="contribution"),
    )
    assert _rows(project, "SELECT session, scope FROM extraction_sessions") == [
        ("s1", "contribution")
    ]


def test_resolution_keys_are_scope_local(project: Project) -> None:
    _resolved(project, None, "a")
    _resolved(project, "contribution", "b")
    _resolved(project, "contribution", "neither")
    assert _rows(project, "SELECT scope, choice FROM extraction_resolutions ORDER BY scope") == [
        ("contribution", "neither"),
        ("evidence", "a"),
    ]


def test_audits_and_closures_carry_scope(project: Project) -> None:
    _record(
        project,
        "extraction.closed",
        ExtractionClosed(
            work_id=WORK,
            pass_label=PassLabel.A,
            task_id=TASK,
            rows=0,
            claims=0,
            reason="no items",
            pack="contribution",
        ),
    )
    _sampled(project, "contribution")
    _record(
        project,
        "extraction.audit_labelled",
        ExtractionAuditLabelled(
            audit_id=AUD,
            work_id=WORK,
            row_key=ROW,
            field="v",
            correct=True,
            channel=Channel.CLI,
            pack="contribution",
        ),
    )
    assert _rows(project, "SELECT scope FROM extraction_closures") == [("contribution",)]
    assert _rows(project, "SELECT scope FROM extraction_audits") == [("contribution",)]
    assert _rows(project, "SELECT scope, correct FROM extraction_audit_items") == [
        ("contribution", 1)
    ]


def test_cited_entry_projected(project: Project) -> None:
    _row(
        project,
        "ext_01HZX3K4M5N6P7Q8R9S0TVWXYB",
        "contribution@1",
        CitedEntry(reference_extraction_id=REX, ordinal=3, marker="matched"),
    )
    assert _rows(
        project,
        "SELECT scope, pack, cited_extraction_id, cited_ordinal, cited_marker FROM extraction_rows",
    ) == [("contribution", "contribution", REX, 3, "matched")]


def test_cited_entry_shape() -> None:
    for bad in (
        {"reference_extraction_id": REX, "ordinal": 0, "marker": "matched"},
        {"reference_extraction_id": "ext_x", "ordinal": 1, "marker": "matched"},
        {"reference_extraction_id": REX, "ordinal": 1, "marker": "maybe"},
    ):
        with pytest.raises(ValidationError):
            CitedEntry.model_validate(bad)


def test_pack_column_indexed(project: Project) -> None:
    plan = _rows(
        project,
        "EXPLAIN QUERY PLAN SELECT extraction_id FROM extraction_rows WHERE pack = 'contribution'",
    )
    assert any("ix_extraction_rows_pack" in str(row) for row in plan)


def test_rebuild_state_hash_stable_with_both_scopes(project: Project) -> None:
    _opened(project, None, 1)
    _opened(project, "contribution", 2)
    _row(project, "ext_01HZX3K4M5N6P7Q8R9S0TVWXYA", "ml-benchmark@1")
    _row(
        project,
        "ext_01HZX3K4M5N6P7Q8R9S0TVWXYB",
        "contribution@1",
        CitedEntry(reference_extraction_id=REX, ordinal=1, marker="absent"),
    )
    _resolved(project, None, "a")
    _resolved(project, "contribution", "b")
    before = project.index.state_hash()
    project.index.rebuild()
    assert project.index.state_hash() == before


def test_projection_version_bumped() -> None:
    assert PROJECTION_VERSION == "89"

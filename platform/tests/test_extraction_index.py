"""Projection of extraction events: passes, rows, fields, claims, closures, resolutions, audits.

Events are recorded directly, as the other index tests do; the services are not needed to show
what the projector writes.
"""

from typing import Any

from sqlalchemy import text

from factory.events.envelope import Actor, Event
from factory.index.default import PROJECTION_VERSION
from factory.model.extraction import (
    AuditItemRef,
    ClaimRecorded,
    ClaimType,
    EvidenceType,
    ExtractionAuditLabelled,
    ExtractionAuditSampled,
    ExtractionClosed,
    ExtractionPassJoined,
    ExtractionPassOpened,
    ExtractionRecorded,
    ExtractionResolved,
    ReportedIn,
    StoredField,
    Strength,
)
from factory.model.protocol import ScreeningStage
from factory.model.screening import (
    Channel,
    DecisionRecorded,
    Framing,
    PassLabel,
    PassOpened,
    ScreeningPhase,
    Verdict,
)
from factory.services.context import Project

PROTOCOL = "P@1a2b3c4d"
WORK = "rf:jones2021-sparse-1e2f3a4b"
TASK = "tsk_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
DOC = "doc_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
CNV = "cnv_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
ROW = "rk_0123456789ab"
MODEL = "claude-opus-5-5"


def _agent(project: Project) -> Actor:
    return Actor(
        kind="agent",
        id="extractor",
        user="obd",
        session=project.session,
        model=MODEL,
        skill="rf-extract@1a2b3c4d",
    )


def _record(project: Project, type_: str, payload: Any, *, agent: bool = False) -> Event:
    if agent:
        blob = project.blobs.put(b"instruction")
        event = project.events.make(type_, payload, _agent(project), input_blob=blob)
    else:
        event = project.events.make(type_, payload, project.system_actor())
    project.record([event])
    return event


def _rows(project: Project, sql: str) -> list[tuple[Any, ...]]:
    with project.index.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql)).all()]


def _field(value: str, **kw: Any) -> StoredField:
    return StoredField(
        value=value, canonical=value, copy_marker=False, anchor="t2", cell="t2.r5.c3", **kw
    )


def _row(
    project: Project,
    ext: str,
    *,
    supersedes: str | None = None,
    row_key: str = ROW,
    fields: dict[str, StoredField] | None = None,
) -> Event:
    payload = ExtractionRecorded(
        extraction_id=ext,
        work_id=WORK,
        pass_label=PassLabel.A,
        task_id=TASK,
        protocol_id=PROTOCOL,
        schema_ref="ml-benchmark@1",
        document_id=DOC,
        conversion_id=CNV,
        row_key=row_key,
        fields=fields if fields is not None else {"value": _field("82.4", unit="%")},
        supersedes=supersedes,
        verifier=1,
    )
    return _record(project, "extraction.recorded", payload, agent=True)


def _resolved(project: Project, field: str | None, choice: str, reason: str) -> Event:
    payload = ExtractionResolved.model_validate(
        {
            "work_id": WORK,
            "row_key": ROW,
            "field": field,
            "choice": choice,
            "reason": reason,
            "channel": Channel.CLI,
            "protocol_id": PROTOCOL,
        }
    )
    return _record(project, "extraction.resolved", payload)


def test_projection_version_pinned() -> None:
    assert PROJECTION_VERSION == "28"


def test_pass_join_and_close_first_write_wins(project: Project) -> None:
    for seed, order in ((7, "schema"), (9, "reversed")):
        _record(
            project,
            "extraction.pass_opened",
            ExtractionPassOpened.model_validate(
                {"pass_label": "B", "random_seed": seed, "field_order": order}
            ),
        )
    for model in ("m1", "m2"):
        _record(
            project,
            "extraction.pass_joined",
            ExtractionPassJoined(pass_label=PassLabel.B, session=project.session, model=model),
        )
    for rows in (1, 5):
        _record(
            project,
            "extraction.closed",
            ExtractionClosed(
                work_id=WORK,
                pass_label=PassLabel.B,
                task_id=TASK,
                rows=rows,
                claims=0,
                reason=None,
            ),
        )
    assert _rows(project, "SELECT pass_label, random_seed, field_order FROM extraction_passes") == [
        ("B", 7, "schema")
    ]
    assert _rows(project, "SELECT session, pass_label, model FROM extraction_sessions") == [
        (project.session, "B", "m1")
    ]
    assert _rows(project, "SELECT task_id, work_id, rows, claims FROM extraction_closures") == [
        (TASK, WORK, 1, 0)
    ]


def test_fields_projected_per_field(project: Project) -> None:
    _row(
        project,
        "ext_01HZX3K4M5N6P7Q8R9S0TVWXY1",
        fields={
            "value": _field("82.4", unit="%", quote="82.4%", reproduced=True),
            "metric": StoredField(
                value="top-1",
                canonical="top-1",
                copy_marker=True,
                reported_in=ReportedIn.CITED,
                cited_work="rf:wang2021-x-aaaaaaaa",
            ),
        },
    )
    assert _rows(
        project,
        "SELECT field, value, unit, canonical, anchor, cell, quote, reported_in, copy_marker,"
        " reproduced, cited_work FROM extraction_fields ORDER BY field",
    ) == [
        (
            "metric",
            "top-1",
            None,
            "top-1",
            None,
            None,
            None,
            "cited",
            1,
            0,
            "rf:wang2021-x-aaaaaaaa",
        ),
        ("value", "82.4", "%", "82.4", "t2", "t2.r5.c3", "82.4%", "own", 0, 1, None),
    ]


def test_supersession_sets_superseded_by(project: Project) -> None:
    ext1 = "ext_01HZX3K4M5N6P7Q8R9S0TVWXY1"
    ext2 = "ext_01HZX3K4M5N6P7Q8R9S0TVWXY2"
    e1 = _row(project, ext1)
    e2 = _row(project, ext2, supersedes=ext1)
    assert _rows(
        project,
        "SELECT extraction_id, supersedes, superseded_by, event_id, row_key, pass_label,"
        " schema_ref FROM extraction_rows ORDER BY extraction_id",
    ) == [
        (ext1, None, ext2, e1.id, ROW, "A", "ml-benchmark@1"),
        (ext2, ext1, None, e2.id, ROW, "A", "ml-benchmark@1"),
    ]
    assert _rows(project, "SELECT extraction_id FROM extraction_fields ORDER BY extraction_id") == [
        (ext1,),
        (ext2,),
    ]


def test_claims_project_and_supersede(project: Project) -> None:
    ids = ["clm_01HZX3K4M5N6P7Q8R9S0TVWXY1", "clm_01HZX3K4M5N6P7Q8R9S0TVWXY2"]
    for i, supersedes in enumerate((None, ids[0])):
        _record(
            project,
            "extraction.claim_recorded",
            ClaimRecorded(
                claim_id=ids[i],
                work_id=WORK,
                pass_label=PassLabel.A,
                task_id=TASK,
                protocol_id=PROTOCOL,
                document_id=DOC,
                conversion_id=CNV,
                statement="It works.",
                claim_type=ClaimType.FINDING,
                evidence_type=EvidenceType.EXPERIMENT,
                strength=Strength.MODERATE,
                anchor="p3",
                quote="it works",
                supersedes=supersedes,
            ),
            agent=True,
        )
    assert _rows(
        project,
        "SELECT claim_id, claim_type, evidence_type, strength, superseded_by"
        " FROM extraction_claims ORDER BY claim_id",
    ) == [
        (ids[0], "finding", "experiment", "moderate", ids[1]),
        (ids[1], "finding", "experiment", "moderate", None),
    ]


def test_resolution_last_write_wins(project: Project) -> None:
    _resolved(project, "value", "a", "first")
    e2 = _resolved(project, "value", "b", "second")
    _resolved(project, None, "neither", "whole row")
    assert _rows(
        project,
        "SELECT field, choice, reason, event_id FROM extraction_resolutions ORDER BY field",
    ) == [
        (
            "*",
            "neither",
            "whole row",
            _rows(project, "SELECT event_id FROM extraction_resolutions WHERE field = '*'")[0][0],
        ),
        ("value", "b", "second", e2.id),
    ]


def test_audit_label_sets_correct(project: Project) -> None:
    audit = "xau_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
    items = (
        AuditItemRef(work_id=WORK, row_key=ROW, field="value"),
        AuditItemRef(work_id=WORK, row_key=ROW, field="metric"),
    )
    _record(
        project,
        "extraction.audit_sampled",
        ExtractionAuditSampled(
            audit_id=audit,
            items=items,
            random_seed=3,
            population=10,
            population_digest="sha256:abc",
            protocol_id=PROTOCOL,
        ),
    )
    assert _rows(
        project,
        "SELECT audit_id, random_seed, population, population_digest FROM extraction_audits",
    ) == [(audit, 3, 10, "sha256:abc")]
    assert _rows(project, "SELECT field, correct FROM extraction_audit_items ORDER BY field") == [
        ("metric", None),
        ("value", None),
    ]
    for correct, note in ((True, ""), (False, "wrong cell")):
        _record(
            project,
            "extraction.audit_labelled",
            ExtractionAuditLabelled(
                audit_id=audit,
                work_id=WORK,
                row_key=ROW,
                field="value",
                correct=correct,
                note=note,
                channel=Channel.CLI,
            ),
        )
    assert _rows(
        project, "SELECT field, correct, note FROM extraction_audit_items ORDER BY field"
    ) == [
        ("metric", None, ""),
        ("value", 0, "wrong cell"),
    ]


def test_handlers_are_total_for_unknown_references(project: Project) -> None:
    _record(
        project,
        "extraction.audit_labelled",
        ExtractionAuditLabelled(
            audit_id="xau_01HZX3K4M5N6P7Q8R9S0TVWXY9",
            work_id=WORK,
            row_key=ROW,
            field="value",
            correct=True,
            channel=Channel.MCP,
        ),
    )
    _row(project, "ext_01HZX3K4M5N6P7Q8R9S0TVWXY2", supersedes="ext_01HZX3K4M5N6P7Q8R9S0TVWXY0")
    assert _rows(project, "SELECT count(*) FROM extraction_rows") == [(1,)]
    assert _rows(project, "SELECT count(*) FROM extraction_audit_items") == [(0,)]


def _script(project: Project) -> None:
    ext1 = "ext_01HZX3K4M5N6P7Q8R9S0TVWXY1"
    _record(
        project,
        "extraction.pass_opened",
        ExtractionPassOpened.model_validate(
            {"pass_label": "A", "random_seed": 1, "field_order": "schema"}
        ),
    )
    _row(project, ext1)
    _row(project, "ext_01HZX3K4M5N6P7Q8R9S0TVWXY2", supersedes=ext1)
    _resolved(project, "value", "a", "r")
    _record(
        project,
        "extraction.closed",
        ExtractionClosed(
            work_id=WORK, pass_label=PassLabel.A, task_id=TASK, rows=1, claims=0, reason=None
        ),
    )


def test_rebuild_state_hash_stable(project: Project) -> None:
    _script(project)
    before = project.index.state_hash()
    assert project.index.rebuild() == before
    assert project.index.rebuild() == before


def test_extraction_events_leave_screening_tables_unchanged(project: Project) -> None:
    _record(
        project,
        "screening.pass_opened",
        PassOpened(
            pass_label=PassLabel.A,
            framing=Framing.INCLUSION,
            criterion_order="protocol",
            random_seed=1,
            sample=None,
        ),
    )
    _record(
        project,
        "screening.decision_recorded",
        DecisionRecorded(
            decision_id="dec_01HZX3K4M5N6P7Q8R9S0TVWXYZ",
            work_id=WORK,
            pass_label=PassLabel.A,
            phase=ScreeningPhase.SCREENING,
            stage=ScreeningStage.TITLE_ABSTRACT,
            verdict=Verdict.INCLUDE,
            criterion=None,
            quote="Paper",
            rationale="r",
            protocol_id=PROTOCOL,
            task_id=TASK,
            supersedes=None,
        ),
    )
    tables = [
        name
        for (name,) in _rows(
            project,
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'extraction_%'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name",
        )
    ]
    tables = [t for t in tables if t not in {"events", "sync_state", "meta"}]
    assert "decisions" in tables

    def snapshot() -> dict[str, list[tuple[Any, ...]]]:
        return {t: sorted(_rows(project, f"SELECT * FROM {t}"), key=repr) for t in tables}

    before = snapshot()
    _script(project)
    assert snapshot() == before
    project.index.rebuild()
    assert snapshot() == before


def test_row_key_and_field_columns_exist_and_are_indexed(project: Project) -> None:
    for table, column in (("extraction_rows", "row_key"), ("extraction_fields", "field")):
        columns = {row[1] for row in _rows(project, f"PRAGMA table_info({table})")}
        assert column in columns
        firsts = []
        for index in _rows(project, f"PRAGMA index_list({table})"):
            info = _rows(project, f"PRAGMA index_info({index[1]})")
            firsts.append(next(row[2] for row in info if row[0] == 0))
        assert column in firsts
        plan = " ".join(
            str(row)
            for row in _rows(
                project,
                f"EXPLAIN QUERY PLAN SELECT extraction_id FROM {table} WHERE {column} = 'x'",
            )
        )
        assert "USING INDEX" in plan or "USING COVERING INDEX" in plan

# ruff: noqa: F811
"""Scope through passes, tasks, recording, staleness and reads (plan G2-A, task 4).

The pinned conversion is plan D's synthetic LaTeXML fixture: paragraph `s3.p1` reads "Lorem ipsum
dolor sit amet." and table `t1` has the row `Lorem | 1 | 2`. Contribution items quote `s3.p1`.
"""

from collections.abc import Callable, Mapping, Sequence

import pytest

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.extraction import (
    CitedEntry,
    FieldInput,
    Scope,
    StoredField,
)
from factory.model.screening import PassLabel
from factory.services import extraction
from factory.services.context import Project
from factory.services.document_read import document_read
from factory.services.extraction import (
    DUPLICATE_ITEM,
    DUPLICATE_ROW,
    ContributionBatch,
    ContributionBatchContent,
    ExtractBatch,
    ExtractionRow,
    ExtraVerdict,
    UnitPin,
    extract_next,
    extract_record,
    is_extraction_session,
    join_extraction_pass,
    live_rows,
    next_unit,
    pass_config,
    record_unit,
    scope_population,
    session_scope,
    stale_extractions,
    unit_states,
)
from factory.services.methods import methods_report
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.references import current_extraction, extract_references, included_works
from factory.services.stages import CONTRIB_KINDS, EXTRACT_KINDS, kinds_for, scope_of_kind
from factory.services.tasks import TaskSpec, claim_next, create_tasks, get_task, task_content
from tests.document_helpers import StubConverter, make_registry, run_convert
from tests.extraction_helpers import (  # noqa: F401
    CONTRIB_FIELDS,
    LATENCY_FIELDS,
    QUOTE,
    SESSION_A,
    SESSION_B,
    _declare_latency,
    _extractor,
    _item,
    _new_document_version,
    _row,
    _schemas,
    add_refs,
    ctr_a,
    ctr_b,
    ext_a,
    scope_world,
    screened,
)

C = Scope.CONTRIBUTION
REX = "rex_01JZ9Q3K5M7N8P0R2S4T6V8W0X"


_CONVERSIONS = iter(range(1, 1000))


def _extract(project: Project, agent: Actor, work: str) -> None:
    """Extract the references of `work`; a re-extraction first converts the document anew, since
    one on the same conversion is refused (a genuine replacement needs a new conversion)."""
    if current_extraction(project, work) is not None:
        run_convert(project, make_registry(StubConverter(version=f"9.9+scope{next(_CONVERSIONS)}")))
    extract_references(project, agent, [work], sources={})


def _amend(project: Project, agent: Actor, section: str, **update: object) -> None:
    current = current_protocol(project)
    assert current is not None
    schema = getattr(current.spec, section)
    assert schema is not None
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={section: schema.model_copy(update=update)}),
        reason=f"amend {section}",
        semantic=True,
        effects={},
    )


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _contrib(project: Project, actor: Actor, label: PassLabel = PassLabel.A) -> ContributionBatch:
    batch = next_unit(project, actor, label, scope=C, content=add_refs).batch
    assert isinstance(batch, ContributionBatch)
    return batch


def _work(batch: ExtractBatch | ContributionBatch) -> str:
    return batch.records[0]["work_id"]


def _cite(rex: str) -> Callable[..., ExtraVerdict]:
    def check(
        project: Project,
        pin: UnitPin,
        fields: Mapping[str, StoredField],
        rows: Sequence[ExtractionRow],
    ) -> ExtraVerdict:
        if "cited_entry" not in fields:
            return ExtraVerdict(cited=None, issues=[])
        entry = CitedEntry(reference_extraction_id=rex, ordinal=1, marker="absent")
        return ExtraVerdict(cited=entry, issues=[])

    return check


# --- Kinds ---


def test_kinds_per_scope() -> None:
    assert CONTRIB_KINDS == {PassLabel.A: "contrib_a", PassLabel.B: "contrib_b"}
    assert kinds_for(Scope.EVIDENCE) is EXTRACT_KINDS and kinds_for(C) is CONTRIB_KINDS
    assert [scope_of_kind(k) for k in ("extract_a", "contrib_b", "screen_a")] == [
        Scope.EVIDENCE,
        C,
        None,
    ]


# --- Preconditions and population ---


def test_contribution_refused_until_schema_declared(
    project: Project, agent: Actor, ctr_a: Actor, screened: list[str]
) -> None:
    _declare_latency(project, agent, 1.0)  # the evidence schema only
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        next_unit(project, ctr_a, PassLabel.A, scope=C, content=add_refs)
    assert e.value.issues[0].field == "contribution_schema"
    assert "R-13" in e.value.issues[0].reason
    assert len(_events(project)) == before


def test_evidence_schema_cannot_use_the_contribution_pack(
    project: Project, agent: Actor, screened: list[str]
) -> None:
    current = current_protocol(project)
    assert current is not None
    _, contribution = _schemas()
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        amend_protocol(
            project,
            agent,
            current.spec.model_copy(update={"extraction_schema": contribution}),
            reason="misuse the reserved pack",
            semantic=True,
            effects={},
        )
    assert "extraction_schema.pack" in [i.field for i in e.value.issues]
    assert len(_events(project)) == before


def test_contribution_population_is_g1_included_works(
    project: Project, ctr_a: Actor, world: list[str]
) -> None:
    population = scope_population(project, C)
    assert population == included_works(project) == world
    assert all(current_extraction(project, w) is None for w in population)
    batch = _contrib(project, ctr_a)
    assert _work(batch) in population  # a work with no G1 extraction is served


# --- Sessions and passes ---


def test_session_cannot_cross_scopes(
    project: Project, ext_a: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]
) -> None:
    assert extract_next(project, ext_a, PassLabel.A).batch is not None
    before = len(_events(project))
    for label in PassLabel:
        with pytest.raises(FactoryValidationError) as e:
            next_unit(project, ext_a, label, scope=C, content=add_refs)
        assert e.value.issues[0].field == "pass"
        with pytest.raises(FactoryValidationError):
            join_extraction_pass(project, ext_a, label, scope=C)
    assert len(_events(project)) == before
    _contrib(project, ctr_a)
    with pytest.raises(FactoryValidationError) as e:
        extract_next(project, ctr_a, PassLabel.B)
    assert e.value.issues[0].field == "pass"
    assert session_scope(project, ctr_a.session) is C
    assert session_scope(project, ext_a.session) is Scope.EVIDENCE
    assert is_extraction_session(project, ctr_a.session)
    # Models are independent per scope: contribution B may not reuse contribution A's model.
    with pytest.raises(FactoryValidationError) as e:
        same_model = ctr_b.model_copy(update={"model": ctr_a.model})
        next_unit(project, same_model, PassLabel.B, scope=C, content=add_refs)
    assert e.value.issues[0].field == "model"


def test_both_scopes_open_pass_a_independently(
    project: Project, ext_a: Actor, ctr_a: Actor, world: list[str]
) -> None:
    extract_next(project, ext_a, PassLabel.A)
    _contrib(project, ctr_a)
    evidence = pass_config(project, PassLabel.A)
    contribution = pass_config(project, PassLabel.A, scope=C)
    assert evidence is not None and contribution is not None
    opened = [e for e in _events(project) if e.type == "extraction.pass_opened"]
    joined = [e for e in _events(project) if e.type == "extraction.pass_joined"]
    assert [e.payload.get("pack") for e in opened] == [None, "contribution"]
    assert [e.payload.get("pack") for e in joined] == [None, "contribution"]
    report = methods_report(project)
    assert report.extraction_passes == 1 and report.extraction_sessions == 1


# --- Tasks ---


def test_contribution_tasks_use_contrib_kinds_and_content_hook(
    project: Project, ctr_a: Actor, world: list[str]
) -> None:
    nxt = next_unit(project, ctr_a, PassLabel.A, scope=C, content=add_refs)
    assert nxt.batch is not None
    task = get_task(project, nxt.batch.task_id)
    assert task is not None and task.kind == "contrib_a"
    stored = ContributionBatchContent.model_validate(task_content(project, task))
    assert stored.schema_ref == "contribution@1" and stored.claims is False
    assert [f["name"] for f in stored.fields] == list(CONTRIB_FIELDS)
    assert nxt.remaining == len(world)


def test_contribution_task_served_as_contribution_batch(
    project: Project, ctr_a: Actor, world: list[str]
) -> None:
    batch = _contrib(project, ctr_a)
    assert batch.references.status == "none"
    assert batch.item_rules == ["a not-stated item names absent_kind and nothing else"]
    # Served again while held: the same task, still a contribution batch.
    again = next_unit(project, ctr_a, PassLabel.A, scope=C, content=add_refs).batch
    assert isinstance(again, ContributionBatch) and again.task_id == batch.task_id


def test_contribution_needs_a_content_hook(
    project: Project, ctr_a: Actor, world: list[str]
) -> None:
    with pytest.raises(TypeError):
        next_unit(project, ctr_a, PassLabel.A, scope=C)


# --- Recording ---


def test_extract_record_refuses_contribution_task(
    project: Project, ctr_a: Actor, world: list[str]
) -> None:
    batch = _contrib(project, ctr_a)
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        extract_record(project, ctr_a, batch.task_id, [_item()])
    assert e.value.issues[0].field == "task_id"
    assert "contribution_record" in e.value.issues[0].reason
    assert len(_events(project)) == before


def test_task_schema_must_match_its_scope(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:
    batch = _contrib(project, ctr_a)
    evidence, _ = _schemas()
    content = ContributionBatchContent.model_validate(
        {**batch.model_dump(exclude={"task_id"}), "schema_ref": "ml-benchmark@1"}
    )
    created = create_tasks(
        project, agent, [TaskSpec(kind="contrib_a", content=content.model_dump(mode="json"))]
    )
    (bogus,) = created.written
    assert claim_next(project, ctr_a, "contrib_a", task_ids={bogus}) is not None
    with pytest.raises(FactoryValidationError) as e:
        record_unit(project, ctr_a, bogus, [_item()])
    assert e.value.issues[0].field == "task_id"
    assert evidence.pack in e.value.issues[0].reason or "scope" in e.value.issues[0].reason


def test_extra_check_rejects_row_and_stores_cited(
    project: Project, ctr_a: Actor, world: list[str]
) -> None:
    batch = _contrib(project, ctr_a)
    seen: list[list[str]] = []
    pins: list[UnitPin] = []

    def check(
        project: Project,
        pin: UnitPin,
        fields: Mapping[str, StoredField],
        rows: Sequence[ExtractionRow],
    ) -> ExtraVerdict:
        pins.append(pin)
        seen.append([r.row_key for r in rows])
        if fields["name"].value == "ipsum":
            return ExtraVerdict(
                cited=None, issues=[ValidationIssue("fields.cited_entry", "entry-unknown")]
            )
        return ExtraVerdict(
            cited=CitedEntry(reference_extraction_id=REX, ordinal=1, marker="absent"), issues=[]
        )

    res = record_unit(
        project,
        ctr_a,
        batch.task_id,
        [_item(cited_entry=FieldInput(value=1)), _item(name="ipsum"), _item(name="dolor")],
        extra_check=check,
    )
    assert len(res.rows.written) == 2
    assert [(e.index, e.issues[0].field) for e in res.rows.rejected] == [(1, "fields.cited_entry")]
    assert len(seen[0]) == 0 and len(seen[1]) == 1 and len(seen[2]) == 1
    assert pins[0].scope is C and pins[0].work_id == _work(batch)
    assert pins[0].pass_label is PassLabel.A and pins[0].task_id == batch.task_id
    rows = live_rows(project, scope=C)
    assert {r.extraction_id for r in rows} == set(res.rows.written)
    assert all(
        r.cited == CitedEntry(reference_extraction_id=REX, ordinal=1, marker="absent") for r in rows
    )
    recorded = [e for e in _events(project) if e.type == "extraction.recorded"]
    assert all(e.payload["cited"]["reference_extraction_id"] == REX for e in recorded)
    assert all(e.payload["schema_ref"] == "contribution@1" for e in recorded)


def test_close_check_refuses_finish(project: Project, ctr_a: Actor, world: list[str]) -> None:
    batch = _contrib(project, ctr_a)
    record_unit(project, ctr_a, batch.task_id, [_item()])
    before = len(_events(project))
    seen: list[tuple[int, str | None]] = []

    def refuse(
        project: Project, pin: UnitPin, rows: Sequence[ExtractionRow], reason: str | None
    ) -> list[ValidationIssue]:
        seen.append((len(rows), reason))
        return [ValidationIssue("finish", "an addition is required")]

    with pytest.raises(FactoryValidationError) as e:
        record_unit(
            project, ctr_a, batch.task_id, [_item(name="ipsum")], finish=True, close_check=refuse
        )
    assert e.value.issues[0].field == "finish"
    assert len(_events(project)) == before
    assert seen == [(2, None)]
    res = record_unit(project, ctr_a, batch.task_id, [], finish=True, close_check=lambda *_: [])
    assert res.completed
    (closed,) = [e for e in _events(project) if e.type == "extraction.closed"]
    assert closed.payload["pack"] == "contribution" and closed.payload["rows"] == 1


def test_duplicate_reason_replaces_message(
    project: Project, ctr_a: Actor, world: list[str]
) -> None:
    batch = _contrib(project, ctr_a)
    res = record_unit(
        project, ctr_a, batch.task_id, [_item(), _item()], duplicate_reason=DUPLICATE_ITEM
    )
    assert [(i.field, i.reason) for i in res.rows.rejected[0].issues] == [
        ("fields.value", DUPLICATE_ITEM)
    ]
    assert "finer anchor" in DUPLICATE_ITEM and DUPLICATE_ITEM != DUPLICATE_ROW
    res = record_unit(project, ctr_a, batch.task_id, [_item()])
    assert [(i.field, i.reason) for i in res.rows.rejected[0].issues] == [
        ("fields.value", DUPLICATE_ROW)
    ]


# --- Separation of reads ---


def _both_units(
    project: Project, ext_a: Actor, ctr_a: Actor
) -> tuple[str, str, ExtractBatch, ContributionBatch]:
    """One closed evidence unit (a row carrying `split`) and one closed contribution unit of the
    same work (an addition carrying `compared_to`); (evidence row, contribution row, batches)."""
    evidence = extract_next(project, ext_a, PassLabel.A).batch
    assert isinstance(evidence, ExtractBatch)
    for _ in range(50):
        contribution = _contrib(project, ctr_a)
        if _work(contribution) == _work(evidence):
            break
        record_unit(project, ctr_a, contribution.task_id, [], finish=True, reason="not this one")
    else:
        raise AssertionError("work not served")
    ev = extract_record(
        project, ext_a, evidence.task_id, [_row(split=FieldInput(value="test"))], finish=True
    )
    item = _item("addition", compared_to=FieldInput(value="ipsum", anchor="s3.p1", quote=QUOTE))
    ct = record_unit(project, ctr_a, contribution.task_id, [item], finish=True)
    assert ev.completed and ct.completed, (ev.rows.rejected, ct.rows.rejected)
    return ev.rows.written[0], ct.rows.written[0], evidence, contribution


def test_evidence_reads_exclude_contribution_rows(
    project: Project, ext_a: Actor, ctr_a: Actor, world: list[str]
) -> None:
    ev, ct, evidence, _ = _both_units(project, ext_a, ctr_a)
    assert [r.extraction_id for r in live_rows(project)] == [ev]
    assert [r.extraction_id for r in live_rows(project, scope=C)] == [ct]
    assert [
        r.extraction_id for r in live_rows(project, PassLabel.A, work_id=_work(evidence), scope=C)
    ] == [ct]
    work = _work(evidence)
    states = {s.work_id: s.state for s in unit_states(project) if s.pass_label is PassLabel.A}
    c_states = {
        s.work_id: s.state for s in unit_states(project, scope=C) if s.pass_label is PassLabel.A
    }
    assert states[work] == c_states[work] == "current"
    assert stale_extractions(project) == stale_extractions(project, scope=C) == set()


# --- Staleness ---


def test_contribution_amendment_stales_only_contribution_rows(
    project: Project, agent: Actor, ext_a: Actor, ctr_a: Actor, world: list[str]
) -> None:
    ev, ct, evidence, _ = _both_units(project, ext_a, ctr_a)
    work = _work(evidence)
    _amend(
        project,
        agent,
        "contribution_schema",
        fields=tuple(f for f in CONTRIB_FIELDS if f != "compared_to"),
    )
    assert stale_extractions(project, scope=C) == {ct}
    assert stale_extractions(project) == set()
    (c_state,) = [
        s
        for s in unit_states(project, scope=C)
        if s.work_id == work and s.pass_label is PassLabel.A
    ]
    (e_state,) = [
        s for s in unit_states(project) if s.work_id == work and s.pass_label is PassLabel.A
    ]
    assert (c_state.state, c_state.reason) == ("stale", "schema")
    assert e_state.state == "current"
    _amend(
        project, agent, "extraction_schema", fields=tuple(f for f in LATENCY_FIELDS if f != "split")
    )
    assert stale_extractions(project) == {ev}
    assert stale_extractions(project, scope=C) == {ct}


def test_new_document_version_stales_both_scopes(
    project: Project, ext_a: Actor, ctr_a: Actor, world: list[str]
) -> None:
    ev, ct, evidence, _ = _both_units(project, ext_a, ctr_a)
    work = _work(evidence)
    _new_document_version(project, work)
    assert stale_extractions(project) == {ev}
    assert stale_extractions(project, scope=C) == {ct}
    for scope in Scope:
        (state,) = [
            s
            for s in unit_states(project, scope=scope)
            if s.work_id == work and s.pass_label is PassLabel.A
        ]
        assert (state.state, state.reason) == ("stale", "document-version")


def _state_of(project: Project, work: str) -> tuple[str, str | None]:
    (state,) = [
        s
        for s in unit_states(project, scope=C)
        if s.work_id == work and s.pass_label is PassLabel.A
    ]
    return state.state, state.reason


def _serve_until(project: Project, actor: Actor, work: str) -> ContributionBatch | None:
    """Serve pass A, closing every other unit, until `work` is served; None when the queue ends."""
    for _ in range(50):
        batch = next_unit(project, actor, PassLabel.A, scope=C, content=add_refs).batch
        if batch is None:
            return None
        assert isinstance(batch, ContributionBatch)
        if _work(batch) == work:
            return batch
        record_unit(project, actor, batch.task_id, [], finish=True, reason="not this one")
    raise AssertionError("the queue did not end")


def test_cited_row_stale_when_g1_extraction_replaced(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:
    batch = _contrib(project, ctr_a)
    work = _work(batch)
    _extract(project, agent, work)
    first = current_extraction(project, work)
    assert first is not None
    res = record_unit(
        project,
        ctr_a,
        batch.task_id,
        [_item(cited_entry=FieldInput(value=1))],
        finish=True,
        extra_check=_cite(first),
    )
    assert res.completed
    (row_id,) = res.rows.written
    assert stale_extractions(project, scope=C) == set()
    _extract(project, agent, work)
    assert current_extraction(project, work) not in (None, first)
    assert stale_extractions(project, scope=C) == {row_id}
    (state,) = [
        s
        for s in unit_states(project, scope=C)
        if s.work_id == work and s.pass_label is PassLabel.A
    ]
    assert (state.state, state.reason) == ("stale", "references")
    assert stale_extractions(project) == set()
    # The next call queues a new task for the stale unit; recording against the new extraction
    # makes the unit current, though the old row stays live and stale.
    second = current_extraction(project, work)
    assert second is not None
    served = _serve_until(project, ctr_a, work)
    assert served is not None and served.task_id != batch.task_id
    res = record_unit(
        project,
        ctr_a,
        served.task_id,
        [_item(cited_entry=FieldInput(value=1))],
        finish=True,
        extra_check=_cite(second),
    )
    assert res.completed
    (new_id,) = res.rows.written
    assert _state_of(project, work) == ("current", None)
    assert stale_extractions(project, scope=C) == {row_id}
    # next_unit does not offer the unit again.
    assert _serve_until(project, ctr_a, work) is None
    assert _state_of(project, work) == ("current", None)
    # A later replacement stales the unit again: only rows stale at the closing are discounted.
    _extract(project, agent, work)
    assert _state_of(project, work) == ("stale", "references")
    assert stale_extractions(project, scope=C) == {row_id, new_id}


def test_references_replaced_during_an_open_task_reoffer_the_unit_once(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:
    batch = _contrib(project, ctr_a)
    work = _work(batch)
    _extract(project, agent, work)
    first = current_extraction(project, work)
    assert first is not None
    rows = [_item(cited_entry=FieldInput(value=1)), _item(name="ipsum")]
    written = record_unit(project, ctr_a, batch.task_id, rows, extra_check=_cite(first))
    assert len(written.rows.written) == 2
    _extract(project, agent, work)  # no agent has seen this extraction
    second = current_extraction(project, work)
    assert second is not None
    assert record_unit(project, ctr_a, batch.task_id, [], finish=True).completed
    assert _state_of(project, work) == ("stale", "references")
    served = _serve_until(project, ctr_a, work)
    assert served is not None and served.task_id != batch.task_id
    res = record_unit(
        project,
        ctr_a,
        served.task_id,
        [_item(cited_entry=FieldInput(value=1))],
        finish=True,
        extra_check=_cite(second),
    )
    assert res.completed
    assert _state_of(project, work) == ("current", None)
    assert _serve_until(project, ctr_a, work) is None


def test_requeued_task_may_close_with_a_reason_and_keep_the_stale_row_visible(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:
    batch = _contrib(project, ctr_a)
    work = _work(batch)
    _extract(project, agent, work)
    first = current_extraction(project, work)
    assert first is not None
    res = record_unit(
        project,
        ctr_a,
        batch.task_id,
        [_item(cited_entry=FieldInput(value=1))],
        finish=True,
        extra_check=_cite(first),
    )
    (row_id,) = res.rows.written
    _extract(project, agent, work)
    served = _serve_until(project, ctr_a, work)
    assert served is not None
    reason = "the new reference list no longer holds the entry"
    assert record_unit(project, ctr_a, served.task_id, [], finish=True, reason=reason).completed
    assert _state_of(project, work) == ("current", None)
    assert stale_extractions(project, scope=C) == {row_id}
    assert _serve_until(project, ctr_a, work) is None


# --- document_read gate ---


def test_contribution_session_reads_only_its_queue(
    project: Project, ctr_a: Actor, world: list[str]
) -> None:
    batch = _contrib(project, ctr_a)
    work = _work(batch)
    page = document_read(project, work_id=work, session=ctr_a.session)
    assert page.conversion_id == batch.records[0]["conversion_id"]
    other = next(w for w in world if w != work)
    with pytest.raises(FactoryValidationError) as e:
        document_read(project, work_id=other, session=ctr_a.session)
    assert e.value.issues[0].field == "work_id"


def test_unit_pin_is_per_scope(project: Project, ctr_a: Actor, world: list[str]) -> None:
    batch = _contrib(project, ctr_a)
    work = _work(batch)
    assert extraction.unit_pin(project, work) is None
    assert extraction.unit_pin(project, work, scope=C) == (
        batch.records[0]["document_id"],
        batch.records[0]["conversion_id"],
    )

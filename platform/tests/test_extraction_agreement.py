# ruff: noqa: F811, RUF001
"""Extraction agreement, human resolution, final and grouped rows (plan D, task 8; R-46, ruling 10).

Rows of the two passes align on `row_key`; each declared field of an aligned pair is compared
(text normalised, numbers by canonical value and unit, `reported_in` and `reproduced` equal; never
the quote, anchor or cell). Agreement is computed, never typed. A disagreement is resolved only by
a human choosing `a`, `b` or `neither`, and an unresolved one never reaches the final rows.

The pinned conversion is the synthetic fixture of `test_extraction_record`: table `t1` has the
row `Lorem | 1 | 2` under the header `Low | High`; paragraph `s3.p1` reads "Lorem ipsum dolor sit
amet."."""

from collections.abc import Sequence
from decimal import Decimal

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.extraction.numbers import canonical, parse_printed
from factory.model.extraction import (
    ExtractedRowInput,
    ExtractionPassJoined,
    ExtractionRecorded,
    FieldInput,
    ReportedIn,
    StoredField,
)
from factory.model.screening import Channel, PassLabel
from factory.packs import ML_BENCHMARK_V1, FieldKind
from factory.services import extraction
from factory.services.context import Project
from factory.services.extraction import (
    ExtractionRow,
    extract_next,
    extract_record,
    in_dual_sample,
    live_rows,
    pass_config,
)
from factory.services.extraction_agreement import (
    NON_COMPARABLE_KEYS,
    AgreementOverall,
    FinalField,
    FinalRow,
    IndependenceCounts,
    agreement_overall,
    extraction_agreement,
    field_disagreements,
    final_field,
    final_rows,
    group_rows,
    grouped_rows,
    independence_counts,
    resolve_extraction,
)
from tests.extraction_helpers import (  # noqa: F401
    FIELDS,
    KEYS,
    SESSION_A,
    SESSION_B,
    _amend_schema,
    _both,
    _declare,
    _extractor,
    _r,
    _run,
    _same_rows,
    _schema,
    _with,
    ext_a,
    ext_b,
    screened,
    world,
)
from tests.screening_helpers import _check

pytestmark = pytest.mark.slow  # over ~60 s per file: dev runs deselect with -m "not slow"

PACK = ML_BENCHMARK_V1


def _events(project: Project) -> list[Event]:
    return read_all(project.paths.events_dir, project.catalog)


def _final(project: Project, work: str) -> list[FinalRow]:
    return [r for r in final_rows(project) if r.work_id == work]


# --- Pure comparison ---


def _stored(name: str, value: str | bool, unit: str | None = None, **over: object) -> StoredField:
    definition = PACK.field(name)
    assert definition is not None
    canon = None
    if definition.kind in (FieldKind.NUMBER, FieldKind.INTEGER) and isinstance(value, str):
        printed = parse_printed(value)
        assert isinstance(printed, Decimal)
        canon = canonical(printed, unit, definition.unit_family)
    values: dict[str, object] = {
        "value": value,
        "unit": unit,
        "anchor": "t1",
        "cell": "t1.r3.c2",
        "quote": str(value),
        "canonical": canon,
        "copy_marker": False,
        **over,
    }
    return StoredField.model_validate(values)


def _row_of(label: PassLabel = PassLabel.A, **fields: StoredField) -> ExtractionRow:
    return ExtractionRow(
        extraction_id=f"ext_{label.value}",
        work_id="rf:w1",
        pass_label=label,
        task_id="tsk_1",
        protocol_id="P@1",
        conversion_id="cnv_1",
        document_id="doc_1",
        row_key="rk_0123456789ab",
        fields=fields,
        event_id=f"evt_{label.value}",
    )


def _kinds(a: ExtractionRow, b: ExtractionRow, fields: Sequence[str] = FIELDS) -> list[str]:
    return [d.kind for d in field_disagreements(PACK, fields, a, b)]


def test_numbers_must_match_exactly_after_normalisation() -> None:
    a = _row_of(value=_stored("value", "82.40", "%"))
    b = _row_of(PassLabel.B, value=_stored("value", "82.4", "%"))
    c = _row_of(PassLabel.B, value=_stored("value", "82.5", "%"))
    assert _kinds(a, b) == []
    assert _kinds(a, c) == ["value"]


def test_one_and_one_point_zero_agree_via_canonical() -> None:
    # The projection stores values as text; "1" and "1.0" differ as text but not canonically.
    a = _row_of(value=_stored("value", "1"))
    b = _row_of(PassLabel.B, value=_stored("value", "1.0"))
    assert a.fields["value"].value != b.fields["value"].value
    assert _kinds(a, b) == []


def test_unit_difference_is_a_disagreement() -> None:
    a = _row_of(value=_stored("value", "82.4", "%"))
    b = _row_of(PassLabel.B, value=_stored("value", "82.4", "fraction"))
    assert _kinds(a, b) == ["value"]
    unstated = _row_of(PassLabel.B, value=_stored("value", "82.4"))
    assert _kinds(a, unstated) == ["value"]
    fields = (*FIELDS, "params")
    m = _row_of(params=_stored("params", "22.1", "M"))
    plain = _row_of(PassLabel.B, params=_stored("params", "22100000", ""))
    assert _kinds(m, plain, fields) == []
    k = _row_of(PassLabel.B, params=_stored("params", "22.1", "K"))
    assert _kinds(m, k, fields) == ["value"]


def test_text_field_compared_normalised_not_fuzzy() -> None:
    a = _row_of(
        dataset=_stored("dataset", "ImageNet-1K"), method_name=_stored("method_name", "DeiT-S")
    )
    b = _row_of(
        PassLabel.B,
        dataset=_stored("dataset", " imagenet-1k "),
        method_name=_stored("method_name", "DeiT-Small"),
    )
    (only,) = field_disagreements(PACK, FIELDS, a, b)
    assert (only.field, only.kind) == ("method_name", "value")


def test_resolution_normaliser_used_in_comparison() -> None:
    fields = (*FIELDS, "input_resolution")
    a = _row_of(input_resolution=_stored("input_resolution", "224"))
    b = _row_of(PassLabel.B, input_resolution=_stored("input_resolution", "224 × 224"))
    assert _kinds(a, b, fields) == []


def test_provenance_fields_do_not_disagree() -> None:
    a = _row_of(value=_stored("value", "1", quote="1", anchor="t1", cell="t1.r3.c2"))
    b = _row_of(
        PassLabel.B, value=_stored("value", "1", quote="Lorem 1", anchor="t1.r3.c2", cell=None)
    )
    assert _kinds(a, b) == []


def test_reported_in_and_reproduced_are_compared() -> None:
    a = _row_of(value=_stored("value", "1"))
    cited = _row_of(PassLabel.B, value=_stored("value", "1", reported_in=ReportedIn.CITED))
    reproduced = _row_of(PassLabel.B, value=_stored("value", "1", reproduced=True))
    assert _kinds(a, cited) == ["value"]
    assert _kinds(a, reproduced) == ["value"]


def test_field_in_one_row_only_is_missing_and_undeclared_ignored() -> None:
    a = _row_of(
        value=_stored("value", "1"), task=_stored("task", "x"), hardware=_stored("hardware", "a")
    )
    b = _row_of(PassLabel.B, value=_stored("value", "1"), hardware=_stored("hardware", "b"))
    (only,) = field_disagreements(PACK, FIELDS, a, b)
    assert (only.field, only.kind, only.b) == ("task", "missing", None)
    assert only.a is not None and only.a.extraction_id == "ext_A"


def test_bool_fields_compared_by_value() -> None:
    fields = (*FIELDS, "is_proposed")
    a = _row_of(is_proposed=_stored("is_proposed", True))
    b = _row_of(PassLabel.B, is_proposed=_stored("is_proposed", False))
    assert _kinds(a, b, fields) == ["value"]
    assert _kinds(a, _row_of(PassLabel.B, is_proposed=_stored("is_proposed", True)), fields) == []


# --- Refusals and the non-refusing overall ---


def test_agreement_refused_while_tasks_open(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    with pytest.raises(FactoryValidationError) as e:
        extraction_agreement(project, human)  # no pass is opened
    assert e.value.issues[0].field == "passes"
    _run(project, ext_a, PassLabel.A, _same_rows)
    with pytest.raises(FactoryValidationError) as e:
        extraction_agreement(project, human)  # pass B unopened under a dual plan
    assert e.value.issues[0].field == "passes"
    assert extract_next(project, ext_b, PassLabel.B).batch is not None  # one task claimed
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        extraction_agreement(project, human)
    assert e.value.issues[0].field == "passes"
    assert "open" in e.value.issues[0].reason
    assert len(_events(project)) == before


def test_agreement_refused_without_schema(
    project: Project, human: Actor, screened: list[str]
) -> None:
    with pytest.raises(FactoryValidationError) as e:
        extraction_agreement(project, human)
    assert e.value.issues[0].field == "extraction_schema"


def test_agreement_refused_to_an_extraction_session(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    with pytest.raises(FactoryValidationError) as e:
        extraction_agreement(project, ext_a)
    assert e.value.issues[0].field == "session"


def _raw_join(project: Project, session: str, label: PassLabel, model: str) -> None:
    actor = _extractor(session, model)
    payload = ExtractionPassJoined(pass_label=label, session=session, model=model)
    blob = project.blobs.put_json({"pass_label": label.value})
    project.record([project.events.make("extraction.pass_joined", payload, actor, input_blob=blob)])


def test_agreement_refused_when_passes_share_model_or_session(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    assert extraction_agreement(project, human).overall == 1.0
    # A join the services would refuse, written straight to the log: one session in both passes.
    _raw_join(project, SESSION_A, PassLabel.B, "claude-haiku-5-5")
    with pytest.raises(FactoryValidationError) as e:
        extraction_agreement(project, human)
    assert e.value.issues[0].field == "passes"
    assert "session" in e.value.issues[0].reason


def test_agreement_refused_when_passes_share_model(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    _raw_join(project, "01JZ9Q3K5M7N8P0R2S4T6V8W1C", PassLabel.B, "claude-opus-5-5")
    with pytest.raises(FactoryValidationError) as e:
        extraction_agreement(project, human)
    assert e.value.issues[0].field == "passes"
    assert "model" in e.value.issues[0].reason


def test_agreement_overall_never_refuses(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, screened: list[str], agent: Actor
) -> None:
    empty = AgreementOverall(overall=None, dual=0, single=0, rows_aligned=0, rows_unmatched=0)
    assert agreement_overall(project) == empty
    _declare(project, agent)
    assert agreement_overall(project) == empty
    _run(project, ext_a, PassLabel.A, _same_rows)
    assert extract_next(project, ext_b, PassLabel.B).batch is not None
    open_tasks = agreement_overall(project)
    assert open_tasks.overall is None and open_tasks.dual == len(screened)
    _run(project, ext_b, PassLabel.B, _same_rows)
    done = agreement_overall(project)
    assert done.overall == extraction_agreement(project, human).overall == 1.0
    assert (done.dual, done.single) == (len(screened), 0)


# --- Alignment, rates and disagreements ---


def test_unmatched_row_is_a_row_disagreement(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    extra = world[0]
    _both(
        project,
        ext_a,
        ext_b,
        a=lambda w: [_r(), _r("2", "t1.r3.c3")] if w == extra else [_r()],
    )
    ag = extraction_agreement(project, human)
    (row,) = ag.disagreements
    assert (row.work_id, row.kind, row.field, row.b) == (extra, "row", None, None)
    assert row.a is not None and row.a.canonical == "2"
    assert (ag.rows_aligned, ag.rows_unmatched) == (len(world), 1)
    assert ag.overall == 1.0
    assert extra not in {r.work_id for r in final_rows(project) if r.row_key == row.row_key}


def test_per_group_rates_and_overall(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _both(project, ext_a, ext_b, b=lambda w: [_r(task="detection")] if w == odd else [_r()])
    ag = extraction_agreement(project, human)
    rates = {g.group: (g.compared, g.agreed, g.rate) for g in ag.rates}
    n = len(world)
    # Per row: identity method_name; task task, dataset, split; result metric, value.
    assert rates["identity"] == (n, n, 1.0)
    assert rates["task"] == (3 * n, 3 * n - 1, (3 * n - 1) / (3 * n))
    assert rates["result"] == (2 * n, 2 * n, 1.0)
    assert rates["regime"] == (0, 0, None)  # declared, never extracted: nothing compared
    assert ag.overall == (6 * n - 1) / (6 * n)
    assert [g.group for g in ag.rates] == ["identity", "task", "result", "regime"]


def test_disagreements_never_auto_resolved(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _both(
        project,
        ext_a,
        ext_b,
        a=lambda w: [_r(), _r("2", "t1.r3.c3")] if w == odd else [_r()],
        b=lambda w: [_r(task="detection")] if w == odd else [_r()],
    )
    ag = extraction_agreement(project, human)
    assert len(ag.disagreements) == 2 and ag.resolved == 0
    assert {d.kind for d in ag.disagreements} == {"value", "row"}
    rows = final_rows(project)
    assert {r.work_id for r in rows} == set(world) - {odd}
    assert {r.status for r in rows} == {"agreed"}
    assert grouped_rows(project).unresolved == ag.disagreements


def test_agreed_row_takes_pass_a_fields(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    a_ids = {r.extraction_id for r in live_rows(project, PassLabel.A)}
    for row in final_rows(project):
        assert row.status == "agreed" and row.independent
        assert {f.extraction_id for f in row.fields.values()} <= a_ids
        assert row.fields["value"].canonical == "1"
        assert set(row.fields) == {"method_name", "task", "dataset", "split", "metric", "value"}


def test_duplicate_live_row_key_is_a_row_disagreement(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    original = next(e for e in _events(project) if e.type == "extraction.recorded")
    payload = ExtractionRecorded.model_validate(original.payload)
    twin = payload.model_copy(update={"extraction_id": project.ids.new("ext")})
    project.record(
        [
            project.events.make(
                "extraction.recorded",
                twin,
                original.actor,
                refs=(twin.extraction_id,),
                input_blob=original.input_blob,
            )
        ]
    )
    ag = extraction_agreement(project, human)
    (dup,) = ag.disagreements
    assert (dup.work_id, dup.row_key, dup.kind) == (payload.work_id, payload.row_key, "row")
    assert dup.a is None  # never pick one of the two
    assert not [r for r in final_rows(project) if r.row_key == payload.row_key]
    with pytest.raises(FactoryValidationError) as e:
        resolve_extraction(
            project, human, payload.work_id, payload.row_key, None, "a", "x", Channel.CLI
        )
    assert e.value.issues[0].field == "choice"
    resolve_extraction(
        project, human, payload.work_id, payload.row_key, None, "neither", "dup", Channel.CLI
    )
    assert extraction_agreement(project, human).disagreements == []


# --- Resolution ---


def test_human_choice_resolves_and_final_value_is_the_chosen_verified_one(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _both(project, ext_a, ext_b, b=lambda w: [_r(unit="%")] if w == odd else [_r()])
    (d,) = extraction_agreement(project, human).disagreements
    assert (d.field, d.kind) == ("value", "value")
    assert d.b is not None and d.b.unit == "%"
    b_id = d.b.extraction_id
    event_id = resolve_extraction(
        project, human, odd, d.row_key, "value", "b", "pass B read the table correctly", Channel.CLI
    )
    resolved = next(e for e in _events(project) if e.id == event_id)
    assert resolved.type == "extraction.resolved" and resolved.actor.kind == "human"
    assert resolved.payload["choice"] == "b" and resolved.payload["field"] == "value"
    (row,) = _final(project, odd)
    assert row.status == "resolved"
    assert row.fields["value"].unit == "%" and row.fields["value"].canonical == "1"
    assert row.fields["value"].extraction_id == b_id
    assert row.fields["task"].extraction_id != b_id  # agreed fields stay pass A's
    ag = extraction_agreement(project, human)
    assert ag.disagreements == [] and ag.resolved == 1
    assert ag.overall is not None and ag.overall < 1.0  # resolving never changes agreement


def test_whole_row_choice_resolves_every_field(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _both(
        project,
        ext_a,
        ext_b,
        b=lambda w: [_r(unit="%", task="detection")] if w == odd else [_r()],
    )
    disagreements = extraction_agreement(project, human).disagreements
    assert len(disagreements) == 2
    resolve_extraction(project, human, odd, disagreements[0].row_key, None, "b", "B", Channel.CLI)
    (row,) = _final(project, odd)
    assert row.status == "resolved"
    assert (row.fields["task"].value, row.fields["value"].unit) == ("detection", "%")
    assert extraction_agreement(project, human).resolved == 2


def test_neither_drops_field_and_lists_it(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd, other = world[0], world[1]
    _both(
        project,
        ext_a,
        ext_b,
        a=lambda w: [_r(), _r("2", "t1.r3.c3")] if w == other else [_r()],
        b=lambda w: [_r(split="test")] if w == odd else [_r()],
    )
    ag = extraction_agreement(project, human)
    (field,) = [d for d in ag.disagreements if d.kind == "value"]
    (row,) = [d for d in ag.disagreements if d.kind == "row"]
    resolve_extraction(
        project, human, odd, field.row_key, "split", "neither", "unclear", Channel.CLI
    )
    resolve_extraction(
        project, human, other, row.row_key, None, "neither", "not a row", Channel.CLI
    )
    (final,) = _final(project, odd)
    assert final.status == "resolved" and "split" not in final.fields
    (kept,) = _final(project, other)
    assert kept.row_key != row.row_key and kept.status == "agreed"
    after = extraction_agreement(project, human)
    assert after.disagreements == [] and after.resolved == 2
    assert {(d.work_id, d.field) for d in after.dropped} == {(odd, "split"), (other, None)}


def test_resolution_refusals_write_nothing(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _both(project, ext_a, ext_b, b=lambda w: [_r(task="detection")] if w == odd else [_r()])
    (d,) = extraction_agreement(project, human).disagreements
    agreed_key = next(r.row_key for r in final_rows(project))
    before = len(_events(project))
    cases: list[tuple[str, str, str | None, str]] = [
        (odd, "rk_000000000000", "task", "row_key"),  # unknown row
        (world[1], agreed_key, None, "row_key"),  # a row without disagreement
        (odd, d.row_key, "hardware", "field"),  # not a declared field
        (odd, d.row_key, "metric", "field"),  # a declared field that agrees
    ]
    for work, key, name, field in cases:
        with pytest.raises(FactoryValidationError) as e:
            resolve_extraction(project, human, work, key, name, "a", "x", Channel.CLI)
        assert e.value.issues[0].field == field, (key, name)
    with pytest.raises(FactoryValidationError) as e:
        resolve_extraction(project, human, odd, d.row_key, "task", "a", "  ", Channel.CLI)
    assert e.value.issues[0].field == "reason"
    assert len(_events(project)) == before


def test_agent_cannot_resolve_and_pass_session_cannot_relay(
    project: Project, human: Actor, agent: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _both(project, ext_a, ext_b, b=lambda w: [_r(task="detection")] if w == odd else [_r()])
    (d,) = extraction_agreement(project, human).disagreements
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        resolve_extraction(project, agent, odd, d.row_key, "task", "a", "x", Channel.CLI)
    assert e.value.issues[0].field == "actor"
    relay = human.model_copy(update={"session": SESSION_B})
    with pytest.raises(FactoryValidationError) as e:
        resolve_extraction(project, relay, odd, d.row_key, "task", "a", "x", Channel.MCP)
    assert e.value.issues[0].field == "channel"
    assert len(_events(project)) == before
    # Decision 55: the world's `human` shares a session with its screening agents, so a relay
    # needs a session that joined no pass of either module.
    clean = human.model_copy(update={"session": "01JZ9Q3K5M7N8P0R2S4T6V8W1Y"})
    resolve_extraction(project, clean, odd, d.row_key, "task", "a", "relayed", Channel.MCP)
    assert extraction_agreement(project, human).disagreements == []


def test_resolution_before_a_correction_no_longer_applies(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _both(project, ext_a, ext_b, b=lambda w: [_r(task="detection")] if w == odd else [_r()])
    (d,) = extraction_agreement(project, human).disagreements
    resolve_extraction(project, human, odd, d.row_key, "task", "b", "B", Channel.CLI)
    assert extraction_agreement(project, human).disagreements == []
    # Pass B is served the unit again (a new document version would do the same); here a raw
    # correction event stands for the agent's later record of the same row.
    b_row = next(r for r in live_rows(project, PassLabel.B, work_id=odd))
    original = next(e for e in _events(project) if b_row.extraction_id in e.refs)
    payload = ExtractionRecorded.model_validate(original.payload)
    fields = dict(payload.fields)
    fields["task"] = fields["task"].model_copy(update={"value": "segmentation"})
    fix = payload.model_copy(
        update={
            "extraction_id": project.ids.new("ext"),
            "fields": fields,
            "supersedes": b_row.extraction_id,
        }
    )
    project.record(
        [
            project.events.make(
                "extraction.recorded",
                fix,
                original.actor,
                refs=(fix.extraction_id,),
                input_blob=original.input_blob,
            )
        ]
    )
    (again,) = extraction_agreement(project, human).disagreements
    assert again.b is not None and again.b.value == "segmentation"
    assert not _final(project, odd)


# --- Sample, staleness, supersession ---


def test_sample_recorded_with_seed_and_single_extraction_listed(
    project: Project,
    human: Actor,
    agent: Actor,
    ext_a: Actor,
    ext_b: Actor,
    screened: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = next(
        s
        for s in range(1000)
        if 0 < sum(in_dual_sample(s, w, 0.5) for w in screened) < len(screened)
    )
    monkeypatch.setattr(extraction.secrets, "randbits", lambda _bits: seed)
    _declare(project, agent, 0.5)
    _both(project, ext_a, ext_b)
    config = pass_config(project, PassLabel.B)
    assert config is not None and config.seed == seed
    dual = sorted(w for w in screened if in_dual_sample(seed, w, 0.5))
    single = sorted(set(screened) - set(dual))
    ag = extraction_agreement(project, human)
    assert ag.dual_works == len(dual) and ag.single_extraction == single
    assert {p.pass_label: p.seed for p in ag.passes}[PassLabel.B] == seed
    assert {p.pass_label: p.field_order for p in ag.passes} == {
        PassLabel.A: "schema",
        PassLabel.B: "reversed",
    }
    assert {p.pass_label: p.sessions for p in ag.passes} == {
        PassLabel.A: [SESSION_A],
        PassLabel.B: [SESSION_B],
    }
    assert {p.pass_label: p.models for p in ag.passes}[PassLabel.B] == ["claude-sonnet-5-5"]
    status = {r.work_id: r.status for r in final_rows(project)}
    assert status == {**dict.fromkeys(dual, "agreed"), **dict.fromkeys(single, "single")}
    assert agreement_overall(project) == AgreementOverall(
        overall=1.0,
        dual=len(dual),
        single=len(single),
        rows_aligned=len(dual),
        rows_unmatched=0,
        unmatched_slots=0,
        overall_all_rows=1.0,
    )


def test_stale_and_superseded_rows_excluded(
    project: Project, human: Actor, agent: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    def corrected(work: str) -> list[ExtractedRowInput]:
        return [_r(task="first reading")]

    # Pass A records a row, then corrects it; only the correction is live and compared.
    first = world[0]
    for _ in range(100):
        batch = extract_next(project, ext_a, PassLabel.A).batch
        if batch is None:
            break
        work = batch.records[0]["work_id"]
        rows = corrected(work) if work == first else [_r()]
        (written,) = extract_record(project, ext_a, batch.task_id, rows).rows.written
        if work == first:
            fix = extract_record(
                project, ext_a, batch.task_id, [_r()], finish=True, supersedes={0: written}
            )
            assert fix.completed
        else:
            assert extract_record(project, ext_a, batch.task_id, [], finish=True).completed
    _run(project, ext_b, PassLabel.B, _same_rows)
    assert extraction_agreement(project, human).disagreements == []
    (row,) = _final(project, first)
    assert row.fields["task"].value == "classification"
    # An amendment adding a field stales every row: none is final, none is compared.
    _amend_schema(project, agent, fields=(*FIELDS, "hardware"))
    assert final_rows(project) == []
    assert agreement_overall(project).overall is None
    assert grouped_rows(project).groups == {}


# --- Final fields, independence and grouping ---


def _ff(
    value: str | bool, *, unit: str | None = None, canon: str | None = None, **over: object
) -> FinalField:
    values: dict[str, object] = {
        "value": value,
        "unit": unit,
        "canonical": canon,
        "anchor": None,
        "cell": None,
        "quote": None,
        "reported_in": ReportedIn.OWN,
        "copy_marker": False,
        "reproduced": False,
        "cited_work": None,
        "extraction_id": "ext_1",
        **over,
    }
    return FinalField.model_validate(values)


def _final_row(
    key: str = "rk_0123456789ab", independent: bool = True, **fields: FinalField
) -> FinalRow:
    return FinalRow(
        work_id="rf:w1",
        document_id="doc_1",
        conversion_id="cnv_1",
        row_key=key,
        status="agreed",
        fields=fields,
        independent=independent,
    )


def test_final_field_is_effectively_cited_on_a_marker() -> None:
    own = final_field(_stored("value", "1"), "ext_1")
    marked = final_field(_stored("value", "1", copy_marker=True), "ext_1")
    cited = final_field(_stored("value", "1", reported_in=ReportedIn.CITED), "ext_1")
    assert own.reported_in is ReportedIn.OWN
    assert marked.reported_in is ReportedIn.CITED and marked.copy_marker
    assert cited.reported_in is ReportedIn.CITED


def test_copied_result_not_counted_independent(
    project: Project, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    rows = [
        _final_row(value=_ff("1")),
        _final_row(value=_ff("1", reported_in=ReportedIn.CITED), independent=False),
        _final_row(
            value=_ff("1", reported_in=ReportedIn.CITED, copy_marker=True), independent=False
        ),
    ]
    assert independence_counts(rows) == IndependenceCounts(independent=1, copied=2)
    # Through the services: a value declared cited is not independent.
    cited = world[0]

    def rows_for(work: str) -> list[ExtractedRowInput]:
        return [_r(reported_in=ReportedIn.CITED)] if work == cited else [_r()]

    _both(project, ext_a, ext_b, a=rows_for, b=rows_for)
    finals = final_rows(project)
    assert {r.work_id for r in finals if not r.independent} == {cited}
    assert independence_counts(finals) == IndependenceCounts(independent=len(world) - 1, copied=1)


GROUP_KEYS = ("task", "dataset", "split", "metric", "input_resolution", "pretraining_data")


def _keyed(key: str, **over: FinalField) -> FinalRow:
    fields = {
        "task": _ff("Image Classification"),
        "dataset": _ff("ImageNet-1K"),
        "split": _ff("val"),
        "metric": _ff("Top-1  Accuracy"),
        "input_resolution": _ff("224 × 224"),
        "pretraining_data": _ff("None"),
        "value": _ff("82.4", unit="%", canon="82.4"),
        **over,
    }
    return _final_row(key, **fields)


def test_grouped_rows_use_comparability_keys_only() -> None:
    first = _keyed("rk_000000000001")
    other_value = _keyed("rk_000000000002", value=_ff("79.0", unit="%", canon="79"))
    row_missing_split = _keyed("rk_000000000003")
    del row_missing_split.fields["split"]
    g = group_rows([first, other_value, row_missing_split], PACK, GROUP_KEYS)
    assert list(g.groups) == [
        (
            ("task", "image classification"),
            ("dataset", "imagenet-1k"),
            ("split", "val"),
            ("metric", "top-1 accuracy"),
            ("input_resolution", "224x224"),
            ("pretraining_data", "none"),
        )
    ]
    (members,) = g.groups.values()
    assert members == [first, other_value]
    assert g.ungrouped == [row_missing_split]


def test_resolution_variants_group_together() -> None:
    rows = [
        _keyed(f"rk_00000000000{i}", input_resolution=_ff(variant))
        for i, variant in enumerate(("224", "224x224", "224²", "224 × 224"))
    ]
    g = group_rows(rows, PACK, GROUP_KEYS)
    assert len(g.groups) == 1 and len(next(iter(g.groups.values()))) == 4


def test_throughput_never_part_of_group_key() -> None:
    fast = _keyed("rk_000000000001", throughput=_ff("1200", canon="1200"))
    slow = _keyed("rk_000000000002", throughput=_ff("300", canon="300"))
    g = group_rows([fast, slow], PACK, (*GROUP_KEYS, "throughput", "latency", "memory"))
    (key,) = g.groups
    assert {name for name, _ in key} == set(GROUP_KEYS)
    assert g.groups[key] == [fast, slow] and g.ungrouped == []


def test_grouped_rows_through_the_services(
    project: Project, agent: Actor, ext_a: Actor, ext_b: Actor, screened: list[str]
) -> None:
    fields = (*FIELDS, "throughput")
    _declare(project, agent, fields=fields, keys=(*KEYS, "pretraining_data"))
    unsplit = screened[0]

    def rows_for(work: str) -> list[ExtractedRowInput]:
        speed = FieldInput(value="2", anchor="t1", cell="t1.r3.c3", quote="2")
        none = FieldInput(value="None")
        if work == unsplit:
            return [_r(split=None, pretraining_data=none, throughput=speed)]
        return [_r(pretraining_data=none, throughput=speed)]

    _both(project, ext_a, ext_b, a=rows_for, b=rows_for)
    g = grouped_rows(project)
    assert list(g.groups) == [
        (
            ("task", "classification"),
            ("dataset", "lorem ipsum"),
            ("split", "val"),
            ("metric", "low"),
            ("pretraining_data", "none"),
        )
    ]
    assert len(next(iter(g.groups.values()))) == len(screened) - 1
    assert [r.work_id for r in g.ungrouped] == [unsplit]
    assert g.unresolved == []


def test_number_keys_use_canonical_value() -> None:
    a = _keyed("rk_000000000001", params=_ff("22.1", unit="M", canon="22100000"))
    b = _keyed("rk_000000000002", params=_ff("22100000", unit="", canon="22100000"))
    g = group_rows([a, b], PACK, (*GROUP_KEYS, "params"))
    assert len(g.groups) == 1


# --- Fix round 1: required fields, neither rules, denominators, schema rule, model check ---


def _value_split(project: Project, ext_a: Actor, ext_b: Actor, odd: str) -> None:
    """Pass B differs on the value's unit and on `task` in `odd`, and omits `split` there."""
    _both(
        project,
        ext_a,
        ext_b,
        b=lambda w: [_r(unit="%", task="detection", split=None)] if w == odd else [_r()],
    )


def _required_present(project: Project) -> None:
    for row in final_rows(project):
        assert set(PACK.required) <= set(row.fields), row


def test_neither_on_value_drops_the_whole_row(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _value_split(project, ext_a, ext_b, odd)
    key = extraction_agreement(project, human).disagreements[0].row_key
    resolve_extraction(project, human, odd, key, "value", "neither", "unreadable", Channel.CLI)
    assert _final(project, odd) == []
    after = extraction_agreement(project, human)
    assert after.disagreements == []
    assert [(d.work_id, d.row_key, d.field) for d in after.dropped] == [(odd, key, None)]
    _required_present(project)


def test_neither_on_another_required_field_is_refused(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _value_split(project, ext_a, ext_b, odd)
    key = extraction_agreement(project, human).disagreements[0].row_key
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        resolve_extraction(project, human, odd, key, "task", "neither", "x", Channel.CLI)
    assert e.value.issues[0].field == "choice"
    assert "drop the row instead" in e.value.issues[0].reason
    assert len(_events(project)) == before
    # A field the pack does not require may be dropped; the row is final once all is resolved.
    resolve_extraction(project, human, odd, key, "split", "neither", "x", Channel.CLI)
    resolve_extraction(project, human, odd, key, "task", "a", "x", Channel.CLI)
    resolve_extraction(project, human, odd, key, "value", "b", "x", Channel.CLI)
    (row,) = _final(project, odd)
    assert "split" not in row.fields and row.status == "resolved"
    _required_present(project)


def test_no_final_row_lacks_a_required_field(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _value_split(project, ext_a, ext_b, odd)
    _required_present(project)
    key = extraction_agreement(project, human).disagreements[0].row_key
    resolve_extraction(project, human, odd, key, None, "b", "B", Channel.CLI)
    (row,) = _final(project, odd)
    assert "split" not in row.fields
    _required_present(project)


def test_field_choice_on_a_dropped_row_is_refused(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _value_split(project, ext_a, ext_b, odd)
    key = extraction_agreement(project, human).disagreements[0].row_key
    resolve_extraction(project, human, odd, key, None, "neither", "drop", Channel.CLI)
    before = len(_events(project))
    with pytest.raises(FactoryValidationError) as e:
        resolve_extraction(project, human, odd, key, "split", "a", "x", Channel.CLI)
    assert e.value.issues[0].field == "field"
    assert len(_events(project)) == before
    # A whole-row choice still changes something and is accepted.
    resolve_extraction(project, human, odd, key, None, "a", "keep A", Channel.CLI)
    assert len(_final(project, odd)) == 1


def test_field_choice_after_neither_on_value_is_refused(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _value_split(project, ext_a, ext_b, odd)
    key = extraction_agreement(project, human).disagreements[0].row_key
    resolve_extraction(project, human, odd, key, "value", "neither", "drop", Channel.CLI)
    with pytest.raises(FactoryValidationError) as e:
        resolve_extraction(project, human, odd, key, "split", "a", "x", Channel.CLI)
    assert e.value.issues[0].field == "field"


def test_agreement_overall_reports_its_row_denominators(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    extra = world[0]
    _both(
        project,
        ext_a,
        ext_b,
        a=lambda w: [_r(), _r("2", "t1.r3.c3")] if w == extra else [_r()],
    )
    overall = agreement_overall(project)
    ag = extraction_agreement(project, human)
    assert (overall.rows_aligned, overall.rows_unmatched) == (ag.rows_aligned, ag.rows_unmatched)
    assert (overall.rows_aligned, overall.rows_unmatched) == (len(world), 1)


def test_speed_and_memory_are_not_comparability_keys() -> None:
    fields = ("method_name", "task", "dataset", "metric", "value", "throughput", "memory")
    bad = _schema(fields=fields, comparability_keys=("task", "throughput", "memory"))
    issues = {i.field: i.reason for i in _check(_with(bad)).errors}
    for index in (1, 2):
        assert issues[f"extraction_schema.comparability_keys[{index}]"] == (
            "speed/memory are not comparability keys"
        )
    assert "extraction_schema.comparability_keys[0]" not in issues
    assert {"throughput", "latency", "memory"} == NON_COMPARABLE_KEYS


def test_model_switch_in_recorded_rows_is_caught(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    _both(project, ext_a, ext_b)
    b_row = live_rows(project, PassLabel.B)[0]
    original = next(e for e in _events(project) if b_row.extraction_id in e.refs)
    payload = ExtractionRecorded.model_validate(original.payload)
    fix = payload.model_copy(
        update={"extraction_id": project.ids.new("ext"), "supersedes": b_row.extraction_id}
    )
    switched = original.actor.model_copy(update={"model": ext_a.model})
    project.record(
        [
            project.events.make(
                "extraction.recorded",
                fix,
                switched,
                refs=(fix.extraction_id,),
                input_blob=original.input_blob,
            )
        ]
    )
    with pytest.raises(FactoryValidationError) as e:
        extraction_agreement(project, human)
    assert e.value.issues[0].field == "passes"
    assert "model" in e.value.issues[0].reason


# --- IDEA-69 (2): unmatched rows count against the rate over all rows ---


def test_rate_over_all_rows_counts_unmatched_slots(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    # pass B cites another cell on one work: two row keys, one slot, six compared values lost
    _both(project, ext_a, ext_b, b=lambda w: [_r("2", "t1.r3.c3")] if w == odd else [_r()])
    ag = extraction_agreement(project, human)
    n = len(world)
    assert (ag.rows_aligned, ag.rows_unmatched, ag.unmatched_slots) == (n - 1, 2, 1)
    assert ag.overall == 1.0
    assert ag.overall_all_rows == pytest.approx((n - 1) / n)
    overall = agreement_overall(project)
    assert (overall.overall_all_rows, overall.unmatched_slots) == (ag.overall_all_rows, 1)
    from factory.cli.render import agreement_lines

    line = agreement_lines(ag)[1]
    assert "over all rows" in line and f"aligned {n - 1}" in line and "unmatched slots 1" in line


def test_an_extra_row_of_one_pass_is_one_slot(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    extra = world[0]
    _both(
        project,
        ext_a,
        ext_b,
        a=lambda w: [_r(), _r("2", "t1.r3.c3")] if w == extra else [_r()],
    )
    ag = extraction_agreement(project, human)
    n = len(world)
    assert (ag.unmatched_slots, ag.overall) == (1, 1.0)
    assert ag.overall_all_rows == pytest.approx(6 * n / (6 * n + 6))

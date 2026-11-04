"""The protocol's extraction schema: hash, readiness, amendment staleness (rulings 1, 9, 12)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.project import RigorMode
from factory.model.protocol import (
    ExtractionSchema,
    ExtractionStale,
    ProtocolAmended,
    ProtocolSpec,
    protocol_version,
)
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol, list_amendments
from factory.services.protocol_rules import extraction_stale
from tests.helpers import SourcesFor, pilot_protocol_spec, ready_protocol
from tests.test_protocol_rules import _check, _fields, _spec

PINNED_P_ID = "P@1e7c316e"  # pilot_protocol_spec("Q@aaaaaaaa", "prb_1") before extraction_schema
FIELDS = ("method_name", "task", "dataset", "split", "metric", "value", "latency")
KEYS = ("task", "dataset", "metric")


def _schema(**kw: Any) -> ExtractionSchema:
    base: dict[str, Any] = {
        "pack": "ml-benchmark",
        "pack_version": 1,
        "fields": FIELDS,
        "comparability_keys": KEYS,
        "dual_extract_sample": 0.5,
    }
    base.update(kw)
    return ExtractionSchema.model_validate(base)


def _with(schema: ExtractionSchema | None) -> ProtocolSpec:
    return _spec(extraction_schema=schema)


def _extraction_fields(fields: list[Any]) -> set[str]:
    return {f for f in fields if f.startswith("extraction")}


def test_p_id_unchanged_without_schema() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    assert spec.extraction_schema is None
    assert protocol_version(spec) == PINNED_P_ID


def test_p_id_changes_with_schema() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    with_schema = spec.model_copy(update={"extraction_schema": _schema()})
    assert protocol_version(with_schema) != PINNED_P_ID
    other = spec.model_copy(update={"extraction_schema": _schema(claims=False)})
    assert protocol_version(other) != protocol_version(with_schema)


def test_schema_model_defaults_and_bounds() -> None:
    s = _schema(dual_extract_sample=None)
    assert (s.audit_fraction, s.audit_minimum, s.claims) == (0.02, 50, True)
    for bad in (
        {"fields": ()},
        {"fields": ("task", "task")},
        {"comparability_keys": ("task", "task")},
        {"pack_version": 0},
        {"dual_extract_sample": 0},
        {"dual_extract_sample": 1.5},
        {"audit_fraction": 1.1},
        {"audit_minimum": -1},
    ):
        with pytest.raises(ValidationError):
            _schema(**bad)


def test_no_schema_means_no_extraction_issues() -> None:
    check = _check(_with(None))
    assert not _extraction_fields(_fields(check.errors + check.gaps))


def test_valid_schema_has_no_issues() -> None:
    check = _check(_with(_schema()))
    assert not _extraction_fields(_fields(check.errors + check.gaps))


def test_unknown_pack_field_and_missing_required_are_errors() -> None:
    bad = _schema(fields=("bogus", "task"), comparability_keys=())
    errs = set(_fields(_check(_with(bad)).errors))
    assert {"extraction_schema.fields[0]", "extraction_schema.fields"} <= errs
    unknown = set(_fields(_check(_with(_schema(pack="nope"))).errors))
    assert "extraction_schema.pack" in unknown
    version = set(_fields(_check(_with(_schema(pack_version=99))).errors))
    assert "extraction_schema.pack" in version


def test_comparability_key_must_be_declared_field() -> None:
    errs = _fields(_check(_with(_schema(comparability_keys=("pretraining_data",)))).errors)
    assert "extraction_schema.comparability_keys[0]" in errs


def _gap_fields(mode: RigorMode, **kw: Any) -> set[str]:
    return _extraction_fields(_fields(_check(_with(_schema(**kw)), mode).gaps))


def test_pilot_needs_fraction_systematic_needs_all() -> None:
    assert "extraction_schema.dual_extract_sample" in _gap_fields(
        RigorMode.PILOT, dual_extract_sample=None
    )
    assert not _gap_fields(RigorMode.PILOT, dual_extract_sample=0.5)
    assert "extraction_schema.dual_extract_sample" in _gap_fields(
        RigorMode.SYSTEMATIC, dual_extract_sample=0.5
    )
    assert not _gap_fields(RigorMode.SYSTEMATIC, dual_extract_sample=1.0)
    assert not _gap_fields(RigorMode.SYSTEMATIC, dual_extract_sample=None)


def test_systematic_gap_message_says_every_work_is_extracted_twice() -> None:
    gaps = _check(_with(_schema(dual_extract_sample=0.5)), RigorMode.SYSTEMATIC).gaps
    [gap] = [g for g in gaps if g.field == "extraction_schema.dual_extract_sample"]
    assert gap.reason == (
        "systematic extraction needs dual_extract_sample unset or 1.0: "
        "every work is extracted twice"
    )


def test_pilot_and_systematic_need_comparability_keys() -> None:
    for mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC):
        assert "extraction_schema.comparability_keys" in _gap_fields(
            mode, comparability_keys=(), dual_extract_sample=1.0
        )
        assert not _gap_fields(mode, dual_extract_sample=1.0)
    assert not _gap_fields(RigorMode.EXPLORATORY, comparability_keys=())


def test_audit_floors_apply_in_pilot_and_systematic_only() -> None:
    for mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC):
        gaps = _gap_fields(mode, dual_extract_sample=1.0, audit_fraction=0.01, audit_minimum=10)
        assert {"extraction_schema.audit_fraction", "extraction_schema.audit_minimum"} <= gaps
    assert not _gap_fields(
        RigorMode.EXPLORATORY, dual_extract_sample=None, audit_fraction=0.0, audit_minimum=0
    )


S = _schema()


def _minus(schema: ExtractionSchema, name: str) -> ExtractionSchema:
    return schema.model_copy(update={"fields": tuple(f for f in schema.fields if f != name)})


def test_extraction_stale_rules() -> None:
    assert extraction_stale(None, S) is None
    assert extraction_stale(None, None) is None
    plus = S.model_copy(update={"fields": (*S.fields, "params")})
    assert extraction_stale(S, plus) == ExtractionStale(all_records=True)
    assert extraction_stale(S, _minus(S, "latency")) == ExtractionStale(
        all_records=False, fields=("latency",)
    )
    other_keys = S.model_copy(update={"comparability_keys": ("task",)})
    assert extraction_stale(S, other_keys) is None
    settings = S.model_copy(update={"dual_extract_sample": 1.0, "audit_minimum": 60})
    assert extraction_stale(S, settings) is None
    assert extraction_stale(S, S.model_copy(update={"claims": False})) is None
    assert extraction_stale(S, S) is None
    assert extraction_stale(S, None) == ExtractionStale(all_records=True)
    assert extraction_stale(S, S.model_copy(update={"pack_version": 2})) == ExtractionStale(
        all_records=True
    )
    assert extraction_stale(S, S.model_copy(update={"pack": "other"})) == ExtractionStale(
        all_records=True
    )


def test_extraction_stale_add_and_remove_together_is_all_records() -> None:
    swapped = S.model_copy(update={"fields": (*_minus(S, "latency").fields, "params")})
    assert extraction_stale(S, swapped) == ExtractionStale(all_records=True)


def test_extraction_stale_removal_ignores_field_order() -> None:
    reordered = S.model_copy(update={"fields": tuple(reversed(_minus(S, "latency").fields))})
    assert extraction_stale(S, reordered) == ExtractionStale(all_records=False, fields=("latency",))


def test_amend_records_extraction_stale_and_reports_other_change(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources, press=False)
    old = current_protocol(project)
    assert old is not None
    first = old.spec.model_copy(update={"extraction_schema": _schema()})
    amend_protocol(project, agent, first, reason="declare", semantic=True, effects={})
    first_amendment = list_amendments(project)[-1]
    assert first_amendment.extraction_stale is None  # nothing was declared before
    assert "extraction_schema" in first_amendment.other_changes

    smaller = first.model_copy(update={"extraction_schema": _minus(_schema(), "latency")})
    amend_protocol(project, agent, smaller, reason="drop latency", semantic=True, effects={})
    amended = list_amendments(project)[-1]
    assert amended.extraction_stale == ExtractionStale(all_records=False, fields=("latency",))
    assert "extraction_schema" in amended.other_changes and amended.semantic is True


def test_amend_refuses_a_schema_the_pack_does_not_support(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources, press=False)
    old = current_protocol(project)
    assert old is not None
    bad = old.spec.model_copy(update={"extraction_schema": _schema(fields=("bogus",))})
    before = len(read_all(project.paths.events_dir, project.catalog))
    with pytest.raises(FactoryValidationError) as raised:
        amend_protocol(project, agent, bad, reason="bad", semantic=True, effects={})
    assert "extraction_schema.fields[0]" in [i.field for i in raised.value.issues]
    assert len(read_all(project.paths.events_dir, project.catalog)) == before  # nothing written


def test_old_amendment_event_validates_without_extraction_stale() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    payload = {
        "amendment_id": "amd_01JZ9Q3K5M7N8P0R2S4T6V8W0X",
        "from_version": PINNED_P_ID,
        "to_version": PINNED_P_ID,
        "spec": spec.model_dump(mode="json"),
        "reason": "old",
        "semantic": False,
    }
    assert ProtocolAmended.model_validate(payload).extraction_stale is None

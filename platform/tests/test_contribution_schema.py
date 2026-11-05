"""The protocol's `contribution_schema`: hash, readiness, scope-local amendment staleness.

Slice 3b ruling 5; plan G2-A ruling 6 and Review Focus 5.
"""

from __future__ import annotations

from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.project import RigorMode
from factory.model.protocol import (
    AMENDABLE_FIELDS,
    ExtractionSchema,
    ExtractionStale,
    ProtocolAmended,
    ProtocolSpec,
    protocol_version,
)
from factory.packs.contribution import CONTRIBUTION_V1
from factory.services.context import Project
from factory.services.protocol import amend_protocol, current_protocol, list_amendments
from tests.extraction_helpers import PINNED_P_ID as PINNED_NO_SCHEMAS
from tests.extraction_helpers import _schema as _evidence
from tests.helpers import SourcesFor, pilot_protocol_spec, ready_protocol
from tests.test_protocol_rules import _check, _fields, _spec

PINNED_P_ID = "P@ac93b512"
"""pilot_protocol_spec("Q@aaaaaaaa", "prb_1") with the evidence schema only, computed before
`contribution_schema` existed."""

CONTRIBUTION_FIELDS = tuple(f.name for f in CONTRIBUTION_V1.fields)


def _contribution(**kw: Any) -> ExtractionSchema:
    base: dict[str, Any] = {
        "pack": "contribution",
        "pack_version": 1,
        "fields": CONTRIBUTION_FIELDS,
        "dual_extract_sample": 0.5,
        "claims": False,
    }
    base.update(kw)
    return ExtractionSchema.model_validate(base)


def _minus(schema: ExtractionSchema, name: str) -> ExtractionSchema:
    return schema.model_copy(update={"fields": tuple(f for f in schema.fields if f != name)})


def _with(
    contribution: ExtractionSchema | None = None, evidence: ExtractionSchema | None = None
) -> ProtocolSpec:
    return _spec(contribution_schema=contribution, extraction_schema=evidence)


def _scoped(fields: list[str], prefix: str) -> set[str]:
    return {f for f in fields if f.startswith(prefix)}


def _errors(**kw: Any) -> set[str]:
    return set(_fields(_check(_with(**kw)).errors))


def _gaps(mode: RigorMode, **kw: Any) -> set[str]:
    return _scoped(_fields(_check(_with(_contribution(**kw)), mode).gaps), "contribution_schema")


def test_p_id_unchanged_without_contribution_schema() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    assert spec.contribution_schema is None
    assert protocol_version(spec) == PINNED_NO_SCHEMAS
    with_evidence = spec.model_copy(update={"extraction_schema": _evidence()})
    assert protocol_version(with_evidence) == PINNED_P_ID


def test_p_id_changes_with_contribution_schema() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1").model_copy(
        update={"extraction_schema": _evidence()}
    )
    declared = spec.model_copy(update={"contribution_schema": _contribution()})
    assert protocol_version(declared) != PINNED_P_ID
    other = spec.model_copy(update={"contribution_schema": _contribution(audit_minimum=60)})
    assert protocol_version(other) != protocol_version(declared)


def test_contribution_schema_is_amendable() -> None:
    assert "contribution_schema" in AMENDABLE_FIELDS


def test_valid_contribution_schema_has_no_issues() -> None:
    for mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC, RigorMode.EXPLORATORY):
        sample = 0.5 if mode is RigorMode.PILOT else 1.0
        check = _check(_with(_contribution(dual_extract_sample=sample), _evidence()), mode)
        assert not _scoped(_fields(check.errors + check.gaps), "contribution_schema")
        assert not _scoped(_fields(check.errors), "extraction_schema")


def test_contribution_schema_errors() -> None:
    assert "contribution_schema.pack" in _errors(contribution=_contribution(pack="ml-benchmark"))
    assert "contribution_schema.pack" in _errors(contribution=_contribution(pack_version=99))
    assert "contribution_schema.claims" in _errors(contribution=_contribution(claims=True))
    keyed = _contribution(comparability_keys=("name",))
    assert "contribution_schema.comparability_keys" in _errors(contribution=keyed)
    assert "extraction_schema.pack" in _errors(
        evidence=_evidence(pack="contribution", fields=CONTRIBUTION_FIELDS, comparability_keys=())
    )


def test_contribution_schema_field_errors_follow_plan_d() -> None:
    errs = _errors(contribution=_contribution(fields=("bogus", "name")))
    assert {"contribution_schema.fields[0]", "contribution_schema.fields"} <= errs
    message = [
        i.reason
        for i in _check(_with(_contribution(fields=("name",)))).errors
        if i.field == "contribution_schema.fields"
    ]
    assert message == ["required by the pack: item_kind"]


def test_contribution_gaps_follow_plan_d_rules() -> None:
    assert "contribution_schema.dual_extract_sample" in _gaps(
        RigorMode.PILOT, dual_extract_sample=None
    )
    assert not _gaps(RigorMode.PILOT, dual_extract_sample=0.5)
    assert "contribution_schema.dual_extract_sample" in _gaps(
        RigorMode.SYSTEMATIC, dual_extract_sample=0.5
    )
    assert not _gaps(RigorMode.SYSTEMATIC, dual_extract_sample=1.0)
    assert not _gaps(RigorMode.SYSTEMATIC, dual_extract_sample=None)
    for mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC):
        gaps = _gaps(mode, dual_extract_sample=1.0, audit_fraction=0.01, audit_minimum=10)
        assert gaps == {"contribution_schema.audit_fraction", "contribution_schema.audit_minimum"}
    assert not _gaps(
        RigorMode.EXPLORATORY, dual_extract_sample=None, audit_fraction=0.0, audit_minimum=0
    )


def _ready_with_both(project: Project, agent: Actor, human: Actor, sources: SourcesFor) -> None:
    ready_protocol(project, agent, human, sources, press=False)
    old = current_protocol(project)
    assert old is not None
    both = old.spec.model_copy(
        update={"extraction_schema": _evidence(), "contribution_schema": _contribution()}
    )
    amend_protocol(project, agent, both, reason="declare both", semantic=True, effects={})
    declared = list_amendments(project)[-1]
    assert declared.extraction_stale is None and declared.contribution_stale is None
    assert {"extraction_schema", "contribution_schema"} <= set(declared.other_changes)


def _amend(project: Project, agent: Actor, **update: ExtractionSchema) -> ProtocolAmended:
    current = current_protocol(project)
    assert current is not None
    spec = current.spec.model_copy(update=update)
    amend_protocol(project, agent, spec, reason="narrow", semantic=True, effects={})
    return list_amendments(project)[-1]


def test_amendments_are_scope_local(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    _ready_with_both(project, agent, human, mock_sources)
    a = _amend(project, agent, contribution_schema=_minus(_contribution(), "compared_to"))
    assert a.contribution_stale == ExtractionStale(all_records=False, fields=("compared_to",))
    assert a.extraction_stale is None
    assert a.other_changes == ("contribution_schema",)
    b = _amend(project, agent, extraction_schema=_minus(_evidence(), "latency"))
    assert b.extraction_stale == ExtractionStale(all_records=False, fields=("latency",))
    assert b.contribution_stale is None
    assert b.other_changes == ("extraction_schema",)


def test_amend_refuses_invalid_contribution_schema(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor
) -> None:
    ready_protocol(project, agent, human, mock_sources, press=False)
    old = current_protocol(project)
    assert old is not None
    bad = old.spec.model_copy(update={"contribution_schema": _contribution(claims=True)})
    before = len(read_all(project.paths.events_dir, project.catalog))
    with pytest.raises(FactoryValidationError) as raised:
        amend_protocol(project, agent, bad, reason="bad", semantic=True, effects={})
    assert "contribution_schema.claims" in [i.field for i in raised.value.issues]
    assert len(read_all(project.paths.events_dir, project.catalog)) == before


def test_old_amendment_event_validates_without_contribution_stale() -> None:
    spec = pilot_protocol_spec("Q@aaaaaaaa", "prb_1")
    payload = {
        "amendment_id": "amd_01JZ9Q3K5M7N8P0R2S4T6V8W0X",
        "from_version": PINNED_NO_SCHEMAS,
        "to_version": PINNED_NO_SCHEMAS,
        "spec": spec.model_dump(mode="json"),
        "reason": "old",
        "semantic": False,
        "extraction_stale": {"all_records": True},
    }
    amended = ProtocolAmended.model_validate(payload)
    assert amended.contribution_stale is None
    assert "contribution_stale" not in amended.model_dump(exclude_defaults=True)

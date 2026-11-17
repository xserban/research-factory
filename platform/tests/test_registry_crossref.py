"""Crossref is a lookup and status source, not a searchable default source (IDEA-89)."""

from factory.model.project import RigorMode
from factory.model.protocol import SourcePlan
from factory.services.protocol_rules import protocol_issues
from factory.sources.registry import default_sources, lookup_sources, status_sources
from tests.screening_helpers import PROBES, QID, QUESTION, _spec


def test_crossref_is_a_lookup_and_status_source_only() -> None:
    assert "crossref" not in default_sources()
    assert set(lookup_sources()) == set(status_sources()) == {*default_sources(), "crossref"}


def test_protocol_naming_crossref_is_refused_at_validation() -> None:
    spec = _spec(sources=(SourcePlan(name="crossref", included=True, probe_id="prb_1"),))
    check = protocol_issues(
        spec,
        question=QUESTION,
        current_question_id=QID,
        mode=RigorMode.PILOT,
        seeds=[],
        probes=PROBES,
        known_sources=set(default_sources()),
    )
    assert ("sources[0].name", "unknown source") in [(i.field, i.reason) for i in check.errors]

"""Every input that names a work matches it by NFC form (IDEA-66).

A Hangul word of a work id is stored decomposed (jamo: `normalize_title` applies NFKD), while a
model or a person writes it composed. Each entry point takes either spelling, writes the stored
spelling into its event, and still refuses an id that names no work. The world is the full-text
test world with one Korean work added (as in `test_document_read_nfc`).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.extraction import ExtractedRowInput, FieldInput
from factory.model.hypotheses import LeadInput, Trigger, TriggerKind
from factory.model.protocol import ScreeningStage
from factory.model.screening import Channel
from factory.regions.rules import MemberType
from factory.services import audit, work_layers
from factory.services.audit import audit_record, audit_sample
from factory.services.calibration import calibration_items, draw_calibration, label_calibration
from factory.services.context import Project
from factory.services.document_convert import convert_documents
from factory.services.fulltext import fetch_fulltext
from factory.services.labels import LabelInput, apply_labels
from factory.services.leads import record_lead
from factory.services.trace import trace
from factory.services.work_layers import move_layer, request_mining
from factory.sources.registry import SourceFactory
from tests.document_helpers import (
    ARTICLE,
    StubConverter,
    events_of_type,
    fetched_document,
    make_registry,
    promoted_works,
)
from tests.fulltext_helpers import _routes, _world
from tests.helpers import openalex_item

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
TA = ScreeningStage.TITLE_ABSTRACT
FT = ScreeningStage.FULL_TEXT

KOREAN = openalex_item(
    title="Agents 과학 discovery",
    author="Minsu Ahn",
    published="2021-01-01",
    openalex_id="W901",
    doi="10.1000/k1",
)


@pytest.fixture
def stored(project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor) -> str:
    """The Korean work's stored (decomposed) id, in a world promoted through title/abstract with
    a full-text calibration floor large enough to hold every work."""
    _world(project, agent, human, mock_sources, extra_items=[KOREAN], calibration=200)
    (work,) = [w for w in promoted_works(project) if unicodedata.normalize("NFC", w) != w]
    return work


def _composed(work: str) -> str:
    composed = unicodedata.normalize("NFC", work)
    assert composed != work
    return composed


def _payloads(project: Project, event_type: str) -> list[dict[str, Any]]:
    return [dict(e.payload) for e in events_of_type(project, event_type)]


# --- Screening labels (human) ---


def test_calibration_label_takes_the_composed_spelling(
    project: Project, human: Actor, stored: str
) -> None:
    for work in promoted_works(project):
        fetched_document(project, work, ARTICLE)
    convert_documents(project, make_registry(StubConverter()))
    draw_calibration(project, project.system_actor(), random_seed=3, stage=FT)
    assert stored in calibration_items(project, stage=FT)
    label_calibration(project, human, _composed(stored), "include", None, Channel.CLI, stage=FT)
    (payload,) = [p for p in _payloads(project, "calibration.labelled") if p["stage"] == FT]
    assert payload["work_id"] == stored


def test_audit_label_takes_the_composed_spelling(
    project: Project, human: Actor, stored: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The Korean work is in this world's title/abstract calibration set, so no audit can sample
    # it; the sample check is narrowed to the stored id to isolate the resolution step.
    sampled = audit_sample(project, human, random_seed=7, stage=TA)
    monkeypatch.setattr(audit, "_sampled", lambda project, audit_id, work_id: work_id == stored)
    audit_record(project, human, sampled.audit_id, _composed(stored), "include", None, Channel.CLI)
    (payload,) = _payloads(project, "audit.labelled")
    assert payload["work_id"] == stored


def test_audit_label_still_refuses_an_unknown_work(
    project: Project, human: Actor, stored: str
) -> None:
    sampled = audit_sample(project, human, random_seed=7, stage=TA)
    with pytest.raises(FactoryValidationError) as caught:
        audit_record(project, human, sampled.audit_id, stored + "x", "include", None, Channel.CLI)
    assert [i.field for i in caught.value.issues] == ["work_id"]


# --- Documents ---


def test_convert_by_work_takes_the_composed_spelling(project: Project, stored: str) -> None:
    fetched_document(project, stored, ARTICLE)
    summary = convert_documents(
        project, make_registry(StubConverter()), work_ids=[_composed(stored)]
    )
    assert [o.work_id for o in summary.outcomes] == [stored]


def test_fetch_by_work_takes_the_composed_spelling(project: Project, stored: str) -> None:
    summary = fetch_fulltext(
        project, routes=_routes(html={stored}), work_ids=[_composed(stored)], refresh=True
    )
    assert [w.work_id for w in summary.works] == [stored]
    (started,) = _payloads(project, "fulltext.fetch_started")
    assert started["work_ids"] == [stored]


# --- Trace, labels, leads ---


def test_trace_takes_the_composed_spelling(project: Project, stored: str) -> None:
    assert trace(project, _composed(stored)).id == trace(project, stored).id


def test_trace_still_refuses_an_unknown_work(project: Project, stored: str) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        trace(project, stored[:-8] + "00000000")
    assert [i.field for i in caught.value.issues] == ["ref"]


def test_label_apply_takes_the_composed_spelling(
    project: Project, agent: Actor, stored: str
) -> None:
    item = LabelInput(target_type=MemberType.WORK, target=_composed(stored), text="korean")
    result = apply_labels(project, agent, [item])
    assert result.rejected == [] and len(result.written) == 1
    (payload,) = _payloads(project, "label.applied")
    assert payload["target"] == stored


def test_lead_record_takes_the_composed_spelling(
    project: Project, agent: Actor, stored: str
) -> None:
    lead = LeadInput(
        text="a lead on the Korean work",
        triggers=(Trigger(kind=TriggerKind.WORK, ref=_composed(stored)),),
    )
    record_lead(project, agent, lead)
    (payload,) = _payloads(project, "lead.recorded")
    assert [t["ref"] for t in payload["triggers"]] == [stored]


# --- Extraction rows (extract_record, mine_record and contribution_record share `_record`) ---


def test_a_cited_work_in_a_row_takes_the_stored_spelling(stored: str) -> None:
    from factory.services.extraction import _cited_as_stored

    row = ExtractedRowInput(fields={"cites": FieldInput(value="x", cited_work=_composed(stored))})
    checked, issues = _cited_as_stored(row, {stored, "rf:other-00000000"})
    assert issues == []
    assert checked.fields["cites"].cited_work == stored


def test_a_cited_work_matching_several_is_an_issue() -> None:
    from factory.services.extraction import _cited_as_stored

    split = "rf:한-00000000"
    partly = "rf:한-00000000"
    row = ExtractedRowInput(
        fields={"cites": FieldInput(value="x", cited_work=unicodedata.normalize("NFC", split))}
    )
    _, issues = _cited_as_stored(row, {split, partly})
    assert [i.field for i in issues] == ["fields.cites.cited_work"]


# --- The hub's write path (layer acts) ---


def test_move_layer_resolves_the_composed_spelling(
    project: Project, human: Actor, stored: str
) -> None:
    # No layer scheme is recorded, so the act is refused on `layer`: the work id has been
    # accepted (a composed id would otherwise be refused on `work_id`).
    with pytest.raises(FactoryValidationError) as caught:
        move_layer(project, human, _composed(stored), "L1", "because")
    assert [i.field for i in caught.value.issues] == ["layer"]
    with pytest.raises(FactoryValidationError) as unknown:
        move_layer(project, human, stored + "x", "L1", "because")
    assert [i.field for i in unknown.value.issues] == ["work_id"]


def test_request_mining_takes_the_composed_spelling(
    project: Project, human: Actor, stored: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(work_layers, "_on_demand_miners", lambda project: ["m-test"])
    monkeypatch.setattr(work_layers, "included_works", lambda project: promoted_works(project))
    request_mining(project, human, works=(_composed(stored),), reason="read it")
    (payload,) = _payloads(project, "mining.requested")
    assert list(payload["works"]) == [stored]

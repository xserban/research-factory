# ruff: noqa: F401, F811
"""Row-basis scoping, definition caching and merge/support staleness of cards (H-A fix round 1)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest
from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.cards import InferredBasis, QuoteBasis, RowBasis
from factory.model.screening import PassLabel
from factory.services import cards as cards_service
from factory.services.cards import (
    AssertionInput,
    assert_properties,
    card_view,
    create_card,
    effective_card_props,
)
from factory.services.context import Project
from factory.services.document_read import ConversionRef
from factory.services.extraction import live_rows
from factory.services.extraction_agreement import final_rows
from factory.services.properties import merge_properties, unmerge_property
from factory.sources.registry import SourceFactory
from tests.card_helpers import TOP1, CardWorld, approve, cw, quote_basis
from tests.evidence_helpers import frow, run_pass
from tests.extraction_helpers import SESSION_A, SESSION_B, _declare, _extractor, _r
from tests.fulltext_helpers import _screened_full_text_world
from tests.lineage_helpers import ctr_a, ctr_b, lin, screened, world

SourcesFor = Callable[..., Mapping[str, SourceFactory]]
KEY = "rk_0123456789ab"


def _row_item(work: str, key: str, value: str, unit: str | None = "%") -> AssertionInput:
    return AssertionInput(
        property="pr:top1",
        value=value,
        unit=unit,
        basis_kind="row",
        basis=RowBasis(work_id=work, row_key=key, field="value"),
    )


def test_row_basis_is_scoped_to_its_work_in_a_real_extraction_world(
    project: Project,
    agent: Actor,
    agent_other: Actor,
    human: Actor,
    other_session_human: Actor,
    mock_sources: SourcesFor,
) -> None:
    _screened_full_text_world(project, agent, agent_other, human, mock_sources)
    _declare(project, agent)
    run_pass(project, _extractor(SESSION_A, "claude-opus-5-5"), PassLabel.A, lambda _w: [_r()])
    run_pass(project, _extractor(SESSION_B, "claude-sonnet-5-5"), PassLabel.B, lambda _w: [_r()])
    rows = final_rows(project)
    assert len({r.work_id for r in rows}) >= 2
    first, second = rows[0], next(r for r in rows if r.work_id != rows[0].work_id)
    approve(project, agent, other_session_human, TOP1)
    card = create_card(project, agent, "method", first.work_id, "obd")
    ok = assert_properties(
        project, agent, card, [_row_item(first.work_id, first.row_key, "1", None)]
    )
    assert ok.rejected == [] and ok.accepted[0][2] == "stated"
    # the other work's name does not find this work's row
    wrong = assert_properties(
        project, agent, card, [_row_item(second.work_id, first.row_key, "1", None)]
    )
    assert [x.reason for x in wrong.rejected[0][1]] == ["row-unknown"]


def test_shared_row_key_is_resolved_per_work(
    project: Project,
    agent: Actor,
    other_session_human: Actor,
    cw: CardWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = {
        (cw.source, KEY): frow(cw.source, KEY, "A", "82.4"),
        (cw.other, KEY): frow(cw.other, KEY, "B", "70"),
    }
    monkeypatch.setattr(cards_service, "_load_final_rows", lambda _p: rows)
    c1 = create_card(project, agent, "method", cw.source, "obd")
    c2 = create_card(project, agent, "method", cw.other, "obd")
    r1 = assert_properties(project, agent, c1, [_row_item(cw.source, KEY, "82.4")])
    r2 = assert_properties(project, agent, c2, [_row_item(cw.other, KEY, "70")])
    assert r1.rejected == [] and r2.rejected == []  # neither verified against the other's row
    rows[(cw.source, KEY)] = frow(cw.source, KEY, "A", "83.0")  # only the first work's row changes
    assert card_view(project, c1, include_stale=True).assertions[0].stale_reasons == (  # type: ignore[union-attr]
        "row-changed",
    )
    assert card_view(project, c2).assertions[0].effective == "stated"  # type: ignore[union-attr]


def test_definition_is_read_once_per_property_per_call(
    project: Project,
    agent: Actor,
    cw: CardWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = {
        (cw.source, KEY): frow(cw.source, KEY, "A", "82.4"),
        (cw.other, KEY): frow(cw.other, KEY, "B", "82.4"),
    }
    monkeypatch.setattr(cards_service, "_load_final_rows", lambda _p: rows)
    cards = [
        create_card(project, agent, "method", w, "obd") for w in (cw.source, cw.other, cw.idea)
    ]
    for card, work in zip(cards, (cw.source, cw.other, cw.source), strict=True):
        assert_properties(project, agent, card, [_row_item(work, KEY, "82.4")])
    calls: list[str] = []
    real = cards_service.resolve_property

    def counting(p: Project, key: str) -> Any:
        calls.append(key)
        return real(p, key)

    monkeypatch.setattr(cards_service, "resolve_property", counting)
    got = list(effective_card_props(project, ["pr:top1"], {"stated"}))
    assert len(got) == 3
    assert calls.count("pr:top1") == 1


def test_later_merge_or_unmerge_stales_with_definition_changed(
    project: Project, agent: Actor, other_session_human: Actor, cw: CardWorld
) -> None:
    card = create_card(project, agent, "method", cw.source, "obd")
    item = AssertionInput(
        property="pr:attention-kind",
        value="linear",
        basis_kind="quote",
        basis=quote_basis(cw, "s1.p1", "linear attention"),
    )
    assert_properties(project, agent, card, [item])
    from tests.card_helpers import prop

    approve(
        project,
        agent,
        other_session_human,
        prop("pr:attention-2", allowed=["linear", "softmax"], value_aliases={}),
    )
    merge_properties(project, other_session_human, "pr:attention-kind", "pr:attention-2", "same")
    view = card_view(project, card, include_stale=True)
    assert view is not None and view.assertions[0].stale_reasons == ("definition-changed",)
    unmerge_property(project, other_session_human, "pr:attention-kind", "split")
    view = card_view(project, card, include_stale=True)
    assert view is not None and view.assertions[0].stale_reasons == ("definition-changed",)
    assert_properties(project, agent, card, [item])  # asserted again, it is current
    assert card_view(project, card).assertions[0].effective == "stated"  # type: ignore[union-attr]


def test_inferred_supports_are_checked_for_staleness(
    project: Project,
    agent: Actor,
    cw: CardWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = create_card(project, agent, "method", cw.source, "obd")
    item = AssertionInput(
        property="pr:long-sequences",
        value=True,
        basis_kind="inferred",
        basis=InferredBasis(
            note="reasoned", supports=(quote_basis(cw, "s1.p4", "very long sequences degrade"),)
        ),
    )
    assert_properties(project, agent, card, [item])
    monkeypatch.setattr(
        cards_service,
        "default_conversion",
        lambda _p, _w: ConversionRef("doc_other", "cnv_01JZ9Q3K5M7N8P0R2S4T6V8WZZ"),
    )
    view = card_view(project, card, include_inferred=True, include_stale=True)
    assert view is not None and view.assertions[0].stale_reasons == ("document-superseded",)


def test_agent_researcher_assertion_is_not_projected_as_stated(
    project: Project, agent: Actor, cw: CardWorld
) -> None:
    card = create_card(project, agent, "problem", "a task", "obd")
    payload: dict[str, Any] = {
        "assertion_id": "pas_01JZ9Q3K5M7N8P0R2S4T6V8W1C",
        "card_id": card,
        "property": "pr:dense-prediction",
        "value": True,
        "basis_kind": "researcher",
        "status": "stated",
        "vocabulary_version": "V@00000000",
    }
    model = project.catalog.get("card.asserted").payload.model_validate(payload)
    blob = project.blobs.put_json(payload)
    project.record([project.events.make("card.asserted", model, agent, input_blob=blob)])
    project.index.sync()
    with project.index.connect() as conn:
        folded = conn.execute(text("SELECT folded FROM card_assertions")).all()
        props = conn.execute(text("SELECT count(*) FROM card_props")).scalar_one()
    assert folded == [(0,)] and props == 0  # kept, visibly not folded
    view = card_view(project, card, include_inferred=True, include_stale=True)
    assert view is not None and view.assertions == [] and view.hidden_counts == {}
    assert cards_service.list_cards(project, "problem")[0].assertions == 0

"""Inbox event payloads (slice 4a, Design: Events)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from factory.events.catalog import default_catalog
from factory.model.inbox import (
    INBOX_ID_RE,
    Basis,
    InboxLinkAdded,
    InboxLinkResolved,
    InboxLinkWithdrawn,
    InboxRoute,
    ResolveStatus,
)

ITEM = "inb_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
QUERY = "qry_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
RUN = "run_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
DOC = "doc_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
DEV = "dev_01HZX3K4M5N6P7Q8R9S0TVWXYZ"
WORK = "rf:zhou2021-linear-attention-1a2b3c4d"


def added(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "item_id": ITEM,
        "route": "link",
        "link": "https://arxiv.org/abs/2103.14030v2",
        "identifier_kind": "arxiv",
        "identifier_value": "2103.14030",
        "identifier_version": "v2",
        "note": "from a colleague",
        "basis": None,
        "channel": "cli",
    }
    payload.update(overrides)
    return payload


def resolved(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "item_id": ITEM,
        "query_id": QUERY,
        "run_id": RUN,
        "status": "new",
        "work_id": WORK,
        "deviation_id": None,
    }
    payload.update(overrides)
    return payload


def test_id_pattern() -> None:
    assert INBOX_ID_RE == r"^inb_[0-9A-HJKMNP-TV-Z]{26}$"
    with pytest.raises(ValidationError):
        InboxLinkAdded.model_validate(added(item_id="inb_short"))


def test_added_round_trips() -> None:
    event = InboxLinkAdded.model_validate(added())
    assert event.route is InboxRoute.LINK
    assert InboxLinkAdded.model_validate(event.model_dump(mode="json")) == event


def test_note_limit() -> None:
    InboxLinkAdded.model_validate(added(note="x" * 300))
    with pytest.raises(ValidationError):
        InboxLinkAdded.model_validate(added(note="x" * 301))


def test_link_limit() -> None:
    with pytest.raises(ValidationError):
        InboxLinkAdded.model_validate(added(link="x" * 501))
    with pytest.raises(ValidationError):
        InboxLinkAdded.model_validate(added(link=" "))


def test_identifier_kind_closed() -> None:
    with pytest.raises(ValidationError):
        InboxLinkAdded.model_validate(added(identifier_kind="url"))


def test_basis_document_needs_id_and_anchor() -> None:
    Basis(kind="document", document_id=DOC, anchor="s2.p3")
    Basis(kind="knowledge")
    with pytest.raises(ValidationError):
        Basis(kind="document", document_id=DOC)
    with pytest.raises(ValidationError):
        Basis(kind="document", anchor="s2.p3")
    with pytest.raises(ValidationError):
        Basis(kind="knowledge", document_id=DOC, anchor="s2.p3")
    with pytest.raises(ValidationError):
        Basis(kind="document", document_id="cnv_bad", anchor="s2.p3")


def test_added_with_basis() -> None:
    basis = {"kind": "document", "document_id": DOC, "anchor": "b12"}
    event = InboxLinkAdded.model_validate(added(note=None, basis=basis, channel="mcp"))
    assert event.basis == Basis(kind="document", document_id=DOC, anchor="b12")


def test_withdrawn_needs_reason() -> None:
    InboxLinkWithdrawn(item_id=ITEM, reason="duplicate of another link")
    with pytest.raises(ValidationError):
        InboxLinkWithdrawn(item_id=ITEM, reason=" ")


@pytest.mark.parametrize("status", ["new", "in-corpus"])
def test_found_statuses_need_work(status: str) -> None:
    InboxLinkResolved.model_validate(resolved(status=status))
    with pytest.raises(ValidationError):
        InboxLinkResolved.model_validate(resolved(status=status, work_id=None))


@pytest.mark.parametrize("status", ["not-found", "ambiguous", "failed"])
def test_other_statuses_carry_no_work(status: str) -> None:
    InboxLinkResolved.model_validate(resolved(status=status, work_id=None))
    with pytest.raises(ValidationError):
        InboxLinkResolved.model_validate(resolved(status=status))


def test_resolve_status_values() -> None:
    assert [s.value for s in ResolveStatus] == [
        "new",
        "in-corpus",
        "not-found",
        "ambiguous",
        "failed",
    ]


def test_resolved_round_trips_with_deviation() -> None:
    event = InboxLinkResolved.model_validate(resolved(deviation_id=DEV))
    assert InboxLinkResolved.model_validate(event.model_dump(mode="json")) == event


def test_catalog_registers_inbox_events_at_schema_one() -> None:
    catalog = default_catalog()
    expected = {
        "inbox.link_added": InboxLinkAdded,
        "inbox.link_withdrawn": InboxLinkWithdrawn,
        "inbox.link_resolved": InboxLinkResolved,
    }
    for name, payload in expected.items():
        assert catalog.get(name).schema == 1
        assert catalog.get(name).payload is payload

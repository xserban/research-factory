"""Shared fixtures for inbox tests: identifier-keyed sources and capture/resolve shortcuts.

The sources are the REAL OpenAlex and arXiv adapters over a mock transport whose answer depends
on the identifier asked for, so a resolve finds exactly the records the test scripted for it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from factory.events.envelope import Actor
from factory.model.inbox import Basis
from factory.model.protocol import SuppliedLinksPlan
from factory.model.screening import Channel
from factory.services.context import Project
from factory.services.inbox import LinkInput, ResolveOutcome, add_links, resolve_links
from factory.services.protocol import amend_protocol, current_protocol
from factory.sources.arxiv import ArxivSource
from factory.sources.http import PoliteClient
from factory.sources.openalex import OpenAlexSource
from factory.sources.registry import SourceFactory
from tests.helpers import arxiv_atom, openalex_item

KNOWLEDGE = Basis(kind="knowledge")


def link_item(n: int, *, doi: str | None = None, title: str | None = None) -> dict[str, Any]:
    """An OpenAlex record for a linked paper `n` (DOI `10.2000/s<n>` unless given)."""
    return openalex_item(
        title=title or f"Linked paper {n}",
        author="Cy Park",
        published="2021-05-01",
        openalex_id=f"W{7000 + n}",
        doi=doi or f"10.2000/s{n}",
    )


class Keyed:
    """Sources answering per identifier: `openalex` keyed by filter text (`doi:<doi>` or
    `openalex:<id>`), `arxiv` keyed by bare id. `fail` makes every request a 503; `calls`
    counts requests."""

    def __init__(
        self,
        openalex: Mapping[str, Sequence[dict[str, Any]]] | None = None,
        arxiv: Mapping[str, Sequence[tuple[str, str, int, str]]] | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self.openalex = dict(openalex or {})
        self.arxiv = dict(arxiv or {})
        self.fail = fail
        self.calls = 0

    def _openalex(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail:
            return httpx.Response(503, text="unavailable")
        items = list(self.openalex.get(request.url.params.get("filter", ""), []))
        page = {"meta": {"count": len(items), "next_cursor": None}, "results": items}
        return httpx.Response(200, text=json.dumps(page))

    def _arxiv(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail:
            return httpx.Response(503, text="unavailable")
        ids = request.url.params.get("id_list", "").split(",")
        entries = [entry for key in ids for entry in self.arxiv.get(key, [])]
        return httpx.Response(200, text=arxiv_atom(entries))

    def sources(self) -> dict[str, SourceFactory]:
        def polite(handler: Any) -> PoliteClient:
            transport = httpx.MockTransport(handler)
            return PoliteClient(httpx.Client(transport=transport), sleep=lambda _s: None)

        return {
            "openalex": SourceFactory(
                OpenAlexSource.kinds,
                lambda s, c: OpenAlexSource(polite(self._openalex), clock=c, mailto=s.mailto),
            ),
            "arxiv": SourceFactory(
                ArxivSource.kinds,
                lambda s, c: ArxivSource(polite(self._arxiv), clock=c, mailto=s.mailto),
            ),
        }


def raising_sources() -> dict[str, SourceFactory]:
    """Sources whose construction fails: proof that a code path never contacts a source."""

    def boom(*_args: Any) -> Any:
        raise AssertionError("a source was contacted")

    return {
        "openalex": SourceFactory(OpenAlexSource.kinds, boom),
        "arxiv": SourceFactory(ArxivSource.kinds, boom),
    }


def capture(
    project: Project,
    actor: Actor,
    *links: str,
    note: str | None = None,
    basis: Basis | None = None,
    channel: Channel = Channel.CLI,
) -> list[str]:
    """Capture links; every one must be accepted. Returns the item ids."""
    if actor.kind == "agent" and basis is None:
        basis = KNOWLEDGE
    items = [LinkInput(link=link, note=note, basis=basis) for link in links]
    result = add_links(project, actor, items, channel)
    assert result.rejected == [], result.rejected
    return result.written


def resolve(
    project: Project,
    actor: Actor,
    keyed: Keyed,
    *item_ids: str,
    deviation_id: str | None = None,
) -> list[ResolveOutcome]:
    return resolve_links(
        project,
        actor,
        sources=keyed.sources(),
        item_ids=list(item_ids) or None,
        deviation_id=deviation_id,
    )


def accept_supplied(project: Project, agent: Actor, *kinds: str) -> None:
    """Amend the current protocol to accept supplied links from `kinds`."""
    current = current_protocol(project)
    assert current is not None
    plan = SuppliedLinksPlan.model_validate({"accept_from": list(kinds)})
    spec = current.spec.model_copy(update={"supplied_links": plan})
    amend_protocol(project, agent, spec, reason="accept supplied links", semantic=True, effects={})

"""Shared setup for the reference extraction and resolution service tests.

A LaTeXML-style HTML document with an invented bibliography, and scripted lookup sources: the real
OpenAlex and arXiv adapters over `httpx.MockTransport`, answering by the query they receive.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from factory.events.envelope import Actor
from factory.model.work_ids import normalize_doi, normalize_title
from factory.services.context import Project
from factory.services.search import corpus_size
from factory.sources.arxiv import ArxivSource
from factory.sources.http import PoliteClient
from factory.sources.openalex import OpenAlexSource
from factory.sources.registry import SourceFactory
from tests.document_helpers import fetched_document, make_registry, promoted_works, run_convert
from tests.helpers import arxiv_atom

_CITE = re.compile(r"\{cite:(\d+)\}")


def bib_html(entries: Sequence[str], body: Sequence[str]) -> bytes:
    """A LaTeXML article: one section of `body` paragraphs and a bibliography of `entries`.

    `{cite:n}` in a body paragraph becomes an `ltx_cite` link to the n-th bibitem.
    """

    def para(text: str) -> str:
        escaped = html.escape(text)
        linked = _CITE.sub(
            lambda m: (
                f'<cite class="ltx_cite">[<a class="ltx_ref" href="#bib.bib{m.group(1)}">'
                f"{m.group(1)}</a>]</cite>"
            ),
            escaped,
        )
        return f'<div class="ltx_para"><p class="ltx_p">{linked}</p></div>'

    items = "".join(
        f'<li class="ltx_bibitem" id="bib.bib{i}"><span class="ltx_bibblock">'
        f"{html.escape(text)}</span></li>"
        for i, text in enumerate(entries, start=1)
    )
    doc = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>T</title></head>'
        '<body><article class="ltx_document"><h1 class="ltx_title ltx_title_document">T</h1>'
        '<section class="ltx_section" id="S1"><h2 class="ltx_title ltx_title_section">'
        '<span class="ltx_tag ltx_tag_section">1 </span>Introduction</h2>'
        + "".join(para(p) for p in body)
        + '</section><section class="ltx_bibliography">'
        '<h2 class="ltx_title ltx_title_bibliography">References</h2>'
        f'<ul class="ltx_biblist">{items}</ul></section></article></body></html>'
    )
    return doc.encode("utf-8")


def oa_item(
    title: str, author: str, year: int, openalex_id: str, doi: str | None = None
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": f"https://openalex.org/{openalex_id}",
        "display_name": title,
        "publication_date": f"{year}-01-01",
        "type": "article",
        "authorships": [{"author": {"display_name": author}, "institutions": []}],
    }
    if doi is not None:
        item["doi"] = f"https://doi.org/{doi}"
    return item


@dataclass
class Lookups:
    """What the scripted sources know, and the filter / id texts they were asked."""

    openalex: list[dict[str, Any]] = field(default_factory=list)
    arxiv: dict[str, tuple[str, int, str]] = field(default_factory=dict)
    fail_openalex: bool = False
    fail_arxiv: bool = False
    asked: list[str] = field(default_factory=list)

    def sources(self) -> dict[str, SourceFactory]:
        def openalex(request: httpx.Request) -> httpx.Response:
            expression = request.url.params.get("filter", "")
            self.asked.append(f"openalex {expression}")
            if self.fail_openalex:
                raise httpx.ConnectError("scripted failure", request=request)
            results = [i for i in self.openalex if _oa_matches(i, expression)]
            page = {"meta": {"count": len(results), "next_cursor": None}, "results": results}
            return httpx.Response(200, json=page)

        def arxiv(request: httpx.Request) -> httpx.Response:
            ids = request.url.params.get("id_list", "")
            self.asked.append(f"arxiv {ids}")
            if self.fail_arxiv:
                raise httpx.ConnectError("scripted failure", request=request)
            found = [(f"{i}v1", *self.arxiv[i]) for i in ids.split(",") if i and i in self.arxiv]
            return httpx.Response(200, text=arxiv_atom(found))

        def polite(handler: Callable[[httpx.Request], httpx.Response]) -> PoliteClient:
            client = httpx.Client(transport=httpx.MockTransport(handler))
            return PoliteClient(client, sleep=lambda _s: None)

        return {
            "openalex": SourceFactory(
                OpenAlexSource.kinds,
                lambda s, c: OpenAlexSource(polite(openalex), clock=c, mailto=s.mailto),
            ),
            "arxiv": SourceFactory(
                ArxivSource.kinds,
                lambda s, c: ArxivSource(polite(arxiv), clock=c, mailto=s.mailto),
            ),
        }


def _oa_matches(item: dict[str, Any], expression: str) -> bool:
    if expression.startswith("doi:"):
        wanted = {normalize_doi(d) for d in expression[4:].split("|")}
        doi = item.get("doi")
        return doi is not None and normalize_doi(str(doi)) in wanted
    if expression.startswith("title.search:"):
        words = set(normalize_title(expression.split(":", 1)[1]).split())
        title = set(normalize_title(str(item["display_name"])).split())
        return len(words & title) >= 2
    return False


def converted_work(project: Project, entries: Sequence[str], body: Sequence[str]) -> str:
    """The first promoted work, given one converted document with this bibliography."""
    work = promoted_works(project)[0]
    fetched_document(project, work, bib_html(entries, body))
    run_convert(project, make_registry())
    return work


def corpus_works(project: Project) -> int:
    return corpus_size(project)[0]


def second_agent(agent: Actor) -> Actor:
    return agent.model_copy(update={"id": "checker", "session": "01JZ9Q3K5M7N8P0R2S4T6V8W1Z"})

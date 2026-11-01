"""OpenAlex adapter.

Free, CC0, no key. Two properties matter here:

**Cursor paging.** OpenAlex caps offset paging at 10,000 but places no limit on cursor
paging, so this adapter sidesteps the deep-pagination truncation that Stage 03 warns about
rather than having to partition around it.

**Inverted-index abstracts.** Abstracts arrive as `{word: [positions]}` and must be
reconstructed. The reconstruction is lossy in punctuation and is marked as such — it is fine
for screening, and should not be quoted as if it were the author's prose.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx

from factory.clock import Clock
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import (
    Author,
    Dates,
    Identifiers,
    Provenance,
    ProvenanceMethod,
    Venue,
    Work,
    WorkType,
)
from factory.sources.base import PageSink, RawPage, SearchResult, SourceError
from factory.sources.http import PoliteClient

_ENDPOINT = "https://api.openalex.org/works"
_PAGE_SIZE = 200  # the documented maximum

# OpenAlex `type` -> our vocabulary. Unmapped types become OTHER rather than guessing.
_TYPES: dict[str, WorkType] = {
    "article": WorkType.JOURNAL_ARTICLE,
    "review": WorkType.JOURNAL_ARTICLE,
    "letter": WorkType.JOURNAL_ARTICLE,
    "editorial": WorkType.JOURNAL_ARTICLE,
    "preprint": WorkType.PREPRINT,
    "conference-paper": WorkType.CONFERENCE_PAPER,
    # A conference abstract is not a paper: it reports no method and cannot be appraised
    # like one. Mapping it to CONFERENCE_PAPER would quietly promote it.
    "conference-abstract": WorkType.OTHER,
    "book-chapter": WorkType.BOOK_CHAPTER,
    "dissertation": WorkType.THESIS,
    "report": WorkType.TECH_REPORT,
    "standard": WorkType.STANDARD,
    "dataset": WorkType.DATASET,
    "patent": WorkType.PATENT,
    "book": WorkType.BOOK_CHAPTER,
    "paratext": WorkType.OTHER,
}

_METHODS: dict[QueryPurpose, ProvenanceMethod] = {
    QueryPurpose.CHASE: ProvenanceMethod.CITATION_CHASE,
    QueryPurpose.SEED: ProvenanceMethod.SEED_ADMISSION,
}

_SKIPPED = "records skipped (untitled or duplicate within run)"
_TRUNCATED = "truncated by caller-supplied limit"


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """Rebuild prose from OpenAlex's `{word: [positions]}` form."""
    if not inverted:
        return None
    positions = sorted((pos, word) for word, spots in inverted.items() for pos in spots)
    return " ".join(word for _, word in positions) or None


def _strip_url(value: str | None, prefix: str) -> str | None:
    if not value:
        return None
    return value.removeprefix(prefix) or None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _page_range(biblio: dict[str, Any]) -> str | None:
    first, last = biblio.get("first_page"), biblio.get("last_page")
    if first and last:
        return f"{first}-{last}"
    return first or last or None


def _payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SourceError(f"openalex returned unparseable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceError("openalex returned a non-object payload")
    return payload


class OpenAlexSource:
    """Exhaustive cursor-paged retrieval from OpenAlex."""

    name: str = "openalex"
    kinds: frozenset[QueryKind] = frozenset({QueryKind.KEYWORD, QueryKind.FILTER})

    def __init__(
        self,
        http: PoliteClient,
        *,
        clock: Clock,
        mailto: str | None = None,
        page_size: int = _PAGE_SIZE,
    ) -> None:
        # The polite pool wants a contact address. The caller passes it from configuration
        # (Settings.mailto, env FACTORY_MAILTO) — never hardcoded. A repo that ships someone's
        # email address ships it to everyone who clones it.
        self._http = http
        self._clock = clock
        self._mailto = mailto
        self._page_size = page_size

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
        resume_from: str | None = None,
    ) -> SearchResult:
        if spec.kind not in self.kinds:
            raise ValueError(f"openalex does not take {spec.kind.value} queries")

        query_sent = self._filter_expression(spec)
        method = _METHODS.get(spec.purpose, ProvenanceMethod.DATABASE)
        works: list[Work] = []
        seen: set[str] = set()
        skipped = 0
        archived = 0
        reported: int | None = None
        truncated = False
        # OpenAlex resumes from its own opaque cursor, which is exactly why the resume token
        # is a string rather than an offset.
        cursor = resume_from or "*"

        while cursor:
            params: dict[str, str | int] = {
                "filter": query_sent,
                "per-page": self._page_size,
                "cursor": cursor,
            }
            if self._mailto:
                params["mailto"] = self._mailto

            try:
                response = self._http.get(_ENDPOINT, params)
            except httpx.HTTPError as exc:
                return SearchResult(
                    source=self.name,
                    query_sent=query_sent,
                    reported_count=reported,
                    works=works,
                    pages=archived,
                    status=RunStatus.PARTIAL if works else RunStatus.FAILED,
                    skipped=skipped,
                    note=f"{type(exc).__name__}: {exc}",
                    resume_token=cursor,
                )

            # Archive the verbatim response before any of its records are parsed (R-03).
            now = self._clock.now()
            raw_blob = archive(
                RawPage(
                    ordinal=archived,
                    body=response.text,
                    url=str(response.url),
                    fetched_at=now,
                )
            )
            archived += 1

            try:
                payload = _payload(response)
            except SourceError as exc:
                # The page is archived above, so the failure is explained and resumable (R9).
                return SearchResult(
                    source=self.name,
                    query_sent=query_sent,
                    reported_count=reported,
                    works=works,
                    pages=archived,
                    status=RunStatus.PARTIAL if works else RunStatus.FAILED,
                    skipped=skipped,
                    note=f"SourceError: {exc}",
                    resume_token=cursor,
                )
            meta = payload.get("meta") or {}
            if reported is None and isinstance(meta.get("count"), int):
                reported = meta["count"]

            results = payload.get("results") or []
            for item in results:
                work = self.to_work(
                    item,
                    run_id=run_id,
                    query_id=query_id,
                    raw_blob=raw_blob,
                    at=now,
                    method=method,
                )
                if work is None or work.id in seen:
                    skipped += 1
                    continue
                seen.add(work.id)
                works.append(work)

            next_cursor = meta.get("next_cursor") or ""
            if spec.limit is not None and len(works) >= spec.limit:
                truncated = len(works) > spec.limit or bool(next_cursor)
                del works[spec.limit :]
                break

            cursor = next_cursor
            if not results:
                break

        if truncated:
            status, note = RunStatus.PARTIAL, _TRUNCATED
        else:
            status, note = RunStatus.COMPLETE, None
            if reported is not None and len(works) < reported:
                note = f"{skipped} {_SKIPPED}"
                if len(works) + skipped != reported:
                    note += "; source count differs"

        return SearchResult(
            source=self.name,
            query_sent=query_sent,
            reported_count=reported,
            works=works,
            pages=archived,
            status=status,
            skipped=skipped,
            note=note,
        )

    @staticmethod
    def _filter_expression(spec: QuerySpec) -> str:
        if spec.kind is QueryKind.KEYWORD:
            expression = f"title_and_abstract.search:{spec.text}"
        else:
            # FILTER text is sent verbatim: `doi:a|b`, `openalex:W1|W2`, `cites:W1`.
            expression = spec.text
        return expression + "".join(f",{key}:{value}" for key, value in spec.filters.items())

    def to_work(
        self,
        item: dict[str, Any],
        *,
        run_id: str,
        query_id: str,
        raw_blob: str,
        at: datetime,
        method: ProvenanceMethod,
    ) -> Work | None:
        title = item.get("display_name") or item.get("title")
        if not title:
            return None  # OpenAlex carries a tail of untitled records; they cannot be screened

        ids = item.get("ids") or {}
        location = item.get("primary_location") or {}
        venue_source = location.get("source") or {}
        biblio = item.get("biblio") or {}

        return Work.build(
            title=title,
            abstract=reconstruct_abstract(item.get("abstract_inverted_index")),
            language=item.get("language"),
            type=_TYPES.get(item.get("type") or "", WorkType.OTHER),
            authors=[
                Author(
                    name=name,
                    orcid=_strip_url(author.get("orcid"), "https://orcid.org/"),
                    affiliation=next(
                        (i.get("display_name") for i in (entry.get("institutions") or [])), None
                    ),
                )
                for entry in (item.get("authorships") or [])
                if (author := entry.get("author") or {}) and (name := author.get("display_name"))
            ],
            identifiers=Identifiers(
                openalex=_strip_url(item.get("id"), "https://openalex.org/"),
                doi=_strip_url(item.get("doi"), "https://doi.org/"),
                pmid=_strip_url(ids.get("pmid"), "https://pubmed.ncbi.nlm.nih.gov/"),
                pmcid=_strip_url(ids.get("pmcid"), "https://www.ncbi.nlm.nih.gov/pmc/articles/"),
                url=location.get("landing_page_url"),
            ),
            venue=Venue(
                name=venue_source.get("display_name"),
                publisher=venue_source.get("host_organization_name"),
                volume=biblio.get("volume"),
                issue=biblio.get("issue"),
                pages=_page_range(biblio),
            ),
            dates=Dates(
                published=_parse_date(item.get("publication_date")),
                retrieved=at,
            ),
            subjects=[
                name for topic in (item.get("topics") or []) if (name := topic.get("display_name"))
            ],
            cited_by_count=item.get("cited_by_count"),
            retracted=bool(item.get("is_retracted")),
            provenance=[
                Provenance(
                    source=self.name,
                    run_id=run_id,
                    query_id=query_id,
                    at=at,
                    raw_blob=raw_blob,
                    raw_ref=_strip_url(item.get("id"), "https://openalex.org/"),
                    method=method,
                )
            ],
        )

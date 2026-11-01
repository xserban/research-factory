"""arXiv adapter.

arXiv is the only source that serves LaTeX source alongside metadata, which later makes it the
highest-quality full-text route we have. Here it does metadata only.

The API is Atom XML over https://export.arxiv.org/api/query, takes no key, and asks for roughly
one request every three seconds. That delay is not negotiable politeness — arXiv throttles hard,
and an adapter that gets the project blocked has cost more than it saved. The interval, the 429
handling and the retries live in `PoliteClient`, not here.
"""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree

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
from factory.model.work_ids import normalize_arxiv
from factory.sources.base import PageSink, RawPage, SearchResult, SourceError
from factory.sources.http import PoliteClient

_ENDPOINT = "https://export.arxiv.org/api/query"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

# arXiv caps a single response at 2000 and recommends far less; 100 pages politely.
_PAGE_SIZE = 100

_METHODS: dict[QueryPurpose, ProvenanceMethod] = {
    QueryPurpose.CHASE: ProvenanceMethod.CITATION_CHASE,
    QueryPurpose.SEED: ProvenanceMethod.SEED_ADMISSION,
}

_SKIPPED = "records skipped (untitled or duplicate within run)"
_TRUNCATED = "truncated by caller-supplied limit"


def _text(node: ElementTree.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    return " ".join(node.text.split())


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _split_ids(text: str) -> list[str]:
    return [part for raw in text.split(",") if (part := raw.strip())]


def _feed(body: str) -> tuple[int | None, list[ElementTree.Element]]:
    """The reported total and the raw entries of one Atom response."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise SourceError(f"arxiv returned unparseable XML: {exc}") from exc

    reported = None
    total = root.find("opensearch:totalResults", _NS)
    if total is not None and total.text and total.text.isdigit():
        reported = int(total.text)
    return reported, root.findall("atom:entry", _NS)


class ArxivSource:
    """Exhaustive, paged retrieval from arXiv."""

    name: str = "arxiv"
    kinds: frozenset[QueryKind] = frozenset({QueryKind.KEYWORD, QueryKind.ID_LIST})

    def __init__(self, http: PoliteClient, *, clock: Clock, page_size: int = _PAGE_SIZE) -> None:
        self._http = http
        self._clock = clock
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
        """Page through every result for `spec`.

        Keyword queries are ordered by submission date — never by relevance, which is not
        reproducible across runs and would make paging skip or repeat records. Ascending is the
        default because it is stable as new papers appear. **But ascending plus `limit` returns
        the oldest n**, which is rarely what a probe wants, so a capped keyword query flips to
        descending and gets the newest n.

        ID_LIST queries name specific arXiv ids and are fetched through `id_list` in batches.
        Seeds are named by id, and resolving them through the search endpoint is unreliable —
        arXiv phrase matching breaks on hyphens and colons, so a seed can appear "missing" when
        the search syntax was simply wrong. `id_list` removes that failure mode entirely.

        `limit` makes the run `partial` with a note, so a capped search and a complete one are
        never indistinguishable afterwards. Each raw response goes to `archive` before any of its
        entries are parsed.
        """
        if spec.kind not in self.kinds:
            raise ValueError(f"arxiv does not take {spec.kind.value} queries")
        ids = _split_ids(spec.text) if spec.kind is QueryKind.ID_LIST else []
        if spec.kind is QueryKind.ID_LIST and not ids:
            raise ValueError("an id_list query must name at least one arXiv id")

        query_sent = ",".join(ids) if spec.kind is QueryKind.ID_LIST else spec.text
        method = _METHODS.get(spec.purpose, ProvenanceMethod.DATABASE)
        works: list[Work] = []
        seen: set[str] = set()
        skipped = 0
        pages = 0
        reported: int | None = None
        truncated = False
        start = int(resume_from) if resume_from else 0

        while True:
            try:
                response = self._http.get(_ENDPOINT, self._params(spec, ids, start))
            except httpx.HTTPError as exc:
                return SearchResult(
                    source=self.name,
                    query_sent=query_sent,
                    reported_count=reported,
                    works=works,
                    pages=pages,
                    status=RunStatus.PARTIAL if works else RunStatus.FAILED,
                    skipped=skipped,
                    note=f"{type(exc).__name__}: {exc}",
                    resume_token=str(start),
                )

            # Archive the verbatim response before any of its records are parsed (R-03).
            # Ordinals are offsets over the page size, so a resumed run continues the sequence.
            now = self._clock.now()
            raw_blob = archive(
                RawPage(
                    ordinal=start // self._page_size,
                    body=response.text,
                    url=str(response.url),
                    fetched_at=now,
                )
            )
            pages += 1

            page_total, entries = _feed(response.text)
            if page_total is not None:
                if spec.kind is QueryKind.ID_LIST:
                    # Each batch reports the ids it matched; the run's total is their sum.
                    reported = (reported or 0) + page_total
                elif reported is None:
                    reported = page_total

            for entry in entries:
                work = self._to_work(
                    entry,
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

            exhausted = self._exhausted(spec, ids, start, len(entries))
            if spec.limit is not None and len(works) >= spec.limit:
                # Enforce the cap here rather than trusting the server to honour max_results.
                # A limit that is requested but not applied produces a result set that looks
                # complete and is not, which is the one outcome this adapter must never produce.
                truncated = len(works) > spec.limit or not exhausted
                del works[spec.limit :]
                break
            if exhausted:
                break
            start += self._page_size

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
            pages=pages,
            status=status,
            skipped=skipped,
            note=note,
        )

    def _params(self, spec: QuerySpec, ids: list[str], start: int) -> dict[str, str | int]:
        if spec.kind is QueryKind.ID_LIST:
            # For id lists, `start` is an index into the ids, and the token is that index.
            batch = ids[start : start + self._page_size]
            return {"id_list": ",".join(batch), "max_results": len(batch), "start": 0}
        return {
            "search_query": spec.text,
            "start": start,
            # Always the full page, with any caller limit applied to the results afterwards.
            # Requesting a shrinking final page would break the offset-to-ordinal mapping.
            "max_results": self._page_size,
            "sortBy": "submittedDate",
            "sortOrder": "descending" if spec.limit is not None else "ascending",
        }

    def _exhausted(self, spec: QuerySpec, ids: list[str], start: int, entries: int) -> bool:
        if spec.kind is QueryKind.ID_LIST:
            return start + self._page_size >= len(ids)
        return entries < self._page_size

    def matching(
        self,
        ids: list[str],
        text: str,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
    ) -> set[str]:
        """Which of `ids` the query actually retrieves — measured, not sampled.

        arXiv intersects `id_list` with `search_query`, so seed recall can be established
        exactly in one request no matter how large the result set is. This matters more than it
        sounds: recall computed over a truncated sample is not recall. A query matching 69,000
        records, sampled 900 deep, will report 0% recall for a perfectly good strategy purely
        because the seeds were not in the slice — which is a property of the sampling, not of
        the query.
        """
        found: set[str] = set()
        for start in range(0, len(ids), self._page_size):
            batch = ids[start : start + self._page_size]
            response = self._http.get(
                _ENDPOINT,
                {
                    "id_list": ",".join(batch),
                    "search_query": text,
                    "max_results": len(batch),
                    "start": 0,
                },
            )
            now = self._clock.now()
            raw_blob = archive(
                RawPage(
                    ordinal=start // self._page_size,
                    body=response.text,
                    url=str(response.url),
                    fetched_at=now,
                )
            )
            _, entries = _feed(response.text)
            works = (
                self._to_work(
                    entry,
                    run_id=run_id,
                    query_id=query_id,
                    raw_blob=raw_blob,
                    at=now,
                    method=ProvenanceMethod.DATABASE,
                )
                for entry in entries
            )
            found.update(
                normalize_arxiv(w.identifiers.arxiv) for w in works if w and w.identifiers.arxiv
            )
        return found

    def _to_work(
        self,
        entry: ElementTree.Element,
        *,
        run_id: str,
        query_id: str,
        raw_blob: str,
        at: datetime,
        method: ProvenanceMethod,
    ) -> Work | None:
        title = _text(entry.find("atom:title", _NS))
        raw_id = _text(entry.find("atom:id", _NS))
        if not title or not raw_id:
            return None  # cannot be screened without a title or an identifier

        published = _parse_date(_text(entry.find("atom:published", _NS)))
        updated = _parse_date(_text(entry.find("atom:updated", _NS)))
        journal_ref = _text(entry.find("arxiv:journal_ref", _NS))

        return Work.build(
            title=title,
            abstract=_text(entry.find("atom:summary", _NS)),
            # A journal_ref means arXiv knows it was published; the preprint is still the
            # record we hold, and Stage 03 dedup is what merges it with the published version.
            type=WorkType.PREPRINT,
            authors=[
                Author(name=name)
                for name in (
                    _text(a.find("atom:name", _NS)) for a in entry.findall("atom:author", _NS)
                )
                if name
            ],
            identifiers=Identifiers(
                arxiv=raw_id,
                doi=_text(entry.find("arxiv:doi", _NS)),
                url=raw_id,
            ),
            dates=Dates(
                published=published.date() if published else None,
                updated=updated.date() if updated else None,
                retrieved=at,
            ),
            subjects=[
                term
                for c in entry.findall("atom:category", _NS)
                if (term := c.get("term")) is not None
            ],
            venue=Venue(name=journal_ref) if journal_ref else None,
            provenance=[
                Provenance(
                    source=self.name,
                    run_id=run_id,
                    query_id=query_id,
                    at=at,
                    raw_blob=raw_blob,
                    raw_ref=raw_id,
                    method=method,
                )
            ],
        )

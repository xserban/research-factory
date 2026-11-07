"""arXiv adapter.

arXiv is the only source that serves LaTeX source alongside metadata, which later makes it the
highest-quality full-text route we have. Here it does metadata only.

The API is Atom XML over https://export.arxiv.org/api/query, takes no key, and asks for roughly
one request every three seconds. That delay is not negotiable politeness — arXiv throttles hard,
and an adapter that gets the project blocked has cost more than it saved. The interval, the 429
handling and the retries live in `PoliteClient`, not here.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import ClassVar
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
from factory.sources.base import PageSink, RawPage, SearchResult, SourceError, StatusRecord
from factory.sources.http import PoliteClient, redact

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
    QueryPurpose.SUPPLIED: ProvenanceMethod.SUPPLIED,
    QueryPurpose.IMPORT: ProvenanceMethod.LIBRARY_IMPORT,
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


def _requested_ids(text: str) -> list[tuple[str, str]]:
    """The distinct arXiv ids named in an id_list query, in the order given, as (raw, key).

    `raw` is the id as the caller wrote it (stripped, first occurrence) and is what gets sent to
    arXiv: an old-style id such as `hep-th/9901001` must keep its archive prefix on the wire.
    `key` is `normalize_arxiv(raw)`, used only to decide whether two requests are the same id,
    so a version pin and a bare id collapse, and `hep-th/9901001` stays distinct from
    `cond-mat/9901001`. `reported_count` for an id_list is the number of distinct keys.
    """
    first: dict[str, str] = {}
    for part in text.split(","):
        raw = part.strip()
        if raw:
            first.setdefault(normalize_arxiv(raw), raw)
    return [(raw, key) for key, raw in first.items()]


def _id_list_note(requested: list[tuple[str, str]], works: list[Work], skipped: int) -> str | None:
    """Name the requested ids that did not come back, so an unresolved id is never silent."""
    returned = {normalize_arxiv(w.identifiers.arxiv) for w in works if w.identifiers.arxiv}
    missing = [raw for raw, key in requested if key not in returned]
    if not missing:
        return None
    note = f"{len(missing)} requested id(s) not returned: {', '.join(missing[:10])}"
    if len(missing) > 10:
        note += f" (+{len(missing) - 10} more)"
    if skipped:
        note += f"; {skipped} {_SKIPPED}"
    return note


def _entry_arxiv_key(entry: ElementTree.Element) -> str | None:
    """The normalised arXiv id of an entry that could be screened, or None if it is untitled."""
    title = _text(entry.find("atom:title", _NS))
    raw_id = _text(entry.find("atom:id", _NS))
    if not title or not raw_id:
        return None
    return normalize_arxiv(raw_id)


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
    window_filter: ClassVar[bool] = True
    """Honours `filters["listed_since"]` (YYYY-MM-DD): arXiv's `submittedDate` is when the record
    was first listed, which is what a watch window needs (slice 4b, ruling 2)."""

    def __init__(
        self,
        http: PoliteClient,
        *,
        clock: Clock,
        mailto: str | None = None,
        page_size: int = _PAGE_SIZE,
    ) -> None:
        # arXiv is never sent the address, but it travels in the User-Agent, so anything built
        # from a request or an exception is redacted before it is archived or noted.
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
        if spec.purpose is QueryPurpose.STATUS:
            return self._run_status(spec, archive)
        is_ids = spec.kind is QueryKind.ID_LIST
        requested = _requested_ids(spec.text) if is_ids else []
        ids = [raw for raw, _ in requested]
        if is_ids and not ids:
            raise ValueError("an id_list query must name at least one arXiv id")

        query_sent = ",".join(ids) if is_ids else _search_query(spec)
        method = _METHODS.get(spec.purpose, ProvenanceMethod.DATABASE)
        works: list[Work] = []
        seen: set[str] = set()
        skipped = 0
        pages = 0
        # For an id_list the source's own total is not the measure: what was asked for is.
        reported: int | None = len(ids) if is_ids else None
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
                    note=redact(f"{type(exc).__name__}: {exc}", self._mailto),
                    resume_token=str(start),
                )

            # Archive the verbatim response before any of its records are parsed (R-03).
            # Ordinals are offsets over the page size, so a resumed run continues the sequence.
            now = self._clock.now()
            raw_blob = archive(
                RawPage(
                    ordinal=start // self._page_size,
                    body=response.text,
                    url=redact(str(response.url), self._mailto),
                    fetched_at=now,
                )
            )
            pages += 1

            try:
                page_total, entries = _feed(response.text)
            except SourceError as exc:
                # The page is archived above, so the failure is explained and resumable (R9).
                return SearchResult(
                    source=self.name,
                    query_sent=query_sent,
                    reported_count=reported,
                    works=works,
                    pages=pages,
                    status=RunStatus.PARTIAL if works else RunStatus.FAILED,
                    skipped=skipped,
                    note=redact(f"SourceError: {exc}", self._mailto),
                    resume_token=str(start),
                )
            if not is_ids and reported is None:
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
            if is_ids:
                note = _id_list_note(requested, works, skipped)
            elif reported is not None and len(works) < reported:
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

    def _run_status(self, spec: QuerySpec, archive: PageSink) -> SearchResult:
        """A status lookup: `id_list` of bare ids (the latest version answers), no works.

        One record per returned entry carries the versioned id, and the published DOI and
        `journal_ref` when arXiv gives them. Each response is archived before it is parsed.
        """
        if spec.kind is not QueryKind.ID_LIST:
            raise ValueError("an arxiv status query is an id_list")
        requested = _requested_ids(spec.text)
        ids = [raw for raw, _ in requested]
        if not ids:
            raise ValueError("an id_list query must name at least one arXiv id")
        records: list[StatusRecord] = []
        pages = 0
        for start in range(0, len(ids), self._page_size):
            batch = ids[start : start + self._page_size]
            params: dict[str, str | int] = {
                "id_list": ",".join(batch),
                "max_results": len(batch),
                "start": 0,
            }
            note: str | None = None
            entries: list[ElementTree.Element] = []
            try:
                response = self._http.get(_ENDPOINT, params)
            except httpx.HTTPError as exc:
                note = redact(f"{type(exc).__name__}: {exc}", self._mailto)
            else:
                archive(
                    RawPage(
                        ordinal=start // self._page_size,
                        body=response.text,
                        url=redact(str(response.url), self._mailto),
                        fetched_at=self._clock.now(),
                    )
                )
                pages += 1
                try:
                    _, entries = _feed(response.text)
                except SourceError as exc:
                    note = redact(f"SourceError: {exc}", self._mailto)
            if note is not None:
                return SearchResult(
                    source=self.name,
                    query_sent=",".join(ids),
                    reported_count=None,
                    works=[],
                    pages=pages,
                    status=RunStatus.PARTIAL if records else RunStatus.FAILED,
                    note=note,
                    resume_token=str(start),
                    status_records=tuple(records),
                )
            for entry in entries:
                record = _status_record(entry)
                if record is not None:
                    records.append(record)
        returned = {normalize_arxiv(r.source_version) for r in records if r.source_version}
        missing = [raw for raw, key in requested if key not in returned]
        note = (
            f"{len(missing)} requested id(s) not returned: {', '.join(missing[:10])}"
            if missing
            else None
        )
        return SearchResult(
            source=self.name,
            query_sent=",".join(ids),
            reported_count=None,
            works=[],
            pages=pages,
            status=RunStatus.COMPLETE,
            note=note,
            status_records=tuple(records),
        )

    def _params(self, spec: QuerySpec, ids: list[str], start: int) -> dict[str, str | int]:
        if spec.kind is QueryKind.ID_LIST:
            # For id lists, `start` is an index into the ids, and the token is that index.
            batch = ids[start : start + self._page_size]
            return {"id_list": ",".join(batch), "max_results": len(batch), "start": 0}
        return {
            "search_query": _search_query(spec),
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

    def count(self, spec: QuerySpec, *, archive: PageSink) -> int | None:
        """arXiv's own total for a keyword query, from one request that carries one record.

        `max_results=1` costs one small response rather than a page, even for a query matching
        69,000 records. `max_results=0` would carry none, but the API answers it with a 500
        (observed 2026-11-07), so it is not used.
        """
        self._require_keyword(spec)
        _, reported, _ = self._probe_get(
            {"search_query": spec.text, "max_results": 1, "start": 0},
            ordinal=0,
            archive=archive,
        )
        return reported

    def matching(self, ids: Sequence[str], spec: QuerySpec, *, archive: PageSink) -> set[str]:
        """Which of `ids` the query actually retrieves — measured, not sampled.

        arXiv intersects `id_list` with `search_query`, so seed recall can be established
        exactly in one request no matter how large the result set is. This matters more than it
        sounds: recall computed over a truncated sample is not recall. A query matching 69,000
        records, sampled 900 deep, will report 0% recall for a perfectly good strategy purely
        because the seeds were not in the slice — which is a property of the sampling, not of
        the query.

        Ids are compared by their normalised form (a version pin and a bare id are the same
        paper) and returned in the form they were given.
        """
        self._require_keyword(spec)
        given = {normalize_arxiv(i): i for i in ids}
        found: set[str] = set()
        for start in range(0, len(ids), self._page_size):
            batch = ids[start : start + self._page_size]
            _, _, entries = self._probe_get(
                {
                    "id_list": ",".join(batch),
                    "search_query": spec.text,
                    "max_results": len(batch),
                    "start": 0,
                },
                ordinal=start // self._page_size,
                archive=archive,
            )
            for entry in entries:
                key = _entry_arxiv_key(entry)
                if key is not None and key in given:
                    found.add(given[key])
        return found

    @staticmethod
    def _require_keyword(spec: QuerySpec) -> None:
        if spec.kind is not QueryKind.KEYWORD:
            raise ValueError(f"arxiv probes take keyword queries, not {spec.kind.value}")

    def _probe_get(
        self, params: dict[str, str | int], *, ordinal: int, archive: PageSink
    ) -> tuple[str, int | None, list[ElementTree.Element]]:
        """One archived probe request: the blob ref, the reported total and the entries.

        Transport failures become `SourceError`, with the contact address redacted. The response
        is archived before it is parsed, as in a run.
        """
        try:
            response = self._http.get(_ENDPOINT, params)
        except httpx.HTTPError as exc:
            raise SourceError(redact(f"{type(exc).__name__}: {exc}", self._mailto)) from exc
        raw_blob = archive(
            RawPage(
                ordinal=ordinal,
                body=response.text,
                url=redact(str(response.url), self._mailto),
                fetched_at=self._clock.now(),
            )
        )
        reported, entries = _feed(response.text)
        return raw_blob, reported, entries

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


def _status_record(entry: ElementTree.Element) -> StatusRecord | None:
    """The version (and published-version link) an arXiv entry states, or None if it has no id."""
    raw_id = _text(entry.find("atom:id", _NS))
    if not raw_id:
        return None
    doi = _text(entry.find("arxiv:doi", _NS))
    journal_ref = _text(entry.find("arxiv:journal_ref", _NS))
    return StatusRecord(
        target=Identifiers(arxiv=raw_id),
        kind="version",
        source_version=raw_id.rsplit("/abs/", 1)[-1],
        linked=Identifiers(doi=doi) if doi else None,
        venue=journal_ref,
    )


def _search_query(spec: QuerySpec) -> str:
    """The query text as sent: with `listed_since`, an open-ended `submittedDate` clause."""
    since = spec.filters.get("listed_since")
    if since is None:
        return spec.text
    stamp = date.fromisoformat(since).strftime("%Y%m%d")
    return f"({spec.text}) AND submittedDate:[{stamp}0000 TO 999912312359]"

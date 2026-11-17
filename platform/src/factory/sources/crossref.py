"""Crossref adapter: notice lookups (slice 4b, living-C) and works lookups (IDEA-89).

Works lookups (PROBE purpose) serve reference resolution without OpenAlex: a FILTER query
`doi:<a>|<b>|...` is sent as `/works?filter=doi:a,doi:b`, and `title.search:<query>` as
`/works?query.bibliographic=<query>`. Each response is one archived page, parsed into `Work`s.

Crossref records which later items declare themselves a retraction, correction, withdrawal or
expression of concern of a DOI (`update-to`). The query is a `filter` expression such as
`updates:10.1000/x`; the response is parsed into `StatusRecord`s, never into `Work`s: a status
lookup yields no corpus works. Only STATUS and PROBE purposes are accepted.

Update types other than the four notice kinds (and `reinstatement`) are ignored and counted in
the run's note, so an unmapped type is never silent.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any

import httpx

from factory.clock import Clock
from factory.model.notices import NoticeKind
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
from factory.model.work_ids import normalize_doi
from factory.sources.base import (
    BUDGET_STOP_NOTE,
    PageSink,
    RawPage,
    SearchResult,
    SourceError,
    StatusRecord,
    budget_spent,
    report_progress,
)
from factory.sources.http import PoliteClient, redact

NAME = "crossref"
_ENDPOINT = "https://api.crossref.org/works"
_ROWS = 1000
_TITLE_ROWS = 10  # rows of a title lookup when the query states no limit
_DOI_PREFIX = "doi:"
_TITLE_PREFIX = "title.search:"
_TRUNCATED = "truncated by caller-supplied limit"

# Crossref `type` -> our vocabulary. Unmapped types become OTHER rather than guessing.
_TYPES: dict[str, WorkType] = {
    "journal-article": WorkType.JOURNAL_ARTICLE,
    "proceedings-article": WorkType.CONFERENCE_PAPER,
    "book-chapter": WorkType.BOOK_CHAPTER,
    "book": WorkType.BOOK_CHAPTER,
    "monograph": WorkType.BOOK_CHAPTER,
    "dissertation": WorkType.THESIS,
    "report": WorkType.TECH_REPORT,
    "standard": WorkType.STANDARD,
    "dataset": WorkType.DATASET,
    "posted-content": WorkType.PREPRINT,
}
_DATE_FIELDS = ("issued", "published", "published-print", "published-online", "posted")

# Crossref `update-to[].type` -> notice kind. Anything else is ignored and counted.
_KINDS: dict[str, NoticeKind] = {
    "retraction": NoticeKind.RETRACTION,
    "withdrawal": NoticeKind.WITHDRAWAL,
    "correction": NoticeKind.CORRECTION,
    "expression_of_concern": NoticeKind.EXPRESSION_OF_CONCERN,
    "reinstatement": NoticeKind.REINSTATEMENT,
}


def _date_parts(node: Any) -> date | None:
    """The date of a Crossref `{"date-parts": [[y, m, d]]}` value; a missing part is 1."""
    if not isinstance(node, dict):
        return None
    parts = node.get("date-parts")
    if not (isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]):
        return None
    numbers = parts[0]
    if not all(isinstance(n, int) for n in numbers[:3]):
        return None
    year, month, day = [*numbers, 1, 1][:3]
    try:
        return date(year, month, day)
    except ValueError:
        return None


_TAG = re.compile(r"<[^>]+>")


def _plain(text: str | None) -> str | None:
    """`text` without JATS/HTML tags and with entities decoded (Crossref titles carry both)."""
    if text is None:
        return None
    return " ".join(html.unescape(_TAG.sub("", text)).split()) or None


def _first(value: Any) -> str | None:
    """The first non-empty string of a Crossref list-of-strings field (or a bare string)."""
    if isinstance(value, str):
        return " ".join(value.split()) or None
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str) and entry.strip():
                return " ".join(entry.split())
    return None


def _author_name(author: Any) -> str | None:
    """Display name `Given Family` (the surname is the last token), or an organisation's name."""
    if not isinstance(author, dict):
        return None
    family, given = author.get("family"), author.get("given")
    parts = [p.strip() for p in (given, family) if isinstance(p, str) and p.strip()]
    if parts:
        return " ".join(parts)
    name = author.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else None


def _orcid(author: Any) -> str | None:
    value = author.get("ORCID") if isinstance(author, dict) else None
    if not isinstance(value, str) or not value:
        return None
    return value.rsplit("/", 1)[-1] or None


def _published(item: dict[str, Any]) -> date | None:
    """The first date among `issued`, `published`, `published-print`, `published-online` and
    `posted` (a preprint's own date), a missing month or day being 1; None without a year."""
    for name in _DATE_FIELDS:
        found = _date_parts(item.get(name))
        if found is not None:
            return found
    return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_work(
    item: Any,
    *,
    run_id: str,
    query_id: str,
    raw_blob: str,
    at: datetime,
    method: ProvenanceMethod = ProvenanceMethod.DATABASE,
) -> Work | None:
    """One Crossref work item as a `Work`, or None when it is not an object or has no title.

    Authors carry `Given Family` display names (the family name is the last token); the year
    comes from `issued`, else the other publication dates, else `posted`; the venue is the
    first `container-title`; both lose markup tags and entities. Crossref's JATS abstract is not
    carried.
    """
    if not isinstance(item, dict):
        return None
    title = _plain(_first(item.get("title")))
    if not title:
        return None
    doi = _text(item.get("DOI"))
    cited = item.get("is-referenced-by-count")
    return Work.build(
        title=title,
        type=_TYPES.get(str(item.get("type") or ""), WorkType.OTHER),
        authors=[
            Author(name=name, orcid=_orcid(a))
            for a in (item.get("author") or [])
            if (name := _author_name(a))
        ],
        identifiers=Identifiers(doi=normalize_doi(doi) if doi else None),
        venue=Venue(
            name=_plain(_first(item.get("container-title"))),
            publisher=_text(item.get("publisher")),
            volume=_text(item.get("volume")),
            issue=_text(item.get("issue")),
            pages=_text(item.get("page")),
        ),
        dates=Dates(published=_published(item), retrieved=at),
        cited_by_count=cited if isinstance(cited, int) else None,
        provenance=[
            Provenance(
                source=NAME,
                run_id=run_id,
                query_id=query_id,
                at=at,
                raw_blob=raw_blob,
                raw_ref=normalize_doi(doi) if doi else None,
                method=method,
            )
        ],
    )


def _message(body: str) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise SourceError(f"crossref returned unparseable JSON: {exc}") from exc
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict):
        raise SourceError("crossref returned no message object")
    return message


def parse_notices(items: list[Any]) -> tuple[list[StatusRecord], list[str]]:
    """Notice records of the response items, and the ignored update types (one per update)."""
    records: list[StatusRecord] = []
    ignored: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        notice_doi = item.get("DOI")
        issued = _date_parts(item.get("issued"))
        for update in item.get("update-to") or []:
            if not isinstance(update, dict) or not update.get("DOI"):
                continue
            type_ = str(update.get("type") or "")
            kind = _KINDS.get(type_)
            if kind is None:
                ignored.append(type_ or "untyped")
                continue
            records.append(
                StatusRecord(
                    target=Identifiers(doi=str(update["DOI"])),
                    kind="notice",
                    notice_kind=kind,
                    notice_doi=str(notice_doi) if notice_doi else None,
                    notice_date=_date_parts(update.get("updated")) or issued,
                )
            )
    return records, ignored


class CrossrefSource:
    """Notice lookups through the Crossref REST API (polite pool, cursor paging)."""

    name: str = NAME
    kinds: frozenset[QueryKind] = frozenset({QueryKind.FILTER})

    def __init__(self, http: PoliteClient, *, clock: Clock, mailto: str | None = None) -> None:
        self._http = http
        self._clock = clock
        self._mailto = mailto

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
        resume_from: str | None = None,
    ) -> SearchResult:
        if spec.purpose not in (QueryPurpose.STATUS, QueryPurpose.PROBE):
            raise ValueError("crossref takes status and probe queries only")
        if spec.kind not in self.kinds:
            raise ValueError(f"crossref does not take {spec.kind.value} queries")
        if spec.purpose is QueryPurpose.PROBE:
            return self._run_lookup(spec, run_id=run_id, query_id=query_id, archive=archive)
        records: list[StatusRecord] = []
        ignored: list[str] = []
        cursor = resume_from or "*"
        archived = 0
        seen_items = 0
        while True:
            if budget_spent(archive):
                return self._result(
                    spec, records, ignored, archived, RunStatus.PARTIAL, BUDGET_STOP_NOTE, cursor
                )
            params: dict[str, str | int] = {"filter": spec.text, "rows": _ROWS, "cursor": cursor}
            if self._mailto:
                params["mailto"] = self._mailto
            try:
                response = self._http.get(_ENDPOINT, params)
            except httpx.HTTPError as exc:
                return self._result(
                    spec,
                    records,
                    ignored,
                    archived,
                    RunStatus.PARTIAL if records else RunStatus.FAILED,
                    redact(f"{type(exc).__name__}: {exc}", self._mailto),
                    cursor,
                )
            archive(
                RawPage(
                    ordinal=archived,
                    body=response.text,
                    url=redact(str(response.url), self._mailto),
                    fetched_at=self._clock.now(),
                )
            )
            archived += 1
            try:
                message = _message(response.text)
            except SourceError as exc:
                return self._result(
                    spec,
                    records,
                    ignored,
                    archived,
                    RunStatus.PARTIAL if records else RunStatus.FAILED,
                    f"SourceError: {exc}",
                    cursor,
                )
            items = message.get("items") or []
            page_records, page_ignored = parse_notices(items)
            records.extend(page_records)
            ignored.extend(page_ignored)
            seen_items += len(items)
            total = message.get("total-results")
            report_progress(
                archive, seen_items, total if isinstance(total, int) else None, archived
            )
            next_cursor = message.get("next-cursor")
            if (
                not items
                or not isinstance(next_cursor, str)
                or (isinstance(total, int) and seen_items >= total)
            ):
                break
            cursor = next_cursor
        return self._result(spec, records, ignored, archived, RunStatus.COMPLETE, None, None)

    def _run_lookup(
        self, spec: QuerySpec, *, run_id: str, query_id: str, archive: PageSink
    ) -> SearchResult:
        """A works lookup: one request, its page archived before it is parsed.

        `doi:a|b` asks for exactly those DOIs (rows = the number asked); `title.search:q` asks
        for the best matches of `q` (rows = the query's limit, else 10). A lookup is never
        paged: more matches than a stated limit is a truncation, noted as such.
        """
        text = spec.text
        params: dict[str, str | int]
        if text.startswith(_DOI_PREFIX):
            dois = [d.strip() for d in text[len(_DOI_PREFIX) :].split("|") if d.strip()]
            if not dois:
                raise ValueError("crossref doi lookup names no DOI")
            params = {
                "filter": ",".join(f"doi:{d}" for d in dois),
                "rows": min(len(dois), _ROWS),
            }
        elif text.startswith(_TITLE_PREFIX):
            query = text[len(_TITLE_PREFIX) :].strip()
            if not query:
                raise ValueError("crossref title lookup names no title")
            params = {"query.bibliographic": query, "rows": spec.limit or _TITLE_ROWS}
        else:
            raise ValueError("crossref lookups are `doi:<a>|<b>` or `title.search:<query>`")
        if budget_spent(archive):
            return self._lookup_result(spec, [], 0, 0, RunStatus.PARTIAL, BUDGET_STOP_NOTE)
        if self._mailto:
            params["mailto"] = self._mailto
        try:
            response = self._http.get(_ENDPOINT, params)
        except httpx.HTTPError as exc:
            note = redact(f"{type(exc).__name__}: {exc}", self._mailto)
            return self._lookup_result(spec, [], 0, 0, RunStatus.FAILED, note)
        now = self._clock.now()
        raw_blob = archive(
            RawPage(
                ordinal=0,
                body=response.text,
                url=redact(str(response.url), self._mailto),
                fetched_at=now,
            )
        )
        try:
            message = _message(response.text)
        except SourceError as exc:
            return self._lookup_result(spec, [], 0, 1, RunStatus.FAILED, f"SourceError: {exc}")
        works: list[Work] = []
        seen: set[str] = set()
        skipped = 0
        for item in message.get("items") or []:
            work = parse_work(item, run_id=run_id, query_id=query_id, raw_blob=raw_blob, at=now)
            if work is None or work.id in seen:
                skipped += 1
                continue
            seen.add(work.id)
            works.append(work)
        total = message.get("total-results")
        if spec.limit is not None and isinstance(total, int) and total > int(params["rows"]):
            return self._lookup_result(spec, works, skipped, 1, RunStatus.PARTIAL, _TRUNCATED)
        skip_note = (
            f"{skipped} records skipped (untitled or duplicate within run)" if skipped else None
        )
        return self._lookup_result(spec, works, skipped, 1, RunStatus.COMPLETE, skip_note)

    def _lookup_result(
        self,
        spec: QuerySpec,
        works: list[Work],
        skipped: int,
        pages: int,
        status: RunStatus,
        note: str | None,
    ) -> SearchResult:
        return SearchResult(
            source=self.name,
            query_sent=spec.text,
            reported_count=None,
            works=works,
            pages=pages,
            status=status,
            skipped=skipped,
            note=note,
        )

    def _result(
        self,
        spec: QuerySpec,
        records: list[StatusRecord],
        ignored: list[str],
        pages: int,
        status: RunStatus,
        note: str | None,
        resume_token: str | None,
    ) -> SearchResult:
        if ignored and note is None:
            kinds = ", ".join(sorted(set(ignored)))
            note = f"{len(ignored)} update(s) of other types ignored: {kinds}"
        return SearchResult(
            source=self.name,
            query_sent=spec.text,
            reported_count=None,
            works=[],
            pages=pages,
            status=status,
            note=note,
            resume_token=resume_token,
            status_records=tuple(records),
        )

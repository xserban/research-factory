"""Crossref adapter for notice lookups (slice 4b, living-C).

Crossref records which later items declare themselves a retraction, correction, withdrawal or
expression of concern of a DOI (`update-to`). The query is a `filter` expression such as
`updates:10.1000/x`; the response is parsed into `StatusRecord`s, never into `Work`s: a status
lookup yields no corpus works. Only STATUS-purpose queries are accepted.

Update types other than the four notice kinds (and `reinstatement`) are ignored and counted in
the run's note, so an unmapped type is never silent.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from factory.clock import Clock
from factory.model.notices import NoticeKind
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import Identifiers
from factory.sources.base import (
    BUDGET_STOP_NOTE,
    PageSink,
    RawPage,
    SearchResult,
    SourceError,
    StatusRecord,
    budget_spent,
)
from factory.sources.http import PoliteClient, redact

NAME = "crossref"
_ENDPOINT = "https://api.crossref.org/works"
_ROWS = 1000

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
        if spec.purpose is not QueryPurpose.STATUS:
            raise ValueError("crossref takes status queries only")
        if spec.kind not in self.kinds:
            raise ValueError(f"crossref does not take {spec.kind.value} queries")
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
            next_cursor = message.get("next-cursor")
            if (
                not items
                or not isinstance(next_cursor, str)
                or (isinstance(total, int) and seen_items >= total)
            ):
                break
            cursor = next_cursor
        return self._result(spec, records, ignored, archived, RunStatus.COMPLETE, None, None)

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

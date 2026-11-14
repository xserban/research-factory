"""Raw records that never became works, and each run's shortfall against what its source reported.

Read-only. A search run archives every raw response (`search.page_archived`, read back through the
`pages` table) before parsing it, and records each parsed record in `provenance` with the raw blob
of its page. A raw record of an archived page that has no parsed provenance row in its own run is
listed with a reason:

- `untitled`: the source gave no title, so the adapter cannot screen it;
- `duplicate-within-run`: an earlier titled record of the same run had the same native id;
- `unparsed`: a titled record with no parsed row in its run and page (no native id, or the
  adapter dropped it for another reason).

Native ids are arXiv ids (normalised, as the adapter normalises them) and OpenAlex W-ids. Only
arXiv and OpenAlex pages are read; a run of another source lists no raw records. Probe and status
lookups are outside the search and are excluded, as `search_report` excludes them.
"""

import json
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text

from factory.model.base import StrictModel
from factory.model.search import QueryPurpose
from factory.model.work_ids import normalize_arxiv
from factory.services.context import Project
from factory.sources.arxiv import _NS, _feed, _text
from factory.sources.base import SourceError
from factory.sources.openalex import _strip_url

SkipReason = Literal["untitled", "duplicate-within-run", "unparsed"]

_OPENALEX_PREFIX = "https://openalex.org/"


class SkippedRecord(StrictModel):
    """One raw record of an archived page that did not produce a parsed record in its run."""

    run_id: str
    query_id: str
    source: str
    native_id: str | None
    """The arXiv id (normalised) or OpenAlex W-id; None when the source gave none."""
    title: str | None
    """The title as the source gave it; None when the source gave none."""
    reason: SkipReason


class RunStatusNote(StrictModel):
    """One run of a query, as its status and note recorded it."""

    run_id: str
    status: str
    reported_count: int | None
    retrieved_count: int
    skipped: int
    note: str | None


class RunGap(StrictModel):
    """How far one query's runs fell short of the total its source reported.

    `retrieved` is the sum over the query's runs, which resume one another (a resumed run starts
    at the cursor where the last one stopped, so no record is counted twice). `reported` is the
    last run's reported count that is not None. `gap` is `reported - retrieved`, or None when no
    run reported a total.
    """

    query_id: str
    source: str
    reported: int | None
    retrieved: int
    gap: int | None
    runs: tuple[RunStatusNote, ...]


@dataclass(frozen=True, slots=True)
class _RawEntry:
    """A record as a source's page gives it, before the adapter's own checks."""

    title: str | None
    native_id: str | None


def _arxiv_entries(body: str) -> list[_RawEntry]:
    """The entries of one arXiv Atom page, parsed by the adapter's own feed reader."""
    try:
        _, entries = _feed(body)
    except SourceError:
        return []  # an unparseable page yields no entries; the run itself records the failure
    found: list[_RawEntry] = []
    for entry in entries:
        title = _text(entry.find("atom:title", _NS)) or None
        raw_id = _text(entry.find("atom:id", _NS))
        found.append(_RawEntry(title, normalize_arxiv(raw_id) if raw_id else None))
    return found


def _openalex_entries(body: str) -> list[_RawEntry]:
    """The results of one OpenAlex JSON page, with the title rule of `OpenAlexSource.to_work`."""
    try:
        payload: Any = json.loads(body)
    except ValueError:
        return []
    if not isinstance(payload, dict):
        return []
    found: list[_RawEntry] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = item.get("display_name") or item.get("title") or None
        found.append(_RawEntry(title, _strip_url(item.get("id"), _OPENALEX_PREFIX)))
    return found


_PARSERS = {"arxiv": _arxiv_entries, "openalex": _openalex_entries}


@dataclass(frozen=True, slots=True)
class _Run:
    run_id: str
    query_id: str
    source: str
    status: str
    reported_count: int | None
    retrieved_count: int
    skipped: int
    note: str | None


def _search_runs(project: Project) -> list[_Run]:
    """Every run of a search-type query, in run order (probe and status lookups excluded)."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.run_id, r.query_id, r.source, r.status, r.reported_count, "
                "r.retrieved_count, r.skipped, r.note FROM runs r "
                "JOIN queries q ON q.query_id = r.query_id "
                "WHERE q.purpose NOT IN (:probe, :status) ORDER BY r.run_id"
            ),
            {"probe": QueryPurpose.PROBE.value, "status": QueryPurpose.STATUS.value},
        ).all()
    return [
        _Run(
            run_id=str(run_id),
            query_id=str(query_id),
            source=str(source),
            status=str(status),
            reported_count=None if reported is None else int(reported),
            retrieved_count=int(retrieved or 0),
            skipped=int(skipped or 0),
            note=None if note is None else str(note),
        )
        for run_id, query_id, source, status, reported, retrieved, skipped, note in rows
    ]


def _archived_pages(project: Project) -> dict[str, list[str]]:
    """The raw blob refs of each run's archived search pages, in page order."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT pg.run_id, pg.raw_blob FROM pages pg "
                "JOIN runs r ON r.run_id = pg.run_id "
                "JOIN queries q ON q.query_id = r.query_id "
                "WHERE q.purpose NOT IN (:probe, :status) ORDER BY pg.run_id, pg.ordinal"
            ),
            {"probe": QueryPurpose.PROBE.value, "status": QueryPurpose.STATUS.value},
        ).all()
    pages: dict[str, list[str]] = {}
    for run_id, blob in rows:
        pages.setdefault(str(run_id), []).append(str(blob))
    return pages


def _parsed_keys(project: Project) -> set[tuple[str, str, str]]:
    """(run_id, raw_blob, native id) of every parsed provenance row of a search run.

    The native id is normalised as the adapter's `raw_ref` is: arXiv ids are stored as the URL
    form and are normalised here; OpenAlex refs are already W-ids.
    """
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT p.run_id, p.raw_blob, p.raw_ref, p.source FROM provenance p "
                "JOIN queries q ON q.query_id = p.query_id "
                "WHERE q.purpose NOT IN (:probe, :status) AND p.raw_blob IS NOT NULL "
                "AND p.raw_ref IS NOT NULL"
            ),
            {"probe": QueryPurpose.PROBE.value, "status": QueryPurpose.STATUS.value},
        ).all()
    keys: set[tuple[str, str, str]] = set()
    for run_id, blob, ref, source in rows:
        native = normalize_arxiv(str(ref)) if source == "arxiv" else str(ref)
        keys.add((str(run_id), str(blob), native))
    return keys


def skipped_records(project: Project) -> list[SkippedRecord]:
    """The raw records of every search run that did not produce a parsed record, in run order.

    Records are classified in page order within each run, so a record that repeats an earlier
    titled record of the same run is `duplicate-within-run` and not `unparsed`. A titled record
    with a native id that has a parsed row for its own run and page is not listed. Raises
    `BlobNotFoundError` or `BlobIntegrityError` if an archived page is missing or altered.
    """
    runs = _search_runs(project)
    pages = _archived_pages(project)
    parsed = _parsed_keys(project)
    out: list[SkippedRecord] = []
    for run in runs:
        parser = _PARSERS.get(run.source)
        if parser is None:
            continue
        seen: set[str] = set()
        for blob in pages.get(run.run_id, []):
            body = project.blobs.get(blob).decode("utf-8")
            for entry in parser(body):
                if entry.title is None:
                    out.append(_skip(run, entry, "untitled"))
                    continue
                if entry.native_id is not None and entry.native_id in seen:
                    out.append(_skip(run, entry, "duplicate-within-run"))
                    continue
                if entry.native_id is not None:
                    seen.add(entry.native_id)
                    if (run.run_id, blob, entry.native_id) in parsed:
                        continue
                out.append(_skip(run, entry, "unparsed"))
    return out


def _skip(run: _Run, entry: _RawEntry, reason: SkipReason) -> SkippedRecord:
    return SkippedRecord(
        run_id=run.run_id,
        query_id=run.query_id,
        source=run.source,
        native_id=entry.native_id,
        title=entry.title,
        reason=reason,
    )


def run_gaps(project: Project) -> list[RunGap]:
    """Per search query: reported against retrieved, with each run's status and note.

    Queries are listed in id order; a query appears only if it has at least one search run.
    """
    by_query: dict[str, list[_Run]] = {}
    for run in _search_runs(project):
        by_query.setdefault(run.query_id, []).append(run)
    return [_gap(query_id, runs) for query_id, runs in sorted(by_query.items())]


def _gap(query_id: str, runs: list[_Run]) -> RunGap:
    reported_values = [run.reported_count for run in runs if run.reported_count is not None]
    reported = reported_values[-1] if reported_values else None
    retrieved = sum(run.retrieved_count for run in runs)
    return RunGap(
        query_id=query_id,
        source=runs[0].source,
        reported=reported,
        retrieved=retrieved,
        gap=None if reported is None else reported - retrieved,
        runs=tuple(
            RunStatusNote(
                run_id=run.run_id,
                status=run.status,
                reported_count=run.reported_count,
                retrieved_count=run.retrieved_count,
                skipped=run.skipped,
                note=run.note,
            )
            for run in runs
        ),
    )


__all__ = ["RunGap", "RunStatusNote", "SkipReason", "SkippedRecord", "run_gaps", "skipped_records"]

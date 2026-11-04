"""The offline `importlist` source: works rebuilt from stored import records (slice 3d, ruling 22).

An imported record that no OpenAlex or arXiv identifier query can name is admitted through this
pseudo-source. The query text is a comma-separated list of record keys (`imp_<ULID>:<ordinal>`),
the reader returns the stored records those keys name, and each becomes a work of type `other`
built from the record's allow-listed fields only (title, first-author surname, year, DOI, arXiv
id, URL, venue). Abstract, tags and the export's other fields are not used.

Invariants:
- No network: the raw page is the canonical JSON of the records' fields and `record_sha256`,
  sorted by key, archived before any work is built.
- The work's id is `work_id()` of the title, first-author surname, year, DOI and arXiv id. Its
  provenance is `source = importlist`, method `library-import`, `raw_ref` = the record key.
- A year, when the record has one, is stored as 1 January of that year; only the year is claimed.
- A key the reader does not return (no record, or a record without a title) is a shortfall, named
  in the note; a malformed or repeated key is a `SourceError`, so the run is recorded as failed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime

from factory.canonical import canonical_json
from factory.clock import Clock
from factory.model.imports import RECORD_KEY_RE
from factory.model.search import QueryKind, QuerySpec, RunStatus
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

NAME = "importlist"
_KEY = re.compile(RECORD_KEY_RE)


@dataclass(frozen=True)
class ImportlistEntry:
    """One stored record as the source serves it: allow-listed fields and hash, never the raw
    text of the export."""

    key: str
    title: str
    first_author: str | None
    year: int | None
    doi: str | None
    arxiv: str | None
    url: str | None
    venue: str | None
    record_sha256: str


ImportlistReader = Callable[[Sequence[str]], Mapping[str, ImportlistEntry]]
"""Returns the stored, titled records among the given keys, keyed by record key."""


def entry_keys(text: str) -> list[str]:
    """The record keys of a query text, in order. Raises `SourceError` when one is malformed or
    repeated, or when there is none."""
    keys = [part.strip() for part in text.split(",") if part.strip()]
    if not keys:
        raise SourceError("an importlist query names at least one record key")
    bad = [k for k in keys if _KEY.match(k) is None]
    if bad:
        raise SourceError(f"not a record key: {bad[0][:60]!r}")
    if len(set(keys)) != len(keys):
        raise SourceError("an importlist query names each record key once")
    return keys


class ImportlistSource:
    """Serves stored import records as works. Offline; one page per run."""

    name = NAME
    kinds: frozenset[QueryKind] = frozenset({QueryKind.ID_LIST})

    def __init__(self, read: ImportlistReader, *, clock: Clock) -> None:
        self._read = read
        self._clock = clock

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
            raise SourceError(f"importlist does not take {spec.kind.value} queries")
        keys = entry_keys(spec.text)
        found = self._read(keys)
        entries = sorted((found[k] for k in keys if k in found), key=lambda e: e.key)
        now = self._clock.now()
        query_sent = ",".join(keys)
        body = canonical_json({"entries": [asdict(e) for e in entries]}).decode()
        raw_blob = archive(
            RawPage(ordinal=0, body=body, url=f"{NAME}:{query_sent}", fetched_at=now)
        )
        works = [_work(e, run_id, query_id, raw_blob, now) for e in entries]
        missing = [k for k in keys if k not in found]
        note = (
            f"{len(missing)} record keys name no stored titled record: " + ", ".join(missing)
            if missing
            else None
        )
        return SearchResult(
            source=NAME,
            query_sent=query_sent,
            reported_count=len(keys),
            works=works,
            pages=1,
            status=RunStatus.COMPLETE,
            note=note,
        )


def _work(entry: ImportlistEntry, run_id: str, query_id: str, raw_blob: str, at: datetime) -> Work:
    return Work.build(
        title=entry.title,
        type=WorkType.OTHER,
        authors=[Author(name=entry.first_author)] if entry.first_author else [],
        identifiers=Identifiers(doi=entry.doi, arxiv=entry.arxiv, url=entry.url),
        dates=Dates(published=date(entry.year, 1, 1)) if entry.year else Dates(),
        venue=Venue(name=entry.venue) if entry.venue else None,
        provenance=[
            Provenance(
                source=NAME,
                run_id=run_id,
                query_id=query_id,
                at=at,
                raw_blob=raw_blob,
                raw_ref=entry.key,
                method=ProvenanceMethod.LIBRARY_IMPORT,
            )
        ],
    )


__all__ = ["NAME", "ImportlistEntry", "ImportlistReader", "ImportlistSource", "entry_keys"]

"""The offline `reflist` source: works rebuilt from stored reference entries (slice 3a, ruling 8).

A reference entry resolved to a `no-source-record` work names a work that no source returned. A
snowball round retrieves it through this pseudo-source: the query text is a comma-separated list
of entry keys (`rex_<ULID>:<ordinal>`), the reader returns the stored entries those keys name, and
each becomes a work of type `other` built from the entry's parsed fields only.

Invariants:
- No network and no document text: the raw page is the canonical JSON of the entries' parsed
  fields and `entry_sha256` (ruling 14), sorted by key, archived before any work is built.
- The work's id is `work_id()` of the parsed title, first-author surname, year, DOI and arXiv id,
  the id the resolution recorded for the link. Its provenance is `source = reflist`,
  method `citation-chase`, `raw_ref` = the entry key.
- The year is stored as 1 January of that year (`Dates` has no year-only field); only the year is
  claimed.
- A key the reader does not return is a shortfall, named in the note; a malformed or repeated
  key is a `SourceError`, so the run is recorded as failed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime

from factory.canonical import canonical_json
from factory.clock import Clock
from factory.model.references import ENTRY_KEY_RE
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

NAME = "reflist"
_KEY = re.compile(ENTRY_KEY_RE)
_METHODS = {
    QueryPurpose.CHASE: ProvenanceMethod.CITATION_CHASE,
}


@dataclass(frozen=True)
class ReflistEntry:
    """One stored entry as the source serves it: parsed fields and hash, never the raw text."""

    key: str
    title: str
    first_author: str | None
    year: int
    doi: str | None
    arxiv: str | None
    url: str | None
    venue: str | None
    entry_sha256: str


EntryReader = Callable[[Sequence[str]], Mapping[str, ReflistEntry]]
"""Returns the stored `no-source-record` entries among the given keys, keyed by entry key."""


def entry_keys(text: str) -> list[str]:
    """The entry keys of a query text, in order. Raises `SourceError` when one is malformed or
    repeated, or when there is none."""
    keys = [part.strip() for part in text.split(",") if part.strip()]
    if not keys:
        raise SourceError("a reflist query names at least one entry key")
    bad = [k for k in keys if _KEY.match(k) is None]
    if bad:
        raise SourceError(f"not an entry key: {bad[0][:60]!r}")
    if len(set(keys)) != len(keys):
        raise SourceError("a reflist query names each entry key once")
    return keys


class ReflistSource:
    """Serves stored `no-source-record` entries as works. Offline; one page per run."""

    name = NAME
    kinds: frozenset[QueryKind] = frozenset({QueryKind.ID_LIST})

    def __init__(self, read: EntryReader, *, clock: Clock) -> None:
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
            raise SourceError(f"reflist does not take {spec.kind.value} queries")
        keys = entry_keys(spec.text)
        found = self._read(keys)
        entries = sorted((found[k] for k in keys if k in found), key=lambda e: e.key)
        now = self._clock.now()
        query_sent = ",".join(keys)
        body = canonical_json({"entries": [asdict(e) for e in entries]}).decode()
        raw_blob = archive(
            RawPage(ordinal=0, body=body, url=f"{NAME}:{query_sent}", fetched_at=now)
        )
        method = _METHODS.get(spec.purpose, ProvenanceMethod.DATABASE)
        works = [_work(e, run_id, query_id, raw_blob, method, now) for e in entries]
        missing = [k for k in keys if k not in found]
        note = (
            f"{len(missing)} entry keys name no stored no-source-record entry: "
            + ", ".join(missing)
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


def _work(
    entry: ReflistEntry,
    run_id: str,
    query_id: str,
    raw_blob: str,
    method: ProvenanceMethod,
    at: datetime,
) -> Work:
    return Work.build(
        title=entry.title,
        type=WorkType.OTHER,
        authors=[Author(name=entry.first_author)] if entry.first_author else [],
        identifiers=Identifiers(doi=entry.doi, arxiv=entry.arxiv, url=entry.url),
        dates=Dates(published=date(entry.year, 1, 1)),
        venue=Venue(name=entry.venue) if entry.venue else None,
        provenance=[
            Provenance(
                source=NAME,
                run_id=run_id,
                query_id=query_id,
                at=at,
                raw_blob=raw_blob,
                raw_ref=entry.key,
                method=method,
            )
        ],
    )


__all__ = ["NAME", "EntryReader", "ReflistEntry", "ReflistSource", "entry_keys"]

"""The offline `stored` source: works re-served from the records the project already holds
(decision 135).

A reference link resolved to a work that a lookup returned earlier; the stored record is the best
a round can get for it, so a backward round retrieves it through this pseudo-source instead of
asking a network source again. The query text is a comma-separated list of work ids; the reader
returns the stored `Work` of each id.

Invariants:
- No network: the raw page is the canonical JSON of the stored records, sorted by id, archived
  before any work is built.
- A served work keeps its id and every content field; its provenance is replaced by one row:
  `source = stored`, method `citation-chase`, `raw_ref` = the work id. Earlier provenance stays
  in the index under the runs that made it.
- An id the reader does not return is a shortfall, named in the note; a malformed or repeated id
  is a `SourceError`, so the run is recorded as failed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence

from factory.canonical import canonical_json
from factory.clock import Clock
from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.model.work import Provenance, ProvenanceMethod, Work
from factory.model.work_ids import WORK_ID_RE
from factory.sources.base import PageSink, RawPage, SearchResult, SourceError

NAME = "stored"
_ID = re.compile(WORK_ID_RE)

WorkReader = Callable[[Sequence[str]], Mapping[str, Work]]
"""Returns the stored works among the given ids, keyed by work id."""


def work_ids(text: str) -> list[str]:
    """The work ids of a query text, in order. Raises `SourceError` when one is malformed or
    repeated, or when there is none."""
    ids = [part.strip() for part in text.split(",") if part.strip()]
    if not ids:
        raise SourceError("a stored query names at least one work id")
    bad = [i for i in ids if _ID.match(i) is None]
    if bad:
        raise SourceError(f"not a work id: {bad[0][:60]!r}")
    if len(set(ids)) != len(ids):
        raise SourceError("a stored query names each work id once")
    return ids


class StoredSource:
    """Serves stored works again. Offline; one page per run."""

    name = NAME
    kinds: frozenset[QueryKind] = frozenset({QueryKind.ID_LIST})

    def __init__(self, read: WorkReader, *, clock: Clock) -> None:
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
            raise SourceError(f"stored does not take {spec.kind.value} queries")
        ids = work_ids(spec.text)
        found = self._read(ids)
        works = sorted((found[i] for i in ids if i in found), key=lambda w: w.id)
        now = self._clock.now()
        query_sent = ",".join(ids)
        body = canonical_json({"works": [w.model_dump(mode="json") for w in works]}).decode()
        raw_blob = archive(
            RawPage(ordinal=0, body=body, url=f"{NAME}:{query_sent}", fetched_at=now)
        )
        served = [
            w.model_copy(
                update={
                    "provenance": [
                        Provenance(
                            source=NAME,
                            run_id=run_id,
                            query_id=query_id,
                            at=now,
                            raw_blob=raw_blob,
                            raw_ref=w.id,
                            method=ProvenanceMethod.CITATION_CHASE,
                        )
                    ]
                }
            )
            for w in works
        ]
        missing = [i for i in ids if i not in found]
        note = (
            f"{len(missing)} work ids name no stored work: " + ", ".join(missing)
            if missing
            else None
        )
        return SearchResult(
            source=NAME,
            query_sent=query_sent,
            reported_count=len(ids),
            works=served,
            pages=1,
            status=RunStatus.COMPLETE,
            note=note,
        )


__all__ = ["NAME", "StoredSource", "WorkReader", "work_ids"]

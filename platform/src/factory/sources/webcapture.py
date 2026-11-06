"""The offline `webcapture` source: a work from the stored fields of one captured page.

A capture (`services.grey.capture_url`) fetches a page once, puts its bytes in the project
library and registers a `grey`-purpose query whose filters carry the facts of the fetch. This
source turns those facts into one work of type `other`, with provenance method `grey-website`.
No network; the page's bytes never pass through it.

Invariants:
- The query text is the page URL; the filters hold `source_id`, `title`, `sha256`, `captured_at`,
  `status` and `headers` (canonical JSON of a few response headers). A missing filter is a
  `SourceError`.
- The archived raw page is the canonical JSON of the URL and those facts, so the capture's hash,
  timestamp and headers are in the event log while the bytes stay in the library (decision 39).
- The work's id is derived from its title alone (no authors, no year), so a repeat capture of the
  same page under the same title is the same work with a new version of its document.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import JsonValue

from factory.canonical import canonical_json
from factory.clock import Clock
from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.model.work import (
    Dates,
    Identifiers,
    Provenance,
    ProvenanceMethod,
    Work,
    WorkType,
)
from factory.sources.base import PageSink, RawPage, SearchResult, SourceError

NAME = "webcapture"
REQUIRED_FILTERS = ("source_id", "title", "sha256", "captured_at", "status", "headers")


class WebCaptureSource:
    """Serves one captured page as a work. Offline; one page per run."""

    name = NAME
    kinds: frozenset[QueryKind] = frozenset({QueryKind.FILTER})

    def __init__(self, *, clock: Clock) -> None:
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
            raise SourceError(f"webcapture does not take {spec.kind.value} queries")
        missing = [key for key in REQUIRED_FILTERS if not spec.filters.get(key)]
        if missing:
            raise SourceError(f"a capture query needs the filters {', '.join(missing)}")
        try:
            captured = datetime.fromisoformat(spec.filters["captured_at"])
        except ValueError as exc:
            raise SourceError("captured_at is not an ISO timestamp") from exc
        now = self._clock.now()
        facts: dict[str, JsonValue] = {
            "url": spec.text,
            **{key: spec.filters[key] for key in REQUIRED_FILTERS},
        }
        raw_blob = archive(
            RawPage(ordinal=0, body=canonical_json(facts).decode(), url=spec.text, fetched_at=now)
        )
        work = Work.build(
            title=spec.filters["title"],
            type=WorkType.OTHER,
            identifiers=Identifiers(url=spec.text),
            dates=Dates(retrieved=captured),
            provenance=[
                Provenance(
                    source=NAME,
                    run_id=run_id,
                    query_id=query_id,
                    at=now,
                    raw_blob=raw_blob,
                    raw_ref=spec.filters["sha256"],
                    method=ProvenanceMethod.GREY_WEBSITE,
                )
            ],
        )
        return SearchResult(
            source=NAME,
            query_sent=spec.text,
            reported_count=1,
            works=[work],
            pages=1,
            status=RunStatus.COMPLETE,
        )

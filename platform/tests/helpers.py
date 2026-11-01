import json
from datetime import UTC, date, datetime
from typing import Any

from factory.model.base import StrictModel
from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.model.work import Author, Dates, Identifiers, Provenance, Work
from factory.sources.base import PageSink, RawPage, SearchResult, SourceError

T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
SESSION = "01JZ9Q3K5M7N8P0R2S4T6V8W0X"
S2 = "01JZ9Q3K5M7N8P0R2S4T6V8W0Y"
S3 = "01JZ9Q3K5M7N8P0R2S4T6V8W0Z"


class Demo(StrictModel):
    n: int


FAKE_PAGES: list[list[dict[str, Any]]] = [
    [
        {"title": "Linear attention", "authors": ["Ada Zhou"], "year": 2024},
        {"title": "Sparse attention", "authors": ["Ben Li"], "year": 2023},
    ],
    [{"title": "Efficient transformers", "authors": ["Cai Wu"], "year": 2022}],
]


class FakeSource:
    """A scripted `Source` for search tests.

    Each page is a list of record dicts. Every page is archived through the sink before its
    records are parsed, exactly as the real adapters do. Scripted behaviour:

    - `fail_after=n`: page `n` fails with a soft error, reported as a PARTIAL/FAILED result
      with a resume token (what the HTTP adapters do on a transport error).
    - `parse_fail_at=n`: page `n` is archived, then fails to parse. As the fixed adapters do
      (R9), that is a PARTIAL/FAILED result with a `SourceError` note and the page's resume token;
      the records of earlier pages are kept.
    - `raise_at=n`: page `n` raises `raise_error` (default `SourceError`) before it is archived.
      Adapters do not raise this way any more; it exercises the service's safety net.
    - `reported`: the count the source claims; a smaller delivery is explained in the note.
    - Duplicate records within the run are skipped, as the real adapters skip them.
    - `resume_from` is the page index to start from, as a resume token would be.
    """

    name: str = "fake"
    kinds: frozenset[QueryKind] = frozenset({QueryKind.KEYWORD})

    def __init__(
        self,
        pages: list[list[dict[str, Any]]],
        *,
        reported: int | None = None,
        fail_after: int | None = None,
        parse_fail_at: int | None = None,
        raise_at: int | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self._pages = pages
        self._reported = reported
        self._fail_after = fail_after
        self._parse_fail_at = parse_fail_at
        self._raise_at = raise_at
        self._raise_error = raise_error or SourceError("fake page unreadable")

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
        resume_from: str | None = None,
    ) -> SearchResult:
        works: list[Work] = []
        seen: set[str] = set()
        skipped = 0
        archived = 0
        for ordinal in range(int(resume_from or 0), len(self._pages)):
            if ordinal == self._fail_after:
                return self._result(
                    works,
                    archived,
                    skipped,
                    note="FakeNetworkError: connection reset",
                    resume_token=str(ordinal),
                )
            if ordinal == self._raise_at:
                raise self._raise_error
            ref = archive(
                RawPage(
                    ordinal=ordinal,
                    body=json.dumps(self._pages[ordinal]),
                    url=f"fake://pages/{ordinal}",
                    fetched_at=T0,
                )
            )
            archived += 1
            if ordinal == self._parse_fail_at:
                return self._result(
                    works,
                    archived,
                    skipped,
                    note="SourceError: fake page unreadable",
                    resume_token=str(ordinal),
                )
            for record in self._pages[ordinal]:
                work = _work(record, run_id=run_id, query_id=query_id, raw_blob=ref)
                if work.id in seen:
                    skipped += 1
                    continue
                seen.add(work.id)
                works.append(work)

        note = None
        if skipped:
            note = f"{skipped} duplicate record(s) skipped"
        if self._reported is not None and len(works) < self._reported:
            missing = f"{self._reported - len(works)} of {self._reported} reported not delivered"
            note = f"{note}; {missing}" if note else missing
        return self._result(works, archived, skipped, note=note)

    def _result(
        self,
        works: list[Work],
        archived: int,
        skipped: int,
        *,
        note: str | None,
        resume_token: str | None = None,
    ) -> SearchResult:
        status = RunStatus.COMPLETE
        if resume_token is not None:
            status = RunStatus.PARTIAL if works else RunStatus.FAILED
        return SearchResult(
            source=self.name,
            query_sent="fake",
            reported_count=self._reported,
            works=works,
            pages=archived,
            status=status,
            skipped=skipped,
            note=note,
            resume_token=resume_token,
        )


def _work(record: dict[str, Any], *, run_id: str, query_id: str, raw_blob: str) -> Work:
    year = record.get("year")
    return Work.build(
        title=str(record["title"]),
        authors=[Author(name=name) for name in record.get("authors", [])],
        identifiers=Identifiers(
            doi=record.get("doi"), arxiv=record.get("arxiv"), openalex=record.get("openalex")
        ),
        dates=Dates(published=date(year, 1, 1)) if year else Dates(),
        abstract=record.get("abstract"),
        provenance=[
            Provenance(
                source="fake",
                run_id=run_id,
                query_id=query_id,
                at=T0,
                raw_blob=raw_blob,
            )
        ],
    )

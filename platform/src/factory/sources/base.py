"""The contract every source adapter implements.

Adapters fetch and parse. They never filter, rank, score, or truncate — that is the Stage 03
prohibition, and it is enforced here by the shape of the return value: an adapter reports what
the source *said* it had alongside what it actually delivered, so a shortfall is visible in the
record rather than absorbed silently.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol, runtime_checkable

from factory.errors import FactoryError
from factory.model.notices import NoticeKind
from factory.model.search import QueryKind, QuerySpec, RunStatus
from factory.model.work import Identifiers, Work
from factory.model.work_ids import arxiv_id_from_doi, normalize_arxiv, normalize_doi

_RESULT_STATUSES = frozenset({RunStatus.COMPLETE, RunStatus.PARTIAL, RunStatus.FAILED})


class SourceError(FactoryError):
    """An adapter could not complete a request."""


@dataclass(frozen=True, slots=True)
class RawPage:
    """One verbatim response, archived before parsing."""

    ordinal: int
    body: str
    url: str
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class StatusRecord:
    """One fact a status lookup read from a source's metadata about a known work.

    `target` carries every identifier the response gave for the work it is about (the service
    matches it to a corpus work). A `notice` record has a `notice_kind`, and may have the notice's
    own DOI and date; a `version` record has a `source_version` (a newer arXiv version, as the
    versioned id) and/or a `linked` published version (identifiers and venue).
    """

    target: Identifiers
    kind: Literal["notice", "version"]
    notice_kind: NoticeKind | None = None
    notice_doi: str | None = None
    notice_date: date | None = None
    source_version: str | None = None
    linked: Identifiers | None = None
    venue: str | None = None


PageSink = Callable[[RawPage], str]

BUDGET_STOP_NOTE = "budget-exhausted: requests:search"
"""Why a run stopped at its request budget (slice 5 ruling 17). Such a run is partial and carries
its resume token, so it continues once the budget is raised (R-23)."""


@dataclass(frozen=True, slots=True)
class BudgetedSink:
    """A page sink that also knows whether the run may ask its source for another page."""

    sink: PageSink
    spent: Callable[[], bool]
    progress: Callable[[int, int | None, int], None] | None = None
    """Optional `(records retrieved, reported count, pages)` hook for live progress (IDEA-44)."""

    def __call__(self, page: RawPage) -> str:
        return self.sink(page)


def report_progress(archive: PageSink, retrieved: int, reported: int | None, pages: int) -> None:
    """Tell a progress hook how far a paginating adapter is; a no-op for a plain sink, and a hook
    that fails never breaks the fetch."""
    if isinstance(archive, BudgetedSink) and archive.progress is not None:
        try:
            archive.progress(retrieved, reported, pages)
        except Exception:
            return


def budget_spent(archive: PageSink) -> bool:
    """Asked by a paginating adapter before each request. A plain sink has no budget."""
    return isinstance(archive, BudgetedSink) and archive.spent()


"""Archives one raw response and returns its blob ref.

Called as each response arrives, before its records are parsed, so a long search that dies on
page 26 has already stored the 25 pages it paid for. Adapters put the returned ref into each
parsed record's `Provenance.raw_blob`.
"""


@dataclass(frozen=True, slots=True)
class SearchResult:
    """The outcome of one source's part of one run.

    `reported_count` and `retrieved_count` are kept apart on purpose. A source claiming 1,840
    results and yielding 1,832 is routine; recording only the number delivered is how a corpus
    becomes unreproducible in a way nobody can see.

    Note rule: `note` is required whenever `status != COMPLETE`, and for `COMPLETE` whenever
    `has_shortfall`. A run that delivered fewer records than its source reported must say why,
    or it cannot be recorded (R-23, slice-1 acceptance 14). `status` is limited to the terminal
    outcomes an adapter can report: COMPLETE, PARTIAL or FAILED.
    """

    source: str
    query_sent: str
    reported_count: int | None
    works: list[Work]
    pages: int
    status: RunStatus
    skipped: int = 0
    note: str | None = None
    status_records: tuple[StatusRecord, ...] = ()
    """What a STATUS lookup read (living-C); such a result has no `works`."""
    resume_token: str | None = None
    """Where a partial run stopped, in whatever form the source resumes from.

    A token rather than an integer because sources paginate differently: arXiv resumes from a
    numeric offset, OpenAlex from an opaque cursor. Forcing them into one shape would make the
    field meaningless for one of them.
    """

    def __post_init__(self) -> None:
        if self.status not in _RESULT_STATUSES:
            raise ValueError(
                f"a source run reports complete, partial or failed, not {self.status.value!r}"
            )
        has_note = self.note is not None and bool(self.note.strip())
        if not has_note and (self.status is not RunStatus.COMPLETE or self.has_shortfall):
            reason = (
                f"status is {self.status.value!r}"
                if self.status is not RunStatus.COMPLETE
                else f"{self.retrieved_count} of {self.reported_count} records delivered"
            )
            raise ValueError(f"a run that is not fully explained needs a note ({reason})")

    @property
    def retrieved_count(self) -> int:
        return len(self.works)

    @property
    def has_shortfall(self) -> bool:
        return self.reported_count is not None and self.retrieved_count < self.reported_count


@runtime_checkable
class Source(Protocol):
    """What every adapter must provide."""

    name: str
    kinds: frozenset[QueryKind]

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
        resume_from: str | None = None,
    ) -> SearchResult:
        """Exhaustively retrieve everything `spec` matches, in the source's native syntax.

        Each raw response goes to `archive` as it arrives, before parsing; durability cannot
        wait for the run to finish. `resume_from` is a `SearchResult.resume_token` from an
        earlier partial run of the same query.
        """
        ...


@runtime_checkable
class Prober(Protocol):
    """Measures a query at a source without retrieving its records.

    A probe asks the source, not the corpus: `count` is the source's own total, and `matching`
    reports which of the given source-native ids the query actually retrieves. Every response
    goes to `archive` before it is parsed, exactly as in a run.
    """

    def count(self, spec: QuerySpec, *, archive: PageSink) -> int | None:
        """The source's reported total for `spec`, or None if the source reports none."""
        ...

    def matching(self, ids: Sequence[str], spec: QuerySpec, *, archive: PageSink) -> set[str]:
        """The members of `ids` that `spec` retrieves, returned in the form they were given."""
        ...


@dataclass(frozen=True, slots=True)
class SampledRecord:
    """One record of a probe's title sample: a title and the identifiers the source gave it.

    It is never a `Work`: a sample enters neither the corpus nor PRISMA.
    """

    title: str
    identifiers: Identifiers


SampleKind = Literal["random", "top"]


@runtime_checkable
class Sampler(Protocol):
    """Draws a small sample of titles from a query's results, so a scientist can judge noise.

    `random` is a seeded random sample of the whole result set; `top` is the first page by
    relevance, for sources with no random sample. Every response goes to `archive` before it is
    parsed.
    """

    def sample(
        self, spec: QuerySpec, size: int, *, archive: PageSink
    ) -> tuple[SampleKind, list[SampledRecord]]:
        """At most `size` records of `spec`, and how they were drawn."""
        ...


@runtime_checkable
class OverlapCounter(Protocol):
    """Counts a query's results that are also hosted on arXiv (an estimate of the overlap)."""

    def count_on_arxiv(self, spec: QuerySpec, *, archive: PageSink) -> int | None:
        """The source's own total for `spec` restricted to records hosted on arXiv, if reported."""
        ...


def probe_key(source: str, work: Work) -> str | None:
    """The identity a probe matches a work by, in the source's own namespace.

    For arXiv this is the normalised id, bridged from a DataCite DOI when the record carries only
    that. For OpenAlex it is the work id; a work resolved elsewhere has none, so it falls back to
    `doi:<normalised doi>`, the record's DOI or else the DataCite DOI of its arXiv id (which
    OpenAlex indexes). A DOI that would break OpenAlex's filter syntax (`,` or `|`) gives no key.
    For PubMed it is the PMID, or None for a work without one. Other sources have no probe key,
    so None.
    """
    if source == "arxiv":
        if work.identifiers.arxiv:
            return normalize_arxiv(work.identifiers.arxiv)
        if work.identifiers.doi:
            return arxiv_id_from_doi(work.identifiers.doi)
        return None
    if source == "pubmed":
        return work.identifiers.pmid or None
    if source == "openalex":
        if work.identifiers.openalex:
            return work.identifiers.openalex
        doi: str | None = None
        if work.identifiers.doi:
            doi = normalize_doi(work.identifiers.doi)
        elif work.identifiers.arxiv:
            doi = f"10.48550/arxiv.{normalize_arxiv(work.identifiers.arxiv)}"
        if doi is None or "," in doi or "|" in doi:
            return None
        return f"doi:{doi}"
    return None


__all__ = [
    "BUDGET_STOP_NOTE",
    "BudgetedSink",
    "PageSink",
    "Prober",
    "RawPage",
    "SearchResult",
    "Source",
    "SourceError",
    "StatusRecord",
    "budget_spent",
    "probe_key",
]

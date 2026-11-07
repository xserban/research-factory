"""OpenAlex adapter.

Free, CC0, no key. Two properties matter here:

**Cursor paging.** OpenAlex caps offset paging at 10,000 but places no limit on cursor
paging, so this adapter sidesteps the deep-pagination truncation that Stage 03 warns about
rather than having to partition around it.

**Inverted-index abstracts.** Abstracts arrive as `{word: [positions]}` and must be
reconstructed. The reconstruction is lossy in punctuation and is marked as such — it is fine
for screening, and should not be quoted as if it were the author's prose.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, ClassVar

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
from factory.model.work_ids import arxiv_id_from_doi, normalize_doi
from factory.sources.base import (
    BUDGET_STOP_NOTE,
    PageSink,
    RawPage,
    SampledRecord,
    SampleKind,
    SearchResult,
    SourceError,
    StatusRecord,
    budget_spent,
    report_progress,
)
from factory.sources.http import PoliteClient, redact, redact_api_key

_ENDPOINT = "https://api.openalex.org/works"
_PAGE_SIZE = 200  # the documented maximum
_PROBE_BATCH = 50  # ids per probe request: one page, no cursor to follow
_SAMPLE_SEED = 20261107  # fixed, so a repeated probe draws the same sample
_SAMPLE_MAX = _PAGE_SIZE  # a sample is one page
_ARXIV_SOURCE = "S4306400194"  # OpenAlex's source id for arXiv

# OpenAlex `type` -> our vocabulary. Unmapped types become OTHER rather than guessing.
_TYPES: dict[str, WorkType] = {
    "article": WorkType.JOURNAL_ARTICLE,
    "review": WorkType.JOURNAL_ARTICLE,
    "letter": WorkType.JOURNAL_ARTICLE,
    "editorial": WorkType.JOURNAL_ARTICLE,
    "preprint": WorkType.PREPRINT,
    "conference-paper": WorkType.CONFERENCE_PAPER,
    # A conference abstract is not a paper: it reports no method and cannot be appraised
    # like one. Mapping it to CONFERENCE_PAPER would quietly promote it.
    "conference-abstract": WorkType.OTHER,
    "book-chapter": WorkType.BOOK_CHAPTER,
    "dissertation": WorkType.THESIS,
    "report": WorkType.TECH_REPORT,
    "standard": WorkType.STANDARD,
    "dataset": WorkType.DATASET,
    "patent": WorkType.PATENT,
    "book": WorkType.BOOK_CHAPTER,
    "paratext": WorkType.OTHER,
}

_METHODS: dict[QueryPurpose, ProvenanceMethod] = {
    QueryPurpose.CHASE: ProvenanceMethod.CITATION_CHASE,
    QueryPurpose.SEED: ProvenanceMethod.SEED_ADMISSION,
    QueryPurpose.SUPPLIED: ProvenanceMethod.SUPPLIED,
    QueryPurpose.IMPORT: ProvenanceMethod.LIBRARY_IMPORT,
    QueryPurpose.GREY: ProvenanceMethod.GREY_STRUCTURED,
}

_SKIPPED = "records skipped (untitled or duplicate within run)"
_TRUNCATED = "truncated by caller-supplied limit"


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """Rebuild prose from OpenAlex's `{word: [positions]}` form."""
    if not inverted:
        return None
    positions = sorted((pos, word) for word, spots in inverted.items() for pos in spots)
    return " ".join(word for _, word in positions) or None


def _strip_url(value: str | None, prefix: str) -> str | None:
    if not value:
        return None
    return value.removeprefix(prefix) or None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _page_range(biblio: dict[str, Any]) -> str | None:
    first, last = biblio.get("first_page"), biblio.get("last_page")
    if first and last:
        return f"{first}-{last}"
    return first or last or None


def _payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SourceError(f"openalex returned unparseable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceError("openalex returned a non-object payload")
    return payload


def _doi_of_url(url: str | None) -> str | None:
    """The DOI in a `https://doi.org/...` landing-page URL, or None."""
    if not url:
        return None
    lowered = url.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/"):
        if lowered.startswith(prefix):
            return normalize_doi(url[len(prefix) :]) or None
    return None


def status_records(item: dict[str, Any]) -> list[StatusRecord]:
    """What an OpenAlex work record says about notices and published versions (living-C).

    `is_retracted` yields a retraction notice with no notice DOI and no date: OpenAlex states
    neither. A `publishedVersion` location whose landing page is a DOI different from the work's
    own yields a link to that DOI, with the location's source as the venue.
    """
    openalex = _strip_url(item.get("id"), "https://openalex.org/")
    doi_url = _strip_url(item.get("doi"), "https://doi.org/")
    doi = normalize_doi(doi_url) if doi_url else None
    target = Identifiers(openalex=openalex, doi=doi, arxiv=arxiv_id_from_doi(doi) if doi else None)
    out: list[StatusRecord] = []
    if item.get("is_retracted"):
        out.append(StatusRecord(target=target, kind="notice", notice_kind=NoticeKind.RETRACTION))
    for location in item.get("locations") or []:
        if not isinstance(location, dict) or location.get("version") != "publishedVersion":
            continue
        published = _doi_of_url(location.get("landing_page_url")) or (
            normalize_doi(str(location["doi"])) if location.get("doi") else None
        )
        if published is None or published == doi:
            continue
        venue = (location.get("source") or {}).get("display_name")
        out.append(
            StatusRecord(
                target=target,
                kind="version",
                linked=Identifiers(doi=published),
                venue=venue if isinstance(venue, str) else None,
            )
        )
        break  # one link per work: the first published location
    return out


class OpenAlexSource:
    """Exhaustive cursor-paged retrieval from OpenAlex."""

    name: str = "openalex"
    kinds: frozenset[QueryKind] = frozenset({QueryKind.KEYWORD, QueryKind.FILTER})
    window_filter: ClassVar[bool] = False
    """`filters["listed_since"]` maps to `from_created_date`, but whether OpenAlex accepts that
    filter without an API key is unverified (slice 4b, ruling 2; `test_watch_network.py`). It
    stays False, so a watch cannot window OpenAlex, until that test passes."""

    def __init__(
        self,
        http: PoliteClient,
        *,
        clock: Clock,
        mailto: str | None = None,
        api_key: str | None = None,
        page_size: int = _PAGE_SIZE,
    ) -> None:
        # The polite pool wants a contact address. The caller passes it from configuration
        # (Settings.mailto, env FACTORY_MAILTO) — never hardcoded. A repo that ships someone's
        # email address ships it to everyone who clones it.
        self._http = http
        self._clock = clock
        self._mailto = mailto
        # OpenAlex needs a free API key for cursor paging past the first page (2026). The key
        # comes from configuration and is redacted from every URL and note like the address.
        self._api_key = api_key
        self._page_size = page_size

    def _redact(self, text: str) -> str:
        return redact_api_key(redact(text, self._mailto), self._api_key)

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
            raise ValueError(f"openalex does not take {spec.kind.value} queries")
        if spec.purpose is QueryPurpose.STATUS:
            return self._run_status(spec, archive)

        query_sent = self._filter_expression(spec)
        method = _METHODS.get(spec.purpose, ProvenanceMethod.DATABASE)
        works: list[Work] = []
        seen: set[str] = set()
        skipped = 0
        archived = 0
        reported: int | None = None
        truncated = False
        # OpenAlex resumes from its own opaque cursor, which is exactly why the resume token
        # is a string rather than an offset.
        cursor = resume_from or "*"

        while cursor:
            if budget_spent(archive):
                return SearchResult(
                    source=self.name,
                    query_sent=query_sent,
                    reported_count=reported,
                    works=works,
                    pages=archived,
                    status=RunStatus.PARTIAL,
                    skipped=skipped,
                    note=BUDGET_STOP_NOTE,
                    resume_token=cursor,
                )
            params: dict[str, str | int] = {
                "filter": query_sent,
                "per-page": self._page_size,
                "cursor": cursor,
            }
            if self._mailto:
                params["mailto"] = self._mailto
            if self._api_key:
                params["api_key"] = self._api_key

            try:
                response = self._http.get(_ENDPOINT, params)
            except httpx.HTTPError as exc:
                return SearchResult(
                    source=self.name,
                    query_sent=query_sent,
                    reported_count=reported,
                    works=works,
                    pages=archived,
                    status=RunStatus.PARTIAL if works else RunStatus.FAILED,
                    skipped=skipped,
                    note=self._redact(f"{type(exc).__name__}: {exc}"),
                    resume_token=cursor,
                )

            # Archive the verbatim response before any of its records are parsed (R-03).
            now = self._clock.now()
            raw_blob = archive(
                RawPage(
                    ordinal=archived,
                    body=response.text,
                    url=self._redact(str(response.url)),
                    fetched_at=now,
                )
            )
            archived += 1

            try:
                payload = _payload(response)
            except SourceError as exc:
                # The page is archived above, so the failure is explained and resumable (R9).
                return SearchResult(
                    source=self.name,
                    query_sent=query_sent,
                    reported_count=reported,
                    works=works,
                    pages=archived,
                    status=RunStatus.PARTIAL if works else RunStatus.FAILED,
                    skipped=skipped,
                    note=self._redact(f"SourceError: {exc}"),
                    resume_token=cursor,
                )
            meta = payload.get("meta") or {}
            if reported is None and isinstance(meta.get("count"), int):
                reported = meta["count"]

            results = payload.get("results") or []
            for item in results:
                work = self.to_work(
                    item,
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

            report_progress(archive, len(works), reported, archived)
            next_cursor = meta.get("next_cursor") or ""
            if spec.limit is not None and len(works) >= spec.limit:
                truncated = len(works) > spec.limit or bool(next_cursor)
                del works[spec.limit :]
                break

            cursor = next_cursor
            if not results:
                break

        if truncated:
            status, note = RunStatus.PARTIAL, _TRUNCATED
        else:
            status, note = RunStatus.COMPLETE, None
            if reported is not None and len(works) < reported:
                note = f"{skipped} {_SKIPPED}"
                if len(works) + skipped != reported:
                    note += "; source count differs"

        return SearchResult(
            source=self.name,
            query_sent=query_sent,
            reported_count=reported,
            works=works,
            pages=archived,
            status=status,
            skipped=skipped,
            note=note,
        )

    def _run_status(self, spec: QuerySpec, archive: PageSink) -> SearchResult:
        """A status lookup: the same filter and paging, parsed into status records, no works.

        Each response is archived before it is parsed. A failure after some pages is a partial
        result whose resume token is the cursor to continue from.
        """
        query_sent = self._filter_expression(spec)
        records: list[StatusRecord] = []
        archived = 0
        returned = 0
        cursor = "*"
        while cursor:
            if budget_spent(archive):
                return SearchResult(
                    source=self.name,
                    query_sent=query_sent,
                    reported_count=None,
                    works=[],
                    pages=archived,
                    status=RunStatus.PARTIAL,
                    note=BUDGET_STOP_NOTE,
                    resume_token=cursor,
                    status_records=tuple(records),
                )
            params: dict[str, str | int] = {
                "filter": query_sent,
                "per-page": self._page_size,
                "cursor": cursor,
            }
            if self._mailto:
                params["mailto"] = self._mailto
            if self._api_key:
                params["api_key"] = self._api_key
            note: str | None = None
            payload: dict[str, Any] = {}
            try:
                response = self._http.get(_ENDPOINT, params)
            except httpx.HTTPError as exc:
                note = self._redact(f"{type(exc).__name__}: {exc}")
            else:
                archive(
                    RawPage(
                        ordinal=archived,
                        body=response.text,
                        url=self._redact(str(response.url)),
                        fetched_at=self._clock.now(),
                    )
                )
                archived += 1
                try:
                    payload = _payload(response)
                except SourceError as exc:
                    note = self._redact(f"SourceError: {exc}")
            if note is not None:
                return SearchResult(
                    source=self.name,
                    query_sent=query_sent,
                    reported_count=None,
                    works=[],
                    pages=archived,
                    status=RunStatus.PARTIAL if records else RunStatus.FAILED,
                    note=note,
                    resume_token=cursor,
                    status_records=tuple(records),
                )
            results = payload.get("results") or []
            for item in results:
                records.extend(status_records(item))
            returned += len(results)
            cursor = (payload.get("meta") or {}).get("next_cursor") or ""
            if not results:
                break
        return SearchResult(
            source=self.name,
            query_sent=query_sent,
            reported_count=None,
            works=[],
            pages=archived,
            status=RunStatus.COMPLETE,
            note=f"{returned} record(s) returned",
            status_records=tuple(records),
        )

    def count(self, spec: QuerySpec, *, archive: PageSink) -> int | None:
        """OpenAlex's own total for `spec`, from one request for a single record."""
        self._require_known_kind(spec)
        meta, _ = self._probe_get(
            {"filter": self._filter_expression(spec), "per-page": 1},
            ordinal=0,
            archive=archive,
        )
        count = meta.get("count")
        return count if isinstance(count, int) else None

    def matching(self, ids: Sequence[str], spec: QuerySpec, *, archive: PageSink) -> set[str]:
        """Which of `ids` `spec` retrieves, measured in batches of at most 50 ids.

        An id is a work id (`W1`) or a DOI key (`doi:10.x/y`, see `probe_key`). Each batch is
        `openalex:W1|W2` or `doi:a|b`, intersected with the query's own filter expression, so one
        response answers for up to 50 seeds. Ids are compared case-insensitively and returned
        in the form given. A DOI that OpenAlex does not hold as a work's DOI reads as not
        retrieved, as an untestable seed does.
        """
        self._require_known_kind(spec)
        works = [i for i in ids if not i.strip().casefold().startswith("doi:")]
        dois = [i for i in ids if i.strip().casefold().startswith("doi:")]
        found: set[str] = set()
        ordinal = 0
        for field, group in (("openalex", works), ("doi", dois)):
            given = {i.strip().casefold(): i for i in group}
            for start in range(0, len(group), _PROBE_BATCH):
                batch = group[start : start + _PROBE_BATCH]
                values = [i.strip()[4:] if field == "doi" else i.strip() for i in batch]
                # The same expression the count and the run send, so recall is measured against
                # the query that will actually be searched.
                params: dict[str, str | int] = {
                    "filter": f"{field}:{'|'.join(values)},{self._filter_expression(spec)}",
                    "per-page": _PROBE_BATCH,
                }
                _, results = self._probe_get(params, ordinal=ordinal, archive=archive)
                ordinal += 1
                for item in results:
                    if field == "doi":
                        doi = _strip_url(item.get("doi"), "https://doi.org/")
                        key = f"doi:{normalize_doi(doi)}" if doi else ""
                    else:
                        key = (_strip_url(item.get("id"), "https://openalex.org/") or "").casefold()
                    if key.casefold() in given:
                        found.add(given[key.casefold()])
        return found

    def sample(
        self, spec: QuerySpec, size: int, *, archive: PageSink
    ) -> tuple[SampleKind, list[SampledRecord]]:
        """A seeded random sample of at most `size` records (`sample` with a fixed `seed`).

        The sample is drawn from the records the query's filter expression selects, so it shows
        what a run would retrieve. OpenAlex's `seed` makes it repeatable for an unchanged index.
        """
        self._require_known_kind(spec)
        size = min(size, _SAMPLE_MAX)
        _, results = self._probe_get(
            {
                "filter": self._filter_expression(spec),
                "sample": size,
                "seed": _SAMPLE_SEED,
                "per-page": size,
            },
            ordinal=0,
            archive=archive,
        )
        records: list[SampledRecord] = []
        for item in results[:size]:
            title = item.get("display_name") or item.get("title")
            if not title:
                continue
            doi_url = _strip_url(item.get("doi"), "https://doi.org/")
            doi = normalize_doi(doi_url) if doi_url else None
            records.append(
                SampledRecord(
                    title=" ".join(str(title).split()),
                    identifiers=Identifiers(
                        openalex=_strip_url(item.get("id"), "https://openalex.org/"),
                        doi=doi,
                        arxiv=arxiv_id_from_doi(doi) if doi else None,
                    ),
                )
            )
        return "random", records

    def count_on_arxiv(self, spec: QuerySpec, *, archive: PageSink) -> int | None:
        """The total of `spec`'s results hosted on arXiv: the filter plus the arXiv source id.

        An estimate of the overlap with an arXiv search of the same topic, not a dedup.
        """
        self._require_known_kind(spec)
        meta, _ = self._probe_get(
            {
                "filter": f"{self._filter_expression(spec)},locations.source.id:{_ARXIV_SOURCE}",
                "per-page": 1,
            },
            ordinal=0,
            archive=archive,
        )
        count = meta.get("count")
        return count if isinstance(count, int) else None

    def _require_known_kind(self, spec: QuerySpec) -> None:
        if spec.kind not in self.kinds:
            raise ValueError(f"openalex does not take {spec.kind.value} queries")

    def _probe_get(
        self, params: dict[str, str | int], *, ordinal: int, archive: PageSink
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """One archived probe request: its `meta` and `results`.

        The contact address is sent (polite pool) but never archived: the archived URL is
        redacted, as for a run. Transport failures become `SourceError`.
        """
        if self._mailto:
            params = {**params, "mailto": self._mailto}
        if self._api_key:
            params = {**params, "api_key": self._api_key}
        try:
            response = self._http.get(_ENDPOINT, params)
        except httpx.HTTPError as exc:
            raise SourceError(self._redact(f"{type(exc).__name__}: {exc}")) from exc
        archive(
            RawPage(
                ordinal=ordinal,
                body=response.text,
                url=self._redact(str(response.url)),
                fetched_at=self._clock.now(),
            )
        )
        payload = _payload(response)
        meta = payload.get("meta") or {}
        results = payload.get("results") or []
        return meta, results

    @staticmethod
    def _filter_expression(spec: QuerySpec) -> str:
        if spec.kind is QueryKind.KEYWORD:
            expression = f"title_and_abstract.search:{spec.text}"
        else:
            # FILTER text is sent verbatim: `doi:a|b`, `openalex:W1|W2`, `cites:W1`.
            expression = spec.text
        parts = (
            ("from_created_date" if key == "listed_since" else key, value)
            for key, value in spec.filters.items()
        )
        return expression + "".join(f",{key}:{value}" for key, value in parts)

    def to_work(
        self,
        item: dict[str, Any],
        *,
        run_id: str,
        query_id: str,
        raw_blob: str,
        at: datetime,
        method: ProvenanceMethod,
    ) -> Work | None:
        title = item.get("display_name") or item.get("title")
        if not title:
            return None  # OpenAlex carries a tail of untitled records; they cannot be screened

        ids = item.get("ids") or {}
        location = item.get("primary_location") or {}
        venue_source = location.get("source") or {}
        biblio = item.get("biblio") or {}

        return Work.build(
            title=title,
            abstract=reconstruct_abstract(item.get("abstract_inverted_index")),
            language=item.get("language"),
            type=_TYPES.get(item.get("type") or "", WorkType.OTHER),
            authors=[
                Author(
                    name=name,
                    orcid=_strip_url(author.get("orcid"), "https://orcid.org/"),
                    affiliation=next(
                        (i.get("display_name") for i in (entry.get("institutions") or [])), None
                    ),
                )
                for entry in (item.get("authorships") or [])
                if (author := entry.get("author") or {}) and (name := author.get("display_name"))
            ],
            identifiers=Identifiers(
                openalex=_strip_url(item.get("id"), "https://openalex.org/"),
                doi=_strip_url(item.get("doi"), "https://doi.org/"),
                pmid=_strip_url(ids.get("pmid"), "https://pubmed.ncbi.nlm.nih.gov/"),
                pmcid=_strip_url(ids.get("pmcid"), "https://www.ncbi.nlm.nih.gov/pmc/articles/"),
                url=location.get("landing_page_url"),
            ),
            venue=Venue(
                name=venue_source.get("display_name"),
                publisher=venue_source.get("host_organization_name"),
                volume=biblio.get("volume"),
                issue=biblio.get("issue"),
                pages=_page_range(biblio),
            ),
            dates=Dates(
                published=_parse_date(item.get("publication_date")),
                retrieved=at,
            ),
            subjects=[
                name for topic in (item.get("topics") or []) if (name := topic.get("display_name"))
            ],
            cited_by_count=item.get("cited_by_count"),
            retracted=bool(item.get("is_retracted")),
            provenance=[
                Provenance(
                    source=self.name,
                    run_id=run_id,
                    query_id=query_id,
                    at=at,
                    raw_blob=raw_blob,
                    raw_ref=_strip_url(item.get("id"), "https://openalex.org/"),
                    method=method,
                )
            ],
        )

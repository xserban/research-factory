"""PubMed adapter, over NCBI E-utilities.

E-utilities is a two-step API. `esearch` (with `usehistory=y`) returns the reported count and a
server-side history handle (`WebEnv`, `query_key`); `efetch` then pulls the records through that
handle in batches. A run can therefore stop in either phase.

PubMed serves at most 9,999 records of one query. A query that reports more is recorded as
`partial` with a cap note (R-23); the adapter never slices a query by itself, the agent does.

The query text is PubMed syntax and is sent verbatim. The API key and the contact address are
sent to NCBI but never reach an archived URL or a note.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import ClassVar
from xml.etree import ElementTree

import httpx

from factory.clock import Clock
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
from factory.sources.base import (
    BUDGET_STOP_NOTE,
    PageSink,
    RawPage,
    SampledRecord,
    SampleKind,
    SearchResult,
    SourceError,
    budget_spent,
    report_progress,
)
from factory.sources.http import PoliteClient, redact, redact_api_key

_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_ESEARCH = f"{_BASE}/esearch.fcgi"
_EFETCH = f"{_BASE}/efetch.fcgi"

_BATCH = 200
_CAP = 9999
"""The most records PubMed will serve for one query."""

_METHODS: dict[QueryPurpose, ProvenanceMethod] = {
    QueryPurpose.CHASE: ProvenanceMethod.CITATION_CHASE,
    QueryPurpose.SEED: ProvenanceMethod.SEED_ADMISSION,
    QueryPurpose.SUPPLIED: ProvenanceMethod.SUPPLIED,
    QueryPurpose.IMPORT: ProvenanceMethod.LIBRARY_IMPORT,
}

_SKIPPED = "records skipped (untitled or duplicate within run)"
_TRUNCATED = "truncated by caller-supplied limit"

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}

_TYPES: dict[str, WorkType] = {
    "preprint": WorkType.PREPRINT,
}
"""Publication types that are not plain articles. Everything else in PubMed (reviews, trials,
editorials, letters, ...) is at least a journal article."""

_RETRACTION_TYPES = frozenset({"retracted publication", "retraction of publication"})


def ncbi_api_key() -> str | None:
    """The NCBI API key from `FACTORY_NCBI_API_KEY`, else the first line of
    `~/.config/research-factory/ncbi-api-key`, else None. Never stored in the repository or the
    event log."""
    key = os.environ.get("FACTORY_NCBI_API_KEY", "").strip()
    if key:
        return key
    path = Path.home() / ".config" / "research-factory" / "ncbi-api-key"
    try:
        return path.read_text(encoding="utf-8").strip().splitlines()[0] or None
    except (OSError, IndexError):
        return None


def _text(node: ElementTree.Element | None) -> str | None:
    """The text of a node with inline markup (`<i>`, `<sub>`) flattened, whitespace collapsed."""
    if node is None:
        return None
    joined = " ".join(node.itertext())
    return " ".join(joined.split()) or None


def _parse_pubdate(node: ElementTree.Element | None) -> date | None:
    """PubMed dates are irregular: Year/Month/Day, or a free-text MedlineDate."""
    if node is None:
        return None
    year_text = _text(node.find("Year"))
    if not year_text:
        medline = _text(node.find("MedlineDate")) or ""
        year_text = next((tok for tok in medline.split() if tok.isdigit()), None)
    if not year_text or not year_text.isdigit():
        return None
    month_text = (_text(node.find("Month")) or "1").lower()
    month = _MONTHS.get(month_text[:3], int(month_text) if month_text.isdigit() else 1)
    day_text = _text(node.find("Day")) or "1"
    day = int(day_text) if day_text.isdigit() else 1
    try:
        return date(int(year_text), max(1, min(12, month)), max(1, min(28, day)))
    except ValueError:
        return None


def _abstract(meta: ElementTree.Element) -> str | None:
    """Join structured abstracts, keeping their section labels (BACKGROUND, METHODS, ...)."""
    parts: list[str] = []
    for node in meta.findall("Abstract/AbstractText"):
        text = _text(node)
        if not text:
            continue
        label = node.get("Label")
        parts.append(f"{label}: {text}" if label else text)
    return "\n\n".join(parts) or None


def _authors(meta: ElementTree.Element) -> list[Author]:
    authors: list[Author] = []
    for node in meta.findall("AuthorList/Author"):
        last, fore = _text(node.find("LastName")), _text(node.find("ForeName"))
        name = _text(node.find("CollectiveName")) or " ".join(x for x in (fore, last) if x)
        if not name:
            continue
        orcid = next(
            (
                _text(i)
                for i in node.findall("Identifier")
                if (i.get("Source") or "").upper() == "ORCID"
            ),
            None,
        )
        authors.append(
            Author(
                name=name,
                orcid=orcid.rsplit("/", 1)[-1] if orcid else None,
                affiliation=_text(node.find("AffiliationInfo/Affiliation")),
            )
        )
    return authors


def _subjects(citation: ElementTree.Element) -> list[str]:
    """MeSH descriptors first, then author keywords."""
    mesh = citation.findall("MeshHeadingList/MeshHeading/DescriptorName")
    keywords = citation.findall("KeywordList/Keyword")
    terms = [_text(node) for node in (*mesh, *keywords)]
    return [term for term in terms if term]


def _requested_pmids(text: str) -> list[str]:
    """The distinct PMIDs named in an id_list query, in the order given (comma or whitespace)."""
    return list(dict.fromkeys(part for part in re.split(r"[,\s]+", text) if part))


def _identifiers(article: ElementTree.Element) -> Identifiers:
    """The PMID, DOI and PMC id of one `PubmedArticle`."""
    article_ids = {
        (el.get("IdType") or ""): (el.text or "").strip()
        for el in article.findall("PubmedData/ArticleIdList/ArticleId")
    }
    return Identifiers(
        pmid=_text(article.find("MedlineCitation/PMID")),
        doi=article_ids.get("doi") or None,
        pmcid=article_ids.get("pmc") or None,
    )


def _articles(body: str) -> list[ElementTree.Element]:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise SourceError(f"pubmed efetch returned unparseable XML: {exc}") from exc
    return root.findall(".//PubmedArticle")


class PubmedSource:
    """Exhaustive retrieval from PubMed through esearch history and efetch batches."""

    name: str = "pubmed"
    kinds: frozenset[QueryKind] = frozenset({QueryKind.KEYWORD, QueryKind.ID_LIST})
    window_filter: ClassVar[bool] = False

    def __init__(
        self,
        http: PoliteClient,
        *,
        clock: Clock,
        mailto: str | None = None,
        api_key: str | None = None,
        batch_size: int = _BATCH,
    ) -> None:
        self._http = http
        self._clock = clock
        self._mailto = mailto
        self._api_key = api_key
        self._batch_size = batch_size

    def _redact(self, text: str) -> str:
        return redact_api_key(redact(text, self._mailto), self._api_key)

    def _params(self, **extra: str | int) -> dict[str, str | int]:
        params: dict[str, str | int] = {"db": "pubmed", **extra}
        if self._api_key:
            params["api_key"] = self._api_key
        if self._mailto:
            params["tool"] = "research-factory"
            params["email"] = self._mailto
        return params

    def run(
        self,
        spec: QuerySpec,
        *,
        run_id: str,
        query_id: str,
        archive: PageSink,
        resume_from: str | None = None,
    ) -> SearchResult:
        """Retrieve every record `spec` matches.

        A keyword query runs `esearch` (count and history handle), then `efetch` in batches from
        the offset in `resume_from`. WebEnv expires, so a resumed run searches again and continues
        from the offset; its note says the result set may have changed. An id_list is fetched
        directly, and its reported count is the number of distinct ids given.

        More than 9,999 matches gives `partial` with the cap note. A `limit` gives `partial` with
        the truncated note. A request budget stops the run `partial` with a resume token. Every
        raw response is archived before it is parsed; unparseable XML or JSON raises `SourceError`.
        """
        if spec.kind not in self.kinds:
            raise ValueError(f"pubmed does not take {spec.kind.value} queries")
        if spec.purpose is QueryPurpose.STATUS:
            raise ValueError("pubmed has no status lookup")
        is_ids = spec.kind is QueryKind.ID_LIST
        ids = _requested_pmids(spec.text) if is_ids else []
        if is_ids and not ids:
            raise ValueError("an id_list query must name at least one PMID")

        method = _METHODS.get(spec.purpose, ProvenanceMethod.DATABASE)
        query_sent = ",".join(ids) if is_ids else spec.text
        start = int(resume_from) if resume_from else 0
        works: list[Work] = []
        seen: set[str] = set()
        skipped = 0
        pages = 0
        reported: int | None = len(ids) if is_ids else None
        notes: list[str] = []
        if resume_from and not is_ids:
            notes.append(
                f"resumed at offset {start} after a new esearch; the result set may have changed"
            )

        def result(status: RunStatus, note: str | None, token: str | None = None) -> SearchResult:
            return SearchResult(
                source=self.name,
                query_sent=query_sent,
                reported_count=reported,
                works=works,
                pages=pages,
                status=status,
                skipped=skipped,
                note="; ".join(([note] if note else []) + notes) or None,
                resume_token=token,
            )

        history: dict[str, str | int] = {}
        target = len(ids)
        if not is_ids:
            if budget_spent(archive):
                return result(RunStatus.PARTIAL, BUDGET_STOP_NOTE, str(start))
            try:
                response = self._http.get(
                    _ESEARCH,
                    self._params(term=spec.text, usehistory="y", retmode="json", retmax=0),
                )
            except httpx.HTTPError as exc:
                return result(
                    RunStatus.FAILED,
                    self._redact(f"esearch: {type(exc).__name__}: {exc}"),
                    str(start),
                )
            archive(
                RawPage(
                    ordinal=0,
                    body=response.text,
                    url=self._redact(str(response.url)),
                    fetched_at=self._clock.now(),
                )
            )
            pages += 1
            reported, history = self._esearch_result(response)
            target = min(reported, _CAP)
            if reported > _CAP:
                cap = f"esearch-cap: {reported} reported, {_CAP} retrievable"
                notes.insert(0, f"{cap}; split the query by date")

        truncated = False
        while start < target:
            if budget_spent(archive):
                return result(RunStatus.PARTIAL, BUDGET_STOP_NOTE, str(start))
            if is_ids:
                params = self._params(
                    id=",".join(ids[start : start + self._batch_size]), retmode="xml"
                )
            else:
                params = self._params(
                    **history, retstart=start, retmax=self._batch_size, retmode="xml"
                )
            try:
                response = self._http.get(_EFETCH, params)
            except httpx.HTTPError as exc:
                return result(
                    RunStatus.PARTIAL,
                    self._redact(f"efetch: {type(exc).__name__}: {exc}"),
                    str(start),
                )
            now = self._clock.now()
            raw_blob = archive(
                RawPage(
                    ordinal=start // self._batch_size + (0 if is_ids else 1),
                    body=response.text,
                    url=self._redact(str(response.url)),
                    fetched_at=now,
                )
            )
            pages += 1
            articles = _articles(response.text)
            for article in articles:
                work = self._to_work(
                    article,
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
            start += self._batch_size
            report_progress(archive, len(works), reported, pages)
            if spec.limit is not None and len(works) >= spec.limit:
                truncated = len(works) > spec.limit or start < target
                del works[spec.limit :]
                break

        if truncated:
            return result(RunStatus.PARTIAL, _TRUNCATED)
        if reported is not None and reported > _CAP and not is_ids:
            return result(RunStatus.PARTIAL, None)
        note: str | None = None
        if is_ids:
            returned = {w.identifiers.pmid for w in works}
            missing = [i for i in ids if i not in returned]
            if missing:
                note = f"{len(missing)} requested id(s) not returned: {', '.join(missing[:10])}"
                if len(missing) > 10:
                    note += f" (+{len(missing) - 10} more)"
                if skipped:
                    note += f"; {skipped} {_SKIPPED}"
        elif reported is not None and len(works) < reported:
            note = f"{skipped} {_SKIPPED}"
            if len(works) + skipped != reported and not notes:
                note += "; source count differs"
        return result(RunStatus.COMPLETE, note)

    def count(self, spec: QuerySpec, *, archive: PageSink) -> int | None:
        """PubMed's own total for a keyword query, from one esearch that carries no records."""
        self._require_keyword(spec)
        payload = self._probe_search(
            {"term": spec.text, "rettype": "count", "retmode": "json"}, ordinal=0, archive=archive
        )
        count = str(payload.get("count", ""))
        return int(count) if count.isdigit() else None

    def matching(self, ids: Sequence[str], spec: QuerySpec, *, archive: PageSink) -> set[str]:
        """Which of `ids` (PMIDs) the query retrieves, measured in chunks of `_BATCH`.

        Each chunk is one esearch of `(<query>) AND (<pmid>[uid] OR ...)`. Ids that are not all
        digits cannot be PMIDs and are ignored. Returned in the form given.
        """
        self._require_keyword(spec)
        candidates = [i for i in ids if i.isascii() and i.isdigit()]
        found: set[str] = set()
        for start in range(0, len(candidates), _BATCH):
            chunk = candidates[start : start + _BATCH]
            clause = " OR ".join(f"{pmid}[uid]" for pmid in chunk)
            payload = self._probe_search(
                {
                    "term": f"({spec.text}) AND ({clause})",
                    "retmax": len(chunk),
                    "retmode": "json",
                },
                ordinal=start // _BATCH,
                archive=archive,
            )
            listed = payload.get("idlist")
            if isinstance(listed, list):
                returned = {str(i) for i in listed}
                found.update(pmid for pmid in chunk if pmid in returned)
        return found

    def sample(
        self, spec: QuerySpec, size: int, *, archive: PageSink
    ) -> tuple[SampleKind, list[SampledRecord]]:
        """The first `size` records by relevance. E-utilities has no random sample, so the kind
        is `top`: the titles show the best matches, which flatters the query."""
        self._require_keyword(spec)
        payload = self._probe_search(
            {"term": spec.text, "sort": "relevance", "retmax": size, "retmode": "json"},
            ordinal=0,
            archive=archive,
        )
        listed = payload.get("idlist")
        pmids = [str(i) for i in listed][:size] if isinstance(listed, list) else []
        if not pmids:
            return "top", []
        body = self._probe_get(
            _EFETCH,
            {"id": ",".join(pmids), "retmode": "xml"},
            ordinal=1,
            archive=archive,
        )
        records: list[SampledRecord] = []
        for article in _articles(body):
            title = _text(article.find("MedlineCitation/Article/ArticleTitle"))
            if title:
                records.append(SampledRecord(title=title, identifiers=_identifiers(article)))
        return "top", records

    @staticmethod
    def _require_keyword(spec: QuerySpec) -> None:
        if spec.kind is not QueryKind.KEYWORD:
            raise ValueError(f"pubmed probes take keyword queries, not {spec.kind.value}")

    def _probe_get(
        self, url: str, extra: dict[str, str | int], *, ordinal: int, archive: PageSink
    ) -> str:
        """One archived probe request, returning the body. The response is archived before it
        is parsed; transport failures become `SourceError` with key and address redacted."""
        try:
            response = self._http.get(url, self._params(**extra))
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
        return response.text

    def _probe_search(
        self, extra: dict[str, str | int], *, ordinal: int, archive: PageSink
    ) -> dict[str, object]:
        """One archived esearch, returning its `esearchresult` object."""
        body = self._probe_get(_ESEARCH, extra, ordinal=ordinal, archive=archive)
        try:
            payload = json.loads(body).get("esearchresult")
        except (ValueError, AttributeError) as exc:
            raise SourceError(f"pubmed esearch returned unparseable JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise SourceError("pubmed esearch returned no esearchresult")
        return payload

    @staticmethod
    def _esearch_result(response: httpx.Response) -> tuple[int, dict[str, str | int]]:
        """The reported count and the history handle of an archived esearch response."""
        try:
            payload = response.json().get("esearchresult")
        except (ValueError, AttributeError) as exc:
            raise SourceError(f"pubmed esearch returned unparseable JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise SourceError("pubmed esearch returned no esearchresult")
        count = str(payload.get("count", ""))
        webenv, query_key = payload.get("webenv"), payload.get("querykey")
        if not count.isdigit():
            raise SourceError(f"pubmed esearch reported no count: {payload.get('ERROR', '')}")
        if int(count) > 0 and not (webenv and query_key):
            raise SourceError("pubmed esearch returned no history handle")
        handle: dict[str, str | int] = (
            {"WebEnv": str(webenv), "query_key": str(query_key)} if webenv and query_key else {}
        )
        return int(count), handle

    def _to_work(
        self,
        article: ElementTree.Element,
        *,
        run_id: str,
        query_id: str,
        raw_blob: str,
        at: datetime,
        method: ProvenanceMethod,
    ) -> Work | None:
        citation = article.find("MedlineCitation")
        if citation is None:
            return None
        meta = citation.find("Article")
        title = _text(meta.find("ArticleTitle")) if meta is not None else None
        if meta is None or not title:
            return None  # cannot be screened without a title

        pub_types = {
            t.lower()
            for p in meta.findall("PublicationTypeList/PublicationType")
            if (t := _text(p))
        }
        journal = meta.find("Journal")
        issue = journal.find("JournalIssue") if journal is not None else None
        identifiers = _identifiers(article)
        pmid = identifiers.pmid

        return Work.build(
            title=title,
            abstract=_abstract(meta),
            language=_text(meta.find("Language")),
            type=next(
                (_TYPES[t] for t in sorted(pub_types) if t in _TYPES), WorkType.JOURNAL_ARTICLE
            ),
            authors=_authors(meta),
            identifiers=identifiers,
            venue=Venue(
                name=_text(journal.find("Title")) if journal is not None else None,
                volume=_text(issue.find("Volume")) if issue is not None else None,
                issue=_text(issue.find("Issue")) if issue is not None else None,
                pages=_text(meta.find("Pagination/MedlinePgn")),
            ),
            dates=Dates(
                published=_parse_pubdate(issue.find("PubDate") if issue is not None else None),
                retrieved=at,
            ),
            subjects=_subjects(citation),
            retracted=bool(pub_types & _RETRACTION_TYPES),
            provenance=[
                Provenance(
                    source=self.name,
                    run_id=run_id,
                    query_id=query_id,
                    at=at,
                    raw_blob=raw_blob,
                    raw_ref=pmid,
                    method=method,
                )
            ],
        )

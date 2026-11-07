"""Probe vocabulary: value types a probe reports, shared by services and events.

`TermSuggestion` is what vocabulary suggestions report. The payloads below are written by
`factory.services.probe` and folded by `factory.index.probe`. A probe measures a query against
development seeds and negatives only; a held-out seed id never appears in any payload.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE, DecisionId
from factory.model.question import QUESTION_ID_RE
from factory.model.work import QUERY_ID_RE

PROBE_ID_RE = rf"^prb_{ULID_RE}$"


class TermSuggestion(StrictModel):
    """A phrase several missed seeds share and the query does not cover.

    `seeds` is the number of positive seeds that carry the phrase (missed or not), and `holders`
    their seed ids in the order the seeds were given. Both are computed, never typed.
    """

    term: str
    seeds: int
    holders: tuple[str, ...]


class ProbePageArchived(StrictModel):
    """One raw response a probe received, archived before it is measured (R-03)."""

    probe_id: str = Field(pattern=PROBE_ID_RE)
    query_id: str = Field(pattern=QUERY_ID_RE)
    ordinal: int = Field(ge=0)
    url: str
    fetched_at: AwareDatetime
    raw_blob: str = Field(pattern=BLOB_REF_RE)
    role: Literal["count", "match", "sample", "overlap"]


class ProbeMeasured(StrictModel):
    """A query measured against the development seeds and the negatives.

    `development_tested` and `negatives_tested` are the seeds that carry a probe key for the
    source; `untestable` lists the rest of those roles. Untestable seeds are listed, not counted
    as misses: recall is retrieved over `development_tested`.

    `sample_titles` is a small sample of the query's results, for judging noise, and
    `sample_kind` says how it was drawn (`random`, or `top` for the first page by relevance). A
    sample is never a corpus record and holds no held-out seed's work. Both default to empty, so
    events written before samples fold unchanged.

    `openalex_on_arxiv` is, for an OpenAlex query measured in a probe that also measured arXiv,
    the query's total restricted to records hosted on arXiv: an estimate of the overlap between
    the two sources, not a dedup.
    """

    probe_id: str = Field(pattern=PROBE_ID_RE)
    query_id: str = Field(pattern=QUERY_ID_RE)
    source: str
    question_id: str = Field(pattern=QUESTION_ID_RE)
    reported_count: int | None = Field(default=None, ge=0)
    development_tested: tuple[str, ...]
    development_retrieved: tuple[str, ...]
    negatives_tested: tuple[str, ...]
    negatives_retrieved: tuple[str, ...]
    untestable: tuple[str, ...]
    suggestions: tuple[TermSuggestion, ...]
    sample_titles: tuple[str, ...] = ()
    sample_kind: Literal["random", "top"] | None = None
    openalex_on_arxiv: int | None = Field(default=None, ge=0)
    decision_ids: tuple[DecisionId, ...] | None = None


class ProbeFailed(StrictModel):
    """A query whose measurement failed at its source. No recall is claimed for it."""

    probe_id: str = Field(pattern=PROBE_ID_RE)
    query_id: str = Field(pattern=QUERY_ID_RE)
    source: str
    reason: str = Field(min_length=1)

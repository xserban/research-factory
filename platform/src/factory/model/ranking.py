"""Event of a screening ranking (slice 8, IDEA-42, decision 116): `ranking.computed`.

A ranking orders the records still to be screened by their similarity to the development seeds. It
excludes nothing and judges nothing. The order itself is a content-addressed blob (a JSON list of
`{"work_id", "score"}` in rank order); the event holds the blob's ref, a hash of the ranked set,
the model and the parameters. Pure value types; written by `factory.services.ranking`, folded by
`index.ranking`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.identity import BLOB_REF_RE, ULID_RE

RNK_ID_RE = rf"^rnk_{ULID_RE}$"


class RankingParameters(StrictModel):
    """How the scores were made. `references` are the work ids of the development seeds whose text
    was embedded (never a held-out seed's); `skipped_seeds` counts development positives with no
    resolved work or no title, which could not be embedded."""

    method: Literal["max-cosine"] = "max-cosine"
    text: Literal["title [SEP] abstract"] = "title [SEP] abstract"
    stage: Literal["title_abstract"] = "title_abstract"
    references: tuple[str, ...]
    skipped_seeds: int = Field(ge=0)


class RankingComputed(StrictModel):
    """A ranking of the works still to be screened, as the corpus stood when it was computed.

    `corpus_hash` is the sha256 of the sorted ranked work ids joined by newlines and `count` their
    number; `order` is the blob of the ranked list. `weights_hash` is the tree hash of the model
    directory and identifies the revision exactly; `software` names the libraries that ran it."""

    ranking_id: str = Field(pattern=RNK_ID_RE)
    model_id: str = Field(min_length=1)
    weights_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    software: str = Field(min_length=1)
    parameters: RankingParameters
    corpus_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    count: int = Field(ge=1)
    order: str = Field(pattern=BLOB_REF_RE)

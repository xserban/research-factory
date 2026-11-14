"""Seeds: works the review must find (positive) or must not contain (negative), by identifier.

A seed is named by the person or agent that states it; the platform only looks it up. Its
identity keys (normalised DOI, arXiv id, OpenAlex id, PMID) are what duplicates are checked against,
so the same paper given in two forms is one seed. Written by `factory.services.seeds`, folded by
`factory.index.seeds`.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Self

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from factory.model.base import StrictModel
from factory.model.identity import DecisionId
from factory.model.work import RUN_ID_RE, ProvenanceMethod
from factory.model.work_ids import WORK_ID_RE, arxiv_id_from_doi, normalize_arxiv, normalize_doi

SEED_ID_RE = r"^(SEED|NEG)\d{2,}$"
POSITIVE_SEED_ID_RE = r"^SEED\d{2,}$"
SPLIT_PROCEDURE = "year-stratified-thirds-v1"
_OPENALEX_PREFIX = "https://openalex.org/"


class SeedKind(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


def normalize_openalex(value: str) -> str:
    """The bare OpenAlex work id, upper-cased: `https://openalex.org/w42` is `W42`."""
    stripped = value.strip()
    if stripped.lower().startswith(_OPENALEX_PREFIX):
        stripped = stripped[len(_OPENALEX_PREFIX) :]
    return stripped.upper()


_PMID_PREFIX_RE = re.compile(r"^pmid\s*:\s*", re.IGNORECASE)


def normalize_pmid(value: str) -> str:
    """The bare PMID: stripped, a `PMID:` or `pmid:` prefix removed. Raises ValueError unless the
    rest is all ASCII digits."""
    stripped = _PMID_PREFIX_RE.sub("", value.strip()).strip()
    if not (stripped.isascii() and stripped.isdigit()):
        raise ValueError("pmid must be digits only, optionally prefixed `PMID:`")
    return stripped


class SeedSpec(StrictModel):
    """One seed as stated: its kind, how to cite it, and at least one identifier."""

    kind: SeedKind
    cite: str = Field(min_length=1)
    doi: str | None = None
    arxiv: str | None = None
    openalex: str | None = None
    pmid: str | None = None
    why: str = ""

    @field_validator("pmid")
    @classmethod
    def _normal_pmid(cls, value: str | None) -> str | None:
        return None if value is None else normalize_pmid(value)

    @model_validator(mode="after")
    def _has_identifier(self) -> Self:
        given = (self.doi, self.arxiv, self.openalex, self.pmid)
        if not any(value and value.strip() for value in given):
            raise ValueError("give at least one of doi, arxiv, openalex or pmid")
        return self

    @model_serializer(mode="wrap")
    def _omit_absent_pmid(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """`pmid` is left out of every dump while None, so seed events written before it existed
        (and the blobs and hashes over them) read and dump as they were."""
        data: dict[str, Any] = handler(self)
        if data.get("pmid") is None:
            data.pop("pmid", None)
        return data

    def identity_keys(self) -> dict[str, str]:
        """Normalised identifiers by field name. A DOI that is an arXiv DOI also keys its arXiv id.

        The arXiv key is the explicit id when given, otherwise the id a DataCite DOI denotes; a
        preprint seeded by its DOI and by its arXiv id is therefore one seed.
        """
        keys: dict[str, str] = {}
        bridged = arxiv_id_from_doi(self.doi) if self.doi and self.doi.strip() else None
        if self.arxiv and self.arxiv.strip():
            keys["arxiv"] = normalize_arxiv(self.arxiv)
        elif bridged:
            keys["arxiv"] = bridged
        if self.doi and self.doi.strip():
            keys["doi"] = normalize_doi(self.doi)
        if self.openalex and self.openalex.strip():
            keys["openalex"] = normalize_openalex(self.openalex)
        if self.pmid and self.pmid.strip():
            keys["pmid"] = normalize_pmid(self.pmid)
        return keys


# --- Event payloads (schema 1). Written by `factory.services.seeds`, folded by `index.seeds`.


class SeedAdded(StrictModel):
    seed_id: str = Field(pattern=SEED_ID_RE)
    spec: SeedSpec
    decision_ids: tuple[DecisionId, ...] | None = None


class SeedResolved(StrictModel):
    seed_id: str = Field(pattern=SEED_ID_RE)
    work_id: str = Field(pattern=WORK_ID_RE)
    run_id: str = Field(pattern=RUN_ID_RE)


class SeedUnresolved(StrictModel):
    seed_id: str = Field(pattern=SEED_ID_RE)
    run_id: str | None = Field(default=None, pattern=RUN_ID_RE)
    reason: str = Field(min_length=1)


class SeedSplitDrawn(StrictModel):
    """The hold-out split of the positive seeds, with the seed it was drawn from.

    `development` and `held_out` partition the positives present when the split was drawn.
    """

    random_seed: int = Field(ge=0, lt=2**32)
    procedure: str = Field(min_length=1)
    development: tuple[str, ...]
    held_out: tuple[str, ...]


class SeedMissExplained(StrictModel):
    """Why a positive seed was not retrieved, and the admission route planned for it."""

    seed_id: str = Field(pattern=POSITIVE_SEED_ID_RE)
    reason: str = Field(min_length=1)
    route: ProvenanceMethod

    @model_validator(mode="after")
    def _route_is_not_the_database(self) -> Self:
        if self.route is ProvenanceMethod.DATABASE:
            raise ValueError("a miss is not explained by the database search itself")
        if self.route is ProvenanceMethod.SUPPLIED:
            # A search miss is remedied by admission; a supplied link is not a seed route.
            raise ValueError("a miss is not explained by a supplied link")
        return self

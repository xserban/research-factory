"""Event of a rendered level document (slice 8, plan A9): `document.rendered`.

A level (goal, questions, plan, seeds, probe, protocol) is rendered as Markdown from its decision
events. The Markdown is a content-addressed blob; the event holds the level, the version number
within that level (from 1, one more than the last render of the level), the ids of the events the
document was drawn from and the blob's ref. Nothing depends on this event: it is a record of what
was shown. Pure value types; written by `factory.services.develop_render`, folded by
`index.develop`.
"""

from __future__ import annotations

from pydantic import Field

from factory.model.base import StrictModel
from factory.model.decisions import DecisionLevel
from factory.model.identity import BLOB_REF_RE


class DocumentRendered(StrictModel):
    """One rendering of a level. `sources` are event ids, sorted and unique."""

    level: DecisionLevel
    version: int = Field(ge=1)
    sources: tuple[str, ...]
    blob: str = Field(pattern=BLOB_REF_RE)

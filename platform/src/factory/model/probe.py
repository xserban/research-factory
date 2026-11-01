"""Probe vocabulary: value types a probe reports, shared by services and events.

Probe payloads are added alongside the services that emit them. This module holds only the
types the vocabulary suggestions are written against.
"""

from __future__ import annotations

from factory.model.base import StrictModel


class TermSuggestion(StrictModel):
    """A phrase several missed seeds share and the query does not cover.

    `seeds` is the number of positive seeds that carry the phrase (missed or not), and `holders`
    their work ids in the order the seeds were given. Both are computed, never typed.
    """

    term: str
    seeds: int
    holders: tuple[str, ...]

"""Held-out identifiers and their scrubbing (R-20), for every agent-facing surface.

Declares: `WITHHELD`, `withhold`, `held_out_tokens`. A service that stores what it gives an agent
(the context pack) scrubs before it stores, so this lives below `mcp`. Read-only.

Invariant: only a held-out seed's own id and stated identifiers are tokens, unless the caller
asks for work ids; a tool that names works does not, since a `[withheld]` among work ids would
mark the work as a seed (decisions 37 item 9 and 81).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import JsonValue

from factory.model.seed import SeedSpec
from factory.services import seeds as seeds_service
from factory.services.context import Project
from factory.services.seeds import SeedRole

WITHHELD = "[withheld]"


def withhold(value: JsonValue, tokens: Iterable[str]) -> JsonValue:
    """`value` with every whole-identifier occurrence of a token replaced in its strings.

    Tokens match case-insensitively and only as whole identifiers, so `10.1000/p2` does not
    match inside `10.1000/p21`. An agent-facing response passes through this with the identifiers
    of every held-out seed (R-20); nothing else is changed.
    """
    cleaned = sorted({token for token in tokens if token}, key=len, reverse=True)
    if not cleaned:
        return value
    pattern = re.compile(
        r"(?<![0-9A-Za-z])(?:" + "|".join(re.escape(t) for t in cleaned) + r")(?![0-9A-Za-z])",
        re.IGNORECASE,
    )
    return _scrub(value, pattern)


def _scrub(value: JsonValue, pattern: re.Pattern[str]) -> JsonValue:
    if isinstance(value, str):
        return pattern.sub(WITHHELD, value)
    if isinstance(value, dict):
        return {key: _scrub(item, pattern) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, pattern) for item in value]
    return value


def held_out_tokens(project: Project, include_work_ids: bool = True) -> set[str]:
    """The id, and every identifier as stated or normalised, of each held-out seed.

    `include_work_ids` adds `seed.work_id`, for the seed tools and the probe. Any tool that names
    works leaves it out: a work's id is not a seed's identity, and a `[withheld]`
    among `rf:` ids would mark the work as a seed (decisions 37 item 9 and 81)."""
    tokens: set[str] = set()
    for seed in seeds_service.all_seeds(project):
        if seed.role is not SeedRole.HELD_OUT:
            continue
        stated = SeedSpec(
            kind=seed.kind,
            cite=seed.cite,
            doi=seed.doi,
            arxiv=seed.arxiv,
            openalex=seed.openalex,
        )
        tokens.add(seed.seed_id)
        tokens.update(stated.identity_keys().values())
        tokens.update(value for value in (seed.doi, seed.arxiv, seed.openalex) if value)
        if include_work_ids and seed.work_id:
            tokens.add(seed.work_id)
    return tokens

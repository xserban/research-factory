"""Held-out identifiers and their scrubbing (R-20), for every agent-facing surface.

Declares: `WITHHELD`, `withhold`, `held_out_tokens`, `seed_id_tokens`. A service that stores
what it gives an agent (the context pack) scrubs before it stores, so this lives below `mcp`.
Read-only.

Invariant: only a held-out seed's own id and stated identifiers are tokens, unless the caller
asks for work ids; a tool that names works does not, since a `[withheld]` among work ids would
mark the work as a seed (decisions 37 item 9 and 81).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from pydantic import JsonValue
from sqlalchemy import bindparam, text

from factory.model.seed import SeedSpec, normalize_openalex
from factory.services import seeds as seeds_service
from factory.services.context import Project
from factory.services.seeds import SeedRole

WITHHELD = "[withheld]"


def withhold(value: JsonValue, tokens: Iterable[str], same_length: bool = False) -> JsonValue:
    """`value` with every whole-identifier occurrence of a token replaced in its strings.

    Tokens match case-insensitively and only as whole identifiers, so `10.1000/p2` does not
    match inside `10.1000/p21`. An agent-facing response passes through this with the identifiers
    of every held-out seed (R-20); nothing else is changed. With `same_length` each match is
    replaced by as many `#` as it has characters, so offsets into the text stay exact.
    """
    cleaned = sorted({token for token in tokens if token}, key=len, reverse=True)
    if not cleaned:
        return value
    pattern = re.compile(
        r"(?<![0-9A-Za-z])(?:" + "|".join(re.escape(t) for t in cleaned) + r")(?![0-9A-Za-z])",
        re.IGNORECASE,
    )
    return _scrub(value, pattern, same_length)


def _scrub(value: JsonValue, pattern: re.Pattern[str], same_length: bool = False) -> JsonValue:
    if isinstance(value, str):
        if same_length:
            return pattern.sub(lambda m: "#" * len(m.group(0)), value)
        return pattern.sub(WITHHELD, value)
    if isinstance(value, dict):
        return {key: _scrub(item, pattern, same_length) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, pattern, same_length) for item in value]
    return value


def held_out_tokens(project: Project, include_work_ids: bool = True) -> set[str]:
    """The id, and every identifier as stated or normalised, of each held-out seed.

    `include_work_ids` adds `seed.work_id` and the OpenAlex id (as stored and normalised) of the
    work the seed resolved to, for the seed tools and the probe (IDEA-19). Any tool that names
    works leaves it out: a work's id is not a seed's identity, and a `[withheld]`
    among `rf:` ids would mark the work as a seed (decisions 37 item 9 and 81)."""
    tokens: set[str] = set()
    resolved_of: list[str] = []
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
            resolved_of.append(seed.work_id)
    for resolved in _resolved_openalex(project, resolved_of):
        tokens.update((resolved, normalize_openalex(resolved)))
    return tokens


def seed_id_tokens(project: Project) -> set[str]:
    """The id of each held-out seed, and nothing else.

    Invariant: no DOI, arXiv id, OpenAlex id or `rf:` work id is a token. For the feed tools,
    which are not seed tools: a feed entry that is a held-out seed's paper shows its stated
    identifiers like any paper's (researcher ruling 2026-11-14; decisions 37 item 9, 81 and 123).
    The seed's own id (`SEED<n>`) stays a token: it names the seed, not a paper, and no feed
    entry carries one."""
    return {
        seed.seed_id for seed in seeds_service.all_seeds(project) if seed.role is SeedRole.HELD_OUT
    }


def _resolved_openalex(project: Project, work_ids: list[str]) -> list[str]:
    """The non-blank OpenAlex ids stored on `work_ids`, read in one query of the `works` table
    (no provenance is loaded). A work that is absent or has no OpenAlex id adds nothing."""
    if not work_ids:
        return []
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT data FROM works WHERE work_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": work_ids},
        ).all()
    found: list[str] = []
    for (data,) in rows:
        identifiers = json.loads(str(data)).get("identifiers") or {}
        value = identifiers.get("openalex") if isinstance(identifiers, dict) else None
        if isinstance(value, str) and value.strip():
            found.append(value)
    return found

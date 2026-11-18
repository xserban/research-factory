"""Resolve a selection of papers to the works a chat will read (plan chat, T1).

A `SelectionSpec` names a population, optional layers, and explicit includes and excludes. The
result lists the works kept, each with its default conversion and size, and the works left out with
the reason.

Invariants:
- Read-only: no event is written. The index is synced before reading.
- Validated at the boundary: an unknown layer (not a layer of the project's current layer scheme)
  is refused on field `layers` before anything is read.
- `include` and `exclude` ids pass the shared work-id resolver (IDEA-66): an NFC-different
  spelling of a stored id names that work; one matching several works is refused on that field.
- `works` and `excluded` are sorted by work id; a work appears in at most one of them.
- A work is kept only with a default conversion; one without goes to `excluded` as
  `no-conversion`. An `include` id that is no work of the project goes to `excluded` as
  `unknown-work`; an explicitly excluded work is listed as `excluded` when it was otherwise
  selected.
- `chars` is the sum of the characters of the canonical Markdown of the kept conversions;
  `est_tokens` is an estimate only (`chars // CHARS_PER_TOKEN`).
- `resolve_selection_cached` reuses a result for the same spec in the same project while the event
  log is unchanged: the key is the canonical JSON of the spec and the project directory, the
  validity check is the log signature (total size and newest modification time of the event
  files). Any appended event changes the size, so it ends the cache; nothing else does, and a
  result is never older than the log it was read from. The cache is per process and holds
  `CACHE_ENTRIES` results at most (oldest dropped first).
- `digest` is the sha256 of the canonical JSON of the sorted `[work_id, conversion_id]` pairs, so
  it does not depend on input order and changes when a conversion changes.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass

from pydantic import Field, JsonValue
from sqlalchemy import text

from factory.canonical import canonical_json
from factory.events.reader import event_files
from factory.errors import FactoryValidationError, ValidationIssue
from factory.mining.spec import Population
from factory.model.base import StrictModel
from factory.services.context import Project
from factory.services.conversions import conversion_of
from factory.services.document_read import default_conversions
from factory.services.mining import population_works
from factory.services.reference_layers import current_scheme
from factory.services.work_layers import layers_for
from factory.services.work_ref import resolve_work_ids

__all__ = [
    "CACHE_ENTRIES",
    "CHARS_PER_TOKEN",
    "SelectedWork",
    "Selection",
    "SelectionSpec",
    "event_log_signature",
    "resolve_selection",
    "resolve_selection_cached",
]

CHARS_PER_TOKEN = 4
"""Characters per token used for `est_tokens`. A rough estimate, not a tokeniser count."""


class SelectionSpec(StrictModel):
    """Which works a chat reads: the works of `population`, restricted to `layers` when given,
    plus `include` (known works, even outside the population), minus `exclude`."""

    layers: list[str] = Field(default_factory=list)
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    population: Population = Population.INCLUDED_FT


@dataclass(frozen=True)
class SelectedWork:
    """One kept work with the conversion a chat reads and its size in characters."""

    work_id: str
    document_id: str
    conversion_id: str
    chars: int


@dataclass(frozen=True)
class Selection:
    """The resolved selection (see the module invariants)."""

    works: tuple[SelectedWork, ...]
    excluded: tuple[tuple[str, str], ...]
    chars: int
    est_tokens: int
    digest: str


def _known_layers(project: Project) -> set[str]:
    scheme = current_scheme(project)
    return set() if scheme is None else {d.id for d in scheme.layers}


def _is_work(project: Project, work_id: str) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(text("SELECT 1 FROM works WHERE work_id = :w"), {"w": work_id}).first()
    return row is not None


def _markdown_chars(project: Project, conversion_id: str) -> int:
    conversion = conversion_of(project, conversion_id)
    if conversion is None:
        raise FactoryValidationError(
            [ValidationIssue("conversion_id", f"{conversion_id}: unknown conversion")]
        )
    return len(project.library.get(conversion.markdown_hash).decode("utf-8"))


def resolve_selection(project: Project, spec: SelectionSpec) -> Selection:
    """Resolve `spec` to the kept works and the left-out ones. Read-only; see the module
    invariants. Raises `FactoryValidationError` on field `layers` for an unknown layer."""
    project.index.sync()
    unknown = sorted(set(spec.layers) - _known_layers(project))
    if unknown:
        raise FactoryValidationError(
            [ValidationIssue("layers", f"unknown layer: {', '.join(unknown)}")]
        )

    base = list(population_works(project, spec.population))
    if spec.layers:
        wanted = set(spec.layers)
        found = layers_for(project, base)
        base = [w for w in base if w in found and found[w].layer in wanted]
    candidates = set(base)
    excluded: dict[str, str] = {}
    for work in resolve_work_ids(project, spec.include, field="include"):
        if work in candidates:
            continue
        if _is_work(project, work):
            candidates.add(work)
        else:
            excluded[work] = "unknown-work"
    for work in resolve_work_ids(project, spec.exclude, field="exclude"):
        if work in candidates:
            candidates.discard(work)
            excluded[work] = "excluded"

    ordered = sorted(candidates)
    conversions = default_conversions(project, ordered)
    works: list[SelectedWork] = []
    for work in ordered:
        ref = conversions.get(work)
        if ref is None:
            excluded[work] = "no-conversion"
            continue
        works.append(
            SelectedWork(
                work,
                ref.document_id,
                ref.conversion_id,
                _markdown_chars(project, ref.conversion_id),
            )
        )
    pairs: list[JsonValue] = [[w.work_id, w.conversion_id] for w in works]
    total = sum(w.chars for w in works)
    return Selection(
        works=tuple(works),
        excluded=tuple(sorted(excluded.items())),
        chars=total,
        est_tokens=total // CHARS_PER_TOKEN,
        digest=hashlib.sha256(canonical_json(pairs)).hexdigest(),
    )


CACHE_ENTRIES = 16
"""The most results `resolve_selection_cached` keeps."""

_CACHE: dict[tuple[str, bytes], tuple[tuple[int, float], Selection]] = {}
_CACHE_LOCK = threading.Lock()


def event_log_signature(project: Project) -> tuple[int, float]:
    """(total size, newest modification time) of the project's event files."""
    size, newest = 0, 0.0
    for path in event_files(project.paths.events_dir):
        try:
            stat = path.stat()
        except OSError:
            continue
        size += stat.st_size
        newest = max(newest, stat.st_mtime)
    return size, newest


def resolve_selection_cached(project: Project, spec: SelectionSpec) -> Selection:
    """`resolve_selection`, reused while the event log is unchanged (see the module invariants).
    A refused spec raises as `resolve_selection` does and is not cached."""
    key = (str(project.paths.dir), canonical_json(spec.model_dump(mode="json")))
    signature = event_log_signature(project)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == signature:
            return hit[1]
    fresh = resolve_selection(project, spec)
    with _CACHE_LOCK:
        _CACHE.pop(key, None)
        _CACHE[key] = (signature, fresh)
        while len(_CACHE) > CACHE_ENTRIES:
            del _CACHE[next(iter(_CACHE))]
    return fresh

"""A persistent, derived cache of the lead engine's two slow scans (candidates; accepted quote
verdicts), so `factory leads candidates|queue` is not cold in every process.

Invariants:
- DERIVED: never an event, never a table in the index, never authoritative; safe to delete at any
  time (the next call recomputes). Files live only under `projects/<slug>/cache/lead-engine/`.
- Candidates entry key: project slug, last folded event id, `code_version()` (a hash of the source
  files the result depends on) and the parameters that change the result. A new event, a code
  change or other parameters is a miss, never a stale hit; an entry is stored only when no event
  arrived during the scan.
- The stale-row ledger of a miner scope (the slowest read of a queue call) is stored the same way,
  keyed by scope, last event and code version.
- The verdict file holds only ACCEPTED verdicts (negatives are never cached, as in the in-process
  `_VERIFIED` memo). Its ids hash the row, its conversion's markdown hash, the quote and the
  anchor, so a verdict cannot outlive a change of the text it checked; it is valid for one code
  version.
- Readers take no lock and ignore a file that is unreadable, partial, of another format or does
  not match the key. Writers write a temp file and rename it (atomic); concurrent writers cannot
  corrupt a file (the last rename wins, a lost entry is recomputed). Size is bounded: the newest
  `KEEP` candidate entries per project and `MAX_VERIFIED` verdict ids.
- The cache stores the unmasked service output; the MCP layer masks held-out identifiers on every
  reply, cached or computed.
- `FACTORY_LEAD_CACHE=off` (or 0, false, no) disables reading and writing.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import threading
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from factory.model.lead_engine import Candidates
from factory.services.context import Project

__all__ = [
    "KEEP",
    "MAX_VERIFIED",
    "Slot",
    "candidate_params",
    "clear",
    "code_version",
    "enabled",
    "slot",
    "stale_get",
    "stale_put",
    "verified_add",
    "verified_id",
    "verified_load",
]

FORMAT = 1
KEEP = 6
KEEP_STALE = 16
MAX_VERIFIED = 200_000
ENV = "FACTORY_LEAD_CACHE"
_CODE_MODULES = (
    "factory.services.lead_cache",
    "factory.services.lead_candidates",
    "factory.services.lead_queue",
    "factory.services.technique_graph",
    "factory.services.chat_read",
    "factory.services.extraction",
    "factory.services.mining",
    "factory.services.work_layers",
    "factory.services.claims_digest",
    "factory.services.paper_profile",
    "factory.model.lead_engine",
    "factory.model.technique_graph",
)
_code: str | None = None
_WRITE = threading.Lock()


def enabled() -> bool:
    """False when `FACTORY_LEAD_CACHE` is off, 0, false or no."""
    return os.environ.get(ENV, "").strip().lower() not in {"off", "0", "false", "no"}


def code_version() -> str:
    """Hash of the contents of the source files the cached results depend on (once per process)."""
    global _code
    if _code is None:
        digest = hashlib.sha256()
        for name in _CODE_MODULES:
            path = getattr(importlib.import_module(name), "__file__", None)
            digest.update(name.encode())
            if path:
                digest.update(Path(path).read_bytes())
        _code = digest.hexdigest()[:20]
    return _code


def _dir(project: Project) -> Path:
    return project.paths.dir / "cache" / "lead-engine"


def candidate_params(
    *, sources: Iterable[str], per_source: int, layer: str, min_works: int, max_co_works: int
) -> dict[str, Any]:
    """The parameters of a candidates call that change its result, in a canonical form."""
    return {
        "sources": sorted(set(sources)),
        "per_source": per_source,
        "layer": layer,
        "technique_min_works": min_works,
        "max_co_works": max_co_works,
    }


def _write(path: Path, data: Mapping[str, Any]) -> None:
    """Atomic: a temp file in the same folder, then a rename; failures leave the cache as it was."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return None
    return data


def clear(project: Project) -> None:
    """Delete every entry of the project (the `--refresh` path); nothing else is touched."""
    folder = _dir(project)
    try:
        names = list(folder.iterdir())
    except OSError:
        return
    for path in names:
        if path.suffix == ".json" or path.suffix == ".tmp":
            path.unlink(missing_ok=True)


def _prune(folder: Path, prefix: str = "cand-", keep: int = KEEP) -> None:
    try:
        entries = sorted(
            folder.glob(f"{prefix}*.json"),
            key=lambda p: (p.stat().st_mtime_ns, p.name),
            reverse=True,
        )
    except OSError:
        return
    for stale in entries[keep:]:
        stale.unlink(missing_ok=True)


@dataclass
class Slot:
    """One candidates call's place in the cache; `head` is None when the cache is not in use."""

    project: Project
    params: dict[str, Any]
    head: str | None

    def _path(self) -> Path:
        assert self.head is not None
        key = json.dumps([self.project.paths.slug, self.head, code_version(), self.params])
        return _dir(self.project) / f"cand-{hashlib.sha256(key.encode()).hexdigest()[:24]}.json"

    def _meta(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "slug": self.project.paths.slug,
            "head": self.head,
            "code": code_version(),
            "params": self.params,
        }

    def get(self) -> Candidates | None:
        """The stored result for this key, or None (a miss, or any file that does not match)."""
        if self.head is None:
            return None
        data = _read(self._path())
        if data is None:
            return None
        meta = self._meta()
        if any(data.get(k) != v for k, v in meta.items()):
            return None
        try:
            return Candidates.model_validate(data["payload"])
        except (KeyError, ValueError):
            return None

    def put(self, result: Candidates) -> Candidates:
        """Store `result` unless an event arrived since the slot was taken; returns `result`."""
        if self.head is not None and self.project.index.last_event_id() == self.head:
            payload = result.model_dump(mode="json", by_alias=True)
            with _WRITE:
                _write(self._path(), {**self._meta(), "payload": payload})
                _prune(_dir(self.project))
        return result


def slot(project: Project, params: dict[str, Any], *, refresh: bool = False) -> Slot:
    """The cache slot of a candidates call: syncs the index to take the head; with `refresh` the
    project's entries are deleted first; off or on an empty index the slot never hits or stores."""
    if not enabled():
        return Slot(project, params, None)
    if refresh:
        clear(project)
    project.index.sync()
    return Slot(project, params, project.index.last_event_id())


def _stale_path(project: Project, scope: str, head: str) -> Path:
    key = json.dumps([project.paths.slug, scope, head, code_version()])
    return _dir(project) / f"stale-{hashlib.sha256(key.encode()).hexdigest()[:24]}.json"


def stale_get(project: Project, scope: str, head: str | None) -> frozenset[str] | None:
    """The stored stale-row ledger of a miner scope at `head`, or None (off, miss or damage)."""
    if head is None or not enabled():
        return None
    data = _read(_stale_path(project, scope, head))
    ids = None if data is None else data.get("ids")
    meta = {"slug": project.paths.slug, "scope": scope, "head": head, "code": code_version()}
    if data is None or not isinstance(ids, list) or any(data.get(k) != v for k, v in meta.items()):
        return None
    return frozenset(i for i in ids if isinstance(i, str))


def stale_put(project: Project, scope: str, head: str | None, ids: Iterable[str]) -> None:
    """Store a stale-row ledger unless an event arrived since `head` was read."""
    if head is None or not enabled() or project.index.last_event_id() != head:
        return
    data = {
        "format": FORMAT,
        "slug": project.paths.slug,
        "scope": scope,
        "head": head,
        "code": code_version(),
        "ids": sorted(set(ids)),
    }
    with _WRITE:
        _write(_stale_path(project, scope, head), data)
        _prune(_dir(project), "stale-", KEEP_STALE)


def verified_id(key: tuple[str, ...]) -> str:
    """The stable id of an in-process verdict key."""
    return hashlib.sha256("\x1f".join(key).encode()).hexdigest()[:32]


def _verified_path(project: Project) -> Path:
    return _dir(project) / "verified.json"


def verified_load(project: Project) -> frozenset[str]:
    """The persisted accepted verdict ids of this code version (empty when off or unreadable)."""
    if not enabled():
        return frozenset()
    data = _read(_verified_path(project))
    if data is None or data.get("code") != code_version():
        return frozenset()
    ids = data.get("ids")
    if not isinstance(ids, list):
        return frozenset()
    return frozenset(i for i in ids if isinstance(i, str))


def verified_add(project: Project, ids: Iterable[str]) -> None:
    """Add accepted verdict ids (never negatives), bounded by `MAX_VERIFIED`."""
    new = set(ids)
    if not new or not enabled():
        return
    with _WRITE:
        merged = set(verified_load(project)) | new
        if len(merged) > MAX_VERIFIED:
            merged = new
        _write(
            _verified_path(project),
            {"format": FORMAT, "code": code_version(), "ids": sorted(merged)},
        )

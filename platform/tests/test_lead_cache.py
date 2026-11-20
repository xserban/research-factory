"""The persistent lead engine cache: derived, keyed, bounded, tolerant of damage."""

# ruff: noqa: F811
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.mcp import server as mcp_server
from factory.model.lead_engine import Candidates
from factory.services import lead_cache
from factory.services import lead_candidates as lc
from factory.services.context import Project
from factory.services.lead_candidates import lead_candidates
from factory.services.lead_queue import lead_queue
from factory.services.seeds import SeedRole, all_seeds
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.helpers import open_session
from tests.lead_engine_helpers import engine_world, mine_claims
from tests.test_mcp_lead_engine_heldout import _candidate

KNOBS: dict[str, Any] = {"layer": "all", "technique_min_works": 1}


@pytest.fixture(autouse=True)
def _cache_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(lead_cache.ENV, raising=False)


@pytest.fixture
def built(project: Project, agent: Actor, human: Actor, world: list[str]) -> Project:
    engine_world(project, agent, human, world)
    return project


def _entries(project: Project) -> list[Path]:
    return sorted((project.paths.dir / "cache" / "lead-engine").glob("cand-*.json"))


def _count_scans(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    real = lc.tg.read_inputs

    def spy(project: Project) -> Any:
        calls.append(1)
        return real(project)

    monkeypatch.setattr(lc.tg, "read_inputs", spy)
    return calls


def test_miss_then_hit_equals_computed(built: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _count_scans(monkeypatch)
    first = lead_candidates(built, **KNOBS)
    assert len(calls) == 1 and len(_entries(built)) == 1 and first.candidates
    second = lead_candidates(built, **KNOBS)
    assert len(calls) == 1  # served from disk
    assert second == first
    assert second.model_dump_json(by_alias=True) == first.model_dump_json(by_alias=True)
    lead_cache.clear(built)
    assert lead_candidates(built, **KNOBS) == first


def test_round_trip_through_the_model(built: Project) -> None:
    found = lead_candidates(built, **KNOBS)
    data = json.loads(_entries(built)[0].read_text())
    assert Candidates.model_validate(data["payload"]) == found
    assert data["slug"] == built.paths.slug and data["head"] == built.index.last_event_id()


def test_a_new_event_invalidates(
    project: Project,
    agent: Actor,
    human: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordered = engine_world(project, agent, human, world, claims=False)
    first = lead_candidates(project, **KNOBS)
    calls = _count_scans(monkeypatch)
    mine_claims(project, agent, ordered)  # new events
    second = lead_candidates(project, **KNOBS)
    assert len(calls) == 1 and len(_entries(project)) == 2
    assert second != first  # the claims source now yields candidates


def test_code_version_change_is_a_miss(built: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    lead_candidates(built, **KNOBS)
    calls = _count_scans(monkeypatch)
    monkeypatch.setattr(lead_cache, "_code", "another-version")
    lead_candidates(built, **KNOBS)
    assert len(calls) == 1


def test_code_version_hashes_the_sources() -> None:
    assert lead_cache.code_version() == lead_cache.code_version()
    assert len(lead_cache.code_version()) == 20


@pytest.mark.parametrize("damage", ["", "{", "[1]", '{"format": 99}', "\x00\x01"])
def test_damaged_file_is_ignored_and_rewritten(
    built: Project, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    first = lead_candidates(built, **KNOBS)
    path = _entries(built)[0]
    path.write_text(damage)
    calls = _count_scans(monkeypatch)
    assert lead_candidates(built, **KNOBS) == first
    assert len(calls) == 1
    assert Candidates.model_validate(json.loads(path.read_text())["payload"]) == first


def test_a_payload_that_does_not_validate_is_a_miss(
    built: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = lead_candidates(built, **KNOBS)
    path = _entries(built)[0]
    data = json.loads(path.read_text())
    data["payload"] = {"candidates": "nope"}
    path.write_text(json.dumps(data))
    calls = _count_scans(monkeypatch)
    assert lead_candidates(built, **KNOBS) == first and len(calls) == 1


def test_mismatched_meta_is_a_miss(built: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    lead_candidates(built, **KNOBS)
    path = _entries(built)[0]
    data = json.loads(path.read_text())
    data["head"] = "evt_other"
    path.write_text(json.dumps(data))
    calls = _count_scans(monkeypatch)
    lead_candidates(built, **KNOBS)
    assert len(calls) == 1


def test_other_parameters_are_other_entries(
    built: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    lead_candidates(built, **KNOBS)
    calls = _count_scans(monkeypatch)
    lead_candidates(built, **{**KNOBS, "per_source": 3})
    lead_candidates(built, **{**KNOBS, "layer": "core"})
    lead_candidates(built, sources=("claims-limitation",), **KNOBS)
    assert len(_entries(built)) == 4
    lead_candidates(built, **{**KNOBS, "per_source": 3})
    # claims-only never reads the technique inputs
    assert len(calls) == 2


def test_the_claims_grouping_mode_is_part_of_the_key(built: Project) -> None:
    grouped = lead_candidates(built, **KNOBS)
    ungrouped = lead_candidates(built, group_claims_by_work=False, **KNOBS)
    assert len(_entries(built)) == 2
    assert grouped.parameters["group_claims_by_work"] == 1
    assert ungrouped.parameters["group_claims_by_work"] == 0
    # a repeat of each call is served from its own entry, not the other mode's
    assert lead_candidates(built, **KNOBS) == grouped
    assert lead_candidates(built, group_claims_by_work=False, **KNOBS) == ungrouped


def test_source_order_does_not_matter(built: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    lead_candidates(built, sources=("technique-gap", "technique-challenge"), **KNOBS)
    calls = _count_scans(monkeypatch)
    lead_candidates(built, sources=("technique-challenge", "technique-gap"), **KNOBS)
    assert not calls


def test_refresh_recomputes_and_rewrites(built: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    first = lead_candidates(built, **KNOBS)
    calls = _count_scans(monkeypatch)
    assert lead_candidates(built, refresh=True, **KNOBS) == first
    assert len(calls) == 1 and len(_entries(built)) == 1


def test_off_neither_reads_nor_writes(built: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(lead_cache.ENV, "off")
    calls = _count_scans(monkeypatch)
    lead_candidates(built, **KNOBS)
    lead_candidates(built, **KNOBS)
    assert len(calls) == 2 and not (built.paths.dir / "cache").exists()
    lead_queue(built, **KNOBS)
    assert not (built.paths.dir / "cache").exists()


def test_the_cache_is_bounded(built: Project) -> None:
    for n in range(1, lead_cache.KEEP + 4):
        lead_candidates(built, per_source=n, **KNOBS)
    assert len(_entries(built)) == lead_cache.KEEP


def test_nothing_is_written_outside_the_cache_folder(built: Project) -> None:
    before = {p for p in built.paths.dir.rglob("*") if p.is_file()}
    lead_queue(built, **KNOBS)
    new = {p for p in built.paths.dir.rglob("*") if p.is_file()} - before
    assert all("cache/lead-engine" in str(p) for p in new if ".index" not in str(p))


def test_concurrent_writers_leave_valid_files(built: Project) -> None:
    found = lead_candidates(built, **KNOBS)
    errors: list[BaseException] = []

    def write() -> None:
        try:
            for _ in range(15):
                lead_cache.slot(built, {"k": 1}).put(found)
                lead_cache.verified_add(built, ["a", "b"])
        except BaseException as err:
            errors.append(err)

    threads = [threading.Thread(target=write) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    for path in _entries(built):
        assert json.loads(path.read_text())["format"] == lead_cache.FORMAT
    assert lead_cache.verified_load(built) >= {"a", "b"}
    folder = built.paths.dir / "cache" / "lead-engine"
    assert not list(folder.glob("*.tmp"))


def test_verdicts_persist_and_only_accepted_ones(
    built: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = lead_queue(built, **KNOBS)
    persisted = lead_cache.verified_load(built)
    assert persisted  # the world's quotes are verbatim
    from factory.services import lead_queue as lq

    lq._VERIFIED.clear()
    asked: list[int] = []
    real = lq.chat_verify

    def spy(project: Project, items: Any) -> Any:
        asked.append(len(items))
        return real(project, items)

    monkeypatch.setattr(lq, "chat_verify", spy)
    again = lead_queue(built, **KNOBS)
    assert not asked  # a new process: only the disk holds the verdicts
    assert again.model_dump_json(by_alias=True) == first.model_dump_json(by_alias=True)
    monkeypatch.setattr(lead_cache, "_code", "other")
    assert lead_cache.verified_load(built) == frozenset()


def test_negative_verdicts_are_never_stored(built: Project) -> None:
    lead_cache.verified_add(built, [])
    path = built.paths.dir / "cache" / "lead-engine" / "verified.json"
    assert not path.exists() or json.loads(path.read_text())["ids"] == []


@pytest.mark.anyio
async def test_a_cached_reply_is_still_masked(
    settings: Settings,
    built: Project,
    clock: FixedClock,
) -> None:
    [held, *_] = [s for s in all_seeds(built) if s.role is SeedRole.HELD_OUT]
    ids = [i for i in (held.seed_id, held.doi, held.arxiv, held.openalex) if i]
    cand = _candidate(ids, held.work_id or "rf:keepme")
    params = lead_cache.candidate_params(
        sources=lc.SOURCES, per_source=20, layer="core", min_works=3, max_co_works=0
    )
    lead_cache.slot(built, params).put(Candidates(parameters={}, totals={}, candidates=(cand,)))
    async with open_session(settings, clock) as client:
        out = await client.call("lead_candidates", project="demo")
    assert out["ok"] is True, out
    text = json.dumps(out)
    assert "rf:keepme" in text or held.work_id in text or "technique-gap" in text
    for ident in ids:
        assert ident not in text, ident
    assert "[withheld]" in text
    assert mcp_server is not None


def test_the_stale_ledger_persists_and_follows_the_head(
    built: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services import lead_queue as lq

    first = lead_queue(built, **KNOBS)
    folder = built.paths.dir / "cache" / "lead-engine"
    assert list(folder.glob("stale-*.json"))
    lq._STALE.clear()
    calls: list[int] = []
    real = lq.stale_extractions

    def spy(*a: Any, **k: Any) -> Any:
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(lq, "stale_extractions", spy)
    again = lead_queue(built, **KNOBS)
    assert not calls
    assert again.model_dump_json(by_alias=True) == first.model_dump_json(by_alias=True)
    assert lead_cache.stale_get(built, "m-claims", "evt_other") is None
    lq._STALE.clear()
    lead_queue(built, refresh=True, **KNOBS)
    assert calls  # refresh recomputed it

"""The portfolio builder: one row per project, every count derived, nothing written, failures
isolated, nothing agent-withheld in the JSON (spec 7a acceptance 1-6, rulings 3, 6-8).

The three fixture projects are built once per session and copied per test (see `build_world`).
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from factory.clock import FixedClock
from factory.config import Settings
from factory.services.context import Project, list_projects
from factory.services.human_queue import Gate
from factory.services.portfolio import (
    Portfolio,
    Stage,
    derive_stage,
    portfolio,
    stage_facts,
)
from factory.services.prisma import prisma_flow
from factory.services.project import ProjectStatus, init_project, project_status
from factory.services.search import list_works
from factory.services.seeds import all_seeds
from tests.helpers import SESSION, T0
from tests.portfolio_helpers import EXT_SLUG, SCOPING_SLUG, TA_SLUG, fresh

AS_OF = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
FORBIDDEN_KEY_WORDS = {"kappa", "rate", "recall", "sensitivity", "specificity"}


def _build(settings: Settings) -> Portfolio:
    return portfolio(settings, clock=FixedClock(T0), as_of=AS_OF)


def _event_hashes(settings: Settings) -> dict[str, str]:
    return {
        str(path.relative_to(settings.root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(settings.root.glob("projects/*/events/**/*"))
        if path.is_file()
    }


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_rows_sorted_with_stages_and_human_items(portfolio_settings: Settings) -> None:
    built = _build(portfolio_settings)
    assert built.schema_version == 1
    assert built.generated_at == AS_OF
    assert [row.slug for row in built.projects] == [TA_SLUG, EXT_SLUG, SCOPING_SLUG]
    ta, ext, scoping = built.projects
    assert ta.stage is Stage.TA_SCREENING
    ta_gates = {item.gate for item in ta.human.items}
    assert Gate.SCREENING_DISAGREEMENTS in ta_gates
    assert Gate.CALIBRATION_LABELS in ta_gates
    # The fixture leaves one promoted work without a document, so the first matching row is full
    # text; the extraction audit is waiting on the human all the same.
    facts = stage_facts(fresh(portfolio_settings, EXT_SLUG, FixedClock(T0)))
    assert facts.extraction_schema
    assert ext.stage is derive_stage(facts)
    assert Gate.EXTRACTION_AUDIT in {item.gate for item in ext.human.items}
    assert scoping.stage is Stage.SCOPING
    assert scoping.human.items == []
    assert [row.error for row in built.projects] == [None, None, None]


def test_counts_equal_the_projects_own_reports(portfolio_settings: Settings) -> None:
    clock = FixedClock(T0)
    for row in _build(portfolio_settings).projects:
        project = fresh(portfolio_settings, row.slug, clock)
        status = project_status(project)
        flow = prisma_flow(project)
        assert row.rigor_mode is status.rigor_mode
        assert row.works == status.works == len(list_works(project))
        assert (row.tasks_open, row.tasks_claimed, row.tasks_expired) == (
            status.tasks.open,
            status.tasks.claimed,
            status.tasks.expired,
        )
        assert row.ta_included == flow.included
        assert row.ft_included == flow.full_text.included
        assert row.last_event_at == status.last_event_at
        assert row.human == status.human
        assert row.question_id == status.question
        if status.protocol is None:
            assert row.protocol_id is None and row.protocol_status is None
        else:
            assert row.protocol_id == status.protocol.protocol_id
            assert row.protocol_status is status.protocol.status
            assert row.press == status.protocol.press


def test_last_search_is_the_latest_finished_search_run(portfolio_settings: Settings) -> None:
    ta, ext, scoping = _build(portfolio_settings).projects
    assert ta.last_search_at is not None and ext.last_search_at is not None
    assert scoping.last_search_at is None


def test_portfolio_writes_no_event(portfolio_settings: Settings) -> None:
    before = _event_hashes(portfolio_settings)
    assert before
    _build(portfolio_settings)
    assert _event_hashes(portfolio_settings) == before


def test_corrupt_project_isolated(portfolio_settings: Settings) -> None:
    clock = FixedClock(T0)
    bad = init_project(portfolio_settings, "delta-corrupt", "pilot", session=SESSION, clock=clock)
    log = next(bad.paths.events_dir.glob("*/*.jsonl"))
    with log.open("a", encoding="utf-8") as handle:
        handle.write("{this is not json\n")
    built = _build(portfolio_settings)
    by_slug = {row.slug: row for row in built.projects}
    assert set(by_slug) == set(list_projects(portfolio_settings))
    broken = by_slug["delta-corrupt"]
    assert broken.error is not None and broken.error.isidentifier()  # a class name, no message
    assert broken.stage is None
    assert all(by_slug[s].error is None for s in (TA_SLUG, EXT_SLUG, SCOPING_SLUG))
    assert by_slug[TA_SLUG].stage is Stage.TA_SCREENING


def test_json_carries_no_sensitive_values(portfolio_settings: Settings) -> None:
    dumped = _build(portfolio_settings).model_dump_json()
    clock = FixedClock(T0)
    secrets: set[str] = set()
    for slug in list_projects(portfolio_settings):
        project = fresh(portfolio_settings, slug, clock)
        secrets |= {work.title for work in list_works(project)}
        for seed in all_seeds(project):
            secrets |= {seed.seed_id, seed.cite}
            secrets |= {seed.work_id} if seed.work_id else set()
    assert secrets
    assert not [s for s in secrets if s and s in dumped]
    for key in _keys(json.loads(dumped)):
        assert not set(key.lower().split("_")) & FORBIDDEN_KEY_WORDS, key


def test_deterministic_across_calls_and_rebuild(portfolio_settings: Settings) -> None:
    first = _build(portfolio_settings).model_dump_json()
    assert _build(portfolio_settings).model_dump_json() == first
    clock = FixedClock(T0)
    for slug in list_projects(portfolio_settings):
        fresh(portfolio_settings, slug, clock).index.rebuild()
    assert _build(portfolio_settings).model_dump_json() == first


def test_no_projects_gives_an_empty_portfolio(tmp_path: Path) -> None:
    built = portfolio(Settings(root=tmp_path, user="obd"), clock=FixedClock(T0), as_of=AS_OF)
    assert built.projects == []


def test_database_and_os_errors_isolate_one_project(
    portfolio_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import factory.services.portfolio as module

    real = module.project_status

    def flaky(project: Project) -> ProjectStatus:
        if project.paths.slug == TA_SLUG:
            raise OperationalError("select 1", {}, Exception("database is locked"))
        if project.paths.slug == EXT_SLUG:
            raise PermissionError("unreadable")
        return real(project)

    monkeypatch.setattr(module, "project_status", flaky)
    by_slug = {row.slug: row for row in _build(portfolio_settings).projects}
    assert by_slug[TA_SLUG].error == "OperationalError"
    assert by_slug[EXT_SLUG].error == "PermissionError"
    assert by_slug[SCOPING_SLUG].error is None
    assert by_slug[SCOPING_SLUG].stage is Stage.SCOPING

"""The import_status and import_coverage MCP tools and the CLI coverage command (Import-C task 3).

Held-out records are resolved like any corpus work (spec ruling 23); what stays hidden is which
records, and how many, are held out (decision 43). Every record and work is invented.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.imports.model import ImportFormat
from factory.model.imports import ImportRole
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.coverage import coverage_report
from factory.services.import_resolve import resolve_import
from factory.services.imports import list_import_records, record_import
from factory.services.screening import open_pass
from tests.helpers import SourcesFor, _setup, open_session, ready_protocol
from tests.import_helpers import bib_entry
from tests.references_service_helpers import Lookups, oa_item
from tests.test_cli import _cli_env, runner
from tests.test_screening_next import _draw

AGENT = {"role": "referencer", "model": "claude-sonnet-5-5", "skill": "rf-screen"}
N = 12


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


@pytest.fixture
def split_import(
    project: Project, agent: Actor, human: Actor, mock_sources: SourcesFor, tmp_path: Path
) -> str:
    """A ready protocol, no search yet, and a resolved reference import with a drawn split."""
    ready_protocol(project, agent, human, mock_sources)
    entries = [
        bib_entry(
            f"z{k}",
            f"Zebra Moss Mapping Study {k}",
            year=2018,
            author="Kim, Ana",
            doi=f"10.7777/z.{k}",
        )
        for k in range(1, N + 1)
    ]
    path = tmp_path / "split.bib"
    path.write_text("".join(entries))
    summary = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=7
    )
    lookups = Lookups(
        openalex=[
            oa_item(
                f"Zebra Moss Mapping Study {k}", "Ana Kim", 2018, f"W7{k:02d}", doi=f"10.7777/z.{k}"
            )
            for k in range(1, N + 1)
        ]
    )
    resolve_import(project, summary.import_id, sources=lookups.sources())
    return summary.import_id


def _held_out_titles(project: Project, import_id: str) -> list[str]:
    return [
        r.title
        for r in list_import_records(project, import_id, view="held-out")
        if r.title is not None
    ]


@pytest.mark.anyio
async def test_mcp_withholds_held_out(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    split_import: str,
) -> None:
    held = len(_held_out_titles(project, split_import))
    assert 0 < held < N
    full = coverage_report(project, split_import)
    async with open_session(settings, clock, {}) as session:
        before = await session.call("import_coverage", project="demo", import_id=split_import)
        status = await session.call("import_status", project="demo")
        assert before["ok"] is True and status["ok"] is True, (before, status)
        data = before["data"]
        assert [p["part"] for p in data["parts"]] == ["development"]
        assert data["parts"][0]["resolved"] == full.parts[0].resolved == N - held
        assert data["included_not_in_library"] is None
        text = json.dumps([before, status])
        for title in _held_out_titles(project, split_import):
            assert title not in text
        assert "ordinal" not in text
        [row] = status["data"]["items"]
        assert row["import_id"] == split_import
        assert row["buckets"]["query-miss"] == N - held
        assert row["states"]["resolved"] == N - held

        open_pass(project, agent, PassLabel.A)  # screening starts: held-out figures appear
        after = await session.call("import_coverage", project="demo", import_id=split_import)
        parts = {p["part"]: p for p in after["data"]["parts"]}
        assert set(parts) == {"development", "held-out"}
        assert parts["held-out"]["resolved"] == held
        assert parts["held-out"]["excluded"] == []
        assert after["data"]["included_not_in_library"] is not None
        assert "ordinal" not in json.dumps(after)
        for title in _held_out_titles(project, split_import):
            assert title not in json.dumps(after)
        status_after = await session.call("import_status", project="demo")
        assert status_after["data"]["items"][0]["buckets"] == row["buckets"]  # development only


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["import_status", "import_coverage"])
async def test_mcp_refused_to_pass_session(
    tool: str,
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: SourcesFor,
    tmp_path: Path,
) -> None:
    _setup(project, agent, human, mock_sources)
    _draw(project)
    path = tmp_path / "one.bib"
    path.write_text(bib_entry("k", "Some Title Of Reeds", year=2001, author="A, B"))
    import_id = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE
    ).import_id
    args: dict[str, Any] = {"import_id": import_id} if tool == "import_coverage" else {}
    async with open_session(settings, clock, {}) as screener:
        joined = await screener.call("screen_next", project="demo", pass_label="A", **AGENT)
        assert joined["ok"] is True, joined
        before = _count(project)
        body = await screener.call(tool, project="demo", **args)
    assert body["ok"] is False
    assert [e["field"] for e in body["errors"]] == ["session"]
    assert _count(project) == before


@pytest.mark.anyio
async def test_mcp_status_paginated(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    split_import: str,
    tmp_path: Path,
) -> None:
    for n in range(2):
        path = tmp_path / f"more{n}.bib"
        path.write_text(bib_entry(f"k{n}", f"Another Title {n} Of Reeds", year=2001, author="A, B"))
        record_import(project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE)
    async with open_session(settings, clock, {}) as session:
        first = await session.call("import_status", project="demo", limit=2)
        assert len(first["data"]["items"]) == 2 and first["data"]["next_cursor"] == "2"
        rest = await session.call(
            "import_status", project="demo", cursor=first["data"]["next_cursor"], limit=2
        )
        assert len(rest["data"]["items"]) == 1 and rest["data"]["next_cursor"] is None
        ids = [i["import_id"] for i in (*first["data"]["items"], *rest["data"]["items"])]
        assert len(set(ids)) == 3
        unknown = await session.call("import_coverage", project="demo", import_id="imp_nope")
        assert unknown["ok"] is False


def test_cli_coverage_shows_all_parts(
    settings: Settings, project: Project, split_import: str
) -> None:
    result = runner.invoke(app, ["import", "coverage", split_import], env=_cli_env(settings.root))
    assert result.exit_code == 0, result.stderr
    assert "development" in result.stdout and "held-out" in result.stdout
    as_json = runner.invoke(
        app, ["import", "coverage", split_import, "--json"], env=_cli_env(settings.root)
    )
    assert as_json.exit_code == 0, as_json.stderr
    report = json.loads(as_json.stdout)
    assert [p["part"] for p in report["parts"]] == ["development", "held-out"]
    assert sum(p["resolved"] for p in report["parts"]) == N


@pytest.mark.anyio
async def test_report_prisma_hides_record_keys(
    settings: Settings,
    project: Project,
    corpus: None,
    agent: Actor,
    clock: FixedClock,
    tmp_path: Path,
) -> None:
    """The offline admission query's text names records as `imp_...:<ordinal>`; no agent surface
    may show an ordinal."""
    from factory.services.import_admit import admit_import
    from tests.import_helpers import admission_records, admit_lookups, declare_library, import_bib
    from tests.test_import_admit import _corpus_doi

    declare_library(project, agent)
    imp = import_bib(project, tmp_path, admission_records(_corpus_doi(project)))
    lookups = admit_lookups()
    resolve_import(project, imp, sources=lookups.sources())
    admit_import(project, imp, sources=lookups.sources())
    async with open_session(settings, clock, {}) as session:
        body = await session.call("report_prisma", project="demo")
    assert body["ok"] is True
    text = json.dumps(body)
    assert not re.search(r"imp_[0-9A-Z]{26}:[0-9]+", text)
    assert imp in text  # the import itself is still reported

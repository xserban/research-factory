"""`factory import resolve|confirm|reject|admit|attach` (Import-B task 6). Synthetic data only."""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.references import LinkState
from factory.services.context import Project
from factory.services.dedup import canonical_works
from factory.services.import_resolve import record_states, resolve_import
from tests.document_helpers import events_of_type
from tests.import_helpers import (
    admission_records,
    admit_lookups,
    bib_entry,
    declare_library,
    import_bib,
)
from tests.references_service_helpers import Lookups, oa_item
from tests.test_cli import _cli_env, runner
from tests.test_fulltext_import import _pdf


def _invoke(settings: Settings, *args: str):  # type: ignore[no-untyped-def]
    return runner.invoke(app, list(args), env=_cli_env(settings.root))


def _use(monkeypatch: pytest.MonkeyPatch, lookups: Lookups) -> None:
    monkeypatch.setattr("factory.cli.main.default_sources", lookups.sources)


def _doi(project: Project) -> str:
    doi = next(w.identifiers.doi for w in canonical_works(project) if w.identifiers.doi)
    assert doi is not None
    return doi


def test_cli_resolve_counts(
    project: Project,
    corpus: None,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imp = import_bib(project, tmp_path, admission_records(_doi(project)))
    lookups = admit_lookups()
    _use(monkeypatch, lookups)
    result = _invoke(settings, "import", "resolve", imp)
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert "resolved: 2" in out and "unresolved: 2" in out and "unconfirmed: 0" in out
    assert "ambiguous: 0" in out
    assert "imp_" not in out.replace(imp, "")  # counts only: no record keys, no ordinals
    assert record_states(project, imp)[1] is LinkState.RESOLVED


def test_cli_confirm_writes_human_decision(
    project: Project,
    corpus: None,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imp = import_bib(
        project,
        tmp_path,
        [bib_entry("a", "Efficient Reed Transformers v2", year=2021, author="Lee, Bo")],
    )
    lookups = Lookups(openalex=[oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501")])
    resolve_import(project, imp, sources=lookups.sources())
    refused = _invoke(settings, "import", "confirm", imp, "1")  # no rationale
    assert refused.exit_code != 0
    ok = _invoke(settings, "import", "confirm", imp, "1", "--rationale", "Same paper.")
    assert ok.exit_code == 0, ok.stderr
    [event] = events_of_type(project, "import.resolution_decided")
    assert event.actor.kind == "human" and event.payload["decision"] == "confirm"
    assert event.payload["confirmed_by"] == "human"
    assert record_states(project, imp)[1] is LinkState.RESOLVED
    again = _invoke(settings, "import", "reject", imp, "1", "--rationale", "On reflection, no.")
    assert again.exit_code == 0, again.stderr
    assert record_states(project, imp)[1] is LinkState.UNRESOLVED


def test_cli_confirm_unknown_record_fails(
    project: Project, settings: Settings, tmp_path: Path
) -> None:
    imp = import_bib(project, tmp_path, [bib_entry("a", "Made-Up Pears", year=2019, author="Q, A")])
    result = _invoke(settings, "import", "confirm", imp, "7", "--rationale", "x")
    assert result.exit_code == 1 and events_of_type(project, "import.resolution_decided") == []


def test_cli_admit_prints_runs_and_gaps(
    explore_project: Project, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = explore_project
    imp = import_bib(project, tmp_path, admission_records("10.1000/none"))
    lookups = admit_lookups()
    _use(monkeypatch, lookups)
    assert _invoke(settings, "import", "resolve", imp).exit_code == 0
    result = _invoke(settings, "import", "admit", imp)
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert "runs: 2" in out and "new works: 3" in out and "failed runs: 0" in out
    assert "library_sources" in out  # the promotion gap of an exploratory project


def test_cli_admit_refusal_exits_nonzero(
    project: Project,
    corpus: None,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imp = import_bib(project, tmp_path, admission_records(_doi(project)))
    _use(monkeypatch, admit_lookups())
    assert _invoke(settings, "import", "resolve", imp).exit_code == 0
    result = _invoke(settings, "import", "admit", imp)  # pilot, no library_sources declared
    assert result.exit_code == 1
    assert "library_sources" in result.stderr


def test_cli_attach_report_lists(
    project: Project,
    corpus: None,
    agent: Actor,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = tmp_path / "files"
    files.mkdir()
    _pdf(files / "a.pdf", "First page")
    doi = _doi(project)
    head = "@article{a, title={Paper}, author={Zhou, Ada}, year={2020}"
    imp = import_bib(
        project,
        tmp_path,
        [f"{head}, doi={{{doi}}}, file={{PDF:files/a.pdf:application/pdf}}}}\n"],
    )
    _use(monkeypatch, Lookups())
    assert _invoke(settings, "import", "resolve", imp).exit_code == 0
    default = _invoke(settings, "import", "attach", imp)
    assert default.exit_code == 0, default.stderr
    assert "attached: 1" in default.stdout and "not promoted: 0" in default.stdout
    assert "rf:" not in default.stdout  # no work ids or ordinals unless asked for
    again = _invoke(settings, "import", "attach", imp, "--researcher")
    assert again.exit_code == 0, again.stderr
    assert "already attached: 1" in again.stdout
    assert "already attached ordinals: 1" in again.stdout


def test_cli_show_researcher_lists_link_state(
    project: Project,
    corpus: None,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imp = import_bib(project, tmp_path, admission_records(_doi(project)))
    _use(monkeypatch, admit_lookups())
    assert _invoke(settings, "import", "resolve", imp).exit_code == 0
    shown = _invoke(settings, "import", "show", imp, "--part", "all", "--researcher")
    assert shown.exit_code == 0, shown.stderr
    assert "state" in shown.stdout.splitlines()[0]
    assert "unresolved" in shown.stdout and "resolved" in shown.stdout


def test_cli_admit_in_pilot_with_a_declared_library(
    project: Project,
    corpus: None,
    agent: Actor,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declare_library(project, agent)
    imp = import_bib(project, tmp_path, admission_records(_doi(project)))
    _use(monkeypatch, admit_lookups())
    assert _invoke(settings, "import", "resolve", imp).exit_code == 0
    result = _invoke(settings, "import", "admit", imp)
    assert result.exit_code == 0, result.stderr
    assert "new works: 2" in result.stdout and "already in corpus: 1" in result.stdout
    assert "library_sources" not in result.stdout

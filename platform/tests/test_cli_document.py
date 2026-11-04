"""CLI `factory document` (plan 2B2, task 6): convert, status, read.

The converter is a stub registry, so no LaTeXML binary is needed. Each command is a thin wrapper:
the tests check its output and the events it leaves behind.
"""

from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.document import Converted
from factory.services.context import Project
from tests.document_helpers import (
    ARTICLE,
    StubConverter,
    event_bytes,
    events_of_type,
    excluded_after_conversion,
    fetched_document,
    make_registry,
    promoted_works,
)

runner = CliRunner()
SENTENCE = "Ut enim ad minim veniam"


def _env(root: Any) -> dict[str, str | None]:
    # FACTORY_PROJECT is cleared so a developer's shell cannot leak into the test.
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}


@pytest.fixture
def stub_converters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("factory.cli.main.default_converters", make_registry)


def _use_registry(monkeypatch: pytest.MonkeyPatch, converter: StubConverter) -> None:
    monkeypatch.setattr("factory.cli.main.default_converters", lambda: make_registry(converter))


@pytest.mark.usefixtures("corpus", "stub_converters")
def test_convert_then_status_shows_the_conversion(project: Project, settings: Settings) -> None:
    work = promoted_works(project)[0]
    document = fetched_document(project, work, ARTICLE)

    convert = runner.invoke(app, ["document", "convert"], env=_env(settings.root))

    assert convert.exit_code == 0, convert.stderr
    lines = convert.stdout.splitlines()
    assert f"{document}  {work}  converted  -" in lines
    assert lines[-1] == "converted 1, unchanged 0, failed 0, raw-missing 0, restored 0"

    status = runner.invoke(app, ["document", "status"], env=_env(settings.root))

    assert status.exit_code == 0, status.stderr
    assert "converted: 1" in status.stdout.splitlines()
    assert any(
        line.startswith(f"{document}  {work}  converted  latexml-html 1.0+stub")
        for line in status.stdout.splitlines()
    ), status.stdout


@pytest.mark.usefixtures("corpus", "stub_converters")
def test_read_prints_a_known_sentence(project: Project, settings: Settings) -> None:
    work = promoted_works(project)[0]
    fetched_document(project, work, ARTICLE)
    runner.invoke(app, ["document", "convert"], env=_env(settings.root))

    result = runner.invoke(app, ["document", "read", work], env=_env(settings.root))

    assert result.exit_code == 0, result.stderr
    assert SENTENCE in result.stdout


@pytest.mark.usefixtures("corpus", "stub_converters")
def test_restore_regenerates_a_deleted_blob(project: Project, settings: Settings) -> None:
    work = promoted_works(project)[0]
    document = fetched_document(project, work, ARTICLE)
    runner.invoke(app, ["document", "convert"], env=_env(settings.root))
    [event] = events_of_type(project, "document.converted")
    markdown_ref = Converted.model_validate(event.payload).markdown_hash
    project.library.path(markdown_ref).unlink()
    before = event_bytes(project)

    result = runner.invoke(app, ["document", "convert", "--restore"], env=_env(settings.root))

    assert result.exit_code == 0, result.stderr
    assert f"{document}  {work}  restored  -" in result.stdout.splitlines()
    assert project.library.exists(markdown_ref)
    assert event_bytes(project) == before


@pytest.mark.usefixtures("corpus", "stub_converters")
def test_unknown_document_exits_nonzero_and_writes_nothing(
    project: Project, settings: Settings
) -> None:
    fetched_document(project, promoted_works(project)[0], ARTICLE)
    before = event_bytes(project)

    result = runner.invoke(
        app, ["document", "convert", "--document", "fdoc_nope"], env=_env(settings.root)
    )

    assert result.exit_code == 1
    assert result.stderr.startswith("document_ids: fdoc_nope: unknown or superseded")
    assert event_bytes(project) == before


@pytest.mark.usefixtures("corpus", "stub_converters")
def test_restore_with_work_is_rejected(project: Project, settings: Settings) -> None:
    work = promoted_works(project)[0]
    fetched_document(project, work, ARTICLE)
    before = event_bytes(project)

    result = runner.invoke(
        app, ["document", "convert", "--restore", "--work", work], env=_env(settings.root)
    )

    assert result.exit_code == 1
    assert result.stderr.startswith("restore: takes no --work or --document")
    assert event_bytes(project) == before


@pytest.mark.usefixtures("corpus", "stub_converters")
def test_status_labels_a_failure_by_whether_the_document_is_converted(
    project: Project, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = promoted_works(project)[0]
    document = fetched_document(project, work, ARTICLE)
    _use_registry(monkeypatch, StubConverter(unavailable=True))
    runner.invoke(app, ["document", "convert"], env=_env(settings.root))

    failed = runner.invoke(app, ["document", "status"], env=_env(settings.root))
    assert failed.exit_code == 0, failed.stderr
    assert f"{document}  {work}  not converted  last failure: converter-unavailable" in (
        failed.stdout.splitlines()
    )

    _use_registry(monkeypatch, StubConverter())
    runner.invoke(app, ["document", "convert"], env=_env(settings.root))

    converted = runner.invoke(app, ["document", "status"], env=_env(settings.root))
    assert converted.exit_code == 0, converted.stderr
    [line] = [ln for ln in converted.stdout.splitlines() if ln.startswith(document)]
    assert "converted  latexml-html 1.0+stub" in line
    assert line.endswith("earlier failure: converter-unavailable")
    assert "last failure" not in line


@pytest.mark.usefixtures("corpus", "stub_converters")
def test_read_refuses_a_work_no_longer_included_with_its_conversion(
    project: Project, settings: Settings, agent: Actor
) -> None:
    work = promoted_works(project)[0]
    excluded_after_conversion(project, agent, work)
    before = event_bytes(project)

    result = runner.invoke(app, ["document", "read", work], env=_env(settings.root))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == f"work_id: {work}: not promoted at title/abstract\n"
    assert event_bytes(project) == before


@pytest.mark.usefixtures("corpus", "stub_converters")
def test_read_refuses_a_work_with_no_conversion(project: Project, settings: Settings) -> None:
    work = promoted_works(project)[0]
    before = event_bytes(project)

    result = runner.invoke(app, ["document", "read", work], env=_env(settings.root))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        f"work_id: {work}: has no conversion; run `factory document convert` first\n"
    )
    assert event_bytes(project) == before


@pytest.mark.usefixtures("corpus", "stub_converters")
def test_read_refuses_after_combined_with_anchor(project: Project, settings: Settings) -> None:
    work = promoted_works(project)[0]
    fetched_document(project, work, ARTICLE)
    runner.invoke(app, ["document", "convert"], env=_env(settings.root))
    before = event_bytes(project)

    result = runner.invoke(
        app,
        ["document", "read", work, "--after", "sec_x", "--anchor", "sec_y"],
        env=_env(settings.root),
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "after: cannot be combined with anchor\n"
    assert event_bytes(project) == before

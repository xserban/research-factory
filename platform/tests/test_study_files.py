"""Registered study files: the service, the projection and the CLI (plan flow-transparency, B)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from factory.cli.main import app
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.index.default import default_projection
from factory.model.files import FileRegistered
from factory.services.context import Project
from factory.services.study_files import file_status, list_files, register_file

runner = CliRunner()


def _write(project: Project, rel: str, content: str) -> Path:
    path = project.paths.dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_register_writes_event_blob_and_row(project: Project) -> None:
    _write(project, "docs/plan.md", "# Plan\n")
    result = register_file(project, "docs/plan.md", "study-document", "Plan", project.human_actor())
    assert result.changed
    reg = result.registration
    digest = hashlib.sha256(b"# Plan\n").hexdigest()
    assert (reg.sha256, reg.version, reg.supersedes, reg.title) == (digest, 1, None, "Plan")
    assert project.blobs.get(reg.blob) == b"# Plan\n"
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT path, sha256, kind, title, blob, event_id FROM registered_files")
        ).one()
    assert tuple(row) == ("docs/plan.md", digest, "study-document", "Plan", reg.blob, reg.event_id)


def test_unchanged_file_is_idempotent(project: Project) -> None:
    _write(project, "docs/plan.md", "v1")
    first = register_file(project, "docs/plan.md", "study-document", None, project.human_actor())
    again = register_file(project, "docs/plan.md", "study-document", None, project.human_actor())
    assert not again.changed and again.registration == first.registration
    assert len(list_files(project)) == 1 and not list_files(project)[0].history


def test_same_content_with_another_kind_or_title_is_a_new_registration(project: Project) -> None:
    _write(project, "docs/plan.md", "v1")
    first = register_file(project, "docs/plan.md", "study-document", None, project.human_actor())
    second = register_file(project, "docs/plan.md", "other", "Plan", project.human_actor())
    assert second.changed and second.metadata_only
    reg = second.registration
    assert (reg.version, reg.kind, reg.title) == (2, "other", "Plan")
    assert reg.supersedes == first.registration.event_id
    assert reg.sha256 == first.registration.sha256 and reg.blob == first.registration.blob
    third = register_file(project, "docs/plan.md", "other", " Plan ", project.human_actor())
    assert not third.changed


def test_site_folder_is_refused(project: Project) -> None:
    _write(project, "site/x.md", "x")
    with pytest.raises(FactoryValidationError):
        register_file(project, "site/x.md", "other", None, project.human_actor())
    assert list_files(project) == []


def test_changed_file_is_a_new_version_that_supersedes(project: Project) -> None:
    path = _write(project, "docs/plan.md", "v1")
    first = register_file(project, "docs/plan.md", "study-document", None, project.human_actor())
    path.write_text("v2", encoding="utf-8")
    second = register_file(project, "docs/plan.md", "study-document", None, project.human_actor())
    assert second.changed and second.registration.version == 2
    assert second.registration.supersedes == first.registration.event_id
    entry = list_files(project)[0]
    assert entry.latest.event_id == second.registration.event_id
    assert [r.version for r in entry.history] == [1]
    assert project.blobs.get(first.registration.blob) == b"v1"  # the old content survives


@pytest.mark.parametrize(
    ("rel", "outside"),
    [
        ("../escape.md", False),
        ("/etc/hostname", False),
        ("events/x.md", False),
        ("blobs/x", False),
        ("library/x.pdf", False),
        (".index/x", False),
        ("docs/missing.md", False),
        ("docs", False),
    ],
)
def test_refusals_write_nothing(project: Project, rel: str, outside: bool) -> None:
    _write(project, "docs/present.md", "x")
    (project.paths.dir / "events").mkdir(exist_ok=True)
    (project.paths.dir / "events" / "x.md").write_text("x", encoding="utf-8")
    (project.paths.dir / "docs").mkdir(exist_ok=True)
    with pytest.raises(FactoryValidationError):
        register_file(project, rel, "other", None, project.human_actor())
    assert list_files(project) == []


def test_symlink_out_of_the_folder_is_refused(project: Project, tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")
    (project.paths.dir / "docs").mkdir(exist_ok=True)
    (project.paths.dir / "docs" / "link.md").symlink_to(outside)
    with pytest.raises(FactoryValidationError):
        register_file(project, "docs/link.md", "other", None, project.human_actor())


def test_only_a_human_registers_and_kind_is_checked(project: Project, agent: Actor) -> None:
    _write(project, "docs/plan.md", "x")
    with pytest.raises(FactoryValidationError):
        register_file(project, "docs/plan.md", "other", None, agent)
    with pytest.raises(FactoryValidationError):
        register_file(project, "docs/plan.md", "memo", None, project.human_actor())
    assert list_files(project) == []


def test_status_unchanged_changed_missing(project: Project) -> None:
    a = _write(project, "docs/a.md", "a")
    b = _write(project, "docs/b.md", "b")
    _write(project, "docs/c.md", "c")
    for name in ("a", "b", "c"):
        register_file(project, f"docs/{name}.md", "study-document", None, project.human_actor())
    b.write_text("b2", encoding="utf-8")
    (project.paths.dir / "docs" / "c.md").unlink()
    assert a.exists()
    states = {s.path: s.state for s in file_status(project)}
    assert states == {"docs/a.md": "unchanged", "docs/b.md": "changed", "docs/c.md": "missing"}


def test_projection_rebuild_keeps_versions(project: Project) -> None:
    path = _write(project, "docs/plan.md", "v1")
    register_file(project, "docs/plan.md", "study-document", None, project.human_actor())
    path.write_text("v2", encoding="utf-8")
    register_file(project, "docs/plan.md", "study-document", None, project.human_actor())
    project.index.rebuild()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT supersedes FROM registered_files ORDER BY event_id")).all()
    assert len(rows) == 2 and rows[0][0] is None and rows[1][0] is not None


def test_handler_ignores_a_registration_without_its_blob(project: Project) -> None:
    """A hand-written event whose input blob is not the file's content changes nothing."""
    payload = FileRegistered(path="docs/x.md", sha256="0" * 64, size=1, kind="other")
    event = project.events.make("file.registered", payload, project.human_actor())
    project.record([event])
    with project.index.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM registered_files")).scalar() == 0


def test_table_is_declared() -> None:
    assert "registered_files" in default_projection().metadata.tables


def _env(root: Path) -> dict[str, str | None]:
    return {"FACTORY_ROOT": str(root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}


def test_cli_register_list_status(project: Project, tmp_path: Path) -> None:
    env = _env(tmp_path)
    plan = _write(project, "docs/plan.md", "v1")
    _write(project, "docs/notes.md", "n")
    first = runner.invoke(
        app,
        ["files", "register", "docs/plan.md", "docs/notes.md", "--kind", "study-document"],
        env=env,
    )
    assert first.exit_code == 0, first.output
    assert first.stdout.count("registered ") == 2
    plan.write_text("v2", encoding="utf-8")
    second = runner.invoke(
        app,
        ["files", "register", "docs/plan.md", "docs/notes.md", "--kind", "study-document"],
        env=env,
    )
    assert second.exit_code == 0, second.output
    assert "registered docs/plan.md v2" in second.stdout
    assert "unchanged docs/notes.md v1" in second.stdout
    third = runner.invoke(app, ["files", "register", "docs/notes.md", "--kind", "other"], env=env)
    assert "re-registered (kind or title changed) docs/notes.md v2" in third.stdout
    listed = runner.invoke(app, ["files", "list", "--json"], env=env)
    assert listed.exit_code == 0, listed.output
    data = json.loads(listed.stdout)
    assert sorted(d["latest"]["path"] for d in data) == ["docs/notes.md", "docs/plan.md"]
    status = runner.invoke(app, ["files", "status"], env=env)
    assert status.exit_code == 0 and "unchanged  docs/plan.md  v2" in status.stdout


def test_cli_refusal_exits_1_and_goes_on(project: Project, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _write(project, "docs/ok.md", "x")
    result = runner.invoke(
        app, ["files", "register", "events/x", "docs/ok.md", "--kind", "other"], env=env
    )
    assert result.exit_code == 1
    assert "events/x" in result.stderr
    assert "registered docs/ok.md" in result.stdout


def test_cli_title_needs_one_file(project: Project, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["files", "register", "a", "b", "--kind", "other", "--title", "T"],
        env=_env(tmp_path),
    )
    assert result.exit_code == 1

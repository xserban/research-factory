"""`factory files`: register the study's own files with their hash (plan flow-transparency, B).

Business logic stays in `services/study_files.py`. `register` writes one `file.registered` event
per changed file; `list` and `status` are read-only. The shared helpers of `factory.cli.main` are
imported inside the commands, because that module imports this one. There is no MCP tool: agents
do not register the researcher's files.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from factory.errors import FactoryValidationError
from factory.model.files import FILE_KINDS
from factory.services import study_files

files_app = typer.Typer(
    name="files",
    help="Study files registered with their hash: register, list, status.",
    no_args_is_help=True,
)


def _project_relative(arg: str, root: Path) -> str:
    """`arg` as a path relative to the project folder: an absolute path or one that exists from
    the current folder inside the project is converted; anything else is taken as given."""
    base = root.resolve()
    candidate = Path(arg)
    for option in (candidate, Path.cwd() / candidate):
        if option.exists():
            resolved = option.resolve()
            if resolved.is_relative_to(base):
                return resolved.relative_to(base).as_posix()
    return Path(arg).as_posix()


@files_app.command("register")
def files_register_cmd(
    ctx: typer.Context,
    paths: Annotated[list[str], typer.Argument(help="Files, relative to the project folder.")],
    kind: Annotated[str, typer.Option("--kind", help=" | ".join(FILE_KINDS))],
    title: Annotated[str | None, typer.Option("--title", help="A title (one file).")] = None,
) -> None:
    """Register files as records of the study. Unchanged content, kind and title write nothing."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    if title is not None and len(paths) > 1:
        typer.echo("title: give a title for one file at a time", err=True)
        raise typer.Exit(1)
    failed = False
    with _reporting_errors():
        project = _resolve_project(state)
        for arg in paths:
            rel = _project_relative(arg, project.paths.dir)
            try:
                result = study_files.register_file(project, rel, kind, title, project.human_actor())
            except FactoryValidationError as exc:  # report this file, go on with the others
                for issue in exc.issues:
                    typer.echo(f"{rel}: {issue.field}: {issue.reason}", err=True)
                failed = True
                continue
            reg = result.registration
            word = (
                "unchanged"
                if not result.changed
                else "re-registered (kind or title changed)"
                if result.metadata_only
                else "registered"
            )
            typer.echo(f"{word} {reg.path} v{reg.version} {reg.sha256[:12]} {reg.event_id}")
    if failed:
        raise typer.Exit(1)


@files_app.command("list")
def files_list_cmd(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """The latest registration of each path, with its versions."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        rows = study_files.list_files(project)
    if as_json:
        typer.echo(json.dumps([asdict(r) for r in rows], indent=2))
        return
    for row in rows:
        r = row.latest
        label = f" ({r.title})" if r.title else ""
        typer.echo(
            f"{r.kind}  {r.path}{label}  v{r.version}  {r.sha256[:12]}  {r.registered_at[:10]}"
        )


@files_app.command("status")
def files_status_cmd(ctx: typer.Context) -> None:
    """Each registered path against the disk: unchanged, changed since registration, or missing."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        rows = study_files.file_status(project)
    for s in rows:
        word = {"unchanged": "unchanged", "changed": "CHANGED", "missing": "MISSING"}[s.state]
        typer.echo(f"{word}  {s.path}  v{s.version}")

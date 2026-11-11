"""`factory pages`: recorded model-written pages (plan site-hub, step 4).

Business logic stays in `services/pages.py`. `record` writes one `page.recorded` event; the other
commands are read-only. The shared helpers of `factory.cli.main` are imported inside the commands,
because that module imports this one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from factory.services import pages as pages_service

pages_app = typer.Typer(
    name="pages",
    help="Recorded synthesis pages: the brief, record a page, list, show.",
    no_args_is_help=True,
)


@pages_app.command("brief")
def pages_brief_cmd(
    ctx: typer.Context,
    scope: Annotated[str, typer.Argument(help="overview, technique=<v>, stage=<v> or field=<v>")],
    part: Annotated[int, typer.Option("--part", help="Part of the digest.")] = 0,
) -> None:
    """Print the brief a page is written from: statistics, rules and a digest of quoted rows."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        data = pages_service.brief(project, scope, part)
    typer.echo(
        f"scope {data['scope']} ({data['label']}), {data['works']} works, "
        f"part {data['part']} of {data['parts']}, fingerprint {data['fingerprint']}"
    )
    if "stats" in data:
        typer.echo(f"\nSTATS\n{data['stats']}\n\n{data['rules']}")
    typer.echo(f"\nDIGEST\n{data['digest']}")


@pages_app.command("record")
def pages_record_cmd(
    ctx: typer.Context,
    scope: Annotated[str, typer.Argument(help="overview, technique=<v>, stage=<v> or field=<v>")],
    file: Annotated[Path, typer.Option("--file", help="The page, as Markdown.")],
    title: Annotated[str, typer.Option("--title", help="The page title.")],
    supersedes: Annotated[
        str | None, typer.Option("--supersedes", help="A page to replace.")
    ] = None,
) -> None:
    """Record a page written by a human (agents use the MCP tool). The check runs first."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        payload, check = pages_service.record_page(
            project,
            project.human_actor(),
            scope,
            title,
            file.read_text(encoding="utf-8"),
            supersedes,
        )
    typer.echo(f"recorded {payload.page_id}: {check.words} words, {len(check.flags)} flag(s)")


@pages_app.command("list")
def pages_list_cmd(ctx: typer.Context) -> None:
    """The latest page of each scope, with flags and staleness."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        rows = pages_service.list_pages(project)
    for p in rows:
        tag = " STALE" if p.stale else ""
        typer.echo(
            f"{p.page_id} {p.scope}: {p.title} ({p.model or p.actor_kind}, "
            f"{p.words} words, {p.flags} flag(s)){tag}"
        )


@pages_app.command("show")
def pages_show_cmd(
    ctx: typer.Context, page_id: Annotated[str, typer.Argument(help="A page id (pg_...).")]
) -> None:
    """Print one recorded page."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        data = pages_service.read_page(project, page_id)
    typer.echo(str(data["body"]))

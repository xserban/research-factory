"""`factory site`: the project's hub of products, built from the events (plan 2026-11-10-site-hub).

Business logic stays in `services/site.py`. Nothing here writes an event. The shared helpers of
`factory.cli.main` are imported inside the commands, because that module imports this one.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer

import factory.mcp.server  # noqa: F401  (registers the server builder for the tool catalog)
from factory.services import site as site_service
from factory.services import site_server as server_service

site_app = typer.Typer(
    name="site",
    help="The project hub: every product of the factory in one place, rebuilt from the events.",
    no_args_is_help=True,
)


@site_app.command("build")
def site_build_cmd(
    ctx: typer.Context,
    only: Annotated[
        list[str] | None, typer.Option("--only", help="Build only this product; repeatable.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Rebuild even when a product is up to date.")
    ] = False,
    lazy: Annotated[
        bool,
        typer.Option(
            "--lazy",
            help="Skip the item pages of products that support it (the conversion inspector); "
            "a served hub renders each on its first request. Used by `site serve`.",
        ),
    ] = False,
) -> None:
    """Build every stale product and the hub page (`<project>/site/index.html`)."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        try:
            results = site_service.build(project, only=only or (), force=force, lazy=lazy)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
    for r in results:
        what = "up to date" if r.skipped else "built" if r.built else f"FAILED: {r.error}"
        typer.echo(f"{r.id}: {what}")
    typer.echo(f"hub: {site_service.site_dir(project) / 'index.html'}")


@site_app.command("status")
def site_status_cmd(ctx: typer.Context) -> None:
    """Each product with its build time and whether it is stale."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        rows = site_service.status(project)
    for s in rows:
        flag = "failed" if s.error else "stale" if s.stale else "up to date"
        typer.echo(f"{s.id}: {flag} (built {s.built_at or 'never'}) {s.error or ''}".rstrip())


def _feed_runner(state: Any) -> server_service.FeedRunner:
    """The hub's feed runner: `feed_run_all` over every configured project with one shared
    fetch (`refetch` skips the shared cache). Built lazily: the source and the ranker are only
    created when a run starts."""
    from factory.services import feed as feed_service
    from factory.services.ranking_model import Specter2Embedder
    from factory.sources.arxiv import ArxivSource
    from factory.sources.http import default_http

    def run(refetch: bool) -> feed_service.FeedRunAll:
        source = ArxivSource(
            default_http(state.settings), clock=state.clock, mailto=state.settings.mailto
        )
        return feed_service.feed_run_all(
            state.settings,
            embedder_factory=Specter2Embedder,
            source=source,
            session=state.session,
            clock=state.clock,
            bypass_cache=refetch,
        )

    return server_service.FeedRunner(run)


@site_app.command("serve")
def site_serve_cmd(
    ctx: typer.Context,
    port: Annotated[int, typer.Option("--port", help="Port on 127.0.0.1.")] = (
        server_service.DEFAULT_PORT
    ),
    every: Annotated[
        int,
        typer.Option(
            "--every",
            help="Settle window: a product is rebuilt at most once per this many seconds; "
            "meanwhile its previous build is served with an 'as of' badge.",
        ),
    ] = 600,
    dev: Annotated[
        bool,
        typer.Option(
            "--dev",
            help="Development: no settle window, so a changed page or new events show on the "
            "next open (builds still run in a child process with the code on disk).",
        ),
    ] = False,
    eager: Annotated[
        bool,
        typer.Option(
            "--eager",
            help="Also rebuild every stale product in the background (by default a product is "
            "rebuilt only when it is opened).",
        ),
    ] = False,
    all_projects: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Serve every project under the root: a portal at / and each hub at /p/<slug>/.",
        ),
    ] = False,
    feed: Annotated[
        bool,
        typer.Option(
            "--feed/--no-feed",
            help="With --all: run the arXiv feed of the configured projects once a day while "
            "the hub is up (a run is due once per the feed's interval).",
        ),
    ] = True,
) -> None:
    """Serve the hub on 127.0.0.1; a stale product is rebuilt when it is opened."""
    from factory.cli.main import _authorized, _reporting_errors, _resolve_project, _state
    from factory.services.context import list_projects, open_project
    from factory.services.site_create import create_project

    state = _state(ctx)
    if all_projects:
        runner = _feed_runner(state) if feed else None
        hub = server_service.MainHub(
            state.settings.root,
            lambda: list_projects(state.settings),
            lambda slug: _authorized(
                state,
                open_project(state.settings, slug, session=state.session, clock=state.clock),
            ),
            min_gap=0.0 if dev else float(every),
            background=True,
            eager=eager,
            child_builds=True,
            feed=runner,
            create=lambda slug, title, profile: create_project(
                state.settings, slug, title, profile, session=state.session, clock=state.clock
            ),
            factory_feed=server_service.FactoryFeedEnv(state.settings, state.session, state.clock),
        )
        with _reporting_errors():
            main_server = server_service.make_main_server(hub, port)
        typer.echo(
            f"hub of {len(hub.prepare_all())} project(s) on "
            f"http://{server_service.HOST}:{main_server.server_port}/ (Ctrl-C to stop)"
        )
        try:
            main_server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            hub.stop()
            main_server.server_close()
        return
    with _reporting_errors():
        project = _resolve_project(state)
    httpd, rebuilder = server_service.make_server(
        project, port, min_gap=0.0 if dev else float(every), eager=eager, child_builds=True
    )
    typer.echo(f"site on http://{server_service.HOST}:{httpd.server_port}/ (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        rebuilder.stop()
        httpd.server_close()

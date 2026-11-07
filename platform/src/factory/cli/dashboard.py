"""`factory dashboard` (slice 8, I1): a local read-only page of the project, served or exported.

Business logic stays in `services/dashboard.py`; the server and export are in
`services/dashboard_server.py`. Nothing here writes an event. The shared helpers of
`factory.cli.main` are imported inside the commands, because that module imports this one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from factory.services import dashboard_server as server_service

dashboard_app = typer.Typer(
    name="dashboard",
    help="The live dashboard: serve it on 127.0.0.1 or export a static snapshot.",
    no_args_is_help=True,
)


@dashboard_app.command("serve")
def dashboard_serve_cmd(
    ctx: typer.Context,
    port: Annotated[int, typer.Option("--port", help="Port on 127.0.0.1.")] = (
        server_service.DEFAULT_PORT
    ),
) -> None:
    """Serve the page and `/api/state` on 127.0.0.1 until interrupted; the page polls every 5 s."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
    httpd = server_service.make_server(project, port)
    typer.echo(f"dashboard on http://{server_service.HOST}:{httpd.server_port}/ (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


@dashboard_app.command("export")
def dashboard_export_cmd(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Where to write the HTML snapshot.")],
) -> None:
    """Write one HTML file with the current state embedded; it needs no server."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        server_service.export_snapshot(project, path)
    typer.echo(f"wrote {path}")

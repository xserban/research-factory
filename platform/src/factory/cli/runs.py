"""`factory runs adopt` (plan restart-and-costs, R4): record a pilot-style driver that was started
outside the runner (a prompt file, a model, an allow-list of tools, an MCP config, a log) as a run
folder, so `factory resume` can restart it.

It parses input, calls `services.runner.adopt_driver` and prints the new run id. It starts nothing.
The helpers of `factory.cli.main` are imported inside the command, because that module imports this
one to register the command on the `runs` group. The root `--project` option selects the project,
as for every command.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer


def adopt_cmd(
    ctx: typer.Context,
    stage: Annotated[
        str, typer.Option("--stage", help="The stage key (screen, extract, mine:<id>, ...).")
    ],
    prompt: Annotated[Path, typer.Option("--prompt", help="The prompt file the driver ran.")],
    model: Annotated[str, typer.Option("--model", help="The model the driver ran.")],
    tool: Annotated[
        list[str] | None,
        typer.Option("--tool", help="An allowed tool of the stage (repeat for each tool)."),
    ] = None,
    mcp_config: Annotated[
        Path | None,
        typer.Option("--mcp-config", help="The driver's MCP config; only its factory env kept."),
    ] = None,
    log: Annotated[
        Path | None,
        typer.Option("--log", help="The driver's log; records the run as ended (lost) at once."),
    ] = None,
) -> None:
    """Record the driver as a run and print its run id. Refused, with nothing written, when the
    stage, model or tools are not valid for the stage, or a run of the project is open."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state
    from factory.services import runner

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        run_id = runner.adopt_driver(
            project,
            stage=stage,
            prompt_file=prompt,
            model=model,
            tools=tool or [],
            mcp_config=mcp_config,
            log_file=log,
            started_at=None,
        )
    typer.echo(run_id)

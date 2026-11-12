"""`factory taxonomy`, `factory layers move` and `factory mine request` (IDEA-50, T8).

Parse, call a service, format. Business logic stays in `services/taxonomies.py` and
`services/work_layers.py`. Registration, the layer moves and mining requests are the researcher's
acts: they run with the human principal, and the services refuse any other actor. The shared
helpers of `factory.cli.main` are imported inside the commands, because that module imports this
one.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from factory.mining.taxonomy import taxonomy_to_json
from factory.services import taxonomies as taxonomies_service
from factory.services import taxonomy_agreement as taxonomy_agreement_service
from factory.services import work_layers as work_layers_service

taxonomy_app = typer.Typer(
    name="taxonomy",
    help="Versioned taxonomies: register (the researcher), view, list, diff, coverage, proposals.",
    no_args_is_help=True,
)
work_layers_app = typer.Typer(
    name="layers",
    help="Work layers: the researcher moves a work to another layer of the latest scheme.",
    no_args_is_help=True,
)


def _json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


@taxonomy_app.command("register")
def taxonomy_register_cmd(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help="A taxonomy specification (a JSON file).")],
) -> None:
    """Register a taxonomy version from a specification file (the researcher's act)."""
    from factory.cli.main import _fail, _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    try:
        body = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"{file}: cannot read a JSON specification ({exc})", 1)
    with _reporting_errors():
        project = _resolve_project(state)
        result = taxonomies_service.register_taxonomy(project, project.human_actor(), body)
    if result.written:
        typer.echo(f"registered {result.name} version {result.version} ({result.digest})")
    else:
        typer.echo(
            f"{result.name} version {result.version} already registered with this digest; "
            "nothing written"
        )


@taxonomy_app.command("view")
def taxonomy_view_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The taxonomy's name.")],
    version: Annotated[
        int | None,
        typer.Option(
            "--version", help="The version; without it the registered versions are listed."
        ),
    ] = None,
) -> None:
    """The specification of one registered version, or the registered versions of a taxonomy."""
    from factory.cli.main import _fail, _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        if version is None:
            versions = [r for r in taxonomies_service.list_taxonomies(project) if r.name == name]
            if not versions:
                _fail(f"no taxonomy named {name}", 1)
            for row in versions:
                typer.echo(f"{row.name} version {row.version} ({row.digest})")
            return
        found = taxonomies_service.taxonomy_row(project, name, version)
        spec = taxonomies_service.registered_taxonomy(project, name, version)
    if found is None or spec is None:
        _fail(f"{name} version {version} is not registered", 1)
    typer.echo(_json(taxonomy_to_json(spec)))


@taxonomy_app.command("list")
def taxonomy_list_cmd(ctx: typer.Context) -> None:
    """Every registered taxonomy version, by name then version."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        rows = taxonomies_service.list_taxonomies(project)
    if not rows:
        typer.echo("no taxonomy registered")
    for row in rows:
        typer.echo(
            f"{row.name} version {row.version} ({row.digest}); accepts {len(row.accepts)}, "
            f"rejects {len(row.rejects)}"
        )


@taxonomy_app.command("diff")
def taxonomy_diff_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The taxonomy's name.")],
    a: Annotated[int, typer.Argument(help="The older version.")],
    b: Annotated[int, typer.Argument(help="The newer version.")],
) -> None:
    """The computed difference from version A to version B."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        found = taxonomies_service.taxonomy_diff(project, name, a, b)
    typer.echo(_json(asdict(found)))


@taxonomy_app.command("coverage")
def taxonomy_coverage_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The taxonomy's name.")],
    version: Annotated[int, typer.Argument(help="The registered version.")],
    miner: Annotated[str, typer.Option("--miner", help="A descriptor miner's name.")],
    miner_version: Annotated[int, typer.Option("--miner-version", help="Its version.")],
    field: Annotated[
        list[str] | None,
        typer.Option("--field", help="DIM=FIELD[,FIELD...]: the miner's fields read for DIM."),
    ] = None,
) -> None:
    """Pattern coverage of the taxonomy over a descriptor miner's pass-A quotes. Computed."""
    from factory.cli.main import _fail, _reporting_errors, _resolve_project, _state

    fields: dict[str, tuple[str, ...]] = {}
    for item in field or []:
        dimension, sep, names = item.partition("=")
        if not sep or not dimension.strip():
            _fail(f"--field {item}: expected DIM=FIELD[,FIELD...]", 2)
        listed = tuple(n.strip() for n in names.split(",") if n.strip())
        fields[dimension.strip()] = fields.get(dimension.strip(), ()) + listed

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = taxonomies_service.taxonomy_coverage(
            project, name, version, miner=miner, miner_version=miner_version, fields=fields
        )
    typer.echo(_json(asdict(report)))


@taxonomy_app.command("proposals")
def taxonomy_proposals_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The taxonomy's name.")],
) -> None:
    """The change proposals against the taxonomy, each with its status."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        proposals = taxonomies_service.list_proposals(project, name)
    if not proposals:
        typer.echo(f"no proposal against {name}")
    for p in proposals:
        reason = "" if p.reason is None else f" ({p.reason})"
        typer.echo(
            f"{p.proposal_id} {p.kind} on version {p.base_version} "
            f"targets {', '.join(p.targets) or '-'}: {p.status}{reason}"
        )


@taxonomy_app.command("agreement")
def taxonomy_agreement_cmd(
    ctx: typer.Context,
    miner: Annotated[str, typer.Argument(help="A listed miner derived from a taxonomy.")],
) -> None:
    """Agreement of the two passes per dimension (computed; quotes are never compared)."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = taxonomy_agreement_service.taxonomy_agreement(project, miner)
    typer.echo(_json(asdict(report)))


@work_layers_app.command("move")
def layers_move_cmd(
    ctx: typer.Context,
    work: Annotated[str, typer.Argument(help="The work to move.")],
    layer: Annotated[str, typer.Argument(help="A layer of the latest scheme.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the researcher moves it.")],
) -> None:
    """Move a work to another layer of the latest recorded scheme (the researcher's act)."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        event_id = work_layers_service.move_layer(
            project, project.human_actor(), work, layer, reason
        )
    typer.echo(f"moved {work} to {layer} ({event_id})")


def mine_request_cmd(
    ctx: typer.Context,
    work: Annotated[
        list[str] | None, typer.Option("--work", help="A work to mine; repeatable.")
    ] = None,
    layer: Annotated[
        str | None, typer.Option("--layer", help="A layer: mine its included works.")
    ] = None,
    miner: Annotated[
        list[str] | None, typer.Option("--miner", help="An on-demand miner; repeatable.")
    ] = None,
    reason: Annotated[str | None, typer.Option("--reason", help="Why.")] = None,
) -> None:
    """Request mining beyond the protocol's automatic layers: give --work (repeatable) or
    --layer, and optionally the on-demand --miner names (the researcher's act). Registered on the
    existing `factory mine` group in `cli/main.py`."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        request_id = work_layers_service.request_mining(
            project,
            project.human_actor(),
            works=tuple(work or ()),
            layer=layer,
            miners=tuple(miner or ()),
            reason=reason,
        )
    typer.echo(f"requested mining ({request_id})")

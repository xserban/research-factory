"""`factory screen-check` (slice 8, H2): band checks, tuning batches and measurement batches.

Business logic stays in `services/screening_check.py`. The records of a draw are shown to the
person blind (title and abstract only); the agent's verdicts appear in the report. The shared
helpers of `factory.cli.main` are imported inside the commands, because that module imports this
one.
"""

from __future__ import annotations

from typing import Annotated

import typer

from factory.model.screening import Channel, PassLabel
from factory.model.screening_check import (
    DEFAULT_BANDS,
    DEFAULT_MEASUREMENT_SIZE,
    DEFAULT_PER_BAND,
    DEFAULT_TUNING_SIZE,
    CheckDrawn,
    CheckKind,
)
from factory.services import screening_check as service
from factory.services.context import Project
from factory.services.search import list_works

screen_check_app = typer.Typer(
    name="screen-check",
    help="Check the screener: band checks, tuning batches, measurement batches.",
    no_args_is_help=True,
)


def check_report_lines(report: service.ScreenCheckReport) -> list[str]:
    """The report as text: one line per band, then the disagreements."""
    head = f"{report.kind.value} {report.draw_id}"
    if report.name:
        head += f" ({report.name})"
    lines = [
        f"{head}: {report.labelled}/{report.drawn} labelled, pass {report.pass_label.value}, "
        f"seed {report.random_seed}"
    ]
    if report.bands:
        lines.append(
            "bands " + ", ".join(b.label for b in report.bands) + f"; {report.per_band} each"
        )
    for row in report.rows:
        rate = "n/a" if row.agreement is None else f"{row.agreement:.2f}"
        lines.append(
            f"  {row.band}: drawn {row.drawn}, labelled {row.labelled}, agreement {rate} "
            f"({row.agreed}/{row.compared}), human would add {row.would_add_includes} includes "
            f"and {row.would_add_excludes} excludes, undecided {row.undecided}"
        )
    if report.agreement is not None:
        lines.append(f"agreement {report.agreement:.2f}")
    if report.agreement_note:
        lines.append(report.agreement_note)
    for d in report.disagreements:
        score = "-" if d.score is None else str(d.score)
        lines.append(
            f"  {d.work_id}  agent {d.agent_verdict} (score {score}), "
            f"human {d.human_verdict}  {d.title}"
        )
    return lines


def _show(drawn: CheckDrawn, project_titles: dict[str, tuple[str, str]]) -> None:
    kind = drawn.kind.value
    typer.echo(f"{kind} {drawn.draw_id}: {len(drawn.items)} records (seed {drawn.random_seed})")
    for item in drawn.items:
        title, abstract = project_titles.get(item.work_id, ("", ""))
        typer.echo(f"{item.work_id}  [{item.band}]  {title}")
        if abstract:
            typer.echo(f"    {abstract}")


def _titles(project: Project) -> dict[str, tuple[str, str]]:
    return {w.id: (w.title, w.abstract or "") for w in list_works(project)}


@screen_check_app.command("band")
def band_cmd(
    ctx: typer.Context,
    stage: str = typer.Option("title-abstract", "--stage"),
    pass_label: Annotated[str, typer.Option("--pass", help="The pass drawn from: A or B.")] = "A",
    bands: Annotated[str, typer.Option("--bands", help="Score bands.")] = ",".join(
        b.label for b in DEFAULT_BANDS
    ),
    per_band: Annotated[int, typer.Option("--per-band")] = DEFAULT_PER_BAND,
    seed: Annotated[int | None, typer.Option("--seed", help="Random seed.")] = None,
) -> None:
    """Draw records of a pass, stratified by relevance score, for the person to label."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state
    from factory.model.protocol import ScreeningStage

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        drawn = service.draw_band_check(
            project,
            project.human_actor(),
            stage=ScreeningStage(stage),
            pass_label=PassLabel(pass_label.upper()),
            bands=service.parse_bands(bands),
            per_band=per_band,
            random_seed=seed,
        )
        titles = _titles(project)
    _show(drawn, titles)


@screen_check_app.command("tuning")
def tuning_cmd(
    ctx: typer.Context,
    stage: str = typer.Option("title-abstract", "--stage"),
    size: Annotated[int, typer.Option("--size")] = DEFAULT_TUNING_SIZE,
    name: Annotated[str | None, typer.Option("--name")] = None,
    seed: Annotated[int | None, typer.Option("--seed")] = None,
) -> None:
    """Draw a tuning batch: fresh records the agent screens first, then the person labels."""
    _fresh(ctx, CheckKind.TUNING, stage, size, name, seed)


@screen_check_app.command("measure")
def measure_cmd(
    ctx: typer.Context,
    stage: str = typer.Option("title-abstract", "--stage"),
    size: Annotated[int, typer.Option("--size")] = DEFAULT_MEASUREMENT_SIZE,
    name: Annotated[str | None, typer.Option("--name")] = None,
    seed: Annotated[int | None, typer.Option("--seed")] = None,
) -> None:
    """Draw a measurement batch: fresh, disjoint from tuning batches and example records."""
    _fresh(ctx, CheckKind.MEASUREMENT, stage, size, name, seed)


def _fresh(
    ctx: typer.Context, kind: CheckKind, stage: str, size: int, name: str | None, seed: int | None
) -> None:
    from factory.cli.main import _reporting_errors, _resolve_project, _state
    from factory.model.protocol import ScreeningStage

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        draw = (
            service.draw_tuning_batch
            if kind is CheckKind.TUNING
            else service.draw_measurement_batch
        )
        drawn = draw(
            project,
            project.human_actor(),
            stage=ScreeningStage(stage),
            size=size,
            name=name,
            random_seed=seed,
        )
        titles = _titles(project)
    _show(drawn, titles)


@screen_check_app.command("label")
def label_cmd(
    ctx: typer.Context,
    draw_id: Annotated[str, typer.Argument(help="The draw being labelled.")],
    work: Annotated[str, typer.Argument(help="A record of the draw.")],
    verdict: Annotated[str, typer.Argument(help="include or exclude.")],
) -> None:
    """A person's label on one drawn record."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        service.check_label(project, project.human_actor(), draw_id, work, verdict, Channel.CLI)
    typer.echo(f"labelled {work} in {draw_id} ({verdict})")


@screen_check_app.command("example")
def example_cmd(
    ctx: typer.Context,
    draw_id: Annotated[str, typer.Argument(help="The tuning batch.")],
    work: Annotated[str, typer.Argument(help="A labelled record the agent got wrong.")],
    criterion: Annotated[str, typer.Argument(help="The criterion the example belongs to.")],
    example_text: Annotated[str, typer.Argument(help="Title and a one-line reason.")],
) -> None:
    """Make a disagreement an example of a criterion, by a protocol amendment."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        result = service.add_tuning_example(
            project,
            project.human_actor(),
            draw_id,
            work,
            criterion,
            example_text,
            Channel.CLI,
        )
    typer.echo(f"amendment {result.amendment_id}: example added to {criterion}")


@screen_check_app.command("report")
def report_cmd(
    ctx: typer.Context,
    draw_id: Annotated[
        str | None, typer.Argument(help="A draw; the latest of --kind if absent.")
    ] = None,
    kind: Annotated[str, typer.Option("--kind", help="band, tuning or measurement.")] = "band",
    stage: str = typer.Option("title-abstract", "--stage"),
) -> None:
    """Agreement per band (band check), the disagreements (tuning), or the agreement on a
    current measurement batch."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state
    from factory.model.protocol import ScreeningStage

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = service.check_report(
            project, draw_id, kind=CheckKind(kind), stage=ScreeningStage(stage)
        )
    if report is None:
        typer.echo("no such draw")
        return
    for line in check_report_lines(report):
        typer.echo(line)


@screen_check_app.command("list")
def list_cmd(ctx: typer.Context, stage: str = typer.Option("title-abstract", "--stage")) -> None:
    """The draws of a stage."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state
    from factory.model.protocol import ScreeningStage

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        rows = service.check_list(project, stage=ScreeningStage(stage))
    if not rows:
        typer.echo("no draws")
    for row in rows:
        current = "" if row.current else "  (examples changed since)"
        typer.echo(
            f"{row.draw_id}  {row.kind.value}  {row.labelled}/{row.drawn} labelled"
            f"{' ' + row.name if row.name else ''}{current}"
        )

"""The `factory` command: parse arguments, call a service, format output. No business logic here."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, NoReturn

import typer

from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.mcp.server import run
from factory.model.identity import IdGenerator
from factory.model.screening import Channel
from factory.model.work import ProvenanceMethod
from factory.services import agreement as agreement_service
from factory.services import audit as audit_service
from factory.services import calibration as calibration_service
from factory.services import project as project_service
from factory.services import protocol as protocol_service
from factory.services import seeds as seeds_service
from factory.services.context import Project, list_projects, open_project
from factory.services.project import ScreeningStatus
from factory.services.search import list_works

app = typer.Typer(
    name="factory",
    help="Research Factory platform CLI.",
    no_args_is_help=True,
    add_completion=False,
)
seeds_app = typer.Typer(
    name="seeds",
    help="List the seeds with their hold-out roles, draw the split, explain a miss.",
    invoke_without_command=True,
    no_args_is_help=False,
)
protocol_app = typer.Typer(name="protocol", help="Confirm PRESS reviews.", no_args_is_help=True)
calibrate_app = typer.Typer(
    name="calibrate", help="Draw the calibration set and label it.", no_args_is_help=True
)
screen_app = typer.Typer(
    name="screen",
    help="Disagreements between the passes, and their resolution.",
    no_args_is_help=True,
)
audit_app = typer.Typer(
    name="audit", help="Sample, label and report the audit.", no_args_is_help=True
)
app.add_typer(seeds_app)
app.add_typer(protocol_app)
app.add_typer(calibrate_app)
app.add_typer(screen_app)
app.add_typer(audit_app)


@dataclass
class CliState:
    settings: Settings
    project: str | None
    session: str
    clock: Clock


def _state(ctx: typer.Context) -> CliState:
    state = ctx.obj
    if not isinstance(state, CliState):
        raise RuntimeError("CLI state missing; the root callback did not run")
    return state


def _fail(message: str, code: int) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code)


@contextmanager
def _reporting_errors() -> Iterator[None]:
    """Turn service errors into stderr lines and exit 1. Nothing is written on these paths."""
    try:
        yield
    except FactoryValidationError as exc:
        for issue in exc.issues:
            typer.echo(f"{issue.field}: {issue.reason}", err=True)
        raise typer.Exit(1) from None
    except ProjectNotFoundError as exc:
        _fail(str(exc), 1)


def _resolve_project(state: CliState) -> Project:
    """Open the `--project` slug, or the only project under the root. Ambiguity is exit 2."""
    if state.project is not None:
        try:
            return open_project(
                state.settings, state.project, session=state.session, clock=state.clock
            )
        except ProjectNotFoundError:
            _fail(f"unknown project: {state.project}", 1)
    slugs = list_projects(state.settings)
    if not slugs:
        _fail("no project; run factory init", 2)
    if len(slugs) > 1:
        _fail(f"several projects: {', '.join(slugs)}; pass --project", 2)
    return open_project(state.settings, slugs[0], session=state.session, clock=state.clock)


@app.callback()
def main(
    ctx: typer.Context,
    root: Annotated[
        Path | None,
        typer.Option(help="Factory root directory.", envvar="FACTORY_ROOT"),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option("--project", help="Project slug.", envvar="FACTORY_PROJECT"),
    ] = None,
) -> None:
    clock = SystemClock()
    with _reporting_errors():
        settings = Settings.load(root=root)
    ctx.obj = CliState(
        settings=settings,
        project=project,
        session=IdGenerator(clock).ulid(),
        clock=clock,
    )


@app.command()
def init(
    ctx: typer.Context,
    slug: Annotated[str, typer.Argument(help="New project slug.")],
    mode: Annotated[str, typer.Option("--mode", help="Rigor mode.")] = "pilot",
) -> None:
    """Create a project."""
    state = _state(ctx)
    with _reporting_errors():
        project_service.init_project(
            state.settings, slug, mode, session=state.session, clock=state.clock
        )
    typer.echo(f"initialised {slug} ({mode})")


@app.command()
def rebuild(ctx: typer.Context) -> None:
    """Rebuild the project index from the event log and print its state hash."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        digest = project.index.rebuild()
    typer.echo(f"state {digest}")


@app.command()
def status(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Print ProjectStatus as JSON.")] = False,
) -> None:
    """Show a project's rigor mode, event counts and task queue."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = project_service.project_status(project)
    if as_json:
        typer.echo(report.model_dump_json())
        return
    typer.echo(f"project: {report.slug}")
    typer.echo(f"rigor mode: {report.rigor_mode.value}")
    typer.echo(f"events: {report.events_total}")
    typer.echo(f"question: {report.question or 'none'}")
    protocol = report.protocol
    if protocol is None:
        typer.echo("protocol: none")
    else:
        typer.echo(
            f"protocol: {protocol.protocol_id} ({protocol.status.value}, PRESS {protocol.press})"
        )
    seeds = report.seeds
    drawn = "split drawn" if seeds.split_drawn else "not split"
    typer.echo(
        f"seeds: {seeds.positive} positive ({drawn}), {seeds.negative} negative, "
        f"{seeds.unresolved} unresolved"
    )
    tasks = report.tasks
    typer.echo(
        f"tasks: open {tasks.open} / claimed {tasks.claimed} / "
        f"expired {tasks.expired} / completed {tasks.completed}"
    )
    for line in _screening_lines(report.screening):
        typer.echo(line)
    typer.echo(f"works: {report.works} (records {report.records}, merges {report.merges_active})")
    search = report.search
    typer.echo(
        f"searches: {search.runs} runs (complete {search.complete} / partial {search.partial} / "
        f"failed {search.failed} / interrupted {search.interrupted})"
    )
    for short in search.shortfalls:
        typer.echo(
            f"shortfall: {short.run_id} {short.source} "
            f"{short.retrieved_count}/{short.reported_count} \u2014 {short.note or 'no note'}"
        )


def _screening_lines(screening: ScreeningStatus) -> list[str]:
    """The screening lines of `status`: counts and rates, never a work or a label."""
    cal = screening.calibration
    gate = "required" if cal.required else "not required"
    passed = ", ".join(f"{label} {'yes' if ok else 'no'}" for label, ok in cal.passed.items())
    lines = [
        f"calibration: drawn {cal.drawn}, labelled {cal.labelled}; gate {gate}; passed {passed}"
    ]
    for label, progress in screening.passes.items():
        if progress.queued is None:
            lines.append(f"pass {label}: not opened")
            continue
        sensitivity = _rate(cal.per_pass[label].sensitivity)
        lines.append(
            f"pass {label}: queued {progress.queued}, decided {progress.decided}, "
            f"remaining {progress.remaining}; calibration sensitivity {sensitivity}"
        )
    if screening.kappa is None and screening.unresolved_disagreements is None:
        lines.append("agreement: not available until both passes finish")
    else:
        disagreements = screening.unresolved_disagreements
        lines.append(
            f"agreement: kappa {_rate(screening.kappa)}, unresolved disagreements {disagreements}"
        )
    lines.append(f"stale decisions: {screening.stale_decisions}")
    if screening.audit_sample is None:
        lines.append("audit: none sampled")
    else:
        lines.append(
            f"audit: sample {screening.audit_sample}, labelled {screening.audit_labelled}, "
            f"false-exclusion rate {_rate(screening.false_exclusion_rate)}"
        )
    return lines


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _binary(verdict: str) -> Literal["include", "exclude"]:
    """A human's verdict on a disagreement or a label: include or exclude, else refused."""
    if verdict == "include":
        return "include"
    if verdict == "exclude":
        return "exclude"
    raise FactoryValidationError([ValidationIssue("verdict", "must be include or exclude")])


@seeds_app.callback()
def seeds(ctx: typer.Context) -> None:
    """Print every seed with its hold-out role. Held-out roles are shown to humans only."""
    if ctx.invoked_subcommand is not None:
        return
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        records = seeds_service.all_seeds(project)
        checks = {check.seed_id: check.status for check in seeds_service.seed_check(project)}
    header = ["id", "kind", "role", "resolution", "check"]
    rows = [
        [
            record.seed_id,
            record.kind.value,
            record.role.value,
            record.work_id
            or (f"unresolved: {record.unresolved_reason}" if record.unresolved_reason else "-"),
            checks.get(record.seed_id, "-"),
        ]
        for record in records
    ]
    table = [header, *rows]
    widths = [max(len(row[column]) for row in table) for column in range(len(header))]
    for row in table:
        typer.echo(
            "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        )


@seeds_app.command("split")
def seeds_split(
    ctx: typer.Context,
    random_seed: Annotated[
        int | None,
        typer.Option("--random-seed", help="The seed of the draw; omitted, 32 random bits."),
    ] = None,
) -> None:
    """Draw and record the hold-out split of the positive seeds."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        drawn = seeds_service.split_seeds(project, random_seed=random_seed)
    typer.echo(f"split drawn with random seed {drawn.random_seed}")


@seeds_app.command("explain")
def seeds_explain(
    ctx: typer.Context,
    seed_id: Annotated[str, typer.Argument(help="A positive seed, such as SEED03.")],
    route: Annotated[str, typer.Option(help="The admission route planned for the seed.")],
    reason: Annotated[str, typer.Option(help="Why the seed was not retrieved.")],
) -> None:
    """Record why a positive seed was not retrieved, and the route planned for it."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        try:
            method = ProvenanceMethod(route)
        except ValueError:
            choices = ", ".join(
                m.value for m in ProvenanceMethod if m is not ProvenanceMethod.DATABASE
            )
            raise FactoryValidationError(
                [ValidationIssue("route", f"must be one of: {choices}")]
            ) from None
        seeds_service.explain_seed_miss(project, project.human_actor(), seed_id, reason, method)
    typer.echo(f"explained {seed_id} ({route})")


@protocol_app.command("confirm-press")
def protocol_confirm_press(
    ctx: typer.Context,
    review_id: Annotated[str, typer.Argument(help="The PRESS review to confirm.")],
    response: Annotated[
        list[str] | None,
        typer.Option("--response", help="A response to one finding; give one per finding."),
    ] = None,
) -> None:
    """A human's confirmation of a PRESS review, one response per finding in order."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        protocol_service.confirm_press(
            project, project.human_actor(), review_id, list(response or [])
        )
    typer.echo(f"confirmed {review_id}")


@app.command()
def serve(ctx: typer.Context) -> None:
    """Run the MCP server on stdio."""
    run(_state(ctx).settings)


@calibrate_app.command("draw")
def calibrate_draw(ctx: typer.Context) -> None:
    """Draw the calibration set once; a later draw returns the same set."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        items = calibration_service.draw_calibration(project, project.human_actor())
    typer.echo(f"calibration set: {len(items)} works")


@calibrate_app.command("label")
def calibrate_label(
    ctx: typer.Context,
    work: Annotated[str, typer.Argument(help="A work of the calibration set.")],
    verdict: Annotated[str, typer.Argument(help="include or exclude.")],
    criterion: Annotated[
        str | None, typer.Option("--criterion", help="The EX criterion of an exclusion.")
    ] = None,
) -> None:
    """A human's label on one work of the calibration set."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        calibration_service.label_calibration(
            project, project.human_actor(), work, verdict, criterion, Channel.CLI
        )
    typer.echo(f"labelled {work} ({verdict})")


@screen_app.command("disagreements")
def screen_disagreements(ctx: typer.Context) -> None:
    """List the works the two passes disagree on, each pass's decision and quote."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        agreement = agreement_service.screen_agreement(project, project.human_actor())
    if not agreement.disagreements:
        typer.echo("no unresolved disagreements")
        return
    for disagreement in agreement.disagreements:
        typer.echo(f"{disagreement.work_id}  reason {disagreement.reason}")
        for label, view in (("A", disagreement.a), ("B", disagreement.b)):
            cited = view.criterion or "-"
            typer.echo(
                f"  {label}: {view.verdict.value} {cited}  quote: {view.quote}  "
                f"rationale: {view.rationale}"
            )


@screen_app.command("resolve")
def screen_resolve(
    ctx: typer.Context,
    work: Annotated[str, typer.Argument(help="A disputed work.")],
    verdict: Annotated[str, typer.Argument(help="include or exclude.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the human decided.")],
    criterion: Annotated[
        str | None, typer.Option("--criterion", help="The EX criterion of an exclusion.")
    ] = None,
) -> None:
    """The human's verdict on a disagreement, or on an unsure single-pass work."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        agreement_service.resolve_disagreement(
            project,
            project.human_actor(),
            work,
            _binary(verdict),
            criterion,
            reason,
            Channel.CLI,
        )
    typer.echo(f"resolved {work} ({verdict})")


@audit_app.command("sample")
def audit_sample_cmd(ctx: typer.Context) -> None:
    """Draw the audit sample of the agreed works; each work with its agreed verdict and title."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        drawn = audit_service.audit_sample(project, project.human_actor())
        titles = {work.id: work.title for work in list_works(project)}
        agreed = agreement_service.agreed_works(project)
    typer.echo(
        f"audit {drawn.audit_id}: {len(drawn.work_ids)} of {drawn.population} agreed works "
        f"({drawn.exclusions} exclusions, {drawn.inclusions} inclusions)"
    )
    for work_id in drawn.work_ids:
        typer.echo(f"{work_id}  agreed {agreed[work_id].verdict}  {titles[work_id]}")


@audit_app.command("label")
def audit_label(
    ctx: typer.Context,
    audit_id: Annotated[str, typer.Argument(help="The audit being labelled.")],
    work: Annotated[str, typer.Argument(help="A work of the audit sample.")],
    verdict: Annotated[str, typer.Argument(help="include or exclude.")],
    criterion: Annotated[
        str | None, typer.Option("--criterion", help="The EX criterion of an exclusion.")
    ] = None,
) -> None:
    """A human's label on one sampled work."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        audit_service.audit_record(
            project, project.human_actor(), audit_id, work, verdict, criterion, Channel.CLI
        )
    typer.echo(f"labelled {work} in {audit_id} ({verdict})")


@audit_app.command("report")
def audit_report_cmd(ctx: typer.Context) -> None:
    """The latest audit's labelled count, false-exclusion rate and implicated criteria."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = audit_service.audit_report(project)
    if report is None:
        typer.echo("no audit sampled")
        return
    above = "yes" if report.above_ceiling else "no"
    typer.echo(f"audit {report.audit_id}: sample {report.sample_size}, labelled {report.labelled}")
    typer.echo(
        f"false-exclusion rate {_rate(report.rates.false_exclusion)} "
        f"(ceiling {report.ceiling:.2f}, above ceiling: {above})"
    )
    typer.echo(f"criteria implicated: {', '.join(report.criteria_implicated) or 'none'}")

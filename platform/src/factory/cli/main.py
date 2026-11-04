"""The `factory` command: parse arguments, call a service, format output. No business logic here."""

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, NoReturn

import typer

from factory.cli import evidence_render, portfolio_render, render
from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.document.registry import default_converters
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.imports.model import ImportFormat, ImportRole
from factory.mcp.conventions import parse_routes
from factory.mcp.server import run
from factory.model.chase import ChaseDirection
from factory.model.fulltext import Route
from factory.model.identity import IdGenerator
from factory.model.project import RigorMode
from factory.model.protocol import ScreeningStage
from factory.model.references import Decision, Direction, LinkState
from factory.model.screening import Channel
from factory.model.watch import CycleStatus
from factory.model.work import ProvenanceMethod
from factory.services import agreement as agreement_service
from factory.services import audit as audit_service
from factory.services import calibration as calibration_service
from factory.services import chase as chase_service
from factory.services import check as check_service
from factory.services import discovery as discovery_service
from factory.services import document_convert as document_convert_service
from factory.services import document_read as document_read_service
from factory.services import evidence as evidence_service
from factory.services import evidence_report as evidence_report_service
from factory.services import exports as exports_service
from factory.services import extraction as extraction_service
from factory.services import extraction_agreement as extraction_agreement_service
from factory.services import extraction_audit as extraction_audit_service
from factory.services import fulltext as fulltext_service
from factory.services import fulltext_import as fulltext_import_service
from factory.services import fulltext_status as fulltext_status_service
from factory.services import import_admit as import_admit_service
from factory.services import import_attach as import_attach_service
from factory.services import import_resolve as import_resolve_service
from factory.services import imports as imports_service
from factory.services import inbox as inbox_service
from factory.services import methods as methods_service
from factory.services import portfolio as portfolio_service
from factory.services import prisma as prisma_service
from factory.services import project as project_service
from factory.services import protocol as protocol_service
from factory.services import reference_resolve as reference_resolve_service
from factory.services import references as references_service
from factory.services import seeds as seeds_service
from factory.services import snapshots as snapshot_service
from factory.services import snowball as snowball_service
from factory.services import trace as trace_service
from factory.services import watch as watch_service
from factory.services.context import Project, list_projects, open_project
from factory.services.extraction_agreement import Choice
from factory.services.living_hooks import DEFAULT_HOOKS
from factory.services.project import ScreeningStatus
from factory.services.search import list_works
from factory.sources.fulltext.registry import default_routes
from factory.sources.registry import default_sources


class StageChoice(StrEnum):
    """The stages a screening run can have; `either` is a criterion's scope, not a stage."""

    TITLE_ABSTRACT = "title-abstract"
    FULL_TEXT = "full-text"


StageOption = Annotated[
    StageChoice, typer.Option("--stage", help="The screening stage: title-abstract or full-text.")
]


class ExtractChoice(StrEnum):
    """A human's choice on an extraction disagreement."""

    A = "a"
    B = "b"
    NEITHER = "neither"


_CHOICES: dict[ExtractChoice, Choice] = {
    ExtractChoice.A: "a",
    ExtractChoice.B: "b",
    ExtractChoice.NEITHER: "neither",
}


def _stage(choice: StageChoice) -> ScreeningStage:
    return ScreeningStage(choice.value)


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
search_app = typer.Typer(
    name="search", help="Citation chasing from the included works.", no_args_is_help=True
)
audit_app = typer.Typer(
    name="audit", help="Sample, label and report the audit.", no_args_is_help=True
)
fulltext_app = typer.Typer(
    name="fulltext",
    help="Full text: fetch, status, restore, and import the researcher's PDFs.",
    no_args_is_help=True,
)
document_app = typer.Typer(
    name="document",
    help="Convert retrieved documents to Markdown, check them, and read them.",
    no_args_is_help=True,
)
extract_app = typer.Typer(
    name="extract",
    help="Extraction: unit status, agreement, resolution and the audit.",
    no_args_is_help=True,
)
import_app = typer.Typer(
    name="import",
    help="Import an existing library (BibTeX, CSL JSON, a PDF folder); list and show imports.",
    no_args_is_help=True,
)
report_app = typer.Typer(
    name="report",
    help="PRISMA flow, search report, methods statement and evidence report.",
    no_args_is_help=True,
)
export_app = typer.Typer(
    name="export",
    help="Bibliography (BibTeX, CSL-JSON) and the PRISMA diagram (SVG), from the events.",
    no_args_is_help=True,
)
watch_app = typer.Typer(
    name="watch",
    help="Run the due watch cycle, show the watch status and plan.",
    no_args_is_help=True,
)
living_app = typer.Typer(
    name="living",
    help="Living review: snapshots and the PRISMA update flow.",
    no_args_is_help=True,
)
inbox_app = typer.Typer(
    name="inbox",
    help="Supplied links: capture, list, resolve into the corpus, withdraw.",
    no_args_is_help=True,
)
references_app = typer.Typer(
    name="references",
    help="Reference lists of the included works: extract, status, list, decide.",
    no_args_is_help=True,
)
snowball_app = typer.Typer(
    name="snowball", help="Snowball rounds: plan, run, compare.", no_args_is_help=True
)
app.add_typer(references_app)
app.add_typer(snowball_app)
app.add_typer(seeds_app)
app.add_typer(watch_app)
app.add_typer(living_app)
app.add_typer(inbox_app)
app.add_typer(report_app)
app.add_typer(export_app)
app.add_typer(protocol_app)
app.add_typer(calibrate_app)
app.add_typer(screen_app)
app.add_typer(audit_app)
app.add_typer(search_app)
app.add_typer(fulltext_app)
app.add_typer(document_app)
app.add_typer(extract_app)
app.add_typer(import_app)


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
        + (f" / abandoned {tasks.abandoned}" if tasks.abandoned else "")
    )
    for line in [*_screening_lines(report.screening), *_full_text_lines(report.screening)]:
        typer.echo(line)
    typer.echo(f"chase rounds: {report.chase_rounds}")
    typer.echo(f"admitted seeds: {report.admitted_seeds}")
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
    if report.human is not None and report.human.items:
        typer.echo("waiting on you:")
        for item in report.human.items:
            stage = "" if item.stage is None else f" ({item.stage})"
            typer.echo(f"  {item.gate.value}{stage}: {item.count} \u2014 {item.command}")


@app.command("portfolio")
def portfolio_cmd(
    ctx: typer.Context,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the Portfolio model as JSON.")
    ] = False,
    html: Annotated[
        Path | None, typer.Option("--html", help="Write a self-contained HTML report here.")
    ] = None,
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="ISO timestamp for ages and the stamp; default: now."),
    ] = None,
) -> None:
    """Every project: derived stage, open work and pending human decisions. Writes no event."""
    state = _state(ctx)
    moment = state.clock.now()
    if as_of is not None:
        try:
            moment = datetime.fromisoformat(as_of)
        except ValueError:
            _fail(f"--as-of: not an ISO timestamp: {as_of}", 2)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
    if html is not None and html.is_dir():
        _fail(f"--html: {html} is a directory", 1)
    with _reporting_errors():
        built = portfolio_service.portfolio(state.settings, clock=state.clock, as_of=moment)
    if not built.projects:
        _fail("no project; run factory init", 2)
    if html is not None:
        try:
            html.write_text(portfolio_render.render_html(built, moment), encoding="utf-8")
        except OSError as exc:
            _fail(f"--html: {exc.strerror or 'cannot write'}: {html}", 1)
    if as_json:
        typer.echo(built.model_dump_json())
    elif html is None:
        typer.echo(portfolio_render.render_markdown(built, moment), nl=False)
    if all(row.error is not None for row in built.projects):
        _fail("no project could be read", 1)


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


def _full_text_lines(screening: ScreeningStatus) -> list[str]:
    """Pass progress at full text: nothing while the protocol declares no full-text plan."""
    if screening.full_text_passes is None:
        return []
    lines: list[str] = []
    for label, progress in screening.full_text_passes.items():
        if progress.queued is None:
            lines.append(f"full-text pass {label}: not opened")
        else:
            lines.append(
                f"full-text pass {label}: queued {progress.queued}, "
                f"decided {progress.decided}, remaining {progress.remaining}"
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
    """Print every seed with its hold-out role and, for a retrieved positive, the route that found
    it. Held-out roles and seed routes are shown to humans only."""
    if ctx.invoked_subcommand is not None:
        return
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        records = seeds_service.all_seeds(project)
        checks = {
            check.seed_id: check.status
            if check.found_by is None
            else f"{check.status} ({check.found_by})"
            for check in seeds_service.seed_check(project)
        }
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
                m.value
                for m in ProvenanceMethod
                if m not in (ProvenanceMethod.DATABASE, ProvenanceMethod.SUPPLIED)
            )
            raise FactoryValidationError(
                [ValidationIssue("route", f"must be one of: {choices}")]
            ) from None
        seeds_service.explain_seed_miss(project, project.human_actor(), seed_id, reason, method)
    typer.echo(f"explained {seed_id} ({route})")


@seeds_app.command("admit")
def seeds_admit(
    ctx: typer.Context,
    seed_id: Annotated[
        str, typer.Argument(help="A positive seed explained as a seed-admission miss.")
    ],
    deviation: Annotated[
        str | None,
        typer.Option("--deviation", help="A recorded deviation that authorises the lookup."),
    ] = None,
) -> None:
    """Look up an explained seed-admission miss by its identifier and admit what is found.

    The lookup is a query like any other: in a pilot or systematic project the protocol must
    plan it, or a recorded deviation (`--deviation`) must authorise it."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        admitted = seeds_service.admit_seed(
            project,
            project.human_actor(),
            seed_id,
            sources=dict(default_sources()),
            deviation_id=deviation,
        )
    found = "found a work" if admitted.work_id else "found no work"
    typer.echo(f"admitted {seed_id} ({found})")


@inbox_app.command("add")
def inbox_add(
    ctx: typer.Context,
    links: Annotated[list[str], typer.Argument(help="arXiv, DOI or OpenAlex links or ids.")],
    note: Annotated[
        str | None, typer.Option("--note", help="A short note (at most 300 characters).")
    ] = None,
) -> None:
    """Capture links as inbox items. Offline; an unsupported link is reported and not written."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        items = [inbox_service.LinkInput(link, note=note) for link in links]
        result = inbox_service.add_links(project, project.human_actor(), items, Channel.CLI)
    for item_id in result.written:
        typer.echo(f"captured {item_id}")
    for error in result.rejected:
        reasons = "; ".join(f"{i.field}: {i.reason}" for i in error.issues)
        typer.echo(f"rejected {links[error.index]}  {reasons}", err=True)
    if result.rejected:
        raise typer.Exit(1)


@inbox_app.command("list")
def inbox_list(
    ctx: typer.Context,
    status: Annotated[
        str | None, typer.Option("--status", help="open, resolved or withdrawn.")
    ] = None,
    cursor: Annotated[str | None, typer.Option("--cursor", help="Next page offset.")] = None,
) -> None:
    """Inbox items with their status and last resolution outcome."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        page = inbox_service.list_items(project, status=status, cursor=cursor)
    for line in render.inbox_lines(page):
        typer.echo(line)


@inbox_app.command("resolve")
def inbox_resolve(
    ctx: typer.Context,
    item: Annotated[
        list[str] | None, typer.Option("--item", help="Resolve only these open items.")
    ] = None,
    deviation: Annotated[
        str | None,
        typer.Option("--deviation", help="A recorded deviation that authorises the lookups."),
    ] = None,
) -> None:
    """Look up open items by identifier as recorded `supplied` queries, gated by the protocol."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        outcomes = inbox_service.resolve_links(
            project,
            project.human_actor(),
            sources=dict(default_sources()),
            item_ids=item or None,
            deviation_id=deviation,
        )
    for line in render.resolve_lines(outcomes):
        typer.echo(line)


@inbox_app.command("withdraw")
def inbox_withdraw(
    ctx: typer.Context,
    item_id: Annotated[str, typer.Argument(help="An open inbox item.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the link is withdrawn.")],
) -> None:
    """Withdraw an open item; a resolved item stays (its work leaves only by screening)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        inbox_service.withdraw_link(project, project.human_actor(), item_id, reason)
    typer.echo(f"withdrew {item_id}")


@search_app.command("chase")
def search_chase_cmd(
    ctx: typer.Context,
    backward: Annotated[
        bool, typer.Option("--backward", help="Works the included works cite.")
    ] = False,
    forward: Annotated[
        bool, typer.Option("--forward", help="Works that cite the included works.")
    ] = False,
) -> None:
    """Chase citations from the included works; with neither flag, in both directions."""
    state = _state(ctx)
    directions = [
        direction
        for direction, wanted in (
            (ChaseDirection.BACKWARD, backward or not forward),
            (ChaseDirection.FORWARD, forward or not backward),
        )
        if wanted
    ]
    with _reporting_errors():
        project = _resolve_project(state)
        summary = chase_service.search_chase(
            project, project.human_actor(), directions, sources=dict(default_sources())
        )
    typer.echo(
        f"chase round {summary.round_id}: {len(summary.runs)} queries, "
        f"{summary.new_works} new works, {len(summary.unchasable)} unchasable"
    )


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


@references_app.command("extract")
def references_extract_cmd(
    ctx: typer.Context,
    work: Annotated[
        list[str] | None, typer.Option("--work", help="A work to extract; repeatable.")
    ] = None,
) -> None:
    """Extract and resolve the reference lists; default: every included work not yet extracted."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        summary = references_service.extract_references(
            project, project.human_actor(), work, sources=dict(default_sources())
        )
    for line in render.extract_summary_lines(summary):
        typer.echo(line)


@references_app.command("status")
def references_status_cmd(ctx: typer.Context) -> None:
    """Counts over the live extractions; the four link states sum to the entries."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        counts = references_service.reference_counts(project)
    for line in render.reference_counts_lines(counts):
        typer.echo(line)


@references_app.command("list")
def references_list_cmd(
    ctx: typer.Context,
    state_filter: Annotated[
        str | None, typer.Option("--state", help="resolved, unconfirmed, ambiguous or unresolved.")
    ] = None,
    work: Annotated[str | None, typer.Option("--work", help="A citing work.")] = None,
    after: Annotated[int, typer.Option("--after", help="Items already seen.")] = 0,
    limit: Annotated[int, typer.Option("--limit", help="At most 100.")] = 50,
) -> None:
    """Entries with their links."""
    state = _state(ctx)
    with _reporting_errors():
        parsed = None
        if state_filter is not None:
            try:
                parsed = LinkState(state_filter)
            except ValueError:
                choices = ", ".join(s.value for s in LinkState)
                raise FactoryValidationError(
                    [ValidationIssue("state", f"must be one of: {choices}")]
                ) from None
        project = _resolve_project(state)
        page = references_service.list_references(
            project, state=parsed, work_id=work, after=after, limit=limit
        )
    for line in render.reference_page_lines(page):
        typer.echo(line)


@references_app.command("decide")
def references_decide_cmd(
    ctx: typer.Context,
    extraction: Annotated[str, typer.Argument(help="The extraction id (rex_...).")],
    ordinal: Annotated[int, typer.Argument(help="The entry's ordinal.")],
    confirm: Annotated[bool, typer.Option("--confirm", help="Confirm the link.")] = False,
    reject: Annotated[bool, typer.Option("--reject", help="Reject the link.")] = False,
    rationale: Annotated[str, typer.Option("--rationale", help="Why.")] = "",
    entry_quote: Annotated[
        str, typer.Option("--entry-quote", help="Verbatim from the entry.")
    ] = "",
    candidate_quote: Annotated[
        str, typer.Option("--candidate-quote", help="Verbatim from the candidate's title/authors.")
    ] = "",
    work: Annotated[str | None, typer.Option("--work", help="The candidate work.")] = None,
) -> None:
    """The human's binding decision on an unconfirmed or ambiguous link."""
    state = _state(ctx)
    if confirm == reject:
        _fail("give exactly one of --confirm and --reject", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        reference_resolve_service.decide_reference(
            project,
            project.human_actor(),
            extraction,
            ordinal,
            Decision.CONFIRM if confirm else Decision.REJECT,
            rationale=rationale,
            quotes=(entry_quote, candidate_quote),
            work_id=work,
        )
    typer.echo(f"{'confirmed' if confirm else 'rejected'} {extraction}:{ordinal}")


def _round_direction(value: str) -> Direction:
    try:
        return Direction(value)
    except ValueError:
        _fail("direction must be backward or forward", 2)


@snowball_app.command("plan")
def snowball_plan_cmd(
    ctx: typer.Context,
    direction: Annotated[str, typer.Argument(help="backward or forward.")],
) -> None:
    """A dry run: what a round would do, the candidates ranked, and the plan's gaps."""
    state = _state(ctx)
    parsed = _round_direction(direction)
    with _reporting_errors():
        project = _resolve_project(state)
        result = snowball_service.snowball_round(
            project, project.human_actor(), parsed, sources=dict(default_sources()), dry_run=True
        )
        gaps = snowball_service.plan_gaps(project)
    for line in render.round_plan_lines(parsed.value, result, gaps):
        typer.echo(line)


@snowball_app.command("run")
def snowball_run_cmd(
    ctx: typer.Context,
    direction: Annotated[str, typer.Argument(help="backward or forward.")],
) -> None:
    """Record and run a round (the researcher's go-ahead is this command)."""
    state = _state(ctx)
    parsed = _round_direction(direction)
    with _reporting_errors():
        project = _resolve_project(state)
        result = snowball_service.snowball_round(
            project, project.human_actor(), parsed, sources=dict(default_sources()), dry_run=False
        )
    for line in render.round_result_lines(result):
        typer.echo(line)


@snowball_app.command("compare")
def snowball_compare_cmd(
    ctx: typer.Context, round_id: Annotated[str, typer.Argument(help="A backward round.")]
) -> None:
    """A backward round's resolved references against the chase rounds."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        comparison = snowball_service.snowball_compare(project, round_id)
    for line in render.comparison_lines(comparison):
        typer.echo(line)


@app.command()
def serve(ctx: typer.Context) -> None:
    """Run the MCP server on stdio."""
    run(_state(ctx).settings)


@calibrate_app.command("draw")
def calibrate_draw(ctx: typer.Context, stage: StageOption = StageChoice.TITLE_ABSTRACT) -> None:
    """Draw the calibration set once; a later draw returns the same set."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        run_stage = _stage(stage)
        items = calibration_service.draw_calibration(
            project, project.human_actor(), stage=run_stage
        )
        found = {
            item: evidence_service.work_evidence(project, item, run_stage, include_decisions=False)
            for item in items
        }
    typer.echo(f"calibration set: {len(items)} works")
    if run_stage is ScreeningStage.FULL_TEXT:
        for item in items:
            typer.echo(item)
            for line in render.evidence_lines(
                item, found[item].document_id, found[item].conversion_id
            ):
                typer.echo(line)


@calibrate_app.command("label")
def calibrate_label(
    ctx: typer.Context,
    work: Annotated[str, typer.Argument(help="A work of the calibration set.")],
    verdict: Annotated[str, typer.Argument(help="include or exclude.")],
    criterion: Annotated[
        str | None, typer.Option("--criterion", help="The EX criterion of an exclusion.")
    ] = None,
    stage: StageOption = StageChoice.TITLE_ABSTRACT,
) -> None:
    """A human's label on one work of the calibration set."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        calibration_service.label_calibration(
            project,
            project.human_actor(),
            work,
            verdict,
            criterion,
            Channel.CLI,
            stage=_stage(stage),
        )
    typer.echo(f"labelled {work} ({verdict})")


@screen_app.command("disagreements")
def screen_disagreements(
    ctx: typer.Context, stage: StageOption = StageChoice.TITLE_ABSTRACT
) -> None:
    """List the works the two passes disagree on, each pass's decision and quote."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        agreement = agreement_service.screen_agreement(
            project, project.human_actor(), stage=_stage(stage)
        )
    if not agreement.disagreements:
        typer.echo("no unresolved disagreements")
        return
    for disagreement in agreement.disagreements:
        typer.echo(f"{disagreement.work_id}  reason {disagreement.reason}")
        first = disagreement.a
        for line in render.evidence_lines(
            disagreement.work_id, first.document_id, first.conversion_id
        ):
            typer.echo(line)
        for label, view in (("A", disagreement.a), ("B", disagreement.b)):
            for line in render.decision_lines(label, view):
                typer.echo(line)


@screen_app.command("resolve")
def screen_resolve(
    ctx: typer.Context,
    work: Annotated[str, typer.Argument(help="A disputed work.")],
    verdict: Annotated[str, typer.Argument(help="include or exclude.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the human decided.")],
    criterion: Annotated[
        str | None, typer.Option("--criterion", help="The EX criterion of an exclusion.")
    ] = None,
    stage: StageOption = StageChoice.TITLE_ABSTRACT,
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
            stage=_stage(stage),
        )
    typer.echo(f"resolved {work} ({verdict})")


@audit_app.command("sample")
def audit_sample_cmd(
    ctx: typer.Context,
    stage: StageOption = StageChoice.TITLE_ABSTRACT,
    top_up: Annotated[
        bool,
        typer.Option("--top-up", help="Extend the previous audit over works agreed since."),
    ] = False,
) -> None:
    """Draw the audit sample of the agreed works; each work with its agreed verdict and title."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        drawn = audit_service.audit_sample(
            project, project.human_actor(), stage=_stage(stage), top_up=top_up
        )
        titles = {work.id: work.title for work in list_works(project)}
        agreed = agreement_service.agreed_works(project, stage=_stage(stage))
        found = {
            work_id: evidence_service.work_evidence(project, work_id, _stage(stage))
            for work_id in drawn.work_ids
        }
    typer.echo(
        f"audit {drawn.audit_id}: {len(drawn.work_ids)} of {drawn.population} agreed works "
        f"({drawn.exclusions} exclusions, {drawn.inclusions} inclusions)"
    )
    for work_id in drawn.work_ids:
        typer.echo(f"{work_id}  agreed {agreed[work_id].verdict}  {titles[work_id]}")
        item = found[work_id]
        for line in render.evidence_lines(work_id, item.document_id, item.conversion_id):
            typer.echo(line)
        for label, view in item.decisions.items():
            for line in render.decision_lines(label, view):
                typer.echo(line)


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
def audit_report_cmd(ctx: typer.Context, stage: StageOption = StageChoice.TITLE_ABSTRACT) -> None:
    """The latest audit's labelled count, false-exclusion rate and implicated criteria."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = audit_service.audit_report(project, stage=_stage(stage))
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
    for line in render.audit_item_lines(report):
        typer.echo(line)


@extract_app.command("status")
def extract_status_cmd(ctx: typer.Context) -> None:
    """Extraction units per pass: current, open, queued and stale."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        states = extraction_service.unit_states(project)
    for line in render.extraction_status_lines(states):
        typer.echo(line)


@extract_app.command("agreement")
def extract_agreement_cmd(ctx: typer.Context) -> None:
    """The agreement of the two extraction passes and the unresolved disagreements."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        agreement = extraction_agreement_service.extraction_agreement(
            project, project.human_actor()
        )
    for line in render.agreement_lines(agreement):
        typer.echo(line)


@extract_app.command("resolve")
def extract_resolve_cmd(
    ctx: typer.Context,
    work: Annotated[str, typer.Argument(help="A work with a disagreement.")],
    row_key: Annotated[str, typer.Argument(help="The disputed row.")],
    choice: Annotated[ExtractChoice, typer.Option("--choice", help="a, b or neither.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the human decided.")],
    field: Annotated[
        str | None, typer.Option("--field", help="One field; the whole row when omitted.")
    ] = None,
) -> None:
    """The human's choice between the passes on one disagreement."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        extraction_agreement_service.resolve_extraction(
            project,
            project.human_actor(),
            work,
            row_key,
            field,
            _CHOICES[choice],
            reason,
            Channel.CLI,
        )
    typer.echo(f"resolved {work} {row_key} {field or 'row'} ({choice.value})")


@extract_app.command("audit-sample")
def extract_audit_sample_cmd(ctx: typer.Context) -> None:
    """Draw the extraction audit sample; each value with its quote and the cited element text."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        human = project.human_actor()
        drawn = extraction_audit_service.extraction_audit_sample(project, human)
        evidence = extraction_audit_service.audit_evidence(
            project, human, drawn.audit_id, Channel.CLI
        )
    typer.echo(f"audit {drawn.audit_id}: {len(drawn.items)} of {drawn.population} agreed values")
    for item in evidence:
        for line in render.audit_evidence_lines(item):
            typer.echo(line)


@extract_app.command("audit-label")
def extract_audit_label_cmd(
    ctx: typer.Context,
    audit_id: Annotated[str, typer.Argument(help="The audit being labelled.")],
    work: Annotated[str, typer.Argument(help="A work of the audit sample.")],
    row_key: Annotated[str, typer.Argument(help="The sampled row.")],
    field: Annotated[str, typer.Argument(help="The sampled field.")],
    correct: Annotated[
        bool, typer.Option("--correct/--incorrect", help="Whether the value was extracted right.")
    ],
    note: Annotated[str, typer.Option("--note", help="An optional note.")] = "",
) -> None:
    """A human's label on one sampled value."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        extraction_audit_service.extraction_audit_record(
            project,
            project.human_actor(),
            audit_id,
            work,
            row_key,
            field,
            correct,
            note,
            Channel.CLI,
        )
    typer.echo(
        f"labelled {work} {row_key} {field} in {audit_id} ({'correct' if correct else 'incorrect'})"
    )


@extract_app.command("audit-report")
def extract_audit_report_cmd(ctx: typer.Context) -> None:
    """The latest extraction audit's counts and error rate."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = extraction_audit_service.extraction_audit_report(project)
    if report is None:
        typer.echo("no audit sampled")
        return
    for line in render.audit_report_lines(report):
        typer.echo(line)


_JSON = Annotated[bool, typer.Option("--json", help="Print the report model as JSON.")]


class PrismaFormat(StrEnum):
    MD = "md"
    SVG = "svg"


@report_app.command("prisma")
def report_prisma(
    ctx: typer.Context,
    as_json: _JSON = False,
    fmt: Annotated[
        PrismaFormat, typer.Option("--format", help="Markdown (default) or the SVG diagram.")
    ] = PrismaFormat.MD,
) -> None:
    """The PRISMA 2020 flow, computed from the events."""
    state = _state(ctx)
    if as_json and fmt is PrismaFormat.SVG:
        _fail("--json and --format svg are exclusive", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        if fmt is PrismaFormat.SVG:
            svg = exports_service.export_prisma_svg(project)
        else:
            flow = prisma_service.prisma_flow(project)
    if fmt is PrismaFormat.SVG:
        typer.echo(svg, nl=False)
        return
    typer.echo(flow.model_dump_json() if as_json else render.prisma_markdown(flow), nl=as_json)


def _emit(chunks: Iterable[str], out: Path | None) -> None:
    """Stream `chunks` to `out` (overwriting it without asking) or to stdout."""
    if out is None:
        for chunk in chunks:
            typer.echo(chunk, nl=False)
        return
    try:
        with out.open("w", encoding="utf-8") as handle:
            for chunk in chunks:
                handle.write(chunk)
    except OSError as exc:
        _fail(f"cannot write {out}: {exc.strerror or exc}", 1)


_SCOPE = Annotated[
    str | None, typer.Option("--scope", help="included (default) or corpus; not with --id.")
]
_IDS = Annotated[list[str] | None, typer.Option("--id", help="A work id (repeatable).")]
_OUT = Annotated[
    Path | None, typer.Option("--out", help="Write here (overwritten) instead of printing.")
]


def _export_bibliography(
    ctx: typer.Context,
    fmt: Literal["bibtex", "csl"],
    scope: str | None,
    ids: list[str] | None,
    ascii_only: bool,
    out: Path | None,
) -> None:
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        chunks = exports_service.export_bibliography(
            project,
            fmt,
            scope=scope,
            ids=ids or (),
            ascii_only=ascii_only,
        )
        _emit(chunks, out)


@export_app.command("bibtex")
def export_bibtex(
    ctx: typer.Context,
    scope: _SCOPE = None,
    ids: _IDS = None,
    ascii_only: Annotated[
        bool, typer.Option("--ascii", help="Escape non-ASCII characters as LaTeX.")
    ] = False,
    out: _OUT = None,
) -> None:
    """The bibliography as BibTeX."""
    _export_bibliography(ctx, "bibtex", scope, ids, ascii_only, out)


@export_app.command("csl")
def export_csl(
    ctx: typer.Context,
    scope: _SCOPE = None,
    ids: _IDS = None,
    ascii_only: Annotated[
        bool, typer.Option("--ascii", help="Accepted for symmetry; CSL-JSON is always UTF-8.")
    ] = False,
    out: _OUT = None,
) -> None:
    """The bibliography as CSL-JSON."""
    _export_bibliography(ctx, "csl", scope, ids, ascii_only, out)


@export_app.command("prisma")
def export_prisma(ctx: typer.Context, out: _OUT = None) -> None:
    """The PRISMA 2020 flow diagram as SVG."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        svg = exports_service.export_prisma_svg(project)
        _emit([svg], out)


@report_app.command("search")
def report_search(ctx: typer.Context, as_json: _JSON = False) -> None:
    """The PRISMA-S search report: each registered query and what it retrieved."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = prisma_service.search_report(project)
    typer.echo(report.model_dump_json() if as_json else render.search_markdown(report), nl=as_json)


@report_app.command("methods")
def report_methods(ctx: typer.Context, as_json: _JSON = False) -> None:
    """The methods statement, generated from the events."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = methods_service.methods_report(project)
    typer.echo(
        report.model_dump_json() if as_json else methods_service.render_methods(report),
        nl=as_json,
    )


@report_app.command("discovery")
def report_discovery(ctx: typer.Context, as_json: _JSON = False) -> None:
    """How the corpus was found: by first-surfaced route and surfacer, and route overlaps."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = discovery_service.discovery_report(project)
    typer.echo(
        report.model_dump_json() if as_json else render.discovery_markdown(report), nl=as_json
    )


class EvidenceFormat(StrEnum):
    MD = "md"
    JSON = "json"
    CSV_ROWS = "csv-rows"
    CSV_POINTS = "csv-points"


def _parse_expect(text: str) -> dict[str, str]:
    """`key=value,key=value` as a partial key; anything else exits 2 with a message."""
    parsed: dict[str, str] = {}
    for part in text.split(","):
        key, sep, value = part.partition("=")
        if not sep or not key.strip() or not value.strip() or key.strip() in parsed:
            _fail(f"bad --expect {text!r}: want key=value,key=value", 2)
        parsed[key.strip()] = value.strip()
    return parsed


@report_app.command("evidence")
def report_evidence(
    ctx: typer.Context,
    expect: Annotated[
        list[str] | None,
        typer.Option(
            "--expect",
            help="Expected partial key, key=value,key=value (repeatable); no comma in a value.",
        ),
    ] = None,
    fmt: Annotated[
        EvidenceFormat, typer.Option("--format", help="Output format.")
    ] = EvidenceFormat.MD,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write to this file instead of printing.")
    ] = None,
) -> None:
    """The evidence report: grouped final rows, frontiers and limits (full view, audit shown)."""
    state = _state(ctx)
    expectations = [_parse_expect(e) for e in expect or []]
    with _reporting_errors():
        project = _resolve_project(state)
        report = evidence_report_service.evidence_report(project, expect=expectations)
    if fmt is EvidenceFormat.JSON:
        text = report.model_dump_json()
    elif fmt is EvidenceFormat.CSV_ROWS:
        text = evidence_render.rows_csv(report)
    elif fmt is EvidenceFormat.CSV_POINTS:
        text = evidence_render.points_csv(report)
    else:
        text = evidence_render.evidence_markdown(report, show_audit=True)
    if output is not None:
        try:
            output.write_text(text, encoding="utf-8")
        except OSError as exc:
            _fail(f"cannot write {output}: {exc.strerror or exc}", 1)
        return
    typer.echo(text, nl=not text.endswith("\n"))


@fulltext_app.command("import")
def fulltext_import_cmd(
    ctx: typer.Context,
    folder: Annotated[Path, typer.Argument(help="A folder of PDFs, matched to promoted works.")],
) -> None:
    """Import the researcher's PDFs from FOLDER by the identifiers they carry; prints every list."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = fulltext_import_service.import_folder(project, folder)
    for line in render.import_lines(report):
        typer.echo(line)


@fulltext_app.command("fetch")
def fulltext_fetch_cmd(
    ctx: typer.Context,
    work: Annotated[
        list[str] | None, typer.Option("--work", help="A promoted work; repeat for several.")
    ] = None,
    route: Annotated[
        list[str] | None,
        typer.Option("--route", help="Try only this route, all of them; repeat for several."),
    ] = None,
    refresh: Annotated[
        bool,
        typer.Option(
            "--refresh",
            help="Revisit every promoted work, even those with a document or attempt.",
        ),
    ] = False,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            help="At most this many works (1 to 200). More --work ids than this are refused.",
        ),
    ] = 20,
) -> None:
    """Fetch full text for promoted works, as the researcher.

    Without --work, selects promoted works with no document and no attempt yet; works whose
    routes all failed are retried with --refresh or by naming them with --work.
    """
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        only = parse_routes(route or None, "route")
        summary = fulltext_service.fetch_fulltext(
            project,
            routes=default_routes(state.settings),
            work_ids=work or None,
            only=only,
            refresh=refresh,
            limit=limit,
            actor=project.human_actor(),
        )
    for line in render.fetch_lines(summary):
        typer.echo(line)


@fulltext_app.command("status")
def fulltext_status_cmd(ctx: typer.Context) -> None:
    """Each promoted work's full-text state, with the reason from each route it missed."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        status = fulltext_status_service.fulltext_status(project)
    for line in render.fulltext_status_lines(status):
        typer.echo(line)


@fulltext_app.command("restore")
def fulltext_restore_cmd(
    ctx: typer.Context,
    document: Annotated[str | None, typer.Argument(help="The document to restore.")] = None,
    missing: Annotated[
        bool, typer.Option("--missing", help="Restore every document whose library entry is gone.")
    ] = False,
) -> None:
    """Restore a library entry from its recorded route, checking its hash.

    A researcher-supplied document is never fetched: it is listed, to be imported again. Exit 1
    when a route did not retrieve a document, naming it.
    """
    state = _state(ctx)
    if (document is None) == (not missing):
        _fail("give one document id, or --missing", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        routes = default_routes(state.settings)
        human = project.human_actor()
        supplied: list[str] = []
        targets = [document] if document is not None else []
        if missing:
            absent = fulltext_service.library_missing(project)
            if not absent:
                typer.echo("no library entry is missing")
                return
            supplied = [d for d, route in absent if route is Route.RESEARCHER]
            targets = [d for d, route in absent if route is not Route.RESEARCHER]
        results = [
            (d, fulltext_service.restore_document(project, d, routes=routes, actor=human))
            for d in targets
        ]
    for d in supplied:
        typer.echo(f"{d}  needs re-import (researcher-supplied)")
    for d, outcome in results:
        typer.echo(f"{d}  {outcome}")
    unavailable = [d for d, outcome in results if outcome == "unavailable"]
    if unavailable:
        _fail(f"unavailable: {' '.join(unavailable)}", 1)


@document_app.command("convert")
def document_convert_cmd(
    ctx: typer.Context,
    work: Annotated[
        list[str] | None,
        typer.Option("--work", help="A promoted work; repeat for several."),
    ] = None,
    document: Annotated[
        list[str] | None,
        typer.Option("--document", help="A live document; repeat for several."),
    ] = None,
    restore: Annotated[
        bool,
        typer.Option(
            "--restore",
            help="Regenerate missing or damaged stored conversions. Takes no --work or --document.",
        ),
    ] = False,
) -> None:
    """Convert the retrieved documents of promoted works, as the researcher.

    Without --work or --document, converts every live document of a promoted work. A failed
    document is recorded and the rest continue. --restore regenerates the stored Markdown of
    recorded conversions that are missing or damaged; it writes no event.
    """
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        summary = document_convert_service.convert_or_restore(
            project,
            default_converters(),
            restore=restore,
            work_ids=work,
            document_ids=document,
        )
    for line in render.convert_lines(summary):
        typer.echo(line)


@document_app.command("status")
def document_status_cmd(ctx: typer.Context) -> None:
    """Show each live document of a promoted work: converted or not, its converter and version,
    anchor counts, and its latest recorded failure."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        status = document_convert_service.document_status(project)
    for line in render.document_status_lines(status):
        typer.echo(line)


@document_app.command("read")
def document_read_cmd(
    ctx: typer.Context,
    work: Annotated[str, typer.Argument(help="A promoted work.")],
    document: Annotated[
        str | None, typer.Option("--document", help="Read this document's latest conversion.")
    ] = None,
    conversion: Annotated[
        str | None, typer.Option("--conversion", help="Read this conversion.")
    ] = None,
    anchor: Annotated[
        str | None, typer.Option("--anchor", help="Read only this anchor, cells included.")
    ] = None,
    after: Annotated[
        str | None, typer.Option("--after", help="Continue after this anchor (the next_after).")
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", help="At most this many segments (1 to 200)."),
    ] = document_read_service.DEFAULT_LIMIT,
) -> None:
    """Print a promoted work's converted text, one page of segments at a time."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        page = document_read_service.document_read(
            project,
            work_id=work,
            document_id=document,
            conversion_id=conversion,
            after=after,
            anchor=anchor,
            limit=limit,
        )
    for line in render.document_page_lines(page):
        typer.echo(line)


@app.command()
def trace(
    ctx: typer.Context,
    ref: Annotated[str, typer.Argument(help="Any identifier: decision, work, query, seed, Q@...")],
    forward: Annotated[
        bool, typer.Option("--forward", help="What was derived from REF, not what it came from.")
    ] = False,
) -> None:
    """The chain from REF as an indented tree, seeds included (the human view)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        tree = trace_service.trace(project, ref, direction="forward" if forward else "back")
    for line in render.trace_lines(tree):
        typer.echo(line)


def _watch_projects(state: CliState, project: str | None, all_projects: bool) -> list[str]:
    """The slugs a `watch` command covers: all, the named one, or the one the root resolves."""
    if all_projects and project is not None:
        _fail("--all and --project are exclusive", 2)
    if all_projects:
        return list_projects(state.settings)
    if project is not None:
        return [project]
    return [_resolve_project(state).paths.slug]


def _watch_one(
    state: CliState,
    slug: str,
    *,
    dry_run: bool,
    force: bool,
    human: bool,
    skip_unplanned: bool,
) -> tuple[int, dict[str, object], list[str]]:
    """Run, or preview, one project's cycle. Returns its exit code, JSON and text lines."""
    try:
        project = open_project(state.settings, slug, session=state.session, clock=state.clock)
        status = watch_service.watch_status(project)
        if not status.has_plan and skip_unplanned:
            return 0, {"project": slug, "result": "no watch_plan"}, [f"{slug}: no watch_plan"]
        if dry_run:
            due = [s.source for s in status.sources if force or s.due]
            lines = [f"{slug}: would run {', '.join(due) or 'nothing'}"]
            lines += render.watch_status_lines(slug, status)[1:]
            return 0, {"project": slug, "result": "dry-run", "sources": due}, lines
        summary = watch_service.watch_run(
            project,
            sources=dict(default_sources()),
            trigger="human" if human else "scheduler",
            actor=project.human_actor() if human else None,
            force=force,
            after_runs=DEFAULT_HOOKS,
        )
    except FactoryValidationError as exc:
        lines = [f"{slug}: {issue.field}: {issue.reason}" for issue in exc.issues]
        issues = [{"field": i.field, "reason": i.reason} for i in exc.issues]
        return 2, {"project": slug, "result": "invalid", "issues": issues}, lines
    except ProjectNotFoundError as exc:
        return 2, {"project": slug, "result": "invalid", "issues": [str(exc)]}, [str(exc)]
    except Exception as exc:  # one project's failure must not stop the others
        message = f"{slug}: {type(exc).__name__}: {exc}"
        return 1, {"project": slug, "result": "error", "error": message}, [message]
    if summary is None:
        return 0, {"project": slug, "result": "nothing-due"}, render.cycle_lines(slug, None)
    code = 0 if summary.status is CycleStatus.COMPLETE else 1
    data = {"project": slug, "result": summary.status.value, **summary.model_dump(mode="json")}
    return code, data, render.cycle_lines(slug, summary)


@watch_app.command("run")
def watch_run_cmd(
    ctx: typer.Context,
    project: Annotated[str | None, typer.Option("--project", help="Project slug.")] = None,
    all_projects: Annotated[
        bool, typer.Option("--all", help="Every project; those without a watch_plan are skipped.")
    ] = False,
    due: Annotated[
        bool, typer.Option("--due/--force", help="Run what is due (default), or every source.")
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would run; write nothing.")
    ] = False,
    human: Annotated[
        bool, typer.Option("--human", help="Record the cycle as a human's, not the scheduler's.")
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print one JSON object per project.")
    ] = False,
) -> None:
    """Run the due watch cycle; exit 0 nothing due or complete, 1 partial or failed, 2 invalid."""
    state = _state(ctx)
    slugs = _watch_projects(state, project if project is not None else state.project, all_projects)
    exit_code = 0
    for slug in slugs:
        code, data, lines = _watch_one(
            state, slug, dry_run=dry_run, force=not due, human=human, skip_unplanned=all_projects
        )
        exit_code = max(exit_code, code)
        if as_json:
            typer.echo(json.dumps(data, sort_keys=True))
        else:
            for line in lines:
                typer.echo(line, err=code == 2)
    raise typer.Exit(exit_code)


def _watch_target(state: CliState, project: str | None) -> Project:
    if project is None:
        return _resolve_project(state)
    return open_project(state.settings, project, session=state.session, clock=state.clock)


@living_app.command("snapshot")
def living_snapshot_cmd(ctx: typer.Context) -> None:
    """Take a snapshot of the review: the computed PRISMA flow and included works now."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        recorded = snapshot_service.snapshot(project, project.human_actor(), trigger="human")
    typer.echo(f"snapshot {recorded.snapshot_id} at {recorded.cutoff_event}")


@watch_app.command("status")
def watch_status_cmd(
    ctx: typer.Context,
    project: Annotated[str | None, typer.Option("--project", help="Project slug.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print WatchStatus as JSON.")] = False,
) -> None:
    """Per source: last cycle, next due, mode, window start and failures."""
    state = _state(ctx)
    with _reporting_errors():
        opened = _watch_target(state, project)
        status = watch_service.watch_status(opened)
    if as_json:
        typer.echo(status.model_dump_json())
        return
    for line in render.watch_status_lines(opened.paths.slug, status):
        typer.echo(line)


@watch_app.command("plan")
def watch_plan_cmd(
    ctx: typer.Context,
    project: Annotated[str | None, typer.Option("--project", help="Project slug.")] = None,
) -> None:
    """Print the current protocol's watch_plan as JSON."""
    state = _state(ctx)
    with _reporting_errors():
        current = protocol_service.current_protocol(_watch_target(state, project))
    plan = None if current is None else current.spec.watch_plan
    if plan is None:
        _fail("no watch_plan in the current protocol", 1)
    typer.echo(plan.model_dump_json(indent=2))


@app.command()
def check(
    ctx: typer.Context,
    promote_to: Annotated[
        str | None, typer.Option("--promote-to", help="Evaluate as this rigour mode.")
    ] = None,
) -> None:
    """List the project's gaps, with ids; exit 1 when any is an error (the human view)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = check_service.check(project, promote_to=_mode(promote_to))
    for line in render.check_lines(report):
        typer.echo(line)
    if not report.ok:
        raise typer.Exit(1)


def _mode(value: str | None) -> RigorMode | None:
    if value is None:
        return None
    try:
        return RigorMode(value)
    except ValueError:
        choices = ", ".join(mode.value for mode in RigorMode)
        raise FactoryValidationError(
            [ValidationIssue("promote-to", f"must be one of: {choices}")]
        ) from None


class PartChoice(StrEnum):
    """Which records `factory import show` lists."""

    DEVELOPMENT = "development"
    HELD_OUT = "held-out"
    ALL = "all"


RoleOption = Annotated[
    ImportRole,
    typer.Option("--role", help="reference (kept outside the corpus) or corpus (candidates)."),
]
CollectionOption = Annotated[
    str | None, typer.Option("--collection", help="The collection this file exports.")
]
SeedOption = Annotated[
    int | None, typer.Option("--seed", help="Random seed of the development/held-out split.")
]
NoSplitOption = Annotated[
    bool, typer.Option("--no-split", help="Decline the split of a pre-search import.")
]


def _library_import(
    ctx: typer.Context,
    path: Path,
    format: ImportFormat,
    role: ImportRole,
    collection: str | None,
    seed: int | None,
    no_split: bool,
) -> None:
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        summary = imports_service.record_import(
            project,
            path,
            format=format,
            role=role,
            collection=collection,
            random_seed=seed,
            split=not no_split,
        )
    for line in render.library_import_lines(summary):
        typer.echo(line)


@import_app.command("bib")
def import_bib_cmd(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="A BibTeX export.")],
    role: RoleOption,
    collection: CollectionOption = None,
    seed: SeedOption = None,
    no_split: NoSplitOption = False,
) -> None:
    """Archive and record a BibTeX export; prints the import id, counts and split."""
    _library_import(ctx, path, ImportFormat.BIBTEX, role, collection, seed, no_split)


@import_app.command("csl")
def import_csl_cmd(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="A CSL JSON export.")],
    role: RoleOption,
    collection: CollectionOption = None,
    seed: SeedOption = None,
    no_split: NoSplitOption = False,
) -> None:
    """Archive and record a CSL JSON export; prints the import id, counts and split."""
    _library_import(ctx, path, ImportFormat.CSL, role, collection, seed, no_split)


@import_app.command("pdfs")
def import_pdfs_cmd(
    ctx: typer.Context,
    folder: Annotated[Path, typer.Argument(help="A folder of PDFs.")],
    role: RoleOption,
    collection: CollectionOption = None,
    seed: SeedOption = None,
    no_split: NoSplitOption = False,
) -> None:
    """Archive and record a folder of PDFs; prints the import id, counts and split."""
    _library_import(ctx, folder, ImportFormat.PDFS, role, collection, seed, no_split)


@import_app.command("list")
def import_list_cmd(ctx: typer.Context) -> None:
    """Every import, oldest first, with its counts."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        listings = imports_service.list_imports(project)
    for line in render.library_imports_lines(listings):
        typer.echo(line)


@import_app.command("show")
def import_show_cmd(
    ctx: typer.Context,
    import_id: Annotated[str, typer.Argument(help="An import id (imp_...).")],
    part: Annotated[
        PartChoice,
        typer.Option("--part", help="development (default), or held-out/all with --researcher."),
    ] = PartChoice.DEVELOPMENT,
    researcher: Annotated[
        bool,
        typer.Option("--researcher", help="Confirm a researcher's view; needed for held-out/all."),
    ] = False,
) -> None:
    """The records of an import. By default: records that are not held out, by hash, with no
    ordinals, and the held-out count. `--researcher` lists ordinals and parts."""
    state = _state(ctx)
    if part is not PartChoice.DEVELOPMENT:
        if not researcher:
            _fail(f"--part {part.value} lists held-out records; pass --researcher", 1)
        typer.echo(
            "warning: researcher view with held-out records; this output must not be shown to "
            "agents",
            err=True,
        )
    with _reporting_errors():
        project = _resolve_project(state)
        if researcher:
            records = imports_service.list_import_records(project, import_id, view=part.value)
            lines = render.import_record_lines(records)
        else:
            view = imports_service.development_view(project, import_id)
            lines = render.development_view_lines(view)
    for line in lines:
        typer.echo(line)


@import_app.command("resolve")
def import_resolve_cmd(
    ctx: typer.Context,
    import_id: Annotated[str, typer.Argument(help="An import id (imp_...).")],
) -> None:
    """Resolve the import's records to works (probe lookups, outside the corpus); prints counts
    by state. Fuzzy and ambiguous matches wait for `import confirm` or `import reject`."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        summary = import_resolve_service.resolve_import(
            project, import_id, sources=dict(default_sources())
        )
    for line in render.import_resolve_lines(summary):
        typer.echo(line)


RationaleOption = Annotated[str, typer.Option("--rationale", help="Why (required).")]


def _decide_import(
    ctx: typer.Context,
    import_id: str,
    ordinal: int,
    decision: Decision,
    rationale: str,
    work: str | None,
) -> None:
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        import_resolve_service.decide_import(
            project,
            project.human_actor(),
            import_id,
            ordinal,
            decision,
            rationale=rationale,
            work_id=work,
        )
        live = import_resolve_service.record_states(project, import_id).get(ordinal)
    for line in render.import_decision_lines(import_id, decision, live):
        typer.echo(line)


@import_app.command("confirm")
def import_confirm_cmd(
    ctx: typer.Context,
    import_id: Annotated[str, typer.Argument(help="An import id (imp_...).")],
    ordinal: Annotated[
        int, typer.Argument(help="The record's ordinal (`import show --researcher`).")
    ],
    rationale: RationaleOption,
    work: Annotated[
        str | None, typer.Option("--work", help="The candidate work (needed for ambiguous).")
    ] = None,
) -> None:
    """Confirm a fuzzy or ambiguous match, or a PDF's identity, as the researcher."""
    _decide_import(ctx, import_id, ordinal, Decision.CONFIRM, rationale, work)


@import_app.command("reject")
def import_reject_cmd(
    ctx: typer.Context,
    import_id: Annotated[str, typer.Argument(help="An import id (imp_...).")],
    ordinal: Annotated[
        int, typer.Argument(help="The record's ordinal (`import show --researcher`).")
    ],
    rationale: RationaleOption,
) -> None:
    """Reject a match as the researcher; the record is then unresolved."""
    _decide_import(ctx, import_id, ordinal, Decision.REJECT, rationale, None)


@import_app.command("admit")
def import_admit_cmd(
    ctx: typer.Context,
    import_id: Annotated[str, typer.Argument(help="An import id (imp_...).")],
) -> None:
    """Admit a corpus import's resolved records as pending candidates through recorded searches;
    prints counts and any promotion gap."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        summary = import_admit_service.admit_import(
            project, import_id, sources=dict(default_sources())
        )
    for line in render.import_admit_lines(summary):
        typer.echo(line)


@import_app.command("attach")
def import_attach_cmd(
    ctx: typer.Context,
    import_id: Annotated[str, typer.Argument(help="An import id (imp_...).")],
    researcher: Annotated[
        bool,
        typer.Option("--researcher", help="List ordinals, works and documents (not for agents)."),
    ] = False,
) -> None:
    """Attach the files the export names to their records' promoted works; prints counts."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = import_attach_service.attach_import(project, import_id)
    if researcher:
        typer.echo(
            "warning: researcher view with ordinals; this output must not be shown to agents",
            err=True,
        )
    for line in render.import_attach_lines(report, researcher=researcher):
        typer.echo(line)

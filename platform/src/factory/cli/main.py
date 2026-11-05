"""The `factory` command: parse arguments, call a service, format output. No business logic here."""

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, NoReturn, TypeVar, cast

import typer
from pydantic import BaseModel, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from factory.cli import evidence_render, portfolio_render, render
from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.document.registry import default_converters
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.imports.model import ImportFormat, ImportRole
from factory.lineage.graph import GraphFilter
from factory.living.digest_render import to_json as digest_json
from factory.living.digest_render import to_markdown as digest_markdown
from factory.mcp.conventions import parse_routes
from factory.mcp.server import run
from factory.model import lineage as lineage_model
from factory.model.chase import ChaseDirection
from factory.model.conclusions import BasisRef, Predicate
from factory.model.fulltext import Route
from factory.model.hypotheses import AbandonReason, DiscardReason
from factory.model.identity import IdGenerator
from factory.model.intuition import (
    ConceptInput,
    ConceptSourceInput,
    InterpretationInput,
    LinkStatus,
    ReviewState,
    SourceInput,
)
from factory.model.notices import AssessmentDecision
from factory.model.project import RigorMode
from factory.model.protocol import ScreeningStage
from factory.model.references import Decision, Direction, LinkState
from factory.model.regions import Facet, RegionKind
from factory.model.screening import Channel
from factory.model.watch import CycleStatus
from factory.model.work import ProvenanceMethod
from factory.regions.rules import MemberType, RuleSet
from factory.services import agreement as agreement_service
from factory.services import audit as audit_service
from factory.services import calibration as calibration_service
from factory.services import cards as cards_service
from factory.services import chase as chase_service
from factory.services import check as check_service
from factory.services import concepts as concepts_service
from factory.services import conclusions as conclusions_service
from factory.services import contributions as contributions_service
from factory.services import coverage as coverage_service
from factory.services import digest as digest_service
from factory.services import discovery as discovery_service
from factory.services import document_convert as document_convert_service
from factory.services import document_read as document_read_service
from factory.services import evidence as evidence_service
from factory.services import evidence_report as evidence_report_service
from factory.services import exports as exports_service
from factory.services import extraction as extraction_service
from factory.services import extraction_agreement as extraction_agreement_service
from factory.services import extraction_audit as extraction_audit_service
from factory.services import finders as findings_service
from factory.services import fulltext as fulltext_service
from factory.services import fulltext_import as fulltext_import_service
from factory.services import fulltext_status as fulltext_status_service
from factory.services import gates as gates_service
from factory.services import hypotheses as hypotheses_service
from factory.services import ideas as ideas_service
from factory.services import import_admit as import_admit_service
from factory.services import import_attach as import_attach_service
from factory.services import import_resolve as import_resolve_service
from factory.services import imports as imports_service
from factory.services import inbox as inbox_service
from factory.services import inbox_watch as inbox_watch_service
from factory.services import interpretations as interpretations_service
from factory.services import leads as leads_service
from factory.services import lineage as graph_service
from factory.services import matching as matching_service
from factory.services import methods as methods_service
from factory.services import mining as mining_service
from factory.services import notices as notices_service
from factory.services import portfolio as portfolio_service
from factory.services import prisma as prisma_service
from factory.services import prisma_update as prisma_update_service
from factory.services import project as project_service
from factory.services import properties as properties_service
from factory.services import protocol as protocol_service
from factory.services import reference_resolve as reference_resolve_service
from factory.services import references as references_service
from factory.services import regions as regions_service
from factory.services import relations as relations_service
from factory.services import seeds as seeds_service
from factory.services import snapshots as snapshot_service
from factory.services import snowball as snowball_service
from factory.services import trace as trace_service
from factory.services import versions as versions_service
from factory.services import watch as watch_service
from factory.services.context import Project, list_projects, open_project
from factory.services.extraction_agreement import Choice
from factory.services.gate_status import gates_status
from factory.services.living_hooks import DEFAULT_HOOKS
from factory.services.modules.listing import module_rows
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
gate_app = typer.Typer(name="gate", help="Audit the agent's acts at a gate.", no_args_is_help=True)
gate_audit_app = typer.Typer(
    name="audit", help="Sample, label and report a gate audit.", no_args_is_help=True
)
gate_app.add_typer(gate_audit_app)
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
miner_app = typer.Typer(
    name="miner",
    help="Registered miners: register a specification, list the registered versions.",
    no_args_is_help=True,
)
mine_app = typer.Typer(
    name="mine",
    help="Mining with registered miners: unit status.",
    no_args_is_help=True,
)
contributions_app = typer.Typer(
    name="contributions",
    help="Contribution items: status, list, agreement, resolution and the audit.",
    no_args_is_help=True,
)
contributions_audit_app = typer.Typer(
    name="audit", help="Sample, label and report the contribution audit.", no_args_is_help=True
)
contributions_app.add_typer(contributions_audit_app)
relations_app = typer.Typer(
    name="relations",
    help="Lineage relations: list them, confirm or reject an inferred one (human only).",
    no_args_is_help=True,
)
ideas_app = typer.Typer(
    name="ideas",
    help="Ideas: define, list, confirm, reject, merge and unmerge (human only).",
    no_args_is_help=True,
)
vocabulary_app = typer.Typer(
    name="vocabulary",
    help="The property vocabulary: list, approve, reject, merge and unmerge (human only).",
    no_args_is_help=True,
)
cards_app = typer.Typer(
    name="cards",
    help="Method cards and problem descriptions: list, show, assert, confirm and reject.",
    no_args_is_help=True,
)
finders_app = typer.Typer(
    name="finders",
    help="Computed candidates: numeric conflicts and gaps. Not conclusions.",
    no_args_is_help=True,
)
contradictions_app = typer.Typer(
    name="contradictions",
    help="Claim contradictions: list, confirm and reject (human only).",
    no_args_is_help=True,
)
leads_app = typer.Typer(
    name="leads",
    help="Research-idea leads: list, promote, park and discard (human).",
    no_args_is_help=True,
)
hypotheses_app = typer.Typer(
    name="hypotheses",
    help="Hypotheses: list, show, register, abandon and conclude (human).",
    no_args_is_help=True,
)
models_app = typer.Typer(
    name="models",
    help="Model facts the platform cannot know: training cut-offs (human).",
    no_args_is_help=True,
)
interpretations_app = typer.Typer(
    name="interpretations",
    help="Interpretations of the intuition layer: list, show, review, supersede and write (human).",
    no_args_is_help=True,
)
concepts_app = typer.Typer(
    name="concepts",
    help="Background concepts: define, approve a source, review, merge and unmerge (human).",
    no_args_is_help=True,
)
concept_links_app = typer.Typer(
    name="concept-links",
    help="`uses` links from papers, ideas and concepts to concepts: list, confirm, reject.",
    no_args_is_help=True,
)
regions_app = typer.Typer(
    name="regions",
    help="Regions and foci: typed rules, pinned versions R@, drift and human review.",
    no_args_is_help=True,
)
graph_app = typer.Typer(
    name="graph",
    help="The lineage graph: build, status, bounded queries and JSON or DOT export.",
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
notices_app = typer.Typer(
    name="notices",
    help="Notices of retraction, correction or concern about the works the review depends on.",
    no_args_is_help=True,
)
versions_app = typer.Typer(
    name="versions",
    help="Newer versions, published-version links and the preferred document of a work.",
    no_args_is_help=True,
)
living_app = typer.Typer(
    name="living",
    help="Living review: snapshots and the PRISMA update flow.",
    no_args_is_help=True,
)
conclusions_app = typer.Typer(
    name="conclusions",
    help="Registered conclusions: register, retire, their computed state and diffs.",
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
app.add_typer(conclusions_app)
app.add_typer(notices_app)
app.add_typer(versions_app)
app.add_typer(inbox_app)
app.add_typer(report_app)
app.add_typer(export_app)
app.add_typer(protocol_app)
app.add_typer(calibrate_app)
app.add_typer(screen_app)
app.add_typer(audit_app)
app.add_typer(gate_app)
app.add_typer(search_app)
app.add_typer(fulltext_app)
app.add_typer(document_app)
app.add_typer(extract_app)
app.add_typer(miner_app)
app.add_typer(mine_app)
app.add_typer(contributions_app)
app.add_typer(relations_app)
app.add_typer(ideas_app)
app.add_typer(vocabulary_app)
app.add_typer(cards_app)
app.add_typer(finders_app)
app.add_typer(contradictions_app)
app.add_typer(leads_app)
app.add_typer(hypotheses_app)
app.add_typer(models_app)
app.add_typer(graph_app)
app.add_typer(interpretations_app)
app.add_typer(concepts_app)
app.add_typer(concept_links_app)
app.add_typer(regions_app)
app.add_typer(import_app)


_M = TypeVar("_M", bound=BaseModel)


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


@app.command("modules")
def modules_cmd(
    as_json: Annotated[bool, typer.Option("--json", help="Print the module rows as JSON.")] = False,
) -> None:
    """The declared stage modules: kind, event types, task kinds, protocol sections, gates with
    their floor, checks and strategies. Reads declarations only; no project is opened."""
    rows = module_rows()
    if as_json:
        typer.echo(json.dumps([row.model_dump(mode="json") for row in rows]))
    else:
        for line in render.module_lines(rows):
            typer.echo(line)


@app.command("gates")
def gates_cmd(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Print the gate rows as JSON.")] = False,
) -> None:
    """Every decision gate: its policy and source, acts per autonomy level, audit, and acts below
    the current policy. Read-only."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        rows = gates_status(project)
    if as_json:
        typer.echo(json.dumps([row.model_dump(mode="json") for row in rows]))
    else:
        for line in render.gate_lines(rows):
            typer.echo(line)


@gate_audit_app.command("sample")
def gate_audit_sample_cmd(
    ctx: typer.Context,
    gate: Annotated[str, typer.Argument(help="An agent_audit gate, e.g. reference.link_confirm.")],
    seed: Annotated[int | None, typer.Option("--seed", help="Random seed; default: fresh.")] = None,
) -> None:
    """Draw the human audit sample of the agent acts at a gate."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        drawn = gates_service.gate_audit_sample(
            project, project.human_actor(), gate, random_seed=seed
        )
    typer.echo(
        f"gate audit {drawn.audit_id}: {len(drawn.act_event_ids)} of {drawn.population} agent acts"
    )
    for act in drawn.act_event_ids:
        typer.echo(act)


@gate_audit_app.command("label")
def gate_audit_label_cmd(
    ctx: typer.Context,
    audit_id: Annotated[str, typer.Argument(help="The gate audit being labelled.")],
    act: Annotated[str, typer.Argument(help="An act event of the audit sample.")],
    verdict: Annotated[str, typer.Argument(help="correct or incorrect.")],
    note: Annotated[str | None, typer.Option("--note", help="Why, if incorrect.")] = None,
) -> None:
    """A human's label on one sampled agent act."""
    if verdict not in ("correct", "incorrect"):
        _fail("verdict: must be correct or incorrect", 2)
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        gates_service.gate_audit_record(
            project, project.human_actor(), audit_id, act, verdict == "correct", note, Channel.CLI
        )
    typer.echo(f"labelled {act} in {audit_id} ({verdict})")


@gate_audit_app.command("report")
def gate_audit_report_cmd(
    ctx: typer.Context,
    gate: Annotated[str, typer.Argument(help="The gate.")],
) -> None:
    """The latest audit of a gate: labelled count, error rate and the ceiling."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = gates_service.gate_audit_report(project, gate)
    if report is None:
        typer.echo("no gate audit sampled")
        return
    verdict = report.verdict
    rate = "n/a" if verdict.rate is None else f"{verdict.rate:.3f}"
    typer.echo(
        f"gate audit {report.audit_id}: sample {report.sample_size}, labelled {report.labelled}, "
        f"incorrect {report.incorrect}"
    )
    typer.echo(
        f"error rate {rate} (ceiling {verdict.ceiling:.2f}, above ceiling: "
        f"{'yes' if verdict.above else 'no'}, enforced: {'yes' if verdict.enforced else 'no'})"
    )


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
    watch: Annotated[
        bool, typer.Option("--watch", help="List pending works by discovery route instead.")
    ] = False,
    after: Annotated[
        str | None, typer.Option("--after", help="With --watch: the last work id of the page.")
    ] = None,
) -> None:
    """Inbox items with their status and last resolution outcome."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        if watch:
            for entry in inbox_watch_service.inbox_entries(project, after=after):
                typer.echo(
                    f"{entry.work_id}  {entry.route}  {entry.route_ref}  {entry.surfaced_at}"
                )
            return
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
    clear: Annotated[
        bool, typer.Option("--clear", help="Withdraw the human decision on the entry.")
    ] = False,
    rationale: Annotated[str, typer.Option("--rationale", help="Why.")] = "",
    entry_quote: Annotated[
        str, typer.Option("--entry-quote", help="Verbatim from the entry.")
    ] = "",
    candidate_quote: Annotated[
        str, typer.Option("--candidate-quote", help="Verbatim from the candidate's title/authors.")
    ] = "",
    work: Annotated[str | None, typer.Option("--work", help="The candidate work.")] = None,
) -> None:
    """The human's binding decision on an unconfirmed or ambiguous link, or its withdrawal."""
    state = _state(ctx)
    if confirm + reject + clear != 1:
        _fail("give exactly one of --confirm, --reject and --clear", 2)
    decision = Decision.CONFIRM if confirm else Decision.REJECT if reject else Decision.CLEAR
    with _reporting_errors():
        project = _resolve_project(state)
        reference_resolve_service.decide_reference(
            project,
            project.human_actor(),
            extraction,
            ordinal,
            decision,
            rationale=rationale,
            quotes=(entry_quote, candidate_quote),
            work_id=work,
        )
    done = {Decision.CONFIRM: "confirmed", Decision.REJECT: "rejected", Decision.CLEAR: "cleared"}
    typer.echo(f"{done[decision]} {extraction}:{ordinal}")


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


@miner_app.command("register")
def miner_register_cmd(
    ctx: typer.Context,
    spec: Annotated[Path, typer.Argument(help="A miner specification (a JSON file).")],
) -> None:
    """Register a miner version from a specification file (the researcher's act)."""
    state = _state(ctx)
    try:
        body = json.loads(spec.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"{spec}: cannot read a JSON specification ({exc})", 1)
    with _reporting_errors():
        project = _resolve_project(state)
        registered = mining_service.register_miner(project, project.human_actor(), body)
    typer.echo(f"registered {registered.name} version {registered.version} ({registered.digest})")


@miner_app.command("list")
def miner_list_cmd(ctx: typer.Context) -> None:
    """The registered miners and whether the protocol lists them."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        listing = mining_service.miner_listing(project)
    for line in render.miner_listing_lines(listing):
        typer.echo(line)


@mine_app.command("status")
def mine_status_cmd(ctx: typer.Context) -> None:
    """Units, rows and agreement of each miner the protocol lists."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        status = mining_service.mine_status(project)
    for line in render.mine_status_lines(status):
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


# --- Contributions (slice 3b, G2-B): the plan-D commands with the contribution scope ---


@contributions_app.command("status")
def contributions_status_cmd(ctx: typer.Context) -> None:
    """Contribution units, items by kind, `not-stated` and marker counts, and the works with no
    current reference extraction. Every figure is computed from the log."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        status = contributions_service.contribution_status(project)
    for line in render.contribution_status_lines(status):
        typer.echo(line)


@contributions_app.command("list")
def contributions_list_cmd(
    ctx: typer.Context,
    work: Annotated[str | None, typer.Option("--work", help="Only this work.")] = None,
    kind: Annotated[
        str | None, typer.Option("--kind", help="Only this item kind, e.g. base-idea.")
    ] = None,
    include_stale: Annotated[
        bool, typer.Option("--include-stale", help="Also list stale items.")
    ] = False,
) -> None:
    """The live contribution items of both passes, with their quotes and cited entries."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        items = contributions_service.live_items(
            project, work_id=work, kind=kind, include_stale=include_stale
        )
    for line in render.contribution_item_lines(items):
        typer.echo(line)


@contributions_app.command("agreement")
def contributions_agreement_cmd(ctx: typer.Context) -> None:
    """The agreement of the two contribution passes and the unresolved disagreements."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        agreement = contributions_service.contribution_agreement(project, project.human_actor())
    for line in render.agreement_lines(agreement):
        typer.echo(line)


@contributions_app.command("resolve")
def contributions_resolve_cmd(
    ctx: typer.Context,
    work: Annotated[str, typer.Argument(help="A work with a disagreement.")],
    row_key: Annotated[str, typer.Argument(help="The disputed row.")],
    choice: Annotated[ExtractChoice, typer.Option("--choice", help="a, b or neither.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the human decided.")],
    field: Annotated[
        str | None, typer.Option("--field", help="One field; the whole row when omitted.")
    ] = None,
) -> None:
    """The human's choice between the passes on one contribution disagreement."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        contributions_service.resolve_contribution(
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


@contributions_audit_app.command("sample")
def contributions_audit_sample_cmd(ctx: typer.Context) -> None:
    """Draw the contribution audit sample; each value with its quote and the cited element."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        human = project.human_actor()
        drawn = contributions_service.contribution_audit_sample(project, human)
        evidence = extraction_audit_service.audit_evidence(
            project, human, drawn.audit_id, Channel.CLI
        )
    typer.echo(f"audit {drawn.audit_id}: {len(drawn.items)} of {drawn.population} agreed values")
    for item in evidence:
        for line in render.audit_evidence_lines(item):
            typer.echo(line)


@contributions_audit_app.command("label")
def contributions_audit_label_cmd(
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
    """A human's label on one sampled contribution value."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        contributions_service.contribution_audit_record(
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


@contributions_audit_app.command("report")
def contributions_audit_report_cmd(ctx: typer.Context) -> None:
    """The latest contribution audit's counts and error rate."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = contributions_service.contribution_audit_report(project)
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
    update: Annotated[
        str | None,
        typer.Option("--update", help="The update flow: `last`, or the snapshot it closed at."),
    ] = None,
) -> None:
    """The PRISMA 2020 flow, computed from the events."""
    state = _state(ctx)
    if as_json and fmt is PrismaFormat.SVG:
        _fail("--json and --format svg are exclusive", 2)
    if update is not None and fmt is PrismaFormat.SVG:
        _fail("--update and --format svg are exclusive", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        if update is not None:
            shown = prisma_update_service.prisma_update(
                project, until=None if update == "last" else update
            )
            typer.echo(
                shown.model_dump_json() if as_json else render.update_markdown(shown), nl=as_json
            )
            return
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
    include_notice_affected: Annotated[
        bool,
        typer.Option(
            "--include-notice-affected",
            help="Keep the rows of works a notice excludes, labelled (researcher view only).",
        ),
    ] = False,
) -> None:
    """The evidence report: grouped final rows, frontiers and limits (full view, audit shown)."""
    state = _state(ctx)
    expectations = [_parse_expect(e) for e in expect or []]
    with _reporting_errors():
        project = _resolve_project(state)
        report = evidence_report_service.evidence_report(
            project, expect=expectations, include_notice_affected=include_notice_affected
        )
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
    with_interpretation: Annotated[
        bool,
        typer.Option(
            "--with-interpretation",
            help="Also show the interpretation items an anchor, work or idea carries.",
        ),
    ] = False,
) -> None:
    """The chain from REF as an indented tree, seeds included (the human view)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        tree = trace_service.trace(
            project,
            ref,
            direction="forward" if forward else "back",
            layer="all" if with_interpretation else "evidence",
        )
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


@notices_app.command("list")
def notices_list_cmd(ctx: typer.Context) -> None:
    """Every observed notice with its source, date and latest assessment (the human view)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        assessed = notices_service.current_assessments(project)
        states = notices_service.work_states(project)
        for notice in notices_service.observed_notices(project):
            current = assessed.get(notice.notice_id)
            verdict = "unassessed" if current is None else current[1].decision.value
            when = (
                "date not stated by source"
                if notice.notice_date is None
                else notice.notice_date.isoformat()
            )
            typer.echo(
                f"{notice.notice_id}  {notice.work_id}  {notice.kind.value}  {when}  "
                f"{notice.source}  {verdict}  {states[notice.work_id].flag}"
            )


@notices_app.command("assess")
def notices_assess_cmd(
    ctx: typer.Context,
    notice_id: Annotated[str, typer.Argument(help="The notice (ntc_...).")],
    decision: Annotated[
        str, typer.Option("--decision", help="exclude, keep-flagged, no-effect or affects.")
    ],
    rationale: Annotated[str, typer.Option("--rationale", help="Why.")],
    field: Annotated[
        list[str] | None,
        typer.Option("--field", help="With affects: a field the correction changes (repeatable)."),
    ] = None,
) -> None:
    """Record your assessment of a notice; a later assessment supersedes it."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        try:
            chosen = AssessmentDecision(decision)
        except ValueError:
            choices = ", ".join(d.value for d in AssessmentDecision)
            raise FactoryValidationError(
                [ValidationIssue("decision", f"must be one of {choices}")]
            ) from None
        event_id = notices_service.assess_notice(
            project,
            project.human_actor(),
            notice_id,
            chosen,
            fields=tuple(field or ()),
            rationale=rationale,
        )
    typer.echo(f"assessed {notice_id}  {event_id}")


@versions_app.command("list")
def versions_list_cmd(ctx: typer.Context) -> None:
    """Newer versions on a route, published-version links, refused links and preferences."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        for version in versions_service.newer_versions(project):
            typer.echo(f"newer  {version.work_id}  {version.route.value}  {version.source_version}")
        for work_id in versions_service.vor_available(project):
            typer.echo(
                f"published-version  {work_id}  {versions_service.aliases(project, work_id)}"
            )
        for conflict in versions_service.link_conflicts(project):
            held = conflict.other_work_id
            typer.echo(f"link-conflict  {conflict.work_id}  {conflict.doi}  held by {held}")
        for work_id, (document_id, why) in versions_service.preferences(project).items():
            typer.echo(f"preferred  {work_id}  {document_id}  {why}")


@versions_app.command("prefer")
def versions_prefer_cmd(
    ctx: typer.Context,
    work_id: Annotated[str, typer.Argument(help="The work.")],
    document_id: Annotated[str, typer.Argument(help="A live document of the work.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why.")],
) -> None:
    """Make a document the one `default_conversion` serves for the work (human act)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        event_id = versions_service.prefer_document(
            project, project.human_actor(), work_id, document_id, rationale
        )
    typer.echo(f"preferred {document_id} for {work_id}  {event_id}")


@living_app.command("snapshot")
def living_snapshot_cmd(ctx: typer.Context) -> None:
    """Take a snapshot of the review: the computed PRISMA flow and included works now."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        recorded = snapshot_service.snapshot(project, project.human_actor(), trigger="human")
    typer.echo(f"snapshot {recorded.snapshot_id} at {recorded.cutoff_event}")


@living_app.command("prisma-update")
def living_prisma_update_cmd(
    ctx: typer.Context,
    since: Annotated[
        str | None, typer.Option("--since", help="Snapshot id the update opens at.")
    ] = None,
    until: Annotated[str | None, typer.Option("--until", help="Snapshot id it closes at.")] = None,
    as_json: _JSON = False,
) -> None:
    """The PRISMA update flow between two snapshots (default: the last snapshot to now)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        flow = prisma_update_service.prisma_update(project, since=since, until=until)
    typer.echo(flow.model_dump_json() if as_json else render.update_markdown(flow), nl=as_json)


def _basis_refs(items: list[str]) -> list[BasisRef]:
    """`KIND:REF` options as basis references; a malformed one is exit 2."""
    refs: list[BasisRef] = []
    for item in items:
        kind, _, ref = item.partition(":")
        try:
            refs.append(BasisRef.model_validate({"kind": kind, "ref": ref}))
        except ValueError as exc:
            _fail(f"basis: {item}: {_first_line(exc)}", 2)
    return refs


def _first_line(exc: Exception) -> str:
    return str(exc).splitlines()[-1] if str(exc) else type(exc).__name__


@conclusions_app.command("register")
def conclusions_register_cmd(
    ctx: typer.Context,
    statement: Annotated[str, typer.Option("--statement", help="The conclusion, in your words.")],
    basis: Annotated[
        list[str],
        typer.Option("--basis", help="KIND:REF (cell, row, group, work or relation); repeatable."),
    ],
    predicate: Annotated[
        str | None, typer.Option("--predicate", help="A fact predicate as JSON.")
    ] = None,
) -> None:
    """Register a conclusion with its basis (human act); every basis reference must resolve."""
    state = _state(ctx)
    refs = _basis_refs(basis)
    parsed: Predicate | None = None
    if predicate is not None:
        try:
            parsed = Predicate.model_validate_json(predicate)
        except ValueError as exc:
            _fail(f"predicate: {_first_line(exc)}", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        conclusion_id = conclusions_service.register_conclusion(
            project, project.human_actor(), statement, refs, parsed
        )
    typer.echo(f"registered {conclusion_id}")


@conclusions_app.command("retire")
def conclusions_retire_cmd(
    ctx: typer.Context,
    conclusion_id: Annotated[str, typer.Argument(help="The conclusion.")],
    reason: Annotated[str, typer.Option("--reason", help="Why it is withdrawn.")],
) -> None:
    """Withdraw a conclusion from evaluation (human act); the registration stays in the log."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        conclusions_service.retire_conclusion(project, project.human_actor(), conclusion_id, reason)
    typer.echo(f"retired {conclusion_id}")


@conclusions_app.command("status")
def conclusions_status_cmd(
    ctx: typer.Context,
    show_all: Annotated[bool, typer.Option("--all", help="Also list retired conclusions.")] = False,
) -> None:
    """Each active conclusion with your statement and its computed state since the last snapshot."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        records = conclusions_service.conclusions(project, include_retired=show_all)
        statements = {c.conclusion_id: c.statement for c in records}
        for record in records:
            if record.retired:
                typer.echo(f"{record.conclusion_id}  retired: {record.retire_reason}")
                typer.echo(f"  statement: {record.statement}")
        for diff in conclusions_service.conclusion_diff(project):
            for line in render.conclusion_lines(diff):
                typer.echo(line)
            typer.echo(f"  statement: {statements[diff.conclusion_id]}")


@conclusions_app.command("diff")
def conclusions_diff_cmd(
    ctx: typer.Context,
    since: Annotated[
        str | None, typer.Option("--since", help="Snapshot id to compare with (default: last).")
    ] = None,
) -> None:
    """Computed state of each active conclusion against a snapshot (no statements)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        for diff in conclusions_service.conclusion_diff(project, since=since):
            for line in render.conclusion_lines(diff):
                typer.echo(line)


class DigestFormat(StrEnum):
    MD = "md"
    JSON = "json"
    BOTH = "both"


@app.command("digest")
def digest_cmd(
    ctx: typer.Context,
    project: Annotated[str | None, typer.Option("--project", help="Project slug.")] = None,
    all_projects: Annotated[bool, typer.Option("--all", help="Every project.")] = False,
    since: Annotated[
        str, typer.Option("--since", help="`last` (default) or an event id.")
    ] = "last",
    fmt: Annotated[DigestFormat, typer.Option("--format", help="md, json or both.")] = (
        DigestFormat.MD
    ),
    out: Annotated[Path | None, typer.Option("--out", help="Write files into this directory.")] = (
        None
    ),
    record: Annotated[
        bool, typer.Option("--record", help="Store the digest and write digest.generated.")
    ] = False,
) -> None:
    """The computed digest since the last one (or an event): print it, or write it to --out."""
    state = _state(ctx)
    slugs = _watch_projects(state, project if project is not None else state.project, all_projects)
    if fmt is DigestFormat.BOTH and out is None:
        _fail("--format both needs --out", 2)
    with _reporting_errors():
        opened = [
            open_project(state.settings, slug, session=state.session, clock=state.clock)
            for slug in slugs
        ]
        if not opened:
            _fail("no project; run factory init", 2)
        built = digest_service.digest_build(opened, since=since)
        if record:
            built = built.model_copy(
                update={"digest_id": digest_service.record_digest(opened, built)}
            )
    name = built.digest_id or "digest"
    wanted = (DigestFormat.MD, DigestFormat.JSON) if fmt is DigestFormat.BOTH else (fmt,)
    for kind in wanted:
        text = digest_markdown(built) if kind is DigestFormat.MD else digest_json(built)
        if out is None:
            typer.echo(text, nl=False)
        else:
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{name}.{kind.value}").write_text(text, encoding="utf-8")
    if out is not None and built.digest_id is not None:
        typer.echo(f"recorded {built.digest_id}")


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


@import_app.command("coverage")
def import_coverage_cmd(
    ctx: typer.Context,
    import_id: Annotated[str, typer.Argument(help="An import id (imp_...).")],
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the report model as JSON.")
    ] = False,
) -> None:
    """How far the search reached the imported library, every part included (the researcher's
    view): counts per bucket, search sensitivity, corpus coverage, term suggestions."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = coverage_service.coverage_report(project, import_id)
    typer.echo(
        "warning: researcher view with held-out figures; this output must not be shown to agents",
        err=True,
    )
    if as_json:
        typer.echo(report.model_dump_json())
        return
    for line in render.import_coverage_lines(report):
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


# --- Relations and ideas (slice 3b, G2-C): every decision here is a human act ---


@relations_app.command("list")
def relations_list_cmd(
    ctx: typer.Context,
    status: Annotated[
        list[str] | None,
        typer.Option(
            "--status",
            help="Effective status to show (repeatable): stated, confirmed, inferred, stale or "
            "rejected. Default: stated and confirmed.",
        ),
    ] = None,
    work: Annotated[str | None, typer.Option("--work", help="Only relations of this work.")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Page size.")] = 200,
    offset: Annotated[int, typer.Option("--offset", min=0, help="Rows to skip.")] = 0,
) -> None:
    """Live relations with their effective status, reason and basis."""
    state = _state(ctx)
    try:
        statuses = (
            lineage_model.DEFAULT_STATUSES
            if not status
            else frozenset(lineage_model.EdgeStatus(s) for s in status)
        )
    except ValueError as exc:
        _fail(f"--status: {exc}", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        views = relations_service.list_relations(
            project, statuses=statuses, work_id=work, limit=limit, offset=offset
        )
        notes = relations_service.relation_notes(project, [v.relation_id for v in views])
    for line in render.relation_lines(views, notes):
        typer.echo(line)


def _decide_relation(
    ctx: typer.Context,
    relation: str,
    decision: lineage_model.LineageDecision,
    rationale: str,
) -> None:
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        relations_service.decide_relation(
            project, project.human_actor(), relation, decision, rationale
        )


@relations_app.command("confirm")
def relations_confirm_cmd(
    ctx: typer.Context,
    relation: Annotated[str, typer.Argument(help="An inferred relation id.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why it holds.")],
) -> None:
    """Confirm an inferred relation (it then counts in default views)."""
    _decide_relation(ctx, relation, lineage_model.LineageDecision.CONFIRM, rationale)
    typer.echo(f"confirmed {relation}")


@relations_app.command("reject")
def relations_reject_cmd(
    ctx: typer.Context,
    relation: Annotated[str, typer.Argument(help="A live relation id.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why it does not hold.")],
) -> None:
    """Reject a relation; it stays in the log and leaves default views."""
    _decide_relation(ctx, relation, lineage_model.LineageDecision.REJECT, rationale)
    typer.echo(f"rejected {relation}")


@ideas_app.command("list")
def ideas_list_cmd(
    ctx: typer.Context,
    all_: Annotated[
        bool, typer.Option("--all", help="Also list ideas still only proposed.")
    ] = False,
) -> None:
    """Confirmed ideas (merged ones fold into the idea they were merged into)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        views = ideas_service.list_ideas(project, include_unconfirmed=all_)
    for line in render.idea_lines(views):
        typer.echo(line)


@ideas_app.command("define")
def ideas_define_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The idea's name, as it occurs in the origin.")],
    origin: Annotated[str, typer.Option("--origin", help="The introducing work.")],
    name_item: Annotated[
        str, typer.Option("--name-item", help="A recorded item of the origin whose quote has it.")
    ],
    member: Annotated[
        list[str] | None,
        typer.Option("--member", help="A member work (repeatable); the origin is always one."),
    ] = None,
) -> None:
    """Propose an idea as a human; it still needs `ideas confirm`."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        members = sorted({origin, *(member or [])})
        idea_id = ideas_service.propose_idea(
            project, project.human_actor(), name, origin, name_item, members
        )
    typer.echo(f"defined {idea_id}")


def _decide_idea(
    ctx: typer.Context,
    idea: str,
    decision: lineage_model.LineageDecision,
    rationale: str,
) -> None:
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        ideas_service.decide_idea(project, project.human_actor(), idea, decision, rationale)


@ideas_app.command("confirm")
def ideas_confirm_cmd(
    ctx: typer.Context,
    idea: Annotated[str, typer.Argument(help="An idea id.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why it holds.")],
) -> None:
    """Confirm an idea and its members."""
    _decide_idea(ctx, idea, lineage_model.LineageDecision.CONFIRM, rationale)
    typer.echo(f"confirmed {idea}")


@ideas_app.command("reject")
def ideas_reject_cmd(
    ctx: typer.Context,
    idea: Annotated[str, typer.Argument(help="An idea id.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why it does not hold.")],
) -> None:
    """Reject an idea."""
    _decide_idea(ctx, idea, lineage_model.LineageDecision.REJECT, rationale)
    typer.echo(f"rejected {idea}")


@ideas_app.command("merge")
def ideas_merge_cmd(
    ctx: typer.Context,
    from_idea: Annotated[str, typer.Argument(help="The idea that is folded away.")],
    into: Annotated[str, typer.Argument(help="The idea it joins.")],
    reason: Annotated[str, typer.Option("--reason", help="Why they are one idea.")],
) -> None:
    """Merge two naming variants; reversible with `ideas unmerge`."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        ideas_service.merge_ideas(project, project.human_actor(), from_idea, into, reason)
    typer.echo(f"merged {from_idea} into {into}")


@ideas_app.command("unmerge")
def ideas_unmerge_cmd(
    ctx: typer.Context,
    from_idea: Annotated[str, typer.Argument(help="The merged idea to restore.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the merge is undone.")],
) -> None:
    """Undo the latest merge of an idea."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        ideas_service.unmerge_idea(project, project.human_actor(), from_idea, reason)
    typer.echo(f"unmerged {from_idea}")


@ideas_app.command("candidates")
def ideas_candidates_cmd(
    ctx: typer.Context,
    origin: Annotated[str, typer.Option("--origin", help="The introducing work.")],
    name: Annotated[str, typer.Option("--name", help="The idea's name.")],
) -> None:
    """Works that may belong to the idea (listing only; confirm members with `ideas define`)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        found = ideas_service.idea_candidates(project, origin, name)
    for line in render.idea_candidate_lines(found):
        typer.echo(line)


# --- The interpretation layer (slice 3c, plan G3-C): every review here is a human act ---

_BLOB_SHOWN = 2000


def _verdict(reviewed: bool, wrong: bool) -> Literal["reviewed", "wrong"]:
    if reviewed == wrong:
        _fail("name exactly one of --reviewed and --wrong", 2)
    return "wrong" if wrong else "reviewed"


def _parse_model(model: type[_M], data: object, label: str) -> _M:
    """Validate `data` as `model`; a failure is reported as `label.field: reason`, exit 1."""
    try:
        return model.model_validate(data)
    except PydanticValidationError as exc:
        for error in exc.errors():
            where = ".".join(str(p) for p in error["loc"])
            typer.echo(f"{label}{'.' + where if where else ''}: {error['msg']}", err=True)
        raise typer.Exit(1) from None


def _sources(raw: list[str] | None) -> list[object]:
    parsed: list[object] = []
    for i, text_ in enumerate(raw or []):
        try:
            parsed.append(json.loads(text_))
        except json.JSONDecodeError as exc:
            _fail(f"source[{i}]: not JSON ({exc.msg})", 1)
    return parsed


def _source_inputs(raw: list[str] | None) -> list[object]:
    adapter = TypeAdapter(SourceInput)
    out: list[object] = []
    for i, data in enumerate(_sources(raw)):
        try:
            out.append(adapter.validate_python(data))
        except PydanticValidationError as exc:
            for error in exc.errors():
                where = ".".join(str(p) for p in error["loc"])
                typer.echo(f"source[{i}].{where}: {error['msg']}", err=True)
            raise typer.Exit(1) from None
    return out


def _concept_source(kind: str | None, citation: str | None, work: str | None) -> object:
    if kind is None and citation is None and work is None:
        return None
    if kind is None or citation is None:
        _fail("a source needs --source-kind and --citation", 2)
    return _parse_model(
        ConceptSourceInput, {"kind": kind, "citation": citation, "work_id": work}, "source"
    )


@interpretations_app.command("list")
def interpretations_list_cmd(
    ctx: typer.Context,
    state_: Annotated[
        list[str] | None,
        typer.Option(
            "--state",
            help="unreviewed, reviewed, wrong or superseded (repeatable); default the first two.",
        ),
    ] = None,
    target: Annotated[str | None, typer.Option("--target", help="An idea or paper.")] = None,
    cursor: Annotated[str | None, typer.Option("--cursor", help="Continue after this id.")] = None,
) -> None:
    """Interpretations, labelled; wrong and superseded ones are hidden and counted."""
    state = _state(ctx)
    states: list[ReviewState] | None = None
    if state_:
        try:
            states = [ReviewState(s) for s in state_]
        except ValueError:
            _fail("--state: unreviewed, reviewed, wrong or superseded", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        found = interpretations_service.list_interpretations(
            project, target=target, states=states, cursor=cursor
        )
    for line in render.interpretation_list_lines(found):
        typer.echo(line)


@interpretations_app.command("show")
def interpretations_show_cmd(
    ctx: typer.Context, interpretation: Annotated[str, typer.Argument(help="An int_ id.")]
) -> None:
    """One interpretation: text, sources with quote and anchor, writer, input and flags."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        found = interpretations_service.list_interpretations(
            project, states=list(ReviewState), interpretation_id=interpretation
        )
        if not found.items:
            raise FactoryValidationError([ValidationIssue("interpretation_id", "unknown")])
        view = found.items[0]
        blob: str | None = None
        if view.input_blob is not None:
            try:
                blob = project.blobs.get(view.input_blob).decode("utf-8")
                if len(blob) > _BLOB_SHOWN:
                    blob = blob[:_BLOB_SHOWN] + " ... (cut)"
            except (OSError, UnicodeDecodeError, KeyError):
                blob = None
    for line in render.interpretation_lines(view, blob):
        typer.echo(line)


@interpretations_app.command("history")
def interpretations_history_cmd(
    ctx: typer.Context, interpretation: Annotated[str, typer.Argument(help="An int_ id.")]
) -> None:
    """Every step of an interpretation, with review notes."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        entries = interpretations_service.interpretation_history(project, interpretation)
        if not entries:
            raise FactoryValidationError([ValidationIssue("interpretation_id", "unknown")])
    for line in render.history_lines(entries):
        typer.echo(line)


@interpretations_app.command("review")
def interpretations_review_cmd(
    ctx: typer.Context,
    interpretation: Annotated[str, typer.Argument(help="An int_ id.")],
    reviewed: Annotated[bool, typer.Option("--reviewed", help="It is right.")] = False,
    wrong: Annotated[bool, typer.Option("--wrong", help="It is wrong (needs --note).")] = False,
    note: Annotated[str, typer.Option("--note", help="Why.")] = "",
) -> None:
    """Review an interpretation as the human; a wrong verdict needs a note."""
    verdict = _verdict(reviewed, wrong)
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        interpretations_service.review_interpretation(
            project, project.human_actor(), interpretation, verdict, note, Channel.CLI
        )
    typer.echo(f"{interpretation}  interpretation · {verdict}")


@interpretations_app.command("supersede")
def interpretations_supersede_cmd(
    ctx: typer.Context,
    interpretation: Annotated[str, typer.Argument(help="The int_ id to replace.")],
    text_: Annotated[str, typer.Option("--text", help="The replacement text.")],
    source: Annotated[
        list[str] | None, typer.Option("--source", help="A source as JSON (repeatable).")
    ] = None,
) -> None:
    """Replace an interpretation with the human's own; the earlier one becomes superseded."""
    state = _state(ctx)
    sources = _source_inputs(source)
    with _reporting_errors():
        project = _resolve_project(state)
        new = interpretations_service.supersede_interpretation(
            project,
            project.human_actor(),
            interpretation,
            text_,
            cast(list[SourceInput], sources),
        )
    typer.echo(f"{new}  interpretation · unreviewed  supersedes {interpretation}")


@interpretations_app.command("write")
def interpretations_write_cmd(
    ctx: typer.Context,
    target: Annotated[str, typer.Option("--target", help="A confirmed idea or a corpus paper.")],
    text_: Annotated[str, typer.Option("--text", help="At most 600 characters.")],
    source: Annotated[
        list[str] | None, typer.Option("--source", help="A source as JSON (repeatable, 1 to 5).")
    ] = None,
) -> None:
    """Write an interpretation as the human (no task)."""
    state = _state(ctx)
    sources = _source_inputs(source)
    with _reporting_errors():
        project = _resolve_project(state)
        entry = InterpretationInput(
            target=target, text=text_, sources=tuple(cast(list[SourceInput], sources))
        )
        new = interpretations_service.record_interpretation(project, project.human_actor(), entry)
    typer.echo(f"{new}  interpretation · unreviewed")


@concepts_app.command("list")
def concepts_list_cmd(
    ctx: typer.Context,
    all_: Annotated[
        bool, typer.Option("--all", help="Also list concepts that are hidden by default.")
    ] = False,
    cursor: Annotated[str | None, typer.Option("--cursor", help="Continue after this id.")] = None,
) -> None:
    """Concepts with an approved source, labelled; the others are counted."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        found = concepts_service.list_concepts(project, include_hidden=all_, cursor=cursor)
    for line in render.concept_list_lines(found):
        typer.echo(line)


@concepts_app.command("show")
def concepts_show_cmd(
    ctx: typer.Context, concept: Annotated[str, typer.Argument(help="A cpt_ id.")]
) -> None:
    """One concept: name, text, source, quotes, writer and flags."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        view = concepts_service.concept_view(project, concept)
        if view is None:
            raise FactoryValidationError([ValidationIssue("concept_id", "concept-unknown")])
    for line in render.concept_lines(view):
        typer.echo(line)


@concepts_app.command("history")
def concepts_history_cmd(
    ctx: typer.Context, concept: Annotated[str, typer.Argument(help="A cpt_ id.")]
) -> None:
    """Every step of a concept: definitions, source decisions and reviews."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        entries = concepts_service.concept_history(project, concept)
        if not entries:
            raise FactoryValidationError([ValidationIssue("concept_id", "concept-unknown")])
    for line in render.history_lines(entries):
        typer.echo(line)


@concepts_app.command("define")
def concepts_define_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The concept's name.")],
    alias: Annotated[list[str] | None, typer.Option("--alias", help="Another name.")] = None,
    text_: Annotated[str | None, typer.Option("--text", help="A short explanation.")] = None,
    source_kind: Annotated[
        str | None, typer.Option("--source-kind", help="textbook, survey, corpus-paper or other.")
    ] = None,
    citation: Annotated[
        str | None, typer.Option("--citation", help="The source, as cited.")
    ] = None,
    work: Annotated[
        str | None, typer.Option("--work", help="The source's work id, if in the corpus.")
    ] = None,
    approve: Annotated[
        bool, typer.Option("--approve", help="Approve the source in the same step.")
    ] = False,
) -> None:
    """Define a concept as the human; with --approve its source is approved too."""
    state = _state(ctx)
    source = _concept_source(source_kind, citation, work)
    entry = _parse_model(
        ConceptInput,
        {"name": name, "aliases": alias or [], "text": text_, "source": source},
        "concept",
    )
    with _reporting_errors():
        project = _resolve_project(state)
        concept_id = concepts_service.define_concept(
            project, project.human_actor(), entry, approve_source=approve
        )
    typer.echo(f"{concept_id}  concept defined" + ("; source approved" if approve else ""))


@concepts_app.command("source")
def concepts_source_cmd(
    ctx: typer.Context,
    concept: Annotated[str, typer.Argument(help="A cpt_ id.")],
    source_kind: Annotated[
        str, typer.Option("--source-kind", help="textbook, survey, corpus-paper or other.")
    ],
    citation: Annotated[str, typer.Option("--citation", help="The source, as cited.")],
    work: Annotated[str | None, typer.Option("--work", help="The source's work id.")] = None,
) -> None:
    """Give a concept a new source (a redefinition by the human) and approve it."""
    state = _state(ctx)
    source = _concept_source(source_kind, citation, work)
    with _reporting_errors():
        project = _resolve_project(state)
        view = concepts_service.concept_view(project, concept)
        if view is None:
            raise FactoryValidationError([ValidationIssue("concept_id", "concept-unknown")])
        live = [
            h for h in concepts_service.concept_history(project, concept) if h.kind == "recorded"
        ]
        entry = _parse_model(
            ConceptInput,
            {
                "name": view.name,
                "aliases": view.aliases,
                "text": view.text,
                "source": source,
                "concept_id": concept,
                "supersedes": live[-1].event_id,
            },
            "concept",
        )
        concepts_service.define_concept(project, project.human_actor(), entry, approve_source=True)
    typer.echo(f"{concept}  source redefined and approved")


@concepts_app.command("approve")
def concepts_approve_cmd(
    ctx: typer.Context,
    concept: Annotated[str, typer.Argument(help="A cpt_ id.")],
    note: Annotated[str, typer.Option("--note", help="Optional.")] = "",
) -> None:
    """Approve a concept's source; the concept then shows, labelled unreviewed."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        concepts_service.decide_concept_source(
            project, project.human_actor(), concept, "approve", note, Channel.CLI
        )
    typer.echo(f"{concept}  source approved")


@concepts_app.command("reject-source")
def concepts_reject_source_cmd(
    ctx: typer.Context,
    concept: Annotated[str, typer.Argument(help="A cpt_ id.")],
    note: Annotated[str, typer.Option("--note", help="Why the source does not serve.")] = "",
) -> None:
    """Reject a concept's source (a note is required)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        concepts_service.decide_concept_source(
            project, project.human_actor(), concept, "reject", note, Channel.CLI
        )
    typer.echo(f"{concept}  source rejected")


@concepts_app.command("review")
def concepts_review_cmd(
    ctx: typer.Context,
    concept: Annotated[str, typer.Argument(help="A cpt_ id.")],
    reviewed: Annotated[bool, typer.Option("--reviewed", help="The definition is right.")] = False,
    wrong: Annotated[bool, typer.Option("--wrong", help="It is wrong (needs --note).")] = False,
    note: Annotated[str, typer.Option("--note", help="Why.")] = "",
) -> None:
    """Review a concept's live definition as the human; a wrong verdict needs a note."""
    verdict = _verdict(reviewed, wrong)
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        concepts_service.review_concept(
            project, project.human_actor(), concept, verdict, note, Channel.CLI
        )
    typer.echo(f"{concept}  interpretation · {verdict}")


@concepts_app.command("merge")
def concepts_merge_cmd(
    ctx: typer.Context,
    into: Annotated[str, typer.Argument(help="The concept that stays.")],
    from_concept: Annotated[str, typer.Argument(help="The concept folded into it.")],
    reason: Annotated[str, typer.Option("--reason", help="Why they are one concept.")],
) -> None:
    """Merge two names of one concept; reversible with `concepts unmerge`."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        concepts_service.merge_concepts(project, project.human_actor(), into, from_concept, reason)
    typer.echo(f"merged {from_concept} into {into}")


@concepts_app.command("unmerge")
def concepts_unmerge_cmd(
    ctx: typer.Context,
    into: Annotated[str, typer.Argument(help="The concept it was merged into.")],
    from_concept: Annotated[str, typer.Argument(help="The merged concept to restore.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the merge is undone.")],
) -> None:
    """Undo a merge."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        concepts_service.unmerge_concepts(
            project, project.human_actor(), into, from_concept, reason
        )
    typer.echo(f"unmerged {from_concept} from {into}")


@concept_links_app.command("list")
def concept_links_list_cmd(
    ctx: typer.Context,
    status_: Annotated[
        list[str] | None,
        typer.Option("--status", help="stated, inferred, confirmed or rejected (repeatable)."),
    ] = None,
    cursor: Annotated[str | None, typer.Option("--cursor", help="Continue after this id.")] = None,
) -> None:
    """`uses` links, labelled; the default shows stated and confirmed ones."""
    state = _state(ctx)
    statuses: list[LinkStatus] | None = None
    if status_:
        try:
            statuses = [LinkStatus(s) for s in status_]
        except ValueError:
            _fail("--status: stated, inferred, confirmed or rejected", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        found = concepts_service.list_concept_links(project, statuses=statuses, cursor=cursor)
    for line in render.concept_link_lines(found):
        typer.echo(line)


def _decide_link(
    ctx: typer.Context, link: str, decision: Literal["confirm", "reject"], rationale: str
) -> None:
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        concepts_service.decide_concept_link(
            project, project.human_actor(), link, decision, rationale, Channel.CLI
        )


@concept_links_app.command("confirm")
def concept_links_confirm_cmd(
    ctx: typer.Context,
    link: Annotated[str, typer.Argument(help="An inferred cul_ link.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why the concept is used.")],
) -> None:
    """Confirm an inferred `uses` link."""
    _decide_link(ctx, link, "confirm", rationale)
    typer.echo(f"{link}  interpretation · confirmed")


@concept_links_app.command("reject")
def concept_links_reject_cmd(
    ctx: typer.Context,
    link: Annotated[str, typer.Argument(help="A cul_ link.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why it does not hold.")],
) -> None:
    """Reject a `uses` link; it stays in the log and leaves the views."""
    _decide_link(ctx, link, "reject", rationale)
    typer.echo(f"{link}  interpretation · rejected")


# --- Vocabulary and cards (slice 6, H-A): every decision here is a human act ---


@vocabulary_app.command("list")
def vocabulary_list_cmd(
    ctx: typer.Context,
    all_: Annotated[
        bool,
        typer.Option("--all", help="Also list proposed, rejected and superseded definitions."),
    ] = False,
) -> None:
    """The approved properties (`V@` names them)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        views = properties_service.list_properties(
            project, include_proposed=all_, include_rejected=all_
        )
        version = properties_service.vocabulary_version(project)
    typer.echo(f"vocabulary {version}")
    for line in render.property_lines(views):
        typer.echo(line)


def _decide_property(
    ctx: typer.Context, key: str, decision: Literal["approve", "reject"], why: str
) -> None:
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        properties_service.decide_property(project, project.human_actor(), key, decision, why)


@vocabulary_app.command("approve")
def vocabulary_approve_cmd(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="A property key, pr:<slug>.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why it belongs.")],
) -> None:
    """Approve a proposed definition; until then it is unusable."""
    _decide_property(ctx, key, "approve", rationale)
    typer.echo(f"approved {key}")


@vocabulary_app.command("reject")
def vocabulary_reject_cmd(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="A property key, pr:<slug>.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why it does not belong.")],
) -> None:
    """Reject a pending proposal, or withdraw the approved definition of the key."""
    _decide_property(ctx, key, "reject", rationale)
    typer.echo(f"rejected {key}")


@vocabulary_app.command("merge")
def vocabulary_merge_cmd(
    ctx: typer.Context,
    from_key: Annotated[str, typer.Argument(help="The property that is folded away.")],
    into: Annotated[str, typer.Argument(help="The property it joins.")],
    reason: Annotated[str, typer.Option("--reason", help="Why they are one property.")],
) -> None:
    """Merge two properties of one kind; reversible with `vocabulary unmerge`."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        properties_service.merge_properties(project, project.human_actor(), from_key, into, reason)
    typer.echo(f"merged {from_key} into {into}")


@vocabulary_app.command("unmerge")
def vocabulary_unmerge_cmd(
    ctx: typer.Context,
    from_key: Annotated[str, typer.Argument(help="The merged property to restore.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the merge is undone.")],
) -> None:
    """Undo the latest merge of a property."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        properties_service.unmerge_property(project, project.human_actor(), from_key, reason)
    typer.echo(f"unmerged {from_key}")


@cards_app.command("list")
def cards_list_cmd(
    ctx: typer.Context,
    kind: Annotated[
        str | None, typer.Option("--kind", help="method or problem; default both.")
    ] = None,
) -> None:
    """Method cards and problem descriptions, with their live assertion counts."""
    if kind not in (None, "method", "problem"):
        _fail("--kind must be method or problem", 2)
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        found = cards_service.list_cards(project, kind)  # type: ignore[arg-type]
    for line in render.card_lines(found):
        typer.echo(line)


@cards_app.command("show")
def cards_show_cmd(
    ctx: typer.Context,
    card: Annotated[str, typer.Argument(help="A card id, mcd_ or pbd_.")],
    inferred: Annotated[
        bool,
        typer.Option("--inferred", help="Also show inferred and imported-unverified assertions."),
    ] = False,
) -> None:
    """A card with its assertions; stale ones are shown and labelled with why."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        view = cards_service.card_view(project, card, include_inferred=inferred, include_stale=True)
    if view is None:
        _fail(f"{card}: unknown card", 1)
    for line in render.card_view_lines(view):
        typer.echo(line)


@cards_app.command("assert")
def cards_assert_cmd(
    ctx: typer.Context,
    card: Annotated[str, typer.Argument(help="A card id.")],
    property_key: Annotated[str, typer.Option("--property", help="An approved property key.")],
    value: Annotated[
        str, typer.Option("--value", help="The value; true/false for a bool, a,b for a set.")
    ],
    unit: Annotated[str | None, typer.Option("--unit", help="The unit of a number.")] = None,
    researcher: Annotated[
        bool,
        typer.Option("--researcher", help="State it yourself (researcher basis); required."),
    ] = False,
) -> None:
    """Record a property you state yourself (a `researcher` basis assertion, `stated`)."""
    if not researcher:
        _fail("a human assertion is a researcher statement: add --researcher", 2)
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        item = cards_service.AssertionInput(
            property=property_key,
            value=cards_service.parse_cli_value(project, property_key, value),
            unit=unit,
            basis_kind="researcher",
        )
        result = cards_service.assert_properties(project, project.human_actor(), card, [item])
    for _, ident, status in result.accepted:
        typer.echo(f"asserted {ident} ({status})")
    for _, issues in result.rejected:
        for issue in issues:
            typer.echo(f"refused: {issue.field}: {issue.reason}", err=True)
    if result.rejected:
        raise typer.Exit(1)


def _decide_assertion(
    ctx: typer.Context, assertion: str, decision: Literal["confirm", "reject"], why: str
) -> None:
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        cards_service.decide_assertion(project, project.human_actor(), assertion, decision, why)


@cards_app.command("confirm")
def cards_confirm_cmd(
    ctx: typer.Context,
    assertion: Annotated[str, typer.Argument(help="An inferred assertion id, pas_.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why it holds.")],
) -> None:
    """Confirm an inferred (or imported-unverified) assertion."""
    _decide_assertion(ctx, assertion, "confirm", rationale)
    typer.echo(f"confirmed {assertion}")


@cards_app.command("reject")
def cards_reject_cmd(
    ctx: typer.Context,
    assertion: Annotated[str, typer.Argument(help="An assertion id, pas_.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why it does not hold.")],
) -> None:
    """Reject an assertion; it stays in the log and leaves the default views."""
    _decide_assertion(ctx, assertion, "reject", rationale)
    typer.echo(f"rejected {assertion}")


_INCLUDE_INFERRED = typer.Option(
    "--include-inferred", help="Also show inferred relations and unconfirmed ideas, labelled."
)
_INCLUDE_STALE = typer.Option("--include-stale", help="Also show stale relations, labelled.")
_WITH_INTERPRETATION = typer.Option(
    "--with-interpretation",
    help="Also show the interpretation layer, in a separate part marked as not evidence.",
)


def _layer(with_interpretation: bool) -> graph_service.Layer:
    return "all" if with_interpretation else "evidence"


@graph_app.command("build")
def graph_build_cmd(ctx: typer.Context) -> None:
    """Sync the index (which projects the graph) and print the graph status."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        project.index.sync()
        status = graph_service.graph_status(project)
    for line in render.graph_status_lines(status):
        typer.echo(line)


@graph_app.command("status")
def graph_status_cmd(
    ctx: typer.Context, with_interpretation: Annotated[bool, _WITH_INTERPRETATION] = False
) -> None:
    """Node and edge counts by type and status; the layer's counts only on request."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        status = graph_service.graph_status(project, layer=_layer(with_interpretation))
    for line in render.graph_status_lines(status):
        typer.echo(line)


@graph_app.command("query")
def graph_query_cmd(
    ctx: typer.Context,
    kind: Annotated[
        str,
        typer.Argument(
            help="ancestors, descendants, path, improvements_on, cited_by_at_least or "
            "no_stated_base."
        ),
    ],
    node: Annotated[str | None, typer.Option("--node", help="The work or idea.")] = None,
    target: Annotated[str | None, typer.Option("--target", help="The path's end.")] = None,
    depth: Annotated[int, typer.Option("--depth", help="Levels (at most 8).")] = 3,
    k: Annotated[int, typer.Option("--k", help="Distinct citing works.")] = 2,
    include_inferred: Annotated[bool, _INCLUDE_INFERRED] = False,
    include_stale: Annotated[bool, _INCLUDE_STALE] = False,
    with_interpretation: Annotated[bool, _WITH_INTERPRETATION] = False,
) -> None:
    """Run a bounded lineage query; the default view shows stated and confirmed edges."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        result = graph_service.graph_query(
            project,
            kind,
            node=node,
            target=target,
            depth=depth,
            k=k,
            flt=GraphFilter(include_inferred=include_inferred, include_stale=include_stale),
            layer=_layer(with_interpretation),
        )
    for line in render.graph_query_lines(result):
        typer.echo(line)


@graph_app.command("export")
def graph_export_cmd(
    ctx: typer.Context,
    format_: Annotated[str, typer.Option("--format", help="json or dot.")] = "json",
    query: Annotated[str | None, typer.Option("--query", help="Export a query's subgraph.")] = None,
    node: Annotated[str | None, typer.Option("--node")] = None,
    target: Annotated[str | None, typer.Option("--target")] = None,
    depth: Annotated[int, typer.Option("--depth")] = 3,
    k: Annotated[int, typer.Option("--k")] = 2,
    include_inferred: Annotated[bool, _INCLUDE_INFERRED] = False,
    include_stale: Annotated[bool, _INCLUDE_STALE] = False,
    with_interpretation: Annotated[bool, _WITH_INTERPRETATION] = False,
    out: Annotated[Path | None, typer.Option("--out", help="Write to this file.")] = None,
) -> None:
    """Export the graph (no size cap), streamed in a deterministic order."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        chunks = graph_service.iter_graph_export(
            project,
            cast(graph_service.ExportFormat, format_),  # validated by the service
            query=query,
            node=node,
            target=target,
            depth=depth,
            k=k,
            flt=GraphFilter(include_inferred=include_inferred, include_stale=include_stale),
            layer=_layer(with_interpretation),
        )
        if out is None:
            for chunk in chunks:
                typer.echo(chunk, nl=False)
        else:
            with out.open("w", encoding="utf-8") as handle:
                for chunk in chunks:
                    handle.write(chunk)
            typer.echo(f"wrote {out}")


# --- Matching, finders and contradictions (slice 6, H-B) ---


@app.command("match")
def match_cmd(
    ctx: typer.Context,
    problem: Annotated[str, typer.Argument(help="A problem description id, pbd_.")],
    inferred: Annotated[
        bool, typer.Option("--inferred", help="Also count inferred assertions, labelled.")
    ] = False,
    transfer: Annotated[
        bool, typer.Option("--transfer", help="Only cards with no member work in this project.")
    ] = False,
    limit: Annotated[int, typer.Option("--limit", help="Rows per page.")] = 50,
    after: Annotated[str | None, typer.Option("--after", help="Cursor from a page.")] = None,
) -> None:
    """Method cards matched against a problem description: a computed candidate list."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        page = matching_service.match(
            project,
            problem,
            include_inferred=inferred,
            transfer_only=transfer,
            limit=limit,
            after=after,
        )
    for line in render.match_lines(page):
        typer.echo(line)


@finders_app.command("conflicts")
def finders_conflicts_cmd(
    ctx: typer.Context,
    group: Annotated[str | None, typer.Option("--group", help="One group id, grp_.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Pairs per page.")] = 50,
    after: Annotated[str | None, typer.Option("--after", help="Cursor from a page.")] = None,
) -> None:
    """Numeric conflicts inside comparability groups, with the conditions that differ."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        page = findings_service.find_conflicts(project, group_id=group, limit=limit, after=after)
    for line in render.conflict_lines(page):
        typer.echo(line)


@finders_app.command("gaps")
def finders_gaps_cmd(
    ctx: typer.Context,
    rows: Annotated[str, typer.Option("--rows", help="method or card.")],
    columns: Annotated[
        str, typer.Option("--columns", help="A comparability key, or a pr: property key.")
    ],
    filter_: Annotated[
        list[str] | None, typer.Option("--filter", help="KEY=VALUE; repeat for more.")
    ] = None,
) -> None:
    """Empty cells of a method x condition grid, with the corpus definition."""
    filters: dict[str, str] = {}
    for item in filter_ or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            _fail(f"--filter {item!r}: expected KEY=VALUE", 2)
        filters[key] = value
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = findings_service.find_gaps(
            project, rows_axis=rows, columns_axis=columns, filters=filters
        )
    for line in render.gap_lines(report):
        typer.echo(line)


@contradictions_app.command("list")
def contradictions_list_cmd(
    ctx: typer.Context,
    state_: Annotated[
        list[str] | None,
        typer.Option("--state", help="inferred, confirmed, rejected or stale; repeat for more."),
    ] = None,
) -> None:
    """Claim contradictions; the default shows the confirmed ones."""
    chosen = state_ or ["confirmed"]
    for name in chosen:
        if name not in ("inferred", "confirmed", "rejected", "stale"):
            _fail(f"--state {name!r}: expected inferred, confirmed, rejected or stale", 2)
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        views = findings_service.list_contradictions(project, states=chosen)
    for line in render.contradiction_lines(views):
        typer.echo(line)


def _decide_contradiction(
    ctx: typer.Context, ident: str, decision: Literal["confirm", "reject"], why: str
) -> None:
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        findings_service.decide_contradiction(project, project.human_actor(), ident, decision, why)


@contradictions_app.command("confirm")
def contradictions_confirm_cmd(
    ctx: typer.Context,
    contradiction: Annotated[str, typer.Argument(help="A contradiction id, ctr_.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why the two refs contradict.")],
) -> None:
    """Confirm a proposed contradiction (a human act, not from the proposing session)."""
    _decide_contradiction(ctx, contradiction, "confirm", rationale)
    typer.echo(f"confirmed {contradiction}")


@contradictions_app.command("reject")
def contradictions_reject_cmd(
    ctx: typer.Context,
    contradiction: Annotated[str, typer.Argument(help="A contradiction id, ctr_.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why they do not.")],
) -> None:
    """Reject a proposed contradiction; it stays in the log."""
    _decide_contradiction(ctx, contradiction, "reject", rationale)
    typer.echo(f"rejected {contradiction}")


# --- Regions and foci (slice 3d, Regions-A) ---


def _read_rules(path: Path) -> RuleSet:
    try:
        return RuleSet.model_validate_json(path.read_text())
    except (OSError, PydanticValidationError) as exc:
        _fail(f"--rules {path}: {exc}", 2)


def _parse_facet(raw: str) -> Facet:
    question, _, slot = raw.rpartition(":")
    try:
        return Facet(question_id=question, slot=slot)
    except PydanticValidationError as exc:
        _fail(f"--facet must be Q@xxxxxxxx:slot ({exc.errors()[0]['msg']})", 2)


@regions_app.command("define")
def regions_define_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="The region's name.")],
    kind: Annotated[RegionKind, typer.Option("--kind", help="focus or region.")],
    definition: Annotated[str, typer.Option("--definition", help="What it selects, at most 600.")],
    rules: Annotated[Path, typer.Option("--rules", help="A JSON file holding the rule set.")],
    facet: Annotated[
        str | None, typer.Option("--facet", help="Q@xxxxxxxx:slot, for a focus only.")
    ] = None,
) -> None:
    """Define a region or a focus as a human; take a snapshot to pin a version."""
    state = _state(ctx)
    rule_set = _read_rules(rules)
    bound = None if facet is None else _parse_facet(facet)
    with _reporting_errors():
        project = _resolve_project(state)
        region_id = regions_service.define_region(
            project,
            project.human_actor(),
            kind=kind,
            name=name,
            definition=definition,
            rules=rule_set,
            facet=bound,
        )
    typer.echo(f"defined {region_id}")


@regions_app.command("revise")
def regions_revise_cmd(
    ctx: typer.Context,
    region: Annotated[str, typer.Argument(help="A region id, reg_.")],
    name: Annotated[str, typer.Option("--name", help="The region's name.")],
    definition: Annotated[str, typer.Option("--definition", help="What it selects, at most 600.")],
    rules: Annotated[Path, typer.Option("--rules", help="A JSON file holding the rule set.")],
) -> None:
    """Record a new definition of a region; its kind and facet stay."""
    state = _state(ctx)
    rule_set = _read_rules(rules)
    with _reporting_errors():
        project = _resolve_project(state)
        kind = regions_service.region_state(project, region).kind
        regions_service.define_region(
            project,
            project.human_actor(),
            kind=kind,
            name=name,
            definition=definition,
            rules=rule_set,
            region_id=region,
        )
    typer.echo(f"revised {region}")


@regions_app.command("snapshot")
def regions_snapshot_cmd(
    ctx: typer.Context,
    region: Annotated[str, typer.Argument(help="A region id, reg_.")],
) -> None:
    """Evaluate the rules now and pin the member set as a version R@."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        version = regions_service.snapshot_region(project, project.human_actor(), region)
    typer.echo(f"snapshot {version}")


@regions_app.command("review")
def regions_review_cmd(
    ctx: typer.Context,
    version: Annotated[str, typer.Argument(help="A region version, R@xxxxxxxx.")],
    reviewed: Annotated[bool, typer.Option("--reviewed", help="The members are right.")] = False,
    wrong: Annotated[bool, typer.Option("--wrong", help="The members are wrong.")] = False,
    note: Annotated[str | None, typer.Option("--note", help="Required with --wrong.")] = None,
) -> None:
    """Review a pinned version (a human act; not from the session that wrote the definition)."""
    state = _state(ctx)
    if reviewed == wrong:
        _fail("pass exactly one of --reviewed and --wrong", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        regions_service.review_region(
            project, project.human_actor(), version, "wrong" if wrong else "reviewed", note
        )
    typer.echo(f"{'wrong' if wrong else 'reviewed'} {version}")


def _decide_region_member(
    ctx: typer.Context,
    region: str,
    member: str,
    member_type: MemberType,
    decision: Literal["add", "remove", "reject"],
    rationale: str | None = None,
    proposal: str | None = None,
) -> None:
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        regions_service.decide_member(
            project,
            project.human_actor(),
            region,
            member_type,
            member,
            decision,
            rationale,
            proposal_id=proposal,
        )
    typer.echo(f"{decision} {member}")


_RATIONALE = typer.Option("--rationale", help="Why, at most 600 characters.")
_PROPOSAL = typer.Option("--proposal", help="The proposal this answers, rmp_.")


@regions_app.command("add")
def regions_add_cmd(
    ctx: typer.Context,
    region: Annotated[str, typer.Argument(help="A region id, reg_.")],
    member: Annotated[str, typer.Argument(help="A work, idea or concept id.")],
    member_type: Annotated[
        MemberType, typer.Option("--type", help="work, idea or concept.")
    ] = MemberType.WORK,
    rationale: Annotated[str | None, _RATIONALE] = None,
    proposal: Annotated[str | None, _PROPOSAL] = None,
) -> None:
    """Add a member to a region by a human decision; it enters the next snapshot."""
    _decide_region_member(ctx, region, member, member_type, "add", rationale, proposal)


@regions_app.command("remove")
def regions_remove_cmd(
    ctx: typer.Context,
    region: Annotated[str, typer.Argument(help="A region id, reg_.")],
    member: Annotated[str, typer.Argument(help="A work, idea or concept id.")],
    member_type: Annotated[
        MemberType, typer.Option("--type", help="work, idea or concept.")
    ] = MemberType.WORK,
    rationale: Annotated[str | None, _RATIONALE] = None,
    proposal: Annotated[str | None, _PROPOSAL] = None,
) -> None:
    """Remove a member from a region by a human decision; it leaves the next snapshot."""
    _decide_region_member(ctx, region, member, member_type, "remove", rationale, proposal)


@regions_app.command("reject")
def regions_reject_cmd(
    ctx: typer.Context,
    region: Annotated[str, typer.Argument(help="A region id, reg_.")],
    member: Annotated[str, typer.Argument(help="A work, idea or concept id.")],
    member_type: Annotated[
        MemberType, typer.Option("--type", help="work, idea or concept.")
    ] = MemberType.WORK,
    rationale: Annotated[str | None, _RATIONALE] = None,
    proposal: Annotated[str | None, _PROPOSAL] = None,
) -> None:
    """Reject the proposals of a member; membership is unchanged and the proposal closes."""
    _decide_region_member(ctx, region, member, member_type, "reject", rationale, proposal)


@regions_app.command("proposals")
def regions_proposals_cmd(
    ctx: typer.Context,
    region: Annotated[str, typer.Argument(help="A region id, reg_.")],
) -> None:
    """The open member proposals of a region, with their verified basis."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        open_ones = regions_service.pending_proposals(project, region)
    for line in render.proposal_lines(open_ones):
        typer.echo(line)


@regions_app.command("link")
def regions_link_cmd(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="The first version, R@xxxxxxxx.")],
    target: Annotated[str, typer.Argument(help="The second version, R@xxxxxxxx.")],
    subregion_of: Annotated[
        bool, typer.Option("--subregion-of", help="SOURCE's members are all in TARGET.")
    ] = False,
    related: Annotated[bool, typer.Option("--related", help="The two are related.")] = False,
    note: Annotated[str | None, typer.Option("--note", help="A note on the link.")] = None,
) -> None:
    """Declare a link between two pinned versions (a human act; `subregion-of` is verified)."""
    state = _state(ctx)
    if subregion_of == related:
        _fail("pass exactly one of --subregion-of and --related", 2)
    link_type: Literal["subregion-of", "related"] = "subregion-of" if subregion_of else "related"
    with _reporting_errors():
        project = _resolve_project(state)
        regions_service.link_regions(
            project, project.human_actor(), link_type, source, target, note
        )
    typer.echo(f"{link_type} {source} {target}")


@regions_app.command("export")
def regions_export_cmd(
    ctx: typer.Context,
    version: Annotated[str, typer.Argument(help="A region version, R@xxxxxxxx.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Every member of a version with its basis: ids and types only, no text."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        rows = regions_service.export_version(project, version)
    for line in render.export_lines(version, rows, as_json=as_json):
        typer.echo(line)


@regions_app.command("list")
def regions_list_cmd(ctx: typer.Context) -> None:
    """Regions and foci with their latest version, review state and drift."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        states = [
            regions_service.region_state(project, rid)
            for rid in regions_service.region_ids(project)
        ]
    for line in render.region_lines(states):
        typer.echo(line)


@regions_app.command("show")
def regions_show_cmd(
    ctx: typer.Context,
    ident: Annotated[str, typer.Argument(help="A region id (reg_) or a version (R@).")],
    members: Annotated[bool, typer.Option("--members", help="List the members.")] = False,
    offset: Annotated[int, typer.Option("--offset", min=0, help="Members to skip.")] = 0,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Page size.")] = 500,
) -> None:
    """One region (live state and drift) or one version (counts and review state)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        if ident.startswith("R@"):
            info = regions_service.version_info(project, ident)
            if info is None:
                raise FactoryValidationError([ValidationIssue("version", "version-unknown")])
            lines = render.version_lines(info)
            version: str | None = ident
        else:
            region_state = regions_service.region_state(project, ident)
            lines = render.region_lines([region_state])
            version = region_state.latest_version
        page = (
            regions_service.region_members(project, version, offset=offset, limit=limit)
            if members and version is not None
            else []
        )
    for line in [*lines, *render.member_lines(page)]:
        typer.echo(line)


@regions_app.command("diff")
def regions_diff_cmd(
    ctx: typer.Context,
    older: Annotated[str, typer.Argument(help="The earlier version, R@.")],
    newer: Annotated[str, typer.Argument(help="The later version, R@.")],
) -> None:
    """Members added and removed going from one version to another."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        added, removed = regions_service.snapshot_diff(project, older, newer)
    for line in render.diff_lines(added, removed):
        typer.echo(line)


# --- Leads, hypotheses and model cut-offs (slice 6, plan H-C) ------------------------------


@leads_app.command("list")
def leads_list_cmd(
    ctx: typer.Context,
    state_: Annotated[
        list[str] | None,
        typer.Option("--state", help="open, promoted, parked or discarded; repeat for more."),
    ] = None,
) -> None:
    """Leads with their triggers and the prior failures they were shown; the default is all."""
    chosen = state_ or ["open", "promoted", "parked", "discarded"]
    for name in chosen:
        if name not in ("open", "promoted", "parked", "discarded"):
            _fail(f"--state {name!r}: expected open, promoted, parked or discarded", 2)
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        views = leads_service.list_leads(project, states=chosen)  # type: ignore[arg-type]
    for line in render.lead_lines(views):
        typer.echo(line)


def _decide_lead_cmd(
    ctx: typer.Context,
    lead: str,
    decision: Literal["promote", "park", "discard"],
    reason: str | None = None,
    note: str | None = None,
) -> None:
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        try:
            why = None if reason is None else DiscardReason(reason)
        except ValueError:
            choices = ", ".join(r.value for r in DiscardReason)
            _fail(f"--reason {reason!r}: expected one of {choices}", 2)
        leads_service.decide_lead(project, project.human_actor(), lead, decision, why, note)
    typer.echo(
        f"{ {'promote': 'promoted', 'park': 'parked', 'discard': 'discarded'}[decision] } {lead}"
    )


@leads_app.command("promote")
def leads_promote_cmd(
    ctx: typer.Context, lead: Annotated[str, typer.Argument(help="A lead id, led_.")]
) -> None:
    """Promote a lead so that a hypothesis may be drafted from it."""
    _decide_lead_cmd(ctx, lead, "promote")


@leads_app.command("park")
def leads_park_cmd(
    ctx: typer.Context, lead: Annotated[str, typer.Argument(help="A lead id, led_.")]
) -> None:
    """Park a lead; it stays in the log and shows as a prior for later leads."""
    _decide_lead_cmd(ctx, lead, "park")


@leads_app.command("discard")
def leads_discard_cmd(
    ctx: typer.Context,
    lead: Annotated[str, typer.Argument(help="A lead id, led_.")],
    reason: Annotated[
        str,
        typer.Option(
            "--reason",
            help="duplicate, prior-failure, out-of-scope, infeasible, not-falsifiable or other.",
        ),
    ],
    note: Annotated[str | None, typer.Option("--note", help="Required for `other`.")] = None,
) -> None:
    """Discard a lead with a reason; nothing is deleted."""
    _decide_lead_cmd(ctx, lead, "discard", reason, note)


@hypotheses_app.command("list")
def hypotheses_list_cmd(
    ctx: typer.Context,
    state_: Annotated[
        list[str] | None,
        typer.Option(
            "--state",
            help="draft, reviewed, registered, evaluated, abandoned or superseded; repeat.",
        ),
    ] = None,
) -> None:
    """Hypotheses with their versions and computed states."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        views = hypotheses_service.list_hypotheses(project, states=state_)
    for line in render.hypothesis_lines(views):
        typer.echo(line)


@hypotheses_app.command("show")
def hypotheses_show_cmd(
    ctx: typer.Context, hypothesis: Annotated[str, typer.Argument(help="A hypothesis id, hyp_.")]
) -> None:
    """One hypothesis: the falsifier sentence, state, flags and autonomy label."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        view = hypotheses_service.hypothesis_view(project, hypothesis)
    if view is None:
        _fail(f"unknown hypothesis {hypothesis}", 1)
    for line in render.hypothesis_detail_lines(view):
        typer.echo(line)


@hypotheses_app.command("register")
def hypotheses_register_cmd(
    ctx: typer.Context, hypothesis: Annotated[str, typer.Argument(help="A hypothesis id, hyp_.")]
) -> None:
    """Register a reviewed hypothesis and freeze its version (a human act)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        hypotheses_service.register_hypothesis(project, project.human_actor(), hypothesis)
        view = hypotheses_service.hypothesis_view(project, hypothesis)
    typer.echo(f"registered {hypothesis} {view.h_version if view else ''}".rstrip())


@hypotheses_app.command("abandon")
def hypotheses_abandon_cmd(
    ctx: typer.Context,
    hypothesis: Annotated[str, typer.Argument(help="A hypothesis id, hyp_.")],
    reason: Annotated[
        str,
        typer.Option(
            "--reason",
            help="no-runnable-code, budget-exhausted, infeasible, data-unavailable or other.",
        ),
    ],
    note: Annotated[str, typer.Option("--note", help="Why, in at most 300 characters.")],
) -> None:
    """Abandon a hypothesis with a reason (a human act); it stays in the log."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        try:
            why = AbandonReason(reason)
        except ValueError:
            choices = ", ".join(r.value for r in AbandonReason)
            _fail(f"--reason {reason!r}: expected one of {choices}", 2)
        hypotheses_service.abandon_hypothesis(project, project.human_actor(), hypothesis, why, note)
    typer.echo(f"abandoned {hypothesis}")


@hypotheses_app.command("conclude")
def hypotheses_conclude_cmd(
    ctx: typer.Context,
    hypothesis: Annotated[str, typer.Argument(help="A hypothesis id, hyp_.")],
    text_: Annotated[
        str, typer.Option("--text", help="Your reading of the outcome, at most 1,200 characters.")
    ],
) -> None:
    """Add a conclusion, labelled as interpretation, to an evaluated hypothesis (a human act)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        hypotheses_service.conclude_hypothesis(project, project.human_actor(), hypothesis, text_)
    typer.echo(f"concluded {hypothesis}")


@models_app.command("cutoff")
def models_cutoff_cmd(
    ctx: typer.Context,
    model: Annotated[str, typer.Argument(help="The model name as agents report it.")],
    cutoff: Annotated[str, typer.Argument(help="Training cut-off, YYYY-MM-DD.")],
    source: Annotated[
        str, typer.Option("--source", help="Where the cut-off is stated (a card, a page).")
    ],
) -> None:
    """Declare a model's training cut-off (R-53); the latest declaration per model wins."""
    try:
        day = date.fromisoformat(cutoff)
    except ValueError:
        _fail(f"cutoff {cutoff!r}: expected YYYY-MM-DD", 2)
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        hypotheses_service.declare_cutoff(project, project.human_actor(), model, day, source)
    typer.echo(f"declared {model} {day.isoformat()}")

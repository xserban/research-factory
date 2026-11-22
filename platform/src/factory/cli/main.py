"""The `factory` command: parse arguments, call a service, format output. No business logic here."""

import json
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn, TypeVar, cast

import click
import typer
from pydantic import BaseModel, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from factory.cli import appraisal_render, evidence_render, portfolio_render, render
from factory.cli.activity import activity_cmd
from factory.cli.admin import member_app, token_app, user_app
from factory.cli.answers import answers_app
from factory.cli.chat import chat_app
from factory.cli.costs import costs_app
from factory.cli.dashboard import dashboard_app
from factory.cli.decisions import decide_app
from factory.cli.develop import develop_app
from factory.cli.feed import feed_app
from factory.cli.files import files_app
from factory.cli.hub import hub_app
from factory.cli.ledger import budget_app, ledger_cmd
from factory.cli.library import library_app
from factory.cli.manuscripts import manuscript_app
from factory.cli.organisation import consolidation_app, labels_app, terms_app
from factory.cli.pages import pages_app
from factory.cli.queue import queue_app
from factory.cli.resume import resume_cmd
from factory.cli.runs import adopt_cmd
from factory.cli.screen_check import screen_check_app
from factory.cli.sheets import sheets_app
from factory.cli.site import site_app
from factory.cli.taxonomy import mine_request_cmd, taxonomy_app, work_layers_app
from factory.cli.team import (
    project_app,
    protocol_amend_cmd,
    protocol_deviation_cmd,
    protocol_record_cmd,
    review_app,
    workspace_cmd,
)
from factory.cli.tour import tour_cmd
from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.document.optional import converter_infos, override_registry
from factory.document.registry import default_converters
from factory.errors import (
    FactoryError,
    FactoryValidationError,
    ProjectNotFoundError,
    ValidationIssue,
)
from factory.events.envelope import Actor
from factory.imports.model import ImportFormat, ImportRole
from factory.index.index import IndexHeldError
from factory.lineage.graph import GraphFilter
from factory.living.digest_render import to_json as digest_json
from factory.living.digest_render import to_markdown as digest_markdown
from factory.mcp.conventions import parse_routes
from factory.mcp.http import build_http_app
from factory.mcp.server import run
from factory.model import lineage as lineage_model
from factory.model.appraisal import Answer as AppraisalAnswer
from factory.model.chase import ChaseDirection
from factory.model.conclusions import BasisRef, Predicate
from factory.model.curation import CurationDecision
from factory.model.directions import Conditions, DirectionReason
from factory.model.drafts import AuditLabel, DraftKind, SentenceClass, SupportSpan, Verdict
from factory.model.experiments import DeviationKind, ExperimentDesign
from factory.model.extraction import ExtractedRowInput, MinerScope
from factory.model.fulltext import SourceDecision
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
from factory.model.lead_engine import DEFAULT_ORDER, SOURCES
from factory.model.notices import AssessmentDecision
from factory.model.project import RigorMode
from factory.model.protocol import ScreeningStage
from factory.model.references import Decision, Direction, LayerSchemeRecorded, LinkState
from factory.model.regions import Facet, RegionKind
from factory.model.screening import Channel, HumanRecordFile, HumanScreeningItem, PassLabel
from factory.model.watch import CycleStatus
from factory.model.work import ProvenanceMethod
from factory.regions.rules import MemberType, RuleSet
from factory.services import agent_view as agent_view_service
from factory.services import agreement as agreement_service
from factory.services import appraisal_judgements as appraisal_service
from factory.services import appraisal_report as appraisal_report_service
from factory.services import audit as audit_service
from factory.services import benchmark_ledger as ledger_service
from factory.services import briefing as briefing_service
from factory.services import calibration as calibration_service
from factory.services import card_import, pubmed_slices, region_adoption
from factory.services import cards as cards_service
from factory.services import chase as chase_service
from factory.services import check as check_service
from factory.services import concepts as concepts_service
from factory.services import conclusions as conclusions_service
from factory.services import contributions as contributions_service
from factory.services import conversion_coverage as conversion_coverage_service
from factory.services import core_works as core_works_service
from factory.services import coverage as coverage_service
from factory.services import curation as curation_service
from factory.services import dedup as dedup_service
from factory.services import digest as digest_service
from factory.services import directions as directions_service
from factory.services import discovery as discovery_service
from factory.services import document_convert as document_convert_service
from factory.services import document_read as document_read_service
from factory.services import draft_audit as draft_audit_service
from factory.services import draft_release as draft_release_service
from factory.services import draft_verify as draft_verify_service
from factory.services import drafts as drafts_service
from factory.services import evaluation as evaluation_service
from factory.services import evaluation_view as evaluation_view_service
from factory.services import evidence as evidence_service
from factory.services import evidence_report as evidence_report_service
from factory.services import experiments as experiments_service
from factory.services import export_works as export_works_service
from factory.services import exports as exports_service
from factory.services import extraction as extraction_service
from factory.services import extraction_agreement as extraction_agreement_service
from factory.services import extraction_audit as extraction_audit_service
from factory.services import finders as findings_service
from factory.services import flow_ledger as flow_ledger_service
from factory.services import flow_query as flow_query_service
from factory.services import flow_skipped as flow_skipped_service
from factory.services import fulltext as fulltext_service
from factory.services import fulltext_import as fulltext_import_service
from factory.services import fulltext_status as fulltext_status_service
from factory.services import gates as gates_service
from factory.services import grey as grey_service
from factory.services import horizon as horizon_service
from factory.services import human_pass as human_pass_service
from factory.services import hypotheses as hypotheses_service
from factory.services import ideas as ideas_service
from factory.services import import_admit as import_admit_service
from factory.services import import_attach as import_attach_service
from factory.services import import_describe as import_describe_service
from factory.services import import_resolve as import_resolve_service
from factory.services import imports as imports_service
from factory.services import inbox as inbox_service
from factory.services import inbox_watch as inbox_watch_service
from factory.services import interpretations as interpretations_service
from factory.services import lab_pack as lab_pack_service
from factory.services import labels as labels_service
from factory.services import leads as leads_service
from factory.services import lineage as graph_service
from factory.services import matching as matching_service
from factory.services import methods as methods_service
from factory.services import mine_reopen as mine_reopen_service
from factory.services import miner_add as miner_add_service
from factory.services import miner_gold as miner_gold_service
from factory.services import miner_report as miner_report_service
from factory.services import miners as miners_service
from factory.services import mining as mining_service
from factory.services import notices as notices_service
from factory.services import onion as onion_service
from factory.services import organisation_export as organisation_export_service
from factory.services import outline as outline_service
from factory.services import passage_index as passage_index_service
from factory.services import passage_vectors as passage_vectors_service
from factory.services import performance as performance_service
from factory.services import portfolio as portfolio_service
from factory.services import prisma as prisma_service
from factory.services import prisma_update as prisma_update_service
from factory.services import project as project_service
from factory.services import properties as properties_service
from factory.services import protocol as protocol_service
from factory.services import question as question_service
from factory.services import ranking as ranking_service
from factory.services import ranking_model as ranking_model_service
from factory.services import reanchor as reanchor_service
from factory.services import reference_layers as layers_service
from factory.services import reference_resolve as reference_resolve_service
from factory.services import references as references_service
from factory.services import regions as regions_service
from factory.services import relations as relations_service
from factory.services import reproduction as reproduction_service
from factory.services import screening as screening_service
from factory.services import seeds as seeds_service
from factory.services import selection as selection_service
from factory.services import shared_mining as shared_mining_service
from factory.services import snapshots as snapshot_service
from factory.services import snowball as snowball_service
from factory.services import suggestions as suggestions_service
from factory.services import technique_graph as technique_service
from factory.services import trace as trace_service
from factory.services import version_pairs as version_pairs_service
from factory.services import versions as versions_service
from factory.services import view_coverage as view_coverage_service
from factory.services import views as views_service
from factory.services import watch as watch_service
from factory.services import xruns as xruns_service
from factory.services.access import authorize_command, authorize_export_works, full_view_allowed
from factory.services.access_log import admin_call, audited, os_login
from factory.services.cli_access import authorise_root_command, server_root
from factory.services.commit import commit_hosted
from factory.services.context import Principal, Project, list_projects, open_project
from factory.services.extraction_agreement import Choice
from factory.services.gate_status import gates_status
from factory.services.lead_candidates import lead_candidates as lead_candidates_service
from factory.services.lead_queue import lead_queue as lead_queue_service
from factory.services.lead_stats import lead_stats as lead_stats_service
from factory.services.living_hooks import DEFAULT_HOOKS, make_status_hook
from factory.services.modules.listing import module_rows
from factory.services.notices import NoticeCheckSummary
from factory.services.project import ScreeningStatus
from factory.services.search import list_works
from factory.services.serve_http import serve_http_issues
from factory.services.server_check import server_check
from factory.services.server_init import init_server
from factory.services.xrun_accounting import baseline_verdicts
from factory.sources.fulltext.registry import default_routes
from factory.sources.registry import default_sources, lookup_sources, status_sources
from factory.views import render as views_render
from factory.views.briefing_render import briefing_markdown


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
protocol_app = typer.Typer(
    name="protocol",
    help="Read the protocol; record, amend it or declare a deviation (human); confirm PRESS.",
    no_args_is_help=True,
)
question_app = typer.Typer(name="question", help="Read the question.", no_args_is_help=True)
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
dedup_app = typer.Typer(
    name="dedup", help="Find duplicate works, list merges and revert one.", no_args_is_help=True
)
rank_app = typer.Typer(
    name="rank",
    help="Order the records still to be screened by similarity to the development seeds.",
    no_args_is_help=True,
)
passages_app = typer.Typer(
    name="passages",
    help="Passage vectors for meaning-based search: embed and status (IDEA-102).",
    no_args_is_help=True,
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
miner_calibrate_app = typer.Typer(
    name="calibrate",
    help="Calibrate an agent-authored miner: draw the sample, record the gold labels.",
    no_args_is_help=True,
)
miner_app.add_typer(miner_calibrate_app)
mine_app = typer.Typer(
    name="mine",
    help="Mining with registered miners: unit status, agreement, resolution and the audit.",
    no_args_is_help=True,
)
shared_app = typer.Typer(
    name="shared",
    help="The shared mining store: a rebuildable projection across the projects of this root.",
    no_args_is_help=True,
)
mine_audit_app = typer.Typer(
    name="audit",
    help="Audit a registered miner's agreed values: sample, label, report.",
    no_args_is_help=True,
)
mine_app.add_typer(mine_audit_app)
contributions_app = typer.Typer(
    name="contributions",
    help="Contribution items: status, list, agreement, resolution and the audit.",
    no_args_is_help=True,
)
contributions_audit_app = typer.Typer(
    name="audit", help="Sample, label and report the contribution audit.", no_args_is_help=True
)
contributions_app.add_typer(contributions_audit_app)
appraisal_app = typer.Typer(
    name="appraisal",
    help="Per-paper appraisal: status, sheet, agreement, judgement items and the audit.",
    no_args_is_help=True,
)
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
    help="Hypotheses: list, show, register, evaluate, abandon and conclude (human).",
    no_args_is_help=True,
)
experiments_app = typer.Typer(
    name="experiments",
    help="Experiment designs: list, show, freeze, unlock, deviation, accept-baseline (human).",
    no_args_is_help=True,
)
runs_app = typer.Typer(
    name="runs",
    help="Experiment runs: list and record results from a runner's file (human or runner).",
    no_args_is_help=True,
)
directions_app = typer.Typer(
    name="directions",
    help="Failed directions: close one that never became a hypothesis (human).",
    no_args_is_help=True,
)
draft_app = typer.Typer(
    name="draft",
    help="Drafts written from verified material: create, list, show, write, withdraw.",
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
technique_app = typer.Typer(
    name="technique",
    help="The landscape of approaches (techniques) read from the technique miners: exploratory, "
    "derived at read time, never evidence.",
    no_args_is_help=True,
)
view_app = typer.Typer(
    name="view",
    help="Read-only views over the log: onion rings, coverage map, group timeline and horizon.",
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
    help="Bibliography, PRISMA diagram, RO-Crate and nanopublications, from the events.",
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
grey_app = typer.Typer(
    name="grey",
    help="Grey literature: capture declared web pages, log reported searches and contacts.",
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
curation_app = typer.Typer(
    name="curation",
    help="Curation proposals made from audit findings: list lessons and proposals, decide.",
    no_args_is_help=True,
)
scheme_app = typer.Typer(
    name="scheme", help="The researcher's reference-layer scheme.", no_args_is_help=True
)
layers_app = typer.Typer(
    name="layers",
    help="Reference layers: status, the calibration sample, the researcher's labels.",
    no_args_is_help=True,
)
references_app.add_typer(scheme_app)
references_app.add_typer(layers_app)
app.add_typer(curation_app)
app.add_typer(references_app)
snowball_core_app = typer.Typer(
    name="core",
    help="Core works: the works a forward snowball round may start from (a researcher's mark).",
    no_args_is_help=True,
)
snowball_app.add_typer(snowball_core_app)
app.add_typer(snowball_app)
app.add_typer(seeds_app)
app.add_typer(watch_app)
app.add_typer(living_app)
app.add_typer(conclusions_app)
app.add_typer(notices_app)
app.add_typer(versions_app)
app.add_typer(inbox_app)
app.add_typer(grey_app)
app.add_typer(report_app)
app.add_typer(export_app)
app.add_typer(protocol_app)
app.add_typer(question_app)
app.add_typer(calibrate_app)
app.add_typer(screen_app)
app.add_typer(audit_app)
app.add_typer(gate_app)
app.add_typer(search_app)
app.add_typer(dedup_app)
app.add_typer(rank_app)
app.add_typer(passages_app)
app.add_typer(fulltext_app)
app.add_typer(library_app)
app.add_typer(feed_app)
app.add_typer(document_app)
app.add_typer(extract_app)
app.add_typer(miner_app)
app.add_typer(mine_app)
app.add_typer(shared_app)
app.add_typer(contributions_app)
app.add_typer(appraisal_app)
app.add_typer(relations_app)
app.add_typer(ideas_app)
app.add_typer(vocabulary_app)
app.add_typer(cards_app)
app.add_typer(finders_app)
app.add_typer(contradictions_app)
app.add_typer(leads_app)
app.add_typer(hypotheses_app)
app.add_typer(models_app)
app.add_typer(directions_app)
app.add_typer(experiments_app)
app.add_typer(runs_app)
runs_app.command("adopt")(adopt_cmd)
app.add_typer(draft_app)
app.add_typer(manuscript_app)
app.add_typer(decide_app)
app.add_typer(dashboard_app)
app.add_typer(site_app)
app.add_typer(hub_app)
app.add_typer(costs_app)
app.add_typer(pages_app)
app.add_typer(sheets_app)
app.add_typer(answers_app)
app.add_typer(chat_app)
app.add_typer(files_app)
app.add_typer(develop_app)
app.add_typer(screen_check_app)
app.add_typer(taxonomy_app)
app.add_typer(work_layers_app)
mine_app.command("request")(mine_request_cmd)
app.add_typer(graph_app)
app.add_typer(technique_app)
app.add_typer(view_app)
app.add_typer(interpretations_app)
app.add_typer(concepts_app)
app.add_typer(concept_links_app)
app.add_typer(regions_app)
app.add_typer(labels_app)
app.add_typer(terms_app)
app.add_typer(consolidation_app)
app.add_typer(import_app)
server_app = typer.Typer(name="server", help="The lab server.", no_args_is_help=True)
app.add_typer(server_app)
app.add_typer(user_app)
app.add_typer(token_app)
app.add_typer(member_app)
app.add_typer(project_app)
app.add_typer(review_app)
protocol_app.command("record")(protocol_record_cmd)
protocol_app.command("amend")(protocol_amend_cmd)
protocol_app.command("deviation")(protocol_deviation_cmd)
app.command("tour")(tour_cmd)
app.command("workspace")(workspace_cmd)
app.command("ledger")(ledger_cmd)
app.add_typer(queue_app)
app.command("resume")(resume_cmd)
app.command("activity")(activity_cmd)
app.add_typer(budget_app)


_M = TypeVar("_M", bound=BaseModel)
_JSON = Annotated[bool, typer.Option("--json", help="Print the report model as JSON.")]
_AS_COMMANDS = frozenset({"server", "user", "token", "member"})


@dataclass
class CliState:
    settings: Settings
    project: str | None
    session: str
    clock: Clock
    as_user: str | None = None
    tool: str = ""
    """The running command as `TOOL_PERMISSIONS` names it, as `cli:<group> <command>`."""


def _state(ctx: typer.Context) -> CliState:
    state = ctx.obj
    if not isinstance(state, CliState):
        raise RuntimeError("CLI state missing; the root callback did not run")
    names: list[str] = []
    current: Any = ctx
    while current.parent is not None:
        names.append(str(current.info_name))
        current = current.parent
    state.tool = "cli:" + " ".join(reversed(names))
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
    except IndexHeldError as exc:  # another code line holds the index (IDEA-62)
        _fail(str(exc), 1)


@contextmanager
def _engine_errors() -> Iterator[None]:
    """`_reporting_errors` for the lead engine commands: a refusal also carries the exploratory
    notice on stderr, as the MCP refusals do."""
    from factory.model.lead_engine import NOTICE

    try:
        with _reporting_errors():
            yield
    except typer.Exit as exc:
        if exc.exit_code != 0:
            typer.echo(f"EXPLORATORY: {NOTICE}", err=True)
        raise


def _authorized(state: CliState, project: Project) -> Project:
    """`project`, once the running command is allowed on it (slice 5 ruling 10)."""
    with (
        _reporting_errors(),
        audited(
            state.settings,
            project.principal,
            session=state.session,
            clock=state.clock,
            tool=state.tool,
            project=project.paths.slug,
        ),
    ):
        authorize_command(project, project.principal, state.tool)
    return project


def _full_view(project: Project) -> bool:
    """Whether this person reads the full view; if not, the agent view (slice 5 ruling 20)."""
    return full_view_allowed(project, project.principal)


def _resolve_project(state: CliState) -> Project:
    """The project of this command, authorised; refuses a command barred while screening a pass."""
    project = _authorized(state, _selected_project(state))
    context = click.get_current_context(silent=True)
    command = "" if context is None else " ".join(context.command_path.split()[1:])
    with _reporting_errors():
        human_pass_service.require_command_allowed(project, command)
    return project


def _selected_project(state: CliState) -> Project:
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
    as_user: Annotated[
        str | None,
        typer.Option("--as", help="The lab admin acting, when not the OS login (admin only)."),
    ] = None,
) -> None:
    clock = SystemClock()
    with _reporting_errors():
        settings = Settings.load(root=root)
    session = IdGenerator(clock).ulid()
    if as_user is not None and ctx.invoked_subcommand not in _AS_COMMANDS:
        # Any other command would act as the configured user, and a human act is permanent.
        with (
            _reporting_errors(),
            audited(
                settings,
                Principal.local(settings, Channel.CLI),
                session=session,
                clock=clock,
                tool=f"cli:{ctx.invoked_subcommand}",
                login=os_login(),
            ),
        ):
            raise FactoryValidationError(
                [ValidationIssue("as", "--as is for the server, user, token and member commands")]
            )
    ctx.obj = CliState(
        settings=settings,
        project=project,
        session=session,
        clock=clock,
        as_user=as_user,
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
        authorise_root_command(state.settings, "cli:init", session=state.session, clock=state.clock)
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
    mine: Annotated[
        bool,
        typer.Option("--mine", help="Show only the pending decisions routed to you."),
    ] = False,
) -> None:
    """Show a project's rigor mode, event counts and task queue."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = (
            project_service.project_status(project)
            if _full_view(project)
            else agent_view_service.agent_status(project)
        )
        if mine and report.human is not None:
            report = report.model_copy(
                update={
                    "human": report.human.model_copy(
                        update={
                            "items": [
                                i for i in report.human.items if i.assignee == project.settings.user
                            ]
                        }
                    )
                }
            )
    if as_json:
        typer.echo(report.model_dump_json())
        return
    typer.echo(f"project: {report.slug}")
    typer.echo(f"rigor mode: {report.rigor_mode.value}")
    typer.echo(f"stage: {report.stage.value if report.stage else 'unknown'}")
    typer.echo(f"events: {report.events_total}")
    for blocked in report.blocking:
        typer.echo(f"BLOCKING next step: {blocked}")
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
            who = "" if item.assignee is None else f" [{item.assignee}]"
            typer.echo(f"  {item.gate.value}{stage}{who}: {item.count} \u2014 {item.command}")


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


@app.command("briefing")
def briefing_cmd(
    ctx: typer.Context,
    agent: Annotated[
        bool, typer.Option("--agent", help="Print the agent context pack; records nothing.")
    ] = False,
    format_: Annotated[
        str | None, typer.Option("--format", help="md or json; --agent is json only.")
    ] = None,
    out: Annotated[Path | None, typer.Option("--out", help="Write to this file.")] = None,
) -> None:
    """The project briefing, complete (the researcher's variant): a reading path for a person
    joining mid-way. Writes no event; only the MCP tool `briefing_get` records a served pack."""
    state = _state(ctx)
    with _reporting_errors():
        chosen = format_ or ("json" if agent else "md")
        if chosen not in ("md", "json") or (agent and chosen != "json"):
            raise FactoryValidationError(
                [ValidationIssue("format", "must be md or json; --agent is json only")]
            )
        project = _resolve_project(state)
        if agent:
            body = briefing_service.agent_pack(project)
        else:
            built = briefing_service.build_briefing(project)
            body = views_service.to_json(built) if chosen == "json" else briefing_markdown(built)
        _emit_view(body, out)


@app.command("performance")
def performance_cmd(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
) -> None:
    """Measured figures per role, model and skill version. CLI only: no agent tool shows them.
    A figure below the sample floor prints its count, not a rate. Writes no event."""
    state = _state(ctx)
    with _reporting_errors():
        report = performance_service.performance(_resolve_project(state))
    if as_json:
        typer.echo(views_service.to_json(report), nl=False)
        return
    for line in performance_service.lines(report):
        typer.echo(line)


@app.command("pack")
def pack_cmd(
    ctx: typer.Context,
    since: Annotated[
        str, typer.Option("--since", help="`last` (the last recorded digest) or an event id.")
    ] = "last",
    out: Annotated[Path | None, typer.Option("--out", help="Write the pack to this file.")] = None,
    handover: Annotated[
        bool, typer.Option("--handover", help="Add the open tasks and what each gate needs.")
    ] = False,
) -> None:
    """The weekly meeting pack, or with --handover a handover note. Counts and titles only;
    writes no event."""
    state = _state(ctx)
    with _reporting_errors():
        built = lab_pack_service.lab_pack(_resolve_project(state), since, handover=handover)
    _emit_view(lab_pack_service.pack_markdown(built), out)


@curation_app.command("lessons")
def curation_lessons_cmd(ctx: typer.Context) -> None:
    """The computed lessons proposals can answer (counts only)."""
    state = _state(ctx)
    with _reporting_errors():
        found = curation_service.lessons(_resolve_project(state))
    for lesson in found:
        typer.echo(f"{lesson.lesson_id}  {lesson.subject}  n={lesson.count}")
    if not found:
        typer.echo("no lessons")


@curation_app.command("list")
def curation_list_cmd(
    ctx: typer.Context,
    open_only: Annotated[bool, typer.Option("--open", help="Undecided proposals only.")] = False,
) -> None:
    """The proposals, rejected ones included."""
    state = _state(ctx)
    with _reporting_errors():
        found = curation_service.proposals(_resolve_project(state), open_only=open_only)
    for p in found:
        label = "open" if p.decision is None else p.decision.value
        typer.echo(f"{p.cur_id}  {p.kind.value}  {label}  by {p.proposer}")
        typer.echo(f"  {p.text}")
        typer.echo(f"  lessons: {', '.join(p.lessons)}")
    if not found:
        typer.echo("no proposals")


@curation_app.command("decide")
def curation_decide_cmd(
    ctx: typer.Context,
    cur_id: Annotated[str, typer.Argument(help="The proposal.")],
    decision: Annotated[str, typer.Argument(help="accepted or rejected.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why.")],
    amendment_event: Annotated[
        str | None,
        typer.Option("--amendment-event", help="The protocol.amended event that carried it out."),
    ] = None,
) -> None:
    """Accept or reject a proposal. Acceptance changes no protocol: amend it with protocol amend."""
    state = _state(ctx)
    try:
        choice = CurationDecision(decision)
    except ValueError:
        _fail("decision: must be one of: accepted, rejected", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        event_id = curation_service.decide_proposal(
            project,
            project.human_actor(),
            cur_id,
            choice,
            rationale=rationale,
            amendment_event=amendment_event,
        )
    typer.echo(f"recorded {event_id}")


@app.command("suggest")
def suggest_cmd(
    ctx: typer.Context,
    cap: Annotated[int, typer.Option("--cap", help="At most this many suggestions.")] = 100,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Computed hints from the other projects under the root, each with its reason. Read-only:
    nothing is written in any project; add a work to the inbox yourself to act on one."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        found = suggestions_service.suggestions(project, cap=cap)
    if as_json:
        typer.echo(json.dumps([s.model_dump(mode="json") for s in found], indent=2))
        return
    for item in found:
        typer.echo(f"{item.from_project}\t{item.signal}\t{item.work}\t{item.identifier or '-'}")
        typer.echo(f"  {item.reason}")
    if not found:
        typer.echo("no suggestions")


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
    if not cal.required:  # the preset's enforcement is off: say so, not only "gate not required"
        lines.append("calibration not required in this mode (the preset does not enforce it)")
    for label, progress in screening.passes.items():
        if progress.queued is None:
            lines.append(f"pass {label}: not opened")
            continue
        rates = cal.per_pass.get(label)  # empty in the agent view
        sensitivity = _rate(None if rates is None else rates.sensitivity)
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
    if screening.cannot_assess_open:
        counts = ", ".join(f"{k} {v}" for k, v in screening.cannot_assess_open.items())
        lines.append(f"cannot-assess to resolve: {counts}")
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
    page: Annotated[
        bool,
        typer.Option(
            "--page", help="Treat a link with no identifier as a publisher page (citation_doi)."
        ),
    ] = False,
) -> None:
    """Capture links as inbox items. Offline; an unsupported link is reported and not written."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        items = [inbox_service.LinkInput(link, note=note, page=page) for link in links]
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
        page = inbox_service.list_items(
            project, status=status, cursor=cursor, prioritised_first=True
        )
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


@inbox_app.command("prioritise")
def inbox_prioritise(
    ctx: typer.Context,
    item_id: Annotated[str, typer.Argument(help="An open inbox item.")],
    clear: Annotated[bool, typer.Option("--clear", help="Remove the mark instead.")] = False,
) -> None:
    """Mark an open item to look at first (a hint for this listing only; screening order is
    unaffected)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        wrote = inbox_service.prioritise(
            project, project.human_actor(), item_id, prioritised=not clear
        )
    word = "cleared" if clear else "prioritised"
    typer.echo(f"{word} {item_id}" if wrote else f"{item_id} already {word}")


@grey_app.command("capture")
def grey_capture(
    ctx: typer.Context,
    url: Annotated[str, typer.Argument(help="An http or https page or PDF.")],
    source: Annotated[
        str, typer.Option("--source", help="The declared `website` target in grey_sources.")
    ],
    title: Annotated[str, typer.Option("--title", help="The title the work is recorded under.")],
    deviation: Annotated[
        str | None,
        typer.Option("--deviation", help="A recorded deviation that authorises the capture."),
    ] = None,
) -> None:
    """Fetch a page once into the library and record it as a grey `website` work."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        result = grey_service.capture_url(
            project,
            project.human_actor(),
            url,
            source_id=source,
            title=title,
            deviation_id=deviation,
        )
    typer.echo(f"captured {result.work_id} ({result.media_type}, {result.sha256})")
    typer.echo(
        f"document {result.document_id}"
        if result.document_id
        else "these bytes were already captured for the work"
    )


@grey_app.command("contact")
def grey_contact(
    ctx: typer.Context,
    target: Annotated[
        str, typer.Option("--target", help="The declared `expert-contact` target (a role label).")
    ],
    summary: Annotated[str, typer.Option("--summary", help="What was asked and what came back.")],
    on: Annotated[
        str | None, typer.Option("--on", help="ISO date or timestamp; today when omitted.")
    ] = None,
    url: Annotated[list[str] | None, typer.Option("--url", help="A link the contact gave.")] = None,
) -> None:
    """Log an expert contact. The log holds a label and a summary, never an address."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        when = project.clock.now() if on is None else datetime.fromisoformat(on)
        if when.tzinfo is None:
            when = when.replace(tzinfo=project.clock.now().tzinfo)
        outcome = grey_service.log_contact(
            project,
            project.human_actor(),
            target=target,
            contacted_on=when,
            summary=summary,
            urls=url or (),
        )
    typer.echo(f"logged {outcome.record_id}")
    for link in outcome.unparsed:
        typer.echo(f"not an identifier link, not offered: {link}", err=True)


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
    if summary.tolerated_pending:
        typer.echo(
            f"went ahead without {len(summary.tolerated_pending)} pending work(s) "
            f"(pending_tolerance): {', '.join(summary.tolerated_pending)}"
        )


@search_app.command("slice")
def search_slice_cmd(
    ctx: typer.Context,
    query_id: Annotated[str, typer.Argument(help="The capped pubmed keyword query (qry_...).")],
    run: Annotated[bool, typer.Option("--run", help="Register and run every slice.")] = False,
    first_year: Annotated[int, typer.Option("--first-year", help="First year cut singly.")] = 1900,
    deviation: Annotated[
        str | None, typer.Option("--deviation", help="Deviation (dev_...) that allows the slices.")
    ] = None,
) -> None:
    """Split a capped PubMed query by date; without --run, show the plan and write nothing."""
    state = _state(ctx)
    sources = dict(default_sources())
    with _reporting_errors():
        project = _resolve_project(state)
        if not run:
            plan = pubmed_slices.propose_slices(
                project, query_id, sources=sources, first_year=first_year
            )
            for planned in plan.slices:
                if planned.count:
                    typer.echo(
                        f"{planned.window.start} .. {planned.window.end}  {planned.count}"
                        + ("  over the cap" if planned.over_cap else "")
                    )
            typer.echo(f"{len(plan.runnable)} slices, total {plan.total} of {plan.parent_count}")
            return
        summary = pubmed_slices.run_slices(
            project,
            project.human_actor(),
            query_id,
            sources=sources,
            deviation_id=deviation,
            first_year=first_year,
        )
    typer.echo(
        f"{len(summary.runs)} runs; slice total {summary.report.slice_reported_total}, "
        f"unsplit {summary.report.parent_reported}"
    )
    if summary.report.note:
        typer.echo(summary.report.note)


@protocol_app.command("show")
def protocol_show_cmd(ctx: typer.Context, as_json: _JSON = False) -> None:
    """The current protocol: id, status, PRESS state, amendments and the whole spec."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        view = protocol_service.protocol_view(project)
    if as_json:
        typer.echo(view.model_dump_json())
        return
    for line in render.protocol_view_lines(view):
        typer.echo(line)


@question_app.command("show")
def question_show_cmd(ctx: typer.Context, as_json: _JSON = False) -> None:
    """The current question: its id, the latest raw goal and the spec."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        view = question_service.question_view(project)
    if as_json:
        typer.echo(view.model_dump_json())
        return
    for line in render.question_view_lines(view):
        typer.echo(line)


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
    corpus_only: Annotated[
        bool,
        typer.Option(
            "--corpus-only",
            help="Match entries against the corpus only, asking no external source. Entries "
            "that need a lookup are recorded as source-error; `references re-resolve` asks again.",
        ),
    ] = False,
    lookup_source: Annotated[
        str,
        typer.Option(
            "--source",
            help="Where DOI and title lookups go: crossref (default) or openalex.",
        ),
    ] = "crossref",
) -> None:
    """Extract and resolve the reference lists; default: every included work not yet extracted."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        summary = references_service.extract_references(
            project,
            project.human_actor(),
            work,
            sources={} if corpus_only else dict(lookup_sources()),
            lookup_source=lookup_source,
        )
    for line in render.extract_summary_lines(summary):
        typer.echo(line)


@dedup_app.command("run")
def dedup_run_cmd(ctx: typer.Context) -> None:
    """Reconcile the recorded merges with the cascade; a reverted pair stays apart."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        summary = dedup_service.dedup_run(project)
    typer.echo(
        f"merged {len(summary.created)}, reverted {len(summary.reverted)}, "
        f"unchanged {summary.unchanged}; {summary.canonical} works from {summary.works}"
    )


@rank_app.command("compute")
def rank_compute_cmd(ctx: typer.Context) -> None:
    """Rank the records still to be screened with the local embedding model (decision 116).

    Needs the `ranker` extra and FACTORY_RANKER_MODEL; orders only, excludes nothing."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        event = ranking_service.compute_ranking(project, ranking_model_service.Specter2Embedder())
    typer.echo(
        f"ranked {event.count} records ({event.ranking_id}); model {event.model_id}, "
        f"weights {event.weights_hash[:12]}, {len(event.parameters.references)} reference seeds"
    )


@rank_app.command("show")
def rank_show_cmd(
    ctx: typer.Context,
    top: Annotated[int, typer.Option("--top", min=1, help="How many works to list.")] = 20,
) -> None:
    """The latest ranking: its model and the first works with their scores."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        view = ranking_service.latest_ranking(project, top)
    if view is None:
        typer.echo("no ranking yet; run `factory rank compute`")
        return
    typer.echo(
        f"{view.ranking_id}: {view.count} records; model {view.model_id}, "
        f"weights {view.weights_hash[:12]}, {view.software}"
    )
    for item in view.ranked:
        typer.echo(f"{item.position:>5}  {item.score:.6f}  {item.work_id}")


def _passage_selection(
    layers: list[str] | None, include: list[str] | None, exclude: list[str] | None
) -> selection_service.SelectionSpec:
    def split(values: list[str] | None) -> list[str]:
        return [part for v in values or [] for part in v.split(",") if part]

    return selection_service.SelectionSpec(
        layers=split(layers), include=split(include), exclude=split(exclude)
    )


_LAYERS = Annotated[
    list[str] | None, typer.Option("--layers", help="Layer ids (repeat or comma-separate).")
]
_INCLUDE = Annotated[
    list[str] | None, typer.Option("--include", help="Work ids to add to the selection.")
]
_EXCLUDE = Annotated[
    list[str] | None, typer.Option("--exclude", help="Work ids to remove from the selection.")
]


@passages_app.command("embed")
def passages_embed_cmd(
    ctx: typer.Context,
    layers: _LAYERS = None,
    include: _INCLUDE = None,
    exclude: _EXCLUDE = None,
    prune: Annotated[
        bool,
        typer.Option("--prune", help="Also remove vectors made under any other model key."),
    ] = False,
) -> None:
    """Embed the passages of a selection that lack a vector (SPECTER2, local, resumable).

    Needs the `ranker` extra and FACTORY_RANKER_MODEL. Writes only the passage sidecar. Vectors of
    other model keys are kept unless --prune is given."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        project.index.sync()
        spec = _passage_selection(layers, include, exclude)
        works = selection_service.resolve_selection_cached(project, spec).works
        embedder = passage_vectors_service.default_embedder()
        report = passage_vectors_service.ensure_embedded(
            project,
            works,
            embedder,
            progress=lambda done, total: typer.echo(f"embedded {done}/{total}"),
        )
        pruned = passage_vectors_service.prune_other_keys(project, report.model_key) if prune else 0
    typer.echo(
        f"embedded {report.embedded}, already held {report.reused}, removed {report.removed}, "
        f"missing {report.missing}; key {report.model_key}"
    )
    if prune:
        typer.echo(f"pruned {pruned} vectors of other keys")


@passages_app.command("status")
def passages_status_cmd(
    ctx: typer.Context,
    layers: _LAYERS = None,
    include: _INCLUDE = None,
    exclude: _EXCLUDE = None,
) -> None:
    """Passages of a selection, embedded under the current key, and missing."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        project.index.sync()
        spec = _passage_selection(layers, include, exclude)
        works = selection_service.resolve_selection_cached(project, spec).works
        embedder = passage_vectors_service.default_embedder()
        passage_index_service.ensure_indexed(project, works)
        key = passage_vectors_service.model_key(embedder)
        missing = passage_vectors_service.count_missing(project, works, key)
        total = passage_vectors_service.count_passages(project, works)
    typer.echo(f"passages {total}, embedded {total - missing}, missing {missing}; key {key}")


@dedup_app.command("list")
def dedup_list_cmd(ctx: typer.Context) -> None:
    """Every merge, active and reverted, with its rule, works and any reversal's reason."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        merges = dedup_service.list_merges(project)
    for line in render.merge_lines(merges):
        typer.echo(line)


@dedup_app.command("pairs")
def dedup_pairs_cmd(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", min=1, help="How many candidates to show.")] = 50,
) -> None:
    """Candidate version pairs, best first, for the researcher to rule on."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        found = version_pairs_service.candidates(project, limit=limit)
    for line in render.pair_lines(found):
        typer.echo(line)


@dedup_app.command("pair")
def dedup_pair_cmd(
    ctx: typer.Context,
    work_a: Annotated[str, typer.Argument(help="One work id.")],
    work_b: Annotated[str, typer.Argument(help="The other work id.")],
    decision: Annotated[str, typer.Argument(help="same or different.")],
    rationale: Annotated[
        str, typer.Option("--rationale", help="Why the works are or are not one.")
    ],
) -> None:
    """Record the researcher's ruling on a pair and apply it at once (human only)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        event_id = version_pairs_service.decide_pair(
            project, project.human_actor(), work_a, work_b, decision, rationale
        )
    typer.echo(f"recorded {event_id}")
    typer.echo("dedup applied")


@dedup_app.command("revert")
def dedup_revert_cmd(
    ctx: typer.Context,
    merge: Annotated[str, typer.Argument(help="An active merge id.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the works are not one paper.")],
) -> None:
    """Undo an active merge; the pair stays apart on every later run."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        dedup_service.revert_merge(project, project.human_actor(), merge, reason)
    typer.echo(f"reverted {merge}")


@references_app.command("re-resolve")
def references_re_resolve_cmd(
    ctx: typer.Context,
    work: Annotated[
        list[str] | None, typer.Option("--work", help="A citing work to retry; repeatable.")
    ] = None,
    states: Annotated[
        list[str] | None,
        typer.Option(
            "--state",
            help="An unresolved reason or a link state to retry; repeatable. "
            "Default: source-error.",
        ),
    ] = None,
    only_identifiers: Annotated[
        bool,
        typer.Option(
            "--only-identifiers",
            help="Retry only entries with a DOI or arXiv id (identifier lookup, no title search).",
        ),
    ] = False,
    lookup_source: Annotated[
        str,
        typer.Option(
            "--source",
            help="Where DOI and title lookups go: crossref (default) or openalex.",
        ),
    ] = "crossref",
    layer: Annotated[
        list[str] | None,
        typer.Option(
            "--layer",
            help="Retry only entries whose cited item holds this layer of the latest scheme "
            "(a human label wins over the agent's); repeatable.",
        ),
    ] = None,
    snowball_layers: Annotated[
        bool,
        typer.Option(
            "--snowball-layers",
            help="Retry only entries in the scheme's layers marked snowball.",
        ),
    ] = False,
) -> None:
    """Look up again links whose lookup failed or whose matcher changed; extraction ids stay."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        layers = [*(layer or [])]
        if snowball_layers:
            layers += layers_service.snowball_layer_ids(project)
        summary = references_service.re_resolve(
            project,
            project.human_actor(),
            work_ids=work,
            states=states or ("source-error",),
            sources=dict(lookup_sources()),
            only_identifiers=only_identifiers,
            lookup_source=lookup_source,
            layers=list(dict.fromkeys(layers)) if (layer or snowball_layers) else None,
        )
    for line in render.re_resolve_summary_lines(summary):
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


@scheme_app.command("record")
def references_scheme_record_cmd(
    ctx: typer.Context,
    file: Annotated[
        Path,
        typer.Argument(
            help="A JSON file: {version, layers, inner_sample?: {from_version, draw: {layer: n}}}."
        ),
    ],
) -> None:
    """Record the layer scheme (the researcher's act, before any agent assigns a layer)."""
    state = _state(ctx)
    try:
        scheme = LayerSchemeRecorded.model_validate_json(file.read_text(encoding="utf-8"))
    except OSError as exc:
        _fail(f"{file}: cannot read ({exc})", 1)
    except PydanticValidationError as exc:
        for error in exc.errors():
            where = ".".join(str(p) for p in error["loc"])
            typer.echo(f"{file}{'.' + where if where else ''}: {error['msg']}", err=True)
        raise typer.Exit(1) from None
    with _reporting_errors():
        project = _resolve_project(state)
        result = layers_service.record_scheme(project, project.human_actor(), scheme)
    if result.recorded:
        typer.echo(f"recorded scheme version {result.version} ({result.event_id})")
    else:
        typer.echo(f"scheme version {result.version} already recorded; nothing written")


@layers_app.command("status")
def references_layers_status_cmd(ctx: typer.Context) -> None:
    """Items by assessability, layers per stage, items left and the calibration state."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        result = layers_service.status(project)
    for line in render.layer_status_lines(result):
        typer.echo(line)


def _current_scheme_or_refuse(project: Project) -> LayerSchemeRecorded:
    scheme = layers_service.current_scheme(project)
    if scheme is None:
        raise FactoryValidationError(
            [ValidationIssue("scheme", "no layer scheme is recorded; record one first")]
        )
    return scheme


@layers_app.command("sample")
def references_layers_sample_cmd(ctx: typer.Context) -> None:
    """The calibration sample: key, stratum (`base`, or `inner:<layer>` of the earlier scheme),
    citing count, year (`?` if unknown), `P` for a precursor, whether you have labelled it, and
    the title."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        scheme = _current_scheme_or_refuse(project)
        sample = layers_service.calibration_sample_strata(project, scheme.version)
        labelled = layers_service.researcher_labels(project, scheme.version)
    typer.echo(f"scheme version {scheme.version}; {len(sample)} item(s)")
    for item, stratum in sample:
        mark = "labelled" if item.key in labelled else "-"
        year = "?" if item.year is None else str(item.year)
        pre = "P" if layers_service.is_precursor(item, scheme) else "-"
        typer.echo(
            f"{item.key}\t{stratum}\t{item.citing_count}\t{year}\t{pre}\t{mark}\t{item.title}"
        )


@layers_app.command("label")
def references_layers_label_cmd(
    ctx: typer.Context,
    item: Annotated[
        str | None, typer.Option("--item", help="One item key (non-interactive).")
    ] = None,
    layer: Annotated[str | None, typer.Option("--layer", help="Its layer id.")] = None,
    note: Annotated[str | None, typer.Option("--note", help="An optional note.")] = None,
) -> None:
    """Label calibration items with your own layer. Without --item it asks for each unlabelled
    item in turn (number or id, `s` to skip, `q` to quit); the agent's layer, if any, is shown
    only after you have chosen."""
    state = _state(ctx)
    if (item is None) != (layer is None):
        _fail("give --item and --layer together, or neither", 2)
    if item is None and note is not None:
        _fail("--note needs --item and --layer", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        scheme = _current_scheme_or_refuse(project)
        actor = project.human_actor()
        if item is not None and layer is not None:
            event_id = layers_service.record_label(
                project, actor, item, scheme.version, layer, note
            )
            typer.echo(f"labelled {item} as {layer} ({event_id})")
            return
        labelled = layers_service.researcher_labels(project, scheme.version)
        todo = [
            i
            for i in layers_service.calibration_sample(project, scheme.version)
            if i.key not in labelled
        ]
        ordered = sorted(scheme.layers, key=lambda d: d.ring)
        ids = [d.id for d in ordered]
        typer.echo(f"{len(todo)} item(s) to label under scheme version {scheme.version}")
        for n, entry in enumerate(todo, start=1):
            year = "n.d." if entry.year is None else str(entry.year)
            precursor = ", precursor" if layers_service.is_precursor(entry, scheme) else ""
            typer.echo(
                f"\n[{n}/{len(todo)}] {entry.title} ({year}{precursor}), "
                f"cited {entry.citing_count}x"
            )
            for number, d in enumerate(ordered, start=1):
                typer.echo(f"  {number}. [ring {d.ring}] {d.id}: {d.name}")
            chosen = _ask_layer(ids)
            if chosen == "q":
                break
            if chosen == "s":
                continue
            text = typer.prompt("note (optional)", default="", show_default=False).strip()
            layers_service.record_label(
                project, actor, entry.key, scheme.version, chosen, text or None
            )
            theirs = layers_service.agent_layers(project, "title", scheme.version).get(entry.key)
            typer.echo(f"recorded {chosen}" + ("" if theirs is None else f"; agent chose {theirs}"))


def _ask_layer(ids: list[str]) -> str:
    """A layer id from a number or an id; `s` or `q` pass through. Asks again on bad input."""
    while True:
        answer = str(typer.prompt("layer (number or id, s skip, q quit)")).strip()
        if answer in ("s", "q") and answer not in ids:
            return answer
        if answer in ids:
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(ids):
            return ids[int(answer) - 1]
        typer.echo("not a layer of this scheme", err=True)


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
    decision: Annotated[
        list[str] | None,
        typer.Option(
            "--decision",
            help="A selected plan decision on the subject snowball-<direction>-<round_no>; "
            "pilot and systematic projects need it (the researcher's recorded go-ahead).",
        ),
    ] = None,
) -> None:
    """Record and run a round; pilot and systematic need a selected decision (--decision)."""
    state = _state(ctx)
    parsed = _round_direction(direction)
    with _reporting_errors():
        project = _resolve_project(state)
        result = snowball_service.snowball_round(
            project,
            project.human_actor(),
            parsed,
            sources=dict(default_sources()),
            dry_run=False,
            decision_ids=decision,
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


@snowball_core_app.command("mark")
def snowball_core_mark_cmd(
    ctx: typer.Context,
    work_id: Annotated[str, typer.Argument(help="The work to mark core.")],
    note: Annotated[str | None, typer.Option("--note", help="Why (optional).")] = None,
) -> None:
    """Mark a work core: a forward round with forward_core_only may start from it."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        event_id = core_works_service.mark_core(project, project.human_actor(), work_id, note)
    typer.echo(f"recorded {event_id}")


@snowball_core_app.command("unmark")
def snowball_core_unmark_cmd(
    ctx: typer.Context,
    work_id: Annotated[str, typer.Argument(help="The work to take the mark from.")],
    note: Annotated[str | None, typer.Option("--note", help="Why (optional).")] = None,
) -> None:
    """Take a work's core mark back (a positive seed's work stays core)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        event_id = core_works_service.unmark_core(project, project.human_actor(), work_id, note)
    typer.echo(f"recorded {event_id}")


@snowball_core_app.command("list")
def snowball_core_list_cmd(ctx: typer.Context) -> None:
    """The marked core works and the seeds' works, which are core without a mark."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        marks = core_works_service.core_marks(project)
        seeds = core_works_service.seed_core_works(project)
    for mark in marks:
        typer.echo(f"{mark.work_id}  marked  {mark.note or ''}".rstrip())
    for work in seeds:
        typer.echo(f"{work}  seed")
    if not marks and not seeds:
        typer.echo("no core works")


@server_app.command("check")
def server_check_cmd(ctx: typer.Context) -> None:
    """Check that this root can host projects; exit 1 when it cannot."""
    issues = server_check(_state(ctx).settings)
    for issue in issues:
        typer.echo(f"{issue.field}: {issue.reason}", err=True)
    if issues:
        raise typer.Exit(1)
    typer.echo("ok")


@server_app.command("init")
def server_init_cmd(
    ctx: typer.Context,
    host_id: Annotated[
        str | None, typer.Option("--host-id", help="This machine's host id.")
    ] = None,
    push_url: Annotated[
        list[str] | None,
        typer.Option("--push-url", help="A URL `factory commit --push` may push to; repeatable."),
    ] = None,
) -> None:
    """Make this root a lab server: the lab registry with you as admin, `.server/`, `.gitignore`.

    Push URLs are only ever the ones given here: none is read from a git remote."""
    state = _state(ctx)
    with (
        _reporting_errors(),
        admin_call(
            state.settings,
            state.as_user,
            session=state.session,
            clock=state.clock,
            tool="cli:server init",
        ) as (settings, _),
    ):
        done = init_server(
            settings,
            host_id=host_id,
            push_urls=push_url or (),
            session=state.session,
            clock=state.clock,
        )
    typer.echo(f"host {done.host_id}")
    if done.admin is not None:
        typer.echo(f"registered {done.admin} as lab admin")
    typer.echo(f"{done.push_urls} push URL(s) allowed")


@app.command("commit")
def commit_cmd(
    ctx: typer.Context,
    no_sign: Annotated[
        bool, typer.Option("--no-sign", help="Leave the commit unsigned; signing is the default.")
    ] = False,
    push: Annotated[str | None, typer.Option("--push", help="Remote to push to.")] = None,
) -> None:
    """Commit the new event and text-blob files of the projects hosted here."""
    state = _state(ctx)
    with _reporting_errors():
        if server_root(state.settings):
            authorise_root_command(
                state.settings, "cli:commit", session=state.session, clock=state.clock
            )
        report = commit_hosted(state.settings, sign=not no_sign, push=push)
    for slug, files in sorted(report.projects.items()):
        typer.echo(f"{slug}: {files} files")
    typer.echo(report.commit or "nothing to commit")
    if push is not None and not report.pushed:
        _fail(f"push to {push} failed", 1)


@app.command()
def serve(
    ctx: typer.Context,
    http: Annotated[bool, typer.Option("--http", help="Serve over streamable HTTP.")] = False,
    host: Annotated[str, typer.Option("--host", help="Address to bind (with --http).")] = (
        "127.0.0.1"
    ),
    port: Annotated[int, typer.Option("--port", help="Port to bind (with --http).")] = 8765,
    issuer_url: Annotated[
        str | None, typer.Option("--issuer-url", help="Issuer URL the metadata names.")
    ] = None,
    resource_url: Annotated[
        str | None, typer.Option("--resource-url", help="Public URL of this server.")
    ] = None,
    allowed_host: Annotated[
        list[str] | None,
        typer.Option("--allowed-host", help="A Host header value to accept; repeatable."),
    ] = None,
    insecure_direct: Annotated[
        bool, typer.Option("--insecure-direct", help="Allow a non-loopback bind without TLS.")
    ] = False,
) -> None:
    """Run the MCP server on stdio, or with --http over authenticated streamable HTTP."""
    settings = _state(ctx).settings
    if not http:
        run(settings)
        return
    issues = serve_http_issues(settings, host, insecure_direct=insecure_direct)
    for issue in issues:
        typer.echo(f"{issue.field}: {issue.reason}", err=True)
    if issues:
        raise typer.Exit(1)
    import uvicorn  # the optional `server` extra

    base = f"http://{host}:{port}"
    app_ = build_http_app(
        settings,
        issuer_url=issuer_url or base,
        resource_url=resource_url or base,
        allowed_hosts=[f"{host}:{port}", *(allowed_host or [])],
        allowed_origins=[],
    )
    uvicorn.run(app_, host=host, port=port)


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
    for item in items:
        typer.echo(item)
        if run_stage is ScreeningStage.FULL_TEXT:
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


@screen_app.command("join")
def screen_join(
    ctx: typer.Context,
    pass_label: Annotated[PassLabel, typer.Option("--pass", help="The pass to screen: A or B.")],
    stage: StageOption = StageChoice.TITLE_ABSTRACT,
) -> None:
    """Join a pass as a human screener, once per stage."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        screening_service.join_pass(project, project.human_actor(), pass_label, stage=_stage(stage))
    typer.echo(f"joined pass {pass_label.value} ({_stage(stage).value})")


def _next_batch(project: Project, stage: ScreeningStage) -> tuple[dict[str, Any], Actor]:
    """The next batch of the person's pass as an agent is served it, and the actor of the pass."""
    actor, label = human_pass_service.pass_actor(project, stage)
    served = screening_service.screen_next(project, actor, label, stage=stage)
    view = served.model_dump(mode="json")
    if human_pass_service.served_agent_view(project, project.principal):
        return cast(
            dict[str, Any], agent_view_service.withheld(project, view, include_work_ids=False)
        ), actor
    return view, actor


@screen_app.command("next")
def screen_next_cmd(ctx: typer.Context, stage: StageOption = StageChoice.TITLE_ABSTRACT) -> None:
    """Serve the next batch of your pass, as an agent sees it, with a file to fill in."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        view, _ = _next_batch(project, _stage(stage))
    for reason in view["blocked"]:
        typer.echo(f"blocked: {reason}")
    if view["batch"] is None:
        typer.echo(f"no batch; {view['remaining']} works remaining")
        return
    for line in render.human_batch_lines(view["batch"]):
        typer.echo(line)
    typer.echo(f"{view['remaining']} works remaining")


def _prompted_item(
    project: Project, actor: Actor, task_id: str, record: dict[str, Any]
) -> HumanScreeningItem:
    """One verdict, asked for until it can be recorded. Only the quote is asked for again when it
    alone is at fault."""
    full_text = "conversion_id" in record
    while True:
        fields: dict[str, Any] = {
            "work_id": record["work_id"],
            "verdict": typer.prompt("verdict (include, exclude, cannot-assess, unsure)"),
            "criterion": typer.prompt("criterion", default="", show_default=False) or None,
            "rationale": typer.prompt("rationale", default="", show_default=False),
        }
        if full_text:
            fields["anchor"] = typer.prompt("anchor")
        while True:
            fields["quote"] = typer.prompt("quote", default="", show_default=False)
            try:
                item = HumanScreeningItem.model_validate(fields)
            except PydanticValidationError as exc:
                for error in exc.errors():
                    typer.echo(f"{error['msg']}", err=True)
                break
            issues = screening_service.item_issues(project, actor, task_id, item)
            if not issues:
                return item
            for issue in issues:
                typer.echo(f"{issue.field}: {issue.reason}", err=True)
            if not all(issue.field.endswith(".quote") for issue in issues):
                break


def _report_recorded(written: int, rejected: list[Any]) -> None:
    typer.echo(f"recorded {written} decisions")
    for item in rejected:
        for issue in item.issues:
            typer.echo(f"{issue.field}: {issue.reason}", err=True)
    if rejected:
        raise typer.Exit(1)


@screen_app.command("record")
def screen_record_cmd(
    ctx: typer.Context,
    file: Annotated[
        Path | None, typer.Argument(help="A filled-in template from `factory screen next`.")
    ] = None,
    interactive: Annotated[
        bool, typer.Option("--interactive", help="Prompt for each record of your batch.")
    ] = False,
    stage: StageOption = StageChoice.TITLE_ABSTRACT,
) -> None:
    """Record your verdicts on a held batch, from a file or by prompts."""
    if (file is None) == (not interactive):
        _fail("give a decision file or --interactive, not both", 2)
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        run_stage = _stage(stage)
        if file is None:
            view, actor = _next_batch(project, run_stage)
            batch = view["batch"]
            if batch is None:
                for reason in view["blocked"]:
                    typer.echo(f"blocked: {reason}")
                typer.echo("no batch")
                return
            items: list[HumanScreeningItem] = []
            for record in batch["records"]:
                for line in render.human_record_lines(record):
                    typer.echo(line)
                items.append(_prompted_item(project, actor, batch["task_id"], record))
            task_id = str(batch["task_id"])
        else:
            actor, _ = human_pass_service.pass_actor(project, run_stage)
            try:
                raw = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                _fail(f"cannot read {file}: {exc}", 1)
            parsed = _parse_model(HumanRecordFile, raw, "file")
            items = list(parsed.items)
            task_id = parsed.task_id
        result = screening_service.screen_record(project, actor, task_id, items)
    _report_recorded(len(result.written), result.rejected)


@screen_app.command("disagreements")
def screen_disagreements(
    ctx: typer.Context, stage: StageOption = StageChoice.TITLE_ABSTRACT
) -> None:
    """List the works the two passes disagree on, each pass's decision and quote; at full text,
    first the unresolved cannot-assess works a human may settle with `screen resolve` (each
    pass's decision, the read and resolve commands), listed before both passes finish."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        queue = agreement_service.cannot_assess_queue(project, stage=_stage(stage))
        try:
            agreement: agreement_service.Agreement | None = agreement_service.screen_agreement(
                project, project.human_actor(), stage=_stage(stage)
            )
            waiting = None
        except FactoryValidationError as exc:
            if _stage(stage) is not ScreeningStage.FULL_TEXT:
                raise
            agreement, waiting = None, str(exc)
    for item in queue:
        typer.echo(f"{item.work_id}  cannot-assess (promoted until resolved)")
        for label, view in item.passes.items():
            for line in render.decision_lines(label, view):
                typer.echo(line)
        if item.read_command is not None:
            typer.echo(f"  read: {item.read_command}")
        typer.echo(f"  resolve: {item.resolve_command}")
    if agreement is None:
        typer.echo(f"disagreements: not available until both passes finish ({waiting})")
        return
    for line in render.tolerated_pending_lines(agreement.tolerated_pending, "not in the agreement"):
        typer.echo(line)
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
    work: Annotated[
        str, typer.Argument(help="A disputed work, or a cannot-assess work at full text.")
    ],
    verdict: Annotated[str, typer.Argument(help="include or exclude.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the human decided.")],
    criterion: Annotated[
        str | None, typer.Option("--criterion", help="The EX criterion of an exclusion.")
    ] = None,
    stage: StageOption = StageChoice.TITLE_ABSTRACT,
) -> None:
    """The human's verdict on a disagreement, on an unsure single-pass work, or, at full text, on
    a cannot-assess work (single-pass or dual-pass). An exclusion needs an EX criterion."""
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


@miner_app.command("add")
def miner_add_cmd(
    ctx: typer.Context,
    document: Annotated[
        Path,
        typer.Argument(help="A JSON file: {spec, use, reason}, or a bare miner specification."),
    ],
    check: Annotated[
        bool, typer.Option("--check", help="Validate and report; write nothing.")
    ] = False,
    reason: Annotated[
        str | None, typer.Option("--reason", help="The protocol amendment's reason.")
    ] = None,
) -> None:
    """Validate, register and list a miner in one step, and name its hub page (IDEA-51)."""
    state = _state(ctx)
    try:
        body = json.loads(document.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"{document}: cannot read a JSON file ({exc})", 1)
    with _reporting_errors():
        project = _resolve_project(state)
        added = miner_add_service.add_miner(
            project, project.human_actor(), body, reason=reason, check_only=check
        )
    verb = ("would register", "would list") if check else ("registered", "listed")
    label = f"{added.name} version {added.version}"
    typer.echo(f"{verb[0] if added.registered else 'already registered'} {label}")
    if added.listed:
        extra = f" (replaces version {added.replaced_version})" if added.replaced_version else ""
        typer.echo(f"{verb[1]} in the protocol{extra}")
    else:
        typer.echo("already listed in the protocol")
    for note in added.notes:
        typer.echo(f"note: {note}")
    typer.echo(f"page: {added.page} (main hub: {added.hub_page})")


@miner_app.command("adopt")
def miner_adopt_cmd(
    ctx: typer.Context,
    source: Annotated[str, typer.Option("--from", help="The source project's slug.")],
    miner: Annotated[str, typer.Option("--miner", help="The miner, as <name>@<version>.")],
) -> None:
    """Register the spec another project registered, recording where it came from."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        name, version = _miner_ref(miner)
        registered = shared_mining_service.register_from(
            project, project.human_actor(), source, name, version
        )
    typer.echo(f"registered {registered.name} version {registered.version}")


@miner_app.command("list")
def miner_list_cmd(ctx: typer.Context) -> None:
    """The registered miners and whether the protocol lists them."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        listing = mining_service.miner_listing(project)
    for line in render.miner_listing_lines(listing):
        typer.echo(line)


@miner_app.command("retire")
def miner_retire_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The miner's name.")],
    version: Annotated[int, typer.Argument(help="The version to retire.")],
    reason: Annotated[str, typer.Option("--reason", help="Why it is retired.")],
) -> None:
    """Retire a miner version: no task is served, its rows stay and are reported."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        miners_service.retire_miner(project, project.human_actor(), name, version, reason)
    typer.echo(f"retired {name} version {version}")


@miner_app.command("reopen")
def miner_reopen_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The miner's name.")],
    version: Annotated[int, typer.Argument(help="The version it was mined under.")],
    work_id: Annotated[str, typer.Argument(help="The work to mine again.")],
    pass_label: Annotated[PassLabel, typer.Option("--pass", help="The pass: A or B.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the work is mined again.")],
) -> None:
    """Reopen one mined work after a selector miss (the researcher's act, IDEA-99): allowed only
    when its completed task's heading patterns matched under 10 % of the paragraph words and the
    selector can fall back (heading patterns; element kinds empty or including paragraphs). The
    next `mine_next` of that version serves a fresh task; the earlier rows are stale at once and
    stay out of final views until the fresh task is mined. Reopening one pass leaves the other
    as it was; reopen both passes when agreement matters."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        event_id = mine_reopen_service.reopen_unit(
            project, project.human_actor(), name, version, work_id, pass_label, reason
        )
    typer.echo(
        f"reopened {work_id} in pass {pass_label.value} of {name} version {version} ({event_id})"
    )


@miner_app.command("admit")
def miner_admit_cmd(
    ctx: typer.Context, name: Annotated[str, typer.Argument(help="The listed miner's name.")]
) -> None:
    """Admit a calibrated miner as evidence (the researcher's act; an amendment of the protocol)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        miners_service.admit_miner(project, project.human_actor(), name)
    typer.echo(f"admitted {name} as evidence")


@miner_calibrate_app.command("draw")
def miner_calibrate_draw_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The miner's name.")],
    version: Annotated[int, typer.Argument(help="The version to calibrate.")],
    seed: Annotated[int | None, typer.Option("--seed", help="A recorded random seed.")] = None,
) -> None:
    """Draw the calibration sample of a listed miner version (the researcher's act)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        drawn = miners_service.draw_miner_calibration(
            project, project.human_actor(), name, version, random_seed=seed
        )
    typer.echo(
        f"calibration {drawn.calibration_id}: {len(drawn.units)} unit(s) of {drawn.population}, "
        f"seed {drawn.random_seed}"
    )
    for unit in drawn.units:
        typer.echo(unit.work_id)


@miner_calibrate_app.command("label")
def miner_calibrate_label_cmd(
    ctx: typer.Context,
    calibration_id: Annotated[str, typer.Argument(help="The calibration.")],
    work_id: Annotated[str, typer.Argument(help="A unit of its sample.")],
    rows: Annotated[
        Path | None, typer.Argument(help="A JSON file: the list of gold rows of the unit.")
    ] = None,
    empty: Annotated[bool, typer.Option("--empty", help="The unit holds no record.")] = False,
) -> None:
    """Record the gold label of one unit: its rows (verified like an agent's), or --empty."""
    state = _state(ctx)
    items: list[ExtractedRowInput] = []
    if rows is not None:
        try:
            body = json.loads(rows.read_text())
            items = [ExtractedRowInput.model_validate(item) for item in body]
        except (OSError, json.JSONDecodeError, PydanticValidationError, TypeError) as exc:
            _fail(f"{rows}: cannot read gold rows ({exc})", 1)
    with _reporting_errors():
        project = _resolve_project(state)
        miner_gold_service.label_miner_calibration(
            project,
            project.human_actor(),
            calibration_id,
            work_id,
            items,
            empty=empty,
            channel=Channel.CLI,
        )
    typer.echo(f"labelled {work_id}: {'empty' if empty else f'{len(items)} gold row(s)'}")


@shared_app.command("rebuild")
def shared_rebuild_cmd(ctx: typer.Context) -> None:
    """Rebuild the shared store from every project's log and print its state hash."""
    state = _state(ctx)
    with _reporting_errors():
        digest = shared_mining_service.shared_store(state.settings, state.clock).rebuild()
    typer.echo(f"state {digest}")


@shared_app.command("status")
def shared_status_cmd(ctx: typer.Context) -> None:
    """Sync the shared store and list each project, the opted-out and the unreadable ones too."""
    state = _state(ctx)
    with _reporting_errors():
        store = shared_mining_service.shared_store(state.settings, state.clock)
        store.sync()
        listing = store.projects()
    for line in render.shared_status_lines(listing):
        typer.echo(line)


def _miner_ref(ref: str) -> tuple[str, int]:
    """`<name>@<version>` as a name and a version; refused on `miner` otherwise."""
    name, _, version = ref.rpartition("@")
    if not name or not version.isdigit():
        raise FactoryValidationError(
            [ValidationIssue("miner", "give the miner as <name>@<version>")]
        )
    return name, int(version)


def _unit_ref(ref: str) -> tuple[str, str]:
    """`<work_id>@<conversion_id>` as a pair; refused on `units` otherwise."""
    work, _, conversion = ref.rpartition("@")
    if not work or not conversion:
        raise FactoryValidationError(
            [ValidationIssue("units", "give a unit as <work_id>@<conversion_id>")]
        )
    return work, conversion


@mine_app.command("import")
def mine_import_cmd(
    ctx: typer.Context,
    miner: Annotated[str, typer.Option("--miner", help="The miner, as <name>@<version>.")],
    source: Annotated[str | None, typer.Option("--from", help="The source project's slug.")] = None,
    unit: Annotated[
        list[str] | None,
        typer.Option("--unit", help="A source unit, <work_id>@<conversion_id>; repeatable."),
    ] = None,
    list_units: Annotated[
        bool, typer.Option("--list", help="List the importable units; import nothing.")
    ] = False,
    page: Annotated[int, typer.Option("--page", help="The page of the listing.")] = 0,
) -> None:
    """Import whole units of a miner from another project, each re-verified against this project's
    own conversion, or list the units that could be imported (the researcher's act)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        name, version = _miner_ref(miner)
        if list_units:
            row = mining_service.registered_row(project, name, version)
            if row is None:
                raise FactoryValidationError(
                    [ValidationIssue("miner", f"{miner} is not registered in this project")]
                )
            store = shared_mining_service.shared_store(state.settings, state.clock)
            store.sync()
            units = shared_mining_service.available_units(
                store, project, name, version, row.digest, source=source, page=page
            )
            for line in render.shared_unit_lines(units):
                typer.echo(line)
            return
        if source is None:
            raise FactoryValidationError([ValidationIssue("source", "give --from <slug>")])
        result = shared_mining_service.mine_import(
            project,
            project.human_actor(),
            source,
            name,
            version,
            None if not unit else [_unit_ref(u) for u in unit],
        )
    for line in render.mine_import_lines(result):
        typer.echo(line)


@mine_app.command("agreement")
def mine_agreement_cmd(
    ctx: typer.Context, miner: Annotated[str, typer.Argument(help="The miner's name.")]
) -> None:
    """The agreement of a miner's two passes and its unresolved disagreements."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        agreement = extraction_agreement_service.extraction_agreement(
            project, project.human_actor(), scope=MinerScope(miner)
        )
    for line in render.agreement_lines(agreement):
        typer.echo(line)


@mine_app.command("resolve")
def mine_resolve_cmd(
    ctx: typer.Context,
    miner: Annotated[str, typer.Argument(help="The miner's name.")],
    work: Annotated[str, typer.Argument(help="A work with a disagreement.")],
    row_key: Annotated[str, typer.Argument(help="The disputed row.")],
    choice: Annotated[ExtractChoice, typer.Option("--choice", help="a, b or neither.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the human decided.")],
    field: Annotated[
        str | None, typer.Option("--field", help="One field; the whole row when omitted.")
    ] = None,
) -> None:
    """The human's choice between a miner's passes on one disagreement."""
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
            scope=MinerScope(miner),
        )
    typer.echo(f"resolved {work} {row_key} {field or 'row'} ({choice.value})")


@mine_audit_app.command("sample")
def mine_audit_sample_cmd(
    ctx: typer.Context, miner: Annotated[str, typer.Argument(help="The miner's name.")]
) -> None:
    """Draw a miner's audit sample; each value with its quote and the cited element text."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        human = project.human_actor()
        drawn = extraction_audit_service.extraction_audit_sample(
            project, human, scope=MinerScope(miner)
        )
        evidence = extraction_audit_service.audit_evidence(
            project, human, drawn.audit_id, Channel.CLI
        )
    typer.echo(f"audit {drawn.audit_id}: {len(drawn.items)} of {drawn.population} agreed values")
    for line in render.tolerated_pending_lines(drawn.tolerated_pending, "recorded in the audit"):
        typer.echo(line)
    for item in evidence:
        for line in render.audit_evidence_lines(item):
            typer.echo(line)


@mine_audit_app.command("label")
def mine_audit_label_cmd(
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
    """A human's label on one sampled miner value."""
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


@mine_audit_app.command("report")
def mine_audit_report_cmd(
    ctx: typer.Context, miner: Annotated[str, typer.Argument(help="The miner's name.")]
) -> None:
    """The latest audit of a miner: its counts and error rate."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = extraction_audit_service.extraction_audit_report(project, scope=MinerScope(miner))
    if report is None:
        typer.echo("no audit sampled")
        return
    for line in render.audit_report_lines(report):
        typer.echo(line)


@miner_calibrate_app.command("report")
def miner_calibrate_report_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The miner's name.")],
    version: Annotated[int, typer.Argument(help="The version.")],
) -> None:
    """The calibration of a miner version: its state, units and scores (the researcher's view)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = miner_report_service.miner_calibration_report(project, name, version)
        lifecycle = miners_service.miner_state(project, name, version)
    typer.echo(f"{name} version {version}: {lifecycle.value}")
    if report is None:
        typer.echo("no calibration drawn")
        return
    for line in render.miner_calibration_lines(report):
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
    for line in render.tolerated_pending_lines(drawn.tolerated_pending, "recorded in the audit"):
        typer.echo(line)
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
    for line in render.tolerated_pending_lines(drawn.tolerated_pending, "recorded in the audit"):
        typer.echo(line)
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


# --- Appraisal (plan EQ): a declared instrument, items never summed ---


@appraisal_app.command("status")
def appraisal_status_cmd(ctx: typer.Context, as_json: _JSON = False) -> None:
    """Works, span items by state, judgement items open and recorded, stale works. Computed."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        status = appraisal_service.appraisal_status(project)
    if as_json:
        typer.echo(status.model_dump_json())
        return
    for line in appraisal_render.status_lines(status):
        typer.echo(line)


@appraisal_app.command("sheet")
def appraisal_sheet_cmd(
    ctx: typer.Context,
    work: Annotated[str, typer.Argument(help="An appraised work.")],
    as_json: _JSON = False,
) -> None:
    """One work item by item: computed items, both passes' answers with quotes, judgements."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        sheet = appraisal_service.appraisal_sheet(project, work)
    if as_json:
        typer.echo(sheet.model_dump_json())
        return
    for line in appraisal_render.sheet_lines(sheet):
        typer.echo(line)


@appraisal_app.command("agreement")
def appraisal_agreement_cmd(ctx: typer.Context) -> None:
    """Agreement by item between the passes and the open disagreements."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        by_item = appraisal_service.agreement(project)
        open_ = appraisal_service.disagreements(project)
    for line in appraisal_render.agreement_lines(by_item, open_):
        typer.echo(line)


@appraisal_app.command("resolve")
def appraisal_resolve_cmd(
    ctx: typer.Context,
    work: Annotated[str, typer.Argument(help="A work with a disagreement.")],
    item: Annotated[str, typer.Argument(help="The disputed item.")],
    choice: Annotated[ExtractChoice, typer.Option("--choice", help="a, b or neither.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the human decided.")],
) -> None:
    """The human's choice between the passes on one span-item disagreement."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        appraisal_service.resolve_disagreement(
            project, project.human_actor(), work, item, choice.value, reason, channel=Channel.CLI
        )
    typer.echo(f"resolved {work} {item} ({choice.value})")


@appraisal_app.command("judge")
def appraisal_judge_cmd(
    ctx: typer.Context,
    work: Annotated[str, typer.Argument(help="An appraised work.")],
    item: Annotated[str, typer.Argument(help="A judgement item of the instrument.")],
    answer: Annotated[str, typer.Argument(help="yes, no or unclear.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why the human judged so.")],
) -> None:
    """A human's judgement of one item of one work; a later judgement supersedes it."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        appraisal_service.record_judgement(
            project,
            project.human_actor(),
            work,
            item,
            AppraisalAnswer(answer),
            rationale=rationale,
            channel=Channel.CLI,
        )
    typer.echo(f"judged {work} {item} ({answer})")


@appraisal_app.command("audit-sample")
def appraisal_audit_sample_cmd(
    ctx: typer.Context,
    seed: Annotated[
        int | None, typer.Option("--seed", help="Random seed; fresh if omitted.")
    ] = None,
) -> None:
    """Draw the audit sample of final span answers."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        drawn = appraisal_service.appraisal_audit_sample(
            project, project.human_actor(), random_seed=seed
        )
    typer.echo(f"audit {drawn.audit_id}: {len(drawn.items)} answers")
    for work_id, item in drawn.items:
        typer.echo(f"  {work_id}  {item}")


@appraisal_app.command("audit-label")
def appraisal_audit_label_cmd(
    ctx: typer.Context,
    audit_id: Annotated[str, typer.Argument(help="The audit being labelled.")],
    work: Annotated[str, typer.Argument(help="A work of the sample.")],
    item: Annotated[str, typer.Argument(help="The sampled item.")],
    correct: Annotated[
        bool, typer.Option("--correct/--incorrect", help="Whether the final answer is right.")
    ],
    note: Annotated[str, typer.Option("--note", help="An optional note.")] = "",
) -> None:
    """A human's label on one sampled answer."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        appraisal_service.appraisal_audit_label(
            project, project.human_actor(), audit_id, work, item, correct, note, Channel.CLI
        )
    typer.echo(f"labelled {work} {item} in {audit_id} ({'correct' if correct else 'incorrect'})")


@appraisal_app.command("audit-report")
def appraisal_audit_report_cmd(ctx: typer.Context) -> None:
    """The latest appraisal audit's counts and error rate."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = appraisal_service.appraisal_audit_report(project)
    if report is None:
        typer.echo("no audit sampled")
        return
    rate = "n/a" if report.error_rate is None else f"{report.error_rate:.3f}"
    typer.echo(
        f"audit {report.audit_id}: sampled {report.sampled}, labelled {report.labelled}, "
        f"incorrect {report.incorrect}, error rate {rate}"
    )


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
        if not _full_view(project) and as_json:
            typer.echo(json.dumps(agent_view_service.prisma_view(project, update)))
            return
        if not _full_view(project):
            if update is not None:
                until = None if update == "last" else update
                text = render.update_markdown(
                    prisma_update_service.prisma_update(project, until=until)
                )
            elif fmt is PrismaFormat.SVG:
                text = exports_service.export_prisma_svg(project)
            else:
                text = render.prisma_markdown(prisma_service.prisma_flow(project))
            typer.echo(agent_view_service.scrubbed_text(project, text), nl=False)
            return
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
    str | None,
    typer.Option("--scope", help="included (default), corpus or draft:<drf_...>; not with --id."),
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
def export_prisma(
    ctx: typer.Context,
    out: _OUT = None,
    update: Annotated[
        str | None,
        typer.Option("--update", help="The update flow: `last`, or the snapshot it closed at."),
    ] = None,
) -> None:
    """The PRISMA 2020 flow diagram as SVG (with --update, the update flow)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        svg = (
            exports_service.export_prisma_svg(project)
            if update is None
            else exports_service.export_update_flow_svg(
                project, None if update == "last" else update
            )
        )
        _emit([svg], out)


@export_app.command("crate")
def export_crate_cmd(
    ctx: typer.Context,
    out: Annotated[Path, typer.Option("--out", help="A directory, or a file with --zip.")],
    zip_: Annotated[bool, typer.Option("--zip", help="Write one zip file.")] = False,
    force: Annotated[bool, typer.Option("--force", help="Replace a crate at --out.")] = False,
) -> None:
    """The project as an RO-Crate 1.1, without library content; prints what was written."""
    state = _state(ctx)
    renderers = exports_service.CrateRenderers(
        prisma_markdown=render.prisma_markdown,
        search_markdown=render.search_markdown,
        evidence_markdown=evidence_render.evidence_markdown,
        evidence_rows_csv=evidence_render.rows_csv,
        evidence_points_csv=evidence_render.points_csv,
    )
    with _reporting_errors():
        project = _resolve_project(state)
        summary = exports_service.export_crate(project, out, renderers, zip_=zip_, force=force)
    typer.echo(
        f"{summary.files} files, {summary.bytes} bytes; {summary.documents_listed} library "
        f"documents listed; {summary.drafts} released drafts"
    )
    if summary.blobs_binary or summary.blobs_left_out:
        typer.echo(f"blobs left out: {summary.blobs_binary} binary, {summary.blobs_left_out} other")


@export_app.command("nanopub")
def export_nanopub_cmd(
    ctx: typer.Context,
    out: Annotated[Path, typer.Option("--out", help="A new or empty directory.")],
    edges: Annotated[
        bool, typer.Option("--edges", help="Add stated and confirmed lineage edges.")
    ] = False,
    with_quotes: Annotated[
        bool, typer.Option("--with-quotes", help="Add quote text, for local use.")
    ] = False,
) -> None:
    """Claims and, with --edges, lineage edges as nanopublications in TriG, one file each."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        summary = exports_service.export_nanopubs(
            project, out, edges=edges, with_quotes=with_quotes
        )
    typer.echo(
        f"{summary.written} written ({summary.claims} claims, {summary.edges} edges); "
        f"{summary.skipped_no_identifier} skipped without a DOI or arXiv id"
    )
    if with_quotes:
        typer.echo("unsigned; holds quote text, for local use only: do not publish")
    else:
        typer.echo("unsigned; sign and publish with nanopub tooling")


@export_app.command("works")
def export_works_cmd(
    ctx: typer.Context,
    out: Annotated[Path, typer.Option("--out", help="A new directory, or a new file ending .zip.")],
    layer: Annotated[str | None, typer.Option("--layer", help="Every work of this layer.")] = None,
    ids: Annotated[str | None, typer.Option("--ids", help="Work ids, comma separated.")] = None,
    from_file: Annotated[
        Path | None, typer.Option("--from-file", help="Work ids, one per line.")
    ] = None,
    pdfs: Annotated[
        bool, typer.Option("--pdfs", help="Add the stored PDFs (licensed files; needs --confirm).")
    ] = False,
    confirm: Annotated[
        bool, typer.Option("--confirm", help="Confirm that licensed PDFs may be copied out.")
    ] = False,
    max_works: Annotated[int, typer.Option("--max-works", help="Selection cap.")] = (
        export_works_service.MAX_WORKS
    ),
    max_mb: Annotated[int, typer.Option("--max-mb", help="Total size cap in MB.")] = (
        export_works_service.MAX_BYTES // (1024 * 1024)
    ),
) -> None:
    """The converted Markdown of chosen works (and with --pdfs their PDFs) with a header per file
    and a manifest, for upload to a notebook tool. With --pdfs, --confirm is required."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        authorize_export_works(project, project.principal, pdfs=pdfs, confirm=confirm)
        given = [x for x in (layer, ids, from_file) if x is not None]
        if len(given) != 1:
            raise FactoryValidationError(
                [ValidationIssue("selection", "give exactly one of --layer, --ids, --from-file")]
            )
        if layer is not None:
            selection = export_works_service.select_by_layer(project, layer)
        elif ids is not None:
            selection = export_works_service.Selection(
                export_works_service.work_ids_of(ids.split(",")), "ids"
            )
        else:
            assert from_file is not None
            selection = export_works_service.Selection(
                export_works_service.read_ids_file(from_file), f"ids from file {from_file.name}"
            )
        summary = export_works_service.export_works(
            project,
            selection,
            out,
            pdfs=pdfs,
            max_works=max_works,
            max_bytes=max_mb * 1024 * 1024,
        )
    typer.echo(
        f"{summary.exported} exported, {summary.skipped} skipped; "
        f"{summary.bytes} bytes -> {summary.out}"
    )
    if pdfs:
        typer.echo(f"without a PDF: {summary.without_pdf} (listed in the manifest)")
    typer.echo("answers produced in the other tool are not records; see MANIFEST.md")


@report_app.command("search")
def report_search(ctx: typer.Context, as_json: _JSON = False) -> None:
    """The PRISMA-S search report: each registered query and what it retrieved."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = (
            prisma_service.search_report(project)
            if _full_view(project)
            else agent_view_service.agent_search(project)
        )
    typer.echo(report.model_dump_json() if as_json else render.search_markdown(report), nl=as_json)


@report_app.command("flow")
def report_flow(
    ctx: typer.Context,
    by_source: Annotated[
        bool, typer.Option("--by-source", help="The PRISMA counts per source group, as a table.")
    ] = False,
    as_json: _JSON = False,
) -> None:
    """The PRISMA counts per source group, and whether they reconcile with the flow."""
    state = _state(ctx)
    if not by_source:
        _fail("report flow needs --by-source, its only view so far", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        if not _full_view(project):
            typer.echo(json.dumps(agent_view_service.by_source_view(project)))
            return
        rows = flow_ledger_service.flow_ledger(project)
        counts = flow_ledger_service.flow_by_source(project, rows)
        mismatches = flow_ledger_service.ledger_reconciles(project, rows)
    if as_json:
        payload = {
            "by_source": {key: value.model_dump(mode="json") for key, value in counts.items()},
            "reconciles": mismatches,
        }
        typer.echo(json.dumps(payload))
        return
    typer.echo(render.flow_table_markdown(counts), nl=False)
    if mismatches:
        for line in mismatches:
            typer.echo(f"not reconciled: {line}")
    else:
        typer.echo("reconciles with the PRISMA flow")


@report_app.command("flow-works")
def report_flow_works(
    ctx: typer.Context,
    source: Annotated[str | None, typer.Option("--source", help="A source group.")] = None,
    step: Annotated[
        str | None,
        typer.Option("--step", help="title-abstract, full-text-retrieval or full-text."),
    ] = None,
    outcome: Annotated[
        str | None, typer.Option("--outcome", help="The step's outcome (needs --step).")
    ] = None,
    criterion: Annotated[
        str | None,
        typer.Option(
            "--criterion", help="An exclusion criterion (needs --step, outcome excluded)."
        ),
    ] = None,
    cursor: Annotated[str | None, typer.Option("--cursor", help="Continue a listing.")] = None,
    limit: Annotated[
        int, typer.Option("--limit", help="Rows per page, at most 50.")
    ] = flow_query_service.PAGE_LIMIT,
    as_json: _JSON = False,
) -> None:
    """The work ledger, filtered and one page at a time."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        if not _full_view(project):
            typer.echo(
                json.dumps(
                    agent_view_service.flow_works_view(
                        project,
                        source_group=source,
                        step=step,
                        outcome=outcome,
                        criterion=criterion,
                        cursor=cursor,
                        limit=limit,
                    )
                )
            )
            return
        page = flow_query_service.flow_works(
            project,
            source_group=source,
            step=step,
            outcome=outcome,
            criterion=criterion,
            cursor=cursor,
            limit=limit,
        )
    typer.echo(page.model_dump_json() if as_json else "\n".join(render.flow_works_lines(page)))


@report_app.command("flow-trail")
def report_flow_trail(
    ctx: typer.Context,
    work_id: Annotated[str, typer.Argument(help="The work's id.")],
    as_json: _JSON = False,
) -> None:
    """The trail of one work: what happened to it, in time order."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        if not _full_view(project):
            typer.echo(json.dumps(agent_view_service.flow_trail_view(project, work_id)))
            return
        steps = flow_query_service.flow_trail(project, work_id)
    if as_json:
        payload = {"work_id": work_id, "steps": [step.model_dump(mode="json") for step in steps]}
        typer.echo(json.dumps(payload))
        return
    typer.echo("\n".join(render.flow_trail_lines(work_id, steps)))


@report_app.command("flow-skipped")
def report_flow_skipped(ctx: typer.Context, as_json: _JSON = False) -> None:
    """The raw records that never became works, and each query's run gaps."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        if not _full_view(project):
            typer.echo(json.dumps(agent_view_service.flow_skipped_view(project)))
            return
        records = flow_skipped_service.skipped_records(project)
        gaps = flow_skipped_service.run_gaps(project)
    if as_json:
        payload = {
            "skipped": [record.model_dump(mode="json") for record in records],
            "run_gaps": [gap.model_dump(mode="json") for gap in gaps],
        }
        typer.echo(json.dumps(payload))
        return
    typer.echo("\n".join(render.flow_skipped_lines(records, gaps)))


@report_app.command("methods")
def report_methods(ctx: typer.Context, as_json: _JSON = False) -> None:
    """The methods statement, generated from the events."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        if not _full_view(project):
            if as_json:
                typer.echo(json.dumps(agent_view_service.methods_view(project)))
            else:
                typer.echo(agent_view_service.methods_text(project), nl=False)
            return
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
        if not _full_view(project):
            typer.echo(json.dumps(agent_view_service.discovery_view(project)))
            return
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
    without_grey: Annotated[
        bool,
        typer.Option(
            "--without-grey",
            help="Show the tables without works found by a grey method; both counts are stated.",
        ),
    ] = False,
    with_appraisal: Annotated[
        bool,
        typer.Option(
            "--with-appraisal",
            help="Add the appraisal matrix (md and json only). It shows items; it filters nothing.",
        ),
    ] = False,
) -> None:
    """The evidence report: grouped final rows, frontiers and limits (full view, audit shown)."""
    state = _state(ctx)
    expectations = [_parse_expect(e) for e in expect or []]
    if with_appraisal and fmt not in (EvidenceFormat.MD, EvidenceFormat.JSON):
        _fail("--with-appraisal applies to the md and json formats", 2)
    with _reporting_errors():
        project = _resolve_project(state)
        full = _full_view(project)
        if full:
            report = evidence_report_service.evidence_report(
                project,
                expect=expectations,
                include_notice_affected=include_notice_affected,
                without_grey=without_grey,
            )
        elif include_notice_affected:
            _fail("--include-notice-affected: researcher view only", 1)
        elif with_appraisal:
            _fail("--with-appraisal: researcher view only", 1)
        else:
            report = agent_view_service.agent_evidence(
                project, expectations, without_grey=without_grey
            )
        matrix = appraisal_report_service.appraisal_report(project) if with_appraisal else None
    if fmt is EvidenceFormat.JSON:
        text = report.model_dump_json()
        if matrix is not None:
            text = '{"evidence": ' + text + ', "appraisal": ' + matrix.model_dump_json() + "}"
    elif fmt is EvidenceFormat.CSV_ROWS:
        text = evidence_render.rows_csv(report)
    elif fmt is EvidenceFormat.CSV_POINTS:
        text = evidence_render.points_csv(report)
    else:
        text = evidence_render.evidence_markdown(report, show_audit=full)
        if matrix is not None:
            text = text.rstrip("\n") + "\n" + appraisal_render.report_markdown(matrix)
    if not full:
        text = agent_view_service.scrubbed_text(project, text)
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
    accept: Annotated[
        list[str] | None,
        typer.Option(
            "--accept", help="A file listed as identity unchecked that you vouch for; repeatable."
        ),
    ] = None,
) -> None:
    """Import the researcher's PDFs from FOLDER by the identifiers they carry; prints every list."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = fulltext_import_service.import_folder(project, folder, accept=accept or ())
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
        if document is not None:
            outcomes: Iterator[fulltext_service.RestoreOutcome] = iter(
                [
                    fulltext_service.RestoreOutcome(
                        document,
                        fulltext_service.restore_document(
                            project, document, routes=routes, actor=human
                        ),
                    )
                ]
            )
        else:
            outcomes = fulltext_service.restore_missing(project, routes, human)
        counts: dict[str, int] = {}
        unavailable: list[str] = []
        for outcome in outcomes:
            typer.echo(f"{outcome.document_id}  {outcome.status}")
            key = outcome.status.split(":")[0]
            counts[key] = counts.get(key, 0) + 1
            if outcome.status == "unavailable":
                unavailable.append(outcome.document_id)
        if missing:
            if not counts:
                typer.echo("no library entry is missing")
                return
            typer.echo(", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    if unavailable:
        _fail(f"unavailable: {' '.join(unavailable)}", 1)


@fulltext_app.command("resolve")
def fulltext_resolve_cmd(
    ctx: typer.Context,
    document: Annotated[str, typer.Argument(help="The document whose source changed.")],
    observed_hash: Annotated[str, typer.Argument(help="The hash `fulltext status` lists.")],
    decision: Annotated[SourceDecision, typer.Argument(help="What to do with the new bytes.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why, in a sentence or two.")],
) -> None:
    """Resolve a changed source (a human act). The original bytes stay referenced either way."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        new_document = fulltext_service.resolve_source_change(
            project,
            project.human_actor(),
            document,
            observed_hash,
            decision,
            rationale=rationale,
        )
    typer.echo(f"{document}  {decision.value}")
    if new_document is not None:
        typer.echo(f"{new_document}  supersedes {document}; convert it to read it")


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
    converter: Annotated[
        str | None,
        typer.Option(
            "--converter",
            help="Use this converter instead of decision 49's (`factory document converters`).",
        ),
    ] = None,
    upgrade: Annotated[
        bool,
        typer.Option(
            "--upgrade",
            help="Re-convert documents whose latest conversion is an older converter version.",
        ),
    ] = False,
) -> None:
    """Convert the retrieved documents of promoted works, as the researcher.

    Without --work or --document, converts every live document of a promoted work. A failed
    document is recorded and the rest continue. --restore regenerates the stored Markdown of
    recorded conversions that are missing or damaged; it writes no event. --converter adds a
    conversion beside the existing ones, and a later run without it leaves that document alone.
    A document whose latest conversion is an older version of the same converter is skipped and
    reported as `outdated`; --upgrade converts it, keeping the old conversion.
    """
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        registry = default_converters() if converter is None else override_registry(converter)
        summary = document_convert_service.convert_or_restore(
            project,
            registry,
            restore=restore,
            work_ids=work,
            document_ids=document,
            override=converter is not None,
            upgrade=upgrade,
        )
    for line in render.convert_lines(summary):
        typer.echo(line)


@document_app.command("reanchor")
def document_reanchor_cmd(
    ctx: typer.Context,
    converter: Annotated[
        str | None,
        typer.Option("--converter", help="Only documents whose latest conversion is by this one."),
    ] = None,
    document: Annotated[
        list[str] | None,
        typer.Option("--document", help="A live document; repeat for several."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report what would happen; store and record nothing."),
    ] = False,
) -> None:
    """Re-anchor the latest conversions under the current anchoring rules, as the researcher.

    Recomputes anchors from the stored Markdown, without the converter, and records a NEW
    conversion per document (converter version plus `+anchors<n>`); the old conversion is kept
    and the new one becomes the one read. A document already at the current rules is unchanged.
    """
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        summary = reanchor_service.reanchor_conversions(
            project, converter=converter, document_ids=document, dry_run=dry_run
        )
    for line in render.convert_lines(summary):
        typer.echo(line)


@document_app.command("converters")
def document_converters_cmd() -> None:
    """List the converters, which ones decision 49 chose, and whether each can run here."""
    for line in render.converter_lines(converter_infos()):
        typer.echo(line)


@document_app.command("coverage")
def document_coverage_cmd(ctx: typer.Context) -> None:
    """Compare each converted document's original text with its Markdown (word 5-grams) and store
    the result as a derived cache that the dashboard shows. A triage aid; it decides nothing."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        report = conversion_coverage_service.refresh(project)
    typer.echo(
        f"measured {len(report.rows)} documents; not measured: {report.not_measured or 'none'}"
    )


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
        full = _full_view(project)
        read = trace_service.trace if full else agent_view_service.agent_trace
        tree = read(
            project,
            ref,
            direction="forward" if forward else "back",
            layer="all" if with_interpretation else "evidence",
        )
    for line in render.trace_lines(tree):
        typer.echo(line if full else agent_view_service.scrubbed_text(project, line))


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
    full_replay: bool = False,
) -> tuple[int, dict[str, object], list[str]]:
    """Run, or preview, one project's cycle. Returns its exit code, JSON and text lines."""
    try:
        project = open_project(state.settings, slug, session=state.session, clock=state.clock)
        authorize_command(project, project.principal, state.tool)
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
            full_replay=full_replay,
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
    full_replay: Annotated[
        bool,
        typer.Option(
            "--full-replay",
            help="Replay every source in full this cycle (needs --human; never automatic).",
        ),
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
            state,
            slug,
            dry_run=dry_run,
            force=not due,
            human=human,
            skip_unplanned=all_projects,
            full_replay=full_replay,
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
    opened = open_project(state.settings, project, session=state.session, clock=state.clock)
    return _authorized(state, opened)


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


@notices_app.command("check")
def notices_check_cmd(
    ctx: typer.Context,
    all_works: Annotated[
        bool,
        typer.Option("--all", help="Check every corpus work, not only the works the review uses."),
    ] = False,
    budget: Annotated[
        int, typer.Option("--budget", min=1, help="At most this many works are looked up.")
    ] = 200,
) -> None:
    """Look up notices for every corpus work (least recently checked first) within a budget, as a
    human-triggered watch cycle: the protocol's planned searches run in that cycle as well. Reports
    what the budget left out and what no source can be asked about."""
    if not all_works:
        _fail("pass --all; the dependents are checked by `factory watch run`", 2)
    state = _state(ctx)
    seen: list[NoticeCheckSummary] = []
    with _reporting_errors():
        project = _resolve_project(state)
        sources = dict(default_sources())
        hook = make_status_hook(
            {**status_sources(), **sources},
            scope="corpus",
            budget=budget,
            on_summary=seen.append,
        )
        cycle = watch_service.watch_run(
            project,
            sources=sources,
            trigger="human",
            actor=project.human_actor(),
            force=True,
            after_runs=(hook,),
        )
    if cycle is None or not seen:
        typer.echo("no cycle ran")
        raise typer.Exit(1)
    summary = seen[0]
    typer.echo(
        f"{cycle.cycle_id}  checked {summary.checked}  new notices {summary.new_notices}  "
        f"beyond budget {summary.beyond_budget}  failed lookups {summary.failed}"
    )
    typer.echo(f"no identifier a source takes: {len(summary.unaskable)}")
    typer.echo(f"no Crossref DOI: {len(summary.unchecked_crossref)}")


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
    region: Annotated[
        str | None,
        typer.Option("--region", help="Only the work members of this region's latest version."),
    ] = None,
) -> None:
    """The computed digest since the last one (or an event): print it, or write it to --out."""
    state = _state(ctx)
    if record and region is not None:
        _fail("a digest restricted to a region is not recorded: it would move the cut-off", 2)
    slugs = _watch_projects(state, project if project is not None else state.project, all_projects)
    if fmt is DigestFormat.BOTH and out is None:
        _fail("--format both needs --out", 2)
    with _reporting_errors():
        opened = [
            _authorized(
                state,
                open_project(state.settings, slug, session=state.session, clock=state.clock),
            )
            for slug in slugs
        ]
        if not opened:
            _fail("no project; run factory init", 2)
        built = digest_service.digest_build(opened, since=since, region=region)
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
        full = _full_view(project)
        read = check_service.check if full else check_service.agent_check
        report = read(project, promote_to=_mode(promote_to))
    for line in render.check_lines(report):
        typer.echo(line if full else agent_view_service.scrubbed_text(project, line))
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


@import_app.command("ris")
def import_ris_cmd(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="A RIS export.")],
    role: RoleOption,
    collection: CollectionOption = None,
    seed: SeedOption = None,
    no_split: NoSplitOption = False,
) -> None:
    """Archive and record a RIS export; prints the import id, counts and split."""
    _library_import(ctx, path, ImportFormat.RIS, role, collection, seed, no_split)


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
    hints: Annotated[
        bool,
        typer.Option(
            "--hints", help="With --researcher: the first line of each untitled record's file."
        ),
    ] = False,
) -> None:
    """The records of an import. By default: records that are not held out, by hash, with no
    ordinals, and the held-out count. `--researcher` lists ordinals, parts and, for a PDF folder,
    file names."""
    state = _state(ctx)
    if hints and not researcher:
        _fail("--hints shows file text; pass --researcher", 1)
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
            names = imports_service.import_file_names(project, import_id)
            shown = imports_service.first_page_hints(project, import_id) if hints else {}
            lines = render.import_record_lines(records, names, shown)
        else:
            view = imports_service.development_view(project, import_id)
            lines = render.development_view_lines(view)
    for line in lines:
        typer.echo(line)


@import_app.command("resolve")
def import_resolve_cmd(
    ctx: typer.Context,
    import_id: Annotated[str, typer.Argument(help="An import id (imp_...).")],
    described: Annotated[
        bool,
        typer.Option(
            "--described",
            help="Only the records described since their last resolution; other decisions stand.",
        ),
    ] = False,
) -> None:
    """Resolve the import's records to works (probe lookups, outside the corpus); prints counts
    by state. Fuzzy and ambiguous matches wait for `import confirm` or `import reject`."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        summary = import_resolve_service.resolve_import(
            project, import_id, sources=dict(default_sources()), described_only=described
        )
        tagged = labels_service.import_tags_as_labels(project, import_id)
    for line in render.import_resolve_lines(summary):
        typer.echo(line)
    if tagged:
        typer.echo(f"tags applied as labels: {tagged}")


RationaleOption = Annotated[str, typer.Option("--rationale", help="Why (required).")]


@import_app.command("describe")
def import_describe_cmd(
    ctx: typer.Context,
    import_id: Annotated[str, typer.Argument(help="An import id (imp_...).")],
    ordinal: Annotated[
        int | None,
        typer.Argument(help="The record's ordinal (`import show --researcher`); not with --csv."),
    ] = None,
    rationale: RationaleOption = "",
    title: Annotated[str | None, typer.Option("--title", help="The work's title.")] = None,
    author: Annotated[
        list[str] | None, typer.Option("--author", help="An author; repeat, in order.")
    ] = None,
    year: Annotated[int | None, typer.Option("--year", help="Year of publication.")] = None,
    doi: Annotated[str | None, typer.Option("--doi", help="The work's DOI.")] = None,
    arxiv: Annotated[str | None, typer.Option("--arxiv", help="The work's arXiv id.")] = None,
    venue: Annotated[str | None, typer.Option("--venue", help="Journal or venue.")] = None,
    record_type: Annotated[
        str | None, typer.Option("--type", help="article, inproceedings, preprint, book, ...")
    ] = None,
    abstract: Annotated[str | None, typer.Option("--abstract", help="The abstract.")] = None,
    csv_file: Annotated[
        Path | None,
        typer.Option(
            "--csv",
            help="A CSV with a header from ordinal,title,authors,year,doi,arxiv,venue; authors "
            "separated by ';'. Read, never archived.",
        ),
    ] = None,
) -> None:
    """Say what a record is, as the researcher: an overlay on the record, which stays as it was.
    Run `import resolve IMP --described` afterwards."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        actor = project.human_actor()
        if csv_file is not None:
            if ordinal is not None:
                _fail("give an ORDINAL or --csv, not both", 1)
            summary = import_describe_service.describe_records(
                project, actor, import_id, csv_file, rationale=rationale
            )
            lines = render.import_describe_lines(import_id, summary.described, summary.rejected)
        else:
            if ordinal is None:
                _fail("give an ORDINAL or --csv", 1)
            fields = {
                "title": title,
                "authors": author,
                "year": year,
                "doi": doi,
                "arxiv": arxiv,
                "venue": venue,
                "type": record_type,
                "abstract": abstract,
            }
            import_describe_service.describe_record(
                project,
                actor,
                import_id,
                ordinal,
                import_describe_service.parse_description(fields),
                rationale=rationale,
            )
            lines = render.import_describe_lines(import_id, 1, [])
    for line in lines:
        typer.echo(line)


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
        tagged = labels_service.import_tags_as_labels(project, import_id)
    for line in render.import_decision_lines(import_id, decision, live):
        typer.echo(line)
    if tagged:
        typer.echo(f"tags applied as labels: {tagged}")


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
        tagged = labels_service.import_tags_as_labels(project, import_id)
    for line in render.import_admit_lines(summary):
        typer.echo(line)
    if tagged:
        typer.echo(f"tags applied as labels: {tagged}")


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


@cards_app.command("import")
def cards_import_cmd(
    ctx: typer.Context,
    card: Annotated[str, typer.Argument(help="The source card id, mcd_ or pbd_.")],
    source: Annotated[
        Path, typer.Option("--from", help="The source project's directory, projects/<slug>.")
    ],
) -> None:
    """Import a card from another project on this machine, as a human act. An assertion is
    stated only if its basis re-verifies here; the rest are imported-unverified. The source
    project is never written."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        result = card_import.import_card(project, project.human_actor(), source, card)
    typer.echo(f"imported {result.card_id}")
    for source_id, new_id, status in result.imported:
        typer.echo(f"  {source_id} -> {new_id} ({status})")
    for source_id, reason in result.skipped:
        typer.echo(f"  skipped {source_id}: {reason}")


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


_LAYER_OPT = typer.Option("--layer", help="core (default), all, or another layer id.")
_FORMAT_OPT = typer.Option("--format", help="table or json.")


def _technique_out(result: BaseModel, lines: Callable[[Any], list[str]], format_: str) -> None:
    """Print a technique result as table lines or as JSON (class key written)."""
    if format_ not in ("table", "json"):
        raise typer.BadParameter("must be table or json", param_hint="--format")
    if format_ == "json":
        typer.echo(result.model_dump_json(by_alias=True, indent=2))
        return
    for line in lines(result):
        typer.echo(line)


@technique_app.command("landscape")
def technique_landscape_cmd(
    ctx: typer.Context,
    stage: Annotated[str | None, typer.Option("--stage", help="One stage.")] = None,
    layer: Annotated[str, _LAYER_OPT] = "core",
    evidence: Annotated[str | None, typer.Option("--evidence", help="Evidence level.")] = None,
    status: Annotated[str | None, typer.Option("--status", help="Use status.")] = None,
    min_co_works: Annotated[int, typer.Option("--min-co-works")] = 2,
    format_: Annotated[str, _FORMAT_OPT] = "table",
) -> None:
    """The approaches by stage with the number of works and each stage miner's agreement."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        result = technique_service.technique_landscape(
            project,
            layer=layer,
            stage=stage,
            evidence=evidence,
            status=status,
            min_co_works=min_co_works,
        )
    _technique_out(result, render.technique_landscape_lines, format_)


@technique_app.command("show")
def technique_show_cmd(
    ctx: typer.Context,
    approach: Annotated[str, typer.Argument(help="An approach id such as ide-01.")],
    layer: Annotated[str, _LAYER_OPT] = "core",
    format_: Annotated[str, _FORMAT_OPT] = "table",
) -> None:
    """One approach: its works, rows with quotes and anchors, derives-from candidates."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        result = technique_service.technique_view(project, approach, layer=layer)
    _technique_out(result, render.technique_view_lines, format_)


@technique_app.command("candidates")
def technique_candidates_cmd(
    ctx: typer.Context,
    layer: Annotated[str, _LAYER_OPT] = "core",
    format_: Annotated[str, _FORMAT_OPT] = "table",
) -> None:
    """The candidate derives-from edges (all exploratory; none is accepted before a decision)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        result = technique_service.technique_derivations(project, layer=layer)
    _technique_out(result, render.technique_candidate_lines, format_)


@technique_app.command("neighbors")
def technique_neighbors_cmd(
    ctx: typer.Context,
    approach: Annotated[str, typer.Argument(help="An approach id.")],
    layer: Annotated[str, _LAYER_OPT] = "core",
    min_works: Annotated[int, typer.Option("--min-works")] = 1,
    limit: Annotated[int | None, typer.Option("--limit")] = 50,
    format_: Annotated[str, _FORMAT_OPT] = "table",
) -> None:
    """Co-used approaches by weight, stages reached, works, derives-from candidates."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        result = technique_service.technique_neighbors(
            project, approach, layer=layer, min_works=min_works, limit=limit
        )
    _technique_out(result, render.technique_neighbor_lines, format_)


@technique_app.command("gaps")
def technique_gaps_cmd(
    ctx: typer.Context,
    from_stage: Annotated[str, typer.Option("--from-stage")],
    to_stage: Annotated[str, typer.Option("--to-stage")],
    min_works: Annotated[int, typer.Option("--min-works")] = 3,
    max_to_share: Annotated[float, typer.Option("--max-to-share")] = 0.0,
    layer: Annotated[str, _LAYER_OPT] = "core",
    limit: Annotated[int | None, typer.Option("--limit")] = 100,
    rank_by: Annotated[
        str, typer.Option("--rank-by", help="composite or one component")
    ] = "composite",
    top: Annotated[int | None, typer.Option("--top", help="ranked shortlist size")] = 50,
    format_: Annotated[str, _FORMAT_OPT] = "table",
) -> None:
    """Ranked hypotheses to check: approaches used at one stage whose users show none at another."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        result = technique_service.technique_gaps(
            project,
            from_stage=from_stage,
            to_stage=to_stage,
            min_works=min_works,
            max_to_share=max_to_share,
            layer=layer,
            limit=limit,
            rank_by=rank_by,
            top=top,
        )
    _technique_out(result, render.technique_candidate_list_lines, format_)


@technique_app.command("combinations")
def technique_combinations_cmd(
    ctx: typer.Context,
    min_works: Annotated[int, typer.Option("--min-works")] = 3,
    max_co_works: Annotated[int, typer.Option("--max-co-works")] = 0,
    stage: Annotated[str | None, typer.Option("--stage")] = None,
    layer: Annotated[str, _LAYER_OPT] = "core",
    limit: Annotated[int | None, typer.Option("--limit")] = 100,
    rank_by: Annotated[
        str, typer.Option("--rank-by", help="composite or one component")
    ] = "composite",
    top: Annotated[int | None, typer.Option("--top", help="ranked shortlist size")] = 50,
    format_: Annotated[str, _FORMAT_OPT] = "table",
) -> None:
    """Ranked hypotheses to check: well-used approach pairs that no work uses together."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        result = technique_service.technique_combinations(
            project,
            min_works=min_works,
            max_co_works=max_co_works,
            stage=stage,
            layer=layer,
            limit=limit,
            rank_by=rank_by,
            top=top,
        )
    _technique_out(result, render.technique_candidate_list_lines, format_)


@technique_app.command("challenges")
def technique_challenges_cmd(
    ctx: typer.Context,
    layer: Annotated[str, _LAYER_OPT] = "core",
    limit: Annotated[int | None, typer.Option("--limit")] = 100,
    format_: Annotated[str, _FORMAT_OPT] = "table",
) -> None:
    """Hypotheses to check: approaches reported as failing in one work and supported in another."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        result = technique_service.technique_challenges(project, layer=layer, limit=limit)
    _technique_out(result, render.technique_candidate_list_lines, format_)


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
    with_labels: Annotated[
        bool,
        typer.Option(
            "--with-labels", help="Add the labels and terms beside the graph (organisation class)."
        ),
    ] = False,
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
        if with_labels:
            chunks = organisation_export_service.iter_with_labels(project, format_, chunks)
        if out is None:
            for chunk in chunks:
                typer.echo(chunk, nl=False)
        else:
            with out.open("w", encoding="utf-8") as handle:
                for chunk in chunks:
                    handle.write(chunk)
            typer.echo(f"wrote {out}")


# --- Views (slice 7b, V-A) ---


@view_app.command("onion")
def view_onion_cmd(
    ctx: typer.Context,
    max_ring: Annotated[int, typer.Option("--max-ring", help="Rings to show (at most 3).")] = 2,
    edge_type: Annotated[
        list[str] | None,
        typer.Option("--edge-type", help="cites, builds-on or improves-on; repeat for several."),
    ] = None,
    include_inferred: Annotated[bool, _INCLUDE_INFERRED] = False,
    focus: Annotated[
        list[str] | None, typer.Option("--focus", help="A corpus work id; repeat for several.")
    ] = None,
    format_: Annotated[str, typer.Option("--format", help="md, json or dot.")] = "md",
    out: Annotated[Path | None, typer.Option("--out", help="Write to this file.")] = None,
) -> None:
    """The onion view, complete (the researcher's variant): rings of works around the included
    corpus with their processing depth."""
    state = _state(ctx)
    with _reporting_errors():
        if format_ not in ("md", "json", "dot"):
            raise FactoryValidationError([ValidationIssue("format", "must be md, json or dot")])
        project = _resolve_project(state)
        flt = onion_service.parse_filter(max_ring, edge_type, include_inferred, focus)
        view = onion_service.onion_view(project, flt)
        body = (
            views_service.to_json(view)
            if format_ == "json"
            else views_render.onion_dot(view)
            if format_ == "dot"
            else views_render.onion_markdown(view)
        )
        if out is None:
            typer.echo(body, nl=False)
        else:
            out.write_text(body, encoding="utf-8")
            typer.echo(f"wrote {out}")


def _emit_view(body: str, out: Path | None) -> None:
    if out is None:
        typer.echo(body, nl=False)
    else:
        out.write_text(body, encoding="utf-8")
        typer.echo(f"wrote {out}")


def _view_format(format_: str) -> None:
    if format_ not in ("md", "json", "csv"):
        raise FactoryValidationError([ValidationIssue("format", "must be md, json or csv")])


@view_app.command("coverage")
def view_coverage_cmd(
    ctx: typer.Context,
    format_: Annotated[str, typer.Option("--format", help="md, json or csv.")] = "md",
    out: Annotated[Path | None, typer.Option("--out", help="Write to this file.")] = None,
) -> None:
    """The coverage map, complete: methods and confirmed ideas by comparability group, counts
    only."""
    state = _state(ctx)
    with _reporting_errors():
        _view_format(format_)
        view = view_coverage_service.coverage_view(_resolve_project(state))
        body = (
            views_service.to_json(view)
            if format_ == "json"
            else views_render.coverage_csv(view)
            if format_ == "csv"
            else views_render.coverage_markdown(view)
        )
        _emit_view(body, out)


@view_app.command("timeline")
def view_timeline_cmd(
    ctx: typer.Context,
    group_id: Annotated[str, typer.Argument(help="A comparability group id, grp_.")],
    format_: Annotated[str, typer.Option("--format", help="md, json or csv.")] = "md",
    out: Annotated[Path | None, typer.Option("--out", help="Write to this file.")] = None,
) -> None:
    """The record timeline and per-year frontiers of one comparability group."""
    state = _state(ctx)
    with _reporting_errors():
        _view_format(format_)
        view = horizon_service.timeline_view(_resolve_project(state), group_id)
        body = (
            views_service.to_json(view)
            if format_ == "json"
            else views_render.timeline_csv(view)
            if format_ == "csv"
            else views_render.timeline_markdown(view)
        )
        _emit_view(body, out)


@view_app.command("horizon")
def view_horizon_cmd(
    ctx: typer.Context,
    format_: Annotated[str, typer.Option("--format", help="md, json or csv.")] = "md",
    out: Annotated[Path | None, typer.Option("--out", help="Write to this file.")] = None,
) -> None:
    """Activity per year: ideas, lineage edges and record counts, with the corpus horizon."""
    state = _state(ctx)
    with _reporting_errors():
        _view_format(format_)
        view = horizon_service.horizon_view(_resolve_project(state))
        body = (
            views_service.to_json(view)
            if format_ == "json"
            else views_render.horizon_csv(view)
            if format_ == "csv"
            else views_render.horizon_markdown(view)
        )
        _emit_view(body, out)


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
    kind: Annotated[RegionKind, typer.Option("--kind", help="focus or region.")],
    name: Annotated[str, typer.Option("--name", help="The region's name.")] = "",
    definition: Annotated[
        str, typer.Option("--definition", help="What it selects, at most 600.")
    ] = "",
    rules: Annotated[
        Path | None, typer.Option("--rules", help="A JSON file holding the rule set.")
    ] = None,
    facet: Annotated[
        str | None, typer.Option("--facet", help="Q@xxxxxxxx:slot, for a focus only.")
    ] = None,
    from_import: Annotated[
        str | None,
        typer.Option(
            "--from-import",
            help="Draft a region from the development part of this import (imp_); replaces "
            "--rules, and --name and --definition may be left to the draft.",
        ),
    ] = None,
) -> None:
    """Define a region or a focus as a human; take a snapshot to pin a version."""
    state = _state(ctx)
    if (rules is None) == (from_import is None):
        _fail("pass exactly one of --rules and --from-import", 2)
    bound = None if facet is None else _parse_facet(facet)
    with _reporting_errors():
        project = _resolve_project(state)
        if from_import is not None:
            drafted_name, drafted_definition, rule_set = regions_service.import_draft(
                project, from_import
            )
            name = name or drafted_name
            definition = definition or drafted_definition
        else:
            assert rules is not None
            rule_set = _read_rules(rules)
        if not name or not definition:
            _fail("--name and --definition are required with --rules", 2)
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
    name: Annotated[str | None, typer.Option("--name", help="The region's name.")] = None,
    definition: Annotated[
        str | None, typer.Option("--definition", help="What it selects, at most 600.")
    ] = None,
    rules: Annotated[
        Path | None, typer.Option("--rules", help="A JSON file holding the rule set.")
    ] = None,
) -> None:
    """Record a new definition of a region; its kind and facet stay, and what is not given keeps
    its current value."""
    state = _state(ctx)
    if name is None and definition is None and rules is None:
        _fail("give --name, --definition or --rules", 2)
    rule_set = None if rules is None else _read_rules(rules)
    with _reporting_errors():
        project = _resolve_project(state)
        kind = regions_service.region_state(project, region).kind
        old_name, old_definition, old_rules = regions_service.current_definition(project, region)
        regions_service.define_region(
            project,
            project.human_actor(),
            kind=kind,
            name=old_name if name is None else name,
            definition=old_definition if definition is None else definition,
            rules=old_rules if rule_set is None else rule_set,
            region_id=region,
        )
    typer.echo(f"revised {region}")


@regions_app.command("links")
def regions_links_cmd(
    ctx: typer.Context,
    region: Annotated[str | None, typer.Argument(help="Only links of this region, reg_.")] = None,
) -> None:
    """The declared links between pinned versions."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        links = regions_service.region_links(project, region)
    if not links:
        typer.echo("no link yet")
    for link in links:
        note = "" if link.note is None else f"  {link.note}"
        typer.echo(f"{link.link_type}  {link.source} -> {link.target}{note}")


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


@regions_app.command("adopt")
def regions_adopt_cmd(
    ctx: typer.Context,
    version: Annotated[str, typer.Argument(help="A reviewed region version, R@xxxxxxxx.")],
    source: Annotated[
        Path, typer.Option("--from", help="The source project's directory, projects/<slug>.")
    ],
) -> None:
    """Adopt a reviewed region version from another project on this machine, read-only (a human
    act); the source project is never written and no corpus count changes."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        event_id = region_adoption.adopt_region(project, project.human_actor(), source, version)
    typer.echo(f"adopted {version} ({event_id})")


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


def _csv(value: str | None, option: str) -> list[str] | None:
    if value is None:
        return None
    parts = [v.strip() for v in value.split(",") if v.strip()]
    if not parts:
        raise typer.BadParameter("give one or more names, comma-separated", param_hint=option)
    return parts


_SOURCES_OPT = typer.Option(
    "--sources",
    help="Comma list of technique-challenge, technique-combination, technique-gap, "
    "claims-limitation (default all).",
)
_PER_SOURCE_OPT = typer.Option("--per-source", help="Candidates kept per source (default 20).")
_TECH_MIN_OPT = typer.Option("--technique-min-works", help="Works each approach needs (3).")
_CO_WORKS_OPT = typer.Option("--max-co-works", help="Works that may already use both (0).")
_GROUP_OPT = typer.Option(
    "--group-claims/--no-group-claims",
    help="One claims candidate per work (default) or one per limitation row.",
)
_FULL_OPT = typer.Option(
    "--full", help="Table: print every quote and trigger (default is the compact view)."
)
_SHOW_OPT = typer.Option(
    "--show", help="Print one candidate in full (all quotes and triggers) by candidate id."
)


def _engine_table(
    result: BaseModel,
    lines: Callable[[], list[str]],
    format_: str,
    show: str | None = None,
) -> None:
    """Print a lead-engine result: the table (compact unless `--full`, one candidate with
    `--show`) or complete JSON (the one candidate with `--show`)."""
    if format_ not in ("table", "json"):
        raise typer.BadParameter("must be table or json", param_hint="--format")
    try:
        if format_ == "json" and show is not None:
            from factory.cli.render import _find

            items = getattr(result, "candidates", None) or getattr(result, "items", ())
            picked = _find(items, show)
            typer.echo(picked.model_dump_json(by_alias=True, indent=2))
            return
        if format_ == "json":
            typer.echo(result.model_dump_json(by_alias=True, indent=2))
            return
        for line in lines():
            typer.echo(line)
    except ValueError as err:
        raise typer.BadParameter(str(err), param_hint="--show") from err


@leads_app.command("candidates")
def leads_candidates_cmd(
    ctx: typer.Context,
    sources: Annotated[str | None, _SOURCES_OPT] = None,
    per_source: Annotated[int, _PER_SOURCE_OPT] = 20,
    layer: Annotated[str, _LAYER_OPT] = "core",
    technique_min_works: Annotated[int, _TECH_MIN_OPT] = 3,
    max_co_works: Annotated[int, _CO_WORKS_OPT] = 0,
    group_claims: Annotated[bool, _GROUP_OPT] = True,
    refresh: Annotated[
        bool,
        typer.Option(
            "--refresh",
            help="Drop the on-disk lead cache first and recompute (see FACTORY_LEAD_CACHE).",
        ),
    ] = False,
    top: Annotated[
        int, typer.Option("--top", min=1, help="Candidates in the table (default 20).")
    ] = 20,
    full: Annotated[bool, _FULL_OPT] = False,
    show: Annotated[str | None, _SHOW_OPT] = None,
    format_: Annotated[str, _FORMAT_OPT] = "table",
) -> None:
    """Observations to check (exploratory, read-only; records nothing). The table is compact:
    a line per candidate and its first quote; `--full` prints every quote and trigger,
    `--show <candidate_id>` one candidate in full; `--top` limits the table, JSON is complete."""
    state = _state(ctx)
    with _engine_errors():
        project = _resolve_project(state)
        chosen = _csv(sources, "--sources")
        result = lead_candidates_service(
            project,
            sources=tuple(chosen) if chosen else SOURCES,
            per_source=per_source,
            layer=layer,
            technique_min_works=technique_min_works,
            max_co_works=max_co_works,
            group_claims_by_work=group_claims,
            refresh=refresh,
        )
    _engine_table(
        result,
        lambda: render.lead_candidates_lines(result, top=top, full=full, show=show),
        format_,
        show,
    )


@leads_app.command("queue")
def leads_queue_cmd(
    ctx: typer.Context,
    sources: Annotated[str | None, _SOURCES_OPT] = None,
    per_source: Annotated[int, _PER_SOURCE_OPT] = 20,
    layer: Annotated[str, _LAYER_OPT] = "core",
    order_by: Annotated[
        str | None,
        typer.Option(
            "--order-by",
            help="Comma list of measures in turn: support, independence, verification, "
            "supportive_share, overlap, diversity, prior_hits, narrow_prior_hits, "
            "broad_prior_hits, score, basis. Default: independence, support, narrow_prior_hits, "
            "verification, diversity, score (a shared work alone never reorders).",
        ),
    ] = None,
    top: Annotated[int, typer.Option("--top", help="Entries shown (default 50).")] = 50,
    balance: Annotated[
        bool,
        typer.Option(
            "--balance/--no-balance",
            help="Share the top across the sources (default) or keep the global order.",
        ),
    ] = True,
    per_source_top: Annotated[
        int | None, typer.Option("--per-source-top", help="Entries per source when balanced.")
    ] = None,
    exclude_prior: Annotated[
        bool, typer.Option("--exclude-prior", help="Leave out candidates with a prior hit.")
    ] = False,
    recorded: Annotated[
        str,
        typer.Option(
            "--recorded",
            help="A candidate already cited by a lead: after (default), first or hide.",
        ),
    ] = "after",
    technique_min_works: Annotated[int, _TECH_MIN_OPT] = 3,
    max_co_works: Annotated[int, _CO_WORKS_OPT] = 0,
    group_claims: Annotated[bool, _GROUP_OPT] = True,
    refresh: Annotated[
        bool,
        typer.Option(
            "--refresh",
            help="Drop the on-disk lead cache first and recompute (see FACTORY_LEAD_CACHE).",
        ),
    ] = False,
    full: Annotated[bool, _FULL_OPT] = False,
    show: Annotated[str | None, _SHOW_OPT] = None,
    format_: Annotated[str, _FORMAT_OPT] = "table",
) -> None:
    """Candidates and open leads ordered by computed measures (exploratory, read-only). The
    table is compact (a line per entry, the first quote); `--full` prints every quote and
    trigger, `--show <candidate_id>` one candidate in full; JSON is complete."""
    state = _state(ctx)
    with _engine_errors():
        project = _resolve_project(state)
        chosen = _csv(sources, "--sources")
        order = _csv(order_by, "--order-by")
        result = lead_queue_service(
            project,
            order_by=tuple(order) if order else DEFAULT_ORDER,
            sources=tuple(chosen) if chosen else SOURCES,
            top=top,
            exclude_prior=exclude_prior,
            per_source=per_source,
            layer=layer,
            technique_min_works=technique_min_works,
            max_co_works=max_co_works,
            group_claims_by_work=group_claims,
            balance=balance,
            per_source_top=per_source_top,
            recorded=recorded,
            refresh=refresh,
        )
    _engine_table(
        result,
        lambda: render.lead_queue_lines(result, full=full, show=show),
        format_,
        show,
    )


@leads_app.command("stats")
def leads_stats_cmd(ctx: typer.Context, format_: Annotated[str, _FORMAT_OPT] = "table") -> None:
    """Counts of recorded leads, the hypotheses drafted from them and their outcomes."""
    state = _state(ctx)
    with _engine_errors():
        project = _resolve_project(state)
        result = lead_stats_service(project)
    _technique_out(result, render.lead_stats_lines, format_)


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
    with _reporting_errors():
        evaluated = evaluation_view_service.evaluation_detail(project, hypothesis)
    if evaluated is not None:
        for line in render.evaluation_lines(evaluated):
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


@hypotheses_app.command("evaluate")
def hypotheses_evaluate_cmd(
    ctx: typer.Context,
    hypothesis: Annotated[str, typer.Argument(help="A hypothesis id, hyp_.")],
    incomplete: Annotated[
        bool,
        typer.Option(
            "--incomplete", help="Record a progress report when a primary cell has no run yet."
        ),
    ] = False,
) -> None:
    """Evaluate a registered hypothesis: the platform computes the outcome from the recorded runs
    (or the later literature) by the rule fixed at registration. Nobody sets an outcome."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        event_id = evaluation_service.evaluate_hypothesis(
            project, hypothesis, request_incomplete=incomplete
        )
        evaluated = evaluation_view_service.evaluation_detail(project, hypothesis)
    typer.echo(f"evaluated {hypothesis}: {event_id}")
    if evaluated is not None:
        for line in render.evaluation_lines(evaluated):
            typer.echo(line)


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


# --- Experiment designs and runs (slice 6, plan XP-A) ------------------------------------------


@experiments_app.command("list")
def experiments_list_cmd(ctx: typer.Context) -> None:
    """Experiment designs with their versions and computed states."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        views = experiments_service.list_experiments(project)
    for line in render.experiment_lines(views):
        typer.echo(line)


@experiments_app.command("show")
def experiments_show_cmd(
    ctx: typer.Context, experiment: Annotated[str, typer.Argument(help="A design id, exp_.")]
) -> None:
    """One design: factor, seeds, budget used, confirmatory reads, baselines and deviations. The
    unlock nonce is not shown; `unlock` prints it once."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        view = experiments_service.experiment_view(project, experiment)
        verdicts = {} if view is None else baseline_verdicts(project, experiment)
    if view is None:
        _fail(f"unknown experiment {experiment}", 1)
    for line in render.experiment_detail_lines(view, verdicts):
        typer.echo(line)


@experiments_app.command("amend")
def experiments_amend_cmd(
    ctx: typer.Context,
    experiment: Annotated[str, typer.Argument(help="A design id, exp_.")],
    design: Annotated[Path, typer.Option("--design", help="A JSON file holding the design.")],
    reason: Annotated[str, typer.Option("--reason", help="Why the design changes.")],
    semantic: Annotated[
        bool, typer.Option("--semantic/--prose", help="Whether the change alters the design.")
    ] = True,
) -> None:
    """Replace the design of an experiment not yet frozen; `E@` is recomputed."""
    state = _state(ctx)
    try:
        data = json.loads(design.read_text())
    except (OSError, ValueError) as exc:
        _fail(f"--design {design}: {exc}", 2)
    parsed = _parse_model(ExperimentDesign, data, "design")
    with _reporting_errors():
        project = _resolve_project(state)
        experiments_service.amend_experiment(
            project, project.human_actor(), experiment, parsed, reason, semantic
        )
    typer.echo(f"amended {experiment}")


@experiments_app.command("evaluate-baselines")
def experiments_evaluate_baselines_cmd(
    ctx: typer.Context, experiment: Annotated[str, typer.Argument(help="A design id, exp_.")]
) -> None:
    """Write the verdict of every baseline that is ready and has none: what a crash between a
    reproduction's ingestion and its verdict left pending. Safe to repeat."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        if experiments_service.experiment_view(project, experiment) is None:
            raise FactoryValidationError([ValidationIssue("experiment", "unknown")])
        written = reproduction_service.evaluate_baselines(project, experiment)
    typer.echo(f"baseline verdicts written: {len(written)}")


@experiments_app.command("freeze")
def experiments_freeze_cmd(
    ctx: typer.Context, experiment: Annotated[str, typer.Argument(help="A design id, exp_.")]
) -> None:
    """Freeze a design (an act at the gate `experiments.freeze_unlock`); `E@` is then fixed."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        experiments_service.freeze_experiment(project, project.human_actor(), experiment)
        view = experiments_service.experiment_view(project, experiment)
    typer.echo(f"frozen {experiment} {view.e_version if view else ''}".rstrip())


@experiments_app.command("unlock")
def experiments_unlock_cmd(
    ctx: typer.Context, experiment: Annotated[str, typer.Argument(help="A design id, exp_.")]
) -> None:
    """Unlock confirmatory runs (an act at the gate `experiments.freeze_unlock`). Prints the nonce
    once: put it in the runner configuration; confirmatory results must carry it."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        experiments_service.unlock_experiment(project, project.human_actor(), experiment)
        nonce = experiments_service.unlock_nonce(project, experiment)
    typer.echo(f"unlocked {experiment}")
    typer.echo(f"nonce {nonce}")
    typer.echo("This is the only time the nonce is shown; confirmatory results must carry it.")


@experiments_app.command("deviation")
def experiments_deviation_cmd(
    ctx: typer.Context,
    experiment: Annotated[str, typer.Argument(help="A design id, exp_.")],
    kind: Annotated[
        str,
        typer.Option("--kind", help="planned-change-after-freeze, environment or other."),
    ],
    text_: Annotated[str, typer.Option("--text", help="What departed from the design.")],
    semantic: Annotated[
        bool, typer.Option("--semantic", help="Flag the outcome `deviated` after the unlock.")
    ] = False,
) -> None:
    """Record a departure from a frozen design (a human act, R-14)."""
    if kind not in ("planned-change-after-freeze", "environment", "other"):
        _fail(f"--kind {kind!r}: expected planned-change-after-freeze, environment or other", 2)
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        experiments_service.record_deviation(
            project,
            project.human_actor(),
            experiment,
            cast(DeviationKind, kind),
            text_,
            semantic,
        )
    typer.echo(f"recorded {kind} deviation for {experiment}")


@experiments_app.command("accept-baseline")
def experiments_accept_baseline_cmd(
    ctx: typer.Context,
    experiment: Annotated[str, typer.Argument(help="A design id, exp_.")],
    row_key: Annotated[str, typer.Argument(help="The baseline's evidence row key, rk_.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why, in at most 300 characters.")],
) -> None:
    """Accept a baseline that did not reproduce (a human act, R-122); every outcome of the design
    is then flagged `baseline-not-reproduced`."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        experiments_service.accept_baseline(
            project, project.human_actor(), experiment, row_key, rationale
        )
    typer.echo(f"accepted baseline {row_key} of {experiment}")


@runs_app.command("list")
def runs_list_cmd(
    ctx: typer.Context,
    experiment: Annotated[str, typer.Argument(help="A design id, exp_.")],
    arm: Annotated[str | None, typer.Option("--arm", help="Only this arm.")] = None,
    split: Annotated[str | None, typer.Option("--split", help="dev or confirmatory.")] = None,
) -> None:
    """The runs of a design with their state, cell and metrics."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        runs = xruns_service.xrun_list(project, experiment, arm=arm, split=split)
    for line in render.xrun_lines(runs):
        typer.echo(line)


@runs_app.command("record")
def runs_record_cmd(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help="The runner's results file (JSON, schema 1).")],
    runner: Annotated[
        str | None,
        typer.Option("--runner", help="Record as the system actor runner-NAME (a GPU runner)."),
    ] = None,
) -> None:
    """Ingest a results file for a registered run. Results enter only here (never over MCP)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        xruns_service.ingest_results(project, project.human_actor(), file, runner=runner)
    typer.echo(f"recorded {file.name}")


@app.command("benchmark-ledger")
def benchmark_ledger_cmd(
    ctx: typer.Context,
    group: Annotated[
        str | None, typer.Option("--group", help="One evidence group, by its group id.")
    ] = None,
) -> None:
    """Reported against reproduced values and own results, beside the evidence report (which
    never contains them)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        groups = ledger_service.ledger(project, group_id=group)
    for line in render.ledger_lines(groups):
        typer.echo(line)


@app.command("registry")
def registry_cmd(
    ctx: typer.Context,
    key: Annotated[
        list[str] | None,
        typer.Option("--key", help="A card, idea, property, work, trigger or ds:<name>; repeat."),
    ] = None,
    reason: Annotated[
        list[str] | None, typer.Option("--reason", help="Narrow to a reason; repeat.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Rows per page, 1 to 200.")] = 50,
    after: Annotated[str | None, typer.Option("--after", help="Continue after this id.")] = None,
) -> None:
    """Search the failed-directions registry (the researcher's variant, with closing notes)."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        page = directions_service.registry_query(
            project, key or (), reasons=reason, limit=limit, after=after
        )
    for line in render.registry_lines(page):
        typer.echo(line)


@directions_app.command("close")
def directions_close_cmd(
    ctx: typer.Context,
    text_: Annotated[str, typer.Option("--text", help="What was tried, at most 600 characters.")],
    reason: Annotated[str, typer.Option("--reason", help="Why it failed (a registry reason).")],
    key: Annotated[
        list[str],
        typer.Option("--key", help="What the direction is about: a card, idea, work, ...; repeat."),
    ],
    condition: Annotated[
        list[str] | None,
        typer.Option(
            "--condition",
            help="K=V of e_version, datasets, gpu_hours_used, models or code_commit; repeat.",
        ),
    ] = None,
) -> None:
    """Close a direction that never became a hypothesis, with the conditions it failed under (a
    human act). The row stays for good: failed here, not impossible."""
    state = _state(ctx)
    fields: dict[str, Any] = {}
    for item in condition or ():
        name, sep, value = item.partition("=")
        if not sep or name not in {
            "e_version",
            "datasets",
            "gpu_hours_used",
            "models",
            "code_commit",
        }:
            _fail(f"--condition {item!r}: expected K=V with a known K", 2)
        if name in ("datasets", "models"):
            fields.setdefault(name, []).append(value)
        else:
            fields[name] = value
    with _reporting_errors():
        project = _resolve_project(state)
        try:
            why = DirectionReason(reason)
        except ValueError:
            choices = ", ".join(r.value for r in DirectionReason)
            _fail(f"--reason {reason!r}: expected one of {choices}", 2)
        try:
            conditions = Conditions.model_validate(fields)
        except PydanticValidationError as exc:
            _fail(f"--condition: {exc.errors()[0]['msg']}", 2)
        direction_id = directions_service.close_direction(
            project, project.human_actor(), text_, why, conditions, key
        )
    typer.echo(f"closed {direction_id}")


# --- Writing from verified material (slice 7b, plan W-A) ---------------------------------------


def _scope(
    ideas: list[str] | None, groups: list[str] | None, works: list[str] | None
) -> outline_service.OutlineScope:
    return outline_service.OutlineScope(
        works="included" if not works else tuple(works),
        ideas=None if not ideas else tuple(ideas),
        groups=None if not groups else tuple(groups),
    )


_IDEA_OPT = typer.Option("--idea", help="Restrict to this confirmed idea; repeat for several.")
_GROUP_OPT = typer.Option("--group", help="Restrict to this comparability group; repeat.")
_WORK_OPT = typer.Option("--work", help="Restrict to this included work; repeat for several.")


@app.command("outline")
def outline_cmd(
    ctx: typer.Context,
    json_: Annotated[bool, typer.Option("--json", help="Print the canonical JSON.")] = False,
    idea: Annotated[list[str] | None, _IDEA_OPT] = None,
    group: Annotated[list[str] | None, _GROUP_OPT] = None,
    work: Annotated[list[str] | None, _WORK_OPT] = None,
) -> None:
    """The outline of verified material to write against, complete (the researcher's variant):
    ids and codes only. A draft pins the agent variant, which withholds label-derived limits."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        outline = outline_service.build_outline(project, _scope(idea, group, work), agent=False)
    if json_:
        typer.echo(outline_service.outline_json(outline), nl=False)
        return
    for line in render.outline_lines(outline):
        typer.echo(line)


@draft_app.command("create")
def draft_create_cmd(
    ctx: typer.Context,
    title: Annotated[str, typer.Option("--title", help="The draft's title.")],
    kind: Annotated[
        str,
        typer.Option("--kind", help="related-work, review, grant-background, horizon-note, other."),
    ],
    idea: Annotated[list[str] | None, _IDEA_OPT] = None,
    group: Annotated[list[str] | None, _GROUP_OPT] = None,
    work: Annotated[list[str] | None, _WORK_OPT] = None,
) -> None:
    """Create a draft pinned to the outline of the scope."""
    state = _state(ctx)
    with _reporting_errors():
        try:
            draft_kind = DraftKind(kind)
        except ValueError:
            raise FactoryValidationError([ValidationIssue("kind", "unknown kind")]) from None
        project = _resolve_project(state)
        draft_id = drafts_service.create_draft(
            project,
            title=title,
            kind=draft_kind,
            scope=_scope(idea, group, work),
            actor=project.human_actor(),
        )
    typer.echo(f"created {draft_id}")


@draft_app.command("list")
def draft_list_cmd(ctx: typer.Context) -> None:
    """The drafts with their pinned outline and the number of live sentences."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        drafts = drafts_service.list_drafts(project)
    for line in render.draft_list_lines(drafts):
        typer.echo(line)


@draft_app.command("show")
def draft_show_cmd(
    ctx: typer.Context, draft: Annotated[str, typer.Argument(help="A draft id, drf_.")]
) -> None:
    """One draft: sections and live sentences with class, status, flags and supports."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        found = drafts_service.get_draft(project, draft)
        sentences = [] if found is None else drafts_service.live_sentences(project, draft)
        statuses = [] if found is None else drafts_service.sentence_status(project, draft)
    if found is None:
        _fail(f"unknown draft {draft}", 1)
    for line in render.draft_detail_lines(found, sentences, statuses):
        typer.echo(line)


@draft_app.command("write")
def draft_write_cmd(
    ctx: typer.Context,
    draft: Annotated[str, typer.Argument(help="A draft id, drf_.")],
    section: Annotated[str, typer.Option("--section", help="A section id, sec_01.")],
    class_: Annotated[
        str, typer.Option("--class", help="claim, synthesis, interpretive or structural.")
    ],
    text: Annotated[str, typer.Option("--text", help="One sentence.")],
    support: Annotated[
        list[str] | None, typer.Option("--support", help="A support, <kind>:<ref>; repeat.")
    ] = None,
    supersedes: Annotated[
        str | None, typer.Option("--supersedes", help="A live sentence this one replaces.")
    ] = None,
    order: Annotated[
        int | None, typer.Option("--order", help="Its place in the section; default: last.")
    ] = None,
) -> None:
    """Write one sentence as the researcher (author human). It passes the same checks as an
    agent's; a refusal prints each issue and writes nothing."""
    state = _state(ctx)
    with _reporting_errors():
        try:
            cls = SentenceClass(class_)
        except ValueError:
            raise FactoryValidationError([ValidationIssue("class", "unknown class")]) from None
        project = _resolve_project(state)
        result = drafts_service.write_sentences(
            project,
            draft,
            [
                drafts_service.SentenceInput(
                    section_id=section,
                    cls=cls,
                    text=text,
                    supports=list(support or []),
                    order=order,
                    supersedes=supersedes,
                )
            ],
            actor=project.human_actor(),
        )
    if result.rejected:
        for issue in result.rejected[0].issues:
            typer.echo(f"{issue.field}: {issue.reason}", err=True)
        raise typer.Exit(1)
    typer.echo(f"wrote {result.written[0]}")


@draft_app.command("repin")
def draft_repin_cmd(
    ctx: typer.Context,
    draft: Annotated[str, typer.Argument(help="A draft id, drf_.")],
    work: Annotated[list[str] | None, _WORK_OPT] = None,
    idea: Annotated[list[str] | None, _IDEA_OPT] = None,
    group: Annotated[list[str] | None, _GROUP_OPT] = None,
) -> None:
    """Pin a draft to a fresh outline, of the same scope unless one is named. New sections are
    added; sentences whose supports left the outline read as off-outline."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        scope = _scope(idea, group, work) if idea or group or work else None
        drafts_service.repin_outline(project, draft, scope, actor=project.human_actor())
    typer.echo(f"repinned {draft}")


@draft_app.command("reorder")
def draft_reorder_cmd(
    ctx: typer.Context,
    draft: Annotated[str, typer.Argument(help="A draft id, drf_.")],
    section: Annotated[str, typer.Argument(help="A section id, sec_01.")],
    sentences: Annotated[list[str], typer.Argument(help="The section's live sentences, in order.")],
) -> None:
    """Set the order of a section's live sentences; name each exactly once."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        drafts_service.reorder(project, draft, section, sentences, actor=project.human_actor())
    typer.echo(f"reordered {section}")


@draft_app.command("status")
def draft_status_cmd(
    ctx: typer.Context, draft: Annotated[str, typer.Argument(help="A draft id, drf_.")]
) -> None:
    """Counts by status, each sentence's computed status, and the audit with its rate."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        found = drafts_service.get_draft(project, draft)
        if found is None:
            raise FactoryValidationError([ValidationIssue("draft_id", "unknown draft")])
        lines = render.draft_status_lines(
            found,
            drafts_service.sentence_status(project, draft),
            draft_audit_service.audit_report(project, draft),
            draft_audit_service.audit_sheet(project, draft),
        )
    for line in lines:
        typer.echo(line)


@draft_app.command("render")
def draft_render_cmd(
    ctx: typer.Context,
    draft: Annotated[str, typer.Argument(help="A draft id, drf_.")],
    clean: Annotated[
        bool, typer.Option("--clean/--review", help="Clean prose, or every sentence with quotes.")
    ] = False,
    out: Annotated[
        Path | None, typer.Option("--out", help="Write here, outside the project; default stdout.")
    ] = None,
) -> None:
    """The draft as Markdown, to stdout or a path you name, never under the project."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        if out is not None:
            drafts_service.refuse_project_path(project, out)
        body = drafts_service.draft_render(project, draft, "clean" if clean else "review")
    _emit([body], out)


@draft_app.command("audit")
def draft_audit_cmd(
    ctx: typer.Context,
    draft: Annotated[str, typer.Argument(help="A draft id, drf_.")],
    draw: Annotated[bool, typer.Option("--draw", help="Draw a sample first.")] = False,
) -> None:
    """The audit of the draft's supported verdicts; `--draw` draws a new sample first."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        if draw:
            typer.echo(f"drew {draft_audit_service.draw_audit(project, draft)}")
        found = drafts_service.get_draft(project, draft)
        if found is None:
            raise FactoryValidationError([ValidationIssue("draft_id", "unknown draft")])
        lines = render.draft_status_lines(
            found,
            [],
            draft_audit_service.audit_report(project, draft),
            draft_audit_service.audit_sheet(project, draft),
        )
    for line in lines[2:]:
        typer.echo(line)


@draft_app.command("label")
def draft_label_cmd(
    ctx: typer.Context,
    audit: Annotated[str, typer.Argument(help="An audit id, dau_.")],
    verdict: Annotated[str, typer.Argument(help="A verdict id, svd_.")],
    correct: Annotated[
        bool | None, typer.Option("--correct/--incorrect", help="Your label of the verdict.")
    ] = None,
    note: Annotated[str | None, typer.Option("--note", help="At most 300 characters.")] = None,
) -> None:
    """Label one sampled verdict. A later label of it replaces the earlier."""
    state = _state(ctx)
    with _reporting_errors():
        if correct is None:
            raise FactoryValidationError(
                [ValidationIssue("label", "give --correct or --incorrect")]
            )
        project = _resolve_project(state)
        label = AuditLabel.CORRECT if correct else AuditLabel.INCORRECT
        draft_audit_service.record_audit(
            project, audit, verdict, label, note, actor=project.human_actor()
        )
    typer.echo(f"labelled {verdict} {label.value}")


@draft_app.command("release")
def draft_release_cmd(
    ctx: typer.Context, draft: Annotated[str, typer.Argument(help="A draft id, drf_.")]
) -> None:
    """Release the draft through the gate `writing.release`. A refusal prints the blocking counts
    and writes nothing."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        draft_release_service.release(project, draft, actor=project.human_actor())
    typer.echo(f"released {draft}")


def _human_verdict(
    unit: draft_verify_service.VerifyUnit,
    verdict: str | None,
    sentence_span: str | None,
    support_span: list[str] | None,
    note: str | None,
) -> draft_verify_service.VerdictInput:
    """The verdict on a unit already printed: what the options left out is asked for now, as the
    spans can only be chosen once the unit has been read."""
    chosen = verdict if verdict is not None else str(typer.prompt("verdict"))
    if sentence_span is None and chosen != Verdict.SUPPORTED.value:
        sentence_span = str(typer.prompt("the part of the sentence you judge"))
    pairs = [(ref, quote) for ref, _, quote in (s.partition("=") for s in support_span or [])]
    if not pairs and chosen != Verdict.UNSUPPORTED.value:
        for support in unit.supports:
            quote = str(
                typer.prompt(
                    f"substring of {support.ref} (empty to skip)", default="", show_default=False
                )
            )
            if quote:
                pairs.append((support.ref, quote))
    try:
        return draft_verify_service.VerdictInput(
            verdict=Verdict(chosen),
            sentence_span=sentence_span,
            support_spans=[SupportSpan(ref=ref, substring=quote) for ref, quote in pairs],
            note=note,
        )
    except ValueError:
        raise FactoryValidationError(
            [ValidationIssue("verdict", "unknown verdict or malformed --support-span")]
        ) from None


@draft_app.command("verify")
def draft_verify_cmd(
    ctx: typer.Context,
    draft: Annotated[str, typer.Argument(help="A draft id, drf_.")],
    verdict: Annotated[
        str | None,
        typer.Option(
            "--verdict",
            help="supported, partial, unsupported, contradicted or overstated; asked if left out.",
        ),
    ] = None,
    sentence_span: Annotated[
        str | None, typer.Option("--sentence-span", help="The part of the sentence you judge.")
    ] = None,
    support_span: Annotated[
        list[str] | None,
        typer.Option("--support-span", help="<support>=<substring of its span>; repeat."),
    ] = None,
    note: Annotated[str | None, typer.Option("--note", help="At most 300 characters.")] = None,
) -> None:
    """Verify the next sentence as the researcher (spec ruling 16: a human may verify an agent's
    sentence, never their own): print the unit, ask for what the options left out, then record
    your verdict in the same command, as a task is leased to one session. A refusal, or leaving
    the prompts, gives the unit back."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        actor = project.human_actor()
        unit = draft_verify_service.verify_next(project, draft, actor=actor)
        if unit is None:
            typer.echo("none left")
            return
        typer.echo(unit.model_dump_json(indent=2))
        try:
            item = _human_verdict(unit, verdict, sentence_span, support_span, note)
            verdict_id = draft_verify_service.verify_record(
                project, unit.task_id, item, actor=actor
            )
        except (FactoryError, typer.Abort):
            draft_verify_service.verify_release(project, unit.task_id, actor=actor)
            raise
    typer.echo(f"recorded {verdict_id}")


@draft_app.command("withdraw")
def draft_withdraw_cmd(
    ctx: typer.Context,
    sentence: Annotated[str, typer.Argument(help="A sentence id, snt_.")],
    reason: Annotated[str, typer.Option("--reason", help="Why it is withdrawn.")],
) -> None:
    """Withdraw a live sentence; it stays in the log."""
    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        drafts_service.withdraw(project, sentence, reason, actor=project.human_actor())
    typer.echo(f"withdrew {sentence}")

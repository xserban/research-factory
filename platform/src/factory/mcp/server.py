"""The MCP server. Tools parse input, call a service and format output; each call runs as the
principal and session its transport names (`factory.mcp.sessions`)."""

import json
import os
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal, TypeVar, cast, get_args

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from pydantic import Field, JsonValue, StringConstraints, TypeAdapter, ValidationError

from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.events.envelope import Actor
from factory.hypotheses.design import design_version
from factory.lineage.graph import GraphFilter
from factory.mcp import conventions
from factory.mcp.authz import authorising
from factory.mcp.conventions import (
    PAGE_LIMIT,
    dotted,
    guarded,
    paginate,
    parse_input,
    parse_routes,
    parse_stage,
    spec_path,
    withhold,
)
from factory.mcp.elicit import confirm_human_act, elicit_human_selection
from factory.mcp.sessions import (
    THIS_SESSION,
    CallContext,
    ContextProvider,
    ScopedServer,
    ThisSession,
    current_call,
    stdio_provider,
)
from factory.mcp.unit_cap import UnitCap
from factory.mining.taxonomy import taxonomy_to_json
from factory.model.appraisal_events import AnswerInput
from factory.model.base import StrictModel
from factory.model.budgets import REQUESTS_SEARCH
from factory.model.cards import CardKind, PropertyDef, QuoteBasis
from factory.model.chase import ChaseDirection
from factory.model.curation import CurationKind
from factory.model.decisions import DecisionItem, DecisionLevel
from factory.model.drafts import DraftKind, SupportSpan, Verdict
from factory.model.experiments import Cell, ExperimentDesign
from factory.model.extraction import ClaimInput, ExtractedRowInput, MinerScope
from factory.model.findings import ContradictionInput
from factory.model.fulltext import Route
from factory.model.hypotheses import (
    DiscardReason,
    HypothesisSpec,
    LeadDecision,
    LeadInput,
    ReviewInput,
)
from factory.model.inbox import Basis
from factory.model.intuition import (
    ConceptInput,
    ConceptState,
    InterpretationInput,
    ReviewState,
    UseBasisInput,
)
from factory.model.lineage import DEFAULT_STATUSES, EdgeStatus, RelationProposal
from factory.model.notices import AssessmentDecision
from factory.model.project import RigorMode
from factory.model.protocol import CriterionEffect, PressFinding, ProtocolSpec, ScreeningStage
from factory.model.question import QuestionSpec
from factory.model.references import Decision, Direction, LayerAssigned, LinkState
from factory.model.regions import Facet, MemberBasis, RegionKind
from factory.model.reviews import ReviewDecision, ReviewKind
from factory.model.reviews import ReviewState as RequestState
from factory.model.screening import CalibrationLabelled, Channel, PassLabel, ScreeningItem
from factory.model.screening_check import (
    DEFAULT_MEASUREMENT_SIZE,
    DEFAULT_TUNING_SIZE,
    CheckKind,
)
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.model.seed import SeedSpec
from factory.model.taxonomies import ProposalKind
from factory.modules.contract import Autonomy, PolicyKind
from factory.regions.rules import MemberType, RuleSet
from factory.services import agent_view as agent_view_service
from factory.services import agreement as agreement_service
from factory.services import appraisal_judgements as appraisal_service
from factory.services import appraisal_passes as appraisal_passes_service
from factory.services import audit as audit_service
from factory.services import benchmark_ledger as ledger_service
from factory.services import briefing as briefing_service
from factory.services import budgets as budget_service
from factory.services import calibration as calibration_service
from factory.services import cards as cards_service
from factory.services import chase as chase_service
from factory.services import concepts as concepts_service
from factory.services import conclusions as conclusions_service
from factory.services import consolidation as consolidation_service
from factory.services import contributions as contributions_service
from factory.services import core_works as core_works_service
from factory.services import coverage as coverage_service
from factory.services import curation as curation_service
from factory.services import decisions as decisions_service
from factory.services import dedup as dedup_service
from factory.services import develop_render as develop_render_service
from factory.services import digest as digest_service
from factory.services import directions as directions_service
from factory.services import document_convert as document_convert_service
from factory.services import document_read as document_read_service
from factory.services import draft_audit as draft_audit_service
from factory.services import draft_release as draft_release_service
from factory.services import draft_verify as draft_verify_service
from factory.services import drafts as drafts_service
from factory.services import evaluation_view as evaluation_view_service
from factory.services import evidence as evidence_service
from factory.services import experiments as experiments_service
from factory.services import exports as exports_service
from factory.services import extraction as extraction_service
from factory.services import extraction_agreement as extraction_agreement_service
from factory.services import extraction_audit as extraction_audit_service
from factory.services import feed as feed_service
from factory.services import feed_read as feed_read_service
from factory.services import finders as findings_service
from factory.services import fulltext as fulltext_service
from factory.services import fulltext_status as fulltext_status_service
from factory.services import gates as gates_service
from factory.services import grey as grey_service
from factory.services import horizon as horizon_service
from factory.services import human_pass as human_pass_service
from factory.services import hypotheses as hypotheses_service
from factory.services import hypothesis_review as review_service
from factory.services import ideas as ideas_service
from factory.services import inbox as inbox_service
from factory.services import interpretations as interpretations_service
from factory.services import lab_library as lab_library_service
from factory.services import labels as labels_service
from factory.services import leads as leads_service
from factory.services import ledger as contribution_ledger_service
from factory.services import lineage as graph_service
from factory.services import manuscript_verify as manuscript_verify_service
from factory.services import manuscripts as manuscripts_service
from factory.services import matching as matching_service
from factory.services import miner_gold as miner_gold_service
from factory.services import mining as mining_service
from factory.services import notices as notices_service
from factory.services import onion as onion_service
from factory.services import outline as outline_service
from factory.services import pages as pages_service
from factory.services import passes as passes_service
from factory.services import probe as probe_service
from factory.services import progress as progress_service
from factory.services import properties as properties_service
from factory.services import protocol as protocol_service
from factory.services import pubmed_slices
from factory.services import question as question_service
from factory.services import ranking as ranking_service
from factory.services import ranking_model as ranking_model_service
from factory.services import reference_layers as layers_service
from factory.services import reference_resolve as reference_resolve_service
from factory.services import references as references_service
from factory.services import regions as regions_service
from factory.services import relations as relations_service
from factory.services import reviews as reviews_service
from factory.services import screening as screening_service
from factory.services import screening_check as check_service
from factory.services import search as search_service
from factory.services import seeds as seeds_service
from factory.services import shared_mining as shared_mining_service
from factory.services import snowball as snowball_service
from factory.services import tasks as tasks_service
from factory.services import taxonomies as taxonomies_service
from factory.services import taxonomy_agreement as taxonomy_agreement_service
from factory.services import terms as terms_service
from factory.services import trace as trace_service
from factory.services import view_coverage as view_coverage_service
from factory.services import watch as watch_service
from factory.services import xruns as xruns_service
from factory.services.access_log import AccessLog
from factory.services.agent_view import require_pass_opened as _require_pass_opened
from factory.services.context import Project, list_projects
from factory.services.context import open_project as open_as
from factory.services.extraction import ExtractResult
from factory.services.gate_status import GateStatusRow, gates_status
from factory.services.hypothesis_gates import GateName, gate_policy
from factory.services.lab import Lab, lab_exists, open_lab
from factory.services.living_hooks import default_hooks
from factory.services.members import roles_of
from factory.services.rate_limit import RateLimiter
from factory.services.results import BatchResult, ItemError
from factory.services.search import list_works
from factory.services.seeds import SeedOutcome
from factory.services.withholding import held_out_tokens, seed_id_tokens
from factory.services.workspace import workspace_counts
from factory.services.xrun_accounting import hidden_acceptances
from factory.sources.fulltext.base import FullTextRoute
from factory.sources.fulltext.registry import default_routes
from factory.sources.registry import SourceFactory, default_sources

_M = TypeVar("_M", bound=StrictModel)
_SYSTEM_CLOCK = SystemClock()
_FIELD_NAMES = {"text": "query"}  # QuerySpec calls the query text `text`; the tool calls it `query`


class _LinkItem(StrictModel):
    """One `inbox_add` item as sent: the link, a relayed human note, or an agent's basis."""

    link: str
    note: str | None = None
    basis: Basis | None = None
    page: bool = False


class _ProbeQuery(StrictModel):
    """One probe request as an agent states it: `query` is the text, `kind` defaults to keyword."""

    source: str
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    kind: QueryKind = QueryKind.KEYWORD
    filters: dict[str, str] = Field(default_factory=dict)


MCP_EXPORT_MAX_WORKS = 2000
"""The most works one `export_bibliography` call returns; larger exports use the CLI."""


def build_server(
    settings: Settings,
    clock: Clock = _SYSTEM_CLOCK,
    sources: Mapping[str, SourceFactory] | None = None,
    fulltext_routes: Callable[[], Mapping[Route, FullTextRoute]] | None = None,
    context: ContextProvider | None = None,
    auth: AuthSettings | None = None,
    token_verifier: TokenVerifier | None = None,
    limiter: RateLimiter | None = None,
    cap: UnitCap | None = None,
) -> MCPServer:
    """The factory's MCP server. `context` names each call's principal and session; by default the
    local user and one session per process, as on stdio. `auth` and `token_verifier` are the HTTP
    transport's (`factory.mcp.http`). `cap` is the unit cap of a headless run; by default it is
    read from `FACTORY_UNIT_CAP` and `FACTORY_RUN_ID` (none: no cap).

    `fulltext_routes`, when given, is called once per `fulltext_fetch` call to build that call's
    routes; tests use it to supply stubs. By default each call builds `default_routes(settings)`,
    so no arXiv version answer outlives the call that asked for it.
    """
    provider = stdio_provider(settings, clock) if context is None else context
    unit_cap = UnitCap.from_env(os.environ) if cap is None else cap
    adapters = dict(default_sources() if sources is None else sources)
    session = THIS_SESSION

    def open_for_call(slug: str, call: CallContext) -> Project:
        return open_as(settings, slug, session=call.session, clock=clock, principal=call.principal)

    def open_registry(lab_session: str) -> Lab | None:
        return (
            open_lab(settings, session=lab_session, clock=clock) if lab_exists(settings) else None
        )

    remote = context is not None
    log = AccessLog(settings.root) if remote or (settings.root / ".server").is_dir() else None
    server = ScopedServer(
        "factory",
        wrap=authorising(provider, open_for_call, open_registry, log, clock, limiter),
        auth=auth,
        token_verifier=token_verifier,
    )

    def open_project(
        settings: Settings, slug: str, *, session: ThisSession, clock: Clock
    ) -> Project:
        """Every tool opens a project as the principal and session of its call."""
        return open_for_call(slug, current_call())

    def make_agent_actor(
        settings: Settings, session: ThisSession, role: str, model: str, skill: str
    ) -> Actor:
        """The agent of this call, acting for its principal."""
        call = current_call()
        return conventions.make_agent_actor(
            settings, call.session, role, model, skill, call.principal
        )

    def _fetch_routes() -> Mapping[Route, FullTextRoute]:
        return default_routes(settings) if fulltext_routes is None else fulltext_routes()

    def _reply(
        project_slug: str,
        fn: Callable[[], JsonValue],
        rename: Callable[[str], str] = str,
        *,
        include_work_ids: bool = True,
        seed_ids_only: bool = False,
    ) -> dict[str, JsonValue]:
        """`guarded`, with every agent-facing response scrubbed of held-out identifiers (R-20).

        A success is scrubbed by its tool (`_withheld`), and a refusal here, as defence in depth:
        the services never name a held-out seed. Tools that list works pass
        `include_work_ids=False`; see `_held_out_tokens`. The feed tools pass `seed_ids_only=True`
        (see `seed_id_tokens`)."""
        result = guarded(fn, rename)
        if result["ok"] is True:
            return result
        try:
            opened = open_project(settings, project_slug, session=session, clock=clock)
        except ProjectNotFoundError:
            return result
        tokens = (
            seed_id_tokens(opened) if seed_ids_only else _held_out_tokens(opened, include_work_ids)
        )
        scrubbed = withhold(result, tokens)
        return scrubbed if isinstance(scrubbed, dict) else result

    @server.tool()
    def project_status(project: str) -> dict[str, JsonValue]:
        """Report a project's rigor mode, event counts, task queue state, derived `stage` (null to
        a session that has joined a pass) and `human`: what waits on the researcher, each with the
        command that does it. Imports, conversion and gate decisions are the researcher's acts on
        the CLI: relay the command, there is no tool for them."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            return agent_view_service.status_view(opened)

        return _reply(project, status)

    @server.tool()
    def whoami(project: str | None = None) -> dict[str, JsonValue]:
        """Who this session acts for: the principal, the session and the roles held, on every
        project or on `project`. With `project`, also the workspace counts, which a session that
        has joined a pass is not given. Read-only."""

        def identify() -> JsonValue:
            call = current_call()
            principal = call.principal
            data: dict[str, JsonValue] = {
                "user": principal.user,
                "credential": principal.credential,
                "channel": principal.channel.value,
                "session": call.session,
            }
            slugs = list_projects(settings) if project is None else [project]
            roles: dict[str, JsonValue] = {}
            for slug in slugs:
                opened = open_project(settings, slug, session=session, clock=clock)
                held: list[JsonValue] = [
                    role.value for role in sorted(roles_of(opened, principal.user))
                ]
                roles[slug] = held
            data["roles"] = roles
            if project is not None:
                opened = open_project(settings, project, session=session, clock=clock)
                if not passes_service.is_pass_session(opened, call.session):
                    data["workspace"] = workspace_counts(opened, principal.user)
            return data

        return guarded(identify)

    @server.tool()
    def search_run(
        project: str,
        source: str,
        query: str,
        role: str,
        model: str,
        skill: str,
        kind: str = "keyword",
        purpose: str = "search",
        limit: int | None = None,
        resume_run: str | None = None,
        deviation_id: str | None = None,
        filters: dict[str, str] | None = None,
    ) -> dict[str, JsonValue]:
        """Run a literature query against OpenAlex or arXiv exhaustively; every raw page is archived and counts are recorded.

        `filters` are the source's filters exactly as the protocol plans them (OpenAlex, e.g.
        `{"from_publication_date": "2025-01-01", "language": "en"}`); a planned query matches
        only with the same filters.

        Set `resume_run` to a partial or failed run of the same query to continue it from where
        it stopped; `source`, `query` and `kind` must then restate that run's query. In a pilot
        or systematic project a query the protocol does not plan needs a `deviation_id` recorded
        against the current protocol.
        """  # noqa: E501

        def search() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            spec = _spec(source, query, kind, purpose, limit, filters or {})
            budget_service.require_for(opened, actor, REQUESTS_SEARCH)
            if resume_run is not None:
                query_id = search_service.resume_query_id(opened, resume_run, spec)
            else:
                query_id = search_service.register_query(
                    opened, actor, spec, sources=adapters, deviation_id=deviation_id
                )
            summary = search_service.run_query(
                opened, query_id, sources=adapters, resume_run=resume_run, actor=actor
            )
            return _withheld(opened, summary.model_dump(mode="json"))

        return _reply(project, search)

    @server.tool()
    def search_chase(
        project: str, directions: list[str], role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Chase citations from the included works: the platform builds the queries.

        `directions` is `backward` (works the included works cite), `forward` (works citing
        them) or both. Refused while any work is pending a final outcome, past the `snowball_plan`
        maximum of forward rounds (a forward chase uses one up), and when no included
        work has an OpenAlex id. Never write chase queries by hand; follow with `dedup_run`."""

        def chase() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = _directions(directions)
            summary = chase_service.search_chase(opened, actor, parsed, sources=adapters)
            return _withheld(opened, summary.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, chase, include_work_ids=False)

    @server.tool()
    def search_slice(
        project: str,
        query_id: str,
        role: str,
        model: str,
        skill: str,
        run: bool = False,
        first_year: int = 1900,
        deviation_id: str | None = None,
    ) -> dict[str, JsonValue]:
        """Split a capped PubMed query (partial, note `esearch-cap`) by publication date.

        The platform counts by year, then month, then day until every slice is within PubMed's
        9,999 cap; nothing is guessed and no model is involved. Without `run` it returns the plan
        (slices and PubMed's counts) and writes nothing. With `run` it registers each non-empty
        slice as its own search, the slice term verbatim, runs it, and returns the report: the
        slices against the unsplit count, with any difference stated. Running again continues.
        In a pilot or systematic project the slices are not planned queries: pass a
        `deviation_id` recorded against the current protocol."""

        def slice_() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            if not run:
                plan = pubmed_slices.propose_slices(
                    opened, query_id, sources=adapters, first_year=first_year
                )
                return {
                    "parent_count": plan.parent_count,
                    "slice_total": plan.total,
                    "counts_requested": plan.counts_requested,
                    "slices": [
                        {
                            "start": s.window.start.isoformat(),
                            "end": s.window.end.isoformat(),
                            "unit": s.window.unit,
                            "count": s.count,
                            "over_cap": s.over_cap,
                        }
                        for s in plan.slices
                    ],
                }
            budget_service.require_for(opened, actor, REQUESTS_SEARCH)
            summary = pubmed_slices.run_slices(
                opened,
                actor,
                query_id,
                sources=adapters,
                deviation_id=deviation_id,
                first_year=first_year,
            )
            return _withheld(opened, summary.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, slice_, include_work_ids=False)

    @server.tool()
    def dedup_run(project: str, role: str, model: str, skill: str) -> dict[str, JsonValue]:
        """Find and record duplicate works; merges are reversible."""

        def dedup() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            make_agent_actor(settings, session, role, model, skill)
            report = dedup_service.dedup_run(opened).model_dump(mode="json")
            return _withheld(opened, report)

        return _reply(project, dedup)

    @server.tool()
    def ranking_compute(project: str, role: str, model: str, skill: str) -> dict[str, JsonValue]:
        """Rank the records still to be screened by similarity to the development seeds, with a
        local embedding model (decision 116). The ranking only orders; it judges, includes and
        excludes nothing, and held-out seeds are never used. Runs offline from supplied weights
        (`FACTORY_RANKER_MODEL`); refused with the remedy when the extra or weights are missing.
        Returns the model, the weights hash and the count, not the order."""

        def rank() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            make_agent_actor(settings, session, role, model, skill)
            embedder = ranking_model_service.Specter2Embedder()
            event = ranking_service.compute_ranking(opened, embedder)
            return _withheld(opened, event.model_dump(mode="json", exclude={"order"}))

        return _reply(project, rank)

    @server.tool()
    def gate_status(project: str) -> dict[str, JsonValue]:
        """Per decision gate: its policy kind and source, the acts passed at each autonomy level,
        and whether a human audit was drawn. No fraction, minimum, sample size, label or error
        rate is returned. Read-only. Refused to a session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            hidden = hidden_acceptances(opened)
            rows: list[JsonValue] = [
                _without_hidden_acceptances(row, hidden).agent_view().model_dump(mode="json")
                for row in gates_status(opened)
            ]
            return _withheld(opened, {"gates": rows}, include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def watch_status(project: str) -> dict[str, JsonValue]:
        """Per watched source: last cycle, next due, mode, window start, consecutive failures;
        and the open cycle. Read-only. Refused to a session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            report = watch_service.watch_status(opened).model_dump(mode="json")
            return _withheld(opened, report)

        return _reply(project, status)

    @server.tool()
    def watch_run(
        project: str, role: str, model: str, skill: str, force: bool = False
    ) -> dict[str, JsonValue]:
        """Run the project's due watch cycle: every planned query of every due source, then
        incremental deduplication; the platform builds the queries. `force` runs every watched
        source whether or not it is due. Writes nothing and returns `cycle: null` when nothing is
        due. An open cycle is resumed. Refused to a session that has joined a pass."""

        def run_cycle() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            summary = watch_service.watch_run(
                opened,
                sources=adapters,
                trigger="agent",
                actor=actor,
                force=force,
                after_runs=default_hooks(adapters),
            )
            if summary is None:
                return {"cycle": None}
            report = summary.model_dump(mode="json", exclude={"new_work_ids"})
            report["new_works"] = len(summary.new_work_ids)
            return _withheld(opened, {"cycle": report})

        return _reply(project, run_cycle)

    def _feed_source() -> feed_service.FeedSource:
        """The arXiv adapter the feed fetches with: the watch's own factory, so an injected
        adapter is honoured in tests."""
        factory = adapters["arxiv"] if "arxiv" in adapters else default_sources()["arxiv"]
        return cast(feed_service.FeedSource, factory(settings, clock))

    @server.tool()
    def feed_list(
        project: str,
        role: str,
        model: str,
        skill: str,
        top: int = 30,
        ranking_id: str | None = None,
    ) -> dict[str, JsonValue]:
        """The latest feed ranking (or `ranking_id`) as at most `top` items: rank, score, whether
        the item is an exploration pick, its nearest reference work, the researcher's reaction and
        whether it was sent to the inbox. Read-only; the reactions and sends are the researcher's
        acts on the CLI, there is no tool for them. Refused to a session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            make_agent_actor(settings, session, role, model, skill)
            report = feed_read_service.feed_list(opened, ranking_id=ranking_id, top=top)
            return _withheld(opened, report.model_dump(mode="json"), seed_ids_only=True)

        return _reply(project, listing, seed_ids_only=True)

    @server.tool()
    def feed_run(
        project: str, role: str, model: str, skill: str, dry_run: bool = False
    ) -> dict[str, JsonValue]:
        """Run the project's feed cycle now: fetch the listings of the window, then rank the new
        entries against the reference works with the local embedding model. Runs only when the
        cadence says it is due. The feed's events are recorded as this agent, with its model,
        skill and the call's arguments as input. `dry_run` fetches and writes nothing. Refused to
        a session that has joined a pass."""

        def run_cycle() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            result = feed_service.feed_run(
                opened,
                feed_service.LazyEmbedder(None, ranking_model_service.Specter2Embedder),
                _feed_source(),
                due=True,
                dry_run=dry_run,
                actor=actor,
            )
            return _withheld(opened, result.model_dump(mode="json"), seed_ids_only=True)

        return _reply(project, run_cycle, seed_ids_only=True)

    @server.tool()
    def feed_status(project: str, role: str, model: str, skill: str) -> dict[str, JsonValue]:
        """The feed's configuration, the last complete fetch window, whether a run is due, the
        last ranking and the counts of entries, fetches, rankings, reactions and sends. Read-only.
        Refused to a session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            make_agent_actor(settings, session, role, model, skill)
            report = feed_service.feed_status(opened)
            return _withheld(opened, report.model_dump(mode="json"), seed_ids_only=True)

        return _reply(project, status, seed_ids_only=True)

    @server.tool()
    def notice_list(project: str) -> dict[str, JsonValue]:
        """Notices of retraction, correction or concern about works the review depends on, with
        source, date (null when the source states none) and the latest human assessment. Read-only;
        a seed's work reads as any corpus work. Refused to a session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            views = notices_service.notice_views(opened)
            return _withheld(
                opened,
                {"count": len(views), "notices": [v.model_dump(mode="json") for v in views]},
                include_work_ids=False,
            )

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def conclusion_status(project: str) -> dict[str, JsonValue]:
        """The researcher's registered conclusions as computed state: each id, whether it is
        unchanged, changed, basis-affected or new since the last snapshot, the affected basis
        references and the fact diff. Never the statement: a human judgement is not evidence.
        Read-only; a seed's work reads as any corpus work. Refused to a session that has joined a
        pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            diffs = conclusions_service.conclusion_diff(opened)
            return _withheld(
                opened,
                {"conclusions": [d.model_dump(mode="json") for d in diffs]},
                include_work_ids=False,
            )

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def digest_get(project: str, since: str | None = "last") -> dict[str, JsonValue]:
        """The computed digest of the project since `since` (`last`: the last recorded digest; an
        event id; null: the start): new candidates with the queries that returned them, counts of
        open human decisions, notices, versions, conclusion changes, failed runs, overdue watches
        and the update flow. No abstract, verdict, conclusion statement or seed information. It
        never records a digest. Refused to a session that has joined a pass."""

        def get() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            built = digest_service.agent_digest(digest_service.digest_build([opened], since=since))
            return _withheld(opened, built.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, get, include_work_ids=False)

    @server.tool()
    def notice_assess(
        project: str,
        notice_id: str,
        decision: str,
        rationale: str,
        fields: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """The human's assessment of a notice, relayed (decision 37): `exclude` or `keep-flagged`
        for a retraction, withdrawal or expression of concern; `no-effect` or `affects` (with the
        affected `fields`) for a correction. Recorded as the human; a later one supersedes it.
        Refused to a session that has joined a pass."""

        def assess() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            try:
                chosen = AssessmentDecision(decision)
            except ValueError:
                raise FactoryValidationError(
                    [ValidationIssue("decision", f"must be {_choices(AssessmentDecision)}")]
                ) from None
            channel, said = confirm_human_act(
                f"Assessment of notice {notice_id}",
                {"decision": chosen.value, "rationale": rationale},
                {"decision": tuple(d.value for d in AssessmentDecision)},
            )
            event_id = notices_service.assess_notice(
                opened,
                opened.human_actor(),
                notice_id,
                AssessmentDecision(said["decision"]),
                fields=tuple(fields or ()),
                rationale=said["rationale"],
                channel=channel,
            )
            return {"event_id": event_id}

        return _reply(project, assess, include_work_ids=False)

    @server.tool()
    def question_record(
        project: str,
        spec: dict[str, JsonValue],
        role: str,
        model: str,
        skill: str,
        raw_goal: str | None = None,
        reason: str | None = None,
        decision_ids: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """Record the question. `raw_goal`, when given, is stored verbatim first. A new version
        needs a `reason`; an unchanged spec writes nothing. `decision_ids` are the selected
        `questions` decisions it implements; pilot and systematic projects refuse a new version
        without one."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = parse_input(QuestionSpec, spec, "spec")
            result = question_service.record_question(
                opened, actor, parsed, reason=reason, raw_goal=raw_goal, decision_ids=decision_ids
            )
            return {
                "question_id": result.question_id,
                "created": result.created,
                "goal_event_id": result.goal_event_id,
            }

        return _reply(project, record, rename=spec_path)

    @server.tool()
    def seed_add(
        project: str,
        seeds: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
        decision_ids: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """Add seeds by identifier (doi, arxiv, openalex or pmid) and look each one up. Each seed is
        written or rejected on its own; rejections name the item by index and field.
        `decision_ids` are the selected `seeds` decisions the batch implements; pilot and
        systematic projects refuse the whole call without one. A failed binding (no id, an
        unknown, wrong-level, superseded or unselected decision) refuses the whole batch, before
        any per-item check."""

        def add() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            accepted: list[tuple[int, SeedSpec]] = []
            rejected: list[ItemError] = []
            for index, item in enumerate(seeds):
                try:
                    accepted.append((index, parse_input(SeedSpec, item, f"seeds.{index}")))
                except FactoryValidationError as exc:
                    rejected.append(ItemError(index=index, issues=exc.issues))
            result = seeds_service.add_seeds(
                opened,
                actor,
                [spec for _, spec in accepted],
                sources=adapters,
                decision_ids=decision_ids,
            )
            for error in result.rejected:
                original = accepted[error.index][0]
                issues = [
                    ValidationIssue(f"seeds.{original}.{issue.field}", issue.reason)
                    for issue in error.issues
                ]
                rejected.append(ItemError(index=original, issues=issues))
            batch = BatchResult[SeedOutcome](
                written=result.written,
                rejected=sorted(rejected, key=lambda item: item.index),
            )
            return _withheld(opened, batch.model_dump(mode="json"))

        return _reply(project, add)

    @server.tool()
    def seed_list(
        project: str, cursor: str | None = None, limit: int = PAGE_LIMIT
    ) -> dict[str, JsonValue]:
        """The seeds an agent may use, in id order, one page at a time. Held-out seeds are never
        listed; `next_cursor` is passed back to read the next page."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            page = paginate(seeds_service.agent_seeds(opened), cursor, limit)
            return _withheld(
                opened,
                {
                    "items": [seed.model_dump(mode="json") for seed in page.items],
                    "next_cursor": page.next_cursor,
                },
            )

        return _reply(project, listing)

    @server.tool()
    def probe_run(
        project: str,
        queries: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
        sample: int = 20,
        decision_ids: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """Measure queries against the development seeds and the negatives: recall and negative
        hits per query and per source. Each query is {source, query, kind="keyword", filters={}};
        arXiv takes only filters={"listed_since": "YYYY-MM-DD"}. The first probe of a pilot or
        systematic project draws the hold-out split. Each measured query also returns `sample`
        titles (default 20, 0 for none) to judge noise: a seeded random sample from OpenAlex, the
        first page by relevance from arXiv and PubMed (`sample_kind` says
        which). A PubMed sample also returns `mesh_suggestions`, the MeSH descriptors of the
        sampled records with counts: suggestions only, never applied to a query. Samples are not
        corpus records and drop any held-out seed's work. `decision_ids` are the selected `probe`
        decisions this round implements; pilot and systematic projects
        refuse a probe without one."""

        def probe() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            specs = [_probe_spec(item, index) for index, item in enumerate(queries)]
            report = probe_service.run_probe(
                opened, actor, specs, sources=adapters, sample=sample, decision_ids=decision_ids
            )
            return _withheld(opened, report.model_dump(mode="json"))

        return _reply(project, probe, rename=dotted)

    @server.tool()
    def protocol_record(
        project: str,
        spec: dict[str, JsonValue],
        role: str,
        model: str,
        skill: str,
        ready: bool = False,
        review_request_id: str | None = None,
        decision_ids: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """Record the protocol as a draft, or as ready when `ready` is true. Gaps are returned
        whether or not the protocol was written. A ready protocol changes only by protocol_amend.
        `review_request_id` consumes an approved request whose proposal is this call.
        `decision_ids` are the selected `protocol` decisions it implements; pilot and systematic
        projects refuse a recording without one."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = parse_input(ProtocolSpec, spec, "spec")
            result = protocol_service.record_protocol(
                opened,
                actor,
                parsed,
                ready=ready,
                review_request_id=review_request_id,
                decision_ids=decision_ids,
            )
            data = result.model_dump(mode="json")
            data["gaps"] = [
                {"field": spec_path(gap.field), "reason": gap.reason} for gap in result.gaps
            ]
            return _withheld(opened, data)

        return _reply(project, record, rename=spec_path)

    @server.tool()
    def protocol_press_review(
        project: str,
        protocol_id: str,
        findings: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
    ) -> dict[str, JsonValue]:
        """Record an agent's PRESS review of the current protocol; a human confirms it next."""

        def review() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = [
                parse_input(PressFinding, item, f"findings.{index}")
                for index, item in enumerate(findings)
            ]
            review_id = protocol_service.press_review(opened, actor, protocol_id, parsed)
            return {"review_id": review_id}

        return _reply(project, review, rename=dotted)

    @server.tool()
    def protocol_amend(
        project: str,
        spec: dict[str, JsonValue],
        reason: str,
        semantic: bool,
        effects: dict[str, str],
        role: str,
        model: str,
        skill: str,
        review_request_id: str | None = None,
    ) -> dict[str, JsonValue]:
        """Amend the ready protocol. `effects` names each changed criterion as loosened,
        tightened or clarified; `semantic` is false only for prose and clarifications.
        `review_request_id` consumes an approved request whose proposal is this call."""

        def amend() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = parse_input(ProtocolSpec, spec, "spec")
            declared = _effects(effects)
            result = protocol_service.amend_protocol(
                opened,
                actor,
                parsed,
                reason=reason,
                semantic=semantic,
                effects=declared,
                review_request_id=review_request_id,
            )
            return _withheld(opened, result.model_dump(mode="json"))

        return _reply(project, amend, rename=spec_path)

    @server.tool()
    def screen_next(
        project: str,
        pass_label: str,
        role: str,
        model: str,
        skill: str,
        stage: str = "title-abstract",
    ) -> dict[str, JsonValue]:
        """Serve the next screening batch of pass A or B to this session, or say why none is
        served. The records are the text to screen; `blocked` says why ordinary work waits.
        `stage` is `title-abstract` (default) or `full-text`; a full-text batch names each work's
        document and the pinned conversion to read with `document_read`."""

        def screen() -> JsonValue:
            run_stage = parse_stage(stage)
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            # A batch is served whole, up to SCREEN_BATCH records: reserve them all first, so
            # that the cap is never passed, and give back what the batch does not use.
            with unit_cap.serving(
                screening_service.SCREEN_BATCH, whole=screening_service.SCREEN_BATCH
            ) as done:
                result = screening_service.screen_next(
                    opened, actor, _pass_label(pass_label), stage=run_stage
                )
                dumped = result.model_dump(mode="json")
                done(dumped)
            return _withheld(opened, dumped, include_work_ids=False)

        return _reply(project, screen, include_work_ids=False)

    @server.tool()
    def screen_record(
        project: str,
        task_id: str,
        items: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
        reported_usage: dict[str, JsonValue] | None = None,
    ) -> dict[str, JsonValue]:
        """Record verdicts for a held batch. Each item is {work_id, verdict, criterion, quote,
        rationale, score}, `score` being the relevance, an integer 1 to 10 (10 = clearly meets
        every inclusion), plus `anchor` for a full-text batch (the stage is the batch's); an
        invalid item is reported by index and the valid ones are written. `reported_usage` may state
        `input_tokens`, `output_tokens` and `cost_usd`: it goes on the batch's completion, is shown
        as reported and is never enforced."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            accepted, rejected = _parse_items(items)
            result = screening_service.screen_record(
                opened,
                actor,
                task_id,
                [item for _, item in accepted],
                reported_usage=budget_service.parse_reported_usage(reported_usage),
            )
            for error in result.rejected:
                original = accepted[error.index][0]
                rejected.append(
                    ItemError(
                        index=original,
                        issues=[
                            ValidationIssue(_items_path(issue.field, original), issue.reason)
                            for issue in error.issues
                        ],
                    )
                )
            batch = BatchResult[str](
                written=result.written, rejected=sorted(rejected, key=lambda item: item.index)
            )
            return _withheld(opened, batch.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, record, include_work_ids=False)

    @server.tool()
    def screen_agreement(
        project: str,
        role: str | None = None,
        model: str | None = None,
        skill: str | None = None,
        stage: str = "title-abstract",
    ) -> dict[str, JsonValue]:
        """The agreement of the two passes at `stage` (`title-abstract` or `full-text`): κ,
        per-criterion κ, disagreements and cannot-assess rates. Read-only. The actor is an agent
        when role, model or skill is given, else human. Refused to a session that has joined a
        pass."""

        def agreement() -> JsonValue:
            run_stage = parse_stage(stage)
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            if role is None and model is None and skill is None:
                actor = opened.human_actor()
            else:
                actor = make_agent_actor(settings, session, role or "", model or "", skill or "")
            result = agreement_service.agent_agreement(
                agreement_service.screen_agreement(opened, actor, stage=run_stage)
            )
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, agreement, include_work_ids=False)

    @server.tool()
    def calibration_label(
        project: str,
        work_id: str | None = None,
        verdict: str | None = None,
        criterion: str | None = None,
        stage: str = "title-abstract",
    ) -> dict[str, JsonValue]:
        """With no `work_id`: the next unlabelled calibration record and the counts. With one: the
        human's label on it. The first no-argument call draws the calibration set of `stage`
        (`title-abstract` or `full-text`). Labels are human acts; a session that has joined a pass
        cannot use this tool."""

        def label() -> JsonValue:
            run_stage = parse_stage(stage)
            opened = open_project(settings, project, session=session, clock=clock)
            human = opened.human_actor()
            if work_id is None:
                _refuse_pass_session(opened)
                if verdict is not None or criterion is not None:
                    raise FactoryValidationError(
                        [ValidationIssue("work_id", "is required to record a label")]
                    )
                calibration_service.draw_calibration(opened, human, stage=run_stage)
                return _withheld(
                    opened, _next_calibration(opened, run_stage), include_work_ids=False
                )
            if verdict is None:
                raise FactoryValidationError(
                    [ValidationIssue("verdict", "is required with a work_id")]
                )
            # Only the no-argument call draws the set. A labelled call is refused, and writes
            # nothing, while the set is undrawn; its own fields are checked first.
            _check_label(work_id, verdict, criterion)
            if not calibration_service.calibration_drawn(opened, stage=run_stage):
                raise FactoryValidationError(
                    [
                        ValidationIssue(
                            "work_id", "calibration set not drawn; call without arguments first"
                        )
                    ]
                )
            channel, said = confirm_human_act(
                f"Calibration label for {work_id}",
                {"verdict": verdict, "criterion": criterion or ""},
                {"verdict": ("include", "exclude")},
            )
            chosen = said["criterion"] or None
            if channel is Channel.ELICIT:
                _check_label(work_id, said["verdict"], chosen)
            event_id = calibration_service.label_calibration(
                opened, human, work_id, said["verdict"], chosen, channel, stage=run_stage
            )
            return {"event_id": event_id}

        return _reply(project, label, include_work_ids=False)

    @server.tool()
    def audit_sample(project: str, stage: str = "title-abstract") -> dict[str, JsonValue]:
        """Draw the audit sample of the agreed works of `stage` (`title-abstract` or `full-text`),
        for the human to label: each work's id, title and agreed verdict, with the population and
        the counts. Refused to a session that has joined a pass."""

        def sample() -> JsonValue:
            run_stage = parse_stage(stage)
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            drawn = audit_service.audit_sample(opened, opened.human_actor(), stage=run_stage)
            titles = {work.id: work.title for work in list_works(opened)}
            agreed = agreement_service.agreed_works(opened, stage=run_stage)
            data: dict[str, JsonValue] = {
                "audit_id": drawn.audit_id,
                "items": [
                    {
                        "work_id": work_id,
                        "title": titles[work_id],
                        "agreed_verdict": agreed[work_id].verdict,
                        **_evidence_fields(opened, work_id, run_stage),
                    }
                    for work_id in drawn.work_ids
                ],
                "population": drawn.population,
                "exclusions": drawn.exclusions,
                "inclusions": drawn.inclusions,
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, sample, include_work_ids=False)

    @server.tool()
    def audit_record(
        project: str,
        audit_id: str,
        work_id: str,
        verdict: str,
        criterion: str | None = None,
    ) -> dict[str, JsonValue]:
        """The human's label on one sampled work; the audit's stage is the sample's. `criterion`
        names an EX criterion for an exclusion, and is qualified against the current protocol."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            channel, said = confirm_human_act(
                f"Audit label for {work_id}",
                {"verdict": verdict, "criterion": criterion or ""},
                {"verdict": ("include", "exclude")},
            )
            event_id = audit_service.audit_record(
                opened,
                opened.human_actor(),
                audit_id,
                work_id,
                said["verdict"],
                said["criterion"] or None,
                channel,
            )
            return {"event_id": event_id}

        return _reply(project, record, include_work_ids=False)

    @server.tool()
    def screen_check_draw(
        project: str,
        kind: str = "band",
        stage: str = "title-abstract",
        bands: str = "1-3,4-7,8-10",
        per_band: int = 10,
        size: int | None = None,
        name: str | None = None,
        random_seed: int | None = None,
    ) -> dict[str, JsonValue]:
        """Draw records for the human to check the screener (H2). `kind` is `band` (pass A
        decisions stratified by score: `bands` such as `1-3,4-7,8-10`, `per_band` each), `tuning`
        (`size` fresh records, default 20, which the agent screens first) or `measurement` (`size`
        fresh records, default 30, disjoint from tuning batches and examples). The seed, bands and
        sizes are recorded. Items carry title and abstract, never the agent's verdict. Refused to
        a session that has joined a pass."""

        def draw() -> JsonValue:
            run_stage = parse_stage(stage)
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            human = opened.human_actor()
            try:
                chosen = CheckKind(kind)
            except ValueError:
                raise FactoryValidationError(
                    [ValidationIssue("kind", "must be band, tuning or measurement")]
                ) from None
            if chosen is CheckKind.BAND:
                drawn = check_service.draw_band_check(
                    opened,
                    human,
                    stage=run_stage,
                    bands=check_service.parse_bands(bands),
                    per_band=per_band,
                    random_seed=random_seed,
                )
            elif chosen is CheckKind.TUNING:
                drawn = check_service.draw_tuning_batch(
                    opened,
                    human,
                    stage=run_stage,
                    size=size or DEFAULT_TUNING_SIZE,
                    name=name,
                    random_seed=random_seed,
                )
            else:
                drawn = check_service.draw_measurement_batch(
                    opened,
                    human,
                    stage=run_stage,
                    size=size or DEFAULT_MEASUREMENT_SIZE,
                    name=name,
                    random_seed=random_seed,
                )
            works = {work.id: work for work in list_works(opened)}
            data: dict[str, JsonValue] = {
                "draw_id": drawn.draw_id,
                "kind": drawn.kind.value,
                "random_seed": drawn.random_seed,
                "items": [
                    {
                        "work_id": item.work_id,
                        "band": item.band,
                        "title": works[item.work_id].title if item.work_id in works else "",
                        "abstract": (works[item.work_id].abstract or "")
                        if item.work_id in works
                        else "",
                    }
                    for item in drawn.items
                ],
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, draw, include_work_ids=False)

    @server.tool()
    def screen_check_label(
        project: str, draw_id: str, work_id: str, verdict: str
    ) -> dict[str, JsonValue]:
        """The human's include or exclude on one drawn record; the stage is the draw's."""

        def label() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            channel, said = confirm_human_act(
                f"Check label for {work_id}",
                {"verdict": verdict},
                {"verdict": ("include", "exclude")},
            )
            event_id = check_service.check_label(
                opened, opened.human_actor(), draw_id, work_id, said["verdict"], channel
            )
            return {"event_id": event_id}

        return _reply(project, label, include_work_ids=False)

    @server.tool()
    def screen_check_example(
        project: str, draw_id: str, work_id: str, criterion: str, text: str
    ) -> dict[str, JsonValue]:
        """Make a disagreement of a tuning batch an example of `criterion` (a protocol
        amendment). `text` is one line, a title and a reason, with no work id; the human's label
        decides whether it is an include or an exclude example."""

        def example() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            channel, said = confirm_human_act(
                f"Example for {criterion} from {work_id}",
                {"criterion": criterion, "text": text},
                {},
            )
            result = check_service.add_tuning_example(
                opened,
                opened.human_actor(),
                draw_id,
                work_id,
                said["criterion"],
                said["text"],
                channel,
            )
            return {"amendment_id": result.amendment_id}

        return _reply(project, example, include_work_ids=False)

    @server.tool()
    def screen_check_report(
        project: str,
        draw_id: str | None = None,
        kind: str = "band",
        stage: str = "title-abstract",
    ) -> dict[str, JsonValue]:
        """A draw's report (the latest of `kind` when no `draw_id`): per band the labelled count,
        agreement and the records the human would add (includes and excludes). A tuning batch
        lists its disagreements and reports no agreement; agreement on a measurement batch is
        reported only while no example has changed since it was drawn."""

        def report() -> JsonValue:
            run_stage = parse_stage(stage)
            opened = open_project(settings, project, session=session, clock=clock)
            try:
                chosen = CheckKind(kind)
            except ValueError:
                raise FactoryValidationError(
                    [ValidationIssue("kind", "must be band, tuning or measurement")]
                ) from None
            found = check_service.check_report(opened, draw_id, kind=chosen, stage=run_stage)
            if found is None:
                return {"report": None}
            return _withheld(opened, found.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, report, include_work_ids=False)

    @server.tool()
    def protocol_deviation(
        project: str,
        description: str,
        reason: str,
        role: str,
        model: str,
        skill: str,
        affects: list[str] | None = None,
        review_request_id: str | None = None,
    ) -> dict[str, JsonValue]:
        """Record a deviation from the current protocol. A search the protocol does not plan
        needs the returned `deviation_id`. `review_request_id` consumes an approved request whose
        proposal is this call."""

        def deviate() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            deviation_id = protocol_service.record_deviation(
                opened,
                actor,
                description=description,
                reason=reason,
                affects=affects or (),
                review_request_id=review_request_id,
            )
            return {"deviation_id": deviation_id}

        return _reply(project, deviate)

    @server.tool()
    def report_prisma(
        project: str, update: str | None = None, by_source: bool = False
    ) -> dict[str, JsonValue]:
        """The PRISMA 2020 flow and the PRISMA-S search report, computed from the events.
        `update` adds the update flow of a living review: `last` (since the last snapshot) or a
        snapshot id (the update that snapshot closed). `by_source` adds the flow's counts per source
        group (`by_source`) and the ledger's reconciliation with the flow (`reconciles`, empty when
        they agree). Refused to a session that has joined a pass: the flow's included, pending and
        per-criterion exclusion counts derive from the final outcomes (human labels and both
        passes)."""

        def report() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            return agent_view_service.prisma_view(opened, update, by_source=by_source)

        return _reply(project, report, include_work_ids=False)

    @server.tool()
    def ledger_view(project: str) -> dict[str, JsonValue]:
        """The contribution ledger: counts per person and CRediT role, counts per agent role under
        its delegating user, unmapped event types, the map version, the hash and each person's
        confirmation status. Computed from the log; empty with a notice on a fresh project.
        Read-only. Refused to any session that has joined a pass."""

        def view() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            report = contribution_ledger_service.ledger_report(opened).model_dump(mode="json")
            return _withheld(opened, report, include_work_ids=False)

        return _reply(project, view, include_work_ids=False)

    @server.tool()
    def budget_status(project: str) -> dict[str, JsonValue]:
        """Each declared budget with its computed consumption and what is left in its period, and
        the usage agents reported, which is shown and never enforced. Empty with a notice on a
        project with neither. Read-only. Refused to any session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            report = budget_service.budget_status(opened).model_dump(mode="json")
            return _withheld(opened, report, include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def report_methods(project: str) -> dict[str, JsonValue]:
        """The methods statement: its figures and the rendered text. Refused to any session that
        has joined a pass, since it reports agreement, calibration and audit figures. Kappa is
        reported only once every dual-coded work is decided in both passes, so a session outside
        the passes never reads a partial figure."""

        def methods() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            return agent_view_service.methods_view(opened)

        return _reply(project, methods, include_work_ids=False)

    def _inbox_actor(
        opened: Project, role: str | None, model: str | None, skill: str | None
    ) -> Actor:
        """An agent when role, model or skill is given; else the human, relayed over MCP."""
        if role is None and model is None and skill is None:
            return opened.human_actor()
        return make_agent_actor(settings, session, role or "", model or "", skill or "")

    @server.tool()
    def inbox_add(
        project: str,
        items: list[dict[str, JsonValue]],
        channel: str = "agent",
        role: str | None = None,
        model: str | None = None,
        skill: str | None = None,
    ) -> dict[str, JsonValue]:
        """Capture links (arXiv, DOI or OpenAlex) as inbox items: each `{link, note?, basis?}`.
        `channel="agent"`: an agent proposes the link and must give `basis`, either
        `{"kind": "document", "document_id": "doc_...", "anchor": "..."}` for a citing span it
        read or `{"kind": "knowledge"}`; it gives no note. `channel="mcp"`: a human's link relayed
        verbatim, with an optional note and no basis. `page: true` on an item keeps an http(s) link
        with no identifier as a publisher page, whose `citation_doi` is read once at resolve.
        Offline; each item is written or rejected
        on its own. Refused to a session that has joined a pass; a session that captures a link
        cannot later screen. Screeners never see how a work was found."""

        def add() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            if channel not in ("agent", "mcp"):
                raise FactoryValidationError([ValidationIssue("channel", "agent or mcp")])
            actor = (
                make_agent_actor(settings, session, role or "", model or "", skill or "")
                if channel == "agent"
                else opened.human_actor()
            )
            accepted: list[tuple[int, inbox_service.LinkInput]] = []
            rejected: list[ItemError] = []
            for index, item in enumerate(items):
                try:
                    parsed = parse_input(_LinkItem, item, f"items.{index}")
                    accepted.append(
                        (
                            index,
                            inbox_service.LinkInput(
                                parsed.link, parsed.note, parsed.basis, parsed.page
                            ),
                        )
                    )
                except FactoryValidationError as exc:
                    rejected.append(ItemError(index=index, issues=exc.issues))
            result = inbox_service.add_links(
                opened, actor, [link for _, link in accepted], Channel.MCP
            )
            for error in result.rejected:
                original = accepted[error.index][0]
                issues = [
                    ValidationIssue(f"items.{original}.{issue.field}", issue.reason)
                    for issue in error.issues
                ]
                rejected.append(ItemError(index=original, issues=issues))
            batch = BatchResult[str](
                written=result.written, rejected=sorted(rejected, key=lambda e: e.index)
            )
            return _withheld(opened, batch.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, add, include_work_ids=False)

    @server.tool()
    def inbox_resolve(
        project: str,
        item_ids: list[str] | None = None,
        deviation_id: str | None = None,
        role: str | None = None,
        model: str | None = None,
        skill: str | None = None,
    ) -> dict[str, JsonValue]:
        """Look up open inbox items (all, or `item_ids`) by identifier as recorded `supplied`
        queries, each gated by the protocol (`supplied_links`, or `deviation_id`). Returns each
        item's status (`new`, `in-corpus`, `not-found`, `ambiguous`, `failed`) or why it was
        refused. The actor is an agent when role, model or skill is given, else the human.
        Refused to a session that has joined a pass."""

        def run() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = _inbox_actor(opened, role, model, skill)
            outcomes = inbox_service.resolve_links(
                opened, actor, sources=adapters, item_ids=item_ids, deviation_id=deviation_id
            )
            data: list[JsonValue] = [
                {
                    "item_id": o.item_id,
                    "status": None if o.status is None else o.status.value,
                    "work_id": o.work_id,
                    "run_id": o.run_id,
                    "errors": [{"field": i.field, "reason": i.reason} for i in o.issues],
                }
                for o in outcomes
            ]
            return _withheld(opened, {"items": data}, include_work_ids=False)

        return _reply(project, run, include_work_ids=False)

    @server.tool()
    def inbox_list(
        project: str, status: str | None = None, cursor: str | None = None, limit: int = PAGE_LIMIT
    ) -> dict[str, JsonValue]:
        """Inbox items in id order with status and last resolution outcome, one page at a time
        (`status`: open, resolved or withdrawn). Until a screening pass is open, items carry no
        link or identifier. Refused to a session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            page = inbox_service.list_items(opened, status=status, cursor=cursor, limit=limit)
            shown = inbox_service.agent_page(opened, page)
            return _withheld(opened, shown, include_work_ids=False)

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def grey_search_report(
        project: str,
        target: str,
        engine: str,
        query: str,
        timestamp: str,
        urls: list[str],
        stopping_rule: str,
        role: str | None = None,
        model: str | None = None,
        skill: str | None = None,
    ) -> dict[str, JsonValue]:
        """Report a web search you ran yourself (grey literature, an explicit R-21 exception).
        `target` is a declared `agent-web-search` entry of the protocol's `grey_sources`;
        `timestamp` is ISO 8601 with a zone; `stopping_rule` states when you stopped. The
        platform cannot verify the search: the event records what you say you ran. The `urls`
        are offered to the inbox (only arXiv, DOI and OpenAlex links parse; the rest are listed
        as unparsed); no work is enrolled by this call, and a reported search is never the only
        evidence of a planned source. Refused to a session that has joined a pass."""

        def report() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = _inbox_actor(opened, role, model, skill)
            try:
                when = datetime.fromisoformat(timestamp)
            except ValueError as exc:
                raise FactoryValidationError(
                    [ValidationIssue("timestamp", "an ISO 8601 timestamp with a zone")]
                ) from exc
            outcome = grey_service.report_search(
                opened,
                actor,
                target=target,
                engine=engine,
                query=query,
                timestamp=when,
                urls=urls,
                stopping_rule=stopping_rule,
            )
            return _withheld(
                opened,
                {
                    "report_id": outcome.record_id,
                    "offered": list(outcome.offered),
                    "unparsed": list(outcome.unparsed),
                },
                include_work_ids=False,
            )

        return _reply(project, report, include_work_ids=False)

    @server.tool()
    def report_discovery(project: str) -> dict[str, JsonValue]:
        """How the corpus was found: counts by first-surfaced route and by first surfacer's
        actor kind at each level (identified, title/abstract included, full-text included, in
        evidence), and route overlaps. Seed admission is reported as `other`. Refused to a
        session that has joined a pass."""

        def report() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            return agent_view_service.discovery_view(opened)

        return _reply(project, report, include_work_ids=False)

    @server.tool()
    def report_evidence(
        project: str, expect: list[dict[str, JsonValue]] | None = None
    ) -> dict[str, JsonValue]:
        """The evidence report: final extracted rows grouped by comparable setting, with
        frontiers, limits and the researcher's expectations (each a partial key, as
        `{"dataset": "coco"}`) matched against the groups. The audit error rate is reported to
        the researcher and withheld here. Refused to any session that has joined a screening or
        extraction pass. Read-only."""

        def evidence() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            return agent_view_service.evidence_view(opened, _expectations(expect or []))

        return _reply(project, evidence, include_work_ids=False)

    @server.tool()
    def export_bibliography(
        project: str,
        format: str = "bibtex",
        scope: str = "included",
        ids: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """The bibliography of a scope of works as BibTeX or CSL-JSON text (`format` bibtex or
        csl; `scope` included, corpus or draft:<drf_...>, or explicit work `ids`, which replace
        the scope). At
        most MCP_EXPORT_MAX_WORKS works; use the CLI for more. Built from events only; refused to
        any session that has joined a screening or extraction pass, and until a screening pass
        is open (use the CLI before then). Read-only."""

        def export() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            exports_service.refuse_before_screening(opened)
            chosen = exports_service.select_works(opened, None if ids else scope, ids or ())
            if len(chosen) > MCP_EXPORT_MAX_WORKS:
                raise FactoryValidationError(
                    [
                        ValidationIssue(
                            "scope",
                            f"{len(chosen)} works exceed the {MCP_EXPORT_MAX_WORKS} limit "
                            "of this tool; too large; use the CLI",
                        )
                    ]
                )
            body = "".join(exports_service.render_bibliography(opened, format, chosen))
            data: dict[str, JsonValue] = {
                "text": body,
                "count": len(chosen),
                "scope": "ids" if ids else scope,
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, export, include_work_ids=False)

    @server.tool()
    def trace(
        project: str, ref: str, direction: str = "back", layer: str = "evidence"
    ) -> dict[str, JsonValue]:
        """The chain from any identifier: `back` to what it was derived from, `forward` to what
        was derived from it. Held-out seed ids are refused as unknown; seed nodes, and the seed
        and probe lookups that found a work, are not shown. `layer` is `evidence` (default) or
        `all`; `all` adds the interpretation items an anchor, work or idea carries, each labelled
        `interpretation` with its review state (a layer id `int_`, `cpt_` or `cul_` is traced
        either way). Refused to a session that has joined a pass, since the chain leads to the
        other pass's decisions, resolutions and audit, and to one verifying a draft the chain
        reaches."""

        def walk() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            way = _direction(direction)
            return agent_view_service.trace_view(
                opened, ref, direction=way, layer=cast(trace_service.Layer, layer)
            )

        return _reply(project, walk, include_work_ids=False)

    @server.tool()
    def check(project: str, promote_to: str | None = None) -> dict[str, JsonValue]:
        """Gaps of the project: broken links, missing provenance, unexplained shortfalls, seed,
        protocol, screening, audit and chase gaps. With `promote_to`, the errors a promotion to
        that rigour mode would add. Seed gaps are counted by role, never named. Refused to a
        session that has joined a pass."""

        def gaps() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            return agent_view_service.check_view(opened, _rigor_mode(promote_to))

        return _reply(project, gaps, include_work_ids=False)

    @server.tool()
    def fulltext_fetch(
        project: str,
        role: str,
        model: str,
        skill: str,
        work_ids: list[str] | None = None,
        routes: list[str] | None = None,
        refresh: bool = False,
        limit: int = 20,
    ) -> dict[str, JsonValue]:
        """Fetch full text for promoted works. Routes are tried in order (arxiv-html, arxiv-source,
        pmc-jats, europepmc-jats, oa-pdf) and each work stops at its first retrieved attempt.
        `routes` names routes to try instead, all of them, without stopping.
        `work_ids` defaults to the promoted works that have no document and no attempt yet, so a
        work whose routes all failed is retried only by `refresh` (every promoted work),
        `routes`, or by naming it in `work_ids`. `limit` caps the works processed; more
        `work_ids` than `limit` are refused. Returns each work's attempts and documents, and
        `remaining`, the promoted works still without a document. A researcher's
        PDF is imported by the researcher, never fetched. Refused to a session that has joined a
        pass."""

        def fetch() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            summary = fulltext_service.fetch_fulltext(
                opened,
                routes=_fetch_routes(),
                work_ids=work_ids,
                only=parse_routes(routes, "routes"),
                refresh=refresh,
                limit=limit,
                actor=actor,
            )
            return _withheld(opened, summary.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, fetch, include_work_ids=False)

    @server.tool()
    def fulltext_status(project: str, work_ids: list[str] | None = None) -> dict[str, JsonValue]:
        """The full-text state of each promoted work, or of the named ones: retrieved, not
        retrieved (with the latest reason from each route) or unsought, and the live documents
        per route. Read-only. Refused to a session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            report = fulltext_status_service.fulltext_status(opened, work_ids=work_ids)
            return _withheld(opened, report.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def library_adoptable(project: str, work_id: str) -> dict[str, JsonValue]:
        """The documents of one promoted work that other projects of the lab hold in the lab
        library and this project may adopt: source project, document, route, quality, provenance,
        licence status and the number of conversions that come with it. A project you may not read
        is absent. Read-only. Refused to a session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            found = lab_library_service.adoptable(opened, work_id)
            rows: list[JsonValue] = [asdict(candidate) for candidate in found]
            return _withheld(opened, {"candidates": rows}, include_work_ids=False)

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def library_adopt(
        project: str,
        work_id: str,
        source_project: str,
        source_doc: str,
        role: str,
        model: str,
        skill: str,
    ) -> dict[str, JsonValue]:
        """Adopt a document another project acquired as this project's full text of a promoted
        work: the bytes are shared through the lab library, the adoption is recorded as an attempt
        on the `lab-library` route with the source named, and the source's conversions come with it.
        Refused, with nothing written, for a work not promoted, a source you may not read, bytes
        the lab library does not hold, and a researcher-supplied document whose source the owner has
        not confirmed. Returns the new document id. Refused to a session that has joined a pass."""

        def adopt() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            document_id = lab_library_service.adopt(
                opened, actor, work_id, source_project, source_doc
            )
            return _withheld(opened, {"document_id": document_id}, include_work_ids=False)

        return _reply(project, adopt, include_work_ids=False)

    @server.tool()
    def document_read(
        project: str,
        work_id: str,
        document_id: str | None = None,
        conversion_id: str | None = None,
        after: str | None = None,
        anchor: str | None = None,
        limit: int = document_read_service.DEFAULT_LIMIT,
        max_chars: int = document_read_service.DEFAULT_MAX_CHARS,
        selected: bool = False,
    ) -> dict[str, JsonValue]:
        """One page of a promoted work's converted document: its segments in document order, each
        with its anchor, kind and text (cut and flagged when long), and `next_after` for the next
        page. `anchor` reads one anchor, cells included. Agents read documents only through this
        tool. Conversion is the researcher's act (`factory document convert`); there is no MCP
        convert tool. Only works promoted at title/abstract are read. Read-only. Refused to a
        title/abstract pass session; a full-text screener reads only the works of its own batches,
        at the conversion each pins. `selected` returns only the anchors the miner task you hold
        selected for the work: with `limit` 200 and `max_chars` 60000 a whole selection is usually
        one or two pages."""

        def read() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            page = document_read_service.document_read(
                opened,
                work_id=work_id,
                document_id=document_id,
                conversion_id=conversion_id,
                after=after,
                anchor=anchor,
                limit=limit,
                max_chars=max_chars,
                session=opened.session,
                selected=selected,
            )
            return _withheld(opened, page.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, read, include_work_ids=False)

    @server.tool()
    def extract_next(
        project: str, pass_label: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Serve the next extraction task of pass A or B to this session, or say why none is
        served. The batch names the declared fields, the work and the pinned conversion to read
        with `document_read`; `blocked` says why ordinary work waits. Joins this session to the
        pass on its first call."""

        def serve() -> JsonValue:
            with unit_cap.serving() as done:
                label = _pass_label(pass_label)
                opened = open_project(settings, project, session=session, clock=clock)
                actor = make_agent_actor(settings, session, role, model, skill)
                served = extraction_service.extract_next(opened, actor, label)
                dumped = served.model_dump(mode="json")
                done(dumped)
            return _withheld(opened, dumped, include_work_ids=False)

        return _reply(project, serve, include_work_ids=False)

    @server.tool()
    def extract_record(
        project: str,
        task_id: str,
        rows: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
        claims: list[dict[str, JsonValue]] | None = None,
        finish: bool = False,
        reason: str | None = None,
        supersedes: dict[str, str] | None = None,
        claim_supersedes: dict[str, str] | None = None,
        reported_usage: dict[str, JsonValue] | None = None,
    ) -> dict[str, JsonValue]:
        """Record the rows (and, in pass A, claims) extracted from a held task. A row is
        {fields: {name: {value, unit, anchor, cell, quote, reported_in, cited_work}}}. An invalid
        item is reported by index and the valid ones are written. `supersedes` maps the index of
        a row of this call (a string key) to the id of the row it corrects; `claim_supersedes`
        likewise for claims. `finish` closes the work once no item is rejected; a work with no
        results needs a `reason`. `reported_usage` may state `input_tokens`, `output_tokens` and
        `cost_usd`: it goes on the completion, is shown as reported and is never enforced."""

        def record() -> JsonValue:
            row_targets = _index_keys("supersedes", supersedes or {})
            claim_targets = _index_keys("claim_supersedes", claim_supersedes or {})
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            good_rows, bad_rows = _parse_all(ExtractedRowInput, rows, "rows")
            good_claims, bad_claims = _parse_all(ClaimInput, claims or [], "claims")
            result = extraction_service.extract_record(
                opened,
                actor,
                task_id,
                [item for _, item in good_rows],
                [item for _, item in good_claims],
                finish=finish and not bad_rows and not bad_claims,
                reason=reason,
                supersedes=_renumbered("supersedes", row_targets, good_rows, len(rows)),
                claim_supersedes=_renumbered(
                    "claim_supersedes", claim_targets, good_claims, len(claims or [])
                ),
                reported_usage=budget_service.parse_reported_usage(reported_usage),
            )
            merged = ExtractResult(
                rows=_merged(result.rows, good_rows, bad_rows),
                claims=_merged(result.claims, good_claims, bad_claims),
                completed=result.completed,
            )
            return _withheld(opened, merged.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, record, include_work_ids=False)

    @server.tool()
    def extract_agreement(project: str) -> dict[str, JsonValue]:
        """The agreement of the two extraction passes: per-group rates, the unresolved
        disagreements with both values, and the single-extraction works. Read-only. Refused to a
        session that has joined an extraction or screening pass."""

        def agreement() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            result = extraction_agreement_service.extraction_agreement(opened, opened.human_actor())
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, agreement, include_work_ids=False)

    @server.tool()
    def extract_audit_sample(project: str) -> dict[str, JsonValue]:
        """Draw the audit sample of the agreed extracted values, for the human to label: each
        item with its value, quote and the text of the cited document element. Refused to a
        session that has joined an extraction or screening pass."""

        def sample() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            human = opened.human_actor()
            drawn = extraction_audit_service.extraction_audit_sample(opened, human)
            evidence = extraction_audit_service.audit_evidence(
                opened, human, drawn.audit_id, Channel.MCP
            )
            data: dict[str, JsonValue] = {
                "audit_id": drawn.audit_id,
                "items": [item.model_dump(mode="json") for item in evidence],
                "population": drawn.population,
                "sample_size": len(drawn.items),
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, sample, include_work_ids=False)

    @server.tool()
    def extract_audit_record(
        project: str,
        audit_id: str,
        work_id: str,
        row_key: str,
        field: str,
        correct: bool,
        note: str = "",
    ) -> dict[str, JsonValue]:
        """The human's label on one sampled value: was it extracted correctly. Refused to a
        session that has joined an extraction or screening pass."""

        def label() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            channel, said = confirm_human_act(
                f"Extraction audit label for {work_id} / {row_key} / {field}",
                {"correct": "yes" if correct else "no", "note": note},
                {"correct": ("yes", "no")},
            )
            event_id = extraction_audit_service.extraction_audit_record(
                opened,
                opened.human_actor(),
                audit_id,
                work_id,
                row_key,
                field,
                said["correct"] == "yes",
                said["note"],
                channel,
            )
            return {"event_id": event_id}

        return _reply(project, label, include_work_ids=False)

    @server.tool()
    def mine_next(
        project: str,
        miner: str,
        version: int,
        pass_label: str,
        role: str,
        model: str,
        skill: str,
        calibration: bool = False,
    ) -> dict[str, JsonValue]:
        """Serve the next task of pass A or B of a registered miner to this session, or say why
        none is served. The miner must be registered and listed in the protocol's `miners`
        section. The batch names the miner's fields and the rule of each kind, the work, the
        pinned conversion to read with `document_read` and the anchors the miner's selector
        selects; `blocked` says why ordinary work waits. Joins this session to the miner's pass on
        its first call. With `calibration` the pass is the miner's calibration pass (pass A): the
        units of its drawn sample only, for a session that neither proposed the miner, nor took
        part in a production pass, nor recorded a gold label. A production pass is refused for a
        version with no passed calibration unless the protocol declares that miner use
        exploratory (a protocol amendment with a reason, made by the researcher; no quality
        claim; the task carries the mark). You cannot declare it yourself."""

        def serve() -> JsonValue:
            with unit_cap.serving() as done:
                label = _pass_label(pass_label)
                opened = open_project(settings, project, session=session, clock=clock)
                _require_pass_opened(opened, "miner")
                actor = make_agent_actor(settings, session, role, model, skill)
                served = mining_service.mine_next(
                    opened,
                    actor,
                    miner,
                    version,
                    label,
                    calibration=calibration,
                )
                dumped = served.model_dump(mode="json")
                done(dumped)
            return _withheld(opened, dumped, include_work_ids=False)

        return _reply(project, serve, include_work_ids=False)

    @server.tool()
    def mine_record(
        project: str,
        task_id: str,
        rows: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
        finish: bool = False,
        reason: str | None = None,
        supersedes: dict[str, str] | None = None,
    ) -> dict[str, JsonValue]:
        """Record the rows mined from a held miner task. A row is {fields: {name: {value, unit,
        anchor, cell, quote, reported_in, cited_work}}}. An invalid item is reported by index and
        the valid ones are written. `supersedes` maps the index of a row of this call (a string
        key) to the id of the row it corrects. `finish` closes the work once no item is rejected;
        a work with no records needs a `reason`."""

        def record() -> JsonValue:
            row_targets = _index_keys("supersedes", supersedes or {})
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            good_rows, bad_rows = _parse_all(ExtractedRowInput, rows, "rows")
            result = mining_service.mine_record(
                opened,
                actor,
                task_id,
                [item for _, item in good_rows],
                finish=finish and not bad_rows,
                reason=reason,
                supersedes=_renumbered("supersedes", row_targets, good_rows, len(rows)),
            )
            merged = ExtractResult(
                rows=_merged(result.rows, good_rows, bad_rows),
                claims=result.claims,
                completed=result.completed,
            )
            return _withheld(opened, merged.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, record, include_work_ids=False)

    @server.tool()
    def mine_status(project: str) -> dict[str, JsonValue]:
        """Counts per listed miner and state (units, open, closed, rows, stale). A session that
        joined a miner pass sees its own miner and its own pass only. Carries no rate. Read-only."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            listed = mining_service.mine_status(
                opened, session=opened.session, with_agreement=False
            )
            data: dict[str, JsonValue] = {
                "miners": [entry.model_dump(mode="json") for entry in listed]
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def miner_register(
        project: str, spec: dict[str, JsonValue], role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Register a miner from its specification: name (m-...), version, selector, typed
        fields, row key, evidence rule, procedure skill and regime. The spec is validated and
        refused with located issues; a field of free text is refused. Registering the same spec
        again changes nothing; a changed spec needs a new version. A registered miner runs only
        after the protocol's `miners` section lists it. Refused to a session that has joined a
        pass."""

        def register() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            registered = mining_service.register_miner(opened, actor, spec)
            return _withheld(opened, registered.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, register, include_work_ids=False)

    @server.tool()
    def miner_list(project: str) -> dict[str, JsonValue]:
        """The registered miners: name, version, digest, who proposed it and whether the
        protocol lists it. Read-only."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            data: dict[str, JsonValue] = {
                "miners": [m.model_dump(mode="json") for m in mining_service.miner_listing(opened)]
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def taxonomy_view(project: str, name: str, version: int) -> dict[str, JsonValue]:
        """The registered taxonomy `name` at `version`: its registration row (digest, the
        proposals it accepts and rejects) and its specification in canonical form. Refused when
        that version is not registered. Read-only."""

        def view() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            row = taxonomies_service.taxonomy_row(opened, name, version)
            spec = taxonomies_service.registered_taxonomy(opened, name, version)
            if row is None or spec is None:
                raise FactoryValidationError(
                    [ValidationIssue("version", f"{name} version {version} is not registered")]
                )
            data: dict[str, JsonValue] = {
                "row": _plain(asdict(row)),
                "spec": _plain(taxonomy_to_json(spec)),
            }
            return _withheld(opened, data)

        return _reply(project, view)

    @server.tool()
    def taxonomy_list(project: str) -> dict[str, JsonValue]:
        """Every registered taxonomy version, by name then version: digest and the proposals each
        names. Read-only."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            rows = [_plain(asdict(row)) for row in taxonomies_service.list_taxonomies(opened)]
            return _withheld(opened, {"taxonomies": rows})

        return _reply(project, listing)

    @server.tool()
    def taxonomy_diff(project: str, name: str, a: int, b: int) -> dict[str, JsonValue]:
        """The computed difference from version `a` to version `b` of taxonomy `name`: added,
        removed, redefined, renamed, split and merged categories, and changed cardinality. Both
        versions must be registered. Read-only."""

        def difference() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            found = taxonomies_service.taxonomy_diff(opened, name, a, b)
            return _withheld(opened, _plain(asdict(found)))

        return _reply(project, difference)

    @server.tool()
    def taxonomy_coverage(
        project: str,
        name: str,
        version: int,
        miner: str,
        miner_version: int,
        fields: dict[str, list[str]],
    ) -> dict[str, JsonValue]:
        """Pattern coverage of taxonomy `name` at `version` over a descriptor miner's live pass-A
        quotes: per dimension, the works with quotes, and per category with a pattern, the works
        matching it with sample quotes, and the works matching no pattern. `fields` maps a
        dimension id to the miner's field names read for it. Computed; counts never classify.
        Refused to a session that has joined a pass."""

        def coverage() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            report = taxonomies_service.taxonomy_coverage(
                opened,
                name,
                version,
                miner=miner,
                miner_version=miner_version,
                fields={dimension: tuple(names) for dimension, names in fields.items()},
            )
            return _withheld(opened, _plain(asdict(report)))

        return _reply(project, coverage)

    @server.tool()
    def taxonomy_propose(
        project: str,
        name: str,
        base_version: int,
        kind: str,
        rationale: str,
        role: str,
        model: str,
        skill: str,
        targets: list[str] | None = None,
        works: list[str] | None = None,
        rows: list[str] | None = None,
        drafts: dict[str, JsonValue] | None = None,
        cluster_id: str | None = None,
    ) -> dict[str, JsonValue]:
        """Propose a change to taxonomy `name` at `base_version`. `kind` is add, split, merge,
        redefine, rename or retire; every kind but add names its `targets` as full ids
        `dimension/category` of the base version. `works` and `rows` cite what the change rests
        on; `drafts` is an optional object stored as a blob. The proposal changes no taxonomy: the
        researcher registers a new version or refuses it. All problems are reported together and
        nothing is written on any. Refused to a session that has joined a pass."""

        def propose() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            proposal_id = taxonomies_service.propose_change(
                opened,
                actor,
                taxonomy=name,
                base_version=base_version,
                kind=_proposal_kind(kind),
                targets=tuple(targets or ()),
                drafts=drafts,
                works=tuple(works or ()),
                rows=tuple(rows or ()),
                cluster_id=cluster_id,
                rationale=rationale,
            )
            return _withheld(opened, {"proposal_id": proposal_id})

        return _reply(project, propose)

    @server.tool()
    def taxonomy_proposals(project: str, name: str) -> dict[str, JsonValue]:
        """The change proposals against taxonomy `name`, by id, each with its status: open,
        accepted, or rejected with the reason and the version that settled it. Read-only."""

        def proposals() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            rows = [_plain(asdict(row)) for row in taxonomies_service.list_proposals(opened, name)]
            return _withheld(opened, {"proposals": rows})

        return _reply(project, proposals)

    @server.tool()
    def taxonomy_agreement(project: str, miner: str) -> dict[str, JsonValue]:
        """Agreement of the two passes of a miner derived from a taxonomy, per dimension: exact
        category for single dimensions, per-category presence and per-work Jaccard for multi
        dimensions; one pass `not-stated` against a category is completeness, not disagreement.
        Computed from the rows; quotes are never compared. Refused to a session that joined a
        pass. Read-only."""

        def read() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            report = taxonomy_agreement_service.taxonomy_agreement(opened, miner)
            return _withheld(opened, _plain(asdict(report)))

        return _reply(project, read)

    @server.tool()
    def page_brief(project: str, scope: str, part: int = 0) -> dict[str, JsonValue]:
        """The brief a synthesis page is written from, computed from the recorded rows: for a
        scope (`overview`, `technique=<value>`, `stage=<value>` or `field=<value>`) the statistics
        and rules (part 0) and a digest of quoted rows, paged by `part`. Read it all before
        writing. Refused to a session that joined a pass."""

        def read() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            return _withheld(
                opened, pages_service.brief(opened, scope, part), include_work_ids=False
            )

        return _reply(project, read, include_work_ids=False)

    @server.tool()
    def page_record(
        project: str,
        scope: str,
        title: str,
        body: str,
        role: str,
        model: str,
        skill: str,
        supersedes: str | None = None,
    ) -> dict[str, JsonValue]:
        """Record a synthesis page written from `page_brief`. The platform checks it: every cited
        work exists, every quotation is verbatim from a cited work's recorded quotes, every number
        is a statistic of the brief or a year. A failing page is refused with the sentences named;
        soft flags (a generalisation with no number or citation) are recorded with the page.
        `supersedes` names the page of the same scope that this one replaces. Refused to a session
        that joined a pass."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            payload, check = pages_service.record_page(
                opened, actor, scope, title, body, supersedes
            )
            data: dict[str, JsonValue] = {
                "page": payload.model_dump(mode="json"),
                "check": check.model_dump(mode="json"),
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, record, include_work_ids=False)

    @server.tool()
    def page_list(project: str) -> dict[str, JsonValue]:
        """The recorded pages (the latest of each scope) with their provenance, flags and whether
        the brief has changed since (stale). Read-only."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            data: dict[str, JsonValue] = {
                "pages": [p.model_dump(mode="json") for p in pages_service.list_pages(opened)]
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def mine_disagreements(
        project: str, miner: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """The unresolved disagreements of a miner's two passes, each with both values, for an
        agent to resolve where the project's policy for the gate `mine.resolve` lets an agent.
        Carries no rate. Refused when that gate is human, and to a session that joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _require_pass_opened(opened, "miner")
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            if gates_service.effective_policy(opened, "mine.resolve").kind is PolicyKind.HUMAN:
                raise FactoryValidationError(
                    [ValidationIssue("miner", "disagreements are resolved by a human here")]
                )
            agreement = extraction_agreement_service.extraction_agreement(
                opened, actor, scope=MinerScope(miner)
            )
            data: dict[str, JsonValue] = {
                "disagreements": [d.model_dump(mode="json") for d in agreement.disagreements]
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def mine_resolve(
        project: str,
        miner: str,
        work_id: str,
        row_key: str,
        choice: str,
        reason: str,
        role: str,
        model: str,
        skill: str,
        field: str | None = None,
    ) -> dict[str, JsonValue]:
        """Resolve one disagreement of a miner's passes (`a`, `b` or `neither`, with a reason),
        where the project's policy for the gate `mine.resolve` lets an agent. Refused when that
        gate is human, to the miner's proposer and to a session that joined a pass."""

        def resolve() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _require_pass_opened(opened, "miner")
            actor = make_agent_actor(settings, session, role, model, skill)
            picked: extraction_agreement_service.Choice
            if choice == "a":
                picked = "a"
            elif choice == "b":
                picked = "b"
            elif choice == "neither":
                picked = "neither"
            else:
                raise FactoryValidationError([ValidationIssue("choice", "must be a, b or neither")])
            event_id = extraction_agreement_service.resolve_extraction(
                opened,
                actor,
                work_id,
                row_key,
                field,
                picked,
                reason,
                Channel.MCP,
                scope=MinerScope(miner),
            )
            return {"event_id": event_id}

        return _reply(project, resolve, include_work_ids=False)

    @server.tool()
    def miner_calibration_label(
        project: str,
        calibration_id: str,
        work_id: str,
        rows: list[dict[str, JsonValue]],
        empty: bool = False,
    ) -> dict[str, JsonValue]:
        """The human's gold label of one unit of a miner calibration: the verified rows the unit
        holds, or `empty`. Each row is verified as an agent's row is. Refused to a session that
        has joined a pass and to the session that proposed the miner."""

        def label() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            parsed = [
                parse_input(ExtractedRowInput, row, f"rows.{index}")
                for index, row in enumerate(rows)
            ]
            event_id = miner_gold_service.label_miner_calibration(
                opened,
                opened.human_actor(),
                calibration_id,
                work_id,
                parsed,
                empty=empty,
                channel=Channel.MCP,
            )
            return {"event_id": event_id}

        return _reply(project, label, include_work_ids=False)

    @server.tool()
    def mine_import(
        project: str,
        source: str,
        miner: str,
        version: int,
        units: list[list[str]] | None = None,
    ) -> dict[str, JsonValue]:
        """The human's import of whole units of a miner from another project: `units` names them as
        [work_id, conversion_id] of the source, none takes every unit on a conversion this project
        holds. Each row is re-verified against this project's own conversion; a unit with a failing
        row is refused. Refused to a session that has joined a pass."""

        def run() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            if units is not None and any(len(unit) != 2 for unit in units):
                raise FactoryValidationError(
                    [ValidationIssue("units", "give each unit as [work_id, conversion_id]")]
                )
            result = shared_mining_service.mine_import(
                opened,
                opened.human_actor(),
                source,
                miner,
                version,
                None if units is None else [(unit[0], unit[1]) for unit in units],
                channel=Channel.MCP,
            )
            return {
                "imported_units": len(result.written),
                "rejected": [error.model_dump(mode="json") for error in result.rejected],
            }

        return _reply(project, run, include_work_ids=False)

    @server.tool()
    def import_status(
        project: str, cursor: str | None = None, limit: int = PAGE_LIMIT
    ) -> dict[str, JsonValue]:
        """Imported libraries, oldest first, one page at a time: each import's format, role,
        coverage label, records by resolution state and by coverage bucket. Development part
        only: no ordinals, no record total, no held-out figure (decision 43). Read-only. Refused
        to a session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            page = paginate(coverage_service.agent_import_status(opened), cursor, limit)
            return _withheld(
                opened,
                {
                    "items": [row.model_dump(mode="json") for row in page.items],
                    "next_cursor": page.next_cursor,
                },
                include_work_ids=False,
            )

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def import_coverage(project: str, import_id: str) -> dict[str, JsonValue]:
        """How far the systematic search reached an imported library: counts per bucket
        (found-database, found-supplementary, outside-limits, not-in-sources, source-unchecked,
        query-miss), search sensitivity and corpus coverage with numerators and denominators,
        and term suggestions for the misses. The development part is always shown; the held-out
        part appears only once a screening pass has been opened (decision 43), as figures
        without records. Read-only. Refused to a session that has joined a pass."""

        def coverage() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            report = coverage_service.agent_coverage(opened, import_id)
            return _withheld(opened, report.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, coverage, include_work_ids=False)

    @server.tool()
    def contribution_next(
        project: str, pass_label: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Serve the next contribution task of pass A or B to this session, or say why none is
        served. The batch names the declared fields, the work, the pinned conversion to read with
        `document_read`, and the reference entries available for `cited_entry` (`references`;
        status `current`, `none` or `other-conversion`). Joins this session to the contribution
        pass on its first call."""

        def serve() -> JsonValue:
            with unit_cap.serving() as done:
                label = _pass_label(pass_label)
                opened = open_project(settings, project, session=session, clock=clock)
                actor = make_agent_actor(settings, session, role, model, skill)
                served = contributions_service.contribution_next(opened, actor, label)
                dumped = served.model_dump(mode="json")
                done(dumped)
            return _withheld(opened, dumped, include_work_ids=False)

        return _reply(project, serve, include_work_ids=False)

    @server.tool()
    def contribution_record(
        project: str,
        task_id: str,
        items: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
        finish: bool = False,
        reason: str | None = None,
        supersedes: dict[str, str] | None = None,
    ) -> dict[str, JsonValue]:
        """Record the contribution items read from a held task. An item is {fields: {name:
        {value, unit, anchor, cell, quote}}}; `item_kind` is one of base-idea, addition, result,
        limitation, not-stated. An invalid item is reported by index and the valid ones are
        written. `supersedes` maps the index of an item of this call (a string key) to the id of
        the item it corrects. `finish` closes the work once no item is rejected; the platform
        refuses it until base idea and limitation are covered and an addition is recorded, and a
        work with no result needs a `reason`."""

        def record() -> JsonValue:
            targets = _index_keys("supersedes", supersedes or {})
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            good, bad = _parse_all(ExtractedRowInput, items, "items")
            result = contributions_service.contribution_record(
                opened,
                actor,
                task_id,
                [item for _, item in good],
                finish=finish and not bad,
                reason=reason,
                supersedes=_renumbered("supersedes", targets, good, len(items)),
            )
            merged = ExtractResult(
                rows=_merged(result.rows, good, bad),
                claims=result.claims,
                completed=result.completed,
            )
            return _withheld(opened, merged.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, record, include_work_ids=False)

    @server.tool()
    def references_extract(
        project: str,
        role: str,
        model: str,
        skill: str,
        work_ids: list[str] | None = None,
        re_resolve: bool = False,
        states: list[str] | None = None,
        only_identifiers: bool = False,
    ) -> dict[str, JsonValue]:
        """Extract and resolve the reference lists of included works from their converted
        documents. With no `work_ids`: every included work with a conversion and no current
        extraction. A malformed id refuses the call, and so does a named work whose current
        extraction already uses this conversion and parser version; works that cannot be
        extracted (not included, no conversion) are reported under `skipped` while the others
        are recorded. With `re_resolve` nothing is parsed: the links of the live extractions
        selected by `states` (default `source-error`; an unresolved reason or a link state) are
        looked up again under the same extraction ids, where the lookup failed or the matcher has
        changed. With `only_identifiers` (re-resolution only) just the entries with a DOI or arXiv
        id are retried, by identifier lookup. Refused to a session that has joined a pass."""

        def extract() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            if re_resolve:
                retried = references_service.re_resolve(
                    opened,
                    actor,
                    work_ids=work_ids,
                    states=states or ("source-error",),
                    sources=adapters,
                    only_identifiers=only_identifiers,
                )
                return _withheld(opened, retried.model_dump(mode="json"), include_work_ids=False)
            summary = references_service.extract_references(
                opened, actor, work_ids, sources=adapters
            )
            return _withheld(opened, summary.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, extract, include_work_ids=False)

    @server.tool()
    def references_status(project: str) -> dict[str, JsonValue]:
        """Counts over the live reference extractions: entries by link state (they sum to
        `entries`), works in the corpus and new candidates. Read-only. Refused to a session that
        has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            counts = references_service.reference_counts(opened)
            return _withheld(opened, counts.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def reference_layer_next(
        project: str, stage: Literal["title", "abstract"], limit: int = 25
    ) -> dict[str, JsonValue]:
        """Serve the next cited items to assign a relevance layer at `stage`, under the
        researcher's current scheme (its version and each layer's id, name, criteria and
        examples are in `scheme`). Until the calibration passes, the title stage serves only
        calibration-sample items (`calibrating`). Cite `input_blob` when recording. `remaining`
        counts items still to assign; at stage `abstract`, `awaiting_resolution` counts shortlisted
        items with no abstract yet. Read-only. Refused to a session that has joined a pass, and
        when no scheme is recorded."""

        def serve() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            batch = layers_service.next_items(opened, stage=stage, limit=limit)
            scheme = layers_service.current_scheme(opened)
            data = _plain(asdict(batch))
            if isinstance(data, dict) and scheme is not None:
                data["scheme"] = _plain(scheme.model_dump(mode="json"))
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, serve, include_work_ids=False)

    @server.tool()
    def reference_layer_record(
        project: str,
        scheme_version: int,
        stage: Literal["title", "abstract"],
        assignments: list[dict[str, JsonValue]],
        input_blob: str,
        role: str,
        model: str,
        skill: str,
    ) -> dict[str, JsonValue]:
        """Record layers for served items. Each assignment is {item_key, layer, rationale}; the
        layer is an id of the scheme version named. The whole batch is validated first and any
        issue refuses it with nothing written. `input_blob` is the one `reference_layer_next`
        returned. The scheme and the researcher's calibration labels are not recorded through
        this tool. Refused to a session that has joined a pass."""

        def record() -> JsonValue:
            issues: list[ValidationIssue] = []
            triples: list[tuple[str, str, str]] = []
            for index, row in enumerate(assignments):
                try:
                    parsed = parse_input(
                        LayerAssigned,
                        {**row, "scheme_version": scheme_version, "stage": stage},
                        f"assignments.{index}",
                    )
                except FactoryValidationError as exc:
                    issues.extend(exc.issues)
                    continue
                triples.append((parsed.item_key, parsed.layer, parsed.rationale))
            if issues:
                raise FactoryValidationError(issues)
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            result = layers_service.record_assignments(
                opened, actor, scheme_version, stage, triples, input_blob
            )
            return _withheld(opened, _plain(asdict(result)), include_work_ids=False)

        return _reply(project, record, include_work_ids=False)

    @server.tool()
    def reference_layer_status(project: str) -> dict[str, JsonValue]:
        """Counts of the reference layers: items by assessability, layers per stage, items left,
        abstracts awaiting resolution, and the calibration counts (sample size, labelled, assigned,
        dropped) with whether it has passed; agreement and kappa are the researcher's.
        Read-only. Refused to a session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            return _withheld(
                opened,
                _plain(asdict(layers_service.status(opened, agent=True))),
                include_work_ids=False,
            )

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def references_list(
        project: str,
        state: str | None = None,
        work_id: str | None = None,
        after: int = 0,
        limit: int = 50,
    ) -> dict[str, JsonValue]:
        """Entries of the live extractions with their links, by citing work and ordinal.
        `state` filters by link state (resolved, unconfirmed, ambiguous, unresolved), `work_id`
        by citing work; `after` is the number of items already seen and `limit` at most 100.
        Read-only. Refused to a session that has joined a pass."""

        def listing() -> JsonValue:
            link_state = _link_state(state)
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            page = references_service.list_references(
                opened,
                state=link_state,
                work_id=work_id,
                after=after,
                limit=limit,
            )
            return _withheld(opened, page.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def reference_decide(
        project: str,
        extraction_id: str,
        ordinal: int,
        decision: str,
        rationale: str,
        quotes: list[str],
        role: str,
        model: str,
        skill: str,
        work_id: str | None = None,
    ) -> dict[str, JsonValue]:
        """Propose or record a decision on an unconfirmed or ambiguous reference link.
        `decision` is `propose-confirm` or `propose-reject`; `confirm` and `reject` are binding
        and a human's (a second agent may only confirm in pilot mode, a recorded proposal of
        another session); `clear` is a human's alone. `quotes` is exactly two strings: a verbatim
        part of the entry, and a
        verbatim part of the candidate's title or author line. `work_id` names the candidate for
        an ambiguous link. Refused to a session that has joined a pass."""

        def decide() -> JsonValue:
            parsed = _decision(decision)
            if len(quotes) != 2:
                raise FactoryValidationError(
                    [
                        ValidationIssue(
                            "quotes", "give exactly two: the entry quote, then the candidate quote"
                        )
                    ]
                )
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            reference_resolve_service.decide_reference(
                opened,
                actor,
                extraction_id,
                ordinal,
                parsed,
                rationale=rationale,
                quotes=(quotes[0], quotes[1]),
                work_id=work_id,
            )
            return {"extraction_id": extraction_id, "ordinal": ordinal, "decision": parsed.value}

        return _reply(project, decide, include_work_ids=False)

    @server.tool()
    def snowball_round(
        project: str,
        direction: str,
        role: str,
        model: str,
        skill: str,
        dry_run: bool = True,
    ) -> dict[str, JsonValue]:
        """Plan (default) or run a snowball round: `backward` (the references of the included
        works' documents) or `forward` (works citing them). A dry run writes nothing and shows
        the candidates, the queries and whether the protocol's `snowball_plan` allows the round.
        Run a real round only after the researcher's go-ahead; follow with `dedup_run`.
        Refused to a session that has joined a pass."""

        def round_() -> JsonValue:
            parsed = _round_direction(direction)
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            result = snowball_service.snowball_round(
                opened, actor, parsed, sources=adapters, dry_run=dry_run
            )
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, round_, include_work_ids=False)

    @server.tool()
    def snowball_compare(project: str, round_id: str) -> dict[str, JsonValue]:
        """For a recorded backward round: the works its resolved references name against the
        works the `cited_by:` chase rounds found. A quality check, not a selection. Read-only.
        Refused to a session that has joined a pass."""

        def compare() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            result = snowball_service.snowball_compare(opened, round_id)
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, compare, include_work_ids=False)

    @server.tool()
    def snowball_core_list(project: str) -> dict[str, JsonValue]:
        """The core works a forward snowball round with `forward_core_only` may start from: the
        works the researcher marked, and the development seeds' works (core without a mark). Only
        the researcher marks a work core. Read-only. Refused to a session that has joined a
        pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            data: JsonValue = {
                "marked": [
                    m.model_dump(mode="json") for m in core_works_service.core_marks(opened)
                ],
                "seed_works": list(
                    core_works_service.seed_core_works(opened, development_only=True)
                ),
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def relation_propose(
        project: str,
        source_work: str,
        target: str,
        edge_type: str,
        role: str,
        model: str,
        skill: str,
        basis_item: str | None = None,
        note: str | None = None,
        status: str | None = None,
    ) -> dict[str, JsonValue]:
        """Propose a `builds-on` or `improves-on` relation from a recorded base-idea or addition
        item (`basis_item`) of `source_work` to a work or idea `target`. The platform sets the
        status: `stated` only when the item's cited reference entry resolves to exactly `target`,
        else `inferred` (reason and flags are returned) and a human decides. Without a basis
        item a `note` (at most 500 characters, not evidence) is required. No tool confirms a
        relation. `status` is not an input: giving it is refused. Refused to a session that has
        joined a pass."""

        def propose() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            if status is not None:
                raise FactoryValidationError(
                    [ValidationIssue("status", "the platform sets the status; do not send one")]
                )
            actor = make_agent_actor(settings, session, role, model, skill)
            proposal = parse_input(
                RelationProposal,
                {
                    "source_work": source_work,
                    "target": target,
                    "edge_type": edge_type,
                    "basis_item": basis_item,
                    "note": note,
                },
                "relation",
            )
            result = relations_service.propose_relation(opened, actor, proposal)
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, propose, include_work_ids=False)

    @server.tool()
    def idea_propose(
        project: str,
        name: str,
        origin: str,
        name_item: str,
        members: list[str],
        role: str,
        model: str,
        skill: str,
    ) -> dict[str, JsonValue]:
        """Propose a named idea: `origin` is the introducing work, `name_item` a recorded item of
        it whose `name` quote contains `name`, `members` the works that share it (including the
        origin). The idea stays unconfirmed, and out of default views, until a human confirms it;
        no tool merges or confirms ideas. Refused to a session that has joined a pass."""

        def propose() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            idea_id = ideas_service.propose_idea(opened, actor, name, origin, name_item, members)
            return _withheld(opened, {"idea_id": idea_id}, include_work_ids=False)

        return _reply(project, propose, include_work_ids=False)

    @server.tool()
    def graph_status(project: str, layer: str = "evidence") -> dict[str, JsonValue]:
        """Counts of the lineage graph: papers (corpus or external) and ideas, and edges by type
        and status (every status, derived from the log), plus the contribution works with no
        extraction or no references. Names the status filter it counted. `layer` is `evidence`
        (default) or `all`; `all` adds the interpretation layer's counts in a separate `layer`
        part, labelled and never added to the evidence counts. Read-only; refused to a session
        that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            report = graph_service.graph_status(
                opened, layer=cast(graph_service.Layer, layer)
            ).model_dump(mode="json")
            return _withheld(opened, report, include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def graph_query(
        project: str,
        query: str,
        node: str | None = None,
        target: str | None = None,
        depth: int = 3,
        k: int = 2,
        include_inferred: bool = False,
        include_stale: bool = False,
        layer: str = "evidence",
    ) -> dict[str, JsonValue]:
        """A bounded lineage query: `ancestors` / `descendants` (of `node`, up to `depth` levels,
        at most 8), `path` (shortest, `node` to `target`), `improvements_on` (`node`),
        `cited_by_at_least` (`k` distinct citing works) or `no_stated_base` (works with no stated
        base, by category). The default view shows stated and confirmed edges and confirmed
        ideas; `include_inferred` and `include_stale` widen it, labelled. The result names its
        filter and carries ids and statuses only. `layer` is `evidence` (default) or `all`; `all`
        adds the interpretation layer attached to the result's nodes as a separate `layer` part,
        every item labelled `interpretation` with its review state, never merged into `nodes` or
        `edges`. Refused to a session that has joined a pass."""

        def run() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            result = graph_service.graph_query(
                opened,
                query,
                node=node,
                target=target,
                depth=depth,
                k=k,
                flt=GraphFilter(include_inferred=include_inferred, include_stale=include_stale),
                layer=cast(graph_service.Layer, layer),
            )
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, run, include_work_ids=False)

    @server.tool()
    def graph_export(
        project: str,
        format: str = "json",
        query: str | None = None,
        node: str | None = None,
        target: str | None = None,
        depth: int = 3,
        k: int = 2,
        include_inferred: bool = False,
        include_stale: bool = False,
        layer: str = "evidence",
    ) -> dict[str, JsonValue]:
        """The graph (or, with `query`, a query's subgraph) as JSON or Graphviz DOT text, in a
        deterministic order, naming its filter; ids, statuses and bibliographic titles only. A
        whole-graph export of more than 2000 edges is refused: use a query or the CLI. `layer`
        is `evidence` (default) or `all`; `all` adds the interpretation layer as a separate,
        labelled part with a notice. Refused to a session that has joined a pass."""

        def export() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            if format not in ("json", "dot"):
                raise FactoryValidationError([ValidationIssue("format", "must be json or dot")])
            text = graph_service.graph_export(
                opened,
                "json" if format == "json" else "dot",
                query=query,
                node=node,
                target=target,
                depth=depth,
                k=k,
                flt=GraphFilter(include_inferred=include_inferred, include_stale=include_stale),
                max_edges=graph_service.MCP_EXPORT_MAX_EDGES,
                layer=cast(graph_service.Layer, layer),
            )
            return _withheld(opened, text, include_work_ids=False)

        return _reply(project, export, include_work_ids=False)

    @server.tool()
    def vocabulary_propose(
        project: str,
        definition: dict[str, JsonValue],
        role: str,
        model: str,
        skill: str,
    ) -> dict[str, JsonValue]:
        """Propose a property for the project vocabulary: `definition` has `key` (`pr:<slug>`),
        `kind` (enum, set, bool or number), `allowed` (enum and set), `unit_family` (number),
        `match` (equal, covers, at-most or at-least), `applies_to` (method, problem or both),
        `aliases` and `value_aliases` (phrases that stand for the property or a value), and a
        `description`. It stays unusable until the researcher approves it; no tool approves,
        rejects or merges properties. Propose only when no approved key fits. Refused to a
        session that has joined a pass."""

        def propose() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = parse_input(PropertyDef, definition, "definition")
            key = properties_service.propose_property(opened, actor, parsed)
            return _withheld(opened, {"key": key}, include_work_ids=False)

        return _reply(project, propose, include_work_ids=False)

    @server.tool()
    def card_create(
        project: str,
        kind: str,
        subject: str,
        owner: str,
        role: str,
        model: str,
        skill: str,
    ) -> dict[str, JsonValue]:
        """Create the card of a subject and return its id (an existing card of the subject is
        returned instead). A `method` card's subject is a confirmed lineage idea (`ida_`) or a
        work id; a `problem` card's subject is the project's current question id (`Q@...`) or a
        short task name under it. `owner` names who the card is for. Refused to a session that
        has joined a pass."""

        def create() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            if kind not in ("method", "problem"):
                raise FactoryValidationError([ValidationIssue("kind", "must be method or problem")])
            actor = make_agent_actor(settings, session, role, model, skill)
            card_id = cards_service.create_card(opened, actor, kind, subject, owner)  # type: ignore[arg-type]
            return _withheld(opened, {"card_id": card_id}, include_work_ids=False)

        return _reply(project, create, include_work_ids=False)

    @server.tool()
    def card_assert(
        project: str,
        card_id: str,
        items: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
        status: str | None = None,
    ) -> dict[str, JsonValue]:
        """Record property assertions on a card, each item alone (partial acceptance). An item is
        {property, value, unit?, basis_kind, basis}: `basis_kind` `quote` with basis {work_id,
        conversion_id, anchor, quote} (the quote must be verbatim and carry the value; a number is
        checked as in extraction; a `false` bool cannot be quoted), `row` with basis {row_key,
        field} of a final evidence row that says the same, or `inferred` with basis {note,
        supports?} (waits for the researcher; say so). Record one assertion per property, quoting
        the sentence that states it. The platform computes the status; `status` is not an input:
        giving it, here or in an item, is refused. Rejected items are returned with their reasons.
        No tool confirms an assertion. Refused to a session that has joined a pass."""

        def assert_() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            if status is not None:
                raise FactoryValidationError(
                    [ValidationIssue("status", "the platform sets the status; do not send one")]
                )
            actor = make_agent_actor(settings, session, role, model, skill)
            result = cards_service.assert_properties_raw(opened, actor, card_id, items)
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, assert_, include_work_ids=False)

    @server.tool()
    def card_view(
        project: str, card_id: str, include_inferred: bool = False
    ) -> dict[str, JsonValue]:
        """A card with its live assertions and their effective status. The default view shows
        stated and confirmed assertions; `include_inferred` adds inferred ones, labelled. Stale
        and rejected assertions are counted in `hidden_counts`, not shown. Read-only; refused to
        a session that has joined a pass."""

        def view() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            found = cards_service.card_view(opened, card_id, include_inferred=include_inferred)
            if found is None:
                raise FactoryValidationError([ValidationIssue("card_id", "unknown")])
            return _withheld(opened, found.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, view, include_work_ids=False)

    @server.tool()
    def intuition_next(
        project: str,
        role: str,
        model: str,
        skill: str,
        targets: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """Serve the next idea (or a named paper) to interpret, as a task claimed by this session:
        its member works and their recorded contribution items with verified quotes, and the
        limits (600 characters, 1 to 5 sources). Without `targets` the confirmed ideas are served
        in id order; papers only when named. Targets that cannot be served are listed with the
        reason. A null `batch` means nothing is left. An interpretation is not evidence. Refused to
        a session that has joined a pass."""

        def serve() -> JsonValue:
            with unit_cap.serving() as done:
                opened = open_project(settings, project, session=session, clock=clock)
                _refuse_pass_session(opened)
                _require_pass_opened(opened)
                actor = make_agent_actor(settings, session, role, model, skill)
                served = interpretations_service.intuition_next(
                    opened, actor, targets=list(targets) if targets else None
                )
                dumped = served.model_dump(mode="json")
                done(dumped)
            return _withheld(opened, dumped, include_work_ids=False)

        return _reply(project, serve, include_work_ids=False)

    @server.tool()
    def interpretation_record(
        project: str,
        task_id: str,
        target: str,
        text: str,
        sources: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
        supersedes: str | None = None,
    ) -> dict[str, JsonValue]:
        """Record an interpretation of the task's `target` (at most 600 characters) with 1 to 5
        sources. A source is {kind: "quote", role, work_id, conversion_id, anchor, quote}, the
        quote verbatim in that anchor of that conversion, or {kind: "citation", role, reference:
        "rex_...:n"} or {kind: "citation", role, work_id}; `role` is `supports` or `background`.
        All problems are reported together and nothing is written on any. `supersedes` may name
        only your project's unreviewed or wrong agent-written interpretation of the same target;
        reviewing, or replacing a reviewed or human-written one, is a human step. Refused to a
        session that has joined a pass."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            items: list[JsonValue] = [*sources]
            entry = parse_input(
                InterpretationInput,
                {"target": target, "text": text, "sources": items, "supersedes": supersedes},
                "interpretation",
            )
            interpretation_id = interpretations_service.record_interpretation(
                opened, actor, entry, task_id=task_id
            )
            return _withheld(
                opened, {"interpretation_id": interpretation_id}, include_work_ids=False
            )

        return _reply(project, record, rename=dotted, include_work_ids=False)

    @server.tool()
    def interpretation_list(
        project: str,
        target: str | None = None,
        states: list[str] | None = None,
        cursor: str | None = None,
    ) -> dict[str, JsonValue]:
        """Interpretations of an idea or paper, by id, one page: each with `class`
        (`interpretation`, never evidence), `label`, review state, text, sources, writer and
        `source_stale`. By default the unreviewed and reviewed ones; `states` widens it to `wrong`
        and `superseded`. The hidden counts are always reported. `next_cursor` continues the
        listing. Read-only; refused to a session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            chosen: list[ReviewState] | None = None
            if states:
                try:
                    chosen = [ReviewState(s) for s in states]
                except ValueError:
                    raise FactoryValidationError(
                        [ValidationIssue("states", f"must be among {_choices_of(ReviewState)}")]
                    ) from None
            result = interpretations_service.list_interpretations(
                opened, target=target, states=chosen, cursor=cursor
            )
            return _withheld(
                opened, result.model_dump(mode="json", by_alias=True), include_work_ids=False
            )

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def concept_propose(
        project: str,
        concept_name: str,
        role: str,
        model: str,
        skill: str,
        aliases: list[str] | None = None,
        text: str | None = None,
        source: dict[str, JsonValue] | None = None,
        quotes: list[dict[str, JsonValue]] | None = None,
        concept_id: str | None = None,
        supersedes: str | None = None,
    ) -> dict[str, JsonValue]:
        """Propose a background concept named `concept_name`: an outside idea a paper relies on,
        with an optional
        `text` (at most 600 characters), a `source` {kind: textbook|survey|corpus-paper|other,
        citation, work_id?} and verbatim `quotes` of that source's own work (only for a source
        with a work_id). The concept stays hidden and `unreviewed` until a human approves the
        source and reviews the text; you cannot approve either. To replace your own definition
        name `concept_id` and `supersedes` (the live definition's event id). All problems are
        reported together and nothing is written on any. A concept is not evidence. Refused to a
        session that has joined a pass."""

        def propose() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            entry = parse_input(
                ConceptInput,
                {
                    "name": concept_name,
                    "aliases": list(aliases or []),
                    "text": text,
                    "source": source,
                    "quotes": [*(quotes or [])],
                    "concept_id": concept_id,
                    "supersedes": supersedes,
                },
                "concept",
            )
            new_id = concepts_service.define_concept(opened, actor, entry)
            view = concepts_service.concept_view(opened, new_id)
            assert view is not None
            return _withheld(
                opened,
                {
                    "concept_id": new_id,
                    "source_state": view.source_state,
                    "review_state": view.review_state.value,
                },
                include_work_ids=False,
            )

        return _reply(project, propose, rename=dotted, include_work_ids=False)

    @server.tool()
    def concept_link(
        project: str,
        from_node: str,
        concept_id: str,
        role: str,
        model: str,
        skill: str,
        quote: dict[str, JsonValue] | None = None,
        reference: str | None = None,
        note: str | None = None,
    ) -> dict[str, JsonValue]:
        """Propose that a paper, a confirmed idea or a concept (`from_node`) uses `concept_id`.
        Basis: a verbatim `quote` source of the from-work ({kind: "quote", role, work_id,
        conversion_id, anchor, quote}), or a `reference` entry (`rex_...:n`) of its live
        reference list, or neither with a `note`. The platform decides the status: `stated` when
        the quote names the concept or the reference cites its approved source, otherwise
        `inferred`, which waits for a human; you cannot confirm. Returns the link, its status and
        reason, and whether it already existed. Refused to a session that has joined a pass."""

        def propose() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            basis = parse_input(UseBasisInput, {"quote": quote, "reference": reference}, "basis")
            result = concepts_service.propose_concept_link(
                opened, actor, from_node, concept_id, basis, note
            )
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, propose, rename=dotted, include_work_ids=False)

    @server.tool()
    def match_query(
        project: str,
        problem_id: str,
        include_inferred: bool = False,
        transfer_only: bool = False,
        limit: int = 50,
        after: str | None = None,
    ) -> dict[str, JsonValue]:
        """Method cards matched against a problem description (`pbd_`), one page: per card the
        satisfied, conflicting and unknown properties, ordered by fewest conflicts, most
        satisfied, fewest unknown, then id. `transfer` is True when no member work of the card's
        subject is included in this project. A computed candidate list, not a conclusion; only
        stated and confirmed assertions count unless `include_inferred`. `match_key` names the
        inputs. Page with `after`. Read-only; refused to a session that has joined a pass."""

        def query() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            page = matching_service.match(
                opened,
                problem_id,
                include_inferred=include_inferred,
                transfer_only=transfer_only,
                limit=limit,
                after=after,
            )
            return _withheld(opened, page.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, query, include_work_ids=False)

    @server.tool()
    def finder_contradictions(
        project: str, group_id: str | None = None, limit: int = 50, after: str | None = None
    ) -> dict[str, JsonValue]:
        """Numeric conflicts inside comparability groups: two independent rows of one method
        from different works whose values differ beyond the tolerance, with the regime fields
        that differ. Copied rows never conflict. `claims` lists the human-confirmed claim
        contradictions. Computed candidates; nothing is compared across groups. Page with
        `after`. Read-only; refused to a session that has joined a pass."""

        def find() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            page = findings_service.find_conflicts(
                opened, group_id=group_id, limit=limit, after=after
            )
            data = page.model_dump(mode="json")
            data["claims"] = [
                v.model_dump(mode="json") for v in findings_service.list_contradictions(opened)
            ]
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, find, include_work_ids=False)

    @server.tool()
    def finder_gaps(
        project: str,
        rows_axis: str,
        columns_axis: str,
        filters: dict[str, str] | None = None,
    ) -> dict[str, JsonValue]:
        """Empty cells of a grid: methods (`method`, from final evidence rows) or method cards
        (`card`) by one declared comparability key of the evidence schema, or by a property key
        (`pr:`, cards only). Each report carries the corpus definition and the sentence "not
        found in this corpus". A grid above 10,000 cells is refused: add a filter (a
        comparability key and a value). Read-only; refused to a session that has joined a
        pass."""

        def find() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            report = findings_service.find_gaps(
                opened, rows_axis=rows_axis, columns_axis=columns_axis, filters=filters
            )
            return _withheld(opened, report.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, find, include_work_ids=False)

    @server.tool()
    def contradiction_propose(
        project: str,
        ref_a: str,
        ref_b: str,
        note: str,
        role: str,
        model: str,
        skill: str,
        decision: str | None = None,
    ) -> dict[str, JsonValue]:
        """Propose that two live claims (`clm_`) or contribution items (`ext_`) of different
        works contradict each other, with a note of at most 500 characters. The platform stores
        both quotes. A proposal stays inferred until the researcher confirms it; `decision` is
        not an input and giving it is refused. The same pair proposed twice is written once.
        Refused to a session that has joined a pass."""

        def propose() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            if decision is not None:
                raise FactoryValidationError(
                    [ValidationIssue("decision", "only the researcher decides; do not send one")]
                )
            actor = make_agent_actor(settings, session, role, model, skill)
            item = parse_input(
                ContradictionInput, {"ref_a": ref_a, "ref_b": ref_b, "note": note}, "item"
            )
            ident, written = findings_service.propose_contradiction(opened, actor, item)
            return _withheld(
                opened, {"contradiction_id": ident, "written": written}, include_work_ids=False
            )

        return _reply(project, propose, include_work_ids=False)

    @server.tool()
    def region_propose(
        project: str,
        region_name: str,
        kind: str,
        definition: str,
        rules: dict[str, JsonValue],
        role: str,
        model: str,
        skill: str,
        facet: dict[str, JsonValue] | None = None,
        region_id: str | None = None,
    ) -> dict[str, JsonValue]:
        """Define a region (`kind` `region`) or a focus (`kind` `focus`, with `facet`
        {question_id, slot}): a `region_name`, a `definition` of at most 600 characters and typed
        `rules` {include: [...], exclude: [...], within: rule or null}. To replace a definition name
        `region_id`; its kind and facet stay. The region stays `unreviewed` until a human reviews a
        pinned version; you cannot review. A region selects and asserts nothing. A rule that
        would reach the held-out part of an import, or a run of an import, seed or probe query, is
        refused as a whole. Returns the region and its live state. Refused to a session that has
        joined a pass."""

        def propose() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            region_kind = _region_kind(kind)
            rule_set = parse_input(RuleSet, rules, "rules")
            bound = None if facet is None else parse_input(Facet, facet, "facet")
            if region_id is not None:
                regions_service.require_agent_visible(opened, region_id=region_id)
            new_id = regions_service.define_region(
                opened,
                actor,
                kind=region_kind,
                name=region_name,
                definition=definition,
                rules=rule_set,
                facet=bound,
                region_id=region_id,
            )
            state = regions_service.agent_region_state(opened, new_id)
            return _withheld(opened, state.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, propose, rename=dotted, include_work_ids=False)

    @server.tool()
    def region_propose_member(
        project: str,
        region_id: str,
        member_type: str,
        member: str,
        basis: dict[str, JsonValue],
        role: str,
        model: str,
        skill: str,
        note: str | None = None,
    ) -> dict[str, JsonValue]:
        """Propose one member (`member_type` work, idea or concept) of a region with exactly one
        verified `basis`: {kind: "quote", work_id, conversion_id, anchor, quote}, a verbatim quote
        of the candidate work in that anchored element of its conversion (work members only), or
        {kind: "edge", edge_id}, a live graph edge or a stated or confirmed concept use (`lnk_`)
        that touches the candidate and a current member of the region. `note` is at most 300
        characters and is never counted. The proposal never enters a version until a human adds the
        member; you cannot add, remove or reject. An identical open proposal is returned, not
        duplicated. All problems are reported together and nothing is written on any. Refused to
        a session that has joined a pass."""

        def propose() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            kind = _member_type(member_type)
            parsed = _parse_basis(basis)
            regions_service.require_agent_visible(opened, region_id=region_id)
            proposal = regions_service.propose_member(
                opened, actor, region_id, kind, member, parsed, note
            )
            return _withheld(opened, {"proposal_id": proposal}, include_work_ids=False)

        return _reply(project, propose, rename=dotted, include_work_ids=False)

    @server.tool()
    def region_snapshot(
        project: str, region_id: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Evaluate the region's rules now and pin the member set as a version `R@xxxxxxxx`. An
        unchanged evaluation returns the latest version and writes nothing. Returns the version,
        its counts by member type and its review state. A region that reaches the held-out part
        of an import or a run of an import, seed or probe query is refused as a whole. Refused to
        a session that has joined a pass."""

        def snapshot() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            regions_service.require_agent_visible(opened, region_id=region_id)
            version = regions_service.snapshot_region(opened, actor, region_id)
            info = regions_service.version_info(opened, version)
            assert info is not None
            return _withheld(opened, info.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, snapshot, rename=dotted, include_work_ids=False)

    @server.tool()
    def region_status(
        project: str, region_id: str | None = None, limit: int = 100, after: str | None = None
    ) -> dict[str, JsonValue]:
        """One region (`region_id`) or every region, one page: live counts by member type, drift
        from the latest version, latest version, review state and the author of its definition. A
        region that reaches the held-out part of an import or a run of an import, seed or probe
        query is listed without counts (`counts_withheld`). Page with `after`. Read-only; refused
        to a session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            ids = [region_id] if region_id is not None else regions_service.region_ids(opened)
            page = paginate(ids, after, limit)
            states: list[JsonValue] = [
                regions_service.agent_region_state(opened, rid).model_dump(mode="json")
                for rid in page.items
            ]
            data: JsonValue = {"regions": states, "next": page.next_cursor}
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def region_query(
        project: str,
        query: Literal["members", "regions_of", "overlap", "diff"],
        version: str | None = None,
        member_type: str | None = None,
        member: str | None = None,
        a: str | None = None,
        b: str | None = None,
        offset: int = 0,
        limit: int = 500,
    ) -> dict[str, JsonValue]:
        """Read pinned regions. `members` (`version`): one page of at most 500 members, by type and
        id, from `offset`. `regions_of` (`member_type`, `member`): at most 100 regions whose latest
        version holds the member, with the basis. `overlap` (`a`, `b` versions): shared and
        exclusive counts by member type and the Jaccard index. `diff` (`a`, `b`): members added
        and removed going from `a` to `b`, paged like `members`. A region that reaches the
        held-out part of an import or a run of an import, seed or probe query is refused (or, for
        `regions_of`, left out) as a whole. Read-only; refused to a session that has joined a
        pass."""

        def read() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            data = _region_read(opened, query, version, member_type, member, a, b, offset, limit)
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, read, include_work_ids=False)

    # --- Leads and hypotheses (slice 6, plan H-C) -----------------------------------------
    # Every tool is refused to a pass session and, before a pass opens, answers with the same
    # neutral message as the finders. The decision tools exist for the gates an agent may pass:
    # they refuse under a `human` policy and never name a rate, a label or a threshold.

    def _agent_gate(opened: Project, gate: GateName) -> None:
        if gate_policy(opened, gate).kind is PolicyKind.HUMAN:
            raise FactoryValidationError(
                [ValidationIssue("gate", f"{gate} is a human gate: the researcher decides")]
            )

    @server.tool()
    def lead_record(
        project: str,
        text: str,
        triggers: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
        framework: str | None = None,
    ) -> dict[str, JsonValue]:
        """Record a research-idea lead (at most 600 characters) with at least one trigger: a
        work (`rf:`), an evidence `row` key, a `claim`, a contribution `item`, an `idea`, an
        `interpretation`, a `concept`, a method or problem `card`, a `contradiction`, an earlier
        `lead` or `hypothesis`, or a builder row (`match`, `conflict`, `gap`) given with the key
        and the row exactly as the builder returned it. Each trigger is `{kind, ref}` (builder
        kinds also `row`). The answer lists `prior`: the parked and discarded leads and the
        hypotheses that share a trigger, card, idea or property; read it and say how this lead
        differs. Name the ideation `framework` you used. Refused to a session that has joined a
        pass."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            item = parse_input(
                LeadInput,
                {"text": text, "triggers": cast(JsonValue, triggers), "framework": framework},
                "lead",
            )
            lead_id = leads_service.record_lead(opened, actor, item)
            view = leads_service.lead_view(opened, lead_id)
            assert view is not None
            data: dict[str, JsonValue] = {
                "lead_id": lead_id,
                "prior": list(view.prior),
                "prior_total": view.prior_total,
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, record, include_work_ids=False)

    @server.tool()
    def lead_decide(
        project: str,
        lead_id: str,
        decision: str,
        role: str,
        model: str,
        skill: str,
        reason: str | None = None,
        note: str | None = None,
    ) -> dict[str, JsonValue]:
        """Promote, park or discard a lead. Refused unless the gate `hypotheses.lead_decide` is
        one an agent may pass in this project, and refused to the lead's own session. A discard
        needs a `reason` (duplicate, prior-failure, out-of-scope, infeasible, not-falsifiable,
        other) and `other` needs a `note`. Refused to a session that has joined a pass."""

        def decide() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            _agent_gate(opened, "hypotheses.lead_decide")
            actor = make_agent_actor(settings, session, role, model, skill)
            if decision not in ("promote", "park", "discard"):
                raise FactoryValidationError(
                    [ValidationIssue("decision", "must be promote, park or discard")]
                )
            try:
                why = None if reason is None else DiscardReason(reason)
            except ValueError:
                raise FactoryValidationError(
                    [ValidationIssue("reason", "not a discard reason")]
                ) from None
            event_id = leads_service.decide_lead(
                opened,
                actor,
                lead_id,
                cast(LeadDecision, decision),
                why,
                note,
            )
            return _withheld(opened, {"event_id": event_id}, include_work_ids=False)

        return _reply(project, decide, include_work_ids=False)

    @server.tool()
    def hypothesis_draft(
        project: str,
        spec: dict[str, JsonValue],
        role: str,
        model: str,
        skill: str,
        supersedes: str | None = None,
    ) -> dict[str, JsonValue]:
        """Draft a hypothesis: kind (experiment or literature), a statement, the promoted `lead`
        (required in pilot and systematic mode), treatment and baseline (a method card, a lineage
        idea or a name, with an optional evidence row), one metric, conditions (comparability
        keys of the evidence schema), a prediction with a margin stated before any result, a
        decision rule from the menu (superiority, non-inferiority, literature-direction) and a
        test. The platform computes the version `H@` and the falsifier sentence; you never state
        a state or a version. `supersedes` names the draft this one replaces; a hypothesis with
        evidence cannot be replaced. Refused to a session that has joined a pass."""

        def draft() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = parse_input(HypothesisSpec, spec, "spec")
            hypothesis_id, version = hypotheses_service.draft_hypothesis(
                opened, actor, parsed, supersedes=supersedes
            )
            created = hypotheses_service.hypothesis_view(opened, hypothesis_id)
            assert created is not None
            data: dict[str, JsonValue] = {
                "hypothesis_id": hypothesis_id,
                "h_version": version,
                "falsifier": created.falsifier,
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, draft, include_work_ids=False)

    @server.tool()
    def hypothesis_view(project: str, hypothesis_id: str) -> dict[str, JsonValue]:
        """One hypothesis: its spec, version, falsifier sentence, computed state, reviews,
        registration, the R-53 flags of a literature hypothesis and the autonomy label of its
        registration. Once the platform has evaluated it, also the computed `evaluation`: the
        outcome with its statistics and flags, the specification curve, ablations and controls. The
        rationale and the lead are shown to the drafting session only (R-51). Read-only; refused
        to a session that has joined a pass."""

        def view() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            found = hypotheses_service.hypothesis_view(opened, hypothesis_id)
            if found is None:
                raise FactoryValidationError([ValidationIssue("hypothesis_id", "unknown")])
            data = found.model_dump(mode="json")
            if found.drafter_session != opened.session:
                # R-51: only the drafter reads its own reasoning and the lead behind it
                spec = data["spec"]
                assert isinstance(spec, dict)
                spec.pop("rationale", None)
                spec.pop("lead", None)
            detail = evaluation_view_service.evaluation_detail(opened, hypothesis_id)
            data["evaluation"] = None if detail is None else detail.model_dump(mode="json")
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, view, include_work_ids=False)

    @server.tool()
    def hypothesis_review_next(
        project: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Claim the oldest hypothesis draft that has no independent review and return its
        review task: the artefact only (spec without prose, statement, the lead's triggers and
        the prior failures), never the lead's text or the drafter's reasoning. A review this
        session already holds is served again. The data is null when none waits. Refused to the
        drafter's session, to the lead author's session and, when the protocol asks for a distinct
        critic model, to the drafter's model. Refused to a session that has joined a pass."""

        def serve() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            served = review_service.review_next(opened, actor)
            if served is None:
                return None
            return _withheld(opened, served.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, serve, include_work_ids=False)

    @server.tool()
    def hypothesis_review(
        project: str,
        task_id: str,
        review: dict[str, JsonValue],
        role: str,
        model: str,
        skill: str,
    ) -> dict[str, JsonValue]:
        """Record the review of a claimed review task: `items` (every checklist item as pass,
        fail or n/a), optional `notes` per item (at most 300 characters) and `recommend`
        (register, revise or reject; a failing item allows only revise or reject). Judge the
        artefact in the task; do not ask for or read the proposer's notes. Refused to a session
        that has joined a pass."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = parse_input(ReviewInput, review, "review")
            event_id = review_service.record_review(opened, actor, task_id, parsed)
            return _withheld(opened, {"event_id": event_id}, include_work_ids=False)

        return _reply(project, record, include_work_ids=False)

    @server.tool()
    def hypothesis_register(
        project: str, hypothesis_id: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Register a reviewed hypothesis and freeze its version. Refused unless the gate
        `hypotheses.register` is one an agent may pass in this project, and refused to the
        drafter's and the lead author's sessions. A registration by an agent is labelled and is
        never reported as confirmatory. Refused to a session that has joined a pass."""

        def register() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            _agent_gate(opened, "hypotheses.register")
            actor = make_agent_actor(settings, session, role, model, skill)
            event_id = hypotheses_service.register_hypothesis(opened, actor, hypothesis_id)
            return _withheld(opened, {"event_id": event_id}, include_work_ids=False)

        return _reply(project, register, include_work_ids=False)

    @server.tool()
    def label_apply(
        project: str,
        items: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
    ) -> dict[str, JsonValue]:
        """Apply free labels, each `{target_type: work|idea|concept, target, text, quote?}`: a
        short label of at most 60 characters on a recorded work, idea or concept. A `quote` is a
        verbatim {work_id, conversion_id, anchor, quote} of the target work; the platform decides
        the status: `stated` when the verified quote contains the label key, otherwise `inferred`,
        which waits for a human. Each item is written or rejected on its own. A label is
        organisation, not evidence: it selects nothing until a human promotes it to a term.
        Refused to a session that has joined a pass."""

        def apply() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            accepted: list[tuple[int, labels_service.LabelInput]] = []
            rejected: list[ItemError] = []
            for index, item in enumerate(items):
                try:
                    accepted.append(
                        (index, parse_input(labels_service.LabelInput, item, f"items.{index}"))
                    )
                except FactoryValidationError as exc:
                    rejected.append(ItemError(index=index, issues=exc.issues))
            result = labels_service.apply_labels(opened, actor, [item for _, item in accepted])
            for error in result.rejected:
                original = accepted[error.index][0]
                issues = [
                    ValidationIssue(f"items.{original}.{dotted(issue.field)}", issue.reason)
                    for issue in error.issues
                ]
                rejected.append(ItemError(index=original, issues=issues))
            batch = BatchResult[str](
                written=result.written, rejected=sorted(rejected, key=lambda e: e.index)
            )
            return _withheld(opened, batch.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, apply, include_work_ids=False)

    @server.tool()
    def consolidation_next(project: str, role: str, model: str, skill: str) -> dict[str, JsonValue]:
        """Claim the next candidate cluster of labels, ideas or concepts that may name one thing
        (computed by the platform; each pair names its signals). Returns the task, the members
        with their names and aliases, and the signals; or no task. Propose with
        `consolidation_propose`; you cannot merge, keep or split: a human decides. Refused to a
        session that has joined a pass."""

        def serve() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            task = consolidation_service.consolidation_next(opened, actor)
            body: JsonValue = None if task is None else task.model_dump(mode="json")
            return _withheld(opened, {"task": body}, include_work_ids=False)

        return _reply(project, serve, include_work_ids=False)

    @server.tool()
    def consolidation_propose(
        project: str,
        task_id: str,
        action: str,
        members: list[str],
        reason: str,
        role: str,
        model: str,
        skill: str,
        into: str | None = None,
        quotes: list[dict[str, JsonValue]] | None = None,
    ) -> dict[str, JsonValue]:
        """Propose, for the cluster of a claimed task, to `merge` the named `members` into `into`
        (one of them), to `keep` them separate, or to `split` them, with a `reason` of at most
        600 characters and optional verbatim `quotes` ({work_id, conversion_id, anchor, quote}).
        The task is completed. A human decides; nothing is merged by this call. Refused to a
        session that has joined a pass."""

        def propose() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            if action not in ("merge", "keep", "split"):
                raise FactoryValidationError([ValidationIssue("action", "merge, keep or split")])
            parsed = [parse_input(QuoteBasis, q, f"quotes.{i}") for i, q in enumerate(quotes or [])]
            proposal = consolidation_service.propose(
                opened,
                actor,
                task_id,
                action=cast(consolidation_service.Action, action),
                into=into,
                members=members,
                reason=reason,
                quotes=parsed,
            )
            return _withheld(opened, {"proposal_id": proposal}, include_work_ids=False)

        return _reply(project, propose, rename=dotted, include_work_ids=False)

    @server.tool()
    def term_list(project: str, offset: int = 0, limit: int = 50) -> dict[str, JsonValue]:
        """The live terms (promoted label keys) with their aliases, definitions and the number
        of their applications by status, one page from `offset`. Applications that came from an
        import's tags are not counted. Terms are organisation, not evidence. Read-only; refused
        to a session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            page = terms_service.list_terms(
                opened,
                exclude_import_tags=True,
                limit=max(1, min(limit, 200)),
                offset=max(0, offset),
            )
            body: JsonValue = [t.model_dump(mode="json", by_alias=True) for t in page]
            return _withheld(opened, {"terms": body}, include_work_ids=False)

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def view_onion(
        project: str,
        max_ring: int = 2,
        edge_types: list[str] | None = None,
        include_inferred: bool = False,
        focus: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """The onion view: rings of works at hop distance 0 to `max_ring` (at most 3) from the
        included corpus, or from the corpus works named in `focus`, over `edge_types` (any of
        `cites`, `builds-on`, `improves-on`; default all) in the default status filter (stated and
        confirmed edges; `include_inferred` widens it, stated in the filter). Each ring has
        complete counts (total and per processing depth) and at most 500 listed works, ordered
        by depth then id; `truncated` says when a list is cut. A work lists the confirmed ideas
        it belongs to and the reviewed focus regions that an agent may read. The result names its
        filter and `as_of`; it carries ids, bibliographic titles and years only. Read-only;
        refused to a session that has joined a pass, and before a screening pass has opened."""

        def build() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            flt = onion_service.parse_filter(max_ring, edge_types, include_inferred, focus)
            result = onion_service.onion_view(opened, flt, agent=True)
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, build, include_work_ids=False)

    @server.tool()
    def view_coverage(project: str) -> dict[str, JsonValue]:
        """The coverage map: which normalised methods have final evidence rows in which
        comparability groups, as counts only (own rows, copied rows, works; never a value), and the
        same counts per confirmed idea (ids) from result items linked to evidence rows. Rows are
        those of corpus works as PRISMA counts them. Complete totals; lists are cut at 200 groups
        and 500 methods or ideas and `truncated` says so. The result names its filter, `as_of`
        and the corpus horizon (latest search date per source). Counts are activity, not quality.
        Read-only; refused to a session that has joined a pass, and before a screening pass has
        opened."""

        def build() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            result = view_coverage_service.coverage_view(opened)
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, build, include_work_ids=False)

    @server.tool()
    def view_timeline(project: str, group_id: str) -> dict[str, JsonValue]:
        """The record timeline of one comparability group (`grp_...`, from `report_evidence` or
        `view_coverage`): per value unit, the records (independent rows whose value is strictly
        better than every earlier-dated row's; dated by the work's publication year) and, per year
        and declared cost axis, the Pareto frontier of rows dated up to that year, as trace ids.
        A group with an unknown or conflicting metric direction has no timeline and a notice;
        undated works are listed. Nothing crosses groups or units. Read-only; refused to a session
        that has joined a pass, and before a screening pass has opened."""

        def build() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            result = horizon_service.timeline_view(opened, group_id)
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, build, include_work_ids=False)

    @server.tool()
    def view_horizon(project: str) -> dict[str, JsonValue]:
        """Activity per publication year: included works per confirmed idea, new confirmed ideas
        (by origin work), new stated or confirmed builds-on or improves-on edges (by citing work),
        and record counts per comparability group; undated items counted apart. It computes no
        label such as "emerging" and no citation score. States the corpus horizon: the latest
        finished search or watch run per source, and that later work is absent. Lists at most 200
        ideas and 200 groups (`truncated`). Read-only; refused to a session that has joined a
        pass, and before a screening pass has opened."""

        def build() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            result = horizon_service.horizon_view(opened)
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, build, include_work_ids=False)

    @server.tool()
    def briefing_get(project: str) -> dict[str, JsonValue]:
        """The context pack for a new agent session: question, protocol, gates passed or not with
        dates, corpus counts, the reading path, comparability groups with work counts, open issues
        by code, pending human decisions by count, and released drafts. At most 40000 characters;
        `truncated` states what was cut. It holds no rate, kappa, label or seed. Before a screening
        pass has opened the reading path, groups and drafts are empty. The pack is stored and
        `briefing.served` records that this session received it; the same pack is recorded once.
        Refused to a session that has joined a pass."""

        def serve() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            blob, pack = briefing_service.serve_pack(opened, session=opened.session)
            data: dict[str, JsonValue] = {"blob": blob, "pack": json.loads(pack)}
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, serve, include_work_ids=False)

    # --- Writing from verified material (slice 7b, plan W-A) ---------------------------------
    # Five tools. The outline holds ids only; a slot task shows the verified quotes of its
    # supports; a sentence is checked and recorded or refused alone. Nothing here sets a status,
    # a flag, a stat value or a citation key. Every tool is refused to a pass session and, before
    # a pass opens, answers with the neutral message of the other tools of the slice.

    @server.tool()
    def writing_outline(
        project: str,
        scope_works: list[str] | None = None,
        ideas: list[str] | None = None,
        groups: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """The outline of verified material to write against, for a scope (default: the included
        corpus): one section per confirmed idea in lineage order, one per comparability group of
        at least two works with its method disagreements as slots, one per claim type for live
        claims no section covers, and the limits (what the corpus does not support). It holds
        ids and fixed codes only, no quote and no prose, and its id `OL@...` is a hash of its
        content. `ideas` and `groups` restrict the sections to the ids named. Read-only; refused to
        a session that has joined a pass, and before a screening pass has opened."""

        def build() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            scope = outline_service.OutlineScope(
                works="included" if scope_works is None else tuple(scope_works),
                ideas=None if ideas is None else tuple(ideas),
                groups=None if groups is None else tuple(groups),
            )
            outline = outline_service.build_outline(opened, scope, agent=True)
            return _withheld(opened, outline.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, build, include_work_ids=False)

    @server.tool()
    def draft_create(
        project: str,
        title: str,
        kind: str,
        role: str,
        model: str,
        skill: str,
        scope_works: list[str] | None = None,
        ideas: list[str] | None = None,
        groups: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """Create a draft pinned to the outline of a scope (see `writing_outline`). `kind` is
        related-work, review, grant-background, horizon-note or other. The draft has one section
        per outline section (`sec_01`, ...). Refused to a session that has joined a pass."""

        def create() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            actor = make_agent_actor(settings, session, role, model, skill)
            try:
                draft_kind = DraftKind(kind)
            except ValueError:
                raise FactoryValidationError([ValidationIssue("kind", "unknown kind")]) from None
            scope = outline_service.OutlineScope(
                works="included" if scope_works is None else tuple(scope_works),
                ideas=None if ideas is None else tuple(ideas),
                groups=None if groups is None else tuple(groups),
            )
            draft_id = drafts_service.create_draft(
                opened, title=title, kind=draft_kind, scope=scope, actor=actor
            )
            return _withheld(opened, {"draft_id": draft_id}, include_work_ids=False)

        return _reply(project, create, include_work_ids=False)

    @server.tool()
    def draft_next(
        project: str,
        draft_id: str,
        role: str,
        model: str,
        skill: str,
        section_id: str | None = None,
    ) -> dict[str, JsonValue]:
        """The next section of the draft that has no sentence yet (or the named one) as a task:
        its `content` lists the section's eligible supports (`ref`, works, the verified quotes,
        numbers, stat values) and method disagreements, and the sentences already there. Cite only
        supports shown here. Returns `slot: null` when no section is left. The task is leased to
        this session; pass its `task_id` to `draft_write`. Refused to a session that has joined a
        pass."""

        def serve() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            actor = make_agent_actor(settings, session, role, model, skill)
            slot = drafts_service.draft_next(opened, draft_id, section_id=section_id, actor=actor)
            data: dict[str, JsonValue] = {
                "slot": None
                if slot is None
                else {
                    "task_id": slot.task_id,
                    "section_id": slot.section_id,
                    "content": slot.content,
                }
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, serve, include_work_ids=False)

    @server.tool()
    def draft_write(
        project: str,
        draft_id: str,
        sentences: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
        task_id: str | None = None,
    ) -> dict[str, JsonValue]:
        """Record sentences, one item per sentence: `{section_id, class, text, supports,
        supersedes?, order?}`. `class` is claim (about the literature, needs supports),
        synthesis (an aggregate: needs a stat or group support), interpretive (your reading;
        may cite reviewed interpretations; no numbers) or structural (no supports, no numbers,
        no citation, no author-year, no method name of the draft). `supports` are typed
        references (`claim:clm_...`, `cell:rk_.../<field>`, `item:ext_...`, `edge:rel_...`,
        `group:grp_...`, `stat:<kind>:<arg>`) shown in the slot, or `interp:int_...` from
        `interpretation_list`, which a slot does not list. One sentence
        per item, at most 400 characters and 6 supports. Each sentence stands or falls alone: the
        result lists those written and those rejected with their issues. Any number in a claim
        or synthesis must appear in a support. Do not type citations: the renderer adds them.
        Pass the slot's `task_id`. Refused to a session that has joined a pass."""

        def write() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed: list[drafts_service.SentenceInput] = []
            positions: list[int] = []
            rejected: dict[int, JsonValue] = {}
            for index, raw in enumerate(sentences):
                body = {("cls" if k == "class" else k): v for k, v in raw.items()}
                try:
                    parsed.append(drafts_service.SentenceInput.model_validate(body))
                    positions.append(index)
                except ValidationError as exc:
                    issues: list[JsonValue] = [
                        {
                            "field": ".".join(
                                ["sentences", str(index), *(str(x) for x in err["loc"])]
                            ),
                            "reason": str(err["msg"]),
                        }
                        for err in exc.errors()
                    ]
                    rejected[index] = {"index": index, "issues": issues}
            result = drafts_service.write_sentences(
                opened, draft_id, parsed, actor=actor, task_id=task_id
            )
            for item in result.rejected:
                rejected[positions[item.index]] = {
                    "index": positions[item.index],
                    "issues": [{"field": i.field, "reason": i.reason} for i in item.issues],
                }
            data: dict[str, JsonValue] = {
                "written": list(result.written),
                "rejected": [rejected[i] for i in sorted(rejected)],
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, write, include_work_ids=False)

    @server.tool()
    def draft_status(project: str, draft_id: str) -> dict[str, JsonValue]:
        """The draft's live sentences in order, each with its class, supports, flags the platform
        computed (citation-mismatch, quantifier-without-statistic, cross-group,
        single-source-generalisation, off-outline) and its computed status: `unchecked` until a
        verifier has judged it, then `supported` or `flagged` (its `reason` is the verdict),
        `stale` when a support no longer holds (its `reason` says why: revise the sentence), and
        `structural` and `interpretive`, which are labels. No verifier's note is shown. Once any
        verdict is labelled, `audit_note` says that these statuses exclude the human audit and the
        researcher's rendering is authoritative; otherwise it is null. Read-only; refused to a
        session that has joined a pass or that is verifying this draft."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            found = drafts_service.get_draft(opened, draft_id)
            if found is None:
                raise FactoryValidationError([ValidationIssue("draft_id", "unknown draft")])
            statuses = {
                s.sentence_id: s
                for s in drafts_service.sentence_status(
                    opened, draft_id, agent=True, session=opened.session
                )
            }
            rows = drafts_service.live_sentences(opened, draft_id)
            report = draft_audit_service.audit_report(opened, draft_id)
            data: dict[str, JsonValue] = {
                "draft": found.model_dump(mode="json"),
                "sentences": [
                    {
                        "sentence_id": r.sentence_id,
                        "section_id": r.section_id,
                        "order": r.order,
                        "class": r.cls.value,
                        "text": r.text,
                        "supports": list(r.supports),
                        "flags": [f.value for f in r.flags],
                        "status": statuses[r.sentence_id].status,
                        "reason": statuses[r.sentence_id].reason,
                    }
                    for r in rows
                ],
                "audit": draft_audit_service.agent_audit_report(report).model_dump(mode="json"),
                "audit_note": draft_audit_service.agent_audit_note(report),
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def draft_verify_next(
        project: str, draft_id: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """The next sentence of the draft that needs a verdict, as a task leased to this session:
        `sentence_id`, `text`, `cls`, `context_previous` (the preceding sentence, context only),
        `flags` (what the platform computed, a pointer and never a verdict) and `supports`, each
        with its `ref`, `kind`, `spans`, the only text you judge from, and `spans_omitted`, the
        values of a large group not shown. Returns
        `unit: null` when none is left. Pass `rf-verify` as `skill`. Refused to a session that
        wrote a sentence of the draft or joined a pass; in systematic mode, to the writer's
        model."""

        def serve() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            actor = make_agent_actor(settings, session, role, model, skill)
            unit = draft_verify_service.verify_next(opened, draft_id, actor=actor)
            data: dict[str, JsonValue] = {
                "unit": None if unit is None else unit.model_dump(mode="json")
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, serve, include_work_ids=False)

    @server.tool()
    def draft_verify_record(
        project: str,
        task_id: str,
        verdict: str,
        role: str,
        model: str,
        skill: str,
        sentence_span: str | None = None,
        support_spans: list[dict[str, JsonValue]] | None = None,
        note: str | None = None,
    ) -> dict[str, JsonValue]:
        """Record the verdict of the unit: supported, partial, unsupported, contradicted or
        overstated (the sentence is stronger than the spans). `sentence_span` is the part of the
        sentence you judge, required unless supported. `support_spans` lists `{ref, substring}`,
        verbatim from a span of that support, at least one unless unsupported. `note` is at most
        300 characters. The platform checks the substrings; it does not judge. Refused to a
        session that wrote in the draft or joined a pass."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            actor = make_agent_actor(settings, session, role, model, skill)
            try:
                item = draft_verify_service.VerdictInput(
                    verdict=Verdict(verdict),
                    sentence_span=sentence_span,
                    support_spans=[SupportSpan.model_validate(s) for s in support_spans or []],
                    note=note,
                )
            except ValueError:
                raise FactoryValidationError(
                    [ValidationIssue("verdict", "unknown verdict or malformed support_spans")]
                ) from None
            verdict_id = draft_verify_service.verify_record(opened, task_id, item, actor=actor)
            return _withheld(opened, {"verdict_id": verdict_id}, include_work_ids=False)

        return _reply(project, record, include_work_ids=False)

    @server.tool()
    def draft_render(project: str, draft_id: str, mode: str = "review") -> dict[str, JsonValue]:
        """The draft as Markdown text. `review` shows each sentence with its status, flags,
        supports and their quotes; `clean` the prose with citation keys, `[[UNSUPPORTED: ...]]`
        and `[[INTERPRETATION]]` markers, the counts and the methods paragraph. An audit's result
        is the researcher's and is not stated; once any verdict is labelled a line under the title
        says so. Read-only; refused to a session that has joined a pass or that is verifying this
        draft."""

        def render() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            if mode not in ("review", "clean"):
                raise FactoryValidationError([ValidationIssue("mode", "must be review or clean")])
            body = drafts_service.draft_render(
                opened,
                draft_id,
                "review" if mode == "review" else "clean",
                agent=True,
                session=opened.session,
            )
            return _withheld(opened, {"text": body}, include_work_ids=False)

        return _reply(project, render, include_work_ids=False)

    @server.tool()
    def draft_release(
        project: str, draft_id: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Release the draft through the gate `writing.release`: in exploratory mode any non-empty
        draft; in pilot mode once the audit the researcher drew is labelled and no sentence is
        stale. A refusal lists the blocking counts. Refused in systematic mode, where only the
        reviewer of record releases, at the terminal; refused to a session that joined a pass."""

        def act() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            actor = make_agent_actor(settings, session, role, model, skill)
            event_id = draft_release_service.release(opened, draft_id, actor=actor)
            return _withheld(opened, {"event_id": event_id}, include_work_ids=False)

        return _reply(project, act, include_work_ids=False)

    # --- External manuscripts (slice 7b, plan W-C) ----------------------------------------
    # Three tools and no more: an agent verifies. Adding a manuscript, confirming a fuzzy citation
    # and auditing are the researcher's, at the command line. Every tool is refused to a pass
    # session, and before a pass opens, since a unit names a work.

    @server.tool()
    def manuscript_verify_next(
        project: str, manuscript_id: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """The next unit of the manuscript that needs a verdict, as a task leased to this session:
        `task_id`, `manuscript_id`, `ordinal`, `work_id` and `conversion_id`, ids only. Read the
        sentence with `manuscript_read` and the source with `document_read` at that conversion.
        Returns `unit: null` when none is left. Pass `rf-verify` as `skill`. Refused to a session
        that joined a pass."""

        def serve() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            actor = make_agent_actor(settings, session, role, model, skill)
            unit = manuscript_verify_service.manuscript_verify_next(
                opened, manuscript_id, actor=actor
            )
            data: dict[str, JsonValue] = {
                "unit": None if unit is None else unit.model_dump(mode="json")
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, serve, include_work_ids=False)

    @server.tool()
    def manuscript_read(
        project: str, manuscript_id: str, ordinal: int, context: int = 1
    ) -> dict[str, JsonValue]:
        """One sentence of a manuscript: `text`, its `length`, its citation `keys`, and up to
        `context` (0 to 3) preceding sentences in `before`, as context only; `after` is empty.
        Agents read manuscripts only through this tool; never copy the text into a note.
        Read-only; refused to a session that joined a pass."""

        def read() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            found = manuscripts_service.manuscript_read(
                opened, manuscript_id, ordinal, context=context, session=opened.session
            )
            return _withheld(
                opened, found.model_dump(mode="json"), include_work_ids=False, same_length=True
            )

        return _reply(project, read, include_work_ids=False)

    @server.tool()
    def manuscript_verify_record(
        project: str,
        role: str,
        model: str,
        skill: str,
        task_id: str | None = None,
        verdict: str | None = None,
        sentence_span: list[int] | None = None,
        anchor: str | None = None,
        quote: str | None = None,
        note: str | None = None,
        manuscript_id: str | None = None,
        uncited_ordinal: int | None = None,
    ) -> dict[str, JsonValue]:
        """Record the verdict of the unit `task_id`: supported, partial, unsupported, contradicted
        or overstated. `sentence_span` is `[start, end]`, character offsets inside the sentence,
        required unless supported. `quote` is verbatim from the anchor `anchor` of the unit's
        conversion, required unless unsupported. `note` is at most 300 characters and must not
        copy the manuscript. Or, with `manuscript_id` and `uncited_ordinal` and no task, flag an
        uncited sentence as `uncited-claim`: advisory, never a verdict. The platform checks the
        quote; it does not judge. Refused to a session that joined a pass."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            actor = make_agent_actor(settings, session, role, model, skill)
            if uncited_ordinal is not None:
                if manuscript_id is None or task_id is not None or verdict is not None:
                    raise FactoryValidationError(
                        [ValidationIssue("uncited_ordinal", "give manuscript_id and no task")]
                    )
                flag_id = manuscript_verify_service.flag_uncited(
                    opened, manuscript_id, uncited_ordinal, note, actor=actor
                )
                return _withheld(opened, {"flag_id": flag_id}, include_work_ids=False)
            if task_id is None or verdict is None:
                raise FactoryValidationError(
                    [ValidationIssue("task_id", "give task_id and verdict")]
                )
            try:
                judged = Verdict(verdict)
            except ValueError:
                raise FactoryValidationError(
                    [ValidationIssue("verdict", "unknown verdict")]
                ) from None
            if sentence_span is not None and len(sentence_span) != 2:
                raise FactoryValidationError(
                    [ValidationIssue("sentence_span", "must be [start, end]")]
                )
            verdict_id = manuscript_verify_service.manuscript_verify_record(
                opened,
                task_id,
                judged,
                sentence_span=None
                if sentence_span is None
                else (sentence_span[0], sentence_span[1]),
                anchor=anchor,
                quote=quote,
                note=note,
                actor=actor,
            )
            return _withheld(opened, {"verdict_id": verdict_id}, include_work_ids=False)

        return _reply(project, record, include_work_ids=False)

    # --- Experiment designs and runs (slice 6, plan XP-A) ---------------------------------
    # Four tools and no more: an agent drafts and amends a design before the freeze and registers
    # planned runs. Nothing here freezes, unlocks, ingests a result, accepts a baseline or records
    # a deviation (those are the researcher's, at the command line), and no view carries the
    # unlock nonce, a metric value or a designer's session. Every tool is refused to a pass session
    # and, before a pass opens, answers with the neutral message of the other tools of the slice.

    @server.tool()
    def experiment_design(
        project: str,
        design: dict[str, JsonValue],
        role: str,
        model: str,
        skill: str,
        supersedes: str | None = None,
        amend_of: str | None = None,
        reason: str | None = None,
        semantic: bool = False,
    ) -> dict[str, JsonValue]:
        """Draft an experiment design for a registered or drafted experiment hypothesis, or amend
        one that is not yet frozen (`amend_of` with a `reason`; `semantic` says whether the change
        alters what is tested). The design names the one factor (key to baseline and treatment
        value), the fixed configuration, seeds (at least the plan's minimum), multiverse axes with
        a primary universe, ablations that each change one key, controls, baselines as final
        evidence rows with a tolerance, datasets with split roles, metrics with one primary,
        a budget and the code and environment. The platform computes the version `E@`; you never
        state an id, a version or a configuration map. `supersedes` names an unfrozen design of
        the same hypothesis that this one replaces. A frozen design cannot be amended. Refused to
        a session that has joined a pass."""

        def draft() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = parse_input(ExperimentDesign, cast(JsonValue, design), "design")
            if amend_of is not None and supersedes is not None:
                raise FactoryValidationError(
                    [ValidationIssue("amend_of", "give amend_of or supersedes, not both")]
                )
            if amend_of is None:
                experiment_id, version = experiments_service.design_experiment(
                    opened, actor, parsed, supersedes=supersedes
                )
            else:
                if reason is None:
                    raise FactoryValidationError(
                        [ValidationIssue("reason", "an amendment states its reason")]
                    )
                experiments_service.amend_experiment(
                    opened, actor, amend_of, parsed, reason, semantic
                )
                experiment_id, version = amend_of, design_version(parsed)
            data: dict[str, JsonValue] = {
                "experiment_id": experiment_id,
                "e_version": version,
                "issues": [],
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, draft, include_work_ids=False)

    @server.tool()
    def experiment_view(project: str, experiment_id: str) -> dict[str, JsonValue]:
        """One experiment design: the design, its version `E@`, its computed state (draft, frozen,
        unlocked, superseded), deviations, flags, the budget used, the confirmatory reads per
        primary cell and the state of each baseline (pending, reproduced, not-reproduced,
        accepted). It carries no unlock nonce and no designer session. Read-only; refused to a
        session that has joined a pass."""

        def view() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            found = experiments_service.experiment_view(opened, experiment_id)
            if found is None:
                raise FactoryValidationError([ValidationIssue("experiment_id", "unknown")])
            shown, states = experiments_service.agent_baseline_view(opened, found)
            data = shown.model_dump(mode="json", exclude={"designer_sessions"})
            data["baselines"] = cast(JsonValue, states)
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, view, include_work_ids=False)

    @server.tool()
    def xrun_register(
        project: str,
        experiment_id: str,
        cell: dict[str, JsonValue],
        role: str,
        model: str,
        skill: str,
    ) -> dict[str, JsonValue]:
        """Register a planned run of a frozen design. The `cell` is `{universe, seed, arm, split}`:
        `universe` the pairs of axis key and value (sorted by key), `arm` one of treatment,
        baseline, `ablation:<name>`, `control:<name>`, `reproduction:<row_key>`, and `split` dev or
        confirmatory. The platform computes the run's configuration; sending one is refused. A
        confirmatory cell needs the researcher's unlock, and a cell the design does not plan is
        accepted only on the dev split, as exploratory. You never submit a result. Refused to a
        session that has joined a pass."""

        def register() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = parse_input(Cell, cast(JsonValue, cell), "cell")
            run_id = xruns_service.register_run(opened, actor, experiment_id, parsed)
            return _withheld(opened, {"run_id": run_id}, include_work_ids=False)

        return _reply(project, register, include_work_ids=False)

    @server.tool()
    def xrun_list(
        project: str,
        experiment_id: str,
        arm: str | None = None,
        split: str | None = None,
    ) -> dict[str, JsonValue]:
        """The runs of a design with their cell, configuration hash, state (planned, completed,
        failed), exploratory mark and flags; no metric value. Read-only; refused to a session that
        has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            if experiments_service.experiment_view(opened, experiment_id) is None:
                raise FactoryValidationError([ValidationIssue("experiment_id", "unknown")])
            runs = xruns_service.xrun_list(opened, experiment_id, arm=arm, split=split)
            rows: list[JsonValue] = [
                r.model_dump(
                    mode="json",
                    include={
                        "run_id",
                        "cell",
                        "config_hash",
                        "state",
                        "exploratory",
                        "flags",
                        "event_id",
                    },
                )
                for r in runs
            ]
            return _withheld(opened, {"runs": rows}, include_work_ids=False)

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def registry_query(
        project: str,
        keys: list[str] | None = None,
        reasons: list[str] | None = None,
        limit: int = 50,
        after: str | None = None,
    ) -> dict[str, JsonValue]:
        """Search the failed-directions registry: refuted, inconclusive and abandoned hypotheses,
        discarded leads, baselines that did not reproduce and directions the researcher closed.
        Give `keys` (a method card, a lineage idea, a property key, a work, a trigger, an evidence
        row or `ds:<dataset>`) to find the rows that share one, and `reasons` to narrow them. Each
        row states why it failed and the conditions it failed under (design, datasets, compute,
        models, code commit) in a fixed sentence of ids and names: a row says "failed here", never
        "impossible", and is never removed. A baseline that reproduces on the confirmatory split
        is left out until the unlock. Read-only; refused to a session that has joined a
        pass."""

        def query() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            page = directions_service.registry_query(
                opened, keys or (), reasons=reasons, limit=limit, after=after, agent=True
            )
            return _withheld(opened, page.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, query, include_work_ids=False)

    @server.tool()
    def benchmark_ledger_view(project: str, group_id: str | None = None) -> dict[str, JsonValue]:
        """The benchmark ledger: for each evidence group (or the one named), its rows with the
        reported value, the reproduced value and whether it reproduced (`reproduced`,
        `not-reproduced`, `accepted`, `none`; `resolved`, with no value, while a confirmatory
        reproduction awaits the unlock) and the own results of hypotheses whose conditions and
        metric the group holds. Own and reproduced results never enter the evidence report.
        Read-only; refused to a session that has joined a pass."""

        def view() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened)
            groups = ledger_service.ledger(opened, group_id=group_id, agent=True)
            data: dict[str, JsonValue] = {
                "groups": [g.model_dump(mode="json") for g in groups],
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, view, include_work_ids=False)

    # The surface reads (plan MS). Each is refused to a pass session (decisions 37 and 43: a pass
    # session gets what it needs in its batch). A tool that names works also answers neutrally
    # before a pass opens, as the graph tools do. No tool here performs a human act: imports,
    # conversion, gate decisions and resolutions stay on the CLI (decisions 46 item 7 and 60).

    @server.tool()
    def protocol_view(project: str) -> dict[str, JsonValue]:
        """The current protocol: its id, status, PRESS state, whole spec and amendments, so the
        spec can be read and passed back to `protocol_amend`. `notice` says so when none is
        recorded. No seed data. Read-only; refused to a session that has joined a pass."""

        def view() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            found = protocol_service.protocol_view(opened)
            data = found.model_dump(mode="json")
            if found.protocol_id is None:
                data["notice"] = "no protocol recorded yet"
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, view, include_work_ids=False)

    @server.tool()
    def question_view(project: str) -> dict[str, JsonValue]:
        """The current question: its id, spec and the latest raw goal, verbatim. `notice` says so
        when none is recorded. Read-only; refused to a session that has joined a pass."""

        def view() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            found = question_service.question_view(opened)
            data = found.model_dump(mode="json")
            if found.question_id is None:
                data["notice"] = "no question recorded yet"
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, view, include_work_ids=False)

    @server.tool()
    def document_status(
        project: str, cursor: str | None = None, limit: int = PAGE_LIMIT
    ) -> dict[str, JsonValue]:
        """The conversion state of each live document of a promoted work, one page at a time:
        converted or not, the converter and version, anchor counts and the latest failure's
        reason, with the totals. No document text. Conversion is the researcher's act
        (`factory document convert`). Read-only. Refused to a session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            found = document_convert_service.document_status(opened)
            page = paginate(found.documents, cursor, limit)
            rows: list[JsonValue] = [row.model_dump(mode="json") for row in page.items]
            data = _listing(rows, page.next_cursor, "no document of a promoted work yet")
            data["converted"] = found.converted
            data["not_converted"] = found.not_converted
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def report_search(project: str) -> dict[str, JsonValue]:
        """The PRISMA-S search report alone: each registered query and what it retrieved. While
        no pass is open an import is one row without counts, as in `report_prisma`. Read-only.
        Refused to a session that has joined a pass."""

        def report() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            return agent_view_service.search_view(opened)

        return _reply(project, report, include_work_ids=False)

    @server.tool()
    def flow_works(
        project: str,
        source_group: str | None = None,
        step: str | None = None,
        outcome: str | None = None,
        criterion: str | None = None,
        cursor: str | None = None,
        limit: int = PAGE_LIMIT,
    ) -> dict[str, JsonValue]:
        """The work ledger: one row per identified record (a canonical work or an absorbed
        duplicate), with its source group, its title/abstract state and its full-text state. Filter
        by `source_group` (as `report_prisma(by_source=true)` names them), by `step`
        (`title-abstract`, `full-text-retrieval` or `full-text`), by that step's `outcome`, and by
        `criterion` (with `step`, and `outcome` `excluded`). Unknown filters, a cursor past the
        end and a limit above 50 are refused with the field named. One page of `limit` (at most
        50); `next_cursor` continues it. Read-only. Refused to a session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            return agent_view_service.flow_works_view(
                opened,
                source_group=source_group,
                step=step,
                outcome=outcome,
                criterion=criterion,
                cursor=cursor,
                limit=limit,
            )

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def flow_skipped(project: str) -> dict[str, JsonValue]:
        """The raw records that never became works (`untitled`, `duplicate-within-run` or
        `unparsed`), and each query's runs against the total its source reported (`run_gaps`).
        Read-only. Refused to a session that has joined a pass."""

        def skipped() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            return agent_view_service.flow_skipped_view(opened)

        return _reply(project, skipped, include_work_ids=False)

    @server.tool()
    def flow_trail(project: str, work_id: str) -> dict[str, JsonValue]:
        """The trail of one work: what happened to it, in time order (where it was found, merges
        and their reversal, screening and full-text decisions, and the extraction and claim counts),
        read from the events. An unknown work id is refused with the field named. Read-only.
        Refused to a session that has joined a pass."""

        def trail() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            return agent_view_service.flow_trail_view(opened, work_id)

        return _reply(project, trail, include_work_ids=False)

    @server.tool()
    def extraction_status(
        project: str, cursor: str | None = None, limit: int = PAGE_LIMIT
    ) -> dict[str, JsonValue]:
        """Each evidence extraction unit (a work in one pass) with its state (queued, open,
        current, stale) and why it is stale, one page at a time, and the counts by state. No row
        or value. Read-only. Refused to a session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            units = extraction_service.unit_states(opened)
            page = paginate(units, cursor, limit)
            rows: list[JsonValue] = [unit.model_dump(mode="json") for unit in page.items]
            data = _listing(rows, page.next_cursor, "no extraction unit yet")
            data["counts"] = cast(JsonValue, dict(Counter(unit.state for unit in units)))
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def contribution_status(
        project: str, cursor: str | None = None, limit: int = PAGE_LIMIT
    ) -> dict[str, JsonValue]:
        """The contribution counts: units by state, final items by kind, not-stated kinds and
        citation markers. The three lists (`no_references`, `other_conversion`,
        `closed_without_items`) are one page each, with their totals in `totals`; `next_cursor`
        continues them together. Read-only. Refused to a session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            found = contributions_service.contribution_status(opened)
            data: dict[str, JsonValue] = found.model_dump(
                mode="json",
                exclude={"no_references", "other_conversion", "closed_without_items"},
            )
            lists: dict[str, list[JsonValue]] = {
                "no_references": list(found.no_references),
                "other_conversion": list(found.other_conversion),
                "closed_without_items": [
                    item.model_dump(mode="json") for item in found.closed_without_items
                ],
            }
            pages = {name: paginate(rows, cursor, limit) for name, rows in lists.items()}
            data.update({name: page.items for name, page in pages.items()})
            data["totals"] = {name: len(rows) for name, rows in lists.items()}
            data["next_cursor"] = next(
                (p.next_cursor for p in pages.values() if p.next_cursor is not None), None
            )
            if not found.units:
                data["notice"] = "no contribution unit yet"
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    @server.tool()
    def relation_list(
        project: str,
        work_id: str | None = None,
        status: list[str] | None = None,
        cursor: str | None = None,
        limit: int = PAGE_LIMIT,
    ) -> dict[str, JsonValue]:
        """Live relations by source, type and target, one page at a time, each with its effective
        status, the reasons it is stale and its basis item. `work_id` matches the source or the
        target; `status` widens the default (stated, confirmed) to inferred, stale or rejected.
        Empty with a notice until a screening pass has opened. Read-only; refused to a session
        that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            statuses = _edge_statuses(status)
            offset, size = _window(cursor, limit)
            if _before_any_pass(opened):
                return NOT_YET
            views = relations_service.list_relations(
                opened, statuses=statuses, work_id=work_id, limit=size + 1, offset=offset
            )
            rows: list[JsonValue] = [view.model_dump(mode="json") for view in views[:size]]
            following = str(offset + size) if len(views) > size else None
            return _withheld(
                opened, _listing(rows, following, "no relation found"), include_work_ids=False
            )

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def idea_list(
        project: str,
        status: str = "confirmed",
        cursor: str | None = None,
        limit: int = PAGE_LIMIT,
    ) -> dict[str, JsonValue]:
        """Ideas by id, one page at a time, with name, origin, members and state. `status` is
        `confirmed` (default) or `all`, which adds the ideas still only proposed; a rejected,
        merged or superseded idea is never listed. Empty with a notice until a screening pass has
        opened. Read-only; refused to a session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            if status not in ("confirmed", "all"):
                raise FactoryValidationError(
                    [ValidationIssue("status", "must be confirmed or all")]
                )
            offset, size = _window(cursor, limit)
            if _before_any_pass(opened):
                return NOT_YET
            views = ideas_service.list_ideas(
                opened, include_unconfirmed=status == "all", limit=size + 1, offset=offset
            )
            rows: list[JsonValue] = [view.model_dump(mode="json") for view in views[:size]]
            following = str(offset + size) if len(views) > size else None
            return _withheld(
                opened, _listing(rows, following, "no idea found"), include_work_ids=False
            )

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def concept_list(
        project: str,
        state: str | None = None,
        cursor: str | None = None,
        limit: int = PAGE_LIMIT,
    ) -> dict[str, JsonValue]:
        """Background concepts by id, one page at a time, each with `class` and `label` (never
        evidence), text, source, review state and flags. By default the visible ones; `state`
        (unreviewed, reviewed, wrong, merged) lists those in that state, hidden or not. The hidden
        counts are always reported; `next_cursor` is the id to continue after. Empty with a notice
        until a screening pass has opened. Read-only; refused to a session that has joined a
        pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            try:
                chosen = None if state is None else ConceptState(state)
            except ValueError:
                choices = ", ".join(item.value for item in ConceptState)
                raise FactoryValidationError(
                    [ValidationIssue("state", f"must be among {choices}")]
                ) from None
            if _before_any_pass(opened):
                return NOT_YET
            found = concepts_service.list_concepts(
                opened,
                review_state=chosen,
                cursor=cursor,
                limit=min(max(limit, 1), PAGE_LIMIT),
            )
            rows: list[JsonValue] = [
                item.model_dump(mode="json", by_alias=True, exclude={"input_blob"})
                for item in found.items
            ]
            data = _listing(rows, found.next_cursor, "no concept found")
            data["hidden"] = found.hidden.model_dump(mode="json")
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def lead_list(
        project: str,
        state: list[str] | None = None,
        cursor: str | None = None,
        limit: int = PAGE_LIMIT,
    ) -> dict[str, JsonValue]:
        """Leads by id, one page at a time, with triggers, framework, prior failures and state
        (`state` narrows to open, promoted, parked or discarded). The lead's text is shown to its
        author's session only: everywhere else `text` is null (R-51). Empty with a notice until a
        screening pass has opened. Read-only; refused to a session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            allowed = get_args(leads_service.LeadState)
            if state and any(name not in allowed for name in state):
                raise FactoryValidationError(
                    [ValidationIssue("state", f"must be among {', '.join(allowed)}")]
                )
            if _before_any_pass(opened):
                return NOT_YET
            chosen = cast(list[leads_service.LeadState], state or list(allowed))
            page = paginate(
                leads_service.agent_leads(opened, opened.session, states=chosen), cursor, limit
            )
            rows: list[JsonValue] = [row.model_dump(mode="json") for row in page.items]
            return _withheld(
                opened, _listing(rows, page.next_cursor, "no lead found"), include_work_ids=False
            )

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def hypothesis_list(
        project: str,
        state: list[str] | None = None,
        cursor: str | None = None,
        limit: int = PAGE_LIMIT,
    ) -> dict[str, JsonValue]:
        """Hypotheses by id, one page at a time, as `hypothesis_view` shows each: the rationale
        and the lead to the drafting session only, and no drafter session or model. `state`
        narrows to draft, reviewed, registered, evaluated, abandoned or superseded. Empty with a
        notice until a screening pass has opened. Read-only; refused to a session that has joined
        a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            allowed = get_args(hypotheses_service.HypothesisState)
            if state and any(name not in allowed for name in state):
                raise FactoryValidationError(
                    [ValidationIssue("state", f"must be among {', '.join(allowed)}")]
                )
            if _before_any_pass(opened):
                return NOT_YET
            page = paginate(
                hypotheses_service.agent_hypotheses(opened, opened.session, states=state or None),
                cursor,
                limit,
            )
            rows = cast(list[JsonValue], page.items)
            return _withheld(
                opened,
                _listing(rows, page.next_cursor, "no hypothesis found"),
                include_work_ids=False,
            )

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def card_list(
        project: str,
        kind: str | None = None,
        cursor: str | None = None,
        limit: int = PAGE_LIMIT,
    ) -> dict[str, JsonValue]:
        """Method and problem cards by id, one page at a time, each with its subject, owner and
        live assertion count; `kind` is method or problem. `card_view` reads one. Empty with a
        notice until a screening pass has opened. Read-only; refused to a session that has joined
        a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            if kind is not None and kind not in get_args(CardKind):
                raise FactoryValidationError([ValidationIssue("kind", "must be method or problem")])
            offset, size = _window(cursor, limit)
            if _before_any_pass(opened):
                return NOT_YET
            cards = cards_service.list_cards(
                opened, cast(CardKind | None, kind), limit=size + 1, offset=offset
            )
            rows: list[JsonValue] = [card.model_dump(mode="json") for card in cards[:size]]
            following = str(offset + size) if len(cards) > size else None
            return _withheld(
                opened, _listing(rows, following, "no card found"), include_work_ids=False
            )

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def experiment_list(
        project: str,
        hypothesis_id: str | None = None,
        cursor: str | None = None,
        limit: int = PAGE_LIMIT,
    ) -> dict[str, JsonValue]:
        """Experiment designs by id, one page at a time: hypothesis, version `E@`, computed state,
        flags, the deviation count and the baseline states as `experiment_view` shows them. No
        metric or baseline value and no design: `experiment_view` reads one. Empty with a notice
        until a screening pass has opened. Read-only; refused to a session that has joined a
        pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            if _before_any_pass(opened):
                return NOT_YET
            page = paginate(
                experiments_service.agent_experiments(opened, hypothesis_id=hypothesis_id),
                cursor,
                limit,
            )
            rows: list[JsonValue] = [row.model_dump(mode="json") for row in page.items]
            return _withheld(
                opened,
                _listing(rows, page.next_cursor, "no experiment found"),
                include_work_ids=False,
            )

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def draft_list(
        project: str, cursor: str | None = None, limit: int = PAGE_LIMIT
    ) -> dict[str, JsonValue]:
        """Drafts by id, one page at a time: title, kind, pinned outline, sections and the count
        of live sentences. A draft this session verifies is not listed: a verifier reads only its
        unit. Empty with a notice until a screening pass has opened. Read-only; refused to a
        session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            if _before_any_pass(opened):
                return NOT_YET
            page = paginate(drafts_service.agent_drafts(opened, opened.session), cursor, limit)
            rows: list[JsonValue] = [row.model_dump(mode="json") for row in page.items]
            return _withheld(
                opened, _listing(rows, page.next_cursor, "no draft found"), include_work_ids=False
            )

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def draft_repin(
        project: str,
        draft_id: str,
        role: str,
        model: str,
        skill: str,
        scope_works: list[str] | None = None,
        ideas: list[str] | None = None,
        groups: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """Pin a draft to a fresh outline, of the same scope unless one is named (see
        `writing_outline`). Sections new to the draft are added and `draft_next` serves them;
        sentences whose supports left the outline read as off-outline; a slot task of the old
        outline is retired, so ask `draft_next` again. Refused to a session that verifies the
        draft, to a session that has joined a pass, and before a screening pass has opened."""

        def repin() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            actor = make_agent_actor(settings, session, role, model, skill)
            scope = None
            if scope_works is not None or ideas is not None or groups is not None:
                scope = outline_service.OutlineScope(
                    works="included" if scope_works is None else tuple(scope_works),
                    ideas=None if ideas is None else tuple(ideas),
                    groups=None if groups is None else tuple(groups),
                )
            event_id = drafts_service.repin_outline(opened, draft_id, scope, actor=actor)
            return _withheld(opened, {"event_id": event_id}, include_work_ids=False)

        return _reply(project, repin, include_work_ids=False)

    @server.tool()
    def draft_reorder(
        project: str,
        draft_id: str,
        section_id: str,
        order: list[str],
        role: str,
        model: str,
        skill: str,
    ) -> dict[str, JsonValue]:
        """Set the order of a section's sentences: `order` lists exactly its live sentences, once
        each. Refused to a session that verifies the draft, to a session that has joined a pass,
        and before a screening pass has opened."""

        def reorder() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            _require_pass_opened(opened, "view")
            actor = make_agent_actor(settings, session, role, model, skill)
            event_id = drafts_service.reorder(opened, draft_id, section_id, order, actor=actor)
            return _withheld(opened, {"event_id": event_id}, include_work_ids=False)

        return _reply(project, reorder, include_work_ids=False)

    @server.tool()
    def dedup_merges(
        project: str, cursor: str | None = None, limit: int = PAGE_LIMIT
    ) -> dict[str, JsonValue]:
        """Every merge by id, active and reverted, one page at a time, with the matching rule, the
        record count, the works and a reversal's reason. Until a screening pass has opened the
        works and reasons are null on every row. Read-only; refused to a session that has joined a
        pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            merges = dedup_service.list_merges(opened, named=not _before_any_pass(opened))
            page = paginate(merges, cursor, limit)
            rows: list[JsonValue] = [row.model_dump(mode="json") for row in page.items]
            return _withheld(
                opened, _listing(rows, page.next_cursor, "no merge yet"), include_work_ids=False
            )

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def merge_revert(
        project: str, merge_id: str, reason: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Undo an active merge, stating why. The pair stays apart on every later `dedup_run`, and
        your input is kept for audit. Refused to a session that has joined a pass."""

        def revert() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            dedup_service.revert_merge(opened, actor, merge_id, reason)
            return _withheld(opened, {"merge_id": merge_id}, include_work_ids=False)

        return _reply(project, revert, include_work_ids=False)

    @server.tool()
    def lessons_list(
        project: str, cursor: str | None = None, limit: int = PAGE_LIMIT
    ) -> dict[str, JsonValue]:
        """The computed lessons a curation proposal can answer, by id, one page at a time: audit
        errors and disagreements by criterion, `cannot-assess` spikes and failed runs, each with
        its kind, subject and a count. No rate is given (decision 43). Empty with a notice when
        there are none. Read-only; refused to a session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            offset, size = _window(cursor, limit)
            found = curation_service.lessons(opened)
            rows: list[JsonValue] = [
                item.model_dump(mode="json") for item in found[offset : offset + size]
            ]
            following = str(offset + size) if len(found) > offset + size else None
            return _withheld(
                opened, _listing(rows, following, "no lesson yet"), include_work_ids=False
            )

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def curation_propose(
        project: str,
        kind: str,
        text: str,
        lessons: list[str],
        role: str,
        model: str,
        skill: str,
        target: str | None = None,
    ) -> dict[str, JsonValue]:
        """Record a curation proposal: `kind` is `amendment`, `worked-example` or `skill-revision`,
        `text` what is proposed, `lessons` one to twenty ids from `lessons_list`, `target` the
        protocol part or skill it concerns. A human other than the proposer decides; an accepted
        amendment still goes through `protocol_amend`, and a revised skill must pass calibration
        before use. Returns the `cur_` id. Refused to a session that has joined a pass."""

        def propose() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            try:
                chosen = CurationKind(kind)
            except ValueError:
                choices = ", ".join(item.value for item in CurationKind)
                raise FactoryValidationError(
                    [ValidationIssue("kind", f"must be among {choices}")]
                ) from None
            actor = make_agent_actor(settings, session, role, model, skill)
            cur_id = curation_service.propose(opened, actor, chosen, text, lessons, target)
            return _withheld(opened, {"cur_id": cur_id}, include_work_ids=False)

        return _reply(project, propose, include_work_ids=False)

    @server.tool()
    def task_release(
        project: str,
        task_id: str,
        role: str,
        model: str,
        skill: str,
        reason: str = "released by its holder",
    ) -> dict[str, JsonValue]:
        """Give back a task this session holds and cannot finish, so another session need not wait
        for the lease. Only the holder may release, so it serves a pass session too: it shows
        nothing of the task."""

        def release() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            tasks_service.release_task(opened, actor, task_id, reason)
            return _withheld(opened, {"task_id": task_id}, include_work_ids=False)

        return _reply(project, release, include_work_ids=False)

    @server.tool()
    def review_request(
        project: str,
        kind: str,
        proposal: dict[str, JsonValue],
        reason: str,
        role: str,
        model: str,
        skill: str,
    ) -> dict[str, JsonValue]:
        """File a review request for what you may not apply alone. `kind` is `protocol-amend`,
        `protocol-record` or `deviation`; `proposal` holds what that tool takes. Approval applies
        nothing: a holder of the role then runs the tool with `review_request_id`. Refused to a
        session that has joined a pass."""

        def request() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            filed = reviews_service.request_review(
                opened, actor, _review_kind(kind), proposal, reason
            )
            return {"review_request_id": filed}

        return _reply(project, request, include_work_ids=False)

    @server.tool()
    def review_list(
        project: str,
        state: str | None = None,
        review_request_id: str | None = None,
        cursor: str | None = None,
        limit: int = PAGE_LIMIT,
    ) -> dict[str, JsonValue]:
        """Review requests in filing order, or those in `state` (open, approved, rejected,
        withdrawn, consumed, stale). `review_request_id` returns that one with its proposal.
        Read-only. Refused to a session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            if review_request_id is not None:
                one: dict[str, JsonValue] = reviews_service.review(
                    opened, review_request_id
                ).model_dump(mode="json")
                one["proposal"] = reviews_service.proposal_of(opened, review_request_id)
                return _withheld(opened, one, include_work_ids=False)
            found = reviews_service.reviews(opened, state=_request_state(state))
            page = paginate(found, cursor, limit)
            items: list[JsonValue] = [view.model_dump(mode="json") for view in page.items]
            data: dict[str, JsonValue] = {"items": items, "next_cursor": page.next_cursor}
            if not found:
                data["notice"] = reviews_service.NO_REVIEWS_NOTICE
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def review_decide(
        project: str, review_request_id: str, decision: str, rationale: str
    ) -> dict[str, JsonValue]:
        """The human's decision on a review request, relayed: `approve`, `reject` or `withdraw`.
        The requester cannot approve or reject their own request, and only the requester
        withdraws. Refused to a session that has joined a pass."""

        def decide() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            channel, said = confirm_human_act(
                f"Decision on review request {review_request_id}",
                {"decision": decision, "rationale": rationale},
                {"decision": ("approve", "reject", "withdraw")},
            )
            reviews_service.decide_review(
                opened,
                opened.human_actor(),
                review_request_id,
                cast(ReviewDecision, said["decision"]),
                said["rationale"],
                channel,
            )
            return {"review_request_id": review_request_id, "decision": said["decision"]}

        return _reply(project, decide, include_work_ids=False)

    @server.tool()
    def appraisal_next(
        project: str, pass_label: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Serve the next appraisal task of pass A or B to this session, or say why none is
        served. The batch names the instrument, the span items to answer and the pinned
        conversion to read with `document_read`. Refused when the protocol declares no
        instrument, to a session in a screening or extraction pass, to a session or model that
        gave the other pass, and to a session that appraised and then extracts."""

        def serve() -> JsonValue:
            with unit_cap.serving() as done:
                label = _pass_label(pass_label)
                opened = open_project(settings, project, session=session, clock=clock)
                actor = make_agent_actor(settings, session, role, model, skill)
                served = appraisal_passes_service.appraisal_next(opened, actor, label)
                dumped = served.model_dump(mode="json")
                done(dumped)
            return _withheld(opened, dumped, include_work_ids=False)

        return _reply(project, serve, include_work_ids=False)

    @server.tool()
    def appraisal_record(
        project: str,
        task_id: str,
        answers: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
        finish: bool = False,
        reason: str | None = None,
    ) -> dict[str, JsonValue]:
        """Record answers read from a held appraisal task. An answer is {item, answer, anchor,
        quote}: answer is yes, no or unclear; yes and no need the anchor and a verbatim quote
        from that one anchor, unclear needs neither. An invalid answer is reported by index and
        the valid ones are written. `finish` closes the work once no answer of the call is
        rejected and every item has an answer. Judgement items are a human's and never served."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            good, bad = _parse_all(AnswerInput, answers, "answers")
            result = appraisal_passes_service.appraisal_record(
                opened,
                actor,
                task_id,
                [answer for _, answer in good],
                finish=finish and not bad,
                reason=reason,
            )
            merged = result.model_copy(
                update={
                    "rejected": sorted(
                        [
                            *bad,
                            *(
                                ItemError(index=good[e.index][0], issues=e.issues)
                                for e in result.rejected
                            ),
                        ],
                        key=lambda e: e.index,
                    )
                }
            )
            return _withheld(opened, merged.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, record, include_work_ids=False)

    @server.tool()
    def appraisal_status(project: str) -> dict[str, JsonValue]:
        """The appraisal counts: works, span items by state, judgement items open and recorded,
        stale works. No answer, quote or judgement. Read-only. Refused to a session that has
        joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            found = appraisal_service.appraisal_status(opened)
            return _withheld(opened, found.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    # --- Suggest and select (slice 8, plan A4) ---------------------------------------------
    # The agent suggests; the person selects, through an elicitation form and nowhere else over
    # MCP (the CLI is the other way). `decision_select` takes no item ids from the caller, so an
    # agent cannot tick for the person.

    @server.tool()
    def decision_suggest(
        project: str,
        level: str,
        subject: str,
        explanation: str,
        items: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
        supersedes: str | None = None,
    ) -> dict[str, JsonValue]:
        """Suggest a set of items for a decision the scientist owns, at one `level` (goal,
        questions, plan, seeds, probe, protocol). `subject` is a short slug (`exclusions`,
        `tooling`); `explanation` states the step and why. Each item is `{item_id, text, grounds,
        recommended}`: ids `I01`, `I02`, ...; `grounds` names what it rests on (a probe, a seed,
        a document, an earlier decision). `recommended` is allowed only on a technical subject
        (tooling, ordering, fix, model-choice, setting). `supersedes` names an earlier,
        unsuperseded decision this one replaces.
        Refused to a session that has joined a pass. Then wait: the person selects."""

        def suggest() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            issues: list[ValidationIssue] = []
            try:
                chosen_level = DecisionLevel(level)
            except ValueError:
                chosen_level = DecisionLevel.GOAL
                issues.append(ValidationIssue("level", f"must be {_choices(DecisionLevel)}"))
            parsed: list[DecisionItem] = []
            for index, raw in enumerate(items):
                try:
                    parsed.append(parse_input(DecisionItem, raw, f"items.{index}"))
                except FactoryValidationError as exc:
                    issues.extend(exc.issues)
            if issues:
                raise FactoryValidationError(issues)
            decision_id = decisions_service.suggest(
                opened, actor, chosen_level, subject, explanation, parsed, supersedes
            )
            return _withheld(opened, {"decision_id": decision_id}, include_work_ids=False)

        return _reply(project, suggest, include_work_ids=False)

    @server.tool()
    def decision_select(project: str, decision_id: str) -> dict[str, JsonValue]:
        """The person's selection on a decision, asked of the person through an elicitation form:
        tick the items to keep, add items of their own, give a note. There is no way to pass
        item ids here. Refused, with nothing asked or written, for an unknown or superseded
        decision, when the connection has no credential or the client does not support
        elicitation; the person then runs `factory decide select`. Refused to a session that has
        joined a pass."""

        def choose() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            view = decisions_service.view_decision(opened, decision_id)
            if view.state == "superseded":
                raise FactoryValidationError(
                    [ValidationIssue("decision_id", f"superseded by {view.superseded_by}")]
                )
            answer = elicit_human_selection(
                f"Decision {decision_id} ({view.level}: {view.subject})",
                view.explanation,
                [(i.item_id, i.text) for i in view.items if i.origin == "suggested"],
            )
            event_id = decisions_service.select(
                opened,
                opened.human_actor(),
                decision_id,
                answer.selected,
                answer.added,
                answer.note,
                Channel.ELICIT,
            )
            data: dict[str, JsonValue] = {
                "event_id": event_id,
                "selected": list(answer.selected),
                "added": list(answer.added),
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, choose, include_work_ids=False)

    @server.tool()
    def decision_list(
        project: str,
        level: str | None = None,
        open_only: bool = False,
        cursor: str | None = None,
        limit: int = PAGE_LIMIT,
    ) -> dict[str, JsonValue]:
        """The decisions, in id order, one page at a time: level, subject, state (`open` until
        the person selects, then `selected`, or `superseded`), the number of suggested and
        selected items. `open_only` keeps those awaiting the person. Read-only. Refused to a
        session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            try:
                chosen = None if level is None else DecisionLevel(level)
            except ValueError:
                raise FactoryValidationError(
                    [ValidationIssue("level", f"must be {_choices(DecisionLevel)}")]
                ) from None
            found = decisions_service.list_decisions(opened, chosen, open_only)
            page = paginate(found, cursor, limit)
            data: dict[str, JsonValue] = {
                "items": [row.model_dump(mode="json") for row in page.items],
                "next_cursor": page.next_cursor,
            }
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, listing, include_work_ids=False)

    @server.tool()
    def decision_view(project: str, decision_id: str) -> dict[str, JsonValue]:
        """One decision: its explanation, every item with status (proposed, validated, rejected,
        added), origin, grounds and whether it was recommended; the latest selection with the
        person's note; and the decisions it supersedes or is superseded by. Read-only. Refused to
        a session that has joined a pass."""

        def view() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            found = decisions_service.view_decision(opened, decision_id)
            return _withheld(opened, found.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, view, include_work_ids=False)

    @server.tool()
    def develop_render(project: str, level: str) -> dict[str, JsonValue]:
        """One level of the develop stage (goal, questions, plan, seeds, probe, protocol) rendered
        as a formal Markdown document from its decisions: the step and reason, each item with
        its status (Validated, Rejected, Added, Proposed) and grounds, the person's note and the
        supersession history; for questions and protocol also the recorded spec. Records the
        version (nothing is written when the document is unchanged). Refused to a session that
        has joined a pass."""

        def render() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            try:
                chosen = DecisionLevel(level)
            except ValueError:
                raise FactoryValidationError(
                    [ValidationIssue("level", f"must be {_choices(DecisionLevel)}")]
                ) from None
            result = develop_render_service.render_level(opened, chosen)
            data = result.model_dump(mode="json", exclude={"sources"})
            return _withheld(opened, data, include_work_ids=False)

        return _reply(project, render, include_work_ids=False)

    @server.tool()
    def progress_status(project: str) -> dict[str, JsonValue]:
        """The long operations running now or finished in the last ten minutes (ranking, search
        paging, snowball and probe queries, deduplication): done, total, unit, state, rate per
        second and seconds left. Ephemeral: read from small files, never an event, never stored
        in the index. Read-only. Refused to a session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            rows = progress_service.progress_list(opened)
            return _withheld(opened, {"operations": cast(JsonValue, rows)}, include_work_ids=False)

        return _reply(project, status, include_work_ids=False)

    return server


def _review_kind(value: str) -> ReviewKind:
    try:
        return ReviewKind(value)
    except ValueError:
        choices = ", ".join(kind.value for kind in ReviewKind)
        raise FactoryValidationError(
            [ValidationIssue("kind", f"must be one of: {choices}")]
        ) from None


def _proposal_kind(value: str) -> ProposalKind:
    """A taxonomy change kind; any other word is refused with the choices named."""
    kinds = get_args(ProposalKind)
    if value in kinds:
        return cast(ProposalKind, value)
    raise FactoryValidationError([ValidationIssue("kind", f"must be one of: {', '.join(kinds)}")])


def _request_state(value: str | None) -> RequestState | None:
    if value is None:
        return None
    try:
        return RequestState(value)
    except ValueError:
        choices = ", ".join(state.value for state in RequestState)
        raise FactoryValidationError(
            [ValidationIssue("state", f"must be one of: {choices}")]
        ) from None


def _refuse_pass_session(project: Project) -> None:
    """A session that screens or extracts must not read the other pass's results, the report
    surfaces or the answer key (R-20)."""
    if passes_service.is_pass_session(project, project.session):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session has joined a pass and cannot use this tool")]
        )
    human_pass_service.refuse_blind_reader(project, project.principal.user)


def _listing(rows: list[JsonValue], next_cursor: str | None, empty: str) -> dict[str, JsonValue]:
    """One page of a list tool; `notice` says why it holds nothing."""
    data: dict[str, JsonValue] = {"items": rows, "next_cursor": next_cursor}
    if not rows and next_cursor is None:
        data["notice"] = empty
    return data


def _before_any_pass(project: Project) -> bool:
    """Whether a list that names works answers empty: before a screening pass opens an agent must
    not be able to name a held-out seed's work (decision 43). Role-blind, like
    `_require_pass_opened`, and it reads no row, so the answer says nothing of what exists."""
    return not coverage_service.held_out_visible(project)


NOT_YET: dict[str, JsonValue] = {"items": [], "next_cursor": None, "notice": "not available yet"}
"""A list tool's whole answer before a screening pass opens; the same for every project."""


def _window(cursor: str | None, limit: int) -> tuple[int, int]:
    """The offset and page size a cursor and limit name, for a service that pages in SQL. Fetch
    one row more than the size to learn whether another page follows."""
    paginate((), cursor, limit)  # validates the cursor
    return (0 if cursor is None else int(cursor)), min(max(limit, 1), PAGE_LIMIT)


def _edge_statuses(values: list[str] | None) -> frozenset[EdgeStatus]:
    """The statuses a relation list shows; the default view when none is named."""
    if not values:
        return DEFAULT_STATUSES
    try:
        return frozenset(EdgeStatus(value) for value in values)
    except ValueError:
        choices = ", ".join(status.value for status in EdgeStatus)
        raise FactoryValidationError(
            [ValidationIssue("status", f"must be among {choices}")]
        ) from None


REGION_PAGE_LIMIT = 500
"""The most members one `region_query` page returns."""
REGIONS_OF_LIMIT = 100
"""The most regions one `regions_of` answer returns."""


def _region_kind(value: str) -> RegionKind:
    try:
        return RegionKind(value)
    except ValueError:
        raise FactoryValidationError([ValidationIssue("kind", "must be focus or region")]) from None


def _member_type(value: str) -> MemberType:
    try:
        return MemberType(value)
    except ValueError:
        raise FactoryValidationError(
            [ValidationIssue("member_type", "must be work, idea or concept")]
        ) from None


def _parse_basis(data: JsonValue) -> MemberBasis:
    try:
        return TypeAdapter(MemberBasis).validate_python(data)
    except ValidationError as exc:
        issues = [
            ValidationIssue(".".join(["basis", *(str(p) for p in err["loc"])]), str(err["msg"]))
            for err in exc.errors()
        ]
        raise FactoryValidationError(issues) from exc


def _need(**fields: str | None) -> None:
    missing = [ValidationIssue(name, "required") for name, value in fields.items() if not value]
    if missing:
        raise FactoryValidationError(missing)


def _member_page(members: Sequence[tuple[MemberType, str]]) -> list[JsonValue]:
    return [{"type": kind.value, "id": ident} for kind, ident in members]


def _region_read(
    project: Project,
    query: str,
    version: str | None,
    member_type: str | None,
    member: str | None,
    a: str | None,
    b: str | None,
    offset: int,
    limit: int,
) -> JsonValue:
    """The four reads of `region_query`. A region withheld from agents is refused whole (versions)
    or left out (`regions_of`); no member is ever filtered."""
    page_size = min(max(limit, 1), REGION_PAGE_LIMIT)
    if offset < 0:
        raise FactoryValidationError([ValidationIssue("offset", "must not be negative")])
    if query == "members":
        _need(version=version)
        assert version is not None
        regions_service.require_agent_visible(project, version=version)
        info = regions_service.version_info(project, version)
        if info is None:
            raise FactoryValidationError([ValidationIssue("version", "version-unknown")])
        rows = regions_service.region_members(project, version, offset=offset, limit=page_size)
        end = offset + len(rows)
        total = sum(info.counts.values())
        return {
            "version": version,
            "members": _member_page(rows),
            "next_offset": end if end < total else None,
            "counts": dict(info.counts),
        }
    if query == "regions_of":
        _need(member_type=member_type, member=member)
        assert member_type is not None and member is not None
        found = regions_service.regions_of(project, _member_type(member_type), member)
        shown = [m for m in found if not regions_service.region_withheld(project, m.region_id)]
        window = shown[offset : offset + REGIONS_OF_LIMIT]
        end = offset + len(window)
        return {
            "regions": [m.model_dump(mode="json") for m in window],
            "next_offset": end if end < len(shown) else None,
        }
    _need(a=a, b=b)
    assert a is not None and b is not None
    regions_service.require_agent_visible(project, version=a)
    regions_service.require_agent_visible(project, version=b)
    if query == "overlap":
        return regions_service.overlap(project, a, b).model_dump(mode="json")
    page = regions_service.diff(project, a, b, offset=offset, limit=page_size)
    end = offset + len(page.added) + len(page.removed)
    return {
        "a": a,
        "b": b,
        "added": _member_page(page.added),
        "removed": _member_page(page.removed),
        "total_added": page.total_added,
        "total_removed": page.total_removed,
        "next_offset": end if end < page.total_added + page.total_removed else None,
    }


def _index_keys(name: str, given: Mapping[str, str]) -> dict[int, str]:
    """A `supersedes` object's keys as row indices; MCP delivers JSON keys as strings. A key that
    is not an integer is refused, with every such key named, before anything is written."""
    out: dict[int, str] = {}
    issues: list[ValidationIssue] = []
    for key, target in given.items():
        if key.isascii() and key.isdigit():
            out[int(key)] = target
        else:
            issues.append(ValidationIssue(f"{name}.{key}", "key must be an integer item index"))
    if issues:
        raise FactoryValidationError(issues)
    return out


def _expectations(items: list[dict[str, JsonValue]]) -> list[dict[str, str]]:
    """Each expectation as a non-empty map of text to text, or a refusal naming the item."""
    issues: list[ValidationIssue] = []
    parsed: list[dict[str, str]] = []
    for index, item in enumerate(items):
        if not item or not all(isinstance(v, str) and v.strip() for v in item.values()):
            issues.append(
                ValidationIssue(f"expect.{index}", "must be a non-empty map of key to text value")
            )
        else:
            parsed.append({k: str(v) for k, v in item.items()})
    if issues:
        raise FactoryValidationError(issues)
    return parsed


def _plain(value: object) -> JsonValue:
    """`value` as plain JSON (tuples become lists), for a dataclass turned by `asdict`."""
    return cast(JsonValue, json.loads(json.dumps(value)))


def _parse_all(
    model: type[_M], items: list[dict[str, JsonValue]], name: str
) -> tuple[list[tuple[int, _M]], list[ItemError]]:
    """Each item that is a valid `model`, with its index, and each rejection by index."""
    accepted: list[tuple[int, _M]] = []
    rejected: list[ItemError] = []
    for index, item in enumerate(items):
        try:
            accepted.append((index, parse_input(model, item, f"{name}.{index}")))
        except FactoryValidationError as exc:
            rejected.append(ItemError(index=index, issues=exc.issues))
    return accepted, rejected


def _renumbered(
    name: str, targets: Mapping[int, str], accepted: Sequence[tuple[int, object]], total: int
) -> dict[int, str]:
    """`targets` (keyed by call index) keyed by position among the items that parsed. A target of
    an item that failed to parse is dropped, since that item is reported rejected; a key outside
    the call is refused."""
    position = {original: place for place, (original, _) in enumerate(accepted)}
    out: dict[int, str] = {}
    for index, target in targets.items():
        if index in position:
            out[position[index]] = target
        elif not 0 <= index < total:
            raise FactoryValidationError(
                [ValidationIssue(f"{name}.{index}", "is not an item index of this call")]
            )
    return out


def _merged(
    result: BatchResult[str], accepted: Sequence[tuple[int, object]], parse_errors: list[ItemError]
) -> BatchResult[str]:
    """The service's result with its rejections renumbered to call indices, and those of items
    that failed to parse added, by index."""
    errors = [
        ItemError(index=accepted[error.index][0], issues=error.issues) for error in result.rejected
    ]
    return BatchResult[str](
        written=result.written, rejected=sorted(errors + parse_errors, key=lambda e: e.index)
    )


def _without_hidden_acceptances(row: GateStatusRow, hidden: int) -> GateStatusRow:
    """A gate row for an agent, without the acceptances of baselines whose verdict it may not read
    yet: only `not-reproduced` can be accepted (decision 94). The gate is human in every mode."""
    if row.gate_id != "experiments.accept_baseline" or not hidden:
        return row
    human = Autonomy.HUMAN.value
    counts = {**row.counts, human: max(0, row.counts[human] - hidden)}
    return row.model_copy(update={"counts": counts})


def _withheld(
    project: Project,
    value: JsonValue,
    include_work_ids: bool = True,
    same_length: bool = False,
    seed_ids_only: bool = False,
) -> JsonValue:
    """Strip every held-out seed's identifiers from an agent-facing response (R-20). With
    `same_length` a match is filled with `#` of its own length, so offsets stay exact. With
    `seed_ids_only` (the feed tools) only held-out seed ids are stripped; see `seed_id_tokens`."""
    if seed_ids_only:
        return withhold(value, seed_id_tokens(project), same_length)
    return withhold(value, _held_out_tokens(project, include_work_ids), same_length)


def _held_out_tokens(project: Project, include_work_ids: bool = True) -> set[str]:
    """See `withholding.held_out_tokens`."""
    return held_out_tokens(project, include_work_ids)


def _check_label(work_id: str, verdict: str, criterion: str | None) -> None:
    """The label's own fields, checked by the model. A criterion is given bare, so it is qualified
    with a placeholder version only for this check; the service qualifies it for real."""
    qualified = None if criterion is None else f"P@00000000:{criterion}"
    fields: dict[str, JsonValue] = {
        "work_id": work_id,
        "verdict": verdict,
        "criterion": qualified,
        "channel": Channel.MCP.value,
    }
    try:
        parse_input(CalibrationLabelled, fields, "label")
    except FactoryValidationError as exc:
        issues = [
            ValidationIssue(issue.field.removeprefix("label.") or "label", issue.reason)
            for issue in exc.issues
        ]
        raise FactoryValidationError(issues) from exc


def _directions(values: list[str]) -> list[ChaseDirection]:
    """Parse chase directions; an unknown one is refused with the field path of its entry."""
    choices = ", ".join(d.value for d in ChaseDirection)
    issues: list[ValidationIssue] = []
    parsed: list[ChaseDirection] = []
    for index, value in enumerate(values):
        try:
            parsed.append(ChaseDirection(value))
        except ValueError:
            issues.append(ValidationIssue(f"directions[{index}]", f"must be one of: {choices}"))
    if issues:
        raise FactoryValidationError(issues)
    return parsed


def _direction(value: str) -> Literal["back", "forward"]:
    if value == "back":
        return "back"
    if value == "forward":
        return "forward"
    raise FactoryValidationError([ValidationIssue("direction", "must be one of: back, forward")])


def _rigor_mode(value: str | None) -> RigorMode | None:
    if value is None:
        return None
    try:
        return RigorMode(value)
    except ValueError:
        choices = ", ".join(mode.value for mode in RigorMode)
        raise FactoryValidationError(
            [ValidationIssue("promote_to", f"must be one of: {choices}")]
        ) from None


def _pass_label(value: str) -> PassLabel:
    try:
        return PassLabel(value)
    except ValueError:
        raise FactoryValidationError([ValidationIssue("pass_label", "must be A or B")]) from None


def _parse_items(
    items: list[dict[str, JsonValue]],
) -> tuple[list[tuple[int, ScreeningItem]], list[ItemError]]:
    """Each item that is a valid ScreeningItem, with its index, and each rejection by index."""
    accepted: list[tuple[int, ScreeningItem]] = []
    rejected: list[ItemError] = []
    for index, item in enumerate(items):
        try:
            accepted.append((index, parse_input(ScreeningItem, item, f"items.{index}")))
        except FactoryValidationError as exc:
            rejected.append(ItemError(index=index, issues=exc.issues))
    return accepted, rejected


def _items_path(field: str, original: int) -> str:
    """A service's `items.<n>...` path, renumbered to the item's position in the call."""
    return re.sub(r"^items\.\d+", f"items.{original}", field)


def _evidence_fields(
    project: Project, work_id: str, stage: ScreeningStage, *, with_decisions: bool = True
) -> dict[str, JsonValue]:
    """A full-text item's document, pinned conversion and, unless `with_decisions` is false, the
    passes' cited anchors and quotes; nothing at title/abstract. Calibration passes false: the
    answer key is labelled blind to the passes' verdicts."""
    if stage is not ScreeningStage.FULL_TEXT:
        return {}
    found = evidence_service.work_evidence(
        project, work_id, stage, include_decisions=with_decisions
    )
    decisions: JsonValue = {
        label: view.model_dump(mode="json") for label, view in found.decisions.items()
    }
    fields: dict[str, JsonValue] = {
        "document_id": found.document_id,
        "conversion_id": found.conversion_id,
    }
    if with_decisions:
        fields["decisions"] = decisions
    return fields


def _next_calibration(project: Project, stage: ScreeningStage) -> JsonValue:
    """The first calibration work without a human label, with the counts. Counts only otherwise."""
    items = calibration_service.calibration_items(project, stage=stage)
    labels = calibration_service.calibration_labels(project, stage=stage)
    corpus = {work.id: work for work in list_works(project)}
    pending = [item for item in items if item not in labels]
    record: JsonValue = None
    if pending:
        work = corpus[pending[0]]
        record = {
            "work_id": work.id,
            "title": work.title,
            "abstract": work.abstract,
            **_evidence_fields(project, work.id, stage, with_decisions=False),
        }
    return {"record": record, "drawn": len(items), "labelled": len(items) - len(pending)}


def _probe_spec(item: dict[str, JsonValue], index: int) -> QuerySpec:
    parsed = parse_input(_ProbeQuery, item, f"queries.{index}")
    return QuerySpec(
        source=parsed.source, kind=parsed.kind, text=parsed.query, filters=parsed.filters
    )


def _effects(declared: Mapping[str, str]) -> dict[str, CriterionEffect]:
    """Each criterion's declared effect, or every unknown one reported by its field path."""
    effects: dict[str, CriterionEffect] = {}
    issues: list[ValidationIssue] = []
    choices = ", ".join(effect.value for effect in CriterionEffect)
    for cid, value in declared.items():
        try:
            effects[cid] = CriterionEffect(value)
        except ValueError:
            issues.append(ValidationIssue(f"effects.{cid}", f"must be one of: {choices}"))
    if issues:
        raise FactoryValidationError(issues)
    return effects


def _spec(
    source: str,
    query: str,
    kind: str,
    purpose: str,
    limit: int | None,
    filters: dict[str, str] | None = None,
) -> QuerySpec:
    """A QuerySpec from tool arguments; every bad field is reported by name."""
    issues: list[ValidationIssue] = []
    try:
        kind_value = QueryKind(kind)
    except ValueError:
        issues.append(ValidationIssue("kind", f"must be one of: {_choices(QueryKind)}"))
    # Chases and seeds come from their own tools; this tool only runs searches.
    if purpose != QueryPurpose.SEARCH.value:
        issues.append(ValidationIssue("purpose", f"must be {QueryPurpose.SEARCH.value}"))
    if issues:
        raise FactoryValidationError(issues)
    try:
        return QuerySpec(
            source=source,
            kind=kind_value,
            text=query,
            purpose=QueryPurpose.SEARCH,
            limit=limit,
            filters=filters or {},
        )
    except ValidationError as exc:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    _FIELD_NAMES.get(str(err["loc"][0]), str(err["loc"][0])), str(err["msg"])
                )
                for err in exc.errors()
            ]
        ) from exc


def _choices_of(values: type[ReviewState]) -> str:
    return ", ".join(v.value for v in values)


def _choices(
    values: Iterable[QueryKind | QueryPurpose | AssessmentDecision | DecisionLevel],
) -> str:
    return ", ".join(str(value.value) for value in values)


def _link_state(value: str | None) -> LinkState | None:
    if value is None:
        return None
    try:
        return LinkState(value)
    except ValueError:
        choices = ", ".join(s.value for s in LinkState)
        raise FactoryValidationError(
            [ValidationIssue("state", f"must be one of: {choices}")]
        ) from None


def _decision(value: str) -> Decision:
    try:
        return Decision(value)
    except ValueError:
        choices = ", ".join(d.value for d in Decision)
        raise FactoryValidationError(
            [ValidationIssue("decision", f"must be one of: {choices}")]
        ) from None


def _round_direction(value: str) -> Direction:
    try:
        return Direction(value)
    except ValueError:
        raise FactoryValidationError(
            [ValidationIssue("direction", "must be one of: backward, forward")]
        ) from None


def run(settings: Settings) -> None:
    build_server(settings).run("stdio")

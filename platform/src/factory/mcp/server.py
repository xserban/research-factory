"""The MCP server: one session per process. Tools parse input, call a service and format output."""

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Annotated, Literal, TypeVar

from mcp.server.mcpserver import MCPServer
from pydantic import Field, JsonValue, StringConstraints, ValidationError

from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.events.envelope import Actor
from factory.mcp.conventions import (
    PAGE_LIMIT,
    dotted,
    guarded,
    make_agent_actor,
    paginate,
    parse_input,
    parse_routes,
    parse_stage,
    spec_path,
    withhold,
)
from factory.model.base import StrictModel
from factory.model.chase import ChaseDirection
from factory.model.extraction import ClaimInput, ExtractedRowInput
from factory.model.fulltext import Route
from factory.model.identity import IdGenerator
from factory.model.inbox import Basis
from factory.model.project import RigorMode
from factory.model.protocol import CriterionEffect, PressFinding, ProtocolSpec, ScreeningStage
from factory.model.question import QuestionSpec
from factory.model.references import Decision, Direction, LinkState
from factory.model.screening import CalibrationLabelled, Channel, PassLabel, ScreeningItem
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.model.seed import SeedSpec
from factory.services import agreement as agreement_service
from factory.services import audit as audit_service
from factory.services import calibration as calibration_service
from factory.services import chase as chase_service
from factory.services import check as check_service
from factory.services import coverage as coverage_service
from factory.services import dedup as dedup_service
from factory.services import discovery as discovery_service
from factory.services import document_read as document_read_service
from factory.services import evidence as evidence_service
from factory.services import evidence_report as evidence_report_service
from factory.services import exports as exports_service
from factory.services import extraction as extraction_service
from factory.services import extraction_agreement as extraction_agreement_service
from factory.services import extraction_audit as extraction_audit_service
from factory.services import fulltext as fulltext_service
from factory.services import fulltext_status as fulltext_status_service
from factory.services import inbox as inbox_service
from factory.services import methods as methods_service
from factory.services import prisma as prisma_service
from factory.services import prisma_update as prisma_update_service
from factory.services import probe as probe_service
from factory.services import project as project_service
from factory.services import protocol as protocol_service
from factory.services import question as question_service
from factory.services import reference_resolve as reference_resolve_service
from factory.services import references as references_service
from factory.services import screening as screening_service
from factory.services import search as search_service
from factory.services import seeds as seeds_service
from factory.services import snowball as snowball_service
from factory.services import trace as trace_service
from factory.services import watch as watch_service
from factory.services.context import Project, open_project
from factory.services.extraction import ExtractResult
from factory.services.living_hooks import DEFAULT_HOOKS
from factory.services.results import BatchResult, ItemError
from factory.services.search import list_works
from factory.services.seeds import SeedOutcome, SeedRole
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
) -> MCPServer:
    """The factory's MCP server for one session.

    `fulltext_routes`, when given, is called once per `fulltext_fetch` call to build that call's
    routes; tests use it to supply stubs. By default each call builds `default_routes(settings)`,
    so no arXiv version answer outlives the call that asked for it.
    """
    session = IdGenerator(clock).ulid()
    adapters = dict(default_sources() if sources is None else sources)
    server = MCPServer("factory")

    def _fetch_routes() -> Mapping[Route, FullTextRoute]:
        return default_routes(settings) if fulltext_routes is None else fulltext_routes()

    def _reply(
        project_slug: str,
        fn: Callable[[], JsonValue],
        rename: Callable[[str], str] = str,
        *,
        include_work_ids: bool = True,
    ) -> dict[str, JsonValue]:
        """`guarded`, with every agent-facing response scrubbed of held-out identifiers (R-20).

        A success is scrubbed by its tool (`_withheld`), and a refusal here, as defence in depth:
        the services never name a held-out seed. Screening tools pass `include_work_ids=False`,
        since a screener records its verdicts against a held-out work's own id."""
        result = guarded(fn, rename)
        if result["ok"] is True:
            return result
        try:
            opened = open_project(settings, project_slug, session=session, clock=clock)
        except ProjectNotFoundError:
            return result
        scrubbed = withhold(result, _held_out_tokens(opened, include_work_ids))
        return scrubbed if isinstance(scrubbed, dict) else result

    @server.tool()
    def project_status(project: str) -> dict[str, JsonValue]:
        """Report a project's rigor mode, event counts and task queue state."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            report = project_service.project_status(opened).model_dump(mode="json")
            return _withheld(opened, _without_rates(report))

        return _reply(project, status)

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
    ) -> dict[str, JsonValue]:
        """Run a literature query against OpenAlex or arXiv exhaustively; every raw page is archived and counts are recorded.

        Set `resume_run` to a partial or failed run of the same query to continue it from where
        it stopped; `source`, `query` and `kind` must then restate that run's query. In a pilot
        or systematic project a query the protocol does not plan needs a `deviation_id` recorded
        against the current protocol.
        """  # noqa: E501

        def search() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            spec = _spec(source, query, kind, purpose, limit)
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
        them) or both. Refused while any work is pending a final outcome, and when no included
        work has an OpenAlex id. Never write chase queries by hand; follow with `dedup_run`."""

        def chase() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = _directions(directions)
            summary = chase_service.search_chase(opened, actor, parsed, sources=adapters)
            return _withheld(opened, summary.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, chase, include_work_ids=False)

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
                after_runs=DEFAULT_HOOKS,
            )
            if summary is None:
                return {"cycle": None}
            report = summary.model_dump(mode="json", exclude={"new_work_ids"})
            report["new_works"] = len(summary.new_work_ids)
            return _withheld(opened, {"cycle": report})

        return _reply(project, run_cycle)

    @server.tool()
    def question_record(
        project: str,
        spec: dict[str, JsonValue],
        role: str,
        model: str,
        skill: str,
        raw_goal: str | None = None,
        reason: str | None = None,
    ) -> dict[str, JsonValue]:
        """Record the question. `raw_goal`, when given, is stored verbatim first. A new version
        needs a `reason`; an unchanged spec writes nothing."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = parse_input(QuestionSpec, spec, "spec")
            result = question_service.record_question(
                opened, actor, parsed, reason=reason, raw_goal=raw_goal
            )
            return {
                "question_id": result.question_id,
                "created": result.created,
                "goal_event_id": result.goal_event_id,
            }

        return _reply(project, record, rename=spec_path)

    @server.tool()
    def seed_add(
        project: str, seeds: list[dict[str, JsonValue]], role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Add seeds by identifier (doi, arxiv or openalex) and look each one up. Each seed is
        written or rejected on its own; rejections name the item by index and field."""

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
                opened, actor, [spec for _, spec in accepted], sources=adapters
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
        project: str, queries: list[dict[str, JsonValue]], role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Measure queries against the development seeds and the negatives: recall and negative
        hits per query and per source. Each query is {source, query, kind="keyword", filters={}}.
        The first probe of a pilot or systematic project draws the hold-out split."""

        def probe() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            specs = [_probe_spec(item, index) for index, item in enumerate(queries)]
            report = probe_service.run_probe(opened, actor, specs, sources=adapters)
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
    ) -> dict[str, JsonValue]:
        """Record the protocol as a draft, or as ready when `ready` is true. Gaps are returned
        whether or not the protocol was written. A ready protocol changes only by protocol_amend."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = parse_input(ProtocolSpec, spec, "spec")
            result = protocol_service.record_protocol(opened, actor, parsed, ready=ready)
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
    ) -> dict[str, JsonValue]:
        """Amend the ready protocol. `effects` names each changed criterion as loosened,
        tightened or clarified; `semantic` is false only for prose and clarifications."""

        def amend() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            parsed = parse_input(ProtocolSpec, spec, "spec")
            declared = _effects(effects)
            result = protocol_service.amend_protocol(
                opened, actor, parsed, reason=reason, semantic=semantic, effects=declared
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
            result = screening_service.screen_next(
                opened, actor, _pass_label(pass_label), stage=run_stage
            )
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, screen, include_work_ids=False)

    @server.tool()
    def screen_record(
        project: str,
        task_id: str,
        items: list[dict[str, JsonValue]],
        role: str,
        model: str,
        skill: str,
    ) -> dict[str, JsonValue]:
        """Record verdicts for a held batch. Each item is {work_id, verdict, criterion, quote,
        rationale}, plus `anchor` for a full-text batch (the stage is the batch's); an invalid item
        is reported by index and the valid ones are written."""

        def record() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            accepted, rejected = _parse_items(items)
            result = screening_service.screen_record(
                opened, actor, task_id, [item for _, item in accepted]
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
            result = agreement_service.screen_agreement(opened, actor, stage=run_stage)
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
            event_id = calibration_service.label_calibration(
                opened, human, work_id, verdict, criterion, Channel.MCP, stage=run_stage
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
            event_id = audit_service.audit_record(
                opened, opened.human_actor(), audit_id, work_id, verdict, criterion, Channel.MCP
            )
            return {"event_id": event_id}

        return _reply(project, record, include_work_ids=False)

    @server.tool()
    def protocol_deviation(
        project: str,
        description: str,
        reason: str,
        role: str,
        model: str,
        skill: str,
        affects: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """Record a deviation from the current protocol. A search the protocol does not plan
        needs the returned `deviation_id`."""

        def deviate() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            deviation_id = protocol_service.record_deviation(
                opened, actor, description=description, reason=reason, affects=affects or ()
            )
            return {"deviation_id": deviation_id}

        return _reply(project, deviate)

    @server.tool()
    def report_prisma(project: str, update: str | None = None) -> dict[str, JsonValue]:
        """The PRISMA 2020 flow and the PRISMA-S search report, computed from the events.
        `update` adds the update flow of a living review: `last` (since the last snapshot) or a
        snapshot id (the update that snapshot closed). Refused to a session that has joined a
        pass: the flow's included, pending and per-criterion exclusion counts derive from the final
        outcomes (human labels and both passes)."""

        def report() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            data: dict[str, JsonValue] = {
                "flow": prisma_service.prisma_flow(opened).model_dump(mode="json"),
                "search": prisma_service.search_report(opened).model_dump(mode="json"),
            }
            if update is not None:
                until = None if update == "last" else update
                flow = prisma_update_service.prisma_update(opened, until=until)
                shown = prisma_update_service.agent_update(opened, flow)
                data["update"] = shown.model_dump(mode="json")
            return _withheld(opened, data, include_work_ids=update is not None)

        return _reply(project, report, include_work_ids=update is not None)

    @server.tool()
    def report_methods(project: str) -> dict[str, JsonValue]:
        """The methods statement: its figures and the rendered text. Refused to any session that
        has joined a pass, since it reports agreement, calibration and audit figures. Kappa is
        reported only once every dual-coded work is decided in both passes, so a session outside
        the passes never reads a partial figure."""

        def methods() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            full = methods_service.methods_report(opened)
            report, withheld = methods_service.agent_methods(opened, full)
            data: dict[str, JsonValue] = {
                "report": report.model_dump(mode="json"),
                "text": methods_service.render_methods(report, withheld=withheld),
            }
            return _withheld(opened, data, include_work_ids=False)

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
        verbatim, with an optional note and no basis. Offline; each item is written or rejected
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
                        (index, inbox_service.LinkInput(parsed.link, parsed.note, parsed.basis))
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
            return _withheld(opened, batch.model_dump(mode="json"))

        return _reply(project, add)

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
            return _withheld(opened, {"items": data})

        return _reply(project, run)

    @server.tool()
    def inbox_list(
        project: str, status: str | None = None, cursor: str | None = None, limit: int = PAGE_LIMIT
    ) -> dict[str, JsonValue]:
        """Inbox items in id order with status and last resolution outcome, one page at a time
        (`status`: open, resolved or withdrawn). Refused to a session that has joined a pass."""

        def listing() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            page = inbox_service.list_items(opened, status=status, cursor=cursor, limit=limit)
            return _withheld(opened, page.model_dump(mode="json"))

        return _reply(project, listing)

    @server.tool()
    def report_discovery(project: str) -> dict[str, JsonValue]:
        """How the corpus was found: counts by first-surfaced route and by first surfacer's
        actor kind at each level (identified, title/abstract included, full-text included, in
        evidence), and route overlaps. Seed admission is reported as `other`. Refused to a
        session that has joined a pass."""

        def report() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            view = discovery_service.agent_view(discovery_service.discovery_report(opened))
            return _withheld(opened, view, include_work_ids=False)

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
            report = evidence_report_service.agent_evidence(
                evidence_report_service.evidence_report(opened, expect=_expectations(expect or []))
            )
            return _withheld(opened, report.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, evidence, include_work_ids=False)

    @server.tool()
    def export_bibliography(
        project: str,
        format: str = "bibtex",
        scope: str = "included",
        ids: list[str] | None = None,
    ) -> dict[str, JsonValue]:
        """The bibliography of a scope of works as BibTeX or CSL-JSON text (`format` bibtex or
        csl; `scope` included or corpus, or explicit work `ids`, which replace the scope). At
        most MCP_EXPORT_MAX_WORKS works; use the CLI for more. Built from events only; refused to
        any session that has joined a screening or extraction pass. Read-only."""

        def export() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            chosen = exports_service.select_works(
                opened,
                None if ids else scope,
                ids or (),
                exclude_work_ids=exports_service.held_out_work_ids(opened),
            )
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
            return _withheld(opened, data)

        return _reply(project, export)

    @server.tool()
    def trace(project: str, ref: str, direction: str = "back") -> dict[str, JsonValue]:
        """The chain from any identifier: `back` to what it was derived from, `forward` to what
        was derived from it. Held-out seed ids are refused as unknown; seed nodes, and the seed
        and probe lookups that found a work, are not shown. Refused to a session that has joined
        a pass, since the chain leads to the other pass's decisions, resolutions and audit."""

        def walk() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            way = _direction(direction)
            withheld = {t.lower() for t in _held_out_tokens(opened, include_work_ids=False)}
            if ref.strip().lower() in withheld:
                raise FactoryValidationError([ValidationIssue("ref", "unknown id")])
            tree = trace_service.agent_trace(opened, ref, direction=way)
            return _withheld(opened, tree.model_dump(mode="json"), include_work_ids=False)

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
            mode = _rigor_mode(promote_to)
            report = check_service.agent_check(opened, promote_to=mode)
            data: dict[str, JsonValue] = {
                **report.model_dump(mode="json"),
                "ok": report.ok,
            }
            return _withheld(opened, data, include_work_ids=False)

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
        oa-pdf) and each work stops at its first retrieved attempt. `routes` names routes to try
        instead, all of them, without stopping. `work_ids` defaults to the promoted works that have
        no document and no attempt yet, so a work whose routes all failed is retried only by
        `refresh` (every promoted work), `routes`, or by naming it in `work_ids`. `limit` caps the
        works processed; more `work_ids` than `limit` are refused. Returns each work's attempts and
        documents, and `remaining`, the promoted works still without a document. A researcher's
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
            return _withheld(opened, summary.model_dump(mode="json"))

        return _reply(project, fetch)

    @server.tool()
    def fulltext_status(project: str, work_ids: list[str] | None = None) -> dict[str, JsonValue]:
        """The full-text state of each promoted work, or of the named ones: retrieved, not
        retrieved (with the latest reason from each route) or unsought, and the live documents
        per route. Read-only. Refused to a session that has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            report = fulltext_status_service.fulltext_status(opened, work_ids=work_ids)
            return _withheld(opened, report.model_dump(mode="json"))

        return _reply(project, status)

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
    ) -> dict[str, JsonValue]:
        """One page of a promoted work's converted document: its segments in document order, each
        with its anchor, kind and text (cut and flagged when long), and `next_after` for the next
        page. `anchor` reads one anchor, cells included. Agents read documents only through this
        tool. Conversion is the researcher's act (`factory document convert`); there is no MCP
        convert tool. Only works promoted at title/abstract are read. Read-only. Refused to a
        title/abstract pass session; a full-text screener reads only the works of its own batches,
        at the conversion each pins."""

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
            )
            return _withheld(opened, page.model_dump(mode="json"))

        return _reply(project, read)

    @server.tool()
    def extract_next(
        project: str, pass_label: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Serve the next extraction task of pass A or B to this session, or say why none is
        served. The batch names the declared fields, the work and the pinned conversion to read
        with `document_read`; `blocked` says why ordinary work waits. Joins this session to the
        pass on its first call."""

        def serve() -> JsonValue:
            label = _pass_label(pass_label)
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            served = extraction_service.extract_next(opened, actor, label)
            return _withheld(opened, served.model_dump(mode="json"), include_work_ids=False)

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
    ) -> dict[str, JsonValue]:
        """Record the rows (and, in pass A, claims) extracted from a held task. A row is
        {fields: {name: {value, unit, anchor, cell, quote, reported_in, cited_work}}}. An invalid
        item is reported by index and the valid ones are written. `supersedes` maps the index of
        a row of this call (a string key) to the id of the row it corrects; `claim_supersedes`
        likewise for claims. `finish` closes the work once no item is rejected; a work with no
        results needs a `reason`."""

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
            event_id = extraction_audit_service.extraction_audit_record(
                opened,
                opened.human_actor(),
                audit_id,
                work_id,
                row_key,
                field,
                correct,
                note,
                Channel.MCP,
            )
            return {"event_id": event_id}

        return _reply(project, label, include_work_ids=False)

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
            )

        return _reply(project, status)

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
            return _withheld(opened, report.model_dump(mode="json"))

        return _reply(project, coverage)

    @server.tool()
    def references_extract(
        project: str, role: str, model: str, skill: str, work_ids: list[str] | None = None
    ) -> dict[str, JsonValue]:
        """Extract and resolve the reference lists of included works from their converted
        documents. With no `work_ids`: every included work with a conversion and no current
        extraction. A malformed id refuses the call; works that cannot be extracted (not
        included, no conversion) are reported under `skipped` while the others are recorded.
        Refused to a session that has joined a pass."""

        def extract() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            actor = make_agent_actor(settings, session, role, model, skill)
            summary = references_service.extract_references(
                opened, actor, work_ids, sources=adapters
            )
            summary = references_service.agent_extract_view(summary, seeds_service.held_out(opened))
            return _withheld(opened, summary.model_dump(mode="json"))

        return _reply(project, extract)

    @server.tool()
    def references_status(project: str) -> dict[str, JsonValue]:
        """Counts over the live reference extractions: entries by link state (they sum to
        `entries`), works in the corpus and new candidates. Read-only. Refused to a session that
        has joined a pass."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            counts = references_service.reference_counts(opened, seeds_service.held_out(opened))
            return _withheld(opened, counts.model_dump(mode="json"))

        return _reply(project, status)

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
                held_out=seeds_service.held_out(opened),
            )
            return _withheld(opened, page.model_dump(mode="json"))

        return _reply(project, listing)

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
        another session). `quotes` is exactly two strings: a verbatim part of the entry, and a
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

        return _reply(project, decide)

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
            result = snowball_service.agent_round_view(
                opened, result, seeds_service.held_out(opened)
            )
            return _withheld(opened, result.model_dump(mode="json"))

        return _reply(project, round_)

    @server.tool()
    def snowball_compare(project: str, round_id: str) -> dict[str, JsonValue]:
        """For a recorded backward round: the works its resolved references name against the
        works the `cited_by:` chase rounds found. A quality check, not a selection. Read-only.
        Refused to a session that has joined a pass."""

        def compare() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            _refuse_pass_session(opened)
            result = snowball_service.snowball_compare(
                opened, round_id, seeds_service.held_out(opened)
            )
            return _withheld(opened, result.model_dump(mode="json"))

        return _reply(project, compare)

    return server


def _refuse_pass_session(project: Project) -> None:
    """A session that screens or extracts must not read the other pass's results, the report
    surfaces or the answer key (R-20)."""
    if calibration_service.is_pass_session(
        project, project.session
    ) or extraction_service.is_extraction_session(project, project.session):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session has joined a pass and cannot use this tool")]
        )


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


def _without_rates(report: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """The project status for an agent: screening counts and flags only. Label-derived rates
    (sensitivity, specificity, false-exclusion) stay in the CLI status and the human's reports."""
    screening = report.get("screening")
    if isinstance(screening, dict):
        screening.pop("false_exclusion_rate", None)
        calibration = screening.get("calibration")
        if isinstance(calibration, dict):
            calibration.pop("per_pass", None)
    return report


def _withheld(project: Project, value: JsonValue, include_work_ids: bool = True) -> JsonValue:
    """Strip every held-out seed's identifiers from an agent-facing response (R-20)."""
    return withhold(value, _held_out_tokens(project, include_work_ids))


def _held_out_tokens(project: Project, include_work_ids: bool = True) -> set[str]:
    """The id, and every identifier as stated or normalised, of each held-out seed.

    `include_work_ids` adds the held-out seed's work id. Screening tools leave it out: a screener
    must see and record against a held-out work, whose id is not a seed's identity."""
    tokens: set[str] = set()
    for seed in seeds_service.all_seeds(project):
        if seed.role is not SeedRole.HELD_OUT:
            continue
        stated = SeedSpec(
            kind=seed.kind,
            cite=seed.cite,
            doi=seed.doi,
            arxiv=seed.arxiv,
            openalex=seed.openalex,
        )
        tokens.add(seed.seed_id)
        tokens.update(stated.identity_keys().values())
        tokens.update(value for value in (seed.doi, seed.arxiv, seed.openalex) if value)
        if include_work_ids and seed.work_id:
            tokens.add(seed.work_id)
    if include_work_ids:
        tokens.update(seeds_service.held_out_work_ids(project))
    return tokens


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


def _spec(source: str, query: str, kind: str, purpose: str, limit: int | None) -> QuerySpec:
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


def _choices(values: Iterable[QueryKind | QueryPurpose]) -> str:
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

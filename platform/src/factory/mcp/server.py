"""The MCP server: one session per process. Tools parse input, call a service and format output."""

import re
from collections.abc import Callable, Iterable, Mapping
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field, JsonValue, StringConstraints, ValidationError

from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.mcp.conventions import (
    PAGE_LIMIT,
    dotted,
    guarded,
    make_agent_actor,
    paginate,
    parse_input,
    spec_path,
    withhold,
)
from factory.model.base import StrictModel
from factory.model.identity import IdGenerator
from factory.model.protocol import CriterionEffect, PressFinding, ProtocolSpec
from factory.model.question import QuestionSpec
from factory.model.screening import CalibrationLabelled, Channel, PassLabel, ScreeningItem
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.model.seed import SeedSpec
from factory.services import agreement as agreement_service
from factory.services import audit as audit_service
from factory.services import calibration as calibration_service
from factory.services import dedup as dedup_service
from factory.services import probe as probe_service
from factory.services import project as project_service
from factory.services import protocol as protocol_service
from factory.services import question as question_service
from factory.services import screening as screening_service
from factory.services import search as search_service
from factory.services import seeds as seeds_service
from factory.services.context import Project, open_project
from factory.services.results import BatchResult, ItemError
from factory.services.search import list_works
from factory.services.seeds import SeedOutcome, SeedRole
from factory.sources.registry import SourceFactory, default_sources

_SYSTEM_CLOCK = SystemClock()
_FIELD_NAMES = {"text": "query"}  # QuerySpec calls the query text `text`; the tool calls it `query`


class _ProbeQuery(StrictModel):
    """One probe request as an agent states it: `query` is the text, `kind` defaults to keyword."""

    source: str
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    kind: QueryKind = QueryKind.KEYWORD
    filters: dict[str, str] = Field(default_factory=dict)


def build_server(
    settings: Settings,
    clock: Clock = _SYSTEM_CLOCK,
    sources: Mapping[str, SourceFactory] | None = None,
) -> MCPServer:
    session = IdGenerator(clock).ulid()
    adapters = dict(default_sources() if sources is None else sources)
    server = MCPServer("factory")

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
            return _withheld(opened, report)

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
    def dedup_run(project: str, role: str, model: str, skill: str) -> dict[str, JsonValue]:
        """Find and record duplicate works; merges are reversible."""

        def dedup() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            make_agent_actor(settings, session, role, model, skill)
            report = dedup_service.dedup_run(opened).model_dump(mode="json")
            return _withheld(opened, report)

        return _reply(project, dedup)

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
        project: str, pass_label: str, role: str, model: str, skill: str
    ) -> dict[str, JsonValue]:
        """Serve the next screening batch of pass A or B to this session, or say why none is
        served. The records are the text to screen; `blocked` says why ordinary work waits."""

        def screen() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            result = screening_service.screen_next(opened, actor, _pass_label(pass_label))
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
        rationale}; an invalid item is reported by index and the valid ones are written."""

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
    ) -> dict[str, JsonValue]:
        """The agreement of the two passes: κ, per-criterion κ, disagreements and cannot-assess
        rates. Read-only. The actor is an agent when role, model or skill is given, else human."""

        def agreement() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            if role is None and model is None and skill is None:
                actor = opened.human_actor()
            else:
                actor = make_agent_actor(settings, session, role or "", model or "", skill or "")
            result = agreement_service.screen_agreement(opened, actor)
            return _withheld(opened, result.model_dump(mode="json"), include_work_ids=False)

        return _reply(project, agreement, include_work_ids=False)

    @server.tool()
    def calibration_label(
        project: str,
        work_id: str | None = None,
        verdict: str | None = None,
        criterion: str | None = None,
    ) -> dict[str, JsonValue]:
        """With no `work_id`: the next unlabelled calibration record and the counts. With one: the
        human's label on it. The first call draws the calibration set. Labels are human acts."""

        def label() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            human = opened.human_actor()
            if work_id is None:
                if verdict is not None or criterion is not None:
                    raise FactoryValidationError(
                        [ValidationIssue("work_id", "is required to record a label")]
                    )
                calibration_service.draw_calibration(opened, human)
                return _withheld(opened, _next_calibration(opened), include_work_ids=False)
            if verdict is None:
                raise FactoryValidationError(
                    [ValidationIssue("verdict", "is required with a work_id")]
                )
            # Only the no-argument call draws the set. A labelled call is refused, and writes
            # nothing, while the set is undrawn; its own fields are checked first.
            _check_label(work_id, verdict, criterion)
            if not calibration_service.calibration_drawn(opened):
                raise FactoryValidationError(
                    [
                        ValidationIssue(
                            "work_id", "calibration set not drawn; call without arguments first"
                        )
                    ]
                )
            event_id = calibration_service.label_calibration(
                opened, human, work_id, verdict, criterion, Channel.MCP
            )
            return {"event_id": event_id}

        return _reply(project, label, include_work_ids=False)

    @server.tool()
    def audit_sample(project: str) -> dict[str, JsonValue]:
        """Draw the audit sample of the agreed works, for the human to label: each work's id,
        title and agreed verdict, with the population and the counts."""

        def sample() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            drawn = audit_service.audit_sample(opened, opened.human_actor())
            titles = {work.id: work.title for work in list_works(opened)}
            agreed = agreement_service.agreed_works(opened)
            data: dict[str, JsonValue] = {
                "audit_id": drawn.audit_id,
                "items": [
                    {
                        "work_id": work_id,
                        "title": titles[work_id],
                        "agreed_verdict": agreed[work_id].verdict,
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
        """The human's label on one sampled work. `criterion` names an EX criterion for an
        exclusion, and is qualified against the current protocol."""

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

    return server


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


def _next_calibration(project: Project) -> JsonValue:
    """The first calibration work without a human label, with the counts. Counts only otherwise."""
    items = calibration_service.calibration_items(project)
    labels = calibration_service.calibration_labels(project)
    corpus = {work.id: work for work in list_works(project)}
    pending = [item for item in items if item not in labels]
    record: JsonValue = None
    if pending:
        work = corpus[pending[0]]
        record = {"work_id": work.id, "title": work.title, "abstract": work.abstract}
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


def run(settings: Settings) -> None:
    build_server(settings).run("stdio")

"""The MCP server: one session per process. Tools parse input, call a service and format output."""

from collections.abc import Iterable, Mapping

from mcp.server.mcpserver import MCPServer
from pydantic import JsonValue, ValidationError

from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.errors import FactoryValidationError, ValidationIssue
from factory.mcp.conventions import guarded, make_agent_actor
from factory.model.identity import IdGenerator
from factory.model.search import QueryKind, QueryPurpose, QuerySpec
from factory.services import dedup as dedup_service
from factory.services import project as project_service
from factory.services import search as search_service
from factory.services.context import open_project
from factory.sources.registry import SourceFactory, default_sources

_SYSTEM_CLOCK = SystemClock()
_FIELD_NAMES = {"text": "query"}  # QuerySpec calls the query text `text`; the tool calls it `query`


def build_server(
    settings: Settings,
    clock: Clock = _SYSTEM_CLOCK,
    sources: Mapping[str, SourceFactory] | None = None,
) -> MCPServer:
    session = IdGenerator(clock).ulid()
    adapters = dict(default_sources() if sources is None else sources)
    server = MCPServer("factory")

    @server.tool()
    def project_status(project: str) -> dict[str, JsonValue]:
        """Report a project's rigor mode, event counts and task queue state."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            return project_service.project_status(opened).model_dump(mode="json")

        return guarded(status)

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
    ) -> dict[str, JsonValue]:
        """Run a literature query against OpenAlex or arXiv exhaustively; every raw page is archived and counts are recorded.

        Set `resume_run` to a partial or failed run of the same query to continue it from where
        it stopped; `source`, `query` and `kind` must then restate that run's query.
        """  # noqa: E501

        def search() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            actor = make_agent_actor(settings, session, role, model, skill)
            spec = _spec(source, query, kind, purpose, limit)
            if resume_run is not None:
                query_id = search_service.resume_query_id(opened, resume_run, spec)
            else:
                query_id = search_service.register_query(opened, actor, spec, sources=adapters)
            summary = search_service.run_query(
                opened, query_id, sources=adapters, resume_run=resume_run, actor=actor
            )
            return summary.model_dump(mode="json")

        return guarded(search)

    @server.tool()
    def dedup_run(project: str, role: str, model: str, skill: str) -> dict[str, JsonValue]:
        """Find and record duplicate works; merges are reversible."""

        def dedup() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            make_agent_actor(settings, session, role, model, skill)
            return dedup_service.dedup_run(opened).model_dump(mode="json")

        return guarded(dedup)

    return server


def _spec(source: str, query: str, kind: str, purpose: str, limit: int | None) -> QuerySpec:
    """A QuerySpec from tool arguments; every bad field is reported by name."""
    issues: list[ValidationIssue] = []
    try:
        kind_value = QueryKind(kind)
    except ValueError:
        issues.append(ValidationIssue("kind", f"must be one of: {_choices(QueryKind)}"))
    try:
        purpose_value = QueryPurpose(purpose)
    except ValueError:
        issues.append(ValidationIssue("purpose", f"must be one of: {_choices(QueryPurpose)}"))
    if issues:
        raise FactoryValidationError(issues)
    try:
        return QuerySpec(
            source=source,
            kind=kind_value,
            text=query,
            purpose=purpose_value,
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

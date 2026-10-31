"""The MCP server: one session per process. Tools parse input, call a service and format output."""

from mcp.server.mcpserver import MCPServer
from pydantic import JsonValue

from factory.clock import Clock, SystemClock
from factory.config import Settings
from factory.mcp.conventions import guarded
from factory.model.identity import IdGenerator
from factory.services import project as project_service
from factory.services.context import open_project

_SYSTEM_CLOCK = SystemClock()


def build_server(settings: Settings, clock: Clock = _SYSTEM_CLOCK) -> MCPServer:
    session = IdGenerator(clock).ulid()
    server = MCPServer("factory")

    @server.tool()
    def project_status(project: str) -> dict[str, JsonValue]:
        """Report a project's rigor mode, event counts and task queue state."""

        def status() -> JsonValue:
            opened = open_project(settings, project, session=session, clock=clock)
            return project_service.project_status(opened).model_dump(mode="json")

        return guarded(status)

    return server


def run(settings: Settings) -> None:
    build_server(settings).run("stdio")

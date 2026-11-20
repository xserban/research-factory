"""The MCP server builder, supplied by an interface instead of imported by the core.

`site_catalog` lists the tools by building the real server, but the core never imports `mcp`.
An interface (`mcp.server` on import, hence every CLI command that needs the catalog) registers
`build_server` here; `build` calls it. Invariant: with nothing registered `build` raises
`RuntimeError`; it never imports an interface itself.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from factory.config import Settings

ServerBuilder = Callable[[Settings], Any]

_builder: ServerBuilder | None = None


def register(builder: ServerBuilder) -> None:
    """Set the function that builds the MCP server (the last registration wins)."""
    global _builder
    _builder = builder


def build(settings: Settings) -> Any:
    if _builder is None:
        raise RuntimeError(
            "no MCP server builder is registered: import factory.mcp.server before listing tools"
        )
    return _builder(settings)

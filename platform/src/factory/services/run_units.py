"""Names shared by the MCP unit cap (`mcp.unit_cap`, the writer) and the cost reader
(`services.run_costs`). Lives below `mcp` so the core never imports an interface.

Invariant: `UNITS_FILE` is the file name inside a run folder; changing it breaks both sides.
"""

from __future__ import annotations

UNITS_FILE = "units.json"

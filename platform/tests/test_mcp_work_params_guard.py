"""Every MCP tool parameter that names a work resolves NFC spellings (IDEA-66).

A parameter whose name contains `work` is listed below as resolving (the service it calls maps
the id with `services.work_ref`) or as exempt, with a reason. A new tool or parameter fails this
test until it is listed, so no input can skip the resolver unnoticed. Only top-level parameters
are visible here; work ids nested in a structured parameter are resolved by their services
(`label_apply`, `extract_record` rows, `screen_record` items, ...).
"""

from __future__ import annotations

import pytest

from factory.config import Settings
from factory.mcp.server import build_server

RESOLVES: dict[str, frozenset[str]] = {
    "calibration_label": frozenset({"work_id"}),
    "audit_record": frozenset({"work_id"}),
    "screen_check_label": frozenset({"work_id"}),
    "screen_check_example": frozenset({"work_id"}),
    "fulltext_fetch": frozenset({"work_ids"}),
    "fulltext_status": frozenset({"work_ids"}),
    "library_adoptable": frozenset({"work_id"}),
    "library_adopt": frozenset({"work_id"}),
    "document_read": frozenset({"work_id"}),
    "extract_audit_record": frozenset({"work_id"}),
    "taxonomy_propose": frozenset({"works"}),
    "mine_resolve": frozenset({"work_id"}),
    "miner_calibration_label": frozenset({"work_id"}),
    "mine_reopen": frozenset({"work_id"}),
    "references_extract": frozenset({"work_ids"}),
    "references_list": frozenset({"work_id"}),
    "reference_decide": frozenset({"work_id"}),
    "relation_propose": frozenset({"source_work"}),
    "relation_list": frozenset({"work_id"}),
    "flow_trail": frozenset({"work_id"}),
    "chat_sections": frozenset({"work_id"}),
    "paper_profiles": frozenset({"work_ids"}),
    "writing_outline": frozenset({"scope_works"}),
    "draft_create": frozenset({"scope_works"}),
    "draft_repin": frozenset({"scope_works"}),
}

EXEMPT: dict[tuple[str, str], str] = {
    ("lead_record", "framework"): "a framework's name, not a work id",
    ("corpus_search", "per_work_limit"): "a hit count per work, not a work id",
}


@pytest.mark.anyio
async def test_every_work_parameter_is_listed(settings: Settings) -> None:
    server = build_server(settings)
    found: dict[str, set[str]] = {}
    for tool in await server.list_tools():
        names = {p for p in tool.input_schema.get("properties", {}) if "work" in p}
        names -= {p for t, p in EXEMPT if t == tool.name}
        if names:
            found[tool.name] = names
    assert found == {tool: set(names) for tool, names in RESOLVES.items()}

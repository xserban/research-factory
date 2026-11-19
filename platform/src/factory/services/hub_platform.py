"""The `platform` hub payload: what the platform can do (tools, skills, commands by lifecycle
stage, with flags) and the backlog board.

Invariants:
- `build` wraps `site_catalog.build_catalog`, `site_catalog_page.stage_summary` and
  `site_backlog.parse_backlog/classify/area_notes`; no count is typed here, every one is computed.
- The catalog and the backlog fail independently: a failure leaves that half `None` with its error
  text in `catalog_error` / `backlog_error`, and the other half is still built.
- An absent check is reported as absent (`skipped`, `prompts: None`), never as zero.
- The backlog file is read from the main checkout (`site_backlog.backlog_path`); it is hub-level,
  not per project. Nothing is written back.
- Reads no network and calls no model.
"""

# ruff: noqa: E501
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from factory.services import site_backlog as sb
from factory.services import site_catalog as sc
from factory.services.site_catalog_page import stage_summary

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

STATES = ("ready", "blocked", "specified", "done", "parked")
"""The computed states of `site_backlog.classify`, in board-column order."""

COMMANDS: tuple[dict[str, str], ...] = (
    {
        "cmd": "factory hub build <slug> --out <dir>",
        "what": "Writes the hub pages and their data files as static files for one project.",
    },
    {
        "cmd": "factory site build <slug>",
        "what": "Writes the classic hub products (the earlier pages) for one project.",
    },
    {
        "cmd": "factory site serve <slug>",
        "what": "Serves the project's pages from this machine, with the live acts.",
    },
)
"""The commands that start or write the hubs. Declared text, not derived; the earlier
`factory dashboard serve` is not repeated because the live dashboard is a hub page."""

METHODS: dict[str, str] = {
    "catalog": (
        "The tool list comes from the built MCP server; the skills from the plugin's SKILL.md files. "
        "Each skill's stage is declared in its front matter. A tool's stage is that of the first skill "
        "that names it. Nothing is judged: every count is computed from those files."
    ),
    "matrix": (
        "One row per lifecycle stage. Tools, skills and flags are counted per stage; a flag belongs to "
        "the stage of the skill whose file it names, else of the tool its text names. The marker and "
        "access columns count the stage's tools by their declared marker and by the permission row "
        "of the access table."
    ),
    "flags": (
        "Mechanical findings from reading the skills against the tool list and the decision log: an "
        "unknown tool or argument, a clash between two skills, a decision cited but missing or not "
        "decided, a tool or skill no stage covers, a marker that disagrees with the access row. The "
        "platform rules on none of them; they are listed for the researcher."
    ),
    "markers": (
        "A tool that no skill names is an orphan unless it is marked. Markers are declared by hand, on "
        "a ruling, in the catalog source; they are never inferred from a name, and each is checked "
        "against the tool's access row."
    ),
    "backlog": (
        "Read from the backlog document in the main checkout, entry by entry. A state is computed, "
        "never typed: done when built; parked when parked or rejected; specified when accepted; "
        "blocked when a dependency is not done; otherwise ready. Unlocks counts the open ideas "
        "that sit below an idea in the dependency graph."
    ),
    "tree": (
        "Layers follow the recorded dependencies: an idea sits one layer right of its deepest "
        "dependency. Only ideas with a recorded idea dependency (or that others depend on) are drawn."
    ),
}


def _tools(cat: sc.Catalog) -> list[dict[str, Any]]:
    return [
        {
            "n": t.name,
            "d": t.description,
            "params": list(t.params),
            "schema": t.input_schema_json,
            "stage": t.stage,
            "also": list(t.also_used_in),
            "skills": list(t.skills),
            "marker": t.marker,
            "access": t.access,
        }
        for t in cat.tools
    ]


def _skills(cat: sc.Catalog) -> list[dict[str, Any]]:
    return [
        {
            "n": s.name,
            "d": s.description,
            "stages": list(s.stages),
            "file": s.file,
            "sha": s.sha,
            "tools": list(s.tools),
            "steps": [
                {"text": st.text, "line": st.line, "file": st.file, "tools": list(st.tools)}
                for st in s.steps
            ],
        }
        for s in cat.skills
    ]


def _matrix(cat: sc.Catalog, stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stage rows from `stage_summary`, with each stage's tools counted by marker and access."""
    out: list[dict[str, Any]] = []
    for row in stages:
        key = None if row["id"] == "unassigned" else row["id"]
        members = [t for t in cat.tools if t.stage == key]
        out.append(
            {
                "id": row["id"],
                "label": row["label"],
                "covers": row["covers"],
                "n_skills": row["n_skills"],
                "n_tools": row["n_tools"],
                "n_flags": row["n_flags"],
                "markers": dict(Counter(t.marker for t in members if t.marker)),
                "access": dict(Counter(t.access or "none" for t in members)),
                "skills": row["skills"],
                "tools": [t.name for t in members],
                "flags": row["flags"],
            }
        )
    return out


def catalog_payload(settings: Any) -> dict[str, Any]:
    """The capabilities half of the payload (see module invariants)."""
    from factory.services.site import code_hash

    cat = sc.build_catalog(settings)
    cc = cat.count_check
    stages = stage_summary(cat)
    marked = [
        {
            "tool": t.name,
            "kind": t.marker,
            "why": sc.MARKER_KINDS.get(t.marker or "", ""),
            "accepted": sc.ACCEPTED_MISMATCH.get(t.name),
            "access": t.access,
            "skills": list(t.skills),
        }
        for kind in sc.MARKER_KINDS
        for t in cat.tools
        if t.marker == kind
    ]
    return {
        "summary": {
            "tools_registered": cc.registered,
            "tools_listed": cc.listed,
            "skills": len(cat.skills),
            "prompts": cat.prompts,
            "examples": cat.examples,
            "marked": sum(1 for t in cat.tools if t.marker),
            "orphan_tools": cat.flag_counts()["orphan-tool"],
            "flags": len(cat.flags),
        },
        "count_check": {
            "ok": cc.ok,
            "missing": list(cc.missing),
            "extra": list(cc.extra),
            "duplicates": list(cc.duplicates),
        },
        "skipped": dict(sorted(cat.skipped.items())),
        "flag_counts": cat.flag_counts(),
        "flags": [
            {"code": f.code, "where": f"{f.file}:{f.line}", "msg": f.message, "other": f.other}
            for f in cat.flags
        ],
        "stages": _matrix(cat, stages),
        "tools": _tools(cat),
        "skills": _skills(cat),
        "orphans": [t.name for t in cat.tools if t.stage is None and t.marker is None],
        "stageless": [s.name for s in cat.skills if not s.stages],
        "marked": marked,
        "footer": {
            "code": code_hash(),
            "decisions_sha": cat.decisions_sha,
            "skills": {s.name: s.sha for s in cat.skills},
        },
    }


def backlog_payload() -> dict[str, Any]:
    """The backlog half: parsed ideas with computed states, area notes and counts."""
    path = sb.backlog_path()
    if path is None:
        return {"found": False, "ideas": [], "areas": [], "notes": {}, "digest": "none"}
    source = path.read_text(encoding="utf-8")
    ideas = sb.classify(sb.parse_backlog(source))
    areas = list(dict.fromkeys(i["area"] for i in ideas))
    by_state = Counter(i["state"] for i in ideas)
    cells = Counter((i["area"], i["state"]) for i in ideas)
    return {
        "found": True,
        "path": str(path),
        "digest": sb.backlog_digest(),
        "ideas": [
            {
                "id": i["id"],
                "n": i["n"],
                "title": i["title"],
                "area": i["area"],
                "status_raw": i["status_raw"],
                "state": i["state"],
                "added": i["added"],
                "slice": i["slice"],
                "depends_raw": i["depends_raw"],
                "deps": i["deps"],
                "unmet": i["unmet"],
                "unlocks": i["unlocks"],
                "layer": i["layer"],
                "dependents": i["dependents"],
                "what": i["what"],
                "why": i["why"],
                "rigour": i["rigour"],
                "open": i["open"],
            }
            for i in ideas
        ],
        "areas": areas,
        "notes": sb.area_notes(source),
        "by_state": {s: by_state.get(s, 0) for s in STATES},
        "by_area": {a: {s: cells.get((a, s), 0) for s in STATES} for a in areas},
        "slices": sorted({i["slice"] for i in ideas if i["slice"]}),
    }


def build(ctx: HubContext) -> dict[str, Any]:
    """The `platform` payload: `catalog`, `backlog`, `commands` and `methods`."""
    out: dict[str, Any] = {
        "ready": True,
        "methods": dict(METHODS),
        "commands": [dict(c) for c in COMMANDS],
        "states": list(STATES),
        "catalog": None,
        "catalog_error": None,
        "backlog": None,
        "backlog_error": None,
    }
    try:
        out["catalog"] = catalog_payload(ctx.project.settings)
    except Exception as exc:  # one half failing must not hide the other
        out["catalog_error"] = f"{type(exc).__name__}: {exc}"
    try:
        out["backlog"] = backlog_payload()
    except Exception as exc:
        out["backlog_error"] = f"{type(exc).__name__}: {exc}"
    return out

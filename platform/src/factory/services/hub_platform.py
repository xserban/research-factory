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
- `run_map` is declared text (the "How it works" tab): what each actor does per lifecycle stage,
  the loops back and the steps of one tool call. It holds no count; the page takes each stage's
  skills and tool count from `catalog`. Every stage id is a `site_catalog.STAGE_IDS` id, every
  loop joins two of them, and every tool it names is a registered tool (tests check all three).
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
    "run_map": (
        "Declared text from the platform's rules, the rf-run skill and the architecture notes, drawn as a "
        "track of the lifecycle stages. Each stage's skills and tool count come from the capability "
        "catalog; the stage of a skill is declared in its front matter. Loops are drawn as arcs back."
    ),
    "tree": (
        "Layers follow the recorded dependencies: an idea sits one layer right of its deepest "
        "dependency. Only ideas with a recorded idea dependency (or that others depend on) are drawn."
    ),
}


RUN_MAP: dict[str, Any] = {
    "lead": (
        "A project moves through nine stages, with three loops back. Claude reads and judges through "
        "MCP tools, led by one skill per stage. The platform records every act as an event, computes "
        "every count and holds the gates. At the attended level the researcher decides at the gates, from the CLI and this hub; at the supervised and autonomous levels an agent may close the gates that allow it and the researcher reviews afterwards."
    ),
    "entry": (
        "Every session starts with rf-run: it calls project_status, which reads the stage and the "
        "researcher's queue from the log and names the skill that takes over. No stage is remembered "
        "from an earlier session."
    ),
    "stages": (
        {
            "id": "frame",
            "human": (
                "Selects one suggestion per level, top-down: goal, questions, plan, seeds, probe, protocol",
                "Confirms the PRESS review of the search",
            ),
            "cmd": "factory decide select",
            "tools": (
                "decision_suggest",
                "question_record",
                "seed_add",
                "probe_run",
                "protocol_record",
                "protocol_press_review",
            ),
            "sessions": "",
            "platform": (
                "Versions the question and the protocol",
                "Measures the probe's recall on the seeds",
                "Keeps held-out seeds out of every agent answer",
            ),
            "out": "a ready protocol",
        },
        {
            "id": "gather",
            "human": (
                "Imports lists and files, then resolves and admits them",
                "Drops links into the inbox",
                "Sets the stopping rule for snowballing",
            ),
            "cmd": "factory import …",
            "tools": (
                "search_run",
                "dedup_run",
                "inbox_add",
                "references_extract",
                "snowball_round",
                "search_chase",
            ),
            "sessions": "",
            "platform": (
                "Queries the literature sources over a polite client",
                "Merges duplicates, reversibly",
                "Links reference lists to the corpus and applies the stopping rule",
            ),
            "out": "candidate records",
        },
        {
            "id": "screen",
            "human": (
                "Labels the calibration sample",
                "Resolves disagreements between the passes",
                "Passes the screening gate",
            ),
            "cmd": "",
            "tools": ("screen_next", "screen_record", "screen_check_draw", "screen_agreement"),
            "sessions": "Pass A and pass B run in separate Claude Code sessions.",
            "platform": (
                "Hands out batches as leased tasks",
                "Computes agreement and the PRISMA counts",
            ),
            "out": "included works",
        },
        {
            "id": "acquire",
            "human": ("Attaches PDFs the routes cannot fetch", "Runs the conversion"),
            "cmd": "factory document convert",
            "tools": ("library_adoptable", "library_adopt", "fulltext_fetch", "document_read"),
            "sessions": "",
            "platform": (
                "Stores sources in the library, by hash",
                "Converts PDF with docling, LaTeX with pandoc, HTML with latexml",
                "Pins one canonical document per work",
            ),
            "out": "pinned full text",
        },
        {
            "id": "extract",
            "human": (
                "Rules on each miner's design: selection, scope, absence, passes",
                "Labels audit and calibration samples",
                "Resolves the disagreements the gate keeps",
            ),
            "cmd": "",
            "tools": (
                "extract_next",
                "extract_record",
                "mine_next",
                "mine_record",
                "mine_disagreements",
                "extract_agreement",
            ),
            "sessions": "Pass A and pass B run in separate sessions, as in screening.",
            "platform": (
                "Checks every quote against the pinned document",
                "Computes agreement per miner and draws audit samples",
            ),
            "out": "quoted rows per work",
        },
        {
            "id": "understand",
            "human": (
                "Confirms lineage relations and named ideas",
                "Reviews interpretations",
                "Draws regions of interest",
            ),
            "cmd": "",
            "tools": (
                "relation_propose",
                "idea_propose",
                "interpretation_record",
                "region_propose",
                "graph_query",
                "view_onion",
            ),
            "sessions": "",
            "platform": (
                "Builds the graph from confirmed items only",
                "Computes the views: onion, coverage, timeline, horizon",
            ),
            "out": "graph, regions, syntheses",
        },
        {
            "id": "develop",
            "human": (
                "Rates the arguments of a spar and writes the balance",
                "Registers or concludes hypotheses",
            ),
            "cmd": "",
            "tools": (
                "lead_record",
                "hypothesis_draft",
                "hypothesis_review",
                "experiment_design",
                "xrun_register",
            ),
            "sessions": "The critic runs in its own session, apart from the drafter.",
            "platform": (
                "Ties each lead to its trigger in the corpus",
                "Freezes a design before runs are registered",
            ),
            "out": "pre-registered hypotheses",
        },
        {
            "id": "write",
            "human": ("Reads and releases drafts", "Reads the findings of check"),
            "cmd": "",
            "tools": (
                "draft_write",
                "draft_verify_next",
                "draft_verify_record",
                "report_prisma",
                "report_evidence",
                "export_bibliography",
            ),
            "sessions": "The verifier runs in its own session and wrote none of the draft.",
            "platform": (
                "Computes the PRISMA, methods and evidence reports",
                "Links every sentence to the spans it cites",
            ),
            "out": "verified drafts and reports",
        },
        {
            "id": "maintain",
            "human": ("Chooses the digest channel", "Accepts or rejects curation proposals"),
            "cmd": "",
            "tools": ("watch_run", "feed_run", "digest_get", "lessons_list", "curation_propose"),
            "sessions": "A scheduled session runs the watch cycles.",
            "platform": (
                "Runs the due watch cycles",
                "Computes lessons from audits, disagreements and failed runs",
            ),
            "out": "a digest per cycle",
        },
    ),
    "loops": (
        {
            "from": "extract",
            "to": "gather",
            "label": "snowball",
            "what": "References of the included works bring new candidates, which are screened again.",
        },
        {
            "from": "maintain",
            "to": "gather",
            "label": "living review",
            "what": "Each watch cycle brings new papers into the corpus.",
        },
        {
            "from": "maintain",
            "to": "frame",
            "label": "lessons",
            "what": "Accepted curation proposals amend the protocol, the worked examples or a skill.",
        },
    ),
    "call": (
        {"who": "claude", "act": "Ask for work", "text": "mine_next, under the skill rf-mine."},
        {
            "who": "platform",
            "act": "Lease a task",
            "text": "Creates a task with a 30-minute lease and stores its exact content as the input_blob.",
        },
        {
            "who": "claude",
            "act": "Read and judge",
            "text": "Reads the pinned document and decides what it says, with quotes.",
        },
        {
            "who": "claude",
            "act": "Record",
            "text": "mine_record, with the rows, the model and the skill.",
        },
        {
            "who": "platform",
            "act": "Guard",
            "text": "Checks the lease, the pass, the gate and every quote. An invalid call writes nothing.",
        },
        {
            "who": "platform",
            "act": "Append and fold",
            "text": "Appends the event to the session's log file; the projector folds it into the index.",
        },
        {
            "who": "human",
            "act": "Review",
            "text": "The hub page rebuilds when opened; the researcher's decisions go back through the CLI as human events.",
        },
    ),
    "rules": (
        (
            "Independence comes from sessions",
            "One MCP server serves one Claude Code session and its subagents, so a subagent cannot be the second pass. The platform refuses a session that has joined the other pass.",
        ),
        (
            "Judging and bookkeeping never mix",
            "The platform never calls a model. Every judgement comes from Claude through a tool; every count, hash, sample and PRISMA number is computed, never typed.",
        ),
        (
            "Human gates have no tool",
            "When a stage waits on the researcher, project_status lists the exact CLI command and Claude relays it.",
        ),
        (
            "Events are the record",
            "Events are append-only. The index and every hub page can be rebuilt from them.",
        ),
    ),
}
"""Declared text for the "How it works" tab (see module invariants). Not derived: a ruling on the
wording changes it here."""


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
        "run_map": RUN_MAP,
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

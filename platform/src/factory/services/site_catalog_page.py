# ruff: noqa: E501
"""The catalog product's page and build function: HTML from the `Catalog` model, via
`site.page`. Every value is escaped by `esc`; nothing here is typed except labels and layout."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from factory.services.context import Project
from factory.services.site_catalog import (
    ACCEPTED_MISMATCH,
    LIFECYCLE,
    MARKER_KINDS,
    Catalog,
    SkillInfo,
    ToolInfo,
    build_catalog,
)
from factory.services.site_widgets import REPORT_CSS, esc, note, table

CATALOG_CSS = (
    ".card{background:var(--card);border:1px solid var(--mut);padding:10px 14px;margin:8px 0}"
    ".card h3{margin:0 0 4px}.card ol{margin:6px 0 0 18px;padding:0}.card li{margin:3px 0}"
    ".tool{border-top:1px solid var(--mut);padding:8px 0}.tool b{color:var(--ac)}"
    ".tool pre{background:var(--dk);padding:8px;overflow:auto;font-size:11.5px}"
    ".bad{background:var(--card);border:1px solid #c33;border-left:3px solid #c33;color:#e55;padding:10px 14px;margin:8px 0}"
    ".dim{color:var(--dim)}.ex{color:var(--light);margin:2px 0;font-size:12px}"
    "summary{cursor:pointer;color:var(--dim)}"
    ".mark{border:1px solid var(--mut);color:var(--amber);font-size:10.5px;padding:0 5px}"
)


def _skill_card(skill: SkillInfo) -> str:
    steps = "".join(
        f"<li>{esc(s.text)} <small class=dim>({esc(s.file)}:{s.line})</small></li>"
        for s in skill.steps
    )
    extra = [st for st in skill.stages[1:]]
    spans = f" <small class=dim>also: {esc(', '.join(extra))}</small>" if extra else ""
    return (
        f"<div class=card><h3>{esc(skill.name)}{spans}</h3><div>{esc(skill.description)}</div>"
        + (f"<ol>{steps}</ol>" if steps else "")
        + "</div>"
    )


def _tool(tool: ToolInfo, catalog: Catalog) -> str:
    examples = "".join(
        f"<div class=ex>{esc(s.skill)}: {esc(s.text)}</div>"
        for sk in catalog.skills
        for s in sk.steps
        if tool.name in s.tools
    )
    also = (
        f"<div class=dim>also used in: {', '.join(esc(s) for s in tool.also_used_in)}</div>"
        if tool.also_used_in
        else ""
    )
    badge = f" <span class=mark>{esc(tool.marker)}</span>" if tool.marker else ""
    return (
        f"<div class=tool id='{esc(tool.name)}'><b>{esc(tool.name)}</b>{badge} "
        f"<small>({esc(', '.join(tool.params) or 'no inputs')})</small>"
        f"<div>{esc(tool.description)}</div>"
        f"<details><summary>inputs</summary><pre>{esc(tool.input_schema_json)}</pre></details>"
        f"{examples}{also}</div>"
    )


def render(catalog: Catalog, built_at: str, code: str) -> str:
    c = catalog.count_check
    header = "<h1>Capability catalog</h1>" + table(
        [
            "tools registered",
            "tools listed",
            "skills",
            "prompts",
            "examples",
            "marked",
            "orphan tools",
            "flags",
        ],
        [
            [
                c.registered,
                c.listed,
                len(catalog.skills),
                "not derived" if catalog.prompts is None else catalog.prompts,
                catalog.examples,
                sum(1 for t in catalog.tools if t.marker),
                catalog.flag_counts()["orphan-tool"],
                len(catalog.flags),
            ]
        ],
    )
    if c.ok:
        header += note(
            f"Count check: {c.registered} tools registered in the source, all listed by the built server."
        )
    else:
        parts = [f"registered {c.registered}, listed {c.listed}"]
        for label, names in (
            ("not listed", c.missing),
            ("not in source", c.extra),
            ("duplicate", c.duplicates),
        ):
            if names:
                parts.append(f"{label}: {', '.join(names)}")
        header += f"<div class=bad>Count check failed. {esc('; '.join(parts))}</div>"
    for check, reason in sorted(catalog.skipped.items()):
        header += note(f"Not derived: {check} ({reason}).")

    body = [header]
    for stage_id, label, covers in LIFECYCLE:
        skills = [s for s in catalog.skills if s.stages[:1] == (stage_id,)]
        tools = [t for t in catalog.tools if t.stage == stage_id]
        sec = f"<h2 id='{esc(stage_id)}'>{esc(label)}</h2><div class=dim>{esc(covers)}</div>"
        sec += (
            "".join(_skill_card(s) for s in skills) or "<p class=dim>No skill has this stage.</p>"
        )
        sec += (
            "".join(_tool(t, catalog) for t in tools)
            or "<p class=dim>No tool is assigned here.</p>"
        )
        body.append(sec)
    orphans = [t for t in catalog.tools if t.stage is None and t.marker is None]
    stageless = [s for s in catalog.skills if not s.stages]
    body.append(
        "<h2>Unassigned</h2>"
        + note(
            "Tools no skill names and no marker covers (orphans), and skills with no valid stage."
        )
        + (
            "".join(_skill_card(s) for s in stageless) + "".join(_tool(t, catalog) for t in orphans)
            or "<p class=dim>None.</p>"
        )
    )

    marked_rows = [
        [
            t.name,
            t.marker,
            MARKER_KINDS.get(t.marker or "", "")
            + (
                f" Access row differs: {ACCEPTED_MISMATCH[t.name]}"
                if t.name in ACCEPTED_MISMATCH
                else ""
            ),
            t.access or "no access row",
            ", ".join(t.skills) or "none",
        ]
        for kind in MARKER_KINDS
        for t in catalog.tools
        if t.marker == kind
    ]
    body.append(
        "<h2>Marked tools</h2>"
        + note(
            "Declared in services/site_catalog.py (MARKERS), never inferred from a name. A marked tool "
            "that no skill names is not an orphan. A human-only tool named by a skill, or a marker "
            "that disagrees with the tool's access row, is flagged below."
        )
        + table(["tool", "marker", "why", "access row", "named by skills"], marked_rows)
    )

    rows = [
        [f.code, f"{f.file}:{f.line}", f.message + (f"  |  {f.other}" if f.other else "")]
        for f in catalog.flags
    ]
    body.append(
        "<h2>Flags</h2>"
        + note(
            "Mechanical findings, listed for the researcher to judge; the platform rules on none of them."
        )
        + table(["code", "where", "finding"], rows)
    )
    hashes = ", ".join(f"{s.name} {s.sha}" for s in catalog.skills)
    body.append(
        f"<h2>Footer</h2><p class=dim>Built {esc(built_at)} · code {esc(code)} · decisions "
        f"{esc(catalog.decisions_sha or 'n/a')} · skills: {esc(hashes)}</p>"
    )
    from factory.services.site import page

    return page("Capability catalog", "".join(body), REPORT_CSS + CATALOG_CSS)


def build_catalog_product(project: Project, out: Path) -> None:
    from factory.services.site import code_hash

    catalog = build_catalog(project.settings)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    (out / "index.html").write_text(render(catalog, stamp, code_hash()), encoding="utf-8")

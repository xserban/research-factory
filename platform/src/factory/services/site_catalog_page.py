# ruff: noqa: E501
"""The catalog product's page and build function: HTML from the `Catalog` model, via
`site.page`. Every value is escaped by `esc`; nothing here is typed except labels and layout."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from factory.config import Settings
from factory.services.site_catalog import (
    ACCEPTED_MISMATCH,
    LIFECYCLE,
    MARKER_KINDS,
    STAGE_IDS,
    Catalog,
    Flag,
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


def _first_line(text: str) -> str:
    return text.strip().split("\n", 1)[0]


def _flag_stage(flag: Flag, catalog: Catalog) -> str:
    """The stage a flag belongs to: its skill's primary stage (named in the file path), else the
    stage of a tool its message names, else `unassigned`."""
    for sk in catalog.skills:
        if f"/{sk.name}/" in flag.file or flag.file.endswith(f"/{sk.name}"):
            return sk.stages[0] if sk.stages else "unassigned"
    for t in catalog.tools:
        if t.name in flag.message or t.name == flag.file:
            return t.stage or "unassigned"
    return "unassigned"


def stage_summary(catalog: Catalog) -> list[dict[str, Any]]:
    """One row per stage in `STAGE_IDS` order, plus `unassigned` when a tool, skill or flag has
    no stage. Counts are computed from the catalog, never typed."""
    labels = {sid: label for sid, label, _ in LIFECYCLE}
    covers = {sid: c for sid, _, c in LIFECYCLE}
    rows: list[dict[str, Any]] = []
    for sid in (*STAGE_IDS, "unassigned"):
        key: str | None = None if sid == "unassigned" else sid
        skills = [s for s in catalog.skills if (s.stages[:1] == (sid,) if key else not s.stages)]
        tools = [t for t in catalog.tools if t.stage == key]
        flags = [f for f in catalog.flags if _flag_stage(f, catalog) == sid]
        if sid == "unassigned" and not (skills or tools or flags):
            continue
        rows.append(
            {
                "id": sid,
                "label": labels.get(sid, "Unassigned"),
                "covers": covers.get(sid, "tools no skill names; skills with no stage"),
                "n_skills": len(skills),
                "n_tools": len(tools),
                "n_flags": len(flags),
                "skills": [{"n": s.name, "d": s.description, "t": list(s.tools)} for s in skills],
                "tools": [{"n": t.name, "d": _first_line(t.description)} for t in tools],
                "flags": [{"c": f.code, "w": f"{f.file}:{f.line}", "m": f.message} for f in flags],
            }
        )
    return rows


MAP_CSS = (
    "/*cmap*/"
    "#cmap{margin:6px 0 22px}#cmap .bar{display:flex;gap:10px;align-items:center;margin:0 0 10px}"
    "#cmap input{flex:1;max-width:420px;background:var(--dk);color:var(--fg);border:1px solid var(--mut);padding:6px 9px;font:inherit}"
    "#cmap .hint{color:var(--dim);font-size:12px}"
    "#cmap .line{display:flex;align-items:stretch;overflow-x:auto;padding:6px 2px 10px}"
    "#cmap .cn{flex:none;width:26px;align-self:center;height:3px;margin:0 2px;"
    "background:repeating-linear-gradient(90deg,var(--ac) 0 6px,transparent 6px 12px);"
    "background-size:12px 3px;animation:cflow 1s linear infinite;opacity:.75}"
    "#cmap.paused .cn{animation-play-state:paused}"
    "@keyframes cflow{to{background-position:12px 0}}"
    "@media (prefers-reduced-motion:reduce){#cmap .cn{animation:none}}"
    "#cmap .stn{flex:none;position:relative;text-align:left;font:inherit;color:var(--fg);cursor:pointer;"
    "background:var(--card);border:1px solid var(--mut);padding:8px 10px;min-width:96px}"
    "#cmap .stn:hover,#cmap .stn:focus-visible{border-color:var(--ac);outline:none}"
    "#cmap .stn[aria-expanded=true]{border-color:var(--ac);background:var(--sel);box-shadow:0 0 0 1px var(--ac)}"
    "#cmap .stn .k{font:600 10.5px var(--mono,monospace);letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}"
    "#cmap .stn .v{font:700 20px var(--mono,monospace);color:var(--ac);line-height:1.2}"
    "#cmap .stn .s{font-size:11px;color:var(--dim)}"
    "#cmap .stn .fb{position:absolute;top:-7px;right:-7px;background:var(--amber);color:var(--bg);"
    "font:700 10px var(--mono,monospace);padding:1px 5px;border-radius:9px}"
    "#cmap .stn .mc{position:absolute;bottom:-7px;right:-7px;background:var(--green);color:var(--bg);"
    "font:700 10px var(--mono,monospace);padding:1px 5px;border-radius:9px}"
    "#cmap .stn.lit{border-color:var(--green)}#cmap .stn.dimmed{opacity:.4}"
    "#cmap .panel{border:1px solid var(--ac);background:var(--card);padding:10px 14px;margin:4px 0}"
    "#cmap .panel h3{margin:0 0 2px;color:var(--ac)}#cmap .panel h4{margin:12px 0 4px;color:var(--dim);"
    "font-size:11px;letter-spacing:.12em;text-transform:uppercase}"
    "#cmap .panel .it{border-top:1px solid var(--mut);padding:5px 0;font-size:13px}"
    "#cmap .panel .it b{color:var(--fg)}#cmap .panel .t{color:var(--cyan);font-size:12px}"
    "#cmap .panel .fl{color:var(--amber)}#cmap .panel .w{color:var(--dim);font-size:11.5px}"
    "/*end cmap*/"
)

MAP_JS = r"""
(function(){
var root=document.getElementById('cmap');if(!root)return;
var data=JSON.parse(document.getElementById('cmap-data').textContent).stages;
var line=root.querySelector('.line'),panel=root.querySelector('.panel'),q=root.querySelector('input');
var open=null,term='';
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
function hit(s){return !term||(s.n+' '+s.d).toLowerCase().indexOf(term)>=0}
function matches(st){return {skills:st.skills.filter(hit),tools:st.tools.filter(hit)}}
function btn(id){return document.getElementById('st-'+id)}
function paintLine(){
  data.forEach(function(st){
    var b=btn(st.id);if(!b)return;var m=matches(st),n=m.skills.length+m.tools.length;
    var old=b.querySelector('.mc');if(old)old.remove();
    b.classList.toggle('lit',!!term&&n>0);b.classList.toggle('dimmed',!!term&&n===0);
    if(term&&n>0){b.appendChild(el('span','mc',String(n)))}
  });
}
function paintPanel(){
  panel.textContent='';
  if(!open){panel.hidden=true;return}
  var st=data.filter(function(s){return s.id===open})[0];
  if(!st){panel.hidden=true;return}
  var m=matches(st);panel.hidden=false;
  panel.appendChild(el('h3',null,st.label));panel.appendChild(el('div','w',st.covers));
  panel.appendChild(el('h4',null,'Skills ('+m.skills.length+')'));
  m.skills.forEach(function(s){var d=el('div','it');d.appendChild(el('b',null,s.n));
    d.appendChild(el('div',null,s.d));if(s.t.length)d.appendChild(el('div','t','tools: '+s.t.join(', ')));panel.appendChild(d)});
  panel.appendChild(el('h4',null,'Tools ('+m.tools.length+')'));
  m.tools.forEach(function(t){var d=el('div','it');d.appendChild(el('b',null,t.n));d.appendChild(el('span','w',' '+t.d));panel.appendChild(d)});
  if(st.flags.length){panel.appendChild(el('h4',null,'Flags ('+st.flags.length+')'));
    st.flags.forEach(function(f){var d=el('div','it');d.appendChild(el('b','fl',f.c));d.appendChild(el('span','w',' '+f.w));d.appendChild(el('div',null,f.m));panel.appendChild(d)})}
}
function setOpen(id,fromHash){
  open=id;data.forEach(function(s){var b=btn(s.id);if(b)b.setAttribute('aria-expanded',String(s.id===id))});
  paintPanel();
  if(!fromHash){try{history.replaceState(null,'',id?'#stage-'+id:location.pathname+location.search)}catch(e){}}
}
data.forEach(function(st){var b=btn(st.id);if(b)b.addEventListener('click',function(){setOpen(open===st.id?null:st.id)})});
q.addEventListener('input',function(){term=q.value.trim().toLowerCase();paintLine();paintPanel()});
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&open)setOpen(null)});
function fromHash(){var m=/^#stage-([a-z-]+)$/.exec(location.hash);
  if(m&&btn(m[1])){setOpen(m[1],true)}else if(open){setOpen(null,true)}}
window.addEventListener('hashchange',fromHash);
document.addEventListener('visibilitychange',function(){root.classList.toggle('paused',document.hidden)});
root.hidden=false;fromHash();
})();
"""


def _stage_map(catalog: Catalog) -> str:
    rows = stage_summary(catalog)
    biggest = max([int(r["n_tools"]) for r in rows] + [1])
    parts: list[str] = []
    for r in rows:
        width = 96 + round(40 * int(r["n_tools"]) / biggest)
        flag = f"<span class=fb title='flags'>{int(r['n_flags'])}</span>" if r["n_flags"] else ""
        parts.append(
            f"<button type=button class=stn id='st-{esc(r['id'])}' aria-expanded=false "
            f"style='min-width:{width}px'><div class=k>{esc(r['label'])}</div>"
            f"<div class=v>{int(r['n_tools'])}</div>"
            f"<div class=s>{int(r['n_skills'])} skills · {int(r['n_tools'])} tools</div>{flag}</button>"
        )
    line = "<span class=cn aria-hidden=true></span>".join(parts)
    data = json.dumps({"stages": rows}, ensure_ascii=False).replace("</", "<\\/")
    return (
        "<div id=cmap hidden><div class=bar><input type=search id=cmap-q placeholder='Search tools and skills' "
        "aria-label='Search tools and skills'><span class=hint>Click a stage for its skills, tools and flags. Esc closes.</span></div>"
        f"<div class=line>{line}</div><div class=panel hidden></div>"
        f"<script type=application/json id=cmap-data>{data}</script></div>"
        f"<script>{MAP_JS}</script>"
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

    body = [header, _stage_map(catalog)]
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

    return page("Capability catalog", "".join(body), REPORT_CSS + CATALOG_CSS + MAP_CSS)


def render_catalog(settings: Settings) -> str:
    """The capability catalog page as HTML, derived from the skills and tools at the call."""
    from factory.services.site import code_hash

    catalog = build_catalog(settings)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return render(catalog, stamp, code_hash())

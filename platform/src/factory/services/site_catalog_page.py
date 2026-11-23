# ruff: noqa: E501
"""The catalog product's page and build function: HTML from the `Catalog` model, via
`site.page`. Every value is escaped by `esc`; nothing here is typed except labels and layout."""

from __future__ import annotations

import json
import re
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
from factory.services.site_kit_page import kit_page
from factory.services.site_widgets import esc

CATALOG_CSS = (
    ".ct-figs{display:flex;flex-wrap:wrap;gap:8px 28px;margin:0 0 12px}"
    ".ct-figs div{display:flex;flex-direction:column}"
    ".ct-figs b{font:500 var(--t-l)/1.2 var(--f-mono);font-variant-numeric:tabular-nums}"
    ".ct-figs span{font-size:var(--t-xs);color:var(--mut)}"
    ".ct-fail{background:var(--surface);border-radius:var(--r-s);box-shadow:inset 3px 0 0 var(--exc);padding:10px 14px;margin:8px 0;font-size:var(--t-s)}"
    ".ct-fail b{color:var(--exc)}"
    ".ct-skill{margin:0 0 var(--gap)}.ct-skill h3{font:600 var(--t-m)/1.3 var(--f-ui);margin:0 0 4px}"
    ".ct-skill ol{margin:8px 0 0 18px;padding:0}.ct-skill li{margin:4px 0}"
    ".ct-dim{color:var(--dim);font-size:var(--t-s)}"
    ".ct-tool{border-top:1px solid var(--hair);padding:10px 0;font-size:var(--t-s)}"
    ".ct-tool>b{font-family:var(--f-mono);color:var(--fg)}"
    ".ct-tool pre{background:var(--surface);border-radius:var(--r-s);padding:10px;overflow:auto;font:400 var(--t-xs) var(--f-mono);margin:6px 0 0}"
    ".ct-tool summary{cursor:pointer;color:var(--mut)}"
    ".ct-ex{color:var(--mut);margin:2px 0;font-size:var(--t-xs)}"
    ".ct-mark{border-radius:999px;background:var(--raised);color:var(--mut);font-size:var(--t-xs);padding:2px 8px}"
    ".ct-sec{margin:0 0 36px}.ct-sec>h2{font:600 var(--t-l)/1.3 var(--f-ui);margin:0 0 4px}"
    ".ct-sec>p{margin:0 0 12px}"
)


_STEP_NO = re.compile(r"^\s*\d+[.)]\s+")
"""A step's own leading number; the list numbers the steps."""


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
    "#cmap{margin:6px 0 36px}#cmap .ct-bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 12px}"
    "#cmap input{flex:1;min-width:200px;max-width:420px}"
    "#cmap .ct-hint{color:var(--mut);font-size:var(--t-xs)}"
    "#cmap .ct-line{display:flex;align-items:stretch;overflow-x:auto;padding:6px 2px 10px}"
    "#cmap .ct-cn{flex:none;width:22px;align-self:center;height:2px;margin:0 2px;background:var(--line)}"
    "#cmap .ct-stn{flex:none;text-align:left;font:inherit;color:var(--fg);cursor:pointer;border:0;padding:12px 14px;min-width:104px}"
    "#cmap .ct-stn:hover,#cmap .ct-stn:focus-visible{background:var(--raised);outline:none}"
    "#cmap .ct-stn:focus-visible{box-shadow:0 0 0 2px var(--acc)}"
    "#cmap .ct-stn[aria-expanded=true]{background:var(--acc-soft);box-shadow:inset 0 0 0 1px var(--acc)}"
    "#cmap .ct-stn .ct-k{display:block;font:500 var(--t-xs) var(--f-ui);color:var(--mut)}"
    "#cmap .ct-stn .ct-v{display:block;font:500 var(--t-xl)/1.2 var(--f-mono);font-variant-numeric:tabular-nums}"
    "#cmap .ct-stn .ct-s{display:block;font-size:var(--t-xs);color:var(--dim)}"
    "#cmap .ct-stn .ct-fb{display:block;font-size:var(--t-xs);color:var(--exc)}"
    "#cmap .ct-stn .ct-mc{display:block;font-size:var(--t-xs);color:var(--inc)}"
    "#cmap .ct-stn.lit{box-shadow:inset 0 0 0 1px var(--inc)}#cmap .ct-stn.dimmed{opacity:.45}"
    "#cmap .ct-panel{margin:4px 0}"
    "#cmap .ct-panel h3{margin:0 0 2px;font:600 var(--t-m) var(--f-ui)}#cmap .ct-panel h4{margin:14px 0 4px;color:var(--mut);"
    "font:500 var(--t-xs) var(--f-ui)}"
    "#cmap .ct-panel .ct-it{border-top:1px solid var(--hair);padding:6px 0;font-size:var(--t-s)}"
    "#cmap .ct-panel .ct-t{color:var(--mut);font-size:var(--t-xs)}"
    "#cmap .ct-panel .ct-fl{color:var(--exc);font-family:var(--f-mono)}#cmap .ct-panel .ct-w{color:var(--dim);font-size:var(--t-xs)}"
    "/*end cmap*/"
)

MAP_JS = r"""
(function(){
var root=document.getElementById('cmap');if(!root)return;
var data=JSON.parse(document.getElementById('cmap-data').textContent).stages;
var line=root.querySelector('.ct-line'),panel=root.querySelector('.ct-panel'),q=root.querySelector('input');
var open=null,term='';
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
function hit(s){return !term||(s.n+' '+s.d).toLowerCase().indexOf(term)>=0}
function matches(st){return {skills:st.skills.filter(hit),tools:st.tools.filter(hit)}}
function btn(id){return document.getElementById('st-'+id)}
function paintLine(){
  data.forEach(function(st){
    var b=btn(st.id);if(!b)return;var m=matches(st),n=m.skills.length+m.tools.length;
    var old=b.querySelector('.ct-mc');if(old)old.remove();
    b.classList.toggle('lit',!!term&&n>0);b.classList.toggle('dimmed',!!term&&n===0);
    if(term&&n>0){b.appendChild(el('span','ct-mc',n+(n===1?' match':' matches')))}
  });
}
function paintPanel(){
  panel.textContent='';
  if(!open){panel.hidden=true;return}
  var st=data.filter(function(s){return s.id===open})[0];
  if(!st){panel.hidden=true;return}
  var m=matches(st);panel.hidden=false;
  panel.appendChild(el('h3',null,st.label));panel.appendChild(el('div','ct-w',st.covers));
  panel.appendChild(el('h4',null,'Skills ('+m.skills.length+')'));
  m.skills.forEach(function(s){var d=el('div','ct-it');d.appendChild(el('b',null,s.n));
    d.appendChild(el('div',null,s.d));if(s.t.length)d.appendChild(el('div','ct-t','tools: '+s.t.join(', ')));panel.appendChild(d)});
  panel.appendChild(el('h4',null,'Tools ('+m.tools.length+')'));
  m.tools.forEach(function(t){var d=el('div','ct-it');d.appendChild(el('b',null,t.n));d.appendChild(el('span','ct-w',' '+t.d));panel.appendChild(d)});
  if(st.flags.length){panel.appendChild(el('h4',null,'Flags ('+st.flags.length+')'));
    st.flags.forEach(function(f){var d=el('div','ct-it');d.appendChild(el('b','ct-fl',f.c));d.appendChild(el('span','ct-w',' '+f.w));d.appendChild(el('div',null,f.m));panel.appendChild(d)})}
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
    parts: list[str] = []
    for r in rows:
        nf = int(r["n_flags"])
        flag = f"<span class=ct-fb>{nf} flag{'s' if nf != 1 else ''}</span>" if nf else ""
        parts.append(
            f"<button type=button class='card ct-stn' id='st-{esc(r['id'])}' aria-expanded=false>"
            f"<span class=ct-k>{esc(r['label'])}</span>"
            f"<span class=ct-v>{int(r['n_tools'])}</span>"
            f"<span class=ct-s>{int(r['n_skills'])} skills · {int(r['n_tools'])} tools</span>{flag}</button>"
        )
    line = "<span class=ct-cn aria-hidden=true></span>".join(parts)
    data = json.dumps({"stages": rows}, ensure_ascii=False).replace("</", "<\\/")
    return (
        "<div id=cmap hidden><div class=ct-bar><input type=search id=cmap-q placeholder='Search tools and skills' "
        "aria-label='Search tools and skills'><span class=ct-hint>Click a stage for its skills, tools and flags. Esc closes.</span></div>"
        f"<div class=ct-line>{line}</div><div class='card raised ct-panel' hidden></div>"
        f"<script type=application/json id=cmap-data>{data}</script></div>"
    )


def _skill_card(skill: SkillInfo) -> str:
    steps = "".join(
        f"<li>{esc(_STEP_NO.sub('', s.text, count=1))} <small class=ct-dim>({esc(s.file)}:{s.line})</small></li>"
        for s in skill.steps
    )
    extra = [st for st in skill.stages[1:]]
    spans = f" <small class=ct-dim>also: {esc(', '.join(extra))}</small>" if extra else ""
    return (
        f"<div class='card ct-skill'><h3>{esc(skill.name)}{spans}</h3><div>{esc(skill.description)}</div>"
        + (f"<ol>{steps}</ol>" if steps else "")
        + "</div>"
    )


def _tool(tool: ToolInfo, catalog: Catalog) -> str:
    examples = "".join(
        f"<div class=ct-ex>{esc(s.skill)}: {esc(s.text)}</div>"
        for sk in catalog.skills
        for s in sk.steps
        if tool.name in s.tools
    )
    also = (
        f"<div class=ct-dim>also used in: {', '.join(esc(s) for s in tool.also_used_in)}</div>"
        if tool.also_used_in
        else ""
    )
    badge = f" <span class=ct-mark>{esc(tool.marker)}</span>" if tool.marker else ""
    return (
        f"<div class=ct-tool id='{esc(tool.name)}'><b>{esc(tool.name)}</b>{badge} "
        f"<span class=meta>({esc(', '.join(tool.params) or 'no inputs')})</span>"
        f"<div>{esc(tool.description)}</div>"
        f"<details><summary>inputs</summary><pre>{esc(tool.input_schema_json)}</pre></details>"
        f"{examples}{also}</div>"
    )


def _table(headers: list[str], rows: list[list[object]], numeric: tuple[int, ...] = ()) -> str:
    """A kit table; columns named in `numeric` are right-aligned figures. Every cell is escaped."""

    def cls(i: int) -> str:
        return " class=r" if i in numeric else ""

    head = "".join(f"<th{cls(i)}>{esc(h)}</th>" for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f"<td{cls(i)}>{esc(c)}</td>" for i, c in enumerate(row)) + "</tr>"
        for row in rows
    )
    return f"<table class=t><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _sec(title: str, inner: str, *, ident: str = "") -> str:
    attr = f" id='{esc(ident)}'" if ident else ""
    return f"<section class=ct-sec><h2{attr}>{esc(title)}</h2>{inner}</section>"


def render(catalog: Catalog, built_at: str, code: str) -> str:
    c = catalog.count_check
    figs = [
        ("tools registered", c.registered),
        ("tools listed", c.listed),
        ("skills", len(catalog.skills)),
        ("prompts", "not derived" if catalog.prompts is None else catalog.prompts),
        ("examples", catalog.examples),
        ("marked", sum(1 for t in catalog.tools if t.marker)),
        ("orphan tools", catalog.flag_counts()["orphan-tool"]),
        ("flags", len(catalog.flags)),
    ]
    header = (
        "<header class=mh-head><h1>Capabilities</h1><p>The factory's tools and skills by lifecycle "
        "stage, derived from the source at each load.</p></header>"
        "<div class=ct-figs>"
        + "".join(f"<div><b>{esc(v)}</b><span>{esc(k)}</span></div>" for k, v in figs)
        + "</div>"
    )
    if c.ok:
        header += (
            f"<p class=note>Count check passed: {c.registered} tools registered in the source, "
            "all listed by the built server.</p>"
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
        header += f"<div class=ct-fail><b>Count check failed.</b> {esc('; '.join(parts))}</div>"
    for check, reason in sorted(catalog.skipped.items()):
        header += f"<p class=note>Not derived: {esc(check)} ({esc(reason)}).</p>"

    body = [header, _stage_map(catalog)]
    for stage_id, label, covers in LIFECYCLE:
        skills = [s for s in catalog.skills if s.stages[:1] == (stage_id,)]
        tools = [t for t in catalog.tools if t.stage == stage_id]
        sec = f"<p class=ct-dim>{esc(covers)}</p>"
        sec += (
            "".join(_skill_card(s) for s in skills)
            or "<p class=ct-dim>No skill has this stage.</p>"
        )
        sec += (
            "".join(_tool(t, catalog) for t in tools)
            or "<p class=ct-dim>No tool is assigned here.</p>"
        )
        body.append(_sec(label, sec, ident=stage_id))
    orphans = [t for t in catalog.tools if t.stage is None and t.marker is None]
    stageless = [s for s in catalog.skills if not s.stages]
    body.append(
        _sec(
            "Unassigned",
            "<p class=note>Tools no skill names and no marker covers (orphans), and skills with "
            "no valid stage.</p>"
            + (
                "".join(_skill_card(s) for s in stageless)
                + "".join(_tool(t, catalog) for t in orphans)
                or "<p class=ct-dim>None.</p>"
            ),
        )
    )

    marked_rows: list[list[object]] = [
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
        _sec(
            "Marked tools",
            "<p class=note>Declared in services/site_catalog.py (MARKERS), never inferred from a "
            "name. A marked tool that no skill names is not an orphan. A human-only tool named by "
            "a skill, or a marker that disagrees with the tool's access row, is flagged below.</p>"
            + _table(["tool", "marker", "why", "access row", "named by skills"], marked_rows),
        )
    )

    rows: list[list[object]] = [
        [f.code, f"{f.file}:{f.line}", f.message + (f"  |  {f.other}" if f.other else "")]
        for f in catalog.flags
    ]
    body.append(
        _sec(
            "Flags",
            "<p class=note>Mechanical findings, listed for the researcher to judge; the platform "
            "rules on none of them.</p>" + _table(["code", "where", "finding"], rows),
        )
    )
    hashes = ", ".join(f"{s.name} {s.sha}" for s in catalog.skills)
    body.append(
        _sec(
            "Footer",
            f"<p class=ct-dim>Built {esc(built_at)} · code {esc(code)} · decisions "
            f"{esc(catalog.decisions_sha or 'n/a')} · skills: {esc(hashes)}</p>",
        )
    )
    return kit_page(
        "Capabilities", "".join(body), "catalog", css=CATALOG_CSS + MAP_CSS, script=MAP_JS
    )


def render_catalog(settings: Settings) -> str:
    """The capability catalog page as HTML, derived from the skills and tools at the call."""
    from factory.services.site import code_hash

    catalog = build_catalog(settings)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return render(catalog, stamp, code_hash())


def render_unavailable() -> str:
    """The catalog page when no project is listed: says what to do next."""
    return kit_page(
        "Capabilities",
        "<header class=mh-head><h1>Capabilities</h1><p>No project found under the factory "
        "root, so the catalog cannot be derived. Create a project from the portal, then reload "
        "this page.</p></header>",
        "catalog",
    )

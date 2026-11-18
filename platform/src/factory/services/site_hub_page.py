# ruff: noqa: E501
"""The project hub page `site/index.html` (IDEA-96: moved out of `site.py`).

The hub page is not a product: its code is in no product's fingerprint, so changing it rebuilds no
product. It reads the statuses (`site.status`) and a few counts, and writes one file.
"""

from __future__ import annotations

import contextlib
import html
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from sqlalchemy import text

from factory.services.context import Project
from factory.services.site import (
    THEME_CSS,
    Planned,
    Product,
    ProductStatus,
    planned,
    products,
    site_dir,
    status,
)
from factory.services.site_charts import CHART_CSS, activity
from factory.services.site_chrome import BAR_CSS, CHROME_SCRIPT, hub_bar
from factory.services.site_theme import LIGHT_CSS, THEME_SCRIPT

_HUB_CSS: Final = (
    "body{display:flex;flex-direction:column;height:100vh;overflow:hidden;max-width:none;padding:0}"
    ".shell{display:flex;flex:1;min-height:0}"
    "nav input{width:calc(100% - 28px);margin:10px 14px 0;box-sizing:border-box}"
    "nav{width:268px;flex:none;overflow:auto;border-right:1px solid var(--mut);"
    "background:var(--navbg);padding:6px 0 24px}"
    "nav h3{margin:16px 14px 4px;font-size:10.5px;font-weight:600;letter-spacing:.16em;"
    "text-transform:uppercase;color:var(--dim)}"
    "nav a.i{display:flex;align-items:center;gap:10px;padding:6px 14px;color:var(--light);"
    "cursor:pointer;border-left:2px solid transparent;font-size:12.5px}"
    "nav a.i:hover{background:var(--lt);color:var(--fg)}"
    "nav a.i.on{background:var(--sel);color:var(--fg);border-left-color:var(--ac)}"
    "nav a.i.plan{color:var(--dim)}nav .no{color:var(--dim);font-size:10.5px;width:18px}"
    "nav .n{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
    "main{flex:1;min-width:0;position:relative}main iframe{width:100%;height:100%;border:0;"
    "background:var(--bg)}"
    "#home{height:100%;overflow:auto;padding:22px 30px 60px}#home .wrap{max-width:1040px;margin:0 auto}"
    ".sec{font:600 11px var(--mono);letter-spacing:.18em;text-transform:uppercase;"
    "color:var(--ac);margin:26px 0 10px;display:flex;align-items:center;gap:10px}"
    ".sec::after{content:'';flex:1;height:1px;background:var(--mut)}"
    ".line{display:flex;align-items:stretch;overflow-x:auto;padding:4px 2px 8px}"
    ".st{position:relative;flex:1;min-width:104px;margin-right:16px;padding:8px 10px;"
    "background:var(--card);border:1px solid var(--mut);cursor:pointer}"
    ".st:last-child{margin-right:0}.st:not(:last-child)::after{content:'\\25B8';position:absolute;"
    "right:-15px;top:50%;margin-top:-9px;color:var(--ac);font-size:13px}"
    ".st:hover{border-color:var(--ac)}.st .k{display:flex;gap:6px;align-items:center;"
    "font:600 10px var(--mono);letter-spacing:.14em;color:var(--dim);text-transform:uppercase}"
    ".st .k .led{margin-left:auto}.st .v{font:700 21px var(--mono);color:var(--ac);"
    "letter-spacing:.02em;line-height:1.25}.st .s{font:11px var(--mono);color:var(--dim)}"
    ".mods{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}"
    ".pn{position:relative;display:flex;flex-direction:column;background:var(--card);"
    "border:1px solid var(--mut);cursor:pointer}.pn:hover{border-color:var(--ac)}"
    ".pn .pt{display:flex;align-items:center;gap:9px;padding:5px 10px;background:var(--sel);"
    "border-bottom:1px solid var(--mut);font:600 11px var(--mono);letter-spacing:.12em;"
    "text-transform:uppercase;color:var(--fg)}.pn .pt .id{color:var(--ac)}.pn .pt .sp{flex:1}"
    ".pn .pb{padding:10px 12px;color:var(--light);font-size:13px;flex:1}"
    ".pn .pf{display:flex;justify-content:space-between;gap:8px;padding:6px 12px;"
    "border-top:1px solid var(--mut);font:11px var(--mono);color:var(--dim)}"
    ".pn .pf .go{color:var(--ac);letter-spacing:.1em}"
    ".pn.plan{opacity:.55;cursor:default}.pn.plan:hover{border-color:var(--mut)}"
    ".guide{position:relative;border:1px solid var(--mut);border-left:3px solid var(--ac);"
    "background:var(--card);padding:10px 14px;margin:6px 0;color:var(--light);"
    "font-size:13.5px;line-height:1.6}.guide b{color:var(--fg)}"
    ".hint{color:var(--dim);font:12px var(--mono);margin:8px 0 0}.hint code{background:var(--dk);"
    "padding:1px 6px;border:1px solid var(--mut);color:var(--ac)}"
    "@media (max-width:760px){nav{width:190px}.st{min-width:110px}}"
)

_HUB_JS: Final = """
const items=[...document.querySelectorAll('nav a.i')];const frame=document.getElementById('frame');
const home=document.getElementById('home');
let cur=null;
function show(){const id=(location.hash||'#home').slice(1);
 items.forEach(a=>a.classList.toggle('on',a.dataset.id===id));
 const a=items.find(x=>x.dataset.id===id);
 if(!a||a.dataset.id==='home'||!a.dataset.src){home.style.display='block';frame.style.display='none';return;}
 home.style.display='none';frame.style.display='block';
 if(cur!==a.dataset.src){const first=cur===null;cur=a.dataset.src;
  if(first)frame.setAttribute('src',cur);else frame.contentWindow.location.replace(cur);}}
window.addEventListener('hashchange',show);show();
document.querySelectorAll('[data-go]').forEach(r=>r.onclick=()=>{location.hash=r.dataset.go;});
const WORD={ok:'Nominal',stale:'Updates on open',busy:'Updating',bad:'Fault'};
async function live(){if(!location.protocol.startsWith('http'))return;
 const ac=new AbortController();const t=setTimeout(()=>ac.abort(),8000);
 try{const r=await fetch('api/status',{cache:'no-store',signal:ac.signal});const s=await r.json();
  const Q=s.queued||[];const L=st=>st==='ok'?'':st==='busy'?'stale':st;
  s.products.forEach(p=>{const st=Q.includes(p.id)?'busy':p.error?'bad':(p.stale||!p.built)?'stale':'ok';
   const a=items.find(x=>x.dataset.id===p.id);
   if(a){a.querySelector('.led').className='led '+L(st);a.dataset.src=p.id+'/'+p.entry;}
   document.querySelectorAll('[data-led="'+p.id+'"]').forEach(l=>l.className='led '+L(st));
   const pn=document.querySelector('.pn[data-go="'+p.id+'"]');
   if(pn){const b=pn.querySelector('.tg');if(b){b.className='tg '+(st==='ok'?'ok':st==='bad'?'bad':'warn');b.textContent=WORD[st];}
    const m=pn.querySelector('.when');if(m)m.textContent=p.built_at?'built '+p.built_at:'not built yet';}});
  document.getElementById('live').textContent=s.building?'REBUILDING':'LIVE';}catch(e){}
 finally{clearTimeout(t);setTimeout(live,10000);}}
live();
document.getElementById('q').addEventListener('input',e=>{const q=e.target.value.toLowerCase();
 items.forEach(a=>{a.style.display=!q||a.textContent.toLowerCase().includes(q)?'':'none';});});
"""


def _led(s: ProductStatus) -> str:
    return "bad" if s.error else "stale" if s.stale or not s.built else ""


def _word(s: ProductStatus) -> tuple[str, str]:
    if s.error:
        return "bad", "Fault"
    if s.stale or not s.built:
        return "warn", "Stale"
    return "ok", "Nominal"


STATIONS: Final = (
    ("SEARCH", "identified", "records found", "prisma"),
    ("SCREEN", "screened", "records screened", "prisma"),
    ("FULL TEXT", "assessed", "works assessed", "acquisition"),
    ("CONVERT", "converted", "documents", "conversion"),
    ("MINE", "miner_rows", "rows recorded", "miners"),
    ("SYNTHESIZE", "pages", "pages recorded", "synthesis"),
    ("REPORT", "products", "products built", "results"),
)


def _line_numbers(project: Project, built: int) -> dict[str, int]:
    """The counts shown on the production line: the review flow from the Results product's
    `line.json`, the rest from cheap queries."""
    out: dict[str, int] = {"products": built}
    with contextlib.suppress(OSError, ValueError):
        out.update(json.loads((site_dir(project) / "results" / "line.json").read_text("utf-8")))
    with project.index.connect() as conn:
        out["miner_rows"] = int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM extraction_rows WHERE superseded_by IS NULL "
                    "AND pass_label = 'A' AND schema_ref LIKE 'm-%'"
                )
            ).scalar()
            or 0
        )
        out["pages"] = int(
            conn.execute(text("SELECT COUNT(*) FROM events WHERE type = 'page.recorded'")).scalar()
            or 0
        )
        out["events"] = int(conn.execute(text("SELECT COUNT(*) FROM events")).scalar() or 0)
    return out


def _activity_days(project: Project, days: int = 21) -> list[tuple[str, int]]:
    """Events per calendar day, the last `days` days that have events, oldest first."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT substr(ts, 1, 10) AS d, COUNT(*) FROM events GROUP BY d "
                "ORDER BY d DESC LIMIT :n"
            ),
            {"n": days},
        ).all()
    return [(str(d), int(n)) for d, n in reversed(rows)]


def render_hub(
    project: Project,
    registry: Sequence[Product] | None = None,
    *,
    pending: Sequence[Planned] | None = None,
) -> Path:
    """Write `site/index.html`: a control room. A sidebar of every product with a status light;
    the home view shows the production line (stations with counts that open their product) and a
    panel per product with its state; the selected product opens inside the hub."""
    reg = list(registry if registry is not None else products())
    stat = status(project, reg)
    plans = list(pending if pending is not None else planned())
    by_id = {s.id: s for s in stat}
    num = _line_numbers(project, sum(1 for s in stat if s.built))
    groups: list[str] = []
    for item in [*(s.group for s in stat), *(p.group for p in plans)]:
        if item not in groups:
            groups.append(item)
    e = html.escape
    nav: list[str] = [
        "<a class='i on' data-id='home' href='#home'><span class=no>00</span>"
        "<span class='n'>Control room</span></a>"
    ]
    panels: list[str] = []
    idx = 0
    for group in groups:
        nav.append(f"<h3>{e(group)}</h3>")
        panels.append(f"<div class=sec>{e(group)}</div><div class=mods>")
        for s in (x for x in stat if x.group == group):
            idx += 1
            # every product links to its page: a served hub builds it when opened (IDEA-96)
            src = f"{s.id}/{s.entry}"
            nav.append(
                f"<a class='i' data-id='{e(s.id)}' data-src='{e(src)}' href='#{e(s.id)}'>"
                f"<span class=no>{idx:02d}</span><span class='led {_led(s)}'></span>"
                f"<span class='n'>{e(s.title)}</span></a>"
            )
            cls, word = _word(s)
            model = " <span class=tg>model-written</span>" if s.needs_model else ""
            when = f"built {e(s.built_at)}" if s.built_at else "not built yet"
            err = (
                f"<div class=tg style='color:var(--red);margin-top:6px'>{e(s.error)}</div>"
                if s.error
                else ""
            )
            panels.append(
                f"<div class='pn br' data-go='{e(s.id)}'><div class=pt><span class=id>{idx:02d}</span>"
                f"<span>{e(s.title)}</span><span class=sp></span><span class='tg {cls}'>{word}</span></div>"
                f"<div class=pb>{e(s.description)}{err}</div>"
                f"<div class=pf><span><span class=when>{when}</span>{model}</span>"
                "<span class=go>OPEN &rarr;</span></div></div>"
            )
        for p in (x for x in plans if x.group == group):
            idx += 1
            nav.append(
                f"<a class='i plan' data-id='plan-{e(p.title)}' data-src='' href='#home'>"
                f"<span class=no>{idx:02d}</span><span class='led off'></span>"
                f"<span class='n'>{e(p.title)}</span></a>"
            )
            panels.append(
                f"<div class='pn plan'><div class=pt><span class=id>{idx:02d}</span><span>{e(p.title)}</span>"
                "<span class=sp></span><span class=tg>Offline</span></div>"
                f"<div class=pb>{e(p.description)}</div>"
                f"<div class=pf><span>pilot script</span><span class=mono>{e(p.script)}</span></div></div>"
            )
        panels.append("</div>")
    stations = ""
    for name, key, sub, pid in STATIONS:
        prod = by_id.get(pid)
        led = _led(prod) if prod else "off"
        v = num.get(key)
        stations += (
            f"<div class=st data-go='{e(pid)}'><div class=k><span>{e(name)}</span>"
            f"<span class='led {led}' data-led='{e(pid)}'></span></div>"
            f"<div class=v>{'' if v is None else f'{v:,}'}{'' if v is not None else '&ndash;'}</div>"
            f"<div class=s>{e(sub)}</div></div>"
        )
    slug = e(project.paths.slug)
    n_stale = sum(1 for s in stat if s.stale or s.error)
    ready = "SYSTEM NOMINAL" if not n_stale else f"{n_stale} MODULE(S) NEED A REBUILD"
    doc = (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"{THEME_SCRIPT}<title>{slug}</title><style>{THEME_CSS}{_HUB_CSS}{CHART_CSS}{LIGHT_CSS}{BAR_CSS}</style></head><body>"
        + hub_bar(
            "projects",
            context=f"<span class=crumb>// {slug}</span>"
            f"<span class=ro>{ready} &middot; EVENTS <b>{num.get('events', 0):,}</b>"
            " &middot; <b id=live>SNAPSHOT</b></span>",
            main_hub_only=True,
        )
        + CHROME_SCRIPT
        + f"<div class=shell><nav><input id=q placeholder='filter modules'>{''.join(nav)}</nav><main>"
        "<iframe id=frame style='display:none' title='product'></iframe>"
        "<div id=home><div class=wrap><h1>Control room</h1>"
        "<div class=guide><b>Where to start.</b> <b>Explorer</b> to browse the papers and open "
        "any one with its quotes; <b>Results</b> for what the miners found; <b>Miners</b> and "
        "<b>Miner agreement</b> for how each reading was made and how stable it is; "
        "<b>Full-text acquisition</b> for what is missing and what to do about it; "
        "<b>Conversion coverage</b> to check the text extraction against the originals; "
        "<b>Synthesis pages</b> for model-written summaries checked against the quotes. Click "
        "any station or module: each explains what its numbers mean and what you can do.</div>"
        f"<div class=sec>Production line</div><div class=line>{stations}</div>"
        "<div class=sec>Activity: events recorded per day</div>"
        f"{activity(_activity_days(project))}"
        "<p class=hint>Each bar is one day of recorded events (screening verdicts, rows, labels, "
        "decisions). Hover a bar for the count.</p>"
        "<p class=hint>The line runs left to right: records found, screened, read in full, "
        "converted to text, mined for typed quoted values, synthesised, reported. A light turns "
        "amber when a module's inputs changed since it was built.</p>"
        + "".join(panels)
        + "<p class=hint>REBUILD <code>factory site build</code> &nbsp; SERVE LIVE "
        "<code>factory site serve</code> &nbsp; DASHBOARD <code>factory dashboard serve</code></p>"
        + f"</div></div></main></div><script>{_HUB_JS}</script></body></html>"
    )
    path = site_dir(project) / "index.html"
    path.write_text(doc, encoding="utf-8")
    return path

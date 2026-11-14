# ruff: noqa: E501
"""Loading indicators: the progress bar, the busy-button fetch wrapper, the panel spinner and the
corpus loading line."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from factory.services.site_chrome import BAR_CSS, CHROME_JS, CHROME_SCRIPT, with_bar
from factory.services.site_explorer_page import PAGE as EXPLORER_PAGE
from factory.services.site_panel import PANEL_CSS, PANEL_JS
from factory.services.site_portal import render_portal

_DOC = "<!doctype html><html><head><title>t</title></head><body><p>x</p></body></html>"


def test_with_bar_pages_carry_the_progress_bar_the_script_and_the_reduced_motion_rule() -> None:
    doc = with_bar(_DOC, None)
    assert "class=rf-prog" in doc and CHROME_JS in doc
    assert ".rf-prog" in BAR_CSS and "var(--hb-acc)" in BAR_CSS
    assert "prefers-reduced-motion:reduce" in BAR_CSS
    for token in ("pageshow", "window.fetch", "factoryBusy", "120000", "_self", "metaKey"):
        assert token in CHROME_JS


def test_the_project_hub_header_carries_the_bar_script() -> None:
    src = (Path(__file__).parents[1] / "src/factory/services/site.py").read_text()
    assert "+ CHROME_SCRIPT" in src and f"<script>{CHROME_JS}</script>" == CHROME_SCRIPT


def test_the_portal_has_the_bar_and_wrapper() -> None:
    doc = render_portal([], create_token="tok")
    assert "rf-prog" in doc and "window.fetch" in doc


def test_panel_has_a_loading_marker_reset_on_src_change() -> None:
    assert ".rfp-ld" in PANEL_CSS and "prefers-reduced-motion" in PANEL_CSS
    assert "rfp-ld" in PANEL_JS and "addEventListener('load'" in PANEL_JS
    assert PANEL_JS.index("ld.hidden=false") < PANEL_JS.index("fr.setAttribute('src',u)")


def test_explorer_shows_a_loading_line_that_the_first_render_replaces() -> None:
    assert 'id="view"><p class="dim rf-loading"' in EXPLORER_PAGE
    assert "Loading corpus" in EXPLORER_PAGE


_HARNESS = r"""
const vm=require('vm');const code=process.argv[2];
const listeners={};const timers=[];
function mkBtn(label){return {tagName:'BUTTON',nodeType:1,children:[],disabled:false,textContent:label,
 attrs:{},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},
 hasAttribute(k){return k in this.attrs},parentNode:null};}
const win={addEventListener(){},fetch:null};
let resolve,reject;
win.fetch=function(){return new Promise((a,b)=>{resolve=a;reject=b;});};
const doc={querySelector(){return null},addEventListener(t,f,c){(listeners[t]=listeners[t]||[]).push(f)}};
const ctx={window:win,document:doc,location:{pathname:'/',search:'',href:'http://h/',origin:'http://h'},
 setTimeout(f,ms){timers.push([f,ms]);return timers.length},Date,URL,String};
win.window=win;win.document=doc;vm.createContext(ctx);vm.runInContext(code,ctx);
const out={};
(async()=>{
 const b=mkBtn('Go');listeners.click.forEach(f=>f({target:b}));
 const p=win.fetch('/x',{method:'POST'});
 out.during=[b.disabled,b.textContent];
 resolve({});await p;await Promise.resolve();await Promise.resolve();
 out.after=[b.disabled,b.textContent,'data-rf-busy' in b.attrs];
 const c=mkBtn('Run');listeners.click.forEach(f=>f({target:c}));
 const q=win.fetch('/x',{method:'POST'});reject(new Error('x'));await q.catch(()=>{});
 await Promise.resolve();await Promise.resolve();out.err=[c.disabled,c.textContent];
 const d=mkBtn('Slow');listeners.click.forEach(f=>f({target:d}));win.fetch('/x',{method:'POST'});
 const t=timers.filter(x=>x[1]===120000).pop();out.timeout=!!t;t[0]();out.slow=[d.disabled,d.textContent];
 const g=mkBtn('Get');listeners.click.forEach(f=>f({target:g}));win.fetch('/x');out.get=g.disabled;
 const e=mkBtn('Off');e.disabled=true;win.factoryBusy(e,new Promise(r=>r()));await Promise.resolve();await Promise.resolve();
 out.off=e.disabled;
 console.log(JSON.stringify(out));
})();
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_fetch_wrapper_marks_restores_and_times_out(tmp_path: Path) -> None:
    h = tmp_path / "h.js"
    h.write_text(_HARNESS)
    run = subprocess.run(
        ["node", str(h), CHROME_JS], capture_output=True, text=True, timeout=30, check=True
    )
    out = json.loads(run.stdout)
    assert out["during"] == [True, "Go…"]
    assert out["after"] == [False, "Go", False]
    assert out["err"] == [False, "Run"]
    assert out["timeout"] and out["slow"] == [False, "Slow"]
    assert out["get"] is False
    assert out["off"] is True

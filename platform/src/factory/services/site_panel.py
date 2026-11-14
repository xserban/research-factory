# ruff: noqa: E501
"""The paper side panel shared by every product page: clicking a paper title opens the explorer's
detail pane in a slide-over instead of leaving the page.

Invariants:
- Pure strings: nothing is read or written here and no model is called; imports nothing.
- The panel is one iframe on `<explorer>/index.html#open=<slug>&panel=1`, created on first use and
  reused (only its hash changes, the explorer reacts to `hashchange`).
- Intercepted: an `<a>` whose href contains `explorer/index.html#open=`, and any element with
  `data-work="<slug>"`. Ctrl, cmd, shift and middle clicks navigate as usual.
- `window.factoryPanel.open(slug, element)` opens the panel from page code (a canvas click).
- A "Loading…" marker (`.rfp-ld`) shows from a src change until the iframe's `load`.
- The script does nothing inside the explorer itself.
- Colours come from CSS variables of the host page (with a fallback inside `var()`), except the
  overlay's translucent black.
"""

from __future__ import annotations

from typing import Final

_MARK: Final = "<!--rf-panel-->"

PANEL_CSS: Final = (
    ".rfp-ov{position:fixed;inset:0;background:rgba(0,0,0,.45);opacity:0;visibility:hidden;"
    "transition:opacity .15s;z-index:2000}.rfp-ov.open{opacity:1;visibility:visible}"
    ".rfp{position:fixed;top:0;right:0;bottom:0;width:46%;min-width:420px;max-width:100vw;"
    "background:var(--bg,#fff);color:var(--fg,var(--ink,#222));"
    "border-left:1px solid var(--line,var(--mut,#888));box-shadow:-6px 0 24px rgba(0,0,0,.35);"
    "transform:translateX(100%);visibility:hidden;transition:transform .18s,visibility .18s;"
    "z-index:2001;display:flex;flex-direction:column}"
    ".rfp.open{transform:none;visibility:visible}"
    ".rfp-x{position:absolute;top:6px;right:10px;z-index:1;font:inherit;line-height:1;"
    "padding:3px 9px;cursor:pointer;background:var(--card,var(--panel,var(--bg,#fff)));"
    "color:var(--fg,var(--ink,#222));border:1px solid var(--line,var(--mut,#888));"
    "border-radius:6px}"
    ".rfp-ld{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:var(--mut,#888);"
    "font-size:14px;pointer-events:none}.rfp-ld[hidden]{display:none}"
    ".rfp-ld:before{content:'';display:inline-block;width:12px;height:12px;margin-right:8px;"
    "border:2px solid currentColor;border-right-color:transparent;border-radius:50%;"
    "vertical-align:-2px;animation:rfp-spin .8s linear infinite}@keyframes rfp-spin{to{transform:rotate(360deg)}}"
    "@media (prefers-reduced-motion:reduce){.rfp-ld:before{animation:none}}"
    ".rfp iframe{flex:1;width:100%;border:0;background:var(--bg,#fff)}"
    "@media (max-width:700px){.rfp{width:100%;min-width:0}}"
)

PANEL_JS: Final = (
    "<script>(function(){var P=location.pathname;"
    "if(/\\/explorer\\/index\\.html$/.test(P)||window.__rfPanel)return;window.__rfPanel=1;"
    "var DEF='../explorer/index.html',ov,box,fr,xb,ld,from=null;"
    "function build(){ov=document.createElement('div');ov.className='rfp-ov';"
    "box=document.createElement('div');box.className='rfp';box.setAttribute('role','dialog');"
    "box.setAttribute('aria-modal','true');box.setAttribute('aria-label','Paper detail');"
    "box.setAttribute('aria-hidden','true');"
    "xb=document.createElement('button');xb.className='rfp-x';xb.type='button';"
    "xb.setAttribute('aria-label','Close');xb.textContent='\\u00d7';"
    "fr=document.createElement('iframe');fr.title='Paper detail';"
    "ld=document.createElement('div');ld.className='rfp-ld';ld.textContent='Loading\u2026';ld.hidden=true;"
    "fr.addEventListener('load',function(){ld.hidden=true;});"
    "box.appendChild(xb);box.appendChild(ld);box.appendChild(fr);"
    "document.body.appendChild(ov);document.body.appendChild(box);"
    "ov.addEventListener('click',close);xb.addEventListener('click',close);}"
    "function isOpen(){return !!box&&box.className.indexOf('open')>=0;}"
    "function open(base,slug,el){if(!box)build();from=el||null;"
    "var u=base+'#open='+encodeURIComponent(slug)+'&panel=1';"
    "if(fr.getAttribute('src')!==u){ld.hidden=false;fr.setAttribute('src',u);}"
    "ov.className='rfp-ov open';box.className='rfp open';box.setAttribute('aria-hidden','false');"
    "xb.focus();}"
    "function close(){if(!isOpen())return;ov.className='rfp-ov';box.className='rfp';"
    "box.setAttribute('aria-hidden','true');"
    "if(from&&from.focus)from.focus();from=null;}"
    "function plain(e){return e.button===0&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&!e.altKey;}"
    "function find(t){while(t&&t.nodeType===1){"
    "if(t.getAttribute&&t.getAttribute('data-work'))return t;"
    "if(t.tagName==='A'&&"
    "(t.getAttribute('href')||'').indexOf('explorer/index.html#open=')>=0)return t;"
    "t=t.parentNode;}return null;}"
    "document.addEventListener('click',function(e){if(e.defaultPrevented||!plain(e))return;"
    "var t=find(e.target);if(!t)return;var s=t.getAttribute('data-work'),b=DEF;"
    "if(!s){var h=t.getAttribute('href'),i=h.indexOf('#');b=h.slice(0,i);"
    "var m=/(?:^|[#&])open=([^&]*)/.exec(h.slice(i));if(!m)return;"
    "try{s=decodeURIComponent(m[1]);}catch(x){s=m[1];}}"
    "e.preventDefault();open(b,s,t);});"
    "document.addEventListener('keydown',function(e){"
    "if(e.key==='Escape'&&isOpen()){e.preventDefault();close();}});"
    "window.factoryPanel={open:function(slug,el){open(DEF,slug,el);}};"
    "addEventListener('message',function(e){"
    "if(e.origin===location.origin&&e.data==='rfp-close')close();});"
    "})();</script>"
)


def with_panel(doc: str) -> str:
    """`doc` with the panel styles before `</head>` and the script before `</body>`.

    Idempotent: a document that already carries the panel is returned unchanged. A document
    without those tags gets the styles and the script appended."""
    if _MARK in doc:
        return doc
    style = f"<style>{PANEL_CSS}</style>"
    if "</head>" in doc:
        doc = doc.replace("</head>", style + "</head>", 1)
        style = ""
    tail = f"{_MARK}{style}{PANEL_JS}"
    if "</body>" in doc:
        return doc.replace("</body>", tail + "</body>", 1)
    return doc + tail

"""The bibliography product: the included works as a sortable list and as BibTeX (plan site-hub).

Two tabs: a list of titles and years (sortable by title or year, newest first by default, with a
filter) and the full BibTeX with a copy button and a download link. Built from the platform's own
BibTeX export of the included works, so both views show the same entries.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from factory.services.context import Project

_ENTRY = re.compile(r"@\w+\{([^,\s]+),(.*?)\n\}", re.S)
_FIELD = re.compile(r"^\s*(\w+)\s*=\s*(\{.*\}|\S+)\s*,?\s*$", re.M)


def _unbrace(value: str) -> str:
    value = value.strip().rstrip(",")
    while value.startswith("{") and value.endswith("}"):
        value = value[1:-1]
    return re.sub(r"\s+", " ", value.replace("{", "").replace("}", "")).strip()


def parse_entries(bib: str) -> list[dict[str, str]]:
    """Key, title, year, first author and venue of each BibTeX entry."""
    out: list[dict[str, str]] = []
    for key, body in _ENTRY.findall(bib):
        fields = {m.group(1).lower(): m.group(2) for m in _FIELD.finditer(body)}
        author = _unbrace(fields.get("author", ""))
        first = re.split(r"\s+and\s+", author, maxsplit=1)[0] if author else ""
        out.append(
            {
                "key": key,
                "title": _unbrace(fields.get("title", "")) or key,
                "year": _unbrace(fields.get("year", "")),
                "author": first,
                "more": "et al." if " and " in author else "",
                "venue": _unbrace(fields.get("howpublished", fields.get("journal", ""))),
            }
        )
    return out


_CSS = (
    ".tabs{display:flex;gap:4px;border-bottom:1px solid var(--mut);margin:14px 0}"
    ".tabs button{background:none;border:0;border-bottom:2px solid transparent;color:var(--dim);"
    "padding:8px 14px;font:inherit;cursor:pointer}.tabs button:hover{color:var(--fg)}"
    ".tabs button.on{color:var(--fg);border-bottom-color:var(--ac)}"
    ".bar{display:flex;gap:10px;align-items:center;margin:0 0 10px}"
    ".bar input{background:var(--lt);color:var(--fg);border:1px solid var(--mut);"
    "border-radius:6px;padding:5px 10px;font:inherit;width:280px}"
    ".bar button,a.btn{background:var(--lt);color:var(--fg);border:1px solid var(--mut);"
    "border-radius:6px;padding:4px 12px;font:inherit;cursor:pointer}"
    ".bar button:hover,a.btn:hover{border-color:var(--blue);color:var(--ac)}"
    "table{border-collapse:collapse;width:100%}td,th{padding:6px 10px;"
    "border-bottom:1px solid var(--mut);text-align:left;vertical-align:top}"
    "th{color:var(--dim);font-weight:600;font-size:12px;letter-spacing:.06em;"
    "text-transform:uppercase;cursor:pointer;user-select:none;position:sticky;top:0;"
    "background:var(--bg);white-space:nowrap}th:hover{color:var(--fg)}td.y{width:64px;font-variant-numeric:"
    "tabular-nums}td.k{color:var(--dim);font-size:12px;font-family:ui-monospace,monospace}"
    "pre{white-space:pre-wrap;word-break:break-word;background:var(--lt);"
    "border:1px solid var(--mut);border-radius:8px;padding:12px;font-size:12px}"
    "[hidden]{display:none!important}"
)

_JS = """
const D=JSON.parse(document.getElementById('d').textContent);let sortBy='year',dir=-1,q='';
const tb=document.getElementById('tb'),cnt=document.getElementById('cnt');
const E=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function draw(){const rows=D.filter(r=>!q||(r.title+' '+r.author+' '+r.year+' '+r.venue).toLowerCase().includes(q))
 .sort((a,b)=>sortBy==='year'?dir*((+a.year||0)-(+b.year||0))||a.title.localeCompare(b.title):dir*a.title.localeCompare(b.title));
 tb.innerHTML=rows.map(r=>'<tr><td class=y>'+E(r.year)+'</td><td>'+(r.slug?'<a href="../explorer/index.html#open='+r.slug+'">'+E(r.title)+'</a>':E(r.title))+'</td><td>'+E(r.author)+(r.more?' '+r.more:'')+'</td><td class=k>'+E(r.key)+'</td></tr>').join('');
 cnt.textContent=rows.length+' of '+D.length+' works';
 document.getElementById('hy').textContent='Year'+(sortBy==='year'?(dir<0?' ↓':' ↑'):'');
 document.getElementById('ht').textContent='Title'+(sortBy==='title'?(dir<0?' ↓':' ↑'):'');}
function sort(k){if(sortBy===k)dir=-dir;else{sortBy=k;dir=k==='year'?-1:1;}draw();}
document.getElementById('hy').onclick=()=>sort('year');document.getElementById('ht').onclick=()=>sort('title');
document.getElementById('q').oninput=e=>{q=e.target.value.toLowerCase();draw();};
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{
 document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('on',x===b));
 document.getElementById('list').hidden=b.dataset.t!=='list';document.getElementById('bib').hidden=b.dataset.t!=='bib';});
document.getElementById('copy').onclick=async e=>{try{await navigator.clipboard.writeText(document.getElementById('raw').textContent);
 e.target.textContent='Copied';setTimeout(()=>e.target.textContent='Copy BibTeX',1500);}catch(x){e.target.textContent='Select and copy';}};
draw();
"""  # noqa: E501


def build_bibliography(project: Project, out: Path) -> None:
    from factory.services.exports import export_bibliography
    from factory.services.site import page

    bib = "".join(export_bibliography(project, "bibtex"))
    (out / "references.bib").write_text(bib, encoding="utf-8")
    entries = parse_entries(bib)
    from factory.services.site_corpus import corpus_payload

    # a BibTeX key is the work's file-safe name without its hash suffix
    by_key = {w["slug"].rsplit("-", 1)[0]: w["slug"] for w in corpus_payload(project)["works"]}
    for e in entries:
        e["slug"] = by_key.get(e["key"], "")
    data = json.dumps(entries, ensure_ascii=False).replace("</", "<\\/")
    body = (
        "<h1>Bibliography</h1><p class=dim>The included works of the review: "
        f"{len(entries)} entries.</p>"
        "<p class=dim>The <b>List</b> tab is for reading and sorting: click a title to open the "
        "paper in the explorer (summary, quotes, original); click the Year or Title header to "
        "sort; the filter searches titles, authors and years. The <b>BibTeX</b> tab is the same "
        "list as BibTeX, for a reference manager: copy it or download the file. The keys are "
        "stable names made from the first author, year and title.</p>"
        "<div class=tabs><button class=on data-t=list>List</button>"
        "<button data-t=bib>BibTeX</button></div>"
        "<div id=list><div class=bar><input id=q placeholder='Filter by title, author, year…'>"
        "<span class=dim id=cnt></span></div>"
        "<table><thead><tr><th id=hy>Year</th><th id=ht>Title</th><th>First author</th>"
        "<th>Key</th></tr></thead><tbody id=tb></tbody></table></div>"
        "<div id=bib hidden><div class=bar><button id=copy>Copy BibTeX</button>"
        "<a class=btn href='references.bib' download>Download .bib</a></div>"
        f"<pre id=raw>{html.escape(bib)}</pre></div>"
        f"<script id=d type='application/json'>{data}</script><script>{_JS}</script>"
    )
    (out / "index.html").write_text(page("Bibliography", body, _CSS), encoding="utf-8")

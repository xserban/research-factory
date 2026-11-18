# ruff: noqa: E501
"""The conversion inspector: for each converted document, the original beside the extracted Markdown
(plan site-hub; the researcher asked that a low conversion score lead to the two texts).

One page per document (`doc/<slug>.html`), whatever the format:

- **original**: a PDF in the browser's viewer, an HTML page in a sandboxed frame, a LaTeX source
  archive as a listing of its files with the converted text beside it;
- **extracted**: the stored Markdown, rendered, with a link to the raw file;
- **gaps** (where the coverage is below the triage threshold): runs of words of the original that
  the Markdown does not contain (possible lost text) and runs of the Markdown that the original does
  not contain (possible added or scrambled text), by word 5-grams, each with its position;
- **actions**: the exact commands to convert the document again with another converter that accepts
  its format, and to read the converted text.

A mechanical aid: the gaps rank what to look at; a person decides. Nothing here writes an event.
"""

from __future__ import annotations

import html
import json
import os
import re
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from sqlalchemy import text

from factory.document.optional import converter_infos
from factory.services import conversion_coverage as cov
from factory.services.context import Project
from factory.services.site_charts import scatter
from factory.services.site_corpus import library_file, slug_of
from factory.services.site_synthesis import markdown_to_html
from factory.services.site_widgets import REPORT_CSS, esc

_ANCHOR = re.compile(r'<a id="([^"]+)"></a>\s*')
"""The converter's anchor markers; shown as a small label of the anchor."""
GAP_BELOW = 0.9
"""Gaps are listed for a document whose recall or precision is below this."""
MIN_RUN = 6
MAX_RUNS = 30
MAX_SHOWN = 240
EXT = {"application/pdf": "pdf", "text/html": "html", "application/x-eprint-tar": "tar"}


@dataclass(frozen=True)
class Doc:
    document_id: str
    work_id: str
    converter: str
    media_type: str
    raw_hash: str
    markdown_hash: str
    title: str
    recall: float | None
    precision: float | None
    source_words: int | None
    markdown_words: int | None

    @property
    def slug(self) -> str:
        return slug_of(self.work_id)

    @property
    def ext(self) -> str:
        return EXT.get(self.media_type, "bin")


def documents(project: Project, report: cov.CoverageReport) -> list[Doc]:
    """Every converted live document with its coverage figures (None where not measured)."""
    measured = {r.document_id: r for r in report.rows}
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT c.document_id, d.work_id, c.converter, d.media_type, d.raw_hash, "
                "c.markdown_hash, w.data FROM document_conversions c "
                "JOIN fulltext_documents d ON d.document_id = c.document_id "
                "LEFT JOIN works w ON w.work_id = d.work_id "
                "WHERE d.superseded_by IS NULL ORDER BY d.work_id"
            )
        ).all()
    out: list[Doc] = []
    for did, wid, conv, media, raw, md, data in found:
        title = str(json.loads(data).get("title") or wid) if data else str(wid)
        m = measured.get(str(did))
        out.append(
            Doc(
                str(did),
                str(wid),
                str(conv),
                str(media),
                str(raw),
                str(md),
                title,
                m.recall if m else None,
                m.precision if m else None,
                m.source_words if m else None,
                m.markdown_words if m else None,
            )
        )
    return out


def _runs(
    tokens: list[tuple[str, str]], other_grams: set[tuple[str, ...]]
) -> list[tuple[int, str]]:
    """Runs of tokens whose 5-grams are all absent from `other_grams`: (position, text)."""
    words = [t[0] for t in tokens]
    covered = [False] * len(words)
    for i in range(len(words) - cov.GRAM + 1):
        if tuple(words[i : i + cov.GRAM]) in other_grams:
            for j in range(i, i + cov.GRAM):
                covered[j] = True
    runs: list[tuple[int, str]] = []
    i = 0
    while i < len(words):
        if covered[i]:
            i += 1
            continue
        j = i
        while j < len(words) and not covered[j]:
            j += 1
        if j - i >= MIN_RUN:
            runs.append((i, " ".join(t[1] for t in tokens[i:j])))
        i = j
    return runs


def _tokens(value: str) -> list[tuple[str, str]]:
    return [(m.group(0).lower(), m.group(0)) for m in cov._WORD.finditer(value)]


def gaps(
    d: Doc, markdown: str, source: str | None
) -> tuple[list[tuple[int, str]], list[tuple[int, str]], int, int]:
    """(lost, added, source token count, markdown token count) of one document."""
    if source is None:
        return [], [], 0, 0
    src_tok = _tokens(source)
    md_tok = _tokens(cov._TAG.sub(" ", markdown))
    src_grams = {
        tuple(t[0] for t in src_tok[i : i + cov.GRAM]) for i in range(len(src_tok) - cov.GRAM + 1)
    }
    md_grams = {
        tuple(t[0] for t in md_tok[i : i + cov.GRAM]) for i in range(len(md_tok) - cov.GRAM + 1)
    }
    return _runs(src_tok, md_grams), _runs(md_tok, src_grams), len(src_tok), len(md_tok)


def _list(runs: list[tuple[int, str]], total: int, empty: str) -> str:
    if not runs:
        return f"<p class=dim>{esc(empty)}</p>"
    longest = sorted(runs, key=lambda r: -len(r[1]))[:MAX_RUNS]
    items = "".join(
        f"<li><span class=dim>{100 * pos // max(total, 1)}% through, "
        f"{len(txt.split())} words</span><br>{esc(txt[:MAX_SHOWN])}{'…' if len(txt) > MAX_SHOWN else ''}</li>"
        for pos, txt in sorted(longest)
    )
    more = f"<p class=dim>{len(runs)} run(s) in all; the {len(longest)} longest are shown.</p>"
    return f"{more}<ol class=gaps>{items}</ol>"


def _original_pane(d: Doc, source: str | None, tar_listing: str) -> str:
    src = f"../files/{d.slug}.{d.ext}"
    if d.ext == "tar":
        return (
            "<div class='pane box'><p>A LaTeX source archive has no page to show. "
            f"<a href='{src}'>Download {esc(d.slug)}.{d.ext}</a>.</p>{tar_listing}</div>"
        )
    sandbox = "" if d.ext == "pdf" else " sandbox"
    view = f"<iframe class=pane{sandbox} src='{src}{'#view=FitH' if d.ext == 'pdf' else ''}' title='original'></iframe>"
    body = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+\n", "\n", source or "")).strip()
    text_pane = f"<pre class='pane box txt'>{esc(body) if body else 'No text layer.'}</pre>"
    first = "view" if d.ext == "pdf" else "text"
    return (
        "<div class=otabs>"
        f"<button data-o=view class='{'on' if first == 'view' else ''}'>Original view</button>"
        f"<button data-o=text class='{'on' if first == 'text' else ''}'>Original text</button></div>"
        f"<div id=o-view{' hidden' if first != 'view' else ''}>{view}</div>"
        f"<div id=o-text{' hidden' if first != 'text' else ''}>{text_pane}</div>"
        "<script>document.querySelectorAll('.otabs button').forEach(b=>b.onclick=()=>{"
        "document.querySelectorAll('.otabs button').forEach(x=>x.classList.toggle('on',x===b));"
        "document.getElementById('o-view').hidden=b.dataset.o!=='view';"
        "document.getElementById('o-text').hidden=b.dataset.o!=='text';});</script>"
    )


def _tar_listing(raw: bytes) -> str:
    try:
        with tarfile.open(fileobj=BytesIO(raw), mode="r:*") as tar:
            names = [m.name for m in tar.getmembers() if m.isfile()][:60]
    except (tarfile.TarError, OSError, EOFError):
        return "<p class=dim>The archive could not be listed.</p>"
    return (
        "<p class=dim>Files in the archive:</p><ul>"
        + "".join(f"<li class=mono>{esc(n)}</li>" for n in names)
        + "</ul>"
    )


def _actions(project: Project, d: Doc) -> str:
    slug = project.paths.slug
    others = [
        i
        for i in converter_infos()
        if d.media_type in i.accepts and i.name != d.converter and i.available
    ]
    cmds = [
        f"factory --project {slug} document convert --work {d.work_id} --converter {i.name}"
        for i in others
    ]
    if not others:
        cmds.insert(0, f"factory --project {slug} document converters")
    cmds.append(f"factory --project {slug} document read {d.work_id} --document {d.document_id}")
    block = "".join(
        f'<div class=cmd><code>{esc(c)}</code><button onclick="navigator.clipboard.writeText(this.dataset.c)" data-c="{esc(c)}">Copy</button></div>'
        for c in cmds
    )
    note = f"Converted with <b>{esc(d.converter)}</b>. " + (
        "Other converter(s) that accept this format and run here: "
        + ", ".join(f"<b>{esc(i.name)}</b>" for i in others)
        + ". Converting again adds a second conversion beside this one; then compare."
        if others
        else "No other converter that accepts this format runs here. An optional converter can "
        "be installed (see the first command below) and then used with --converter."
    )
    return f"<p class=dim>{note}</p>{block}"


_CSS = (
    REPORT_CSS + "body{max-width:none}.top{display:flex;flex-wrap:wrap;gap:10px;align-items:center}"
    ".top h1{font-size:18px;margin:0}.btn{background:var(--lt);color:var(--fg);border:1px solid var(--mut);"
    "border-radius:6px;padding:3px 12px;font-size:13px}.btn:hover{border-color:var(--blue);color:var(--ac)}"
    ".split{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:12px 0}"
    ".pane{width:100%;height:78vh;border:1px solid var(--mut);border-radius:8px;background:#fff}"
    ".box{background:var(--lt);padding:12px;overflow:auto;color:var(--fg)}"
    ".md{height:78vh;overflow:auto;border:1px solid var(--mut);border-radius:8px;background:var(--lt);"
    "padding:4px 16px}.md h1{font-size:19px}.md h2{font-size:16px;border:0;margin:16px 0 4px;"
    "text-transform:none;letter-spacing:0;color:var(--fg)}.md p{max-width:80ch}"
    ".cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}.gaps li{margin:0 0 10px;font-size:13px}"
    ".cmd{display:flex;gap:8px;align-items:center;margin:4px 0}.cmd code{background:var(--lt);"
    "border:1px solid var(--mut);border-radius:6px;padding:3px 8px;font-size:12px;flex:1;"
    "overflow-x:auto;white-space:nowrap}.cmd button{background:var(--lt);color:var(--fg);"
    "border:1px solid var(--mut);border-radius:6px;padding:2px 10px;cursor:pointer}"
    ".mono{font-family:ui-monospace,monospace;font-size:12px}.pill{border:1px solid var(--mut);"
    "border-radius:10px;padding:0 8px;font-size:12px;color:var(--dim)}"
    ".otabs{display:flex;gap:4px;margin:0 0 6px}.otabs button{background:var(--lt);color:var(--dim);"
    "border:1px solid var(--mut);border-radius:6px;padding:3px 12px;cursor:pointer;font:inherit}"
    ".otabs button.on{color:var(--fg);border-color:var(--ac)}.txt{white-space:pre-wrap;"
    "word-break:break-word;font-size:12.5px;line-height:1.5;margin:0;border-radius:8px}"
    "[hidden]{display:none!important}"
    ".bad{color:var(--amber)}@media (max-width:900px){.split,.cols{grid-template-columns:1fr}}"
)


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.3f}"


def write_document_page(project: Project, d: Doc, out: Path) -> None:
    from factory.services.site import page

    markdown = project.library.get(d.markdown_hash).decode("utf-8", errors="replace")
    low = (d.recall is not None and d.recall < GAP_BELOW) or (
        d.precision is not None and d.precision < GAP_BELOW
    )
    lost: list[tuple[int, str]] = []
    added: list[tuple[int, str]] = []
    n_src = n_md = 0
    source: str | None = None
    tar_listing = ""
    if d.ext == "tar":
        tar_listing = _tar_listing(project.library.get(d.raw_hash))
    else:
        source = cov._source_text(d.media_type, project.library.get(d.raw_hash))
    if low:
        lost, added, n_src, n_md = gaps(d, markdown, source)
    score = ""
    if d.recall is not None:
        cls_r = " bad" if d.recall < cov.LOW else ""
        cls_p = " bad" if (d.precision or 0) < cov.LOW else ""
        score = (
            f"<span class='pill{cls_r}'>recall {_fmt(d.recall)}</span> "
            f"<span class='pill{cls_p}'>precision {_fmt(d.precision)}</span> "
            f"<span class=pill>{d.source_words} → {d.markdown_words} words</span>"
        )
    else:
        score = "<span class=pill>not measured (no comparable plain text)</span>"
    gap_block = ""
    if low:
        gap_block = (
            "<div class=cols><div><h2>In the original, not found in the Markdown</h2>"
            + _list(lost, n_src, "No run of 6 or more words is missing.")
            + "</div><div><h2>In the Markdown, not found in the original</h2>"
            + _list(added, n_md, "No run of 6 or more words is extra.")
            + "</div></div>"
        )
    rendered = markdown_to_html(_ANCHOR.sub("\u27e8\\1\u27e9 ", markdown), {})
    body = (
        "<div class=top><a class=btn href='../index.html'>← all documents</a>"
        f"<h1>{esc(d.title[:140])}</h1></div>"
        f"<p>{score} <a class=btn href='../files/{d.slug}.{d.ext}' target=_blank>Open original</a> "
        f"<a class=btn href='../files/{d.slug}.md' target=_blank>Raw Markdown</a> "
        f"<a class=btn href='../../explorer/index.html#open={d.slug}' target=_blank>In the explorer</a></p>"
        "<div class=split><div><h2>Original (as downloaded)</h2>"
        f"{_original_pane(d, source, tar_listing)}</div>"
        f"<div><h2>Extracted Markdown ({esc(d.converter)})</h2><div class=md>"
        f"{rendered}</div></div></div>" + gap_block + "<h2>What to do</h2>" + _actions(project, d)
    )
    (out / "doc" / f"{d.slug}.html").write_text(page(d.title[:80], body, _CSS), encoding="utf-8")


def write_files(project: Project, d: Doc, out: Path) -> None:
    """Link the original under its own name and write the Markdown next to it."""
    files = out / "files"
    target = files / f"{d.slug}.{d.ext}"
    if target.is_symlink() or target.exists():
        target.unlink()
    os.symlink(library_file(project, d.raw_hash), target)
    (files / f"{d.slug}.md").write_bytes(project.library.get(d.markdown_hash))


_INDEX_JS = """
const D=JSON.parse(document.getElementById('d').textContent);let sortBy='recall',dir=1,q='',conv='',low=false;
const tb=document.getElementById('tb'),cnt=document.getElementById('cnt');
const E=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const num=v=>v===null?9:v;
function draw(){const rows=D.filter(r=>(!q||r.title.toLowerCase().includes(q))&&(!conv||r.converter===conv)&&(!low||(r.recall!==null&&(r.recall<0.8||r.precision<0.8))))
 .sort((a,b)=>{if(sortBy==='title')return dir*a.title.localeCompare(b.title);if(sortBy==='words')return dir*((a.words||0)-(b.words||0));return dir*(num(a[sortBy])-num(b[sortBy]));});
 tb.innerHTML=rows.map(r=>'<tr><td class=n'+(r.recall!==null&&r.recall<0.8?' bad':'')+'>'+(r.recall===null?'n/a':r.recall.toFixed(3))+'</td><td class=n'+(r.precision!==null&&r.precision<0.8?' bad':'')+'>'+(r.precision===null?'n/a':r.precision.toFixed(3))+'</td><td class=n>'+(r.words||'')+'</td><td>'+E(r.converter)+'</td><td><a href="doc/'+r.slug+'.html">'+E(r.title.slice(0,110))+'</a></td></tr>').join('');
 cnt.textContent=rows.length+' of '+D.length+' documents';}
function sort(k){if(sortBy===k)dir=-dir;else{sortBy=k;dir=1;}draw();}
for(const k of ['recall','precision','words','title'])document.getElementById('h-'+k).onclick=()=>sort(k);
document.getElementById('q').oninput=e=>{q=e.target.value.toLowerCase();draw();};
document.getElementById('conv').onchange=e=>{conv=e.target.value;draw();};
document.getElementById('low').onchange=e=>{low=e.target.checked;draw();};
draw();
"""


def build_index(
    project: Project, out: Path, docs: Sequence[Doc], report: cov.CoverageReport
) -> None:
    from factory.services.site import page

    rows = [
        {
            "slug": d.slug,
            "title": d.title,
            "converter": d.converter,
            "recall": d.recall,
            "precision": d.precision,
            "words": d.source_words,
        }
        for d in docs
    ]
    convs = sorted({d.converter for d in docs})
    by: dict[str, list[Doc]] = {}
    for d in docs:
        if d.recall is not None:
            by.setdefault(d.converter, []).append(d)
    summary = ""
    for conv, ds in sorted(by.items()):
        rec = sorted(x.recall or 0 for x in ds)
        pre = sorted(x.precision or 0 for x in ds)
        low_r = sum(1 for x in ds if (x.recall or 0) < cov.LOW)
        low_p = sum(1 for x in ds if (x.precision or 0) < cov.LOW)
        summary += (
            f"<tr><td>{esc(conv)}</td><td class=n>{len(ds)}</td><td class=n>{rec[len(rec) // 2]:.3f}</td>"
            f"<td class=n>{pre[len(pre) // 2]:.3f}</td><td class=n>{low_r}</td><td class=n>{low_p}</td></tr>"
        )
    unmeasured = "".join(f"<li>{esc(k)}: {v}</li>" for k, v in report.not_measured.items())
    classes = ["mk", "c2", "c3"]
    legend = {c: classes[i % 3] for i, c in enumerate(convs)}
    scatter_svg = scatter(
        [
            (
                d.recall or 0,
                d.precision or 0,
                legend.get(d.converter, "mk"),
                f"doc/{d.slug}.html",
                f"{d.title[:70]}: recall {d.recall:.3f}, precision {d.precision:.3f}",
            )
            for d in docs
            if d.recall is not None
        ],
        "recall (share of the original found in the Markdown)",
        "precision",
    )
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    options = "".join(f"<option>{esc(c)}</option>" for c in convs)
    body = (
        "<h1>Conversion coverage</h1>"
        "<div class=note>Word 5-gram comparison of each original with its Markdown (computed "
        f"{esc(report.computed_at)}). Recall: the share of the original found in the Markdown. "
        "Precision: the share of the Markdown found in the original. Both are noisy (running "
        "headers, numbered lines); they rank documents for a person to check and decide nothing. "
        f"Low is below {cov.LOW}. <b>Click a document</b> to see the original beside the "
        "extracted text, where text was lost, and how to convert it again.</div>"
        "<table><tr><th>converter</th><th>documents</th><th>median recall</th>"
        f"<th>median precision</th><th>low recall</th><th>low precision</th></tr>{summary}</table>"
        + "<h2>Every document: recall against precision</h2>"
        "<p class=dim>One mark per document. The dashed box is the low region (below 0.8 on either "
        "axis). Click a mark to open that document beside its extracted text. "
        + " ".join(
            f"<span class='{c}' style='color:inherit'>■ {esc(n)}</span>" for n, c in legend.items()
        )
        + "</p>"
        + scatter_svg
        + (f"<p class=dim>Not measured:</p><ul>{unmeasured}</ul>" if unmeasured else "")
        + "<div class=bar style='display:flex;gap:12px;align-items:center;margin:14px 0'>"
        "<input id=q placeholder='Filter by title…' style='background:var(--lt);color:var(--fg);"
        "border:1px solid var(--mut);border-radius:6px;padding:5px 10px;width:260px'>"
        f"<select id=conv><option value=''>all converters</option>{options}</select>"
        "<label><input type=checkbox id=low> only low (below 0.8)</label>"
        "<span class=dim id=cnt></span></div>"
        "<table><thead><tr><th id=h-recall style='cursor:pointer'>recall ↑</th>"
        "<th id=h-precision style='cursor:pointer'>precision</th>"
        "<th id=h-words style='cursor:pointer'>words</th><th>converter</th>"
        "<th id=h-title style='cursor:pointer'>document</th></tr></thead><tbody id=tb></tbody></table>"
        f"<script id=d type='application/json'>{data}</script><script>{_INDEX_JS}</script>"
    )
    (out / "index.html").write_text(page("Conversion coverage", body, _CSS), encoding="utf-8")


def build_conversion_index(project: Project, out: Path) -> None:
    """The conversion list only (lazy build, IDEA-96): the served hub renders each document's
    page and files on request (`render_conversion_item`)."""
    report = cov.cached(project) or cov.refresh(project)
    (out / "doc").mkdir(parents=True, exist_ok=True)
    (out / "files").mkdir(parents=True, exist_ok=True)
    build_index(project, out, documents(project, report), report)


def render_conversion_item(project: Project, rel: str, out: Path) -> bool:
    """Write the one item `rel` names (`doc/<slug>.html`, `files/<slug>.md` or the original
    `files/<slug>.<ext>`) under `out`, as the full build would; False when no document has it."""
    folder, _, name = rel.partition("/")
    if folder not in ("doc", "files") or "/" in name:
        return False
    report = cov.cached(project) or cov.refresh(project)
    for d in documents(project, report):
        if folder == "doc" and name == f"{d.slug}.html":
            (out / "doc").mkdir(parents=True, exist_ok=True)
            write_document_page(project, d, out)
            return True
        if folder == "files" and name in (f"{d.slug}.md", f"{d.slug}.{d.ext}"):
            (out / "files").mkdir(parents=True, exist_ok=True)
            write_files(project, d, out)
            return True
    return False


def build_conversion_site(project: Project, out: Path) -> None:
    """The conversion product: the list and one inspector page per converted document."""
    report = cov.cached(project) or cov.refresh(project)
    docs = documents(project, report)
    (out / "doc").mkdir(parents=True, exist_ok=True)
    (out / "files").mkdir(parents=True, exist_ok=True)
    for d in docs:
        try:
            write_files(project, d, out)
            write_document_page(project, d, out)
        except (OSError, ValueError):
            continue
    build_index(project, out, docs, report)


__all__ = [
    "Doc",
    "build_conversion_index",
    "build_conversion_site",
    "documents",
    "gaps",
    "html",
    "render_conversion_item",
]

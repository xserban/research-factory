"""Small HTML pieces shared by the report products of the site (bars, tables, sections).

Every function escapes its text. The look is the site's theme (`site.THEME_CSS`).
"""

from __future__ import annotations

import html
from collections import Counter
from collections.abc import Callable, Iterable, Sequence

from factory.services.site_charts import CHART_CSS

REPORT_CSS = CHART_CSS + (
    "table{border-collapse:collapse;margin:4px 0 16px;width:100%;font-size:12.5px}"
    "td,th{padding:5px 10px;border-bottom:1px solid var(--mut);text-align:left;vertical-align:top}"
    "th{color:var(--dim);font-weight:600;font-size:10.5px;letter-spacing:.14em;"
    "text-transform:uppercase;position:sticky;top:0;background:var(--dk);"
    "border-bottom:1px solid var(--ac)}"
    "tr:hover td{background:var(--hov)}"
    "td.n{text-align:right;font-variant-numeric:tabular-nums;width:56px;color:var(--ac)}"
    "td.bar{width:42%}.bar i{display:block;height:10px;min-width:3px;"
    "background:repeating-linear-gradient(90deg,var(--ac) 0 6px,transparent 6px 8px)}"
    "h2{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--light);"
    "margin:30px 0 8px;padding:0 0 6px;border-bottom:1px solid var(--mut)}"
    "h2::before{content:'▮';color:var(--ac);margin-right:9px}"
    "h3{font-size:12.5px;margin:16px 0 4px;letter-spacing:.06em;color:var(--fg)}"
    ".grid td{text-align:center;min-width:34px}"
    ".grid th:first-child,.grid td:first-child{text-align:left}"
    "small{color:var(--dim);font-weight:400}"
    ".note{background:var(--card);border:1px solid var(--mut);"
    "border-left:3px solid var(--ac);"
    "padding:10px 14px;color:var(--light);margin:8px 0;line-height:1.6}"
    ".good{color:var(--ac)}.warn{color:var(--amber)}"
    "tr.clk{cursor:pointer}tr.clk:hover td{background:var(--hov)}td a{color:var(--blue)}"
)


def esc(value: object) -> str:
    return html.escape(str(value))


def bars(
    counter: Counter[str],
    total: int | None = None,
    link: Callable[[str], str | None] | None = None,
) -> str:
    """A table of the counter's values, most common first, with a bar each. With `link`, a value
    that has a target is a link (the explorer filtered to that value)."""
    top = max(counter.values(), default=1)

    def label(k: str) -> str:
        href = link(k) if link else None
        return f"<a href='{html.escape(href, quote=True)}'>{esc(k)}</a>" if href else esc(k)

    rows = "".join(
        f"<tr><td>{label(k)}</td><td class=n>{v}</td>"
        f"<td class=bar><i style='width:{100 * v / top:.0f}%'></i></td></tr>"
        for k, v in counter.most_common()
    )
    return f"<table>{rows}</table>"


def table(headers: Sequence[str], rows: Iterable[Sequence[object]], css: str = "") -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table class='{css}'><tr>{head}</tr>{body}</table>"


def heat_grid(
    rows: Sequence[str],
    cols: Sequence[str],
    cell: dict[tuple[str, str], int],
    corner: str = "",
    link: Callable[[str, str], str | None] | None = None,
) -> str:
    """A table of counts with a tint by value. With `link`, a non-empty cell is a link."""
    top = max(cell.values(), default=1)
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = ""
    for r in rows:
        tds = ""
        for c in cols:
            n = cell.get((r, c), 0)
            pct = 100 * (0.08 + 0.7 * n / top)
            mix = f"color-mix(in srgb,var(--heat) {pct:.0f}%,transparent)"
            style = f" style='background:{mix}'" if n else ""
            href = link(r, c) if link and n else None
            inner = f"<a href='{html.escape(href, quote=True)}'>{n}</a>" if href else f"{n or ''}"
            tds += f"<td{style}>{inner}</td>"
        body += f"<tr><td>{esc(r)}</td>{tds}</tr>"
    return f"<table class=grid><tr><th>{esc(corner)}</th>{head}</tr>{body}</table>"


def section(title: str, body: str) -> str:
    return f"<h2>{esc(title)}</h2>{body}"


def note(text: str) -> str:
    return f"<div class=note>{esc(text)}</div>"


FUTURE_CSS = (
    "*{border-radius:0!important}"
    "body{background-image:linear-gradient(rgba(130,251,156,.035) 1px,transparent 1px),"
    "linear-gradient(90deg,rgba(130,251,156,.035) 1px,transparent 1px);background-size:28px 28px}"
    "button{background:transparent;color:var(--ac);"
    "border:1px solid color-mix(in srgb,var(--ac) 45%,transparent);"
    "font-family:ui-monospace,'JetBrains Mono',monospace;font-weight:600;font-size:11px;"
    "letter-spacing:.1em;text-transform:uppercase;cursor:pointer}"
    "button:hover{background:var(--ac);color:var(--bg)}"
    "button.on{background:var(--ac);color:var(--bg)}"
    "h1,h2,h3,th,header{font-family:ui-monospace,'JetBrains Mono',monospace}"
    "th{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase}"
)
"""Square, grid-backed overlay for the pages that carry their own stylesheet (the explorer and the
dashboard), so every surface of the factory shares one look."""


def link_table(
    headers: Sequence[str], rows: Iterable[tuple[Sequence[object], str | None]], css: str = ""
) -> str:
    """A table whose rows are links: each row is (cells, href); a row with an href is clickable and
    its first cell is a link."""
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = ""
    for cells, href in rows:
        cs = list(cells)
        if href:
            h = html.escape(href, quote=True)
            first = f"<a href='{h}'>{esc(cs[0])}</a>"
            tds = f"<td>{first}</td>" + "".join(f"<td>{esc(c)}</td>" for c in cs[1:])
            body += f"<tr class=clk onclick=\"location.href='{h}'\">{tds}</tr>"
        else:
            body += "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in cs) + "</tr>"
    return f"<table class='{css}'><tr>{head}</tr>{body}</table>"

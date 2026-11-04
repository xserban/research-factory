"""Markdown and HTML renderings of the portfolio. Formatting only: every figure is read from the
`Portfolio` model, so no service is called here and the views cannot differ from the JSON.

Ages ("12 days ago") are computed from the `as_of` argument, never the wall clock, so the same model
and the same `as_of` give byte-identical output. The HTML is one document with inline CSS and no
script; every value passes through `html.escape`.
"""

from datetime import datetime
from html import escape

from factory.services.human_queue import HumanItem
from factory.services.portfolio import Portfolio, PortfolioRow

_HEADERS = (
    "Project",
    "Mode",
    "Stage",
    "Works",
    "TA included",
    "FT included",
    "Tasks open/claimed/expired",
    "Last search",
    "Waiting on you",
)
_NUMERIC = frozenset({3, 4, 5, 8})


def age(then: datetime | None, as_of: datetime) -> str:
    """`never`, `today`, `1 day ago` or `N days ago`, counted in whole days before `as_of`."""
    if then is None:
        return "never"
    days = (as_of - then).days
    if days < 1:
        return "today"
    return "1 day ago" if days == 1 else f"{days} days ago"


def waiting(row: PortfolioRow) -> int:
    """The number of pending human decisions of the row, over all its gates."""
    return sum(item.count for item in row.human.items)


def _cells(row: PortfolioRow, as_of: datetime) -> list[str]:
    if row.error is not None:
        return [row.slug, "n/a", f"error: {row.error}", "-", "-", "-", "-", "-", "-"]
    mode = "n/a" if row.rigor_mode is None else row.rigor_mode.value
    stage = "n/a" if row.stage is None else row.stage.value
    return [
        row.slug,
        mode,
        stage,
        str(row.works),
        str(row.ta_included),
        str(row.ft_included),
        f"{row.tasks_open}/{row.tasks_claimed}/{row.tasks_expired}",
        age(row.last_search_at, as_of),
        str(waiting(row)),
    ]


def _label(item: HumanItem) -> str:
    stage = "" if item.stage is None else f" ({item.stage})"
    return f"{item.gate.value}{stage}"


def _md(cell: str) -> str:
    return cell.replace("|", "\\|")


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def render_markdown(p: Portfolio, as_of: datetime) -> str:
    """The table, then the pending human decisions grouped by project."""
    lines = ["# Portfolio", "", f"As of {_stamp(as_of)}. {len(p.projects)} projects.", ""]
    lines.append("| " + " | ".join(_HEADERS) + " |")
    lines.append(
        "| " + " | ".join("---:" if i in _NUMERIC else "---" for i in range(len(_HEADERS))) + " |"
    )
    for row in p.projects:
        lines.append("| " + " | ".join(_md(c) for c in _cells(row, as_of)) + " |")
    lines.append("")
    waiting_rows = [row for row in p.projects if row.human.items]
    if not waiting_rows:
        lines.append("Nothing is waiting on you.")
        return "\n".join(lines) + "\n"
    lines += ["## Waiting on you", ""]
    for row in waiting_rows:
        lines += [f"### {row.slug}", ""]
        lines += [f"- {_label(i)}: {i.count}. `{i.command}`" for i in row.human.items]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


_CSS = """\
:root { --bg: #fbfbf9; --fg: #1d1d1b; --muted: #5f5f58; --line: #d9d9d2; --accent: #1f5fa8;
  --err: #a02c2c; --code: #efefe9; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161615; --fg: #ececE6; --muted: #a3a39a; --line: #3a3a36; --accent: #7fb0ea;
    --err: #ee8a8a; --code: #232321; }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 24px 16px; background: var(--bg); color: var(--fg);
  font: 15px/1.5 system-ui, sans-serif; }
main { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 4px; }
h2 { font-size: 1.15rem; margin: 28px 0 8px; }
h3 { font-size: 1rem; margin: 16px 0 4px; }
p.meta { color: var(--muted); margin: 0 0 16px; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line);
  white-space: nowrap; }
th { color: var(--muted); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
td.err { color: var(--err); }
code { background: var(--code); padding: 1px 5px; border-radius: 4px; font-size: 0.9em;
  word-break: break-word; }
ul { padding-left: 20px; margin: 4px 0; }
"""


def render_html(p: Portfolio, as_of: datetime) -> str:
    """One self-contained HTML document: inline CSS, light and dark, no script."""
    out = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Portfolio</title>",
        f"<style>\n{_CSS}</style>",
        "</head>",
        "<body>",
        "<main>",
        "<h1>Portfolio</h1>",
        f'<p class="meta">As of {escape(_stamp(as_of))}. {len(p.projects)} projects.</p>',
        '<div class="scroll"><table>',
        "<thead><tr>"
        + "".join(
            f'<th class="num">{escape(h)}</th>' if i in _NUMERIC else f"<th>{escape(h)}</th>"
            for i, h in enumerate(_HEADERS)
        )
        + "</tr></thead>",
        "<tbody>",
    ]
    for row in p.projects:
        cells = []
        for i, cell in enumerate(_cells(row, as_of)):
            css = "num" if i in _NUMERIC else ("err" if i == 2 and row.error else "")
            attr = f' class="{css}"' if css else ""
            cells.append(f"<td{attr}>{escape(cell)}</td>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out += ["</tbody>", "</table></div>"]
    waiting_rows = [row for row in p.projects if row.human.items]
    if not waiting_rows:
        out.append("<p>Nothing is waiting on you.</p>")
    else:
        out.append("<h2>Waiting on you</h2>")
        for row in waiting_rows:
            out.append(f"<h3>{escape(row.slug)}</h3>")
            out.append("<ul>")
            for item in row.human.items:
                out.append(
                    f"<li>{escape(_label(item))}: {item.count}. "
                    f"<code>{escape(item.command)}</code></li>"
                )
            out.append("</ul>")
    out += ["</main>", "</body>", "</html>"]
    return "\n".join(out) + "\n"

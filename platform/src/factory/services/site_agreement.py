# ruff: noqa: E501
"""The miner agreement product: how closely pass A and pass B of each listed miner agree (plan
site-hub, step 3).

Two measures side by side, both computed from the recorded rows, never typed:

- the **platform measure** (`mining.mine_status`): rows align on the row key, which for most miners
  includes where a quote sits, so a correct but differently quoted row counts as unmatched;
- the **fairer measure** (IDEA-53): rows align per work (one-row miners) or on an enum key
  (multi-row miners); enum values compare by value; a `*_secondary` label agrees when it equals the
  other pass's primary or secondary of that dimension, and a label given by one pass only is a
  completeness figure, not a disagreement; free text and quotes are not compared (listed for an
  equivalence judge, a later step).

Neither measure says which pass is right: that needs gold labels.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text

from factory.mining.spec import EnumKind, MinerSpec
from factory.services import mining as mining_service
from factory.services.context import Project
from factory.services.protocol import current_protocol
from factory.services.site_charts import hbars
from factory.services.site_corpus import slug_of
from factory.services.site_widgets import REPORT_CSS, esc, note, section, table

QUOTE_SUFFIX = "\x00q"
ANCHOR_SUFFIX = "\x00a"
"""Row dicts carry each field's quote and anchor under the field name plus these suffixes."""
MULTI_ROW_RATIO = 1.3
"""A miner with more than this many rows per work (pass A) is aligned on its enum row key."""
Rows = dict[str, list[dict[str, str]]]


@dataclass
class Measure:
    works_both: int = 0
    rows_a: int = 0
    rows_b: int = 0
    matched: int = 0
    total: collections.Counter[str] = field(default_factory=collections.Counter)
    agreed: collections.Counter[str] = field(default_factory=collections.Counter)
    one_sided: collections.Counter[str] = field(default_factory=collections.Counter)
    text_pairs: collections.Counter[str] = field(default_factory=collections.Counter)
    note: str = ""
    disagreements: list[dict[str, str]] = field(default_factory=list)

    def overall(self, primary_only: bool = False) -> tuple[int, int]:
        names = [n for n in self.total if not (primary_only and n.endswith("_secondary"))]
        return sum(self.agreed[n] for n in names), sum(self.total[n] for n in names)


def _load(project: Project, schema: str, label: str) -> Rows:
    per_row: dict[str, dict[str, str]] = collections.defaultdict(dict)
    work_of: dict[str, str] = {}
    with project.index.connect() as conn:
        for eid, wid, name, value, quote, anchor in conn.execute(
            text(
                "SELECT x.extraction_id, x.work_id, f.field, f.value, f.quote, f.anchor "
                "FROM extraction_fields f "
                "JOIN extraction_rows x USING (extraction_id) WHERE x.schema_ref = :s "
                "AND x.pass_label = :p AND x.superseded_by IS NULL"
            ),
            {"s": schema, "p": label},
        ):
            per_row[eid][name] = value or ""
            per_row[eid][name + QUOTE_SUFFIX] = quote or ""
            per_row[eid][name + ANCHOR_SUFFIX] = anchor or ""
            work_of[eid] = wid
    out: Rows = collections.defaultdict(list)
    for eid, row in per_row.items():
        out[work_of[eid]].append(row)
    return out


def measure(spec: MinerSpec, a: Rows, b: Rows) -> Measure:
    """The fairer measure of two passes of one miner (see the module docstring)."""
    kinds = {f.name: f.kind for f in spec.fields}
    enums = {n for n, k in kinds.items() if isinstance(k, EnumKind)}
    both = sorted(set(a) & set(b))
    m = Measure(works_both=len(both))
    multi = bool(both) and sum(len(a[w]) for w in both) / len(both) > MULTI_ROW_RATIO
    key = spec.row_key_fields[0] if multi and spec.row_key_fields else None
    if multi and key not in enums:
        m.note = "several rows per work and no enum row key: not measured (needs a key)"
        return m

    def keyed(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
        if key is None:
            return {"_": rows[0]}
        return {r[key]: r for r in rows if r.get(key)}

    for w in both:
        ra, rb = keyed(a[w]), keyed(b[w])
        m.rows_a += len(ra)
        m.rows_b += len(rb)
        for k in set(ra) & set(rb):
            m.matched += 1
            x, y = ra[k], rb[k]

            def record(
                name: str,
                why: str,
                work: str = w,
                row: str = k,
                x: dict[str, str] = x,
                y: dict[str, str] = y,
            ) -> None:
                m.disagreements.append(
                    {
                        "work": work,
                        "row": "" if row == "_" else row,
                        "field": name,
                        "why": why,
                        "a": x.get(name, ""),
                        "b": y.get(name, ""),
                        "qa": x.get(name + QUOTE_SUFFIX, ""),
                        "qb": y.get(name + QUOTE_SUFFIX, ""),
                        "aa": x.get(name + ANCHOR_SUFFIX, ""),
                        "ab": y.get(name + ANCHOR_SUFFIX, ""),
                    }
                )

            for name in sorted(n for n in set(x) | set(y) if "\x00" not in n):
                if name in enums:
                    if name == key:
                        continue
                    if name.endswith("_secondary"):
                        dim = name[: -len("_secondary")]
                        pa = {x.get(f"{dim}_primary"), x.get(name)} - {None}
                        pb = {y.get(f"{dim}_primary"), y.get(name)} - {None}
                        if x.get(name) and y.get(name):
                            m.total[name] += 1
                            ok = x[name] in pb or y[name] in pa
                            m.agreed[name] += int(ok)
                            if not ok:
                                record(name, "different labels")
                        elif x.get(name) or y.get(name):
                            m.one_sided[name] += 1
                    elif name in x and name in y:
                        m.total[name] += 1
                        m.agreed[name] += int(x[name] == y[name])
                        if x[name] != y[name]:
                            record(name, "different values")
                    else:
                        m.total[name] += 1  # one pass left the field empty
                        record(
                            name,
                            "only pass A gave a value" if name in x else "only pass B gave a value",
                        )
                elif name in x and name in y:
                    m.text_pairs[name] += 1
    return m


def _pct(num: int, den: int) -> str:
    return f"{num / den:.3f}" if den else "n/a"


_CSS = (
    REPORT_CSS
    + ".dis{border:1px solid var(--mut);border-radius:8px;background:var(--lt);padding:10px 14px;"
    "margin:8px 0}.dis .t{margin-bottom:6px}.ab{display:grid;grid-template-columns:1fr 1fr;gap:14px}"
    ".q{color:var(--dim);font-size:12px}.pill{border:1px solid var(--mut);border-radius:10px;"
    "padding:0 8px;font-size:12px;color:var(--amber);margin-left:6px}a.m{display:block}"
    "tr.clk{cursor:pointer}tr.clk:hover{background:var(--sel)}"
    "@media (max-width:800px){.ab{grid-template-columns:1fr}}"
)
GLOSSARY = (
    (
        "works in both passes",
        "Works that pass A and the second pass both read; agreement can only be measured on these.",
    ),
    (
        "rows A / B / matched",
        "Rows each pass recorded for those works, and how many pairs could be compared.",
    ),
    (
        "fairer: all enum values",
        "Share of enum values on which the passes agree: rows aligned per work, values compared as labels, a secondary label agreeing when it equals the other pass's primary or secondary.",
    ),
    ("fairer: primary fields", "The same, for the main (non-secondary) fields only."),
    (
        "platform measure",
        "The recorded agreement of the `mine agreement` command: rows aligned on the row key, values compared exactly.",
    ),
)


def _titles(project: Project, works: set[str]) -> dict[str, str]:
    import json

    out: dict[str, str] = {}
    with project.index.connect() as conn:
        for wid in works:
            row = conn.execute(
                text("SELECT data FROM works WHERE work_id = :w"), {"w": wid}
            ).first()
            out[wid] = str(json.loads(row[0]).get("title") or wid) if row else wid
    return out


def _side(label: str, value: str, quote: str, anchor: str) -> str:
    q = (
        f"<div class=q>“{esc(quote[:300])}” {esc(anchor)}</div>"
        if quote and quote != value
        else (f"<div class=q>{esc(anchor)}</div>" if anchor else "")
    )
    return f"<div><b>{label}</b>: {esc(value) if value else '<span class=dim>(no value)</span>'}{q}</div>"


def _miner_page(project: Project, name: str, version: int, spec: MinerSpec, m: Measure) -> str:
    from factory.services.site import page

    titles = _titles(project, {d["work"] for d in m.disagreements})
    by_field: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for d in m.disagreements:
        by_field[d["field"]].append(d)
    rows = [
        [
            f"<a href='#{n}'>{esc(n)}</a>",
            f"{m.agreed[n]}/{m.total[n]}",
            _pct(m.agreed[n], m.total[n]),
            len(by_field.get(n, [])),
        ]
        for n in sorted(m.total)
    ]
    field_table = (
        "<table><tr><th>field</th><th>agreed / compared</th><th>rate</th><th>disagreements</th></tr>"
        + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
        + "</table>"
        if rows
        else "<p class=dim>No enum field was read by both passes.</p>"
    )
    blocks = ""
    for fname in sorted(by_field, key=lambda n: -len(by_field[n])):
        fdef = spec.field_named(fname)
        values = ""
        if fdef is not None and isinstance(fdef.kind, EnumKind):
            values = f"<p class=dim>Allowed values: {esc(' | '.join(fdef.kind.values))}</p>"
        desc = (
            f"<p class=dim>{esc(fdef.description)}</p>"
            if fdef is not None and fdef.description
            else ""
        )
        items = ""
        for d in sorted(by_field[fname], key=lambda d: titles.get(d["work"], "")):
            row = f" · row {esc(d['row'])}" if d["row"] else ""
            items += (
                f"<div class=dis><div class=t><a href='../explorer/index.html#open={slug_of(d['work'])}'>"
                f"{esc(titles.get(d['work'], d['work'])[:110])}</a><span class=pill>{esc(d['why'])}</span>{row}</div>"
                f"<div class=ab>{_side('Pass A', d['a'], d['qa'], d['aa'])}{_side('Pass B', d['b'], d['qb'], d['ab'])}</div></div>"
            )
        blocks += f"<h2 id='{esc(fname)}'>{esc(fname)} <small>({len(by_field[fname])})</small></h2>{desc}{values}{items}"
    cmds = "".join(
        f"<div class=cmd><code>{esc(c)}</code></div>"
        for c in (
            f"factory --project {project.paths.slug} mine agreement {name}",
            f"factory --project {project.paths.slug} mine resolve --help",
        )
    )
    todo = (
        "<h2>What you can do</h2><ul>"
        "<li><b>Read the pairs</b>: open the paper (the title links to the explorer, where the "
        "original and its conversion open) and decide which reading is right.</li>"
        "<li><b>Overlapping categories</b> show as many disagreements on a field whose allowed "
        "values are close in meaning; tighten the definitions in a new version of the miner "
        "(its Miners page lists versions and how).</li>"
        "<li><b>One pass left a field empty</b>: the paper may not state it, or one reading was "
        "more cautious; decide whether the field should be required.</li>"
        "<li><b>Which pass is right</b> needs gold labels from a person on a sample of works; "
        "agreement alone cannot say.</li>"
        f"</ul><p class=dim>Terminal:</p>{cmds}"
    )
    return page(
        f"{name} agreement",
        f"<p class=dim><a href='index.html'>← all miners</a></p><h1>{esc(name)} v{version}: agreement</h1>"
        + note(
            f"Pass A against the second pass on {m.works_both} works both read. Below: each field's "
            "agreement, then every disagreement with both readings and their quotes."
        )
        + (
            hbars(
                [(n, m.agreed[n] / m.total[n], f"#{n}") for n in sorted(m.total) if m.total[n]],
                1.0,
            )
            if rows
            else ""
        )
        + field_table
        + (blocks or "<p class=dim>No disagreement among the enum values compared.</p>")
        + todo,
        _CSS,
    )


def build_agreement(project: Project, out: Path) -> None:
    from factory.services.site import page

    protocol = current_protocol(project)
    listed = [(u.name, u.version) for u in (protocol.spec.miners or ())] if protocol else []
    platform: dict[str, float | None] = {
        s.name: s.agreement for s in mining_service.mine_status(project)
    }
    summary_rows: list[str] = []
    chart_items: list[tuple[str, float, str | None]] = []
    for name, version in sorted(listed):
        spec = mining_service.registered_miner(project, name, version)
        if spec is None:
            continue
        schema = f"{name}@{version}"
        m = measure(spec, _load(project, schema, "A"), _load(project, schema, "B"))
        agreed, total = m.overall()
        p_agreed, p_total = m.overall(primary_only=True)
        plat = platform.get(name)
        (out / f"{name}.html").write_text(
            _miner_page(project, name, version, spec, m), encoding="utf-8"
        )
        cells = [
            f"<a href='{esc(name)}.html'>{esc(name)} v{version}</a>",
            str(m.works_both),
            f"{m.rows_a} / {m.rows_b} / {m.matched}",
            _pct(agreed, total) if total else esc(m.note or "no enum fields"),
            _pct(p_agreed, p_total) if p_total else "n/a",
            "n/a" if plat is None else f"{plat:.3f}",
            str(len(m.disagreements)),
        ]
        if p_total:
            chart_items.append((f"{name} v{version}", p_agreed / p_total, f"{name}.html"))
        summary_rows.append(
            f"<tr class=clk onclick=\"location.href='{esc(name)}.html'\">"
            + "".join(f"<td>{c}</td>" for c in cells)
            + "</tr>"
        )
    head = note(
        "Agreement tells how consistent two readings of the same papers are: pass A read every "
        "work, a second model read a sample, and the platform compares them. It does not say which "
        "reading is right (that needs gold labels). Click a miner to see every disagreement with "
        "both quotes."
    )
    glossary = table(["column", "meaning"], [list(g) for g in GLOSSARY])
    summary = (
        "<table><tr><th>miner</th><th>works in both passes</th><th>rows A / B / matched</th>"
        "<th>fairer: all enum values</th><th>fairer: primary fields</th><th>platform measure</th>"
        "<th>disagreements</th></tr>" + "".join(summary_rows) + "</table>"
    )
    (out / "index.html").write_text(
        page(
            "Miner agreement",
            f"<h1>Miner agreement</h1>{head}"
            + section(
                "Agreement by miner (fairer measure, primary fields)",
                note(
                    "Mint at 0.8 or more, amber from 0.5, red below. Click a bar to see every disagreement of that miner."
                )
                + hbars(chart_items, 1.0),
            )
            + f"{section('How to read the table', glossary)}"
            f"{section('Miners (click one)', summary)}"
            f"<p class=dim>Computed from the recorded rows of {esc(project.paths.slug)}.</p>",
            _CSS,
        ),
        encoding="utf-8",
    )

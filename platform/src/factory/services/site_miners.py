# ruff: noqa: E501
"""The Miners product: every listed miner explained, with its fields, checks, agreement and examples
(plan site-hub; the researcher asked for descriptions throughout and for tables that lead somewhere).

`index.html` explains what a miner is and how to read the table; each row opens `<miner>.html`:
what it records, how it reads, every field with its kind and allowed values, the checks a value must
pass, the protocol's use of it, its agreement (the platform's measure and the fairer per-field
one), example rows with their quotes, its versions, and what a person can do. Read-only; computed
from the registered specs and the recorded rows.
"""

from __future__ import annotations

import collections
from pathlib import Path
from typing import Any

from sqlalchemy import text

from factory.services import mining as mining_service
from factory.services.context import Project
from factory.services.miner_info import miner_detail
from factory.services.site_agreement import _load, measure
from factory.services.site_corpus import slug_of
from factory.services.site_widgets import REPORT_CSS, esc, link_table, note, section, table

COLUMNS = (
    ("Units", "How many works the miner has to read (one unit per work and pass)."),
    (
        "Closed",
        "Units finished: the work was read and its rows accepted, or it was closed with a stated reason.",
    ),
    ("Open", "Units not finished yet."),
    (
        "Rows",
        "Accepted rows. A work gives one row, or several for a miner that records one row per item.",
    ),
    ("Stale", "Rows made outdated by a protocol change; they must be read again."),
    (
        "Second pass",
        "The share of works that another model reads again, so agreement can be measured.",
    ),
    (
        "Agreement (fairer)",
        "Share of enum values on which pass A and the second pass agree, aligned per work, secondary labels as sets, text not compared.",
    ),
    (
        "Agreement (platform)",
        "The recorded agreement of the `mine agreement` command, which aligns rows on the row key and compares exact values.",
    ),
)
KIND_HELP = {
    "enum": "one value from a fixed list, with a supporting quote",
    "quote": "a sentence copied verbatim from the paper",
    "number": "a number as printed, with its unit",
    "integer": "a whole number",
    "citation": "a citation marker found in the quote",
    "anchor": "a paragraph anchor",
    "work_ref": "a reference to another work",
}
CSS = (
    REPORT_CSS + "a.row{display:block}.cmd{display:flex;gap:8px;align-items:center;margin:4px 0}"
    ".cmd code{background:var(--lt);border:1px solid var(--mut);border-radius:6px;padding:3px 8px;"
    "font-size:12px;flex:1;overflow-x:auto;white-space:nowrap}.cmd button{background:var(--lt);"
    "color:var(--fg);border:1px solid var(--mut);border-radius:6px;padding:2px 10px;cursor:pointer}"
    "tr.clk{cursor:pointer}tr.clk:hover{background:var(--sel)}.q{color:var(--dim);font-size:12px}"
    ".sub{color:var(--dim);font-size:13px;margin:2px 0 10px}code{font-size:12px}"
)


def _first_sentence(text_: str) -> str:
    i = text_.find(". ")
    s = text_[: i + 1] if i > 0 else text_
    return s if len(s) <= 220 else s[:217] + "…"


def _kind_text(k: dict[str, Any]) -> str:
    out = str(k.get("type", ""))
    if k.get("values"):
        out += ": " + " | ".join(k["values"])
    if k.get("unit_family"):
        out += f" ({k['unit_family']})"
    return out


def _cmds(slug: str, name: str) -> str:
    cmds = [
        f"factory --project {slug} mine status",
        f"factory --project {slug} mine agreement {name}",
        f"factory --project {slug} mine resolve --help",
    ]
    return "".join(
        f'<div class=cmd><code>{esc(c)}</code><button onclick="navigator.clipboard.writeText(this.dataset.c)" data-c="{esc(c)}">Copy</button></div>'
        for c in cmds
    )


def _examples(project: Project, schema: str, limit: int = 3) -> str:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT x.extraction_id, x.work_id FROM extraction_rows x WHERE x.schema_ref = :s "
                "AND x.pass_label = 'A' AND x.superseded_by IS NULL ORDER BY x.work_id"
            ),
            {"s": schema},
        ).all()
        best: dict[str, tuple[str, int]] = {}
        for eid, wid in rows:
            n = conn.execute(
                text("SELECT COUNT(*) FROM extraction_fields WHERE extraction_id = :e"), {"e": eid}
            ).scalar()
            if wid not in best or int(n or 0) > best[wid][1]:
                best[wid] = (str(eid), int(n or 0))
        picks = sorted(best.items(), key=lambda kv: -kv[1][1])[:limit]
        out = ""
        for wid, (eid, _n) in picks:
            data = conn.execute(
                text("SELECT data FROM works WHERE work_id = :w"), {"w": wid}
            ).scalar()
            import json

            title = str(json.loads(data).get("title") or wid) if data else wid
            frows = conn.execute(
                text(
                    "SELECT field, value, quote, anchor FROM extraction_fields WHERE extraction_id = :e"
                ),
                {"e": eid},
            ).all()
            body = "".join(
                f"<tr><td>{esc(f)}</td><td>{esc((v or '')[:160])}</td>"
                f"<td class=q>{esc((q or '')[:200]) if q and q != v else ''} {esc(a or '')}</td></tr>"
                for f, v, q, a in frows
            )
            out += (
                f"<h3><a href='../explorer/index.html#open={slug_of(wid)}'>{esc(title[:100])}</a></h3>"
                f"<table><tr><th>field</th><th>value</th><th>quote and anchor</th></tr>{body}</table>"
            )
    return out or "<p class=dim>No rows yet.</p>"


def build_miners(project: Project, out: Path) -> None:
    from factory.services.site import page

    statuses = mining_service.mine_status(project)
    slug = project.paths.slug
    index_rows: list[str] = []
    for s in statuses:
        detail = miner_detail(project, s.name, s.version)
        spec: dict[str, Any] = detail["spec"] or {}
        use: dict[str, Any] = detail["use"] or {}
        schema = f"{s.name}@{s.version}"
        spec_obj = mining_service.registered_miner(project, s.name, s.version)
        fair = ""
        field_rows: list[list[object]] = []
        if spec_obj is not None:
            m = measure(spec_obj, _load(project, schema, "A"), _load(project, schema, "B"))
            agreed, total = m.overall(primary_only=True)
            fair = f"{agreed / total:.3f}" if total else (m.note or "n/a")
            field_rows = [
                [n, f"{m.agreed[n]}/{m.total[n]}", f"{m.agreed[n] / m.total[n]:.3f}"]
                for n in sorted(m.total)
            ]
        plat = "n/a" if s.agreement is None else f"{s.agreement:.3f}"
        sample = use.get("dual_extract_sample")
        sample_txt = "every work" if sample is None else f"{round(sample * 100)}%"
        sel = spec.get("selector", {})
        reg = spec.get("regime", {})
        ev = spec.get("evidence", {})
        fields = spec.get("fields", [])
        kinds = collections.Counter(f["kind"]["type"] for f in fields)
        kind_help = "".join(
            f"<li><b>{esc(k)}</b> ({n}): {esc(KIND_HELP.get(k, ''))}</li>" for k, n in kinds.items()
        )
        field_tbl = link_table(
            ["field", "group", "kind", "required", "compared", "what it records"],
            [
                (
                    [
                        f["name"],
                        f["group"],
                        _kind_text(f["kind"]),
                        "yes" if f.get("required") else "",
                        "no" if f.get("compared") is False else "yes",
                        f.get("description", ""),
                    ],
                    f"../agreement/{s.name}.html#{f['name']}"
                    if f["kind"]["type"] == "enum" and f.get("compared") is not False
                    else None,
                )
                for f in fields
            ],
        )
        vers = table(
            ["version", "digest", "listed in the protocol", "proposed by"],
            [
                [v["version"], v["digest"], "yes" if v["listed"] else "no", v["proposer"]]
                for v in detail["versions"]
            ],
        )
        read = table(
            ["", ""],
            [
                ["works read", f"{sel.get('population', '')} (the works the miner runs on)"],
                ["paragraph kinds", ", ".join(sel.get("elements", []))],
                ["sections searched", ", ".join(sel.get("heading_patterns", [])) or "all"],
                ["max works", "no limit" if sel.get("max_units") is None else sel["max_units"]],
                ["procedure (skill)", spec.get("procedure", "")],
                ["one row per", " + ".join(spec.get("row_key_fields", [])) or "work"],
            ],
        )
        quality = table(
            ["", ""],
            [
                ["passes", f"{reg.get('passes')} (pass A reads every work; pass B a sample)"],
                ["second pass", f"{sample_txt} of works read again by another model"],
                [
                    "audit",
                    f"a random {round(100 * use.get('audit_fraction', 0))}% of rows, at least {use.get('audit_minimum', 0)}, checked by the researcher",
                ],
                [
                    "evidence",
                    "rows are admitted to the evidence report"
                    if use.get("evidence")
                    else "rows are NOT admitted to the evidence report (that needs calibration and the researcher's act)",
                ],
                ["imports", use.get("imports", "")],
                *(
                    [["status", "exploratory (declared): no quality claim on its rows"]]
                    if use.get("exploratory")
                    else []
                ),
                [
                    "quote rule",
                    "every enum value needs a supporting quote"
                    if ev.get("enum_needs_quote")
                    else "",
                ],
                [
                    "calibration",
                    f"{reg.get('calibration_size')} works labelled by a person before the miner is trusted; field agreement at least {reg.get('field_agreement_min')}, recall at least {reg.get('recall_min')}",
                ],
            ],
        )
        counts = table(
            [
                "units",
                "closed",
                "open",
                "rows",
                "stale",
                "agreement (fairer)",
                "agreement (platform)",
            ],
            [[s.units, s.closed, s.open, s.rows, s.stale, fair, plat]],
        )
        body = (
            f"<p class=sub><a href='index.html'>← all miners</a> · version {s.version} · digest {esc(s.digest)}</p>"
            f"<h1>{esc(s.name)}</h1><p>{esc(spec.get('rationale', 'No rationale recorded.'))}</p>"
            + section("Status", counts)
            + section(
                "How it reads",
                note(
                    "The platform picks the paragraphs to read; the model reads them and records values; the platform checks every value and quote against the paper before accepting it."
                )
                + read,
            )
            + section(
                f"Fields ({len(fields)})",
                note(
                    "Every value is checked: an enum must be one of its allowed values and carry a quote; a quote field must be verbatim from the cited paragraph. “Compared” fields enter the agreement between passes; the others are evidence only."
                )
                + f"<ul>{kind_help}</ul>"
                + field_tbl,
            )
            + section("Quality and use", quality)
            + section(
                "Agreement by field (fairer measure)",
                note(
                    "Pass A against the second pass on the works both read. Rows align per work; secondary labels count as sets; text and quotes are not compared. It says how consistent the two readings are, not which is right."
                )
                + (
                    table(["field", "agreed / compared", "rate"], field_rows)
                    if field_rows
                    else "<p class=dim>No enum field was read by both passes.</p>"
                ),
            )
            + section(
                "Examples (pass A)",
                note(
                    "Three works with the most fields recorded: the value, the quote behind it and where it sits in the paper. Click a title to open the paper in the explorer."
                )
                + _examples(project, schema),
            )
            + section(
                "Versions",
                note(
                    "A change to a miner is a new version; older versions keep their rows. Only the listed version runs."
                )
                + vers,
            )
            + section(
                "What you can do",
                f"<p class=dim>Run these in a terminal (the hub is read-only).</p>{_cmds(slug, s.name)}<p class=dim>To change what this miner records, register a new version (skill rf-mine), list it in the protocol with an amendment, and run pass A and the second pass; the old version's rows stay.</p>",
            )
        )
        (out / f"{s.name}.html").write_text(page(s.name, body, CSS), encoding="utf-8")
        index_rows.append(
            f"<tr class=clk onclick=\"location.href='{esc(s.name)}.html'\"><td><a href='{esc(s.name)}.html'>{esc(s.name)}</a></td><td>{s.version}</td>"
            f"<td>{esc(_first_sentence(str(spec.get('rationale', ''))))}</td><td class=n>{s.units}</td><td class=n>{s.closed}</td><td class=n>{s.open}</td><td class=n>{s.rows}</td>"
            f"<td class=n>{esc(sample_txt)}</td><td class=n>{esc(fair if fair[:1].isdigit() else 'n/a')}</td><td class=n>{esc(plat)}</td></tr>"
        )
    glossary = table(["column", "meaning"], [list(c) for c in COLUMNS])
    index = (
        "<h1>Miners</h1>"
        + note(
            "A miner reads the included full texts and records typed, quoted values: each value is an enum, a number or a verbatim sentence, never free text. One model reads every work (pass A); another reads a sample (pass B) so agreement can be measured. The platform picks the paragraphs, checks every value and quote against the paper, and counts agreement. Click a miner to see what it records, how it reads, its fields and checks, its agreement, example rows and what you can do."
        )
        + section("How to read the table", glossary)
        + section(
            "Listed miners",
            "<table><tr><th>miner</th><th>version</th><th>what it records</th><th>units</th><th>closed</th><th>open</th><th>rows</th><th>second pass</th><th>agreement (fairer)</th><th>agreement (platform)</th></tr>"
            + "".join(index_rows)
            + "</table>",
        )
    )
    (out / "index.html").write_text(page("Miners", index, CSS), encoding="utf-8")

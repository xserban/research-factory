"""Markdown and CSV renderings of the evidence report. Formatting only: every figure is read
from the model (R-05). Output is deterministic and follows the report's order; the only document
text shown is the verified quote fields and claim statements already in the model."""

import csv
import io

from factory.services.evidence_report import (
    EvidenceReport,
    EvidenceRow,
    FrontierAxis,
    GroupReport,
    Provenance,
)


def _speed_section(report: EvidenceReport) -> list[str]:
    """Hook for the within-paper speed section (plan E task 4); returns no lines until wired.
    When wired it returns the whole section, starting with `## Within-paper speed ratios`."""
    return []


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _val(p: Provenance) -> str:
    if isinstance(p.value, bool):
        return "true" if p.value else "false"
    return f"{p.value} {p.unit}" if p.unit else p.value


def _flags(row: EvidenceRow) -> str:
    flags = ["independent" if row.independent else "copied", row.status]
    if row.is_proposed:
        flags.append("proposed")
    if row.value.reproduced:
        flags.append("reproduced")
    return ", ".join(flags)


def _row_table(rows: list[EvidenceRow]) -> list[str]:
    cost_names = sorted({n for r in rows for n in r.costs})
    head = [
        "row",
        "work",
        "method",
        "variant",
        "value",
        "flags",
        *cost_names,
        "extraction",
        "trace",
    ]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        cells = [
            r.row_key,
            r.work_id,
            r.method_name or "",
            r.variant or "",
            _val(r.value),
            _flags(r),
            *[_val(r.costs[n]) if n in r.costs else "" for n in cost_names],
            r.value.extraction_id,
            r.value.trace_id,
        ]
        out.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return out


def _frontier(axis: FrontierAxis) -> list[str]:
    out = [f"#### Frontier: {axis.axis}", ""]
    if axis.statement:
        out += [axis.statement, ""]
    for part in axis.partitions:
        out.append(f"- unit {part.unit or 'none'}, resolution {part.resolution or 'none'}")
        if part.statement:
            out.append(f"  - {part.statement}")
        for pt in part.points:
            state = "on frontier" if pt.on_frontier else f"dominated by {pt.dominated_by}"
            out.append(
                f"  - {pt.row_key} ({pt.work_id}, {pt.method_name or 'unnamed'}): "
                f"cost {pt.cost}, metric {pt.metric}, {state}"
            )
    for name, rows in sorted(axis.missing.items()):
        out.append(f"- missing {name}: {len(rows)} ({', '.join(rows)})")
    out.append("")
    return out


def _group(g: GroupReport) -> list[str]:
    key = ", ".join(f"{k}={v}" for k, v in g.key)
    c = g.counts
    direction = "" if g.direction is None else f" (higher is better: {str(g.direction).lower()})"
    out = [
        f"### Group {g.group_id}",
        "",
        f"Key: {key}",
        "",
        f"Counts: independent {c.independent}, copied {c.copied}, works {c.works}, "
        f"independent works {c.independent_works}",
        f"Direction: {g.direction_status}{direction}",
        "",
    ]
    out += [f"- {s.text}" for s in g.statements]
    if g.statements:
        out.append("")
    out += _row_table(g.rows)
    out.append("")
    for axis in g.frontiers:
        out += _frontier(axis)
    if g.method_conflicts:
        out += ["#### Method conflicts", ""]
        for m in g.method_conflicts:
            out.append(f"- {m.method} ({m.variant or 'no variant'}): rows {', '.join(m.rows)}")
        out.append("")
    return out


def evidence_markdown(report: EvidenceReport, *, show_audit: bool = True) -> str:
    """The evidence report as Markdown; groups are separate sections, never merged."""
    out = ["# Evidence report", ""]
    if report.provisional:
        out += ["**PROVISIONAL: extraction is not complete or not yet reconciled.**", ""]
    out += [
        f"- protocol: {report.project_protocol_id or 'none'}",
        f"- pack: {report.pack or 'none'} (version {report.pack_version})",
        f"- report version: {report.report_version}",
        f"- comparability keys: {', '.join(report.comparability_keys)}",
        "",
        "## Limits",
        "",
    ]
    out += [f"- {x.text}" for x in report.limits] or ["- none"]
    if report.expectations:
        out += ["", "## Expectations", ""]
        for e in report.expectations:
            want = ", ".join(f"{k}={v}" for k, v in sorted(e.expect.items()))
            out.append(f"- {want}: groups {', '.join(e.group_ids) or 'none'}")
    out += ["", "## Groups", ""]
    for g in report.groups:
        out += _group(g)
    if report.ungrouped:
        out += ["## Ungrouped rows", ""]
        out += _row_table(report.ungrouped)
        out.append("")
    speed = _speed_section(report)
    if speed:
        out += [*speed, ""]
    out += ["## Claims by type", ""]
    for ctype, entries in report.claims.items():
        out += [f"### {ctype}", ""]
        for cl in entries:
            out.append(
                f"- {cl.claim_id} ({cl.work_id}, {cl.evidence_type.value}, {cl.strength.value}): "
                f'{cl.statement} [{cl.anchor}] "{cl.quote}" (trace {cl.trace_id})'
            )
        if not entries:
            out.append("- none")
        out.append("")
    out += ["## Excluded", ""]
    out += [f"- {e.reason}: {e.count} ({', '.join(e.works)})" for e in report.excluded] or [
        "- none"
    ]
    q = report.quality
    agreement = "n/a" if q.agreement_overall is None else q.agreement_overall
    out += [
        "",
        "## Quality",
        "",
        f"- works extracted twice: {q.dual_works}; once: {q.single_extraction_works}",
        f"- agreement overall: {agreement}"
        f" (aligned rows {q.agreement_rows_aligned}, unmatched {q.agreement_rows_unmatched})",
    ]
    if show_audit:
        rate = "n/a" if q.audit_error_rate is None else q.audit_error_rate
        out.append(f"- audit: {q.audit_n} labelled, error rate {rate}")
        if q.audit_above_ceiling is not None:
            out.append(f"- audit above ceiling: {str(q.audit_above_ceiling).lower()}")
    return "\n".join(out) + "\n"


POINTS_COLUMNS = (
    "group_id,axis,unit,resolution,row_key,work_id,method,cost,metric,on_frontier,dominated_by"
)
ROWS_COLUMNS = (
    "group_id,row_key,work_id,method,variant,value,unit,canonical,independent,status,"
    "params,flops,macs,anchor,cell,extraction_id"
)


def _csv(header: str, rows: list[list[object]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header.split(","))
    for r in rows:
        w.writerow(["" if c is None else c for c in r])
    return buf.getvalue()


def points_csv(report: EvidenceReport) -> str:
    """One line per frontier point (hardware-independent axes only), in report order."""
    rows: list[list[object]] = []
    for g in report.groups:
        for axis in g.frontiers:
            for part in axis.partitions:
                for p in part.points:
                    rows.append(
                        [
                            g.group_id,
                            axis.axis,
                            part.unit,
                            part.resolution,
                            p.row_key,
                            p.work_id,
                            p.method_name,
                            p.cost,
                            p.metric,
                            str(p.on_frontier).lower(),
                            p.dominated_by,
                        ]
                    )
    return _csv(POINTS_COLUMNS, rows)


def _cost(row: EvidenceRow, name: str) -> object:
    p = row.costs.get(name)
    return None if p is None else _val(p)


def rows_csv(report: EvidenceReport) -> str:
    """One line per grouped row with its provenance, in report order."""
    rows: list[list[object]] = []
    for g in report.groups:
        for r in g.rows:
            v = r.value
            rows.append(
                [
                    g.group_id,
                    r.row_key,
                    r.work_id,
                    r.method_name,
                    r.variant,
                    v.value,
                    v.unit,
                    v.canonical,
                    str(r.independent).lower(),
                    r.status,
                    _cost(r, "params"),
                    _cost(r, "flops"),
                    _cost(r, "macs"),
                    v.anchor,
                    v.cell,
                    v.extraction_id,
                ]
            )
    return _csv(ROWS_COLUMNS, rows)

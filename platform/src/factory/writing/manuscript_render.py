"""The manuscript report as Markdown (slice 7b, plan W-C). Pure: a report and the sentences' text
go in, text comes out. The caller reads the text from the library; nothing here is stored."""

from __future__ import annotations

from collections.abc import Mapping

from factory.model.manuscripts import ManuscriptReport, ReportUnit


def _counts(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{k} {counts[k]}" for k in sorted(counts)) or "none"


def _unit_lines(unit: ReportUnit) -> list[str]:
    who = unit.work_id or ", ".join(unit.keys)
    if unit.reason is not None:
        return [f"- {who}: cannot-verify: {unit.reason.value}"]
    if unit.verdict is None:
        return [f"- {who}: no verdict yet"]
    v = unit.verdict
    head = f"- {who}: {v.verdict.value}"
    if unit.state == "detached":
        head += " (its citation has changed since)"
    lines = [head]
    if v.span_start is not None and v.span_end is not None:
        lines.append(f"  - sentence span: {v.span_start}-{v.span_end}")
    if v.quote is not None:
        lines.append(f'  - {v.conversion_id}/{v.anchor}: "{v.quote}"')
    if v.note is not None:
        lines.append(f"  - note: {v.note}")
    lines.append(f"  - verdict id: {v.verdict_id}")
    return lines


def render_report(report: ManuscriptReport, texts: Mapping[int, str]) -> str:
    """The title, the counts, the audit and each cited or flagged sentence with its units."""
    audit = report.audit
    lines = [
        f"# {report.label} ({report.manuscript_id})",
        "",
        f"Sentences: {report.sentences}; cited: {report.cited}.",
        f"Verdicts: {_counts(report.verdicts)}.",
        f"Cannot verify: {_counts(report.closed)}.",
        f"Units without a verdict: {report.open_units}; citations awaiting you: {report.waiting}.",
        f"Uncited-claim flags (advisory, not verdicts): {report.flags}.",
        f"Audit: {audit.labelled} of {audit.drawn} labelled, {audit.incorrect} incorrect"
        + ("." if audit.rate is None else f", rate {audit.rate:.3f}.")
        + (" A verdict is newer than the last draw." if audit.outdated else ""),
    ]
    for row in report.rows:
        lines += ["", f"## Sentence {row.ordinal}", "", " ".join(texts[row.ordinal].split()), ""]
        if row.uncited_flag:
            lines.append("- flagged: uncited-claim")
        if row.waiting:
            lines.append(f"- keys not resolved yet: {', '.join(row.waiting)}")
        for unit in row.units:
            lines += _unit_lines(unit)
    return "\n".join(lines) + "\n"

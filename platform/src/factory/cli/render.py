"""Markdown and text renderings of the report models for the CLI. Formatting only: every figure
is read from the model, so the CLI and the MCP tools cannot differ (R-05)."""

from factory.services.check import CheckReport
from factory.services.prisma import PrismaFlow, SearchReport
from factory.services.trace import TraceNode


def prisma_markdown(flow: PrismaFlow) -> str:
    """The PRISMA 2020 flow as a Markdown list, one line per box."""
    lines = ["# PRISMA 2020 flow", ""]
    lines.append("## Identification")
    lines += [f"- {source}: {n}" for source, n in flow.identified_databases.items()]
    lines += [f"- other methods, {method}: {n}" for method, n in flow.identified_other.items()]
    lines.append(f"- duplicates removed: {flow.duplicates_removed}")
    lines += ["", "## Screening", f"- records screened: {flow.screened}"]
    lines += [f"- excluded, {criterion}: {n}" for criterion, n in flow.excluded.items()]
    lines.append(f"- pending: {flow.pending}")
    lines.append(f"- full-text assessment: {flow.full_text}")
    lines += ["", "## Included", f"- included: {flow.included}"]
    if flow.provisional:
        lines += ["", "The flow is provisional: works are pending."]
    lines.append(f"\nProtocol: {flow.protocol_id or 'none'}")
    return "\n".join(lines) + "\n"


def search_markdown(report: SearchReport) -> str:
    """The PRISMA-S search report as Markdown, one section per registered query."""
    lines = ["# PRISMA-S search report", ""]
    for row in report.rows:
        lines.append(f"## {row.query_id} ({row.source}, {row.kind.value}, {row.purpose.value})")
        lines.append(f"- query: `{row.text}`")
        lines.append(f"- interface: {row.interface}")
        lines.append(f"- registered: {row.registered_at.isoformat()}")
        filters = ", ".join(f"{k}={v}" for k, v in row.filters.items()) or "none"
        lines.append(f"- filters: {filters}")
        reported = "not reported" if row.reported is None else str(row.reported)
        lines.append(f"- reported: {reported}; retrieved: {row.retrieved}")
        if row.shortfall_reason:
            lines.append(f"- shortfall: {row.shortfall_reason}")
        if row.deviation_id:
            lines.append(f"- deviation: {row.deviation_id}")
        for run in row.runs:
            lines.append(f"- run {run.run_id}: {run.status.value}, {run.retrieved_count} retrieved")
        lines.append("")
    lines.append(f"PRESS review: {report.press_review_id or 'none'}")
    lines.append(f"PRESS confirmed: {'yes' if report.press_confirmed else 'no'}")
    lines += [f"- limit {limit.field}: {limit.value} ({limit.why})" for limit in report.limits]
    return "\n".join(lines) + "\n"


def trace_lines(node: TraceNode, depth: int = 0) -> list[str]:
    """The trace as an indented tree: kind, id, label and the event that created the node."""
    event = f"  [{node.event_id}]" if node.event_id else ""
    lines = [f"{'  ' * depth}{node.kind} {node.id}  {node.label}{event}"]
    for child in node.children:
        lines += trace_lines(child, depth + 1)
    return lines


def check_lines(report: CheckReport) -> list[str]:
    """The human view of `check`: every finding with its refs (seed ids included)."""
    head = f"mode {report.mode.value}; evaluated as {report.evaluated_as.value}"
    if not report.findings:
        return [head, "no findings"]
    lines = [head]
    for finding in report.findings:
        refs = f"  [{', '.join(finding.refs)}]" if finding.refs else ""
        lines.append(f"{finding.severity}  {finding.code}  {finding.message}{refs}")
    return lines

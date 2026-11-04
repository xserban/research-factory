"""Markdown and text renderings of the report models for the CLI. Formatting only: every figure
is read from the model, so the CLI and the MCP tools cannot differ (R-05)."""

from factory.model.screening import PassLabel
from factory.services.agreement import DecisionView
from factory.services.audit import AuditReport
from factory.services.check import CheckReport
from factory.services.document_convert import ConvertSummary, DocumentStatus
from factory.services.document_read import DocumentPage
from factory.services.extraction import UnitState
from factory.services.extraction_agreement import (
    ExtractionAgreement,
    FieldDisagreement,
    FieldView,
)
from factory.services.extraction_audit import AuditEvidence, ExtractionAuditReport
from factory.services.fulltext import FetchSummary
from factory.services.fulltext_import import ImportReport
from factory.services.fulltext_status import FulltextStatus
from factory.services.imports import ImportListing, ImportSummary, RecordRow
from factory.services.prisma import UNCONVERTED, PrismaFlow, SearchReport
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
    boxes = flow.full_text
    lines += ["", "## Full-text assessment"]
    lines.append(f"- reports sought: {boxes.sought}")
    lines.append(f"- reports not retrieved: {boxes.not_retrieved}")
    lines += [f"  - {reason}: {n}" for reason, n in boxes.not_retrieved_reasons.items()]
    if boxes.not_retrieved_reasons.get(UNCONVERTED):
        lines.append("  - unconverted works need conversion: run `factory document convert`")
    if boxes.stage_run:
        lines.append(f"- reports assessed for eligibility: {boxes.assessed}")
        lines += [f"- excluded, {criterion}: {n}" for criterion, n in boxes.excluded.items()]
        lines.append(f"- pending at full text: {boxes.pending}")
        lines.append(f"- included at full text: {boxes.included}")
    else:
        lines.append("- not assessed in this review stage (no full-text decisions)")
    lines += ["", "## Included", f"- included: {flow.included}"]
    if flow.included_in_review is not None:
        lines.append(f"- included in the review: {flow.included_in_review}")
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


def import_lines(report: ImportReport) -> list[str]:
    """Every list of an import, with its count: imported (file, work, document), then the rest."""
    lines = [f"imported: {len(report.imported)}"]
    lines += [f"  {name}  {work}  {document}" for name, work, document in report.imported]
    for label, names in (
        ("already imported", report.already_imported),
        ("unmatched", report.unmatched),
        ("ambiguous", report.ambiguous),
        ("not promoted", report.not_promoted),
        ("not pdf", report.not_pdf),
    ):
        lines.append(f"{label}: {len(names)}")
        lines += [f"  {name}" for name in names]
    return lines


def fetch_lines(summary: FetchSummary) -> list[str]:
    """The fetch's head line, then each work's status with its attempt and document counts."""
    lines = [f"fetch {summary.fetch_id}: {len(summary.works)} works, {summary.remaining} remaining"]
    for work in summary.works:
        lines.append(
            f"{work.work_id}  {work.status}  documents {len(work.documents)}"
            f"  attempts {len(work.attempts)}"
        )
    return lines


def fulltext_status_lines(status: FulltextStatus) -> list[str]:
    """The counts and the live documents per route, then each work, with its reasons if missed."""
    by_route = ", ".join(f"{route.value} {count}" for route, count in status.by_route.items())
    lines = [
        f"promoted: {status.promoted}",
        f"unsought: {status.unsought}",
        f"retrieved: {status.retrieved}",
        f"not retrieved: {status.not_retrieved}",
        f"by route: {by_route}",
    ]
    for work in status.works:
        reasons = "; ".join(f"{route.value} {reason}" for route, reason in work.reasons.items())
        lines.append(f"{work.work_id}  {work.state}" + (f"  ({reasons})" if reasons else ""))
    return lines


def convert_lines(summary: ConvertSummary) -> list[str]:
    """One line per document outcome (document, work, status, reason), then the counts."""
    lines = [
        f"{o.document_id}  {o.work_id}  {o.status}  {o.reason if o.reason else '-'}"
        for o in summary.outcomes
    ]
    lines.append(
        f"converted {summary.converted}, unchanged {summary.unchanged}, failed {summary.failed}, "
        f"raw-missing {summary.raw_missing}, restored {summary.restored}"
    )
    return lines


def document_status_lines(status: DocumentStatus) -> list[str]:
    """The counts, then each live document: its converter and anchor counts, or not converted.
    Its latest recorded failure follows: `earlier failure` for a converted document, `last failure`
    for one not converted."""
    lines = [
        f"documents: {len(status.documents)}",
        f"converted: {status.converted}",
        f"not converted: {status.not_converted}",
    ]
    for doc in status.documents:
        if doc.converted:
            state = (
                f"converted  {doc.converter} {doc.converter_version}"
                f"  anchors {_anchor_counts(doc.counts)}"
            )
        else:
            state = "not converted"
        failure = ""
        if doc.latest_failure:
            label = "earlier failure" if doc.converted else "last failure"
            failure = f"  {label}: {doc.latest_failure.value}"
        lines.append(f"{doc.document_id}  {doc.work_id}  {state}{failure}")
    return lines


def _anchor_counts(counts: dict[str, int] | None) -> str:
    if counts is None:
        return "-"
    return ", ".join(f"{kind} {n}" for kind, n in counts.items() if n) or "none"


def document_page_lines(page: DocumentPage) -> list[str]:
    """Each segment as its anchor and kind (with a truncation marker), then its text; then the
    anchor to pass as `--after` for the next page, if there is one."""
    lines: list[str] = []
    for index, segment in enumerate(page.segments):
        if index:
            lines.append("")
        marker = "  (truncated)" if segment.truncated else ""
        lines.append(f"[{segment.anchor}] {segment.kind.value}{marker}")
        lines.append(segment.text)
    if page.next_after is not None:
        lines += ["", f"next_after: {page.next_after}"]
    return lines


def evidence_lines(work_id: str, document_id: str | None, conversion_id: str | None) -> list[str]:
    """The document and pinned conversion of a full-text item, and the command that reads it.
    Empty when the item has no conversion (title/abstract)."""
    if conversion_id is None:
        return []
    return [
        f"  document {document_id or '-'}  conversion {conversion_id}",
        f"  read: factory document read {work_id} --conversion {conversion_id}",
    ]


def decision_lines(label: str, view: DecisionView) -> list[str]:
    """One pass's decision on a work: verdict, criterion, the cited anchor and the quote."""
    cited = view.criterion or "-"
    anchor = "" if view.anchor is None else f"  anchor {view.anchor}"
    return [
        f"  {label}: {view.verdict.value} {cited}{anchor}  quote: {view.quote}  "
        f"rationale: {view.rationale}"
    ]


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def extraction_status_lines(states: list[UnitState]) -> list[str]:
    """One line per pass in use: its units by state."""
    if not states:
        return ["no extraction units"]
    lines: list[str] = []
    for label in PassLabel:
        mine = [s for s in states if s.pass_label is label]
        if not mine:
            continue
        counts = ", ".join(
            f"{name} {sum(1 for s in mine if s.state == name)}"
            for name in ("current", "open", "queued", "stale")
        )
        lines.append(f"pass {label.value}: {counts}")
    return lines


def field_view_lines(label: str, view: FieldView | None) -> list[str]:
    """One pass's value of a disagreement: value, unit, anchor, cell and the verbatim quote."""
    if view is None:
        return [f"  {label}: -"]
    unit = f" {view.unit}" if view.unit else ""
    return [
        f"  {label}: {view.value}{unit}  anchor {view.anchor or '-'}  cell {view.cell or '-'}"
        f"  quote: {view.quote or '-'}  reported {view.reported_in.value}"
    ]


def disagreement_lines(item: FieldDisagreement) -> list[str]:
    """A disagreement with both passes' values."""
    lines = [f"{item.work_id}  {item.row_key}  {item.field or 'row'} ({item.kind})"]
    lines += field_view_lines("A", item.a)
    lines += field_view_lines("B", item.b)
    return lines


def agreement_lines(agreement: ExtractionAgreement) -> list[str]:
    """The extraction agreement: counts, per-group rates and the unresolved disagreements."""
    lines = [
        f"dual works {agreement.dual_works}, rows aligned {agreement.rows_aligned}, "
        f"unmatched {agreement.rows_unmatched}, resolved {agreement.resolved}, "
        f"dropped {len(agreement.dropped)}, single-extraction {len(agreement.single_extraction)}",
        f"overall {_rate(agreement.overall)}",
    ]
    lines += [
        f"group {g.group}: {g.agreed}/{g.compared} rate {_rate(g.rate)}" for g in agreement.rates
    ]
    if not agreement.disagreements:
        lines.append("no unresolved disagreements")
    for item in agreement.disagreements:
        lines += disagreement_lines(item)
    return lines


def audit_item_lines(report: AuditReport) -> list[str]:
    """One line per sampled work: `work_id  agreed -> human (criteria)`."""
    lines = []
    for item in report.items:
        line = f"{item.work_id}  {item.agreed_verdict} -> {item.human_verdict or 'unlabelled'}"
        if item.criteria:
            line += f" ({', '.join(item.criteria)})"
        lines.append(line)
    return lines


def audit_evidence_lines(item: AuditEvidence) -> list[str]:
    """One sampled value with its quote and the text of the element it cites."""
    ref = item.item
    unit = f" {item.unit}" if item.unit else ""
    return [
        f"{ref.work_id}  {ref.row_key}  {ref.field} = {item.value}{unit}",
        f"  anchor {item.anchor or '-'}  cell {item.cell or '-'}  quote: {item.quote or '-'}",
        f"  element: {item.element_text}",
    ]


def audit_report_lines(report: ExtractionAuditReport) -> list[str]:
    """The extraction audit's counts, error rate against the ceiling and per-group rates."""
    above = "yes" if report.above_ceiling else "no"
    lines = [
        f"audit {report.audit_id}: sample {report.sample_size}, labelled {report.labelled}, "
        f"incorrect {report.incorrect}",
        f"error rate {_rate(report.error_rate)} (ceiling {report.ceiling:.2f}, "
        f"above ceiling: {above}, enforced: {'yes' if report.enforced else 'no'})",
    ]
    lines += [f"group {g}: {_rate(r)}" for g, r in report.by_group.items()]
    return lines


def library_import_lines(summary: ImportSummary) -> list[str]:
    """A recorded import: its id, counts by parse outcome, attachments and split mode."""
    lines = [f"import: {summary.import_id}"]
    lines += [f"{outcome.value}: {n}" for outcome, n in summary.counts.items()]
    lines.append(f"attachments: {summary.attachments} (missing {summary.attachments_missing})")
    lines.append(f"split: {summary.split}")
    return lines


def library_imports_lines(listings: list[ImportListing]) -> list[str]:
    """One line per import, oldest first: id, time, format, role, split, counts, collection."""
    lines = []
    for listing in listings:
        row = listing.row
        counts = " ".join(f"{o.value}={n}" for o, n in listing.counts.items())
        collection = f"  collection={row.collection}" if row.collection else ""
        lines.append(
            f"{row.import_id}  {row.recorded_at}  {row.format.value}  {row.role.value}"
            f"  split={row.split_mode}  {counts}{collection}"
        )
    return lines or ["no imports"]


def import_record_lines(records: list[RecordRow]) -> list[str]:
    """One line per record: ordinal, part, outcome, year, identifier, title."""
    lines = ["ordinal  part  outcome  year  identifier  title"]
    for r in records:
        identifier = f"doi:{r.doi}" if r.doi else f"arxiv:{r.arxiv}" if r.arxiv else "-"
        year = str(r.year) if r.year is not None else "-"
        lines.append(
            f"{r.ordinal}  {r.part}  {r.outcome.value}  {year}  {identifier}  {r.title or '-'}"
        )
    return lines

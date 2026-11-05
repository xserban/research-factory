"""Markdown and text renderings of the report models for the CLI. Formatting only: every figure
is read from the model, so the CLI and the MCP tools cannot differ (R-05)."""

from collections.abc import Mapping

from factory.errors import ValidationIssue
from factory.model.conclusions import ConclusionDiff
from factory.model.references import Decision, LinkState
from factory.model.screening import PassLabel
from factory.services.agreement import DecisionView
from factory.services.audit import AuditReport
from factory.services.check import CheckReport
from factory.services.contributions import ContributionStatus, ItemView
from factory.services.coverage import CoverageReport, Ratio
from factory.services.discovery import DiscoveryReport
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
from factory.services.ideas import IdeaCandidate, IdeaView
from factory.services.import_admit import AdmissionSummary
from factory.services.import_attach import AttachReport
from factory.services.import_resolve import ImportResolutionSummary
from factory.services.imports import (
    DevelopmentView,
    ImportListing,
    ImportSummary,
    RecordRow,
)
from factory.services.inbox import InboxPage, ResolveOutcome
from factory.services.lineage import GraphQueryResult, GraphStatus
from factory.services.prisma import UNCONVERTED, PrismaFlow, SearchReport
from factory.services.prisma_update import UpdateFlow
from factory.services.references import ExtractSummary, Page, ReferenceCounts
from factory.services.relations import RelationView
from factory.services.snowball import Comparison, RoundCandidate, RoundResult
from factory.services.trace import TraceNode
from factory.services.watch import CycleSummary, WatchStatus


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


def update_markdown(flow: UpdateFlow) -> str:
    """The PRISMA 2020 update flow of a living review as a Markdown list."""
    window = f"{flow.since_snapshot or 'start'} to {flow.until_snapshot or 'now'}"
    lines = ["# PRISMA 2020 update flow", "", f"Window: {window}", ""]
    lines.append(f"- studies included in the previous version: {flow.previous_included}")
    lines += ["", "## Identification"]
    lines += [f"- {source}: {n}" for source, n in flow.identified_databases.items()]
    lines += [f"- other methods, {method}: {n}" for method, n in flow.identified_other.items()]
    lines.append(f"- duplicates removed: {flow.duplicates_removed}")
    lines += ["", "## Screening", f"- records screened: {flow.screened}"]
    lines += [f"- excluded, {criterion}: {n}" for criterion, n in flow.excluded.items()]
    lines.append(f"- pending: {flow.pending}")
    lines.append(f"- full-text reports sought: {flow.full_text.sought}")
    lines += ["", "## Included", f"- included in this update: {flow.included}"]
    lines.append(f"- total included now: {flow.total_included}")
    if flow.changed_previous:
        lines.append(f"- earlier works whose inclusion changed: {len(flow.changed_previous)}")
        lines += [f"  - {work}" for work in flow.changed_previous]
    if flow.provisional:
        lines += ["", "The update flow is provisional: works are pending."]
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


def inbox_lines(page: InboxPage) -> list[str]:
    """One line per inbox item: id, status, last outcome, identifier, submitter and work."""
    if not page.items:
        return ["no inbox items"]
    lines = []
    for item in page.items:
        outcome = item.last_outcome or "-"
        work = f"  {item.work_id}" if item.work_id else ""
        lines.append(
            f"{item.item_id}  {item.status}  {outcome}  {item.identifier_kind}:"
            f"{item.identifier_value}  {item.actor_kind}{work}"
        )
    if page.next_cursor is not None:
        lines.append(f"more: --cursor {page.next_cursor}")
    return lines


def resolve_lines(outcomes: list[ResolveOutcome]) -> list[str]:
    """One line per attempted or refused item."""
    if not outcomes:
        return ["no open inbox items"]
    lines = []
    for o in outcomes:
        if o.status is None:
            reasons = "; ".join(f"{i.field}: {i.reason}" for i in o.issues)
            state = "refused" if o.run_id is None else f"closed during lookup ({o.run_id})"
            lines.append(f"{o.item_id}  {state}  {reasons}")
        else:
            work = f"  {o.work_id}" if o.work_id else ""
            lines.append(f"{o.item_id}  {o.status.value}{work}")
    return lines


def discovery_markdown(report: DiscoveryReport) -> str:
    """The discovery report as Markdown tables: by first route, by first surfacer, overlaps."""
    head = "| | " + " | ".join(report.levels) + " |"
    rule = "|---" * (len(report.levels) + 1) + "|"

    def row(name: str, counts: dict[str, int]) -> str:
        return f"| {name} | " + " | ".join(str(counts[level]) for level in report.levels) + " |"

    lines = ["# Discovery", "", "## By first-surfaced route", "", head, rule]
    lines += [row(route.value, counts) for route, counts in report.by_first_route.items()]
    lines += [row("total", report.totals), "", "## By first surfacer", "", head, rule]
    lines += [row(kind, counts) for kind, counts in report.by_first_actor.items()]
    lines += ["", "## Route overlaps", ""]
    lines += [f"- {key}: {n}" for key, n in report.overlaps.items()] or ["- none"]
    return "\n".join(lines) + "\n"


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
    """One line per record: ordinal, part, outcome, link state, year, identifier, title."""
    lines = ["ordinal  part  outcome  state  year  identifier  title"]
    for r in records:
        identifier = f"doi:{r.doi}" if r.doi else f"arxiv:{r.arxiv}" if r.arxiv else "-"
        year = str(r.year) if r.year is not None else "-"
        lines.append(
            f"{r.ordinal}  {r.part}  {r.outcome.value}  {r.link_state or '-'}  {year}"
            f"  {identifier}  {r.title or '-'}"
        )
    return lines


def import_resolve_lines(summary: ImportResolutionSummary) -> list[str]:
    """A resolution as counts by link state; no ordinal and no record is named."""
    lines = [f"import: {summary.import_id}"]
    lines += [f"{state.value}: {n}" for state, n in summary.counts.items()]
    lines.append(f"lookups: {len(summary.lookup_runs)} runs")
    return lines


def import_decision_lines(import_id: str, decision: Decision, state: LinkState | None) -> list[str]:
    """One decision recorded, and the record's live state after it."""
    return [f"import: {import_id}", f"{decision.value} recorded; the record is now {state or '-'}"]


def import_admit_lines(summary: AdmissionSummary) -> list[str]:
    """An admission as counts, then its promotion gaps."""
    lines = [
        f"import: {summary.import_id}",
        f"runs: {len(summary.runs)}",
        f"new works: {summary.new_works}",
        f"already in corpus: {summary.already_in_corpus}",
        f"failed runs: {summary.failed_runs}",
    ]
    lines += [f"gap: {g.field}: {g.reason}" for g in summary.gaps]
    return lines


def _ratio(name: str, ratio: Ratio | None) -> str:
    if ratio is None:
        return f"{name}: not computed (no denominator)"
    return f"{name}: {ratio.numerator}/{ratio.denominator} = {ratio.value:.3f}"


def import_coverage_lines(report: CoverageReport) -> list[str]:
    """A coverage report in full: every part, bucket, figure, outcome and suggestion. The
    researcher's view; held-out figures are included, so it must not be shown to agents."""
    lines = [
        f"import: {report.import_id}",
        f"label: {report.label}",
        f"protocol: {report.protocol_id or '-'}",
    ]
    for part in report.parts:
        lines.append(f"part: {part.part}")
        lines += [f"  {bucket.value}: {n}" for bucket, n in part.counts.items()]
        lines += [
            f"  resolved: {part.resolved}",
            f"  unresolved: {part.unresolved}",
            f"  unconfirmed: {part.unconfirmed}",
            f"  {_ratio('search sensitivity', part.sensitivity)}",
            f"  {_ratio('corpus coverage', part.coverage)}",
            "  outcomes of found records: "
            + ", ".join(f"{name} {n}" for name, n in part.outcomes.items()),
        ]
        lines += [f"  excluded by screening: {w}" for w in part.excluded]
    if report.included_not_in_library is not None:
        lines.append(f"included works absent from the library: {report.included_not_in_library}")
    lines += [f"suggested term: {s.term} ({s.seeds} works)" for s in report.suggestions]
    return lines


def import_attach_lines(report: AttachReport, *, researcher: bool) -> list[str]:
    """An attachment pass as counts; with `researcher`, also the ordinals (and works and
    documents) behind each count, which must not be shown to agents."""
    lines = [
        f"attached: {len(report.attached)}",
        f"already attached: {len(report.already_attached)}",
        f"not promoted: {len(report.not_promoted)}",
        f"unresolved: {len(report.unresolved)}",
        f"attachment missing: {len(report.attachment_missing)}",
        f"identity unchecked: {len(report.identity_unchecked)}",
    ]
    if researcher:
        lines += [f"attached: {o} {w} {d}" for o, w, d in report.attached]
        for label, ordinals in (
            ("already attached", report.already_attached),
            ("not promoted", report.not_promoted),
            ("unresolved", report.unresolved),
            ("attachment missing", report.attachment_missing),
            ("identity unchecked", report.identity_unchecked),
        ):
            if ordinals:
                lines.append(f"{label} ordinals: {', '.join(str(o) for o in ordinals)}")
    return lines


def cycle_lines(slug: str, summary: CycleSummary | None) -> list[str]:
    """One project's watch result: nothing due, or the cycle with a line per source."""
    if summary is None:
        return [f"{slug}: nothing due"]
    lines = [
        f"{slug}: cycle {summary.cycle_id} {summary.status.value} "
        f"({len(summary.run_ids)} runs, {len(summary.new_work_ids)} new works)"
    ]
    for c in summary.counts:
        extra = "" if c.disappeared is None else f", {c.disappeared} no longer returned"
        extra += "" if c.window_missed is None else f", {c.window_missed} missed by windows"
        lines.append(
            f"  {c.source}: {c.complete_runs}/{c.runs} queries complete, {c.retrieved} records, "
            f"{c.new_works} new, {c.duplicates_in_cycle} duplicate in cycle{extra}"
        )
    return lines


def development_view_lines(view: DevelopmentView) -> list[str]:
    """The default view: counts, then one line per record keyed by its hash, in hash order.

    No ordinal or row number is printed, so the output says nothing about which records are held
    out beyond their count.
    """
    lines = [f"records shown: {len(view.records)}  held out: {view.held_out}"]
    lines.append("record  outcome  year  identifier  title")
    for r in view.records:
        identifier = f"doi:{r.doi}" if r.doi else f"arxiv:{r.arxiv}" if r.arxiv else "-"
        year = str(r.year) if r.year is not None else "-"
        lines.append(
            f"sha256:{r.record_sha256[:16]}  {r.outcome.value}  {year}  {identifier}"
            f"  {r.title or '-'}"
        )
    return lines


def watch_status_lines(slug: str, status: WatchStatus) -> list[str]:
    """Per-source due state of one project's watch."""
    if not status.has_plan:
        return [f"{slug}: no watch_plan"]
    lines = [f"{slug}: protocol {status.protocol_id}, open cycle {status.open_cycle or 'none'}"]
    for s in status.sources:
        due = "due now" if s.due else f"next due {s.next_due:%Y-%m-%d %H:%M}"
        window = f", window from {s.window_start}" if s.window_start else ""
        replay = ", full replay next" if s.full_replay_next else ""
        lines.append(
            f"  {s.source}: {s.mode}, every {s.interval_days} d, {due}{window}{replay}, "
            f"{s.consecutive_failures} consecutive failures"
        )
    return lines


def extract_summary_lines(summary: ExtractSummary) -> list[str]:
    """Extractions with their counts, then the works that were skipped and why."""
    lines = [f"{len(summary.extractions)} extraction(s), {len(summary.skipped)} skipped"]
    for r in summary.extractions:
        states = ", ".join(f"{k.value} {v}" for k, v in r.states.items() if v)
        flags = f" [{', '.join(r.flags)}]" if r.flags else ""
        lines.append(f"  {r.work_id}: {r.entries} entries, {r.markers} markers ({states}){flags}")
    lines += [f"  skipped {s.work_id}: {s.reason}" for s in summary.skipped]
    return lines


def reference_counts_lines(counts: ReferenceCounts) -> list[str]:
    return [f"{name}: {value}" for name, value in counts.model_dump().items()]


def reference_page_lines(page: Page) -> list[str]:
    """One line per entry: extraction:ordinal, state, linked work, year, the stated title."""
    lines = [
        f"{i.extraction_id}:{i.ordinal} {i.state.value} {i.work_id or '-'} "
        f"{i.year or '-'} {i.title or i.anchor}"
        for i in page.items
    ]
    more = "" if page.next_after is None else f"; next --after {page.next_after}"
    return [*lines, f"({len(page.items)} of {page.total}{more})"]


def _candidate_line(c: RoundCandidate) -> str:
    flag = " (no source record)" if c.no_source_record else ""
    return f"  cited by {c.cited_by_included} included work(s): {c.work_key}{flag}"


def round_plan_lines(direction: str, result: RoundResult, gaps: list[ValidationIssue]) -> list[str]:
    """A dry run: whether the round is allowed and why not, the plan's gaps, the candidates
    ranked by how many included works cite them, and the queries."""
    state = result.state
    verdict = "allowed" if state.allowed else "refused"
    lines = [f"{direction} round {state.round_no}: {verdict}"]
    lines += [f"  {i.field}: {i.reason}" for i in state.refusals]
    lines += [f"  note: {n}" for n in state.notes]
    lines += [f"  plan gap {i.field}: {i.reason}" for i in gaps]
    lines.append(f"{len(result.candidates)} candidate(s)")
    lines += [_candidate_line(c) for c in result.candidates]
    lines.append(f"{len(result.queries)} query(ies), {len(result.unqueryable)} unqueryable")
    lines += [f"  {q.source}: {q.text}" for q in result.queries]
    lines += [f"  not extracted {w}: {why}" for w, why in result.unextracted]
    lines.append(f"{result.no_document} work(s) with no document: listed, not blocking")
    return lines


def round_result_lines(result: RoundResult) -> list[str]:
    return [
        f"round {result.round_id}: {len(result.runs)} queries run, {result.new_works} new works"
    ]


def comparison_lines(comparison: Comparison) -> list[str]:
    lines = [
        f"round {comparison.round_id} against chase rounds {', '.join(comparison.chase_rounds)}",
        f"both: {len(comparison.both)}",
        f"document only: {len(comparison.document_only)}",
        f"metadata only: {len(comparison.metadata_only)}",
    ]
    lines += [f"note: {n}" for n in comparison.notes]
    return lines


def contribution_status_lines(status: ContributionStatus) -> list[str]:
    """The contribution counts, one line each; the ids of works without references are listed."""

    def counts(values: dict[str, int]) -> str:
        return ", ".join(f"{name} {n}" for name, n in values.items()) or "none"

    lines = [
        f"units: {counts(status.units)}",
        f"items by kind: {counts(status.items_by_kind)}",
        f"not-stated: {counts(status.not_stated)}",
        f"cited-entry markers: {counts(status.markers)}",
        f"no-references: {len(status.no_references)}",
    ]
    lines += [f"  {work}" for work in status.no_references]
    lines.append(f"other-conversion: {len(status.other_conversion)}")
    lines += [f"  {work}" for work in status.other_conversion]
    lines.append(f"closed without items: {len(status.closed_without_items)}")
    lines += [
        f"  {unit.work_id}  pass {unit.pass_label.value}  reason: {unit.reason or '-'}"
        for unit in status.closed_without_items
    ]
    return lines


def contribution_item_lines(items: list[ItemView]) -> list[str]:
    """One item per two lines: its kind, name, cited entry and marker state, then its quote."""
    if not items:
        return ["no items"]
    lines: list[str] = []
    for item in items:
        entry = "-" if item.cited_entry is None else str(item.cited_entry)
        marker = "" if item.cited is None else f" ({item.cited.marker})"
        stale = "  [stale]" if item.stale else ""
        lines.append(
            f"{item.extraction_id}  {item.work_id}  pass {item.pass_label.value}  "
            f"{item.item_kind}{_absent(item)}  name {item.name or '-'}  entry {entry}{marker}"
            f"  anchor {item.anchor or '-'}{stale}"
        )
        lines.append(f"  quote: {item.quote or '-'}")
    return lines


def _absent(item: ItemView) -> str:
    return f" ({item.absent_kind})" if item.absent_kind else ""


def relation_lines(views: list[RelationView], notes: Mapping[str, str]) -> list[str]:
    """One relation per line with its effective status, reason, staleness and basis; an agent's
    note, when it gave one, on the next line labelled `agent-note` (it is not evidence)."""
    if not views:
        return ["no relations"]
    lines: list[str] = []
    for v in views:
        reason = "" if v.status_reason is None else f" ({v.status_reason.value})"
        stale = f"  stale: {', '.join(v.stale_reasons)}" if v.stale_reasons else ""
        flags = f"  flags: {', '.join(v.flags)}" if v.flags else ""
        basis = v.basis_item or "-"
        lines.append(
            f"{v.relation_id}  {v.source_work} {v.edge_type} {v.target}  {v.effective.value}"
            f"{reason}  basis {basis}{stale}{flags}"
        )
        if v.relation_id in notes:
            lines.append(f"  agent-note: {notes[v.relation_id]}")
    return lines


def idea_lines(views: list[IdeaView]) -> list[str]:
    if not views:
        return ["no ideas"]
    return [
        f"{v.idea_id}  {v.state}  {v.name}  origin {v.origin}  members {len(v.members)}"
        f" (effective {len(v.effective_members)})"
        + (f"  into {v.merged_into}" if v.merged_into else "")
        for v in views
    ]


def idea_candidate_lines(candidates: list[IdeaCandidate]) -> list[str]:
    if not candidates:
        return ["no candidates"]
    return [f"{c.work_id}  {', '.join(c.reasons)}" for c in candidates]


def _filter_line(filter_: Mapping[str, object]) -> str:
    statuses = ", ".join(str(s) for s in filter_.get("statuses", []))  # type: ignore[attr-defined]
    types = ", ".join(str(t) for t in filter_.get("edge_types", []))  # type: ignore[attr-defined]
    ideas = "ideas on" if filter_.get("include_ideas") else "ideas off"
    return f"filter: statuses {statuses}; edge types {types}; {ideas}"


def graph_status_lines(status: GraphStatus) -> list[str]:
    """Counts of the lineage graph, naming the filter they were made with."""
    lines = [_filter_line(status.filter)]
    lines.append("nodes: " + ", ".join(f"{k} {v}" for k, v in status.nodes.items()))
    for edge_type, counts in status.edges.items():
        lines.append(f"{edge_type}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    lines.append(
        f"unextracted {len(status.unextracted)}; no references {len(status.no_references)}; "
        f"not-stated base ideas {status.not_stated}; uncited base ideas {status.uncited_base}"
    )
    return lines


def graph_query_lines(result: GraphQueryResult) -> list[str]:
    """A query's answer: header, the path when it is one, then edges with their statuses."""
    depth = "" if result.depth is None else f" depth {result.depth}"
    flags = (" (depth clamped)" if result.depth_clamped else "") + (
        " (truncated)" if result.truncated else ""
    )
    lines = [_filter_line(result.filter), f"{result.query}{depth}{flags}"]
    ids = [str(n["id"]) for n in result.nodes]
    if result.query == "path":
        lines.append(" -> ".join(ids) if ids else "no path")
    for edge in result.edges:
        lines.append(
            f"{edge['source']} -> {edge['target']}  {edge['type']}  {edge['status']}  {edge['id']}"
        )
    if result.categories is not None:
        for name, works in result.categories.items():
            lines.append(f"{name}: {len(works)}")
            lines.extend(f"  {w}" for w in works)
    elif result.query != "path":
        lines.extend(f"node {n['id']} ({n['type']}, {n['scope'] or '-'})" for n in result.nodes)
    return lines


def conclusion_lines(diff: ConclusionDiff) -> list[str]:
    """One conclusion's computed state: id, state, predicate values, affected basis references and
    the fact changes of its groups. No statement."""
    lines = [f"{diff.conclusion_id}  {diff.state}"]
    if diff.predicate_before is not None or diff.predicate_now is not None:
        lines.append(f"  predicate: {diff.predicate_before} -> {diff.predicate_now}")
    lines += [f"  affected: {reference}" for reference in diff.affected]
    if diff.facts is not None:
        for group in diff.facts.groups:
            lines.append(f"  group {group.group_id}: rows {group.rows_delta:+d}")
            if group.best_changed is not None:
                lines.append(f"    best row: {group.best_changed[0]} -> {group.best_changed[1]}")
    return lines

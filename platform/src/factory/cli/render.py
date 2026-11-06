"""Markdown and text renderings of the report models for the CLI. Formatting only: every figure
is read from the model, so the CLI and the MCP tools cannot differ (R-05)."""

import json
from collections.abc import Mapping, Sequence

from factory.document.optional import ConverterInfo
from factory.errors import ValidationIssue
from factory.model.conclusions import ConclusionDiff
from factory.model.document import FailureReason
from factory.model.drafts import DraftAuditReport, Outline
from factory.model.intuition import (
    HistoryEntry,
    LayerCounts,
    LayerGraph,
    LayerHidden,
    StoredSource,
)
from factory.model.references import Decision, LinkState
from factory.model.regions import EdgeBasis, RegionMemberProposed
from factory.model.screening import PassLabel
from factory.regions.rules import MemberType
from factory.services.agreement import DecisionView
from factory.services.audit import AuditReport
from factory.services.benchmark_ledger import LedgerGroup
from factory.services.cards import CardSummary, CardView
from factory.services.check import LAYER_CHECK_CODES, CheckReport, Finding
from factory.services.concepts import ConceptLinkList, ConceptList, ConceptView
from factory.services.contributions import ContributionStatus, ItemView
from factory.services.coverage import CoverageReport, Ratio
from factory.services.dedup import MergeRow
from factory.services.directions import RegistryPage
from factory.services.discovery import DiscoveryReport
from factory.services.document_convert import ConvertSummary, DocumentStatus
from factory.services.document_read import DocumentPage
from factory.services.drafts import DraftRow, SentenceRow, StatusRow
from factory.services.evaluation_view import EvaluationDetail
from factory.services.experiments import ExperimentView
from factory.services.extraction import UnitState
from factory.services.extraction_agreement import (
    ExtractionAgreement,
    FieldDisagreement,
    FieldView,
)
from factory.services.extraction_audit import AuditEvidence, ExtractionAuditReport
from factory.services.finders import ConflictPage, ContradictionView, GapReport
from factory.services.fulltext import FetchSummary
from factory.services.fulltext_import import ImportReport
from factory.services.fulltext_status import FulltextStatus
from factory.services.gate_status import GateStatusRow
from factory.services.hypotheses import HypothesisView
from factory.services.ideas import IdeaCandidate, IdeaView
from factory.services.import_admit import AdmissionSummary
from factory.services.import_attach import AttachReport
from factory.services.import_describe import RowProblem
from factory.services.import_resolve import ImportResolutionSummary
from factory.services.imports import (
    DevelopmentView,
    ImportListing,
    ImportSummary,
    RecordRow,
)
from factory.services.inbox import InboxPage, ResolveOutcome
from factory.services.interpretations import InterpretationList, InterpretationView
from factory.services.leads import LeadView
from factory.services.lineage import GraphQueryResult, GraphStatus
from factory.services.matching import MatchPage
from factory.services.miner_report import MinerCalibrationReport
from factory.services.mining import MinerListing, MineStatus
from factory.services.modules.listing import ModuleRow
from factory.services.prisma import UNCONVERTED, PrismaFlow, SearchReport
from factory.services.prisma_update import UpdateFlow
from factory.services.properties import PropertyView
from factory.services.protocol import ProtocolView
from factory.services.question import QuestionView
from factory.services.references import ExtractSummary, Page, ReferenceCounts
from factory.services.regions import ExportRow, RegionState, VersionInfo
from factory.services.relations import RelationView
from factory.services.snowball import Comparison, RoundCandidate, RoundResult
from factory.services.trace import TraceNode
from factory.services.watch import CycleSummary, WatchStatus
from factory.services.xruns import XrunView


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

    def one(finding: Finding) -> str:
        refs = f"  [{', '.join(finding.refs)}]" if finding.refs else ""
        return f"{finding.severity}  {finding.code}  {finding.message}{refs}"

    layer = [f for f in report.findings if f.code in LAYER_CHECK_CODES and f.code != "layer-leak"]
    lines += [one(f) for f in report.findings if f not in layer]
    if layer:
        lines.append("interpretation layer (not evidence):")
        lines += [f"  {one(f)}" for f in layer]
        lines.append(f"evidence ok: {'yes' if report.evidence_ok else 'no'}")
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
        ("identity unchecked (--accept FILE to vouch for one)", report.identity_unchecked),
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
    for change in status.changed_sources:
        lines.append(
            f"source changed: {change.document_id}  {change.work_id}  {change.observed_hash}"
        )
    return lines


_NEEDS_A_CONVERTER = (FailureReason.NO_CONVERTER, FailureReason.CONVERTER_UNAVAILABLE)


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


def converter_lines(infos: list[ConverterInfo]) -> list[str]:
    """One line per converter: name, whether decision 49 chose it, what it accepts, its licence,
    then its version or why it cannot run."""
    lines = []
    for info in infos:
        chosen = "default" if info.default else "optional"
        state = f"ready  {info.version}" if info.available else f"unavailable  {info.reason}"
        lines.append(f"{info.name}  {chosen}  {' '.join(info.accepts)}  {info.licence}  {state}")
    return lines


def protocol_view_lines(view: ProtocolView) -> list[str]:
    """The id, status, PRESS state and amendments, then the whole spec as JSON."""
    if view.spec is None:
        return ["no protocol recorded yet"]
    lines = [
        f"protocol: {view.protocol_id}",
        f"status: {view.status}",
        f"press: {view.press}",
        f"amendments: {len(view.amendments)}",
    ]
    lines.extend(
        f"  {row.amendment_id}  {row.from_version} -> {row.to_version}  {row.reason}"
        for row in view.amendments
    )
    lines.append(json.dumps(view.spec.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return lines


def question_view_lines(view: QuestionView) -> list[str]:
    """The id and the latest raw goal, then the spec as JSON."""
    lines = [] if view.raw_goal is None else [f"goal: {view.raw_goal}"]
    if view.spec is None:
        return [*lines, "no question recorded yet"]
    lines.insert(0, f"question: {view.question_id}")
    lines.append(json.dumps(view.spec.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return lines


def merge_lines(merges: Sequence[MergeRow]) -> list[str]:
    """One line per merge: id, status, rule, primary and absorbed works, and a reversal's reason."""
    if not merges:
        return ["no merge yet"]
    lines = []
    for row in merges:
        absorbed = ", ".join(row.absorbed or ())
        why = "" if row.reason is None else f"  ({row.reason})"
        lines.append(
            f"{row.merge_id}  {row.status.value}  {row.rule}  {row.primary} <- {absorbed}{why}"
        )
    return lines


def document_status_lines(status: DocumentStatus) -> list[str]:
    """The counts, then each live document: its converter and anchor counts, or not converted.
    Its latest recorded failure follows: `earlier failure` for a converted document, `last failure`
    for one not converted. A document held back by a missing converter ends the list with the
    command that says what is missing."""
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
    if any(not d.converted and d.latest_failure in _NEEDS_A_CONVERTER for d in status.documents):
        lines.append("no converter could run: see `factory document converters`")
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


def miner_listing_lines(listing: list[MinerListing]) -> list[str]:
    """One line per registered miner version."""
    if not listing:
        return ["no registered miners"]
    return [
        f"{m.name} version {m.version} {m.digest} by {m.proposer_kind}, "
        f"{'listed' if m.listed else 'not listed'}"
        for m in listing
    ]


def miner_calibration_lines(report: MinerCalibrationReport) -> list[str]:
    """The calibration of a miner version as the researcher reads it: units, labels, thresholds
    in force and, once complete, the scores."""
    lines = [
        f"calibration {report.calibration_id}: {report.units} unit(s), {report.labelled} "
        f"labelled, {report.closed} mined",
        f"thresholds in force: recall {report.thresholds[0]:.2f}, "
        f"field agreement {report.thresholds[1]:.2f}",
    ]
    if report.reason is not None:
        lines.append(f"cannot pass: {report.reason}")
    if report.score is None:
        lines.append("score: not computed (waits for every unit to be labelled and mined)")
        return lines
    sc = report.score
    lines.append(f"gold rows {sc.gold_rows}, agent rows {sc.agent_rows}, matched {sc.matched}")
    lines.append(
        f"record recall {_rate(sc.recall)}, field agreement {_rate(sc.field_agreement)}, "
        f"precision {_rate(sc.precision)}, verification rate {_rate(sc.verification_rate)}"
    )
    lines.append("result: " + ("passed" if report.passed else "failed"))
    return lines


def mine_status_lines(status: list[MineStatus]) -> list[str]:
    """One line per listed miner: its units by state, rows and agreement."""
    if not status:
        return ["no listed miners"]
    return [
        f"{m.name} version {m.version}: units {m.units} (closed {m.closed}, open {m.open}, "
        f"stale {m.stale}), rows {m.rows}, agreement {_rate(m.agreement)}"
        for m in status
    ]


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


def import_record_lines(
    records: list[RecordRow], names: Mapping[int, str], hints: Mapping[int, str]
) -> list[str]:
    """One line per record: ordinal, part, outcome, link state, year, identifier, title, then the
    file and the first-page hint when there are any. The researcher's view."""
    head = "ordinal  part  outcome  state  year  identifier  title"
    lines = [head + ("  file" if names else "") + ("  hint" if hints else "")]
    for r in records:
        identifier = f"doi:{r.doi}" if r.doi else f"arxiv:{r.arxiv}" if r.arxiv else "-"
        year = str(r.year) if r.year is not None else "-"
        file = f"  {names.get(r.ordinal, '-')}" if names else ""
        hint = f"  {hints.get(r.ordinal, '-')}" if hints else ""
        lines.append(
            f"{r.ordinal}  {r.part}  {r.outcome.value}  {r.link_state or '-'}  {year}"
            f"  {identifier}  {r.title or '-'}{file}{hint}"
        )
    return lines


def import_describe_lines(import_id: str, described: int, rejected: list[RowProblem]) -> list[str]:
    """Descriptions applied, each CSV row refused, and the command that comes next."""
    lines = [f"described: {described}"]
    lines += [f"line {r.line}: {'; '.join(r.reasons)}" for r in rejected]
    if described:
        lines.append(f"next: factory import resolve {import_id} --described")
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
    if summary.unadmittable:
        lines.append(
            f"not admitted, no title: {summary.unadmittable} "
            f"(factory import show {summary.import_id} --researcher, then import describe)"
        )
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
    if report.autonomy:
        counts = ", ".join(f"{level} {n}" for level, n in report.autonomy.items())
        lines.append(f"resolution decisions by autonomy: {counts}")
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


def property_lines(views: list[PropertyView]) -> list[str]:
    if not views:
        return ["no properties"]
    return [
        f"{v.key}  {v.state}  {v.definition.kind.value}  match {v.definition.match.value}  "
        f"for {v.definition.applies_to}"
        + (f"  allowed {', '.join(v.definition.allowed)}" if v.definition.allowed else "")
        + (f"  into {v.merged_into}" if v.merged_into else "")
        for v in views
    ]


def card_lines(cards: list[CardSummary]) -> list[str]:
    if not cards:
        return ["no cards"]
    return [
        f"{c.card_id}  {c.kind}  {c.subject}  assertions {c.assertions}  owner {c.owner}"
        for c in cards
    ]


def _shown_value(value: str | tuple[str, ...] | bool, unit: str | None) -> str:
    text = ", ".join(value) if isinstance(value, tuple) else str(value).lower()
    return f"{text} {unit}" if unit else text


def card_view_lines(view: CardView) -> list[str]:
    """The card, one line per assertion, labelled by its effective status; a stale assertion
    names why, and what the filter left out is counted."""
    lines = [f"{view.card_id}  {view.kind}  {view.subject}  owner {view.owner}"]
    for a in view.assertions:
        label = a.effective if a.effective == a.status else f"{a.effective} ({a.status})"
        why = f"  [{', '.join(a.stale_reasons)}]" if a.stale_reasons else ""
        lines.append(
            f"  {a.assertion_id}  {a.property} = {_shown_value(a.value, a.unit)}  "
            f"{label}  basis {a.basis_kind}{why}"
        )
    if not view.assertions:
        lines.append("  no assertions shown")
    if view.hidden_counts:
        hidden = ", ".join(f"{n} {k}" for k, n in sorted(view.hidden_counts.items()))
        lines.append(f"  not shown: {hidden}")
    return lines


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
    if status.layer is not None:
        lines += layer_counts_lines(status.layer)
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
    if result.layer is not None:
        lines += layer_graph_lines(result.layer)
    return lines


# --- The interpretation layer (slice 3c, plan G3-C): each item shows `interpretation · state` ---

LAYER_HEADER = "interpretation layer (not evidence)"


def _hidden_line(hidden: LayerHidden) -> str:
    i, c = hidden.interpretations, hidden.concepts
    return (
        f"hidden: interpretations wrong {i.wrong}, superseded {i.superseded}; "
        f"concepts unapproved {c.unapproved}, wrong {c.wrong}, merged {c.merged}; "
        f"links inferred {c.links_inferred}, rejected {c.links_rejected}; "
        f"edges with a hidden endpoint {hidden.endpoint_hidden}"
    )


def layer_counts_lines(counts: LayerCounts) -> list[str]:
    """The layer's own counts, in a section of their own (no total with the evidence)."""
    lines = [LAYER_HEADER]
    lines.append(
        "interpretations: " + ", ".join(f"{k} {v}" for k, v in counts.interpretations.items())
    )
    lines.append("concepts: " + ", ".join(f"{k} {v}" for k, v in counts.concepts.items()))
    lines.append(f"explains edges shown: {counts.explains}")
    lines.append("uses links: " + ", ".join(f"{k} {v}" for k, v in counts.uses.items()))
    lines.append(_hidden_line(counts.hidden))
    return lines


def layer_graph_lines(layer: LayerGraph) -> list[str]:
    """The layer attached to a query: nodes, then edges, each labelled with its review state."""
    lines = [LAYER_HEADER]
    for n in layer.nodes:
        flags = f"  [{', '.join(n.flags)}]" if n.flags else ""
        lines.append(f"{n.node_type} {n.node_id}  {n.label}{flags}  {n.name or ''}".rstrip())
    for e in layer.edges:
        lines.append(f"{e.source} -> {e.target}  {e.edge_type}  {e.label}  {e.edge_id}")
    lines.append(_hidden_line(layer.hidden))
    return lines


def _flag_text(flags: Sequence[str]) -> str:
    return f"  [{', '.join(flags)}]" if flags else ""


def _source_lines(sources: Sequence[StoredSource]) -> list[str]:
    lines = []
    for i, s in enumerate(sources):
        if s.kind == "quote":
            lines.append(
                f"  source {i} {s.role}: quote of {s.work_id} {s.conversion_id}/{s.anchor}"
            )
            lines.append(f'    "{s.quote}"')
        else:
            cited = s.reference or s.work_id
            lines.append(f"  source {i} {s.role}: citation {cited} ({s.link_state or 'work'})")
    return lines


def interpretation_list_lines(result: InterpretationList) -> list[str]:
    """One labelled line per interpretation, then the hidden counts."""
    lines = []
    for v in result.items:
        flags = [
            *(["self-reviewed"] if v.self_reviewed else []),
            *(["source-stale"] if v.source_stale else []),
        ]
        lines.append(
            f"{v.interpretation_id}  {v.label}  {v.target_kind} {v.target}  {v.author}"
            f"{_flag_text(flags)}  {v.text}"
        )
    if not result.items:
        lines.append("no interpretations")
    lines.append(f"hidden: wrong {result.hidden.wrong}, superseded {result.hidden.superseded}")
    if result.next_cursor:
        lines.append(f"more after {result.next_cursor}")
    return lines


def interpretation_lines(view: InterpretationView, blob: str | None) -> list[str]:
    """One interpretation in full: label, target, text, sources with their quotes and anchors,
    the writer and the content of the input the writer saw."""
    flags = [
        *(["self-reviewed"] if view.self_reviewed else []),
        *(["source-stale"] if view.source_stale else []),
    ]
    lines = [
        f"{view.interpretation_id}  {view.label}{_flag_text(flags)}",
        f"  target: {view.target_kind} {view.target}",
        f"  author: {view.author}; writer: {view.writer}",
        f"  text: {view.text}",
        *_source_lines(view.sources),
    ]
    if view.source_stale:
        lines.append("  stale documents: " + ", ".join(view.source_stale))
    if view.input_blob is not None:
        lines.append(
            f"  input_blob {view.input_blob}: {blob if blob is not None else 'not readable'}"
        )
    return lines


def history_lines(entries: Sequence[HistoryEntry]) -> list[str]:
    """One line per step: event, kind, state, actor, flags and the review note."""
    lines = []
    for h in entries:
        state = f" {h.state}" if h.state else ""
        extra = ("" if h.folded else " (did not count)") + (
            " (self-reviewed)" if h.self_reviewed else ""
        )
        note = f"  note: {h.note}" if h.note else ""
        lines.append(f"{h.event_id}  {h.kind}{state}  {h.actor}{extra}{note}")
    return lines


def concept_list_lines(result: ConceptList) -> list[str]:
    """One labelled line per concept, then the hidden counts."""
    lines = []
    for v in result.items:
        shown = v.name + (f" ({', '.join(v.aliases)})" if v.aliases else "")
        lines.append(
            f"{v.concept_id}  {v.label}  source {v.source_state}  {shown}{_flag_text(v.flags)}"
        )
    if not result.items:
        lines.append("no concepts")
    h = result.hidden
    lines.append(
        f"hidden: unapproved {h.unapproved}, wrong {h.wrong}, merged {h.merged}; "
        f"links inferred {h.links_inferred}, rejected {h.links_rejected}"
    )
    if result.next_cursor:
        lines.append(f"more after {result.next_cursor}")
    return lines


def concept_lines(view: ConceptView) -> list[str]:
    """One concept in full: label, name and aliases, text, source and quotes, writer, flags."""
    lines = [f"{view.concept_id}  {view.label}{_flag_text(view.flags)}"]
    lines.append(
        f"  name: {view.name}" + (f" (aliases: {', '.join(view.aliases)})" if view.aliases else "")
    )
    if view.merged_into:
        lines.append(f"  merged into: {view.merged_into}")
    if view.text:
        lines.append(f"  text: {view.text}")
    if view.source is not None:
        work = f" work {view.source.work_id}" if view.source.work_id else ""
        lines.append(
            f"  source ({view.source_state}): {view.source.kind}, {view.source.citation}{work}"
        )
    else:
        lines.append(f"  source ({view.source_state}): none")
    lines += _source_lines(view.quotes)
    lines.append(f"  author: {view.author}; writer: {view.writer}")
    return lines


def concept_link_lines(result: ConceptLinkList) -> list[str]:
    """One labelled line per link, then the hidden counts."""
    lines = []
    for v in result.items:
        basis = (
            v.basis_kind if v.quote is None else f"quote {v.quote.conversion_id}/{v.quote.anchor}"
        )
        lines.append(
            f"{v.link_id}  {v.label}  {v.from_kind} {v.from_node} uses {v.concept_id}  "
            f"{v.status_reason}  basis {basis}"
        )
    if not result.items:
        lines.append("no concept links")
    h = result.hidden
    lines.append(f"hidden: links inferred {h.links_inferred}, rejected {h.links_rejected}")
    if result.next_cursor:
        lines.append(f"more after {result.next_cursor}")
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


# --- Matching and finders (slice 6, H-B): computed candidates, never conclusions ---


def match_lines(page: MatchPage) -> list[str]:
    lines = [
        f"match {page.problem_id}  match_key {page.match_key}  vocabulary {page.vocabulary_version}"
        f"  statuses {', '.join(page.statuses)}  candidates {page.candidates}"
    ]
    if not page.rows:
        lines.append("no cards")
    for r in page.rows:
        flag = "  transfer" if r.transfer else ""
        lines.append(
            f"{r.card_id}  {r.subject}  satisfied {len(r.satisfied)}  "
            f"conflicting {len(r.conflicting)}  unknown {len(r.unknown)}{flag}"
        )
        for label, keys in (("conflicting", r.conflicting), ("unknown", r.unknown)):
            if keys:
                lines.append(f"  {label} {', '.join(keys)}")
        if r.evidence_groups:
            lines.append(f"  groups {', '.join(r.evidence_groups)}")
    if page.next_after is not None:
        lines.append(f"more: --after {page.next_after}")
    return lines


def conflict_lines(page: ConflictPage) -> list[str]:
    if not page.conflicts:
        return ["no conflicts"]
    lines = []
    for c in page.conflicts:
        differs = ", ".join(c.differs_in) if c.differs_in else "-"
        lines.append(
            f"{c.group_id}  {c.method}{'' if c.variant is None else ' / ' + c.variant}  "
            f"{c.row_a} {c.value_a} ({c.work_a})  vs  {c.row_b} {c.value_b} ({c.work_b})  "
            f"difference {c.relative_difference}  differs_in {differs}"
        )
    if page.next_after is not None:
        lines.append(f"more: --after {page.next_after}")
    return lines


def gap_lines(report: GapReport) -> list[str]:
    lines = [
        f"gaps {report.rows_axis} x {report.columns_axis}  cells {report.cells}  "
        f"filled {report.filled}  empty {len(report.empty)}  gap_key {report.gap_key}",
        report.statement,
    ]
    lines += [f"{c.row}  {c.column}" for c in report.empty]
    return lines


def gate_lines(rows: list[GateStatusRow]) -> list[str]:
    """One block per decision gate: policy and its source, acts per autonomy level, the latest
    audit and the acts below the current policy."""
    lines: list[str] = []
    for row in rows:
        policy = row.policy
        if row.fraction is not None and row.minimum is not None:
            policy += f"({row.fraction:g}, {row.minimum})"
        counts = ", ".join(f"{level} {n}" for level, n in row.counts.items())
        lines.append(f"{row.gate_id}: {policy} from the {row.source}, floor {row.floor}")
        lines.append(f"  acts: {counts}")
        audit = row.audit
        if audit is not None and audit.sample_size is not None:
            rate = "n/a" if audit.error_rate is None else f"{audit.error_rate:.3f}"
            lines.append(
                f"  audit {audit.audit_id}: sample {audit.sample_size}, labelled "
                f"{audit.labelled}, incorrect {audit.incorrect}, error rate {rate}"
            )
        elif audit is not None:
            lines.append(f"  audit {audit.audit_id}")
        if row.below_policy:
            lines.append(f"  below policy: {row.below_policy}")
    return lines


def module_lines(rows: list[ModuleRow]) -> list[str]:
    """One block per declared module: counts, task kinds, sections, gates with their floor,
    checks, strategies and the family note."""
    lines: list[str] = []
    for row in rows:
        lines.append(f"{row.name} ({row.kind}): {row.events} event types, {row.tables} tables")
        if row.task_kinds:
            lines.append(f"  task kinds: {', '.join(row.task_kinds)}")
        if row.sections:
            lines.append(f"  protocol sections: {', '.join(row.sections)}")
        if row.gates:
            lines.append(f"  gates: {', '.join(f'{g.gate_id} ({g.floor})' for g in row.gates)}")
        if row.checks:
            lines.append(f"  checks: {', '.join(row.checks)}")
        if row.strategies:
            lines.append(f"  strategies: {', '.join(row.strategies)}")
        if row.note:
            lines.append(f"  note: {row.note}")
    return lines


def contradiction_lines(views: list[ContradictionView]) -> list[str]:
    if not views:
        return ["no contradictions"]
    return [
        f"{v.contradiction_id}  {v.state}  {v.ref_a} ({v.work_a})  vs  {v.ref_b} ({v.work_b})"
        for v in views
    ]


# --- Regions (slice 3d, Regions-A) ---


def _counts(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items())) or "no members"


def region_lines(states: Sequence[RegionState]) -> list[str]:
    """One region per line: id, kind (and slot for a focus), name, latest version, review state,
    live counts and the drift since the snapshot. Counts are read from the model."""
    if not states:
        return ["no regions"]
    lines: list[str] = []
    for s in states:
        slot = "" if s.facet is None else f" {s.facet.question_id}:{s.facet.slot}"
        version = s.latest_version or "no snapshot"
        drift = f"  drift +{s.drift_added} -{s.drift_removed}" if s.latest_version else ""
        lines.append(
            f"{s.region_id}  {s.kind.value}{slot}  {s.name}  {version}  {s.review_state}  "
            f"live {_counts(s.live_counts)}{drift}"
        )
        if s.live_error is not None:
            lines.append(f"  not evaluable: {s.live_error}")
    return lines


def version_lines(info: VersionInfo) -> list[str]:
    latest = "latest" if info.latest else "older"
    return [
        f"{info.version}  {info.region_id}  {latest}  {info.review_state}  {_counts(info.counts)}"
    ]


def proposal_lines(proposals: Sequence[RegionMemberProposed]) -> list[str]:
    if not proposals:
        return ["no open proposals"]
    return [
        f"{p.proposal_id}  {p.member_type.value} {p.member}  "
        f"{p.basis.kind} {p.basis.edge_id if isinstance(p.basis, EdgeBasis) else p.basis.anchor}"
        for p in proposals
    ]


def export_lines(version: str, rows: Sequence[ExportRow], *, as_json: bool) -> list[str]:
    """A version's members with their basis, one per line (tab separated), or one JSON document.
    Ids, types and numbers only."""
    if as_json:
        document = {
            "version": version,
            "members": [
                {
                    "type": r.member_type.value,
                    "id": r.member,
                    "rules": r.rules,
                    "decision": r.decision,
                }
                for r in rows
            ],
        }
        return [json.dumps(document, sort_keys=True, indent=2)]
    return [
        f"{r.member_type.value}\t{r.member}\trules={','.join(str(i) for i in r.rules) or '-'}"
        f"\tdecision={r.decision or '-'}"
        for r in rows
    ]


def member_lines(members: Sequence[tuple[MemberType, str]]) -> list[str]:
    return [f"  {kind.value} {member}" for kind, member in members]


def diff_lines(
    added: Sequence[tuple[MemberType, str]], removed: Sequence[tuple[MemberType, str]]
) -> list[str]:
    return [
        f"added {len(added)}  removed {len(removed)}",
        *(f"+ {kind.value} {member}" for kind, member in added),
        *(f"- {kind.value} {member}" for kind, member in removed),
    ]


def lead_lines(views: list[LeadView]) -> list[str]:
    if not views:
        return ["no leads"]
    lines: list[str] = []
    for v in views:
        shown = ", ".join(f"{t.kind.value} {t.ref}" for t in v.triggers)
        lines.append(f"{v.lead_id}  {v.state}  {v.text}")
        lines.append(f"    triggers: {shown}")
        if v.prior:
            more = "" if v.prior_total == len(v.prior) else f" of {v.prior_total}"
            lines.append(f"    prior: {', '.join(v.prior)}{more}")
        if v.framework:
            lines.append(f"    framework: {v.framework}")
    return lines


def hypothesis_lines(views: list[HypothesisView]) -> list[str]:
    if not views:
        return ["no hypotheses"]
    return [
        f"{v.hypothesis_id}  {v.h_version}  {v.state}"
        + (f"  autonomy: {v.autonomy}" if v.autonomy == "agent" else "")
        + (f"  [{', '.join(v.flags)}]" if v.flags else "")
        + f"  {v.spec.statement}"
        for v in views
    ]


def hypothesis_detail_lines(v: HypothesisView) -> list[str]:
    lines = [
        f"{v.hypothesis_id}  {v.h_version}  {v.state}",
        f"  {v.spec.statement}",
        f"  falsifier: {v.falsifier}",
        f"  kind: {v.spec.kind}; rule: {v.spec.decision_rule.rule}",
    ]
    if v.flags:
        lines.append(f"  flags: {', '.join(v.flags)}")
    if v.registration is not None:
        lines.append(f"  registered by {v.autonomy}: {v.registration}")
        if v.autonomy == "agent":
            lines.append("  autonomy: agent (never reported as confirmatory)")
    if v.reviews:
        lines.append(f"  reviews: {', '.join(v.reviews)}")
    if v.conclusion:
        lines.append(f"  conclusion (interpretation): {v.conclusion}")
    return lines


# --- Experiments and runs (slice 6, plan XP-A) -----------------------------------------------


def experiment_lines(views: list[ExperimentView]) -> list[str]:
    if not views:
        return ["no experiment designs"]
    return [
        f"{v.experiment_id}  {v.e_version}  {v.state}  {v.hypothesis}"
        + (f"  [{', '.join(v.flags)}]" if v.flags else "")
        for v in views
    ]


def experiment_detail_lines(v: ExperimentView, verdicts: Mapping[str, str]) -> list[str]:
    """A design in the researcher's view. The unlock nonce is never part of it: it is printed once,
    by `factory experiments unlock`."""
    d = v.design
    factor = ", ".join(f"{k}: {a} -> {b}" for k, (a, b) in sorted(d.factor.items()))
    lines = [
        f"{v.experiment_id}  {v.e_version}  {v.state}",
        f"  hypothesis: {v.hypothesis}",
        f"  factor: {factor}",
        f"  seeds: {', '.join(str(s) for s in sorted(d.seeds))}",
        f"  code: {d.code.uri} @ {d.code.commit}; environment: {d.environment}",
        f"  budget: {v.budget.gpu_hours_used} of {v.budget.gpu_hours_budget} GPU-hours; "
        f"{v.budget.runs_registered} of {v.budget.max_runs} runs"
        + ("  OVER BUDGET" if v.budget.over else ""),
    ]
    if v.access_limit is not None:
        reads = sum(1 for n in v.access.values() if n > 0)
        lines.append(
            f"  confirmatory reads: {reads} of {len(v.access)} primary cells; "
            f"limit {v.access_limit} per cell"
        )
    if verdicts:
        lines.append(
            "  baselines: " + ", ".join(f"{k} {word}" for k, word in sorted(verdicts.items()))
        )
    if v.flags:
        lines.append(f"  flags: {', '.join(v.flags)}")
    for dev in v.deviations:
        lines.append(
            f"  deviation ({dev.kind}{', semantic' if dev.semantic else ''}"
            f"{', after unlock' if dev.after_unlock else ''}): {dev.text}"
        )
    return lines


def xrun_lines(runs: Sequence[XrunView]) -> list[str]:
    if not runs:
        return ["no runs"]
    out: list[str] = []
    for r in runs:
        coordinates = ",".join(f"{k}={val}" for k, val in r.cell.universe) or "-"
        line = (
            f"{r.run_id}  {r.state}  {r.cell.arm}  seed {r.cell.seed}  {r.cell.split}  "
            f"[{coordinates}]"
        )
        if r.exploratory:
            line += "  exploratory"
        if r.flags:
            line += f"  [{', '.join(r.flags)}]"
        if r.metrics:
            line += "  " + ", ".join(f"{k}={val}" for k, val in sorted(r.metrics.items()))
        out.append(line)
    return out


# --- Evaluation, ledger and registry (slice 6, plan XP-B) --------------------------------------


def evaluation_lines(r: "EvaluationDetail") -> list[str]:
    p = r.evaluation.payload
    head = f"  evaluation {r.evaluation.event_id}: {p.outcome}, n {p.n}"
    if p.mean is not None:
        head += f", mean {p.mean}"
    if p.ci_low is not None and p.ci_high is not None:
        head += f", {p.level} interval [{p.ci_low}, {p.ci_high}]"
    lines = [head]
    if p.flags:
        lines.append(f"  flags: {', '.join(p.flags)}")
    if p.counts:
        lines.append("  counts: " + ", ".join(f"{k} {v}" for k, v in sorted(p.counts.items())))
    if r.evaluation.supersedes:
        lines.append(f"  supersedes {r.evaluation.supersedes}")
    if r.curve is not None and r.curve.points:
        lines.append("  specification curve (non-primary universes are descriptive, dev split):")
        for pt in r.curve.points:
            where = ", ".join(f"{k}={v}" for k, v in sorted(pt.universe.items())) or "-"
            mark = "primary" if pt.primary else "descriptive"
            lines.append(
                f"    {where}  {mark}  {pt.split}  n {pt.n}  mean {pt.mean}  "
                f"[{pt.ci_low}, {pt.ci_high}]  would be {pt.outcome_descriptive}"
            )
    for a in r.ablations:
        lines.append(
            f"  ablation {a.name} ({a.key}): n {a.n}, effect of removing it {a.mean} "
            f"[{a.ci_low}, {a.ci_high}]"
        )
    for c in r.controls:
        verdict = "not evaluated" if c.passed is None else ("passed" if c.passed else "FAILED")
        lines.append(f"  control {c.name} ({c.kind}): n {c.n}, mean {c.mean}, {verdict}")
    return lines


def ledger_lines(groups: "list[LedgerGroup]") -> list[str]:
    if not groups:
        return ["no evidence groups (the evidence report is empty)"]
    lines: list[str] = []
    for g in groups:
        key = ", ".join(f"{k}={v}" for k, v in g.key)
        lines.append(f"{g.group_id}  {key}")
        for row in g.rows:
            repro: str = row.reproduction
            if row.reproduced is not None:
                repro += f" ({row.reproduced})"
            lines.append(
                f"  {row.row_key}  {row.method_name or '-'}  reported {row.reported}  "
                f"reproduction {repro}"
            )
        for own in g.own_results:
            stats = "" if own.mean is None else f", mean {own.mean} [{own.ci_low}, {own.ci_high}]"
            flags = f" [{', '.join(own.flags)}]" if own.flags else ""
            lines.append(
                f"  own result {own.hypothesis_id}: {own.outcome}, n {own.n}{stats}{flags}"
            )
    return lines


def registry_lines(page: "RegistryPage") -> list[str]:
    if not page.rows:
        return ["no failed directions recorded"]
    lines = [f"{page.total} failed direction(s)"]
    for r in page.rows:
        lines.append(f"{r.direction_id}  {r.source_kind}  {r.reason}")
        lines.append(f"  {r.summary}")
        if r.text:
            lines.append(f"  note: {r.text}")
    if page.next:
        lines.append(f"more: --after {page.next}")
    return lines


# --- Writing (slice 7b, plan W-A) ---------------------------------------------------------------


def outline_lines(outline: Outline) -> list[str]:
    """The outline as ids and codes, one section per block."""
    lines = [f"{outline.outline_id}  as of {outline.as_of or 'the empty log'}"]
    for s in outline.sections:
        lines.append(
            f"{s.section_ref}  ({s.kind}; {len(s.works)} works, {len(s.supports)} supports)"
        )
        for conflict in s.conflicts:
            lines.append(f"  disagreement: {', '.join(conflict)}")
        if s.notes:
            lines.append(f"  notes: {', '.join(s.notes)}")
    return lines


def draft_list_lines(drafts: list[DraftRow]) -> list[str]:
    if not drafts:
        return ["no drafts"]
    return [
        f"{d.draft_id}  {d.kind.value}  {d.outline_ref}  {d.sentences} sentences  {d.title}"
        for d in drafts
    ]


def draft_status_lines(
    draft: DraftRow,
    rows: list[StatusRow],
    audit: DraftAuditReport,
    sheet: list[tuple[str, str, str, str | None]],
) -> list[str]:
    """Counts by status, each sentence's status and reason, and the audit as the researcher reads
    it, its sample listed with the verdicts to label."""
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    lines = [f"{draft.draft_id}  {draft.title}"]
    lines.append("  ".join(f"{k} {counts[k]}" for k in sorted(counts)) or "no sentences")
    for row in rows:
        reason = f"  {row.reason}" if row.reason else ""
        lines.append(f"  {row.sentence_id}  {row.cls.value}  {row.status}{reason}")
    if audit.drawn == 0 and audit.all_drawn == 0:
        return [*lines, "audit: none drawn"]
    rate = "undefined" if audit.rate is None else f"{audit.rate:.3f}"
    above = "  above the ceiling" if audit.above_ceiling else ""
    outdated = "  a verdict is newer than the last draw" if audit.outdated else ""
    every = "" if audit.all_rate is None else f"  (every sample: rate {audit.all_rate:.3f})"
    lines.append(
        f"audit: {audit.labelled}/{audit.drawn} labelled, {audit.incorrect} incorrect, "
        f"rate {rate}{every}{above}{outdated}"
    )
    lines += [
        f"  {audit_id}  {verdict}  {sentence}  {label or 'unlabelled'}"
        for audit_id, verdict, sentence, label in sheet
    ]
    return lines


def draft_detail_lines(
    draft: DraftRow, sentences: list[SentenceRow], rows: list[StatusRow]
) -> list[str]:
    """A draft with its live sentences, their class, flags and supports. Sentence text is the
    author's own; no quote appears here."""
    statuses = {r.sentence_id: r.status for r in rows}
    lines = [f"{draft.draft_id}  {draft.kind.value}  {draft.outline_ref}  {draft.title}"]
    for section in draft.sections:
        lines.append(f"{section.section_id}  {section.heading}")
        for row in (r for r in sentences if r.section_id == section.section_id):
            flags = f"  [{', '.join(f.value for f in row.flags)}]" if row.flags else ""
            lines.append(
                f"  {row.sentence_id}  {row.cls.value}  {statuses[row.sentence_id]}"
                f"  ({row.author}){flags}"
            )
            lines.append(f"    {row.text}")
            if row.supports:
                lines.append(f"    supports: {', '.join(row.supports)}")
    return lines

"""Markdown and text renderings of the report models for the CLI. Formatting only: every figure
is read from the model, so the CLI and the MCP tools cannot differ (R-05)."""

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

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
from factory.model.references import BackwardSelection, Decision, LinkState
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
from factory.services.document_convert import ConversionOutcome, ConvertSummary, DocumentStatus
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
from factory.services.flow_ledger import TOTAL, FlowCounts, LedgerRow
from factory.services.flow_query import FlowPage
from factory.services.flow_skipped import RunGap, SkippedRecord
from factory.services.flow_trails import TrailStep
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
from factory.services.reference_layers import CalibrationState, LayerStatus
from factory.services.references import ExtractSummary, Page, ReferenceCounts, ReResolveSummary
from factory.services.regions import ExportRow, RegionState, VersionInfo
from factory.services.relations import RelationView
from factory.services.results import BatchResult
from factory.services.shared_mining import SharedProject, SharedUnit
from factory.services.snowball import Comparison, RoundCandidate, RoundResult
from factory.services.trace import TraceNode
from factory.services.watch import CycleSummary, WatchStatus
from factory.services.xruns import XrunView


def _background_lines(background: dict[str, int]) -> list[str]:
    """The exclusions kept as background (IDEA-47), a subset view under the exclusion rows."""
    return [
        f"  - of which kept as background: {n} ({criterion})" for criterion, n in background.items()
    ]


def prisma_markdown(flow: PrismaFlow) -> str:
    """The PRISMA 2020 flow as a Markdown list, one line per box."""
    lines = ["# PRISMA 2020 flow", ""]
    lines.append("## Identification")
    lines += [f"- {source}: {n}" for source, n in flow.identified_databases.items()]
    lines += [f"- other methods, {method}: {n}" for method, n in flow.identified_other.items()]
    lines.append(f"- duplicates removed: {flow.duplicates_removed}")
    lines += ["", "## Screening", f"- records screened: {flow.screened}"]
    lines += [f"- excluded, {criterion}: {n}" for criterion, n in flow.excluded.items()]
    lines += _background_lines(flow.background)
    lines.append(f"- pending: {flow.pending}")
    if flow.stop_rule is not None:
        lines.append(
            f"- of which not screened because of the stop: {flow.not_screened_stop} "
            f"(rule: {flow.stop_rule})"
        )
    if flow.unscreened_tolerated:
        lines.append(
            "- of which left unscreened within the declared tolerance (a technical reason): "
            f"{flow.unscreened_tolerated}"
        )
        lines += [f"  - {work}" for work in flow.unscreened_tolerated_works]
    boxes = flow.full_text
    lines += ["", "## Full-text assessment"]
    lines.append(f"- promoted, not yet sought: {boxes.not_sought}")
    lines.append(f"- reports sought: {boxes.sought}")
    lines.append(f"- reports not retrieved: {boxes.not_retrieved}")
    lines += [f"  - {reason}: {n}" for reason, n in boxes.not_retrieved_reasons.items()]
    if boxes.not_retrieved_reasons.get(UNCONVERTED):
        lines.append("  - unconverted works need conversion: run `factory document convert`")
    if boxes.stage_run:
        lines.append(f"- reports assessed for eligibility: {boxes.assessed}")
        lines += [f"- excluded, {criterion}: {n}" for criterion, n in boxes.excluded.items()]
        lines += _background_lines(boxes.background)
        if boxes.awaiting_classification:
            lines.append(f"- awaiting classification: {boxes.awaiting_classification}")
        lines.append(f"- pending at full text: {boxes.pending}")
        lines.append(f"- included at full text: {boxes.included}")
    else:
        lines.append("- not assessed in this review stage (no full-text decisions)")
    lines += ["", "## Included", f"- included: {flow.included}"]
    if flow.included_in_review is not None:
        lines.append(f"- included in the review: {flow.included_in_review}")
    if flow.provisional:
        lines += ["", "The flow is provisional: works are pending."]
    elif boxes.provisional:
        lines += ["", "The flow is provisional: reports are pending or awaiting classification."]
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
    lines.append(f"- promoted, not yet sought: {flow.full_text.not_sought}")
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
    for chosen in report.forward_selections:
        lines.append("")
        lines.append(
            f"## Forward round {chosen.round_id} (round {chosen.round_no}): at most "
            f"{chosen.max_per_work} citing works per source work, ordered by similarity to the "
            f"development seeds ({chosen.model_id}, weights {chosen.weights_hash[:12]})"
        )
        if chosen.topic_filter:
            lines.append(f"- topic filter: `{chosen.topic_filter}`")
        lines += [
            f"- {c.work_id}: matched {c.matched}, held {c.in_corpus}, taken {c.taken}, "
            f"not taken {c.not_taken}"
            for c in chosen.cores
        ]
        lines.append(f"- not taken in all: {chosen.not_taken}")
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
        mark = "* " if item.prioritised else ""
        lines.append(
            f"{mark}{item.item_id}  {item.status}  {outcome}  {item.identifier_kind}:"
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
    """One line per document outcome (document, work, status, reason), then the counts, every
    status always named. An `outdated` outcome carries the hint to use `--upgrade`."""
    lines = [
        f"{o.document_id}  {o.work_id}  {o.status}  {_outcome_reason(o)}" for o in summary.outcomes
    ]
    lines.append(
        f"converted {summary.converted}, unchanged {summary.unchanged}, failed {summary.failed}, "
        f"raw-missing {summary.raw_missing}, restored {summary.restored}, "
        f"outdated {summary.outdated}"
    )
    return lines


def _outcome_reason(outcome: ConversionOutcome) -> str:
    if outcome.reason == "other-converter-version":
        return "older converter version; use --upgrade"
    return outcome.reason if outcome.reason else "-"


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


def human_batch_lines(batch: Mapping[str, Any]) -> list[str]:
    """A batch as a person screens it: what an agent is served, then a file to fill in for
    `factory screen record`. `batch` is the agent view of the batch."""
    lines = [
        f"task {batch['task_id']}: pass {batch['pass_label']}, {batch['phase']} batch, "
        f"protocol {batch['protocol_id']}",
        str(batch["instructions"]),
        "criteria:",
    ]
    lines += [
        f"  {c['id']} ({c['kind']}): {c['statement']}  rule: {c['rule']}" for c in batch["criteria"]
    ]
    if batch["worked_examples"]:
        lines.append("worked examples:")
        lines += [
            f"  {e['expected']}: {e['title']}: {e.get('abstract', '')}"
            for e in batch["worked_examples"]
        ]
    lines.append("records:")
    for record in batch["records"]:
        lines.extend(human_record_lines(record))
    lines.append("template:")
    lines.append(json.dumps(human_template(batch), indent=2))
    return lines


def human_record_lines(record: Mapping[str, Any]) -> list[str]:
    """One record of a batch: title and abstract, or the conversion to read at full text."""
    lines = [f"  {record['work_id']}  {record['title']}"]
    if "conversion_id" in record:
        lines.append(
            f"    read: factory document read {record['work_id']} "
            f"--conversion {record['conversion_id']}"
        )
    else:
        lines.append(f"    {record.get('abstract') or '(no abstract)'}")
    return lines


def human_template(batch: Mapping[str, Any]) -> dict[str, Any]:
    """The file `factory screen record` reads, blank for each record of the batch."""
    items: list[dict[str, Any]] = []
    for record in batch["records"]:
        item: dict[str, Any] = {
            "work_id": record["work_id"],
            "verdict": "",
            "criterion": None,
            "quote": "",
            "rationale": "",
        }
        if "conversion_id" in record:
            item["anchor"] = ""
        items.append(item)
    return {"task_id": batch["task_id"], "items": items}


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
    lines.append(
        f"gold rows {sc.gold_rows}, agent rows {sc.agent_rows}, matched {sc.matched}, "
        f"unmatched {sc.unmatched}"
    )
    lines.append(
        f"record recall {_rate(sc.recall)}, field agreement {_rate(sc.field_agreement)} "
        f"(over all rows {_rate(sc.field_agreement_all)}), "
        f"precision {_rate(sc.precision)}, verification rate {_rate(sc.verification_rate)}"
    )
    lines.append("result: " + ("passed" if report.passed else "failed"))
    return lines


_EXPLORATORY_MARK = " (exploratory, declared)"


def mine_status_lines(status: list[MineStatus]) -> list[str]:
    """One line per listed miner: its units by state, rows and agreement."""
    if not status:
        return ["no listed miners"]
    return [
        f"{m.name} version {m.version}{_EXPLORATORY_MARK if m.exploratory else ''}: "
        f"units {m.units} (closed {m.closed}, open {m.open}, "
        f"stale {m.stale}), rows {m.rows}, agreement {_rate(m.agreement)} over all rows "
        f"({_rate(m.agreement_aligned)} over aligned rows)"
        + (
            f", imported dual {m.imported_dual}, single {m.imported_single}"
            if m.imported_dual or m.imported_single
            else ""
        )
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
        f"overall {_rate(agreement.overall)} over aligned rows; "
        f"{_rate(agreement.overall_all_rows)} over all rows "
        f"(aligned {agreement.rows_aligned}, unmatched slots {agreement.unmatched_slots})",
    ]
    lines += [
        f"group {g.group}: {g.agreed}/{g.compared} rate {_rate(g.rate)}" for g in agreement.rates
    ]
    if not agreement.disagreements:
        lines.append("no unresolved disagreements")
    for item in agreement.disagreements:
        lines += disagreement_lines(item)
    lines += tolerated_pending_lines(agreement.tolerated_pending, "not in the agreement")
    return lines


def tolerated_pending_lines(tolerated: Sequence[str], where: str) -> list[str]:
    """The works a step went ahead without, within the protocol's `pending_tolerance`
    (decision 138); `where` says what happened to them. Empty when there are none."""
    if not tolerated:
        return []
    return [
        f"tolerated: {len(tolerated)} work(s) left out, within pending_tolerance ({where}): "
        f"{', '.join(tolerated)}"
    ]


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
        lines.append(
            f"    last full run: {s.last_full_replay or 'none in the watch'}; "
            f"{s.windows_since_full_replay} weekly window(s) since"
        )
    return lines


def re_resolve_summary_lines(summary: ReResolveSummary) -> list[str]:
    lines = [
        f"{r.extraction_id} ({r.work_id}): {len(r.ordinals)} link(s) retried, "
        + ", ".join(f"{state.value} {count}" for state, count in r.states.items() if count)
        for r in summary.re_resolved
    ]
    lines += [f"skipped {s.work_id}: {s.reason}" for s in summary.skipped]
    if not lines:
        lines = ["nothing to retry"]
    lines.append(
        f"{summary.selected} entries selected, {summary.skipped_layer} skipped by layer, "
        f"{summary.skipped_flagged_title} skipped by flagged title"
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


TOP_TAKEN = 10
"""Taken candidates listed under a backward selection (the best by score, then cited-by)."""


def backward_selection_lines(selection: BackwardSelection) -> list[str]:
    """A selected backward round (decision 135): the thresholds, what each step dropped, what was
    taken and the best taken candidates. Counts are those recorded; the number not taken is
    derived."""
    bounds = [
        f"published from {selection.published_from}" if selection.published_from else None,
        f"cited by at least {selection.min_cited_by}" if selection.min_cited_by else None,
        f"similarity at least {selection.min_similarity}" if selection.min_similarity else None,
    ]
    lines = [f"selection: {', '.join(b for b in bounds if b)}"]
    if selection.model_id is not None and selection.weights_hash is not None:
        lines.append(f"  model {selection.model_id}, weights {selection.weights_hash[:12]}")
    lines.append(
        f"  considered {selection.considered}; dropped before the window "
        f"{selection.dropped_before_window}, undated {selection.dropped_undated}, below the "
        f"cited-by floor {selection.dropped_cited_by}, not scorable {selection.dropped_unscored}, "
        f"below the similarity {selection.dropped_similarity}; taken {len(selection.taken)}, "
        f"not taken {selection.not_taken}"
    )
    best = sorted(
        selection.taken,
        key=lambda t: (-(t.score if t.score is not None else -2.0), -t.cited_by, t.work_key),
    )[:TOP_TAKEN]
    for t in best:
        score = "-" if t.score is None else f"{t.score:.4f}"
        lines.append(f"  taken {t.work_key}: score {score}, cited by {t.cited_by}")
    return lines


def _tolerated_lines(tolerated: list[str]) -> list[str]:
    """The works a round goes ahead without, within the protocol's `pending_tolerance`."""
    if not tolerated:
        return []
    return [
        f"  tolerated: {len(tolerated)} work(s) pending or unextracted, within pending_tolerance "
        f"(recorded in the round): {', '.join(tolerated)}"
    ]


def round_plan_lines(direction: str, result: RoundResult, gaps: list[ValidationIssue]) -> list[str]:
    """A dry run: whether the round is allowed and why not, the plan's gaps, the candidates
    ranked by how many included works cite them, and the queries."""
    state = result.state
    verdict = "allowed" if state.allowed else "refused"
    lines = [f"{direction} round {state.round_no}: {verdict}"]
    lines += [f"  {i.field}: {i.reason}" for i in state.refusals]
    lines += [f"  note: {n}" for n in state.notes]
    lines += _tolerated_lines(result.tolerated_pending)
    lines += [f"  plan gap {i.field}: {i.reason}" for i in gaps]
    if result.backward_selection is not None:
        lines += backward_selection_lines(result.backward_selection)
    lines.append(f"{len(result.candidates)} candidate(s)")
    lines += [_candidate_line(c) for c in result.candidates]
    lines.append(f"{len(result.queries)} query(ies), {len(result.unqueryable)} unqueryable")
    lines += [f"  {q.source}: {q.text}" for q in result.queries]
    lines += [f"  not extracted {w}: {why}" for w, why in result.unextracted]
    lines.append(f"{result.no_document} work(s) with no document: listed, not blocking")
    return lines


def round_result_lines(result: RoundResult) -> list[str]:
    lines = [
        f"round {result.round_id}: {len(result.runs)} queries run, {result.new_works} new works"
    ]
    if result.backward_selection is not None:
        lines += backward_selection_lines(result.backward_selection)
    lines += _tolerated_lines(result.tolerated_pending)
    selection = result.selection
    if selection is not None:
        lines.append(
            f"capped at {selection.max_per_work} per source work; model {selection.model_id}, "
            f"weights {selection.weights_hash[:12]}"
        )
        lines += [
            f"  {c.work_id}: matched {c.matched}, held {c.in_corpus}, taken {c.taken}, "
            f"not taken {c.not_taken}"
            for c in selection.cores
        ]
    return lines


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


def shared_status_lines(projects: Sequence[SharedProject]) -> list[str]:
    """One line per project the shared store knows of, or a notice when it knows none."""
    if not projects:
        return ["the shared store holds no project"]
    return [f"{p.slug}: {p.status}, {p.records} record(s)" for p in projects]


def shared_unit_lines(units: Sequence[SharedUnit]) -> list[str]:
    """One line per importable unit, or a notice when there is none."""
    if not units:
        return ["no importable unit"]
    return [
        f"{u.project} {u.work_id} {u.conversion_id}: {u.status}, {u.rows} row(s)"
        + (", dual" if u.dual else "")
        for u in units
    ]


def mine_import_lines(result: BatchResult[str]) -> list[str]:
    """How many units an import wrote, then each refusal by its position."""
    lines = [f"imported {len(result.written)} unit(s)"]
    for error in result.rejected:
        lines += [f"unit {error.index}: {i.field}: {i.reason}" for i in error.issues]
    return lines


def layer_status_lines(status: LayerStatus) -> list[str]:
    """The reference-layer status as a readable table."""
    lines = [
        f"rules {status.rules_version}; scheme "
        + (
            "none recorded" if status.scheme_version is None else f"version {status.scheme_version}"
        ),
        f"entries {status.entries_total}; assessable items {status.assessable}; "
        f"in corpus {status.in_corpus}",
    ]
    if status.unassessable:
        lines.append(
            "unassessable: " + ", ".join(f"{r} {n}" for r, n in status.unassessable.items())
        )
    for stage in ("title", "abstract"):
        counts = status.by_stage.get(stage, {})
        by_layer = ", ".join(f"{k} {v}" for k, v in counts.items()) or "none yet"
        left = status.left.get(stage)
        lines.append(f"{stage}: {by_layer}" + ("" if left is None else f"; left {left}"))
        extras = [
            f"{layer} {status.precursors.get(stage, {}).get(layer, 0)} precursor, "
            f"{status.unknown_year.get(stage, {}).get(layer, 0)} year unknown"
            for layer in counts
        ]
        if extras:
            lines.append("  by layer: " + "; ".join(extras))
    if status.scheme_version is not None:
        lines.append(f"awaiting resolution (abstract stage): {status.awaiting_resolution}")
        lines.append(f"snowball candidates: {status.snowball_candidates}")
    cal = status.calibration
    if isinstance(cal, CalibrationState):
        agreement = "n/a" if cal.agreement is None else f"{cal.agreement:.2f}"
        kappa = "n/a" if cal.kappa is None else f"{cal.kappa:.2f}"
        lines.append(
            f"calibration: sample {cal.sample_size}, labelled {cal.labelled}, "
            f"assigned {cal.assigned}, compared {cal.compared}; agreement {agreement}; "
            f"kappa {kappa} vs floor {cal.floor:.2f}; dropped {cal.dropped}; "
            + ("passed" if cal.passed else "not passed")
        )
        if cal.strata:
            lines.append(
                "  strata: "
                + ", ".join(f"{k} {v}" for k, v in cal.strata.items())
                + (
                    " (inner from: "
                    + ", ".join(f"{k} {v}" for k, v in cal.inner_by_layer.items())
                    + ")"
                    if cal.inner_by_layer
                    else ""
                )
            )
        if cal.inner_shortfall:
            lines.append(
                "  inner shortfall: "
                + ", ".join(f"{k} {v}" for k, v in cal.inner_shortfall.items())
            )
        for layer, k in cal.kappa_by_layer.items():
            a = cal.agreement_by_layer.get(layer)
            lines.append(
                f"  ring {layer}: kappa {'n/a' if k is None else f'{k:.2f}'}, "
                f"agreement {'n/a' if a is None else f'{a:.2f}'}"
            )
    return lines


def flow_table_markdown(by_source: Mapping[str, FlowCounts]) -> str:
    """The PRISMA counts as a table: one row per step, one column per source group, the total
    last. Every figure is read from the counts; criteria rows are those any group excludes by."""
    groups = [key for key in by_source if key != TOTAL] + [TOTAL]
    ta_criteria = sorted({c for counts in by_source.values() for c in counts.ta_excluded})
    ft_criteria = sorted({c for counts in by_source.values() for c in counts.ft_excluded})
    steps: list[tuple[str, Callable[[FlowCounts], int]]] = [
        ("records screened", lambda c: c.screened),
        ("title/abstract included", lambda c: c.ta_included),
        *[
            (f"title/abstract excluded: {crit}", lambda c, k=crit: c.ta_excluded.get(k, 0))
            for crit in ta_criteria
        ],
        ("title/abstract pending", lambda c: c.ta_pending),
        ("full-text not sought", lambda c: c.ft_not_sought),
        ("full-text attempted, not retrieved", lambda c: c.ft_attempted_failed),
        ("full-text retrieved", lambda c: c.ft_retrieved),
        ("full-text included", lambda c: c.ft_included),
        *[
            (f"full-text excluded: {crit}", lambda c, k=crit: c.ft_excluded.get(k, 0))
            for crit in ft_criteria
        ],
        ("full-text pending", lambda c: c.ft_pending),
        ("full-text awaiting", lambda c: c.ft_awaiting),
    ]
    lines = [
        "# PRISMA counts by source group",
        "",
        "| step | " + " | ".join(groups) + " |",
        "|---" * (len(groups) + 1) + "|",
    ]
    for label, value in steps:
        cells = [str(value(by_source[group])) for group in groups]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _ledger_line(row: LedgerRow) -> str:
    ta = row.ta_outcome.value if row.ta_outcome is not None else "-"
    if row.ta_criterion is not None:
        ta = f"{ta} ({row.ta_criterion})"
    ft: str = row.ft_state or "-"
    if row.ft_outcome is not None:
        ft = f"{ft} / {row.ft_outcome}"
    if row.ft_criterion is not None:
        ft = f"{ft} ({row.ft_criterion})"
    return f"{row.work_id}  {row.source_group}  ta: {ta}  ft: {ft}  {row.title}"


def flow_works_lines(page: FlowPage) -> list[str]:
    """One line per ledger row, then the cursor that continues the listing when there is one."""
    lines = [_ledger_line(row) for row in page.items]
    if not page.items:
        lines.append("no work matches these filters")
    if page.next_cursor is not None:
        lines.append(f"next cursor: {page.next_cursor}")
    return lines


def flow_trail_lines(work_id: str, steps: Sequence[TrailStep]) -> list[str]:
    """One line per step, in time order: its time, its kind, then its details."""
    lines = [f"# Trail of {work_id}", ""]
    for step in steps:
        details = ", ".join(f"{key}: {value}" for key, value in step.d.items())
        lines.append(f"- {step.at} {step.kind}" + (f" ({details})" if details else ""))
    if not steps:
        lines.append("no steps")
    return lines


def flow_skipped_lines(records: Sequence[SkippedRecord], gaps: Sequence[RunGap]) -> list[str]:
    """The skipped raw records, then each query's reported against retrieved."""
    lines = ["# Records that never became works", ""]
    for record in records:
        lines.append(
            f"- {record.run_id} {record.query_id} [{record.reason}] "
            f"{record.native_id or '-'}  {record.title or '(untitled)'}"
        )
    if not records:
        lines.append("none")
    lines += ["", "# Run gaps by query", ""]
    for gap in gaps:
        reported = "unknown" if gap.reported is None else str(gap.reported)
        shortfall = "unknown" if gap.gap is None else str(gap.gap)
        lines.append(
            f"- {gap.query_id} ({gap.source}): reported {reported}, "
            f"retrieved {gap.retrieved}, gap {shortfall}"
        )
        for run in gap.runs:
            note = f", note: {run.note}" if run.note else ""
            lines.append(
                f"  - {run.run_id} {run.status}: retrieved {run.retrieved_count}, "
                f"skipped {run.skipped}{note}"
            )
    if not gaps:
        lines.append("none")
    return lines


# --- The technique landscape (IDEA-78): every output starts with the exploratory notice ---


def _technique_head(result: Any) -> list[str]:
    lens = result.lens
    named = [f"layer={lens.layer}"] + [
        f"{k}={v}"
        for k, v in (("stage", lens.stage), ("evidence", lens.evidence), ("status", lens.status))
        if v
    ]
    return [f"EXPLORATORY: {technique_notice()}", "lens: " + ", ".join(named) + ", rows=pass-A"]


def technique_notice() -> str:
    from factory.model.technique_graph import NOTICE

    return NOTICE


def technique_landscape_lines(result: Any) -> list[str]:
    lines = _technique_head(result)
    for s in result.stages:
        agreement = (
            "no second pass"
            if s.agreement is None
            else (
                f"agreement {s.agreement:.2f} (aligned "
                f"{'-' if s.agreement_aligned is None else format(s.agreement_aligned, '.2f')}), "
                f"{s.agreement_note}"
            )
        )
        share = "-" if s.no_evidence_share is None else f"{s.no_evidence_share:.0%}"
        lines.append(
            f"stage {s.stage} ({s.miner} v{s.version}): {s.approaches} approaches, "
            f"{s.works} works, "
            f"{s.rows} rows, no evidence attribute {share}; {agreement}"
        )
        for a in (a for a in result.approaches if a.stage == s.stage):
            lines.append(f"  {a.id}  {a.works} works  {a.name}")
    co = [e for e in result.edges if e.kind == "co-used-with"]
    for e in co:
        lines.append(f"co-used {e.source} + {e.target}: {e.weight} works")
    if result.edges_omitted:
        lines.append(f"({result.edges_omitted} co-used edges omitted)")
    if result.undated_works:
        lines.append("undated works skipped by the date rule: " + ", ".join(result.undated_works))
    return lines


def technique_view_lines(result: Any) -> list[str]:
    a = result.approach
    lines = _technique_head(result)
    lines.append(f"{a.id} {a.name} ({a.stage}): {a.works} works, {a.rows} rows")
    lines.append("evidence: " + ", ".join(f"{k} {v}" for k, v in a.by_evidence.items()))
    for u in result.uses:
        lines.append(f"{u.work_id}  {u.status}  {u.evidence}  {u.anchor or '-'}")
        if u.described_as:
            lines.append(f"    as: {u.described_as}")
        if u.quote:
            lines.append(f"    quote: {u.quote}")
    for e in result.derives_from:
        lines.append(f"candidate derives-from {e.source} -> {e.target}  basis {e.basis}")
    if result.earliest is not None:
        lines.append(
            "earliest-in-corpus (date rule, not an origin): "
            f"{result.earliest.target} {result.earliest.basis}"
        )
    if result.undated_works:
        lines.append("undated, skipped: " + ", ".join(result.undated_works))
    return lines


def technique_candidate_lines(result: Any) -> list[str]:
    lines = _technique_head(result)
    edges = [e for e in result.edges if e.kind == "derives-from"]
    lines += [f"{e.source} -> {e.target}  {e.approach}  {e.state}  {e.basis}" for e in edges]
    if not edges:
        lines.append("no candidate derives-from edges")
    return lines


def technique_neighbor_lines(result: Any) -> list[str]:
    a = result.approach
    lines = _technique_head(result)
    lines.append(f"{a.id} {a.name} ({a.stage}): {len(result.works)} works")
    lines += [
        f"co-used {c.approach.id} {c.approach.name}: {c.weight} works" for c in result.co_used
    ]
    lines += [f"stage {s.stage}: {s.works} works" for s in result.stages]
    lines += [f"candidate derives-from {e.source} -> {e.target}" for e in result.derives_from]
    return lines


def _score_lines(score: Any) -> list[str]:
    if score is None:
        return []
    parts = [
        f"{k}={getattr(score, k):.3f}"
        for k in ("popularity", "stage", "strength", "bridge", "evidence", "generic")
        if getattr(score, k) is not None
    ]
    if getattr(score, "twin_share", None):
        parts.append(f"work_set_overlap={score.twin_share:.2f}")
    parts.append(f"composite={score.composite:.3f}")
    extra = f"  flags: {', '.join(score.flags)}" if score.flags else ""
    lines = [
        f"    score {score.rank_by}={score.value:.3f}: "
        + " ".join(parts)
        + f" (works={score.popularity_raw}, links={score.bridge_links}){extra}"
    ]
    lines += [
        f"    lookalike of {lk.approach_id} in {lk.stage}: possibly the same technique "
        f"({lk.of}, name tokens {lk.jaccard:.2f})"
        for lk in score.lookalikes
    ]
    return lines


def technique_candidate_list_lines(result: Any) -> list[str]:
    lines = [f"EXPLORATORY: {technique_notice()}", f"{result.kind}: {result.total} candidates"]
    for g in result.gaps:
        lines.append(f"{g.rank}. {g.statement}  [{g.label}]")
        lines += _score_lines(g.score)
        if g.quote is not None:
            lines.append(f"    quote {g.quote.work_id} {g.quote.anchor or '-'}: {g.quote.quote}")
    for c in result.combinations:
        lines.append(f"{c.rank}. {c.statement}  [{c.label}]")
        lines += _score_lines(c.score)
        for side, q in (("a", c.quote_a), ("b", c.quote_b)):
            if q is not None:
                lines.append(f"    quote {side} {q.work_id} {q.anchor or '-'}: {q.quote}")
    for h in result.challenges:
        lines.append(f"{h.statement}  [{h.label}]")
        lines += [f"    failed: {u.work_id} {u.anchor or '-'} {u.quote or ''}" for u in h.failed]
        lines += [
            f"    supported: {u.work_id} {u.anchor or '-'} {u.quote or ''}" for u in h.supported
        ]
    return lines


# --- The lead engine (hypothesis engine v1): every output starts with the exploratory notice ---


def _engine_head(result: Any) -> list[str]:
    from factory.model.lead_engine import NOTICE

    return [f"EXPLORATORY: {NOTICE}"]


def _candidate_lines(c: Any, indent: str = "  ") -> list[str]:
    lines = [f"{indent}{c.candidate_id}  [{c.source}]  {c.observation}"]
    works = ", ".join(w.work_id for w in c.works)
    lines.append(f"{indent}  works ({c.works_total}): {works}")
    for q in c.quotes:
        lines.append(f"{indent}  quote {q.role} {q.work_id} {q.anchor or '-'}: {q.quote}")
    lines.append(
        f"{indent}  triggers: "
        + ", ".join(f"{t.kind} {t.ref}" for t in c.triggers)
        + (f"  ({c.trigger_note})" if c.trigger_note else "")
    )
    return lines


def lead_candidates_lines(result: Any) -> list[str]:
    lines = _engine_head(result)
    lines.append("parameters: " + ", ".join(f"{k}={v}" for k, v in result.parameters.items()))
    lines.append(
        "totals before the per-source cap: "
        + ", ".join(f"{k}={v}" for k, v in result.totals.items())
    )
    lines.append(f"{len(result.candidates)} candidates")
    for c in result.candidates:
        lines += _candidate_lines(c)
    lines += [f"skipped {s.candidate_id}: {s.reason}" for s in result.skipped]
    return lines


def _measure_text(m: Any) -> str:
    v = m.verification
    overlap = "-" if m.overlap is None else m.overlap
    share = "-" if v.share is None else f"{v.share:.2f}"
    return (
        f"support={m.support} independence={m.independence} verified={v.verified}/{v.total} "
        f"({share}) diversity={m.diversity:.2f} overlap={overlap} "
        f"prior_hits={m.prior_hits} (narrow {m.narrow_prior_hits}) score={m.score:.3f} "
        f"basis={m.basis}"
    )


def lead_queue_lines(result: Any) -> list[str]:
    lines = _engine_head(result)
    lines.append("order: " + result.order_rule)
    lines.append("parameters: " + ", ".join(f"{k}={v}" for k, v in result.parameters.items()))
    lines.append(f"{len(result.items)} of {result.total_candidates} candidates shown")
    for i in result.items:
        lines.append(
            f"{i.rank}. {i.entry_id}  [{i.source}]"
            + (f"  flags: {', '.join(i.flags)}" if i.flags else "")
        )
        lines.append("    " + _measure_text(i.measures))
        for h in i.prior:
            lines.append(
                f"    prior {h.kind} {h.id}: items {', '.join(h.shared_items) or '-'}; "
                f"works {', '.join(h.shared_works) or '-'}"
            )
        if i.candidate is not None:
            lines += _candidate_lines(i.candidate, "    ")
    for i in result.leads:
        lines.append(f"open lead {i.rank}. {i.entry_id}  [{i.source}]")
        lines.append("    " + _measure_text(i.measures))
    lines += [f"excluded {s.candidate_id}: {s.reason}" for s in result.excluded]
    lines.append(result.comparability)
    return lines


def lead_stats_lines(result: Any) -> list[str]:
    lines = _engine_head(result)
    lines.append(f"{result.notice}")
    lines.append(f"leads recorded: {result.recorded}; by state: {result.by_state}")
    lines.append(
        f"decided: {result.decided}; promotion rate {result.promotion_rate}; "
        f"of decided {result.decided_promotion_rate}"
    )
    lines.append(f"discard reasons: {result.discard_reasons}")
    lines.append(f"by trigger kind: {result.by_trigger_kind}; by source: {result.by_source}")
    lines.append(
        f"hypotheses drafted: {result.hypotheses_drafted} {result.hypotheses_by_state}; "
        f"registered: {result.hypotheses_registered}; closed: {result.hypotheses_closed}"
    )
    lines.append(
        f"reviews: {result.reviews} {result.reviews_by_recommendation}; outcomes: {result.outcomes}"
    )
    for o in result.oldest_undecided:
        lines.append(f"oldest undecided {o.lead_id} [{o.source}] triggers={o.triggers}")
    return lines

"""`check`: the read-only gap report of a project, and the gaps to a higher rigour mode (plan 5b).

Each rule reads one service and yields hits. A hit's severity is read from `LEVELS` for the mode
evaluated: exploratory, pilot or systematic, in that order; `None` means the rule makes no finding
in that mode. A hit may override its severity (`kappa-below-floor` is an error when the protocol
enforces the floor). Nothing is written: no event, no table, no projection version.

`check(project, promote_to=mode)` evaluates the same hits as `mode` and returns only the findings
that are errors under `mode` but not under the project's current mode (acceptance 20; the
promotion section G of docs/specs/01-rigour.md). Gaps the current mode already reports as
errors are not repeated.

Invariants:
- `ok` is true exactly when no finding has severity error.
- Seed findings carry seed identifiers only in `refs`; `role` is the seed's role in the hold-out
  (`held-out`, `development`, or `unsplit` for a positive before the split is drawn). A held-out
  seed is named here because `check` is the human view; the agent view aggregates by role.
- `refs` hold identifiers, never free text. `message` gives counts and names no seed.
"""

import json
import math
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Literal

from sqlalchemy import text

from factory.clock import format_ts, parse_ts
from factory.errors import FactoryValidationError
from factory.events.blobs import BlobIntegrityError
from factory.events.reader import read_all
from factory.index.chase import admitted_works
from factory.index.drafts import identities
from factory.living.counts import source_counts
from factory.model.base import StrictModel
from factory.model.drafts import DRAFT_VERIFY_ERROR_CEILING
from factory.model.extraction import MinerScope, Scope
from factory.model.lineage import EdgeStatus, LineageDecision
from factory.model.notices import NoticeKind, unassessed_notices
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolStatus, ScreeningStage
from factory.model.references import Direction, LinkState
from factory.model.screening import PassLabel
from factory.model.seed import SEED_ID_RE
from factory.model.watch import CycleStatus
from factory.model.work import ProvenanceMethod
from factory.modules.contract import CheckHit
from factory.services.agreement import Outcome, agreement_summary, final_outcomes, single_pass_works
from factory.services.audit import audit_outstanding, audit_report, audit_shortfall
from factory.services.calibration import calibrated_models, calibration_status
from factory.services.call_memo import entering
from factory.services.chase import chase_rounds, forward_chase_rounds
from factory.services.conclusions import conclusion_diff
from factory.services.consolidation_due import consolidation_due
from factory.services.context import FUTURE_MARGIN, Project, future_dated
from factory.services.contributions import (
    contribution_audit_report,
    contribution_status,
    final_items,
    live_items,
)
from factory.services.dedup import active_merges
from factory.services.document_read import default_conversion
from factory.services.draft_audit import audit_report as draft_audit_report
from factory.services.draft_release import released_drafts
from factory.services.drafts import list_drafts, sentence_status
from factory.services.evidence_report import evidence_report
from factory.services.extraction import (
    calibration_task_ids,
    extraction_population,
    in_dual_sample,
    live_claims,
    live_rows,
    pass_config,
    require_schema,
    scope_population,
    stale_documents,
    stale_extractions,
    unit_states,
)
from factory.services.extraction_agreement import final_rows, grouped_rows, independence_counts
from factory.services.extraction_audit import extraction_audit_outstanding, extraction_audit_report
from factory.services.fulltext_status import fulltext_status
from factory.services.gates import audit_hits, gate_hits, labelled_gate_audits
from factory.services.hosting import foreign_event_files
from factory.services.ideas import list_ideas
from factory.services.imports import list_imports
from factory.services.label_check import (
    ORGANISATION_ID,
    organisation_present,
    unconfirmed_applications,
    unused_terms,
)
from factory.services.layer_check import (
    concept_cycles,
    concepts_without_approved_source,
    dropped_reviews,
    inferred_links,
    layer_present,
    self_reviewed_items,
    stale_items,
    unreviewed_concepts,
    unreviewed_interpretations,
)
from factory.services.lineage import graph_status, iter_graph_export
from factory.services.methods import MethodsReport, methods_report, render_methods
from factory.services.miner_report import calibration_passed
from factory.services.miners import MinerState, miner_state
from factory.services.mining import registered_miners
from factory.services.modules import default_modules
from factory.services.notices import (
    assessments,
    dependent_works,
    observed_notices,
)
from factory.services.prisma import prisma_flow, search_report
from factory.services.project import project_status
from factory.services.protocol import current_protocol
from factory.services.protocol_rules import (
    gate_policy_gaps,
    library_source_gaps,
    snowball_plan_gaps,
    watch_plan_gaps,
)
from factory.services.reference_resolve import lost_human_decisions
from factory.services.references import current_extraction, included_works
from factory.services.region_check import AGENT_VIEW, region_findings
from factory.services.relations import RelationView, list_relations
from factory.services.seeds import SeedRole, _rigor_mode, seed_check
from factory.services.slice6_check import slice6_hits
from factory.services.snowball import recorded_rounds, round_runs
from factory.services.status_lookup import (
    crossref_doi,
    effective_last_checked,
    unrecovered_failures,
)
from factory.services.trace import dangling_refs
from factory.services.versions import link_conflicts, newer_versions, vor_available
from factory.services.watch import cycles, watch_status

Severity = Literal["error", "warning"]

LEVELS: dict[str, tuple[Severity | None, Severity | None, Severity | None]] = (
    default_modules().levels()
)
"""code: (exploratory, pilot, systematic); None means no finding in that mode. Each code is
declared by the module that owns its rule (`services/modules/<module>.py`)."""

LAYER_CHECK_CODES = frozenset(
    {
        "interpretation-unreviewed",
        "concept-unreviewed",
        "interpretation-source-stale",
        "interpretation-self-reviewed",
        "concept-source-missing",
        "concept-link-unconfirmed",
        "layer-review-dropped",
        "layer-leak",
        "layer-scan-incomplete",
        "concept-cycle",
    }
)
"""The findings of the interpretation layer. A project with no interpretation and no concept has
none of them."""

INTERPRETATION_UNREVIEWED_CEILING = 0
"""The number of unreviewed interpretations (and of approved, unreviewed concept definitions)
tolerated before `systematic` calls them an error (plan G3-C, ruling C4). A protocol field is
deferred until the pilot shows the review burden."""

_NOTICE_PHRASES: dict[str, str] = {
    "included-retracted": "included work(s) with a retraction or withdrawal no human has assessed",
    "notice-unassessed": "notice(s) no human has assessed",
    "notice-unchecked-crossref": "dependent work(s) without a DOI Crossref can be asked about",
    "notice-coverage-age": "dependent work(s) not looked up for too many cycles",
    "newer-version-available": "work(s) with a newer version on their route than the document held",
    "version-of-record-available": "preprint work(s) with a published version linked",
    "version-link-conflict": "published-version link(s) refused because another work holds the id",
    "status-lookup-failed": "status lookup(s) failed and not yet covered by a later complete run",
}
"""One phrase per notice or version finding. A message is a count and its phrase, so the agent
view can rebuild it after dropping refs that name a held-out seed's work."""

REFERENCE_UNRESOLVED_CEILING = 0.30
"""The share of a live extraction's entries left unresolved or ambiguous above which `check`
reports it (slice 3a ruling 17; provisional, to be set against the pilot)."""
_INCOMPLETE_FLAGS = frozenset(
    {"parse-incomplete", "marker-gap", "no-bibliography", "bibliography-without-entries"}
)

_MODE_ORDER: tuple[RigorMode, ...] = (
    RigorMode.EXPLORATORY,
    RigorMode.PILOT,
    RigorMode.SYSTEMATIC,
)
_DECIDED = (Outcome.INCLUDED, Outcome.EXCLUDED)
_ADMISSION_ROUTES = frozenset({ProvenanceMethod.SEED_ADMISSION, ProvenanceMethod.HAND_SEARCH})
_ROLE_KEYS: dict[SeedRole, str] = {
    SeedRole.HELD_OUT: "held-out",
    SeedRole.DEVELOPMENT: "development",
    SeedRole.LATE: "development",
    SeedRole.UNSPLIT: "unsplit",
}


class Finding(StrictModel):
    """One gap. `role` is set on seed findings only: `held-out`, `development` (development and
    late positives), or `unsplit`, a positive seed before the split is drawn. An unsplit positive
    may still become held-out, so an aggregate must count it as held-out-possible, never as
    development (controller Ruling G)."""

    code: str
    severity: Literal["error", "warning"]
    refs: list[str]
    message: str
    role: str | None = None


class CheckReport(StrictModel):
    mode: RigorMode
    evaluated_as: RigorMode
    findings: list[Finding]

    @property
    def ok(self) -> bool:
        """True when no finding is an error."""
        return not any(finding.severity == "error" for finding in self.findings)

    @property
    def evidence_ok(self) -> bool:
        """True when no finding about the evidence is an error: every error counts except the
        interpretation layer's own, a `layer-leak` excepted (it says the evidence is touched).
        `ok` stays the whole report; a sound project with one unreviewed interpretation is
        `evidence_ok` and, in `systematic`, not `ok`."""
        return not any(
            finding.severity == "error"
            and (finding.code not in LAYER_CHECK_CODES or finding.code == "layer-leak")
            for finding in self.findings
        )


_HELD_OUT_POSSIBLE = "held-out-possible"
_SEED_PHRASES = {
    "seed-missing": "positive seed(s) missing",
    "seed-admission-pending": "positive seed(s) explained, admission pending",
}


_RATE_CODES = {
    "audit-error-high": "the audit's false-exclusion rate is above the declared ceiling "
    "(figures withheld from the agent view)",
    "gate-audit-unlabelled": "a gate audit has sampled acts still unlabelled "
    "(counts withheld from the agent view)",
}
"""Findings whose message carries a label-derived rate or threshold, and the message an agent
reads instead (decision 37.14). The finding itself, its code and severity are unchanged."""

_WITHHELD_CODES = frozenset(
    {
        "extraction-error-high",
        "contribution-error-ceiling",
        "gate-audit-error-high",
        "draft-verify-error-high",
    }
)
"""Findings an agent never reads, because their presence is an audit's ceiling flag (decision
52)."""

_AUDIT_REPORTED = "extraction-audit-reported"
_GATE_AUDIT_REPORTED = "gate-audit-reported"
_DRAFT_AUDIT_REPORTED = "draft-audit-reported"


def agent_view(
    report: CheckReport,
    *,
    labelled_audit: str | None = None,
    labelled_contribution_audit: str | None = None,
    labelled_gate_audits: Sequence[str] = (),
    labelled_draft_audits: Sequence[str] = (),
) -> CheckReport:
    """The report as an agent may read it: seed findings by role and count only (R-20), no
    label-derived rate, and no extraction audit ceiling flag.

    A seed finding becomes one finding per code, severity and role, with no refs, so a held-out
    seed is never named. A positive still `unsplit` may become held-out, so it is counted as
    `held-out-possible` and never as development. Any other ref that is a seed id is dropped.
    `extraction-error-high` is dropped; when `labelled_audit` names an extraction audit with
    labels, one neutral `extraction-audit-reported` warning is appended last whatever the flag,
    so neither the findings, their order nor `ok` depend on it (decision 52).
    """
    counts: dict[tuple[str, Severity, str], int] = {}
    others: list[Finding] = []
    order: list[tuple[str, Severity, str] | int] = []
    for finding in report.findings:
        if finding.code in _WITHHELD_CODES:
            continue
        if finding.role is None:
            refs = [r for r in finding.refs if not re.fullmatch(SEED_ID_RE, r)]
            update: dict[str, object] = {"refs": refs}
            if finding.code in _RATE_CODES:
                update["message"] = _RATE_CODES[finding.code]
            others.append(finding.model_copy(update=update))
            order.append(len(others) - 1)
            continue
        bucket = _HELD_OUT_POSSIBLE if finding.role == "unsplit" else finding.role
        key = (finding.code, finding.severity, bucket)
        if key not in counts:
            order.append(key)
        counts[key] = counts.get(key, 0) + len(finding.refs)
    findings = [
        others[item]
        if isinstance(item, int)
        else Finding(
            code=item[0],
            severity=item[1],
            refs=[],
            role=item[2],
            message=f"{counts[item]} {item[2]} {_SEED_PHRASES.get(item[0], 'seed finding(s)')}",
        )
        for item in order
    ]
    labelled = [a for a in (labelled_audit, labelled_contribution_audit) if a is not None]
    if labelled:  # one marker for both audits, the same above and below either ceiling
        findings.append(
            Finding(
                code=_AUDIT_REPORTED,
                severity="warning",
                refs=labelled,
                message="an extraction audit is labelled; its result is reported to the researcher",
            )
        )
    if labelled_gate_audits:  # likewise one marker, whatever the error rate
        findings.append(
            Finding(
                code=_GATE_AUDIT_REPORTED,
                severity="warning",
                refs=list(labelled_gate_audits),
                message="a gate audit is labelled; its result is reported to the researcher",
            )
        )
    if labelled_draft_audits:  # likewise: the drafts with a labelled verdict audit
        findings.append(
            Finding(
                code=_DRAFT_AUDIT_REPORTED,
                severity="warning",
                refs=list(labelled_draft_audits),
                message="a draft's audit is labelled; its result is reported to the researcher",
            )
        )
    return report.model_copy(update={"findings": findings})


def agent_check(project: Project, *, promote_to: RigorMode | None = None) -> CheckReport:
    """`check` as an agent may read it (`agent_view`), with the neutral statement of the latest
    extraction audit when it has labels. Read-only."""
    with entering(), _region_agent_view():
        audit = extraction_audit_report(project)
        labelled = (
            audit.audit_id if audit is not None and (audit.labelled or audit.outdated) else None
        )
        contribution = contribution_audit_report(project)
        report = agent_view(
            check(project, promote_to=promote_to),
            labelled_audit=labelled,
            labelled_gate_audits=labelled_gate_audits(project),
            labelled_draft_audits=[
                d.draft_id for d in list_drafts(project) if audit_report_of(project, d.draft_id)
            ],
            labelled_contribution_audit=(
                contribution.audit_id
                if contribution is not None and (contribution.labelled or contribution.outdated)
                else None
            ),
        )
        return _development_only(project, report)


_Hit = CheckHit
"""One condition found by a rule, before its severity is read for a mode."""


@dataclass(frozen=True)
class _ChecklistItem:
    """A PRISMA 2020 reporting item, and the derived figure that covers it (None: no source)."""

    number: str
    text: str
    derived: Callable[[MethodsReport], bool] | None


_PRISMA_CHECKLIST: tuple[_ChecklistItem, ...] = (
    _ChecklistItem("6", "information sources", lambda report: bool(report.sources)),
    _ChecklistItem(
        "7",
        "search strategy",
        lambda report: bool(report.sources) and report.protocol_id is not None,
    ),
    _ChecklistItem("8", "selection process", lambda report: report.passes > 0),
    _ChecklistItem("9", "data collection process", None),
    _ChecklistItem("13a", "synthesis eligibility", None),
)
"""PRISMA 2020 items 6-9 and 13a (R-60). Items 6 and 7 are derived from the search report (the
databases searched, under a protocol) and item 8 from the screening passes. Items 9 and 13a have
no stage in this platform in slice 1 that derives them, so each is reported until one does."""


def check(project: Project, *, promote_to: RigorMode | None = None) -> CheckReport:
    """The gaps of the project under its own rigour mode, or, with `promote_to`, the errors a
    promotion to that mode would add. Read-only."""
    with entering():
        current = _rigor_mode(project)
        if promote_to is None:
            return CheckReport(
                mode=current, evaluated_as=current, findings=_findings_as(project, current)
            )
        own_errors = {_gap_key(f) for f in _findings_as(project, current) if f.severity == "error"}
        gaps = [
            f
            for f in _findings_as(project, promote_to)
            if f.severity == "error" and _gap_key(f) not in own_errors
        ]
        return CheckReport(mode=current, evaluated_as=promote_to, findings=gaps)


def _gap_key(finding: Finding) -> tuple[str, tuple[str, ...], str | None]:
    """What makes two findings the same gap: code, refs and role (not the message)."""
    return (finding.code, tuple(finding.refs), finding.role)


def _findings_as(project: Project, mode: RigorMode) -> list[Finding]:
    """The one evaluation path: every finding the project's data gives under `mode`, errors and
    warnings alike. `check` and the tests both read findings through here."""
    findings: list[Finding] = []
    for hit in _hits(project):
        severity = _severity(hit, mode)
        if severity is not None:
            findings.append(_finding(hit, severity))
    return findings


def _severity(hit: _Hit, mode: RigorMode) -> Severity | None:
    if hit.severity is not None:
        return hit.severity
    return LEVELS[hit.code][_MODE_ORDER.index(mode)]


def _finding(hit: _Hit, severity: Severity) -> Finding:
    return Finding(
        code=hit.code,
        severity=severity,
        refs=list(hit.refs),
        message=hit.message,
        role=hit.role,
    )


def _hits(project: Project) -> list[_Hit]:
    """Every condition in the project, composed from the modules' hooks and reported in rule
    order. The rules run once per call: every module reads the same rule results.

    A hit whose code no module declares is an error (KeyError), never dropped."""
    registry = default_modules()
    results = _run_rules(project)
    token = _RULE_HITS.set((project, results))
    try:
        composed = [hit for module in registry.modules() for hit in module.hits(project)]
    finally:
        _RULE_HITS.reset(token)
    for hit in results:
        registry.owner_of_check(hit.code)
    return sorted(composed, key=lambda hit: hit.seq)


_RULE_HITS: ContextVar[tuple[Project, list[_Hit]] | None] = ContextVar("rule_hits", default=None)


def segment_hits(project: Project) -> list[_Hit]:
    """Every rule result for `project`, each stamped with the position of its rule in report
    order (`seq`). Modules select their own codes from it. Within one `_hits` call the rules run
    once and every module reads the same list; outside it they run on each call."""
    cached = _RULE_HITS.get()
    if cached is not None and cached[0] is project:
        return cached[1]
    return _run_rules(project)


def _run_rules(project: Project) -> list[_Hit]:
    """Run each rule once, in report order, and stamp each hit with its position in the report."""
    project.index.sync()
    outcomes = final_outcomes(project)
    groups: list[list[_Hit]] = [
        _broken_links(project),
        _missing_provenance(project),
        _shortfalls(project),
        _seeds(project),
        _protocol_gates(project),
        _screening(project, outcomes),
        _calibration_and_agreement(project),
        _audit(project),
        _chase(project, outcomes),
        _checklist(project),
        _merge_conflicts(project, outcomes),
        _fulltext(project),
        _extraction(project),
        _evidence(project),
        _references(project),
        _snowball(project, outcomes),
        _inbox(project, outcomes),
        _imports(project),
        _living(project),
        _notices(project, outcomes),
        _conclusions(project),
        _lineage(project),
        _layer(project),
        _regions(project),
        _organisation(project),
        gate_hits(project),
        audit_hits(project),
        _gate_policies(project),
        _mining(project),
        _miner_lifecycle(project),
        slice6_hits(project),
        _drafts(project),
        _writer_verified(project),
        _hosting(project),
        _future_dated(project),
    ]
    flat = [hit for group in groups for hit in group]
    return [replace(hit, seq=seq) for seq, hit in enumerate(flat)]


# --- Drafts (slice 7b, plan W-B) ---

_SENTENCE_CODES = (
    ("unchecked", "draft-sentence-unchecked"),
    ("flagged", "draft-sentence-flagged"),
    ("stale", "draft-sentence-stale"),
)


def audit_report_of(project: Project, draft_id: str) -> int:
    """How many verdicts of the draft's audit are labelled (the agent view's neutral marker)."""
    return draft_audit_report(project, draft_id).all_labelled


def _draft_hits(project: Project, draft_id: str, released: bool) -> list[_Hit]:
    rows = sentence_status(project, draft_id, agent=AGENT_VIEW.get())
    hits: list[_Hit] = []
    for status, code in _SENTENCE_CODES:
        refs = tuple(r.sentence_id for r in rows if r.status == status)
        if refs:
            hits.append(
                _Hit(
                    code,
                    (draft_id, *refs),
                    f"{len(refs)} sentence(s) of a draft are {status}",
                    severity=None if released else "warning",
                )
            )
    report = draft_audit_report(project, draft_id)
    supported = any(r.status == "supported" for r in rows)
    if (report.drawn == 0 and supported) or report.labelled < report.drawn or report.outdated:
        hits.append(
            _Hit(
                "draft-audit-missing",
                (draft_id,),
                "a draft's supported verdicts have no complete, current audit",
            )
        )
    if report.all_rate is not None and report.all_rate > DRAFT_VERIFY_ERROR_CEILING:
        hits.append(
            _Hit(
                "draft-verify-error-high",
                (draft_id,),
                "the audit of a draft's verdicts found errors above the declared ceiling",
            )
        )
    return hits


def _drafts(project: Project) -> list[_Hit]:
    """The state of each draft: ids and counts only, never a sentence's text. For a released draft
    the sentence findings read their level by mode (an error in `systematic`); for a draft not
    released they stay warnings. The agent view reads the status without audit labels."""
    released = released_drafts(project)
    return [
        hit
        for draft in list_drafts(project)
        for hit in _draft_hits(project, draft.draft_id, draft.draft_id in released)
    ]


def _writer_verified(project: Project) -> list[_Hit]:
    """Verdicts in the log by someone who wrote in the same draft, whether or not they were folded
    (a service refuses them, so the log holds one only by hand), in either order."""
    with project.index.connect() as conn:
        present = conn.execute(
            text("SELECT 1 FROM events WHERE type = 'draft.verified' LIMIT 1")
        ).first()
    if present is None:
        return []
    writers: dict[str, set[str]] = {}
    draft_of: dict[str, str] = {}
    verdicts: list[tuple[str, frozenset[str]]] = []
    for event in read_all(project.paths.events_dir, project.catalog):
        sentence = event.payload.get("sentence_id")
        if not isinstance(sentence, str):  # a hand-written event: the fold dropped it too
            continue
        if event.type == "draft.sentence_recorded":
            draft = event.payload.get("draft_id")
            if isinstance(draft, str):
                draft_of[sentence] = draft
                writers.setdefault(draft, set()).update(identities(event.actor))
        elif event.type == "draft.verified":
            verdicts.append((sentence, identities(event.actor)))
    broken: dict[str, list[str]] = {}
    for sentence, who in verdicts:
        draft = draft_of.get(sentence, "")
        if who & writers.get(draft, set()):
            broken.setdefault(draft, []).append(sentence)
    return [
        _Hit(
            "draft-writer-verified",
            (draft, *sentences),
            f"{len(sentences)} verdict(s) of a draft by someone who wrote in it",
        )
        for draft, sentences in sorted(broken.items())
    ]


# --- Hosting (slice 5) ---


def _hosting(project: Project) -> list[_Hit]:
    """Event files of a hosted project that the host did not commit. An unhosted project is not
    looked at, so it runs no git."""
    if not project.is_hosted():
        return []
    foreign = foreign_event_files(project)
    if foreign is None:
        return [
            _Hit(
                "host-mismatch-unchecked",
                (),
                "no readable git history at the root: event authorship was not checked",
            )
        ]
    return [
        _Hit(
            "host-mismatch",
            (f.path,),
            f"added to git by {f.author}, not by the host ({', '.join(f.expected)})",
        )
        for f in foreign
    ]


def _future_dated(project: Project) -> list[_Hit]:
    """Events dated past the clock. Such an event cannot be removed: until the clock passes it, it
    sets no ID floor and each new event rebuilds the index. Reads one `meta` row unless one exists,
    since the greatest ID is the latest date."""
    project.index.sync()
    last = project.index.last_event_id()
    now = project.clock.now()
    if last is None or not future_dated(last, now):
        return []
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT id FROM events WHERE ts > :limit ORDER BY id"),
            {"limit": format_ts(now + FUTURE_MARGIN)},
        ).all()
    refs = tuple(str(row[0]) for row in rows)
    return [_Hit("future-dated-event", refs, f"{len(refs)} events are dated past the clock")]


# --- Registered miners (slice M, M-C) ---


def _mining(project: Project) -> list[_Hit]:
    """Findings of the registered miners the protocol lists: units not yet current and works mined
    once outside the dual sample. Each names works by identifier and gives counts; a miner's
    values and quotes never appear. A project that lists no miner has none of them."""
    protocol = current_protocol(project)
    if protocol is None:
        return []
    hits: list[_Hit] = []
    for use in sorted(protocol.spec.miners or (), key=lambda u: u.name):
        scope = MinerScope(use.name)
        try:
            _, schema, _ = require_schema(project, scope=scope)
            population = scope_population(project, scope)
        except FactoryValidationError:
            continue
        pending = sorted(
            {s.work_id for s in unit_states(project, scope=scope) if s.state != "current"}
        )
        if pending:
            hits.append(
                _Hit(
                    "mine-pending",
                    tuple(pending),
                    f"miner {use.name}: {len(pending)} work(s) have a unit not yet current",
                )
            )
        config = pass_config(project, PassLabel.B, scope=scope)
        if config is not None:
            single = sorted(
                w
                for w in population
                if not in_dual_sample(config.seed, w, schema.dual_extract_sample)
            )
            if single:
                hits.append(
                    _Hit(
                        "mine-single",
                        tuple(single),
                        f"miner {use.name}: {len(single)} work(s) are mined once, outside the "
                        "dual sample",
                    )
                )
    return hits


def _production_rows(project: Project, name: str, version: int) -> int:
    """Live production rows of one miner version (calibration rows are apart)."""
    scope = MinerScope(name)
    apart = calibration_task_ids(project, scope)
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT task_id FROM extraction_rows WHERE scope = :s AND schema_ref = :r "
                "AND superseded_by IS NULL"
            ),
            {"s": name, "r": f"{name}@{version}"},
        ).all()
    return sum(1 for (task,) in found if str(task) not in apart)


def _miner_lifecycle(project: Project) -> list[_Hit]:
    """Findings of the lifecycle of registered miners (M-D, R-52): a version that failed its
    calibration is reported (retired or not), and a protocol that admits a miner as evidence while
    it is not calibrated is an error in every mode (it cannot arise through the tools; this guards
    a replayed, hand-edited log). Each names the miner and version only: no score, no threshold."""
    protocol = current_protocol(project)
    admitted = (
        {(u.name, u.version) for u in (protocol.spec.miners or ()) if u.evidence}
        if protocol is not None
        else set()
    )
    hits: list[_Hit] = []
    read = default_modules().read_miners()
    for row in registered_miners(project):
        if (row.name, row.version) not in read and _production_rows(project, row.name, row.version):
            hits.append(
                _Hit(
                    "miner-version-unread",
                    (),
                    f"miner {row.name} version {row.version} has rows no builder reads",
                )
            )
        state = miner_state(project, row.name, row.version)
        label = f"miner {row.name} version {row.version}"
        if calibration_passed(project, row.name, row.version) is False:  # even if retired
            hits.append(_Hit("miner-calibration-failed", (), f"{label} failed its calibration"))
        if (row.name, row.version) in admitted and state is not MinerState.CALIBRATED:
            hits.append(
                _Hit(
                    "miner-uncalibrated-evidence",
                    (),
                    f"{label} is admitted as evidence but is {state.value}",
                )
            )
    return hits


# --- Lineage (slice 3b, plan G2-E) ---

_PAGE = 500


def _lineage(project: Project) -> list[_Hit]:
    """Findings of the contribution items and the lineage graph. Each names works, relations,
    ideas or audits by identifier and gives counts; none carries a quote, a name or a note.
    A project that never declares `contribution_schema`, never runs G1 and records no relation or
    idea has none of them."""
    hits = _contribution_schema_missing(project)
    protocol = current_protocol(project)
    if protocol is None or protocol.spec.contribution_schema is None:
        return hits + _relation_hits(project)
    scope = Scope.CONTRIBUTION
    states = unit_states(project, scope=scope)
    missing = sorted(
        {s.work_id for s in states if s.pass_label is PassLabel.A and s.state != "current"}
    )
    if missing:
        hits.append(
            _Hit(
                "contribution-missing-extraction",
                tuple(missing),
                f"{len(missing)} included work(s) have no current contribution unit",
            )
        )
    not_current = {s.work_id for s in states if s.state != "current"}
    stale = stale_extractions(project, scope=scope)
    inside = set(scope_population(project, scope))
    # A unit read again is current while its old stale rows stay live (nothing supersedes a
    # stale row), so only a work with a unit not yet current is reported stale.
    stale_works = sorted(
        {row.work_id for row in live_rows(project, scope=scope) if row.extraction_id in stale}
        & inside
        & not_current
    )
    if stale_works:
        hits.append(
            _Hit(
                "contribution-stale",
                tuple(stale_works),
                f"{len(stale_works)} work(s) hold contribution items that are stale",
            )
        )
    empty = sorted({u.work_id for u in contribution_status(project).closed_without_items})
    if empty:
        hits.append(
            _Hit(
                "contribution-closed-without-items",
                tuple(empty),
                f"{len(empty)} work(s) have a contribution unit closed with a reason and no "
                "item; no row exists to audit",
            )
        )
    no_g1 = sorted(
        {i.work_id for i in live_items(project, include_stale=True)}
        - {w for w in inside if current_extraction(project, w) is not None}
    )
    if no_g1:
        hits.append(
            _Hit(
                "graph-extraction-missing",
                tuple(no_g1),
                f"{len(no_g1)} work(s) have contribution items and no current reference extraction",
            )
        )
    audit = contribution_audit_report(project)
    if audit is not None and audit.above_ceiling:
        hits.append(
            _Hit(
                "contribution-error-ceiling",
                (audit.audit_id,),
                "the contribution audit's error rate is above the declared ceiling",
            )
        )
    return hits + _relation_hits(project)


# --- The interpretation layer (slice 3c, plan G3-C) ---

_LAYER_ID = re.compile(r"\b(?:int|cpt|cul)_[0-9A-HJKMNP-TV-Z]{26}\b")
_LAYER_EDGE = re.compile(r'"(?:explains:int|uses:cul)_[0-9A-HJKMNP-TV-Z]{26}\b')
_LAYER_CLASS = re.compile(r'"class"\s*:\s*"interpretation"')


def _unreviewed_hit(code: str, noun: str, total: int, refs: list[str]) -> _Hit:
    """Above the ceiling `systematic` reads the level table (an error); at or below it the
    finding stays advisory."""
    return _Hit(
        code,
        tuple(refs),
        f"{total} {noun} not yet reviewed by a human",
        severity=None if total > INTERPRETATION_UNREVIEWED_CEILING else "warning",
    )


def _layer(project: Project) -> list[_Hit]:
    """Findings of the interpretation layer: counts and identifiers only, never a quote or text.
    A project with no interpretation and no concept has none."""
    if not layer_present(project):
        return []
    hits: list[_Hit] = []
    total, refs = unreviewed_interpretations(project)
    if total:
        hits.append(_unreviewed_hit("interpretation-unreviewed", "interpretation(s)", total, refs))
    total, refs = unreviewed_concepts(project)
    if total:
        hits.append(
            _unreviewed_hit("concept-unreviewed", "approved concept definition(s)", total, refs)
        )
    for code, found, phrase in (
        (
            "interpretation-source-stale",
            stale_items(project),
            "interpretation(s) or concept(s) cite a document that has since been superseded",
        ),
        (
            "interpretation-self-reviewed",
            self_reviewed_items(project),
            "interpretation(s) or concept definition(s) reviewed by their own author",
        ),
        (
            "concept-source-missing",
            concepts_without_approved_source(project),
            "concept(s) without an approved source",
        ),
        (
            "concept-link-unconfirmed",
            inferred_links(project),
            "inferred concept link(s) awaiting a human decision",
        ),
        (
            "layer-review-dropped",
            dropped_reviews(project),
            "review(s) did not count (not a human, or the session that wrote the item)",
        ),
        (
            "concept-cycle",
            concept_cycles(project),
            "concept(s) on a cycle of concept links",
        ),
    ):
        if found[0]:
            hits.append(_Hit(code, tuple(found[1]), f"{found[0]} {phrase}"))
    leaked, unscanned = _layer_leaks(project)
    if unscanned:
        hits.append(
            _Hit(
                "layer-scan-incomplete",
                tuple(unscanned),
                f"{len(unscanned)} evidence output(s) could not be computed and were not scanned "
                "for the interpretation layer",
            )
        )
    if leaked:
        hits.append(
            _Hit(
                "layer-leak",
                tuple(leaked),
                f"{len(leaked)} evidence output(s) mention the interpretation layer",
            )
        )
    return hits


@contextmanager
def _region_agent_view() -> Iterator[None]:
    """Region findings are computed for an agent (withheld regions left out) inside this block."""
    token = AGENT_VIEW.set(True)
    try:
        yield
    finally:
        AGENT_VIEW.reset(token)


def _regions(project: Project) -> list[_Hit]:
    """Findings of regions (plan Regions-B): ids and counts only, advisory in every mode."""
    return [_Hit(f.code, f.refs, f.message) for f in region_findings(project)]


def _organisation(project: Project) -> list[_Hit]:
    """Findings of the organisation class (labels, terms, consolidation, regions): counts and
    identifiers only. A project with none of them has none."""
    if not organisation_present(project):
        return []
    hits: list[_Hit] = []
    due = consolidation_due(project)
    if due.due:
        hits.append(
            _Hit(
                "consolidation-due",
                (),
                f"consolidation is due: {due.new_label_keys} new label key(s) and "
                f"{due.new_nodes} new idea(s) or concept(s) since the last completed pass",
            )
        )
    for code, found, phrase in (
        (
            "label-application-unconfirmed",
            unconfirmed_applications(project),
            "agent label application(s) inferred and awaiting a human decision",
        ),
        ("term-unused", unused_terms(project), "term(s) with no stated or confirmed application"),
    ):
        if found[0]:
            hits.append(_Hit(code, tuple(found[1]), f"{found[0]} {phrase}"))
    leaked = _organisation_leaks(project)
    if leaked:
        hits.append(
            _Hit(
                "organisation-leak",
                tuple(leaked),
                f"{len(leaked)} evidence output(s) mention a region, label, term or "
                "consolidation id",
            )
        )
    return hits


def _organisation_leaks(project: Project) -> list[str]:
    """Names of the evidence outputs that carry an organisation id. Outputs that cannot be
    computed are reported by `layer-scan-incomplete` when the layer is present."""
    snapshot = evidence_snapshot(project)
    leaked = [n for n, t in sorted(snapshot.items()) if ORGANISATION_ID.search(t)]
    for fmt in ("json", "dot"):
        if any(ORGANISATION_ID.search(chunk) for chunk in iter_graph_export(project, fmt)):
            leaked.append(f"export:{fmt}")
    return sorted(leaked)


def _snapshot_text(value: object) -> str:
    if hasattr(value, "model_dump_json"):
        return str(value.model_dump_json())
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_snapshot_text(v) for v in value) + "]"
    return repr(value)


_NOT_COMPUTED = "not-computed:"


def _attempt(read: Callable[[], object]) -> str:
    try:
        return _snapshot_text(read())
    except FactoryValidationError as error:  # e.g. no schema yet; reported as unscanned
        return _NOT_COMPUTED + ";".join(f"{i.field}:{i.reason}" for i in error.issues)


def evidence_snapshot(project: Project) -> dict[str, str]:
    """Each evidence output but the graph exports, serialised by name: the final rows, claims,
    groups, independence counts, evidence report, PRISMA flow and search report, methods
    statement (data and rendered text), contribution items, ideas, graph counts and the project
    status. An output that cannot be computed is marked `not-computed:` and reported by
    `layer-scan-incomplete`. `check` is not included (it reads this). The exports are scanned
    chunk by chunk in `_layer_leaks`. Not scanned: the Markdown renderings of the PRISMA flow and
    the evidence report (they are renderings of outputs scanned as data), the digest and the
    exports of bibliographies."""
    return {
        "final_rows": _attempt(lambda: final_rows(project)),
        "grouped_rows": _attempt(lambda: grouped_rows(project)),
        "independence": _attempt(lambda: independence_counts(final_rows(project))),
        "live_claims": _attempt(lambda: live_claims(project)),
        "evidence_report": _attempt(lambda: evidence_report(project)),
        "prisma": _attempt(lambda: prisma_flow(project)),
        "search_report": _attempt(lambda: search_report(project)),
        "methods": _attempt(lambda: methods_report(project)),
        "contribution_items": _attempt(lambda: final_items(project)),
        "ideas": _attempt(lambda: list_ideas(project, include_unconfirmed=True)),
        "graph_status": _attempt(lambda: graph_status(project)),
        "methods_text": _attempt(lambda: render_methods(methods_report(project))),
        "status": _attempt(lambda: project_status(project)),
    }


def _mentions_layer(text_: str) -> bool:
    return bool(_LAYER_ID.search(text_) or _LAYER_EDGE.search(text_) or _LAYER_CLASS.search(text_))


def _layer_leaks(project: Project) -> tuple[list[str], list[str]]:
    """Names of the evidence outputs that carry a layer identifier, a layer edge id or the layer
    class (ruling C5), and of those that could not be computed. The graph exports are read in
    chunks, never held whole."""
    snapshot = evidence_snapshot(project)
    unscanned = sorted(n for n, t in snapshot.items() if t.startswith(_NOT_COMPUTED))
    leaked = [name for name, text_ in sorted(snapshot.items()) if _mentions_layer(text_)]
    for fmt in ("json", "dot"):
        if any(_mentions_layer(chunk) for chunk in iter_graph_export(project, fmt)):
            leaked.append(f"export:{fmt}")
    return sorted(leaked), unscanned


def _contribution_schema_missing(project: Project) -> list[_Hit]:
    """The section is undeclared although G1 has run or a relation or idea exists."""
    protocol = current_protocol(project)
    if protocol is not None and protocol.spec.contribution_schema is not None:
        return []
    with project.index.connect() as conn:
        touched = any(
            conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None
            for table in ("reference_extractions", "relations", "ideas")
        )
    if not touched:
        return []
    return [
        _Hit(
            "contribution-schema-missing",
            (),
            "references or lineage records exist and the protocol declares no contribution schema",
        )
    ]


def _all_relations(project: Project) -> list[RelationView]:
    out: list[RelationView] = []
    while True:
        page = list_relations(project, statuses=set(EdgeStatus), limit=_PAGE, offset=len(out))
        out += page
        if len(page) < _PAGE:
            return out


def _relation_hits(project: Project) -> list[_Hit]:
    hits: list[_Hit] = []
    live = [r for r in _all_relations(project) if r.effective is not EdgeStatus.REJECTED]
    stale = sorted(r.relation_id for r in live if r.effective is EdgeStatus.STALE)
    if stale:
        hits.append(_Hit("relation-stale", tuple(stale), f"{len(stale)} relation(s) are stale"))
    inferred = sorted(r.relation_id for r in live if r.effective is EdgeStatus.INFERRED)
    if inferred:
        hits.append(
            _Hit(
                "relation-unconfirmed",
                tuple(inferred),
                f"{len(inferred)} inferred relation(s) await a human decision",
            )
        )
    uncited = sorted(r.relation_id for r in live if "uncited-base" in r.flags)
    if uncited:
        hits.append(
            _Hit(
                "relation-uncited-base",
                tuple(uncited),
                f"{len(uncited)} relation(s) name a base the paper does not cite",
            )
        )
    broken = _broken_chains(project, live)
    if broken:
        hits.append(
            _Hit(
                "relation-without-basis",
                tuple(broken),
                f"{len(broken)} stated or confirmed relation(s) have no recorded basis item or "
                "reference link",
            )
        )
    ideas = sorted(
        i.idea_id for i in list_ideas(project, include_unconfirmed=True) if i.state == "proposed"
    )
    if ideas:
        hits.append(
            _Hit("idea-unconfirmed", tuple(ideas), f"{len(ideas)} idea(s) await a human decision")
        )
    return hits


def _broken_chains(project: Project, live: list[RelationView]) -> list[str]:
    """Live stated or confirmed relations whose basis row was never recorded, or whose
    (reference extraction, entry) has no link row, found by an anti-join in SQL. A superseded or
    stale basis is still recorded: that is `relation-stale`, not a broken chain."""
    wanted = [
        r.relation_id
        for r in live
        if r.proposal_status == "stated" or r.decision is LineageDecision.CONFIRM
    ]
    if not wanted:
        return []
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.relation_id FROM relations r "
                "WHERE r.relation_id IN (SELECT value FROM json_each(:ids)) AND ("
                "r.basis_item IS NULL OR NOT EXISTS (SELECT 1 FROM extraction_rows e "
                "WHERE e.extraction_id = r.basis_item AND e.scope = 'contribution') "
                "OR (r.reference_extraction_id IS NOT NULL AND NOT EXISTS ("
                "SELECT 1 FROM reference_links l WHERE l.extraction_id = r.reference_extraction_id "
                "AND l.ordinal = r.cited_entry))) ORDER BY r.relation_id"
            ),
            {"ids": json.dumps(sorted(wanted))},
        ).all()
    return [str(r[0]) for r in rows]


# --- Conclusions (slice 4b, living-D) ---


def _conclusions(project: Project) -> list[_Hit]:
    """`conclusion-changed` (advisory) and `conclusion-basis-affected` (error in systematic) over
    the active conclusions, from `conclusion_diff` against the last snapshot. Refs are conclusion
    ids; no statement is read."""
    diffs = conclusion_diff(project)
    changed = [
        d.conclusion_id for d in diffs if d.state != "new" and d.predicate_before != d.predicate_now
    ]
    affected = [d.conclusion_id for d in diffs if d.affected]
    hits: list[_Hit] = []
    if changed:
        hits.append(
            _Hit(
                "conclusion-changed",
                tuple(changed),
                f"{len(changed)} conclusion(s) whose predicate differs from the last snapshot",
            )
        )
    if affected:
        hits.append(
            _Hit(
                "conclusion-basis-affected",
                tuple(affected),
                f"{len(affected)} conclusion(s) with an affected basis",
            )
        )
    return hits


# --- Notices and versions (slice 4b, living-C) ---


def _notice_hit(code: str, refs: list[str]) -> _Hit:
    return _Hit(code, tuple(refs), f"{len(refs)} {_NOTICE_PHRASES[code]}")


def _notices(project: Project, outcomes: Mapping[str, Outcome]) -> list[_Hit]:
    """Findings of the notices and versions observed for the works the review depends on.

    Messages carry counts; refs carry notice or work ids, never text from a notice."""
    hits: list[_Hit] = []
    observed = observed_notices(project)
    unassessed = unassessed_notices(observed, assessments(project))
    if unassessed:
        hits.append(_notice_hit("notice-unassessed", [n.notice_id for n in unassessed]))
        retracted = sorted(
            {
                n.work_id
                for n in unassessed
                if n.kind in (NoticeKind.RETRACTION, NoticeKind.WITHDRAWAL)
                and outcomes.get(n.work_id) is Outcome.INCLUDED
            }
        )
        if retracted:
            hits.append(_notice_hit("included-retracted", retracted))
    failed = unrecovered_failures(project)
    if failed:
        hits.append(_notice_hit("status-lookup-failed", failed))
    protocol = current_protocol(project)
    plan = None if protocol is None else protocol.spec.watch_plan
    if plan is not None:
        hits += _notice_coverage(project, plan.notices, plan.notice_budget)
    newer = sorted({v.work_id for v in newer_versions(project)})
    if newer:
        hits.append(_notice_hit("newer-version-available", newer))
    published = vor_available(project)
    if published:
        hits.append(_notice_hit("version-of-record-available", published))
    for conflict in link_conflicts(project):
        hits.append(
            _Hit(
                "version-link-conflict",
                (conflict.work_id, conflict.other_work_id),
                f"1 {_NOTICE_PHRASES['version-link-conflict']}",
            )
        )
    return hits


def _notice_coverage(project: Project, notice_sources: tuple[str, ...], budget: int) -> list[_Hit]:
    """`notice-unchecked-crossref` and `notice-coverage-age` (spec ruling 2 of the plan)."""
    dependents = dependent_works(project)
    if not dependents:
        return []
    hits: list[_Hit] = []
    from factory.services.search import works_by_ids

    known = works_by_ids(project, dependents)
    if "crossref" in notice_sources:
        without = [w.id for w in known if crossref_doi(w) is None]
        if without:
            hits.append(_notice_hit("notice-unchecked-crossref", sorted(without)))
    if budget > 0:
        limit = 3 * math.ceil(len(dependents) / budget)
        checked = effective_last_checked(project, known, notice_sources)
        finished = sorted(
            v.started_at.isoformat() for v in cycles(project) if v.status is not CycleStatus.OPEN
        )
        stale = [
            w
            for w in dependents
            if checked.get(w) is not None
            and sum(1 for started in finished if started > _iso(checked.get(w))) > limit
        ]
        if stale:
            hits.append(_notice_hit("notice-coverage-age", stale))
    return hits


def _iso(stamp: str | None) -> str:
    """A status run's start (`...Z`) as the cycles' `isoformat` text, for ordering; '' when the
    work was never checked."""
    if not stamp:
        return ""
    return parse_ts(stamp).isoformat()


# --- Living review (slice 4b) ---


def _living(project: Project) -> list[_Hit]:
    """Findings of a living review: the watch, its cycles, the update audit, model drift.

    Messages carry ids, source names and counts, never document text. Nothing is reported for a
    project that declares no watch and has run no cycle, except `watch-plan-missing`."""
    protocol = current_protocol(project)
    if protocol is None:
        return []
    hits: list[_Hit] = []
    if watch_plan_gaps(protocol.spec, RigorMode.EXPLORATORY):
        hits.append(
            _Hit("watch-plan-missing", (), "the living-review profile declares no watch_plan")
        )
    views = cycles(project)
    now = project.clock.now()
    for view in views:
        if view.status is CycleStatus.OPEN and now - view.started_at > timedelta(days=1):
            hits.append(
                _Hit("watch-cycle-open", (view.cycle_id,), "a watch cycle has been open over a day")
            )
    plan = protocol.spec.watch_plan
    if plan is not None:
        hits += _watch_sources(project, plan.max_consecutive_failures, plan.until, now)
    if views:
        hits += _window_misses(project)
        shortfall = audit_shortfall(project)
        if shortfall > 0:
            hits.append(
                _Hit(
                    "update-audit-outstanding",
                    (),
                    f"the audit is short by {shortfall} work(s) after the updates; "
                    "run `factory audit sample --top-up`",
                )
            )
        hits += _model_drift(project)
    return hits


def _watch_sources(
    project: Project, max_failures: int, until: date | None, now: datetime
) -> list[_Hit]:
    status = watch_status(project)
    hits: list[_Hit] = []
    for item in status.sources:
        if item.consecutive_failures >= max_failures:
            hits.append(
                _Hit(
                    "watch-source-failing",
                    (item.source,),
                    f"{item.source}: {item.consecutive_failures} cycles ended without it "
                    "completing",
                )
            )
        ended = until is not None and now.date() > until
        if (
            not ended
            and item.next_due is not None
            and now > item.next_due + timedelta(days=item.interval_days)
        ):
            hits.append(
                _Hit(
                    "watch-overdue",
                    (item.source,),
                    f"{item.source}: no finished cycle for more than two intervals",
                )
            )
    return hits


def _window_misses(project: Project) -> list[_Hit]:
    """The latest full replay of a windowed source, when it found works the windows missed."""
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT s.cycle_id, s.source FROM watch_cycle_sources s JOIN watch_cycles c"
                " ON c.cycle_id = s.cycle_id WHERE s.mode = 'window' AND s.full_replay = 1"
                " AND c.status != 'open' ORDER BY c.started_at DESC, c.cycle_id DESC LIMIT 1"
            )
        ).one_or_none()
    if row is None:
        return []
    cycle_id, source = str(row[0]), str(row[1])
    missed = next(
        (c.window_missed for c in source_counts(project, cycle_id) if c.source == source), None
    )
    if not missed:
        return []
    return [
        _Hit(
            "window-misses",
            (cycle_id,),
            f"{source}: the full replay found {missed} work(s) the windows missed",
        )
    ]


def _model_drift(project: Project) -> list[_Hit]:
    """Sessions of a pass whose model no calibration of the pass recorded (ruling 22)."""
    hits: list[_Hit] = []
    for label in PassLabel:
        models = calibrated_models(project, label)
        if not models:
            continue
        with project.index.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT model FROM pass_sessions WHERE pass_label = :label"
                    " AND stage = 'title-abstract' ORDER BY model"
                ),
                {"label": label.value},
            ).all()
        drifted = [str(r[0]) for r in rows if str(r[0]) not in models]
        if drifted:
            hits.append(
                _Hit(
                    "calibration-model-drift",
                    (f"pass-{label.value}",),
                    f"pass {label.value}: model(s) {', '.join(drifted)} were not calibrated for it",
                )
            )
    return hits


def _inbox(project: Project, outcomes: Mapping[str, Outcome]) -> list[_Hit]:
    """Link inbox (slice 4a): items left open once title/abstract screening has nothing
    pending, items whose last resolve failed, and supplied lookups run under a deviation while
    the protocol declares no `supplied_links` (listed for the methods text, not an error)."""
    with project.index.connect() as conn:
        open_items = [
            str(i)
            for (i,) in conn.execute(
                text("SELECT item_id FROM inbox_items WHERE status = 'open' ORDER BY item_id")
            ).all()
        ]
        failed = [
            str(i)
            for (i,) in conn.execute(
                text(
                    "SELECT r.item_id FROM inbox_resolutions r JOIN inbox_items i"
                    " ON i.item_id = r.item_id WHERE i.status = 'open' AND r.event_id ="
                    " (SELECT MAX(event_id) FROM inbox_resolutions WHERE item_id = r.item_id)"
                    " AND r.status = 'failed' ORDER BY r.item_id"
                )
            ).all()
        ]
        deviated = [
            str(i)
            for (i,) in conn.execute(
                text(
                    "SELECT DISTINCT item_id FROM inbox_resolutions"
                    " WHERE deviation_id IS NOT NULL ORDER BY item_id"
                )
            ).all()
        ]
    hits: list[_Hit] = []
    screened = bool(outcomes) and Outcome.PENDING not in outcomes.values()
    if open_items and screened:
        hits.append(
            _Hit(
                "inbox-open-after-screening",
                tuple(open_items),
                f"{len(open_items)} inbox item(s) open while no title/abstract work is pending",
            )
        )
    if failed:
        hits.append(
            _Hit("inbox-resolve-failed", tuple(failed), f"{len(failed)} inbox item(s) failed")
        )
    protocol = current_protocol(project)
    if deviated and (protocol is None or protocol.spec.supplied_links is None):
        hits.append(
            _Hit(
                "supplied-without-plan",
                tuple(deviated),
                f"{len(deviated)} supplied link(s) resolved under a deviation; the protocol "
                "declares no supplied_links",
            )
        )
    return hits


# --- Links and provenance ---


def _broken_links(project: Project) -> list[_Hit]:
    """Identifiers named by an event's refs or its work payload that no row defines."""
    with project.index.connect() as conn:
        stored = conn.execute(text("SELECT refs FROM events")).scalars().all()
    candidates: set[str] = set()
    for refs in stored:
        candidates.update(str(ref) for ref in json.loads(str(refs)))
    for event in read_all(project.paths.events_dir, project.catalog):
        work = event.payload.get("work_id")
        if isinstance(work, str):
            candidates.add(work)
    candidates.update(_cited_criteria(project))
    dangling = dangling_refs(project, candidates)
    if not dangling:
        return []
    return [_Hit("broken-link", tuple(dangling), f"{len(dangling)} identifier(s) name no row")]


_CRITERION_COLUMNS = (
    "SELECT criterion FROM decisions UNION SELECT criterion FROM resolutions "
    "UNION SELECT criterion FROM calibration_labels UNION SELECT criterion FROM audit_items"
)


def _cited_criteria(project: Project) -> set[str]:
    """Every qualified criterion (`P@xxxx:EX01`) that a decision, resolution, calibration label
    or audit label cites. `dangling_refs` reports one that no protocol version defines."""
    with project.index.connect() as conn:
        rows = conn.execute(text(_CRITERION_COLUMNS)).scalars().all()
    return {str(criterion) for criterion in rows if criterion is not None}


def _provenance_rows(project: Project) -> list[tuple[str, str, str | None, str | None, str | None]]:
    """(event id, actor kind, model, skill, input blob) of every agent event."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, actor_kind, model, skill, input_blob FROM events "
                "WHERE actor_kind = 'agent' ORDER BY id"
            )
        ).all()
    return [
        (
            str(event_id),
            str(kind),
            None if model is None else str(model),
            None if skill is None else str(skill),
            None if blob is None else str(blob),
        )
        for event_id, kind, model, skill, blob in rows
    ]


def _missing_provenance(project: Project) -> list[_Hit]:
    """Agent events without a model, a skill or an input blob (R-02, provenance)."""
    gaps = sorted(
        event_id
        for event_id, _kind, model, skill, blob in _provenance_rows(project)
        if model is None or skill is None or blob is None
    )
    if not gaps:
        return []
    return [
        _Hit(
            "missing-provenance",
            tuple(gaps),
            f"{len(gaps)} agent event(s) lack a model, a skill or an input blob",
        )
    ]


# --- Search ---


def _shortfalls(project: Project) -> list[_Hit]:
    """Searches that retrieved fewer records than they reported, with no recorded reason (R-23)."""
    gaps = [
        row.query_id
        for row in search_report(project).rows
        if row.reported is not None
        and row.retrieved < row.reported
        and row.shortfall_reason is None
    ]
    if not gaps:
        return []
    return [
        _Hit(
            "shortfall-unexplained",
            tuple(gaps),
            f"{len(gaps)} search(es) retrieved fewer records than reported, with no reason",
        )
    ]


# --- Seeds (R-24) ---


def _seeds(project: Project) -> list[_Hit]:
    """Positive seeds not retrieved and not explained, and explained ones whose admission route
    is not yet admitted. One finding per role, so an aggregate view needs no message parsing."""
    routes, admitted = _seed_explanations(project)
    missing: dict[str, list[str]] = {}
    pending: dict[str, list[str]] = {}
    for check in seed_check(project):
        key = _ROLE_KEYS[check.role]
        # A seed reached only by a supplied link was not retrieved (slice 4a ruling 9).
        unexplained = check.status == "supplied" and check.seed_id not in routes
        if check.status == "missing" or unexplained:
            missing.setdefault(key, []).append(check.seed_id)
        elif (
            check.status in ("explained", "supplied")
            and check.seed_id not in admitted
            and routes.get(check.seed_id) in _ADMISSION_ROUTES
        ):
            pending.setdefault(key, []).append(check.seed_id)
    hits = [
        _Hit(
            "seed-missing",
            tuple(sorted(ids)),
            f"{len(ids)} {role} positive seed(s) not retrieved and not explained",
            role=role,
        )
        for role, ids in sorted(missing.items())
    ]
    hits += [
        _Hit(
            "seed-admission-pending",
            tuple(sorted(ids)),
            f"{len(ids)} {role} positive seed(s) explained, admission route not yet admitted",
            role=role,
        )
        for role, ids in sorted(pending.items())
    ]
    return hits


def _seed_explanations(project: Project) -> tuple[dict[str, ProvenanceMethod], set[str]]:
    """Each explained seed's planned route, and the set of admitted seeds."""
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT seed_id, route FROM seed_explanations")).all()
        admitted = set(admitted_works(conn))
    routes = {str(seed_id): ProvenanceMethod(str(route)) for seed_id, route in rows}
    return routes, admitted


# --- Protocol and press ---


def _protocol_gates(project: Project) -> list[_Hit]:
    """No ready protocol; no confirmed PRESS review of its search strategy."""
    protocol = current_protocol(project)
    if protocol is None:
        return [_Hit("protocol-not-ready", (), "no protocol is recorded")]
    hits: list[_Hit] = []
    if protocol.status is not ProtocolStatus.READY:
        hits.append(_Hit("protocol-not-ready", (protocol.protocol_id,), "the protocol is a draft"))
    report = search_report(project)
    if not report.press_confirmed:
        refs = () if report.press_review_id is None else (report.press_review_id,)
        hits.append(_Hit("press-missing", refs, "no confirmed PRESS review of the search strategy"))
    return hits


# --- Screening (R-31 to R-38) ---


def _screening(project: Project, outcomes: dict[str, Outcome]) -> list[_Hit]:
    pending = sorted(work for work, outcome in outcomes.items() if outcome is Outcome.PENDING)
    hits: list[_Hit] = []
    if pending:
        hits.append(
            _Hit(
                "screening-pending", tuple(pending), f"{len(pending)} work(s) have no final outcome"
            )
        )
    single = single_pass_works(project)
    if single:
        hits.append(
            _Hit(
                "single-pass",
                tuple(single),
                f"{len(single)} work(s) have an outcome decided by pass A alone",
            )
        )
    return hits


def _calibration_and_agreement(project: Project) -> list[_Hit]:
    protocol = current_protocol(project)
    if protocol is None:
        return []
    hits: list[_Hit] = []
    status = calibration_status(project)
    labels = ["A", "B"] if protocol.spec.screening.passes == 2 else ["A"]
    unpassed = [label for label in labels if not status.passed.get(label, False)]
    if unpassed:
        hits.append(
            _Hit(
                "calibration-missing",
                (),
                f"calibration not passed by pass {', '.join(unpassed)}",
            )
        )
    agreement = agreement_summary(project)
    if agreement is not None and agreement.below_floor:
        hits.append(
            _Hit(
                "kappa-below-floor",
                (),
                f"kappa {agreement.kappa} is below the declared floor {agreement.kappa_floor}",
                severity="error" if agreement.enforced else "warning",
            )
        )
    return hits


def _audit(project: Project) -> list[_Hit]:
    hits: list[_Hit] = []
    if audit_outstanding(project):
        hits.append(_Hit("audit-missing", (), "the agreed works have no audit over their set"))
    report = audit_report(project)
    if report is not None and report.above_ceiling:
        hits.append(
            _Hit(
                "audit-error-high",
                (report.audit_id,),
                f"false-exclusion rate {report.rates.false_exclusion} is above the ceiling "
                f"{report.ceiling}",
            )
        )
    return hits


# --- Supplementary search and merges ---


def _last_decision_ulid(project: Project) -> str | None:
    """The ULID of the latest screening decision event, or None when there is none."""
    with project.index.connect() as conn:
        last = conn.execute(
            text("SELECT MAX(id) FROM events WHERE type = :type"),
            {"type": "screening.decision_recorded"},
        ).scalar_one()
    return None if last is None else str(last).split("_", 1)[1]


def _chase(project: Project, outcomes: dict[str, Outcome]) -> list[_Hit]:
    """Promoted works exist and no citation chase round follows the last screening decision.

    The proxy is "no chase round after the last `screening.decision_recorded` event", compared by
    ULID order. It is stricter than "after the last agreement", which is not an event in the log:
    any decision recorded after the latest round brings the finding back, even one that changes
    no agreed outcome. A protocol whose `snowball_plan` allows a round governs chasing by that
    plan, its rounds and its stopping rule, so the finding does not apply.
    """
    if not any(outcome is Outcome.INCLUDED for outcome in outcomes.values()):
        return []
    protocol = current_protocol(project)
    plan = None if protocol is None else protocol.spec.snowball_plan
    if plan is not None and (plan.max_backward_rounds or plan.max_forward_rounds):
        return []
    rounds = [round_.round_id.split("_", 1)[1] for round_ in chase_rounds(project)]
    last = _last_decision_ulid(project)
    if rounds and (last is None or max(rounds) > last):
        return []
    return [
        _Hit(
            "chase-missing",
            (),
            "promoted works exist and no citation chase round follows the last decision",
        )
    ]


def _checklist(project: Project) -> list[_Hit]:
    """PRISMA 2020 items with no derived source, for a project that declares a protocol (R-60)."""
    if current_protocol(project) is None:
        return []
    methods = methods_report(project)
    uncovered = [
        item for item in _PRISMA_CHECKLIST if item.derived is None or not item.derived(methods)
    ]
    if not uncovered:
        return []
    listed = "; ".join(f"{item.number} ({item.text})" for item in uncovered)
    return [
        _Hit(
            "profile-checklist",
            tuple(f"prisma-2020:{item.number}" for item in uncovered),
            f"PRISMA 2020 items with no derived source: {listed}",
        )
    ]


def _merge_conflicts(project: Project, outcomes: dict[str, Outcome]) -> list[_Hit]:
    """A merged group whose primary and an absorbed record have different decided outcomes.

    PRISMA counts only the primary's outcome and screening queues the raw works, so a conflict is
    visible only here. A pending record is not a verdict and is not compared.
    """
    hits: list[_Hit] = []
    for merge in active_merges(project):
        primary = outcomes.get(merge.primary)
        if primary not in _DECIDED:
            continue
        conflicting = [
            absorbed
            for absorbed in merge.absorbed
            if outcomes.get(absorbed) in _DECIDED and outcomes[absorbed] is not primary
        ]
        if conflicting:
            hits.append(
                _Hit(
                    "merge-verdict-conflict",
                    (merge.primary, *conflicting),
                    f"merge {merge.merge_id}: absorbed record(s) carry a different outcome",
                )
            )
    return hits


# --- Full text (plan 2A, task 11) ---


def _fulltext(project: Project) -> list[_Hit]:
    """Library entries that are missing or corrupt, changed sources, and promoted works never
    sought. A document's findings name its document and its work. A missing entry is a warning,
    since the library is not in git; a corrupt one is an error, since its bytes are not the
    document's."""
    hits: list[_Hit] = []
    for document_id, work_id, raw_hash in _stored_documents(project):
        state = _library_state(project, raw_hash)
        if state == "missing":
            hits.append(
                _Hit(
                    "library-missing",
                    (document_id, work_id),
                    "a document has no library entry; restore it",
                )
            )
        elif state == "corrupt":
            hits.append(
                _Hit(
                    "library-corrupt",
                    (document_id, work_id),
                    "a library entry does not hash to its document",
                )
            )
    hits += _conversion_library(project)
    for document_id, work_id in _changed_sources(project):
        hits.append(
            _Hit(
                "source-changed",
                (document_id, work_id),
                "a re-fetch hashed differently from its document; a decision is needed",
            )
        )
    unsought = [
        entry.work_id for entry in fulltext_status(project).works if entry.state == "unsought"
    ]
    if unsought:
        hits.append(
            _Hit(
                "fulltext-unsought",
                tuple(unsought),
                f"{len(unsought)} promoted work(s) have no full-text attempt",
            )
        )
    hits += _stale_document_decisions(project)
    return hits


def _stale_document_decisions(project: Project) -> list[_Hit]:
    """Live full-text decisions pinned to a conversion that is no longer the work's default
    (a newer document or conversion exists, or the pinned one is gone). The decision stands; the
    finding names its works so the researcher can decide whether to re-screen (plan 2C ruling 3).
    Reads decisions only, so it never touches the full-text plan."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT work_id, conversion_id FROM decisions WHERE stage = :stage "
                "AND superseded_by IS NULL AND conversion_id IS NOT NULL ORDER BY work_id"
            ),
            {"stage": ScreeningStage.FULL_TEXT.value},
        ).all()
    stale: set[str] = set()
    for work_id, conversion_id in rows:
        current = default_conversion(project, str(work_id))
        if current is None or current.conversion_id != str(conversion_id):
            stale.add(str(work_id))
    if not stale:
        return []
    return [
        _Hit(
            "fulltext-decision-stale-document",
            tuple(sorted(stale)),
            f"{len(stale)} work(s) have a full-text decision pinned to a conversion that is "
            "no longer the current one",
        )
    ]


def _stored_documents(project: Project) -> list[tuple[str, str, str]]:
    """(document id, work id, library hash) of every document, superseded ones included."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT document_id, work_id, raw_hash FROM fulltext_documents ORDER BY event_id")
        ).all()
    return [(str(d), str(w), str(h)) for d, w, h in rows]


def _conversion_library(project: Project) -> list[_Hit]:
    """Conversions whose Markdown or manifest blob is missing (a warning) or corrupt (an error).

    A hit names (document id, work id, conversion id), in event order. A conversion with one blob
    missing and the other corrupt gets one hit of each code.
    """
    hits: list[_Hit] = []
    for conversion_id, document_id, work_id, markdown_hash, manifest_hash in _conversions(project):
        refs = (document_id, work_id, conversion_id)
        states = {_library_state(project, markdown_hash), _library_state(project, manifest_hash)}
        if "missing" in states:
            hits.append(
                _Hit(
                    "library-missing",
                    refs,
                    "a conversion has no library entry; run `factory document convert --restore`",
                )
            )
        if "corrupt" in states:
            hits.append(
                _Hit(
                    "library-corrupt",
                    refs,
                    "a conversion's library entry does not hash to its reference",
                )
            )
    return hits


def _conversions(project: Project) -> list[tuple[str, str, str, str, str]]:
    """(conversion id, document id, work id, Markdown hash, manifest hash) of every conversion, in
    event order. Superseded documents included."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.conversion_id, c.document_id, d.work_id, c.markdown_hash, "
                "c.manifest_hash FROM document_conversions c JOIN fulltext_documents d "
                "ON d.document_id = c.document_id ORDER BY c.event_id"
            )
        ).all()
    return [(str(a), str(b), str(c), str(d), str(e)) for a, b, c, d, e in rows]


def _changed_sources(project: Project) -> list[tuple[str, str]]:
    """(document id, work id) of every recorded source change, in event order."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.document_id, d.work_id FROM fulltext_source_changes c "
                "JOIN fulltext_documents d ON d.document_id = c.document_id "
                "ORDER BY c.event_id"
            )
        ).all()
    return [(str(d), str(w)) for d, w in rows]


def _library_state(project: Project, raw_hash: str) -> Literal["ok", "missing", "corrupt"]:
    """Whether the library holds the hash's bytes. Only `corrupt` reads the file: `BlobStore.get`
    raises when the stored bytes no longer hash to the reference."""
    if not project.library.exists(raw_hash):
        return "missing"
    try:
        project.library.get(raw_hash)
    except BlobIntegrityError:
        return "corrupt"
    return "ok"


# --- Extraction (plan D, task 10) ---


def _extraction(project: Project) -> list[_Hit]:
    """Findings of the extraction stage. Each names works, rows or conversions by identifier and
    carries counts and fixed text only, never a field value or a quote. Without a ready protocol
    declaring a schema and a full-text plan there is no extraction stage and no finding."""
    try:
        _, schema, _ = require_schema(project)
        population = extraction_population(project)
    except FactoryValidationError:
        return []
    inside = set(population)
    hits: list[_Hit] = []
    pending = sorted({s.work_id for s in unit_states(project) if s.state != "current"})
    if pending:
        hits.append(
            _Hit(
                "extraction-pending",
                tuple(pending),
                f"{len(pending)} included work(s) have a unit not yet current",
            )
        )
    config = pass_config(project, PassLabel.B)
    if config is not None:
        single = sorted(
            w for w in population if not in_dual_sample(config.seed, w, schema.dual_extract_sample)
        )
        if single:
            hits.append(
                _Hit(
                    "extraction-single",
                    tuple(single),
                    f"{len(single)} work(s) are extracted once, outside the dual sample",
                )
            )
    unresolved = sorted({d.work_id for d in grouped_rows(project).unresolved})
    if unresolved:
        hits.append(
            _Hit(
                "extraction-unresolved",
                tuple(unresolved),
                f"{len(unresolved)} work(s) have unresolved extraction disagreements",
            )
        )
    if extraction_audit_outstanding(project):
        hits.append(
            _Hit(
                "extraction-audit-missing",
                (),
                "extraction audit not drawn for the current agreed values",
            )
        )
    audit = extraction_audit_report(project)
    if audit is not None and audit.above_ceiling:
        hits.append(
            _Hit(
                "extraction-error-high",
                (audit.audit_id,),
                "the extraction audit's error rate is above the declared ceiling",
            )
        )
    stale = stale_extractions(project)
    live = [row for row in live_rows(project) if row.work_id in inside]
    stale_ids = sorted(row.extraction_id for row in live if row.extraction_id in stale)
    if stale_ids:
        hits.append(
            _Hit(
                "extraction-schema-stale",
                tuple(stale_ids),
                f"{len(stale_ids)} extraction row(s) are stale and are re-extracted",
            )
        )
    hits += _extraction_library(project, {row.conversion_id for row in live})
    documents = [w for w in stale_documents(project) if w in inside]
    if documents:
        hits.append(
            _Hit(
                "extraction-document-stale",
                tuple(documents),
                f"{len(documents)} work(s) are extracted from a conversion that is no longer "
                "the current one",
            )
        )
    copied = sorted(
        {
            row.work_id
            for row in live
            if row.extraction_id not in stale
            and any(f.copy_marker and f.reported_in.value == "own" for f in row.fields.values())
        }
    )
    if copied:
        hits.append(
            _Hit(
                "extraction-copy-flag",
                tuple(copied),
                f"{len(copied)} work(s) declare a result as their own where a citation marker "
                "was found",
            )
        )
    return hits


def _extraction_library(project: Project, pinned: set[str]) -> list[_Hit]:
    """Pinned conversions whose Markdown or manifest blob is absent from the library."""
    missing = sorted(
        conversion_id
        for conversion_id, _document, _work, markdown, manifest in _conversions(project)
        if conversion_id in pinned
        and "missing" in {_library_state(project, markdown), _library_state(project, manifest)}
    )
    if not missing:
        return []
    return [
        _Hit(
            "extraction-library-missing",
            tuple(missing),
            f"{len(missing)} conversion(s) pinned by extraction rows have a missing library entry",
        )
    ]


# --- Evidence report (plan E, task 7) ---

_DIRECTION_PROBLEMS = frozenset({"conflict", "unparseable", "unknown"})


def _evidence(project: Project) -> list[_Hit]:
    """Findings of the evidence report, from one `evidence_report` call. Messages give counts and
    identifiers only; none names a value, a method or a quote. No finding without a schema."""
    report = evidence_report(project)
    if report.pack is None:
        return []
    hits: list[_Hit] = []
    omitted = [e for e in report.excluded if e.reason in ("unresolved", "stale")]
    if omitted:
        works = sorted({w for e in omitted for w in e.works})
        counts = ", ".join(f"{e.count} {e.reason}" for e in omitted)
        hits.append(
            _Hit(
                "evidence-excluded-rows",
                tuple(works),
                f"the evidence report omits rows ({counts}) of {len(works)} work(s)",
            )
        )
    if report.ungrouped:
        works = sorted({r.work_id for r in report.ungrouped})
        hits.append(
            _Hit(
                "evidence-ungrouped",
                tuple(works),
                f"{len(report.ungrouped)} row(s) of {len(works)} work(s) lack a comparability key "
                "and belong to no group",
            )
        )
    bad = sorted(g.group_id for g in report.groups if g.direction_status in _DIRECTION_PROBLEMS)
    if bad:
        hits.append(
            _Hit(
                "evidence-direction",
                tuple(bad),
                f"{len(bad)} group(s) have a metric direction that is conflicting, unparseable "
                "or unknown; no frontier is computed",
            )
        )
    return hits


# --- References and snowballing (slice 3a, plan G1 task 8) ---


@dataclass(frozen=True)
class _LiveExtraction:
    extraction_id: str
    work_id: str
    conversion_id: str
    flags: tuple[str, ...]
    bbl_status: str
    bbl_archive: str | None


def _live_extractions(project: Project) -> list[_LiveExtraction]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT extraction_id, work_id, conversion_id, flags, bbl_status, bbl_archive "
                "FROM reference_extractions WHERE live = 1 ORDER BY extraction_id"
            )
        ).all()
    return [
        _LiveExtraction(
            str(x), str(w), str(c), tuple(str(f) for f in json.loads(str(flags))), str(b), a
        )
        for x, w, c, flags, b, a in rows
    ]


def _references(project: Project) -> list[_Hit]:
    """Findings of reference extraction. Each names works or extractions by identifier and gives
    counts; none carries an entry's text or a parsed field."""
    live = _live_extractions(project)
    extracted = {row.work_id for row in live}
    hits: list[_Hit] = []
    missing = [
        w
        for w in included_works(project)
        if w not in extracted and default_conversion(project, w) is not None
    ]
    if missing:
        hits.append(
            _Hit(
                "references-missing-extraction",
                tuple(missing),
                f"{len(missing)} included work(s) have a converted document and no reference "
                "extraction",
            )
        )
    stale = [row.extraction_id for row in live if current_extraction(project, row.work_id) is None]
    if stale:
        hits.append(
            _Hit(
                "references-stale-extraction",
                tuple(stale),
                f"{len(stale)} reference extraction(s) are pinned to a conversion or parser "
                "version that is no longer current",
            )
        )
    incomplete = [
        row.extraction_id
        for row in live
        if _INCOMPLETE_FLAGS & set(row.flags) or row.bbl_status == "count-mismatch"
    ]
    if incomplete:
        hits.append(
            _Hit(
                "references-parse-incomplete",
                tuple(incomplete),
                f"{len(incomplete)} reference extraction(s) are flagged incomplete (parse, "
                "marker gap, no bibliography or bbl count mismatch)",
            )
        )
    lost = lost_human_decisions(project)
    if lost:
        hits.append(
            _Hit(
                "references-decision-lost",
                tuple(lost),
                f"{sum(lost.values())} human reference decision(s) name an entry that the live "
                f"extraction of their work no longer has ({len(lost)} extraction(s))",
            )
        )
    above = _above_ceiling(project)
    if above:
        hits.append(
            _Hit(
                "references-unresolved-ceiling",
                tuple(above),
                f"{len(above)} reference extraction(s) leave more than "
                f"{REFERENCE_UNRESOLVED_CEILING:.0%} of their entries unresolved or ambiguous",
            )
        )
    blobs = {c: (markdown, manifest) for c, _d, _w, markdown, manifest in _conversions(project)}
    absent = [
        row.extraction_id
        for row in live
        if any(
            not project.library.exists(h)
            for h in (*blobs.get(row.conversion_id, ()), *filter(None, [row.bbl_archive]))
        )
    ]
    if absent:
        hits.append(
            _Hit(
                "references-library-missing",
                tuple(absent),
                f"{len(absent)} reference extraction(s) have a conversion or bbl archive missing "
                "from the library",
            )
        )
    return hits


def _above_ceiling(project: Project) -> list[str]:
    """Live extractions whose unresolved and ambiguous links exceed the ceiling (ruling 17)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT x.extraction_id, COUNT(n.ordinal), "
                "(SELECT COUNT(*) FROM reference_links l WHERE l.extraction_id = x.extraction_id "
                "AND l.state IN (:unresolved, :ambiguous)) "
                "FROM reference_extractions x LEFT JOIN reference_entries n "
                "ON n.extraction_id = x.extraction_id WHERE x.live = 1 "
                "GROUP BY x.extraction_id ORDER BY x.extraction_id"
            ),
            {"unresolved": LinkState.UNRESOLVED.value, "ambiguous": LinkState.AMBIGUOUS.value},
        ).all()
    return [
        str(x)
        for x, entries, open_ in rows
        if int(entries) and int(open_) / int(entries) > REFERENCE_UNRESOLVED_CEILING
    ]


def _gate_policies(project: Project) -> list[_Hit]:
    """Gate policies weaker than a stricter mode's preset (ruling 8), as promotion gaps: those
    weaker than the pilot preset are errors in pilot and systematic, those weaker only than the
    systematic preset are errors in systematic. Exploratory allows both."""
    protocol = current_protocol(project)
    if protocol is None or protocol.spec.gate_policies is None:
        return []
    entries = protocol.spec.gate_policies.entries
    pilot = {g.field for g in gate_policy_gaps(protocol.spec, RigorMode.PILOT)}
    systematic = {g.field for g in gate_policy_gaps(protocol.spec, RigorMode.SYSTEMATIC)} - pilot

    def gates_of(fields: set[str]) -> tuple[str, ...]:
        return tuple(
            e.gate for i, e in enumerate(entries) if f"gate_policies.entries.{i}.policy" in fields
        )

    hits: list[_Hit] = []
    for code, fields, mode in (
        ("gate-policy-below-pilot-preset", pilot, "pilot"),
        ("gate-policy-below-systematic-preset", systematic, "systematic"),
    ):
        if fields:
            hits.append(
                _Hit(
                    code,
                    gates_of(fields),
                    f"{len(fields)} gate polic(ies) are weaker than the {mode} preset",
                )
            )
    return hits


def _snowball(project: Project, outcomes: dict[str, Outcome]) -> list[_Hit]:
    """Findings of the snowball rounds: a missing stopping rule (a promotion gap, ruling 19),
    rounds beyond the declared plan, and snowballed works included without a screening decision
    (a broken chain)."""
    hits: list[_Hit] = []
    protocol = current_protocol(project)
    if protocol is not None and snowball_plan_gaps(protocol.spec, RigorMode.SYSTEMATIC):
        hits.append(
            _Hit(
                "snowball-plan-missing",
                (protocol.protocol_id,),
                "the protocol declares no snowball stopping rule (snowball_plan)",
            )
        )
    rounds = recorded_rounds(project)
    plan = None if protocol is None else protocol.spec.snowball_plan
    if plan is not None:
        limits = {
            Direction.BACKWARD: plan.max_backward_rounds,
            Direction.FORWARD: plan.max_forward_rounds,
        }
        over = [r.round_id for r in rounds if r.round_no > limits[r.direction]]
        delegated = {r.chase_round_id for r in rounds}
        forward = forward_chase_rounds(project)[plan.max_forward_rounds :]
        over += [round_id for round_id in forward if round_id not in delegated]
        if over:
            hits.append(
                _Hit(
                    "snowball-over-plan",
                    tuple(over),
                    f"{len(over)} round(s) exceed the declared maximum of their direction",
                )
            )
    unscreened = _unscreened(project, outcomes, [r.round_id for r in rounds])
    if unscreened:
        hits.append(
            _Hit(
                "snowball-unscreened",
                tuple(unscreened),
                f"{len(unscreened)} snowballed work(s) are included without a screening decision",
            )
        )
    return hits


def _unscreened(project: Project, outcomes: dict[str, Outcome], rounds: list[str]) -> list[str]:
    """Works retrieved by a snowball round's runs (as dedup primaries) whose final outcome is
    INCLUDED with no screening decision and no calibration label behind it."""
    if not rounds:
        return []
    primary = {a: m.primary for m in active_merges(project) for a in m.absorbed}
    runs = [run for round_id in rounds for run in round_runs(project, round_id)]
    with project.index.connect() as conn:
        found = {
            primary.get(str(w), str(w))
            for (w,) in conn.execute(
                text(
                    "SELECT DISTINCT work_id FROM provenance "
                    "WHERE run_id IN (SELECT value FROM json_each(:runs))"
                ),
                {"runs": json.dumps(runs)},
            ).all()
        }
        decided = {
            str(w)
            for (w,) in conn.execute(
                text("SELECT work_id FROM decisions UNION SELECT work_id FROM calibration_labels")
            ).all()
        }
    return sorted(w for w in found if outcomes.get(w) is Outcome.INCLUDED and w not in decided)


# --- Imported libraries (slice 3d) ---

_IMPORT_COUNTS: dict[str, str] = {
    "import-unresolved": "record(s) unresolved",
    "import-unconfirmed": "record(s) await confirmation of a fuzzy or ambiguous match",
    "import-attachment-missing": "record(s) name a file that was not readable at import",
    "import-identity-unchecked": "PDF record(s) neither attached nor confirmed by a human",
}
"""The count findings of an import and the phrase after the count. Messages carry the count and
no record, title or ordinal."""

_COUNT_SQL = """
SELECT
  COALESCE(SUM(CASE WHEN r.link_state IS NULL OR r.link_state = 'unresolved'
               THEN 1 ELSE 0 END), 0),
  COALESCE(SUM(CASE WHEN r.link_state IN ('unconfirmed', 'ambiguous') THEN 1 ELSE 0 END), 0),
  COALESCE(SUM(CASE WHEN r.attachment_path_sha256 IS NOT NULL
               AND r.attachment_content_sha256 IS NULL THEN 1 ELSE 0 END), 0),
  COALESCE(SUM(CASE WHEN i.format = 'pdfs' AND r.link_state = 'resolved'
               AND r.attachment_content_sha256 IS NOT NULL
               AND (r.decision IS NULL OR r.decision != 'confirm')
               AND NOT EXISTS (SELECT 1 FROM import_attachments a
                               WHERE a.import_id = r.import_id AND a.ordinal = r.ordinal)
               THEN 1 ELSE 0 END), 0)
FROM import_records r JOIN imports i ON i.import_id = r.import_id
WHERE r.import_id = :i AND r.outcome != 'malformed'
"""


def _import_counts(project: Project, import_id: str, *, development_only: bool) -> dict[str, int]:
    """The four count findings of one import; `development_only` leaves the held-out part out
    (the agent view, decision 43)."""
    sql = _COUNT_SQL + (" AND r.part != 'held-out'" if development_only else "")
    with project.index.connect() as conn:
        row = conn.execute(text(sql), {"i": import_id}).one()
    return dict(zip(_IMPORT_COUNTS, (int(n) for n in row), strict=True))


def _imports(project: Project) -> list[_Hit]:
    """Findings of the imported libraries: records left unresolved, unconfirmed or without their
    file, PDF identities nobody checked, a corpus import the protocol does not declare (a
    promotion gap) and a pre-search import whose split was declined."""
    protocol = current_protocol(project)
    hits: list[_Hit] = []
    for listing in list_imports(project):
        row = listing.row
        counts = _import_counts(project, row.import_id, development_only=False)
        for code, phrase in _IMPORT_COUNTS.items():
            if counts[code]:
                hits.append(_Hit(code, (row.import_id,), f"{counts[code]} {phrase}"))
        if row.role.value == "corpus" and (
            protocol is None or library_source_gaps(protocol.spec, row.collection, row.format)
        ):
            hits.append(
                _Hit(
                    "import-undeclared",
                    (row.import_id,),
                    "a corpus import without a library_sources entry in the protocol",
                )
            )
        if row.split_mode == "declined":
            hits.append(
                _Hit(
                    "import-coverage-optimistic",
                    (row.import_id,),
                    "the split of a pre-search import was declined; its coverage is optimistic",
                )
            )
    return hits


def _development_only(project: Project, report: CheckReport) -> CheckReport:
    """`report` with each import count finding recounted over the development part, and dropped
    when that count is zero: the held-out part's counts stay out of the agent view."""
    findings: list[Finding] = []
    for finding in report.findings:
        if finding.code not in _IMPORT_COUNTS:
            findings.append(finding)
            continue
        count = _import_counts(project, finding.refs[0], development_only=True)[finding.code]
        if count:
            message = f"{count} {_IMPORT_COUNTS[finding.code]}"
            findings.append(finding.model_copy(update={"message": message}))
    return report.model_copy(update={"findings": findings})

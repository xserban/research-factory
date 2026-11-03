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
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from factory.events.reader import read_all
from factory.index.chase import admitted_works
from factory.model.base import StrictModel
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolStatus
from factory.model.seed import SEED_ID_RE
from factory.model.work import ProvenanceMethod
from factory.services.agreement import Outcome, agreement_summary, final_outcomes, single_pass_works
from factory.services.audit import audit_outstanding, audit_report
from factory.services.calibration import calibration_status
from factory.services.chase import chase_rounds
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.methods import MethodsReport, methods_report
from factory.services.prisma import search_report
from factory.services.protocol import current_protocol
from factory.services.seeds import SeedRole, _rigor_mode, seed_check
from factory.services.trace import dangling_refs

Severity = Literal["error", "warning"]

LEVELS: dict[str, tuple[Severity | None, Severity | None, Severity | None]] = {
    # code: (exploratory, pilot, systematic); None means no finding in that mode.
    "broken-link": ("error", "error", "error"),
    "missing-provenance": ("error", "error", "error"),
    "shortfall-unexplained": ("error", "error", "error"),
    "seed-missing": ("warning", "error", "error"),
    "seed-admission-pending": ("warning", "warning", "error"),
    "protocol-not-ready": (None, "error", "error"),
    "press-missing": (None, "error", "error"),
    "screening-pending": ("warning", "warning", "warning"),
    "single-pass": (None, "warning", "error"),
    "calibration-missing": (None, "error", "error"),
    "kappa-below-floor": ("warning", "warning", "warning"),
    "audit-missing": (None, "warning", "error"),
    "audit-error-high": (None, "warning", "error"),
    "chase-missing": (None, "warning", "error"),
    "profile-checklist": ("warning", "warning", "warning"),
    "merge-verdict-conflict": ("warning", "warning", "warning"),
}

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


_HELD_OUT_POSSIBLE = "held-out-possible"
_SEED_PHRASES = {
    "seed-missing": "positive seed(s) missing",
    "seed-admission-pending": "positive seed(s) explained, admission pending",
}


_RATE_CODES = {
    "audit-error-high": "the audit's false-exclusion rate is above the declared ceiling "
    "(figures withheld from the agent view)",
}
"""Findings whose message carries a label-derived rate or threshold, and the message an agent
reads instead (decision 37.14). The finding itself, its code and severity are unchanged."""


def agent_view(report: CheckReport) -> CheckReport:
    """The report as an agent may read it: seed findings by role and count only (R-20), and no
    label-derived rate.

    A seed finding becomes one finding per code, severity and role, with no refs, so a held-out
    seed is never named. A positive still `unsplit` may become held-out, so it is counted as
    `held-out-possible` and never as development. Any other ref that is a seed id is dropped.
    """
    counts: dict[tuple[str, Severity, str], int] = {}
    others: list[Finding] = []
    order: list[tuple[str, Severity, str] | int] = []
    for finding in report.findings:
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
    return report.model_copy(update={"findings": findings})


@dataclass(frozen=True)
class _Hit:
    """One condition found by a rule, before its severity is read for a mode."""

    code: str
    refs: tuple[str, ...]
    message: str
    role: str | None = None
    severity: Severity | None = None


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
    """Every condition in the project, in rule order. Computed once per check."""
    project.index.sync()
    outcomes = final_outcomes(project)
    hits: list[_Hit] = []
    hits += _broken_links(project)
    hits += _missing_provenance(project)
    hits += _shortfalls(project)
    hits += _seeds(project)
    hits += _protocol_gates(project)
    hits += _screening(project, outcomes)
    hits += _calibration_and_agreement(project)
    hits += _audit(project)
    hits += _chase(project, outcomes)
    hits += _checklist(project)
    hits += _merge_conflicts(project, outcomes)
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
        if check.status == "missing":
            missing.setdefault(key, []).append(check.seed_id)
        elif (
            check.status == "explained"
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
    no agreed outcome.
    """
    if not any(outcome is Outcome.INCLUDED for outcome in outcomes.values()):
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

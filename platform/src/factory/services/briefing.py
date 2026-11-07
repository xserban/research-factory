"""The project briefing: a reading path for a person joining mid-way (slice 7b, plan V-C).

Declares: `build_briefing`, `briefing_agent_view`, `agent_pack`, `serve_pack`, `VIEW_VERSION`,
`BRIEFING_MAX_CHARS`. A builder over the projection; it writes nothing except `briefing.served`,
through `serve_pack`.

Invariants:
- Every section is computed from events through the service that owns it (R-05): question,
  protocol reads, the gate services, `prisma_flow`, `search_horizon`, confirmed ideas and the
  lineage `path`, the visible groups of the coverage view, `check`, `human_queue`, released drafts.
- No library read and no document text: titles and bibliographic metadata only. Idea names and
  amendment reasons are what a person recorded, not text of a document.
- `as_of` is the last event other than `briefing.served`, so recording a pack does not change the
  position the next build says it describes (ruling 4's idempotence). The researcher's briefing
  does read servings, through `briefing-stale`; the pack does not (below).
- Scale. Spec ruling 26 names views, outlines and exports, not briefings, but its aim is kept
  where it can be: `methods_report` and `evidence_report` are not called, and evidence groups
  keep summaries only. A build is not one fold: `check`, `human_queue` and the gates each read
  the extraction state, which is shared within a build (`_load` is memoised for a whole scope),
  while the final rows are settled again by each caller. `prisma_flow` and `check` read every work:
  they are the only definitions of sections 4 and 7, and a second computation would break R-05.
  So a build costs at least what `check` costs, and a repeat call that records nothing pays it
  again (decision rows 92 and 110).
- The researcher's output stays complete; the agent form is `briefing_agent_view`.
- A fresh project gives every section. The question, protocol, reading path, evidence and drafts
  sections say why they are empty in a notice, and the corpus horizon has one; gates and pending
  decisions are simply empty, and `check` findings are what they are.

Invariants of the agent form (plan rulings 2 and 3; spec ruling 24):
- Each source is read in its agent variant: `agent_check` and `sentence_status(agent=True)`. The
  pack takes no figure from `methods_report` or `evidence_report`, so `agent_methods` and
  `agent_evidence` have nothing to remove from it: what those filters guard (rates, kappa, recall,
  ceilings) sits only in `GateBrief.figures`, which the agent form empties. The researcher's
  `passed` of an audit reads the enforced ceiling, so an extraction, contribution or gate audit
  shows an agent only the rate-blind `labelled_complete` (decision 52). A screening audit keeps
  `passed`: `agent_check` already gives an agent that flag as `audit-error-high`.
- Section 8 is counts only. An audit kind counts audits, not items: the size of a sample and the
  labels on it are withheld from agents (decision 37 item 14, `GateStatusRow.agent_view`).
- Before a screening pass has opened the sections that name works or read like the views (5, 6 and
  9) are empty, with one neutral notice for every project: the same role-blind rule as the view
  and draft tools, which refuse then (decision 43). Nothing is marked and no work is masked.
- Held-out seed ids and stated identifiers are scrubbed from every string before the pack is
  stored, since free text (a goal, an amendment reason) may name one; work ids stay.
- A pack is a function of the log: built at the log position `as_of` with the clock read as that
  event's time, so `check`'s date-dependent findings do not vary with the day it is run.
- No part of the pack reads a serving: `as_of` skips them and `issues` leaves out `briefing-stale`,
  the one finding that does, or a serving could change the next pack at the same `as_of`. The
  `check` tool keeps the finding.
- `serve_pack` is refused to a session that joined a pass, and records nothing new when the session
  already holds that very pack: the blob is the identity, and the second call builds the same
  bytes.
- The JSON is at most `BRIEFING_MAX_CHARS`: cuts run from the end of sections 5 and 8 (members,
  paths, entries), then 6, 9 and 7; sections 1 to 4 are cut only when they alone exceed the bound
  (oldest deviations, then oldest amendments). `truncated` states each cut; a pack that still
  does not fit is refused.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import bindparam, text

from factory.clock import FixedClock, parse_ts
from factory.errors import FactoryValidationError, ValidationIssue
from factory.exports.keys import assign_keys
from factory.lineage.graph import Direction, GraphEdge, Neighbours
from factory.lineage.paths import path
from factory.model.lineage import EdgeStatus, EdgeType
from factory.model.protocol import ScreeningStage
from factory.model.views import (
    AmendmentBrief,
    Briefing,
    BriefingServed,
    CorpusBrief,
    DeviationBrief,
    DraftBrief,
    ElementBrief,
    GateBrief,
    GroupSummary,
    NonGoalBrief,
    PathEntry,
    PendingBrief,
    ProtocolBrief,
    QuestionBrief,
    SubQuestionBrief,
    ViewNotice,
    WorkBrief,
)
from factory.model.work import Work
from factory.services.agreement import agreement_summary, screen_agreement
from factory.services.audit import audit_report
from factory.services.briefing_served import served_for
from factory.services.calibration import calibration_status
from factory.services.call_memo import entering
from factory.services.check import CheckReport, agent_check, check
from factory.services.context import Project
from factory.services.contributions import contribution_audit_report
from factory.services.coverage import held_out_visible
from factory.services.draft_audit import audit_sheet
from factory.services.draft_release import released_drafts
from factory.services.drafts import get_draft, list_drafts, sentence_status, status_counts
from factory.services.evidence_groups import summarise
from factory.services.extraction_agreement import agreement_overall
from factory.services.extraction_audit import ExtractionAuditReport, extraction_audit_report
from factory.services.gate_status import gates_status
from factory.services.gates import rigor_mode
from factory.services.human_queue import Gate, human_queue
from factory.services.ideas import IdeaView, confirmed_ideas, list_ideas
from factory.services.layer_check import unreviewed_interpretations
from factory.services.lineage import index_neighbours
from factory.services.outline import lineage_order
from factory.services.passes import is_pass_session
from factory.services.prisma import has_full_text_plan, prisma_flow
from factory.services.protocol import ProtocolVersion, amendments_with_events, current_protocol
from factory.services.question import current_question, goals
from factory.services.relations import list_relations
from factory.services.search import get_work
from factory.services.view_corpus import horizon_notice, search_horizon
from factory.services.view_coverage import coverage_groups
from factory.services.view_rows import merge_notice
from factory.services.views import to_json, view_meta
from factory.services.withholding import held_out_tokens, withhold

VIEW_VERSION = 1
BRIEFING_MAX_CHARS = 40000
MAX_MEMBERS = 5
"""Members of an idea a reading-path entry lists (plan ruling 1)."""
_PAGE = 500
_SERVED = "briefing.served"
_READS_SERVINGS = "briefing-stale"
AUDIT_KINDS = frozenset(
    {
        Gate.SCREENING_AUDIT.value,
        Gate.EXTRACTION_AUDIT.value,
        "contribution-audit",
        "gate-audit",
        "draft-audit",
    }
)
"""Pending kinds whose `ids` name audits and whose `count` is a count of unlabelled items."""


def build_briefing(project: Project) -> Briefing:
    """The complete briefing, as the researcher reads it."""
    with entering():
        return compose(project, check(project), draft_counts(project, agent=False))


def briefing_agent_view(project: Project, *, session: str | None = None) -> Briefing:
    """The briefing as an agent outside the passes may read it (see the module docstring). It
    builds from the project, not from a `Briefing`: section 7 must come from `agent_check`.
    `session`, the reader, is refused when it is verifying a released draft."""
    with entering():
        at_position = _at_log_position(project)
        built = compose(
            at_position,
            agent_check(at_position),
            draft_counts(at_position, agent=True, session=session),
        )
        reduced = _reduced(built, opened=held_out_visible(project))
        reduced = _without_hidden_gate_audit(reduced, at_position)
        scrubbed = withhold(
            reduced.model_dump(mode="json"), held_out_tokens(project, include_work_ids=False)
        )
        return Briefing.model_validate_json(json.dumps(scrubbed))


def agent_pack(project: Project) -> str:
    """The agent context pack: canonical JSON of the agent view, within `BRIEFING_MAX_CHARS`.
    Refused (field `briefing`) when sections 1 to 4 alone do not fit; nothing is written."""
    return to_json(_bounded(briefing_agent_view(project)))


def serve_pack(project: Project, *, session: str) -> tuple[str, str]:
    """Store the agent pack as a blob and record that `session` received it; returns the blob ref
    and the pack. Refused (field `session`), with nothing written, to a session that has joined a
    pass (decisions 43, 48)."""
    if is_pass_session(project, session):
        raise FactoryValidationError(
            [ValidationIssue("session", "this session has joined a pass and cannot use this tool")]
        )
    built = _bounded(briefing_agent_view(project, session=session))
    pack = to_json(built)
    blob = project.blobs.put(pack.encode())
    position = built.meta.as_of
    with project.writing():  # the build above is a long read: outside the write lock
        if position is None or any(row.blob == blob for row in served_for(project, session)):
            return blob, pack
        payload = BriefingServed(session=session, audience="agent", blob=blob, as_of=position)
        actor = project.system_actor().model_copy(update={"session": session})
        project.record([project.events.make("briefing.served", payload, actor)])
    return blob, pack


def as_of(project: Project) -> str | None:
    """The last event of the log other than `briefing.served` (see the module docstring)."""
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM events WHERE type != :t ORDER BY id DESC LIMIT 1"), {"t": _SERVED}
        ).first()
    return None if row is None else str(row[0])


def compose(project: Project, report: CheckReport, counts: dict[str, dict[str, int]]) -> Briefing:
    """The briefing from the two sources whose reading differs by audience: `report` is the
    `check` result, `counts` the status counts of each released draft."""
    position = as_of(project)  # once, before any read: the briefing describes this position
    notices: list[ViewNotice] = []
    question = _question(project, notices)
    protocol = current_protocol(project)
    brief = _protocol(project, protocol, notices)
    horizon = search_horizon(project)
    notices.append(horizon_notice(horizon))
    reading_path = _reading_path(project, notices)
    evidence = _evidence(project, notices)
    drafts = _drafts(project, counts, notices)
    return Briefing(
        meta=view_meta(
            project,
            "briefing",
            VIEW_VERSION,
            {
                "reading_path": "confirmed ideas in lineage order, default graph filter",
                "evidence": "final evidence rows of corpus works, without notice-excluded works",
            },
            notices=notices,
            as_of=position,
        ),
        question=question,
        protocol=brief,
        gates=_gates(project, protocol),
        corpus=CorpusBrief(
            prisma=prisma_flow(project).model_dump(mode="json"), last_search=horizon
        ),
        reading_path=reading_path,
        evidence=evidence,
        issues=issue_counts(report),
        pending=_pending(project),
        drafts=drafts,
    )


def issue_counts(report: CheckReport) -> dict[str, int]:
    """The findings of `report` by code."""
    counts: dict[str, int] = {}
    for finding in report.findings:
        counts[finding.code] = counts.get(finding.code, 0) + 1
    return dict(sorted(counts.items()))


def draft_counts(
    project: Project, *, agent: bool, session: str | None = None
) -> dict[str, dict[str, int]]:
    """The count of each sentence status of every released draft; `agent` is the variant of
    `sentence_status` that reads no audit label. `session` is the agent reader, refused when it
    is verifying a draft."""
    return {
        draft_id: status_counts(sentence_status(project, draft_id, agent=agent, session=session))
        for draft_id in sorted(released_drafts(project))
    }


# --- The agent form ---


def _at_log_position(project: Project) -> Project:
    """`project` with the clock read as the time of the event `as_of` names."""
    position = as_of(project)
    with project.index.connect() as conn:
        ts = conn.execute(text("SELECT ts FROM events WHERE id = :i"), {"i": position}).scalar()
    if ts is None:
        return project
    return dataclasses.replace(project, clock=FixedClock(parse_ts(str(ts))))


_CEILING_WITHHELD = frozenset({"extraction-audit", "gate-audit"})
_WORK_SECTION_NOTICES = frozenset(
    {"reading-path-empty", "evidence-empty", "merge-read", "drafts-none"}
)
_NOT_YET = ViewNotice(
    code="sections-not-available-yet",
    text="The reading path, evidence groups and released drafts are not available yet.",
)


def _reduced(b: Briefing, *, opened: bool) -> Briefing:
    """`b` without figures and identifiers (ruling 2), and before a pass without the sections that
    name works."""
    update: dict[str, object] = {
        "gates": [_rate_blind(g) for g in b.gates],
        "issues": {code: n for code, n in b.issues.items() if code != _READS_SERVINGS},
        "pending": [_counts_only(p) for p in b.pending],
    }
    notices = b.meta.notices
    if not opened:
        update |= {"reading_path": [], "evidence": [], "drafts": []}
        notices = [n for n in notices if n.code not in _WORK_SECTION_NOTICES] + [_NOT_YET]
    meta = b.meta.model_copy(
        update={"notices": notices, "filter": {**b.meta.filter, "audience": "agent"}}
    )
    return b.model_copy(update={**update, "meta": meta})


def _without_hidden_gate_audit(b: Briefing, project: Project) -> Briefing:
    """`b` without the gate-audit row of `experiments.accept_baseline` when every act at that gate
    is an acceptance whose verdict the agent may not read (`hidden_acceptances`): the audit is then
    drawn over hidden acts alone, and its row, `labelled_complete` or date would show that one was
    accepted. The row stays whole when a visible act remains, as `gate_status` leaves its audit."""
    from factory.services.xrun_accounting import hidden_acceptances  # xrun imports services

    gate_id = "experiments.accept_baseline"
    hidden = hidden_acceptances(project)
    if not hidden:
        return b
    visible = next(
        (sum(r.counts.values()) - hidden for r in gates_status(project) if r.gate_id == gate_id), 0
    )
    if visible > 0:
        return b
    kept = [g for g in b.gates if not (g.gate == "gate-audit" and g.scope == gate_id)]
    return b.model_copy(update={"gates": kept})


def _rate_blind(gate: GateBrief) -> GateBrief:
    """`gate` as an agent reads it: no figures, and no `passed` where it holds a withheld flag."""
    hidden = gate.gate in _CEILING_WITHHELD
    return gate.model_copy(update={"figures": {}, "passed": None if hidden else gate.passed})


def _counts_only(item: PendingBrief) -> PendingBrief:
    count = len(item.ids) if item.kind in AUDIT_KINDS else item.count
    return item.model_copy(update={"count": count, "ids": []})


@dataclass(frozen=True)
class _Cut:
    """One step of the bound: `label` names it in `truncated`, `size` counts the units of `b` it
    can cut, `keep` gives `b` with only the first `n` units left whole."""

    label: str
    size: Callable[[Briefing], int]
    keep: Callable[[Briefing, int], Briefing]


def _list_cut(name: str) -> _Cut:
    """A step that drops the tail of the top-level list `name`."""

    def size(b: Briefing) -> int:
        return len(getattr(b, name))

    def keep(b: Briefing, n: int) -> Briefing:
        return b.model_copy(update={name: getattr(b, name)[:n]})

    return _Cut(name, size, keep)


def _entry_cut(name: str) -> _Cut:
    """A step that empties `name` of the reading-path entries after the first `n`."""

    def size(b: Briefing) -> int:
        return len(b.reading_path) if any(getattr(e, name) for e in b.reading_path) else 0

    def keep(b: Briefing, n: int) -> Briefing:
        entries = [
            e if i < n else e.model_copy(update={name: []}) for i, e in enumerate(b.reading_path)
        ]
        return b.model_copy(update={"reading_path": entries})

    return _Cut(f"reading_path.{name}", size, keep)


def _issues_cut() -> _Cut:
    def keep(b: Briefing, n: int) -> Briefing:
        return b.model_copy(update={"issues": dict(list(b.issues.items())[:n])})

    return _Cut("issues", lambda b: len(b.issues), keep)


def _protocol_cut(name: str) -> _Cut:
    """A step that drops the oldest entries (the tail) of a list of section 2."""

    def keep(b: Briefing, n: int) -> Briefing:
        cut = b.protocol.model_copy(update={name: getattr(b.protocol, name)[:n]})
        return b.model_copy(update={"protocol": cut})

    return _Cut(f"protocol.{name}", lambda b: len(getattr(b.protocol, name)), keep)


_CUTS: tuple[_Cut, ...] = (
    _entry_cut("members"),
    _entry_cut("paths"),
    _list_cut("reading_path"),
    _list_cut("pending"),
    _list_cut("evidence"),
    _list_cut("drafts"),
    _issues_cut(),
    _protocol_cut("deviations"),
    _protocol_cut("amendments"),
)


def _fits(b: Briefing) -> bool:
    return len(to_json(b)) <= BRIEFING_MAX_CHARS


def _noted(b: Briefing, cut: _Cut, kept: int) -> Briefing:
    """`b` with the first `kept` units of `cut` left, and the cut stated."""
    total = cut.size(b)
    trimmed = cut.keep(b, kept)
    return trimmed.model_copy(
        update={
            "meta": trimmed.meta.model_copy(update={"truncated": True}),
            "truncated": [*b.truncated, f"{cut.label}: {total - kept} of {total} cut"],
        }
    )


def _bounded(b: Briefing) -> Briefing:
    """`b` within the bound: each step whole until one can stop part way, then the most of that
    step that fits."""
    if _fits(b):
        return b
    for cut in _CUTS:
        total = cut.size(b)
        if total == 0:
            continue
        if not _fits(_noted(b, cut, 0)):
            b = _noted(b, cut, 0)
            continue
        low, high = 0, total - 1  # `low` units fit; find the largest that does
        while low < high:
            middle = (low + high + 1) // 2
            if _fits(_noted(b, cut, middle)):
                low = middle
            else:
                high = middle - 1
        return _noted(b, cut, low)
    raise FactoryValidationError(
        [ValidationIssue("briefing", f"sections 1 to 4 exceed {BRIEFING_MAX_CHARS} characters")]
    )


# --- Sections 1 and 2 ---


def _question(project: Project, notices: list[ViewNotice]) -> QuestionBrief:
    stated = goals(project)
    raw_goal = stated[-1].text if stated else None
    version = current_question(project)
    if version is None:
        notices.append(ViewNotice(code="question-none", text="No question is recorded yet."))
        return QuestionBrief(raw_goal=raw_goal)
    spec = version.spec
    return QuestionBrief(
        question_id=version.question_id,
        raw_goal=raw_goal,
        primary_question=spec.primary_question,
        elements=[
            ElementBrief(name=s.name, value=s.value, open=s.open, resolve_in=s.resolve_in)
            for s in spec.slots
        ],
        non_goals=[NonGoalBrief(id=g.id, text=g.text) for g in spec.non_goals],
        sub_questions=[
            SubQuestionBrief(id=s.id, text=s.text, serves=s.serves) for s in spec.sub_questions
        ],
    )


def _protocol(
    project: Project, protocol: ProtocolVersion | None, notices: list[ViewNotice]
) -> ProtocolBrief:
    mode = rigor_mode(project).value
    if protocol is None:
        notices.append(ViewNotice(code="protocol-none", text="No protocol is recorded yet."))
        return ProtocolBrief(rigor_mode=mode)
    amended = amendments_with_events(project)
    days = _event_days(project, [event for event, _ in amended])
    with project.index.connect() as conn:
        deviations = conn.execute(
            text(
                "SELECT d.deviation_id, substr(e.ts, 1, 10), d.description, d.reason "
                "FROM deviations d JOIN events e ON e.id = d.event_id ORDER BY d.event_id DESC"
            )
        ).all()
    return ProtocolBrief(
        protocol_id=protocol.protocol_id,
        rigor_mode=mode,
        method_profile=protocol.spec.method_profile.value,
        amendments=[
            AmendmentBrief(
                amendment_id=a.amendment_id,
                date=days.get(event, ""),
                reason=a.reason,
                semantic=a.semantic,
            )
            for event, a in reversed(amended)
        ],
        deviations=[
            DeviationBrief(deviation_id=str(i), date=str(d), description=str(t), reason=str(r))
            for i, d, t, r in deviations
        ],
    )


def _event_days(project: Project, events: Sequence[str]) -> dict[str, str]:
    if not events:
        return {}
    statement = text("SELECT id, substr(ts, 1, 10) FROM events WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    with project.index.connect() as conn:
        return {str(i): str(d) for i, d in conn.execute(statement, {"ids": list(events)})}


# --- Section 3 ---


def _last_day(project: Project, *types: str) -> str | None:
    """The day of the latest event of `types`, or None."""
    statement = text(
        "SELECT substr(ts, 1, 10) FROM events WHERE type IN :t ORDER BY id DESC LIMIT 1"
    ).bindparams(bindparam("t", expanding=True))
    with project.index.connect() as conn:
        row = conn.execute(statement, {"t": list(types)}).first()
    return None if row is None else str(row[0])


def _stages(project: Project) -> list[ScreeningStage]:
    stages = [ScreeningStage.TITLE_ABSTRACT]
    if has_full_text_plan(project):
        stages.append(ScreeningStage.FULL_TEXT)
    return stages


def _gates(project: Project, protocol: ProtocolVersion | None) -> list[GateBrief]:
    """Every gate the protocol brings into force, in the order of the review. Nothing is computed
    here but `passed`: the figures are the owning services'."""
    if protocol is None:
        return []
    rows = [
        GateBrief(
            gate="press",
            scope=None,
            passed=protocol.press == "confirmed",
            date=_last_day(project, "protocol.press_confirmed"),
        )
    ]
    stages = _stages(project)
    for stage in stages:
        rows += _calibration(project, protocol, stage)
    if protocol.spec.screening.passes == 2:
        rows += [_agreement(project, stage) for stage in stages]
    for stage in stages:
        rows += _screening_audit(project, stage)
    if protocol.spec.extraction_schema is not None:
        rows.append(_extraction_agreement(project))
    for scope, report in (
        ("evidence", extraction_audit_report(project)),
        ("contribution", contribution_audit_report(project)),
    ):
        if report is not None:
            rows.append(_extraction_audit(project, scope, report))
    rows += _gate_audits(project)
    return rows


def _calibration(
    project: Project, protocol: ProtocolVersion, stage: ScreeningStage
) -> list[GateBrief]:
    """One row per pass. Without a threshold no calibration is required: an undrawn one has no
    row, and a drawn one shows its figures with `passed` None, neither passed nor failed."""
    status = calibration_status(project, stage=stage)
    if not status.required and status.drawn == 0:
        return []
    labels = ["A", "B"] if protocol.spec.screening.passes == 2 else ["A"]
    day = _last_day(project, "calibration.labelled")
    return [
        GateBrief(
            gate="calibration",
            scope=f"{stage.value}/{label}",
            passed=status.passed.get(label, False) if status.required else None,
            date=day if status.required and status.passed.get(label, False) else None,
            figures=(
                status.per_pass[label].model_dump(mode="json") if label in status.per_pass else {}
            ),
        )
        for label in labels
    ]


def _agreement(project: Project, stage: ScreeningStage) -> GateBrief:
    summary = agreement_summary(project, stage=stage)
    if summary is None:
        return GateBrief(gate="agreement", scope=stage.value, passed=False, date=None)
    return GateBrief(
        gate="agreement",
        scope=stage.value,
        passed=not summary.below_floor,
        date=_last_day(project, "screening.decision_recorded"),
        figures={
            "kappa": summary.kappa,
            "kappa_floor": summary.kappa_floor,
            "n_dual": summary.n_dual,
        },
    )


def _audit_passed(complete: bool, above_ceiling: bool | None, enforced: bool | None) -> bool:
    """An audit is passed when fully labelled and not above a ceiling enforced in this mode."""
    return complete and not (above_ceiling and enforced)


def _screening_audit(project: Project, stage: ScreeningStage) -> list[GateBrief]:
    report = audit_report(project, stage=stage)
    if report is None:
        return []
    complete = report.labelled >= report.sample_size
    return [
        GateBrief(
            gate="audit",
            scope=stage.value,
            passed=_audit_passed(complete, report.above_ceiling, report.enforced),
            labelled_complete=complete,
            date=_last_day(project, "audit.labelled"),
            figures={
                "audit_id": report.audit_id,
                "sample_size": report.sample_size,
                "labelled": report.labelled,
                "false_exclusion": report.rates.false_exclusion,
                "ceiling": report.ceiling,
                "above_ceiling": report.above_ceiling,
                "enforced": report.enforced,
            },
        )
    ]


def _extraction_agreement(project: Project) -> GateBrief:
    overall = agreement_overall(project).overall
    return GateBrief(
        gate="extraction-agreement",
        scope=None,
        passed=overall is not None,
        date=None if overall is None else _last_day(project, "extraction.recorded"),
        figures={"overall": overall},
    )


def _extraction_audit(project: Project, scope: str, report: ExtractionAuditReport) -> GateBrief:
    complete = report.labelled >= report.sample_size
    return GateBrief(
        gate="extraction-audit",
        scope=scope,
        passed=_audit_passed(complete, report.above_ceiling, report.enforced),
        labelled_complete=complete,
        date=_last_day(project, "extraction.audit_labelled"),
        figures={
            "audit_id": report.audit_id,
            "sample_size": report.sample_size,
            "labelled": report.labelled,
            "error_rate": report.error_rate,
            "ceiling": report.ceiling,
            "above_ceiling": report.above_ceiling,
            "enforced": report.enforced,
        },
    )


def _gate_audits(project: Project) -> list[GateBrief]:
    day = _last_day(project, "gate.audit_labelled")
    return [
        GateBrief(
            gate="gate-audit",
            scope=row.gate_id,
            passed=_audit_passed(
                (row.audit.labelled or 0) >= (row.audit.sample_size or 0),
                row.audit.above_ceiling,
                row.audit.enforced,
            ),
            labelled_complete=(row.audit.labelled or 0) >= (row.audit.sample_size or 0),
            date=day,
            figures={
                "audit_id": row.audit.audit_id,
                "sample_size": row.audit.sample_size,
                "labelled": row.audit.labelled,
                "error_rate": row.audit.error_rate,
                "above_ceiling": row.audit.above_ceiling,
                "enforced": row.audit.enforced,
            },
        )
        for row in gates_status(project)
        if row.audit is not None
    ]


# --- Section 5 ---


def _memoised(lookup: Neighbours) -> Neighbours:
    """`lookup` with each answer kept for this build: the paths of the entries share their walk."""
    seen: dict[tuple[str, Direction, frozenset[EdgeType]], Sequence[GraphEdge]] = {}

    def neighbours(
        node: str, direction: Direction, types: frozenset[EdgeType]
    ) -> Sequence[GraphEdge]:
        key = (node, direction, types)
        if key not in seen:
            seen[key] = lookup(node, direction, types)
        return seen[key]

    return neighbours


def _work_reader(project: Project) -> Callable[[str], Work | None]:
    seen: dict[str, Work | None] = {}

    def read(work_id: str) -> Work | None:
        if work_id not in seen:
            seen[work_id] = get_work(project, work_id)
        return seen[work_id]

    return read


def _year(work: Work | None) -> int | None:
    published = None if work is None else work.dates.published
    return published.year if isinstance(published, date) else None


def _reading_path(project: Project, notices: list[ViewNotice]) -> list[PathEntry]:
    """Confirmed ideas in lineage order, each with its origin, its most recent members and the
    shortest lineage path to each of them. A path starts at the earliest origin of the reading
    path when one exists, else at the idea's own origin (origin first: `path` runs from the later
    work to the earlier, so the result is reversed)."""
    ordered = lineage_order(project, confirmed_ideas(project))
    if not ordered:
        notices.append(
            ViewNotice(code="reading-path-empty", text="No idea is confirmed yet; no reading path.")
        )
        return []
    read = _work_reader(project)
    neighbours = _memoised(index_neighbours(project))

    def earliness(work_id: str) -> tuple[int, str]:
        year = _year(read(work_id))
        return (date.max.year if year is None else year, work_id)

    earliest = min((i.origin for i in ordered), key=earliness)
    chosen = {i.idea_id: _members(i, read) for i in ordered}
    keys = assign_keys({w for i in ordered for w in (i.origin, *chosen[i.idea_id])})

    def brief(work_id: str) -> WorkBrief:
        work = read(work_id)
        return WorkBrief(
            work_id=work_id,
            title="" if work is None else work.title,
            year=_year(work),
            key=keys[work_id],
        )

    return [
        PathEntry(
            idea_id=idea.idea_id,
            name=idea.name,
            origin=brief(idea.origin),
            members=[brief(w) for w in chosen[idea.idea_id]],
            members_total=len(set(idea.effective_members) - {idea.origin}),
            paths=_paths(neighbours, (earliest, idea.origin), chosen[idea.idea_id]),
        )
        for idea in ordered
    ]


def _members(idea: IdeaView, read: Callable[[str], Work | None]) -> list[str]:
    """The idea's works other than its origin, most recent first; undated works come last."""

    def recency(work_id: str) -> tuple[int, str]:
        year = _year(read(work_id))
        return (1 if year is None else -year, work_id)

    others = set(idea.effective_members) - {idea.origin}
    return sorted(others, key=recency)[:MAX_MEMBERS]


def _paths(
    neighbours: Neighbours, starts: tuple[str, str], members: Sequence[str]
) -> list[list[str]]:
    found: list[list[str]] = []
    for member in members:
        for start in dict.fromkeys(starts):
            nodes = path(neighbours, member, start).nodes
            if nodes:
                found.append(list(reversed(nodes)))
                break
    return found


# --- Sections 6 and 9 ---


def _evidence(project: Project, notices: list[ViewNotice]) -> list[GroupSummary]:
    groups, merged = coverage_groups(project)
    summaries = [summarise(key, rows) for key, rows in groups]
    if (note := merge_notice(merged)) is not None:
        notices.append(note)
    if not summaries:
        notices.append(
            ViewNotice(code="evidence-empty", text="No final evidence row of a corpus work yet.")
        )
    return sorted(summaries, key=lambda s: (-s.works, s.group_id))


def _drafts(
    project: Project, counts: dict[str, dict[str, int]], notices: list[ViewNotice]
) -> list[DraftBrief]:
    with project.index.connect() as conn:
        days = {
            str(d): str(day)
            for d, day in conn.execute(
                text(
                    "SELECT r.draft_id, MAX(substr(e.ts, 1, 10)) FROM draft_releases r "
                    "JOIN events e ON e.id = r.event_id GROUP BY r.draft_id"
                )
            )
        }
    out: list[DraftBrief] = []
    for draft_id, by_status in counts.items():
        found = get_draft(project, draft_id)
        if found is not None:
            out.append(
                DraftBrief(
                    draft_id=draft_id,
                    title=found.title,
                    released=days.get(draft_id, ""),
                    counts=by_status,
                )
            )
    if not out:
        notices.append(ViewNotice(code="drafts-none", text="No draft has been released yet."))
    return out


# --- Section 8 ---


def _pending(project: Project) -> list[PendingBrief]:
    """Every kind with something waiting, in the order of the human queue, then the kinds it does
    not cover. Manuscript citations have no source until plan W-C builds them."""
    base = f"factory --project {project.paths.slug}"
    out: list[PendingBrief] = []
    for item in human_queue(project).items:
        stage = None if item.stage is None else ScreeningStage(item.stage)
        if item.gate is Gate.SCREENING_DISAGREEMENTS and stage is not None:
            out += _disagreements(project, stage, item.command)
            continue
        out.append(
            PendingBrief(
                kind=item.gate.value,
                stage=item.stage,
                count=item.count,
                ids=_audit_ids(project, item.gate, stage),
                command=item.command,
            )
        )
    return out + _other_audits(project, base) + _lineage_pending(project, base)


def _disagreements(project: Project, stage: ScreeningStage, command: str) -> list[PendingBrief]:
    """Outcome disagreements and `unsure` decisions, apart. The human queue found them, so the
    agreement is not refused."""
    found = screen_agreement(project, project.human_actor(), stage=stage).disagreements
    return [
        PendingBrief(kind=kind, stage=stage.value, count=len(ids), ids=ids, command=command)
        for kind, ids in (
            (
                Gate.SCREENING_DISAGREEMENTS.value,
                sorted(d.work_id for d in found if d.reason == "outcome"),
            ),
            ("screening-unsure", sorted(d.work_id for d in found if d.reason == "unsure")),
        )
        if ids
    ]


def _audit_ids(project: Project, gate: Gate, stage: ScreeningStage | None) -> list[str]:
    if gate is Gate.SCREENING_AUDIT and stage is not None:
        report = audit_report(project, stage=stage)
        return [] if report is None else [report.audit_id]
    if gate is Gate.EXTRACTION_AUDIT:
        extraction = extraction_audit_report(project)
        return [] if extraction is None else [extraction.audit_id]
    return []


def _other_audits(project: Project, base: str) -> list[PendingBrief]:
    out: list[PendingBrief] = []
    contribution = contribution_audit_report(project)
    if contribution is not None and contribution.labelled < contribution.sample_size:
        out.append(
            PendingBrief(
                kind="contribution-audit",
                stage=None,
                count=contribution.sample_size - contribution.labelled,
                ids=[contribution.audit_id],
                command=f"{base} contributions audit label <audit-id> <work> <row-key> <field> "
                "--correct|--incorrect",
            )
        )
    gate_audits = [
        (row.audit.audit_id, (row.audit.sample_size or 0) - (row.audit.labelled or 0))
        for row in gates_status(project)
        if row.audit is not None
    ]
    waiting = [(audit_id, left) for audit_id, left in gate_audits if left > 0]
    if waiting:
        out.append(
            PendingBrief(
                kind="gate-audit",
                stage=None,
                count=sum(left for _, left in waiting),
                ids=sorted(audit_id for audit_id, _ in waiting),
                command=f"{base} gate audit label <audit-id> <act> <correct|incorrect>",
            )
        )
    unlabelled = [
        audit_id
        for draft in list_drafts(project)
        for audit_id, _, _, label in audit_sheet(project, draft.draft_id)
        if label is None
    ]
    if unlabelled:
        out.append(
            PendingBrief(
                kind="draft-audit",
                stage=None,
                count=len(unlabelled),
                ids=sorted(set(unlabelled)),
                command=f"{base} draft label <audit-id> <verdict-id> --correct|--incorrect",
            )
        )
    return out


def _lineage_pending(project: Project, base: str) -> list[PendingBrief]:
    relations = _inferred_relations(project)
    ideas = _proposed_ideas(project)
    interpretations, shown = unreviewed_interpretations(project)
    candidates: tuple[tuple[str, int, list[str], str], ...] = (
        (
            "relation-unconfirmed",
            len(relations),
            relations,
            f"{base} relations confirm|reject <relation-id> --rationale <text>",
        ),
        (
            "idea-unconfirmed",
            len(ideas),
            ideas,
            f"{base} ideas confirm|reject <idea-id> --rationale <text>",
        ),
        (
            "interpretation-unreviewed",
            interpretations,
            shown,
            f"{base} interpretations review <interpretation-id> --reviewed|--wrong",
        ),
    )
    return [
        PendingBrief(kind=kind, stage=None, count=count, ids=ids, command=command)
        for kind, count, ids, command in candidates
        if count
    ]


def _inferred_relations(project: Project) -> list[str]:
    found: list[str] = []
    while True:
        page = list_relations(
            project, statuses=(EdgeStatus.INFERRED,), limit=_PAGE, offset=len(found)
        )
        found += [r.relation_id for r in page]
        if len(page) < _PAGE:
            return sorted(found)


def _proposed_ideas(project: Project) -> list[str]:
    found: list[str] = []
    offset = 0
    while True:
        page = list_ideas(project, include_unconfirmed=True, limit=_PAGE, offset=offset)
        found += [i.idea_id for i in page if i.state == "proposed"]
        offset += _PAGE
        if len(page) < _PAGE:
            return sorted(found)

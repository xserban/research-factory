import shutil
from datetime import datetime
from typing import Literal

from pydantic import Field
from sqlalchemy import text

from factory.clock import Clock, parse_ts
from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.dedup import MergeStatus
from factory.model.project import ProjectCreated, RigorMode
from factory.model.protocol import ProtocolStatus, ScreeningStage
from factory.model.seed import SeedKind
from factory.services.agreement import (
    Agreement,
    PassProgress,
    cannot_assess_counts,
    pass_progress,
    screen_agreement,
)
from factory.services.audit import audit_report
from factory.services.calibration import CalibrationStatus, calibration_status
from factory.services.chase import chase_rounds
from factory.services.context import Project, ProjectPaths, build_project, slug_issues
from factory.services.decision_check import recommendation_figure
from factory.services.human_queue import HumanQueue, human_queue
from factory.services.prisma import has_full_text_plan
from factory.services.project_stage import Stage, derive_stage, stage_facts
from factory.services.protocol import current_protocol
from factory.services.question import current_question
from factory.services.screening import stale_screening_decisions
from factory.services.search import SearchCounts, corpus_size, search_counts
from factory.services.seeds import admitted_seed_count, all_seeds, split_is_drawn
from factory.services.tasks import TaskCounts, task_counts


class ProtocolSummary(StrictModel):
    protocol_id: str
    status: ProtocolStatus
    press: Literal["none", "reviewed", "confirmed"]


class SeedCounts(StrictModel):
    """Counts only: no seed identifier, so the status is safe for every agent to read."""

    positive: int
    negative: int
    unresolved: int
    split_drawn: bool


class ScreeningStatus(StrictModel):
    """Screening counts and rates only: no work, seed or label identifier. `kappa` and
    `unresolved_disagreements` are None until the passes have finished (see screen_agreement)."""

    calibration: CalibrationStatus
    passes: dict[str, PassProgress]
    kappa: float | None
    unresolved_disagreements: int | None
    stale_decisions: int
    audit_sample: int | None
    audit_labelled: int
    false_exclusion_rate: float | None
    full_text_passes: dict[str, PassProgress] | None = None
    """Pass progress at full text; None while the protocol declares no full-text plan."""
    cannot_assess_open: dict[str, int] = Field(default_factory=dict)
    """Unresolved cannot-assess works per stage (`agreement.cannot_assess_counts`, IDEA-67): a
    human queue, counted before the passes finish; it blocks nothing."""


class InboxCounts(StrictModel):
    """Link inbox items by status (slice 4a). Counts only: no link or note."""

    open: int = 0
    resolved: int = 0
    withdrawn: int = 0


class DecisionStatus(StrictModel):
    """Suggest and select, counted from the index. `open` are live sets awaiting the scientist;
    `recommendation_followed` is the share of selections where every recommended item was selected
    (None when no selection had a recommendation); see `services/decision_check.py`."""

    open: int = 0
    selected: int = 0
    with_recommendation: int = 0
    followed_in_full: int = 0
    recommendation_followed: float | None = None


class ProjectStatus(StrictModel):
    slug: str
    rigor_mode: RigorMode
    created_at: datetime
    events_total: int
    events_by_type: dict[str, int]
    last_event_at: datetime | None
    tasks: TaskCounts
    search: SearchCounts
    merges_active: int
    works: int
    records: int
    question: str | None
    protocol: ProtocolSummary | None
    seeds: SeedCounts
    screening: ScreeningStatus
    chase_rounds: int
    admitted_seeds: int
    human: HumanQueue | None = None
    """Pending human decisions per gate kind; counts only."""
    inbox: InboxCounts = InboxCounts()
    decisions: DecisionStatus = DecisionStatus()
    stage: Stage | None = None
    """The derived stage (spec 7a ruling 4); None only where an agent path takes it out."""
    blocking: list[str] = Field(default_factory=list)
    """Next steps that stop the flow and that a count would hide; empty when none."""


def init_project(
    settings: Settings, slug: str, rigor_mode: str, *, session: str, clock: Clock
) -> Project:
    """Create a project and record `project.created`. Writes nothing if validation fails."""
    issues = slug_issues(slug)
    try:
        mode = RigorMode(rigor_mode)
    except ValueError:
        choices = ", ".join(m.value for m in RigorMode)
        issues.append(ValidationIssue("rigor_mode", f"must be one of: {choices}"))
    if not issues and ProjectPaths(settings.root, slug).dir.exists():
        issues.append(ValidationIssue("slug", "project already exists"))
    if issues:
        raise FactoryValidationError(issues)

    paths = ProjectPaths(settings.root, slug)
    paths.dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        paths.dir.mkdir()
    except FileExistsError as exc:
        raise FactoryValidationError([ValidationIssue("slug", "project already exists")]) from exc

    try:
        project = build_project(settings, slug, session=session, clock=clock)
        with project.writing():
            event = project.events.make(
                "project.created",
                ProjectCreated(slug=slug, rigor_mode=mode),
                project.human_actor(),
            )
            project.record([event])
    except BaseException:
        shutil.rmtree(paths.dir, ignore_errors=True)
        raise
    return project


def project_status(project: Project, *, agent: bool = False) -> ProjectStatus:
    """The project's state. `agent` gives the human queue of the agent path, whose import gates
    count the development part only; the researcher's status stays complete."""
    project.index.sync()
    slug = project.paths.slug
    with project.index.connect() as conn:
        counts = conn.execute(text("SELECT type, COUNT(*) FROM events GROUP BY type")).all()
        last = conn.execute(text("SELECT MAX(ts) FROM events")).scalar_one()
        row = conn.execute(
            text("SELECT rigor_mode, created_at FROM project WHERE slug = :slug"),
            {"slug": slug},
        ).one_or_none()
        merges = conn.execute(
            text("SELECT COUNT(*) FROM merges WHERE status = :active"),
            {"active": MergeStatus.ACTIVE.value},
        ).scalar_one()
    if row is None:
        raise ProjectNotFoundError(f"project {slug!r} has no project.created event")
    works, records = corpus_size(project)
    question = current_question(project)
    protocol = current_protocol(project)
    seeds = all_seeds(project)
    by_type = {str(name): int(count) for name, count in counts}
    return ProjectStatus(
        slug=slug,
        rigor_mode=RigorMode(row[0]),
        created_at=parse_ts(str(row[1])),
        events_total=sum(by_type.values()),
        events_by_type=by_type,
        last_event_at=parse_ts(str(last)) if last is not None else None,
        tasks=task_counts(project),
        search=search_counts(project),
        merges_active=int(merges),
        works=works,
        records=records,
        question=None if question is None else question.question_id,
        protocol=(
            None
            if protocol is None
            else ProtocolSummary(
                protocol_id=protocol.protocol_id, status=protocol.status, press=protocol.press
            )
        ),
        seeds=SeedCounts(
            positive=sum(1 for seed in seeds if seed.kind is SeedKind.POSITIVE),
            negative=sum(1 for seed in seeds if seed.kind is SeedKind.NEGATIVE),
            unresolved=sum(1 for seed in seeds if seed.work_id is None),
            split_drawn=split_is_drawn(project),
        ),
        screening=_screening_status(project),
        chase_rounds=len(chase_rounds(project)),
        admitted_seeds=admitted_seed_count(project),
        human=human_queue(project, agent=agent),
        inbox=_inbox_counts(project),
        decisions=_decision_status(project),
        stage=derive_stage(stage_facts(project)),
        blocking=_blocking_steps(project),
    )


NO_FULL_TEXT_PLAN = "full-text screening is not planned in the protocol"


def _blocking_steps(project: Project) -> list[str]:
    """A protocol with no `full_text_screening` plan skips the full-text stage without a word in
    the counts; name it so it cannot pass unnoticed. Reads only; no count changes."""
    if current_protocol(project) is not None and not has_full_text_plan(project):
        return [f"{NO_FULL_TEXT_PLAN}; amend the protocol to add a full_text_screening plan"]
    return []


def _decision_status(project: Project) -> DecisionStatus:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT d.decision_id, EXISTS (SELECT 1 FROM decision_items i "
                "WHERE i.decision_id = d.decision_id AND i.status IN ('validated', 'rejected')) "
                "FROM decision_sets d WHERE d.superseded_by IS NULL"
            )
        ).all()
    figure = recommendation_figure(project)
    return DecisionStatus(
        open=sum(1 for r in rows if not r[1]),
        selected=sum(1 for r in rows if r[1]),
        with_recommendation=figure.with_recommendation,
        followed_in_full=figure.followed_in_full,
        recommendation_followed=figure.share,
    )


def _inbox_counts(project: Project) -> InboxCounts:
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT status, COUNT(*) FROM inbox_items GROUP BY status")).all()
    return InboxCounts.model_validate({str(status): int(n) for status, n in rows})


def screening_status(project: Project) -> ScreeningStatus:
    """The screening part of `project_status` alone (calibration, passes, agreement, audit, stale
    decisions, cannot-assess counts), without the stage, queue and snowball reads it also makes."""
    return _screening_status(project)


def _screening_status(project: Project) -> ScreeningStatus:
    agreement = _agreement_or_none(project)
    report = audit_report(project)
    return ScreeningStatus(
        calibration=calibration_status(project),
        passes=pass_progress(project),
        kappa=None if agreement is None else agreement.kappa,
        unresolved_disagreements=None if agreement is None else len(agreement.disagreements),
        stale_decisions=len(stale_screening_decisions(project)),
        audit_sample=None if report is None else report.sample_size,
        audit_labelled=0 if report is None else report.labelled,
        false_exclusion_rate=None if report is None else report.rates.false_exclusion,
        full_text_passes=(
            pass_progress(project, stage=ScreeningStage.FULL_TEXT)
            if has_full_text_plan(project)
            else None
        ),
        cannot_assess_open=cannot_assess_counts(project),
    )


def _agreement_or_none(project: Project) -> Agreement | None:
    """The agreement once both passes have finished; None while it is refused."""
    try:
        return screen_agreement(project, project.human_actor())
    except FactoryValidationError:
        return None

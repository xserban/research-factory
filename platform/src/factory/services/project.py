import shutil
from datetime import datetime
from typing import Literal

from sqlalchemy import text

from factory.clock import Clock, parse_ts
from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.dedup import MergeStatus
from factory.model.project import ProjectCreated, RigorMode
from factory.model.protocol import ProtocolStatus, ScreeningStage
from factory.model.seed import SeedKind
from factory.services.agreement import Agreement, PassProgress, pass_progress, screen_agreement
from factory.services.audit import audit_report
from factory.services.calibration import CalibrationStatus, calibration_status
from factory.services.chase import chase_rounds
from factory.services.context import Project, ProjectPaths, build_project, slug_issues
from factory.services.human_queue import HumanQueue, human_queue
from factory.services.prisma import has_full_text_plan
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


def project_status(project: Project) -> ProjectStatus:
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
        human=human_queue(project),
    )


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
    )


def _agreement_or_none(project: Project) -> Agreement | None:
    """The agreement once both passes have finished; None while it is refused."""
    try:
        return screen_agreement(project, project.human_actor())
    except FactoryValidationError:
        return None

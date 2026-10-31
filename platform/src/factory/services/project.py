from datetime import datetime

from sqlalchemy import text

from factory.clock import Clock
from factory.config import Settings
from factory.errors import FactoryValidationError, ProjectNotFoundError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.project import ProjectCreated, RigorMode
from factory.services.context import Project, ProjectPaths, build_project, slug_issues
from factory.services.tasks import TaskCounts, task_counts


class ProjectStatus(StrictModel):
    slug: str
    rigor_mode: RigorMode
    created_at: datetime
    events_total: int
    events_by_type: dict[str, int]
    last_event_at: datetime | None
    tasks: TaskCounts


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

    project = build_project(settings, slug, session=session, clock=clock)
    event = project.events.make(
        "project.created",
        ProjectCreated(slug=slug, rigor_mode=mode),
        project.human_actor(),
    )
    project.record([event])
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
    if row is None:
        raise ProjectNotFoundError(f"project {slug!r} has no project.created event")
    by_type = {str(name): int(count) for name, count in counts}
    return ProjectStatus(
        slug=slug,
        rigor_mode=RigorMode(row[0]),
        created_at=_parse_ts(str(row[1])),
        events_total=sum(by_type.values()),
        events_by_type=by_type,
        last_event_at=_parse_ts(str(last)) if last is not None else None,
        tasks=task_counts(project),
    )


def _parse_ts(value: str) -> datetime:
    # Stored as `YYYY-MM-DDTHH:MM:SS.mmmZ`, which fromisoformat reads once `Z` becomes an offset.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

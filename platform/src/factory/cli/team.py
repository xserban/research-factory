"""`factory workspace`, `factory project`, `factory review` and the protocol commands of a holder
of `protocol:change` (slice 5, plan teams-B).

They parse input, call a service and format its answer. `main._resolve_project` authorises each by
its `TOOL_PERMISSIONS` row. The shared helpers of `factory.cli.main` are imported inside each
command, because that module imports this one to register the commands.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, cast

import typer
from pydantic import JsonValue

from factory.cli.review import deferred_app
from factory.model.project import Visibility
from factory.model.reviews import (
    DeviationProposal,
    ProtocolAmendProposal,
    ProtocolRecordProposal,
    ReviewDecision,
    ReviewKind,
    ReviewState,
)
from factory.model.screening import Channel
from factory.services import hosting as hosting_service
from factory.services import protocol as protocol_service
from factory.services import reviews as reviews_service
from factory.services import workspace as workspace_service
from factory.services.access import full_view_allowed, set_visibility
from factory.services.agent_view import scrubbed_text
from factory.services.context import Project
from factory.services.reviews import ReviewView

project_app = typer.Typer(name="project", help="The project itself.", no_args_is_help=True)
review_app = typer.Typer(name="review", help="Review requests.", no_args_is_help=True)
review_app.add_typer(deferred_app)

ReviewArg = Annotated[str, typer.Argument(help="Review request id.")]
FileOption = Annotated[
    Path, typer.Option("--file", help="JSON file holding what the tool takes, as a proposal does.")
]
ReviewOption = Annotated[
    str | None, typer.Option("--review", help="The approved review request this consumes.")
]


@contextmanager
def _project(ctx: typer.Context) -> Iterator[Project]:
    from factory.cli import main

    state = main._state(ctx)
    with main._reporting_errors():
        yield main._resolve_project(state)


def _echo(project: Project, text: str) -> None:
    """Print `text`, without held-out identifiers for a person without the full view."""
    full = full_view_allowed(project, project.principal)
    typer.echo(text if full else scrubbed_text(project, text))


def _read_json(path: Path) -> JsonValue:
    from factory.cli import main

    try:
        data: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        main._fail(f"cannot read {path}: {exc}", 1)
    return data


def review_line(view: ReviewView) -> str:
    return (
        f"{view.review_request_id}  {view.kind.value}  {view.state.value}  "
        f"{view.requester}  needs {view.required_role.value}  {view.reason}"
    )


def workspace_lines(built: workspace_service.Workspace) -> list[str]:
    """The workspace as text: a heading per list, its items below."""
    roles = ", ".join(sorted(role.value for role in built.roles)) or "none"
    lines = [f"user: {built.user}", f"roles: {roles}"]
    if built.notice is not None:
        lines.append(built.notice)
    lines.append(f"sessions: {len(built.sessions)}")
    lines.extend(f"  {s.session}  {s.events} events" for s in built.sessions)
    lines.append(f"open tasks: {len(built.open_tasks)}")
    lines.extend(f"  {task}" for task in built.open_tasks)
    lines.append(f"proposals: {len(built.proposals)}")
    lines.extend(f"  {item}" for item in built.proposals)
    lines.append(f"reviews requested: {len(built.reviews_requested)}")
    lines.extend(f"  {review_line(view)}" for view in built.reviews_requested)
    lines.append(f"reviews to decide: {len(built.reviews_to_decide)}")
    lines.extend(f"  {review_line(view)}" for view in built.reviews_to_decide)
    return lines


def workspace_cmd(
    ctx: typer.Context,
    user: Annotated[
        str | None, typer.Option("--user", help="Whose workspace; default: your own.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the Workspace as JSON.")] = False,
) -> None:
    """A person's sessions, tasks, proposals and reviews on this project."""
    with _project(ctx) as project:
        built = workspace_service.workspace(project, user or project.principal.user)
    _echo(project, built.model_dump_json() if as_json else "\n".join(workspace_lines(built)))


@project_app.command("visibility")
def project_visibility_cmd(
    ctx: typer.Context,
    value: Annotated[str, typer.Argument(help="`lab` or `private` (members only).")],
) -> None:
    """Set who reads this project (owner)."""
    with _project(ctx) as project:
        set_visibility(project, project.human_actor(), cast(Visibility, value))
    typer.echo(f"visibility {value}")


@project_app.command("host")
def project_host_cmd(
    ctx: typer.Context,
    slug: Annotated[str, typer.Argument(help="Project slug (events already pulled by git).")],
    owner: Annotated[str, typer.Option("--owner", help="User id of the first owner (required).")],
    reason: Annotated[
        str, typer.Option("--reason", help="Why.")
    ] = "project imported onto this server",
) -> None:
    """Host a project pulled onto this server and name its first owner (lab admin)."""
    from factory.cli.admin import _member_call

    with _member_call(ctx, "cli:project host", slug) as project:
        hosting_service.host_import(project, project.human_actor(), owner, reason)
    typer.echo(f"hosted {slug}; owner {owner}")


@review_app.command("list")
def review_list_cmd(
    ctx: typer.Context,
    state: Annotated[
        ReviewState | None, typer.Option("--state", help="Only requests in this state.")
    ] = None,
) -> None:
    """Review requests, in filing order."""
    with _project(ctx) as project:
        views = reviews_service.reviews(project, state=state)
    if not views:
        typer.echo(reviews_service.NO_REVIEWS_NOTICE)
        return
    _echo(project, "\n".join(review_line(view) for view in views))


@review_app.command("show")
def review_show_cmd(ctx: typer.Context, review_request_id: ReviewArg) -> None:
    """One request and its proposal, as JSON."""
    with _project(ctx) as project:
        view = reviews_service.review(project, review_request_id)
        proposal = reviews_service.proposal_of(project, review_request_id)
    _echo(project, json.dumps({**view.model_dump(mode="json"), "proposal": proposal}, indent=2))


@review_app.command("request")
def review_request_cmd(
    ctx: typer.Context,
    kind: Annotated[ReviewKind, typer.Option("--kind", help="What the proposal changes.")],
    file: FileOption,
    reason: Annotated[str, typer.Option("--reason", help="Why (required).")],
) -> None:
    """File a request for what you may not apply alone."""
    with _project(ctx) as project:
        filed = reviews_service.request_review(
            project, project.human_actor(), kind, _read_json(file), reason
        )
    typer.echo(filed)


@review_app.command("decide")
def review_decide_cmd(
    ctx: typer.Context,
    review_request_id: ReviewArg,
    decision: Annotated[str, typer.Argument(help="`approve` or `reject`.")],
    rationale: Annotated[str, typer.Option("--rationale", help="Why (required).")],
) -> None:
    """Decide a request. Approval applies nothing: run the ordinary command with `--review`."""
    with _project(ctx) as project:
        reviews_service.decide_review(
            project,
            project.human_actor(),
            review_request_id,
            cast(ReviewDecision, decision),
            rationale,
            Channel.CLI,
        )
    typer.echo(f"{decision} {review_request_id}")


@review_app.command("withdraw")
def review_withdraw_cmd(
    ctx: typer.Context,
    review_request_id: ReviewArg,
    rationale: Annotated[str, typer.Option("--rationale", help="Why (required).")],
) -> None:
    """Withdraw your own request."""
    with _project(ctx) as project:
        reviews_service.decide_review(
            project, project.human_actor(), review_request_id, "withdraw", rationale, Channel.CLI
        )
    typer.echo(f"withdrawn {review_request_id}")


DecisionOption = Annotated[
    list[str] | None,
    typer.Option("--decision", help="A selected protocol decision this implements (repeatable)."),
]


def protocol_record_cmd(
    ctx: typer.Context,
    file: FileOption,
    review: ReviewOption = None,
    decision: DecisionOption = None,
) -> None:
    """Record the protocol from a file, as a person."""
    with _project(ctx) as project:
        parsed = reviews_service.parse_proposal(ReviewKind.PROTOCOL_RECORD, _read_json(file))
        assert isinstance(parsed, ProtocolRecordProposal)
        result = protocol_service.record_protocol(
            project,
            project.human_actor(),
            parsed.spec,
            ready=parsed.ready,
            review_request_id=review,
            decision_ids=decision,
        )
    typer.echo(result.protocol_id)


def protocol_amend_cmd(ctx: typer.Context, file: FileOption, review: ReviewOption = None) -> None:
    """Amend the ready protocol from a file, as a person."""
    with _project(ctx) as project:
        parsed = reviews_service.parse_proposal(ReviewKind.PROTOCOL_AMEND, _read_json(file))
        assert isinstance(parsed, ProtocolAmendProposal)
        result = protocol_service.amend_protocol(
            project,
            project.human_actor(),
            parsed.spec,
            reason=parsed.reason,
            semantic=parsed.semantic,
            effects=parsed.effects,
            review_request_id=review,
        )
    typer.echo(result.to_version)


def protocol_deviation_cmd(
    ctx: typer.Context, file: FileOption, review: ReviewOption = None
) -> None:
    """Record a deviation from a file, as a person."""
    with _project(ctx) as project:
        parsed = reviews_service.parse_proposal(ReviewKind.DEVIATION, _read_json(file))
        assert isinstance(parsed, DeviationProposal)
        deviation = protocol_service.record_deviation(
            project,
            project.human_actor(),
            description=parsed.description,
            reason=parsed.reason,
            affects=parsed.affects,
            review_request_id=review,
        )
    typer.echo(deviation)

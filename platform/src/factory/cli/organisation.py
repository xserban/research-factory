"""`factory labels`, `factory terms` and `factory consolidation` (slice 3d, plan Regions-C).

Organisation commands, all as the researcher: they parse input, call a service in
`factory.services` and format its answer. Every printed row names the class `organisation`.
The shared helpers of `factory.cli.main` are imported inside each command, because that module
imports this one to register the command groups.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal, cast

import typer

from factory.regions.rules import MemberType
from factory.services import consolidation as consolidation_service
from factory.services import labels as labels_service
from factory.services import terms as terms_service
from factory.services.consolidation import ClusterRow, Decision
from factory.services.context import Project
from factory.services.labels import LabelView
from factory.services.terms import TermView

labels_app = typer.Typer(
    name="labels",
    help="Free labels (organisation, not evidence): list, apply, withdraw, merge, confirm.",
    no_args_is_help=True,
)
terms_app = typer.Typer(
    name="terms",
    help="Terms: promote a label key, revise, retire, list and suggest promotions.",
    no_args_is_help=True,
)
consolidation_app = typer.Typer(
    name="consolidation",
    help="Consolidation passes: candidate clusters, human merge decisions, completion.",
    no_args_is_help=True,
)

_REASON = typer.Option("--reason", help="Why (required).")
Reason = Annotated[str, _REASON]


@contextmanager
def _project(ctx: typer.Context) -> Iterator[Project]:
    """The researcher's project for one command; service errors become stderr lines and exit 1."""
    from factory.cli import main

    state = main._state(ctx)
    with main._reporting_errors():
        yield main._resolve_project(state)


# --- Formatting ---


def label_lines(views: list[LabelView]) -> list[str]:
    """One line per live application, then the class line."""
    lines = [
        f"{v.application_id}  {v.key!r}"
        + ("" if v.live_key == v.key else f" -> {v.live_key!r}")
        + f"  {v.target_type.value} {v.target}  {v.status}  {v.origin}"
        for v in views
    ]
    return [*lines, f"{len(views)} application(s)  class organisation"]


def term_lines(views: list[TermView]) -> list[str]:
    lines = []
    for v in views:
        counts = ", ".join(f"{n} {k}" for k, n in v.counts.items())
        aliases = f" (aliases: {', '.join(v.aliases)})" if v.aliases else ""
        retired = " [retired]" if v.retired else ""
        lines.append(f"{v.term_id}  {v.name}{aliases}  v{v.version}  {counts}{retired}")
    return [*lines, f"{len(views)} term(s)  class organisation"]


def cluster_lines(rows: list[ClusterRow]) -> list[str]:
    lines = []
    for r in rows:
        shown = r.decision or "undecided"
        proposals = f"  proposals: {', '.join(r.proposal_ids)}" if r.proposal_ids else ""
        lines.append(f"{r.index}  {r.kind}  {shown}  {', '.join(r.members)}{proposals}")
    return lines


# --- labels ---


@labels_app.command("list")
def labels_list_cmd(
    ctx: typer.Context,
    key: Annotated[
        str | None, typer.Option("--key", help="A label key or one merged into it.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 500,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
) -> None:
    """Live label applications, with their status and origin."""
    with _project(ctx) as project:
        views = labels_service.list_labels(project, key=key, limit=limit, offset=offset)
    for line in label_lines(views):
        typer.echo(line)


@labels_app.command("apply")
def labels_apply_cmd(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help="The label, at most 60 characters.")],
    target: Annotated[str, typer.Option("--target", help="A work, idea (ida_) or concept (cpt_).")],
    target_type: Annotated[
        MemberType, typer.Option("--type", help="work, idea or concept.")
    ] = MemberType.WORK,
) -> None:
    """Apply a label as the researcher (confirmed)."""
    with _project(ctx) as project:
        result = labels_service.apply_labels(
            project,
            project.human_actor(),
            [labels_service.LabelInput(target_type=target_type, target=target, text=text)],
        )
        for error in result.rejected:
            for issue in error.issues:
                typer.echo(f"{issue.field}: {issue.reason}", err=True)
        if result.rejected:
            raise typer.Exit(1)
    typer.echo(f"applied {result.written[0]}")


@labels_app.command("withdraw")
def labels_withdraw_cmd(
    ctx: typer.Context,
    application: Annotated[str, typer.Argument(help="An application id, lbl_.")],
    reason: Reason,
) -> None:
    """Withdraw an application; it stays in the log."""
    with _project(ctx) as project:
        labels_service.withdraw_label(project, project.human_actor(), application, reason)
    typer.echo(f"withdrawn {application}")


def _decide(ctx: typer.Context, application: str, decision: str) -> None:
    with _project(ctx) as project:
        labels_service.decide_application(
            project,
            project.human_actor(),
            application,
            cast(Literal["confirm", "reject"], decision),
        )
    typer.echo(
        f"{decision}ed {application}" if decision == "reject" else f"confirmed {application}"
    )


@labels_app.command("confirm")
def labels_confirm_cmd(
    ctx: typer.Context,
    application: Annotated[str, typer.Argument(help="An application id, lbl_.")],
) -> None:
    """Confirm an application as the researcher."""
    _decide(ctx, application, "confirm")


@labels_app.command("reject")
def labels_reject_cmd(
    ctx: typer.Context,
    application: Annotated[str, typer.Argument(help="An application id, lbl_.")],
) -> None:
    """Reject an application; it leaves every view."""
    _decide(ctx, application, "reject")


@labels_app.command("merge")
def labels_merge_cmd(
    ctx: typer.Context,
    into_key: Annotated[str, typer.Argument(help="The key that remains.")],
    from_key: Annotated[str, typer.Argument(help="The key that now reads as `into_key`.")],
    reason: Reason,
) -> None:
    """Merge one label key into another, reversibly."""
    with _project(ctx) as project:
        event = labels_service.merge_labels(
            project, project.human_actor(), into_key, from_key, reason
        )
    typer.echo(f"merged {from_key!r} into {into_key!r}: {event}")


@labels_app.command("unmerge")
def labels_unmerge_cmd(
    ctx: typer.Context,
    merge_event: Annotated[str, typer.Argument(help="The merge's event id, ev_.")],
    reason: Reason,
) -> None:
    """Reverse one label merge."""
    with _project(ctx) as project:
        labels_service.unmerge_labels(project, project.human_actor(), merge_event, reason)
    typer.echo(f"unmerged {merge_event}")


# --- terms ---

_ALIAS = typer.Option("--alias", help="An alias; repeat for several.")
_APPLIES = typer.Option("--applies-to", help="work, idea or concept; repeat for several.")


@terms_app.command("promote")
def terms_promote_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="The preferred name (a label key).")],
    definition: Annotated[str, typer.Option("--definition", help="At most 600 characters.")],
    applies_to: Annotated[list[MemberType], _APPLIES],
    alias: Annotated[list[str] | None, _ALIAS] = None,
    refers_to: Annotated[
        str | None, typer.Option("--refers-to", help="An idea or concept id (navigation only).")
    ] = None,
    from_key: Annotated[
        list[str] | None, typer.Option("--from-key", help="A merged label key this came from.")
    ] = None,
) -> None:
    """Promote a label key to a term as the researcher."""
    with _project(ctx) as project:
        term = terms_service.promote_term(
            project,
            project.human_actor(),
            name=name,
            definition=definition,
            applies_to=applies_to,
            aliases=alias or [],
            refers_to=refers_to,
            from_keys=from_key or [],
        )
    typer.echo(f"promoted {term}")


@terms_app.command("revise")
def terms_revise_cmd(
    ctx: typer.Context,
    term: Annotated[str, typer.Argument(help="A term id, trm_.")],
    name: Annotated[str, typer.Option("--name", help="The preferred name.")],
    definition: Annotated[str, typer.Option("--definition", help="At most 600 characters.")],
    applies_to: Annotated[list[MemberType], _APPLIES],
    alias: Annotated[list[str] | None, _ALIAS] = None,
    refers_to: Annotated[str | None, typer.Option("--refers-to")] = None,
    from_key: Annotated[list[str] | None, typer.Option("--from-key")] = None,
) -> None:
    """Record a new version of a term."""
    with _project(ctx) as project:
        terms_service.revise_term(
            project,
            project.human_actor(),
            term,
            name=name,
            definition=definition,
            applies_to=applies_to,
            aliases=alias or [],
            refers_to=refers_to,
            from_keys=from_key or [],
        )
    typer.echo(f"revised {term}")


@terms_app.command("retire")
def terms_retire_cmd(
    ctx: typer.Context,
    term: Annotated[str, typer.Argument(help="A term id, trm_.")],
    reason: Reason,
) -> None:
    """Retire a term; a region rule naming it is then refused."""
    with _project(ctx) as project:
        terms_service.retire_term(project, project.human_actor(), term, reason)
    typer.echo(f"retired {term}")


@terms_app.command("list")
def terms_list_cmd(
    ctx: typer.Context,
    retired: Annotated[bool, typer.Option("--retired", help="Include retired terms.")] = False,
) -> None:
    """Terms with the number of their applications by status."""
    with _project(ctx) as project:
        views = terms_service.list_terms(project, include_retired=retired)
    for line in term_lines(views):
        typer.echo(line)


@terms_app.command("suggest")
def terms_suggest_cmd(ctx: typer.Context) -> None:
    """Label keys applied to enough distinct targets to be worth promoting."""
    with _project(ctx) as project:
        found = terms_service.promotion_suggestions(project)
    for key, n in found:
        typer.echo(f"{key!r}  {n} targets")
    typer.echo(f"{len(found)} suggestion(s)  class organisation")


# --- consolidation ---


@consolidation_app.command("status")
def consolidation_status_cmd(ctx: typer.Context) -> None:
    """Whether consolidation is due, and the open pass if any."""
    with _project(ctx) as project:
        due = consolidation_service.consolidation_due(project)
        open_pass = consolidation_service.open_pass_id(project)
    typer.echo(f"new label keys: {due.new_label_keys}")
    typer.echo(f"new idea and concept nodes: {due.new_nodes}")
    typer.echo(f"due: {'yes' if due.due else 'no'}")
    typer.echo(f"open pass: {open_pass or '-'}")


@consolidation_app.command("start")
def consolidation_start_cmd(ctx: typer.Context) -> None:
    """Compute the candidate clusters and open a pass (one task per cluster)."""
    with _project(ctx) as project:
        pass_id = consolidation_service.start_pass(project, project.human_actor())
        rows = consolidation_service.list_clusters(project, pass_id)
    typer.echo(f"started {pass_id}: {len(rows)} cluster(s)")


@consolidation_app.command("list")
def consolidation_list_cmd(
    ctx: typer.Context,
    pass_id: Annotated[
        str | None, typer.Argument(help="A pass id, cns_ (default: the open pass).")
    ] = None,
) -> None:
    """The clusters of a pass with their decisions and proposals."""
    with _project(ctx) as project:
        chosen = pass_id or consolidation_service.open_pass_id(project)
        rows = [] if chosen is None else consolidation_service.list_clusters(project, chosen)
    for line in cluster_lines(rows):
        typer.echo(line)
    typer.echo(f"{len(rows)} cluster(s)  class organisation")


@consolidation_app.command("decide")
def consolidation_decide_cmd(
    ctx: typer.Context,
    pass_id: Annotated[str, typer.Argument(help="A pass id, cns_.")],
    index: Annotated[int, typer.Argument(help="The cluster's index.")],
    decision: Annotated[str, typer.Argument(help="merge, keep, split or skip.")],
    reason: Reason,
    into: Annotated[
        str | None, typer.Option("--into", help="The surviving member (merge).")
    ] = None,
    merge_from: Annotated[
        list[str] | None, typer.Option("--from", help="Members to merge; default all others.")
    ] = None,
    proposal: Annotated[str | None, typer.Option("--proposal", help="A proposal id, cnp_.")] = None,
) -> None:
    """Decide one cluster as the researcher; a merge is recorded with its decision."""
    with _project(ctx) as project:
        event = consolidation_service.decide_cluster(
            project,
            project.human_actor(),
            pass_id,
            index,
            cast(Decision, decision),
            into=into,
            merge_from=merge_from,
            reason=reason,
            proposal_id=proposal,
        )
    typer.echo(f"decided {decision}: {event}")


@consolidation_app.command("complete")
def consolidation_complete_cmd(
    ctx: typer.Context,
    pass_id: Annotated[str, typer.Argument(help="A pass id, cns_.")],
) -> None:
    """Complete a pass whose every cluster is decided; the due counts start again."""
    with _project(ctx) as project:
        consolidation_service.complete_pass(project, project.human_actor(), pass_id)
    typer.echo(f"completed {pass_id}")

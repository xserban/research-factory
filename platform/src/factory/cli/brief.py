"""`factory brief` (plan 2026-11-20-tiers-and-autonomy, lane L2): start and read a quick review.

`brief new "<question>"` creates an exploratory project and records the question verbatim as its
goal (the researcher's own words); `brief plan <project>` lists the tier's stages, caps, limits
and what it skips; `brief status <project>` shows where the project stands against that plan.
Thin: the plan is `factory.tiers` data, the state comes from `services/project`. `brief new` is
the act of `factory init` and is authorised as `cli:init`. The helpers of `factory.cli.main` are
imported inside the functions, because that module imports this one.

Tier recording: `new` passes the tier to `init_project` (lane L1), which records it on
`project.created`.
"""

from __future__ import annotations

import re
from dataclasses import replace
from enum import StrEnum
from typing import Annotated

import typer

from factory.model.levels import Tier
from factory.services import project as project_service
from factory.services.context import MAX_SLUG_LENGTH, Project
from factory.services.question import state_goal
from factory.tiers import TierPlan, plan_for, skipped_steps

brief_app = typer.Typer(
    name="brief", help="A quick review: start one, list its plan, read its status."
)

_TIERS = (Tier.BRIEF, Tier.DEEP)


class NoteFormat(StrEnum):
    MD = "md"
    JSON = "json"


def default_slug(question: str) -> str:
    """A slug from the question's first words: lowercase words joined by single hyphens."""
    words = re.findall(r"[a-z0-9]+", question.lower())
    slug = "-".join(["brief", *words[:6]])
    return slug[:MAX_SLUG_LENGTH].rstrip("-")


def _tier_of(project: Project, override: Tier | None) -> Tier:
    """The project's tier when the project service reports one, else `override`, else brief."""
    if override is not None:
        return override
    reader = getattr(project_service, "project_levels", None)
    if reader is not None:
        tier = reader(project).tier
        if tier is not None:
            return Tier(tier)
    return Tier.BRIEF


def plan_lines(plan: TierPlan) -> list[str]:
    lines = [f"tier {plan.tier.value}"]
    if plan.limits is not None:
        lim = plan.limits
        lines.append(
            f"limits: {lim.max_papers} papers, {lim.max_minutes} minutes, {lim.max_runs} runs"
        )
    lines.append("stages:")
    for s in plan.stages:
        caps = ", ".join(f"{k}={v}" for k, v in s.caps.items())
        state = "skipped" if s.skipped else (caps or "uncapped")
        lines.append(f"  {s.stage_id:<10} {s.skill:<14} {state}")
        if s.note and not s.skipped:
            lines.append(f"             {s.note}")
    skipped = skipped_steps(plan.tier)
    lines.append("skipped:" if skipped else "skipped: nothing")
    lines.extend(f"  {step}" for step in skipped)
    return lines


def _open(ctx: typer.Context, slug: str) -> Project:
    from factory.cli import main

    state = main._state(ctx)
    return main._resolve_project(replace(state, project=slug))


@brief_app.command("new")
def brief_new_cmd(
    ctx: typer.Context,
    question: Annotated[str, typer.Argument(help="The question, in the researcher's own words.")],
    slug: Annotated[str | None, typer.Option("--slug", help="Project slug.")] = None,
    tier: Annotated[Tier, typer.Option("--tier", help="brief or deep.")] = Tier.BRIEF,
) -> None:
    """Create an exploratory project for a quick review and record the question as its goal."""
    from factory.cli import main
    from factory.services.cli_access import authorise_root_command

    state = main._state(ctx)
    name = slug or default_slug(question)
    with main._reporting_errors():
        if tier not in _TIERS:
            raise typer.BadParameter("brief new makes a brief or a deep project")
        authorise_root_command(state.settings, "cli:init", session=state.session, clock=state.clock)
        project = project_service.init_project(
            state.settings,
            name,
            "exploratory",
            session=state.session,
            clock=state.clock,
            tier=tier.value,
        )
        state_goal(project, project.human_actor(), question)
    typer.echo(f"initialised {name} (exploratory, tier {tier.value})")
    typer.echo(f"next: factory brief plan {name}")


@brief_app.command("plan")
def brief_plan_cmd(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="Project slug.")],
    tier: Annotated[Tier | None, typer.Option("--tier", help="Show this tier's plan.")] = None,
) -> None:
    """List the stages, caps and limits of the project's tier and what it skips."""
    from factory.cli import main

    with main._reporting_errors():
        opened = _open(ctx, project)
        plan = plan_for(_tier_of(opened, tier))
    for line in plan_lines(plan):
        typer.echo(line)


@brief_app.command("status")
def brief_status_cmd(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="Project slug.")],
) -> None:
    """Where the project stands against the tier's plan and limits."""
    from factory.cli import main

    with main._reporting_errors():
        opened = _open(ctx, project)
        status = project_service.project_status(opened)
        plan = plan_for(_tier_of(opened, None))
    stage = status.stage.value if status.stage is not None else "-"
    typer.echo(f"{status.slug}: tier {plan.tier.value}, mode {status.rigor_mode.value}")
    typer.echo(f"stage {stage}; question {status.question or '-'}")
    typer.echo(f"protocol {'-' if status.protocol is None else status.protocol.protocol_id}")
    papers = f"{status.works} works, {status.records} records"
    if plan.limits is not None:
        papers += f" (limit {plan.limits.max_papers} papers)"
    typer.echo(papers)
    for item in status.blocking:
        typer.echo(f"blocking: {item}")


@brief_app.command("note")
def brief_note_cmd(
    ctx: typer.Context,
    project: Annotated[str, typer.Argument(help="Project slug.")],
    fmt: Annotated[NoteFormat, typer.Option("--format", help="md or json.")] = NoteFormat.MD,
) -> None:
    """The computed evidence note: counts, extracted rows, verified quotes, limits and label.
    Read-only; the agent adds at most a short synthesis that cites verified quotes."""
    from factory.cli import main
    from factory.services import agent_view
    from factory.services import brief_note as note_service

    with main._reporting_errors():
        opened = _open(ctx, project)
        full = main._full_view(opened)
        note = note_service.brief_note(opened, full=full)
        text = (
            note.model_dump_json()
            if fmt is NoteFormat.JSON
            else note_service.render_brief_note(note)
        )
        if not full:
            text = agent_view.scrubbed_text(opened, text)
    typer.echo(text, nl=not text.endswith("\n"))

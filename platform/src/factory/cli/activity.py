"""`factory activity` (IDEA-98): the four panels of the Activity page as plain text.

It parses nothing, calls `factory.services.activity.activity` as of now and formats the answer.
Read-only: nothing is written. Its `TOOL_PERMISSIONS` row is `cli:activity`; the helpers of
`factory.cli.main` are imported inside the command, because that module imports this one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import typer

from factory.services.activity import DORMANT_HOURS, STALE_MINUTES, Activity, activity


def format_activity(found: Activity) -> list[str]:
    """The lines of the four panels; empty panels say so."""
    lines = [f"Activity as of {found.now}", "", "Held tasks"]
    for a in found.active:
        task = (
            a.scope
            + (f" v{a.miner_version}" if a.miner_version is not None else "")
            + (f" pass {a.pass_label}" if a.pass_label else "")
            + (f" {a.mode}" if a.mode else "")
        )
        state = f"STALE (no event for {STALE_MINUTES} min)" if a.stale else "active"
        lines.append(
            f"  {a.session[-6:]}  {task}  {a.title or a.work_id or '-'}  held {a.minutes_held} min"
            f"  lease {a.lease_minutes_left} min left  rows {a.rows_recorded}"
            f"  last event {a.last_event_at or 'none'}  {state}"
        )
    if not found.active:
        lines.append("  no task is held")
    lines += ["", "Passes"]
    for p in found.passes:
        eta = "unknown" if p.eta_estimate_minutes is None else f"{p.eta_estimate_minutes} min"
        name = (
            p.name
            + (f" v{p.version}" if p.version is not None else "")
            + (f" pass {p.pass_label}" if p.pass_label else "")
            + (f" {p.mode}" if p.mode else "")
        )
        lines.append(
            f"  {name}: {p.done}/{p.total} done, {p.claimed} held, {p.abandoned} abandoned, "
            f"{p.completed_recent} in the last 30 min, rate (estimate) "
            f"{p.rate_estimate_per_hour}/h, left (estimate) {eta}, {p.released} released"
        )
    if not found.passes:
        lines.append("  no pass is open")
    if found.dormant:
        lines.append(
            f"  {len(found.dormant)} dormant passes (nothing held or done in the last "
            f"{DORMANT_HOURS} h)"
        )
    lines += ["", "Long operations"]
    for o in found.operations:
        lines.append(
            f"  {o.get('label') or o.get('op_id')}: {o.get('state')}, "
            f"{o.get('done')}/{o.get('total') if o.get('total') is not None else '?'}"
        )
    if not found.operations:
        lines.append("  no long operation is running")
    lines += ["", "Worker traces"]
    for t in found.traces:
        lines.append(f"  {t.path}  {t.modified_at}  {t.last_line}  ({t.size} B)")
    if not found.traces:
        lines.append("  no trace file changed in the last 2 hours")
    return lines


def activity_cmd(ctx: typer.Context) -> None:
    """Print what the agents are working on now: held tasks, passes, long operations, traces."""
    from factory.cli.main import _resolve_project, _state

    project = _resolve_project(_state(ctx))
    for line in format_activity(activity(project, datetime.now(UTC))):
        typer.echo(line)

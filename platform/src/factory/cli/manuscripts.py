"""`factory manuscript` (slice 7b, plan W-C): add, status, resolve, report, audit.

All as the researcher: these commands parse input, call a service and format its answer. Only
`report` prints a manuscript's text, read from the library at render time, to stdout or a path you
name, never under the project. The shared helpers of `factory.cli.main` are imported inside each
command, because that module imports this one to register the command group.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.drafts import AuditLabel
from factory.model.manuscripts import (
    CitationDecision,
    CitationState,
    ManuscriptFormat,
    ManuscriptStatus,
    ResolutionSummary,
)
from factory.services import manuscript_audit as audit_service
from factory.services import manuscript_report as report_service
from factory.services import manuscript_resolve as resolve_service
from factory.services import manuscripts as manuscripts_service

manuscript_app = typer.Typer(
    name="manuscript",
    help="External manuscripts checked against the corpus: add, status, resolve, report, audit.",
    no_args_is_help=True,
)


def _summary(found: ResolutionSummary) -> str:
    return (
        f"citations: {found.resolved} resolved, {found.proposed} proposed, "
        f"{found.unresolved} unresolved; {found.closed} unit(s) closed"
    )


def _status_lines(status: ManuscriptStatus) -> list[str]:
    def counts(values: dict[str, int]) -> str:
        return ", ".join(f"{k} {values[k]}" for k in sorted(values)) or "none"

    return [
        f"{status.manuscript_id}  {status.label}",
        f"sentences: {status.sentences}; cited: {status.cited}",
        f"citations: {counts(status.citations)}",
        f"verdicts: {counts(status.verdicts)}",
        f"cannot verify: {counts(status.closed)}",
        f"units without a verdict: {status.open_units}",
        f"uncited-claim flags (advisory): {status.flags}",
    ]


@manuscript_app.command("add")
def manuscript_add_cmd(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="The manuscript. It is copied, never changed.")],
    format_: Annotated[str, typer.Option("--format", help="markdown, latex or text.")],
    label: Annotated[str, typer.Option("--label", help="Your own label, at most 80 characters.")],
    bib: Annotated[
        Path | None, typer.Option("--bib", help="A companion BibTeX or CSL-JSON file.")
    ] = None,
) -> None:
    """Store a manuscript in the library, segment it and resolve its citations."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        try:
            fmt = ManuscriptFormat(format_)
        except ValueError:
            raise FactoryValidationError(
                [ValidationIssue("format", "must be markdown, latex or text")]
            ) from None
        project = _resolve_project(state)
        manuscript_id = manuscripts_service.add_manuscript(
            project, path, fmt=fmt, bib=bib, label=label, actor=project.human_actor()
        )
        found = resolve_service.resolve_citations(project, manuscript_id)
    typer.echo(f"added {manuscript_id}")
    typer.echo(_summary(found))


@manuscript_app.command("status")
def manuscript_status_cmd(
    ctx: typer.Context,
    manuscript: Annotated[
        str | None, typer.Argument(help="A manuscript id, msc_; all when left out.")
    ] = None,
) -> None:
    """The counts of one manuscript, or the manuscripts of the project."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        if manuscript is not None:
            lines = _status_lines(report_service.manuscript_status(project, manuscript))
        else:
            rows = manuscripts_service.list_manuscripts(project)
            lines = [f"{r.manuscript_id}  {r.sentences} sentences  {r.label}" for r in rows]
            lines = lines or ["no manuscripts; add one with `factory manuscript add`"]
    for line in lines:
        typer.echo(line)


@manuscript_app.command("resolve")
def manuscript_resolve_cmd(
    ctx: typer.Context,
    manuscript: Annotated[str, typer.Argument(help="A manuscript id, msc_.")],
    confirm: Annotated[
        str | None, typer.Option("--confirm", help="Confirm this proposed key.")
    ] = None,
    reject: Annotated[
        str | None, typer.Option("--reject", help="Reject this proposed key.")
    ] = None,
    clear: Annotated[
        str | None, typer.Option("--clear", help="Withdraw the decision on this key.")
    ] = None,
) -> None:
    """Resolve the citations again and list what waits for you, or decide one proposed key."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        given = [k for k in (confirm, reject, clear) if k is not None]
        if len(given) > 1:
            raise FactoryValidationError(
                [ValidationIssue("key", "give one of --confirm, --reject or --clear")]
            )
        project = _resolve_project(state)
        key = given[0] if given else None
        if key is not None:
            decision = (
                CitationDecision.CONFIRM
                if confirm is not None
                else CitationDecision.REJECT
                if reject is not None
                else CitationDecision.CLEAR
            )
            resolve_service.decide_citation(
                project, manuscript, key, decision, actor=project.human_actor()
            )
            typer.echo(f"{decision.value}: {key}")
            return
        found = resolve_service.resolve_citations(project, manuscript)
        typer.echo(_summary(found))
        for citation in manuscripts_service.citation_rows(project, manuscript).values():
            if citation.state is CitationState.PROPOSED:
                typer.echo(f"proposed {citation.key}: {citation.work_id} ({citation.score})")


@manuscript_app.command("report")
def manuscript_report_cmd(
    ctx: typer.Context,
    manuscript: Annotated[str, typer.Argument(help="A manuscript id, msc_.")],
    out: Annotated[
        Path | None, typer.Option("--out", help="Write here, not to stdout; not under the project.")
    ] = None,
) -> None:
    """The verdicts joined with the sentences, whose text is read from the library now."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        if out is not None:
            report_service.refuse_project_path(project, out)
        body = report_service.report_text(project, manuscript)
    if out is None:
        typer.echo(body, nl=False)
    else:
        out.write_text(body, encoding="utf-8")
        typer.echo(f"wrote {out}")


@manuscript_app.command("audit")
def manuscript_audit_cmd(
    ctx: typer.Context,
    manuscript: Annotated[str, typer.Argument(help="A manuscript id, msc_.")],
    draw: Annotated[bool, typer.Option("--draw", help="Draw a new sample first.")] = False,
    verdict: Annotated[
        str | None, typer.Option("--verdict", help="Label this sampled verdict, mvd_.")
    ] = None,
    correct: Annotated[
        bool | None, typer.Option("--correct/--incorrect", help="Your label of the verdict.")
    ] = None,
    note: Annotated[str | None, typer.Option("--note", help="At most 300 characters.")] = None,
) -> None:
    """The audit of the manuscript's supported verdicts: draw a sample, label a verdict, or read
    where it stands. A later label of a verdict replaces the earlier."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        if (verdict is None) != (correct is None):
            raise FactoryValidationError(
                [ValidationIssue("label", "give --verdict with --correct or --incorrect")]
            )
        project = _resolve_project(state)
        manuscripts_service.require_manuscript(project, manuscript)
        if draw:
            typer.echo(f"drew {audit_service.draw_audit(project, manuscript)}")
        if verdict is not None:
            label = AuditLabel.CORRECT if correct else AuditLabel.INCORRECT
            audit_service.record_audit(project, verdict, label, note, actor=project.human_actor())
            typer.echo(f"labelled {verdict} {label.value}")
        report = audit_service.audit_report(project, manuscript)
        sheet = audit_service.audit_sheet(project, manuscript)
    rate = "undefined" if report.rate is None else f"{report.rate:.3f}"
    typer.echo(f"audit: {report.labelled} of {report.drawn} labelled, rate {rate}")
    if report.above_ceiling:
        typer.echo("above the ceiling")
    if report.outdated:
        typer.echo("a verdict is newer than the last draw")
    for audit_id, verdict_id, ordinal, given in sheet:
        typer.echo(f"{audit_id}  {verdict_id}  sentence {ordinal}  {given or 'unlabelled'}")

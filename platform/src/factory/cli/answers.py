"""`factory answers`: answers of the papers chat in Ask mode (plan spar-night N2).

Business logic stays in `services/answers.py`. Agents record answers through the MCP tools; here
the researcher reads an answer with the full paragraph next to each quote and rates it (`rate`
writes one `chat.answer_rated` event as the human). The shared helpers of `factory.cli.main` are
imported inside the commands, because that module imports this one.
"""

from __future__ import annotations

from typing import Annotated

import typer

from factory.services import answers as answers_service

answers_app = typer.Typer(
    name="answers",
    help="Answers of the papers chat (Ask): list, show with paragraphs, and rate (human).",
    no_args_is_help=True,
)


@answers_app.command("list")
def answers_list_cmd(ctx: typer.Context) -> None:
    """Every answer with its sentence count."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        rows = answers_service.list_answers(project)
    typer.echo(f"{len(rows)} answer(s)")
    for a in rows:
        follow = f" (follows {a.parent})" if a.parent else ""
        typer.echo(f"{a.answer_id}{follow} [{a.sentences} sentence(s)]: {a.question}")


@answers_app.command("show")
def answers_show_cmd(
    ctx: typer.Context, answer: Annotated[str, typer.Argument(help="An ans_ id.")]
) -> None:
    """One answer: each sentence with its verified quote and the full paragraph, then the
    computed counts."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        view = answers_service.view_answer(project, answer)
    whole = f" [{view.rating}]" if view.rating else " [unrated]"
    typer.echo(f"{view.info.answer_id}{whole}: {view.info.question}")
    for s in view.sentences:
        rated = f" [{s.rating}]" if s.rating else " [unrated]"
        typer.echo(
            f"\n{s.index}. {s.text}{rated}\n  {s.work_id} [{s.anchor}] "
            f'quote: "{s.quote}"\n  paragraph: {s.paragraph}'
        )
    if view.unanswered:
        typer.echo(f"\nNot answered by the papers: {view.unanswered}")
    c = view.counts
    typer.echo(
        f"\ncounts: {c.sentences} sentence(s) from {c.works} work(s); ratings {c.ratings}; "
        f"unrated: {c.unrated}"
    )
    typer.echo(view.rating_label)


@answers_app.command("rate")
def answers_rate_cmd(
    ctx: typer.Context,
    answer: Annotated[str, typer.Argument(help="An ans_ id.")],
    rating: Annotated[str, typer.Argument(help="sound, weak or wrong.")],
    sentence: Annotated[
        int | None, typer.Option("--sentence", help="0-based sentence; omit for the whole answer.")
    ] = None,
    note: Annotated[str, typer.Option("--note", help="Why.")] = "",
) -> None:
    """Rate an answer or one sentence as the researcher; the latest rating stands."""
    from factory.cli.main import _reporting_errors, _resolve_project, _state

    state = _state(ctx)
    with _reporting_errors():
        project = _resolve_project(state)
        answers_service.rate_answer(
            project, project.human_actor(), answer, rating, note, sentence=sentence
        )
    where = "" if sentence is None else f" sentence {sentence}"
    typer.echo(f"{answer}{where} rated {rating}")

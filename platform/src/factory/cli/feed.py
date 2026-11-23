"""`factory feed` (slice 4c, F8, decision 118): configure, run, show, react, send and status.

It parses input, calls a service and formats its answer. Writes are authorised by the command's
`TOOL_PERMISSIONS` row through `factory.cli.main`. The helpers of `factory.cli.main` are imported
inside each command, because that module imports this one to register the group.

Validation failures print one `field: reason` line per issue on stderr and exit 2, as the other
commands do for invalid input. Nothing is written on those paths.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Annotated, NoReturn

import typer
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.model.feed import FeedNote, FeedReaction
from factory.services import factory_feed, feed_read
from factory.services import factory_feed_actions as actions
from factory.services import feed as feed_service
from factory.services.access import authorize_command
from factory.services.context import Project, list_projects, open_project
from factory.services.hint_input import HintInput
from factory.services.ranking_model import Specter2Embedder
from factory.sources.arxiv import ArxivSource
from factory.sources.http import default_http
from factory.sources.registry import default_sources

if TYPE_CHECKING:
    from factory.cli.main import CliState

feed_app = typer.Typer(
    name="feed",
    help="The discovery feed: configure, run, show, react, send and status.",
    no_args_is_help=True,
)

ProjectOpt = Annotated[str | None, typer.Option("--project", help="Project slug.")]
EntryArg = Annotated[str, typer.Argument(help="arXiv entry id, e.g. 2611.01234.")]
_TITLE_WIDTH = 60
_REACTIONS = ", ".join(r.value for r in FeedReaction)
ScopeOpt = Annotated[
    str, typer.Option("--scope", help="`project` (default) or `factory` (the general feed).")
]


def _exit_with_issues(issues: list[ValidationIssue]) -> NoReturn:
    for issue in issues:
        typer.echo(f"{issue.field}: {issue.reason}", err=True)
    raise typer.Exit(2)


@contextmanager
def _refusals() -> Iterator[None]:
    """Turn a service refusal into its issues on stderr and exit 2."""
    try:
        yield
    except FactoryValidationError as exc:
        _exit_with_issues(list(exc.issues))


def _open(ctx: typer.Context, slug: str | None) -> Project:
    """The project named by `--project` (or the root's), opened and authorised for this command."""
    from factory.cli import main

    state = main._state(ctx)
    target = state if slug is None else replace(state, project=slug)
    return main._resolve_project(target)


def _cut(text: str | None, width: int) -> str:
    if text is None or text == "":
        return "-"
    return text if len(text) <= width else text[: width - 1] + "…"


def _note(note: str | None) -> FeedNote | None:
    """The `--note` text validated as a feed note; an invalid one exits 2."""
    if note is None:
        return None
    try:
        value: FeedNote = TypeAdapter(FeedNote).validate_python(note)
    except PydanticValidationError as exc:
        _exit_with_issues([ValidationIssue("note", str(exc.errors()[0]["msg"]))])
    return value


def _categories(values: list[str]) -> tuple[str, ...]:
    """Repeated `--categories` values, each optionally comma-separated, in the order given."""
    names: list[str] = []
    for value in values:
        names.extend(part.strip() for part in value.split(",") if part.strip())
    return tuple(names)


@feed_app.command("configure")
def feed_configure_cmd(
    ctx: typer.Context,
    project: ProjectOpt = None,
    categories: Annotated[
        list[str] | None,
        typer.Option(
            "--categories",
            help="arXiv categories, e.g. cs.AI. Repeat the option or comma-separate them.",
        ),
    ] = None,
    references: Annotated[
        str,
        typer.Option(
            "--references",
            help="core-layer (default: the works of the core layer), core or core+included.",
        ),
    ] = "core-layer",
    shown: Annotated[int | None, typer.Option("--shown", help="Items shown per cycle.")] = None,
    explore: Annotated[
        float | None, typer.Option("--explore", help="Share of shown items drawn at random.")
    ] = None,
    interval: Annotated[
        int | None, typer.Option("--interval", help="Days between fetches.")
    ] = None,
    overlap: Annotated[
        int | None, typer.Option("--overlap", help="Days of overlap with the last window.")
    ] = None,
    drift_threshold: Annotated[
        float | None, typer.Option("--drift-threshold", help="Drift threshold, 0 to 1.")
    ] = None,
    drift_min: Annotated[
        int | None, typer.Option("--drift-min", help="Minimum count before drift is judged.")
    ] = None,
) -> None:
    """Record the feed configuration. Options not given take the model's defaults."""
    opened = _open(ctx, project)
    given: dict[str, object] = {"categories": _categories(categories or [])}
    optional: dict[str, object | None] = {
        "references": references,
        "shown_per_cycle": shown,
        "exploration_share": explore,
        "interval_days": interval,
        "overlap_days": overlap,
        "drift_threshold": drift_threshold,
        "drift_min_count": drift_min,
    }
    given.update({key: value for key, value in optional.items() if value is not None})
    with _refusals():
        event_id = feed_service.configure(opened, opened.human_actor(), given)
    typer.echo(f"feed configured for {opened.paths.slug} ({event_id})")


@feed_app.command("categories")
def feed_categories_cmd(ctx: typer.Context, project: ProjectOpt = None) -> None:
    """Propose the arXiv categories to follow, from the core layer (read-only; accepting is
    `feed configure --categories ...`, a human act)."""
    from factory.services import feed_categories

    opened = _open(ctx, project)
    with _refusals():
        proposal = feed_categories.propose_categories(opened)
    typer.echo(
        f"core works {proposal.core_works}, with an arXiv category {proposal.with_category}"
        f" (rule: cover {proposal.coverage:.0%}, {proposal.minimum} to {proposal.maximum})"
    )
    for share in proposal.shares[:8]:
        mark = "*" if share.category in proposal.categories else " "
        typer.echo(f" {mark} {share.category:<22} {share.works:>4}  {share.share:.0%}")
    if not proposal.categories:
        typer.echo("no proposal: no core-layer work has an arXiv category")
        return
    typer.echo(f"covered {proposal.covered:.0%}; to accept:")
    typer.echo("  factory feed configure --categories " + ",".join(proposal.categories))


@feed_app.command("run")
def feed_run_cmd(
    ctx: typer.Context,
    project: ProjectOpt = None,
    all_projects: Annotated[
        bool, typer.Option("--all", help="Every project; those without a feed are skipped.")
    ] = False,
    due: Annotated[
        bool, typer.Option("--due/--no-due", help="Run only what is due (default).")
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Fetch and rank nothing is written.")
    ] = False,
) -> None:
    """Run the feed cycle; exit 0 nothing new or complete, 1 partial or failed, 2 refused."""
    from factory.cli import main

    state = main._state(ctx)
    if all_projects and project is not None:
        _exit_with_issues([ValidationIssue("project", "--all and --project are exclusive")])
    slugs: list[str] | None = None
    refused = 0
    if all_projects:
        slugs, refused = _authorised_feed_projects(state)
    else:
        chosen = project if project is not None else state.project
        if chosen is None:
            _exit_with_issues([ValidationIssue("project", "give --project SLUG or --all")])
        _open(ctx, chosen)
        slugs = [chosen]
    source = ArxivSource(
        default_http(state.settings), clock=state.clock, mailto=state.settings.mailto
    )
    run = feed_service.feed_run_all(
        state.settings,
        embedder_factory=Specter2Embedder,
        source=source,
        session=state.session,
        clock=state.clock,
        slugs=slugs,
        due=due,
        dry_run=dry_run,
    )
    for outcome in run.outcomes:
        if outcome.error is not None:
            typer.echo(f"{outcome.slug}: {outcome.error}", err=True)
            continue
        result = outcome.result
        if result is None:
            continue
        detail = ""
        if result.window_from is not None and result.window_to is not None:
            detail = f" window {result.window_from}..{result.window_to}"
        counts = (
            f" fetched {result.fetched}, already known {result.already_known}, "
            f"held {result.held}, ranked {result.ranked}, shown {result.shown} "
            f"({result.explore} explore)"
        )
        note = "" if result.note is None else f" {result.note}"
        typer.echo(f"{outcome.slug}: {result.status}{detail}{counts}{note}")
    raise typer.Exit(max(run.exit_code, 1 if refused else 0))


def _authorised_feed_projects(state: CliState) -> tuple[list[str], int]:
    """Every configured project the running command is allowed on (as `watch run --all` checks
    each project), and how many were refused; a refusal is printed and the others still run."""
    allowed: list[str] = []
    refused = 0
    for slug in list_projects(state.settings):
        try:
            opened = open_project(state.settings, slug, session=state.session, clock=state.clock)
            authorize_command(opened, opened.principal, state.tool)
        except FactoryError as exc:
            typer.echo(f"{slug}: {exc}", err=True)
            refused += 1
            continue
        if feed_service.current_config(opened) is not None:
            allowed.append(slug)
    return allowed, refused


@feed_app.command("show")
def feed_show_cmd(
    ctx: typer.Context,
    project: ProjectOpt = None,
    top: Annotated[int | None, typer.Option("--top", help="Show at most N items.")] = None,
    ranking: Annotated[
        str | None, typer.Option("--ranking", help="A ranking id; default the latest.")
    ] = None,
) -> None:
    """The shown items of a ranking: rank, score, explore mark, entry, nearest core, reaction."""
    opened = _open(ctx, project)
    with _refusals():
        listing = feed_read.feed_list(opened, ranking_id=ranking, top=top)
    if listing.ranking_id is None:
        typer.echo(listing.reason or "no ranking yet")
        return
    reference = (listing.reference_hash or "")[:12]
    typer.echo(f"ranking {listing.ranking_id} (reference hash {reference})")
    header = (
        f"{'rank':>4}  {'score':>6}  {'x':1}  {'entry':<16}  {'title':<{_TITLE_WIDTH}}  "
        f"{'nearest core':<40}  {'reaction':<8}  sent"
    )
    typer.echo(header)
    for item in listing.items:
        typer.echo(
            f"{item.rank:>4}  {item.score:>6.3f}  {'*' if item.explore else ' ':1}  "
            f"{item.entry_id:<16}  {_cut(item.title, _TITLE_WIDTH):<{_TITLE_WIDTH}}  "
            f"{_cut(item.nearest_reference_title, 40):<40}  "
            f"{'-' if item.reaction is None else item.reaction.value:<8}  "
            f"{'yes' if item.sent else '-'}"
        )


@feed_app.command("react")
def feed_react_cmd(
    ctx: typer.Context,
    entry_id: EntryArg,
    reaction: Annotated[str, typer.Argument(help=f"One of: {_REACTIONS}.")],
    project: ProjectOpt = None,
    scope: ScopeOpt = "project",
) -> None:
    """Record a reaction to a shown entry. Human only. `--scope factory` reacts in the factory
    feed (the only scope that takes `unset` and `unsave`)."""
    try:
        parsed = FeedReaction(reaction)
    except ValueError:
        _exit_with_issues([ValidationIssue("reaction", f"must be one of {_REACTIONS}")])
    if scope not in ("project", "factory"):
        _exit_with_issues([ValidationIssue("scope", "must be project or factory")])
    if scope == "factory":
        if project is not None:
            _exit_with_issues([ValidationIssue("project", "--project and --scope factory differ")])
        from factory.cli import main

        state = main._state(ctx)
        with _refusals():
            event_id = actions.react(
                state.settings,
                entry_id=entry_id,
                reaction=parsed,
                session=state.session,
                clock=state.clock,
            )
        typer.echo(f"reacted {parsed.value} to {entry_id} in the factory feed ({event_id})")
        return
    opened = _open(ctx, project)
    with _refusals():
        event_id = feed_service.react(opened, opened.human_actor(), entry_id, parsed)
    typer.echo(f"reacted {parsed.value} to {entry_id} ({event_id})")


@feed_app.command("send")
def feed_send_cmd(
    ctx: typer.Context,
    entry_id: EntryArg,
    project: ProjectOpt = None,
    note: Annotated[str | None, typer.Option("--note", help="A note for the inbox item.")] = None,
    layer: Annotated[
        str | None, typer.Option("--layer", help="Hint: a layer of the current scheme.")
    ] = None,
    category: Annotated[
        str | None,
        typer.Option("--category", help="Hint: a taxonomy category, dimension/category."),
    ] = None,
    taxonomy: Annotated[
        str | None, typer.Option("--taxonomy", help="The taxonomy of --category, if ambiguous.")
    ] = None,
    miner_notes: Annotated[
        str | None, typer.Option("--miner-notes", help="Hint: a note addressed to the miners.")
    ] = None,
) -> None:
    """Send a shown entry to the inbox as its arXiv link. Human only."""
    note_value = _note(note)
    opened = _open(ctx, project)
    with _refusals():
        item_id = feed_service.send(
            opened,
            opened.human_actor(),
            entry_id,
            note=note_value,
            hints=HintInput(layer, category, taxonomy, miner_notes),
        )
    typer.echo(f"sent {entry_id} to the inbox as {item_id}")
    typer.echo("resolve it with `factory inbox resolve` once it is screened or dropped")


@feed_app.command("add")
def feed_add_cmd(
    ctx: typer.Context,
    entry_id: EntryArg,
    project: ProjectOpt = None,
    note: Annotated[str | None, typer.Option("--note", help="A note for the inbox item.")] = None,
    layer: Annotated[
        str | None, typer.Option("--layer", help="Hint: a layer of the current scheme.")
    ] = None,
    category: Annotated[
        str | None,
        typer.Option("--category", help="Hint: a taxonomy category, dimension/category."),
    ] = None,
    taxonomy: Annotated[
        str | None, typer.Option("--taxonomy", help="The taxonomy of --category, if ambiguous.")
    ] = None,
    miner_notes: Annotated[
        str | None, typer.Option("--miner-notes", help="Hint: a note addressed to the miners.")
    ] = None,
) -> None:
    """Send a shown entry to the inbox and look it up at once. Human only. The send stands even
    if the lookup fails or is refused; resolve it later with `factory inbox resolve`."""
    note_value = _note(note)
    opened = _open(ctx, project)
    with _refusals():
        result = feed_service.add(
            opened,
            opened.human_actor(),
            entry_id,
            sources=dict(default_sources()),
            note=note_value,
            hints=HintInput(layer, category, taxonomy, miner_notes),
        )
    typer.echo(f"sent {entry_id} to the inbox as {result.inbox_item_id}: {result.outcome}")
    if result.work_id is not None:
        typer.echo(f"work {result.work_id}")
    if result.reason is not None:
        typer.echo(result.reason, err=True)
        typer.echo("the send stands; retry with `factory inbox resolve`", err=True)


@feed_app.command("status")
def feed_status_cmd(ctx: typer.Context, project: ProjectOpt = None) -> None:
    """The configuration, the last complete fetch window, whether a run is due, and the counts."""
    opened = _open(ctx, project)
    status = feed_service.feed_status(opened)
    if not status.configured or status.config is None:
        typer.echo("feed not configured; run `factory feed configure`")
        return
    config = status.config
    typer.echo(f"categories: {', '.join(config.categories)}")
    typer.echo(f"references: {config.references.value}")
    typer.echo(
        f"shown per cycle: {config.shown_per_cycle}; exploration share: "
        f"{config.exploration_share}; interval {config.interval_days} day(s), "
        f"overlap {config.overlap_days} day(s)"
    )
    typer.echo(f"last complete window to: {status.last_complete_window_to or '-'}")
    typer.echo(f"next window from: {status.next_window_from or '-'}")
    typer.echo(f"due: {'yes' if status.due else 'no'}")
    typer.echo(f"last ranking: {status.last_ranking_id or '-'}")
    typer.echo(
        f"entries {status.entries} (held {status.held_entries}); fetches {status.fetches}; "
        f"rankings {status.rankings}; reactions {status.reactions}; sends {status.sends}"
    )


@feed_app.command("train")
def feed_train_cmd(ctx: typer.Context) -> None:
    """Train the factory feed's general ranker on the likes and dislikes now, then rank the pool.

    Never runs by itself. Needs at least 5 reactions, 3 of them likes, the `ranker` extra and the
    encoder weights. Human only."""
    from factory.cli import main

    state = main._state(ctx)
    with _refusals():
        result = actions.train(
            state.settings,
            Specter2Embedder(),
            session=state.session,
            clock=state.clock,
            command_ref=state.tool,
        )
    typer.echo(
        f"trained ranker v{result.version} on {result.likes} like(s) and {result.dislikes} "
        f"dislike(s) (training set {result.training_set_hash[:12]}, {result.skipped} outside the "
        f"pool, event {result.event_id}); ranking {result.ranking_id or '-'}"
    )


@feed_app.command("today")
def feed_today_cmd(
    ctx: typer.Context,
    page: Annotated[
        int, typer.Option("--page", min=1, help=f"Page of {factory_feed.DEFAULT_SHOWN}.")
    ] = 1,
    sort: Annotated[str, typer.Option("--sort", help="`ranked` (default) or `newest`.")] = "ranked",
) -> None:
    """The factory feed's Today list, from the newest factory ranking. Read-only."""
    from factory.cli import main

    if sort not in ("ranked", "newest"):
        _exit_with_issues([ValidationIssue("sort", "must be ranked or newest")])
    state = main._state(ctx)
    result = factory_feed.today(
        state.settings,
        page=page,
        sort="newest" if sort == "newest" else "ranked",
        clock=state.clock,
    )
    if result.ranking_id is None:
        typer.echo("no factory ranking yet; run `factory feed run`")
        return
    typer.echo(f"ranking {result.ranking_id}; page {result.page}/{result.pages} ({result.total})")
    typer.echo(f"{'rank':>4}  {'pred':>5}  {'entry':<11}  {'date':<10}  {'mark':<4}  title")
    for card in result.cards:
        predicted = "-" if card.score is None else f"{card.score:.0%}"
        mark = (
            {"like": "+", "dislike": "-"}.get(card.label or "", " ")
            + ("s" if card.saved else " ")
            + ("x" if card.explore else " ")
        )
        typer.echo(
            f"{card.rank or 0:>4}  {predicted:>5}  {card.entry_id:<11}  "
            f"{(card.submitted or '-')[:10]:<10}  {mark:<4}  {_cut(card.title, _TITLE_WIDTH)}"
        )

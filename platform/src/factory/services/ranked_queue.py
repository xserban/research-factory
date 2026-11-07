"""Ranked serving and the stopping rule of title/abstract screening (slice 8, IDEA-42).

A ranking only orders the queue; it removes nothing. This module holds the pure parts.

Ranked order. A work's key is `(position in the latest ranking, work id)`; a work the ranking does
not cover sorts after every ranked work, by work id. Without a ranking every key is
`(infinity, work id)`, which is the order screening always had.

Stopping rule (`ScreeningPlan.stop_after_consecutive_excludes`, N). The sequence is the works of the
latest ranking that the pass-A queue holds (the title/abstract population less the calibration
works, which never count), in ranked order. Walk it from the top. A work with a live, current pass-A
screening decision extends the walk: an `exclude` adds one to the run, any other verdict resets it
to zero. The walk ends at the first work without such a decision (the frontier) or at the end of the
sequence. Serving has stopped exactly when the walk ended at a frontier, so the ranking still has
unscreened works, and the run is at least N. A frontier at the end of the ranking is no stop:
records the ranking does not cover are served in the existing order. The state is recomputed from
the decisions, so a corrected decision that breaks the run lifts the stop.

Score rule (`ScreeningPlan.stop_below_score` S with `stop_score_run` N). The same walk, over the
same sequence and with the same frontier, but the run counts the trailing decisions whose relevance
score is present and below S; a decision without a score, or with a score of S or more, resets it.
Serving has stopped when the walk ended at a frontier with a run of at least N. The two rules
share the frontier, so they withhold the same works; whichever holds first stops serving, and
`StopStatus.rule` names it (the excludes rule when both hold).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from pydantic import Field
from sqlalchemy import text

from factory.model.base import StrictModel
from factory.model.screening import Verdict
from factory.services.context import Project

RULE = "stop_after_consecutive_excludes"
SCORE_RULE = "stop_below_score"

_UNRANKED = 1 << 62


class StopStatus(StrictModel):
    """The stopping rule of pass A, evaluated. `stopped` says whether serving has stopped;
    `not_screened` counts the ranked works that will not be screened because of it (those with no
    pass-A decision and no batch already served); both are computed from the events."""

    rule: str = RULE
    n: int = Field(ge=1)
    below_score: int | None = Field(default=None, ge=1, le=10)
    """The score threshold of the score rule; None for the excludes rule."""
    run: int = Field(ge=0)
    stopped: bool
    not_screened: int = Field(ge=0)


class StopWalk(StrictModel):
    """The walk over the ranked sequence: the run at its end and the works from the frontier on."""

    run: int = Field(ge=0)
    rest: list[str]


def stop_rule_text(n: int) -> str:
    """The rule in words, as the PRISMA flow and the methods statement state it."""
    return (
        f"title/abstract screening stops after {n} consecutive exclusions in ranked order "
        "(a rapid-review shortcut; ranked records not screened are reported as such)"
    )


def score_rule_text(below: int, n: int) -> str:
    """The score rule in words."""
    return (
        f"title/abstract screening stops when the last {n} scored decisions in ranked order are "
        f"all below a relevance score of {below} (a rapid-review shortcut; ranked records not "
        "screened are reported as such)"
    )


def stop_rules_text(statuses: Sequence[StopStatus]) -> str:
    """Every declared rule in words, joined; the PRISMA flow and the methods statement state it."""
    return "; ".join(
        stop_rule_text(s.n) if s.below_score is None else score_rule_text(s.below_score, s.n)
        for s in statuses
    )


def ranking_positions(project: Project) -> dict[str, int]:
    """Rank position (from 1) of each work of the latest ranking; empty before any."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT work_id, position FROM ranking_positions")).all()
    return {str(work): int(position) for work, position in rows}


def rank_key(positions: Mapping[str, int]) -> Callable[[str], tuple[int, str]]:
    """The sort key of ranked serving; with no positions it orders by work id."""

    def key(work_id: str) -> tuple[int, str]:
        return positions.get(work_id, _UNRANKED), work_id

    return key


def ranked_sequence(positions: Mapping[str, int], queue: set[str]) -> list[str]:
    """The works of the queue that the ranking covers, in ranked order."""
    return sorted((w for w in queue if w in positions), key=rank_key(positions))


def walk(sequence: Sequence[str], verdicts: Mapping[str, Verdict]) -> StopWalk:
    """Walk `sequence` while each work has a verdict; see the module docstring."""
    run = 0
    for i, work_id in enumerate(sequence):
        verdict = verdicts.get(work_id)
        if verdict is None:
            return StopWalk(run=run, rest=list(sequence[i:]))
        run = run + 1 if verdict is Verdict.EXCLUDE else 0
    return StopWalk(run=run, rest=[])


def unreached(
    sequence: Sequence[str], verdicts: Mapping[str, Verdict], served: set[str]
) -> set[str]:
    """The works of the sequence with no verdict and no served batch: nothing has been shown yet."""
    return {w for w in sequence if w not in verdicts and w not in served}


def stop_status(
    sequence: Sequence[str],
    verdicts: Mapping[str, Verdict],
    served: set[str],
    n: int,
) -> StopStatus:
    """The stopping rule over a ranked sequence: stopped when the walk ends at a frontier with a
    run of at least `n`. The works then not screened are those from the frontier on that have no
    verdict and no served batch."""
    result = walk(sequence, verdicts)
    stopped = bool(result.rest) and result.run >= n
    count = len(unreached(result.rest, verdicts, served)) if stopped else 0
    return StopStatus(n=n, run=result.run, stopped=stopped, not_screened=count)


def score_status(
    sequence: Sequence[str],
    scores: Mapping[str, int | None],
    served: set[str],
    below: int,
    n: int,
) -> StopStatus:
    """The score rule over a ranked sequence: `scores` holds the live pass-A decision of each
    decided work (None when it gave no score). The run counts the trailing decisions before the
    frontier that are scored and below `below`; stopped when the walk ends at a frontier with a
    run of at least `n`. Works not screened are those from the frontier on with no decision and no
    served batch."""
    run = 0
    frontier: int | None = None
    for i, work_id in enumerate(sequence):
        if work_id not in scores:
            frontier = i
            break
        score = scores[work_id]
        run = run + 1 if score is not None and score < below else 0
    rest = [] if frontier is None else list(sequence[frontier:])
    stopped = bool(rest) and run >= n
    count = len([w for w in rest if w not in scores and w not in served]) if stopped else 0
    return StopStatus(
        rule=SCORE_RULE, n=n, below_score=below, run=run, stopped=stopped, not_screened=count
    )

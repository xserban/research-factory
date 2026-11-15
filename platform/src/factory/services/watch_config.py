"""Save the weekly watch settings as a protocol amendment (plan updates-page, T1).

Invariants: human actors only; every named source is an included source of the current protocol;
the plan is windowed (`window` mode, `full_replay_every` None: a full
replay only on the researcher's request) and closes a week after each cycle
(`snapshot_every` 1); any other field of an existing plan (notices, budgets) is kept. A refusal,
including an unchanged plan, writes nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.watch import WatchPlan, WatchSource
from factory.services import protocol as protocol_service
from factory.services.context import Project

OVERLAP_DAYS = 7


def configure_watch(
    project: Project,
    actor: Actor,
    *,
    sources: Sequence[str],
    interval_days: int,
    until: date | None,
    reason: str,
) -> str:
    """Amend the protocol so its watch plan runs `sources` every `interval_days` days in window
    mode, and return the new protocol id. Refused (nothing written) for a non-human actor, no
    protocol, no sources, a source that is not included, an interval below 1, an `until` in the
    past, or a plan equal to the current one (`watch_plan: unchanged`)."""
    issues: list[ValidationIssue] = []
    if actor.kind != "human":
        raise FactoryValidationError(
            [ValidationIssue("actor", "only a human saves watch settings")]
        )
    current = protocol_service.current_protocol(project)
    if current is None:
        raise FactoryValidationError([ValidationIssue("protocol", "no protocol is recorded")])
    names = list(dict.fromkeys(sources))
    included = {s.name for s in current.spec.sources if s.included}
    if not names:
        issues.append(ValidationIssue("sources", "must name at least one source"))
    for name in names:
        if name not in included:
            issues.append(ValidationIssue("sources", f"{name!r} is not an included source"))
    if isinstance(interval_days, bool) or interval_days < 1:
        issues.append(ValidationIssue("interval_days", "must be at least 1"))
    if until is not None and until < date.today():
        issues.append(ValidationIssue("until", "must not be in the past"))
    if issues:
        raise FactoryValidationError(issues)
    old = current.spec.watch_plan
    kept = {} if old is None else old.model_dump(exclude={"sources", "snapshot_every", "until"})
    plan = WatchPlan.model_validate(
        {
            **kept,
            "sources": tuple(
                WatchSource(
                    source=name,
                    interval_days=interval_days,
                    mode="window",
                    overlap_days=OVERLAP_DAYS,
                    full_replay_every=None,
                )
                for name in names
            ),
            "snapshot_every": 1,
            "until": until,
        }
    )
    if plan == old:
        raise FactoryValidationError([ValidationIssue("watch_plan", "unchanged")])
    result = protocol_service.amend_protocol(
        project,
        actor,
        current.spec.model_copy(update={"watch_plan": plan}),
        reason=reason,
        semantic=True,
        effects={},
    )
    return result.to_version

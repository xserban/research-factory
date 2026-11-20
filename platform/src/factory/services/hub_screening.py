"""Deterministic analytics for the hub's Flow page, Screening tab (plan hub-ui, step 4).

Pure functions over plain rows (`Dec`) plus thin read-only loaders. Nothing here calls a model or
writes. Only live (not superseded) decisions are read. The statistics reuse the platform's own:
`cohen_kappa` and `kappa_by_criterion` (quality.stats, as the agreement report uses them), the
ranking order and the stop walk of `ranked_queue`, and the stop rules `screening_stops` evaluates.
`METHODS` holds the plain-English definitions shown to the researcher.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from factory.model.protocol import Criterion, ScreeningStage
from factory.model.screening import DecisionRecorded, PassLabel, ScreeningPhase, Verdict
from factory.services.agreement import cannot_assess_queue
from factory.services.calibration import calibration_items, stage_population
from factory.services.context import Project
from factory.services.hub_tab_help import TAB_HELP
from factory.services.prisma import prisma_flow
from factory.services.project import screening_status
from factory.services.protocol import current_protocol, list_deviations
from factory.services.ranked_queue import (
    rank_key,
    ranked_sequence,
    ranking_positions,
    stop_rules_text,
    walk,
)
from factory.services.ranking import latest_ranking
from factory.services.screening import (
    live_decisions,
    screening_stops,
    stale_screening_decisions,
)
from factory.services.screening_check import check_list, check_report
from factory.services.screening_stats import cohen_kappa, kappa_by_criterion

METHODS: dict[str, str] = {
    "tab_screening": TAB_HELP["screening"],
    "ranked_curve": (
        "Title/abstract screening by pass A, screening phase (calibration never counts). Records "
        "are placed in the order of the latest ranking (rank position 1 first), because "
        "screening serves the best-ranked records first; records the ranking does not cover "
        "follow in the order they were decided (event order). When no ranking exists the whole "
        "curve is in decision (event) order and the mode says so. The curve is the running count "
        "of include verdicts against records screened, so it never falls and ends at the total "
        "included. The stop point is the number of records screened when the declared stop rule "
        "stopped serving (the first ranked record without a decision); it is absent while no rule "
        "has stopped. The shares are the part of all inclusions found within the first 10, 25 and "
        "50 percent of the records the screening covers (rounded up to whole records). Decisions "
        "the platform marks stale (made under an earlier protocol version) are left out of the "
        "curve and of the stop walk alike, so the two agree."
    ),
    "two_screeners": (
        "For each stage and phase, the works with a live decision from both pass A and pass B. "
        "Agreement is the share of those works where both passes reach the same outcome; an "
        "include or cannot-assess verdict proceeds and any other verdict does not, as in the "
        "platform's agreement report. Cohen's kappa is computed from the 2x2 table of those "
        "outcomes (table: both proceed, only A proceeds, only B proceeds, neither), and is empty "
        "when chance agreement is complete. Per criterion, the kappa is over the event 'this "
        "pass excluded the work citing that criterion', across all compared works; the platform "
        "computes it the same way. Among works both passes excluded, the share citing the same "
        "criterion is also given. A disagreement is a work where the outcomes differ or one pass "
        "is unsure. Calibration-phase pairs are reported on their own."
    ),
    "reasons_wall": (
        "For each exclusion criterion, the number of distinct works with a live exclude verdict "
        "citing it (screening phase, either pass) at each stage. Up to k example rationales and "
        "quotes are shown, taken from the works with the smallest work ids; pass A's decision is "
        "used when both passes excluded a work. Excluded works citing no criterion are grouped "
        "as unspecified. The label and rule are those of the current protocol, when it has them."
    ),
    "ranking": (
        "The latest ranking recorded: its id, the model that scored the records, the hash of the "
        "weights and the number of records ranked. Read from the ranking event; nothing is "
        "recomputed."
    ),
    "passes": (
        "Each screening pass's ordinary queue: records queued, records with a live decision that "
        "is not stale, and records remaining. Calibration records are counted by the calibration "
        "gate, not here. Stale decisions were made under an earlier protocol version."
    ),
    "stops": (
        "Each declared stop rule evaluated on the events: its threshold, how many consecutive "
        "low-scored records the run reached, whether it has stopped serving records, and how many "
        "ranked records will not be screened because of it."
    ),
    "calibration": (
        "The calibration draw: records drawn, records labelled by the researcher, whether the "
        "protocol requires it, and whether each pass passed."
    ),
    "checks": (
        "Calibration and audit draws against the researcher's labels. Per band of the pass's own "
        "score: records drawn, labelled, compared with the pass's verdict, agreed, the agreement, "
        "and what the labels would add. A draw is outdated when the protocol has changed since."
    ),
    "cannot_assess": (
        "Full-text works where a pass could not assess the document and the researcher has not "
        "yet resolved it. Such a work stays promoted until resolved; the list blocks nothing."
    ),
    "criteria": (
        "Per exclusion criterion: the works excluded at title and abstract and at full text, with "
        "how many of them are kept as background (an exclusion whose works are not simply "
        "dropped). Counts come from the PRISMA flow; the statements are those of the current "
        "protocol."
    ),
}

SHARE_POINTS = (10, 25, 50)
EXAMPLES = 3
UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class Dec:
    """One live decision, flattened. `order` is the recording order; `criterion` is bare."""

    decision_id: str
    work_id: str
    pass_label: str
    phase: str
    stage: str
    verdict: str
    criterion: str | None
    quote: str
    rationale: str
    order: int

    @property
    def promotes(self) -> bool:
        return Verdict(self.verdict).promotes


def _bare(criterion: str | None) -> str | None:
    return None if criterion is None else criterion.rsplit(":", 1)[-1]


def to_dec(record: DecisionRecorded, order: int) -> Dec:
    """Flatten a decision record; the criterion loses its protocol prefix."""
    return Dec(
        decision_id=record.decision_id,
        work_id=record.work_id,
        pass_label=record.pass_label.value,
        phase=record.phase.value,
        stage=record.stage.value,
        verdict=record.verdict.value,
        criterion=_bare(record.criterion),
        quote=record.quote,
        rationale=record.rationale,
        order=order,
    )


# --- 1. ranked curve ------------------------------------------------------------------------


@dataclass(frozen=True)
class RankedCurve:
    """`points[i]` is the include count after record i+1; `stop_at` the records screened when a
    stop rule stopped serving (None while none has)."""

    mode: str
    screened: int
    total_records: int
    included_total: int
    points: tuple[int, ...]
    stop_at: int | None
    stop_rule: str | None
    shares: dict[str, float | None]


def screened_prefix(sequence: Sequence[str], verdicts: Mapping[str, Verdict]) -> int:
    """Records of the ranked sequence screened before the first one without a verdict: the point
    at which the platform's stop walk ends."""
    return len(sequence) - len(walk(sequence, verdicts).rest)


def ranked_curve(
    order: Sequence[str],
    included: Collection[str],
    *,
    mode: str = "ranked",
    total_records: int | None = None,
    stop_at: int | None = None,
    stop_rule: str | None = None,
) -> RankedCurve:
    """The cumulative inclusions over `order` (the works screened, in the order given).

    `included` holds the works with an include verdict; `total_records` the records the screening
    covers (at least `len(order)`), the base of the shares."""
    running = 0
    points: list[int] = []
    for work in order:
        running += 1 if work in included else 0
        points.append(running)
    total = max(total_records or 0, len(order))
    shares: dict[str, float | None] = {}
    for pct in SHARE_POINTS:
        k = min(math.ceil(total * pct / 100), len(points))
        found = points[k - 1] if k > 0 else 0
        shares[str(pct)] = found / running if running else None
    return RankedCurve(
        mode=mode,
        screened=len(order),
        total_records=total,
        included_total=running,
        points=tuple(points),
        stop_at=stop_at,
        stop_rule=stop_rule,
        shares=shares,
    )


def order_screened(
    decisions: Sequence[Dec], positions: Mapping[str, int] | None
) -> tuple[list[str], str]:
    """Works with a decision in the order screened and the mode: ranked works by rank position,
    then the rest in decision order; with no ranking, decision order alone."""
    by_work: dict[str, int] = {}
    for d in sorted(decisions, key=lambda x: x.order):
        by_work.setdefault(d.work_id, d.order)
    if not positions:
        return sorted(by_work, key=lambda w: by_work[w]), "decision-order"
    ranked = sorted((w for w in by_work if w in positions), key=rank_key(positions))
    rest = sorted((w for w in by_work if w not in positions), key=lambda w: by_work[w])
    return ranked + rest, "ranked"


# --- 2. two screeners -----------------------------------------------------------------------


@dataclass(frozen=True)
class PairDisagreement:
    work_id: str
    reason: str
    a_verdict: str
    b_verdict: str
    a_criterion: str | None
    b_criterion: str | None
    a_rationale: str
    b_rationale: str
    a_quote: str
    b_quote: str


@dataclass(frozen=True)
class PairAgreement:
    stage: str
    phase: str
    n: int
    agree: int
    agreement: float | None
    kappa: float | None
    table: dict[str, int]
    table_works: dict[str, tuple[str, ...]]
    kappa_by_criterion: dict[str, float | None]
    both_excluded: int
    same_criterion: int
    disagreements: tuple[PairDisagreement, ...]


def _reason(a: Dec, b: Dec) -> str | None:
    if Verdict.UNSURE.value in (a.verdict, b.verdict):
        return "unsure"
    return "outcome" if a.promotes != b.promotes else None


def two_screeners(
    decisions: Iterable[Dec], criteria: Sequence[str] = ()
) -> tuple[PairAgreement, ...]:
    """Agreement of pass A and pass B per (stage, phase), over works both decided. Groups with no
    pair are left out. `criteria` adds criterion ids to those cited in the decisions."""
    groups: dict[tuple[str, str], dict[str, dict[str, Dec]]] = {}
    for d in sorted(decisions, key=lambda x: x.order):
        slot = groups.setdefault((d.stage, d.phase), {"A": {}, "B": {}})
        slot[d.pass_label][d.work_id] = d  # a later decision of the same pass wins
    result: list[PairAgreement] = []
    for (stage, phase), passes in sorted(groups.items()):
        works = sorted(set(passes["A"]) & set(passes["B"]))
        if not works:
            continue
        pairs = [(passes["A"][w], passes["B"][w]) for w in works]
        outcomes = [(a.promotes, b.promotes) for a, b in pairs]
        agree = sum(1 for x, y in outcomes if x == y)
        crit_pairs = [
            (
                a.criterion if a.verdict == Verdict.EXCLUDE.value else None,
                b.criterion if b.verdict == Verdict.EXCLUDE.value else None,
            )
            for a, b in pairs
        ]
        cited = {c for pair in crit_pairs for c in pair if c is not None}
        both_excluded = [
            (a, b) for a, b in pairs if a.verdict == b.verdict == Verdict.EXCLUDE.value
        ]
        table = {
            "both_proceed": sum(1 for x, y in outcomes if x and y),
            "only_a_proceeds": sum(1 for x, y in outcomes if x and not y),
            "only_b_proceeds": sum(1 for x, y in outcomes if y and not x),
            "neither_proceeds": sum(1 for x, y in outcomes if not x and not y),
        }
        table_works = {
            "both_proceed": tuple(a.work_id for a, b in pairs if a.promotes and b.promotes),
            "only_a_proceeds": tuple(a.work_id for a, b in pairs if a.promotes and not b.promotes),
            "only_b_proceeds": tuple(a.work_id for a, b in pairs if b.promotes and not a.promotes),
            "neither_proceeds": tuple(
                a.work_id for a, b in pairs if not a.promotes and not b.promotes
            ),
        }
        disagreements = tuple(
            PairDisagreement(
                work_id=a.work_id,
                reason=reason,
                a_verdict=a.verdict,
                b_verdict=b.verdict,
                a_criterion=a.criterion,
                b_criterion=b.criterion,
                a_rationale=a.rationale,
                b_rationale=b.rationale,
                a_quote=a.quote,
                b_quote=b.quote,
            )
            for a, b in pairs
            if (reason := _reason(a, b)) is not None
        )
        result.append(
            PairAgreement(
                stage=stage,
                phase=phase,
                n=len(pairs),
                agree=agree,
                agreement=agree / len(pairs),
                kappa=cohen_kappa(outcomes),
                table=table,
                table_works=table_works,
                kappa_by_criterion=kappa_by_criterion(crit_pairs, sorted(cited | set(criteria))),
                both_excluded=len(both_excluded),
                same_criterion=sum(1 for a, b in both_excluded if a.criterion == b.criterion),
                disagreements=disagreements,
            )
        )
    return tuple(result)


# --- 3. reasons wall ------------------------------------------------------------------------


@dataclass(frozen=True)
class ReasonExample:
    work_id: str
    pass_label: str
    rationale: str
    quote: str


@dataclass(frozen=True)
class ReasonGroup:
    stage: str
    criterion: str
    label: str | None
    rule: str | None
    count: int
    works: tuple[str, ...]
    examples: tuple[ReasonExample, ...]


def reasons_wall(
    decisions: Iterable[Dec],
    criteria: Mapping[str, Criterion] | None = None,
    *,
    k: int = EXAMPLES,
) -> tuple[ReasonGroup, ...]:
    """Per stage and exclusion criterion: distinct works excluded and up to `k` examples by work
    id. Screening phase only (calibration items are not exclusions of the corpus)."""
    criteria = criteria or {}
    best: dict[tuple[str, str, str], Dec] = {}
    for d in sorted(decisions, key=lambda x: (x.pass_label, x.order)):
        if d.phase != ScreeningPhase.SCREENING.value or d.verdict != Verdict.EXCLUDE.value:
            continue
        best.setdefault((d.stage, d.criterion or UNSPECIFIED, d.work_id), d)
    grouped: dict[tuple[str, str], list[Dec]] = {}
    for (stage, crit, _), d in best.items():
        grouped.setdefault((stage, crit), []).append(d)
    out: list[ReasonGroup] = []
    for (stage, crit), items in sorted(
        grouped.items(), key=lambda kv: (kv[0][0], -len(kv[1]), kv[0][1])
    ):
        items.sort(key=lambda x: x.work_id)
        spec = criteria.get(crit)
        out.append(
            ReasonGroup(
                stage=stage,
                criterion=crit,
                label=None if spec is None else spec.statement,
                rule=None if spec is None else spec.rule,
                count=len(items),
                works=tuple(x.work_id for x in items),
                examples=tuple(
                    ReasonExample(x.work_id, x.pass_label, x.rationale, x.quote)
                    for x in items[: max(k, 0)]
                ),
            )
        )
    return tuple(out)


# --- loaders and payload --------------------------------------------------------------------


def load_decisions(project: Project) -> list[Dec]:
    """Every live decision of every stage, in recording order (read-only)."""
    return [to_dec(r, i) for i, r in enumerate(live_decisions(project, stage=None))]


def load_curve(project: Project, decisions: Sequence[Dec]) -> RankedCurve:
    """The ranked curve of pass A at title/abstract, with the platform's stop point."""
    ta = ScreeningStage.TITLE_ABSTRACT
    stale = stale_screening_decisions(project, stage=ta)
    mine = [
        d
        for d in decisions
        if d.pass_label == PassLabel.A.value
        and d.phase == ScreeningPhase.SCREENING.value
        and d.stage == ta.value
        and d.decision_id not in stale
    ]
    positions = ranking_positions(project)
    order, mode = order_screened(mine, positions)
    included = {d.work_id for d in mine if d.verdict == Verdict.INCLUDE.value}
    queue = stage_population(project, ta) - set(calibration_items(project, stage=ta))
    stop_at: int | None = None
    stop_rule: str | None = None
    stopped = [s for s in screening_stops(project, ta) if s.stopped]
    if stopped and positions:
        verdicts = {d.work_id: Verdict(d.verdict) for d in mine}
        stop_at = screened_prefix(ranked_sequence(positions, queue), verdicts)
        stop_rule = stop_rules_text(stopped)
    return ranked_curve(
        order,
        included,
        mode=mode,
        total_records=len(queue | {d.work_id for d in mine}),
        stop_at=stop_at,
        stop_rule=stop_rule,
    )


def criteria_table(project: Project) -> list[dict[str, Any]]:
    """The exclusion criteria with their counts at each stage and those kept as background.

    Rows are the protocol's exclusion criteria plus any criterion the flow counts that the
    protocol no longer has; the counts are `prisma_flow`'s (`excluded`, `background`, and the
    same at full text)."""
    flow = prisma_flow(project)
    ft = flow.full_text
    protocol = current_protocol(project)
    spec = {c.id: c for c in protocol.spec.criteria} if protocol is not None else {}
    ids = sorted(
        {c for c, x in spec.items() if x.id.startswith("EX")}
        | set(flow.excluded)
        | set(ft.excluded)
    )
    return [
        {
            "id": c,
            "statement": spec[c].statement if c in spec else None,
            "ta_excluded": flow.excluded.get(c, 0),
            "ta_background": flow.background.get(c, 0),
            "ft_excluded": ft.excluded.get(c, 0),
            "ft_background": ft.background.get(c, 0),
        }
        for c in ids
    ]


def screening_panel(project: Project) -> dict[str, Any]:
    """The Screening tab's tables, read from the services the old dashboard read: the latest
    ranking, pass progress at both stages, stop rules, calibration, stale decisions, check draws,
    the full-text cannot-assess works and the deviation count. Nothing is recomputed here."""
    status = screening_status(project)
    ranking = latest_ranking(project, top=0)
    checks: list[dict[str, Any]] = []
    for summary in check_list(project):
        report = check_report(project, summary.draw_id, kind=summary.kind)
        checks.append(
            {
                "draw_id": summary.draw_id,
                "kind": summary.kind.value,
                "name": summary.name,
                "drawn": summary.drawn,
                "labelled": summary.labelled,
                "current": summary.current,
                "agreement": None if report is None else report.agreement,
                "agreement_note": None if report is None else report.agreement_note,
                "bands": [] if report is None else [r.model_dump(mode="json") for r in report.rows],
                "disagreements": 0 if report is None else len(report.disagreements),
            }
        )
    protocol = current_protocol(project)
    cannot = (
        []
        if protocol is None or protocol.spec.full_text_screening is None
        else [
            i.model_dump(mode="json")
            for i in cannot_assess_queue(project, stage=ScreeningStage.FULL_TEXT)
        ]
    )
    pass_a = status.passes.get(PassLabel.A.value)
    return {
        "ranking": None
        if ranking is None
        else {
            "ranking_id": ranking.ranking_id,
            "model_id": ranking.model_id,
            "weights_hash": ranking.weights_hash,
            "software": ranking.software,
            "count": ranking.count,
        },
        "passes": {k: v.model_dump(mode="json") for k, v in status.passes.items()},
        "full_text_passes": None
        if status.full_text_passes is None
        else {k: v.model_dump(mode="json") for k, v in status.full_text_passes.items()},
        "records_left": None if pass_a is None else pass_a.remaining,
        "stale_decisions": status.stale_decisions,
        "stops": [s.model_dump(mode="json") for s in screening_stops(project)],
        "calibration": {
            "drawn": status.calibration.drawn,
            "labelled": status.calibration.labelled,
            "required": status.calibration.required,
            "passed": dict(status.calibration.passed),
        },
        "checks": checks,
        "cannot_assess": cannot,
        "deviations": len(list_deviations(project)),
        "criteria": criteria_table(project),
    }


def screening_payload(project: Project) -> dict[str, Any]:
    """The Screening tab's data, JSON-safe."""
    decisions = load_decisions(project)
    protocol = current_protocol(project)
    criteria = {c.id: c for c in protocol.spec.criteria} if protocol is not None else {}
    exclusion_ids = sorted(c for c in criteria if c.startswith("EX"))
    return {
        "methods": METHODS,
        "ranked_curve": asdict(load_curve(project, decisions)),
        "two_screeners": [asdict(p) for p in two_screeners(decisions, exclusion_ids)],
        "reasons_wall": [asdict(g) for g in reasons_wall(decisions, criteria)],
        "panel": screening_panel(project),
    }

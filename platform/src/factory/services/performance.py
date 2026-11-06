"""The performance record: measured figures per role, model and skill version (IDEA-10, plan SV).

Invariants:
- A row is keyed by (role, model, skill) for an agent and (role, person) for a human pass. A change
  of model or skill version starts a new row; two versions are never blended (PD-8 item 1).
- Every figure comes from calibration labels, the agreement of the passes or audit labels, read
  from the index. Nothing is written and nothing is typed in (R-05).
- A figure whose sample is below `SAMPLE_FLOOR` labelled items is `None`; its `n` is reported
  beside it, so a small sample is never shown as a rate.
- Label-derived rates stay off agent surfaces (decision 43): only the CLI calls this module.

The role is the screening pass: `screening:<stage>:<pass label>`. The audit error rate of a row is
the share of its audited exclusions that the human included (a false exclusion).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from itertools import combinations

from sqlalchemy import text

from factory.model.base import StrictModel
from factory.model.screening import ScreeningPhase, Verdict
from factory.quality.stats import cohen_kappa, sensitivity_specificity
from factory.services.context import Project

SAMPLE_FLOOR = 10
"""Labelled items a figure needs before it is shown as a rate."""

_Key = tuple[str, str | None, str | None, str | None]


class PerfRow(StrictModel):
    role: str
    model: str | None
    skill: str | None
    person: str | None
    tasks: int
    sensitivity: float | None
    specificity: float | None
    n_calibration: int
    kappa_with: dict[str, float | None]
    n_pairs: dict[str, int]
    audit_error_rate: float | None
    n_audit: int
    n_labels: int
    first: str
    last: str


class PerformanceReport(StrictModel):
    sample_floor: int
    rows: list[PerfRow]


def row_label(role: str, model: str | None, skill: str | None, person: str | None) -> str:
    who = person if person is not None else f"{model}@{skill}"
    return f"{role} {who}"


def _above(n: int, value: float | None) -> float | None:
    return value if n >= SAMPLE_FLOOR else None


def _sort_key(key: _Key) -> tuple[str, str, str, str]:
    return (key[0], key[1] or "", key[2] or "", key[3] or "")


def performance(project: Project) -> PerformanceReport:
    """One row per (role, model, skill) or (role, person), sorted by role, then model, skill and
    person. Empty when nothing was decided."""
    project.index.sync()
    with project.index.connect() as conn:
        decisions = conn.execute(
            text(
                "SELECT d.work_id, d.pass_label, d.stage, d.phase, d.verdict, d.task_id,"
                " e.model, e.skill, e.actor_kind, e.user, e.ts FROM decisions d"
                " JOIN events e ON e.id = d.event_id WHERE d.superseded_by IS NULL"
            )
        ).all()
        labels = {
            (str(s), str(w)): str(v)
            for s, w, v in conn.execute(
                text("SELECT stage, work_id, verdict FROM calibration_labels")
            ).all()
        }
        audited: dict[tuple[str, str], str] = {}
        for stage, work, human in conn.execute(
            text(
                "SELECT a.stage, i.work_id, i.human_verdict FROM audit_items i"
                " JOIN audits a ON a.audit_id = i.audit_id"
                " WHERE i.human_verdict IS NOT NULL ORDER BY i.audit_id"
            )
        ).all():
            audited[(str(stage), str(work))] = str(human)

    tasks: dict[_Key, set[str]] = defaultdict(set)
    span: dict[_Key, list[str]] = defaultdict(list)
    calibration: dict[_Key, list[tuple[bool, bool]]] = defaultdict(list)
    audit: dict[_Key, list[bool]] = defaultdict(list)  # per audited exclusion: human included
    screened: dict[tuple[str, str], dict[_Key, bool]] = defaultdict(dict)
    for work, label, stage, phase, verdict, task, model, skill, kind, user, ts in decisions:
        human = str(kind) == "human"
        key: _Key = (
            f"screening:{stage}:{label}",
            None if human or model is None else str(model),
            None if human or skill is None else str(skill),
            str(user) if human else None,
        )
        promotes = Verdict(str(verdict)).promotes
        tasks[key].add(str(task))
        span[key].append(str(ts))
        if str(phase) == ScreeningPhase.CALIBRATION.value:
            truth = labels.get((str(stage), str(work)))
            if truth is not None:
                calibration[key].append((truth == "include", promotes))
        elif str(phase) == ScreeningPhase.SCREENING.value:
            screened[(str(stage), str(work))][key] = promotes
            human_verdict = audited.get((str(stage), str(work)))
            if human_verdict is not None and not promotes:
                audit[key].append(human_verdict == "include")

    pairs: dict[tuple[_Key, _Key], list[tuple[bool, bool]]] = defaultdict(list)
    for per_work in screened.values():
        for a, b in combinations(sorted(per_work, key=_sort_key), 2):
            if a[0] != b[0]:
                pairs[(a, b)].append((per_work[a], per_work[b]))

    rows: list[PerfRow] = []
    for key in sorted(tasks, key=_sort_key):
        rates = sensitivity_specificity(calibration[key])
        n_cal = len(calibration[key])
        kappas: dict[str, float | None] = {}
        counts: dict[str, int] = {}
        for (a, b), observed in sorted(
            pairs.items(), key=lambda kv: (_sort_key(kv[0][0]), _sort_key(kv[0][1]))
        ):
            if key not in (a, b):
                continue
            other = b if key == a else a
            oriented = observed if key == a else [(y, x) for x, y in observed]
            name = row_label(*other)
            kappas[name] = _above(len(oriented), cohen_kappa(oriented))
            counts[name] = len(oriented)
        errors = audit[key]
        rate = None if not errors else sum(errors) / len(errors)
        rows.append(
            PerfRow(
                role=key[0],
                model=key[1],
                skill=key[2],
                person=key[3],
                tasks=len(tasks[key]),
                sensitivity=_above(rates.n_positive, rates.sensitivity),
                specificity=_above(rates.n_negative, rates.specificity),
                n_calibration=n_cal,
                kappa_with=kappas,
                n_pairs=counts,
                audit_error_rate=_above(len(errors), rate),
                n_audit=len(errors),
                n_labels=n_cal + len(errors),
                first=min(span[key]),
                last=max(span[key]),
            )
        )
    return PerformanceReport(sample_floor=SAMPLE_FLOOR, rows=rows)


def lines(report: PerformanceReport) -> Sequence[str]:
    """Plain-text rendering for the CLI; a figure below the floor prints as `n=<count>`."""

    def fmt(value: float | None, n: int) -> str:
        return f"{value:.3f}" if value is not None else f"n={n}"

    out = [f"performance record (a rate needs {report.sample_floor} labelled items)"]
    if not report.rows:
        out.append("nothing decided yet")
    for r in report.rows:
        who = r.person if r.person is not None else f"{r.model}@{r.skill}"
        out.append(f"{r.role}  {who}  tasks={r.tasks}  {r.first} .. {r.last}")
        out.append(
            f"  sensitivity {fmt(r.sensitivity, r.n_calibration)}"
            f"  specificity {fmt(r.specificity, r.n_calibration)}"
            f"  audit error {fmt(r.audit_error_rate, r.n_audit)}"
        )
        for other, kappa in r.kappa_with.items():
            out.append(f"  kappa with {other}: {fmt(kappa, r.n_pairs[other])}")
    return out

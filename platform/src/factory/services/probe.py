"""Probes: how well a query retrieves the development seeds, and which negatives it admits.

`run_probe` validates every spec before anything is written: a current question exists, each
source exists and implements `Prober`, and each query is one its prober can measure. In pilot and
systematic projects the split is drawn first, if it has not been (`split_seeds`; its issues
propagate). Then each spec is registered with the caller's actor, with its purpose forced to
`probe`, and measured as the system: `Prober.count` for the source's own total, and
`Prober.matching` for which probe keys of the testable seeds the query retrieves. Every raw
response is archived before it is measured.

Held-out seeds are never measured (R-20). Only development positives (late ones included) and
negatives are sent to a source, and the report, events and validation messages name only those.
The split event itself is the one place held-out ids are recorded, by `split_seeds`.

A `SourceError` writes `probe.failed` for its query, with the redacted reason. Other queries are
still measured, and the failed query claims no recall. A seed without a probe key for the source is
untestable and counts as not retrieved.
"""

from collections.abc import Mapping, Sequence
from typing import Literal

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.probe import (
    ProbeFailed,
    ProbeMeasured,
    ProbePageArchived,
    TermSuggestion,
)
from factory.model.project import RigorMode
from factory.model.search import QueryPurpose, QuerySpec
from factory.model.seed import SeedKind
from factory.model.work import Work
from factory.services.context import Project
from factory.services.project import project_status
from factory.services.question import current_question
from factory.services.search import get_work, query_issues, register_query
from factory.services.seeds import SeedView, agent_seeds, split_is_drawn, split_seeds
from factory.services.vocabulary import suggest_terms
from factory.sources.base import PageSink, Prober, RawPage, SourceError, probe_key
from factory.sources.http import redact
from factory.sources.registry import SourceFactory

THRESHOLDS: dict[RigorMode, float] = {
    RigorMode.EXPLORATORY: 0.6,
    RigorMode.PILOT: 0.9,
    RigorMode.SYSTEMATIC: 1.0,
}


class ProbeQueryResult(StrictModel):
    """One query's measurement. Recall is None unless the query was measured."""

    query_id: str
    source: str
    text: str
    status: Literal["measured", "failed"]
    reported_count: int | None
    recall: float | None
    retrieved: tuple[str, ...]
    missed: tuple[str, ...]
    negatives_retrieved: tuple[str, ...]
    untestable: tuple[str, ...]
    suggestions: tuple[TermSuggestion, ...]
    reason: str | None


class ProbeReport(StrictModel):
    """Every query of one probe, with recall per source and pooled over all sources.

    `per_source_recall` is the union of a source's measured queries over the development count;
    `pooled_recall` is the same union over every measured query. `meets_threshold` is False
    whenever recall is None.
    """

    probe_id: str
    question_id: str
    queries: list[ProbeQueryResult]
    per_source_recall: dict[str, float | None]
    pooled_recall: float | None
    threshold: float
    meets_threshold: bool


def run_probe(
    project: Project,
    actor: Actor,
    specs: Sequence[QuerySpec],
    *,
    sources: Mapping[str, SourceFactory],
) -> ProbeReport:
    """Register and measure each spec against the development seeds and the negatives."""
    question = current_question(project)
    issues: list[ValidationIssue] = []
    if question is None:
        issues.append(ValidationIssue("question", "record a question before probing"))
    probers, spec_issues = _validate(project, specs, sources)
    issues.extend(spec_issues)
    if issues:
        raise FactoryValidationError(issues)
    assert question is not None  # the question check above refused its absence

    mode = project_status(project).rigor_mode
    if mode is not RigorMode.EXPLORATORY and not split_is_drawn(project):
        split_seeds(project)

    probe_id = project.ids.new("prb")
    seeds = agent_seeds(project)
    works = {seed.seed_id: _work_of(project, seed) for seed in seeds}
    results: list[ProbeQueryResult] = []
    for index, spec in enumerate(specs):
        probe_spec = spec.model_copy(update={"purpose": QueryPurpose.PROBE})
        query_id = register_query(project, actor, probe_spec, sources=sources)
        results.append(
            _measure(
                project,
                probe_id=probe_id,
                query_id=query_id,
                question_id=question.question_id,
                spec=probe_spec,
                prober=probers[index],
                seeds=seeds,
                works=works,
            )
        )
    return _report(probe_id, question.question_id, mode, results, seeds)


def _validate(
    project: Project, specs: Sequence[QuerySpec], sources: Mapping[str, SourceFactory]
) -> tuple[list[Prober], list[ValidationIssue]]:
    """A prober for each spec, or the problems that refuse it. Nothing is written here."""
    probers: list[Prober] = []
    issues: list[ValidationIssue] = []
    built: dict[str, Prober] = {}
    for index, spec in enumerate(specs):
        field = f"queries[{index}]"
        factory = sources.get(spec.source)
        if factory is None:
            issues.append(ValidationIssue(f"{field}.source", f"unknown source {spec.source!r}"))
            continue
        if spec.source not in built:
            adapter = factory(project.settings, project.clock)
            if isinstance(adapter, Prober):
                built[spec.source] = adapter
        if spec.source not in built:
            issues.append(ValidationIssue(f"{field}.source", f"{spec.source} cannot measure"))
            continue
        for issue in query_issues(project, spec, sources):
            issues.append(ValidationIssue(f"{field}.{issue.field}", issue.reason))
        probe_kinds = factory.probe_kinds or factory.kinds
        if spec.kind in factory.kinds and spec.kind not in probe_kinds:
            issues.append(
                ValidationIssue(
                    f"{field}.kind", f"{spec.source} cannot measure {spec.kind.value} queries"
                )
            )
        probers.append(built[spec.source])
    return probers, issues


def _work_of(project: Project, seed: SeedView) -> Work | None:
    return None if seed.work_id is None else get_work(project, seed.work_id)


def _measure(
    project: Project,
    *,
    probe_id: str,
    query_id: str,
    question_id: str,
    spec: QuerySpec,
    prober: Prober,
    seeds: list[SeedView],
    works: dict[str, Work | None],
) -> ProbeQueryResult:
    """Measure one registered query. A source failure is recorded and claims no recall."""
    keys: dict[str, str | None] = {}
    for seed in seeds:
        work = works[seed.seed_id]
        keys[seed.seed_id] = None if work is None else probe_key(spec.source, work)
    keyed = sorted({key for key in keys.values() if key is not None})
    try:
        reported = prober.count(spec, archive=_archiver(project, probe_id, query_id, "count"))
        matched = (
            prober.matching(keyed, spec, archive=_archiver(project, probe_id, query_id, "match"))
            if keyed
            else set()
        )
    except SourceError as exc:
        reason = redact(f"{type(exc).__name__}: {exc}", project.settings.mailto)
        failure = ProbeFailed(
            probe_id=probe_id, query_id=query_id, source=spec.source, reason=reason
        )
        with project.writing():
            project.record(
                [
                    project.events.make(
                        "probe.failed", failure, project.system_actor(), refs=(probe_id,)
                    )
                ]
            )
        return ProbeQueryResult(
            query_id=query_id,
            source=spec.source,
            text=spec.text,
            status="failed",
            reported_count=None,
            recall=None,
            retrieved=(),
            missed=(),
            negatives_retrieved=(),
            untestable=(),
            suggestions=(),
            reason=reason,
        )

    development = [s.seed_id for s in seeds if s.kind is SeedKind.POSITIVE]
    negatives = [s.seed_id for s in seeds if s.kind is SeedKind.NEGATIVE]

    def hit(seed_id: str) -> bool:
        key = keys[seed_id]
        return key is not None and key in matched

    retrieved = tuple(sid for sid in development if hit(sid))
    negatives_retrieved = tuple(sid for sid in negatives if hit(sid))
    tested_dev = tuple(sid for sid in development if keys[sid] is not None)
    tested_neg = tuple(sid for sid in negatives if keys[sid] is not None)
    untestable = tuple(sid for sid in [*development, *negatives] if keys[sid] is None)
    missed = tuple(sid for sid in development if sid not in retrieved)
    suggestions = _suggestions(spec.text, development, works, missed)

    payload = ProbeMeasured(
        probe_id=probe_id,
        query_id=query_id,
        source=spec.source,
        question_id=question_id,
        reported_count=reported,
        development_tested=tested_dev,
        development_retrieved=retrieved,
        negatives_tested=tested_neg,
        negatives_retrieved=negatives_retrieved,
        untestable=untestable,
        suggestions=suggestions,
    )
    with project.writing():
        project.record(
            [
                project.events.make(
                    "probe.measured", payload, project.system_actor(), refs=(probe_id,)
                )
            ]
        )
    recall = len(retrieved) / len(development) if development else None
    return ProbeQueryResult(
        query_id=query_id,
        source=spec.source,
        text=spec.text,
        status="measured",
        reported_count=reported,
        recall=recall,
        retrieved=retrieved,
        missed=missed,
        negatives_retrieved=negatives_retrieved,
        untestable=untestable,
        suggestions=suggestions,
        reason=None,
    )


def _suggestions(
    query_text: str,
    development: list[str],
    works: dict[str, Work | None],
    missed: tuple[str, ...],
) -> tuple[TermSuggestion, ...]:
    """Terms the missed development seeds share that the query lacks, held by development seeds.

    Holders are reported as seed ids, not work ids. Works are considered once each, under the
    first seed that carries them.
    """
    seed_of: dict[str, str] = {}
    for seed_id in development:
        work = works[seed_id]
        if work is not None:
            seed_of.setdefault(work.id, seed_id)
    all_works = [works[seed_id] for seed_id in seed_of.values()]
    missed_works = {
        work.id: work
        for seed_id in missed
        if (work := works[seed_id]) is not None and work.id in seed_of
    }
    if not missed_works:
        return ()
    rows = suggest_terms(list(missed_works.values()), [w for w in all_works if w], query_text)
    return tuple(
        row.model_copy(update={"holders": tuple(seed_of[h] for h in row.holders)}) for row in rows
    )


def _archiver(
    project: Project, probe_id: str, query_id: str, role: Literal["count", "match"]
) -> PageSink:
    """Archive each raw response as it arrives, before the probe measures it (R-03)."""

    def archive(page: RawPage) -> str:
        ref = project.blobs.put(page.body.encode("utf-8"))
        payload = ProbePageArchived(
            probe_id=probe_id,
            query_id=query_id,
            ordinal=page.ordinal,
            url=page.url,
            fetched_at=page.fetched_at,
            raw_blob=ref,
            role=role,
        )
        with project.writing():
            project.record(
                [
                    project.events.make(
                        "probe.page_archived", payload, project.system_actor(), refs=(probe_id,)
                    )
                ]
            )
        return ref

    return archive


def _report(
    probe_id: str,
    question_id: str,
    mode: RigorMode,
    results: list[ProbeQueryResult],
    seeds: list[SeedView],
) -> ProbeReport:
    development_count = sum(1 for seed in seeds if seed.kind is SeedKind.POSITIVE)

    def recall_over(rows: list[ProbeQueryResult]) -> float | None:
        measured = [row for row in rows if row.status == "measured"]
        if not measured or development_count == 0:
            return None
        union = {sid for row in measured for sid in row.retrieved}
        return len(union) / development_count

    per_source: dict[str, float | None] = {}
    for row in results:
        if row.source not in per_source:
            per_source[row.source] = recall_over([r for r in results if r.source == row.source])
    pooled = recall_over(results)
    threshold = THRESHOLDS[mode]
    return ProbeReport(
        probe_id=probe_id,
        question_id=question_id,
        queries=results,
        per_source_recall=per_source,
        pooled_recall=pooled,
        threshold=threshold,
        meets_threshold=pooled is not None and pooled >= threshold,
    )


__all__ = ["THRESHOLDS", "ProbeQueryResult", "ProbeReport", "run_probe"]

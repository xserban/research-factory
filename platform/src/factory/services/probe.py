"""Probes: how well a query retrieves the development seeds, and which negatives it admits.

`run_probe` validates every spec before anything is written: a current question exists, each
source exists and implements `Prober`, and each query is one its prober can measure. In pilot and
systematic projects the split is drawn first, if it has not been (`split_seeds`; its issues
propagate). Then each spec is registered with the caller's actor, with its purpose forced to
`probe`, and measured as the system: `Prober.count` for the source's own total, and
`Prober.matching` for which probe keys of the testable seeds the query retrieves. Every raw
response is archived before it is measured.

Each measured query also returns a small sample of titles (`sample`, default 20, 0 disables) so a
scientist can judge noise. OpenAlex draws a seeded random sample; arXiv has none, so it gives the
first page by relevance and says so (`sample_kind`). A sample is archived like any probe page,
never enters the corpus or PRISMA, and drops, without saying why, any record that is a held-out
seed's work. A failed sample request leaves the recall in place and is named in `sample_note`.

When a probe measures both `openalex` and `arxiv`, each OpenAlex query also counts its hits hosted
on arXiv (`openalex_on_arxiv`). That is an estimate of the overlap between the two sources, not a
dedup; the report says so in `overlap_note`.

Held-out seeds are never measured (R-20). Only development positives (late ones included) and
negatives are sent to a source, and the report, events and validation messages name only those.
The split event itself is the one place held-out ids are recorded, by `split_seeds`.

A `SourceError` writes `probe.failed` for its query, with the redacted reason. Other queries are
still measured, and the failed query claims no recall.

A development seed without a probe key for a source is untestable there. It is listed, never counted
as a miss: a source's recall is retrieved over the development seeds testable on that source (None
when none is), and the pooled recall is the union retrieved over the development seeds testable on
at least one measured source. `recall_figures` computes both from (source, tested, retrieved)
rows, which a `probe.measured` payload carries, so events written before this rule give the same
figures.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.budgets import REQUESTS_SEARCH
from factory.model.probe import (
    ProbeFailed,
    ProbeMeasured,
    ProbePageArchived,
    TermSuggestion,
)
from factory.model.project import RigorMode
from factory.model.search import QueryPurpose, QuerySpec
from factory.model.seed import SeedKind
from factory.model.work import Identifiers, Work
from factory.services.budgets import budget_issue, budget_issues, exhausted_unit
from factory.services.context import Project
from factory.services.project import project_status
from factory.services.question import current_question
from factory.services.search import get_work, query_issues, register_query
from factory.services.seeds import (
    SeedView,
    agent_seeds,
    held_out_identifier_matcher,
    split_is_drawn,
    split_seeds,
)
from factory.services.vocabulary import suggest_terms
from factory.sources.base import (
    OverlapCounter,
    PageSink,
    Prober,
    RawPage,
    Sampler,
    SourceError,
    probe_key,
)
from factory.sources.http import redact
from factory.sources.registry import SourceFactory

THRESHOLDS: dict[RigorMode, float] = {
    RigorMode.EXPLORATORY: 0.6,
    RigorMode.PILOT: 0.9,
    RigorMode.SYSTEMATIC: 1.0,
}


OVERLAP_NOTE = (
    "openalex_on_arxiv counts an OpenAlex query's hits hosted on arXiv. It estimates how much the "
    "two sources overlap; it is not a deduplication and does not match records one to one."
)
DEFAULT_SAMPLE = 20
MAX_SAMPLE = 200


class ProbeQueryResult(StrictModel):
    """One query's measurement. Recall is None unless the query was measured."""

    query_id: str
    source: str
    text: str
    status: Literal["measured", "failed"]
    reported_count: int | None
    recall: float | None
    development_tested: tuple[str, ...] = ()
    retrieved: tuple[str, ...]
    missed: tuple[str, ...]
    negatives_retrieved: tuple[str, ...]
    untestable: tuple[str, ...]
    suggestions: tuple[TermSuggestion, ...]
    sample_titles: tuple[str, ...] = ()
    sample_kind: Literal["random", "top"] | None = None
    sample_note: str | None = None
    openalex_on_arxiv: int | None = None
    overlap_note: str | None = None
    reason: str | None


class ProbeReport(StrictModel):
    """Every query of one probe, with recall per source and pooled over all sources.

    `per_source_recall` is the union of a source's measured queries over the development seeds
    testable on that source (None when none is); `untestable_by_source` lists the development
    seeds that source cannot test, which are not in the denominator. `pooled_recall` is the union
    over every measured query over the development seeds testable on at least one measured source;
    `untestable_pooled` lists those testable on none. `meets_threshold` is False whenever recall
    is None.
    """

    probe_id: str
    question_id: str
    queries: list[ProbeQueryResult]
    per_source_recall: dict[str, float | None]
    untestable_by_source: dict[str, tuple[str, ...]]
    pooled_recall: float | None
    untestable_pooled: tuple[str, ...]
    overlap_note: str | None = None
    threshold: float
    meets_threshold: bool


def run_probe(
    project: Project,
    actor: Actor,
    specs: Sequence[QuerySpec],
    *,
    sources: Mapping[str, SourceFactory],
    sample: int = DEFAULT_SAMPLE,
) -> ProbeReport:
    """Register and measure each spec against the development seeds and the negatives.

    `sample` is the number of titles to sample per measured query, 0 for none.
    """
    question = current_question(project)
    issues: list[ValidationIssue] = []
    if not 0 <= sample <= MAX_SAMPLE:
        issues.append(ValidationIssue("sample", f"must be between 0 and {MAX_SAMPLE}"))
    if question is None:
        issues.append(ValidationIssue("question", "record a question before probing"))
    probers, spec_issues = _validate(project, specs, sources)
    issues.extend(spec_issues)
    issues += budget_issues(project, actor, REQUESTS_SEARCH)
    if issues:
        raise FactoryValidationError(issues)
    assert question is not None  # the question check above refused its absence

    mode = project_status(project).rigor_mode
    if mode is not RigorMode.EXPLORATORY and not split_is_drawn(project):
        split_seeds(project)

    probe_id = project.ids.new("prb")
    seeds = agent_seeds(project)
    works = {seed.seed_id: _work_of(project, seed) for seed in seeds}
    # Built once, and only when a sample is wanted: the held-out identifiers stay in this process.
    is_held_out = held_out_identifier_matcher(project) if sample > 0 else (lambda _ids: False)
    count_overlap = {"openalex", "arxiv"} <= {spec.source for spec in specs}
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
                sample=sample,
                is_held_out=is_held_out,
                count_overlap=count_overlap,
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


def _require_requests(project: Project) -> None:
    """A spent request budget ends a query as a source failure does: recorded, with no recall."""
    spent = exhausted_unit(project, project.principal, REQUESTS_SEARCH)
    if spent is not None:
        raise SourceError(budget_issue(spent).reason)


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
    sample: int,
    is_held_out: Callable[[Identifiers], bool],
    count_overlap: bool,
) -> ProbeQueryResult:
    """Measure one registered query. A source failure is recorded and claims no recall."""
    keys: dict[str, str | None] = {}
    for seed in seeds:
        work = works[seed.seed_id]
        keys[seed.seed_id] = None if work is None else probe_key(spec.source, work)
    keyed = sorted({key for key in keys.values() if key is not None})
    try:
        _require_requests(project)
        reported = prober.count(spec, archive=_archiver(project, probe_id, query_id, "count"))
        matched: set[str] = set()
        if keyed:
            _require_requests(project)
            matched = prober.matching(
                keyed, spec, archive=_archiver(project, probe_id, query_id, "match")
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
            development_tested=(),
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
    sample_kind: Literal["random", "top"] | None = None
    titles: tuple[str, ...] = ()
    sample_note: str | None = None
    if sample > 0 and isinstance(prober, Sampler):
        # Network outside `project.writing()`; the sample is archived page by page as it arrives.
        try:
            _require_requests(project)
            kind, records = prober.sample(
                spec, sample, archive=_archiver(project, probe_id, query_id, "sample")
            )
            sample_kind = kind
            titles = tuple(r.title for r in records if not is_held_out(r.identifiers))
        except SourceError as exc:
            sample_note = redact(f"{type(exc).__name__}: {exc}", project.settings.mailto)

    on_arxiv: int | None = None
    overlap_note: str | None = None
    if count_overlap and spec.source == "openalex" and isinstance(prober, OverlapCounter):
        try:
            _require_requests(project)
            on_arxiv = prober.count_on_arxiv(
                spec, archive=_archiver(project, probe_id, query_id, "overlap")
            )
        except SourceError as exc:
            overlap_note = redact(f"{type(exc).__name__}: {exc}", project.settings.mailto)
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
        sample_titles=titles,
        sample_kind=sample_kind,
        openalex_on_arxiv=on_arxiv,
    )
    with project.writing():
        project.record(
            [
                project.events.make(
                    "probe.measured", payload, project.system_actor(), refs=(probe_id,)
                )
            ]
        )
    recall = len(retrieved) / len(tested_dev) if tested_dev else None
    return ProbeQueryResult(
        query_id=query_id,
        source=spec.source,
        text=spec.text,
        status="measured",
        reported_count=reported,
        recall=recall,
        development_tested=tested_dev,
        retrieved=retrieved,
        missed=missed,
        negatives_retrieved=negatives_retrieved,
        untestable=untestable,
        suggestions=suggestions,
        sample_titles=titles,
        sample_kind=sample_kind,
        sample_note=sample_note,
        openalex_on_arxiv=on_arxiv,
        overlap_note=overlap_note,
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
    project: Project,
    probe_id: str,
    query_id: str,
    role: Literal["count", "match", "sample", "overlap"],
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


def recall_figures(
    rows: Sequence[tuple[str, Sequence[str], Sequence[str]]], development: Sequence[str]
) -> tuple[dict[str, float | None], dict[str, tuple[str, ...]], float | None, tuple[str, ...]]:
    """Recall per source and pooled, from (source, development tested, development retrieved).

    Only measured queries are given. A source's recall is the union retrieved over the union
    tested on that source; the pooled recall is the union retrieved over the development seeds
    tested on at least one source. Seeds a source cannot test are listed per source (in
    `development` order) and are not in any denominator. Returns per-source recall, per-source
    untestable, pooled recall and the seeds testable on no given source.
    """
    tested: dict[str, set[str]] = {}
    found: dict[str, set[str]] = {}
    for source, tested_ids, retrieved_ids in rows:
        tested.setdefault(source, set()).update(tested_ids)
        found.setdefault(source, set()).update(retrieved_ids)
    per_source = {
        source: len(found[source]) / len(ids) if ids else None for source, ids in tested.items()
    }
    untestable = {
        source: tuple(sid for sid in development if sid not in ids)
        for source, ids in tested.items()
    }
    testable = set().union(*tested.values()) if tested else set()
    pooled_found = set().union(*found.values()) if found else set()
    pooled = len(pooled_found) / len(testable) if testable else None
    return (
        per_source,
        untestable,
        pooled,
        tuple(sid for sid in development if sid not in testable) if tested else (),
    )


def _report(
    probe_id: str,
    question_id: str,
    mode: RigorMode,
    results: list[ProbeQueryResult],
    seeds: list[SeedView],
) -> ProbeReport:
    development = [seed.seed_id for seed in seeds if seed.kind is SeedKind.POSITIVE]
    measured = [row for row in results if row.status == "measured"]
    per_measured, untestable, pooled, untestable_pooled = recall_figures(
        [(row.source, row.development_tested, row.retrieved) for row in measured], development
    )
    # A source whose queries all failed claims no recall, but is still named.
    per_source: dict[str, float | None] = {row.source: None for row in results}
    per_source.update(per_measured)
    threshold = THRESHOLDS[mode]
    return ProbeReport(
        probe_id=probe_id,
        question_id=question_id,
        queries=results,
        per_source_recall=per_source,
        untestable_by_source=untestable,
        pooled_recall=pooled,
        untestable_pooled=untestable_pooled,
        overlap_note=(
            OVERLAP_NOTE if any(row.openalex_on_arxiv is not None for row in results) else None
        ),
        threshold=threshold,
        meets_threshold=pooled is not None and pooled >= threshold,
    )


__all__ = ["THRESHOLDS", "ProbeQueryResult", "ProbeReport", "recall_figures", "run_probe"]

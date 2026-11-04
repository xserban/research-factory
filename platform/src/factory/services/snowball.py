"""Snowball rounds: supplementary searches from the included works' reference lists (slice 3a).

A backward round (`via = document-reference-list`) takes as its sources the included works with a
current extraction. Its candidates are the works of their live `resolved` links that are not in
the corpus, each with the derived number of distinct source works citing it, ranked by that
number (descending), ties by key; there is no threshold (ruling 7). A candidate's key is its work
id when a source returned the work (a lookup work outside the corpus), else the entry key
`rex_<ULID>:<ordinal>` of its first citing entry for a `no-source-record` work (ruling 8).

The platform builds the round's queries (chase purpose, ruling 20): OpenAlex `openalex:` and
`doi:` filters, arXiv `id_list` texts and `reflist` entry-key lists, each sorted, holding at most
`CHASE_CHUNK` ids and `MAX_QUERY` characters. A candidate no query can name is listed
`unqueryable`, never dropped.

Invariants:
- Validation precedes every write. A round is refused, writing nothing, when the protocol declares
  no `snowball_plan` in `pilot`/`systematic` (an `exploratory` round records `rule: none`), when
  the direction's maximum is reached, when the previous round of the direction yielded no included
  work and the plan says to stop (skipped, with a note, when that round had a failed or partial
  run, so its retry is possible; the maximum still holds), while any corpus work's outcome is
  pending, while an included work has a document but no current extraction (ruling 18), when
  there is no candidate or no queryable candidate, when a query does not fit its source, or when
  the protocol gate refuses (always asked; the round's texts waived).
- `snowball.round_started` is written before any query is registered; each query is then
  registered naming the round (`query.registered` refs end with the round id; only such a query
  has the round's texts waived and counts as the round's run) and run, and a failed run does not
  stop the others. A retry is a new round.
- Candidates are never included: retrieved records enter the corpus as pending works.
- Counts (`cited_by_included`, new works, round numbers) are computed, never supplied.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from pydantic import Field
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.base import StrictModel
from factory.model.chase import CHASE_CHUNK
from factory.model.project import RigorMode
from factory.model.protocol import ScreeningStage, SnowballPlan
from factory.model.references import (
    MAX_QUERY,
    CitingEntry,
    Direction,
    LinkState,
    SnowballCandidate,
    SnowballRoundStarted,
    Unextracted,
    Via,
)
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work_ids import arxiv_id_from_doi
from factory.services.agreement import Outcome, final_outcomes
from factory.services.calibration import calibration_items
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.document_read import default_conversion
from factory.services.protocol import current_protocol, search_authorization
from factory.services.references import current_extraction, included_works
from factory.services.search import (
    RunSummary,
    corpus_size,
    list_works,
    query_issues,
    register_query,
    run_query,
)
from factory.sources.reflist import NAME as REFLIST
from factory.sources.reflist import ReflistEntry
from factory.sources.registry import SourceFactory, reflist_factory

NOT_EXTRACTED = "not-extracted"
NO_DOCUMENT = "no-document"
MAX_LISTED = 20
"""Work ids named in one refusal message; the rest are counted."""


class RoundCandidate(StrictModel):
    """One candidate of a round. `work_id` is the work the links name (for a `no-source-record`
    candidate, the id its `reflist` record gets); `citing_anchors` are (citing work, anchor) pairs
    of the matched in-text markers; `cited_by` the citing entries; `openalex`, `arxiv` and `doi`
    the identifiers of the stored lookup work, from which the queries are built."""

    work_key: str
    work_id: str | None
    cited_by_included: int
    citing_anchors: tuple[tuple[str, str], ...]
    no_source_record: bool
    cited_by: tuple[CitingEntry, ...] = ()
    openalex: str | None = None
    arxiv: str | None = None
    doi: str | None = None


class SnowballPlanState(StrictModel):
    """Whether a round of `direction` may start now, and why not. `rule` is the declared plan."""

    direction: Direction
    round_no: int
    allowed: bool
    refusals: list[ValidationIssue]
    rule: SnowballPlan | None
    notes: list[str] = Field(default_factory=list)
    """Facts that changed how the rule applied, e.g. a no-yield stop skipped after failed runs."""


class RoundPlan(StrictModel):
    """A dry run: everything a round would record, computed from the current state."""

    state: SnowballPlanState
    sources: list[str]
    extraction_ids: list[str]
    candidates: list[RoundCandidate]
    queries: list[QuerySpec]
    unqueryable: list[str]
    unextracted: list[tuple[str, str]]


class RoundResult(StrictModel):
    """What `snowball_round` planned or recorded. `round_id` is None for a dry run."""

    round_id: str | None
    dry_run: bool
    state: SnowballPlanState
    sources: list[str]
    candidates: list[RoundCandidate]
    queries: list[QuerySpec]
    unqueryable: list[str]
    unextracted: list[tuple[str, str]]
    runs: list[RunSummary]
    new_works: int


class RecordedRound(StrictModel):
    """One recorded round, read back from the index, in event order."""

    round_id: str
    direction: Direction
    round_no: int
    event_id: str
    sources: list[str]
    unextracted: list[str]
    queries: list[str]


# --- Recorded rounds ---


def recorded_rounds(project: Project) -> list[RecordedRound]:
    """Every recorded snowball round, in event order."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT round_id, direction, round_no, event_id, sources, unextracted "
                "FROM snowball_rounds ORDER BY event_id"
            )
        ).all()
        texts: dict[str, list[str]] = {}
        for round_id, query in conn.execute(
            text("SELECT round_id, query FROM snowball_queries ORDER BY round_id, position")
        ).all():
            texts.setdefault(str(round_id), []).append(str(query))
    return [
        RecordedRound(
            round_id=str(round_id),
            direction=Direction(str(direction)),
            round_no=int(round_no),
            event_id=str(event_id),
            sources=[str(s) for s in json.loads(str(sources))],
            unextracted=[str(u["work_id"]) for u in json.loads(str(unextracted))],
            queries=texts.get(str(round_id), []),
        )
        for round_id, direction, round_no, event_id, sources, unextracted in rows
    ]


def round_runs(project: Project, round_id: str) -> list[str]:
    """The runs of the queries registered for the round, sorted: queries whose
    `query.registered` refs name `round_id` (`register_query(..., round_id=...)`)."""
    return [run for run, _ in _round_run_statuses(project, round_id)]


def _round_run_statuses(project: Project, round_id: str) -> list[tuple[str, RunStatus]]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.run_id, r.status FROM runs r JOIN events e "
                "ON e.type = 'query.registered' AND json_extract(e.refs, '$[0]') = r.query_id "
                "WHERE EXISTS (SELECT 1 FROM json_each(e.refs) WHERE json_each.value = :round) "
                "ORDER BY r.run_id"
            ),
            {"round": round_id},
        ).all()
    return [(str(run), RunStatus(str(status))) for run, status in rows]


def _round_included(project: Project, recorded: RecordedRound, included: set[str]) -> set[str]:
    """Works the round's runs retrieved that are now included and were not included when it was
    recorded (its sources and its unextracted works); absorbed works count as their primary."""
    runs = round_runs(project, recorded.round_id)
    if not runs:
        return set()
    primary = {absorbed: m.primary for m in active_merges(project) for absorbed in m.absorbed}
    with project.index.connect() as conn:
        retrieved = {
            str(row[0])
            for run in runs
            for row in conn.execute(
                text("SELECT work_id FROM provenance WHERE run_id = :run"), {"run": run}
            ).all()
        }
    earlier = set(recorded.sources) | set(recorded.unextracted)
    return {primary.get(w, w) for w in retrieved} & included - earlier


# --- Candidates and queries ---


def snowball_candidates(project: Project, sources: Sequence[str]) -> list[RoundCandidate]:
    """Candidates drawn from the current extractions of `sources`: live `resolved` links whose
    work is not in the corpus, sorted by (-cited_by_included, work_key)."""
    project.index.sync()
    extractions = {
        rex: work for work in sources if (rex := current_extraction(project, work)) is not None
    }
    with project.index.connect() as conn:
        links = conn.execute(
            text(
                "SELECT l.extraction_id, l.ordinal, l.work_id, l.no_source_record "
                "FROM reference_links l JOIN reference_extractions x "
                "ON x.extraction_id = l.extraction_id AND x.live = 1 "
                "WHERE l.state = :resolved AND l.work_id IS NOT NULL "
                "ORDER BY l.extraction_id, l.ordinal"
            ),
            {"resolved": LinkState.RESOLVED.value},
        ).all()
        contexts = conn.execute(
            text(
                "SELECT extraction_id, entry, citing_anchor FROM citation_contexts "
                "WHERE state = 'matched' ORDER BY extraction_id, position"
            )
        ).all()
    anchors: dict[tuple[str, int], list[str]] = {}
    for rex, entry, anchor in contexts:
        slot = (str(rex), int(entry))
        if str(anchor) not in anchors.setdefault(slot, []):
            anchors[slot].append(str(anchor))
    corpus = {w.id for w in list_works(project)}
    stored = {w.id: w for w in list_works(project, include_probe=True)}
    groups: dict[str, list[tuple[str, int, bool]]] = {}
    for rex, ordinal, wid, flagged in links:
        if str(rex) in extractions and str(wid) not in corpus:
            groups.setdefault(str(wid), []).append((str(rex), int(ordinal), bool(flagged)))
    out: list[RoundCandidate] = []
    for wid, cites in groups.items():
        work = stored.get(wid)
        no_source = work is None and any(flagged for _, _, flagged in cites)
        if no_source:
            first_rex, first_ordinal = min((r, o) for r, o, flagged in cites if flagged)
            key = f"{first_rex}:{first_ordinal}"
        else:
            key = wid
        cited_by = tuple(
            CitingEntry(
                work_id=extractions[rex],
                extraction_id=rex,
                ordinal=ordinal,
                anchors=tuple(anchors.get((rex, ordinal), [])),
            )
            for rex, ordinal, _ in cites
        )
        pairs = sorted({(c.work_id, a) for c in cited_by for a in c.anchors})
        out.append(
            RoundCandidate(
                work_key=key,
                work_id=wid,
                cited_by_included=len({c.work_id for c in cited_by}),
                citing_anchors=tuple(pairs),
                no_source_record=no_source,
                cited_by=cited_by,
                openalex=None if work is None else work.identifiers.openalex,
                arxiv=None
                if work is None
                else _arxiv(work.identifiers.arxiv, work.identifiers.doi),
                doi=None if work is None else work.identifiers.doi,
            )
        )
    return sorted(out, key=lambda c: (-c.cited_by_included, c.work_key))


def _arxiv(arxiv: str | None, doi: str | None) -> str | None:
    return arxiv or (arxiv_id_from_doi(doi) if doi else None)


def _route(candidate: RoundCandidate) -> tuple[str, str] | None:
    """(query family, id) naming the candidate, or None when no query can name it: no usable
    identifier, a DOI the filter syntax cannot carry, or an id too long for one query."""
    route: tuple[str, str] | None = None
    if candidate.no_source_record:
        route = "reflist", candidate.work_key
    elif candidate.openalex:
        route = "openalex", candidate.openalex
    elif candidate.arxiv:
        route = "arxiv", candidate.arxiv
    elif candidate.doi and not any(sep in candidate.doi for sep in "|,"):
        route = "doi", candidate.doi
    if route is None or len(_PREFIX[route[0]]) + len(route[1]) > MAX_QUERY:
        return None
    return route


def unqueryable_keys(candidates: Sequence[RoundCandidate]) -> list[str]:
    """Keys of the candidates no query can name, in the given order (listed, never dropped)."""
    return [c.work_key for c in candidates if _route(c) is None]


_FAMILIES: tuple[tuple[str, str, QueryKind, str, str], ...] = (
    # family, source, kind, prefix, separator
    ("openalex", "openalex", QueryKind.FILTER, "openalex:", "|"),
    ("doi", "openalex", QueryKind.FILTER, "doi:", "|"),
    ("arxiv", "arxiv", QueryKind.ID_LIST, "", ","),
    ("reflist", REFLIST, QueryKind.ID_LIST, "", ","),
)
_PREFIX = {family: prefix for family, _, _, prefix, _ in _FAMILIES}
_GATE_PLACEHOLDER = QuerySpec(
    source=REFLIST, kind=QueryKind.ID_LIST, text="snowball-round", purpose=QueryPurpose.CHASE
)


def _pack(ids: Sequence[str], prefix: str, separator: str) -> list[str]:
    """Texts of at most `CHASE_CHUNK` ids and `MAX_QUERY` characters, ids in the given order."""
    texts: list[str] = []
    chunk: list[str] = []
    for value in ids:
        trial = prefix + separator.join([*chunk, value])
        if chunk and (len(chunk) == CHASE_CHUNK or len(trial) > MAX_QUERY):
            texts.append(prefix + separator.join(chunk))
            chunk = []
        chunk.append(value)
    if chunk:
        texts.append(prefix + separator.join(chunk))
    return texts


def snowball_queries(candidates: Sequence[RoundCandidate]) -> list[QuerySpec]:
    """The chase-purpose queries that retrieve `candidates`: OpenAlex `openalex:` then `doi:`
    filters, arXiv `id_list`, then `reflist` entry keys; ids sorted within each family."""
    ids: dict[str, set[str]] = {family: set() for family, *_ in _FAMILIES}
    for candidate in candidates:
        route = _route(candidate)
        if route is not None:
            ids[route[0]].add(route[1])
    return [
        QuerySpec(source=source, kind=kind, text=t, purpose=QueryPurpose.CHASE)
        for family, source, kind, prefix, separator in _FAMILIES
        for t in _pack(sorted(ids[family]), prefix, separator)
    ]


# --- Plan ---


def _rigor_mode(project: Project) -> RigorMode:
    with project.index.connect() as conn:
        value = conn.execute(
            text("SELECT rigor_mode FROM project WHERE slug = :slug"),
            {"slug": project.paths.slug},
        ).scalar_one()
    return RigorMode(str(value))


def _named(ids: Sequence[str]) -> str:
    shown = ", ".join(ids[:MAX_LISTED])
    more = len(ids) - MAX_LISTED
    return shown + (f" and {more} more" if more > 0 else "")


def _pending(project: Project) -> list[str]:
    """Ordinary works whose outcome is pending at title/abstract, or, when the protocol plans full
    text screening, at full text after promotion. Calibration works are left out."""
    calibration = set(calibration_items(project))
    outcomes = final_outcomes(project)
    pending = {w for w, o in outcomes.items() if o is Outcome.PENDING and w not in calibration}
    protocol = current_protocol(project)
    if protocol is not None and protocol.spec.full_text_screening is not None:
        promoted = {w for w, o in outcomes.items() if o is Outcome.INCLUDED}
        ft_calibration = set(calibration_items(project, stage=ScreeningStage.FULL_TEXT))
        pending |= {
            w
            for w, o in final_outcomes(project, stage=ScreeningStage.FULL_TEXT).items()
            if w in promoted and o is Outcome.PENDING and w not in ft_calibration
        }
    return sorted(pending)


def _has_document(project: Project, work: str) -> bool:
    """Whether the work has a live document that is converted or still convertible (no recorded
    conversion failure)."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT d.document_id, "
                "(SELECT COUNT(*) FROM document_conversions c "
                "WHERE c.document_id = d.document_id), "
                "(SELECT COUNT(*) FROM document_failures f WHERE f.document_id = d.document_id) "
                "FROM fulltext_documents d WHERE d.work_id = :work AND d.superseded_by IS NULL"
            ),
            {"work": work},
        ).all()
    return any(int(converted) > 0 or int(failed) == 0 for _, converted, failed in rows)


def _scope(
    project: Project,
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """(sources, their current extraction ids, unextracted (work, reason)) of the included works."""
    sources: list[str] = []
    extraction_ids: list[str] = []
    unextracted: list[tuple[str, str]] = []
    for work in included_works(project):
        rex = current_extraction(project, work)
        if rex is not None:
            sources.append(work)
            extraction_ids.append(rex)
        elif default_conversion(project, work) is not None or _has_document(project, work):
            unextracted.append((work, NOT_EXTRACTED))
        else:
            unextracted.append((work, NO_DOCUMENT))
    return sources, extraction_ids, unextracted


def plan_round(project: Project, direction: Direction) -> RoundPlan:
    """Plan a round of `direction` without writing anything: the stopping-rule state, sources,
    candidates, queries and the included works without a current extraction."""
    project.index.sync()
    protocol = current_protocol(project)
    rule = None if protocol is None else protocol.spec.snowball_plan
    mode = _rigor_mode(project)
    previous = [r for r in recorded_rounds(project) if r.direction is direction]
    round_no = len(previous) + 1
    sources, extraction_ids, unextracted = _scope(project)
    refusals: list[ValidationIssue] = []
    notes: list[str] = []

    if direction is not Direction.BACKWARD:
        refusals.append(
            ValidationIssue("direction", "forward rounds delegate to search_chase; not available")
        )
    if rule is None and mode in (RigorMode.PILOT, RigorMode.SYSTEMATIC):
        refusals.append(
            ValidationIssue(
                "snowball_plan",
                "snowball-plan-missing: declare the stopping rule in the protocol (amendment)",
            )
        )
    if rule is not None:
        maximum = (
            rule.max_backward_rounds if direction is Direction.BACKWARD else rule.max_forward_rounds
        )
        if round_no > maximum:
            refusals.append(
                ValidationIssue(
                    "round_no",
                    f"round {round_no} exceeds the plan's maximum of {maximum} "
                    f"{direction.value} rounds",
                )
            )
        if rule.stop_when_no_new_included and previous:
            last = previous[-1]
            incomplete = [
                run
                for run, status in _round_run_statuses(project, last.round_id)
                if status in (RunStatus.FAILED, RunStatus.PARTIAL)
            ]
            if incomplete:
                notes.append(
                    f"{last.round_id} had {len(incomplete)} failed or partial runs; the no-yield "
                    "stop does not apply to its retry (the round maximum does)"
                )
            elif not _round_included(project, last, set(included_works(project))):
                refusals.append(
                    ValidationIssue(
                        "previous_round",
                        f"{last.round_id} yielded no newly included work; the plan stops here",
                    )
                )
    pending = _pending(project)
    if pending:
        refusals.append(
            ValidationIssue("screening", f"{len(pending)} works still pending: {_named(pending)}")
        )
    blocking = [w for w, reason in unextracted if reason == NOT_EXTRACTED]
    if blocking:
        refusals.append(
            ValidationIssue(
                "unextracted",
                f"included works with a document and no current extraction: {_named(blocking)}",
            )
        )
    candidates = snowball_candidates(project, sources) if direction is Direction.BACKWARD else []
    queries = snowball_queries(candidates)
    unqueryable = unqueryable_keys(candidates)
    if direction is Direction.BACKWARD and not candidates:
        refusals.append(ValidationIssue("candidates", "no resolved reference outside the corpus"))
    elif direction is Direction.BACKWARD and not queries:
        refusals.append(ValidationIssue("candidates", "no queryable candidate"))
    state = SnowballPlanState(
        direction=direction,
        round_no=round_no,
        allowed=not refusals,
        refusals=refusals,
        rule=rule,
        notes=notes,
    )
    return RoundPlan(
        state=state,
        sources=sources,
        extraction_ids=extraction_ids,
        candidates=candidates,
        queries=queries,
        unqueryable=unqueryable,
        unextracted=unextracted,
    )


# --- The round ---


def round_sources(
    project: Project, sources: Mapping[str, SourceFactory]
) -> dict[str, SourceFactory]:
    """`sources` with the offline `reflist` source bound to this project, unless one is given."""
    out = dict(sources)
    out.setdefault(REFLIST, reflist_factory(lambda keys: reflist_entries(project, keys)))
    return out


def reflist_entries(project: Project, keys: Sequence[str]) -> dict[str, ReflistEntry]:
    """The stored entries among `keys` whose link resolved to a `no-source-record` work."""
    out: dict[str, ReflistEntry] = {}
    with project.index.connect() as conn:
        for key in keys:
            rex, _, ordinal = key.partition(":")
            if not ordinal.isdigit():
                continue
            row = (
                conn.execute(
                    text(
                        "SELECT e.title, e.first_author, e.year, e.doi, e.arxiv, e.url, e.venue, "
                        "e.entry_sha256 FROM reference_entries e JOIN reference_links l "
                        "ON l.extraction_id = e.extraction_id AND l.ordinal = e.ordinal "
                        "WHERE e.extraction_id = :rex AND e.ordinal = :ordinal "
                        "AND l.no_source_record = 1 AND e.title IS NOT NULL "
                        "AND e.year IS NOT NULL"
                    ),
                    {"rex": rex, "ordinal": int(ordinal)},
                )
                .mappings()
                .first()
            )
            if row is not None:
                out[key] = ReflistEntry(
                    key=key,
                    title=str(row["title"]),
                    first_author=row["first_author"],
                    year=int(row["year"]),
                    doi=row["doi"],
                    arxiv=row["arxiv"],
                    url=row["url"],
                    venue=row["venue"],
                    entry_sha256=str(row["entry_sha256"]),
                )
    return out


def snowball_round(
    project: Project,
    actor: Actor,
    direction: Direction,
    *,
    sources: Mapping[str, SourceFactory],
    dry_run: bool = True,
) -> RoundResult:
    """Plan a round (`dry_run`, the default, writes nothing), or record and run it.

    A recorded round is validated in full first (see the module invariants) and refused with
    every issue at once; then `snowball.round_started` is written, and each query is registered
    and run in order.
    """
    adapters = round_sources(project, sources)
    with project.index.exclusive():
        plan = plan_round(project, direction)
        if dry_run:
            return _result(plan, None, [], 0)
        issues = list(plan.state.refusals)
        specs = plan.queries
        issues += [issue for spec in specs for issue in query_issues(project, spec, adapters)]
        # The gate is always asked. Every gate except the planned-query waiver is
        # text-independent, and the waiver holds for every text of the round (as in
        # `search_chase`), so the first spec stands for all; with no spec (already refused
        # above) a placeholder chase spec still reports the text-independent gates.
        probe = specs[0] if specs else _GATE_PLACEHOLDER
        texts = [spec.text for spec in specs] or [probe.text]
        issues += search_authorization(project, probe, deviation_id=None, pending_round_texts=texts)
        if issues:
            raise FactoryValidationError(issues)

        round_id = project.ids.new("snw")
        payload = SnowballRoundStarted(
            round_id=round_id,
            direction=direction,
            via=Via.DOCUMENT_REFERENCE_LIST,
            round_no=plan.state.round_no,
            sources=tuple(plan.sources),
            extraction_ids=tuple(plan.extraction_ids),
            candidates=tuple(
                SnowballCandidate(
                    work_key=c.work_key, cited_by=c.cited_by, no_source_record=c.no_source_record
                )
                for c in plan.candidates
            ),
            queries=tuple(spec.text for spec in specs),
            rule="none" if plan.state.rule is None else plan.state.rule,
            unextracted=tuple(Unextracted(work_id=w, reason=r) for w, r in plan.unextracted),
        )
        input_blob = (
            project.blobs.put_json({"direction": direction.value, "dry_run": dry_run})
            if actor.kind == "agent"
            else None
        )
        before, _ = corpus_size(project)
        project.record(
            [
                project.events.make(
                    "snowball.round_started",
                    payload,
                    actor,
                    refs=(round_id,),
                    input_blob=input_blob,
                )
            ]
        )

    query_ids = [
        register_query(project, actor, spec, sources=adapters, round_id=round_id) for spec in specs
    ]
    runs = [run_query(project, query_id, sources=adapters, actor=actor) for query_id in query_ids]
    after, _ = corpus_size(project)
    return _result(plan, round_id, runs, after - before)


def _result(
    plan: RoundPlan, round_id: str | None, runs: list[RunSummary], new_works: int
) -> RoundResult:
    return RoundResult(
        round_id=round_id,
        dry_run=round_id is None,
        state=plan.state,
        sources=plan.sources,
        candidates=plan.candidates,
        queries=plan.queries,
        unqueryable=plan.unqueryable,
        unextracted=plan.unextracted,
        runs=runs,
        new_works=new_works,
    )

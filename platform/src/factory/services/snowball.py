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

A forward round (`via = source-metadata`) delegates to `search_chase` for `FORWARD` (ruling 10)
from the same sources as a backward round: the works INCLUDED at the last declared stage
(ruling 15) that have an OpenAlex id (those without are listed `unqueryable`); its queries are
the chase round's `cites:` texts. The stopping rule, pending and unextracted checks run first and
write nothing on refusal; the chase round (`start_chase`) and the `snowball.round_started` naming
it (`chase_round_id`) are then recorded together and its queries run (`run_chase`).

A round's runs are linked by reference, never by text: the queries whose `query.registered` refs
name the round (backward) or its chase round (forward). `round_yield` counts what they retrieved,
what was new after dedup and, once settled, what is included; `snowball_compare` sets a backward
round's resolved references against the `cited_by:` runs of the backward chase rounds from
overlapping sources.

The plan's forward options (slice 8, IDEA-43) narrow a forward round without changing its
machinery. `forward_core_only` makes the sources the core works (the researcher's marks that are
included, and every positive seed's work: `services.core_works`), not every included work.
`forward_topic_filter` is appended to each `cites:` text as `,title_and_abstract.search:<expr>`
(OpenAlex comma-AND), so the chase round records the filtered texts. `forward_max_per_work` caps
the citing works taken per source work. A cap needs the citing works' metadata before the round is
recorded, so a recorded capped round first fetches, for each source work, `cites:W[,filter]` as a
`probe`-purpose query (recorded runs whose works join no corpus and no count), embeds the citing
works outside `project.writing()` with the ranker's embedder and takes the top N per source by
maximum cosine to the development seed references (`services.ranking`; ties by work id; citing
works already in the corpus are not candidates). The round's chase texts are then the chosen
works' `openalex:W1|W2` filters (at most `CHASE_CHUNK` ids each), so its runs stay linked to the
round as before and only the chosen works enter the corpus. `snowball.round_started` records, in
`selection`, the model id, weights hash and software, the cap and filter, the probe runs and, per
source work, the citing works matched, already held and taken; the number not taken is derived
(`CoreSelection.not_taken`), never stored (R-05). A dry run fetches nothing and says so in its
notes. Without the `ranker` extra or the weights a capped round is refused, with nothing written
beyond the probes already made, and the refusal names the remedy.

Invariants:
- Validation precedes every write. A round is refused, writing nothing, when the protocol declares
  no `snowball_plan` in `pilot`/`systematic` (an `exploratory` round records `rule: none`), when
  the direction's maximum is reached, when the previous round of the direction yielded no included
  work and the plan says to stop (skipped, with a note, when that round is incomplete: a failed,
  partial or interrupted run, or a recorded query that never ran, so its retry is possible; the
  maximum still holds), while any corpus work can still be acted on at screening, while an
  included work has a document but no current extraction (ruling 18), when
  there is no candidate or no queryable candidate, when a query does not fit its source, or when
  the protocol gate refuses (always asked; the round's texts waived).
- `snowball.round_started` is written before any query is registered; each query is then
  registered naming the round (`query.registered` refs end with the round id; only such a query
  has the round's texts waived and counts as the round's run) and run, and a failed run does not
  stop the others. A retry is a new round. A forward round's chase round and its ledger entry
  are recorded together, in one append under the lock that computed the plan, before any of its
  queries (R-24), so no other round can be recorded in between and no chase round is left
  without its ledger entry.
- Ruling 18 blocks on the works someone can act on now: those pending at title/abstract (queued or
  in disagreement), and the promoted works pending at full text that have a converted or still
  convertible document. A promoted work with no obtainable document is neither included nor
  pending: it is listed `no-document` in `unextracted` and counted (`no_document`), never blocks,
  and blocks again only if a document arrives.
- The no-yield stop reads `round_yield`: a previous round with `included == 0` stops the
  direction; a new work counts once, as its dedup primary; a round without runs is unsettled.
- Candidates are never included: retrieved records enter the corpus as pending works.
- Counts (`cited_by_included`, new works, round numbers) are computed, never supplied.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.model.base import StrictModel
from factory.model.budgets import REQUESTS_SEARCH
from factory.model.chase import CHASE_CHUNK, ChaseDirection
from factory.model.project import RigorMode
from factory.model.protocol import ScreeningStage, SnowballPlan
from factory.model.references import (
    FORWARD_ROUND_RE,
    MAX_QUERY,
    BackwardSelection,
    CitingEntry,
    CoreSelection,
    Direction,
    ForwardSelection,
    LinkState,
    SnowballCandidate,
    SnowballRoundStarted,
    TakenCandidate,
    Unextracted,
    Via,
)
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import Work
from factory.model.work_ids import arxiv_id_from_doi
from factory.services.agreement import Outcome, cannot_assess_open, final_outcomes
from factory.services.budgets import budget_issues
from factory.services.calibration import calibration_items
from factory.services.chase import (
    ChaseStart,
    _forward_limit_issues,
    _pending_gate,
    chase_queries,
    chase_rounds,
    forward_chase_rounds,
    pending_ordinary,
    round_limit_issue,
    run_chase,
    start_chase,
    tolerated_within,
)
from factory.services.context import Project
from factory.services.core_works import forward_core_sources, seed_core_works
from factory.services.dedup import active_merges
from factory.services.document_read import default_conversion
from factory.services.gates import indexed_rigor_mode
from factory.services.progress import track
from factory.services.protocol import current_protocol, search_authorization
from factory.services.protocol_rules import snowball_plan_gaps
from factory.services.ranking import max_cosine_scores, order_by_score, reference_works
from factory.services.ranking_model import Embedder, Specter2Embedder
from factory.services.references import current_extraction, included_works
from factory.services.screening import background_works
from factory.services.search import (
    RunSummary,
    corpus_size,
    corpus_work_ids,
    get_work,
    list_works,
    query_issues,
    register_query,
    run_query,
    stored_works_by_ids,
)
from factory.sources.reflist import NAME as REFLIST
from factory.sources.reflist import ReflistEntry
from factory.sources.registry import SourceFactory, reflist_factory, stored_factory
from factory.sources.stored import NAME as STORED

NOT_EXTRACTED = "not-extracted"
NO_DOCUMENT = "no-document"
BACKGROUND_NOT_EXTRACTED = "background-not-extracted"
"""A work kept as background with a document and no extraction: listed, never blocking."""
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
    stored: bool = False
    """The candidate's work is stored (a lookup returned it): the round serves that record
    offline through the `stored` source (decision 135) instead of asking a network source."""
    published: date | None = None
    """The stored work's publication date, when it has one (the selection's date step)."""


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
    no_document: int = 0
    """How many of `unextracted` have no obtainable document: listed, never blocking."""
    tolerated_pending: list[str] = Field(default_factory=list)
    """Works pending or unextracted that the protocol's `pending_tolerance` lets the round go
    past (decision 138); recorded in the round's event."""


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
    no_document: int = 0
    tolerated_pending: list[str] = Field(default_factory=list)
    """The works the round went ahead without, within `pending_tolerance` (decision 138)."""
    chase_round_id: str | None = None
    """The delegated `search_chase` round of a recorded forward round."""
    selection: ForwardSelection | None = None
    """How a capped forward round chose its citing works; None for any other round."""
    backward_selection: BackwardSelection | None = None
    """How a selected backward round chose its candidates (decision 135), a dry run's included;
    None for any other round."""


class RecordedRound(StrictModel):
    """One recorded round, read back from the index, in event order."""

    round_id: str
    direction: Direction
    round_no: int
    event_id: str
    sources: list[str]
    unextracted: list[str]
    queries: list[str]
    extraction_ids: list[str] = Field(default_factory=list)
    chase_round_id: str | None = None
    selection: ForwardSelection | None = None
    """How a capped forward round chose its works (slice 8); None for any other round."""
    backward_selection: BackwardSelection | None = None
    """How a selected backward round chose its candidates (decision 135); None for any other."""


class RoundYield(StrictModel):
    """What a round's runs brought (R-23, R-25). `retrieved` counts their records (provenance
    rows); `new_after_dedup` the dedup primaries of those works that had no corpus record from an
    earlier run; `included` how many of these are INCLUDED at the last declared stage, or None
    while any of them is still pending there."""

    retrieved: int
    new_after_dedup: int
    included: int | None


class Comparison(StrictModel):
    """A backward round's resolved references against the `cited_by:` runs of the backward
    `search_chase` rounds from overlapping sources (`chase_rounds`); work ids (dedup primaries),
    sorted. A quality check on each mechanism, not a selection."""

    round_id: str
    chase_rounds: list[str]
    document_only: list[str]
    metadata_only: list[str]
    both: list[str]
    extra_chase_sources: list[str] = Field(default_factory=list)
    """Works the compared chase rounds started from that are not the round's sources: their
    `cited_by:` finds cannot be told apart, so they may show as `metadata_only`."""
    notes: list[str] = Field(default_factory=list)
    """E.g. a chase round recorded before its queries named it, whose runs are not compared."""


# --- Recorded rounds ---


def recorded_rounds(project: Project) -> list[RecordedRound]:
    """Every recorded snowball round, in event order."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT round_id, direction, round_no, event_id, sources, unextracted, "
                "extraction_ids, chase_round_id, selection FROM snowball_rounds ORDER BY event_id"
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
            extraction_ids=[str(x) for x in json.loads(str(extractions))],
            chase_round_id=None if chase is None else str(chase),
            selection=None
            if selection is None or Direction(str(direction)) is not Direction.FORWARD
            else ForwardSelection.model_validate_json(selection),
            backward_selection=None
            if selection is None or Direction(str(direction)) is not Direction.BACKWARD
            else BackwardSelection.model_validate_json(selection),
        )
        for (
            round_id,
            direction,
            round_no,
            event_id,
            sources,
            unextracted,
            extractions,
            chase,
            selection,
        ) in rows
    ]


def _recorded(project: Project, round_id: str) -> RecordedRound:
    """The recorded round `round_id`; refused when there is none."""
    found = next((r for r in recorded_rounds(project) if r.round_id == round_id), None)
    if found is None:
        raise FactoryValidationError([ValidationIssue("round_id", "not a recorded snowball round")])
    return found


def round_runs(project: Project, round_id: str) -> list[str]:
    """The runs of the queries registered for the round, sorted: queries whose
    `query.registered` refs name `round_id` (`register_query(..., round_id=...)`), or, for a
    forward round, name its delegated chase round."""
    return [run.run_id for run in _round_run_rows(project, round_id)]


class _RunRow(StrictModel):
    run_id: str
    status: RunStatus
    query_id: str


def _link_ref(project: Project, round_id: str) -> str:
    """The id a round's queries name in their refs: its chase round (forward) or itself."""
    with project.index.connect() as conn:
        chase = conn.execute(
            text("SELECT chase_round_id FROM snowball_rounds WHERE round_id = :r"),
            {"r": round_id},
        ).scalar_one_or_none()
    return round_id if chase is None else str(chase)


def _round_run_rows(project: Project, round_id: str) -> list[_RunRow]:
    project.index.sync()
    return _ref_runs(project, _link_ref(project, round_id))


def _ref_runs(project: Project, ref: str, *, text_prefix: str = "") -> list[_RunRow]:
    """The runs, sorted, of the queries whose `query.registered` refs name `ref` and whose text
    starts with `text_prefix`."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT r.run_id, r.status, r.query_id FROM runs r "
                "JOIN event_refs f ON f.type = 'query.registered' AND f.position = 0 "
                "AND f.ref = r.query_id "
                "JOIN queries q ON q.query_id = r.query_id "
                "WHERE EXISTS (SELECT 1 FROM event_refs n WHERE n.event_id = f.event_id "
                "AND n.position > 0 AND n.ref = :ref) "
                "AND substr(q.text, 1, :n) = :prefix ORDER BY r.run_id"
            ),
            {"ref": ref, "n": len(text_prefix), "prefix": text_prefix},
        ).all()
    return [
        _RunRow(run_id=str(run), status=RunStatus(str(status)), query_id=str(query))
        for run, status, query in rows
    ]


def _named_queries(project: Project, ref: str) -> int:
    """How many registered queries name `ref` in their `query.registered` refs."""
    with project.index.connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM event_refs WHERE type = 'query.registered' "
                "AND position > 0 AND ref = :ref"
            ),
            {"ref": ref},
        ).scalar_one()
    return int(count)


_UNFINISHED = (RunStatus.FAILED, RunStatus.PARTIAL, RunStatus.RUNNING)


def _incomplete(project: Project, recorded: RecordedRound) -> str | None:
    """Why a recorded round is incomplete, or None: a failed, partial or interrupted run, or a
    recorded query that never ran (the run step stopped)."""
    rows = _round_run_rows(project, recorded.round_id)
    unfinished = [r.run_id for r in rows if r.status in _UNFINISHED]
    ran = len({r.query_id for r in rows})
    facts: list[str] = []
    if unfinished:
        facts.append(f"{len(unfinished)} failed or partial (or interrupted) runs")
    if ran < len(recorded.queries):
        facts.append(f"only {ran} of {len(recorded.queries)} queries ran")
    if not facts:
        return None
    return (
        f"{recorded.round_id}: {'; '.join(facts)}; the no-yield stop does not apply to its retry "
        "(the round maximum does)"
    )


def _primaries(project: Project) -> dict[str, str]:
    """Absorbed work -> its primary, for the active merges."""
    return {absorbed: m.primary for m in active_merges(project) for absorbed in m.absorbed}


def _retrieved(project: Project, runs: Sequence[str]) -> list[str]:
    """The work of every provenance row of `runs` (one per record)."""
    with project.index.connect() as conn:
        return [
            str(row[0])
            for run in runs
            for row in conn.execute(
                text("SELECT work_id FROM provenance WHERE run_id = :run"), {"run": run}
            ).all()
        ]


def _settled_included(project: Project, works: set[str]) -> int | None:
    """How many of `works` are INCLUDED at the last declared stage; None while any is pending
    there (at title/abstract, or at full text after promotion when full text is planned). A
    promoted work with no obtainable document is neither: it counts as not included, and does not
    keep the yield unsettled."""
    outcomes = final_outcomes(project)
    protocol = current_protocol(project)
    full_text = protocol is not None and protocol.spec.full_text_screening is not None
    ft = final_outcomes(project, stage=ScreeningStage.FULL_TEXT) if full_text else {}
    included = 0
    for work in works:
        outcome = outcomes.get(work, Outcome.PENDING)
        if full_text and outcome is Outcome.INCLUDED:
            outcome = ft.get(work, Outcome.PENDING)
            if outcome is Outcome.PENDING and not _has_document(project, work):
                continue
        if outcome is Outcome.PENDING:
            return None
        included += outcome is Outcome.INCLUDED
    return included


def round_yield(project: Project, round_id: str) -> RoundYield:
    """The yield of a recorded round, computed from its runs' provenance, the active merges and
    the final outcomes. A work is new after dedup when its primary had no corpus record from a
    run started earlier in the event log than the round's first run (by the position of the
    `search.run_started` events). A round without runs has not been settled: `included` is None.
    """
    project.index.sync()
    _recorded(project, round_id)
    runs = round_runs(project, round_id)
    if not runs:
        return RoundYield(retrieved=0, new_after_dedup=0, included=None)
    rows = _retrieved(project, runs)
    new = _new_after_dedup(project, runs, rows)
    return RoundYield(
        retrieved=len(rows), new_after_dedup=len(new), included=_settled_included(project, new)
    )


def query_yields(project: Project, round_id: str) -> dict[str, RoundYield]:
    """The yield of a recorded round per query (the PRISMA-S rows of the round), keyed by query
    id. Each work new after dedup counts once, under the query whose run retrieved it first (by
    run id), so the queries' `new_after_dedup` and settled `included` sum to `round_yield`'s.
    A query whose works are all settled has `included` set even while other queries' are not."""
    project.index.sync()
    _recorded(project, round_id)
    rows = _round_run_rows(project, round_id)
    if not rows:
        return {}
    runs = [r.run_id for r in rows]
    new = _new_after_dedup(project, runs, _retrieved(project, runs))
    primary = _primaries(project)
    retrieved: dict[str, int] = {}
    attributed: dict[str, set[str]] = {}
    seen: set[str] = set()
    for row in rows:
        works = _retrieved(project, [row.run_id])
        retrieved[row.query_id] = retrieved.get(row.query_id, 0) + len(works)
        mine = attributed.setdefault(row.query_id, set())
        for work in works:
            key = primary.get(work, work)
            if key in new and key not in seen:
                seen.add(key)
                mine.add(key)
    return {
        query: RoundYield(
            retrieved=retrieved[query],
            new_after_dedup=len(works),
            included=_settled_included(project, works),
        )
        for query, works in attributed.items()
    }


def _new_after_dedup(project: Project, runs: Sequence[str], rows: Sequence[str]) -> set[str]:
    """The dedup primaries of `rows` (works retrieved by `runs`) that had no corpus record from a
    run started earlier in the event log than the first of `runs`."""
    primary = _primaries(project)
    with project.index.connect() as conn:
        first = conn.execute(
            text(
                "SELECT MIN(rowid) FROM events WHERE type = 'search.run_started' "
                "AND json_extract(refs, '$[0]') IN (SELECT value FROM json_each(:runs))"
            ),
            {"runs": json.dumps(runs)},
        ).scalar_one()
        earlier = {
            primary.get(str(w), str(w))
            for (w,) in conn.execute(
                text(
                    "SELECT DISTINCT p.work_id FROM provenance p "
                    "JOIN queries q ON q.query_id = p.query_id "
                    "JOIN events e ON e.type = 'search.run_started' "
                    "AND json_extract(e.refs, '$[0]') = p.run_id "
                    "WHERE e.rowid < :first AND q.purpose != :probe"
                ),
                {"first": first, "probe": QueryPurpose.PROBE.value},
            ).all()
        }
    return {primary.get(w, w) for w in rows} - earlier


def snowball_compare(project: Project, round_id: str) -> Comparison:
    """A backward round's resolved references (the `resolved` links, as they stand now, of its
    recorded extractions) against the works the `cited_by:` runs of every backward chase round whose
    `from_works` overlap the round's sources retrieved; dedup primaries on both sides."""
    project.index.sync()
    recorded = _recorded(project, round_id)
    if recorded.direction is not Direction.BACKWARD:
        raise FactoryValidationError(
            [ValidationIssue("round_id", "a comparison is made for a backward round")]
        )
    primary = _primaries(project)
    with project.index.connect() as conn:
        document = {
            primary.get(str(w), str(w))
            for extraction in recorded.extraction_ids
            for (w,) in conn.execute(
                text(
                    "SELECT work_id FROM reference_links WHERE extraction_id = :x "
                    "AND state = :resolved AND work_id IS NOT NULL"
                ),
                {"x": extraction, "resolved": LinkState.RESOLVED.value},
            ).all()
        }
    sources = set(recorded.sources)
    chases = [
        c
        for c in chase_rounds(project)
        if ChaseDirection.BACKWARD in c.directions and sources & set(c.from_works)
    ]
    notes = [
        f"{c.round_id}: chase round predates run linking; not compared"
        for c in chases
        if c.queries and _named_queries(project, c.round_id) == 0
    ]
    runs = [
        r.run_id for c in chases for r in _ref_runs(project, c.round_id, text_prefix="cited_by:")
    ]
    metadata = {primary.get(w, w) for w in _retrieved(project, runs)}
    return Comparison(
        round_id=round_id,
        chase_rounds=sorted(c.round_id for c in chases),
        document_only=sorted(document - metadata),
        metadata_only=sorted(metadata - document),
        both=sorted(document & metadata),
        extra_chase_sources=sorted({w for c in chases for w in c.from_works} - sources),
        notes=sorted(notes),
    )


# --- Candidates and queries ---


def _extraction_rows(
    project: Project, extraction_ids: Sequence[str]
) -> tuple[Sequence[Any], Sequence[Any]]:
    """(`resolved` links, matched contexts) of the given live extractions, in stored order."""
    ids = {"ids": json.dumps(list(extraction_ids))}
    with project.index.connect() as conn:
        links = conn.execute(
            text(
                "SELECT l.extraction_id, l.ordinal, l.work_id, l.no_source_record "
                "FROM reference_links l JOIN reference_extractions x "
                "ON x.extraction_id = l.extraction_id AND x.live = 1 "
                "WHERE l.extraction_id IN (SELECT value FROM json_each(:ids)) "
                "AND l.state = :resolved AND l.work_id IS NOT NULL "
                "ORDER BY l.extraction_id, l.ordinal"
            ),
            {**ids, "resolved": LinkState.RESOLVED.value},
        ).all()
        contexts = conn.execute(
            text(
                "SELECT extraction_id, entry, citing_anchor FROM citation_contexts "
                "WHERE extraction_id IN (SELECT value FROM json_each(:ids)) "
                "AND state = 'matched' ORDER BY extraction_id, position"
            ),
            ids,
        ).all()
    return links, contexts


def snowball_candidates(project: Project, sources: Sequence[str]) -> list[RoundCandidate]:
    """Candidates drawn from the current extractions of `sources`: live `resolved` links whose
    work is not in the corpus, sorted by (-cited_by_included, work_key)."""
    project.index.sync()
    extractions = {
        rex: work for work in sources if (rex := current_extraction(project, work)) is not None
    }
    links, contexts = _extraction_rows(project, sorted(extractions))
    anchors: dict[tuple[str, int], list[str]] = {}
    for rex, entry, anchor in contexts:
        slot = (str(rex), int(entry))
        if str(anchor) not in anchors.setdefault(slot, []):
            anchors[slot].append(str(anchor))
    corpus = corpus_work_ids(project)
    groups: dict[str, list[tuple[str, int, bool]]] = {}
    for rex, ordinal, wid, flagged in links:
        if str(wid) not in corpus:
            groups.setdefault(str(wid), []).append((str(rex), int(ordinal), bool(flagged)))
    out: list[RoundCandidate] = []
    for wid, cites in groups.items():
        work = get_work(project, wid)
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
                stored=work is not None,
                published=None if work is None else work.dates.published,
            )
        )
    return sorted(out, key=lambda c: (-c.cited_by_included, c.work_key))


def _arxiv(arxiv: str | None, doi: str | None) -> str | None:
    return arxiv or (arxiv_id_from_doi(doi) if doi else None)


def selects_backward(rule: SnowballPlan | None) -> bool:
    """The plan sets a backward selection option, so its backward rounds are selected rounds."""
    return rule is not None and (
        rule.backward_published_from is not None
        or rule.backward_min_cited_by is not None
        or rule.backward_min_similarity is not None
    )


def _route(candidate: RoundCandidate, selected: bool = False) -> tuple[str, str] | None:
    """(query family, id) naming the candidate, or None when no query can name it: no usable
    identifier, a DOI the filter syntax cannot carry, or an id too long for one query. Only in a
    `selected` backward round is a stored candidate served offline from its stored record
    (decision 135); otherwise it is asked of a network source as before."""
    route: tuple[str, str] | None = None
    if candidate.no_source_record:
        route = "reflist", candidate.work_key
    elif selected and candidate.stored and candidate.work_id is not None:
        route = "stored", candidate.work_id
    elif candidate.openalex:
        route = "openalex", candidate.openalex
    elif candidate.arxiv:
        route = "arxiv", candidate.arxiv
    elif candidate.doi and not any(sep in candidate.doi for sep in "|,"):
        route = "doi", candidate.doi
    if route is None or len(_PREFIX[route[0]]) + len(route[1]) > MAX_QUERY:
        return None
    return route


def unqueryable_keys(candidates: Sequence[RoundCandidate], selected: bool = False) -> list[str]:
    """Keys of the candidates no query can name, in the given order (listed, never dropped)."""
    return [c.work_key for c in candidates if _route(c, selected) is None]


_FAMILIES: tuple[tuple[str, str, QueryKind, str, str], ...] = (
    # family, source, kind, prefix, separator
    ("openalex", "openalex", QueryKind.FILTER, "openalex:", "|"),
    ("doi", "openalex", QueryKind.FILTER, "doi:", "|"),
    ("arxiv", "arxiv", QueryKind.ID_LIST, "", ","),
    ("reflist", REFLIST, QueryKind.ID_LIST, "", ","),
    ("stored", STORED, QueryKind.ID_LIST, "", ","),
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


def snowball_queries(
    candidates: Sequence[RoundCandidate], selected: bool = False
) -> list[QuerySpec]:
    """The chase-purpose queries that retrieve `candidates`: OpenAlex `openalex:` then `doi:`
    filters, arXiv `id_list`, then `reflist` entry keys; ids sorted within each family."""
    ids: dict[str, set[str]] = {family: set() for family, *_ in _FAMILIES}
    for candidate in candidates:
        route = _route(candidate, selected)
        if route is not None:
            ids[route[0]].add(route[1])
    return [
        QuerySpec(source=source, kind=kind, text=t, purpose=QueryPurpose.CHASE)
        for family, source, kind, prefix, separator in _FAMILIES
        for t in _pack(sorted(ids[family]), prefix, separator)
    ]


# --- Plan ---


def _named(ids: Sequence[str]) -> str:
    shown = ", ".join(ids[:MAX_LISTED])
    more = len(ids) - MAX_LISTED
    return shown + (f" and {more} more" if more > 0 else "")


def _promoted_pending(project: Project) -> set[str]:
    """Ordinary works promoted at title/abstract and pending at full text, when the protocol plans
    full text screening; else none. Calibration works are left out, and so are the works awaiting
    classification (an unresolved full-text cannot-assess, IDEA-49): they wait on the researcher's
    `factory screen resolve`, not on anyone who can screen or convert, so they never block."""
    protocol = current_protocol(project)
    if protocol is None or protocol.spec.full_text_screening is None:
        return set()
    promoted = {w for w, o in final_outcomes(project).items() if o is Outcome.INCLUDED}
    calibration = set(calibration_items(project, stage=ScreeningStage.FULL_TEXT))
    calibration |= set(cannot_assess_open(project, stage=ScreeningStage.FULL_TEXT))
    return {
        w
        for w, o in final_outcomes(project, stage=ScreeningStage.FULL_TEXT).items()
        if w in promoted and o is Outcome.PENDING and w not in calibration
    }


def _pending(project: Project) -> list[str]:
    """The ordinary works that block a round (ruling 18): pending at title/abstract, or promoted
    and pending at full text with a document someone can screen or convert now."""
    calibration = set(calibration_items(project))
    outcomes = final_outcomes(project)
    pending = {w for w, o in outcomes.items() if o is Outcome.PENDING and w not in calibration}
    pending |= {w for w in _promoted_pending(project) if _has_document(project, w)}
    return sorted(pending)


def _has_document(project: Project, work: str) -> bool:
    """Whether the work has a live document that is converted or still convertible: no recorded
    conversion failure and its raw file in the library. A raw-missing document cannot be converted
    until restored, so it is `no-document`, listed and counted, and blocks no round."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT d.raw_hash, "
                "(SELECT COUNT(*) FROM document_conversions c "
                "WHERE c.document_id = d.document_id), "
                "(SELECT COUNT(*) FROM document_failures f WHERE f.document_id = d.document_id) "
                "FROM fulltext_documents d WHERE d.work_id = :work AND d.superseded_by IS NULL"
            ),
            {"work": work},
        ).all()
    return any(
        int(converted) > 0 or (int(failed) == 0 and project.library.exists(str(raw)))
        for raw, converted, failed in rows
    )


def _scope(
    project: Project, *, background: bool = False
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """(sources, their current extraction ids, unextracted (work, reason)) of the included works;
    `unextracted` also lists the promoted works with no obtainable document (`NO_DOCUMENT`).

    With `background` (a backward round under a plan with `background_sources`), the works kept as
    background join: one with a current extraction is a source; one with a document and none is
    listed as `BACKGROUND_NOT_EXTRACTED`; one without a document is left out (IDEA-47).

    Order invariant: the included works come first, sorted, then the background works, sorted;
    the list is not sorted as a whole, and `extraction_ids` runs parallel to `sources`. Both are
    recorded as given in `SnowballRoundStarted`. No hash or digest is taken over `sources` in
    the code (the ledger and index store the lists as recorded), so the order is not
    hash-bearing; it is kept so that a round without background is unchanged."""
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
    unextracted += [
        (work, NO_DOCUMENT)
        for work in sorted(_promoted_pending(project))
        if not _has_document(project, work)
    ]
    if background:
        for work in sorted(background_works(project)):
            rex = current_extraction(project, work)
            if rex is not None:
                sources.append(work)
                extraction_ids.append(rex)
            elif default_conversion(project, work) is not None or _has_document(project, work):
                unextracted.append((work, BACKGROUND_NOT_EXTRACTED))
    return sources, extraction_ids, unextracted


def _openalex_ids(project: Project) -> dict[str, str]:
    """Corpus work -> its OpenAlex id, for the works that have one."""
    return {w.id: w.identifiers.openalex for w in list_works(project) if w.identifiers.openalex}


def _plan_rule(project: Project) -> SnowballPlan | None:
    protocol = current_protocol(project)
    return None if protocol is None else protocol.spec.snowball_plan


def _topic_suffix(rule: SnowballPlan | None) -> str:
    """The clause the plan's topic filter adds to a `cites:` text (OpenAlex comma-AND)."""
    if rule is None or rule.forward_topic_filter is None:
        return ""
    return f",title_and_abstract.search:{rule.forward_topic_filter}"


def _forward_queries(project: Project, chasable: Sequence[str]) -> list[QuerySpec]:
    """The forward chase specs `search_chase` builds for `chasable` (the source works with an
    OpenAlex id), each carrying the plan's topic filter when it has one."""
    openalex = _openalex_ids(project)
    suffix = _topic_suffix(_plan_rule(project))
    return [
        QuerySpec(
            source="openalex", kind=QueryKind.FILTER, text=t + suffix, purpose=QueryPurpose.CHASE
        )
        for t in chase_queries([ChaseDirection.FORWARD], [openalex[w] for w in chasable])
    ]


def plan_gaps(project: Project) -> list[ValidationIssue]:
    """The protocol's `snowball_plan` gaps under the project's current rigor mode."""
    project.index.sync()
    protocol = current_protocol(project)
    if protocol is None:
        return []
    return snowball_plan_gaps(protocol.spec, indexed_rigor_mode(project))


def plan_round(project: Project, direction: Direction) -> RoundPlan:
    """Plan a round of `direction` without writing anything: the stopping-rule state, sources,
    candidates, queries and the included works without a current extraction. A forward plan has
    no candidates; its sources and queries are those `search_chase` would use for `FORWARD`, and
    its `unqueryable` the included works without an OpenAlex id."""
    project.index.sync()
    protocol = current_protocol(project)
    rule = None if protocol is None else protocol.spec.snowball_plan
    mode = indexed_rigor_mode(project)
    previous = [r for r in recorded_rounds(project) if r.direction is direction]
    # A forward round is a chase round, and a standalone forward chase uses up a round as well.
    used = len(previous) if direction is Direction.BACKWARD else len(forward_chase_rounds(project))
    round_no = used + 1
    sources, extraction_ids, unextracted = _scope(
        project,
        background=direction is Direction.BACKWARD and rule is not None and rule.background_sources,
    )
    refusals: list[ValidationIssue] = []
    notes: list[str] = []

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
            refusals.append(round_limit_issue(round_no, maximum, direction.value))
        if rule.stop_when_no_new_included and previous:
            last = previous[-1]
            incomplete = _incomplete(project, last)
            if incomplete is not None:
                notes.append(incomplete)
            elif round_yield(project, last.round_id).included == 0:
                refusals.append(
                    ValidationIssue(
                        "previous_round",
                        f"{last.round_id} yielded no newly included work; the plan stops here",
                    )
                )
    tolerated: set[str] = set()
    pending = _pending(project)
    if pending:
        within = tolerated_within(project, pending, pending_ordinary(project)[1])
        if within:
            tolerated.update(within)
        else:
            refusals.append(
                ValidationIssue(
                    "screening", f"{len(pending)} works still pending: {_named(pending)}"
                )
            )
    blocking = [w for w, reason in unextracted if reason == NOT_EXTRACTED]
    if blocking:
        size = len(blocking) + sum(
            current_extraction(project, w) is not None for w in included_works(project)
        )
        within = tolerated_within(project, blocking, size)
        if within:
            tolerated.update(within)
        else:
            refusals.append(
                ValidationIssue(
                    "unextracted",
                    f"included works with a document and no current extraction: {_named(blocking)}",
                )
            )
    if direction is Direction.BACKWARD:
        candidates = snowball_candidates(project, sources)
        selected = selects_backward(rule)
        queries = snowball_queries(candidates, selected)
        unqueryable = unqueryable_keys(candidates, selected)
        if not candidates:
            refusals.append(
                ValidationIssue("candidates", "no resolved reference outside the corpus")
            )
        elif not queries:
            refusals.append(ValidationIssue("candidates", "no queryable candidate"))
    else:
        candidates = []
        openalex = _openalex_ids(project)
        core_only = rule is not None and rule.forward_core_only
        pool = (
            forward_core_sources(project, included_works(project))
            if core_only
            else included_works(project)
        )
        sources = [w for w in pool if w in openalex]
        unqueryable = [w for w in pool if w not in openalex]
        extraction_ids = []
        queries = _forward_queries(project, sources)
        if not sources:
            refusals.append(
                ValidationIssue(
                    "sources",
                    "no core work with an OpenAlex id"
                    if core_only
                    else "no included work with an OpenAlex id",
                )
            )
        if rule is not None and rule.forward_max_per_work is not None:
            notes.append(
                f"capped at {rule.forward_max_per_work} citing works per source work, ordered by "
                "similarity to the development seeds; the citing works are fetched and chosen "
                "when the round runs, so this plan lists the unchosen cites: queries"
            )
        if any(FORWARD_ROUND_RE.fullmatch(q.text) is None for q in queries):
            refusals.append(
                ValidationIssue("queries", "an OpenAlex id does not fit a forward chase text")
            )
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
        no_document=_no_document(unextracted),
        tolerated_pending=sorted(tolerated),
    )


# --- The round ---


def round_sources(
    project: Project, sources: Mapping[str, SourceFactory]
) -> dict[str, SourceFactory]:
    """`sources` with the offline `reflist` and `stored` sources bound to this project, unless
    one is given."""
    out = dict(sources)
    out.setdefault(REFLIST, reflist_factory(lambda keys: reflist_entries(project, keys)))
    out.setdefault(STORED, stored_factory(lambda ids: stored_works(project, ids)))
    return out


def stored_works(project: Project, ids: Sequence[str]) -> dict[str, Work]:
    """The stored works among `ids` (probe-only ones included), keyed by work id."""
    return {w.id: w for w in stored_works_by_ids(project, ids)}


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
    embedder: Embedder | None = None,
) -> RoundResult:
    """Plan a round (`dry_run`, the default, writes nothing), or record and run it.

    A recorded round is validated in full first (see the module invariants) and refused with
    every issue at once. Under the same lock as the plan, a backward round writes
    `snowball.round_started`; a forward round starts its `search_chase` round (`start_chase`,
    `FORWARD`, from the plan's source works) and records it together with the
    `snowball.round_started` naming it. The lock is then released and the queries are registered
    and run in order (`run_chase` for a forward round).

    A forward round under `forward_max_per_work` first chooses its citing works (`_pick_forward`,
    outside the lock; `embedder` defaults to the SPECTER2 ranker, refused with the remedy when its
    extra or weights are missing) and its chase texts are the chosen works' `openalex:` filters.
    """
    adapters = round_sources(project, sources)
    chase: ChaseStart | None = None
    picked: _Picked | None = None
    chosen: _Chosen | None = None
    if direction is Direction.FORWARD and not dry_run:
        picked = _pick_forward(project, actor, adapters, embedder)
    if direction is Direction.BACKWARD:
        chosen = _choose_backward(project, embedder)
    with project.index.exclusive():
        plan = plan_round(project, direction)
        if chosen is not None:
            plan = _apply_chosen(project, plan, chosen)
        if dry_run:
            return _result(plan, None, [], 0, None if chosen is None else chosen.selection)
        if picked is not None and picked.sources != plan.sources:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "sources",
                        "the source works changed while citing works were fetched; run the "
                        "round again",
                    )
                ]
            )
        if picked is not None:
            now_refs = tuple(w.id for w in reference_works(project)[0])
            if (
                now_refs != picked.references
                or picked.weights_hash != picked.selection.weights_hash
            ):
                raise FactoryValidationError(
                    [
                        ValidationIssue(
                            "seeds",
                            "the reference seeds or the ranker's weights changed while citing "
                            "works were ranked; rank again by running the round again",
                        )
                    ]
                )
        issues = list(plan.state.refusals)
        specs = plan.queries if picked is None else picked.specs
        issues += [issue for spec in specs for issue in query_issues(project, spec, adapters)]
        # The gate is always asked. Every gate except the planned-query waiver is
        # text-independent, and the waiver holds for every text of the round (as in
        # `search_chase`), so the first spec stands for all; with no spec (already refused
        # above) a placeholder chase spec still reports the text-independent gates.
        probe = specs[0] if specs else _GATE_PLACEHOLDER
        texts = [spec.text for spec in specs] or [probe.text]
        issues += search_authorization(project, probe, deviation_id=None, pending_round_texts=texts)
        issues += budget_issues(project, actor, REQUESTS_SEARCH)
        if issues:
            raise FactoryValidationError(issues)
        before, _ = corpus_size(project)
        rule: SnowballPlan | Literal["none"] = (
            "none" if plan.state.rule is None else plan.state.rule
        )
        if direction is Direction.BACKWARD:
            payload = SnowballRoundStarted(
                round_id=project.ids.new("snw"),
                direction=direction,
                via=Via.DOCUMENT_REFERENCE_LIST,
                round_no=plan.state.round_no,
                sources=tuple(plan.sources),
                extraction_ids=tuple(plan.extraction_ids),
                candidates=tuple(
                    SnowballCandidate(
                        work_key=c.work_key,
                        cited_by=c.cited_by,
                        no_source_record=c.no_source_record,
                    )
                    for c in plan.candidates
                ),
                queries=tuple(spec.text for spec in specs),
                rule=rule,
                unextracted=_unextracted(plan),
                backward_selection=None if chosen is None else chosen.selection,
                tolerated_pending=tuple(plan.tolerated_pending),
            )
            project.record([_ledger_event(project, actor, payload)])
        else:
            # `start_chase` validates again (writing nothing on refusal); the chase round and
            # the ledger entry naming it are recorded together, under the lock of the plan.
            plan_rule = plan.state.rule
            core_only = plan_rule is not None and plan_rule.forward_core_only
            chase = start_chase(
                project,
                actor,
                [ChaseDirection.FORWARD],
                sources=sources,
                from_works=sorted([*plan.sources, *plan.unqueryable]),
                texts=(
                    [spec.text for spec in specs]
                    if picked is not None or _topic_suffix(plan_rule)
                    else None
                ),
                extra_sources=seed_core_works(project, development_only=True) if core_only else (),
            )
            payload = SnowballRoundStarted(
                round_id=project.ids.new("snw"),
                direction=direction,
                via=Via.SOURCE_METADATA,
                round_no=plan.state.round_no,
                sources=chase.payload.from_works,
                extraction_ids=(),
                candidates=(),
                queries=chase.payload.queries,
                chase_round_id=chase.payload.round_id,
                rule=rule,
                unextracted=_unextracted(plan),
                selection=None if picked is None else picked.selection,
                tolerated_pending=tuple(plan.tolerated_pending),
            )
            project.record([chase.event, _ledger_event(project, actor, payload)])

    if chase is not None:
        runs = run_chase(project, actor, chase, sources=sources)
    else:
        query_ids = [
            register_query(project, actor, spec, sources=adapters, round_id=payload.round_id)
            for spec in specs
        ]
        runs = []
        with track(
            project, "snowball", "backward round queries", unit="queries", total=len(query_ids)
        ) as reporter:
            for query_id in query_ids:
                runs.append(run_query(project, query_id, sources=adapters, actor=actor))
                reporter.update(len(runs))
    after, _ = corpus_size(project)
    result = _result(
        plan,
        payload.round_id,
        runs,
        after - before,
        None if chosen is None else chosen.selection,
    )
    if chase is None:
        return result
    update: dict[str, Any] = {"chase_round_id": chase.payload.round_id}
    if picked is not None:
        update |= {"selection": picked.selection, "queries": picked.specs}
    return result.model_copy(update=update)


@dataclass(frozen=True)
class _Picked:
    """A capped forward round's choice: the source works it was made for, the chase specs over
    the chosen works and the selection to record."""

    sources: list[str]
    specs: list[QuerySpec]
    selection: ForwardSelection
    references: tuple[str, ...]
    weights_hash: str


_OPENALEX_ID = re.compile(r"^W\d{1,15}$")


def _pick_forward(
    project: Project,
    actor: Actor,
    adapters: Mapping[str, SourceFactory],
    embedder: Embedder | None,
) -> _Picked | None:
    """Choose, for each source work of a forward round, its citing works to take, or None when the
    plan sets no cap. Writes only the probe runs that fetch the citing works' metadata.

    Refused, with nothing written, when the round does not plan, there is no development
    reference, the ranker is unavailable, the request budget is spent, the round limit or the
    pending screening or the search authorization refuses, or a probe query is invalid; all of
    these are checked before any fetch. A fetch that did not complete is refused (the counts would
    be wrong); its probe runs stay recorded.

    Each `CoreSelection.taken` counts the works taken for that core work. A citing work may cite
    several core works, so the counts can overlap and their sum is not the number of distinct
    works the round adds (the chase texts list each chosen work once)."""
    project.index.sync()
    rule = _plan_rule(project)
    if rule is None or rule.forward_max_per_work is None:
        return None
    cap = rule.forward_max_per_work
    ranker = embedder if embedder is not None else Specter2Embedder()
    identity = (ranker.model_id, ranker.weights_hash, ranker.software)
    plan = plan_round(project, Direction.FORWARD)
    if plan.state.refusals:
        raise FactoryValidationError(plan.state.refusals)
    references, _ = reference_works(project)
    if not references:
        raise FactoryValidationError(
            [ValidationIssue("seeds", "no development positive seed has a title")]
        )
    budget = budget_issues(project, actor, REQUESTS_SEARCH)
    if budget:
        raise FactoryValidationError(budget)
    openalex = _openalex_ids(project)
    held = set(openalex.values())
    suffix = _topic_suffix(rule)
    # Every refusal that does not depend on the fetched works comes before the first request.
    gate, _ = _pending_gate(project)
    gate += _forward_limit_issues(project, [ChaseDirection.FORWARD])
    gate += search_authorization(
        project,
        _GATE_PLACEHOLDER,
        deviation_id=None,
        pending_round_texts=[_GATE_PLACEHOLDER.text],
    )
    probes = {
        core: QuerySpec(
            source="openalex",
            kind=QueryKind.FILTER,
            text=f"cites:{openalex[core]}{suffix}",
            purpose=QueryPurpose.PROBE,
        )
        for core in plan.sources
    }
    for probe_spec in probes.values():
        gate += query_issues(project, probe_spec, adapters)
    if gate:
        raise FactoryValidationError(gate)
    probe_runs: list[str] = []
    matched: dict[str, int] = {}
    in_corpus: dict[str, int] = {}
    pools: dict[str, list[Work]] = {}
    for core in plan.sources:
        run = run_query(
            project,
            register_query(project, actor, probes[core], sources=adapters),
            sources=adapters,
            actor=actor,
        )
        probe_runs.append(run.run_id)
        if run.status is not RunStatus.COMPLETE:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "citing",
                        f"the citing works of {core} were not fetched in full "
                        f"({run.status.value}); run the round again",
                    )
                ]
            )
        project.index.sync()
        works = stored_works_by_ids(project, _retrieved(project, [run.run_id]))
        matched[core] = len(works)
        in_corpus[core] = sum(w.identifiers.openalex in held for w in works)
        pools[core] = [
            w
            for w in works
            if w.identifiers.openalex is not None
            and w.identifiers.openalex not in held
            and _OPENALEX_ID.fullmatch(w.identifiers.openalex)
        ]
    candidates = {w.id: w for pool in pools.values() for w in pool}
    ordered_candidates = [candidates[i] for i in sorted(candidates)]
    if candidates:
        with track(
            project,
            "ranking",
            "forward round: SPECTER2 embedding",
            unit="records",
            total=len(references) + len(ordered_candidates),
        ) as reporter:
            scores = max_cosine_scores(ranker, references, ordered_candidates, reporter.update)
    else:
        scores = {}
    taken: dict[str, list[str]] = {}
    chosen: set[str] = set()
    for core in plan.sources:
        order = order_by_score({w.id: scores[w.id] for w in pools[core]})[:cap]
        taken[core] = [work for work, _ in order]
        chosen.update(str(candidates[work].identifiers.openalex) for work in taken[core])
    if not chosen:
        raise FactoryValidationError(
            [ValidationIssue("citing", "no citing work to take: none matched or all are held")]
        )
    ids = sorted(chosen)
    specs = [
        QuerySpec(
            source="openalex",
            kind=QueryKind.FILTER,
            text="openalex:" + "|".join(ids[i : i + CHASE_CHUNK]),
            purpose=QueryPurpose.CHASE,
        )
        for i in range(0, len(ids), CHASE_CHUNK)
    ]
    selection = ForwardSelection(
        model_id=identity[0],
        weights_hash=identity[1],
        software=identity[2],
        max_per_work=cap,
        topic_filter=rule.forward_topic_filter,
        cores=tuple(
            CoreSelection(
                work_id=core,
                matched=matched[core],
                in_corpus=in_corpus[core],
                taken=len(taken[core]),
            )
            for core in plan.sources
        ),
        probe_runs=tuple(probe_runs),
    )
    return _Picked(
        sources=list(plan.sources),
        specs=specs,
        selection=selection,
        references=tuple(w.id for w in references),
        weights_hash=ranker.weights_hash,
    )


@dataclass(frozen=True)
class _Chosen:
    """A selected backward round's choice: the candidates it was made from (keys, in plan order),
    the ones taken, the selection to record and what it was ranked against."""

    considered: tuple[str, ...]
    taken: tuple[str, ...]
    selection: BackwardSelection
    references: tuple[str, ...]


def _choose_backward(project: Project, embedder: Embedder | None) -> _Chosen | None:
    """The candidates a selected backward round takes, or None when the plan sets no backward
    option (ruling 7: every candidate). Writes nothing.

    The steps run in this order, each on the survivors of the one before: publication on or after
    `backward_published_from` (a candidate with no known date is dropped and counted), cited by at
    least `backward_min_cited_by` source works, and a maximum cosine to the development seed
    references of at least `backward_min_similarity` (`services.ranking`; only the survivors are
    embedded; a candidate with no stored work, a `no-source-record` one, is dropped and counted as
    unscored, as an undated one is by the date step). The similarity step needs
    the ranker, and is refused with the remedy when its extra or weights are missing. A plan that
    refuses returns None here, so the refusal is reported by the plan itself. The embedding runs
    outside the write lock, so the caller compares the candidates and references again under it.
    A dry run with `backward_min_similarity` runs the embedder but writes no events. Stored records
    are served as stored (they may lack an abstract), only in selected rounds."""
    project.index.sync()
    rule = _plan_rule(project)
    if rule is None or not selects_backward(rule):
        return None
    plan = plan_round(project, Direction.BACKWARD)
    if plan.state.refusals:
        return None
    survivors = list(plan.candidates)
    considered = tuple(c.work_key for c in survivors)
    before_window = undated = low_cited = 0
    if rule.backward_published_from is not None:
        kept: list[RoundCandidate] = []
        for c in survivors:
            if c.published is None:
                undated += 1
            elif c.published < rule.backward_published_from:
                before_window += 1
            else:
                kept.append(c)
        survivors = kept
    if rule.backward_min_cited_by is not None:
        floor = rule.backward_min_cited_by
        low_cited = sum(c.cited_by_included < floor for c in survivors)
        survivors = [c for c in survivors if c.cited_by_included >= floor]
    unscored = low_similarity = 0
    scores: dict[str, float] = {}
    identity: tuple[str, str, str] | None = None
    references: tuple[str, ...] = ()
    if rule.backward_min_similarity is not None:
        threshold = rule.backward_min_similarity
        ranker = embedder if embedder is not None else Specter2Embedder()
        identity = (ranker.model_id, ranker.weights_hash, ranker.software)
        refs, _ = reference_works(project)
        if not refs:
            raise FactoryValidationError(
                [ValidationIssue("seeds", "no development positive seed has a title")]
            )
        references = tuple(w.id for w in refs)
        stored = [c for c in survivors if c.stored and c.work_id is not None]
        unscored = len(survivors) - len(stored)
        works = stored_works(project, [str(c.work_id) for c in stored])
        pool = [works[i] for i in sorted(works)]
        if pool:
            with track(
                project,
                "ranking",
                "backward round: SPECTER2 embedding",
                unit="records",
                total=len(refs) + len(pool),
            ) as reporter:
                by_work = max_cosine_scores(ranker, refs, pool, reporter.update)
        else:
            by_work = {}
        scores = {c.work_key: by_work[str(c.work_id)] for c in stored if str(c.work_id) in by_work}
        unscored += len(stored) - len(scores)
        kept = [c for c in stored if c.work_key in scores]
        low_similarity = sum(scores[c.work_key] < threshold for c in kept)
        survivors = [c for c in kept if scores[c.work_key] >= threshold]
    taken = tuple(
        TakenCandidate(
            work_key=c.work_key, cited_by=c.cited_by_included, score=scores.get(c.work_key)
        )
        for c in survivors
    )
    selection = BackwardSelection(
        published_from=rule.backward_published_from,
        min_cited_by=rule.backward_min_cited_by,
        min_similarity=rule.backward_min_similarity,
        model_id=None if identity is None else identity[0],
        weights_hash=None if identity is None else identity[1],
        software=None if identity is None else identity[2],
        considered=len(considered),
        dropped_before_window=before_window,
        dropped_undated=undated,
        dropped_cited_by=low_cited,
        dropped_unscored=unscored,
        dropped_similarity=low_similarity,
        taken=taken,
    )
    return _Chosen(
        considered=considered,
        taken=tuple(t.work_key for t in taken),
        selection=selection,
        references=references,
    )


def _apply_chosen(project: Project, plan: RoundPlan, chosen: _Chosen) -> RoundPlan:
    """`plan` narrowed to the chosen candidates, under the lock that computed it.

    Refused, writing nothing, when the candidates or the reference seeds changed since the choice
    was made, or when the selection took nothing. (The ranker's weights are not rechecked: only the
    seeds and the candidates are.) A plan that already
    refuses is returned as it is, so its refusals are reported."""
    if plan.state.refusals:
        return plan
    if tuple(c.work_key for c in plan.candidates) != chosen.considered:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "candidates",
                    "the candidates changed while they were ranked; run the round again",
                )
            ]
        )
    if chosen.selection.min_similarity is not None:
        now_refs = tuple(w.id for w in reference_works(project)[0])
        if now_refs != chosen.references:
            raise FactoryValidationError(
                [
                    ValidationIssue(
                        "seeds",
                        "the reference seeds changed while candidates "
                        "were ranked; rank again by running the round again",
                    )
                ]
            )
    taken = set(chosen.taken)
    candidates = [c for c in plan.candidates if c.work_key in taken]
    queries = snowball_queries(candidates, True)
    refusals = list(plan.state.refusals)
    if not candidates:
        refusals.append(ValidationIssue("candidates", "the selection took no candidate"))
    elif not queries:
        refusals.append(ValidationIssue("candidates", "no queryable candidate"))
    state = plan.state.model_copy(update={"refusals": refusals, "allowed": not refusals})
    return plan.model_copy(
        update={
            "candidates": candidates,
            "queries": queries,
            "unqueryable": unqueryable_keys(candidates, True),
            "state": state,
        }
    )


def _no_document(unextracted: Sequence[tuple[str, str]]) -> int:
    return sum(reason == NO_DOCUMENT for _, reason in unextracted)


def _unextracted(plan: RoundPlan) -> tuple[Unextracted, ...]:
    return tuple(Unextracted(work_id=w, reason=r) for w, r in plan.unextracted)


def _ledger_event(project: Project, actor: Actor, payload: SnowballRoundStarted) -> Event:
    """The `snowball.round_started` event; an agent's request is kept as the input blob."""
    input_blob = (
        project.blobs.put_json({"direction": payload.direction.value, "dry_run": False})
        if actor.kind == "agent"
        else None
    )
    return project.events.make(
        "snowball.round_started", payload, actor, refs=(payload.round_id,), input_blob=input_blob
    )


def _result(
    plan: RoundPlan,
    round_id: str | None,
    runs: list[RunSummary],
    new_works: int,
    backward_selection: BackwardSelection | None = None,
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
        no_document=plan.no_document,
        backward_selection=backward_selection,
        tolerated_pending=plan.tolerated_pending,
    )

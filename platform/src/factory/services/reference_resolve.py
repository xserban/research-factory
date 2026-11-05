"""Reference resolution, re-derivation of entry text, and decisions on links (slice 3a).

Resolution (`resolve_entries`) works on the entries of an extraction before it is recorded and
returns one `Resolution` per entry plus the probe-purpose runs it made. Ordered methods, the first
that yields a decision wins:
1. An identifier (DOI, arXiv id; a DataCite arXiv DOI counts as its arXiv id) is looked up among
   the corpus works, absorbed works mapped to their primary (`corpus-identifier`); else through
   probe-purpose lookups, arXiv `id_list` and OpenAlex `doi:` filters in chunks of at most
   `LOOKUP_CHUNK` (`lookup-identifier`). An entry with an arXiv id is asked of arXiv first; on a
   miss, a plain (non-DataCite) DOI it also states is asked of OpenAlex. An identifier no source
   returns gives a `no-source-record` work (ruling 8) when the entry has a parsed title and year,
   else `unresolved` / `not-found`. A DOI containing `|` or `,` cannot be carried by the OpenAlex
   filter syntax; it is never asked and is settled as not returned (no-source-record or
   not-found), not as a source error. An entry with an identifier is never title-matched: its
   stated identifier is authoritative, and a title match could only contradict it.
2. An entry without an identifier but with a parsed title is matched against the corpus
   (`corpus-title`), then through one probe OpenAlex `title.search` per entry (`lookup-title`).
3. Otherwise `unresolved`: `no-identifier-no-title`, `not-found`, or `source-error` when the
   lookup that would have answered failed (only the entries of that lookup are affected).
A work found by a lookup takes the corpus work's id when its identifiers name one (R-26).

Decisions (`decide_reference`) are validated in full before anything is written: the extraction
is live; the link's recorded state is `unconfirmed` or `ambiguous`; the work is the link's work or
one of its candidates; both quotes are verbatim (ruling 14a), the first in the entry text
re-derived from the pinned conversion (`entry_text`, checked against `entry_sha256`), the second
in the candidate's stored title or author line. A binding decision (`confirm`, `reject`) comes
from a human, or in `pilot` mode from an agent whose session has made no earlier decision or
proposal on the entry, seconding a recorded proposal, on a title-fuzzy (`unconfirmed`) link only,
and never once a human has made a binding decision on it (ruling 3: a human's decision is final
relative to agents). Proposals never change a link's state.

An entry keeps its identity across the extractions of a work through `entry_sha256`. A new
extraction takes over the latest human binding decision on each of its entries
(`carried_decisions`), so an agent cannot reopen it; an agent's decision or proposal does not
carry. A session that decided or proposed on the entry in any extraction of the work cannot
confirm it (`_deciding_sessions`). A human decision whose entry no longer exists in the work's live
extraction is reported by `lost_human_decisions`. A human withdraws a human decision, on any base,
with `clear`: an event like any other, after which the entry's decision neither folds nor carries.

No refusal echoes a named work.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import text

from factory.document.quotes import normalise_quote, quote_in_element
from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.model.project import RigorMode
from factory.model.references import (
    BINDING_DECISIONS,
    MAX_QUOTE,
    MAX_RATIONALE,
    CarriedDecision,
    Confidence,
    ConfirmedBy,
    Decision,
    DecisionQuote,
    LinkCandidate,
    LinkState,
    ReferenceEntry,
    ReferenceResolutionDecided,
    Resolution,
    UnresolvedReason,
)
from factory.model.search import QueryKind, QueryPurpose, QuerySpec, RunStatus
from factory.model.work import Work
from factory.model.work_ids import arxiv_id_from_doi, normalize_title, work_id
from factory.modules.contract import GatePolicy, PolicyKind
from factory.references.match import Candidate, Match, match_title
from factory.references.parse import PARSER_VERSION, RefFields, parse_bibliography
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.dedup import active_merges, canonical_works
from factory.services.gates import effective_policy
from factory.services.search import get_work, list_works, register_query, run_query
from factory.sources.registry import SourceFactory

LOOKUP_CHUNK = 50
TITLE_SEARCH_LIMIT = 10
MAX_TITLE_QUERY = 200

CORPUS_IDENTIFIER = "corpus-identifier"
LOOKUP_IDENTIFIER = "lookup-identifier"
CORPUS_TITLE = "corpus-title"
LOOKUP_TITLE = "lookup-title"
NO_SOURCE_RECORD = "no-source-record"


class Resolvable(Protocol):
    """What `resolve_entries` reads of an entry: an ordinal and the parsed fields of one record.

    `ReferenceEntry` (a bibliography entry) and `ImportResolvable` (an import record) both satisfy
    it, so the two share one resolver. Attributes are read-only.
    """

    @property
    def ordinal(self) -> int: ...
    @property
    def doi(self) -> str | None: ...
    @property
    def arxiv(self) -> str | None: ...
    @property
    def url(self) -> str | None: ...
    @property
    def year(self) -> int | None: ...
    @property
    def first_author(self) -> str | None: ...
    @property
    def title(self) -> str | None: ...
    @property
    def venue(self) -> str | None: ...


def entry_raw(anchor_text: str) -> str:
    """The whitespace-normalised raw text of an entry: the form `entry_sha256` is taken over."""
    return " ".join(anchor_text.split())


def entry_digest(raw: str) -> str:
    """`entry_sha256`: the SHA-256 hex digest of the whitespace-normalised entry text."""
    return hashlib.sha256(entry_raw(raw).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResolutionOutcome:
    """One resolution per entry, ascending by ordinal, and the probe runs made, in order."""

    resolutions: tuple[Resolution, ...]
    lookup_runs: tuple[str, ...]


@dataclass
class Corpus:
    """Identifier keys of the corpus, mapped to the canonical work id, and title candidates."""

    by_doi: dict[str, str] = field(default_factory=dict)
    by_arxiv: dict[str, str] = field(default_factory=dict)
    candidates: list[Candidate] = field(default_factory=list)

    def find(self, arxiv: str | None, doi: str | None) -> str | None:
        if arxiv is not None and arxiv in self.by_arxiv:
            return self.by_arxiv[arxiv]
        if doi is not None and doi in self.by_doi:
            return self.by_doi[doi]
        return None


def _keys(doi: str | None, arxiv: str | None) -> tuple[str | None, str | None]:
    """(arXiv id, DOI) to look up: a DataCite arXiv DOI is its arXiv id and no DOI."""
    if doi is not None and (bridged := arxiv_id_from_doi(doi)) is not None:
        return arxiv or bridged, None
    return arxiv, doi


def _candidate(work: Work, work_id_: str | None = None) -> Candidate:
    return Candidate(
        work_id=work_id_ or work.id,
        title=work.title,
        first_author=work.authors[0].name if work.authors else None,
        year=work.dates.year,
        normalized=normalize_title(work.title),
    )


def load_corpus(project: Project) -> Corpus:
    """The corpus as `resolve_entries` matches against it. Probe lookups add nothing to it, so one
    load serves every work of an extraction call."""
    primary = {absorbed: m.primary for m in active_merges(project) for absorbed in m.absorbed}
    corpus = Corpus()
    for work in list_works(project):
        canonical = primary.get(work.id, work.id)
        arxiv, doi = _keys(work.identifiers.doi, work.identifiers.arxiv)
        if arxiv is not None:
            corpus.by_arxiv.setdefault(arxiv, canonical)
        if doi is not None:
            corpus.by_doi.setdefault(doi, canonical)
    corpus.candidates = [_candidate(w) for w in canonical_works(project)]
    return corpus


@dataclass(frozen=True)
class _Lookup:
    run_id: str | None
    status: RunStatus
    records: list[tuple[Work, str]]


def _lookup(
    project: Project, actor: Actor, spec: QuerySpec, sources: Mapping[str, SourceFactory]
) -> _Lookup:
    """Register and run one probe query; a source the caller does not provide is a failure."""
    if spec.source not in sources:
        return _Lookup(None, RunStatus.FAILED, [])
    query_id = register_query(project, actor, spec, sources=sources)
    run = run_query(project, query_id, sources=sources, actor=actor)
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT work_id, MIN(raw_blob) FROM provenance WHERE run_id = :run "
                "GROUP BY work_id ORDER BY work_id"
            ),
            {"run": run.run_id},
        ).all()
    records: list[tuple[Work, str]] = []
    for wid, blob in rows:
        work = get_work(project, str(wid))
        if work is not None:
            records.append((work, str(blob)))
    return _Lookup(run.run_id, run.status, records)


def _chunks(values: Sequence[str]) -> list[list[str]]:
    return [list(values[i : i + LOOKUP_CHUNK]) for i in range(0, len(values), LOOKUP_CHUNK)]


def _resolved(
    ordinal: int, wid: str, method: str, *, blob: str | None = None, no_source: bool = False
) -> Resolution:
    return Resolution(
        ordinal=ordinal,
        state=LinkState.RESOLVED,
        work_id=wid,
        method=method,
        confidence=Confidence.IDENTIFIER,
        score=1.0,
        source_blob=blob,
        no_source_record=no_source,
    )


def _unresolved(ordinal: int, reason: UnresolvedReason, method: str | None) -> Resolution:
    return Resolution(
        ordinal=ordinal,
        state=LinkState.UNRESOLVED,
        work_id=None,
        method=method,
        confidence=None,
        score=None,
        reason=reason,
    )


def _from_match(ordinal: int, match: Match, method: str, blob: str | None) -> Resolution:
    return Resolution(
        ordinal=ordinal,
        state=match.state,
        work_id=match.work_id,
        method=method,
        confidence=match.confidence,
        score=match.score,
        candidates=tuple(LinkCandidate(work_id=w, score=s) for w, s in match.candidates),
        source_blob=blob,
    )


def _fields(entry: Resolvable) -> RefFields:
    return RefFields(
        entry.doi,
        entry.arxiv,
        entry.url,
        entry.year,
        entry.first_author,
        entry.title,
        entry.venue,
    )


def resolve_entries(
    project: Project,
    actor: Actor,
    entries: Sequence[Resolvable],
    *,
    sources: Mapping[str, SourceFactory],
    corpus: Corpus,
) -> ResolutionOutcome:
    """Resolve `entries` by the ordered methods of the module docstring, against `corpus`
    (`load_corpus`).

    Lookups are probe-purpose queries, recorded as searches by `actor` and outside the corpus.
    Nothing else is written; the caller records the resolutions.
    """
    out: dict[int, Resolution] = {}
    runs: list[str] = []
    by_arxiv: dict[str, list[Resolvable]] = {}
    by_doi: dict[str, list[Resolvable]] = {}
    titled: list[Resolvable] = []
    arxiv_failed: set[int] = set()  # ordinals whose arXiv lookup failed before the DOI fallback
    for entry in entries:
        arxiv, doi = _keys(entry.doi, entry.arxiv)
        if arxiv is None and doi is None:
            titled.append(entry)
        elif (found := corpus.find(arxiv, doi)) is not None:
            out[entry.ordinal] = _resolved(entry.ordinal, found, CORPUS_IDENTIFIER)
        elif arxiv is not None:
            by_arxiv.setdefault(arxiv, []).append(entry)
        else:
            assert doi is not None
            by_doi.setdefault(doi, []).append(entry)

    def settle(
        waiting: dict[str, list[Resolvable]],
        key: str,
        hit: tuple[str, str] | None,
        failed: bool,
    ) -> None:
        for entry in waiting[key]:
            if hit is not None:
                out[entry.ordinal] = _resolved(
                    entry.ordinal, hit[0], LOOKUP_IDENTIFIER, blob=hit[1]
                )
            elif failed or entry.ordinal in arxiv_failed:
                out[entry.ordinal] = _unresolved(entry.ordinal, "source-error", LOOKUP_IDENTIFIER)
            elif entry.title is not None and entry.year is not None:
                no_source = work_id(
                    title=entry.title,
                    authors=[entry.first_author] if entry.first_author else [],
                    year=entry.year,
                    doi=entry.doi,
                    arxiv=entry.arxiv,
                )
                out[entry.ordinal] = _resolved(
                    entry.ordinal, no_source, NO_SOURCE_RECORD, no_source=True
                )
            else:
                out[entry.ordinal] = _unresolved(entry.ordinal, "not-found", LOOKUP_IDENTIFIER)

    def identity(work: Work) -> str:
        arxiv, doi = _keys(work.identifiers.doi, work.identifiers.arxiv)
        return corpus.find(arxiv, doi) or work.id

    for chunk in _chunks(sorted(by_arxiv)):
        spec = QuerySpec(
            source="arxiv", kind=QueryKind.ID_LIST, text=",".join(chunk), purpose=QueryPurpose.PROBE
        )
        result = _lookup(project, actor, spec, sources)
        runs += [result.run_id] if result.run_id else []
        hits: dict[str, tuple[str, str]] = {}
        for work, blob in result.records:
            key, _ = _keys(work.identifiers.doi, work.identifiers.arxiv)
            if key is not None:
                hits.setdefault(key, (identity(work), blob))
        for key in chunk:
            hit = hits.get(key)
            failed = result.status is not RunStatus.COMPLETE
            if hit is None:
                # an arXiv miss: an entry that also states a plain DOI is asked by its DOI
                rest: list[Resolvable] = []
                for entry in by_arxiv[key]:
                    _, doi = _keys(entry.doi, None)
                    if doi is not None:
                        by_doi.setdefault(doi, []).append(entry)
                        if failed:
                            arxiv_failed.add(entry.ordinal)
                    else:
                        rest.append(entry)
                by_arxiv[key] = rest
            settle(by_arxiv, key, hit, failed)

    queryable = sorted(d for d in by_doi if "|" not in d and "," not in d)
    for key in sorted(set(by_doi) - set(queryable)):
        # a DOI the filter syntax cannot carry is never asked; it is settled as not found
        settle(by_doi, key, None, False)
    for chunk in _chunks(queryable):
        spec = QuerySpec(
            source="openalex",
            kind=QueryKind.FILTER,
            text="doi:" + "|".join(chunk),
            purpose=QueryPurpose.PROBE,
        )
        result = _lookup(project, actor, spec, sources)
        runs += [result.run_id] if result.run_id else []
        hits = {}
        for work, blob in result.records:
            if work.identifiers.doi is not None:
                hits.setdefault(work.identifiers.doi, (identity(work), blob))
        for key in chunk:
            settle(by_doi, key, hits.get(key), result.status is not RunStatus.COMPLETE)

    for entry in titled:
        query = normalize_title(entry.title)[:MAX_TITLE_QUERY].strip() if entry.title else ""
        if not query:
            out[entry.ordinal] = _unresolved(entry.ordinal, "no-identifier-no-title", None)
            continue
        fields = _fields(entry)
        match = match_title(fields, corpus.candidates)
        if match.state is not LinkState.UNRESOLVED:
            out[entry.ordinal] = _from_match(entry.ordinal, match, CORPUS_TITLE, None)
            continue
        spec = QuerySpec(
            source="openalex",
            kind=QueryKind.FILTER,
            text=f"title.search:{query}",
            purpose=QueryPurpose.PROBE,
            limit=TITLE_SEARCH_LIMIT,
        )
        result = _lookup(project, actor, spec, sources)
        runs += [result.run_id] if result.run_id else []
        if result.status is RunStatus.FAILED:
            out[entry.ordinal] = _unresolved(entry.ordinal, "source-error", LOOKUP_TITLE)
            continue
        blobs: dict[str, str] = {}
        candidates: list[Candidate] = []
        for work, blob in result.records:
            wid = identity(work)
            if wid not in blobs:
                blobs[wid] = blob
                candidates.append(_candidate(work, wid))
        match = match_title(fields, candidates)
        if match.state is LinkState.UNRESOLVED:
            out[entry.ordinal] = _unresolved(entry.ordinal, "not-found", LOOKUP_TITLE)
        else:
            chosen = match.work_id or match.candidates[0][0]
            out[entry.ordinal] = _from_match(entry.ordinal, match, LOOKUP_TITLE, blobs[chosen])
    return ResolutionOutcome(
        resolutions=tuple(out[o] for o in sorted(out)),
        lookup_runs=tuple(dict.fromkeys(runs)),
    )


# --- Entry text, re-derived ---


def entry_text(project: Project, extraction_id: str, ordinal: int) -> str:
    """The whitespace-normalised text of one entry, re-derived from the pinned conversion.

    The extraction's conversion is read and verified (`conversion_manifest`), its bibliography
    parsed with the same parser version, and the entry's anchor and `entry_sha256` checked. Raises
    `FactoryValidationError` (field `ordinal`, `parser_version`, `anchor` or `entry_sha256`, or
    `conversion_id` from the conversion read) on any difference. Messages carry no entry text.
    """
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT x.conversion_id, x.parser_version, e.anchor, e.entry_sha256 "
                "FROM reference_extractions x JOIN reference_entries e "
                "ON e.extraction_id = x.extraction_id "
                "WHERE x.extraction_id = :rex AND e.ordinal = :ordinal"
            ),
            {"rex": extraction_id, "ordinal": ordinal},
        ).first()
    key = f"{extraction_id}:{ordinal}"
    if row is None:
        raise FactoryValidationError([ValidationIssue("ordinal", f"{key}: no such entry")])
    conversion_id, parser_version, anchor, digest = (str(v) for v in row)
    if parser_version != PARSER_VERSION:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "parser_version",
                    f"{key}: extracted with parser {parser_version}, this platform has "
                    f"{PARSER_VERSION}; re-extract the work",
                )
            ]
        )
    manifest = conversion_manifest(project, conversion_id)
    entry = next((e for e in parse_bibliography(manifest).entries if e.ordinal == ordinal), None)
    element = manifest.get(anchor)
    if entry is None or entry.anchor != anchor or element is None:
        raise FactoryValidationError(
            [ValidationIssue("anchor", f"{key}: the conversion no longer yields entry {anchor}")]
        )
    raw = entry_raw(element.text)
    if entry_digest(raw) != digest:
        raise FactoryValidationError(
            [
                ValidationIssue(
                    "entry_sha256",
                    f"{key}: the entry re-derived from {conversion_id} does not match its "
                    "recorded hash",
                )
            ]
        )
    return raw


# --- Decisions ---


@dataclass(frozen=True)
class _Link:
    live: bool
    base_state: LinkState
    base_work_id: str | None
    candidates: tuple[str, ...]
    confirmed_by: str | None
    """Who made the current binding decision (`human`, `second-agent`), None when there is none."""


def _link(project: Project, extraction_id: str, ordinal: int) -> _Link | None:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT x.live, l.base_state, l.base_work_id, l.candidates, l.confirmed_by "
                "FROM reference_links l JOIN reference_extractions x "
                "ON x.extraction_id = l.extraction_id "
                "WHERE l.extraction_id = :rex AND l.ordinal = :ordinal"
            ),
            {"rex": extraction_id, "ordinal": ordinal},
        ).first()
    if row is None:
        return None
    listed = tuple(str(c["work_id"]) for c in json.loads(str(row[3])))
    return _Link(
        live=bool(row[0]),
        base_state=LinkState(str(row[1])),
        base_work_id=None if row[2] is None else str(row[2]),
        candidates=listed,
        confirmed_by=None if row[4] is None else str(row[4]),
    )


def _has_proposal(project: Project, extraction_id: str, ordinal: int) -> bool:
    with project.index.connect() as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM reference_decisions WHERE extraction_id = :rex "
                "AND ordinal = :ordinal AND kind = 'proposal'"
            ),
            {"rex": extraction_id, "ordinal": ordinal},
        ).first()
    return row is not None


def _entry_key(extraction_id: str, ordinal: int) -> str:
    return f"{extraction_id}:{ordinal}"


def _deciding_sessions(project: Project, extraction_id: str, ordinal: int) -> set[str]:
    """Every session that recorded a decision or proposal on the entry, in any extraction of its
    work (the same `entry_sha256`; events are referenced by the entry key, so all of them are
    found, not only the latest)."""
    with project.index.connect() as conn:
        same_entry = conn.execute(
            text(
                "SELECT e.extraction_id, e.ordinal FROM reference_entries e "
                "JOIN reference_extractions x ON x.extraction_id = e.extraction_id "
                "WHERE x.work_id = (SELECT work_id FROM reference_extractions "
                "WHERE extraction_id = :rex) "
                "AND e.entry_sha256 = (SELECT entry_sha256 FROM reference_entries "
                "WHERE extraction_id = :rex AND ordinal = :ordinal)"
            ),
            {"rex": extraction_id, "ordinal": ordinal},
        ).all()
        keys = [_entry_key(str(rex), int(number)) for rex, number in same_entry]
        rows = conn.execute(
            text(
                "SELECT DISTINCT e.session FROM event_refs f JOIN events e ON e.id = f.event_id "
                "WHERE f.type = 'reference.resolution_decided' "
                "AND f.ref IN (SELECT value FROM json_each(:keys))"
            ),
            {"keys": json.dumps(keys)},
        ).all()
    return {str(row[0]) for row in rows}


def carried_decisions(
    project: Project, work_id: str, entries: Sequence[ReferenceEntry]
) -> tuple[CarriedDecision, ...]:
    """The latest human binding decision on each of `entries`, found by `entry_sha256` among the
    earlier extractions of `work_id`, ascending by ordinal. A decision carried once is carried
    on, under the human's own event."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT e.entry_sha256, d.extraction_id, d.ordinal, d.decision, d.work_id, "
                "d.event_id FROM reference_decisions d "
                "JOIN reference_entries e ON e.extraction_id = d.extraction_id "
                "AND e.ordinal = d.ordinal "
                "JOIN reference_extractions x ON x.extraction_id = d.extraction_id "
                "WHERE x.work_id = :work AND d.kind = 'binding' AND d.confirmed_by = 'human' "
                "ORDER BY d.event_id, d.extraction_id"
            ),
            {"work": work_id},
        ).all()
    latest = {str(row[0]): row for row in rows}
    return tuple(
        CarriedDecision(
            ordinal=entry.ordinal,
            decision=Decision(str(row[3])),
            work_id=None if row[4] is None else str(row[4]),
            from_extraction=str(row[1]),
            from_ordinal=int(row[2]),
            decided_event=str(row[5]),
        )
        for entry in entries
        if (row := latest.get(entry.entry_sha256)) is not None and row[3] != Decision.CLEAR.value
    )


def lost_human_decisions(project: Project) -> dict[str, int]:
    """Live extraction -> how many entries with a human binding decision in an earlier extraction
    of its work it no longer has (by `entry_sha256`). Extractions that lost none are absent."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT live.extraction_id, COUNT(DISTINCT e.entry_sha256) "
                "FROM reference_extractions live "
                "JOIN reference_extractions old ON old.work_id = live.work_id "
                "AND old.extraction_id != live.extraction_id "
                "JOIN reference_decisions d ON d.extraction_id = old.extraction_id "
                "AND d.kind = 'binding' AND d.confirmed_by = 'human' "
                "JOIN reference_entries e ON e.extraction_id = d.extraction_id "
                "AND e.ordinal = d.ordinal "
                "WHERE live.live = 1 AND d.decision != 'clear' "
                "AND e.entry_sha256 NOT IN (SELECT n.entry_sha256 "
                "FROM reference_entries n WHERE n.extraction_id = live.extraction_id) "
                "AND NOT EXISTS (SELECT 1 FROM reference_decisions c "
                "JOIN reference_entries ce ON ce.extraction_id = c.extraction_id "
                "AND ce.ordinal = c.ordinal "
                "JOIN reference_extractions cx ON cx.extraction_id = c.extraction_id "
                "WHERE cx.work_id = live.work_id AND ce.entry_sha256 = e.entry_sha256 "
                "AND c.kind = 'binding' AND c.decision = 'clear' AND c.event_id > d.event_id) "
                "GROUP BY live.extraction_id ORDER BY live.extraction_id"
            )
        ).all()
    return {str(rex): int(count) for rex, count in rows}


def _rigor_mode(project: Project) -> RigorMode:
    with project.index.connect() as conn:
        value = conn.execute(
            text("SELECT rigor_mode FROM project WHERE slug = :slug"),
            {"slug": project.paths.slug},
        ).scalar_one()
    return RigorMode(str(value))


def confirmer_ruling(
    actor: Actor,
    *,
    gate_id: str,
    policy: GatePolicy,
    base_state: LinkState,
    confirmed_by: str | None,
    has_proposal: bool,
    deciding_sessions: set[str],
) -> tuple[ConfirmedBy | None, list[ValidationIssue]]:
    """Who a binding decision by `actor` is recorded as, or why it is refused (ruling 3).

    The policy of slice-3a ruling 3, shared by reference links and import records: a human always;
    where the gate's policy is `agent_audit` (pilot by preset) a second agent, on a title-fuzzy
    (`unconfirmed`) link only, seconding a recorded proposal, from a session that made no earlier
    decision or proposal (`deciding_sessions`), and never once a human has decided.
    """
    if actor.kind == "human":
        return "human", []
    if actor.kind != "agent":
        return None, [ValidationIssue("actor", "only a human confirms or rejects a link")]
    reasons: list[str] = []
    if policy.kind is PolicyKind.HUMAN:
        reasons.append(f"gate {gate_id} is {policy.kind.value}: an agent may only propose")
    if base_state is not LinkState.UNCONFIRMED:
        reasons.append("a second agent decides title-fuzzy (unconfirmed) links only")
    if confirmed_by == "human":
        reasons.append("a human has decided this link; an agent cannot change that decision")
    if not has_proposal:
        reasons.append("a second agent decides only a recorded proposal")
    elif actor.session in deciding_sessions:
        reasons.append("a session that proposed or decided on this entry cannot confirm it")
    if reasons:
        return None, [ValidationIssue("decision", "; ".join(reasons))]
    return "second-agent", []


def _confirmer(
    project: Project, actor: Actor, extraction_id: str, ordinal: int, link: _Link
) -> tuple[ConfirmedBy | None, list[ValidationIssue]]:
    """`confirmer_ruling` for a reference link."""
    has_proposal = _has_proposal(project, extraction_id, ordinal)
    return confirmer_ruling(
        actor,
        gate_id="reference.link_confirm",
        policy=effective_policy(project, "reference.link_confirm", mode=_rigor_mode(project)),
        base_state=link.base_state,
        confirmed_by=link.confirmed_by,
        has_proposal=has_proposal,
        deciding_sessions=(
            _deciding_sessions(project, extraction_id, ordinal) if has_proposal else set()
        ),
    )


def _clear_issues(actor: Actor, link: _Link) -> list[ValidationIssue]:
    """Why `actor` may not clear the entry's decision: a human clears a human decision only."""
    if actor.kind != "human":
        return [ValidationIssue("decision", "only a human clears a decision")]
    if link.confirmed_by != "human":
        return [ValidationIssue("decision", "the entry has no human decision to clear")]
    return []


def _candidate_quote_ok(work: Work, quote: str) -> bool:
    needle = normalise_quote(quote)
    lines = (work.title, ", ".join(a.name for a in work.authors))
    return bool(needle) and any(needle in normalise_quote(line) for line in lines)


def _record_clear(
    project: Project, actor: Actor, extraction_id: str, ordinal: int, rationale: str
) -> None:
    payload = ReferenceResolutionDecided(
        extraction_id=extraction_id,
        ordinal=ordinal,
        decision=Decision.CLEAR,
        work_id=None,
        rationale=rationale,
        confirmed_by="human",
    )
    project.record(
        [
            project.events.make(
                "reference.resolution_decided",
                payload,
                actor,
                refs=(extraction_id, _entry_key(extraction_id, ordinal)),
            )
        ]
    )


def decide_reference(
    project: Project,
    actor: Actor,
    extraction_id: str,
    ordinal: int,
    decision: Decision,
    *,
    rationale: str,
    quotes: tuple[str, str],
    work_id: str | None = None,
) -> None:
    """Record one decision on a link; see the module docstring. Writes nothing when invalid.

    `quotes` is (entry quote, candidate quote). `work_id` defaults to the link's own work for an
    `unconfirmed` link; an `ambiguous` link's confirmation must name one of its candidates. A
    rejection's candidate quote is checked against the named work, else the link's work or first
    candidate. `clear` takes a rationale only: `quotes` and `work_id` are not read.
    """
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        if not rationale.strip():
            issues.append(ValidationIssue("rationale", "state the reason for the decision"))
        elif len(rationale) > MAX_RATIONALE:
            issues.append(ValidationIssue("rationale", f"at most {MAX_RATIONALE} characters"))
        link = _link(project, extraction_id, ordinal)
        if link is None:
            issues.append(ValidationIssue("ordinal", f"{extraction_id}:{ordinal}: no such link"))
            raise FactoryValidationError(issues)
        if not link.live:
            issues.append(
                ValidationIssue("extraction_id", f"{extraction_id}: superseded by a later one")
            )
        decided = link.confirmed_by is not None  # a decided link stays decidable by a human
        if link.base_state not in (LinkState.UNCONFIRMED, LinkState.AMBIGUOUS) and not decided:
            issues.append(
                ValidationIssue(
                    "ordinal",
                    f"{extraction_id}:{ordinal}: the link is {link.base_state.value}; only "
                    "unconfirmed or ambiguous links are decided",
                )
            )
        if decision is Decision.CLEAR:
            issues += _clear_issues(actor, link)
            if issues:
                raise FactoryValidationError(issues)
            _record_clear(project, actor, extraction_id, ordinal, rationale)
            return
        options = tuple(
            dict.fromkeys(w for w in (link.base_work_id, *link.candidates) if w is not None)
        )
        target = work_id
        if target is None and link.base_state is LinkState.UNCONFIRMED:
            target = link.base_work_id
        if target is None and decision in (Decision.CONFIRM, Decision.PROPOSE_CONFIRM):
            issues.append(ValidationIssue("work_id", "a confirmation names the work it confirms"))
        if target is not None and target not in options:
            issues.append(ValidationIssue("work_id", "not a candidate of this link"))
        confirmed_by: ConfirmedBy | None = None
        if decision in BINDING_DECISIONS:
            confirmed_by, refused = _confirmer(project, actor, extraction_id, ordinal, link)
            issues += refused
        if issues:
            raise FactoryValidationError(issues)

        entry_quote, candidate_quote = quotes
        raw = entry_text(project, extraction_id, ordinal)
        if len(entry_quote) > MAX_QUOTE or not quote_in_element(raw, entry_quote):
            issues.append(
                ValidationIssue("quotes", "the entry quote is not a verbatim part of the entry")
            )
        quoted = target or (options[0] if options else None)
        work = None if quoted is None else get_work(project, quoted)
        if work is None:
            issues.append(ValidationIssue("work_id", "the candidate work is not stored"))
        elif len(candidate_quote) > MAX_QUOTE or not _candidate_quote_ok(work, candidate_quote):
            issues.append(
                ValidationIssue(
                    "quotes",
                    "the candidate quote is not a verbatim part of the candidate's title or "
                    "author line",
                )
            )
        if issues:
            raise FactoryValidationError(issues)

        payload = ReferenceResolutionDecided(
            extraction_id=extraction_id,
            ordinal=ordinal,
            decision=decision,
            work_id=target,
            rationale=rationale,
            quotes=(
                DecisionQuote(side="entry", text=entry_quote),
                DecisionQuote(side="candidate", text=candidate_quote),
            ),
            confirmed_by=confirmed_by,
        )
        input_blob = (
            project.blobs.put_json(
                {
                    "extraction_id": extraction_id,
                    "ordinal": ordinal,
                    "decision": decision.value,
                    "work_id": work_id,
                    "rationale": rationale,
                    "quotes": list(quotes),
                }
            )
            if actor.kind == "agent"
            else None
        )
        project.record(
            [
                project.events.make(
                    "reference.resolution_decided",
                    payload,
                    actor,
                    refs=(extraction_id, _entry_key(extraction_id, ordinal)),
                    input_blob=input_blob,
                )
            ]
        )

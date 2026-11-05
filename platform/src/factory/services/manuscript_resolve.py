"""Citation resolution of external manuscripts (slice 7b, plan W-C rulings 3 and 4).

Declares: `GATE`, `resolve_citations`, `decide_citation`. The only module that writes
`manuscript.citation_resolved`, `manuscript.citation_decided` and `manuscript.unit_closed`.

A key's record comes from the companion bibliography, else from the manuscript's reference list.
It is matched offline, with G1's corpus and matcher: a stated identifier found among the works
resolves; else `references.match.match_title`, whose `resolved` resolves and whose `unconfirmed` is
`proposed`. A stated identifier is authoritative, so a title match beside an identifier no work
holds is at most `proposed`: a preprint and its published version often differ in identifiers, and
only a human can say they are one work.

Invariants:
- A proposed citation makes no unit and no closure until a human decides it (slice 3a ruling 3).
  No second agent confirms it: the manuscript is not the project's evidence.
- Closures are computed, never an agent's verdict. A key not resolved closes `citation-unresolved`;
  a work outside the corpus `source-not-in-corpus`; a corpus work with no conversion a tool may
  serve, because it has none or was not promoted, `no-full-text`.
- Running again is idempotent: only what changed is written. A work acquired since lifts its
  closures, by a new resolution of the key.
- A human's decision stands: a later run changes neither its state nor its work.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.model.manuscripts import (
    CitationDecided,
    CitationDecision,
    CitationMethod,
    CitationResolved,
    CitationRow,
    CitationState,
    CloseReason,
    ClosureRow,
    ManuscriptRow,
    ResolutionSummary,
    SentenceRow,
    UnitClosed,
)
from factory.model.references import LinkState
from factory.model.screening import Channel
from factory.references.match import match_title
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.document_read import default_conversion, promoted_works
from factory.services.gates import gate_issues
from factory.services.manuscripts import (
    citation_rows,
    closure_rows,
    format_of,
    library_text,
    manuscript_text,
    read_bibliography,
    require_manuscript,
    sentence_rows,
)
from factory.services.reference_resolve import Corpus, _candidate, _keys, load_corpus
from factory.services.search import list_works
from factory.writing.bibfile import BibFileError, BibRecord, read_reference_list
from factory.writing.segment import reference_span

GATE = "manuscript.citation_confirm"


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


@dataclass(frozen=True)
class _Match:
    state: CitationState
    work_id: str | None
    method: CitationMethod
    score: float | None


@dataclass
class _Works:
    """What a citation can name: the corpus, and the stored works outside it."""

    corpus: Corpus
    outside: Corpus
    corpus_ids: frozenset[str]
    promoted: frozenset[str]


def _works(project: Project) -> _Works:
    corpus = load_corpus(project)
    known = {c.work_id for c in corpus.candidates}
    known |= set(corpus.by_doi.values()) | set(corpus.by_arxiv.values())
    in_corpus = {w.id for w in list_works(project)}  # absorbed works too
    outside = Corpus()
    for work in list_works(project, include_probe=True):
        if work.id in in_corpus:
            continue
        arxiv, doi = _keys(work.identifiers.doi, work.identifiers.arxiv)
        if arxiv is not None:
            outside.by_arxiv.setdefault(arxiv, work.id)
        if doi is not None:
            outside.by_doi.setdefault(doi, work.id)
        outside.candidates.append(_candidate(work))
    return _Works(corpus, outside, frozenset(known), promoted_works(project))


def _records(project: Project, row: ManuscriptRow, keys: Sequence[str]) -> dict[str, BibRecord]:
    """The record of each key: the companion bibliography first, then the reference list."""
    body = manuscript_text(project, row)
    fmt = format_of(row.format)
    span = reference_span(body, fmt)
    records: dict[str, BibRecord] = {}
    if span is not None:
        listed = read_reference_list(body[span[0] : span[1]], fmt, keys)
        records.update({r.key: r for r in listed})
    if row.bib_hash is not None and row.bib_format is not None:
        try:
            read = read_bibliography(library_text(project, row.bib_hash), row.bib_format)
        except BibFileError:
            raise _refuse("bib", "the stored bibliography cannot be read") from None
        records.update({r.key: r for r in read})
    return records


def _by_title(record: BibRecord, corpus: Corpus, identified: bool) -> _Match | None:
    """The match of a record's title in `corpus`, or None when it holds nothing near it."""
    found = match_title(record.fields, corpus.candidates)
    if found.state is LinkState.RESOLVED:
        state = CitationState.PROPOSED if identified else CitationState.RESOLVED
        return _Match(state, found.work_id, CitationMethod.TITLE_EXACT, found.score)
    if found.state is LinkState.UNCONFIRMED:
        return _Match(
            CitationState.PROPOSED, found.work_id, CitationMethod.TITLE_FUZZY, found.score
        )
    if found.state is LinkState.AMBIGUOUS:
        return _Match(CitationState.UNRESOLVED, None, CitationMethod.AMBIGUOUS, None)
    return None


def _match(record: BibRecord | None, works: _Works) -> _Match:
    if record is None:
        return _Match(CitationState.UNRESOLVED, None, CitationMethod.NO_RECORD, None)
    arxiv, doi = _keys(record.doi, record.arxiv)
    found = works.corpus.find(arxiv, doi) or works.outside.find(arxiv, doi)
    if found is not None:
        return _Match(CitationState.RESOLVED, found, CitationMethod.IDENTIFIER, 1.0)
    identified = arxiv is not None or doi is not None
    for corpus in (works.corpus, works.outside):
        match = _by_title(record, corpus, identified)
        if match is not None:
            return match
    method = CitationMethod.NO_MATCH if record.title else CitationMethod.NO_TITLE
    return _Match(CitationState.UNRESOLVED, None, method, None)


def _reason(
    project: Project, state: CitationState, work: str | None, works: _Works
) -> CloseReason | None:
    """Why a key in this state closes its units, or None when it leaves them open or waiting."""
    if state is CitationState.PROPOSED:
        return None
    if state is CitationState.UNRESOLVED or work is None:
        return CloseReason.CITATION_UNRESOLVED
    if work not in works.corpus_ids:
        return CloseReason.SOURCE_NOT_IN_CORPUS
    if work not in works.promoted or default_conversion(project, work) is None:
        return CloseReason.NO_FULL_TEXT
    return None


def _closure_events(
    project: Project,
    manuscript_id: str,
    key: str,
    ordinals: Sequence[int],
    work: str | None,
    reason: CloseReason,
) -> list[Event]:
    return [
        project.events.make(
            "manuscript.unit_closed",
            UnitClosed(
                manuscript_id=manuscript_id, ordinal=o, key=key, work_id=work, reason=reason
            ),
            project.system_actor(),
            refs=[manuscript_id],
        )
        for o in ordinals
    ]


def _ordinals(sentences: Sequence[SentenceRow], key: str) -> list[int]:
    return [s.ordinal for s in sentences if key in s.keys]


def _key_events(
    project: Project,
    manuscript_id: str,
    key: str,
    match: _Match,
    current: CitationRow | None,
    reason: CloseReason | None,
    ordinals: Sequence[int],
    closed: dict[int, ClosureRow],
) -> list[Event]:
    """What brings one key to `match`, its units closed for `reason`: nothing when it is there. A
    resolution lifts the key's closures, so it is followed by all of them; else only the missing
    ones are written."""
    want = {o: (match.work_id, reason) for o in ordinals} if reason is not None else {}
    stale = any(want.get(o) != (c.work_id, c.reason) for o, c in closed.items())
    changed = current is None or (
        current.decision is None
        and (current.state, current.work_id, current.method, current.score)
        != (match.state, match.work_id, match.method, match.score)
    )
    events: list[Event] = []
    if changed or stale:
        payload = CitationResolved(
            manuscript_id=manuscript_id,
            key=key,
            work_id=match.work_id,
            method=match.method,
            score=match.score,
            state=match.state,
        )
        refs = [manuscript_id] if match.work_id is None else [manuscript_id, match.work_id]
        events.append(
            project.events.make(
                "manuscript.citation_resolved", payload, project.system_actor(), refs=refs
            )
        )
    missing = list(want) if changed or stale else [o for o in want if o not in closed]
    if reason is not None and missing:
        events.extend(_closure_events(project, manuscript_id, key, missing, match.work_id, reason))
    return events


def _of_row(row: CitationRow) -> _Match:
    return _Match(row.state, row.work_id, row.method, row.score)


def resolve_citations(project: Project, manuscript_id: str) -> ResolutionSummary:
    """Resolve every key the sentences cite and close the units that cannot be verified. Refused,
    with nothing written, for an unknown manuscript or one whose text is not in this library."""
    with project.index.exclusive(), entering():
        project.index.sync()
        row = require_manuscript(project, manuscript_id)
        sentences = sentence_rows(project, manuscript_id)
        keys = list(dict.fromkeys(k for s in sentences for k in s.keys))
        records = _records(project, row, keys)
        works = _works(project)
        citations = citation_rows(project, manuscript_id)
        closures = closure_rows(project, manuscript_id)
        events: list[Event] = []
        for key in keys:
            current = citations.get(key)
            decided = current is not None and current.decision is not None
            match = (
                _of_row(current)
                if current is not None and decided
                else _match(records.get(key), works)
            )
            closed = {o: c for (o, k), c in closures.items() if k == key}
            events.extend(
                _key_events(
                    project,
                    manuscript_id,
                    key,
                    match,
                    current,
                    _reason(project, match.state, match.work_id, works),
                    _ordinals(sentences, key),
                    closed,
                )
            )
        if events:
            project.record(events)
        states = [c.state for c in citation_rows(project, manuscript_id).values()]
        return ResolutionSummary(
            resolved=states.count(CitationState.RESOLVED),
            proposed=states.count(CitationState.PROPOSED),
            unresolved=states.count(CitationState.UNRESOLVED),
            closed=len(closure_rows(project, manuscript_id)),
        )


def decide_citation(
    project: Project,
    manuscript_id: str,
    key: str,
    decision: CitationDecision,
    *,
    actor: Actor,
    channel: Channel = Channel.CLI,
) -> str:
    """A human's decision on a proposed citation, with the closures that follow from it, and return
    the event id. Refused, with nothing written: anyone but a human (`actor`), whatever the gate's
    policy, as the spec gives this act to a human; a relay from a pass session (`channel`); an
    unknown manuscript; a key that is not proposed or was decided (`key`)."""
    with project.index.exclusive(), entering():
        project.index.sync()
        issues = gate_issues(project, actor, GATE, channel=channel)
        if actor.kind != "human" and not any(i.field == "actor" for i in issues):
            issues.append(ValidationIssue("actor", "a fuzzy citation is decided by a human"))
        if issues:
            raise FactoryValidationError(issues)
        require_manuscript(project, manuscript_id)
        current = citation_rows(project, manuscript_id).get(key)
        if (
            current is None
            or current.state is not CitationState.PROPOSED
            or current.decision is not None
        ):
            raise _refuse("key", "not a proposed citation")
        event = project.events.make(
            "manuscript.citation_decided",
            CitationDecided(manuscript_id=manuscript_id, key=key, decision=decision),
            actor,
            refs=[manuscript_id],
        )
        confirmed = decision is CitationDecision.CONFIRM
        state = CitationState.RESOLVED if confirmed else CitationState.UNRESOLVED
        work = current.work_id if confirmed else None
        reason = _reason(project, state, work, _works(project))
        closures: list[Event] = []
        if reason is not None:
            ordinals = _ordinals(sentence_rows(project, manuscript_id), key)
            closures = _closure_events(project, manuscript_id, key, ordinals, work, reason)
        project.record([event, *closures])
        return event.id

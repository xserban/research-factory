"""Background concepts: definition, source approval and definition review (slice 3c, G3-B).

A concept is an outside idea a paper relies on, with a short explanation, a researcher-approved
source and `uses` links from the ideas and papers that rely on it. It is not evidence: nothing in
this module is imported by an evidence service, and its rows live in the layer's own tables.

Invariants:
- Scripts never judge: the platform verifies quotes, folds names, computes states and records
  what an agent or a human wrote; it never writes concept text and no state is typed.
- Only a human approves or rejects a source and reviews a definition (R-51). The session that
  wrote an agent-written definition never does either, relay included. Both are refused here, at
  the service boundary, with nothing written; the projector repeats the check as defence in depth.
- Every refusal reports all its issues together (fields `actor`, `name`, `aliases[i]`, `text`,
  `source`, `quotes`, `quotes[i].<attr>`, `concept_id`, `supersedes`, `note`, `channel`,
  `reviewer`, `definition`), with reasons from a fixed vocabulary that carry no document text.
- An approval binds to the source's digest (ruling B1), a review to the definition's event
  (ruling B2): a redefinition that changes the source is hidden again, one that keeps it is shown
  `unreviewed`.
- Reads page and count in SQL; none loads every concept.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Sequence
from typing import Any, Literal

from pydantic import ConfigDict, Field
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.intuition.classify import classify_use, fold, source_digest, would_cycle
from factory.intuition.labels import LAYER_CLASS, layer_label
from factory.intuition.validate import text_length
from factory.model.base import StrictModel
from factory.model.intuition import (
    CONCEPT_MAX_ALIASES,
    CONCEPT_NAME_MAX,
    INTERPRETATION_MAX_CHARS,
    INTERPRETATION_MAX_SOURCES,
    Author,
    ConceptBrief,
    ConceptDefined,
    ConceptHidden,
    ConceptInput,
    ConceptLinkDecided,
    ConceptLinkProposed,
    ConceptMerged,
    ConceptReviewed,
    ConceptSourceDecided,
    ConceptState,
    ConceptUnmerged,
    HistoryEntry,
    LinkStatus,
    SourceState,
    StoredConceptSource,
    StoredSource,
    UseBasisInput,
)
from factory.model.screening import Channel
from factory.services.context import Project
from factory.services.ideas import idea_view
from factory.services.interpretations import target_issue
from factory.services.intuition_sources import (
    ENTRY_UNKNOWN,
    EXTRACTION_NOT_LIVE,
    entry_link,
    stale_sources,
    verify_sources,
)
from factory.services.reference_view import is_live_reference_extraction, reference_view_of
from factory.services.search import works_by_ids

LIST_PAGE = 50
_VISIBLE_SQL = (
    "c.source_state = 'approved' AND c.merged_into IS NULL "
    "AND c.review_state IN ('unreviewed', 'reviewed')"
)

CONCEPT_UNKNOWN = "concept-unknown"
NOT_CURRENT_DEFINITION = "not-current-definition"


def _refuse(*issues: ValidationIssue) -> FactoryValidationError:
    return FactoryValidationError(list(issues))


# --- Reads of single rows ---


def _row(project: Project, concept_id: str) -> Any | None:
    with project.index.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT concept_id, name, text, author, author_user, writer_session, "
                    "definition_event, source_kind, source_citation, source_work, source_digest, "
                    "source_verifiable, source_state, review_state, self_reviewed, merged_into "
                    "FROM concepts WHERE concept_id = :c"
                ),
                {"c": concept_id},
            )
            .mappings()
            .first()
        )


def _human_users(project: Project) -> int:
    """How many distinct human users have acted in the project (a count in SQL)."""
    with project.index.connect() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(DISTINCT user) FROM events WHERE actor_kind = 'human'")
            ).scalar_one()
        )


# --- Definition ---


def _shape_issues(entry: ConceptInput) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if text_length(entry.name) > CONCEPT_NAME_MAX:
        issues.append(ValidationIssue("name", f"at most {CONCEPT_NAME_MAX} characters"))
    if len(entry.aliases) > CONCEPT_MAX_ALIASES:
        issues.append(ValidationIssue("aliases", f"at most {CONCEPT_MAX_ALIASES} aliases"))
    for index, alias in enumerate(entry.aliases):
        if text_length(alias) > CONCEPT_NAME_MAX:
            issues.append(
                ValidationIssue(f"aliases[{index}]", f"at most {CONCEPT_NAME_MAX} characters")
            )
    seen = {fold(entry.name)}
    for index, alias in enumerate(entry.aliases):
        if fold(alias) in seen:
            issues.append(ValidationIssue(f"aliases[{index}]", "duplicate-name"))
        seen.add(fold(alias))
    if entry.text is not None:
        if not entry.text.strip():
            issues.append(ValidationIssue("text", "must not be blank"))
        elif text_length(entry.text) > INTERPRETATION_MAX_CHARS:
            issues.append(ValidationIssue("text", f"at most {INTERPRETATION_MAX_CHARS} characters"))
    return issues


def _identity_issues(
    project: Project, entry: ConceptInput, own: str | None
) -> list[ValidationIssue]:
    """Ruling B4: a name or alias equal (folded) to one of a live, unmerged concept, including
    the names and aliases it gained by merge, is refused with the existing id in the reason."""
    wanted = [entry.name, *entry.aliases]
    folded = sorted({fold(w) for w in wanted})
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT x.folded, x.eff FROM ("
                "SELECT c.name_folded AS folded, COALESCE(c.merged_into, c.concept_id) AS eff "
                "FROM concepts c WHERE c.name_folded IN (SELECT value FROM json_each(:f)) "
                "UNION SELECT a.alias_folded, COALESCE(c.merged_into, c.concept_id) "
                "FROM concept_aliases a JOIN concepts c ON c.concept_id = a.concept_id "
                "WHERE a.alias_folded IN (SELECT value FROM json_each(:f))"
                ") x ORDER BY x.folded, x.eff"
            ),
            {"f": json.dumps(folded)},
        ).all()
    taken: dict[str, str] = {}
    for value, eff in found:
        if str(eff) != own:
            taken.setdefault(str(value), str(eff))
    issues: list[ValidationIssue] = []
    if fold(entry.name) in taken:
        issues.append(ValidationIssue("name", f"concept-exists:{taken[fold(entry.name)]}"))
    for index, alias in enumerate(entry.aliases):
        if fold(alias) in taken:
            issues.append(
                ValidationIssue(f"aliases[{index}]", f"concept-exists:{taken[fold(alias)]}")
            )
    return issues


def _redefinition(
    project: Project, actor: Actor, entry: ConceptInput
) -> tuple[Any | None, list[ValidationIssue]]:
    """Ruling B5: the prior row (None for a new concept) and the issues of naming it."""
    if entry.concept_id is None:
        if entry.supersedes is not None:
            return None, [ValidationIssue("supersedes", NOT_CURRENT_DEFINITION)]
        return None, []
    prior = _row(project, entry.concept_id)
    if prior is None:
        return None, [ValidationIssue("concept_id", CONCEPT_UNKNOWN)]
    issues: list[ValidationIssue] = []
    if prior["merged_into"] is not None:
        issues.append(ValidationIssue("concept_id", f"merged:{prior['merged_into']}"))
    if entry.supersedes != prior["definition_event"]:
        issues.append(ValidationIssue("supersedes", NOT_CURRENT_DEFINITION))
    if actor.kind == "agent" and prior["author"] != Author.AGENT.value:
        issues.append(ValidationIssue("concept_id", "human-written"))
    return prior, issues


def _source_issues(
    project: Project, entry: ConceptInput
) -> tuple[tuple[StoredSource, ...], list[ValidationIssue]]:
    """The source's work and the quotes (ruling B3): a source without a work id is unverifiable
    and carries no quotes; a quote must come from the source's own work and verify."""
    issues: list[ValidationIssue] = []
    source = entry.source
    if (
        source is not None
        and source.work_id is not None
        and not works_by_ids(project, [source.work_id])
    ):
        issues.append(ValidationIssue("source.work_id", "work-unknown"))
    if not entry.quotes:
        return (), issues
    if len(entry.quotes) > INTERPRETATION_MAX_SOURCES:
        issues.append(ValidationIssue("quotes", f"at most {INTERPRETATION_MAX_SOURCES} quotes"))
        return (), issues
    if source is None:
        issues.append(ValidationIssue("quotes", "no-source"))
        return (), issues
    if source.work_id is None:
        issues.append(ValidationIssue("quotes", "unverifiable-source"))
        return (), issues
    for index, quote in enumerate(entry.quotes):
        if quote.work_id != source.work_id:
            issues.append(ValidationIssue(f"quotes[{index}].work_id", "not-source-work"))
    verdict = verify_sources(project, entry.quotes, field="quotes")
    issues += verdict.issues
    return verdict.stored, issues


def define_concept(
    project: Project, actor: Actor, entry: ConceptInput, *, approve_source: bool = False
) -> str:
    """Define a concept, or redefine one (`concept_id` and `supersedes` naming the live
    definition), and return its `cpt_` id. An agent may redefine only an agent-written concept; a
    human any. With `approve_source` (a human with a source only) the source's approval is
    appended in the same write. Refused, with nothing written and every issue reported, for a
    wrong actor (`actor`), bounds (`name`, `aliases`, `text`), a name or alias already taken
    (`name`, `aliases[i]`, reason `concept-exists:<id>`), a source or quotes that fail ruling B3
    (`source.work_id`, `quotes`, `quotes[i].<attr>`) and a redefinition that does not name the
    live definition (`concept_id`, `supersedes`)."""
    if actor.kind not in ("agent", "human"):
        raise _refuse(ValidationIssue("actor", "only an agent or a human defines a concept"))
    with project.index.exclusive():
        project.index.sync()
        issues = _shape_issues(entry)
        if approve_source:
            if actor.kind != "human":
                issues.append(ValidationIssue("actor", "only a human approves a source"))
            if entry.source is None:
                issues.append(ValidationIssue("source", "no-source"))
        prior, redefinition = _redefinition(project, actor, entry)
        issues += redefinition
        issues += _identity_issues(
            project, entry, None if prior is None else str(prior["concept_id"])
        )
        quotes, source_problems = _source_issues(project, entry)
        issues += source_problems
        if issues:
            raise FactoryValidationError(issues)
        concept_id = entry.concept_id or f"cpt_{project.ids.ulid()}"
        stored_source: StoredConceptSource | None = None
        if entry.source is not None:
            stored_source = StoredConceptSource(
                kind=entry.source.kind,
                citation=entry.source.citation,
                work_id=entry.source.work_id,
                digest=source_digest(entry.source),
                verifiable=entry.source.work_id is not None,
            )
        payload = ConceptDefined(
            concept_id=concept_id,
            name=entry.name,
            aliases=entry.aliases,
            text=entry.text,
            source=stored_source,
            quotes=quotes,
            author=Author(actor.kind),
            supersedes=entry.supersedes,
        )
        refs = [concept_id] + ([entry.supersedes] if entry.supersedes else [])
        input_blob = project.blobs.put_json({"call": entry.model_dump(mode="json")})
        events: list[Event] = [
            project.events.make("concept.defined", payload, actor, refs=refs, input_blob=input_blob)
        ]
        if approve_source and stored_source is not None:
            events.append(
                project.events.make(
                    "concept.source_decided",
                    ConceptSourceDecided(
                        concept_id=concept_id,
                        decision="approve",
                        source_digest=stored_source.digest,
                        note="",
                        channel=Channel.CLI,
                    ),
                    actor,
                    refs=[concept_id],
                    input_blob=input_blob,
                )
            )
        project.record(events)
        return concept_id


# --- Human decisions on a concept ---


def _decision_issues(
    project: Project, actor: Actor, row: Any, channel: Channel, what: str
) -> list[ValidationIssue]:
    """Refusals common to a source decision and a definition review: the concept must be live,
    the writer's session never decides, and a relay may not come from a pass session."""
    issues: list[ValidationIssue] = []
    if row["merged_into"] is not None:
        issues.append(ValidationIssue("concept_id", f"merged:{row['merged_into']}"))
    if row["author"] == Author.AGENT.value and row["writer_session"] == actor.session:
        issues.append(
            ValidationIssue("actor", f"the session that wrote a concept cannot {what} it")
        )
    if channel is Channel.MCP:
        issues.append(ValidationIssue("channel", "no MCP tool decides; use the command line"))
    return issues


def decide_concept_source(
    project: Project,
    actor: Actor,
    concept_id: str,
    decision: Literal["approve", "reject"],
    note: str,
    channel: Channel,
) -> str:
    """Approve or reject the live definition's source and return the event id. Human only
    (`actor`); the concept must exist and have a source (`concept_id`, `source`); a rejection
    needs a note (`note`); the writer's session is refused (`actor`)."""
    if actor.kind != "human":
        raise _refuse(ValidationIssue("actor", "only a human decides a source"))
    with project.index.exclusive():
        project.index.sync()
        row = _row(project, concept_id)
        if row is None:
            raise _refuse(ValidationIssue("concept_id", CONCEPT_UNKNOWN))
        issues = _decision_issues(project, actor, row, channel, "decide the source of")
        if row["source_digest"] is None:
            issues.append(ValidationIssue("source", "no-source"))
        if decision == "reject" and not note.strip():
            issues.append(ValidationIssue("note", "state why the source is rejected"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "concept.source_decided",
            ConceptSourceDecided(
                concept_id=concept_id,
                decision=decision,
                source_digest=str(row["source_digest"]),
                note=note,
                channel=channel,
            ),
            actor,
            refs=[concept_id],
        )
        project.record([event])
        return event.id


def review_concept(
    project: Project,
    actor: Actor,
    concept_id: str,
    state: Literal["reviewed", "wrong"],
    note: str,
    channel: Channel,
    *,
    definition: str | None = None,
) -> str:
    """Record a human review of the live definition (`reviewed` or `wrong`) and return the event
    id; the latest review of the live definition wins. `definition`, when given, must be the live
    definition's event id (`definition`, `not-current-definition`). Refused, with nothing written,
    for a non-human actor or the writing session (`actor`), a pass session's relay (`channel`),
    an unknown or merged concept (`concept_id`), a `wrong` without a note (`note`), and the author
    of a human-written definition when more than one human has acted in the project (`reviewer`,
    ruling A7); with a single human the review is recorded `self_reviewed`."""
    if actor.kind != "human":
        raise _refuse(ValidationIssue("actor", "only a human reviews"))
    with project.index.exclusive():
        project.index.sync()
        row = _row(project, concept_id)
        if row is None:
            raise _refuse(ValidationIssue("concept_id", CONCEPT_UNKNOWN))
        issues = _decision_issues(project, actor, row, channel, "review")
        if definition is not None and definition != row["definition_event"]:
            issues.append(ValidationIssue("definition", NOT_CURRENT_DEFINITION))
        if state == "wrong" and not note.strip():
            issues.append(ValidationIssue("note", "state why the definition is wrong"))
        self_reviewed = row["author"] == Author.HUMAN.value and row["author_user"] == actor.user
        if self_reviewed and _human_users(project) > 1:
            issues.append(ValidationIssue("reviewer", "another human reviews this definition"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "concept.reviewed",
            ConceptReviewed(
                concept_id=concept_id,
                definition=str(row["definition_event"]),
                state=state,
                note=note,
                self_reviewed=self_reviewed,
                channel=channel,
            ),
            actor,
            refs=[concept_id],
        )
        project.record([event])
        return event.id


# --- Reads ---


class ConceptView(StrictModel):
    """A concept as the reviewer sees it, labelled. `flags` lists `unverifiable-source`,
    `source-stale` and `self-reviewed`. Serialise with `by_alias=True` for the key `class`."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    concept_id: str
    class_: str = Field(serialization_alias="class")
    label: str
    name: str
    aliases: list[str]
    text: str | None
    source: StoredConceptSource | None
    source_state: SourceState
    flags: list[str]
    quotes: list[StoredSource]
    author: str
    writer: str
    review_state: ConceptState
    visible: bool
    merged_into: str | None
    input_blob: str | None


class ConceptList(StrictModel):
    items: list[ConceptView]
    hidden: ConceptHidden
    next_cursor: str | None


_VIEW_SQL = (
    "SELECT c.concept_id, c.name, c.text, c.author, c.source_kind, c.source_citation, "
    "c.source_work, c.source_digest, c.source_verifiable, c.source_state, c.review_state, "
    "c.self_reviewed, c.merged_into, c.input_blob, e.actor_id, e.model FROM concepts c "
    "JOIN events e ON e.id = c.definition_event "
)


def _writer(actor_id: str, model: str | None) -> str:
    return actor_id if model is None else f"{actor_id} ({model})"


def _views(project: Project, found: Sequence[Any]) -> list[ConceptView]:
    ids = [str(r["concept_id"]) for r in found]
    if not ids:
        return []
    payload = json.dumps(ids)
    with project.index.connect() as conn:
        aliases: dict[str, list[str]] = {}
        for cid, alias in conn.execute(
            text(
                "SELECT concept_id, alias FROM concept_aliases WHERE concept_id IN "
                "(SELECT value FROM json_each(:ids)) ORDER BY concept_id, alias_folded"
            ),
            {"ids": payload},
        ).all():
            aliases.setdefault(str(cid), []).append(str(alias))
        quotes: dict[str, list[StoredSource]] = {}
        for r in (
            conn.execute(
                text(
                    "SELECT concept_id, work_id, conversion_id, document_id, anchor, quote "
                    "FROM concept_quotes WHERE concept_id IN (SELECT value FROM json_each(:ids)) "
                    "ORDER BY concept_id, position"
                ),
                {"ids": payload},
            )
            .mappings()
            .all()
        ):
            quotes.setdefault(str(r["concept_id"]), []).append(
                StoredSource(
                    kind="quote",
                    role="background",
                    work_id=r["work_id"],
                    conversion_id=r["conversion_id"],
                    document_id=r["document_id"],
                    anchor=r["anchor"],
                    quote=r["quote"],
                )
            )
    stale = stale_sources(project, only=ids)
    out: list[ConceptView] = []
    for r in found:
        cid = str(r["concept_id"])
        source: StoredConceptSource | None = None
        if r["source_kind"] is not None:
            source = StoredConceptSource(
                kind=r["source_kind"],
                citation=r["source_citation"],
                work_id=r["source_work"],
                digest=r["source_digest"],
                verifiable=bool(r["source_verifiable"]),
            )
        flags: list[str] = []
        if source is not None and not source.verifiable:
            flags.append("unverifiable-source")
        if cid in stale:
            flags.append("source-stale")
        if r["self_reviewed"]:
            flags.append("self-reviewed")
        state = ConceptState(str(r["review_state"]))
        out.append(
            ConceptView(
                concept_id=cid,
                class_=LAYER_CLASS,
                label=layer_label(state.value),
                name=str(r["name"]),
                aliases=aliases.get(cid, []),
                text=r["text"],
                source=source,
                source_state=r["source_state"],
                flags=flags,
                quotes=quotes.get(cid, []),
                author=str(r["author"]),
                writer=_writer(str(r["actor_id"]), r["model"]),
                review_state=state,
                visible=(
                    r["source_state"] == "approved"
                    and r["merged_into"] is None
                    and state in (ConceptState.UNREVIEWED, ConceptState.REVIEWED)
                ),
                merged_into=r["merged_into"],
                input_blob=r["input_blob"],
            )
        )
    return out


def concept_view(project: Project, concept_id: str) -> ConceptView | None:
    """One concept, labelled, hidden or not; None for an unknown id."""
    project.index.sync()
    with project.index.connect() as conn:
        found = (
            conn.execute(text(f"{_VIEW_SQL} WHERE c.concept_id = :c"), {"c": concept_id})
            .mappings()
            .all()
        )
    views = _views(project, found)
    return views[0] if views else None


def concept_hidden(project: Project) -> ConceptHidden:
    """The hidden counts of concepts and `uses` links, from the `layer_hidden` view."""
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "SELECT item, reason, n FROM layer_hidden WHERE item IN ('concept', 'concept_link')"
            )
        ).all()
    n = {(str(i), str(r)): int(c) for i, r, c in found}
    return ConceptHidden(
        unapproved=n.get(("concept", "unapproved"), 0),
        wrong=n.get(("concept", "wrong"), 0),
        merged=n.get(("concept", "merged"), 0),
        links_inferred=n.get(("concept_link", "inferred"), 0),
        links_rejected=n.get(("concept_link", "rejected"), 0),
    )


def list_concepts(
    project: Project,
    *,
    include_hidden: bool = False,
    cursor: str | None = None,
    limit: int = LIST_PAGE,
) -> ConceptList:
    """One page of concepts by id, labelled. By default only the visible ones (an approved
    source, not merged, not reviewed `wrong`; ruling B2); `include_hidden` lists all. The hidden
    counts are always reported. `next_cursor` continues the listing."""
    project.index.sync()
    where = "1 = 1" if include_hidden else _VISIBLE_SQL
    params: dict[str, Any] = {"n": limit + 1}
    if cursor is not None:
        where += " AND c.concept_id > :c"
        params["c"] = cursor
    with project.index.connect() as conn:
        found = (
            conn.execute(text(f"{_VIEW_SQL} WHERE {where} ORDER BY c.concept_id LIMIT :n"), params)
            .mappings()
            .all()
        )
    page = found[:limit]
    items = _views(project, page)
    return ConceptList(
        items=items,
        hidden=concept_hidden(project),
        next_cursor=items[-1].concept_id if len(found) > limit else None,
    )


def visible_concepts(
    project: Project, *, limit: int = 200, cursor: str | None = None
) -> list[ConceptBrief]:
    """Name and aliases of the visible concepts, one page by id (what a writer needs to link and
    cite them)."""
    project.index.sync()
    where = _VISIBLE_SQL
    params: dict[str, Any] = {"n": limit}
    if cursor is not None:
        where += " AND c.concept_id > :c"
        params["c"] = cursor
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                f"SELECT c.concept_id, c.name FROM concepts c WHERE {where} "
                "ORDER BY c.concept_id LIMIT :n"
            ),
            params,
        ).all()
        ids = [str(r[0]) for r in found]
        aliases: dict[str, list[str]] = {}
        if ids:
            for cid, alias in conn.execute(
                text(
                    "SELECT concept_id, alias FROM concept_aliases WHERE concept_id IN "
                    "(SELECT value FROM json_each(:ids)) ORDER BY concept_id, alias_folded"
                ),
                {"ids": json.dumps(ids)},
            ).all():
                aliases.setdefault(str(cid), []).append(str(alias))
    return [
        ConceptBrief(concept_id=str(r[0]), name=str(r[1]), aliases=aliases.get(str(r[0]), []))
        for r in found
    ]


def visible_concept_count(project: Project) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(
            conn.execute(text(f"SELECT COUNT(*) FROM concepts c WHERE {_VISIBLE_SQL}")).scalar_one()
        )


def concept_history(project: Project, concept_id: str) -> list[HistoryEntry]:
    """Every step of a concept in event order: each definition (`recorded`), the replacement of a
    definition (`superseded-by`), each source decision (`source-decided`, state = decision) and
    each definition review (`reviewed`). Empty for an unknown id."""
    project.index.sync()
    with project.index.connect() as conn:
        defs = conn.execute(
            text(
                "SELECT d.event_id, d.supersedes, e.actor_id FROM concept_definitions d "
                "JOIN events e ON e.id = d.event_id WHERE d.concept_id = :c ORDER BY d.event_id"
            ),
            {"c": concept_id},
        ).all()
        decisions = conn.execute(
            text(
                "SELECT s.event_id, s.decision, s.note, e.actor_id FROM concept_source_decisions s "
                "JOIN events e ON e.id = s.event_id WHERE s.concept_id = :c ORDER BY s.event_id"
            ),
            {"c": concept_id},
        ).all()
        reviews = conn.execute(
            text(
                "SELECT r.event_id, r.state, r.note, r.self_reviewed, e.actor_id, r.folded "
                "FROM concept_reviews r JOIN events e ON e.id = r.event_id "
                "WHERE r.concept_id = :c ORDER BY r.event_id"
            ),
            {"c": concept_id},
        ).all()
    history: list[HistoryEntry] = []
    for event_id, supersedes, actor_id in defs:
        history.append(
            HistoryEntry(
                event_id=str(event_id),
                kind="recorded",
                state=None,
                actor=str(actor_id),
                note="",
                self_reviewed=False,
            )
        )
        if supersedes is not None:
            history.append(
                HistoryEntry(
                    event_id=str(event_id),
                    kind="superseded-by",
                    state="superseded",
                    actor=str(actor_id),
                    note="",
                    self_reviewed=False,
                )
            )
    history += [
        HistoryEntry(
            event_id=str(event_id),
            kind="source-decided",
            state=str(decision),
            actor=str(actor_id),
            note=str(note),
            self_reviewed=False,
        )
        for event_id, decision, note, actor_id in decisions
    ]
    history += [
        HistoryEntry(
            event_id=str(event_id),
            kind="reviewed",
            state=str(state),
            actor=str(actor_id),
            note=str(note),
            self_reviewed=bool(self_reviewed),
            folded=bool(folded),
        )
        for event_id, state, note, self_reviewed, actor_id, folded in reviews
    ]
    order = {"recorded": 0, "superseded-by": 1}
    return sorted(history, key=lambda h: (h.event_id, order.get(h.kind, 2)))


def concept_review_counts(project: Project) -> dict[ConceptState, int]:
    """Concepts by live review state (`merged` for merged ones), counted in SQL, every state
    present."""
    project.index.sync()
    with project.index.connect() as conn:
        found: dict[Any, Any] = dict(
            conn.execute(
                text("SELECT review_state, COUNT(*) FROM concepts GROUP BY review_state")
            ).all()
        )
    return {s: int(found.get(s.value, 0)) for s in ConceptState}


# --- `uses` links ---


class LinkResult(StrictModel):
    link_id: str
    status: Literal["stated", "inferred"]
    status_reason: str
    existing: bool


def _concept_names(project: Project, concept_id: str) -> list[str]:
    """The names and aliases of a concept and of the concepts merged into it (ruling B4)."""
    with project.index.connect() as conn:
        names = [
            str(r[0])
            for r in conn.execute(
                text("SELECT name FROM concepts WHERE concept_id = :c OR merged_into = :c"),
                {"c": concept_id},
            ).all()
        ]
        names += [
            str(r[0])
            for r in conn.execute(
                text(
                    "SELECT alias FROM concept_aliases WHERE concept_id IN "
                    "(SELECT concept_id FROM concepts WHERE concept_id = :c OR merged_into = :c)"
                ),
                {"c": concept_id},
            ).all()
        ]
    return names


def effective_concept(project: Project, concept_id: str) -> str:
    """The concept `concept_id` stands for: the one it is merged into, else itself (one level,
    ruling B9)."""
    project.index.sync()
    row = _row(project, concept_id)
    if row is None or row["merged_into"] is None:
        return concept_id
    return str(row["merged_into"])


def _reachable_edges(project: Project, start: str) -> set[tuple[str, str]]:
    """The `uses` edges between concepts, not rejected and merge-resolved, reachable from
    `start`: one recursive query that visits each concept once, never the whole table."""
    with project.index.connect() as conn:
        found = conn.execute(
            text(
                "WITH RECURSIVE reach(n) AS (SELECT :s UNION SELECT e.target FROM layer_edges e "
                "JOIN reach r ON e.source = r.n WHERE e.edge_type = 'uses' "
                "AND e.review_state != 'rejected' AND e.source LIKE 'cpt\\_%' ESCAPE '\\') "
                "SELECT e.source, e.target FROM layer_edges e WHERE e.edge_type = 'uses' "
                "AND e.review_state != 'rejected' AND e.source IN (SELECT n FROM reach)"
            ),
            {"s": start},
        ).all()
    return {(str(a), str(b)) for a, b in found}


def concept_path_issues(project: Project, source: str, target: str) -> list[ValidationIssue]:
    """Ruling B8: whether a link `source` -> `target` between (effective) concepts is a
    self-link or would close a cycle (gate L-cycle)."""
    if source == target:
        return [ValidationIssue("concept_id", "self-link")]
    if would_cycle(_reachable_edges(project, target), (source, target)):
        return [ValidationIssue("concept_id", "cycle")]
    return []


def _basis_digest(basis: UseBasisInput, stored: StoredSource | None) -> str:
    if stored is not None:
        canonical: dict[str, str | None] = {
            "k": "quote",
            "c": stored.conversion_id,
            "a": stored.anchor,
            "q": fold(stored.quote or ""),
        }
    elif basis.reference is not None:
        canonical = {"k": "citation", "r": basis.reference}
    else:
        canonical = {"k": "none"}
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "bas_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _from_works(project: Project, from_node: str, from_kind: str) -> list[str]:
    if from_kind == "idea":
        view = idea_view(project, from_node)
        return [] if view is None else list(view.effective_members)
    return [from_node]


def propose_concept_link(
    project: Project,
    actor: Actor,
    from_node: str,
    concept_id: str,
    basis: UseBasisInput,
    note: str | None = None,
) -> LinkResult:
    """Propose that `from_node` (a corpus paper, a confirmed idea or a live concept) uses
    `concept_id`, and return the link with its computed status (`stated` or `inferred`, ruling
    B6); a human's proposal is also only stated or inferred, and a human confirms it separately.
    A proposal equal to a non-rejected link of the same computed status returns that link and
    writes nothing (ruling B7). Refused, with nothing written and every issue reported, for an
    unknown or merged concept (`concept_id`), an ineligible from-node (`from_node`), a quote or
    reference that is not of the from-node's work or does not verify (`basis.quote.<attr>`,
    `basis.reference`, reason `not-from-work`), no basis and no note (`note`) and a self-link or
    cycle (`concept_id`, reasons `self-link`, `cycle`)."""
    if actor.kind not in ("agent", "human"):
        raise _refuse(ValidationIssue("actor", "only an agent or a human proposes a link"))
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        concept = _row(project, concept_id)
        if concept is None:
            issues.append(ValidationIssue("concept_id", CONCEPT_UNKNOWN))
        elif concept["merged_into"] is not None:
            issues.append(ValidationIssue("concept_id", f"merged:{concept['merged_into']}"))
        from_kind = "concept" if from_node.startswith("cpt_") else _kind_of(from_node)
        if from_kind == "concept":
            source_row = _row(project, from_node)
            if source_row is None:
                issues.append(ValidationIssue("from_node", CONCEPT_UNKNOWN))
            elif source_row["merged_into"] is not None:
                issues.append(ValidationIssue("from_node", f"merged:{source_row['merged_into']}"))
        else:
            problem = target_issue(project, from_node)
            if problem is not None:
                issues.append(ValidationIssue("from_node", problem.reason))
        if issues:
            raise FactoryValidationError(issues)
        assert concept is not None
        stored_quote: StoredSource | None = None
        cited_work: str | None = None
        link_resolved: bool | None = None
        works = _from_works(project, from_node, from_kind)
        if basis.quote is not None:
            if from_kind == "concept":
                issues.append(ValidationIssue("basis.quote", "not-from-work"))
            elif basis.quote.work_id not in works:
                issues.append(ValidationIssue("basis.quote.work_id", "not-from-work"))
            else:
                verdict = verify_sources(project, [basis.quote], field="basis.quote")
                issues += [
                    ValidationIssue(i.field.replace("basis.quote[0]", "basis.quote"), i.reason)
                    for i in verdict.issues
                ]
                stored_quote = verdict.stored[0] if verdict.stored else None
        elif basis.reference is not None:
            issues += _reference_issues(project, basis.reference, from_kind, works)
            if not issues:
                state_work = entry_link(project, basis.reference)
                assert state_work is not None
                link_resolved = state_work[0] == "resolved"
                cited_work = state_work[1]
        elif note is None or not note.strip():
            issues.append(ValidationIssue("note", "a link with no basis needs a note"))
        if from_kind == "concept":
            issues += concept_path_issues(
                project,
                effective_concept(project, from_node),
                effective_concept(project, concept_id),
            )
        if issues:
            raise FactoryValidationError(issues)
        status, reason = classify_use(
            from_kind=from_kind,
            names=_concept_names(project, concept_id),
            quote=None if stored_quote is None else stored_quote.quote,
            cited_work=cited_work,
            link_resolved=link_resolved,
            source_work=concept["source_work"],
            source_approved=concept["source_state"] == "approved",
        )
        digest = _basis_digest(basis, stored_quote)
        with project.index.connect() as conn:
            existing = conn.execute(
                text(
                    "SELECT link_id FROM concept_uses WHERE from_node = :f AND concept_id = :c "
                    "AND basis_digest = :d AND proposed_status = :s AND status != 'rejected' "
                    "ORDER BY link_id LIMIT 1"
                ),
                {"f": from_node, "c": concept_id, "d": digest, "s": status},
            ).scalar()
        if existing is not None:
            return LinkResult(
                link_id=str(existing), status=status, status_reason=reason, existing=True
            )
        link_id = f"cul_{project.ids.ulid()}"
        payload = ConceptLinkProposed(
            link_id=link_id,
            from_node=from_node,
            from_kind=from_kind,
            concept_id=concept_id,
            basis_kind="quote" if stored_quote else ("citation" if basis.reference else "none"),
            quote=stored_quote,
            reference=basis.reference,
            cited_work=cited_work,
            basis_digest=digest,
            status=status,
            status_reason=reason,
            note=note,
        )
        input_blob = project.blobs.put_json(
            {
                "call": {
                    "from_node": from_node,
                    "concept_id": concept_id,
                    "basis": basis.model_dump(mode="json"),
                    "note": note,
                }
            }
        )
        event = project.events.make(
            "concept.link_proposed",
            payload,
            actor,
            refs=[link_id, from_node, concept_id],
            input_blob=input_blob,
        )
        project.record([event])
        return LinkResult(link_id=link_id, status=status, status_reason=reason, existing=False)


def _kind_of(node: str) -> str:
    return "idea" if node.startswith("ida_") else "paper"


def _reference_issues(
    project: Project, reference: str, from_kind: str, works: Sequence[str]
) -> list[ValidationIssue]:
    field = "basis.reference"
    if from_kind == "concept":
        return [ValidationIssue(field, "not-from-work")]
    extraction_id = reference.rpartition(":")[0]
    if not is_live_reference_extraction(project, extraction_id):
        return [ValidationIssue(field, EXTRACTION_NOT_LIVE)]
    view = reference_view_of(project, extraction_id)
    if view is None or view.work_id not in works:
        return [ValidationIssue(field, "not-from-work")]
    if entry_link(project, reference) is None:
        return [ValidationIssue(field, ENTRY_UNKNOWN)]
    return []


def decide_concept_link(
    project: Project,
    actor: Actor,
    link_id: str,
    decision: Literal["confirm", "reject"],
    rationale: str,
    channel: Channel,
) -> str:
    """Confirm an `inferred` link or reject a link that is not already rejected, and return the
    event id; the latest decision wins. Human only (`actor`); the session that proposed an
    agent-written link is refused, relay included (`actor`); a relay from a pass session is
    refused (`channel`); an unknown link (`link_id`); a blank rationale (`rationale`); a confirm
    of a link that is not inferred and a reject of a rejected one (`decision`, reasons
    `not-inferred`, `already-rejected`)."""
    if actor.kind != "human":
        raise _refuse(ValidationIssue("actor", "only a human decides a link"))
    with project.index.exclusive():
        project.index.sync()
        with project.index.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT status, proposer_kind, proposer_session FROM concept_uses "
                        "WHERE link_id = :l"
                    ),
                    {"l": link_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise _refuse(ValidationIssue("link_id", "link-unknown"))
        issues: list[ValidationIssue] = []
        if row["proposer_kind"] == "agent" and row["proposer_session"] == actor.session:
            issues.append(
                ValidationIssue("actor", "the session that proposed a link cannot decide it")
            )
        if channel is Channel.MCP:
            issues.append(ValidationIssue("channel", "no MCP tool decides; use the command line"))
        if not rationale.strip():
            issues.append(ValidationIssue("rationale", "state why"))
        if decision == "confirm" and row["status"] != LinkStatus.INFERRED.value:
            issues.append(ValidationIssue("decision", "not-inferred"))
        if decision == "reject" and row["status"] == LinkStatus.REJECTED.value:
            issues.append(ValidationIssue("decision", "already-rejected"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "concept.link_decided",
            ConceptLinkDecided(
                link_id=link_id, decision=decision, rationale=rationale, channel=channel
            ),
            actor,
            refs=[link_id],
        )
        project.record([event])
        return event.id


class ConceptLinkView(StrictModel):
    """A `uses` link as the reviewer sees it, labelled. `concept_id` is the effective concept
    (after merges), `raw_concept_id` the one the link names. Serialise with `by_alias=True` for
    the key `class`."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    link_id: str
    class_: str = Field(serialization_alias="class")
    label: str
    from_node: str
    from_kind: str
    concept_id: str
    raw_concept_id: str
    basis_kind: str
    quote: StoredSource | None
    reference: str | None
    status: LinkStatus
    status_reason: str
    note: str | None
    note_label: str | None
    decided_by: str | None


class ConceptLinkList(StrictModel):
    items: list[ConceptLinkView]
    hidden: ConceptHidden
    next_cursor: str | None


_LINK_SQL = (
    "SELECT u.link_id, u.from_node, u.from_kind, u.concept_id, u.basis_kind, u.basis_work, "
    "u.basis_conversion, u.basis_document, u.basis_anchor, u.basis_quote, u.reference, "
    "u.status, u.status_reason, u.note, u.decided_by, "
    "COALESCE(c.merged_into, u.concept_id) AS effective FROM concept_uses u "
    "LEFT JOIN concepts c ON c.concept_id = u.concept_id "
)
_ENDPOINT_VISIBLE = (
    "AND EXISTS (SELECT 1 FROM concepts ce WHERE ce.concept_id = COALESCE(c.merged_into, "
    "u.concept_id) AND ce.source_state = 'approved' AND ce.merged_into IS NULL "
    "AND ce.review_state IN ('unreviewed', 'reviewed')) "
    "AND (u.from_kind != 'concept' OR EXISTS (SELECT 1 FROM concepts cf WHERE "
    "cf.concept_id = COALESCE((SELECT m.merged_into FROM concepts m WHERE "
    "m.concept_id = u.from_node), u.from_node) AND cf.source_state = 'approved' "
    "AND cf.merged_into IS NULL AND cf.review_state IN ('unreviewed', 'reviewed'))) "
)


def list_concept_links(
    project: Project,
    *,
    statuses: Collection[LinkStatus] | None = None,
    concept_id: str | None = None,
    include_hidden: bool = False,
    cursor: str | None = None,
    limit: int = LIST_PAGE,
) -> ConceptLinkList:
    """One page of `uses` links by id, labelled. By default the `stated` and `confirmed` links
    whose concept endpoints are visible; `statuses` widens the states, `include_hidden` the
    endpoints, `concept_id` limits to one effective concept. The hidden counts are always
    reported. `next_cursor` continues the listing."""
    wanted = [s.value for s in (statuses or (LinkStatus.STATED, LinkStatus.CONFIRMED))]
    project.index.sync()
    where = "u.status IN (SELECT value FROM json_each(:states)) "
    params: dict[str, Any] = {"states": json.dumps(sorted(wanted)), "n": limit + 1}
    if not include_hidden:
        where += _ENDPOINT_VISIBLE
    if concept_id is not None:
        where += "AND COALESCE(c.merged_into, u.concept_id) = :cid "
        params["cid"] = concept_id
    if cursor is not None:
        where += "AND u.link_id > :cur "
        params["cur"] = cursor
    with project.index.connect() as conn:
        found = (
            conn.execute(text(f"{_LINK_SQL} WHERE {where} ORDER BY u.link_id LIMIT :n"), params)
            .mappings()
            .all()
        )
    page = found[:limit]
    items = [_link_view(r) for r in page]
    return ConceptLinkList(
        items=items,
        hidden=concept_hidden(project),
        next_cursor=items[-1].link_id if len(found) > limit else None,
    )


def _link_view(r: Any) -> ConceptLinkView:
    quote: StoredSource | None = None
    if r["basis_kind"] == "quote":
        quote = StoredSource(
            kind="quote",
            role="supports",
            work_id=r["basis_work"],
            conversion_id=r["basis_conversion"],
            document_id=r["basis_document"],
            anchor=r["basis_anchor"],
            quote=r["basis_quote"],
        )
    status = LinkStatus(str(r["status"]))
    return ConceptLinkView(
        link_id=str(r["link_id"]),
        class_=LAYER_CLASS,
        label=layer_label(status.value),
        from_node=str(r["from_node"]),
        from_kind=str(r["from_kind"]),
        concept_id=str(r["effective"]),
        raw_concept_id=str(r["concept_id"]),
        basis_kind=str(r["basis_kind"]),
        quote=quote,
        reference=r["reference"],
        status=status,
        status_reason=str(r["status_reason"]),
        note=r["note"],
        note_label="agent-note" if r["basis_kind"] == "none" and r["note"] else None,
        decided_by=r["decided_by"],
    )


# --- Merge and unmerge ---


def _merge_issues(project: Project, into: str, from_concept: str) -> list[ValidationIssue]:
    """Ruling B9 (gate concept-merge): both concepts live, distinct and unmerged, `from` with no
    concepts merged into it, and no self-link or cycle after the two become one."""
    if into == from_concept:
        return [ValidationIssue("from_concept", "same-concept")]
    target, source = _row(project, into), _row(project, from_concept)
    issues: list[ValidationIssue] = []
    if target is None:
        issues.append(ValidationIssue("into", CONCEPT_UNKNOWN))
    elif target["merged_into"] is not None:
        issues.append(ValidationIssue("into", f"merged:{target['merged_into']}"))
    if source is None:
        issues.append(ValidationIssue("from_concept", CONCEPT_UNKNOWN))
    elif source["merged_into"] is not None:
        issues.append(ValidationIssue("from_concept", f"merged:{source['merged_into']}"))
    else:
        with project.index.connect() as conn:
            members = conn.execute(
                text("SELECT 1 FROM concepts WHERE merged_into = :c LIMIT 1"), {"c": from_concept}
            ).first()
        if members is not None:
            issues.append(ValidationIssue("from_concept", "has-merged-concepts"))
    if issues:
        return issues
    from_edges = _reachable_edges(project, from_concept)
    into_edges = _reachable_edges(project, into)
    if (from_concept, into) in from_edges or (into, from_concept) in into_edges:
        return [ValidationIssue("from_concept", "self-link")]
    if would_cycle(from_edges, (into, from_concept)) or would_cycle(
        into_edges, (from_concept, into)
    ):
        return [ValidationIssue("from_concept", "cycle")]
    return []


def build_concept_merge(
    project: Project,
    actor: Actor,
    into: str,
    from_concept: str,
    reason: str,
    proposal: str | None = None,
) -> Event:
    """The `concept.merged` event for a valid merge, not recorded. The caller holds the index
    lock and has synced. Refused for a non-human actor (`actor`), a blank reason (`reason`) and
    the cases of `_merge_issues` (`into`, `from_concept`)."""
    if actor.kind != "human":
        raise _refuse(ValidationIssue("actor", "only a human merges concepts"))
    issues = _merge_issues(project, into, from_concept)
    if not reason.strip():
        issues.append(ValidationIssue("reason", "state why"))
    if issues:
        raise FactoryValidationError(issues)
    return project.events.make(
        "concept.merged",
        ConceptMerged(into=into, from_concept=from_concept, reason=reason, proposal=proposal),
        actor,
        refs=[into, from_concept],
    )


def merge_concepts(
    project: Project, actor: Actor, into: str, from_concept: str, reason: str
) -> str:
    """Merge `from_concept` into `into` (human only, reversible) and return the event id: the
    projection re-points `from`'s links and names to `into`; no earlier row changes. Refusals as
    `build_concept_merge`, with nothing written."""
    if actor.kind != "human":
        raise _refuse(ValidationIssue("actor", "only a human merges concepts"))
    with project.index.exclusive():
        project.index.sync()
        event = build_concept_merge(project, actor, into, from_concept, reason)
        project.record([event])
        return event.id


def unmerge_concepts(
    project: Project, actor: Actor, into: str, from_concept: str, reason: str
) -> str:
    """Reverse an active merge `into <- from_concept` (human only) and return the event id.
    Refused for a non-human actor (`actor`), a blank reason (`reason`) and a pair that is not
    merged (`from_concept`, `not-merged`)."""
    if actor.kind != "human":
        raise _refuse(ValidationIssue("actor", "only a human unmerges concepts"))
    with project.index.exclusive():
        project.index.sync()
        issues: list[ValidationIssue] = []
        with project.index.connect() as conn:
            active = conn.execute(
                text(
                    "SELECT 1 FROM concept_merges WHERE from_concept = :f AND into_concept = :i "
                    "AND active = 1"
                ),
                {"f": from_concept, "i": into},
            ).first()
        if active is None:
            issues.append(ValidationIssue("from_concept", "not-merged"))
        if not reason.strip():
            issues.append(ValidationIssue("reason", "state why"))
        if issues:
            raise FactoryValidationError(issues)
        event = project.events.make(
            "concept.unmerged",
            ConceptUnmerged(into=into, from_concept=from_concept, reason=reason),
            actor,
            refs=[into, from_concept],
        )
        project.record([event])
        return event.id

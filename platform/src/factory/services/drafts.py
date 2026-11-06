"""Drafts, slots and sentence recording (slice 7b, plan W-A, task 5).

Declares: `create_draft`, `repin_outline`, `write_sentences`, `withdraw`, `reorder`, `draft_next`,
`live_sentences`, `get_draft`, `list_drafts`, `verifier_sessions`, `is_verifying`,
`refuse_verifier`, `sentence_status`, `status_counts`, `draft_view`, `draft_works`, `draft_render`,
`SentenceInput`, `SentenceRow`, `SlotTask`, `StatusRow`, `DraftView`. The writer of the sentence
events (the verification, audit and release events have their own services).

Invariants:
- The platform never writes prose. Sentences are the writer's; the platform checks them
  (`writing.checks`), stores their supports as ids and their stat values as computed, and serves
  the quotes of the supports only in a slot task's content, read from the projection of the
  extraction events (R-47: no library read). No `draft.*` event carries quote text.
- Partial acceptance: each sentence of a batch stands or falls alone. A sentence with one ineligible
  support among valid ones is refused whole; another valid sentence of the same call is written.
- Every agent-written event carries the call and the task content it was served as its
  `input_blob` (R-04). A human writes without a task.
- A session that has verified a sentence of a draft cannot write in it (`verifier_sessions`), nor
  repin, reorder or withdraw in it; a session holding a verification task of the draft cannot do
  those three either (`_refuse_verifier`, R-51). A session with a verdict on a draft, or a live
  claim on one of its units, is not served the draft by any other door: status, rendering, slot,
  trace, or the sentence refs of `check` (`is_verifying`; ruling 12, R-131). A unit is all it
  judges from.
- A repin adds the outline's new sections and retires the slot tasks of the old outline: a task
  whose `outline` is not the draft's pin is neither served nor written under.
- A refusal writes nothing and carries positions and fixed codes, never document text.
- Status is computed on read and never stored. `stale` wins over `flagged`, `flagged` over
  `supported`, `supported` over `unchecked`; a `structural` or `interpretive` sentence keeps its
  name unless it is stale. A sentence is stale when a support stopped being eligible, when a stat
  recomputes to another value (`stat-changed`), or when a cell, item, claim or edge no longer says
  what the verdict's unit showed (`support-changed`): a value can be replaced under the same row
  key. A group is left out, as an added row would stale every sentence on it. An audit label is a
  human's result, so the agent variant of the status leaves it out: a rate would follow from
  counting the sentences it flags (decision 37.14, as decision 90 item 2 reads it).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue
from sqlalchemy import text

from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.exports.keys import assign_keys
from factory.index.drafts import identities, verifiers_of
from factory.model.base import StrictModel
from factory.model.drafts import (
    MAX_ORDER,
    MAX_REASON,
    MAX_SUPPORTS,
    MAX_TITLE,
    SENTENCE_MAX_CHARS,
    SENTENCE_STATUSES,
    DraftCreated,
    DraftKind,
    DraftOutlineRepinned,
    DraftReordered,
    Outline,
    SectionDef,
    SentenceClass,
    SentenceFlag,
    SentenceRecorded,
    SentenceWithdrawn,
    SupportKind,
    SupportRef,
    Verdict,
    parse_support,
)
from factory.model.task import (
    DRAFT_SLOT_TASK_KIND,
    DRAFT_VERIFY_TASK_KIND,
    Task,
    TaskCompleted,
    TaskStatus,
)
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.dedup import active_merges
from factory.services.draft_audit import (
    agent_audit_note,
    agent_audit_report,
    audit_report,
    incorrect_verdicts,
)
from factory.services.exports import select_works
from factory.services.outline import DEFAULT_SCOPE, OutlineScope, build_outline, outline_json
from factory.services.results import BatchResult, ItemError
from factory.services.supports import (
    ResolvedSupport,
    SupportShown,
    resolve_supports,
    support_shown,
)
from factory.services.tasks import (
    TaskSpec,
    claim_next,
    create_tasks,
    held_refs,
    require_holder,
    task_content,
)
from factory.writing.checks import DraftContext, check_sentence
from factory.writing.render import render_clean, render_closing, render_review, with_note
from factory.writing.stats import STATS_VERSION

ORDER_STEP = 10
MAX_SECTIONS = 99
COMPARED_KINDS = (SupportKind.CELL, SupportKind.ITEM, SupportKind.CLAIM, SupportKind.EDGE)
"""The supports whose words a verdict relied on, compared on read with the unit it was given."""


class SentenceInput(StrictModel):
    """One sentence as the writer gives it: the class, the text and the supports in the grammar of
    `parse_support`. No flag, status, stat value or id is accepted."""

    section_id: str
    cls: SentenceClass
    text: str
    supports: list[str] = Field(default_factory=list)
    order: int | None = None
    supersedes: str | None = None


class SentenceRow(StrictModel):
    sentence_id: str
    draft_id: str
    section_id: str
    order: int
    cls: SentenceClass
    text: str
    supports: list[str]
    stat_values: dict[str, int]
    flags: list[SentenceFlag]
    author: str
    session: str
    model: str | None
    task_id: str | None
    supersedes: str | None
    event_id: str


class SectionRow(StrictModel):
    section_id: str
    heading: str
    outline_section: str | None


class DraftRow(StrictModel):
    draft_id: str
    title: str
    kind: DraftKind
    outline_ref: str
    sections: list[SectionRow]
    sentences: int


SentenceStatus = Literal["structural", "interpretive", "unchecked", "supported", "flagged", "stale"]


@dataclass(frozen=True)
class StatusRow:
    """A live sentence's computed status. `reason` is the verdict of a flagged sentence,
    `audit-incorrect` for a verdict the audit overturned, or the stale reason code; no note."""

    sentence_id: str
    section_id: str
    order: int
    cls: SentenceClass
    status: SentenceStatus
    reason: str | None
    flags: tuple[str, ...]


@dataclass(frozen=True)
class RenderedSentence:
    sentence_id: str
    text: str
    supports: tuple[str, ...]
    works: tuple[str, ...]
    """The canonical works of its supports, in support order, de-duplicated."""


@dataclass(frozen=True)
class RenderedSection:
    section_id: str
    heading: str
    sentences: tuple[RenderedSentence, ...]


@dataclass(frozen=True)
class DraftView:
    """A draft as a rendering reads it: sections in order, each with its live sentences."""

    draft_id: str
    title: str
    sections: tuple[RenderedSection, ...]


@dataclass(frozen=True)
class SlotTask:
    task_id: str
    draft_id: str
    section_id: str
    content: dict[str, JsonValue]


def _refuse(field: str, reason: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field, reason)])


def _require_writer(actor: Actor) -> None:
    if actor.kind not in ("human", "agent"):
        raise _refuse("actor", "only a human or an agent writes a draft")


def verifier_sessions(project: Project, draft_id: str) -> frozenset[str]:
    """The `identities` (sessions, and humans by id) with a verdict on a sentence of the draft."""
    project.index.sync()
    with project.index.connect() as conn:
        return verifiers_of(conn, draft_id)


def is_verifying(project: Project, draft_id: str, session: str) -> bool:
    """Whether the session has a verdict on the draft or a live claim on one of its units."""
    held = any(draft_id in refs for refs in held_refs(project, session, DRAFT_VERIFY_TASK_KIND))
    return held or session in verifier_sessions(project, draft_id)


def refuse_verifier(project: Project, draft_id: str, session: str) -> None:
    """Refuse a session that `is_verifying` the draft."""
    if is_verifying(project, draft_id, session):
        raise _refuse("session", "a session verifying this draft cannot read it")


# --- Reads ---


def _draft_row(project: Project, draft_id: str) -> tuple[str, str, str, str] | None:
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT title, kind, outline_ref, outline_blob FROM drafts WHERE draft_id = :d"),
            {"d": draft_id},
        ).first()
    return None if row is None else (str(row[0]), str(row[1]), str(row[2]), str(row[3]))


def require_draft(project: Project, draft_id: str) -> tuple[str, str, str, str]:
    row = _draft_row(project, draft_id)
    if row is None:
        raise _refuse("draft_id", "unknown draft")
    return row


def _sections(project: Project, draft_id: str) -> list[SectionRow]:
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT section_id, heading, outline_section FROM draft_sections "
                "WHERE draft_id = :d ORDER BY ord"
            ),
            {"d": draft_id},
        ).all()
    return [
        SectionRow(
            section_id=str(r[0]),
            heading=str(r[1]),
            outline_section=None if r[2] is None else str(r[2]),
        )
        for r in rows
    ]


def get_draft(project: Project, draft_id: str) -> DraftRow | None:
    row = _draft_row(project, draft_id)
    if row is None:
        return None
    with project.index.connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM draft_sentences WHERE draft_id = :d "
                "AND superseded_by IS NULL AND withdrawn = 0"
            ),
            {"d": draft_id},
        ).scalar_one()
    return DraftRow(
        draft_id=draft_id,
        title=row[0],
        kind=DraftKind(row[1]),
        outline_ref=row[2],
        sections=_sections(project, draft_id),
        sentences=int(count),
    )


def list_drafts(project: Project) -> list[DraftRow]:
    project.index.sync()
    with project.index.connect() as conn:
        ids = [
            str(r[0]) for r in conn.execute(text("SELECT draft_id FROM drafts ORDER BY draft_id"))
        ]
    return [d for i in ids if (d := get_draft(project, i)) is not None]


def holds_verification(project: Project, session: str, draft_id: str) -> bool:
    """Whether `session` holds a claimed verification task on a sentence of the draft. A task
    whose content cannot be read counts for nothing."""
    project.index.sync()
    with project.index.connect() as conn:
        blobs = conn.execute(
            text(
                "SELECT content_blob FROM tasks WHERE kind = :k AND status = :claimed "
                "AND claim_session = :s"
            ),
            {"k": DRAFT_VERIFY_TASK_KIND, "claimed": TaskStatus.CLAIMED.value, "s": session},
        ).all()
        sentences = {
            str(r[0])
            for r in conn.execute(
                text("SELECT sentence_id FROM draft_sentences WHERE draft_id = :d"),
                {"d": draft_id},
            )
        }
    for (blob,) in blobs:
        try:
            content = project.blobs.get_json(str(blob))
        except (FactoryError, OSError, ValueError):
            continue
        if isinstance(content, dict) and content.get("sentence_id") in sentences:
            return True
    return False


def agent_drafts(project: Project, session: str) -> list[DraftRow]:
    """`list_drafts` for the agent path, without the drafts `session` verifies: it has a verdict
    on one or holds a verification task, and a verifier reads only its unit (R-51)."""
    return [
        row
        for row in list_drafts(project)
        if session not in verifier_sessions(project, row.draft_id)
        and not holds_verification(project, session, row.draft_id)
    ]


def _pinned_outline(project: Project, draft_id: str) -> Outline:
    _, _, _, blob = require_draft(project, draft_id)
    return Outline.model_validate(project.blobs.get_json(blob))


def _outline_refs(outline: Outline) -> frozenset[str]:
    refs: set[str] = set()
    for section in outline.sections:
        refs.update(section.supports)
        refs.update(r for conflict in section.conflicts for r in conflict)
    return frozenset(refs)


def sentence_rows(project: Project, draft_id: str, *, live: bool = True) -> list[SentenceRow]:
    where = " AND s.superseded_by IS NULL AND s.withdrawn = 0" if live else ""
    with project.index.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT s.sentence_id, s.section_id, s.ord, s.cls, s.text, s.author, "
                    "s.session, s.model, s.task_id, s.supersedes, s.event_id "
                    "FROM draft_sentences s JOIN draft_sections d "
                    "ON d.draft_id = s.draft_id AND d.section_id = s.section_id "
                    f"WHERE s.draft_id = :d{where} ORDER BY d.ord, s.ord, s.sentence_id"
                ),
                {"d": draft_id},
            )
            .mappings()
            .all()
        )
        ids = [str(r["sentence_id"]) for r in rows]
        supports: dict[str, list[str]] = {i: [] for i in ids}
        for sid, kind, ref in conn.execute(
            text(
                "SELECT sentence_id, kind, ref FROM sentence_supports "
                "WHERE sentence_id IN (SELECT value FROM json_each(:ids)) "
                "ORDER BY sentence_id, position"
            ),
            {"ids": json.dumps(ids)},
        ):
            supports[str(sid)].append(f"{kind}:{ref}")
        flags: dict[str, list[str]] = {i: [] for i in ids}
        for sid, flag in conn.execute(
            text(
                "SELECT sentence_id, flag FROM sentence_flags "
                "WHERE sentence_id IN (SELECT value FROM json_each(:ids)) ORDER BY flag"
            ),
            {"ids": json.dumps(ids)},
        ):
            flags[str(sid)].append(str(flag))
        stats: dict[str, dict[str, int]] = {i: {} for i in ids}
        for sid, stat, value in conn.execute(
            text(
                "SELECT sentence_id, stat, value FROM sentence_stats "
                "WHERE sentence_id IN (SELECT value FROM json_each(:ids))"
            ),
            {"ids": json.dumps(ids)},
        ):
            stats[str(sid)][str(stat)] = int(value)
    return [
        SentenceRow(
            sentence_id=str(r["sentence_id"]),
            draft_id=draft_id,
            section_id=str(r["section_id"]),
            order=int(r["ord"]),
            cls=SentenceClass(r["cls"]),
            text=str(r["text"]),
            supports=supports[str(r["sentence_id"])],
            stat_values=stats[str(r["sentence_id"])],
            flags=[SentenceFlag(f) for f in flags[str(r["sentence_id"])]],
            author=str(r["author"]),
            session=str(r["session"]),
            model=None if r["model"] is None else str(r["model"]),
            task_id=None if r["task_id"] is None else str(r["task_id"]),
            supersedes=None if r["supersedes"] is None else str(r["supersedes"]),
            event_id=str(r["event_id"]),
        )
        for r in rows
    ]


def live_sentences(project: Project, draft_id: str) -> list[SentenceRow]:
    """The draft's live sentences (not superseded, not withdrawn) in section then sentence order.
    The `off-outline` flag is recomputed against the outline the draft is pinned to now, so a
    repin marks sentences whose supports left the outline (advisory); the other flags are those
    stored at write time."""
    with entering():
        outline = _pinned_outline(project, draft_id)
        refs = _outline_refs(outline)
        rows = sentence_rows(project, draft_id)
        parsed = {r.sentence_id: [parse_support(s) for s in r.supports] for r in rows}
        cells = [s for ss in parsed.values() for s in ss if s.kind is SupportKind.CELL]
        groups: dict[str, tuple[str, ...]] = {}
        if cells:
            resolved = resolve_supports(project, cells, cls=SentenceClass.CLAIM)
            groups = {s.ref.text: s.group_ids for s in resolved}
        out: list[SentenceRow] = []
        for row in rows:
            flags: list[SentenceFlag] = [f for f in row.flags if f is not SentenceFlag.OFF_OUTLINE]
            if any(_off(s, refs, groups) for s in parsed[row.sentence_id]):
                flags.append(SentenceFlag.OFF_OUTLINE)
            out.append(row.model_copy(update={"flags": flags}))
        return out


def _off(support: SupportRef, refs: frozenset[str], groups: dict[str, tuple[str, ...]]) -> bool:
    if support.kind in (SupportKind.STAT, SupportKind.INTERP) or support.text in refs:
        return False
    return not (
        support.kind is SupportKind.CELL
        and any(f"group:{g}" in refs for g in groups.get(support.text, ()))
    )


def stale_reason(row: SentenceRow, resolved: Sequence[ResolvedSupport]) -> str | None:
    """Why the sentence no longer rests on its supports: the closed reason of the first support
    that stopped being eligible, or `stat-changed` when a stat recomputes to another value."""
    for support in resolved:
        if not support.eligible:
            return support.reason
    for support in resolved:
        stored = row.stat_values.get(support.ref.ref)
        if support.ref.kind is SupportKind.STAT and stored != support.stat_value:
            return "stat-changed"
    return None


def _unit_shown(project: Project, blob: str | None) -> dict[str, SupportShown] | None:
    """What the verdict's unit showed, by support; None when the unit cannot be read."""
    if blob is None:
        return None
    try:
        unit = project.blobs.get_json(blob)
        supports = unit.get("supports") if isinstance(unit, dict) else None
        if not isinstance(supports, list):
            return None
        shown = [SupportShown.model_validate(s) for s in supports]
    except (FactoryError, OSError, ValueError):
        return None
    return {s.ref: s for s in shown}


def support_changed(
    project: Project, resolved: Sequence[ResolvedSupport], blob: str | None
) -> bool:
    """Whether an eligible cell, item, claim or edge says other than the verdict's unit showed.
    A unit that cannot be read vouches for nothing, so it reads as changed (fail closed)."""
    shown = _unit_shown(project, blob)
    if shown is None:
        return True
    for support in resolved:
        if support.ref.kind in COMPARED_KINDS:
            then, now = shown.get(support.ref.text), support_shown(project, support)
            if then is None or (then.spans, then.unit) != (now.spans, now.unit):
                return True
    return False


def _latest_verdicts(project: Project, draft_id: str) -> dict[str, tuple[str, Verdict, str | None]]:
    """Sentence id to its latest verdict (id, verdict, the unit's blob), by log order."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT v.sentence_id, v.verdict_id, v.verdict, e.input_blob "
                "FROM sentence_verdicts v JOIN events e ON e.id = v.event_id "
                "WHERE v.draft_id = :d ORDER BY v.event_id"
            ),
            {"d": draft_id},
        ).all()
    return {
        str(r[0]): (str(r[1]), Verdict(str(r[2])), None if r[3] is None else str(r[3]))
        for r in rows
    }


def _resolved_by_sentence(
    project: Project, rows: Sequence[SentenceRow]
) -> dict[str, list[ResolvedSupport]]:
    """The supports of each sentence, resolved in one call per sentence class."""
    found: dict[tuple[SentenceClass, str], ResolvedSupport] = {}
    for cls in {r.cls for r in rows}:
        refs = {s: parse_support(s) for r in rows if r.cls is cls for s in r.supports}
        resolved = resolve_supports(project, list(refs.values()), cls=cls)
        found.update({(cls, s): one for s, one in zip(refs, resolved, strict=True)})
    return {r.sentence_id: [found[(r.cls, s)] for s in r.supports] for r in rows}


def _status_of(
    project: Project,
    row: SentenceRow,
    resolved: Sequence[ResolvedSupport],
    verdict: tuple[str, Verdict, str | None] | None,
    incorrect: frozenset[str],
) -> tuple[SentenceStatus, str | None]:
    stale = stale_reason(row, resolved)
    if stale is None and verdict is not None and support_changed(project, resolved, verdict[2]):
        stale = "support-changed"
    if stale is not None:
        return "stale", stale
    if row.cls is SentenceClass.STRUCTURAL:
        return "structural", None
    if row.cls is SentenceClass.INTERPRETIVE:
        return "interpretive", None
    if verdict is None:
        return "unchecked", None
    if verdict[1] is not Verdict.SUPPORTED:
        return "flagged", verdict[1].value
    if verdict[0] in incorrect:
        return "flagged", "audit-incorrect"
    return "supported", None


def sentence_status(
    project: Project, draft_id: str, *, agent: bool = False, session: str | None = None
) -> list[StatusRow]:
    """The status of each live sentence of the draft, in order. `agent` leaves the audit labels
    out (see the module invariants); the researcher's variant reads them. `session`, the reader an
    agent's tool names, is refused when it is verifying the draft."""
    with entering():
        if session is not None:
            refuse_verifier(project, draft_id, session)
        rows = live_sentences(project, draft_id)
        resolved = _resolved_by_sentence(project, rows)
        verdicts = _latest_verdicts(project, draft_id)
        incorrect = frozenset() if agent else incorrect_verdicts(project, draft_id)
        out: list[StatusRow] = []
        for row in rows:
            status, reason = _status_of(
                project, row, resolved[row.sentence_id], verdicts.get(row.sentence_id), incorrect
            )
            out.append(
                StatusRow(
                    sentence_id=row.sentence_id,
                    section_id=row.section_id,
                    order=row.order,
                    cls=row.cls,
                    status=status,
                    reason=reason,
                    flags=tuple(f.value for f in row.flags),
                )
            )
        return out


def status_counts(rows: Sequence[StatusRow]) -> dict[str, int]:
    """The count of each status, every status present."""
    return {status: sum(1 for r in rows if r.status == status) for status in SENTENCE_STATUSES}


def _works_by_sentence(
    project: Project, resolved: dict[str, list[ResolvedSupport]]
) -> dict[str, tuple[str, ...]]:
    primary = {
        absorbed: merge.primary
        for merge in active_merges(project)
        for absorbed in merge.absorbed
        if absorbed != merge.primary
    }
    return {
        sentence_id: tuple(
            dict.fromkeys(primary.get(w, w) for support in supports for w in support.work_ids)
        )
        for sentence_id, supports in resolved.items()
    }


def draft_works(project: Project, draft_id: str) -> list[str]:
    """The works of the supports of the draft's live sentences (ruling 8: every sentence that has
    a support is `supported`, interpretive or rendered with a marker), merges read as the primary;
    what `draft:<id>` selects before it is limited to the works of the project."""
    with entering():
        require_draft(project, draft_id)
        rows = live_sentences(project, draft_id)
        works = _works_by_sentence(project, _resolved_by_sentence(project, rows))
        return list(dict.fromkeys(w for row in rows for w in works[row.sentence_id]))


def draft_view(project: Project, draft_id: str) -> DraftView:
    """The draft's sections with their live sentences and each sentence's cited works."""
    with entering():
        title = require_draft(project, draft_id)[0]
        rows = live_sentences(project, draft_id)
        works = _works_by_sentence(project, _resolved_by_sentence(project, rows))
        sections = tuple(
            RenderedSection(
                section_id=section.section_id,
                heading=section.heading,
                sentences=tuple(
                    RenderedSentence(
                        sentence_id=r.sentence_id,
                        text=r.text,
                        supports=tuple(r.supports),
                        works=works[r.sentence_id],
                    )
                    for r in rows
                    if r.section_id == section.section_id
                ),
            )
            for section in _sections(project, draft_id)
        )
        return DraftView(draft_id=draft_id, title=title, sections=sections)


def _same_model_verdicts(project: Project, draft_id: str) -> int:
    with project.index.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM sentence_verdicts v JOIN draft_sentences s "
                    "ON s.sentence_id = v.sentence_id WHERE v.draft_id = :d AND v.model = s.model "
                    "AND s.superseded_by IS NULL AND s.withdrawn = 0"
                ),
                {"d": draft_id},
            ).scalar_one()
        )


def draft_render(
    project: Project,
    draft_id: str,
    mode: Literal["review", "clean"],
    *,
    agent: bool = False,
    session: str | None = None,
) -> str:
    """The draft as Markdown. `review` shows each sentence with its status, flags, supports and
    quotes; `clean` is the prose with citations and markers, ending with the bibliography note and
    the methods paragraph. Quotes are read from the extraction events' projection, never from the
    library. `agent` reads the agent variants of the status and of the audit, and says so under the
    title once any verdict is labelled. `session`, as in `sentence_status`, is refused when it is
    verifying the draft. Nothing is written: the caller decides where the text goes, and it is
    never under the project (spec ruling 8)."""
    with entering():
        if session is not None:
            refuse_verifier(project, draft_id, session)
        view = draft_view(project, draft_id)
        statuses = sentence_status(project, draft_id, agent=agent)
        report = audit_report(project, draft_id)
        if mode == "review":
            rows = live_sentences(project, draft_id)
            resolved = _resolved_by_sentence(project, rows)
            spans = {s.ref.text: s.spans for found in resolved.values() for s in found}
            body = render_review(view, statuses, spans)
        else:
            keys = assign_keys(select_works(project, f"draft:{draft_id}"))
            body = (
                render_clean(view, statuses, keys)
                + "\n"
                + render_closing(
                    draft_id,
                    statuses,
                    agent_audit_report(report) if agent else report,
                    _same_model_verdicts(project, draft_id),
                )
            )
        note = agent_audit_note(report) if agent else None
        return body if note is None else with_note(body, note)


def refuse_project_path(project: Project, path: Path) -> None:
    """A rendering goes to stdout or a path the researcher names, never under the project: the
    tree holds events and blobs, not renderings with quotes (spec ruling 8)."""
    if path.resolve().is_relative_to(project.paths.dir.resolve()):
        raise _refuse("out", "a rendering is not written under the project")


# --- Creating and repinning ---


def _call_blob(project: Project, actor: Actor, call: JsonValue) -> str | None:
    return project.blobs.put_json({"call": call}) if actor.kind == "agent" else None


def _scope_of(scope: OutlineScope) -> JsonValue:
    return scope.as_json()


def _heading(kind: str, title_ref: str) -> str:
    return "limits" if kind == "limits" else f"{kind} {title_ref}"[:200]


def create_draft(
    project: Project,
    *,
    title: str,
    kind: DraftKind,
    scope: OutlineScope = DEFAULT_SCOPE,
    actor: Actor,
) -> str:
    """Create a draft pinned to the outline of `scope` and return its `drf_` id. One section per
    outline section, `sec_01`, `sec_02`, ...; an agent's call is stored as the event's input."""
    _require_writer(actor)
    if not title.strip():
        raise _refuse("title", "a draft needs a title")
    if len(title.strip()) > MAX_TITLE:
        raise _refuse("title", f"at most {MAX_TITLE} characters")
    outline = build_outline(project, scope)  # a long read: outside the write lock
    if len(outline.sections) > MAX_SECTIONS:
        raise _refuse("scope", f"the outline has more than {MAX_SECTIONS} sections; narrow it")
    blob = project.blobs.put(outline_json(outline).encode())
    with project.index.exclusive():
        draft_id = project.ids.new("drf")
        payload = DraftCreated(
            draft_id=draft_id,
            title=title.strip(),
            kind=kind,
            outline_ref=outline.outline_id,
            outline_blob=blob,
            sections=[
                SectionDef(
                    section_id=f"sec_{i + 1:02d}",
                    heading=_heading(s.kind, s.title_ref),
                    outline_section=s.section_ref,
                )
                for i, s in enumerate(outline.sections)
            ],
        )
        call: JsonValue = {"title": title, "kind": kind.value, "scope": _scope_of(scope)}
        project.record(
            [
                project.events.make(
                    "draft.created",
                    payload,
                    actor,
                    refs=[draft_id, outline.outline_id],
                    input_blob=_call_blob(project, actor, call),
                )
            ]
        )
        return draft_id


def _refuse_verifier(project: Project, actor: Actor, draft_id: str) -> None:
    """A session with a verdict on the draft, or holding a verification task of it, must not
    reshape the draft it verifies (R-51, MS ruling 4)."""
    if identities(actor) & verifier_sessions(project, draft_id) or holds_verification(
        project, actor.session, draft_id
    ):
        raise _refuse("session", "a session that verifies this draft cannot change it")


def _new_sections(known: Sequence[SectionRow], outline: Outline) -> list[SectionDef]:
    """The outline's sections the draft does not hold, numbered after the last section id."""
    held = {s.outline_section for s in known}
    top = max((int(s.section_id.removeprefix("sec_")) for s in known), default=0)
    fresh = [s for s in outline.sections if s.section_ref not in held]
    if top + len(fresh) > MAX_SECTIONS:
        raise _refuse("scope", f"the draft would have more than {MAX_SECTIONS} sections; narrow it")
    return [
        SectionDef(
            section_id=f"sec_{top + i + 1:02d}",
            heading=_heading(s.kind, s.title_ref),
            outline_section=s.section_ref,
        )
        for i, s in enumerate(fresh)
    ]


def repin_outline(
    project: Project, draft_id: str, scope: OutlineScope | None = None, *, actor: Actor
) -> str:
    """Pin the draft to a new outline (the same scope unless `scope` is given). Sentences whose
    supports are not in it read as `off-outline`; nothing is rewritten. Sections new to the draft
    are added, so `draft_next` serves them; a section the outline dropped stays, and its slot says
    `outline-section-gone`. Refused to a verifier. Returns the event id."""
    _require_writer(actor)
    current = _pinned_outline(project, draft_id)
    _refuse_verifier(project, actor, draft_id)
    if scope is None:
        scope = OutlineScope.from_json(current.scope)
    outline = build_outline(project, scope)  # a long read: outside the write lock
    blob = project.blobs.put(outline_json(outline).encode())
    with project.index.exclusive():
        project.index.sync()
        _refuse_verifier(project, actor, draft_id)
        event = project.events.make(
            "draft.outline_repinned",
            DraftOutlineRepinned(
                draft_id=draft_id,
                outline_ref=outline.outline_id,
                outline_blob=blob,
                sections=_new_sections(_sections(project, draft_id), outline),
            ),
            actor,
            refs=[draft_id, outline.outline_id],
            input_blob=_call_blob(
                project, actor, {"draft_id": draft_id, "scope": _scope_of(scope)}
            ),
        )
        project.record([event])
        return event.id


# --- Writing sentences ---


def _context(project: Project, rows: Sequence[SentenceRow]) -> DraftContext:
    """What a structural sentence may not name, read from the supports of the draft's live
    sentences."""
    refs = list(dict.fromkeys(parse_support(s) for r in rows for s in r.supports))
    refs = [r for r in refs if r.kind is not SupportKind.INTERP]
    if not refs:
        return DraftContext()
    resolved = resolve_supports(project, refs, cls=SentenceClass.CLAIM)
    return _context_of(resolved)


def _context_of(resolved: Sequence[ResolvedSupport]) -> DraftContext:
    """The names a structural sentence may not use. A stale support still counts: its sentence is
    live, so it still names those works."""
    return DraftContext(
        first_authors=frozenset(a for s in resolved for a in s.first_authors),
        method_names=frozenset(m for s in resolved for m in s.method_names),
    )


def _merge(a: DraftContext, resolved: Sequence[ResolvedSupport]) -> DraftContext:
    more = _context_of(resolved)
    return DraftContext(a.first_authors | more.first_authors, a.method_names | more.method_names)


def _task_checks(
    project: Project, actor: Actor, draft_id: str, task_id: str | None
) -> tuple[str | None, str | None, list[ValidationIssue]]:
    """The task blob an agent's call was served as, the section of that slot task, and the issues
    with the task named."""
    if actor.kind == "human":
        return (
            None,
            None,
            ([ValidationIssue("task_id", "a human writes without a task")] if task_id else []),
        )
    if task_id is None:
        return None, None, []
    try:
        task = require_holder(project, actor, task_id)
    except FactoryValidationError as exc:
        return None, None, exc.issues
    if task.kind != DRAFT_SLOT_TASK_KIND:
        return None, None, [ValidationIssue("task_id", "not a writing slot task")]
    content = task_content(project, task)
    if not isinstance(content, dict) or content.get("draft_id") != draft_id:
        return None, None, [ValidationIssue("task_id", "the task is for another draft")]
    if content.get("outline") != require_draft(project, draft_id)[2]:
        issue = ValidationIssue("task_id", "the draft was repinned: ask draft_next again")
        return None, None, [issue]
    return task.content_blob, str(content.get("section_id")), []


def write_sentences(
    project: Project,
    draft_id: str,
    items: Sequence[SentenceInput],
    *,
    actor: Actor,
    input_blob: str | None = None,
    task_id: str | None = None,
) -> BatchResult[str]:
    """Check and record sentences; each stands or falls alone and the result lists the written
    sentence ids and the rejected items (position and issues). The whole call is refused, with
    nothing written, for an unknown draft, a wrong actor or task, or a session that verified the
    draft. A slot task takes sentences of its own section only. An agent's call completes its slot
    task once it has written a sentence, and a call that writes none stores no input blob."""
    _require_writer(actor)
    with project.index.exclusive(), entering():
        project.index.sync()
        require_draft(project, draft_id)
        if identities(actor) & verifier_sessions(project, draft_id):
            raise _refuse("session", "a session that verified this draft cannot write in it")
        task_blob, task_section, task_issues = _task_checks(project, actor, draft_id, task_id)
        if task_issues:
            raise FactoryValidationError(task_issues)
        sections = {s.section_id for s in _sections(project, draft_id)}
        outline_refs = _outline_refs(_pinned_outline(project, draft_id))
        existing = sentence_rows(project, draft_id)
        context = _context(project, existing)
        top: dict[str, int] = {}
        for row in existing:
            top[row.section_id] = max(top.get(row.section_id, 0), row.order)
        live_ids = {r.sentence_id: r for r in existing}
        accepted: list[tuple[SentenceRecorded, str | None]] = []
        rejected: list[ItemError] = []
        for index, item in enumerate(items):
            if task_section is not None and item.section_id != task_section:
                issue = ValidationIssue("section_id", "the task is for another section")
                rejected.append(ItemError(index=index, issues=[issue]))
                continue
            issues, payload, resolved = _prepare(
                project,
                draft_id,
                item,
                sections,
                live_ids,
                top,
                context,
                outline_refs,
                actor,
                task_id,
            )
            if issues or payload is None:
                rejected.append(ItemError(index=index, issues=issues))
                continue
            top[item.section_id] = max(top.get(item.section_id, 0), payload.order)
            context = _merge(context, resolved)
            if item.supersedes is not None:
                live_ids.pop(item.supersedes, None)
            accepted.append((payload, item.supersedes))
        if accepted and actor.kind == "agent" and input_blob is None:
            call: JsonValue = [i.model_dump(mode="json") for i in items]
            input_blob = project.blobs.put_json({"task_input": task_blob, "call": call})
        events: list[Event] = [
            project.events.make(
                "draft.sentence_recorded",
                payload,
                actor,
                refs=[
                    payload.sentence_id,
                    draft_id,
                    *(s.ref for s in payload.supports),
                    *([supersedes] if supersedes else []),
                ],
                input_blob=input_blob,
            )
            for payload, supersedes in accepted
        ]
        written = [payload.sentence_id for payload, _ in accepted]
        if events and actor.kind == "agent" and task_id is not None and task_blob is not None:
            events.append(
                project.events.make(
                    "task.completed",
                    TaskCompleted(task_id=task_id, result_refs=tuple(written)),
                    actor,
                    refs=(task_id,),
                    input_blob=task_blob,
                )
            )
        if events:
            project.record(events)
        return BatchResult[str](written=written, rejected=rejected)


def _order_of(item: SentenceInput, live: dict[str, SentenceRow], top: dict[str, int]) -> int:
    if item.order is not None:
        return item.order
    if item.supersedes is not None and item.supersedes in live:
        return live[item.supersedes].order
    return top.get(item.section_id, 0) + ORDER_STEP


def _prepare(
    project: Project,
    draft_id: str,
    item: SentenceInput,
    sections: set[str],
    live: dict[str, SentenceRow],
    top: dict[str, int],
    context: DraftContext,
    outline_refs: frozenset[str],
    actor: Actor,
    task_id: str | None,
) -> tuple[list[ValidationIssue], SentenceRecorded | None, list[ResolvedSupport]]:
    issues: list[ValidationIssue] = []
    if item.section_id not in sections:
        issues.append(ValidationIssue("section_id", "unknown section"))
    if item.supersedes is not None:
        old = live.get(item.supersedes)
        if old is None or old.section_id != item.section_id:
            issues.append(ValidationIssue("supersedes", "not a live sentence of this section"))
    if not item.text.strip() or len(item.text) > SENTENCE_MAX_CHARS:
        issues.append(
            ValidationIssue("text", f"a sentence has 1 to {SENTENCE_MAX_CHARS} characters")
        )
    if len(item.supports) > MAX_SUPPORTS:
        issues.append(ValidationIssue("supports", f"at most {MAX_SUPPORTS} supports"))
    order = _order_of(item, live, top)
    if not 0 <= order <= MAX_ORDER:
        issues.append(ValidationIssue("order", f"an order is 0 to {MAX_ORDER}"))
    refs: list[SupportRef] = []
    for position, raw in enumerate(item.supports):
        try:
            refs.append(parse_support(raw))
        except ValueError:
            issues.append(ValidationIssue(f"supports[{position}]", "malformed"))
    if len({r.text for r in refs}) != len(refs):
        issues.append(ValidationIssue("supports", "supports must be distinct"))
    if issues:
        return issues, None, []
    resolved = resolve_supports(project, refs, cls=item.cls)
    outcome = check_sentence(
        item.text, item.cls, resolved, draft_context=context, outline_refs=outline_refs
    )
    if outcome.refusals:
        return list(outcome.refusals), None, resolved
    payload = SentenceRecorded(
        sentence_id=project.ids.new("snt"),
        draft_id=draft_id,
        section_id=item.section_id,
        order=order,
        cls=item.cls,
        text=item.text,
        supports=refs,
        stat_values={s.ref.ref: s.stat_value for s in resolved if s.stat_value is not None},
        stats_version=STATS_VERSION,
        flags=list(outcome.flags),
        author="agent" if actor.kind == "agent" else "human",
        task_id=task_id,
        supersedes=item.supersedes,
    )
    return [], payload, resolved


# --- Withdrawing and reordering ---


def withdraw(project: Project, sentence_id: str, reason: str, *, actor: Actor) -> str:
    """Withdraw a live sentence (it stays in the log). Refused to a verifier of its draft. Returns
    the event id."""
    _require_writer(actor)
    with project.index.exclusive():
        project.index.sync()
        with project.index.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT draft_id, superseded_by, withdrawn FROM draft_sentences "
                    "WHERE sentence_id = :s"
                ),
                {"s": sentence_id},
            ).first()
        if row is None:
            raise _refuse("sentence_id", "unknown sentence")
        if row[1] is not None or row[2]:
            raise _refuse("sentence_id", "not a live sentence")
        _refuse_verifier(project, actor, str(row[0]))
        if not reason.strip():
            raise _refuse("reason", "state the reason")
        if len(reason.strip()) > MAX_REASON:
            raise _refuse("reason", f"at most {MAX_REASON} characters")
        event = project.events.make(
            "draft.sentence_withdrawn",
            SentenceWithdrawn(sentence_id=sentence_id, reason=reason.strip()),
            actor,
            refs=[sentence_id, str(row[0])],
            input_blob=_call_blob(project, actor, {"sentence_id": sentence_id}),
        )
        project.record([event])
        return event.id


def reorder(
    project: Project, draft_id: str, section_id: str, order: Sequence[str], *, actor: Actor
) -> str:
    """Set the order of a section's live sentences; `order` must list exactly those. Refused to a
    verifier of the draft. Returns the event id."""
    _require_writer(actor)
    with project.index.exclusive():
        require_draft(project, draft_id)
        _refuse_verifier(project, actor, draft_id)
        if section_id not in {s.section_id for s in _sections(project, draft_id)}:
            raise _refuse("section_id", "unknown section")
        live = {
            r.sentence_id for r in sentence_rows(project, draft_id) if r.section_id == section_id
        }
        if set(order) != live or len(set(order)) != len(order):
            raise _refuse("order", "list exactly the live sentences of the section, once each")
        event = project.events.make(
            "draft.reordered",
            DraftReordered(draft_id=draft_id, section_id=section_id, order=list(order)),
            actor,
            refs=[draft_id],
            input_blob=_call_blob(
                project,
                actor,
                {"draft_id": draft_id, "section_id": section_id, "order": list(order)},
            ),
        )
        project.record([event])
        return event.id


# --- Slots ---


def _slot_content(project: Project, draft_id: str, section: SectionRow) -> dict[str, JsonValue]:
    outline = _pinned_outline(project, draft_id)
    found = [s for s in outline.sections if s.section_ref == section.outline_section]
    content: dict[str, JsonValue] = {
        "draft_id": draft_id,
        "section_id": section.section_id,
        "heading": section.heading,
        "outline": outline.outline_id,
        "outline_section": section.outline_section,
        "kind": None,
        "works": [],
        "supports": [],
        "conflicts": [],
        "notes": [],
        "omitted": 0,
        "sentences": [
            {"sentence_id": r.sentence_id, "class": r.cls.value, "text": r.text}
            for r in sentence_rows(project, draft_id)
            if r.section_id == section.section_id
        ],
    }
    if not found:
        content["notes"] = ["outline-section-gone"]
        return content
    s = found[0]
    refs = list(dict.fromkeys([*s.supports, *(r for c in s.conflicts for r in c)]))
    parsed = [parse_support(r) for r in refs]
    resolved = resolve_supports(project, parsed, cls=SentenceClass.CLAIM)
    shown: list[JsonValue] = []
    for r in resolved:
        if not r.eligible:
            continue
        entry: dict[str, JsonValue] = {
            "ref": r.ref.text,
            "works": list(r.work_ids),
            "quotes": list(r.spans),
            "numbers": [str(n) for n in r.numbers],
            "years": list(r.years),
        }
        if r.stat_value is not None:
            entry["stat_value"] = r.stat_value
        entry.update(dict(r.extra))
        shown.append(entry)
    content.update(
        {
            "kind": s.kind,
            "works": list(s.works),
            "supports": shown,
            "conflicts": [list(c) for c in s.conflicts],
            "notes": list(s.notes),
            "omitted": len(resolved) - len(shown),
        }
    )
    return content


def _open_slot_task(project: Project, draft_id: str, section_id: str) -> str | None:
    """The section's slot task not completed, under the outline the draft is pinned to: a task of
    an earlier pin holds old content, and a release would only offer it again."""
    pinned = require_draft(project, draft_id)[2]
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT task_id, content_blob FROM tasks WHERE kind = :k AND status != :done"),
            {"k": DRAFT_SLOT_TASK_KIND, "done": TaskStatus.COMPLETED.value},
        ).all()
    for task_id, blob in rows:
        try:
            content = project.blobs.get_json(str(blob))
        except (FactoryError, OSError, ValueError):
            continue  # a hand-written task blocks nothing
        if (
            isinstance(content, dict)
            and content.get("draft_id") == draft_id
            and content.get("section_id") == section_id
            and content.get("outline") == pinned
        ):
            return str(task_id)
    return None


def draft_next(
    project: Project, draft_id: str, *, section_id: str | None = None, actor: Actor
) -> SlotTask | None:
    """Serve the next section of the draft with no live sentence (or the named one) as a task
    claimed by `actor`, its content listing the section's eligible supports with their quotes and
    stored as the task's input. A task this session already holds is served again; a section whose
    task another session holds is passed over. None when nothing is left to serve. Refused to a
    session verifying the draft: a slot shows the section's sentences."""
    if actor.kind != "agent":
        raise _refuse("actor", "only an agent is served a task")
    with project.index.exclusive(), entering():
        project.index.sync()
        require_draft(project, draft_id)
        refuse_verifier(project, draft_id, actor.session)
        sections = _sections(project, draft_id)
        if section_id is not None and section_id not in {s.section_id for s in sections}:
            raise _refuse("section_id", "unknown section")
        written = {r.section_id for r in sentence_rows(project, draft_id)}
        for section in sections:
            if section_id is not None and section.section_id != section_id:
                continue
            if section_id is None and section.section_id in written:
                continue
            task_id = _open_slot_task(project, draft_id, section.section_id)
            if task_id is None:
                content = _slot_content(project, draft_id, section)
                made = create_tasks(
                    project,
                    project.system_actor(),
                    [TaskSpec(DRAFT_SLOT_TASK_KIND, content, refs=(draft_id, section.section_id))],
                )
                task_id = made.written[0]
            claimed: Task | None
            try:
                claimed = require_holder(project, actor, task_id)  # already ours: serve it again
            except FactoryValidationError:
                claimed = claim_next(project, actor, DRAFT_SLOT_TASK_KIND, task_ids={task_id})
            if claimed is None:
                continue
            served = task_content(project, claimed)
            assert isinstance(served, dict)
            return SlotTask(claimed.task_id, draft_id, section.section_id, served)
        return None

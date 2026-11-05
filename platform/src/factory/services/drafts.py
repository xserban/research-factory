"""Drafts, slots and sentence recording (slice 7b, plan W-A, task 5).

Declares: `create_draft`, `repin_outline`, `write_sentences`, `withdraw`, `reorder`, `draft_next`,
`live_sentences`, `get_draft`, `list_drafts`, `verifier_sessions`, `SentenceInput`, `SentenceRow`,
`SlotTask`. The only module that writes `draft.*` events.

Invariants:
- The platform never writes prose. Sentences are the writer's; the platform checks them
  (`writing.checks`), stores their supports as ids and their stat values as computed, and serves
  the quotes of the supports only in a slot task's content, read from the projection of the
  extraction events (R-47: no library read). No `draft.*` event carries quote text.
- Partial acceptance: each sentence of a batch stands or falls alone. A sentence with one ineligible
  support among valid ones is refused whole; another valid sentence of the same call is written.
- Every agent-written event carries the call and the task content it was served as its
  `input_blob` (R-04). A human writes without a task.
- A session that has verified a sentence of a draft cannot write in it (`verifier_sessions`).
- A refusal writes nothing and carries positions and fixed codes, never document text.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import Field, JsonValue
from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor, Event
from factory.index.drafts import identities, verifiers_of
from factory.model.base import StrictModel
from factory.model.drafts import (
    MAX_ORDER,
    MAX_SUPPORTS,
    SENTENCE_MAX_CHARS,
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
    parse_support,
)
from factory.model.task import DRAFT_SLOT_TASK_KIND, Task, TaskCompleted, TaskStatus
from factory.services.call_memo import entering
from factory.services.context import Project
from factory.services.outline import DEFAULT_SCOPE, OutlineScope, build_outline, outline_json
from factory.services.results import BatchResult, ItemError
from factory.services.supports import ResolvedSupport, resolve_supports
from factory.services.tasks import (
    TaskSpec,
    claim_next,
    create_tasks,
    require_holder,
    task_content,
)
from factory.writing.checks import DraftContext, check_sentence
from factory.writing.stats import STATS_VERSION

ORDER_STEP = 10
MAX_SECTIONS = 99


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


def provisional_status(cls: SentenceClass) -> str:
    """The status a sentence has until the verification plan (W-B) adds verdicts: `structural` and
    `interpretive` sentences are what they are; a claim or synthesis is `unchecked`."""
    if cls in (SentenceClass.STRUCTURAL, SentenceClass.INTERPRETIVE):
        return cls.value
    return "unchecked"


def verifier_sessions(project: Project, draft_id: str) -> frozenset[str]:
    """The `identities` (sessions, and humans by id) with a verdict on a sentence of the draft."""
    project.index.sync()
    with project.index.connect() as conn:
        return verifiers_of(conn, draft_id)


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
    outline = build_outline(project, scope)  # a long read: outside the write lock
    if len(outline.sections) > MAX_SECTIONS:
        raise _refuse("scope", f"the outline has more than {MAX_SECTIONS} sections; narrow it")
    blob = project.blobs.put(outline_json(outline).encode())
    with project.index.exclusive():
        draft_id = project.ids.new("drf")
        payload = DraftCreated(
            draft_id=draft_id,
            title=title.strip()[:200],
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


def repin_outline(
    project: Project, draft_id: str, scope: OutlineScope | None = None, *, actor: Actor
) -> str:
    """Pin the draft to a new outline (the same scope unless `scope` is given). Sentences whose
    supports are not in it read as `off-outline`; nothing is rewritten. Returns the event id."""
    _require_writer(actor)
    current = _pinned_outline(project, draft_id)
    if scope is None:
        scope = OutlineScope.from_json(current.scope)
    outline = build_outline(project, scope)  # a long read: outside the write lock
    blob = project.blobs.put(outline_json(outline).encode())
    with project.index.exclusive():
        event = project.events.make(
            "draft.outline_repinned",
            DraftOutlineRepinned(
                draft_id=draft_id, outline_ref=outline.outline_id, outline_blob=blob
            ),
            actor,
            refs=[draft_id, outline.outline_id],
            input_blob=_call_blob(project, actor, {"draft_id": draft_id}),
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
    return DraftContext(
        first_authors=frozenset(a for s in resolved if s.eligible for a in s.first_authors),
        method_names=frozenset(m for s in resolved if s.eligible for m in s.method_names),
    )


def _merge(a: DraftContext, resolved: Sequence[ResolvedSupport]) -> DraftContext:
    more = _context_of(resolved)
    return DraftContext(a.first_authors | more.first_authors, a.method_names | more.method_names)


def _task_checks(
    project: Project, actor: Actor, draft_id: str, task_id: str | None
) -> tuple[str | None, list[ValidationIssue]]:
    """The task blob an agent's call was served as, and the issues with the task named."""
    if actor.kind == "human":
        return None, (
            [ValidationIssue("task_id", "a human writes without a task")] if task_id else []
        )
    if task_id is None:
        return None, []
    try:
        task = require_holder(project, actor, task_id)
    except FactoryValidationError as exc:
        return None, exc.issues
    if task.kind != DRAFT_SLOT_TASK_KIND:
        return None, [ValidationIssue("task_id", "not a writing slot task")]
    content = task_content(project, task)
    if not isinstance(content, dict) or content.get("draft_id") != draft_id:
        return None, [ValidationIssue("task_id", "the task is for another draft")]
    return task.content_blob, []


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
    draft. An agent's call completes its slot task once it has written a sentence."""
    _require_writer(actor)
    with project.index.exclusive(), entering():
        project.index.sync()
        require_draft(project, draft_id)
        if identities(actor) & verifier_sessions(project, draft_id):
            raise _refuse("session", "a session that verified this draft cannot write in it")
        task_blob, task_issues = _task_checks(project, actor, draft_id, task_id)
        if task_issues:
            raise FactoryValidationError(task_issues)
        if actor.kind == "agent" and input_blob is None:
            call: JsonValue = [i.model_dump(mode="json") for i in items]
            input_blob = project.blobs.put_json({"task_input": task_blob, "call": call})
        sections = {s.section_id for s in _sections(project, draft_id)}
        outline_refs = _outline_refs(_pinned_outline(project, draft_id))
        existing = sentence_rows(project, draft_id)
        context = _context(project, existing)
        top: dict[str, int] = {}
        for row in existing:
            top[row.section_id] = max(top.get(row.section_id, 0), row.order)
        live_ids = {r.sentence_id: r for r in existing}
        events: list[Event] = []
        written: list[str] = []
        rejected: list[ItemError] = []
        for index, item in enumerate(items):
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
            events.append(
                project.events.make(
                    "draft.sentence_recorded",
                    payload,
                    actor,
                    refs=[
                        payload.sentence_id,
                        draft_id,
                        *(s.ref for s in payload.supports),
                        *([item.supersedes] if item.supersedes else []),
                    ],
                    input_blob=input_blob,
                )
            )
            written.append(payload.sentence_id)
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
    """Withdraw a live sentence (it stays in the log). Returns the event id."""
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
        if not reason.strip():
            raise _refuse("reason", "state the reason")
        event = project.events.make(
            "draft.sentence_withdrawn",
            SentenceWithdrawn(sentence_id=sentence_id, reason=reason.strip()[:300]),
            actor,
            refs=[sentence_id, str(row[0])],
            input_blob=_call_blob(project, actor, {"sentence_id": sentence_id}),
        )
        project.record([event])
        return event.id


def reorder(
    project: Project, draft_id: str, section_id: str, order: Sequence[str], *, actor: Actor
) -> str:
    """Set the order of a section's live sentences; `order` must list exactly those. Returns the
    event id."""
    _require_writer(actor)
    with project.index.exclusive():
        require_draft(project, draft_id)
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
            input_blob=_call_blob(project, actor, {"draft_id": draft_id}),
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
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT task_id, content_blob FROM tasks WHERE kind = :k AND status != :done"),
            {"k": DRAFT_SLOT_TASK_KIND, "done": TaskStatus.COMPLETED.value},
        ).all()
    for task_id, blob in rows:
        content = project.blobs.get_json(str(blob))
        if (
            isinstance(content, dict)
            and content.get("draft_id") == draft_id
            and content.get("section_id") == section_id
        ):
            return str(task_id)
    return None


def draft_next(
    project: Project, draft_id: str, *, section_id: str | None = None, actor: Actor
) -> SlotTask | None:
    """Serve the next section of the draft with no live sentence (or the named one) as a task
    claimed by `actor`, its content listing the section's eligible supports with their quotes and
    stored as the task's input. A task this session already holds is served again; a section whose
    task another session holds is passed over. None when nothing is left to serve."""
    if actor.kind != "agent":
        raise _refuse("actor", "only an agent is served a task")
    with project.index.exclusive(), entering():
        project.index.sync()
        require_draft(project, draft_id)
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

"""Answers of the papers chat in Ask mode: record, rate, view, list (plan spar-night N2).

An answer is the recorded result of an Ask session: the question, the selection it was asked over
and sentences, each resting on one verified quote. The platform judges nothing: the agent writes
the sentences; the platform verifies every quote, checks the selection and computes the counts.

Invariants:
- Written only by an agent session (`chat.answer_recorded`, with the session's model, skill and an
  `input_blob`); the rating (`chat.answer_rated`) only by a human, here and in the projection. A
  refusal writes nothing and reports every issue together, located as `sentences[i].<field>` or a
  plain field.
- The caller names the digest of the selection it worked on; the selection must still resolve to
  that digest, else the answer is stale and is asked again. This is checked again under the lock.
- A sentence names a work of the selection, an anchor and a quote that `chat_verify` accepts in the
  conversation the selection pins; the verified conversion id and markdown hash are recorded with
  it. A sentence without a verified quote is refused: there is no unsupported sentence. An answer
  has at least one sentence, or an `unanswered` note saying what the papers do not answer.
- `parent`, when given, is an earlier answer or sheet of the project.
- A view shows each sentence with the full paragraph of its anchor, read from the pinned
  conversion, next to the quote. Counts (sentences, works, ratings per value, unrated) are computed
  from the folded rows. A rating is the researcher's; nothing here states a verdict.
- Held-out handling is that of the tools that call this module (scrub of every reply).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, get_args

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.index.answers import WHOLE
from factory.model.answers import (
    ANSWER_ID_RE,
    NOTE_MAX,
    PARENT_RE,
    QUESTION_MAX,
    SENTENCE_MAX,
    UNANSWERED_MAX,
    AnswerRated,
    AnswerRating,
    AnswerRecorded,
    AnswerSentence,
    SelectionWork,
)
from factory.services.chat_read import VerifyItem, chat_verify
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.selection import SelectionSpec, resolve_selection_cached
from factory.services.work_ref import resolve_work_id

__all__ = [
    "RATING_LABEL",
    "AnswerCounts",
    "AnswerInfo",
    "AnswerView",
    "SentenceInput",
    "SentenceView",
    "list_answers",
    "rate_answer",
    "record_answer",
    "view_answer",
]

RATING_LABEL = (
    "Counts are computed. A verified quote is not a verified reading: a sentence is the writer's "
    "reading of its paragraph, and a rating is the researcher's."
)


@dataclass(frozen=True)
class SentenceInput:
    """One sentence as an agent proposes it."""

    text: str
    work_id: str
    anchor: str
    quote: str


@dataclass(frozen=True)
class AnswerInfo:
    answer_id: str
    question: str
    mode: str
    selection_digest: str
    parent: str | None
    sentences: int
    actor: str
    session: str | None
    model: str | None
    ts: str


@dataclass(frozen=True)
class SentenceView:
    index: int
    text: str
    work_id: str
    anchor: str
    quote: str
    paragraph: str
    conversion_id: str
    markdown_hash: str
    rating: str | None
    rating_note: str | None


@dataclass(frozen=True)
class AnswerCounts:
    """Computed from the folded rows, never typed."""

    sentences: int
    works: int
    ratings: dict[str, int]
    unrated: int


@dataclass(frozen=True)
class AnswerView:
    info: AnswerInfo
    sentences: tuple[SentenceView, ...]
    unanswered: str | None
    rating: str | None
    rating_note: str | None
    counts: AnswerCounts
    rating_label: str = RATING_LABEL
    selection: dict[str, Any] = field(default_factory=dict)


def _issue(field_name: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_name, message)])


def _parent_exists(project: Project, parent: str) -> bool:
    table, column = (
        ("answers", "answer_id") if parent.startswith("ans_") else ("sheets", "sheet_id")
    )
    with project.index.connect() as conn:
        return (
            conn.execute(text(f"SELECT 1 FROM {table} WHERE {column} = :p"), {"p": parent}).first()
            is not None
        )


def record_answer(
    project: Project,
    actor: Actor,
    question: str,
    spec: SelectionSpec,
    selection_digest: str,
    sentences: Sequence[SentenceInput],
    *,
    unanswered: str | None = None,
    parent: str | None = None,
) -> AnswerRecorded:
    """Record one answer, all or none (see the module invariants). Raises `FactoryValidationError`
    (nothing written) for a non-agent actor, a bad question, note or parent, a stale selection,
    an answer with neither sentences nor an `unanswered` note, and every sentence whose text is
    out of bounds, whose work is not in the selection or whose quote `chat_verify` does not
    accept."""
    import re

    if actor.kind != "agent":
        raise _issue("actor", "an agent session records an answer")
    issues: list[ValidationIssue] = []
    question = question.strip()
    if not question or len(question) > QUESTION_MAX:
        issues.append(ValidationIssue("question", f"a question has 1 to {QUESTION_MAX} characters"))
    note = (unanswered or "").strip() or None
    if note is not None and len(note) > UNANSWERED_MAX:
        issues.append(
            ValidationIssue("unanswered", f"a note has at most {UNANSWERED_MAX} characters")
        )
    if not sentences and note is None:
        issues.append(
            ValidationIssue("sentences", "give at least one sentence, or say what is unanswered")
        )
    project.index.sync()
    if parent is not None and (
        re.fullmatch(PARENT_RE, parent) is None or not _parent_exists(project, parent)
    ):
        issues.append(ValidationIssue("parent", f"{parent}: no such answer or sheet"))
    selection = resolve_selection_cached(project, spec)
    if selection.digest != selection_digest:
        issues.append(
            ValidationIssue(
                "selection_digest", "the selection changed since it was resolved; ask again"
            )
        )
    pinned = {w.work_id: w.conversion_id for w in selection.works}
    checks: list[tuple[int, str]] = []
    for i, s in enumerate(sentences):
        at = f"sentences[{i}]"
        if not s.text.strip() or len(s.text.strip()) > SENTENCE_MAX:
            issues.append(
                ValidationIssue(f"{at}.text", f"a sentence has 1 to {SENTENCE_MAX} characters")
            )
        if not s.anchor.strip():
            issues.append(ValidationIssue(f"{at}.anchor", "is required"))
        if not s.quote.strip():
            issues.append(ValidationIssue(f"{at}.quote", "is required"))
        try:
            work = resolve_work_id(project, s.work_id, field=f"{at}.work_id")
        except FactoryValidationError as err:
            issues.extend(err.issues)
            continue
        if work not in pinned:
            issues.append(ValidationIssue(f"{at}.work_id", f"{work}: not in the selection"))
            continue
        if s.anchor.strip() and s.quote.strip():
            checks.append((i, work))
    verdicts: dict[int, Any] = {}
    if checks:
        items = [
            VerifyItem(work, sentences[i].anchor.strip(), sentences[i].quote, pinned[work])
            for i, work in checks
        ]
        for (i, _work), verdict in zip(checks, chat_verify(project, items), strict=True):
            verdicts[i] = verdict
            if verdict.status != "accepted":
                issues.append(
                    ValidationIssue(
                        f"sentences[{i}].quote", f"{verdict.status}: {verdict.item.anchor}"
                    )
                )
    if issues:
        raise FactoryValidationError(issues)
    blob = project.blobs.put_json(
        {
            "question": question,
            "selection_digest": selection_digest,
            "verified": [
                {
                    "sentence": i,
                    "work_id": v.item.work_id,
                    "anchor": v.item.anchor,
                    "quote": v.item.quote,
                    "status": v.status,
                    "conversion_id": v.conversion_id,
                    "markdown_hash": v.markdown_hash,
                }
                for i, v in sorted(verdicts.items())
            ],
        }
    )
    with project.index.exclusive():
        project.index.sync()
        again = resolve_selection_cached(project, spec)
        if again.digest != selection_digest:
            raise _issue(
                "selection_digest", "the selection changed since it was resolved; ask again"
            )
        if parent is not None and not _parent_exists(project, parent):
            raise _issue("parent", f"{parent}: no such answer or sheet")
        payload = AnswerRecorded(
            answer_id=project.ids.new("ans"),
            question=question,
            selection=spec.model_dump(mode="json"),
            selection_digest=selection_digest,
            selection_works=tuple(
                SelectionWork(work_id=w.work_id, conversion_id=w.conversion_id) for w in again.works
            ),
            parent=parent,
            sentences=tuple(
                AnswerSentence(
                    text=s.text.strip(),
                    work_id=verdicts[i].item.work_id,
                    anchor=s.anchor.strip(),
                    quote=s.quote,
                    conversion_id=str(verdicts[i].conversion_id),
                    markdown_hash=str(verdicts[i].markdown_hash),
                )
                for i, s in enumerate(sentences)
            ),
            unanswered=note,
        )
        event = project.events.make(
            "chat.answer_recorded", payload, actor, refs=(payload.answer_id,), input_blob=blob
        )
        project.record([event])
    return payload


def rate_answer(
    project: Project,
    actor: Actor,
    answer_id: str,
    rating: str,
    note: str = "",
    *,
    sentence: int | None = None,
) -> AnswerRated:
    """The researcher's rating of an answer (`sentence` None) or of one of its sentences (sound,
    weak or wrong); the latest rating stands. Refused (nothing written) for anyone but a human,
    an unknown answer or sentence index, a rating that is not one of the three, or a long note."""
    if actor.kind != "human":
        raise _issue("actor", "a rating is the researcher's act")
    if rating not in get_args(AnswerRating):
        raise _issue("rating", f"{rating}: must be sound, weak or wrong")
    if len(note) > NOTE_MAX:
        raise _issue("note", f"a note has at most {NOTE_MAX} characters")
    project.index.sync()
    with project.index.connect() as conn:
        found = conn.execute(
            text("SELECT sentence_count FROM answers WHERE answer_id = :a"), {"a": answer_id}
        ).first()
    if found is None:
        raise _issue("answer_id", f"{answer_id}: no such answer")
    if sentence is not None and not 0 <= sentence < int(found[0]):
        raise _issue("sentence", f"{sentence}: the answer has {int(found[0])} sentence(s)")
    payload = AnswerRated(answer_id=answer_id, sentence=sentence, rating=rating, note=note)
    with project.index.exclusive():
        project.record(
            [project.events.make("chat.answer_rated", payload, actor, refs=(answer_id,))]
        )
    return payload


def _info(row: Any) -> AnswerInfo:
    return AnswerInfo(
        answer_id=row["answer_id"],
        question=row["question"],
        mode=row["mode"],
        selection_digest=row["selection_digest"],
        parent=row["parent"],
        sentences=int(row["sentence_count"]),
        actor=row["actor"],
        session=row["session"],
        model=row["model"],
        ts=row["ts"],
    )


def list_answers(project: Project) -> list[AnswerInfo]:
    """Every answer, oldest first."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT * FROM answers ORDER BY event_id")).mappings().all()
    return [_info(r) for r in rows]


def view_answer(project: Project, answer_id: str) -> AnswerView:
    """One answer with each sentence's full paragraph, the ratings and the computed counts.
    Read-only. A paragraph that cannot be read from the stored conversion is empty."""
    import re

    if re.fullmatch(ANSWER_ID_RE, answer_id) is None:
        raise _issue("answer_id", f"{answer_id}: not an answer id")
    project.index.sync()
    with project.index.connect() as conn:
        row = (
            conn.execute(text("SELECT * FROM answers WHERE answer_id = :a"), {"a": answer_id})
            .mappings()
            .first()
        )
        if row is None:
            raise _issue("answer_id", f"{answer_id}: no such answer")
        sentences = (
            conn.execute(
                text("SELECT * FROM answer_sentences WHERE answer_id = :a ORDER BY idx"),
                {"a": answer_id},
            )
            .mappings()
            .all()
        )
        ratings = {
            int(r["sentence"]): r
            for r in conn.execute(
                text("SELECT * FROM answer_ratings WHERE answer_id = :a"), {"a": answer_id}
            )
            .mappings()
            .all()
        }
    manifests: dict[str, Any] = {}
    views: list[SentenceView] = []
    for s in sentences:
        cid = str(s["conversion_id"])
        if cid not in manifests:
            try:
                manifests[cid] = conversion_manifest(project, cid)
            except FactoryValidationError:
                manifests[cid] = None
        anchor = None if manifests[cid] is None else manifests[cid].get(s["anchor"])
        rated = ratings.get(int(s["idx"]))
        views.append(
            SentenceView(
                index=int(s["idx"]),
                text=s["text"],
                work_id=s["work_id"],
                anchor=s["anchor"],
                quote=s["quote"],
                paragraph="" if anchor is None else str(anchor.text),
                conversion_id=cid,
                markdown_hash=s["markdown_hash"],
                rating=None if rated is None else rated["rating"],
                rating_note=None if rated is None else rated["note"],
            )
        )
    whole = ratings.get(WHOLE)
    counts = AnswerCounts(
        sentences=len(views),
        works=len({v.work_id for v in views}),
        ratings={r: sum(1 for v in views if v.rating == r) for r in get_args(AnswerRating)},
        unrated=sum(1 for v in views if v.rating is None),
    )
    return AnswerView(
        info=_info(row),
        sentences=tuple(views),
        unanswered=row["unanswered"],
        rating=None if whole is None else whole["rating"],
        rating_note=None if whole is None else whole["note"],
        counts=counts,
        selection=_loads(row["selection"]),
    )


def _loads(raw: str) -> dict[str, Any]:
    import json

    value = json.loads(raw)
    assert isinstance(value, dict)
    return value

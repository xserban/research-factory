"""Projection of the goal and of each recorded question version.

`goals` keeps every stated goal in event order. `questions` keeps every `question.recorded` row;
the current question is the row with the greatest `event_id`, so a rebuild reproduces it exactly.
Handlers are total: an event whose row already exists is ignored (first write wins).
"""

from dataclasses import dataclass

from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from factory.canonical import canonical_json
from factory.clock import format_ts
from factory.events.envelope import Event
from factory.index.projection import Handler
from factory.model.question import GoalStated, QuestionRecorded


@dataclass(frozen=True)
class QuestionTables:
    goals: Table
    questions: Table


def question_tables(metadata: MetaData) -> QuestionTables:
    goals = Table(
        "goals",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("text", String, nullable=False),
        Column("at", String, nullable=False),
        Column("actor_id", String, nullable=False),
    )
    questions = Table(
        "questions",
        metadata,
        Column("event_id", String, primary_key=True),
        Column("question_id", String, nullable=False),
        Column("supersedes", String),
        Column("reason", String),
        Column("spec", String, nullable=False),
        Column("at", String, nullable=False),
    )
    return QuestionTables(goals, questions)


def question_handlers(t: QuestionTables) -> dict[str, Handler]:
    return {
        "question.goal_stated": _goal_stated(t),
        "question.recorded": _question_recorded(t),
    }


def _goal_stated(t: QuestionTables) -> Handler:
    def goal_stated(conn: Connection, event: Event) -> None:
        payload = GoalStated.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.goals)
            .values(
                event_id=event.id,
                text=payload.text,
                at=format_ts(event.ts),
                actor_id=event.actor.id,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return goal_stated


def _question_recorded(t: QuestionTables) -> Handler:
    def question_recorded(conn: Connection, event: Event) -> None:
        payload = QuestionRecorded.model_validate(event.payload)
        conn.execute(
            sqlite_insert(t.questions)
            .values(
                event_id=event.id,
                question_id=payload.question_id,
                supersedes=payload.supersedes,
                reason=payload.reason,
                spec=canonical_json(payload.spec.model_dump(mode="json")).decode(),
                at=format_ts(event.ts),
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )

    return question_recorded

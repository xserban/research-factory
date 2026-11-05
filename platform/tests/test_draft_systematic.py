"""Verification and release in a `systematic` project (slice 7b, plan W-B).

The rigor mode is fixed when a project is created, and a systematic project's screening needs more
than the writing world has, so these drafts rest on computed figures (`stat` supports) of a fresh
project; `project` is overridden here.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.model.drafts import DraftKind, SentenceVerified, SupportSpan, Verdict
from factory.services.context import Project
from factory.services.draft_verify import verify_next, verify_record
from factory.services.drafts import create_draft, write_sentences
from factory.services.project import init_project
from tests.draft_b_helpers import SYNTH, WRITER_MODEL, sent, verdict_on, verifier, writer

SESSION = "01JZ9Q3K5M7N8P0R2S4T6V8W0X"
ULID = "01JZ9Q3K5M7N8P0R2S4T6V8W"


@pytest.fixture
def project(settings: Settings, clock: FixedClock) -> Project:
    return init_project(settings, "demo", "systematic", session=SESSION, clock=clock)


@dataclass
class SysDraft:
    draft: str
    sentences: list[str]


def stat_draft(project: Project, n: int = 2) -> SysDraft:
    draft = create_draft(project, title="Notes", kind=DraftKind.OTHER, actor=project.human_actor())
    written = write_sentences(
        project,
        draft,
        [
            sent(
                "sec_01",
                SYNTH,
                f"No idea is confirmed in part {'abcdefg'[i]}",
                "stat:ideas-confirmed",
            )
            for i in range(n)
        ],
        actor=writer(),
    )
    assert not written.rejected
    return SysDraft(draft, written.written)


@pytest.fixture
def sd(project: Project) -> SysDraft:
    return stat_draft(project)


def test_systematic_same_model_refused(project: Project, sd: SysDraft) -> None:
    same = verifier(model=WRITER_MODEL)
    with pytest.raises(FactoryValidationError) as caught:
        verify_next(project, sd.draft, actor=same)
    assert caught.value.issues[0].field == "model"
    unit = verify_next(project, sd.draft, actor=verifier())
    assert unit is not None
    changed = verifier().model_copy(update={"model": WRITER_MODEL})
    with pytest.raises(FactoryValidationError) as recorded:
        verify_record(project, unit.task_id, verdict_on(unit), actor=changed)
    assert recorded.value.issues[0].field == "model"


def test_systematic_serves_another_writers_sentence_to_that_model(
    project: Project, sd: SysDraft
) -> None:
    """A verifier of one writer's model is passed over that writer's sentences only."""
    other = writer("01JZ9Q3K5M7N8P0R2S4T6V8W44", model="claude-haiku-5-5")
    done = write_sentences(
        project,
        sd.draft,
        [sent("sec_01", SYNTH, "No idea is confirmed here", "stat:ideas-confirmed")],
        actor=other,
    )
    unit = verify_next(project, sd.draft, actor=verifier(model=WRITER_MODEL))
    assert unit is not None and unit.sentence_id == done.written[0]


def test_forged_verdict_of_the_writers_model_is_inert(project: Project, sd: SysDraft) -> None:
    unit = verify_next(project, sd.draft, actor=verifier())
    assert unit is not None
    blob = project.blobs.put_json(unit.model_dump(mode="json", exclude={"task_id"}))
    spans = [SupportSpan(ref=unit.supports[0].ref, substring=unit.supports[0].spans[0])]

    def forged(model: str, n: int) -> int:
        payload = SentenceVerified(
            verdict_id=f"svd_{ULID}{n:02d}",
            sentence_id=unit.sentence_id,
            verdict=Verdict.SUPPORTED,
            support_spans=spans,
        )
        project.record(
            [project.events.make("draft.verified", payload, verifier(model=model), input_blob=blob)]
        )
        project.index.sync()
        with project.index.connect() as conn:
            return int(conn.execute(text("SELECT COUNT(*) FROM sentence_verdicts")).scalar_one())

    assert forged(WRITER_MODEL, 1) == 0
    assert forged("claude-opus-5-5", 2) == 1

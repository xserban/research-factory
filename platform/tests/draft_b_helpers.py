"""Writers, verifiers and a small draft for the tests of plan W-B (slice 7b).

`Written` is a draft over the W-A world with two claims and a structural sentence in the first
idea section, and `verified` records one verdict through the real services.
"""

# ruff: noqa: F401, F811

from __future__ import annotations

from dataclasses import dataclass

import pytest

from factory.events.envelope import Actor
from factory.model.drafts import DraftKind, SentenceClass, SupportSpan, Verdict
from factory.services.context import Project
from factory.services.draft_verify import VerdictInput, VerifyUnit, verify_next, verify_record
from factory.services.drafts import SentenceInput, create_draft, get_draft, write_sentences
from tests.contribution_helpers import ctr_a, ctr_b, ext_a, screened
from tests.views_b_helpers import ext_b
from tests.writing_helpers import WWorld, ww

W1 = "01JZ9Q3K5M7N8P0R2S4T6V8W11"
V1 = "01JZ9Q3K5M7N8P0R2S4T6V8W21"
V2 = "01JZ9Q3K5M7N8P0R2S4T6V8W22"
CLAIM, SYNTH, STRUCT = SentenceClass.CLAIM, SentenceClass.SYNTHESIS, SentenceClass.STRUCTURAL
INTERP = SentenceClass.INTERPRETIVE
LOREM = "Lorem is described in the method section"
IPSUM = "Ipsum is described in the second section"
QUOTE = "Lorem ipsum dolor sit amet."
WRITER_MODEL = "claude-sonnet-5-5"
VERIFIER_MODEL = "claude-opus-5-5"


def writer(session: str = W1, model: str = WRITER_MODEL) -> Actor:
    return Actor(
        kind="agent",
        id="writer",
        user="obd",
        session=session,
        model=model,
        skill="rf-write@1a2b3c4d",
    )


def verifier(session: str = V1, model: str = VERIFIER_MODEL) -> Actor:
    return Actor(
        kind="agent",
        id="verifier",
        user="obd",
        session=session,
        model=model,
        skill="rf-verify@1a2b3c4d",
    )


def sent(
    section: str, cls: SentenceClass, body: str, *supports: str, **kw: object
) -> SentenceInput:
    return SentenceInput(section_id=section, cls=cls, text=body, supports=list(supports), **kw)  # type: ignore[arg-type]


def section_of(project: Project, draft: str, ref_prefix: str = "idea:") -> str:
    row = get_draft(project, draft)
    assert row is not None
    return next(
        s.section_id for s in row.sections if (s.outline_section or "").startswith(ref_prefix)
    )


@dataclass
class Written:
    draft: str
    section: str
    first: str
    second: str
    structural: str


def write_draft(project: Project, ww: WWorld, actor: Actor | None = None) -> Written:
    me = project.human_actor()
    draft = create_draft(project, title="Related work", kind=DraftKind.RELATED_WORK, actor=me)
    section = section_of(project, draft)
    result = write_sentences(
        project,
        draft,
        [
            sent(section, CLAIM, LOREM, ww.claim(0)),
            sent(section, STRUCT, "The next paragraph states the scope"),
            sent(section, CLAIM, IPSUM, ww.claim(1)),
        ],
        actor=actor or writer(),
    )
    assert not result.rejected
    first, structural, second = result.written
    return Written(draft, section, first, second, structural)


@pytest.fixture
def wd(project: Project, ww: WWorld) -> Written:
    return write_draft(project, ww)


def verdict_on(unit: VerifyUnit, verdict: Verdict = Verdict.SUPPORTED) -> VerdictInput:
    """A verdict with substrings that hold for `unit`."""
    span = None if verdict is Verdict.SUPPORTED else unit.text
    support = unit.supports[0]
    spans = (
        []
        if verdict is Verdict.UNSUPPORTED
        else [SupportSpan(ref=support.ref, substring=support.spans[0])]
    )
    return VerdictInput(verdict=verdict, sentence_span=span, support_spans=spans)


def verify_one(
    project: Project,
    draft: str,
    verdict: Verdict = Verdict.SUPPORTED,
    actor: Actor | None = None,
) -> str:
    """Serve the next unit to `actor` and record `verdict`; returns the sentence verified."""
    who = actor or verifier()
    unit = verify_next(project, draft, actor=who)
    assert unit is not None
    verify_record(project, unit.task_id, verdict_on(unit, verdict), actor=who)
    return unit.sentence_id


def verify_all(project: Project, draft: str, verdict: Verdict = Verdict.SUPPORTED) -> list[str]:
    done: list[str] = []
    who = verifier()
    while (unit := verify_next(project, draft, actor=who)) is not None:
        verify_record(project, unit.task_id, verdict_on(unit, verdict), actor=who)
        done.append(unit.sentence_id)
    return done

"""Answers of the papers chat in Ask mode (plan spar-night N2).

Declaration only (slice M, decision 55); behaviour stays in `services/answers.py`. A proposal
module: an agent session records a question, the selection it was asked over and sentences, each
with a verified quote; the researcher rates the answer or a sentence. An answer is a note, never
evidence: it enters no count, table or result of another module."""

from factory.modules.contract import ArtifactKind, EventFamily, ModuleKind, ModuleSpec
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="answers",
    kind=ModuleKind.PROPOSAL,
    inputs=(ArtifactKind.RECORD,),
    outputs=(ArtifactKind.REPORT,),
    events=EventFamily(
        types=("chat.answer_recorded", "chat.answer_rated"),
        tables=("answers", "answer_sentences", "answer_ratings"),
    ),
)

MODULE = RuleModule(SPEC)

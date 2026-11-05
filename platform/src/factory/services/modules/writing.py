"""Writing from verified material: drafts, sentences, supports and write-time checks (slice 7b,
plan W-A).

Declaration only (slice M, decision 55); behaviour stays in the services. Drafting is a proposal an
agent or a human makes sentence by sentence; its quality regime (an independent verifier pass) and
its release gate belong to plan W-B and are declared there."""

from factory.modules.contract import EventFamily, ModuleKind, ModuleSpec
from factory.services.modules.base import RuleModule
from factory.services.modules.task_kinds import default_task_kinds

SPEC = ModuleSpec(
    name="writing",
    kind=ModuleKind.PROPOSAL,
    events=EventFamily(
        types=(
            "draft.created",
            "draft.outline_repinned",
            "draft.reordered",
            "draft.sentence_recorded",
            "draft.sentence_withdrawn",
            "draft.verified",
        ),
        tables=(
            "draft_sections",
            "draft_sentences",
            "drafts",
            "sentence_flags",
            "sentence_stats",
            "sentence_supports",
            "sentence_verdicts",
        ),
    ),
    task_kinds=default_task_kinds().kinds_of("writing"),
)

MODULE = RuleModule(SPEC)

"""Chat requests for a headless spar or ask (plan spar-night N3).

Declaration only (slice M, decision 55); behaviour stays in `services/chat_requests.py`. A proposal
module: the researcher orders a spar or an ask, a headless run takes the order and answers it with
a sheet or an answer. A request orders work and enters no count, table or result of another
module; its state is derived from the runs and the results that name it."""

from factory.modules.contract import ArtifactKind, EventFamily, ModuleKind, ModuleSpec
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="chat_requests",
    kind=ModuleKind.PROPOSAL,
    inputs=(ArtifactKind.RECORD,),
    outputs=(ArtifactKind.RECORD,),
    events=EventFamily(
        types=("chat.requested", "chat.request_taken"),
        tables=("chat_requests",),
    ),
)

MODULE = RuleModule(SPEC)

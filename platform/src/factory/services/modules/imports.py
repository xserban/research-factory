"""Import of bibliographic libraries: records, resolution, attachments and coverage.

Declaration only (slice M, decision 55); behaviour stays in the services."""

from factory.modules.contract import (
    ArtifactKind,
    CheckRule,
    EventFamily,
    GateKind,
    GateSpec,
    ModuleKind,
    ModuleSpec,
    PolicyKind,
)
from factory.services.modules.base import RuleModule

SPEC = ModuleSpec(
    name="imports",
    kind=ModuleKind.RETRIEVAL,
    outputs=(ArtifactKind.WORK,),
    events=EventFamily(
        types=(
            "import.admission_planned",
            "import.attachment_linked",
            "import.recorded",
            "import.resolution_decided",
            "import.resolved",
            "import.split_drawn",
        ),
        tables=(
            "import_admission_queries",
            "import_attachments",
            "import_decisions",
            "import_records",
            "imports",
        ),
    ),
    protocol_sections=("library_sources",),
    gates=(
        GateSpec(
            "import.resolution_confirm",
            GateKind.DECISION,
            ("import.resolution_decided",),
            PolicyKind.AGENT_AUDIT,
            ("slice 3d ruling 21",),
        ),
    ),
    checks=(
        CheckRule("import-unresolved", ("warning", "warning", "warning")),
        CheckRule("import-unconfirmed", ("warning", "warning", "warning")),
        CheckRule("import-attachment-missing", ("warning", "warning", "warning")),
        CheckRule("import-identity-unchecked", ("warning", "warning", "warning")),
        CheckRule("import-undeclared", ("warning", "error", "error")),
        CheckRule("import-coverage-optimistic", ("warning", "warning", "warning")),
    ),
)

MODULE = RuleModule(SPEC)

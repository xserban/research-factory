"""The `ai-research-system` extraction pack, version 1 (pure data; slice 8, Phase C).

Unit of extraction: one row per (system, stage). A system is an AI research system as its paper
names it; a stage is one step of its research process as the paper names it. A paper that
describes several systems yields several rows per system.

Evidence grades (``evidence_grade``), from strongest to weakest:
    A  peer-reviewed and accepted by the venue;
    B  evaluated by independent experts, or replicated by others;
    C  a controlled comparison run by the authors;
    D  automated evaluation only;
    E  a demonstration (examples, case studies, no measured comparison);
    F  a claim only, without supporting evidence in the paper.

``self_reported`` is ``yes`` when the result comes from the system's own authors and ``no``
otherwise. ``human_role`` records the human's part at the stage: ``none``, ``validates``
(checks outputs), ``directs`` (sets goals or steers the process) or ``contributes`` (adds
content, as stated in ``human_adds``).

Invariants: the pack is frozen; ``system`` and ``stage`` are the row key; every enumerated field
is a TEXT field whose ``allowed`` tuple is the closed value set; free text is quote-checked
against the paper; no conditionals are declared (the pack does not judge). Any change to this
content is a new version. Packs never judge; the grade is a reading of the paper, recorded by
the agent with its quote.
"""

from __future__ import annotations

from factory.packs.ml_benchmark import CITATION_PATTERNS
from factory.packs.model import Check, FieldDef, FieldKind, Pack, UnitFamily

AI_RESEARCH_SYSTEM_PACK = "ai-research-system"
PROCESS_SHAPES = ("linear", "iterative-loop", "tree-search", "parallel-branches", "other")
EVIDENCE_GRADES = ("A", "B", "C", "D", "E", "F")
HUMAN_ROLES = ("none", "validates", "directs", "contributes")
RELEASED_VALUES = ("code-and-system", "code-only", "none", "unclear")
SELF_REPORTED_VALUES = ("yes", "no")

_T = FieldKind.TEXT
_NONE_U = UnitFamily.NONE
_TQ, _NOCHK = Check.TEXT_IN_QUOTE, Check.NONE


def _text(name: str, group: str) -> FieldDef:
    """A free-text field quoted from the paper."""
    return FieldDef(name, group, _T, _NONE_U, _TQ)


def _enum(name: str, group: str, allowed: tuple[str, ...]) -> FieldDef:
    """An enumerated field: a TEXT kind whose value must be one of ``allowed``."""
    return FieldDef(name, group, _T, _NONE_U, _NOCHK, allowed=allowed)


AI_RESEARCH_SYSTEM_V1 = Pack(
    name=AI_RESEARCH_SYSTEM_PACK,
    version=1,
    fields=(
        _text("system", "identity"),
        _text("stage", "identity"),
        _enum("process_shape", "shape", PROCESS_SHAPES),
        _text("automated_span", "shape"),
        _text("stage_inputs", "shape"),
        _text("stage_outputs", "shape"),
        _text("approach", "method"),
        _text("compared_to", "evaluation"),
        _text("metric", "evaluation"),
        _text("result", "evaluation"),
        _enum("evidence_grade", "evaluation", EVIDENCE_GRADES),
        _text("ablation", "evaluation"),
        _enum("human_role", "human", HUMAN_ROLES),
        _text("human_adds", "human"),
        _text("human_vs_automated", "human"),
        _text("components_models", "method"),
        _enum("released", "release", RELEASED_VALUES),
        _text("idea_assessment_method", "ideas"),
        _text("assessment_reliability", "ideas"),
        _enum("self_reported", "evaluation", SELF_REPORTED_VALUES),
    ),
    required=("system", "stage", "evidence_grade", "self_reported"),
    default_comparability_keys=(),
    citation_patterns=CITATION_PATTERNS,
    row_key_fields=("system", "stage"),
    row_anchor_fields=("system", "stage"),
    compared_fields=(
        "system",
        "stage",
        "evidence_grade",
        "human_role",
        "released",
        "self_reported",
    ),
)

__all__ = [
    "AI_RESEARCH_SYSTEM_PACK",
    "AI_RESEARCH_SYSTEM_V1",
    "EVIDENCE_GRADES",
    "HUMAN_ROLES",
    "PROCESS_SHAPES",
    "RELEASED_VALUES",
    "SELF_REPORTED_VALUES",
]

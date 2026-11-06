"""Per-paper appraisal: the instrument in force, computed platform items, agent passes and human
judgements (IDEA-21, R-41; plan EQ). This module is the business logic; `mcp/` and `cli/` only
call it.

Invariants:
- Optional: a project with no `appraisal_instrument` gets empty results and nothing is written.
- Platform items are computed on read from the conversion and never stored; a rule reports
  presence only, so an absent pattern reads `not-found`, never `no`.
- No total, weight, grade or sort by quality is computed anywhere (decision 42).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from factory.document.anchors import Anchor, AnchorKind, Manifest
from factory.model.appraisal import (
    AppraisalInstrument,
    AppraisalItem,
    ItemKind,
)
from factory.model.base import StrictModel
from factory.model.protocol import section_digest
from factory.model.work import WorkType
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.protocol import current_protocol

__all__ = [
    "PLATFORM_RULES",
    "InstrumentInForce",
    "PlatformAnswer",
    "instrument_in_force",
    "item_applies",
    "platform_answers",
]

_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org|huggingface\.co|"
    r"codeberg\.org|zenodo\.org|sourceforge\.net|figshare\.com)/\S+",
    re.IGNORECASE,
)
_CODE_WORDS_RE = re.compile(
    r"\b(?:our|the|source)\s+code\s+(?:is|are|will be)\s+(?:publicly\s+)?available\b",
    re.IGNORECASE,
)
_BENCHMARKS = (
    "ImageNet|CIFAR-?10+|MNIST|COCO|GLUE|SuperGLUE|SQuAD|WikiText|Penn Treebank|LibriSpeech|"
    "Cityscapes|Pascal VOC|OpenWebText|The Pile|C4|MMLU|GSM8K|HumanEval|WMT"
)
_DATASET_RE = re.compile(
    rf"\b(?:{_BENCHMARKS})\b"
    r"|\b[A-Z][\w-]+(?:\s[A-Z][\w-]+){0,3}\s+(?:dataset|benchmark|corpus)\b",
)
_NUMBER_WORDS = "one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|fifty"
_SEEDS_RE = re.compile(
    rf"\b(?:\d+|{_NUMBER_WORDS})\s+(?:independent\s+|random\s+)?(?:seeds|runs|trials|repetitions)\b"
    r"|\brandom\s+seeds?\b|\bseeds?\s*(?:=|:)?\s*\d+\b",
    re.IGNORECASE,
)
_HARDWARE_RE = re.compile(
    r"\b(?:GPUs?|TPUs?|A100|V100|H100|P100|T4|RTX\s?\d+|Tesla|NVIDIA|Xeon|EPYC|CPU cores?)\b"
)


class PlatformAnswer(StrictModel):
    """The result of one computed rule for one work: where the pattern was found, or not."""

    item: str
    rule: str
    status: Literal["found", "not-found"]
    anchor: str | None = None
    conversion_id: str


def _first_match(manifest: Manifest, pattern: re.Pattern[str]) -> Anchor | None:
    for anchor in manifest.anchors:
        if anchor.kind is AnchorKind.CELL:
            continue
        if pattern.search(anchor.text):
            return anchor
    return None


def _code_url(manifest: Manifest) -> Anchor | None:
    return _first_match(manifest, _URL_RE) or _first_match(manifest, _CODE_WORDS_RE)


PLATFORM_RULES: Mapping[str, Callable[[Manifest], Anchor | None]] = {
    "code-url-present": _code_url,
    "dataset-named": lambda m: _first_match(m, _DATASET_RE),
    "seeds-reported": lambda m: _first_match(m, _SEEDS_RE),
    "hardware-reported": lambda m: _first_match(m, _HARDWARE_RE),
}
"""The fixed menu of computed rules (plan EQ ruling 1): each a deterministic pattern over the
conversion, returning the first anchor it matches or None. Keys are `PLATFORM_RULE_NAMES`."""


@dataclass(frozen=True)
class InstrumentInForce:
    instrument: AppraisalInstrument
    digest: str
    protocol_id: str


def instrument_in_force(project: Project) -> InstrumentInForce | None:
    """The instrument of the current protocol with its section digest, or None when the project
    declares none. Syncs the index."""
    protocol = current_protocol(project)
    if protocol is None or protocol.spec.appraisal_instrument is None:
        return None
    return InstrumentInForce(
        protocol.spec.appraisal_instrument,
        section_digest(protocol.spec, "appraisal_instrument"),
        protocol.protocol_id,
    )


def platform_answers(
    project: Project, work_id: str, conversion_id: str | None = None
) -> list[PlatformAnswer]:
    """The computed items of the declared instrument for one work, over the conversion given or
    the one `document_read` serves by default. Empty when no instrument is declared or the work
    has no conversion. Computed on every call and never stored."""
    from factory.services.document_read import default_conversion  # imports the pass gate

    found = instrument_in_force(project)
    if found is None:
        return []
    if conversion_id is None:
        ref = default_conversion(project, work_id)
        if ref is None:
            return []
        conversion_id = ref.conversion_id
    manifest = conversion_manifest(project, conversion_id)
    answers: list[PlatformAnswer] = []
    for item in found.instrument.of_kind(ItemKind.PLATFORM):
        if item.rule in PLATFORM_RULES and item_applies(project, work_id, item):
            answers.append(_computed(item, manifest, conversion_id))
    return answers


def item_applies(project: Project, work_id: str, item: AppraisalItem) -> bool:
    """Whether `item` is asked about this work: `all`, or by the work type's default of peer
    review (`WorkType.is_peer_reviewed_by_default`; a default, never a finding)."""
    if item.applies_to == "all":
        return True
    project.index.sync()
    with project.index.connect() as conn:
        row = conn.execute(
            text("SELECT data FROM works WHERE work_id = :w"), {"w": work_id}
        ).first()
    if row is None:
        return True
    try:
        kind = WorkType(str(json.loads(str(row[0])).get("type", "other")))
    except ValueError:
        kind = WorkType.OTHER
    return kind.is_peer_reviewed_by_default == (item.applies_to == "peer-reviewed")


def _computed(item: AppraisalItem, manifest: Manifest, conversion_id: str) -> PlatformAnswer:
    assert item.rule is not None  # a platform item names its rule (model validator)
    rule = PLATFORM_RULES[item.rule]
    anchor = rule(manifest)
    return PlatformAnswer(
        item=item.id,
        rule=item.rule,
        status="found" if anchor is not None else "not-found",
        anchor=None if anchor is None else anchor.id,
        conversion_id=conversion_id,
    )

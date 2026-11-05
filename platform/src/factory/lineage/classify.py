"""The stated/inferred rule for relations (slice 3b ruling 11; requirement R-xx(e)).

Pure. A relation is `stated` only when its basis item cites a reference entry whose G1 link is
`resolved` to exactly the proposed target, and the target is a work. Every other relation is
`inferred`, with the first failing reason in this order: `no-basis`, `no-cited-entry`,
`link-unconfirmed`, `target-differs`. The agent supplies none of the facts: the service reads
them from the item and the G1 link.
"""

from __future__ import annotations

from dataclasses import dataclass

from factory.model.lineage import ProposalStatus, StatusReason
from factory.model.references import LinkState

CLASSIFIER_VERSION = "1"
UNCITED_BASE = "uncited-base"


@dataclass(frozen=True)
class BasisFacts:
    item_kind: str
    cited_entry: int | None
    reference_extraction_id: str | None


@dataclass(frozen=True)
class LinkFacts:
    """The G1 link of the cited entry in the extraction the item cites."""

    state: LinkState
    work_id: str | None


@dataclass(frozen=True)
class Classification:
    status: ProposalStatus
    reason: StatusReason | None
    resolved_target: str | None
    flags: tuple[str, ...]


def classify(
    basis: BasisFacts | None,
    link: LinkFacts | None,
    target: str,
    *,
    target_is_idea: bool,
    target_cited: bool,
) -> Classification:
    """Classify a proposed relation. `link` is None when the basis cites no entry or its work has
    no usable G1 extraction. `target_cited`: some entry of the source work's current extraction
    resolves to `target`; when it does not and the target is a work, the flag `uncited-base` is set.
    """
    flags = (UNCITED_BASE,) if not target_is_idea and not target_cited else ()
    resolved = link.work_id if link is not None and link.state is LinkState.RESOLVED else None

    def inferred(reason: StatusReason) -> Classification:
        return Classification("inferred", reason, resolved, flags)

    if basis is None:
        return inferred(StatusReason.NO_BASIS)
    if basis.cited_entry is None or link is None:
        return inferred(StatusReason.NO_CITED_ENTRY)
    if link.state is not LinkState.RESOLVED:
        return inferred(StatusReason.LINK_UNCONFIRMED)
    if target_is_idea or resolved != target:
        return inferred(StatusReason.TARGET_DIFFERS)
    return Classification("stated", None, resolved, flags)

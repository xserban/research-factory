"""Where a full-text decision's evidence lives, for the human who reviews it.

A human labelling a calibration work, reviewing a disagreement or auditing a sample needs the
document and the pinned conversion to read, and the anchors and quotes the passes cited. This
module looks those up so that `cli/` and `mcp/` only format them.

Invariants:
- At title/abstract everything here is empty: no document, no conversion, no decisions.
- The conversion is the one the live full-text decisions pin (pass A's first); with no decision
  yet it is the default conversion that a new batch would pin. Read-only; never writes.
"""

from factory.model.base import StrictModel
from factory.model.protocol import ScreeningStage
from factory.services.agreement import DecisionView
from factory.services.context import Project
from factory.services.conversions import conversion_document
from factory.services.document_read import default_conversion
from factory.services.screening import live_decisions


class WorkEvidence(StrictModel):
    document_id: str | None
    conversion_id: str | None
    decisions: dict[str, DecisionView]
    """Live full-text decisions by pass label (`A`, `B`)."""


NO_EVIDENCE = WorkEvidence(document_id=None, conversion_id=None, decisions={})


def work_evidence(project: Project, work_id: str, stage: ScreeningStage) -> WorkEvidence:
    """The document, pinned conversion and live decisions of `work_id` at `stage`."""
    if stage is not ScreeningStage.FULL_TEXT:
        return NO_EVIDENCE
    project.index.sync()
    decisions = {
        d.pass_label.value: d for d in live_decisions(project, stage=stage) if d.work_id == work_id
    }
    pinned = next(
        (decisions[k].conversion_id for k in sorted(decisions) if decisions[k].conversion_id), None
    )
    document_id: str | None
    if pinned is not None:
        document_id = conversion_document(project, pinned)
    else:
        default = default_conversion(project, work_id)
        pinned, document_id = (
            (None, None)
            if default is None
            else (
                default.conversion_id,
                default.document_id,
            )
        )
    views = {
        label: DecisionView(
            verdict=d.verdict,
            criterion=None if d.criterion is None else d.criterion.rsplit(":", 1)[-1],
            quote=d.quote,
            rationale=d.rationale,
            anchor=d.anchor,
            conversion_id=d.conversion_id,
            document_id=document_id if d.conversion_id == pinned else None,
        )
        for label, d in decisions.items()
    }
    return WorkEvidence(document_id=document_id, conversion_id=pinned, decisions=views)

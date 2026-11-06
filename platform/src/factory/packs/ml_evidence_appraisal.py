"""The built-in appraisal instrument `ml-evidence` version 1 (plan EQ; reference M14).

Items follow the reporting checklist of a machine-learning venue. A platform item reports presence
of a pattern only; a span item asks an agent to find the passage; a judgement item is for a human.
Pure data: a project copies it into its protocol (`appraisal_instrument`) and may change it, which
is an amendment like any other. No item is weighted and none is summed (decision 42).
"""

from __future__ import annotations

from factory.model.appraisal import AppraisalInstrument, AppraisalItem, ItemKind

_P, _S, _J = ItemKind.PLATFORM, ItemKind.AGENT_SPAN, ItemKind.JUDGEMENT

ML_EVIDENCE_V1 = AppraisalInstrument(
    name="ml-evidence",
    version=1,
    items=(
        AppraisalItem(
            id="code-available",
            statement="Is a link to the code given?",
            kind=_P,
            rule="code-url-present",
        ),
        AppraisalItem(
            id="dataset-named",
            statement="Is each dataset used named?",
            kind=_P,
            rule="dataset-named",
        ),
        AppraisalItem(
            id="seeds-reported",
            statement="Is the number of random seeds or runs reported?",
            kind=_P,
            rule="seeds-reported",
        ),
        AppraisalItem(
            id="hardware-reported",
            statement="Is the hardware used reported?",
            kind=_P,
            rule="hardware-reported",
        ),
        AppraisalItem(
            id="hyperparameters-stated",
            statement="Are the hyperparameters stated, and how they were chosen?",
            kind=_S,
        ),
        AppraisalItem(
            id="splits-described",
            statement="Are the data splits described?",
            kind=_S,
        ),
        AppraisalItem(
            id="variance-reported",
            statement="Are error bars, confidence intervals or a spread over runs reported?",
            kind=_S,
        ),
        AppraisalItem(
            id="compute-reported",
            statement="Is the compute used (time or accelerator hours) reported?",
            kind=_S,
        ),
        AppraisalItem(
            id="limitations-discussed",
            statement="Does the paper discuss its own limitations?",
            kind=_S,
        ),
        AppraisalItem(
            id="baselines-fair",
            statement="Are the baselines tuned and trained with comparable effort?",
            kind=_J,
        ),
        AppraisalItem(
            id="claims-supported",
            statement="Do the experiments support the claims made?",
            kind=_J,
        ),
    ),
    dual_sample=None,
)

BUILT_IN_INSTRUMENTS: dict[tuple[str, int], AppraisalInstrument] = {
    (ML_EVIDENCE_V1.name, ML_EVIDENCE_V1.version): ML_EVIDENCE_V1
}
"""Instruments a project can copy into its protocol, by `(name, version)`. PROBAST and RoB 2 are
data to add when a biomedical project declares them (plan EQ)."""


def built_in_instrument(name: str, version: int) -> AppraisalInstrument | None:
    return BUILT_IN_INSTRUMENTS.get((name, version))

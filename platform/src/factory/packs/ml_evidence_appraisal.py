"""The built-in appraisal instruments, version 1 (plans EQ and SG; reference M14).

`ml-evidence` follows the reporting checklist of a machine-learning venue; `aacods` the checklist
for grey literature. A platform item reports presence
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

AACODS_V1 = AppraisalInstrument(
    name="aacods",
    version=1,
    items=(
        AppraisalItem(
            id="authority-author-named",
            statement="Is the author or issuing organisation named, with an affiliation or role?",
            kind=_S,
            applies_to="grey",
        ),
        AppraisalItem(
            id="authority-recognised",
            statement="Is the author or organisation recognised as an authority on the topic?",
            kind=_J,
            applies_to="grey",
        ),
        AppraisalItem(
            id="accuracy-sources-cited",
            statement="Does the document cite its sources or give a method for its claims?",
            kind=_S,
            applies_to="grey",
        ),
        AppraisalItem(
            id="accuracy-trustworthy",
            statement="Is the document free of evident errors and consistent with other sources?",
            kind=_J,
            applies_to="grey",
        ),
        AppraisalItem(
            id="coverage-scope-stated",
            statement="Does the document state its scope and what it leaves out?",
            kind=_S,
            applies_to="grey",
        ),
        AppraisalItem(
            id="objectivity-interests-declared",
            statement="Does the document declare funding, sponsorship or competing interests?",
            kind=_S,
            applies_to="grey",
        ),
        AppraisalItem(
            id="objectivity-balanced",
            statement="Is the document free of evident bias or an advocacy agenda?",
            kind=_J,
            applies_to="grey",
        ),
        AppraisalItem(
            id="date-stated",
            statement="Is a date of publication or last update stated?",
            kind=_S,
            applies_to="grey",
        ),
        AppraisalItem(
            id="significance-relevant",
            statement="Does the document bear on the question under review?",
            kind=_J,
            applies_to="grey",
        ),
    ),
    dual_sample=None,
)
"""The AACODS checklist for grey literature (authority, accuracy, coverage, objectivity, date,
significance), one or two items per domain. Every item applies to grey works only, so a project
that also appraises peer-reviewed works declares a second instrument or amends the first. The
statements are the platform's own wording."""

BUILT_IN_INSTRUMENTS: dict[tuple[str, int], AppraisalInstrument] = {
    (ML_EVIDENCE_V1.name, ML_EVIDENCE_V1.version): ML_EVIDENCE_V1,
    (AACODS_V1.name, AACODS_V1.version): AACODS_V1,
}
"""Instruments a project can copy into its protocol, by `(name, version)`. PROBAST and RoB 2 are
data to add when a biomedical project declares them (plan EQ)."""


def built_in_instrument(name: str, version: int) -> AppraisalInstrument | None:
    return BUILT_IN_INSTRUMENTS.get((name, version))

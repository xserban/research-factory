"""The per-tab help paragraphs of the old dashboard, kept verbatim (DB-3).

Each text is trusted HTML (`<b>` only) and is shown in the information panel of the view that
replaced the tab. Edits from the old wording: the Conversion text lost its last sentence, which
named the old hub's Conversion product. Extraction and Products have no matching v2 view and
are not ported.
"""

# ruff: noqa: E501
from __future__ import annotations

TAB_HELP: dict[str, str] = {
    "protocol": (
        "<b>The protocol</b> is the review\u2019s plan, recorded before screening: the question, the inclusion and exclusion criteria, the sources and queries, how screening and extraction are done, and which miners are used. Every later change is an <b>amendment</b> (with a reason and whether it changes the meaning) or a <b>deviation</b> (something done differently from the plan). Read this first: everything else is judged against it."
    ),
    "decisions": (
        "<b>Decisions</b> are the researcher\u2019s rulings: the options that were on the table, the choice, who decided and why. They are append-only; a ruling is replaced by a newer one, never edited. Open an entry to see its options and its consequences."
    ),
    "press": (
        "<b>PRESS</b> is a peer review of the search strategy (terms, databases, limits) before the search is run. Each finding gets a response, and the search counts as confirmed only after the review is closed."
    ),
    "probes": (
        "<b>Probes</b> are small trial searches that test the strategy before the real one: how many records a query returns, and whether known seed papers are found. They are not part of the review\u2019s results."
    ),
    "search": (
        "<b>The search</b>: each query, the source it ran on, the number of records the source reported and the number retrieved, any shortfall with its reason, and the duplicates removed afterwards. The PRISMA flow is computed from these counts."
    ),
    "screening": (
        "<b>Screening</b> decides which records stay in the review. Pass A screens every record; a second pass screens a sample, so the agreement between the two shows how stable the decisions are. Calibration and audits are checks by the researcher. Title/abstract screening comes first; full-text screening follows for the records promoted."
    ),
    "conversion": (
        "<b>Conversion</b> turns each downloaded PDF or HTML page into Markdown with a numbered anchor on every paragraph, so a quote can point to its place. <b>Recall</b> is the share of the original\u2019s words found in the Markdown (low: text may be lost); <b>precision</b> is the share of the Markdown\u2019s words found in the original (low: text added or scrambled). Both are noisy and only rank documents for a person to check."
    ),
    "miners": (
        "<b>Miners</b> read the included full texts and record typed, quoted values: each value is an enum, a number or a verbatim sentence, never free text. One model reads every work (pass A); another reads a sample (pass B) so agreement can be measured. Click a miner below to see what it records, how it reads, its fields and how to work with it."
    ),
    "cost": (
        "<b>Cost and time</b>: how many agent events each stage and model recorded, the budgets declared and the usage reported. These are recorded events, not dollars: the model sessions\u2019 own cost figures are not stored by the platform."
    ),
}

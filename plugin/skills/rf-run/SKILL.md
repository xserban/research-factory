---
name: rf-run
description: Use when a session starts on a project, or when it is unclear what comes next: states the order of stages, which session runs which pass, which steps are the researcher's, and how to read the next step from the tools.
stage: [cross]
---

# rf-run

The map of a whole run. It records nothing: it says where to look and which skill takes over.

## Find the next step

1. Call `project_status`. Read `stage`, `human`, `tasks`, `protocol` and `question`.
2. `human` lists what waits on the researcher, each item with its count and the exact command.
   Relay those commands. Do not try to do them: see "The researcher's acts".
3. Take the stage from the table and hand over to its skill.

| `stage` | What happens | Skill |
| --- | --- | --- |
| `scoping` | Question and protocol are not both recorded | `rf-develop`, then `rf-frame`, `rf-probe`, `rf-protocol` |
| `protocol` | The protocol is not ready, or PRESS is not confirmed | `rf-protocol` |
| `search` | No complete search run | `search_run`, then `dedup_run` |
| `ta-screening` | Works wait at title and abstract | `rf-screen` |
| `full-text` | Works wait for retrieval or a full-text outcome | `library_adoptable`, `library_adopt`, `fulltext_fetch`, `rf-screen` |
| `extraction` | Extraction units or disagreements are open | `rf-extract`, `rf-mine`, `rf-contributions` |
| `snowballing` | The stopping rule has not stopped the rounds | `rf-references`, `rf-search` |
| `reporting` | Nothing above is open | the reports below, then `rf-lineage`, `rf-write` |

At `full-text`, read `library_adoptable` for a work before fetching it: when another project of the
lab already holds its document, adopt that copy with `library_adopt` instead of fetching again.

`stage` is null in a session that has joined a pass: that session follows its own skill and its
own batches only.

## Decisions come first

Before the scoping skills record anything, the scientist decides each level with `rf-develop`:
goal, questions, plan, seeds, probe, protocol, one at a time, top-down. `decision_list` with
`open_only` shows the suggestion sets awaiting the scientist. Selecting is the scientist's act
(`decision_select`, or `factory decide select` in the terminal); never record one for them. In
`pilot` and `systematic`, `question_record`, `seed_add`, `probe_run` and `protocol_record` cite
a decision with an accepted selection (`decision_ids`). `develop_render` renders a level as a
document.

## Read what exists

A fresh session needs no ids from anyone.

- Decisions: `decision_list`, `decision_view`, `develop_render`.
- Plan: `protocol_view` (the whole spec, to read and to pass back to `protocol_amend`),
  `question_view`.
- Corpus: `fulltext_status`, `document_status`, `extraction_status`, `contribution_status`,
  `dedup_merges`.
- Layers: `relation_list`, `idea_list`, `concept_list`, `card_list`, `graph_status`, `graph_query`,
  `region_status`, `term_list`.
- Hypotheses and writing: `lead_list`, `hypothesis_list`, `experiment_list`, `draft_list`, then the
  `*_view` or `draft_status` tool for one item.
- Reports and views: `report_prisma`, `report_search`, `report_methods`, `report_evidence`,
  `report_discovery`, `view_onion`, `view_coverage`, `view_timeline`, `view_horizon`, `trace`,
  `check`.

A list that answers `not available yet` is waiting for a screening pass to open. That is no fault
and says nothing about what the project holds. Report any `notice` as it is.

## One session, one pass

- One session holds one pass. A session that has joined a pass cannot use the read tools above,
  and it receives what it needs in its batches.
- Pass A and pass B of screening, of extraction and of a miner each run in their own Claude Code
  session. Subagents share their parent's session, so they cannot serve as the other pass.
- A hypothesis's critic and a draft's verifier are sessions of their own as well. A verifier reads
  its unit only: it does not read, repin, reorder or withdraw in the draft it verifies.
- If a session cannot finish a task it holds, it calls `task_release` rather than leaving the lease
  to run out.

## The researcher's acts

No tool performs these. Print the command `project_status` gives and wait.

- Imports: `factory import ...`, including resolving, confirming, admitting and attaching.
- Conversion of documents: `factory document convert`.
- Selections on suggested decisions (`decision_select` asks them; `factory decide select`).
- Gate decisions, calibration and audit labels, resolving disagreements, unless the protocol's
  policy for the gate lets an agent act.
- Registering or concluding what the protocol keeps for the researcher.

## Never

- Never guess a stage from memory of an earlier session. Read `project_status`.
- Never ask for, name or look for held-out seeds. Withheld identifiers stay withheld.
- Never act on a `check` finding to clear it: report it, with its code and severity.

## Done when

The stage is `reporting`, `human` is empty, and `check` has been reported to the researcher.

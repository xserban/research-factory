# MCP and CLI Surface Implementation Plan (backlog triage, plan MS)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Proposed 2026-11-05 (backlog triage, `2026-11-05-backlog-triage.md`).** Items marked [confirm] await the researcher.

> **Dependencies.** Base `d66387f` or later. Task 4's `experiment_list` and Task 7's experiment commands rebase cleanly over XP-B. Every task adds to the tail of `mcp/server.py` and to the ordered list in `tests/test_mcp_server.py`, so this plan owns those two files among the triage plans; PI adds no tool, and EQ, SG and SV add theirs after MS merges. Paths are relative to `platform/` unless they start with `docs/` or `plugin/`.

**Goal:** Every service a pilot needs can be reached, and an agent starting a fresh session can find out what exists without being told ids by hand.

**Why.** Compared on the base (`mcp/server.py` has 112 tools; XP-B adds `benchmark_ledger_view` and `registry_query`):

1. **Neither MCP nor CLI shows the current protocol or question.** `factory status` prints ids. `protocol_amend` takes the whole spec, so a fresh session must retype a spec it cannot read.
2. `factory document status`, `report search` and most `list` commands have no MCP counterpart. An agent cannot list leads, hypotheses, cards, experiments, drafts, relations, ideas or concepts, nor see which documents converted, though `hypothesis_view`, `card_view` and the like need an id.
3. `drafts.repin_outline` and `drafts.reorder` have neither tool nor command (iterate line 121).
4. `dedup.revert_merge` has no surface at all, though `dedup_run` tells agents that merges are reversible.
5. `tasks.release_task` has no surface, so a session that cannot finish a task waits for the lease.
6. `amend_experiment` and `evaluate_baselines` have no CLI (iterate lines 104, 106). `region_links` has none (line 74).
7. `project_status` has no stage and its human queue stops at six gates, so nothing tells a researcher that imports wait for confirmation or that documents wait for conversion.
8. No installed skill covers the miner tools (iterate line 58), and 44 of the 112 tools are named by no skill: full text, reports, views, the graph reads.

**Architecture:** Thin tools and commands over existing services, plus one small change to `human_queue`. Each reading tool applies the guard of its neighbours (`_refuse_pass_session`, `_withheld`) and calls the agent variant of a service where one exists. Task 5 is the one task that changes a fold.

**Spec and decision basis:** `docs/specs/00-system.md` (MCP conventions); slices 1, 3b, 6, 7a, 7b; decisions 26, 37, 43, 69 (the portfolio has no MCP tool: the stage goes on `project_status`, which is per project, and no cross-project tool is added), 70, 95, 96. Iterate lines 53, 58, 74, 104, 106, 109, 121.

**Projection:** Task 5 bumps `PROJECTION_VERSION` by one (it changes the `draft.outline_repinned` fold). No other task does.

## Rulings made in this plan

1. **Human acts stay CLI [confirm, triage ruling R6].** No tool performs an import, a conversion, a gate decision or a resolution. Decisions 46 item 7 and 60 and plan B1 ruling 6 keep them on the CLI. The human queue names the exact command instead (Task 8).
2. **Reads are refused to pass sessions [confirm].** `protocol_view`, `question_view` and every list tool here are refused to a session that has joined a pass, as `report_methods` and `trace` are (decision 43). A pass session receives what it needs in its batch, and criteria order and framing are part of decision 37's engineered independence.
3. **`protocol_view` returns the spec only**, with its id, status, PRESS state and amendment list: never seed data. Reviewer and label fields follow `_without_rates`.
4. **Repin and reorder [confirm].** A verifier session is refused both, and `withdraw` too, as `write_sentences` already refuses it: today only `_require_writer` guards them. Without this a session holding verdicts could reshape the draft it verifies (R-51).
5. **An agent may call `merge_revert`** with a reason: the service already keeps an agent's input for audit. A revert is refused to pass sessions.

## Global Constraints

- `mcp/` and `cli/` only parse, call a service and format. If a list needs logic, it goes in `services/`.
- A view composing sources calls each source's agent variant. The researcher's CLI output stays complete.
- Views are empty with a notice on a fresh project.
- No tool returns a held-out seed record, seed id, stated identifier, held-out rate or an import's held-out part. A corpus work is never filtered or marked (decision 81 as proposed; see the handoff's held-out section).

## Review Focus

1. Each new read has its pass-session refusal, proved by removing the guard.
2. `lead_list` and `hypothesis_list` carry nothing the agent trace withholds. On XP-B, `test_agent_trace_labels_omit_lead_text_and_rationale` sets that bar: check the view's fields against it.
3. Tool-list pin, `OMITTED_WHEN_EMPTY` and the `TOOL_PERMISSIONS` rows of deploy-B are all extended when these land.

## File Structure

Modify `mcp/server.py`, `tests/test_mcp_server.py`, `cli/main.py`, `cli/render.py`, `services/human_queue.py`, `services/project.py`, `services/drafts.py`, `model/drafts.py`, `index/drafts.py`, `index/default.py`, `services/portfolio.py` (export the stage rule). Create `plugin/skills/rf-run/SKILL.md`, `plugin/skills/rf-mine/SKILL.md`.

### Task 1: Read the protocol and the question

*Tier: standard.*

**Interfaces:**
- MCP: `protocol_view(project) -> {protocol_id, status, press, spec, amendments}`; `question_view(project) -> {question_id, spec, raw_goal}`.
- CLI: `factory protocol show [--json]`, `factory question show [--json]`. A new `question_app`.
- Consumes `current_protocol`, `current_question`. Add a read in `services/protocol.py` for the amendment list if none exists.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(mcp): read the current protocol and question`.

**Tests (later):** spec round-trips into `protocol_amend`; refused to a pass session; empty notice with no protocol; pin list.

### Task 2: Document status and the search report

*Tier: light.*

**Interfaces:** MCP `document_status(project)` over `document_convert.document_status`, with `_withheld(..., include_work_ids=False)` as `fulltext_status`; MCP `report_search(project)` over `prisma.search_report`, with the same treatment as `report_prisma`.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(mcp): document status and search report tools`.

**Tests (later):** refusal; a failed conversion listed with its reason and no text; withheld identifiers scrubbed.

### Task 3: List tools, literature layer

*Tier: standard.*

**Interfaces:** `extraction_status`, `contribution_status`, `relation_list(work_id?, status?, cursor, limit)` over `list_relations`, `idea_list(status?, cursor, limit)` over `list_ideas`, `concept_list(state?, cursor, limit)` over `list_concepts`. Each pages. Follow the corresponding CLI command's service call, then the agent variant where one exists. `layer` labels stay on concepts (decision 83).

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(mcp): list relations, ideas, concepts; extraction and contribution status`.

**Tests (later):** refusal; paging covers all rows once; class label kept on concepts; empty project.

### Task 4: List tools, hypotheses and writing

*Tier: standard.*

**Interfaces:** `lead_list(state?)`, `hypothesis_list(state?)`, `card_list(kind?)`, `experiment_list(hypothesis_id?)`, `draft_list()`, over `list_leads`, `list_hypotheses`, `list_cards`, `list_experiments`, `list_drafts`. No metric value in `experiment_list`, as `xrun_list`.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(mcp): list leads, hypotheses, cards, experiments and drafts`.

**Tests (later):** refusal; no metric in `experiment_list`; review focus 2.

### Task 5: Repin and reorder a draft

*Tier: critical (draft folds, R-51). Bumps the projection.*

**Files:** Modify `services/drafts.py`, `model/drafts.py`, `index/drafts.py`, `index/default.py`, `mcp/server.py`, `cli/main.py`.

**Interfaces:**
- Consumes: `repin_outline(project, draft_id, scope=None, *, actor) -> str` (`services/drafts.py:654`); `reorder(project, draft_id, section_id, order, *, actor) -> str` (`:916`).
- MCP: `draft_repin(project, draft_id, role, model, skill, scope_works?, ideas?, groups?)`, `draft_reorder(project, draft_id, section_id, order, role, model, skill)`, with the guards of `draft_create`.
- CLI: `factory draft repin DRF [--work W …] [--idea I …] [--group G …]`, `factory draft reorder DRF SECTION SEN …`; `draft write --order`.
- `draft.outline_repinned` gains `sections` (default empty, so old events replay as they did), and the fold adds the new outline's sections, so `draft_next` serves them (iterate line 109). The input blob records the scope, as `create_draft` does. An open slot task of a repinned draft is released, not served with its old content (`_open_slot_task`, `:1039`).
- Ruling 4's refusal in `repin_outline`, `reorder`, `withdraw`, service and fold.

- [ ] **Step 1:** Implement, bump. **Step 2:** Commit `feat(writing): repin and reorder drafts over MCP and CLI`.

**Tests (later):** new section served after repin; old log replays identically; verifier refused, with the guard removal proved; forged repin from a verifier changes nothing; reorder must list exactly the live sentences; open task released.

### Task 6: Merges

*Tier: standard.*

**Interfaces:** MCP `dedup_merges(project, cursor, limit)` (active and reverted, with the matching rule, no verdict), `merge_revert(project, merge_id, reason, role, model, skill)`. CLI `factory dedup run|list|revert`. Consumes `active_merges`, `revert_merge`.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(dedup): list and revert merges`.

**Tests (later):** a reverted pair stays apart on the next run; refusal; agent input kept.

### Task 7: Small surfaces

*Tier: light.*

**Interfaces:**
- MCP `task_release(project, task_id, role, model, skill)` over `release_task` (holder only).
- CLI `factory experiments amend EXP --design FILE --reason R`; `factory experiments evaluate-baselines EXP` (iterate lines 104, 106; a pending baseline otherwise blocks `unlock_experiment` after a crash between the two writes).
- CLI `factory regions links [REGION]` (line 74). `regions revise` defaults name, definition and rules to the current version (line 53).

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(cli): release tasks, amend experiments, evaluate baselines, list region links`.

**Tests (later):** non-holder refused; each command through the CLI runner.

### Task 8: Stage and a fuller human queue

*Tier: standard.*

**Files:** Modify `services/human_queue.py`, `services/project.py`, `services/portfolio.py`, `cli/render.py`.

**Interfaces:**
- `ProjectStatus.stage` from `derive_stage(stage_facts(project))`, made importable without the portfolio's cost.
- New `Gate` kinds, each a count plus a fixed command: `import-confirmation` (`factory import show --researcher`), `import-admission`, `attachments-waiting` (`factory import attach`), `documents-unconverted` (`factory document converters`), `inbox-open`. Counts only, so nothing about the held-out part is exposed: an import's counts use `agent_import_status` on the agent path.
- Add these to the portfolio's sort order only. Decision 69's outputs gain rows only where the count is non-zero.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(status): derived stage and intake gates in the human queue`.

**Tests (later):** each gate from real events; absent at zero; the portfolio golden unchanged on a project without imports.

### Task 9: Skills

*Tier: light.*

**Files:** Create `plugin/skills/rf-run/SKILL.md`, `plugin/skills/rf-mine/SKILL.md`; Modify `plugin/.claude-plugin/plugin.json` (the description names three skills of nineteen), `plugin/PROVENANCE.md`, `plugin/skills/rf-search/SKILL.md`.

**Content:** `rf-run` states the order of stages, which session runs which pass, which steps are the researcher's and how to read `project_status` to find the next one, including `fulltext_status`, `document_status`, the report and view tools. `rf-mine` covers `miner_register`, `mine_next`, `mine_record`, `mine_status`, `mine_disagreements`, `mine_resolve`, and is the skill a registered miner may name as its `procedure`. Both state the rule that one session holds one pass.

- [ ] **Step 1:** Write. **Step 2:** Commit `docs(plugin): rf-run and rf-mine skills`.

**Tests (later):** none; a registered miner naming `rf-mine` resolves through `skill_ref`.

## Self-review notes

- `draft_withdraw`, `draft_audit` and `draft_label` stay CLI: W-A and W-B list them so. W-B's plan line 24 names an MCP relay for `record_audit` that does not exist; relaying is a human act and falls under ruling 1, so it is left for R6.
- `factory portfolio` stays without a tool (decision 69).

## Later (not v1)

- `draft_status` and `draft_render` refused to a session holding a verification task (iterate line 125) is in plan PF, since it changes existing tools.
- A write-capable relay for human acts, if R6 is answered that way.

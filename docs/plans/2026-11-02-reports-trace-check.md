# Reports, Trace and Check Implementation Plan (slice 1, sub-plan 5b of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every reported number is derived from events: the PRISMA 2020 flow, the PRISMA-S search report, and a methods statement that discloses automation. `trace` walks from any ID back to the question and forward to its decisions. `check` lists broken links, gate failures and, with `--promote-to`, the gaps for a stricter mode. A final acceptance file covers slice-1 acceptance 1–22 (flow 11; R-01, R-05, R-24, R-25, R-60).

**Architecture:** Read-only services over the projection and the event log. No new event types. They write nothing and need no `PROJECTION_VERSION` change unless a task adds a reader table (none planned). Reports are pydantic models first and text second: the MCP tools return JSON, and the CLI renders Markdown from the same model, so a number cannot differ between the two.

**Tech Stack:** as plans 1–5a.

**Spec:** `docs/specs/00-system.md`, `docs/specs/01-rigour.md` (R-01, R-02, R-05, R-23–R-25, R-31–R-38, R-60, the promotion paragraph), `docs/specs/slice-1.md` (flow 11; acceptance 1–22, especially 10, 15, 20, 22). Decisions #36, #37, #38 are binding. Prerequisite: plan 5a is merged.

## Rulings made in this plan

1. **PRISMA scope in slice 1** is title/abstract screening only. The full-text boxes (sought, not retrieved, assessed, excluded with reasons) are present and reported as `not assessed in this review stage`, never as 0.
2. **Count definitions**, all computed:
   - *identified (databases)*: records parsed by `search`-purpose runs, per source.
   - *identified (other methods)*: records parsed by `chase` and `seed` runs, per method (R-25 counts their new-after-dedup works).
   - *duplicates removed*: records minus canonical works.
   - *screened*: canonical corpus works.
   - *excluded*: works with final outcome `exclude`, broken down by the cited EX criterion (the human's for resolved or calibration works).
   - *pending*: shown when > 0, and the report is then marked `provisional`.
   - *included*: works with final outcome `promote`.
   - Probe-purpose runs never count.
   - A work with any `database` provenance counts under databases (decision #38.6).
3. **`report_methods` is generated text from a fixed template** whose every slot is filled from events. Held-out and development recall are reported separately, held-out first and development labelled optimistic (R-24). `model` is stated as agent-reported (decision #38.5). It names no seed.
4. **`check` severities:** `error` fails the command (exit 1), and `warning` does not. Mode decides severity (e.g. single-pass records are a warning in `pilot` and an error in `systematic`). `--promote-to M` re-evaluates the same rules as if the project were in mode `M` and lists only what would become an error.
5. **MCP visibility:** `check` over MCP reports seed findings by role and count only (`1 held-out positive seed missing`), never by seed ID. The CLI, which is the human view, lists IDs. `trace` over MCP refuses a seed ID that is held out, answering as for an unknown ID.

## Global Constraints

- All constraints from plans 1–5a hold. These services write no events.
- R-05: no report field may be set from a tool argument. Every number has one computing function in `services/`, and the CLI and MCP only format it.
- Coverage ≥ 90 % for `factory.services` and `factory.model`. `mypy --strict` and ruff pass.
- Branch `plan-5b-reports`. Commit after each task. Commit trailer: `Co-Authored-By: Claude <Model> 5.5 <noreply@anthropic.com>`.
- Commands run from `platform/`.

## Review Focus

1. **A work is merged, then the merge is reverted.** Expected: PRISMA duplicates and screened counts follow the live merge set, and `trace` shows the revert. → Task 1 `test_prisma_follows_reverted_merge`.
2. **A protocol amendment staled earlier decisions** and some are not yet re-decided. Expected: they count as pending, not as their stale verdict, and the report is `provisional`. → Task 1 `test_stale_decisions_count_as_pending`.
3. **A run has a shortfall** (retrieved < reported) with or without a recorded reason. Expected: the PRISMA-S row shows both counts and the reason; an unexplained shortfall is a `check` error in every mode (acceptance 14). → Task 4 `test_unexplained_shortfall_is_error`.
4. **An agent asks `check` or `trace` about a held-out seed.** Expected: no held-out ID, DOI or arXiv form in the output. → Task 5 `test_mcp_check_and_trace_never_name_held_out`.
5. **An event refers to an ID that no event defines** (e.g. a hand-edited log, or a criterion removed by an amendment that a decision still cites). Expected: `check` reports a `broken-link` error naming the event and the ref. → Task 4 `test_broken_ref_reported`.

---

## File Structure

```
platform/src/factory/services/
  prisma.py      PrismaFlow, prisma_flow, SearchReport, search_report
  methods.py     MethodsReport, methods_report, render_methods
  trace.py       TraceNode, trace
  check.py       Finding, CheckReport, check
platform/src/factory/mcp/server.py   + report_prisma, report_methods, trace, check
platform/src/factory/cli/main.py     + report prisma|search|methods, trace ID, check [--promote-to MODE]
platform/tests/test_acceptance_slice1.py
```

---

### Task 1: PRISMA flow and PRISMA-S search report

**Files:**
- Create: `platform/src/factory/services/prisma.py`
- Test: `platform/tests/test_prisma.py`

**Interfaces:**
- Consumes: `search.search_counts`, `search.list_works`, `dedup.canonical_works`, `agreement.final_outcomes`, `screening.stale_screening_decisions`, the `queries`/`runs` index tables, `protocol.list_deviations`, the PRESS review readers.
- Produces:
  - `class PrismaFlow(StrictModel)`: `identified_databases: dict[str, int]`, `identified_other: dict[str, int]` (keys `citation-chase`, `seed-admission`, `hand-search`), `duplicates_removed: int`, `screened: int`, `excluded: dict[str, int]` (criterion ID → n, plus `"unspecified"` only if an exclusion lacks one, which should not occur), `pending: int`, `included: int`, `full_text: Literal["not assessed in this review stage"]`, `provisional: bool`, `protocol_id: str | None`
  - `def prisma_flow(project: Project) -> PrismaFlow`
  - `class SearchReportRow(StrictModel)`: `query_id, source, interface, kind, text, filters, purpose, registered_at, runs: list[RunSummary], reported: int | None, retrieved: int, shortfall_reason: str | None, deviation_id: str | None`
  - `class SearchReport(StrictModel)`: `rows: list[SearchReportRow]`, `press_review_id: str | None`, `press_confirmed: bool`, `limits: list[Limit]`
  - `def search_report(project: Project) -> SearchReport` (probe queries excluded)
- Invariant, asserted in tests: `sum(identified_databases) + sum(identified_other) − duplicates_removed == screened`, and `screened == sum(excluded) + pending + included`. A calibration work counts by its human label.

- [ ] **Step 1: Write failing tests** on a fixture project (reuse `tests/helpers.py` builders):
  - `test_prisma_identities_hold`: both invariants hold.
  - `test_prisma_counts_chase_under_other_methods`.
  - `test_work_found_by_database_and_chase_counts_once_under_databases`.
  - `test_prisma_follows_reverted_merge`.
  - `test_stale_decisions_count_as_pending`.
  - `test_full_text_not_reported_as_zero`.
  - `test_probe_runs_never_counted`.
  - `test_search_report_has_prisma_s_fields`: each row has source, interface, exact text, filters, date, reported and retrieved.
- [ ] **Step 2–4: Fail, implement, pass (suite, mypy, ruff).**
- [ ] **Step 5: Commit** `feat(reports): PRISMA 2020 flow and PRISMA-S search report from events`.

---

### Task 2: Methods statement

**Files:**
- Create: `platform/src/factory/services/methods.py`
- Test: `platform/tests/test_methods.py`

**Interfaces:**
- Consumes: `prisma_flow`, `current_protocol`, `protocol_lineage`, `list_amendments`, `list_deviations`, `seeds.seed_recall`, `calibration.calibration_status`, `agreement.screen_agreement` data (via an internal reader that does not require a non-pass session: add `agreement.agreement_summary(project) -> Agreement | None` if needed, refusing nothing, for reports only; it must not be exposed to pass sessions — the MCP tool in Task 5 applies the same pass-session refusal as `screen_agreement`), `audit.audit_report`.
- Produces:
  - `class MethodsReport(StrictModel)` with fields:
    - `rigor_mode`, `method_profile`, `protocol_id`, `amendments: int`, `deviations: int`
    - `sources: list[str]`, `models: list[str]` (distinct agent-reported models across agent events), `skills: list[str]` (distinct `skill_ref`s)
    - `passes: int`, `dual_sample: float | None`, `kappa: float | None`, `kappa_by_criterion: dict[str, float | None]`
    - `calibration_sensitivity: dict[str, float | None]` (per pass)
    - `audit_false_exclusion_rate: float | None`, `audit_n: int`
    - `recall_held_out: float | None`, `recall_development: float | None`
    - `chase_rounds: int`, `admitted_seeds: int`
    - `prisma: PrismaFlow`
  - `def methods_report(project: Project) -> MethodsReport`
  - `def render_methods(report: MethodsReport) -> str`: Markdown paragraphs in this order: search, deduplication, screening and automation disclosure, agreement and audit, seed recall, deviations. A `None` figure renders as `not computed`. The automation paragraph must contain the sentence `Screening decisions were made by Claude models (as reported by the agent: <models>) following the skills <skills>; the platform made no model calls.`
- [ ] **Step 1: Write failing tests.**
  - `test_methods_reports_held_out_before_development`: in the rendered text, the held-out figure precedes development, and development carries the word `optimistic`.
  - `test_methods_discloses_models_as_agent_reported`.
  - `test_methods_none_renders_not_computed`.
  - `test_methods_names_no_seed`: no seed ID or seed DOI appears in the render.
  - `test_methods_numbers_match_prisma`: every count in the screening paragraph equals `prisma_flow`.
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Commit** `feat(reports): methods statement generated from events`.

---

### Task 3: `trace`

**Files:**
- Create: `platform/src/factory/services/trace.py`
- Test: `platform/tests/test_trace.py`

**Interfaces:**
- Produces:
  - `class TraceNode(StrictModel)`: `id: str`, `kind: str` (one of `question, element, criterion, protocol, query, run, page, record, merge, work, decision, resolution, audit, seed, chase_round`), `label: str` (short: query text, criterion ID and text, verdict and so on), `event_id: str`, `children: list[TraceNode]`
  - `def trace(project: Project, ref: str, *, direction: Literal["back", "forward"] = "back") -> TraceNode`
- Chain (R-01): question → element/non-goal → criterion → protocol → query → run → raw page blob → record → merge → work → decision → resolution/audit.
  - *Back* from a decision: decision → work → its merges and provenance rows → run → query → protocol → cited criterion → parent element → question.
  - *Forward* from a criterion or query: every downstream node.
  - The ID prefix selects the starting kind. An unknown ID raises `FactoryValidationError([ValidationIssue("ref", "unknown id")])`.
  - Cycles cannot occur, but the walker keeps a visited set and stops on a repeat.
- [ ] **Step 1: Write failing tests.**
  - `test_trace_decision_reaches_question`: the path includes the run's archived page blob and the cited criterion's parent element.
  - `test_trace_forward_from_criterion_lists_decisions_citing_it`.
  - `test_trace_chased_work_shows_chase_round`.
  - `test_trace_unknown_id_refused`.
  - `test_trace_shows_reverted_merge`.
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Commit** `feat(trace): walk the chain from any id`.

---

### Task 4: `check` and promotion gaps

**Files:**
- Create: `platform/src/factory/services/check.py`
- Test: `platform/tests/test_check.py`

**Interfaces:**
- Produces:
  - `class Finding(StrictModel)`: `code: str`, `severity: Literal["error", "warning"]`, `refs: list[str]`, `message: str`
  - `class CheckReport(StrictModel)`: `mode: RigorMode`, `evaluated_as: RigorMode`, `findings: list[Finding]`, and a property `ok` (no errors)
  - `def check(project: Project, *, promote_to: RigorMode | None = None) -> CheckReport`
- Rules (code, then severity as *exploratory / pilot / systematic*):

| code | condition | E / P / S |
|---|---|---|
| `broken-link` | an event `ref` or payload ID that no event defines | error everywhere |
| `missing-provenance` | agent event without model, skill or input_blob | error everywhere |
| `shortfall-unexplained` | retrieved < reported and no reason | error everywhere |
| `seed-missing` | `seed_check` status `missing` | warning / error / error |
| `seed-admission-pending` | miss explained with an admission route not yet admitted (hand-search included) | warning / warning / error |
| `protocol-not-ready` | no ready protocol | – / error / error |
| `press-missing` | no confirmed PRESS review for the current strategy | – / error / error |
| `screening-pending` | pending works > 0 | warning everywhere |
| `single-pass` | promote/exclude works decided by pass A only | – / warning / error |
| `calibration-missing` | a pass without passing calibration under the current protocol | – / error / error |
| `kappa-below-floor` | κ < declared floor | warning, or error if `kappa_enforced` |
| `audit-missing` | no audit sample over the current agreed set | – / warning / error |
| `audit-error-high` | false-exclusion rate > `AUDIT_ERROR_CEILING` | – / warning / error |
| `chase-missing` | promote works exist and no chase round after the last agreement | – / warning / error |
| `profile-checklist` | R-60: the method profile's reporting items with no derived source (start with PRISMA 2020 items 6–9, 13a; list the uncovered ones) | warning everywhere |

  `promote_to` evaluates as that mode and returns only the findings that are errors under it but not under the current mode (acceptance 20).
- [ ] **Step 1: Write failing tests**, one per row (`test_<code>_<mode>`, table-driven), plus:
  - `test_broken_ref_reported`.
  - `test_unexplained_shortfall_is_error`.
  - `test_promote_pilot_to_systematic_lists_single_pass_and_missing_audit` (acceptance 20).
  - `test_clean_project_is_ok`.
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Commit** `feat(check): links, gates and promotion gaps`.

---

### Task 5: MCP tools, CLI and slice-1 acceptance

**Files:**
- Modify: `platform/src/factory/mcp/server.py`
  - `report_prisma()` returns `PrismaFlow` plus `SearchReport` JSON.
  - `report_methods()` returns `{"report": MethodsReport, "text": str}` and is refused to pass sessions while a pass is unfinished, as `screen_agreement` is.
  - `trace(ref, direction)`.
  - `check(promote_to)`: seed findings are aggregated by role per ruling 5, and the scrub is applied.
- Modify: `platform/src/factory/cli/main.py`: `report prisma`, `report search`, `report methods` (Markdown, or `--json`); `trace REF [--forward]` (indented tree); `check [--promote-to MODE]` (exit code 1 on errors, the human view with IDs).
- Modify: `plugin/skills/rf-screen/SKILL.md` or `rf-search/SKILL.md`: a closing step that runs `check` and reports findings to the human. Change nothing else in the skill.
- Create: `platform/tests/test_acceptance_slice1.py`
- Modify: `CLAUDE.md` status line (slice 1 sub-plans 1–5 implemented); `docs/specs/slice-1.md` (flow 11 implemented)

- [ ] **Step 1: Write failing tests.**
  - `test_mcp_check_and_trace_never_name_held_out`.
  - `test_mcp_report_methods_refused_to_pass_session_mid_screening`.
  - `test_cli_check_exit_code`.
  - `test_cli_report_prisma_matches_mcp_numbers`.
  - In `test_acceptance_slice1.py`, one test per slice-1 acceptance criterion 1–22, named `test_ac<NN>_<slug>`. Where an earlier acceptance file already proves a criterion, the test imports and calls that file's scenario helper rather than duplicating it. Each test's docstring quotes the criterion.
- [ ] **Step 2–4: Fail, implement, pass. Then run** `uv run pytest --cov=factory.services --cov=factory.model --cov-fail-under=90 -q`, `uv run mypy --strict src` and `uv run ruff check`.
- [ ] **Step 5: Commit** `feat(reports): MCP and CLI for reports, trace and check; slice-1 acceptance`.

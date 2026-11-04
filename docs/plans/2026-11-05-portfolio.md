# Portfolio View Implementation Plan (slice 7a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Option A is the accepted option (decision 69). Task 5 records no new decision (69 is recorded) and only updates the spec's "Implemented" note and 00-system §1 and §9. If slice M is on the base, Task 1's `human_queue` names gates by their slice-M ids. It implements option A of `docs/specs/slice-7a-portfolio.md`. Tasks 1–3 (human queue, stage rule, builder and JSON) are needed by options B and C as well; only Task 4 (Markdown and HTML renderers) is specific to option A. If the researcher chooses B or C, Tasks 1–3 stand and Task 4 is replaced.

> **Dependencies.** Plans 2C, 2D and 2E merged (screening stages, extraction, audits). G1 and slice 4a are optional: their gate kinds are added when their services exist on the base (spec ruling 5). Paths are relative to `platform/` unless they start with `docs/`.

**Goal:** A read-only `factory portfolio` command that lists every project with its derived stage, open agent work and pending human decisions, as Markdown, self-contained HTML and JSON.

**Architecture:** `services/human_queue.py` derives one project's pending human acts from existing services; `services/portfolio.py` folds `project_status`, `human_queue` and the stage rule over `list_projects`; `cli/portfolio_render.py` renders the model. Nothing writes an event; each project is opened with a fresh session id.

**Tech Stack:** as slices 1–2; no new dependencies (HTML is built with `html.escape` and string templates).

**Spec:** `docs/specs/slice-7a-portfolio.md` rulings 1–8, acceptance 1–7. `docs/specs/01-rigour.md` R-01, R-05, R-39. Decisions 37 (item 8), 43.

## Global Constraints
- The platform never calls a model. The portfolio writes no event; index refresh is the projector's own write.
- No label-derived rate, seed id, held-out figure or work title in any output (spec ruling 3).
- Business logic in `services/`; renderers take the model only.
- `uv run pytest -m "not network"`, `mypy --strict`, ruff pass after each task; coverage ≥ 90% for `services/` and `model/`.

## Review Focus
1. Events files are byte-identical before and after `portfolio(...)` (Task 3, `test_portfolio_writes_no_event`).
2. A corrupt project is isolated; the others render (Task 3, `test_corrupt_project_isolated`).
3. No title, seed id or rate reaches the JSON (Task 3, `test_json_carries_no_sensitive_values`).
4. Each stage row of spec ruling 4 is reached by exactly one fixture and the first matching row wins (Task 2).

## File Structure
- Create `services/human_queue.py`, `services/portfolio.py`, `cli/portfolio_render.py`.
- Modify `services/project.py` (optional `human` field), `cli/main.py` (`portfolio` command; `status` prints the human list).
- Tests: `tests/test_human_queue.py`, `tests/test_portfolio_stage.py`, `tests/test_portfolio.py`, `tests/test_portfolio_render.py`, `tests/test_cli_portfolio.py`; helper `tests/portfolio_helpers.py` (builds projects at each stage under one tmp root by reusing `tests/screening_helpers.py` and `tests/extraction_helpers.py`).

---

### Task 1: Per-project human queue

*Tier: standard (implementer sonnet, review sonnet: correctness of each count).*

**Files:** Create `services/human_queue.py`; Modify `services/project.py`; Test `tests/test_human_queue.py`.

**Interfaces:**
- Consumes: `current_protocol` (`press`), `calibration_status(project, stage=…)`, `screen_agreement(project, human_actor, stage=…)` (refused while passes are open → 0 and no item), `audit_report(project, stage=…)`, `extract_agreement`, `extraction_audit_report`; when present on the base, G1's reference-decision counts and slice 4a's `list_items(status="open")`.
- Produces: `class Gate(StrEnum)`: `press-confirmation`, `calibration-labels`, `screening-disagreements`, `screening-audit`, `extraction-disagreements`, `extraction-audit`, and, conditionally, `reference-confirmation`, `inbox-open`; `HumanItem(gate: Gate, stage: str | None, count: int, command: str)`; `HumanQueue(items: list[HumanItem])`; `human_queue(project) -> HumanQueue` (items with `count > 0` only, sorted by gate order then stage); `ProjectStatus.human: HumanQueue | None = None`, filled by `project_status`.

- [ ] **Step 1: Tests.** One fixture per gate (count and command string asserted); `unsure` in one pass counts as a disagreement; a project with nothing waiting returns no items; `screen_agreement` refusal while a pass is open yields no disagreement item (not an exception); `project_status(...).human` equals `human_queue(...)`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement; commands are fixed strings with `--project <slug>` and `--stage` where the gate is staged. **Step 4:** Status suites (the only edited assertion is the status key set). **Step 5:** Commit `feat(status): human queue per project`.

### Task 2: Stage rule (pure)

*Tier: standard.*

**Files:** Create the rule inside `services/portfolio.py` as `derive_stage(facts: StageFacts) -> Stage`; Test `tests/test_portfolio_stage.py`.

**Interfaces:**
- Produces: `class Stage(StrEnum)`: `scoping`, `protocol`, `search`, `ta-screening`, `full-text`, `extraction`, `snowballing`, `reporting`; `@dataclass(frozen=True) StageFacts(has_question, has_protocol, protocol_ready, press_confirmed, press_required, complete_search_runs, ta_pending, ft_plan, ft_open, extraction_schema, extraction_open, snowball_plan, snowball_open)`; `stage_facts(project) -> StageFacts` (service reads: `current_question`, `current_protocol`, `search_counts`, `final_outcomes`, `fulltext_queue`/`fulltext_status`, extraction units without final rows, the G1 stopping-rule state when present).

- [ ] **Step 1: Tests.** Table-driven over `StageFacts` (one case per row of spec ruling 4, plus precedence cases where two rows match); `stage_facts` on four helper projects (scoping, protocol, ta-screening, extraction).
- [ ] **Step 2:** FAIL. **Step 3:** Implement `derive_stage` as an ordered list of `(predicate, stage)`. **Step 4:** mypy; ruff. **Step 5:** Commit `feat(portfolio): derived stage rule`.

### Task 3: Portfolio builder and JSON

*Tier: critical (read-only guarantee, information hiding).*

**Files:** Modify `services/portfolio.py`; Test `tests/test_portfolio.py`.

**Interfaces:**
- Consumes: `list_projects`, `open_project(settings, slug, session=new ULID, clock)`, `project_status`, `prisma_flow` (included counts only), `full_text_boxes`, `human_queue`, `stage_facts`, `derive_stage`.
- Produces: `PortfolioRow`, `Portfolio` (spec, Model; `schema = 1`); `portfolio(settings, *, clock, as_of: datetime) -> Portfolio`; a row with `error: str | None` (exception class name only) when a project cannot be read.

- [ ] **Step 1: Tests.** Acceptance 1, 2 (counts equal `project_status`, `prisma_flow`), `test_portfolio_writes_no_event` (hash every file under `events/` before and after), `test_corrupt_project_isolated`, `test_json_carries_no_sensitive_values` (scan the dumped JSON for each fixture title, every seed id, and keys containing `kappa`, `rate`, `recall`, `sensitivity`, `specificity`), determinism across two calls and across `factory rebuild`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement; catch `FactoryError` and `ValidationError` per project only. **Step 4:** mypy; ruff. **Step 5:** Commit `feat(portfolio): builder and JSON model`.

### Task 4: Renderers and CLI (option A)

*Tier: standard (implementer haiku or sonnet, review haiku).*

**Files:** Create `cli/portfolio_render.py`; Modify `cli/main.py`; Test `tests/test_portfolio_render.py`, `tests/test_cli_portfolio.py`.

**Interfaces:**
- Produces: `render_markdown(p: Portfolio, as_of: datetime) -> str`; `render_html(p: Portfolio, as_of: datetime) -> str` (one document, inline CSS with light and dark tokens under `prefers-color-scheme`, no `<script>`, every value through `html.escape`); CLI `factory portfolio [--json] [--html PATH] [--as-of ISO]`; `factory status` prints the human list after the existing lines.

- [ ] **Step 1: Tests.** Markdown snapshot for the two-project fixture; HTML contains no `<script`, escapes a slug-like hostile string in an error message, and is byte-identical across runs; CLI writes `--html` to the path and refuses an existing directory path with exit 1; `--json` output parses into `Portfolio`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** CLI suites. **Step 5:** Commit `feat(portfolio): Markdown and HTML renderers, CLI`.

### Task 5: Docs and decision

*Tier: mechanical.*

**Files:** Modify `docs/specs/slice-7a-portfolio.md` (status, "Implemented" note), `docs/specs/00-system.md` (§1 scope sentence on generated read-only reports; §9 adds `factory portfolio`), `docs/decisions.md` (the spec's proposed entry, numbered at the next free number), `docs/backlog.md` (IDEA-01 → `accepted`, linked), `CLAUDE.md` status line.

- [ ] **Step 1:** Edit docs. **Step 2:** Run the whole suite once. **Step 3:** Commit `docs(portfolio): spec status, system scope, decision`.

## Later (not v1)

None: every task of this plan is in v1.

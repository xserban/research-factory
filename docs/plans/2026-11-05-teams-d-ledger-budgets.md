# Contribution Ledger and Budgets Implementation Plan (slice 5, sub-plan teams-D)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** `CREDIT_MAP_V1` also maps the families of slices 3d, 4a, 4b, 6 and 7b (slice-5 reconciliation item 4) and lists unmapped families. Names: `services/ledger.py`, `ledger_view` and `factory ledger` belong to this plan; slice 6 uses `benchmark_ledger`; `budget-exhausted` is this plan's (slice 6 uses `compute-budget-*`). Bumps `PROJECTION_VERSION` by one from the value it finds.

> **Dependencies.** teams-A merged (`Principal`, `ProjectRole`, `authorize`, `Permission.PROJECT_GOVERN`). Independent of teams-B and teams-C; if teams-C is merged, the ledger counts human screening decisions under Investigation through the same map. deploy-B's per-tool wrapper picks up the new tools' `TOOL_PERMISSIONS` rows.

**Goal:** Derive who contributed what (CRediT roles for people, an AI-assistance statement for agents) from events, confirmed by each person; and bound agent work per project and per person by declared, computed budgets.

**Architecture:** `services/ledger.py` folds the event log through a versioned map from event type to CRediT role; the ledger has a canonical hash; `ledger.confirmed` pins a person's confirmation to that hash. `services/budgets.py` folds `budget.set` events and counts consumption from `task.claimed` and source-request events in a period; `require_budget` is called by the `*_next` services and by the source-calling services before any write.

**Tech Stack:** as slice 2.

**Spec:** `docs/specs/slice-5-teams-deployment.md` rulings 16, 17; Design "Ledger", "Budgets"; R-112; check findings `ledger-unconfirmed`, `budget-exhausted`; acceptance 10, 11.

## Rulings made in this plan

1. **`CREDIT_MAP_V1`** (event type prefix → CRediT role): `question.` → Conceptualization; `seed.`, `probe.`, `protocol.` → Methodology; `query.`, `search.`, `chase.`, `snowball.`, `screening.decision_recorded`, `extraction.recorded`, `extraction.claim_recorded`, `reference.extracted` → Investigation; `dedup.`, `fulltext.`, `document.`, `reference.resolved` → Data curation; `calibration.labelled`, `audit.labelled`, `extraction.audit_labelled`, `screening.disagreement_resolved`, `extraction.resolved`, `reference.resolution_decided` → Validation; `review.decided`, `member.`, `budget.set` → Supervision (people only); `task.`, `project.`, `screening.pass_*`, `extraction.pass_*` → none. Unknown types → none, listed as `unmapped` so the map's coverage is visible. Longest prefix wins. [confirm]
2. **Agents.** Agent events are grouped by (role, model, skill) under `actor.user` and never appear in the CRediT table; they appear in the AI-assistance statement with the CRediT role they would map to and counts. [confirm]
3. **Ledger hash** = SHA-256 of the canonical JSON of the ledger rows (not of the rendering) plus the map version. [confirm]
4. **Budget units.** `tasks:<kind>` for each task kind (`screen_a`, `screen_b`, extraction kinds, …) and `tasks:*`; `requests:search` (`search.page_archived`, `probe.page_archived`), `requests:fulltext` (`fulltext.attempted`). [confirm]
5. **Who is charged.** A task claim is charged to `actor.user` of the claiming event; a source request to `actor.user` of the run's starting event. [confirm]
6. **Refusal point.** `*_next` refuses before claiming when the user's or the project's consumption in the period has reached the limit; a search run checks before each page and stops as a partial run (R-23: recorded as partial, resumable) when the budget is reached mid-run. [confirm]

## Global Constraints

- Nothing in the ledger or consumption is typed; both are computed from events (R-05).
- Reported usage is shown, labelled *reported*, and never enforced.
- Budget refusal writes nothing (except the partial-run record of ruling 6, which is today's partial-run event).
- `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff pass; coverage ≥ 90%.

## Review Focus

1. Ledger counts equal hand-computed counts on a constructed log with two people, two agent roles and an unmapped event type (Task 1, `test_ledger_counts_by_hand`).
2. One event after a confirmation makes it stale (Task 2, `test_confirmation_goes_stale`).
3. Budget k: the (k+1)-th `screen_next` is refused for that user and allowed for another (Task 4, `test_user_budget_refuses_next`).
4. A search hitting its request budget mid-run ends as a resumable partial run (Task 4, `test_search_budget_partial_run`).

## File Structure

- Create `services/ledger.py`, `services/budgets.py`, `model/ledger.py`, `model/budgets.py`, `index/budgets.py`.
- Modify `model/task.py` (`TaskCompleted.reported_usage`), `events/catalog.py`, `index/default.py`, `services/screening.py`, `services/extraction.py`, `services/search.py`, `services/fulltext.py`, `services/check.py`, `services/methods.py`, `mcp/server.py`, `cli/main.py`.
- Tests: `tests/test_ledger.py`, `tests/test_ledger_confirm.py`, `tests/test_budgets.py`, `tests/test_budget_enforcement.py`.

---

### Task 1: Ledger fold

*Tier: standard.*

**Files:** Create `model/ledger.py`, `services/ledger.py`; Test `tests/test_ledger.py`.

**Interfaces:**
- Produces: `CreditRole(StrEnum)` (the 14 CRediT roles; only those of ruling 1 are produced); `CREDIT_MAP_V1: tuple[tuple[str, CreditRole | None], ...]`, `MAP_VERSION = "credit-map@1"`; `PersonRow(user, role: CreditRole, events: int, first: datetime, last: datetime)`; `AgentRow(user, agent_role, model, skill, role: CreditRole | None, events: int)`; `Ledger(people: list[PersonRow], agents: list[AgentRow], unmapped: dict[str, int], map_version: str, ledger_hash: str)`; `ledger(project) -> Ledger` (reads events in ID order, streaming per file; no full in-memory list beyond per-key counters).

- [ ] **Step 1: Tests.** `test_ledger_counts_by_hand`, `test_agents_not_in_credit_table`, `test_unmapped_listed`, `test_longest_prefix_wins`, `test_hash_stable_across_rebuild`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(ledger): contribution ledger derived from events`.

### Task 2: Rendering and confirmation

*Tier: standard.*

**Files:** Modify `services/ledger.py`, `events/catalog.py`, `cli/main.py`, `mcp/server.py`, `services/check.py`; Test `tests/test_ledger_confirm.py`.

**Interfaces:**
- Produces: event `ledger.confirmed` `LedgerConfirmed(user, ledger_hash, map_version, channel: Channel)` (human; the confirming user must be the `user`, or an owner confirming for a deactivated user with a reason); `confirmations(project) -> dict[str, Confirmation(hash, current: bool)]`; `render_ledger(ledger, confirmations) -> str` (Markdown: CRediT table per person, AI-assistance statement, map version, hash, confirmation status); CLI `factory ledger [--confirm]`; MCP `ledger_view(project)` (counts only, read); check `ledger-unconfirmed` (promotion gap, before any export command of slice 7).

- [ ] **Step 1: Tests.** `test_confirm_pins_hash`, `test_confirmation_goes_stale`, `test_cannot_confirm_for_another_user`, `test_render_names_map_version_and_hash`, `test_ledger_view_refused_to_pass_session`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(ledger): rendering and per-person confirmation`.

### Task 3: Budgets and consumption

*Tier: standard.*

**Files:** Create `model/budgets.py`, `index/budgets.py`, `services/budgets.py`; Modify `events/catalog.py`, `index/default.py`; Test `tests/test_budgets.py`.

**Interfaces:**
- Produces: `BudgetSet(budget_id: str (bdg_<ULID>), scope_user: str | None, unit: str, limit: int (ge 0), period: Literal["total", "week"])` (owner; supersedes the previous budget of the same `(scope_user, unit)`); `budgets(project) -> list[Budget]`; `consumption(project, *, user: str | None, unit: str, period: str, now: datetime) -> int` (SQL count over indexed `task_claims(user, kind, ts)` and `source_requests(user, kind, ts)` projection tables; ISO week in UTC); `remaining(project, user, unit, now) -> int | None` (minimum over the user's and the project's budgets; None when unbudgeted).

- [ ] **Step 1: Tests.** `test_budget_supersedes_same_scope`, `test_consumption_counts_claims_by_user_and_kind`, `test_week_boundary_utc`, `test_remaining_is_min_of_user_and_project`, `test_counts_scale_by_index` (`slow`: 10^5 claims, query under 100 ms).
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(budgets): declared budgets and computed consumption`.

### Task 4: Enforcement, reported usage, tools

*Tier: standard.*

**Files:** Modify `services/screening.py` (`screen_next`), `services/extraction.py` (`extract_next`), `services/search.py` (page loop), `services/fulltext.py` (attempt loop), `model/task.py`, `services/methods.py`, `mcp/server.py`, `cli/main.py`, `services/check.py`; Test `tests/test_budget_enforcement.py`.

**Interfaces:**
- Produces: `require_budget(project, principal, unit) -> None` raising `FactoryValidationError([ValidationIssue("budget", "budget-exhausted: <unit>")])`; `TaskCompleted.reported_usage: dict[str, float] | None = None` (keys `input_tokens`, `output_tokens`, `cost_usd`; agent-reported); MCP `budget_status(project)`; CLI `factory budget set|status`; methods sentence on budgets and reported usage; check `budget-exhausted` (advisory).

- [ ] **Step 1: Tests.** `test_user_budget_refuses_next`, `test_project_budget_refuses_everyone`, `test_refusal_writes_nothing`, `test_search_budget_partial_run` (resumable after the budget is raised), `test_reported_usage_never_enforced`, `test_budget_status_counts`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Verification `uv run pytest -m "not network and not slow" -q && uv run mypy --strict src && uv run ruff check .`; commit `feat(budgets): enforcement at task issuance and source requests`.

## Later (not v1)

None: every task of this plan is in v1.

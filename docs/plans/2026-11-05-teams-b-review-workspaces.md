# Review Requests, Team Gates and Workspaces Implementation Plan (slice 5, sub-plan teams-B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Slice M is merged: Task 2 does not write a `TEAM_GATES` table; it adds `required_role` to slice M's `GateSpec` (default `maintainer` for human decision gates, `owner` for membership, visibility and budgets) and computes `TEAM_GATES` from `default_modules()`, covering the gates of every slice (slice-M reconciliation table). Bumps `PROJECTION_VERSION` by one from the value it finds.

> **Dependencies.** teams-A merged (`ProjectRole`, `roles_of`, `Permission`, `authorize`, `Principal`). May run in parallel with deploy-B, teams-C and teams-D. When slice M ([slice-M-modules.md](../specs/slice-M-modules.md)) lands, `TEAM_GATES` moves into each module's gate policy as its role dimension; the review mechanism here is unchanged by that move.

**Goal:** Let contributors propose what they may not apply alone, let a holder of the required role decide, and apply only through the ordinary validated tool; add project visibility, a per-person workspace view and the role-based held-out view.

**Architecture:** `review.requested` / `review.decided` events in the project log; review state is folded on read in `services/reviews.py`. `TEAM_GATES` maps gate names to the role that passes them; `authorize` consults it for gate tools. `protocol_amend` gains `review_request_id` and consumes an approved review. Visibility is a project event; the workspace is a read model over existing tables filtered by user.

**Tech Stack:** as slice 2.

**Spec:** `docs/specs/slice-5-teams-deployment.md` rulings 13, 14, 20; Design "Review requests"; check findings `member-missing-reviewer-of-record`, `review-open`, `review-stale`; acceptance 7, 13.

## Rulings made in this plan

1. **Review kinds in this plan.** `protocol-amend` (target: current `P@`; proposal: `ProtocolSpec` + reason + semantic flag + criterion effects, as `protocol_amend` takes them), `protocol-record` (target: the project; proposal as `protocol_record`), `deviation` (target: current `P@`). Kinds for relations, ideas and interpretations are added by the plans that build those gates (G2-C, G3) using the same events. [confirm]
2. **Stale.** A `protocol-amend` or `deviation` request is stale when the current protocol id differs from its `target_version`. A stale request can be decided `reject` or `withdraw` only. [confirm]
3. **Consumption.** An approved request is consumed by the first successful tool call that names it; a second call naming it is refused. Consumption is the tool's own event carrying `review_request_id`; no separate event. [confirm]
4. **Who may withdraw.** Only the requester; withdrawal needs no role. [confirm]

## Global Constraints

- Approval never executes anything; the approver runs the ordinary tool, which validates as today.
- Requester ≠ decider (R-51), checked by user, not by session.
- Events are the source of truth; review status is computed on read.
- Business logic in `services/`; `mcp/`, `cli/` parse and format only.
- `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff pass; coverage ≥ 90%.

## Review Focus

1. A requester cannot approve their own request, even from another session or through an agent (Task 1, `test_requester_cannot_decide`).
2. An amendment through an approved request produces exactly the `P@` that a direct amendment with the same spec produces (Task 2, `test_reviewed_amend_equals_direct_amend`).
3. A screener's CLI `report prisma` equals the MCP agent view (Task 4, `test_screener_cli_gets_agent_view`).

## File Structure

- Create `model/reviews.py`, `index/reviews.py`, `services/reviews.py`, `services/workspace.py`.
- Modify `model/protocol.py` (`ProtocolAmended.review_request_id`, `DeviationRecorded.review_request_id`), `services/protocol.py`, `services/access.py` (`TEAM_GATES`), `model/project.py` (`ProjectVisibilitySet`), `events/catalog.py`, `index/default.py`, `services/check.py`, `mcp/server.py`, `cli/main.py`.
- Tests: `tests/test_reviews.py`, `tests/test_reviewed_amend.py`, `tests/test_workspace.py`, `tests/test_heldout_by_role.py`.

---

### Task 1: Review requests and decisions

*Tier: critical.*

**Files:** Create `model/reviews.py`, `index/reviews.py`, `services/reviews.py`; Modify `events/catalog.py`, `index/default.py`; Test `tests/test_reviews.py`.

**Interfaces:**
- Produces: `REVIEW_REQUEST_ID_RE = rf"^rrq_{ULID_RE}$"`; `ReviewKind(StrEnum)`: `PROTOCOL_AMEND`, `PROTOCOL_RECORD`, `DEVIATION`; `ReviewRequested(review_request_id, kind, target: str, target_version: str | None, proposal_blob: str, required_role: ProjectRole, reason: str)`; `ReviewDecided(review_request_id, decision: Literal["approve", "reject", "withdraw"], rationale: str, channel: Channel)`; `ReviewState(StrEnum)`: `OPEN`, `APPROVED`, `REJECTED`, `WITHDRAWN`, `CONSUMED`, `STALE`.
- Produces: `request_review(project, actor, kind, proposal: JsonValue, reason) -> str` (actor needs `work:run`; proposal validated by the kind's model before writing); `decide_review(project, actor, review_request_id, decision, rationale, channel) -> None` (human only; `review:decide` and the required role; requester refused; stale allows reject/withdraw only); `review(project, review_request_id) -> ReviewView`; `reviews(project, *, state: ReviewState | None = None) -> list[ReviewView]`.

- [ ] **Step 1: Tests.** `test_request_validates_proposal` (an invalid `ProtocolSpec` writes nothing, errors under `proposal.*`), `test_requester_cannot_decide` (same user via CLI, via another session, via agent actor: all refused), `test_contributor_cannot_decide`, `test_withdraw_by_requester_only`, `test_state_folds_on_read`, `test_rebuild_identical`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(reviews): review requests and decisions`.

### Task 2: Protocol changes through review; `TEAM_GATES`

*Tier: critical.*

**Files:** Modify `model/protocol.py`, `services/protocol.py`, `services/access.py`, `services/reviews.py`; Test `tests/test_reviewed_amend.py`.

**Interfaces:**
- Produces: `TEAM_GATES: Mapping[str, ProjectRole]` (`protocol.record`, `protocol.amend`, `protocol.deviation`, `protocol.press_confirm` → `MAINTAINER`; `member.grant`, `budget.set` → `OWNER`; and, for each of the slice-3 confirmation gates already merged when this plan runs (G1 fuzzy-link confirmation, G2-C relation and idea decisions, G3 interpretation and concept reviews), a row → `MAINTAINER` whose CLI command calls `authorize` before its service); `amend_protocol(..., review_request_id: str | None = None)`, `record_protocol(..., review_request_id=None)`, `record_deviation(..., review_request_id=None)`: when given, the request must be `APPROVED`, of the matching kind, not stale, and its proposal must equal the call's arguments (canonical JSON); the actor must hold the gate's role (the approver or another holder); payload carries `review_request_id`. A contributor calling without a request is refused with `ValidationIssue("permission", "protocol:change not held; file a review request")`.

- [ ] **Step 1: Tests.** `test_contributor_amend_refused`, `test_reviewed_amend_equals_direct_amend` (same `P@`, stale set and calibration effects), `test_request_consumed_once`, `test_mismatched_proposal_refused`, `test_stale_request_cannot_be_consumed`, `test_old_logs_replay_identical_p_ids`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(reviews): protocol changes through approved review requests`.

### Task 3: Visibility and workspace view

*Tier: standard.*

**Files:** Modify `model/project.py`, `events/catalog.py`, `index/project.py`, `services/access.py`; Create `services/workspace.py`; Test `tests/test_workspace.py`.

**Interfaces:**
- Produces: event `project.visibility_set` `ProjectVisibilitySet(visibility: Literal["lab", "private"])` (owner); `visibility(project) -> Literal["lab", "private"]` (default `lab`); `authorize` refuses `project:read` to non-members of a `private` project; lab members without grants get `observer` on `lab` projects.
- Produces: `workspace(project, user) -> Workspace(sessions: list[SessionSummary], open_tasks: list[str], proposals: list[str], reviews_requested: list[ReviewView], reviews_to_decide: list[ReviewView], roles: frozenset[ProjectRole])`, all computed from events by `actor.user`; MCP tool `whoami(project: str | None)` returning principal, session, roles and (with a project) the workspace counts; CLI `factory workspace [--user U]`.

- [ ] **Step 1: Tests.** `test_private_project_refuses_non_member_read`, `test_lab_member_observes_lab_project`, `test_workspace_lists_only_own_items`, `test_reviews_to_decide_require_role`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(workspace): visibility and per-person workspace view`.

### Task 4: Held-out view by role; check findings; tools

*Tier: standard.*

**Files:** Modify `cli/main.py` (report, trace, check, status commands), `services/check.py`, `mcp/server.py`; Test `tests/test_heldout_by_role.py`, `tests/test_check.py` (new tests only).

**Interfaces:**
- Produces: `full_view_allowed(project, principal) -> bool` in `services/access.py` (`owner` or `maintainer`); the CLI's report, trace, check and status commands use the agent-view formatting already used by MCP (`_withheld`, `_without_rates`, `agent_methods`) when it is false; MCP tools `review_request`, `review_list`, `review_decide` (with `TOOL_PERMISSIONS` rows); check findings `member-missing-reviewer-of-record`, `review-open`, `review-stale`.

- [ ] **Step 1: Tests.** `test_screener_cli_gets_agent_view` (byte-equal to the MCP payload for `report_prisma` and `report_methods`), `test_owner_cli_gets_full_view`, `test_unhosted_cli_unchanged` (implicit owner), `test_member_missing_reviewer_of_record`, `test_review_findings`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Verification `uv run pytest -m "not network and not slow" -q && uv run mypy --strict src && uv run ruff check .`; commit `feat(reviews): tools, held-out view by role and check findings`.

## Later (not v1)

None: every task of this plan is in v1.

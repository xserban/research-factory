# Supervision and Lab Rhythm Implementation Plan (backlog triage, plan SV)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Proposed 2026-11-05 (backlog triage, `2026-11-05-backlog-triage.md`).** Items marked [confirm] await the researcher. No spec covers this plan; slice 5 lists IDEA-10 and IDEA-14 as out of scope, so every ruling here is a proposal.

> **Dependencies.** Base `d66387f` or later. Task 2 reads V-C's briefing if merged, and otherwise composes the same sources. Task 3 needs teams-A's roles (plan-teams-a). Task 5's tool lands after MS. Paths are relative to `platform/`.

**Goal:** Supervise agents with measured evidence (IDEA-10), prepare a weekly pack and a handover (IDEA-14), turn audit findings into reviewed proposals (IDEA-15), and give the portfolio a page (IDEA-01 option C).

**Basis:** Agreement, calibration and audit exist; nothing groups them by role, model and skill version. No `performance`, `pack`, `handover` or `curat` symbol exists. `human_queue` has no person dimension. IDEA-03's digest is built (`factory digest`, `digest_get`, `rf-living`); delivery is a skill-level step by decision 63. Decisions 6, 37, 43, 63, 69; R-34, R-51, R-52.

**Projection:** Task 4 bumps `PROJECTION_VERSION` by one. Others do not.

## Proposed decision (number fixed at merge)

**PD-8. Performance record and curation [confirm].**
1. A record is keyed by (role, model, skill version), or a person for human passes. A skill or model change starts a new row, never a blended one. Metrics come only from calibration, agreement and audit events.
2. Label-derived rates stay off agent surfaces (decision 43): the view is CLI only.
3. Curation: an agent reads a computed `lessons` list and records a **proposal** (`cur_`), kind `amendment`, `worked-example` or `skill-revision`. A human other than the proposer decides. An accepted amendment still goes through `protocol_amend` (R-34): the decision only records the link. Learning never enters as retrieved memory. Options on who decides: (a) the researcher; (b) teams-B's review request. **Recommended: (a) in v1**, moving to (b) with teams.

## Global Constraints

- Read-only builders write nothing; every figure is computed (R-05).
- A metric below its sample floor (10 labelled items) is shown with `n`, never as a rate.
- No scheduler (decision 63); no delivery channel in the platform.
- Visibility across people is teams-A's `private`; nothing here widens it.

## Review Focus

1. No rate reaches MCP.
2. A skill-version change splits a row.
3. A proposer cannot decide its own proposal, on rebuild too (R-51).

## File Structure

Create `services/performance.py`, `services/lab_pack.py`, `services/curation.py`, `model/curation.py`, `index/curation.py`, `services/modules/curation.py`, `plugin/skills/rf-curate/SKILL.md`, `plugin/skills/rf-portfolio-page/SKILL.md`. Modify `cli/main.py`, `cli/render.py`, `services/human_queue.py`, `services/check.py`, `events/catalog.py`, `index/default.py`, `mcp/server.py`.

### Task 1: Performance view

*Tier: standard.*

**Interfaces:** `performance(project) -> PerformanceReport`; rows `PerfRow(role, model, skill, tasks, sensitivity, specificity, kappa_with: dict, audit_error_rate, n_labels, first, last)`. `factory performance [--json]`.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(supervision): performance record per role, model and skill version`.

**Tests (later):** hand-computed figures; version split; floor; no tool exposes it.

### Task 2: Meeting pack and handover

*Tier: standard.*

**Interfaces:** `lab_pack(project, since) -> LabPack` (progress counts, amendments, disagreements to discuss, new literature from the digest, human queue); `factory pack [--since EVENT|last] [--out PATH]`; `factory pack --handover` adds open tasks and what each pending gate needs, using V-C's reading path when present. Counts and titles only.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(supervision): meeting pack and handover`.

**Tests (later):** sections from a fixture; fresh project empty with notices; deterministic.

### Task 3: Routing by person

*Tier: standard. Needs teams-A.*

**Interfaces:** `HumanItem.assignee: str | None` from the project role of the gate; `factory status --mine`. Per-person budgets across projects (slice 5 open question 6) stay with teams-D's Later.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(supervision): route pending decisions to the responsible person`.

**Tests (later):** role mapping; unassigned without roles.

### Task 4: Lessons and proposals

*Tier: critical (R-34, R-51). Bumps the projection.*

**Interfaces:** `lessons(project) -> list[Lesson]` (audit errors, disagreements by criterion, `cannot-assess` spikes, failed runs; computed). Events `curation.proposed`, `curation.decided`; `propose(project, actor, kind, text, lessons, target)`, `decide_proposal(project, actor, cur_id, decision, *, rationale, amendment_event=None)`. `factory curation list|decide`.

- [ ] **Step 1:** Implement, bump. **Step 2:** Commit `feat(curation): reviewed proposals from audit findings`.

**Tests (later):** review focus 3; rejected proposals stay (R-52); acceptance changes no protocol by itself; forged decision.

### Task 5: Curator tools and skill

*Tier: light. After MS.*

**Interfaces:** MCP `lessons_list` (without rates; refused to pass sessions), `curation_propose`; skill `rf-curate`. A new skill version must pass calibration before use, as the skill text states (IDEA-15).

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(curation): curator tools and skill`.

**Tests (later):** pin list; refusal; no rate.

### Task 6: Portfolio page and digest delivery notes

*Tier: light.*

**Interfaces:** skill `rf-portfolio-page`: read `factory portfolio --json` and publish a page, option C of slice 7a, a skill-level step. Add to `docs/runbook-living.md` a worked external schedule for `factory watch run --due --all` and `factory digest --all --record`. A local web UI (option B) stays out.

- [ ] **Step 1:** Write. **Step 2:** Commit `docs: portfolio page skill and digest schedule`.

**Tests (later):** none.

## Self-review notes

- Task 3 touches `human_queue.py`, also touched by MS Task 8. Land MS first.

## Later (not v1)

- Local web UI (slice 7a option B). Per-person budgets across projects (slice 5 open question 6), after teams-D. Lessons shared across projects (IDEA-15 open question).

# Scale and Hygiene Implementation Plan (backlog triage, plan SH)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Proposed 2026-11-05 (backlog triage, `2026-11-05-backlog-triage.md`).** Items marked [confirm] await the researcher.

> **Dependencies.** Best run last: it touches `services/check.py` and shared services that the other plans also touch. Tasks 1 and 7 may start at any time. Task 3 needs a ruling. Paths are relative to `platform/`.

**Goal:** Clear the parked findings that matter only at scale, or are cosmetic, tests only or dead code, so `docs/backlog-iterate.md` shrinks to what pilot use raises.

**Basis:** Every row of the triage table marked plan SH. A pilot of tens to hundreds of works does not need these, and the researcher intends to iterate during the pilot, so measure before tuning: Tasks 2 and 4 start by recording timings on the pilot project. Decision 92 item 11 is the one open acceptance miss.

**Projection:** Task 3 bumps by one if option (a) is chosen. Task 4 bumps once if a table is added. Others do not.

## Rulings made in this plan

1. **Decision 92's open miss [confirm].** `view_coverage` and `view_horizon` cost about 0.75 ms per live row, about 150 to 180 s at 2·10^5 rows against a 5 s bound, and `tests/test_coverage_scale.py` sets `LIMIT_SECONDS = 120`, so the test does not assert the bound. Decision 92 item 11 says a SQL path cannot simply equal the fold. Options: (a) project per-group key cells at fold time; (b) relax acceptance 17 to the measured bound for v1, stated in the spec; (c) cache per index state. **Recommended: (c) now, (a) only if a project reaches 10^4 live rows.** At pilot size the view takes seconds.
2. **`check` memo.** One per-call memo (the existing `call_memo`) carries the evidence snapshot, `gates_status`, region states and miner reports. Nothing persists between calls.

## Global Constraints

- No result changes: outputs are byte-identical before and after each task (golden), except Task 5's new findings.
- `services/check.py` is shared with most plans: rebase this plan over them, do not make them wait.

## Review Focus

1. A memo never outlives a call or crosses an index state.
2. A deleted helper had no caller (grep tests and `src`).

## File Structure

Modify `index/index.py`, `index/default.py`, `services/context.py`, `services/check.py`, `services/gates.py`, `services/gate_status.py`, `services/regions.py`, `services/miner_report.py`, `services/mining.py`, `services/view_coverage.py`, `services/horizon.py`, `services/relations.py`, `services/contributions.py`, `services/depth.py`, `services/exports.py`, `services/labels.py`, `services/terms.py`, `services/trace.py`, `services/prisma.py`, plus the tests listed.

### Task 1: Index reads

*Tier: critical (index).*

**Changes:** `Index.sync` fast path on unchanged file sizes and db identity (line 15a). `default_projection()` metadata built once per process (15c). `project_status` computes `human_queue`, agreement and audit once (11b, I18j).

- [ ] **Step 1:** Implement. **Step 2:** Commit `perf(index): sync fast path; projection metadata built once`.

**Tests (later):** a new event is seen; a replaced db is rebuilt; state hash unchanged.

### Task 2: `check` cost

*Tier: standard.*

**Changes:** Ruling 2 over lines 41, 47, 50, 71, 77, 86; `gates_status` can run four times a call. `final_outcomes` once in `prisma_flow` (I18m). Offset paging replaced in `_all_relations` (37). The whole-log read of `check` (I18l).

- [ ] **Step 1:** Measure on the pilot project. **Step 2:** Implement what shows. **Step 3:** Commit `perf(check): one snapshot and one gate read per call`.

**Tests (later):** findings identical; call count spies.

### Task 3: Evidence views

*Tier: critical. Ruling 1 [confirm].*

**Changes:** per ruling 1 (line 97). Set the scale test's bound to what the ruling states.

- [ ] **Step 1:** Implement. **Step 2:** Commit `perf(views): evidence views under the ruled bound`.

**Tests (later):** bound asserted on the real path.

### Task 4: Reads that load everything

*Tier: standard.*

**Changes, when measured:** the rows marked `SH T4` in the triage table (26).

- [ ] **Step 1:** Measure. **Step 2:** Implement what shows, one commit per service.

**Tests (later):** per change, the existing scale test at the real path.

### Task 5: Findings and small guards

*Tier: standard.*

**Changes:** `lead-decision-dropped`, `hypothesis-registration-dropped` (66, on `slice6_check.py`, after XP-B). Forged audit label finding (I18d). Count validators and negative guards (I18a, I18b). The other rows marked `SH T5` in the triage table (61 in all); the `dpa:` rows once deploy-A is merged, the `xpb:` rows once XP-B is. Decide 49c with R6. Line 34b: a CLI session id per process does not stop a human confirming their own definition; record it in the spec as a known limit.

- [ ] **Step 1:** Implement, grouped by file. **Step 2:** One commit per file group.

**Tests (later):** one case per guard.

### Task 6: Test gaps and dead code

*Tier: light.*

**Changes:** tests for lines 6b, 7, 11e, 12b, 17b, 18d, 19b, 20, 36b, 48, 120, I18e, I18g, I18h, `xpb:1`. Real dates in `views_b_helpers` (99). Comment at `trace._chase_assignment` (19c). Remove `GateAct.superseded`'s dead filter or set it (46), `entry_link_state`, `TitleRef.state`, unused `gates.weakest` and `autonomy_acts` once ruled (49b), wire or drop the `methods` hook (45b). Share `_rigor_mode` (seven copies) through `gates.py`. Merge `_off` and `_off_outline`, and `ORDER_STEP` (119). Fix `resolve_extraction`'s stale docstring. Split `trace.py` (2158 lines) and `prisma.py` by concern (I18n), last, as a move only. Register or delete the hand-search adapter (I18o).

- [ ] **Step 1:** Implement. **Step 2:** One commit per item group.

**Tests (later):** the added tests are the work.

### Task 7: Scale tests and the status lines

*Tier: light.*

**Changes:** `tests/test_watch_scale.py` (living-A Later L1), `tests/test_living_notice_scale.py` (living-D Later L1), as written there. Onion measurement on a real citation graph (93b). Update the stale status lines of `docs/backlog.md` from the triage table, and strike the lines of `docs/backlog-iterate.md` that the triage found resolved.

- [ ] **Step 1:** Implement. **Step 2:** Commit `test(living): scale tests`; commit `docs: backlog statuses from the triage`.

**Tests (later):** these are tests; run with `-m slow`.

## Self-review notes

- Task 5 is a list by design: each item is small, and the table holds the evidence. Split it by file when dispatching.

## Later (not v1)

None.

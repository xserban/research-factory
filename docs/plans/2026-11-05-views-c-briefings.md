# Onboarding Briefings and Agent Context Packs Implementation Plan (slice 7b, sub-plan V-C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** The whole plan is Later (spec v1 scope). `briefing.served` is a builder-owned system event (slice-M reconciliation item 3).

> **Dependencies.** V-A, V-B merged (`ViewMeta`, `Index.head`, `group_index`); W-B merged (released drafts, draft status counts). Slice 1 services (`question`, protocol and amendment reads, `prisma_flow`, `check`, `agent_view`, `methods_report`, `agent_methods`), 2E (`agent_evidence`), G2-D (`path`, confirmed ideas). Implements backlog IDEA-09; the human briefing may later be one panel of the slice-7a dashboard.

**Goal:** Generate, from events only, a project briefing for a person joining mid-way (a Markdown reading path) and a bounded JSON context pack for a new agent session, and record which pack each agent session received so that what an agent was told is reproducible.

**Architecture:** `services/briefing.py` builds a `Briefing` read model (sections below) from existing services; `briefing_agent_view` applies every existing agent filter; `views/briefing_render.py` renders Markdown; `briefing_get` (MCP) stores the agent pack as a text blob and records `briefing.served` (system actor). `index/briefings.py` projects served packs for `check` (`briefing-stale`) and `trace`.

**Tech Stack:** as V-A; no new dependency.

**Spec:** `docs/specs/slice-7b-views-writing.md` rulings 23, 24, 25; acceptance 14; R-133. Decisions 36, 37.14, 43, 48, 52 (withholding rules).

## Rulings made in this plan
1. **Sections [confirm].** (1) Question: raw goal, elements, non-goals, `Q@`. (2) Protocol: current `P@`, rigor mode, method profile, amendments (id, date, reason, semantic flag) newest first, deviations. (3) Gates: PRESS confirmation, calibration results per pass (human view only), agreement and audits (human view only), with dates. (4) Corpus: PRISMA counts, last search date per source. (5) Reading path: confirmed ideas in lineage order (W-A outline order rule), each with origin work (title, year, key) and up to 5 members, followed by the shortest `path` from the earliest origin to each most recent member (G2-D `path`, default filter). (6) Evidence: comparability groups with work counts (no values). (7) Open issues: `check` findings by code and count. (8) Pending human decisions: screening disagreements, `unsure`, unlabelled audits, inferred relations and ideas awaiting confirmation, unreviewed interpretations, unresolved manuscript citations (counts and ids). (9) Drafts: released drafts with status counts.
2. **Agent view.** Section 3 reduced to "passed / not passed" per gate with dates (no rates, no κ, no labels); section 7 via `check.agent_view`; no seed ids, no held-out recall, no audit rates (decisions 37.14, 43, 52); section 8 counts only.
3. **Bound.** `BRIEFING_MAX_CHARS = 40000` for the agent pack JSON; when exceeded, sections 5 and 8 are cut from the end (members, then paths, then ids), and `truncated` lists what was cut. The human briefing is not bounded.
4. **Recording.** `briefing_get` writes the pack as a blob and records `briefing.served` (`session`, `audience = agent`, `blob`, `as_of`), system actor. The same session receiving the same pack again records nothing new (idempotent on `(session, blob)`). `briefing-stale` (advisory) lists sessions whose last served pack has `as_of` earlier than a later protocol amendment or included-set change and that wrote agent events after that change.

## Global Constraints
- Derived only; every count computed (R-05); no library read; no document text (titles and bibliographic metadata only).
- `briefing_get` refused to sessions that joined any pass (decisions 43, 48).
- The pack is reproducible: rebuilding and re-running gives a byte-identical blob for the same log.
- TDD; `uv run pytest -m "not network and not slow"`; `mypy --strict`; ruff; coverage ≥ 90%.

## Review Focus
1. The agent pack of a project with held-out seeds, an audit and a calibration contains none of: seed ids, held-out recall, κ, audit error rate (Task 2, `test_agent_pack_withholds`).
2. `briefing.served` is idempotent per (session, blob) (Task 3, `test_served_idempotent`).
3. Truncation keeps sections 1–4 whole (Task 2, `test_truncation_order`).

## File Structure
- Create `services/briefing.py`, `views/briefing_render.py`, `index/briefings.py`; Modify `model/views.py`, event catalog, `index/default.py`, `services/check.py`, `services/trace.py`, `mcp/server.py`, `cli/main.py`.
- Tests: `tests/test_briefing.py`, `tests/test_briefing_agent.py`, `tests/test_briefing_served.py`, `tests/test_briefing_cli_mcp.py`.

## Self-review notes
- A briefing names no person's performance; supervision metrics are IDEA-10 (slice 5).
- `briefing-stale` is advisory; acting on it (re-serving a pack) is the session's choice.

## Later (not v1)

Moved here by the v1 cut of 2026-11-04 (decision 74); built after the v1 plans of the build order (`2026-11-05-build-order.md`), in the order listed. Task text is unchanged; references to "Task N" inside a moved task use the plan's original numbering.

### Later L1 (was Task 1): Briefing builder (human view)

*Tier: standard.*

**Files:** Create `services/briefing.py`; Modify `model/views.py`; Test `tests/test_briefing.py`.

**Interfaces:**
- Produces (`model/views.py`): `Briefing(meta: ViewMeta, question, protocol, gates, corpus, reading_path: list[PathEntry], evidence: list[GroupSummary], issues: dict[str, int], pending: dict[str, list[str]], drafts: list[DraftBrief], truncated: list[str] = [])` with sub-models named after ruling 1.
- Produces (`services/briefing.py`): `build_briefing(project: Project) -> Briefing`.

- [ ] **Step 1: Tests.** `test_sections_from_fixture` (each section against hand values); `test_amendments_newest_first`; `test_reading_path_in_lineage_order`; `test_no_values_in_evidence_section`; `test_deterministic_across_rebuilds`; `test_empty_project_briefing` (no protocol yet: sections present, empty, notices).
- [ ] **Step 2–4.** **Step 5:** Commit `feat(briefing): project briefing builder`.

### Later L2 (was Task 2): Agent view and bound

*Tier: critical (held-out discipline).*

**Files:** Modify `services/briefing.py`; Test `tests/test_briefing_agent.py`.

**Interfaces:**
- Consumes: `check.agent_view`, `agent_methods`, `agent_evidence`, `agent_trace` rules.
- Produces: `BRIEFING_MAX_CHARS = 40000`; `briefing_agent_view(b: Briefing) -> Briefing`; `agent_pack(project: Project) -> str` (JSON, ≤ bound).

- [ ] **Step 1: Tests.** `test_agent_pack_withholds` (Review Focus 1); `test_gates_reduced_to_passed`; `test_truncation_order` (Review Focus 3); `test_pack_within_bound`; `test_pack_deterministic`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(briefing): agent context pack with withholding`.

### Later L3 (was Task 3): Recording served packs; check and trace

*Tier: standard.*

**Files:** Create `index/briefings.py`; Modify event catalog, `index/default.py`, `services/briefing.py`, `services/check.py`, `services/trace.py`; Test `tests/test_briefing_served.py`.

**Interfaces:**
- Produces: event `briefing.served` (schema 1); table `briefings_served`; `serve_pack(project: Project, *, session: str) -> tuple[str, str]` (blob ref, pack); `served_for(project, session) -> list[ServedRow]`; check finding `briefing-stale`; `trace` gains kind `briefing` (identified by the served pack's blob ref) whose downstream nodes are the sessions it was served to and their `briefing.served` events.

- [ ] **Step 1: Tests.** `test_served_records_session_and_as_of`; `test_served_idempotent` (Review Focus 2); `test_briefing_stale_after_amendment`; `test_trace_briefing_lists_sessions`; `test_rebuild_identical`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(briefing): record served context packs`.

### Later L4 (was Task 4): Rendering, MCP tool, CLI

*Tier: standard.*

**Files:** Create `views/briefing_render.py`; Modify `mcp/server.py`, `cli/main.py`; Test `tests/test_briefing_cli_mcp.py`.

**Interfaces:**
- Produces: `briefing_markdown(b: Briefing) -> str` (reading path as a numbered list; amendments as a table; pending decisions with the CLI command that resolves each kind).
- MCP: `briefing_get(project) -> dict` (`{"blob": …, "pack": {...}}`; refused to pass sessions).
- CLI: `factory briefing [--agent] [--format md|json] [--out PATH]` (`--agent` prints the agent pack without recording; only the MCP tool records).

- [ ] **Step 1: Tests.** Tool list pinned; pass session refused; CLI Markdown contains each section heading; `--agent` output equals `agent_pack`; CLI writes no event.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(briefing): briefing tool and command`.

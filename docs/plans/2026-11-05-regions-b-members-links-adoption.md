# Regions B: Member Proposals, Links, Overlap, Adoption and Agent Tools — Implementation Plan (slice 3d)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** v1 cut: the adoption task moved to Later (cross-project; spec v1 scope); the former Task 3 is Later L1, former Tasks 4 and 5 are now Tasks 3 and 4, and Review Focus item 3 applies only when the Later task is built. Bumps `PROJECTION_VERSION` by one from the value it finds.

> **Built 2026-11-05 (v1 tasks 1 to 4; rulings in decision 88).** Tasks 1 and 2 share one commit; Task 3 adds the withheld-region guard (backlog-iterate, Regions-B). Later L1 (adoption) is not built.

> **Dependencies.** Regions-A merged. The read interface of Task 3 (`regions_of`, `region_members`, `overlap`) is the one IDEA-04 (cross-project suggestions), slice 4 (alerts per region) and slice 6 (cross-region matching) are expected to consume; changing it later is an amendment to this plan.

**Goal:** Let agents propose regions and individual members with verified bases and let the researcher decide them; declare and verify links between regions; compute overlap and differences; adopt a reviewed snapshot from another project read-only; expose all of it through MCP and the CLI with `check` and `trace`.

**Architecture:** Proposal and decision events in `model/regions.py`; basis verification reuses `document/quotes.py::quote_in_element` on the pinned conversion and the edge tables of 3b/3c; overlap and diff are SQL over `region_members` or member blobs. Adoption reads the source project read-only through a second `Project` opened without a session (no write path) and copies the member blob by hash.

**Tech Stack:** as Regions-A.

**Spec:** `docs/specs/slice-3d-regions-import.md` rulings 6, 9–11; acceptance 4, 6, 17; MCP tools, CLI and check findings (region part).

## Rulings made in this plan

1. **Basis kinds.** `QuoteBasis(work_id, conversion_id, anchor, quote)` verified verbatim in the anchored element of that work's pinned conversion; `EdgeBasis(edge_id)` where the edge is a live `graph_edges` row (stated or confirmed) or a live `concept_uses` row incident to the proposed member and to a current member of the region.
2. **Decisions.** `add` (from a proposal or directly by the researcher), `remove` (a member selected by rules), `reject` (a proposal). Decisions apply from the next snapshot and enter the version hash (Regions-A ruling 2).
3. **Links.** `subregion-of(child R@, parent R@)` is refused at write time unless child members ⊆ parent members; later versions are re-checked by `check`. `related(R@a, R@b, note)` has no verification.
4. **Adoption.** `factory regions adopt --from PROJECT_PATH R@` (CLI only): the source must be a project directory on this machine, the version `reviewed`, the blob present and its hash equal to `members_hash`. The adopting project records `region.adopted` and stores the blob in its own `blobs/`. Adopted versions appear in `regions_of` with `adopted_from`.
5. **MCP pagination.** `region_query(members)` at most 500 per call with an offset; `regions_of` at most 100 regions.

## Global Constraints

- As Regions-A. No MCP tool decides a member, reviews, links or adopts. Pass sessions are refused every tool of this plan (decisions 37, 43, 48).
- Adoption never writes to the source project and never changes the adopting corpus.

## Review Focus

1. A quote basis with one character changed is rejected and nothing is written (Task 1, `test_member_quote_must_verify`).
2. A proposal never appears in a snapshot until a human adds it (Task 1, `test_proposal_absent_until_added`).
3. Adoption with a tampered blob, or of an unreviewed version, is refused; the adopting project's PRISMA is unchanged (Task L1 (Later), `test_adoption_checks`).
4. A pass session calling any region tool is refused (Task 4, `test_region_tools_refuse_pass_sessions`).

## File Structure

- Modify `model/regions.py`, `services/regions.py`, `index/regions.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`, `services/check.py`, `services/trace.py`; create `plugin/skills/rf-regions/SKILL.md`.
- Tests: `test_region_members.py`, `test_region_links.py`, `test_region_adoption.py`, `test_region_queries.py`, `test_region_mcp.py`, `test_region_check_trace.py`.

---

### Task 1: Member proposals and decisions

*Tier: critical (verification, R-51).*

**Files:** Modify `model/regions.py`, `services/regions.py`, `index/regions.py`; Test `tests/test_region_members.py`.

**Interfaces:**
- Consumes: `quote_in_element`, pinned conversion lookup (`services/conversions.py`), `graph_edges`, `concept_uses`.
- Produces: `class RegionMemberProposed(StrictModel)`: `proposal_id` (`rmp_<ULID>`), `region_id`, `member_type`, `member`, `basis: QuoteBasis | EdgeBasis`, `note: str | None` (≤ 300, agent-note, never counted); `class RegionMemberDecided(StrictModel)`: `region_id`, `member_type`, `member`, `decision: Literal["add", "remove", "reject"]`, `proposal_id: str | None`, `rationale`; `propose_member(project, actor, region_id, member_type, member, basis, note=None) -> str`; `decide_member(project, actor, region_id, member_type, member, decision, *, rationale, proposal_id=None) -> None` (human only); `pending_proposals(project, region_id) -> list[RegionMemberProposed]`. `snapshot_region` passes live adds and removes to `evaluate`.

- [ ] **Step 1: Tests.** `test_member_quote_must_verify` (Review Focus 1), `test_edge_basis_must_touch_region`, `test_proposal_absent_until_added` (Review Focus 2), `test_agent_cannot_decide`, `test_remove_overrides_rule`, `test_reject_closes_proposal`, `test_decisions_enter_version_hash`, `test_duplicate_proposal_idempotent`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(regions): member proposals and human decisions`.

### Task 2: Links, overlap and diff

*Tier: standard.*

**Files:** Modify `model/regions.py`, `services/regions.py`, `index/regions.py`; Test `tests/test_region_links.py`, `tests/test_region_queries.py`.

**Interfaces:**
- Produces: `class RegionLinked(StrictModel)`: `link_type: Literal["subregion-of", "related"]`, `source: str` (R@), `target: str` (R@), `note: str | None`; `link_regions(project, actor, link_type, source, target, note=None) -> None` (human only; ruling 3); `class Overlap(StrictModel)`: `a`, `b`, `shared: dict[MemberType, int]`, `only_a`, `only_b`, `jaccard: dict[MemberType, Ratio]`; `overlap(project, a: str, b: str) -> Overlap`; `diff(project, a: str, b: str, *, offset=0, limit=500) -> RegionDiff` (added and removed members, paginated); `regions_of(project, member_type, member) -> list[RegionMembership]` (`region_id`, `version`, `review_state`, `adopted_from: str | None`, `basis`).

- [ ] **Step 1: Tests.** `test_subregion_verified_at_write`, `test_subregion_violation_found_later`, `test_overlap_counts_and_jaccard`, `test_diff_paginated_deterministic`, `test_regions_of_uses_index` (SQL capture: one indexed read).
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(regions): links, overlap, diff and regions_of`.

### Task 3: MCP tools and skill `rf-regions`

*Tier: standard.*

**Files:** Modify `mcp/server.py`; create `plugin/skills/rf-regions/SKILL.md`; Test `tests/test_region_mcp.py`.

**Interfaces:**
- Produces MCP: `region_propose(name, kind, definition, rules, facet=None, region_id=None)` → `define_region` with the agent actor; `region_propose_member(region_id, member_type, member, basis, note=None)`; `region_snapshot(region_id)`; `region_status(region_id=None)` (all regions when none, paginated); `region_query(query: Literal["members", "regions_of", "overlap", "diff"], …)`. Every agent-written event carries model, skill (`rf-regions@<hash>`) and `input_blob`. `import` rules with `part = "all"` are refused to agents (held-out, spec ruling 23).
- Skill: how to write a short definition, choose rule kinds, prefer rules over member lists, propose members only with a verified quote or edge, never review.

- [ ] **Step 1: Tests.** `test_region_tools_refuse_pass_sessions` (Review Focus 4), `test_agent_import_rule_all_refused`, `test_agent_events_carry_provenance`, `test_no_decision_tool_exists` (the tool list has no review, decide, link or adopt tool), `test_members_paginated`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(mcp): region tools and rf-regions skill`.

### Task 4: Check, trace and CLI completion

*Tier: standard.*

**Files:** Modify `services/check.py`, `services/trace.py`, `cli/main.py`; Test `tests/test_region_check_trace.py`.

**Interfaces:**
- Produces findings: `region-unreviewed`, `region-drift` (with counts), `region-subregion-violated`, `region-focus-slot-missing`, `region-adoption-outdated`, `region-member-proposal-pending`. Severities: advisory in every mode (regions are not evidence), except `region-subregion-violated` (warning).
- Produces trace: `reg_…` and `R@…` → definition (author, provenance), rules, decisions, review history, adoption source; from a member id, the regions containing it and the basis (rule index or decision); forward from a work, its regions.
- CLI: `factory regions add|remove|reject REG MEMBER --rationale`, `factory regions link --subregion-of|--related`, `factory regions export R@ [--json]` (ids, types, basis; no text).

- [ ] **Step 1: Tests.** One per finding in a constructed case; `test_trace_member_basis`; `test_export_byte_identical_across_rebuilds`; `test_findings_carry_no_text`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(check): region findings, trace and export`.

**Verification for the plan:** `cd platform && uv run pytest -m "not network and not slow" && uv run mypy --strict src && uv run ruff check`.

## Later (not v1)

Moved here by the v1 cut of 2026-11-04 (decision 74); built after the v1 plans of the build order (`2026-11-05-build-order.md`), in the order listed. Task text is unchanged; references to "Task N" inside a moved task use the plan's original numbering.

### Later L1 (was Task 3): Adoption from another project

*Tier: standard.*

**Files:** Modify `model/regions.py`, `services/regions.py`, `index/regions.py`, `cli/main.py`; Test `tests/test_region_adoption.py`.

**Interfaces:**
- Produces: `class RegionAdopted(StrictModel)`: `source_project: str` (slug), `source_region: str`, `version: str`, `members_blob: str`, `members_hash: str`, `counts`; `adopt_region(project, actor, source_root: Path, version: str) -> None` (human only; ruling 4); `adoption_outdated(project) -> list[tuple[str, str]]` (adopted version, newer reviewed version in the source when readable).

- [ ] **Step 1: Tests.** `test_adoption_checks` (Review Focus 3: tampered blob, unreviewed version, missing source all refused), `test_adopted_members_in_regions_of`, `test_adoption_changes_no_corpus_count`, `test_outdated_reported_when_source_has_newer`, `test_source_project_not_written` (mtime and event-file listing unchanged).
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(regions): adopt a reviewed region from another project`.

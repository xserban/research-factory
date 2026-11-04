# Matching, Contradiction Finder and Gap Finder Implementation Plan (slice 6, sub-plan H-B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Status: draft — rulings recommended; awaiting the researcher's review before any build.

> **Dependencies.** H-A merged (Interfaces consumed exactly: `resolve_property`, `effective_card_props`, `card_view`, `CardPropRow`, `vocabulary_version`); plan 2E merged (`evidence_report`, `EvidenceReport`, `GroupReport.method_conflicts`, `EvidenceRow.regime`, `group_id`, `final_rows`); plan 2D (`live_claims`). May run in parallel with H-C. When slice 3d lands, the transfer test of Task 2 gains a region branch; the function signature already takes a `scope` argument. When slice M lands, the three builders declare their inputs through its builder contract without changing outputs.

**Goal:** Compute, without judgement, which method cards fit a problem description (and which of them would be a transfer from outside the corpus), which reported results conflict within a comparability group and under which differing conditions, and which method × condition cells of the corpus are empty; and let an agent propose claim-level contradictions that only a human confirms.

**Architecture:** Pure rule functions in `factory/hypotheses/match.py`; the builder `services/matching.py` streams candidate cards from `card_props` by required property keys (no full-card load). `services/finders.py` derives numeric conflicts from the evidence report group by group and counts gap cells with SQL `GROUP BY` over the extraction projection after a grid-size check. Claim contradictions are a small event family `contradiction.*` in `model/findings.py`, folded by `index/findings.py`. Every builder output carries a deterministic key over its inputs.

**Tech Stack:** as plan D; no new dependencies.

**Spec:** `docs/specs/slice-6-hypotheses.md` rulings 6, 7, 9, 10; Design "Matching (builder)", "Finders (builders)"; events `contradiction.*`; MCP `match_query`, `finder_contradictions`, `finder_gaps`, `contradiction_propose`; CLI `contradictions`; acceptance 5–7. `01-rigour.md` R-05, R-51.

## Rulings made in this plan (recommended; [confirm])

1. **Required properties.** A problem description's required properties are its effective stated or confirmed assertions on properties with `applies_to ∈ {problem, both}`. A method card is a candidate when it has at least one effective assertion on a required key. [confirm]
2. **Rule semantics.** `equal`: method value equals the problem value (enum, bool); `covers`: the method's set contains the problem's set; `at-most`: method number ≤ problem number (same unit family, canonical decimals); `at-least`: ≥. A method assertion absent → `unknown`; present but failing → `conflicting`. [confirm]
3. **`match_key`.** `sha256` of the canonical JSON of (problem card id with its effective assertion ids, the candidate cards' effective assertion ids, `V@`, `MATCH_BUILDER_VERSION = "1"`), first 16 hex digits; one key per query result, plus a per-row `row_key = sha256(match_key, card_id)[:16]`. [confirm]
4. **Conflict tolerance.** `CONFLICT_RELATIVE_TOLERANCE = Decimal("0.01")` against the larger magnitude, overridable by `hypothesis_plan.conflict_tolerance` once H-C adds that section; values within it are not conflicts. [confirm]
5. **Gap axes.** Rows axis: `method` (normalised method name of final independent rows) or `card` (method cards); columns axis: one declared comparability key of the evidence schema, or a property key of cards. Limit `GAP_MAX_CELLS = 10_000`. [confirm]
6. **Claim contradictions.** A proposal names two distinct live refs among claims (`clm_`) and contribution items (`ext_` rows of scope contribution) from different works, each with its stored quote; a note ≤ 500 characters is required. Only a human confirms or rejects. A proposal for the same unordered pair is idempotent. [confirm]

## Global Constraints

- Builders are read-only, deterministic and paged; they never write events. Outputs carry ids, counts, canonical values and stored quotes only.
- The platform never calls a model; contradiction status is never set by an agent.
- No query loads all cards, rows or groups into memory at once: matching streams by key; conflicts iterate group by group; gaps aggregate in SQL.
- Business logic in `services/`; rule functions pure; `mcp/`, `cli/` parse and format.
- TDD; `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff; coverage ≥ 90% for `services/` and `model/`.

## Review Focus

1. A card with no assertion on any required property is never read (Task 2, `test_query_touches_only_candidates`, counting SQL statements through a SQLAlchemy event hook).
2. A conflict between a copied row and the row it copies is not reported (Task 3, `test_copied_rows_never_conflict`).
3. The gap grid size is checked before any aggregate query runs (Task 5, `test_grid_too_large_refused_before_query`).
4. An evidence-report byte comparison with contradiction proposals present (Task 4, `test_evidence_report_unchanged_by_contradictions`).

## File Structure

- Create `factory/hypotheses/match.py`, `services/matching.py`, `services/finders.py`, `model/findings.py`, `index/findings.py`.
- Modify `events/catalog.py`, `index/default.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- Tests: `test_match_rules.py`, `test_matching.py`, `test_finder_conflicts.py`, `test_contradictions.py`, `test_finder_gaps.py`, `test_mcp_findings.py`, `test_cli_findings.py`; helper `tests/finder_helpers.py` (H-A card helpers plus a plan-E project with constructed groups: a two-work conflict with a differing `regime` key, a copied row, a within-tolerance pair, and a sparse method × dataset grid).

---

### Task 1: Pure match rules

*Tier: standard.*

**Files:** Create `factory/hypotheses/match.py`; Test `tests/test_match_rules.py`.

**Interfaces:**
- Consumes: `PropertyDef`, `MatchRule`, `PropertyKind`.
- Produces: `Outcome = Literal["satisfied", "conflicting", "unknown"]`; `rule_outcome(defn: PropertyDef, problem_value: tuple[str, ...] | Decimal | bool, method_value: tuple[str, ...] | Decimal | bool | None) -> Outcome` (ruling 2); `order_key(conflicting: int, satisfied: int, unknown: int, card_id: str) -> tuple[int, int, int, str]` (spec ruling 6: `(conflicting, -satisfied, unknown, card_id)`); `MATCH_BUILDER_VERSION = "1"`; `match_key(problem: tuple[str, Sequence[str]], cards: Sequence[tuple[str, Sequence[str]]], vocab: str) -> str` (ruling 3).

- [ ] **Step 1: Tests.** Parametrised `test_rule_outcome` (each rule × satisfied, conflicting, unknown); `test_at_most_uses_canonical_decimals` (`Decimal("1e9")` vs `"1000000000"`); `test_order_is_lexicographic_without_weights`; `test_match_key_independent_of_input_order`; `test_match_key_changes_with_assertion_ids_and_vocab`.
- [ ] **Step 2:** `uv run pytest -m "not network and not slow" tests/test_match_rules.py` — FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(matching): pure match rules, ordering and key`.

### Task 2: Matching builder with transfer flag

*Tier: critical (the basis of transfer hypotheses).*

**Files:** Create `services/matching.py`; Test `tests/test_matching.py`.

**Interfaces:**
- Consumes: Task 1; `card_view`, `effective_card_props`, `resolve_property`, `vocabulary_version`, `idea_view` (effective members), the screening outcome projection (`INCLUDED` works at the last declared stage, as G1 `included_works`), `grouped_rows` (groups holding final rows of member works).
- Produces: `MatchRow(StrictModel)`: `row_key`, `card_id`, `subject`, `satisfied: list[str]`, `conflicting: list[str]`, `unknown: list[str]`, `transfer: bool`, `members_included: list[str]`, `evidence_groups: list[str]`; `MatchPage(StrictModel)`: `match_key`, `problem_id`, `vocabulary_version`, `statuses: list[str]`, `rows: list[MatchRow]`, `next_after: str | None`, `candidates: int`; `match(project, problem_id: str, *, include_inferred: bool = False, transfer_only: bool = False, scope: Literal["project"] = "project", limit: int = 50, after: str | None = None) -> MatchPage`. Transfer (spec ruling 7): a card's subject is a work or an idea; `transfer = True` when none of its member works is `INCLUDED` in this project. `include_inferred` widens both sides and labels the page `statuses = ["stated", "confirmed", "inferred"]`.

- [ ] **Step 1: Tests.**
```python
def test_expected_sets_and_order(project):                 # acceptance 5
    page = match(project, PROBLEM)
    assert [r.card_id for r in page.rows] == [C_ALL_OK, C_ONE_UNKNOWN, C_ONE_CONFLICT]
    assert page.rows[2].conflicting == ["pr:memory-scaling"]
def test_inferred_excluded_by_default(project): ...
def test_transfer_flag_from_included_members(project): ...  # imported card for a non-included idea -> transfer
def test_match_key_changes_when_assertion_superseded(project): ...
def test_query_touches_only_candidates(project): ...        # Review Focus 1
def test_paging_is_stable(project): ...
def test_problem_card_required(project): ...                # a method card id -> structured error `problem_id`
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement with one SQL query over `card_props` filtered by the required keys, grouped by card in Python per page. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(matching): problem-to-card matching builder with transfer flag`.

### Task 3: Numeric conflict finder

*Tier: standard.*

**Files:** Create `services/finders.py` (conflict part); Test `tests/test_finder_conflicts.py`.

**Interfaces:**
- Consumes: `evidence_report(project, ...)` (plan-2E signature, unchanged), `GroupReport.method_conflicts`, `EvidenceRow` (`row_key`, `work_id`, `value.canonical`, `value.copy_marker`, `regime`).
- Produces: `ConflictPair(StrictModel)`: `group_id`, `method`, `variant`, `row_a`, `row_b`, `work_a`, `work_b`, `value_a`, `value_b` (canonical decimal strings), `relative_difference` (string, 4 places), `differs_in: list[str]` (sorted `regime` keys with different values or present on one side only), `trace_ids: tuple[str, str]`; `ConflictPage(conflicts: list[ConflictPair], groups_scanned: int, next_after: str | None)`; `find_conflicts(project, *, group_id: str | None = None, limit: int = 50, after: str | None = None) -> ConflictPage`. Pairs are formed from the rows of each `MethodConflict`, across different works only, excluding rows whose value cell is a copy (`copy_marker`) and pairs within tolerance (ruling 4); ordered by `(group_id, method, row_a, row_b)`.

- [ ] **Step 1: Tests.** `test_conflict_lists_both_rows_and_differing_regime` (acceptance 6), `test_copied_rows_never_conflict` (Review Focus 2), `test_within_tolerance_not_conflict`, `test_same_work_rows_not_paired`, `test_group_filter_and_paging`, `test_no_document_text_in_output`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(finders): numeric conflicts with differing conditions`.

### Task 4: Claim contradiction proposals

*Tier: critical (human-only decision path).*

**Files:** Create `model/findings.py`, `index/findings.py`; Modify `events/catalog.py`, `index/default.py`, `services/finders.py`; Test `tests/test_contradictions.py`.

**Interfaces:**
- Consumes: `live_claims`, the contribution rows view (`scope=CONTRIBUTION`), `CLAIM_ID_RE`, `EXTRACTION_ID_RE`.
- Produces (`model/findings.py`): `CONTRADICTION_ID_RE = rf"^ctr_{ULID_RE}$"`; `ContradictionInput(ref_a: str, ref_b: str, note: str (1..500))`; payloads `ContradictionProposed(contradiction_id, ref_a, ref_b, work_a, work_b, quote_a, quote_b, note)` (refs stored in sorted order), `ContradictionDecided(contradiction_id, decision: Literal["confirm", "reject"], rationale)`; types `contradiction.proposed`, `contradiction.decided`.
- Produces (`index/findings.py`): `contradictions(contradiction_id pk, ref_a, ref_b, work_a, work_b, decision, decision_event_id, event_id)`, unique `(ref_a, ref_b)`; decisions fold only for human actors.
- Produces (`services/finders.py`): `propose_contradiction(project, actor, item: ContradictionInput) -> tuple[str, bool]` (id, written; ruling 6; reasons `ref-unknown`, `ref-not-live`, `same-work`, `same-ref`); `decide_contradiction(project, actor, contradiction_id, decision, rationale) -> str` (human only); `ContradictionView(contradiction_id, ref_a, ref_b, work_a, work_b, state: Literal["inferred", "confirmed", "rejected", "stale"], event_id)` (stale when either ref is no longer live); `list_contradictions(project, *, states=("confirmed",)) -> list[ContradictionView]`.

- [ ] **Step 1: Tests.** `test_propose_stores_quotes_and_sorted_refs`, `test_idempotent_unordered_pair`, `test_refusals_each_reason`, `test_agent_cannot_decide`, `test_projector_ignores_agent_decisions`, `test_superseded_claim_stales_contradiction`, `test_default_list_only_confirmed`, `test_evidence_report_unchanged_by_contradictions` (Review Focus 4: `evidence_report` JSON byte-identical with and without proposals).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(finders): claim contradiction proposals with human decisions`.

### Task 5: Gap finder

*Tier: standard.*

**Files:** Modify `services/finders.py`; Test `tests/test_finder_gaps.py`.

**Interfaces:**
- Consumes: the extraction projection (`extraction_rows` with scope evidence, final status as `final_rows` defines it; implemented as an SQL aggregate over the same filter, with a test that its counts equal a Python count over `final_rows` on fixtures), `card_props`, the current protocol (`P@`, `extraction_schema.comparability_keys`), the latest search-run date, the included-work count.
- Produces: `GapAxis = Literal["method", "card"] | str` (a comparability key or `pr:` key); `GapCell(row: str, column: str, count: int)`; `CorpusDefinition(protocol_id, last_search: str | None, included_works: int)`; `GapReport(StrictModel)`: `rows_axis`, `columns_axis`, `filters: dict[str, str]`, `cells: int`, `empty: list[GapCell]`, `filled: int`, `corpus: CorpusDefinition`, `statement: str` (fixed: "Not found in this corpus (protocol {P@}, {n} included works, last search {date}); absence here is not absence in the literature."), `gap_key`; `find_gaps(project, *, rows_axis: GapAxis, columns_axis: str, filters: Mapping[str, str] = {}) -> GapReport`. Grid size = distinct row values × distinct column values, counted with two `COUNT(DISTINCT …)` queries before the aggregate; above `GAP_MAX_CELLS` → `ValidationFailed` (`filters`, `grid-too-large`, with the size).

- [ ] **Step 1: Tests.** `test_empty_cells_with_corpus_definition` (acceptance 7), `test_counts_equal_python_count_over_final_rows`, `test_grid_too_large_refused_before_query` (Review Focus 3; acceptance 7), `test_unknown_axis_refused`, `test_card_axis_uses_effective_assertions`, `test_gap_key_deterministic`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(finders): bounded gap finder with corpus definition`.

### Task 6: MCP tools and CLI

*Tier: Haiku implement and review.*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`, `tests/test_plugin.py`; Test `tests/test_mcp_findings.py`, `tests/test_cli_findings.py`.

**Interfaces:**
- MCP: `match_query(project, problem_id, include_inferred=False, transfer_only=False, limit=50, after=None)` -> `MatchPage`; `finder_contradictions(project, group_id=None, limit=50, after=None)` -> `ConflictPage` with the confirmed `ContradictionView`s appended under `claims`; `finder_gaps(project, rows_axis, columns_axis, filters={})` -> `GapReport`; `contradiction_propose(project, ref_a, ref_b, note, role, model, skill)` -> id. All refused to pass sessions. No MCP tool reaches `decide_contradiction`.
- CLI: `factory match PROBLEM [--inferred] [--transfer]`, `factory finders conflicts [--group G]`, `factory finders gaps --rows method|card --columns KEY [--filter K=V]…`, `factory contradictions list [--state S]…|confirm CTR|reject CTR` (with `--rationale`).

- [ ] **Step 1: Tests.** Tool list pinned; read tools return the service models unchanged; `contradiction_propose` with a `decision` argument is a structured error; CLI prints the gap statement and the conflict `differs_in` column; `contradictions confirm` writes a human event.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(findings): MCP read tools, contradiction proposal, CLI`.

## Self-review notes

- **Spec coverage.** Rulings 6, 7, 9, 10; acceptance 5 (Task 2), 6 (Tasks 3–4), 7 (Task 5). The skill text for using these tools is part of `rf-ideate` (H-C).
- **Types used later.** `MatchPage`, `MatchRow`, `match`, `ConflictPair`, `find_conflicts`, `ContradictionView`, `list_contradictions`, `GapReport`, `find_gaps`, `CONTRADICTION_ID_RE`, keys `match_key`, `row_key`, `gap_key` (lead triggers in H-C).
- **Tiers.** Task 2, 4 critical; 1, 3, 5 standard; 6 Haiku.

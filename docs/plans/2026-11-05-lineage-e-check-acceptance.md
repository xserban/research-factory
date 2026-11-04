# Lineage Check, Trace, Separation, Acceptance and Pilot Implementation Plan (slice 3b, sub-plan G2-E)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: ready — rulings adopted 2026-11-04; depends on G1 (slice 3a) being built.** G1 ruling 14 is adopted as option (b): the local-library scan of Task 3 allows in events the parsed reference fields and `entry_sha256` (no raw entry text), plus verified quotes and marker tokens.

> **Reconciled with the code 2026-11-04 (overnight).** Consumes G2-A–D per their reconciled plan texts and G1 Task 8 per the reconciled G1 plan (not yet built). Changes: the check severity table is `LEVELS` and the agent-view rate filter `_RATE_CODES` (`services/check.py`); the G1 trace kinds are named (`reference_extraction` for `rex_…`, `snowball_round` for `snw_…`, pinned in G1 Task 8); G2-D is read through `graph_node` / `iter_edges` (no whole-graph load); the acceptance module is marked `slow`.

> **Dependencies.** G2-A to G2-D merged (Interfaces consumed exactly); G1 merged, including its `check` and `trace` extensions (`rex_`, `snw_` node kinds). Task 4 needs the linear-attention pilot project with G1 extraction run and the researcher available.

**Goal:** Close slice 3b: `check` reports missing, stale and unconfirmed lineage items, `trace` resolves any edge to the question, the evidence table is proven untouched by contribution rows, the spec's acceptance criteria run as one test module, and the pilot reads a sourced lineage path.

**Architecture:** Read-only extensions of `services/check.py` and `services/trace.py` over the G2-A–D services; an acceptance module built from hand-written documents (no network); a pilot run carried out by the researcher and Claude with the shipped tools, recording ids and counts only.

**Tech Stack:** as plan D; no new dependencies.

**Spec:** `docs/specs/slice-3b-lineage.md` "Check findings", User flow 7, acceptance 1–19 (7, 16, 17, 18 owned here; the rest re-asserted end to end), Rigour requirements, "Proposed sub-plans" (G2-E). `01-rigour.md` R-01, R-02, R-05, R-43, R-47; proposed R-xx(e)–(g).

## Rulings made in this plan

Rulings marked **[adopted 2026-11-04]** were Adopted 2026-11-04 (researcher's standing approval of the recommendation); Task 5 records them in the *Proposed* decision when built.

1. **Finding severities (exploratory, pilot, systematic). [adopted 2026-11-04]** `contribution-missing-extraction` (warning, warning, error); `contribution-stale` (warning ×3); `contribution-schema-missing` (none, warning, error; raised only when the project has a G1 extraction or any `relation.*`/`idea.*` event); `relation-stale` (warning ×3); `relation-unconfirmed` (warning ×3, advisory, one finding with the count); `relation-uncited-base` (warning ×3); `relation-without-basis` (error ×3); `idea-unconfirmed` (warning ×3); `graph-extraction-missing` (warning ×3); `contribution-error-ceiling` (none, warning, error; the agent view states no rate, as `extraction-error-high`).
2. **Definitions.** `contribution-missing-extraction`: a population work whose pass-A contribution unit is not `current`. `contribution-stale`: works with live contribution rows in `stale_extractions(scope=CONTRIBUTION)`. `relation-stale`: live relations with effective `stale`. `relation-uncited-base`: live, not rejected relations flagged `uncited-base`. `relation-without-basis`: a live relation with proposal status `stated` or a `confirm` decision whose `basis_item` names no recorded contribution row, or whose (`reference_extraction_id`, `cited_entry`) has no `reference_links` row (a broken chain, only constructible by writing events outside the services). `idea-unconfirmed`: live ideas in state `proposed`. `graph-extraction-missing`: works with live contribution items and no current G1 extraction on the pinned conversion. `contribution-error-ceiling`: `contribution_audit_report(...).above_ceiling`. Refs are work, relation or idea ids; messages never carry document text.
3. **Trace node kinds.** `relation` (`rel_…`), `idea` (`ida_…`), `cites` (`cit:<rex_id>:<ordinal>`), and `quote` (`<ext_id>/quote`, the verified quote of a contribution row as its label). Back from a relation: the decision (in the relation's label: proposal status, decision, effective status), the basis `extraction` node (plan D: anchor → conversion → document → retrieval attempt → work → screening decisions → protocol → question) with its `quote` child, the G1 extraction `rex_…` (G1 kind `reference_extraction`) for `cited_entry`, the source work and the target (work or idea). Forward from an `extraction` node: relations using it as basis and ideas using it as `name_item`. Back from an idea: its `name_item`, origin, members and merges. `trace` and `agent_trace` stay refused to pass sessions.

## Global Constraints

- All G2-A–D constraints hold. Check and trace are read-only; they write no event.
- No document text in any finding, trace label (except the `quote` node's verified quote, already in events) or pilot record.
- The pilot record holds ids, statuses and computed counts only; no literature text enters any tracked file; `docs/pilot/heldout-seeds.md` is never opened.
- Every earlier acceptance module (slice 1, plans A–E, G1) passes unedited.
- TDD for Tasks 1–3; `mypy --strict`, ruff; coverage >= 90% for `services/` and `model/`; `-m "not network and not slow"` during tasks; `tests/test_acceptance_lineage.py` is marked `slow` and run with `-m "not network"` in Task 3 Step 3.

## Review Focus

1. A project that never declares `contribution_schema` and never runs G1 gets none of the ten findings in any mode (Task 1, `test_untouched_project_has_no_lineage_findings`).
2. A relation whose basis item was superseded produces `relation-stale`, not `relation-without-basis`; only a hand-written event naming an unknown row produces the latter (Task 1, `test_stale_is_not_broken_chain`).
3. `trace` of a `cit:` edge whose G1 extraction was superseded still resolves to the old extraction, conversion and document (history stays traceable) (Task 2, `test_trace_superseded_cites_edge`).
4. The agent view of `check` never shows the contribution error rate, and `check` is refused to a contribution pass session (Task 1, `test_agent_view_and_pass_session`).
5. The acceptance module's local-library scan fails if a contribution `statement` longer than its quote, an agent `note`, or any raw reference entry text (excluded by G1 ruling 14 (b)) appears in an export or a git-tracked blob (Task 3, `test_no_literature_text_outside_quotes`).

## File Structure

- Modify `services/check.py`, `services/trace.py`.
- Tests: `test_lineage_check.py`, `test_lineage_trace.py`, `test_acceptance_lineage.py`.
- Docs: `docs/pilot/log.md` (Task 4 entries), `docs/decisions.md`, `docs/specs/01-rigour.md`, `docs/specs/00-system.md` (identity rows through the decision), `docs/specs/slice-3b-lineage.md` (implementation note), `CLAUDE.md` (status line).

---

### Task 1: `check` findings

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Modify `services/check.py`; Test `tests/test_lineage_check.py`.

**Interfaces:**
- Consumes: G2-A `unit_states(..., scope=)`, `stale_extractions(..., scope=)`, `scope_population`; G2-B `contribution_status`, `contribution_audit_report`, `contribution_item`, `reference_view`; G2-C `list_relations`, `list_ideas`, `EdgeStatus`; G1 `current_extraction`; existing `Finding`, `_Hit`, `LEVELS` (severity per mode), `_RATE_CODES` and `agent_view` (`services/check.py`).
- Produces: the ten codes of ruling 1 with ruling 2's definitions, added to `LEVELS`; `contribution-error-ceiling` added to `_RATE_CODES` (agent view states no rate, as `extraction-error-high`).

- [ ] **Step 1: Tests.** `@pytest.mark.parametrize("code", LINEAGE_CODES) test_each_finding_in_constructed_case` (acceptance 17; each case built through the services except `relation-without-basis`, built by appending a `relation.proposed` event with an unknown `basis_item`); `test_severity_by_mode` (table above); `test_findings_carry_no_document_text`; `test_relation_unconfirmed_is_one_finding_with_count`; `test_untouched_project_has_no_lineage_findings` (Review Focus 1); `test_stale_is_not_broken_chain` (Review Focus 2); `test_agent_view_and_pass_session` (Review Focus 4); `test_existing_check_suites_unchanged` (run unedited).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(lineage): check findings`.

### Task 2: `trace` from edges, relations, ideas and items

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Modify `services/trace.py`; Test `tests/test_lineage_trace.py`.

**Interfaces:**
- Consumes: `TraceNode(id, kind, label, event_id, children)`, `KINDS`, `_PATTERNS`, `_Walk` (`services/trace.py`); G2-B `contribution_item`; G2-C `relation_view`, `idea_view`, `REL_ID_RE`, `IDEA_ID_RE`; G2-D `graph_edges` (one indexed read by `edge_id` for `cit:` ids); G1 Task 8 trace kinds `reference_extraction` (`rex_…`) and `snowball_round` (`snw_…`).
- Produces: kinds `relation`, `idea`, `cites`, `quote` in `KINDS` after `claim`; patterns for `rel_`, `ida_`, `cit:`; edges per ruling 3.

- [ ] **Step 1: Tests.**
```python
def test_trace_edge_reaches_question(project):                    # acceptance 16
    kinds = flatten_kinds(trace(project, REL_STATED))
    assert {"relation", "extraction", "quote", "anchor", "conversion", "document", "attempt", "work", "decision", "protocol", "question"} <= kinds
def test_trace_quote_node_is_the_verified_quote(project): ...
def test_trace_cites_edge_reaches_link_and_target(project): ...
def test_trace_superseded_cites_edge(project): ...                # Review Focus 3
def test_trace_forward_from_item_lists_relations_and_ideas(project): ...
def test_trace_idea_lists_name_item_origin_members_merges(project): ...
def test_trace_refused_to_pass_session(project): ...
def test_labels_carry_no_text_except_quote_nodes(project): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests; existing trace suites unedited; mypy; ruff. **Step 5:** Commit `feat(lineage): trace from edges, relations, ideas and items`.

### Task 3: Acceptance module and separation

*Tier: Haiku implement; Sonnet reviews the separation and library-scan tests.*

**Files:** Test `tests/test_acceptance_lineage.py` (module marked `pytest.mark.slow`).

- [ ] **Step 1: Tests**, one project built from hand-written documents with `b<n>` references (no network), one flow:
  `test_schema_before_reading` (1: `contribution_next` refused, then allowed after the amendment; a log without the section replays to the pinned `P@`); `test_quote_verification_partial_acceptance` (2); `test_number_check` (3); `test_not_stated_rules_and_count` (4); `test_cited_entry_rejected_and_mismatch_flagged` (5); `test_dual_extraction_agreement_resolution_audit` (6); `test_separation_from_evidence_table` (7: with an evidence schema and final `ml-benchmark` rows, `final_rows`, `grouped_rows`, `independence_counts`, `live_claims` and the rendered evidence report are byte-equal before and after recording, agreeing, resolving and auditing contribution units); `test_stated_rule` (8); `test_confirmation_human_only_and_default_views` (9); `test_edges_carry_basis` (10); `test_staleness_by_version_item_g1_and_amendment` (11); `test_ideas_quote_unconfirmed_merge_reversal` (12, export bytes equal before the merge and after the unmerge); `test_queries_on_constructed_graph` (13); `test_exports_status_basis_dashed_and_stable` (14); `test_rebuild_identical_graph_and_state_hash` (15); `test_trace_edge_to_question` (16); `test_check_findings` (17); `test_no_literature_text_outside_quotes` (Review Focus 5 and R-47: scan every event, blob and both export formats; allowed text = verified quotes, marker tokens and the parsed reference fields and `entry_sha256` of G1 ruling 14 (b)); `test_earlier_acceptance_suites_unchanged`.
- [ ] **Step 2:** Run; fix wiring until PASS (a failure that needs a rule change goes back to the owning sub-plan's task, not into this module). **Step 3:** Full suite, `mypy --strict`, ruff, coverage >= 90% for `services/` and `model/` (acceptance 19). **Step 4:** Commit `test(lineage): slice 3b acceptance`.

### Task 4: Pilot run (acceptance 18)

*Tier: researcher with Claude; no code. Runs only after Tasks 1–3 are merged.*

- [ ] **Step 1: Preconditions.** The pilot project has its full-text included works converted and a current G1 extraction for each (or listed `no-references`); `factory check` shows no `references-missing-extraction` error.
- [ ] **Step 2: Declare.** The researcher amends the protocol with `contribution_schema` = pack `contribution` v1, all nine fields, `comparability_keys = []`, `dual_extract_sample = 0.3`, `audit_fraction = 0.02`, `audit_minimum = 50`, `claims = false`; `factory check --promote-to pilot` shows no `contribution_schema.*` gap.
- [ ] **Step 3: Read.** Pass A in a fresh Claude Code session (model M1) and pass B in another (model M2 ≠ M1), each with `rf-contributions`, until `contribution_next` returns no batch.
- [ ] **Step 4: Agree and audit.** The researcher runs `factory contributions agreement`, resolves every disagreement, then `audit sample`, labels every item and reads `audit report`.
- [ ] **Step 5: Propose.** A third session (no pass joined) with `rf-lineage` proposes relations from base-idea and addition items and ideas for named methods.
- [ ] **Step 6: Confirm.** The researcher reviews `factory relations list --status inferred` and `factory ideas list --all`, confirming or rejecting each with a rationale.
- [ ] **Step 7: Read the lineage.** `factory graph query path --node <current linear-attention vision backbone> --target <base attention formulation>`; if no path exists, `factory graph query no_stated_base` and record the categories (the gap is a finding, never filled by hand).
- [ ] **Step 8: Record** in `docs/pilot/log.md` (ids, statuses and computed counts only): the path's node and edge ids with each edge's status (all must be `stated` or `confirmed`), the counts of `not-stated`, `inferred`, `stale` and `uncited-base` items and edges from `graph_status`, the contribution agreement rate, the audit size and error rate, the two models, and the check findings. Commit `docs(pilot): lineage pilot record`.

### Task 5: Decisions, rigour rows and status

*Tier: Haiku.*

**Files:** Modify `docs/decisions.md`, `docs/specs/01-rigour.md`, `docs/specs/00-system.md`, `docs/specs/slice-3b-lineage.md`, `CLAUDE.md`.

- [ ] **Step 1:** `docs/decisions.md`: one new *Proposed* row "Slice 3b lineage rulings", listing spec rulings 1–14 and the plan rulings marked [adopted 2026-11-04] in G2-A (scope, cross-scope independence, keyed row key, pack v1), G2-B (item evidence, `not-stated` quote rule, closure rule), G2-C (classification order, idea targets inferred with a live basis, supersession, idea definition needs a quote, merges), G2-D (projected facts versus overlays, `no_stated_base` categories including `no-relation`) and G2-E (finding severities); "Rulings adopted 2026-11-04 (researcher's standing approval of the recommendations); entry kept *Proposed* until the slice is built and accepted." Numbered at merge.
- [ ] **Step 2:** `01-rigour.md`: R-xx(e), R-xx(f), R-xx(g) as proposed rows, text from the spec. `00-system.md` §3 identity rows `rel_<ULID>` (relation) and `ida_<ULID>` (idea), citing the new decision.
- [ ] **Step 3:** `slice-3b-lineage.md`: a short "Implemented in plans G2-A–G2-E" paragraph naming the MCP tools and CLI groups; `CLAUDE.md` status line updated.
- [ ] **Step 4:** Commit `docs(lineage): proposed decision, rigour rows, status`.

## Self-review notes

- **Spec coverage.** Check findings (Task 1; acceptance 17), trace (Task 2; acceptance 16, User flow 7), separation (Task 3; acceptance 7), every acceptance criterion end to end (Task 3; 1–17, 19), pilot (Task 4; acceptance 18), decision and rigour records (Task 5).
- **Interfaces.** Only names produced by G2-A–D and G1 Interfaces blocks are consumed; no new service API is introduced.
- **Tiers.** Tasks 1–2 standard (Haiku reviews), Task 3 Haiku with a Sonnet look at the separation and scan tests, Task 4 human, Task 5 Haiku. The final whole-branch review of slice 3b runs on Sonnet.

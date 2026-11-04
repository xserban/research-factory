# Regions C: Labels, Consolidation, Terms, Separation and Acceptance — Implementation Plan (slice 3d)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Status: draft — rulings recommended; awaiting the researcher's review before any build.

> **Dependencies.** Regions-A merged (Regions-B recommended first, for the acceptance task); slice 3b G2-C (`idea.merged`/`idea.unmerged`) and slice 3c G3-B (`concept.merged`/`concept.unmerged`) merged. Import-B optional: Zotero tags arrive as labels only if imports exist (Task 1).

**Goal:** Implement decision 5's emerge → consolidate → promote → record cycle without free labels in the evidence graph: free labels in organisation tables, deterministic candidate synonym clusters, agent merge proposals with human decisions (for labels, ideas and concepts), promotion of labels to typed terms, the `term` region rule, the separation tests for the whole organisation class, and the slice-3d acceptance and pilot.

**Architecture:** `model/labels.py` and `services/labels.py` (applications, merges, terms); `factory/consolidation/` holds pure candidate computation (`signals.py`: normalisation, `rapidfuzz` ratio, acronym rule, inverted-index target overlap); `services/consolidation.py` runs passes, serves clusters as tasks and records proposals and decisions; decisions on ideas and concepts call the existing `services/ideas.py` and `services/concepts.py` merge functions with a `proposal` reference.

**Tech Stack:** as Regions-A; `rapidfuzz` (already a dependency).

**Spec:** `docs/specs/slice-3d-regions-import.md` rulings 7, 12–16, 26; acceptance 7–10, 18, 19.

## Rulings made in this plan

1. **Label key.** `label_key(text) = " ".join(unicodedata.normalize("NFKC", text).casefold().split())`; 1–60 characters after normalisation; no control characters.
2. **Merged keys.** `label.merged(into_key, from_key, reason, proposal_id | None)`; the live key of a label is the end of its merge chain; `label.unmerged` reverses one merge. Cycles are refused.
3. **Clusters.** A pass computes, per kind (`label`, `idea`, `concept`), the pairs meeting any signal (spec ruling 15), then clusters by connected components capped at `CLUSTER_MAX = 12` members (larger components are split by highest-scoring edges first, deterministically). Clusters are ordered by (kind, smallest member id). Signal constants are recorded in `consolidation.pass_started`.
4. **Task flow.** `consolidation_next` creates a `Task` (kind `consolidate`) per cluster with a lease (00-system §8); `input_blob` is the cluster with its signals and, for ideas and concepts, names, aliases and member counts (no document text).
5. **Pass completion.** A pass completes when every cluster has a human decision (`merge`, `keep`, `split`) or was skipped by the researcher with a reason; the due counters reset at completion.
6. **Term application status.** For each live label application whose key is a term's name or alias: `confirmed` if by a human or confirmed later; `stated` if it carries a verified quote containing the key or any of the term's keys (re-checked at read time against the stored quote, not the document); else `inferred`.

## Global Constraints

- As Regions-A. Labels, terms and consolidation rows never enter `graph_nodes`, `graph_edges`, `layer_nodes`, `layer_edges` or any evidence table.
- No MCP tool merges, promotes, confirms or decides a cluster. Pass sessions are refused every tool of this plan.
- Candidate computation never compares all pairs: string signals are blocked by first token and by character trigram; overlap signals use the target inverted index.

## Review Focus

1. A merge and its reversal restore the projection exactly, for labels, ideas and concepts (Task 3, `test_merge_unmerge_restores_state_hash`).
2. "Performer" and "FAVOR+" labels on the same three works form a cluster by target overlap alone (Task 2, `test_overlap_signal_without_string_similarity`).
3. A `term` rule selects only stated and confirmed applications (Task 4, `test_term_rule_excludes_inferred`).
4. The evidence outputs are byte-identical with and without regions, labels and terms; an evidence module importing a region or label module fails the architecture test (Task 5).

## File Structure

- Create `model/labels.py`, `services/labels.py`, `consolidation/__init__.py`, `consolidation/signals.py`, `consolidation/clusters.py`, `services/consolidation.py`, `index/labels.py`, `plugin/skills/rf-consolidate/SKILL.md`.
- Modify `model/lineage.py` or the module holding `IdeaMerged` and `model/intuition.py` or the module holding `ConceptMerged` (optional `proposal: str | None = None`, omitted when absent so earlier events replay identically), `regions/evaluate.py` (`TermRule`), `services/imports.py` (tags as labels), `mcp/server.py`, `cli/main.py`, `services/check.py`, `services/trace.py`, `services/lineage.py` (`graph_export --with-labels`).
- Tests: `test_labels.py`, `test_consolidation_signals.py`, `test_consolidation_service.py`, `test_terms.py`, `test_organisation_separation.py`, `test_acceptance_regions.py`.

---

### Task 1: Label applications

*Tier: standard.*

**Files:** Create `model/labels.py`, `services/labels.py`, `index/labels.py`; modify `services/imports.py`, `events/catalog.py`, `index/default.py`; Test `tests/test_labels.py`.

**Interfaces:**
- Consumes: `quote_in_element`, pinned conversions, target existence (works, live ideas, live concepts).
- Produces: `class LabelApplied(StrictModel)`: `application_id` (`lab_<ULID>`), `target_type: MemberType`, `target`, `text`, `key`, `quote: QuoteBasis | None`, `status: Literal["confirmed", "stated", "inferred"]` (computed by the platform), `origin: Literal["agent", "human", "import-tag"]`, `import_ref: str | None` (record key); `LabelWithdrawn(application_id, reason)`; `LabelApplicationDecided(application_id, decision: Literal["confirm", "reject"])` (human); `apply_labels(project, actor, items: Sequence[LabelInput]) -> BatchResult` (partial acceptance; agent quotes verified); `withdraw_label(...)`; `decide_application(...)` (human only); `labels_of(project, target_type, target) -> list[LabelView]`. Import-B records: `import_tags_as_labels(project, import_id) -> int` (human actor, origin `import-tag`, status `confirmed`) run by `factory import admit` and `factory import resolve` for resolved records.
- Projection `labels(application_id, target_type, target, key, live_key, status, origin, withdrawn)`, indexes `(key)`, `(target)`.

- [ ] **Step 1: Tests.** `test_human_application_confirmed`, `test_agent_quote_with_key_stated`, `test_agent_without_quote_inferred`, `test_non_verbatim_quote_rejected_batch_partial`, `test_key_normalisation`, `test_withdraw_supersedes`, `test_import_tags_become_confirmed_labels`, `test_labels_not_in_graph_tables`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(labels): free label applications in organisation tables`.

### Task 2: Candidate signals and clusters

*Tier: critical (determinism, bounded cost).*

**Files:** Create `consolidation/signals.py`, `consolidation/clusters.py`; Test `tests/test_consolidation_signals.py`.

**Interfaces:**
- Produces (`consolidation/signals.py`): `SYNONYM_RATIO = 0.90`, `SYNONYM_OVERLAP = 0.5`, `ACRONYM_MIN_WORDS = 2`; `@dataclass(frozen=True) Item(kind: str, id: str, names: tuple[str, ...], targets: frozenset[str])`; `@dataclass(frozen=True) Pair(a: str, b: str, signals: tuple[str, ...], score: float)`; `string_pairs(items: Sequence[Item]) -> list[Pair]` (blocked; `rapidfuzz.fuzz.ratio` / 100 ≥ `SYNONYM_RATIO`); `acronym_pairs(items) -> list[Pair]`; `overlap_pairs(items, postings: Mapping[str, Sequence[str]]) -> list[Pair]` (only pairs co-occurring in some posting list).
- Produces (`consolidation/clusters.py`): `CLUSTER_MAX = 12`; `clusters(pairs: Sequence[Pair]) -> list[tuple[str, ...]]` (ruling 3; deterministic).

- [ ] **Step 1: Tests.** `test_string_signal_case_and_punctuation`, `test_acronym_signal` (`"linear transformer attention"` vs `"lta"`), `test_overlap_signal_without_string_similarity` (Review Focus 2), `test_no_all_pairs` (a counting stub: comparisons bounded by block sizes on 10,000 items), `test_clusters_deterministic_and_capped`, `test_pairs_name_their_signals`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(consolidation): deterministic synonym signals and clusters`.

### Task 3: Consolidation passes, proposals and merges

*Tier: critical (reversible merges, R-51).*

**Files:** Create `services/consolidation.py`; modify `model/labels.py`, `services/labels.py`, the idea and concept merge payloads and services, `index/labels.py`; Test `tests/test_consolidation_service.py`.

**Interfaces:**
- Consumes: `idea.merged`/`idea.unmerged` and `concept.merged`/`concept.unmerged` services (G2-C, G3-B), the task queue (`services/tasks.py`).
- Produces: `class ConsolidationPassStarted(StrictModel)`: `pass_id` (`cns_<ULID>`), `clusters_blob`, `constants`, `counts`; `ConsolidationProposed(proposal_id (cnp_<ULID>), pass_id, cluster_index, action: Literal["merge", "keep", "split"], into: str | None, members: tuple[str, ...], reason: str (≤ 600), quotes: tuple[QuoteBasis, ...])`; `ConsolidationDecided(pass_id, cluster_index, decision: Literal["merge", "keep", "split", "skip"], merge_events: tuple[str, ...], reason)`; `ConsolidationPassCompleted(pass_id)`; `LabelMerged(into_key, from_key, reason, proposal_id)`, `LabelUnmerged(merge_event, reason)`; `start_pass(project, actor) -> str`; `consolidation_next(project, actor) -> ClusterTask | None`; `propose(project, actor, task_id, ...) -> str`; `decide_cluster(project, actor, pass_id, cluster_index, decision, *, into=None, reason) -> None` (human; writes the merge events and the decision in one `record` call); `consolidation_due(project) -> DueState` (`new_label_keys`, `new_nodes`, `due: bool`).

- [ ] **Step 1: Tests.** `test_merge_unmerge_restores_state_hash` (Review Focus 1, parametrised over label, idea, concept), `test_agent_cannot_decide`, `test_proposer_session_cannot_decide_via_mcp`, `test_decision_references_proposal`, `test_pass_completes_when_all_decided`, `test_due_counts_reset_on_completion`, `test_label_merge_cycle_refused`, `test_old_idea_merge_events_replay_identically`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(consolidation): passes, proposals and human merge decisions`.

### Task 4: Terms and the `term` rule

*Tier: critical (selectors).*

**Files:** Modify `model/labels.py`, `services/labels.py`, `index/labels.py`, `regions/evaluate.py`; Test `tests/test_terms.py`.

**Interfaces:**
- Produces: `class TermPromoted(StrictModel)`: `term_id` (`trm_<ULID>`), `name`, `aliases: tuple[str, ...]`, `definition` (≤ 600), `applies_to: tuple[MemberType, ...]`, `refers_to: str | None` (idea or concept id), `from_keys: tuple[str, ...]`; `TermRevised` (same fields, `supersedes`), `TermRetired(term_id, reason)`; `promote_term(...)`, `revise_term(...)`, `retire_term(...)` (human only); `term_applications(project, term_id, *, status: frozenset[str] = {"stated", "confirmed"}) -> list[TermApplication]` (ruling 6); `promotion_suggestions(project) -> list[tuple[str, int]]` (keys with at least `PROMOTION_MIN_TARGETS = 3` distinct targets, not yet promoted). `TermRule` evaluation selects targets of `term_applications` with the default status set, refused for a retired term; in `systematic`, a snapshot with a `TermRule` is refused while `consolidation_due(project).due`.

- [ ] **Step 1: Tests.** `test_agent_cannot_promote`, `test_term_applications_classified`, `test_term_rule_excludes_inferred` (Review Focus 3), `test_alias_quote_makes_stated`, `test_retired_term_rule_refused`, `test_systematic_refuses_term_rule_when_due`, `test_promotion_suggestions_threshold`, `test_refers_to_must_exist`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(labels): promotion to terms and the term region rule`.

### Task 5: Tools, separation tests, check and trace

*Tier: critical (organisation never becomes evidence).*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `services/check.py`, `services/trace.py`, `services/lineage.py`; create `plugin/skills/rf-consolidate/SKILL.md`; Test `tests/test_organisation_separation.py`, extend `tests/test_check.py` by new tests only.

**Interfaces:**
- Produces MCP: `label_apply(items)`, `consolidation_next()`, `consolidation_propose(task_id, action, into, members, reason, quotes)`, `term_list(offset, limit)`; refused to pass sessions.
- Produces CLI: `factory labels list|apply|withdraw|merge|unmerge|confirm|reject`, `factory terms promote|revise|retire|list|suggest`, `factory consolidation status|start|list|decide|complete`, `factory graph export --with-labels` (labels and terms with `class = organisation` on every row; default export unchanged).
- Produces findings: `consolidation-due`, `label-application-unconfirmed`, `term-unused`, `organisation-leak` (error, all modes: any evidence output — `final_rows`, groups, frontiers, `live_claims`, PRISMA, `search_report`, `report_methods` counts — containing a `reg_`, `R@`, `lab_` or `trm_` id).
- Produces trace: `lab_`, `trm_`, `cns_`, `cnp_` ids → actor, provenance, quote, merges and decisions.
- Separation tests: AST architecture test (no module among `services/extraction*.py`, `services/evidence*.py`, `services/prisma.py`, `services/methods.py`, `services/screening*.py`, `evidence/` imports `factory.regions`, `factory.consolidation`, `services.regions`, `services.labels`, `services.consolidation` or `services.coverage`); differential test (fixture built twice, with and without regions, labels and terms; evidence outputs byte-identical).

- [ ] **Step 1: Tests.** `test_architecture_no_organisation_imports`, `test_differential_evidence_identical`, `test_organisation_leak_fires_on_constructed_leak`, `test_default_export_unchanged`, `test_with_labels_rows_carry_class`, one per finding, `test_tools_refuse_pass_sessions`, `test_skill_hash_recorded`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(labels): tools, separation tests, check and trace`.

### Task 6: Slice-3d regions acceptance and pilot

*Tier: standard.*

**Files:** Create `tests/test_acceptance_regions.py`; pilot notes in `docs/pilot/log.md` only if the pilot is run (never open `docs/pilot/heldout-seeds.md`).

- [ ] **Step 1: Tests**, one per spec acceptance criterion 1–10 and 17 (region part), on the region helper project: rule determinism and order independence; bounds refusal and the `slow` scale test; version hash sensitivity and the `slow` replay-to-`as_of` test (events up to `as_of` replayed into a fresh index; same member hash); review and proposals; foci; adoption; labels; consolidation; promotion; separation; rebuild and trace.
- [ ] **Step 2:** Pilot (researcher-run, recorded in the pilot log): two foci on the pilot question's slots, one lineage region from a base attention formulation, one consolidation pass with at least one label merge and one promoted term; report counts (members by type, drift, unreviewed, pending proposals, applications by status).
- [ ] **Step 3:** `uv run pytest -m "not network"` including `slow`; mypy; ruff. **Step 4:** Commit `test(regions): slice-3d regions acceptance`.

**Verification for the plan:** `cd platform && uv run pytest -m "not network" && uv run mypy --strict src && uv run ruff check`.

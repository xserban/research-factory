# Evaluation, Multiverse, Ledger, Failed-Directions Registry and Slice-6 Acceptance Implementation Plan (slice 6, sub-plan XP-B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** This plan is XP-B. The ledger of Task 5 is the benchmark ledger: `services/benchmark_ledger.py`, `tests/test_benchmark_ledger.py`, MCP `benchmark_ledger_view`, CLI `factory benchmark-ledger` (slice 5 owns `ledger`). `DirectionReason.BUDGET_EXHAUSTED` has the value `compute-budget-exhausted`. Task 8's "Proposed decision" is decisions 67–68, already recorded. Task 8's acceptance uses constructed runs and stays in v1; the pilot with real runs is Later (spec v1 scope). Bumps `PROJECTION_VERSION` by one from the value it finds.

> **Dependencies.** XP-A merged (Interfaces consumed exactly: `ExperimentDesign`, `Cell`, `primary_cells`, `universes`, `experiment_view`, `xrun_list`, `access_counts`, `baseline_verdicts`, tables `xruns`, `baseline_evaluations`, `experiment_deviations`); H-A–H-C merged (`HypothesisSpec`, `DecisionRule`, `hypothesis_view`, `cutoff_flags`, `PRIOR_SOURCES`, `list_leads`, `card_view`, `resolve_idea`); plan 2E (`evidence_report`, `EvidenceRow`, `GroupReport`, `group_id`); `services/methods.py`, `services/check.py`, `services/trace.py`. When slice M lands, `evaluate`, `ledger` and the registry declare their inputs as builders; their outputs do not change.

**Goal:** Compute the outcome of every registered hypothesis from recorded results by its registered rule, with the flags that qualify it; summarise multiverse, ablations and controls; show reported against reproduced results in a ledger that never alters the evidence report; keep every refuted, inconclusive or abandoned direction searchable with its conditions; and make all of it visible in `check`, `trace` and the methods report.

**Architecture:** Pure statistics in `factory/hypotheses/tquantiles.py` (embedded Student-t table) and `factory/hypotheses/stats.py`; pairing and rule application in `factory/hypotheses/pairing.py` and `factory/hypotheses/rules.py`. `services/evaluation.py` assembles inputs from the projection and writes `hypothesis.evaluated` as a `system` event; `services/multiverse.py` computes specification curves and control outcomes on read; `services/ledger.py` joins evidence groups with own and reproduced results; `services/directions.py` owns `direction.closed` and the `directions` projection and registers itself in `PRIOR_SOURCES`. `check`, `trace` and `methods_report` gain slice-6 sections.

**Tech Stack:** as plan D; no new dependencies (no numpy, no scipy: decimals and an embedded quantile table).

**Spec:** `docs/specs/slice-6-hypotheses.md` rulings 16, 17, 22, 23, 25, 26, 27; Design "Evaluation, reproduction and ledger", "Failed-directions registry"; events `hypothesis.evaluated`, `direction.closed`; MCP `registry_query`, `ledger_view`; CLI `hypotheses evaluate|conclude`, `ledger`, `registry`, `directions close`; check findings; acceptance 15, 18–25. `01-rigour.md` R-01, R-05, R-50–R-54; R-121, R-124, R-125.

## Rulings made in this plan (recommended; [confirm])

1. **t table.** Two-sided quantiles `t_{1-α/2, df}` for levels 0.90, 0.95, 0.99 and df 1–60, then 80, 100, 120, ∞, as decimal strings to 4 places from a standard reference table; df between listed values uses the next lower df (conservative). Tested against ten hand-copied values. [confirm]
2. **Arithmetic.** `Decimal` with a local context of 28 digits; mean, sample standard deviation (n − 1), standard error, CI = mean ± t·se; results quantised to 6 places half-even; square root via `Decimal.sqrt`. [confirm]
3. **Orientation.** Difference = treatment − baseline for `higher` metrics, baseline − treatment for `lower`; positive always means "treatment better". [confirm]
4. **Pairs.** A pair is (treatment run, baseline run) on the confirmatory split, primary universe, same seed, both completed without `failed` or `environment-differs`, configurations differing exactly in the factor keys (spec ruling 22). If several completed runs exist for one cell, the earliest reported is used and the others are listed (`extra_runs`). `n` = number of pairs; `n < 2` → outcome `inconclusive` with flag `too-few-pairs`; `n < min_seeds` → flag `below-min-seeds`. [confirm]
5. **Rule application.** Superiority: supported if `ci_low > margin`; refuted if `ci_high < margin`; else inconclusive. Non-inferiority: supported if `ci_low > −margin`; refuted if `ci_high < −margin`; else inconclusive. Literature-direction (unit: work): among works published on or after the window start whose final independent rows give both a treatment and a baseline value in one comparability group matching the hypothesis conditions, `k` works favour treatment by more than `margin`, `j` favour baseline; supported if `n ≥ n_min` and `k/n ≥ q`; refuted if `n ≥ n_min` and `j/n ≥ q`; else inconclusive, with `insufficient-evidence` when `n < n_min`. [confirm]
6. **Evaluation trigger and staleness.** `evaluate` runs on CLI request or automatically after the ingestion that completes the last primary cell; it writes one `hypothesis.evaluated` per hypothesis (`EVALUATOR_VERSION = "1"`, `inputs_hash` over the sorted run ids, their results blobs, the rule and the plan). A later evaluation (for example after an `incomplete` request) supersedes; the projection keeps all. On rebuild, `check` recomputes and reports `evaluation-stale` if the recomputed outcome or `inputs_hash` differs. [confirm]
7. **Specification curve.** For every universe with at least two pairs: mean, CI, and the rule outcome as if that universe were primary (labelled `descriptive`). `only-non-primary`: the primary outcome is not `supported` and some non-primary universe would be `supported`. `fragile`: universe means of both signs exist. [confirm]
8. **Controls.** A positive control passes when its pairs give `ci_low > 0`; a negative control passes when its CI contains 0; reported as `sensitivity_ok` and `false_positive_ok`; a failing control flags the hypothesis outcome `control-failed`. [confirm]
9. **Registry keys.** As H-C ruling 2 (trigger refs, cards, ideas, properties) plus the hypothesis's treatment and baseline refs and the design's dataset names (`ds:<name>`). [confirm]

## Global Constraints

- The platform never calls a model; outcomes are computed by the platform (`actor.kind = system`), never set by an agent or a human.
- `evidence_report`, `final_rows`, `grouped_rows`, `live_claims` and PRISMA outputs are byte-identical with and without slice-6 artifacts (differential test, Task 8).
- Statistics are pure functions with hand-checked fixtures; no floating point in stored values.
- Registry rows are never removed; corrections supersede.
- Business logic in `services/`; pure helpers in `factory/hypotheses/`; `mcp/`, `cli/` parse and format.
- TDD; `uv run pytest -m "not network and not slow"` (Task 8's end-to-end test is `slow`), `mypy --strict`, ruff; coverage ≥ 90% for `services/` and `model/`.

## Review Focus

1. CI and outcome on three hand-computed fixtures (one per experiment rule outcome) match to 6 places (Task 2, `test_hand_computed_outcomes`).
2. A pair whose configurations differ in a non-factor key is excluded and counted as confounded (Task 2, `test_confounded_pair_excluded`).
3. No actor can write `hypothesis.evaluated`: a human or agent event of that type is refused by the service and ignored by the projector (Task 3, `test_outcome_cannot_be_set`).
4. `evidence_report` byte-identical with own results and reproductions present (Task 5 and Task 8, `test_evidence_report_unchanged`).
5. A refuted hypothesis appears in `prior` of a later lead sharing its treatment card (Task 6, `test_registry_feeds_prior`).

## File Structure

- Create `factory/hypotheses/tquantiles.py`, `factory/hypotheses/stats.py`, `factory/hypotheses/pairing.py`, `factory/hypotheses/rules.py`, `services/evaluation.py`, `services/multiverse.py`, `services/ledger.py`, `services/directions.py`, `model/directions.py`, `index/directions.py`.
- Modify `model/hypotheses.py` (`HypothesisEvaluated`), `index/hypotheses.py`, `services/hypotheses.py` (conclude), `services/xruns.py` (auto-evaluate hook), `services/check.py`, `services/trace.py`, `services/methods.py`, `events/catalog.py`, `index/default.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- Tests: `test_tquantiles.py`, `test_stats.py`, `test_pairing_rules.py`, `test_evaluation.py`, `test_multiverse.py`, `test_benchmark_ledger.py`, `test_directions.py`, `test_slice6_check_trace_methods.py`, `test_slice6_acceptance.py` (slow); helper `tests/evaluation_helpers.py` (XP-A fixtures plus `report_runs(experiment, {(arm, seed): value, ...})` that registers and ingests runs from a table).

---

### Task 1: t quantiles and paired statistics

*Tier: critical (numbers).*

**Files:** Create `factory/hypotheses/tquantiles.py`, `factory/hypotheses/stats.py`; Test `tests/test_tquantiles.py`, `tests/test_stats.py`.

**Interfaces:**
- Produces: `Level = Literal["0.90", "0.95", "0.99"]`; `t_quantile(level: Level, df: int) -> Decimal` (ruling 1; `df < 1` → `ValueError`); `@dataclass(frozen=True) PairedSummary(n: int, mean: Decimal, sd: Decimal | None, se: Decimal | None, ci_low: Decimal | None, ci_high: Decimal | None, level: Level)`; `paired_summary(diffs: Sequence[Decimal], level: Level) -> PairedSummary` (ruling 2; `n < 2` → sd, se, CI `None`); `oriented(treatment: Decimal, baseline: Decimal, direction: Literal["higher", "lower"]) -> Decimal` (ruling 3).

- [ ] **Step 1: Tests.** `test_known_quantiles` (ten values, e.g. `t_quantile("0.95", 2) == Decimal("4.3027")`, `("0.95", 4) == Decimal("2.7764")`, `("0.99", 10) == Decimal("3.1693")`); `test_df_between_rows_uses_lower`; `test_paired_summary_hand_computed` (diffs `[0.8, 1.1, 0.5]` → mean `0.8`, sd `0.3`, CI at 0.95 `[0.054750, 1.545250]` (half-even to 6 places of 0.8 ∓ 4.3027·0.3/√3)); `test_n_one_has_no_ci`; `test_orientation_lower_is_better`; `test_results_quantised_half_even`.
- [ ] **Step 2:** `uv run pytest -m "not network and not slow" tests/test_tquantiles.py tests/test_stats.py` — FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(evaluation): embedded t table and paired statistics`.

### Task 2: Pairing and decision rules

*Tier: critical.*

**Files:** Create `factory/hypotheses/pairing.py`, `factory/hypotheses/rules.py`; Test `tests/test_pairing_rules.py`.

**Interfaces:**
- Consumes: Task 1; `Cell`, `run_config`; `DecisionRule` variants, `Prediction`.
- Produces (`pairing.py`): `@dataclass(frozen=True) RunFact(run_id, cell: Cell, config: Mapping[str, str], value: Decimal | None, flags: frozenset[str], reported_order: int)`; `@dataclass(frozen=True) Pairing(pairs: tuple[tuple[str, str, Decimal], ...], confounded: tuple[tuple[str, str], ...], excluded: dict[str, tuple[str, ...]], extra_runs: tuple[str, ...])`; `pair_runs(facts: Sequence[RunFact], *, factor_keys: frozenset[str], universe: Mapping[str, str], split: SplitRole, direction) -> Pairing` (ruling 4; excluded reasons `failed`, `environment-differs`, `missing-partner`).
- Produces (`rules.py`): `Outcome = Literal["supported", "refuted", "inconclusive"]`; `@dataclass(frozen=True) RuleResult(outcome: Outcome, flags: frozenset[str], summary: PairedSummary | None, counts: Mapping[str, int])`; `apply_experiment_rule(rule: Superiority | NonInferiority, margin: Decimal, summary: PairedSummary, *, min_seeds: int) -> RuleResult`; `apply_literature_rule(rule: LiteratureDirection, margin: Decimal, favour: Sequence[Literal["treatment", "baseline", "tie"]]) -> RuleResult` (ruling 5).

- [ ] **Step 1: Tests.** `test_hand_computed_outcomes` (Review Focus 1; acceptance 18: supported, refuted, inconclusive for superiority; supported and refuted for non-inferiority); `test_confounded_pair_excluded` (Review Focus 2; acceptance 15); `test_failed_and_environment_runs_excluded_with_reason`; `test_earliest_run_used_others_listed`; `test_too_few_pairs_inconclusive`; `test_below_min_seeds_flag`; `test_literature_insufficient_evidence` (acceptance 18); `test_literature_supported_and_refuted`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(evaluation): run pairing and decision-rule application`.

### Task 3: Evaluation service and conclusions

*Tier: critical (computed outcome).*

**Files:** Create `services/evaluation.py`; Modify `model/hypotheses.py`, `index/hypotheses.py`, `services/hypotheses.py`, `services/xruns.py`; Test `tests/test_evaluation.py`.

**Interfaces:**
- Consumes: Tasks 1–2; `hypothesis_view`, `experiment_view`, `xrun_list`, `baseline_verdicts`, `cutoff_flags`, `effective_plan`, `evidence_report` (literature), `Work.dates.published` via the works projection.
- Produces: payload `HypothesisEvaluated(hypothesis_id, h_version, experiment_id: str | None, e_version: str | None, outcome: Outcome | Literal["incomplete"], n: int, mean: str | None, ci_low: str | None, ci_high: str | None, level, counts: dict[str, int], flags: tuple[str, ...], runs: tuple[str, ...], works: tuple[str, ...], inputs_hash, evaluator_version)`; table `hypothesis_evaluations(event_id pk, hypothesis_id, outcome, flags, inputs_hash, supersedes)`; `evaluate_hypothesis(project, hypothesis_id, *, request_incomplete: bool = False) -> str` (writes with `project.system_actor()`; flags gathered: `test-reused` (access count above limit for a primary cell), `deviated`, `baseline-not-reproduced` (any `accepted` baseline), `contaminated`/`cutoff-unknown` (literature), `autonomy:agent` (registration autonomy), `control-failed` and `only-non-primary`/`fragile` from Task 4); refuses unless the hypothesis is `registered` (`state`, `not-registered`); `recompute(project, hypothesis_id) -> HypothesisEvaluated` (pure recomputation for `check`); `conclude_hypothesis` (H-C) now requires an evaluation; the projector ignores `hypothesis.evaluated` from non-system actors and `HypothesisEvaluated` has no input model exposed to MCP or CLI.

- [ ] **Step 0: Register the H-C hook.** Append a provider to `services/hypotheses.EVALUATION_SOURCES` (true when a live `hypothesis.evaluated` row exists for the hypothesis, read from `hypothesis_evaluations`) at import of `services/evaluation.py`, and make `services/hypotheses.py` import that module lazily where it reads the list so that the hook is filled whichever surface loads first. Without it the revision rule (H-C ruling 6), `conclude_hypothesis` and the `evaluated` state silently fail open. Add `test_revision_refused_after_evaluation_without_monkeypatch` and `test_conclude_allowed_after_evaluation_without_monkeypatch`: evaluate a registered hypothesis through the service, then draft with `supersedes=` (expect `evidence-exists`), abandon it (expect refusal) and conclude it (expect success); none of these tests sets or patches the hook lists. Keep the hooks (H-C).
- [ ] **Step 1: Tests.** `test_auto_evaluation_after_last_primary_cell`, `test_incomplete_request_then_full_evaluation_supersedes`, `test_flags_collected` (parametrised over each flag source), `test_literature_evaluation_uses_window` (works before the window ignored), `test_outcome_cannot_be_set` (Review Focus 3; acceptance 18), `test_conclusion_is_interpretation_and_keeps_outcome`, `test_recompute_matches_event`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(evaluation): computed hypothesis outcomes with qualifying flags`.

### Task 4: Multiverse, ablations and controls

*Tier: standard.*

**Files:** Create `services/multiverse.py`; Modify `services/evaluation.py`; Test `tests/test_multiverse.py`.

**Interfaces:**
- Consumes: Tasks 1–3; `universes`.
- Produces: `UniversePoint(universe: dict[str, str], primary: bool, n: int, mean: str | None, ci_low: str | None, ci_high: str | None, outcome_descriptive: Outcome | None)`; `SpecificationCurve(points: list[UniversePoint], flags: tuple[str, ...])` (points sorted by mean, then universe); `specification_curve(project, experiment_id) -> SpecificationCurve` (ruling 7); `AblationResult(name, key, n, mean, ci_low, ci_high)` (ablation arm − treatment, oriented); `ablations(project, experiment_id) -> list[AblationResult]`; `ControlResult(name, kind, n, ci_low, ci_high, passed: bool | None)`; `controls(project, experiment_id) -> list[ControlResult]` (ruling 8); `evaluation.py` reads these for flags `only-non-primary`, `fragile`, `control-failed`.

- [ ] **Step 1: Tests.** `test_only_non_primary_flag` (acceptance 19), `test_fragile_flag` (acceptance 19), `test_curve_sorted_and_primary_marked`, `test_ablation_effect_oriented`, `test_positive_and_negative_control_pass_fail`, `test_exploratory_runs_never_in_curve`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(evaluation): specification curve, ablations and controls`.

### Task 5: Ledger builder

*Tier: standard.*

**Files:** Create `services/benchmark_ledger.py`; Test `tests/test_benchmark_ledger.py`.

**Interfaces:**
- Consumes: `evidence_report`, `GroupReport`, `EvidenceRow`, `baseline_evaluations`, `hypothesis_evaluations`, `experiment_view`.
- Produces: `LedgerRow(row_key, work_id, method_name, reported: str, reproduction: Literal["reproduced", "not-reproduced", "accepted", "none"], reproduced: str | None, experiment_id: str | None, trace_id)`; `OwnResult(hypothesis_id, experiment_id, outcome, mean, ci_low, ci_high, n, flags)`; `LedgerGroup(group_id, key, rows: list[LedgerRow], own_results: list[OwnResult])`; `ledger(project, *, group_id: str | None = None) -> list[LedgerGroup]` (spec ruling 25; own results are attached to the group whose key equals the hypothesis conditions; they never enter `rows`, frontiers or counts).

- [ ] **Step 1: Tests.** `test_reported_and_reproduced_columns` (acceptance 20), `test_own_results_attached_by_conditions`, `test_evidence_report_unchanged` (Review Focus 4; acceptance 20: `evidence_report(...)` JSON byte-identical with and without slice-6 events), `test_group_filter`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(ledger): reported versus reproduced ledger beside the evidence report`.

### Task 6: Failed-directions registry

*Tier: critical (R-52).*

**Files:** Create `model/directions.py`, `index/directions.py`, `services/directions.py`; Modify `events/catalog.py`, `index/default.py`, `services/leads.py` (`PRIOR_SOURCES` registration); Test `tests/test_directions.py`.

**Interfaces:**
- Consumes: `list_leads`, `list_hypotheses`, `hypothesis_evaluations`, `baseline_evaluations`, `experiment_view`, `lead_keys`.
- Produces: `DIR_ID_RE = rf"^dir_{ULID_RE}$"`; `DirectionReason(StrEnum)`: `REFUTED`, `INCONCLUSIVE`, `BELOW_BASELINE`, `BASELINE_NOT_REPRODUCED`, `BUDGET_EXHAUSTED`, `NO_RUNNABLE_CODE`, `INFEASIBLE`, `DATA_UNAVAILABLE`, `DISCARDED_LEAD`, `OTHER`; `Conditions(e_version: str | None, datasets: tuple[str, ...], gpu_hours_used: str | None, models: tuple[str, ...], code_commit: str | None)`; payload `DirectionClosed(direction_id, text (1..600), reason, conditions, keys: tuple[str, ...])` (human); tables `directions(direction_id pk — dir_ id or the source artifact id, source_kind: Literal["hypothesis", "lead", "baseline", "closed"], reason, conditions_json, event_id)`, `direction_keys(direction_id, key)` (index on key). The projection derives rows from `hypothesis.evaluated` (refuted, inconclusive; `below-baseline` when superiority is refuted with a negative mean), `hypothesis.abandoned`, `lead.decided(discard)`, `baseline.evaluated(not-reproduced)` and `direction.closed`. Services: `close_direction(project, actor, text, reason, conditions, keys) -> str` (human; keys must resolve); `RegistryRow(direction_id, source_kind, reason, conditions, keys, summary: str (fixed template with ids), event_id)`; `registry_query(project, keys: Collection[str] = (), *, reasons=None, limit=50, after=None) -> RegistryPage`; provider `prior_from_registry(project, keys) -> list[str]` added to `PRIOR_SOURCES`.

- [ ] **Step 0: Register the H-C hooks.** Append to `services/leads.PRIOR_SOURCES` a provider returning the `direction_keys` matches, and to `services/leads.DIRECTION_RESOLVERS` a resolver true for a `dir_` id in `directions`, at import of `services/directions.py`; load the module lazily from `leads.prior_for` and `leads.trigger_issues` (as `hypothesis_prior` is) so that a surface that never imports it still sees the registry. Add `test_dir_trigger_resolves_without_monkeypatch` (a lead with a `direction` trigger on a closed direction is accepted, an unknown `dir_` is refused) and extend `test_registry_feeds_prior`; neither patches the hook lists.
- [ ] **Step 1: Tests.** `test_each_source_appears_with_conditions` (acceptance 21), `test_query_by_card_idea_property_work` (acceptance 21), `test_registry_feeds_prior` (Review Focus 5), `test_close_direction_human_only`, `test_rows_never_removed_after_later_success` (a later supported hypothesis with the same keys leaves the row), `test_superseded_before_evidence_is_not_failure` (H-C ruling 6).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(registry): failed-directions registry with conditions`.

### Task 7: Check findings, trace and methods text

*Tier: standard (critical review of trace).*

**Files:** Modify `services/check.py`, `services/trace.py`, `services/methods.py`; Test `tests/test_slice6_check_trace_methods.py`.

**Interfaces:**
- Consumes: every slice-6 view.
- Produces: check findings of the spec list (each a `_Hit` with code, ids, severity by mode: `hypothesis-cutoff-unknown`, `evaluation-stale`, `xrun-reported-without-registration` errors in systematic; `controls-missing` error in systematic; others warning or advisory); trace keys for `led_`, `hyp_`, `exp_`, `xrn_`, `mcd_`, `pbd_`, `pas_`, `ctr_`, `dir_` and for an evaluation event (backward: evaluation → runs → results blobs → design → hypothesis → review → lead → triggers → for a `row` trigger, the slice-2 chain; forward from a work: assertions, leads, hypotheses citing it); `MethodsReport.hypotheses: HypothesisCounts(leads_by_decision, hypotheses_by_state, outcomes, flags, deviations_by_kind, test_reuse, baselines_by_verdict, autonomy_agent, registry_rows)` and a rendered paragraph of fixed sentences; MCP `agent_methods` and `agent_trace` keep decision-43 withholding.

- [ ] **Step 1: Tests.** `test_each_finding_in_constructed_case` (no document text in any message), `test_trace_from_outcome_reaches_question` (acceptance 22), `test_trace_forward_from_work`, `test_methods_counts_include_refuted_and_inconclusive` (acceptance 23), `test_methods_reports_autonomy_label` (acceptance 11, 23).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(slice6): check findings, trace and methods text`.

### Task 8: Surfaces and slice acceptance

*Tier: Haiku for surfaces; acceptance test by Sonnet.*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`, `tests/test_plugin.py`; Test `tests/test_slice6_acceptance.py` (marked `slow`).

**Interfaces:**
- MCP: `registry_query(project, keys=[], reasons=None, limit=50, after=None)`; `benchmark_ledger_view(project, group_id=None)`; `hypothesis_view` extended with the latest evaluation, the specification curve and controls. Refused to pass sessions.
- CLI: `factory hypotheses evaluate HYP [--incomplete]|conclude HYP --text T`; `factory benchmark-ledger [--group G]`; `factory registry [--key K]… [--reason R]…`; `factory directions close --text T --reason R --key K… [--condition K=V]…`.

- [ ] **Step 1: Tests.** Surfaces: tool list pinned; no tool writes an evaluation. Acceptance (`slow`): one fixture project runs the spec's pilot flow with constructed runs — vocabulary, two method cards (one imported), a problem description, `match_query` with one transfer row, a conflict and a gap, a lead citing the match row, a draft, an independent critic review, human registration, a design with one baseline and a two-axis multiverse, freeze, reproduction runs, unlock, primary runs, evaluation (refuted), registry row, lead `prior` of a second lead lists it; then `factory rebuild` gives the same state hash; the differential test (evidence report, `final_rows`, `live_claims`, PRISMA counts byte-identical with and without slice-6 events) passes (acceptance 20, 24, 25 in fixture form).
- [ ] **Step 2:** `uv run pytest -m "slow" tests/test_slice6_acceptance.py` and the dev suite — FAIL. **Step 3:** Implement surfaces; fix any integration gap found. **Step 4:** Full suite including `slow`; mypy; ruff; coverage. **Step 5:** Commit `test(slice6): end-to-end acceptance and surfaces`.

## Self-review notes

- **Spec coverage.** Rulings 16, 17, 22, 23, 25, 26, 27; acceptance 15 (Task 2), 18 (Tasks 1–3), 19 (Task 4), 20 (Tasks 5, 8), 21 (Task 6), 22–23 (Task 7), 24–25 (Task 8; the real-run pilot is a researcher activity after build).
- **Rulings record.** When built, Task 8's commit adds one *Proposed* decision collecting the slice-6 spec rulings and the plan rulings of H-A–XP-B, as earlier slices did.
- **Tiers.** Tasks 1–3 and 6 critical; 4, 5, 7 standard (trace reviewed as critical); 8 Haiku/Sonnet.

## Later (not v1)

None: every task of this plan is in v1.

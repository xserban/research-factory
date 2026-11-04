# Experiment Designs, Runs, Result Ingestion and Baseline Reproduction Implementation Plan (slice 6, sub-plan XP-A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** This plan is XP-A (draft XP-A; slice 7b uses XP-A for exports). `may_pass` takes slice-M gate ids: `experiments.freeze_unlock` (freeze and unlock), `experiments.accept_baseline` (draft `baseline-acceptance`). The design budget's names are `compute-budget-*`. Bumps `PROJECTION_VERSION` by one from the value it finds.

> **Dependencies.** H-C merged (Interfaces consumed exactly: `HypothesisSpec`, `hypothesis_view`, `may_pass`, `effective_plan`, `has_confirmatory_evidence` provider hook, `GateName`); plan 2E merged (`final_rows`, `EvidenceRow`, `group_id`). The platform executes nothing in this plan: runs are executed by the researcher or a runner outside, and their output enters through the CLI. When slice M lands, `design-freeze`, `confirmatory-unlock` and `baseline-acceptance` are declared as module gates; when slice 5 adds GPU runners, they are `system` actors that call the same ingestion service.

**Goal:** Record an experiment design that pre-registers everything that decides the outcome (factor, configuration, seeds, multiverse, ablations, controls, baselines, datasets and split roles, metrics, budget, code and environment), fix it by hash, register planned runs against its cells, ingest machine-written results with their provenance, and enforce the order baselines → unlock → confirmatory runs, the test-access limit and the budget, recording every departure as a deviation.

**Architecture:** Pure design validation and cell enumeration in `factory/hypotheses/design.py`; event families `experiment.*`, `xrun.*`, `baseline.evaluated` in `model/experiments.py`, folded by `index/experiments.py`. `services/experiments.py` (design, amend, freeze, unlock, deviations, accept-baseline), `services/xruns.py` (register, ingest, accounting), `services/reproduction.py` (baseline verdicts written as `system` events). Budget, access counts and states are computed on read.

**Tech Stack:** as plan D; no new dependencies. Results files are JSON validated by a pydantic model.

**Spec:** `docs/specs/slice-6-hypotheses.md` rulings 1, 18–24, 26 (declaration part); Design "Experiment designs", "Runs and results", "Evaluation, reproduction and ledger" (reproduction part); events `experiment.*`, `xrun.*`, `baseline.evaluated`; MCP `experiment_design`, `experiment_view`, `xrun_register`, `xrun_list`; CLI `experiments`, `runs`; acceptance 13–17. `01-rigour.md` R-14, R-50, R-54; R-122, R-123.

## Rulings made in this plan (recommended; [confirm])

1. **Configuration values.** `base_config`, axis values and ablation values are scalars (`str | int | bool | Decimal` as canonical strings); keys match `^[a-z0-9_.-]{1,64}$`. The run configuration is `base_config` overlaid by the universe coordinates, then the arm's change (treatment: the factor values; baseline: the base values of the factor keys; ablation: one key; control: declared overrides), then `seed`. `config_hash = sha256(canonical JSON)[:16]`. [confirm]
2. **Factor.** `factor: dict[key, (baseline_value, treatment_value)]`; at least one key; factor keys may not be axes. [confirm]
3. **Cells.** A cell is (universe coordinates, seed, arm, split). Primary cells: primary universe × declared seeds × {treatment, baseline} × confirmatory split. Reproduction cells: per baseline row, seeds × `reproduction:<row_key>` × the split matching the reported setting (declared per baseline). [confirm]
4. **`E@`.** Hashed: every field except `notes`; `E@` = `"E@" + sha256(canonical JSON)[:8]`. One live design per hypothesis; a new design for the same hypothesis supersedes an unfrozen one only. [confirm]
5. **Results file schema v1.** `{"schema": 1, "run": "xrn_…", "metrics": {name: {"value": str, "unit": str|null}}, "compute": {"gpu_hours": str, "wall_clock_s": int, "hardware": str}, "exit_status": int, "code_commit": str, "environment": str, "nonce": str|null, "tracker_run": str|null, "artifacts": [{"name": str, "sha256": str, "uri": str}]}`; at most 64 KiB; stored as a git blob (spec ruling 20). [confirm]
6. **Runner identity.** `Actor(kind="system", id="runner-<name>", user=<settings.user>, session=<CLI session>)` when `--runner NAME` is given; otherwise the human actor. [confirm]
7. **Reproduction verdict.** Reproduced value = mean over the completed reproduction runs of the primary metric (canonical decimals, 6 places); `reproduced` if `|reproduced − reported| ≤ tolerance` (absolute in the metric unit, or relative to `|reported|`); verdict written once all declared seeds for that baseline have a completed run; a later run does not change it (spec: no best-of-n). [confirm]
8. **Unlock preconditions.** Hypothesis `registered`; design frozen and its `hypothesis` equal; every baseline verdict `reproduced` or `accepted` (human `baseline-acceptance` under the gate policy, recorded with a deviation); the design's `controls` present in systematic mode. The nonce is 128 random bits (`secrets.token_hex(16)`), stored in the `experiment.unlocked` event. [confirm]
9. **Budget accounting.** Used GPU-hours = sum over reported runs (failed runs included); `max_runs` counts registered runs; a registration beyond `max_runs` is refused; reported hours above the budget write an automatic `experiment.deviation_recorded` (kind `budget-overrun`, system actor) once. [confirm]

## Global Constraints

- The platform never calls a model and never executes experiment code; no subprocess runs a user command.
- Agents may draft and amend designs before freeze and register planned runs; they never freeze, unlock, accept a baseline or ingest results (spec ruling 19; MCP has no such tool).
- Every agent-written event carries model, skill reference and `input_blob`; runner events carry the `system` runner actor and the results blob ref.
- Results files and their artifacts lists are stored as blobs; checkpoints and logs are referenced by sha256 and URI only (decision 39 pattern).
- Invalid input writes nothing and returns structured errors.
- TDD; `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff; coverage ≥ 90% for `services/` and `model/`.

## Review Focus

1. A confirmatory run cannot be registered and a confirmatory result cannot be ingested before unlock; a result with a wrong nonce is refused (Task 5, `test_order_enforced`).
2. Amending a frozen design is refused; the change goes through `deviation` and, after unlock, flags the design `deviated` when marked semantic (Task 2, `test_frozen_design_only_deviates`).
3. A second confirmatory result for the same primary cell is ingested, recorded as a deviation and counted as test reuse — never dropped (Task 5, `test_second_access_is_deviation`).
4. A run whose commit or environment differs from the design is recorded with `environment-differs` (Task 4, `test_environment_differs_recorded_not_dropped`).
5. Reproduction verdict on the boundary of the tolerance (equal is `reproduced`) and with relative tolerance on a negative-better metric (Task 6, `test_tolerance_boundary`).

## File Structure

- Create `factory/hypotheses/design.py`, `model/experiments.py`, `index/experiments.py`, `services/experiments.py`, `services/xruns.py`, `services/reproduction.py`, `plugin/skills/rf-experiment/SKILL.md`.
- Modify `events/catalog.py`, `index/default.py`, `services/hypotheses.py` (register the `has_confirmatory_evidence` provider), `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- Tests: `test_design_rules.py`, `test_experiments_model.py`, `test_experiments.py`, `test_xruns_register.py`, `test_xruns_ingest.py`, `test_unlock_access_budget.py`, `test_reproduction.py`, `test_mcp_experiments.py`, `test_cli_experiments.py`; helper `tests/experiment_helpers.py` (H-C project with a registered experiment hypothesis, a plan-E final row as baseline, a design builder `design(...)`, and `results_file(run, metrics=..., nonce=...)` writing a JSON file to `tmp_path`).

---

### Task 1: Design model, validation and cell enumeration

*Tier: critical (pre-registration content and hash).*

**Files:** Create `factory/hypotheses/design.py`, `model/experiments.py` (design part); Test `tests/test_design_rules.py`.

**Interfaces:**
- Consumes: `StrictModel`, `UnitFamily`, `MetricSpec`, `HYP_ID_RE`, `strip_prose`.
- Produces (`model/experiments.py`): `EXP_ID_RE = rf"^exp_{ULID_RE}$"`, `E_VERSION_RE = r"^E@[0-9a-f]{8}$"`, `XRUN_ID_RE = rf"^xrn_{ULID_RE}$"`; `SplitRole = Literal["dev", "confirmatory"]`; `Dataset(name, version, sha256, role: SplitRole)`; `DesignMetric(name, direction, unit_family, unit, primary: bool)`; `Ablation(name, key, value)`; `Control(name, kind: Literal["positive", "negative"], overrides: dict[str, str], expect: Literal["effect", "no-effect"])`; `Baseline(row_key, tolerance: str, tolerance_kind: Literal["absolute", "relative"] = "relative", split: SplitRole = "confirmatory")`; `Budget(gpu_hours: str, per_run_gpu_hours: str, max_runs: int)`; `ExperimentDesign(StrictModel)`: `hypothesis`, `factor: dict[str, tuple[str, str]]`, `base_config: dict[str, str]`, `code: CodeRef(uri, commit)`, `environment: str`, `datasets: tuple[Dataset, ...]`, `metrics: tuple[DesignMetric, ...]`, `seeds: tuple[int, ...]`, `axes: dict[str, tuple[str, ...]] = {}`, `primary_universe: dict[str, str] = {}`, `ablations: tuple[Ablation, ...] = ()`, `controls: tuple[Control, ...] = ()`, `baselines: tuple[Baseline, ...] = ()`, `budget: Budget`, `test_access_limit: int | None = None` (None = plan default), `notes: str = ""`.
- Produces (`factory/hypotheses/design.py`): `MAX_UNIVERSES = 256`; `design_issues(d: ExperimentDesign, *, min_seeds: int) -> list[ValidationIssue]` (exactly one primary metric; `len(seeds) ≥ min_seeds`, unique; product of axis lengths ≤ 256 (`axes`, `too-many-universes`); `primary_universe` keys equal axis keys and values in axes; factor keys disjoint from axes and present in `base_config`; each ablation key in `base_config` and its value differs from base (`ablations.<i>`, `not-one-key`); control overrides not touching factor keys; exactly one confirmatory dataset per name at most; datasets non-empty with at least one `confirmatory`); `universes(d) -> Iterator[dict[str, str]]` (sorted product); `Arm = str` (`treatment`, `baseline`, `ablation:<name>`, `control:<name>`, `reproduction:<row_key>`); `Cell(universe: tuple[tuple[str, str], ...], seed: int, arm: Arm, split: SplitRole)`; `cell_hash(cell) -> str`; `run_config(d, cell) -> dict[str, str]` (ruling 1); `config_hash(config) -> str`; `primary_cells(d) -> list[Cell]`; `reproduction_cells(d) -> list[Cell]`; `design_version(d) -> str` (ruling 4).

- [ ] **Step 1: Tests.** `test_too_many_universes_rejected` (acceptance 13), `test_ablation_must_change_one_key` (acceptance 13), `test_min_seeds_by_plan`, `test_primary_universe_in_product`, `test_factor_not_axis`, `test_run_config_overlay_order`, `test_primary_cells_count` (`len == seeds × 2` for one universe), `test_e_version_ignores_notes_and_changes_with_seed_list` (acceptance 13), `test_config_hash_independent_of_key_order`.
- [ ] **Step 2:** `uv run pytest -m "not network and not slow" tests/test_design_rules.py` — FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(experiments): design model, validation, cells and E@`.

### Task 2: Design events, amendments, freeze and deviations

*Tier: critical (events, gate).*

**Files:** Modify `model/experiments.py`; Create `index/experiments.py`, `services/experiments.py`; Modify `events/catalog.py`, `index/default.py`; Test `tests/test_experiments_model.py`, `tests/test_experiments.py`.

**Interfaces:**
- Consumes: Task 1; `hypothesis_view`, `may_pass`, `effective_plan`, `final_rows`.
- Produces: payloads `ExperimentDesigned(experiment_id, design, e_version, supersedes)`, `ExperimentAmended(experiment_id, design, e_version, reason, semantic: bool)`, `ExperimentFrozen(experiment_id, e_version, policy, autonomy)`, `DeviationRecorded(experiment_id, kind: Literal["planned-change-after-freeze", "budget-overrun", "test-reuse", "baseline-accepted", "environment", "other"], text, semantic: bool, after_unlock: bool)`; tables `experiments(experiment_id pk, hypothesis, e_version, design_json, state, supersedes, superseded_by, frozen_event_id, unlocked_event_id, nonce, event_id)`, `experiment_deviations(event_id pk, experiment_id, kind, semantic, after_unlock)`; services `design_experiment(project, actor, design, *, supersedes=None) -> tuple[str, str]` (hypothesis kind `experiment` and state `draft|reviewed|registered`; baselines resolve to final rows whose comparability values equal the hypothesis `conditions` (`baselines.<i>.row_key`, `conditions-differ`); `design_issues`; one live design per hypothesis), `amend_experiment(project, actor, experiment_id, design, reason, semantic) -> str` (refused after freeze: `experiment_id`, `frozen`), `freeze_experiment(project, actor, experiment_id) -> str` (`may_pass(..., "design-freeze", proposer_sessions={designer sessions})`), `record_deviation(project, actor, experiment_id, kind, text, semantic) -> str` (human, or system for automatic kinds); `ExperimentState = Literal["draft", "frozen", "unlocked", "superseded"]`; `ExperimentView(experiment_id, hypothesis, e_version, design, state, deviations: list[DeviationView], flags: tuple[str, ...], budget: BudgetView, access: dict[str, int], event_id)` (flag `deviated` when any semantic deviation after unlock); `experiment_view(project, experiment_id) -> ExperimentView | None`.

- [ ] **Step 1: Tests.** Model: `test_design_event_roundtrip`, `test_deviation_kinds`. Service: `test_baseline_conditions_must_match` (acceptance 13), `test_one_live_design_per_hypothesis`, `test_amend_before_freeze_changes_e_version`, `test_frozen_design_only_deviates` (Review Focus 2), `test_pilot_agent_cannot_freeze`, `test_literature_hypothesis_refused`, `test_rebuild_state_hash_stable`, `test_projection_version_bumped`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(experiments): design events, amendments, freeze, deviations`.

### Task 3: Run registration

*Tier: critical.*

**Files:** Modify `model/experiments.py`, `index/experiments.py`; Create `services/xruns.py` (registration part); Test `tests/test_xruns_register.py`.

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: payload `XrunRegistered(run_id, experiment_id, e_version, cell: Cell, cell_hash, config: dict[str, str], config_hash, exploratory: bool)`; table `xruns(run_id pk, experiment_id, e_version, cell_hash, arm, split, seed, universe_json, config_hash, exploratory, reported_event_id, exit_status, gpu_hours, env_differs, nonce_ok, event_id)` (index `(experiment_id, cell_hash)`); `register_run(project, actor, experiment_id, cell: Cell) -> str` (design must be frozen; a cell outside the design's cells is accepted only on the `dev` split and marked `exploratory = True` (post hoc ablations, IDEA-17); a cell on the confirmatory split requires the experiment `unlocked` (Task 5) — `split`, `locked`; `max_runs` (ruling 9) — `experiment_id`, `max-runs`); `xrun_list(project, experiment_id, *, arm=None, split=None) -> list[XrunView]` with `XrunView(run_id, cell, config_hash, state: Literal["planned", "completed", "failed"], exploratory, flags, event_id)`.

- [ ] **Step 1: Tests.** `test_register_requires_frozen_design`, `test_config_computed_by_platform` (an input `config` is a structured error), `test_unplanned_dev_cell_is_exploratory`, `test_unplanned_confirmatory_cell_refused`, `test_max_runs_refused` (acceptance 16), `test_agent_may_register_planned_run`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(experiments): run registration against planned cells`.

### Task 4: Result ingestion

*Tier: critical (numbers enter the record here).*

**Files:** Modify `model/experiments.py`, `index/experiments.py`, `services/xruns.py`; Test `tests/test_xruns_ingest.py`.

**Interfaces:**
- Consumes: `project.blobs.put`, Tasks 1–3, plan-D unit canonicalisation.
- Produces: `ResultsFile(StrictModel)` (ruling 5); payload `XrunReported(run_id, results_blob, metrics: dict[str, CanonicalValue], gpu_hours: str, exit_status: int, code_commit, environment, nonce: str | None, tracker_run: str | None, artifacts: tuple[ArtifactRef, ...], flags: tuple[str, ...])` with flags `environment-differs`, `failed`; `ingest_results(project, actor, path: Path, *, runner: str | None = None) -> str` (actor must be human or a runner system actor (ruling 6); the file's `run` must be a registered, unreported run (`run`, `already-reported` — a re-run is a new run); every design metric present with a unit of its family (`metrics.<name>`, `missing` / `unit-invalid`), no undeclared metric; size ≤ 64 KiB; `exit_status ≠ 0` → recorded with flag `failed` and metrics optional; commit or environment different → flag `environment-differs`; the raw bytes stored with `blobs.put` and referenced).

- [ ] **Step 1: Tests.** `test_ingest_stores_blob_and_canonical_metrics`, `test_missing_or_undeclared_metric_refused`, `test_agent_actor_refused` (spec ruling 19), `test_runner_actor_recorded`, `test_failed_run_recorded_and_counted`, `test_environment_differs_recorded_not_dropped` (Review Focus 4; acceptance 15), `test_second_report_for_run_refused`, `test_oversized_file_refused`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(experiments): results-file ingestion with runner provenance`.

### Task 5: Unlock, nonce, test access and budget

*Tier: critical (R-50 order).*

**Files:** Modify `model/experiments.py`, `index/experiments.py`, `services/experiments.py`, `services/xruns.py`, `services/hypotheses.py`; Test `tests/test_unlock_access_budget.py`.

**Interfaces:**
- Consumes: Tasks 2–4; Task 6's `baseline_verdicts` (Task 5 is written against a stub returning `{}` and completed after Task 6; or do Task 6 first — the order in this plan is 5 then 6 with the stub); `may_pass`.
- Produces: payload `ExperimentUnlocked(experiment_id, e_version, nonce, policy, autonomy)`; `unlock_experiment(project, actor, experiment_id) -> str` (ruling 8; reasons `hypothesis-not-registered`, `not-frozen`, `baseline-unresolved`, `controls-missing`); ingestion of a confirmatory-split run requires `nonce == unlock nonce` (`nonce`, `nonce-mismatch`); `access_counts(project, experiment_id) -> dict[str, int]` (primary cell hash → confirmatory completed runs); a confirmatory result for a primary cell already at `test_access_limit` is ingested and writes `experiment.deviation_recorded(kind="test-reuse")` (system actor); `BudgetView(gpu_hours_budget, gpu_hours_used, runs_registered, max_runs, over: bool)`; `budget_view(project, experiment_id) -> BudgetView`; automatic `budget-overrun` deviation (ruling 9); `has_confirmatory_evidence` provider registered with H-C (true when any confirmatory result exists for the hypothesis's live design).

- [ ] **Step 1: Tests.** `test_order_enforced` (Review Focus 1; acceptance 14), `test_wrong_nonce_refused` (acceptance 14), `test_second_access_is_deviation` (Review Focus 3; acceptance 14), `test_budget_overrun_writes_one_deviation` (acceptance 16), `test_unlock_requires_controls_in_systematic`, `test_pilot_agent_cannot_unlock`, `test_has_confirmatory_evidence_blocks_revision` (H-C ruling 6 end to end).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(experiments): confirmatory unlock with nonce, access limit and budget`.

### Task 6: Baseline reproduction verdicts and acceptance

*Tier: critical (reproduce before confirm).*

**Files:** Create `services/reproduction.py`; Modify `model/experiments.py`, `index/experiments.py`, `services/experiments.py`; Test `tests/test_reproduction.py`.

**Interfaces:**
- Consumes: `final_rows` (reported canonical value of `row_key`), Tasks 3–4, `may_pass(..., "baseline-acceptance")`.
- Produces: payload `BaselineEvaluated(experiment_id, row_key, reported: str, reproduced: str | None, runs: tuple[str, ...], tolerance, tolerance_kind, verdict: Literal["reproduced", "not-reproduced", "no-runs-completed"], evaluator_version: str)`, `BaselineAccepted(experiment_id, row_key, rationale)`; table `baseline_evaluations(experiment_id, row_key, verdict, reproduced, reported, accepted_event_id, event_id; pk experiment_id, row_key)`; `evaluate_baselines(project, experiment_id) -> list[str]` (system actor; writes a verdict for each baseline whose declared seeds all have a reported reproduction run and that has no verdict yet; ruling 7; failed runs make the verdict `not-reproduced` only when every seed failed, otherwise the failed seeds are excluded and listed); called automatically after each ingestion of a reproduction run; `accept_baseline(project, actor, experiment_id, row_key, rationale) -> str` (gate `baseline-acceptance`; writes `BaselineAccepted` and a `baseline-accepted` deviation); `baseline_verdicts(project, experiment_id) -> dict[str, Literal["reproduced", "not-reproduced", "accepted", "pending"]]`.

- [ ] **Step 1: Tests.** `test_reproduced_within_tolerance` (acceptance 17), `test_not_reproduced_outside` (acceptance 17), `test_tolerance_boundary` (Review Focus 5), `test_verdict_written_once_no_best_of_n`, `test_unlock_refused_until_resolved` (acceptance 17), `test_acceptance_writes_deviation_and_unblocks`, `test_verdict_is_system_event`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement; replace Task 5's stub. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(experiments): baseline reproduction verdicts and human acceptance`.

### Task 7: MCP tools, CLI and the `rf-experiment` skill

*Tier: Haiku implement and review (surfaces); the skill by Sonnet.*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`, `tests/test_plugin.py`; Create `plugin/skills/rf-experiment/SKILL.md`; Test `tests/test_mcp_experiments.py`, `tests/test_cli_experiments.py`, extend `tests/test_skills.py`.

**Interfaces:**
- MCP: `experiment_design(project, design: dict, supersedes=None, amend_of=None, reason=None, semantic=False, role, model, skill)` -> `{experiment_id, e_version, issues}`; `experiment_view(project, experiment_id)` (the nonce is never returned to agents); `xrun_register(project, experiment_id, cell: dict, role, model, skill)` -> run id; `xrun_list(project, experiment_id, arm=None, split=None)`. All refused to screening and extraction pass sessions. No MCP tool freezes, unlocks, ingests, accepts or records deviations.
- CLI: `factory experiments show EXP|freeze EXP|unlock EXP|deviation EXP --kind K --text T [--semantic]|accept-baseline EXP ROW --rationale T`; `factory runs list EXP|record FILE [--runner NAME]`; `factory experiments unlock` prints the nonce once, for the runner configuration.
- Skill `rf-experiment`: write a design for a registered hypothesis with one factor, the plan's minimum seeds, a declared primary universe, ablations that each remove one component, controls, baselines as evidence rows, a budget; register runs for planned cells; never type a result; ask the researcher to freeze, unlock and record results; state any post hoc analysis as exploratory.

- [ ] **Step 1: Tests.** Tool list pinned with four names and none of `*_freeze`, `*_unlock`, `*_record`, `*_accept`; `experiment_view` over MCP omits the nonce; CLI `runs record` with `--runner gpu1` writes a system actor `runner-gpu1`; skill names its tools and "never type a result"; `SKILLS` includes `rf-experiment`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(experiments): MCP tools, CLI and rf-experiment skill`.

## Self-review notes

- **Spec coverage.** Rulings 1, 18–24 and 26 (declaration and unlock check); acceptance 13 (Tasks 1–2), 14 (Task 5), 15 (Task 4; pairing is XP-B), 16 (Tasks 3, 5), 17 (Task 6). Statistics, evaluation, multiverse summaries, control outcomes, ledger and registry are XP-B.
- **Types used later.** `ExperimentDesign`, `Cell`, `cell_hash`, `primary_cells`, `universes`, `run_config`, `ExperimentView`, `experiment_view`, `XrunView`, `xrun_list`, `access_counts`, `budget_view`, `baseline_verdicts`, tables `experiments`, `xruns`, `baseline_evaluations`, `experiment_deviations`.
- **Tiers.** Tasks 1–6 critical; 7 Haiku (skill Sonnet).

## Later (not v1)

None: every task of this plan is in v1.

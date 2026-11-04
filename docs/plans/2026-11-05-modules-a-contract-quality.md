# Module Contract, Registries and Quality-Code Deduplication Implementation Plan (slice M, sub-plan M-A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Build position: after G2 (A–E) and G3 (A–C) are merged (build-order constraint), so the conditional clauses on G2-A resolve to "present": Task 5 registers `contrib_a`/`contrib_b`, and Task 6 also declares `contributions` (`miner`), `lineage` and `intuition` (`proposal`) with their gates (`lineage.relation_confirm`, `lineage.idea_confirm`, `intuition.review`, `intuition.source_approve`, `intuition.uses_confirm`), folding slice-M migration step 6 into this plan; it also declares every other module present on its base. Module kinds are the closed list of slice-M ruling 5 (reconciliation item 2). No projection change.

> **Dependencies.** Branch from `main` after plans 2C, 2D, 2E and the clean-ups plan (`2026-11-05-cleanups.md`) are merged; Task 7 of the clean-ups touches `services/audit.py` and must land first. G1 and G2-A may be merged or not: Tasks 2, 3 and 5 name the G2-A symbols (`Scope`, `contrib_a`/`contrib_b`) conditionally, and Task 6 declares the contribution kinds only when `contrib_a` exists in the code. Plans M-B to M-E consume this plan's Interfaces blocks exactly.

**Goal:** Remove the duplicated quality code (pass-session membership, independence refusal, audit lifecycle, statistics, task-kind tables), introduce the stage-module contract as pure declarations with a registry whose ownership tests cover every event type, task kind, protocol section and check code, and compose `check` from module hooks with byte-identical output.

**Architecture:** Pure declarations in `factory/modules/` (no I/O, no service imports) and pure statistics in `factory/quality/`; shared service code in `services/passes.py` and `services/audit_core.py`; concrete module declarations in `services/modules/` bind existing service functions to the contract. Existing modules keep their public names as thin delegations, so call sites outside the edited files are unchanged.

**Tech Stack:** Python 3.11, pydantic, SQLAlchemy, pytest; no new dependencies.

**Spec:** `docs/specs/slice-M-modules.md` rulings 1–5 and 21; migration steps 0–3; acceptance 1–4. `docs/specs/00-system.md` §4, §7; decisions 37, 43, 48, 50, 51.

## Rulings made in this plan

1. **Re-export, do not rename [confirm].** `services/screening_stats.py` keeps every public name (re-exported from `factory/quality/stats.py`), and the old private helpers become one-line delegations, so no test edits are needed. Delegations are removed in a later clean-up, not here.
2. **Membership of any module at human-act surfaces [confirm].** As spec ruling 21: a session that joined an extraction pass is refused when relaying a screening calibration label, resolution or audit label. New tests pin it; no existing test is edited.
3. **Check order is module order [confirm].** `check._hits` iterates the registry in declaration order; the registry lists modules so that the hit order equals today's `_hits` order (core, scoping, retrieval, screening, chase, full text, extraction, evidence). The rule functions stay in `services/check.py` this plan; modules reference them. Moving them into per-module files is optional later work.

## Global Constraints

- The platform never calls a model. Events are the source of truth; the projector alone writes the index. This plan adds no event type and changes no projection (`PROJECTION_VERSION` unchanged).
- Every pre-existing test passes without edits. Each new test is written first and seen failing, except Task 1 (a pure move: the suite is the test).
- `factory/modules/` and `factory/quality/` import nothing from `services/`, `index/`, `mcp/` or `cli/` (an import-linter style test enforces it).
- `uv run pytest -m "not network and not slow"`, `uv run mypy --strict src`, `uv run ruff check` and `ruff format --check` pass after each task; coverage ≥ 90 % for `services/` and `model/`.

## Review Focus

1. No behaviour change except ruling 2 (Task 2, `test_extraction_session_cannot_relay_screening_label`).
2. The independence refusal still reads extraction joins from the log and screening joins from the table (Task 2, `test_refuse_shared_extraction_reads_log_joins`).
3. `check` output is byte-identical on the acceptance projects (Task 7, `test_check_byte_identical_on_fixture_projects`).
4. Ownership is exhaustive: adding an event type to the catalog without a module fails a test (Task 6, `test_unowned_event_type_fails`).

## File Structure

- Create `src/factory/quality/__init__.py`, `quality/stats.py`; `src/factory/modules/__init__.py`, `modules/contract.py`, `modules/registry.py`; `src/factory/services/passes.py`, `services/audit_core.py`; `src/factory/services/modules/__init__.py` and one file per declared module (`core.py`, `scoping.py`, `retrieval.py`, `dedup.py`, `screening.py`, `fulltext.py`, `conversion.py`, `extraction.py`, `evidence.py`, `references.py`).
- Modify `services/screening_stats.py`, `services/agreement.py`, `services/audit.py`, `services/calibration.py`, `services/screening.py`, `services/extraction.py`, `services/extraction_agreement.py`, `services/extraction_audit.py`, `services/stages.py`, `services/check.py`, `mcp/server.py` (`_refuse_pass_session` only), `cli/main.py` (`factory modules`).
- Tests: `tests/test_quality_stats.py`, `tests/test_passes.py`, `tests/test_audit_core.py`, `tests/test_module_contract.py`, `tests/test_task_kinds.py`, `tests/test_registry_ownership.py`, `tests/test_check_composition.py`, `tests/test_cli_modules.py`.

---

### Task 1: Pure statistics move to `factory/quality/stats.py`

*Tier: mechanical (implementer haiku, review haiku).*

**Files:** Create `quality/__init__.py`, `quality/stats.py`; Modify `services/screening_stats.py`; Test `tests/test_quality_stats.py`.

**Interfaces:**
- Consumes: `services/screening_stats.py` as at base.
- Produces (`factory/quality/stats.py`): `Rates`, `AuditRates`, `cohen_kappa(pairs) -> float | None`, `kappa_by_criterion(...)`, `sensitivity_specificity(pairs) -> Rates`, `audit_size(population: int, fraction: float, minimum: int) -> int`, `draw_audit(exclusions, inclusions, n, rng) -> list[str]`, `draw_uniform(items: Sequence[T], size: int, seed: int, key: Callable[[T], Any]) -> list[T]`, `audit_error_rates(rows, pop_exclusions, pop_inclusions) -> AuditRates`, `EXCLUSION_SHARE`. `services/screening_stats.py` re-exports all and keeps `AUDIT_ERROR_CEILING`, `CALIBRATION_SENSITIVITY`, `quote_in` (they depend on `RigorMode` and screening text).

- [ ] **Step 1: Test.** `test_reexports_are_identical`: `screening_stats.cohen_kappa is quality.stats.cohen_kappa` (and each moved name); `test_draw_uniform_matches_extraction_draw`: for 20 seeds, `draw_uniform(items, k, seed, key=_sort_key)` equals `extraction_audit._draw(items, k, seed)`.
- [ ] **Step 2:** Run `uv run pytest tests/test_quality_stats.py -q`; FAIL (module missing).
- [ ] **Step 3:** Move the bodies; add `draw_uniform` as the body of `extraction_audit._draw` generalised by `key`; make `_draw` delegate.
- [ ] **Step 4:** `uv run pytest -m "not network and not slow" -q`; mypy; ruff. Expected: PASS.
- [ ] **Step 5:** Commit `refactor(quality): pure statistics in factory.quality.stats`.

### Task 2: One pass-membership service and one independence rule

*Tier: critical (independence, decision 37).*

**Files:** Create `services/passes.py`; Modify `services/agreement.py`, `services/audit.py`, `services/calibration.py`, `services/screening.py`, `services/extraction.py`, `services/extraction_agreement.py`, `services/extraction_audit.py`, `mcp/server.py`; Test `tests/test_passes.py`.

**Interfaces:**
- Consumes: tables `pass_sessions(session, pass_label, stage, model)` and `extraction_sessions(session, pass_label, scope, model)`; `PassLabel`, `ScreeningStage`.
- Produces (`services/passes.py`):
  - `@dataclass(frozen=True) PassMembership(module: Literal["screening", "extraction"], scope: str | None, stage: str | None, label: PassLabel)`;
  - `memberships(project: Project, session: str) -> frozenset[PassMembership]` (syncs the index; one query per table);
  - `is_pass_session(project: Project, session: str, *, module: str | None = None, stage: ScreeningStage | None = None) -> bool`;
  - `shared_refusal(sessions: Mapping[PassLabel, set[str]], models: Mapping[PassLabel, set[str]], *, noun: str) -> FactoryValidationError | None` (pure; message texts exactly as today: `"a session has joined both passes; each pass needs its own session"`, `"the passes share a model (…); each pass needs its own"` for screening, the extraction texts for `noun="extraction"`);
  - `require_not_pass_session(project: Project, actor: Actor, channel: Channel, *, field: str = "channel", reason: str) -> list[ValidationIssue]` (MCP relays only).
- Delegations: `agreement._is_pass_session`, `audit._is_pass_session`, `calibration.is_pass_session`, `extraction.is_extraction_session`, `extraction.screening_session`, `screening._is_extraction_session` become one-line calls to `is_pass_session`; `agreement._refuse_shared_sessions/_refuse_shared_models` and `extraction_agreement._refuse_shared` collect as today and raise `shared_refusal(...)`. Human-act relays (calibration label, disagreement resolution, screening audit label, extraction resolution, extraction audit label) ask `is_pass_session(project, session)` with no module (ruling 2).

- [ ] **Step 1: Tests.**
```python
def test_memberships_cover_both_tables(): ...          # screening TA pass A + extraction pass B -> two memberships
def test_is_pass_session_filters_by_stage_and_module(): ...
def test_shared_refusal_messages_unchanged():
    err = shared_refusal({A: {"s1"}, B: {"s1"}}, {A: set(), B: set()}, noun="screening")
    assert err.issues[0].reason == "a session has joined both passes; each pass needs its own session"
def test_refuse_shared_extraction_reads_log_joins(): ...  # a second join hidden from the projection still refuses
def test_extraction_session_cannot_relay_screening_label(): ...  # ruling 2: calibration, resolution, audit, each refused, nothing written
def test_no_duplicate_helpers():
    src = {p: p.read_text() for p in SERVICES.glob("*.py")}
    assert sum("FROM pass_sessions WHERE session" in t for t in src.values()) == 1
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement; delegate. **Step 4:** Full suite unedited (decision-37, 43, 48 suites in `test_agreement.py`, `test_audit.py`, `test_calibration.py`, `test_document_read_gate.py`, `test_extraction_*`), mypy, ruff. **Step 5:** Commit `refactor(passes): one pass-membership service and one independence rule`.

### Task 3: Shared audit lifecycle (`services/audit_core.py`)

*Tier: critical (audit, decisions 37 and 51).*

**Files:** Create `services/audit_core.py`; Modify `services/audit.py`, `services/extraction_audit.py`; Test `tests/test_audit_core.py`.

**Interfaces:**
- Consumes: `population_digest` (`factory/canonical.py`), `audit_size`, `draw_audit`, `draw_uniform`, `passes.is_pass_session`.
- Produces:
  - `@dataclass(frozen=True) AuditPopulation(keys: tuple[str, ...], provenance: tuple[str, ...])` (sorted; `digest` property = `population_digest(zip(keys, provenance))`);
  - `human_gate(project: Project, actor: Actor, channel: Channel, *, noun: str) -> list[ValidationIssue]` (non-human `actor` issue; MCP relay from a pass session `channel` issue; messages per caller as today via `noun`);
  - `refuse_reopen(last_digest: str | None, population: AuditPopulation) -> None` (raises `passes` issue `"an audit of this agreed set is open; a new one waits for a change to it"`);
  - `validate_seed(random_seed: int | None) -> tuple[int, list[ValidationIssue]]`;
  - `@dataclass(frozen=True) CeilingVerdict(rate: float | None, ceiling: float, above: bool, enforced: bool)` and `ceiling_verdict(rate, ceiling, *, enforced: bool) -> CeilingVerdict`.
- `audit.audit_sample/audit_record/audit_report` and `extraction_audit.extraction_audit_sample/extraction_audit_record/extraction_audit_report` call these; their signatures, payloads and messages are unchanged.

- [ ] **Step 1: Tests.** `test_population_digest_order_independent`; `test_refuse_reopen_same_digest`; `test_human_gate_messages_per_noun` (screening and extraction texts exactly as at base); `test_validate_seed_bounds`; `test_ceiling_verdict_enforced_flag`; `test_screening_and_extraction_audits_share_core` (monkeypatch `audit_core.refuse_reopen` to record calls; both services call it).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement and delegate. **Step 4:** `test_audit.py`, `test_extraction_audit.py`, `test_acceptance_screening.py`, `test_acceptance_extraction.py` unedited; mypy; ruff. **Step 5:** Commit `refactor(audit): one audit lifecycle for screening and extraction`.

### Task 4: Contract types and registries (pure)

*Tier: critical (contract every later plan consumes).*

**Files:** Create `modules/__init__.py`, `modules/contract.py`, `modules/registry.py`; Test `tests/test_module_contract.py`.

**Interfaces:**
- Produces (`modules/contract.py`), exactly as the spec's *Core types*: `ModuleKind`, `ArtifactKind`, `GateKind`, `PolicyKind`, `Autonomy`, `GatePolicy`, `GateSpec`, `EventFamily`, `QualityRegime`, `CheckRule`, `StrategySpec`, `ModuleSpec`, `StageModule` (Protocol: `spec`, `hits(project) -> list[CheckHit]`, `methods(project) -> MethodsSection | None`, `autonomy_acts(project) -> Iterable[AutonomyAct]`), `CheckHit(code, refs, message, role=None, severity=None)` (same fields as `check._Hit`), `MethodsSection(title: str, text: str)`, `AutonomyAct(gate_id: str, event_id: str, actor_kind: str, protocol_id: str | None)`. `Project` is referenced under `TYPE_CHECKING` only.
- Produces (`modules/registry.py`): `class ModuleRegistry` with `__init__(modules: Sequence[StageModule], *, catalog_names: Iterable[str])` validating ownership (raises `RegistryError(list[str])`), `modules() -> tuple[StageModule, ...]` (declaration order), `owner_of_event(name) -> str`, `owner_of_task_kind(kind) -> str`, `owner_of_section(section) -> str`, `owner_of_check(code) -> str`, `gate(gate_id) -> GateSpec`, `levels() -> dict[str, tuple[...]]`; `class TaskKindRegistry` with `register(kind: str, module: str, *, stage: str | None, label: PassLabel, scope: str | None)`, `kind_for(module, *, stage=None, label, scope=None) -> str`, `describe(kind) -> TaskKindInfo | None`.

- [ ] **Step 1: Tests.** `test_module_spec_is_frozen`; `test_registry_rejects_duplicate_owner` (two modules owning `screening.decision_recorded` → `RegistryError` naming both); `test_registry_rejects_unknown_event` (a family naming a type outside `catalog_names`); `test_decision_gate_needs_act_events`; `test_builder_has_no_events_or_gates`; `test_miner_needs_regime`; `test_task_kind_registry_round_trip`; `test_modules_package_is_pure` (AST scan: no import of `factory.services`, `factory.index`, `factory.mcp`, `factory.cli` under `factory/modules` and `factory/quality`).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** mypy; ruff. **Step 5:** Commit `feat(modules): contract types and registries`.

### Task 5: Task kinds from the registry

*Tier: standard (implementer sonnet, review haiku).*

**Files:** Modify `services/stages.py`, `services/extraction.py`; Create `services/modules/__init__.py` (first version: `default_task_kinds() -> TaskKindRegistry`); Test `tests/test_task_kinds.py`.

**Interfaces:**
- Consumes: `TaskKindRegistry`.
- Produces: `default_task_kinds()` registering `screen_a`, `screen_b`, `screen_ft_a`, `screen_ft_b` (module `screening`, stages), `extract_a`, `extract_b` (module `extraction`, scope `evidence`) and, when G2-A is merged, `contrib_a`, `contrib_b` (scope `contribution`). `stages.task_kind`, `stages.stage_of_kind` and `stages.EXTRACT_KINDS` are derived from it (same values, same types); the literal tables are deleted.

- [ ] **Step 1: Tests.** `test_kinds_unchanged` (the eight or six strings, by key); `test_stage_of_kind_inverse`; `test_no_kind_literals_outside_registry` (grep `"screen_a"`/`"extract_a"` in `src/factory/services` finds only `services/modules/`).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full suite. **Step 5:** Commit `refactor(tasks): task kinds come from the module registry`.

### Task 6: Declarations of the built modules and ownership tests

*Tier: critical (exhaustive ownership).*

**Files:** Create `services/modules/core.py`, `scoping.py`, `retrieval.py`, `dedup.py`, `screening.py`, `fulltext.py`, `conversion.py`, `extraction.py`, `evidence.py`, `references.py`; Modify `services/modules/__init__.py` (`default_modules() -> ModuleRegistry`); Test `tests/test_registry_ownership.py`.

**Interfaces:**
- Consumes: `default_catalog()`, `ProtocolSpec.model_fields`, `check.LEVELS`.
- Produces: `default_modules() -> ModuleRegistry` with, in this order: `core` (`project.created`, `task.*`; checks `broken-link`, `missing-provenance`), `scoping` (`question.*`, `seed.*` except `seed.admitted`, `probe.*`, `protocol.*`; sections `question_id`, `method_profile`, `criteria`, `rationale`; checks `seed-missing`, `protocol-not-ready`, `press-missing`, `profile-checklist`; gate `protocol.press_confirm`; strategies `interview` (`rf-frame`), `probe` (`rf-probe`)), `retrieval` (`query.registered`, `search.*`, `chase.round_started`, `seed.admitted`, `screening.sample_extended`, `snowball.round_started`; sections `sources`, `queries`, `limits`, `snowball_plan`; checks `shortfall-unexplained`, `seed-admission-pending`, `chase-missing`), `dedup` (`dedup.*`; check `merge-verdict-conflict`), `screening` (kind `filter`; `screening.*` except `sample_extended`, `calibration.*`, `audit.*`; sections `screening`, `full_text_screening`; task kinds `screen_*`; gates `screening.calibration_label`, `screening.resolve`, `screening.audit_label`; regime two passes, `session-and-model`, `outcome`, `human-labelled`, `agreed-sample`, (`amendment`, `document-version`); checks `screening-pending`, `single-pass`, `calibration-missing`, `kappa-below-floor`, `audit-missing`, `audit-error-high`, `fulltext-decision-stale-document`), `fulltext` (`fulltext.*`; checks `library-missing`, `library-corrupt`, `source-changed`, `fulltext-unsought`), `conversion` (`document.*`), `extraction` (kind `miner`; `extraction.*` with `EventFamily.note = "historical name: every field miner writes this family (slice M ruling 2)"`; sections `extraction_schema`, `contribution_schema` when present; task kinds `extract_*`, `contrib_*`; gates `extraction.resolve`, `extraction.audit_label`; `extraction-*` checks), `evidence` (kind `builder`; checks `evidence-*`), `references` (kind `proposal`; `reference.*`, `citation.contexts_recorded`; gate `reference.link_confirm`, act event `reference.resolution_decided`). Each module's `hits` calls the existing `check._…` rule functions it owns, in today's order; `methods` returns None; `autonomy_acts` returns `()` until M-B.
- Where an event's owner is debatable (`screening.sample_extended` is written by the chase service; `seed.admitted` by seed admission), the owner is the module whose service writes it; the declaration's docstring says so.

- [ ] **Step 1: Tests.**
```python
def test_every_catalog_event_has_one_owner():
    reg = default_modules(); assert {reg.owner_of_event(n) for n in default_catalog().names()}
def test_unowned_event_type_fails(): ...       # a catalog with one extra type -> RegistryError naming it
def test_every_protocol_section_has_one_owner(): ...   # ProtocolSpec.model_fields
def test_every_check_code_has_one_owner():
    assert default_modules().levels() == check.LEVELS
def test_every_task_kind_has_one_owner(): ...
def test_gate_ids_unique_and_act_events_registered(): ...
```
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full suite; mypy; ruff. **Step 5:** Commit `feat(modules): declarations of the built modules with exhaustive ownership`.

### Task 7: `check` composed from modules; `factory modules`

*Tier: standard (implementer sonnet, review sonnet: byte-identity matters).*

**Files:** Modify `services/check.py`, `cli/main.py`, `cli/render.py`; Test `tests/test_check_composition.py`, `tests/test_cli_modules.py`.

**Interfaces:**
- Consumes: `default_modules()`.
- Produces: `check.LEVELS` is `default_modules().levels()` (a module-level constant computed once); `check._hits(project)` = concatenation of `m.hits(project)` over `default_modules().modules()`, with the shared precomputation (`final_outcomes`) passed through a per-call cache (`HitContext`), so each rule runs once as today. `factory modules [--json]` lists name, kind, events (count), task kinds, sections, gates (with floor), checks, strategies and, for `extraction`, the family note.

- [ ] **Step 1: Tests.** `test_check_byte_identical_on_fixture_projects` (for each acceptance fixture project used by `test_acceptance_slice1.py`, `test_acceptance_fulltext_screening.py`, `test_acceptance_extraction.py`, `test_acceptance_evidence.py`: render `check` before (golden file captured on the base commit, stored under `tests/fixtures/check_golden/`) and after; equal bytes); `test_check_rules_run_once` (spy on `final_outcomes`: one call per `check`); `test_cli_modules_lists_every_module`.
- [ ] **Step 2:** Capture goldens on the base commit first (a script in the test's docstring); run; FAIL on the composed version only if wrong. **Step 3:** Implement. **Step 4:** Full suite; mypy; ruff; coverage. **Step 5:** Commit `feat(check): findings composed from module declarations; factory modules`.

## Self-review notes

- **Spec coverage.** Ruling 21 (Tasks 1–3, 5), rulings 1, 3, 4, 5 (Tasks 4, 6), migration steps 0–3 (Tasks 1–7), acceptance 1 (Task 6), 2 (Tasks 2, 3, 5), 3 (no projection change), 4 (Task 7; methods unchanged because no module returns a section yet).
- **Types used later.** `ModuleSpec`, `GateSpec`, `GatePolicy`, `PolicyKind`, `Autonomy`, `AutonomyAct`, `CheckHit`, `MethodsSection`, `ModuleRegistry`, `TaskKindRegistry`, `default_modules`, `default_task_kinds`, `passes.memberships`, `passes.is_pass_session`, `passes.shared_refusal`, `audit_core.*`, `quality.stats.draw_uniform`.
- **Tiers.** Tasks 2, 3, 4, 6 critical (subagent-driven, Opus implementer, Sonnet review); 5, 7 standard; 1 mechanical.

## Later (not v1)

None: every task of this plan is in v1.

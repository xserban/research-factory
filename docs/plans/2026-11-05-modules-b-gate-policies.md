# Gate Policies, Presets, Gate Audit and Autonomy Labels Implementation Plan (slice M, sub-plan M-B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** G2-C and G3 are merged before M-A, so their gates are declared and their services call `require_gate` here. The gates of slices 3d, 4a, 4b, 6 and 7b (slice-M reconciliation table) are declared by those slices' plans when built, each adding its rows to `PRESETS` and floors in the same task. Task 5 bumps `PROJECTION_VERSION` by one from the value it finds.

> **Dependencies.** Plan M-A merged (consumes `GateSpec`, `GatePolicy`, `PolicyKind`, `Autonomy`, `AutonomyAct`, `default_modules`, `passes.is_pass_session`, `audit_core.*`). Plan G1 merged (the `reference.link_confirm` gate and `reference_resolve._confirmer`). G2-C and G3 gates are added to the preset table here as declarations only if their code exists; otherwise the G2/G3 plans call `require_gate` when they land.

**Goal:** Make "who may pass each binding decision" one declared, hashed policy: presets per rigor mode that reproduce today's behaviour, an optional amendable `gate_policies` protocol section, one `require_gate` check at every decision gate, a generic gate audit for `agent_audit` gates, `below-policy` flags after a tightening amendment, and autonomy labels computed on read.

**Architecture:** `modules/presets.py` holds the pure preset table, floors and computed-gate enforcement. `services/gates.py` resolves the effective policy under a protocol version, enforces it, lists acts from each gate's act events, computes autonomy and below-policy acts, and runs the gate audit through `audit_core`. Services that today test `RigorMode` for a gate read the preset instead.

**Tech Stack:** as M-A; no new dependencies.

**Spec:** `docs/specs/slice-M-modules.md` rulings 6–10; gate inventory table; events `gate.audit_sampled`, `gate.audit_labelled`; check findings `gate-*`; acceptance 4–8. `docs/specs/slice-3a-references.md` ruling 3 and open question 2; decisions 37 (items 4–6, 14), 50.

## Rulings made in this plan

1. **Entries sorted by gate in the hash [confirm].** `GatePolicies.entries` is sorted by `gate` before hashing (`_SORT_KEYS["gate_policies"] = ("gate",)`), so entry order never changes `P@`.
2. **Policy under the act's protocol version [confirm].** An act's effective policy is the one in force under the protocol version current when the act's event was written (the latest `protocol.recorded`/`protocol.amended` before it in ULID order). Acts before any protocol use the preset.
3. **Messages kept [confirm].** Where a service already refuses an act (for example `reference_resolve._confirmer`), it calls `require_gate` first and, when the policy permits, keeps its own finer refusals and texts; the existing tests pin them.
4. **Gate audit draws over agent acts only [confirm].** The population of a gate audit is the gate's binding acts by agents under `agent_audit`, not yet superseded; human acts are never sampled.

## Global Constraints

- All M-A constraints hold. New event types: `gate.audit_sampled`, `gate.audit_labelled` (schema 1). `PROJECTION_VERSION` bumps once (Task 5).
- A protocol without `gate_policies` keeps its `P@`; every pre-existing test passes unedited.
- Agents never see a rate, threshold or label in a gate refusal (decision 37 item 14); refusals name the gate id and the policy kind only.

## Review Focus

1. Presets reproduce today's accept/refuse behaviour at every gate in every mode (Task 2, `test_presets_reproduce_behaviour`, parametrised over gate × mode × actor kind).
2. `P@` unchanged without `gate_policies`; entry order does not change `P@` (Task 1).
3. Tightening stales no screening decision (Task 4, `test_tightening_flags_without_staling`).
4. The gate audit cannot be relayed by a pass session and refuses agents (Task 5).

## File Structure

- Create `src/factory/modules/presets.py`, `src/factory/services/gates.py`, `src/factory/model/gates.py` (events and protocol section types), `src/factory/index/gates.py`.
- Modify `model/protocol.py`, `services/protocol_rules.py`, `services/protocol.py`, `services/audit.py`, `services/extraction_audit.py`, `services/calibration.py`, `services/reference_resolve.py`, `services/modules/*.py` (`autonomy_acts`, gate checks), `services/methods.py`, `events/catalog.py`, `index/default.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- Tests: `tests/test_gate_policies_protocol.py`, `tests/test_gate_presets.py`, `tests/test_gates_service.py`, `tests/test_gate_blast_radius.py`, `tests/test_gate_audit.py`, `tests/test_autonomy.py`, `tests/test_cli_gates.py`.

---

### Task 1: `gate_policies` protocol section

*Tier: critical (protocol hash).*

**Files:** Create `model/gates.py`; Modify `model/protocol.py`, `services/protocol_rules.py`; Test `tests/test_gate_policies_protocol.py`.

**Interfaces:**
- Consumes: `PolicyKind`, `default_modules().gate(gate_id)`.
- Produces (`model/gates.py`): `GatePolicyEntry(StrictModel)`: `gate: str` (pattern `^[a-z]+\.[a-z_]+$`), `policy: PolicyKind`, `fraction: float | None` (0 < f ≤ 1), `minimum: int | None` (≥ 1); validator: both set iff `policy is AGENT_AUDIT`. `GatePolicies(StrictModel)`: `entries: tuple[GatePolicyEntry, ...]`, unique gates.
- Produces (`model/protocol.py`): `ProtocolSpec.gate_policies: GatePolicies | None = None`; added to `_OMITTED_WHEN_NONE`, `AMENDABLE_FIELDS`, `_SORT_KEYS` (ruling 1).
- Produces (`services/protocol_rules.py`): errors `gate_policies.entries.<i>.gate` (`unknown gate`), `….policy` (`below the floor of <gate>`), and readiness rules: an entry weaker than the mode's preset is an error in `systematic`, a gap in `pilot`, allowed in `exploratory`.

- [ ] **Step 1: Tests.** `test_p_id_unchanged_without_gate_policies` (pinned literal from base); `test_entry_order_does_not_change_p_id`; `test_agent_audit_needs_fraction_and_minimum`; `test_unknown_gate_refused`; `test_below_floor_refused` (`screening.resolve` → `agent`); `test_weaker_than_preset_by_mode` (systematic error, pilot gap, exploratory clean); `test_amendment_reports_gate_policies_in_other_changes`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Protocol and amendment suites unedited; mypy; ruff. **Step 5:** Commit `feat(protocol): gate_policies section with floors and preset rules`.

### Task 2: Presets and computed-gate enforcement

*Tier: critical (behaviour preservation).*

**Files:** Create `modules/presets.py`; Modify `services/audit.py`, `services/extraction_audit.py`, `services/calibration.py`, `services/reference_resolve.py`, `services/modules/*.py` (gate floors from the spec table); Test `tests/test_gate_presets.py`.

**Interfaces:**
- Produces (`modules/presets.py`): `Enforcement(StrEnum)`: `OFF`, `ADVISORY`, `ENFORCED`; `PRESETS: Mapping[RigorMode, Mapping[str, GatePolicy]]` (spec gate table); `ENFORCEMENT: Mapping[RigorMode, Mapping[str, Enforcement]]` for computed gates `protocol.ready`, `screening.calibration_sensitivity`, `screening.audit_ceiling`, `extraction.audit_ceiling`, `gate.audit_ceiling`; `preset(mode, gate_id) -> GatePolicy`; `enforcement(mode, gate_id) -> Enforcement`; `weaker(a: GatePolicy, b: GatePolicy) -> bool` (order `agent` < `agent_audit` < `human`; between two `agent_audit`, smaller fraction or minimum is weaker).
- `audit.audit_report.enforced`, `extraction_audit.extraction_audit_report.enforced` read `enforcement(mode, …) is ENFORCED`; `reference_resolve._confirmer`'s `RigorMode.PILOT` test reads `preset(mode, "reference.link_confirm").kind is AGENT_AUDIT` (M-B Task 3 replaces it with `require_gate`). `CALIBRATION_SENSITIVITY` stays as the threshold table.

- [ ] **Step 1: Tests.** `test_presets_reproduce_behaviour` (parametrised over the spec table: for each gate, mode and actor kind {human, agent}, call the real service on a fixture and compare accept/refuse with the expectation table recorded from base); `test_enforcement_matches_base` (audit and extraction-audit `enforced` per mode); `test_weaker_order`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full suite; mypy; ruff. **Step 5:** Commit `feat(gates): rigor-mode presets and computed-gate enforcement`.

### Task 3: `services/gates.py`: effective policy, `require_gate`, acts and autonomy

*Tier: critical (gate enforcement, R-51).*

**Files:** Create `services/gates.py`; Modify `services/reference_resolve.py`, `services/agreement.py` (`resolve_disagreement`), `services/calibration.py` (`label_calibration`), `services/audit.py` (`audit_record`), `services/extraction_agreement.py` (`resolve_extraction`), `services/extraction_audit.py` (`extraction_audit_record`), `services/protocol.py` (`confirm_press`), `services/modules/*.py` (`autonomy_acts`); Test `tests/test_gates_service.py`, `tests/test_autonomy.py`.

**Interfaces:**
- Consumes: `default_modules()`, `protocol_lineage`, `presets`, `passes.is_pass_session`.
- Produces:
  - `effective_policy(project, gate_id, *, protocol_id: str | None = None) -> GatePolicy` (protocol's entry, else preset of the project's mode);
  - `protocol_at(project, event_id: str) -> str | None` (ruling 2);
  - `require_gate(project, actor, gate_id, *, channel: Channel | None = None, proposer_session: str | None = None) -> GatePolicy` raising `FactoryValidationError` with field `actor` (`"gate <id> is <policy>: an agent cannot pass it"`), `session` (proposer: `"the proposer cannot pass gate <id>"`), `channel` (relay from a pass session);
  - `@dataclass(frozen=True) GateAct(gate_id, event_id, actor_kind, session, protocol_id, superseded: bool)`; `gate_acts(project, gate_id) -> Iterator[GateAct]` (SQL over `events` by `type IN act_events`, ULID order; binding filter supplied by the module's `autonomy_acts`);
  - `autonomy_of(project, act) -> Autonomy` (spec ruling 10; `audited-agent` needs a drawn gate audit whose population contains the act; until Task 5 lands, `agent_audit` acts are `agent`);
  - `autonomy_counts(project, gate_id) -> dict[Autonomy, int]`.
- Every decision-gate service calls `require_gate` before its own checks (ruling 3).

- [ ] **Step 1: Tests.** `test_require_gate_refuses_agent_at_human_gate` (each human-floor gate: agent refused, nothing written); `test_pilot_second_agent_link_confirm_still_allowed`; `test_proposer_cannot_pass`; `test_effective_policy_follows_amendment`; `test_policy_of_act_is_policy_at_its_time` (an act before an amendment keeps the old policy); `test_autonomy_human_after_agent_proposal`; `test_autonomy_counts_per_gate`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full suite unedited (messages pinned); mypy; ruff. **Step 5:** Commit `feat(gates): effective policy, require_gate, acts and autonomy`.

### Task 4: Tightening blast radius (`below-policy`)

*Tier: critical (amendments, decision 50).*

**Files:** Modify `services/gates.py`, `services/modules/core.py` (check `gate-below-policy`); Test `tests/test_gate_blast_radius.py`.

**Interfaces:**
- Produces: `below_policy(project) -> list[GateAct]`: acts whose actor kind the *current* effective policy of their gate would refuse (agent act at a now-`human` gate; agent act at a now-`agent_audit` gate under former `agent` is not below policy but enters the audit population); check rule `CheckRule("gate-below-policy", ("warning", "warning", "error"))`, refs = the act event ids, message `"<n> act(s) at gate <id> were passed by an agent before the policy became human"`.

- [ ] **Step 1: Tests.** `test_tightening_flags_without_staling` (pilot project with second-agent link confirmations; amend `reference.link_confirm` to `human`; `below_policy` lists them; `stale_screening_decisions` and `stale_extractions` unchanged); `test_loosening_flags_nothing`; `test_finding_severity_by_mode`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full suite; mypy; ruff. **Step 5:** Commit `feat(gates): below-policy acts after a tightening amendment`.

### Task 5: Gate audit for `agent_audit` gates

*Tier: critical (audit; slice-3a open question 2).*

**Files:** Modify `model/gates.py` (events), `events/catalog.py`, create `index/gates.py`, modify `index/default.py`, `services/gates.py`, `services/modules/core.py` (checks); Test `tests/test_gate_audit.py`.

**Interfaces:**
- Consumes: `audit_core.AuditPopulation`, `human_gate`, `refuse_reopen`, `validate_seed`, `ceiling_verdict`; `quality.stats.audit_size`, `draw_uniform`.
- Produces: events `gate.audit_sampled` (`GateAuditSampled`: `audit_id` `gau_<ULID>`, `gate_id`, `act_event_ids`, `random_seed`, `population`, `population_digest`, `protocol_id`) and `gate.audit_labelled` (`GateAuditLabelled`: `audit_id`, `act_event_id`, `correct: bool`, `note: str | None`, `channel`); tables `gate_audits`, `gate_audit_items`; `PROJECTION_VERSION` bump; `gate_audit_sample(project, actor, gate_id, *, random_seed=None) -> GateAuditSampled`; `gate_audit_record(project, actor, audit_id, act_event_id, correct, note, channel) -> str`; `GateAuditReport(audit_id, gate_id, sample_size, labelled, incorrect, verdict: CeilingVerdict)`; `gate_audit_report(project, gate_id) -> GateAuditReport | None`; `GATE_AUDIT_ERROR_CEILING = 0.05`; checks `gate-audit-missing` (None, "warning", "error"), `gate-audit-error-high` (None, "warning", "error").

- [ ] **Step 1: Tests.** `test_sample_size_follows_policy` (fraction 0.1, minimum 20, N = 50 → 20; N = 300 → 30); `test_population_is_agent_acts_only`; `test_agent_cannot_draw_or_label`; `test_pass_session_cannot_relay_label`; `test_reopen_refused_for_same_population`; `test_missing_audit_finding_in_pilot`; `test_error_high_finding`; `test_autonomy_becomes_audited_agent_once_sampled`; `test_rebuild_determinism_with_gate_audit`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full suite incl. rebuild-determinism tests; mypy; ruff. **Step 5:** Commit `feat(gates): human audit of agent acts at agent_audit gates`.

### Task 6: Surfaces: `factory gates`, `gate_status`, methods text

*Tier: standard (implementer sonnet, review haiku).*

**Files:** Modify `cli/main.py`, `cli/render.py`, `mcp/server.py`, `services/methods.py`, `services/modules/core.py` (`methods` hook); Test `tests/test_cli_gates.py`, extend `tests/test_methods*.py` by new tests only.

**Interfaces:**
- Produces: `gates_status(project) -> list[GateStatusRow]` (`gate_id`, `kind`, `floor`, `policy`, `source: Literal["preset", "protocol"]`, `counts: dict[Autonomy, int]`, `audit: GateAuditReport | None`, `below_policy: int`); `factory gates [--json]`; MCP `gate_status` (refused to pass sessions; rates withheld from agent view as decision 43); `MethodsReport.gate_policy: list[GateStatusRow] = []` and a methods paragraph *only when* some gate's effective policy is not `human` or some act is below policy, so existing projects render byte-identically.

- [ ] **Step 1: Tests.** `test_factory_gates_lists_every_decision_gate`; `test_gate_status_refused_to_pass_session`; `test_methods_unchanged_for_all_human_projects` (golden from M-A Task 7); `test_methods_states_policy_and_counts_in_pilot_with_agent_links`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full suite; mypy; ruff; coverage. **Step 5:** Commit `feat(gates): gate status surfaces and methods text`.

## Self-review notes

- **Spec coverage.** Ruling 6 (Tasks 1, 2), 7 (Tasks 1, 4), 8 (Tasks 1, 2), 9 (Tasks 2, 5), 10 (Tasks 3, 6); acceptance 4 (Task 6), 5 (Tasks 1, 2), 6 (Task 4), 7 (Task 5), 8 (Tasks 3, 6).
- **Types used later.** `require_gate`, `effective_policy`, `GateAct`, `autonomy_of`, `autonomy_counts`, `gate_audit_*`, `presets.preset`, `presets.enforcement`, `GatePolicies`.
- **Tiers.** Tasks 1–5 critical; Task 6 standard.

## Later (not v1)

None: every task of this plan is in v1.

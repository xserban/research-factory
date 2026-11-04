# Leads, Hypothesis Registry, Critic Review and Gate Policy Implementation Plan (slice 6, sub-plan H-C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Slice M (M-B) is merged first, which owns `services/gates.py`. Ruling 3 and Task 2 are therefore reconciled: the gates are slice-M gates, policies come from M-B `effective_policy`, overrides go in `gate_policies`, and `HypothesisPlan` has no `gates` field (see the edited ruling 3 and Task 2). Experiment plans are XP-A and XP-B (draft XP-A, XP-B). Bumps `PROJECTION_VERSION` by one from the value it finds.

> **Dependencies.** H-A merged (cards); H-B merged for match, conflict and gap trigger kinds (if H-B is not yet merged, Task 1 accepts the other trigger kinds and the three builder kinds land with H-B's merge behind the same `TriggerKind` enum). Slices 3b and 3c merged (`ida_`, contribution items, `int_`, `cpt_` as triggers). When slice M lands, the gate policy of Task 2 becomes the module contract's gate-policy declaration for the gates `lead-promotion`, `hypothesis-registration`; the events do not change.

**Goal:** Capture research ideas from the literature as leads tied to their triggers, show every proposer the failed directions that share those triggers, and turn promoted leads into versioned hypotheses that an independent critic reviews and a gate holder registers under a declared gate policy, with R-53's training cut-off rule applied to literature-tested hypotheses.

**Architecture:** Event families `lead.*`, `hypothesis.*` (draft, review, registration, conclusion, abandonment) and `model.cutoff_declared` in `model/hypotheses.py`, folded by `index/hypotheses.py`. `ProtocolSpec` gains `hypothesis_plan: HypothesisPlan | None` (omitted from the hash while `None`), holding gate policies and defaults. `services/leads.py` resolves triggers and computes `prior`; `services/hypotheses.py` validates specs, computes `H@`, enforces the revision rule and the gate policy; `services/hypothesis_review.py` builds artefact-only critic tasks through the existing task queue and enforces independence. Hypothesis states are computed on read.

**Tech Stack:** as plan D; no new dependencies.

**Spec:** `docs/specs/slice-6-hypotheses.md` rulings 2, 3, 11–15; Design "Leads", "Hypotheses"; events `lead.*`, `hypothesis.drafted|reviewed|registered|concluded|abandoned`, `model.cutoff_declared`; MCP `lead_record`, `hypothesis_draft`, `hypothesis_view`, `hypothesis_review_next`, `hypothesis_review`; acceptance 8–12. `01-rigour.md` R-04, R-14, R-50, R-51, R-52, R-53; R-120.

## Rulings made in this plan (recommended; [confirm])

1. **Trigger kinds.** `work` (`rf:`), `row` (evidence `row_key`), `claim` (`clm_`), `item` (contribution `ext_`), `idea` (`ida_`), `interpretation` (`int_`), `concept` (`cpt_`), `card` (`mcd_`/`pbd_`), `match` (`match_key` + `row_key`), `conflict` (`group_id` + both row keys), `gap` (`gap_key` + cell), `contradiction` (`ctr_`), `lead` (`led_`), `hypothesis` (`hyp_`), `direction` (`dir_`, from XP-B). Builder triggers store their key and the output row as JSON in the event (so the reader sees what the proposer saw); id triggers must resolve (`dangling_refs` for kinds trace knows; table lookups for the others). [confirm]
2. **`prior`.** The keys of a lead are its trigger refs plus the cards, ideas and properties reachable in one step (card subject, card properties, idea of a card). `prior` lists, sorted, every discarded or parked lead, every hypothesis (any state) and, after XP-B, every registry row sharing at least one key, capped at 50 with the total count. Computed at write and stored. [confirm]
3. **Gate policy model (reconciled 2026-11-04).** The gates are slice M's: `GateName` maps the draft names to slice-M gate ids (`lead-promotion` → `hypotheses.lead_decide`, `hypothesis-registration` → `hypotheses.register`, `design-freeze` and `confirmatory-unlock` → `experiments.freeze_unlock`, `baseline-acceptance` → `experiments.accept_baseline`); `critic-review` is not a gate but the quality regime (`HypothesisPlan.critic_distinct_model`, critic review required in pilot and systematic). Policies are M-B's `PolicyKind` (`human`, `agent_audit`, `agent`) from `effective_policy`, with presets from spec ruling 14 and overrides in the protocol's `gate_policies`; `agent_audit` uses M-B's gate audit. `HypothesisPlan` has no `gates` field.
4. **`HypothesisPlan` other fields.** `min_seeds: int` (default 3 pilot, 5 systematic, 2 exploratory), `confidence: Literal["0.90", "0.95", "0.99"] = "0.95"`, `test_access_limit: int = 1`, `conflict_tolerance: str = "0.01"`, `require_lead: bool` (default false exploratory, true otherwise), `critic_distinct_model: bool` (default true systematic only). Amendable, hashed, omitted while `None`. [confirm]
5. **`H@` fields.** Hashed: `kind`, `treatment`, `baseline`, `metric`, `conditions`, `prediction`, `decision_rule`, `test`; stripped: `statement`, `rationale`, `alternatives` (alternatives are links, not content). `H@` = `"H@" + sha256(canonical JSON)[:8]`. [confirm]
6. **Revision.** A draft may be superseded freely; a registered hypothesis may be superseded only while no `hypothesis.evaluated` event exists for it and no `xrun.reported` on a confirmatory split references its design (XP-A adds the second test behind `has_confirmatory_evidence`, which returns `False` until XP-A); the superseded hypothesis keeps its registration and appears in the registry as `superseded-before-evidence` (not a failure). [confirm]
7. **Critic payload.** The review task's content is `ReviewTask(hypothesis_id, h_version, spec_without_prose, statement, triggers (refs and stored builder rows and verified quotes), prior, checklist)`; the statement is included (it is the artefact); the lead's text, its `input_blob` and any `rationale` are not. [confirm]
8. **Checklist.** Items: `falsifiable`, `measurable`, `single-factor`, `baselines-named`, `rule-complete`, `prior-addressed`, `conditions-in-evidence`; each `pass | fail | n/a` with a note (≤ 300 characters); `recommend` must be `revise` or `reject` if any item fails. [confirm]
9. **Cut-offs (spec ruling 15).** `model.cutoff_declared(model, cutoff: date, source)` by a human; the latest declaration per model wins. For a `literature` hypothesis, flags are computed on read over the drafter's and every critic's model: `contaminated` if any cut-off ≥ window start, `cutoff-unknown` if any is undeclared. Registration under systematic is refused with `cutoff-unknown` or `contaminated` (`test.window_start`); pilot registers with the flag. [confirm]

## Global Constraints

- The platform never calls a model; the agent never sets a state, hash, flag or id.
- Every agent-written event carries model, skill reference and `input_blob`; the critic's `input_blob` is the review task content exactly.
- Registration, lead decisions under `HUMAN` policy, conclusions, abandonment and cut-off declarations are human-only service calls; the projector folds them only from human actors (or, under `AGENT` policy, from an agent actor whose eligibility the service recorded in the event).
- A log without `hypothesis_plan` replays to identical `P@` ids.
- Business logic in `services/`; pure helpers in `factory/hypotheses/`; `mcp/`, `cli/` parse and format.
- TDD; `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff; coverage ≥ 90% for `services/` and `model/`.

## Review Focus

1. The critic task `input_blob` contains neither the lead text nor the drafter's rationale (Task 5, `test_review_payload_is_artefact_only`).
2. The drafter's session, the lead author's session and, under `critic_distinct_model`, the drafter's model are refused as critic; a subagent of the drafter's session shares its session and is refused (Task 5, `test_critic_independence`).
3. Under the pilot default, an agent `hypothesis.registered` event written by hand does not register (Task 6, `test_projector_ignores_ineligible_registration`).
4. A registered hypothesis with an evaluation cannot be superseded (Task 4, `test_no_revision_after_evidence`).
5. `P@` unchanged without `hypothesis_plan` (Task 2, `test_p_id_unchanged_without_hypothesis_plan`).

## File Structure

- Create `model/hypotheses.py`, `index/hypotheses.py`, `factory/hypotheses/spec_hash.py`, `services/leads.py`, `services/hypotheses.py`, `services/hypothesis_review.py`, `services/hypothesis_gates.py`, `services/modules/hypotheses.py`, `plugin/skills/rf-ideate/SKILL.md`, `plugin/skills/rf-critic/SKILL.md`.
- Modify `model/protocol.py`, `services/protocol_rules.py`, `services/protocol.py`, `events/catalog.py`, `index/default.py`, `services/stages.py` (task kind `hyp_review`), `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- Tests: `test_leads.py`, `test_hypothesis_plan.py`, `test_hypothesis_model.py`, `test_hypotheses.py`, `test_hypothesis_review.py`, `test_registration.py`, `test_mcp_hypotheses.py`, `test_cli_hypotheses.py`; helper `tests/hypothesis_helpers.py` (H-B fixtures, a problem card and two method cards, sessions `drafter`, `critic`, `lead_author` with distinct ULIDs and models, builders `lead(...)`, `spec(...)`).

---

### Task 1: Leads, triggers and `prior`

*Tier: critical (provenance of ideas).*

**Files:** Create `model/hypotheses.py` (lead part), `index/hypotheses.py` (lead part), `services/leads.py`; Modify `events/catalog.py`, `index/default.py`; Test `tests/test_leads.py`.

**Interfaces:**
- Consumes: `dangling_refs`, `card_view`, `idea_view`, `MatchRow`, `ConflictPair`, `GapCell`, `ContradictionView`.
- Produces: `LEAD_ID_RE = rf"^led_{ULID_RE}$"`; `TriggerKind(StrEnum)` (ruling 1); `Trigger(StrictModel)`: `kind`, `ref: str`, `row: dict[str, JsonValue] | None = None`; `LeadInput(text: str (1..600), triggers: tuple[Trigger, ...] (1..20), framework: str | None (≤ 80))`; payloads `LeadRecorded(lead_id, text, triggers, framework, prior: tuple[str, ...], prior_total: int, keys: tuple[str, ...])`, `LeadDecided(lead_id, decision: Literal["promote", "park", "discard"], reason: DiscardReason | None, note: str | None, policy: GatePolicy)`; `DiscardReason(StrEnum)`: `DUPLICATE`, `PRIOR_FAILURE`, `OUT_OF_SCOPE`, `INFEASIBLE`, `NOT_FALSIFIABLE`, `OTHER`; tables `leads`, `lead_triggers(lead_id, kind, ref)`, `lead_keys(lead_id, key)` (index on `key`); services `record_lead(project, actor, item: LeadInput) -> str` (builder triggers: the stored row must equal the row the builder returns now for that key, else `triggers.<i>`, `trigger-stale`); `lead_keys(project, triggers) -> tuple[str, ...]` and `prior_for(project, keys) -> tuple[list[str], int]` (ruling 2; extended by XP-B through a registered provider list `PRIOR_SOURCES`); `decide_lead(project, actor, lead_id, decision, reason=None, note=None) -> str` (policy from `services/hypothesis_gates.py` Task 2: `HUMAN` → human only; `AGENT` → any session other than the lead's author; `discard` needs a reason, `OTHER` needs a note); `LeadView(lead_id, text, triggers, framework, prior, state: Literal["open", "promoted", "parked", "discarded"], author_session, event_id)`; `list_leads(project, *, states=...) -> list[LeadView]`.

- [ ] **Step 1: Tests.** `test_lead_without_trigger_refused` (acceptance 8), `test_dangling_trigger_refused`, `test_builder_trigger_must_match_current_row`, `test_prior_lists_shared_card_hypothesis_and_discarded_lead` (acceptance 8), `test_prior_capped_with_total`, `test_discard_needs_reason`, `test_author_cannot_decide_own_lead` (acceptance 8), `test_human_policy_refuses_agent`, `test_text_length_limit`, `test_event_provenance`.
- [ ] **Step 2:** `uv run pytest -m "not network and not slow" tests/test_leads.py` — FAIL. **Step 3:** Implement (Task 2's `gate_policy` is stubbed to the mode defaults here and replaced in Task 2). **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(leads): leads with resolved triggers and prior failures`.

### Task 2: `hypothesis_plan` protocol section and gate policy

*Tier: critical (protocol hash).*

**Files:** Modify `model/protocol.py`, `services/protocol_rules.py`, `services/protocol.py`, `modules/presets.py` (presets and floors of the slice-6 gates); Create `services/hypothesis_gates.py` (M-B owns `services/gates.py`), `services/modules/hypotheses.py` (module declarations); Test `tests/test_hypothesis_plan.py`.

**Interfaces:**
- Consumes: `ProtocolSpec`, `AMENDABLE_FIELDS`, `_OMITTED_WHEN_NONE`, `RigorMode`.
- Produces: `GateName = Literal["hypotheses.lead_decide", "hypotheses.register", "experiments.freeze_unlock", "experiments.accept_baseline"]` (slice-M gate ids), `HypothesisPlan(StrictModel)` (ruling 4 fields only); `ProtocolSpec.hypothesis_plan: HypothesisPlan | None = None` in `AMENDABLE_FIELDS` and `_OMITTED_WHEN_NONE`; errors: `min_seeds < 2` (`hypothesis_plan.min_seeds`), `test_access_limit < 1`; gate-policy errors and gaps are M-B's (`gate_policies.<gate>`, floors and presets). `services/hypothesis_gates.py`: `gate_policy(project, gate: GateName) -> GatePolicy` (M-B `effective_policy`); `effective_plan(project) -> HypothesisPlan` (defaults filled); `may_pass(project, actor, gate, *, proposer_sessions: Collection[str]) -> GateVerdict(ok: bool, reason: str | None, policy: GatePolicy, autonomy: Literal["human", "agent"])` (M-B `require_gate` plus the proposer exclusion: under `agent`, an agent or human whose session is not in `proposer_sessions`; under `human`, a human only; under `agent_audit`, as `agent` with the act entering M-B's gate-audit population).

- [ ] **Step 1: Tests.** `test_p_id_unchanged_without_hypothesis_plan` (Review Focus 5; pinned literal), `test_p_id_changes_with_plan`, `test_defaults_follow_mode_table` (spec ruling 14, parametrised over modes and gates), `test_systematic_agent_gate_is_gap`, `test_may_pass_refuses_proposer_session_under_agent`, `test_may_pass_human_only_under_human`, `test_amendment_of_plan_stales_nothing` (no screening or extraction decision becomes stale).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement; replace Task 1's stub. **Step 4:** Pass with protocol and amendment suites unedited; mypy; ruff. **Step 5:** Commit `feat(hypotheses): hypothesis_plan protocol section and gate policies`.

### Task 3: Hypothesis spec, decision rules and `H@`

*Tier: critical (hash, pre-registration content).*

**Files:** Modify `model/hypotheses.py`; Create `factory/hypotheses/spec_hash.py`; Test `tests/test_hypothesis_model.py`.

**Interfaces:**
- Consumes: `strip_prose`, `UnitFamily`, `CARD_ID_RE`, `IDEA_ID_RE`.
- Produces: `HYP_ID_RE = rf"^hyp_{ULID_RE}$"`, `H_VERSION_RE = r"^H@[0-9a-f]{8}$"`; `MethodRef(card: str | None, idea: str | None, name: str | None, row_key: str | None)` (exactly one of card, idea, name; `row_key` optional evidence row); `MetricSpec(name, direction: Literal["higher", "lower"], unit_family: UnitFamily, unit: str | None)`; `Prediction(direction: Literal["treatment-better", "no-worse"], margin: str (decimal ≥ 0), unit: str | None)`; `DecisionRule` = discriminated union on `rule`: `Superiority(rule="superiority")`, `NonInferiority(rule="non-inferiority")`, `LiteratureDirection(rule="literature-direction", n_min: int ≥ 1, q: str (decimal in (0.5, 1]))`; `ExperimentTest(kind="experiment")` (the design points to the hypothesis, not the reverse, so linking a design never changes `H@`; XP-A enforces one live design per hypothesis), `LiteratureTest(kind="literature", window_start: date, sources: tuple[str, ...] (search-run or protocol ids))`; `HypothesisSpec(StrictModel)`: `kind: Literal["experiment", "literature"]`, `statement: str (1..600)`, `lead: str | None`, `treatment: MethodRef`, `baseline: MethodRef`, `metric: MetricSpec`, `conditions: dict[str, str]`, `prediction: Prediction`, `decision_rule: DecisionRule`, `test: ExperimentTest | LiteratureTest`, `alternatives: tuple[str, ...] = ()`, `rationale: str = ""` (validators: `kind` matches `test.kind`; `literature-direction` only with literature kind and vice versa for the two experiment rules; `prediction.direction` `no-worse` ⇔ `non-inferiority`); `hypothesis_version(spec) -> str` (ruling 5); `falsifier_text(spec) -> str` (a fixed sentence generated from rule, margin, metric and conditions, e.g. "Refuted if the 95% CI upper bound of (treatment − baseline) on top-1 accuracy (ImageNet-1k, 224) is below 0.5 points.").

- [ ] **Step 1: Tests.** `test_statement_change_keeps_h_version` (acceptance 9), `test_margin_rule_conditions_change_h_version` (acceptance 9, parametrised), `test_rule_kind_compatibility`, `test_method_ref_exactly_one`, `test_falsifier_text_fixed_sentences` (one per rule), `test_h_version_independent_of_dict_order`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(hypotheses): hypothesis spec, decision-rule menu, H@ hash`.

### Task 4: Hypothesis drafting, states and revision rule

*Tier: critical.*

**Files:** Modify `model/hypotheses.py`, `index/hypotheses.py`; Create `services/hypotheses.py`; Test `tests/test_hypotheses.py`.

**Interfaces:**
- Consumes: Tasks 1–3; `card_view`, `idea_view`, `final_rows` (a `row_key` in a `MethodRef` must be a final evidence row; conditions keys must be comparability keys of the evidence schema: `conditions.<k>`, `not-a-comparability-key`).
- Produces: payloads `HypothesisDrafted(hypothesis_id, spec, h_version, supersedes: str | None)`, `HypothesisAbandoned(hypothesis_id, reason: AbandonReason, note)`, `HypothesisConcluded(hypothesis_id, text (1..1200))`; `AbandonReason(StrEnum)`: `NO_RUNNABLE_CODE`, `BUDGET_EXHAUSTED`, `INFEASIBLE`, `DATA_UNAVAILABLE`, `OTHER`; tables `hypotheses(hypothesis_id pk, h_version, kind, lead, spec_json, supersedes, superseded_by, drafter_session, drafter_model, event_id)`; `draft_hypothesis(project, actor, spec: HypothesisSpec, *, supersedes: str | None = None) -> tuple[str, str]` (id, `H@`; lead required when `require_lead`, and the lead must be `promoted`: `lead`, `lead-not-promoted`; revision rule of ruling 6: `supersedes`, `evidence-exists`); `has_confirmatory_evidence(project, hypothesis_id) -> bool` (False until XP-A registers a provider); `abandon_hypothesis(project, actor, hypothesis_id, reason, note) -> str` and `conclude_hypothesis(project, actor, hypothesis_id, text) -> str` (human only; conclude needs an evaluation, which XP-B provides; until then `state`, `not-evaluated`); `HypothesisState = Literal["draft", "reviewed", "registered", "evaluated", "abandoned", "superseded"]`; `HypothesisView(hypothesis_id, h_version, spec, falsifier, state, reviews: list[str], registration: str | None, flags: tuple[str, ...], autonomy: Literal["human", "agent"] | None, event_id)`; `hypothesis_view(project, hypothesis_id) -> HypothesisView | None`; `list_hypotheses(project, *, states=None) -> list[HypothesisView]`.

- [ ] **Step 1: Tests.** `test_draft_requires_promoted_lead_when_required`, `test_conditions_must_be_comparability_keys`, `test_row_key_must_be_final`, `test_supersede_draft_freely`, `test_no_revision_after_evidence` (Review Focus 4; a hand-written `hypothesis.evaluated` system event in the fixture), `test_abandon_human_only_with_reason`, `test_state_computed_from_events`, `test_event_provenance`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(hypotheses): drafting, states, revision rule, abandonment`.

### Task 5: Critic review task and independence

*Tier: critical (R-51).*

**Files:** Create `services/hypothesis_review.py`; Modify `services/stages.py` (task kind `hyp_review`), `model/hypotheses.py`, `index/hypotheses.py`; Test `tests/test_hypothesis_review.py`.

**Interfaces:**
- Consumes: the task queue (`task.created`/`claimed`/`completed`, `services/tasks.py`), Tasks 1–4, `effective_plan`.
- Produces: `ChecklistItem = Literal["falsifiable", "measurable", "single-factor", "baselines-named", "rule-complete", "prior-addressed", "conditions-in-evidence"]`; `ReviewTask(StrictModel)` (ruling 7); `ReviewInput(items: dict[ChecklistItem, Literal["pass", "fail", "n/a"]], notes: dict[ChecklistItem, str], recommend: Literal["register", "revise", "reject"])`; payload `HypothesisReviewed(hypothesis_id, h_version, items, notes, recommend, critic_session, critic_model)`; `review_next(project, actor) -> ReviewTask | None` (serves the oldest draft without an eligible review; refuses ineligible sessions before serving: `actor`, reasons `drafter-session`, `lead-author-session`, `same-model`); `record_review(project, actor, task_id, review: ReviewInput) -> str` (ruling 8: a failing item forces `revise` or `reject`, `recommend`, `inconsistent`; the `H@` in the task must still be the hypothesis's current version, else `h_version`, `superseded`).

- [ ] **Step 1: Tests.**
```python
def test_review_payload_is_artefact_only(project):        # Review Focus 1; acceptance 10
    task = review_next(project, CRITIC)
    blob = project.blobs.get(task_input_blob(project, task)).decode()
    assert LEAD_TEXT not in blob and RATIONALE not in blob and STATEMENT in blob
def test_critic_independence(project): ...                 # Review Focus 2; drafter, lead author, subagent, same model (systematic)
def test_failing_item_forces_revise_or_reject(project): ...
def test_review_of_superseded_version_refused(project): ...
def test_review_event_provenance(project): ...             # input_blob equals the served task content
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(hypotheses): artefact-only critic review with engineered independence`.

### Task 6: Registration and model cut-offs (R-53)

*Tier: critical (gate).*

**Files:** Modify `model/hypotheses.py`, `index/hypotheses.py`, `services/hypotheses.py`; Test `tests/test_registration.py`.

**Interfaces:**
- Consumes: `may_pass`, `effective_plan`, Task 5 reviews.
- Produces: payloads `HypothesisRegistered(hypothesis_id, h_version, review_event_id: str | None, policy: GatePolicy, autonomy: Literal["human", "agent"], flags: tuple[str, ...])`, `ModelCutoffDeclared(model, cutoff: date, source: str)`; table `model_cutoffs(model pk, cutoff, event_id)` (latest wins); `register_hypothesis(project, actor, hypothesis_id) -> str` (requires an eligible review recommending `register` for the current `H@` unless the `critic-review` gate is optional under the mode default (exploratory); `may_pass(..., "hypothesis-registration", proposer_sessions={drafter, lead author})`; for literature hypotheses computes the cut-off flags (ruling 9) and refuses in systematic); `declare_cutoff(project, actor, model, cutoff, source) -> str` (human only); `cutoff_flags(project, hypothesis_id) -> tuple[str, ...]` (computed on read; used by views and XP-B). The projector folds `hypothesis.registered` only when the recorded `policy` and actor are consistent (`HUMAN` ⇒ human actor; `AGENT` ⇒ session not the drafter's).

- [ ] **Step 1: Tests.** `test_pilot_agent_cannot_register` (acceptance 11), `test_exploratory_non_drafter_agent_registers_with_autonomy_label` (acceptance 11), `test_registration_needs_register_review`, `test_contaminated_and_cutoff_unknown_flags` (acceptance 12), `test_systematic_refuses_unknown_cutoff` (acceptance 12), `test_latest_cutoff_declaration_wins`, `test_projector_ignores_ineligible_registration` (Review Focus 3), `test_registered_h_version_frozen` (a later draft with `supersedes` creates a new `hyp_`; the old view is unchanged).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(hypotheses): gated registration, model cut-offs and R-53 flags`.

### Task 7: MCP tools, CLI and skills `rf-ideate`, `rf-critic`

*Tier: Haiku implement and review (surfaces); skills by Sonnet.*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`, `tests/test_plugin.py`; Create `plugin/skills/rf-ideate/SKILL.md`, `plugin/skills/rf-critic/SKILL.md`; Test `tests/test_mcp_hypotheses.py`, `tests/test_cli_hypotheses.py`, extend `tests/test_skills.py`.

**Interfaces:**
- MCP: `lead_record(project, text, triggers, framework=None, role, model, skill)` -> `{lead_id, prior, prior_total}`; `lead_decide(...)` exists only when the mode's `lead-promotion` gate is `AGENT` and refuses otherwise; `hypothesis_draft(project, spec: dict, supersedes=None, role, model, skill)` -> `{hypothesis_id, h_version, falsifier}`; `hypothesis_view(project, hypothesis_id)`; `hypothesis_review_next(project, role, model, skill)` -> `ReviewTask | None`; `hypothesis_review(project, task_id, review: dict, role, model, skill)`; `hypothesis_register(...)` refuses unless the gate is `AGENT`. All refused to screening and extraction pass sessions.
- CLI: `factory leads list [--state S]|promote LED|park LED|discard LED --reason R [--note N]`; `factory hypotheses list|show HYP|register HYP|abandon HYP --reason R --note N|conclude HYP --text T`; `factory models cutoff MODEL DATE --source TEXT`; `factory hypotheses show` prints the falsifier sentence, state, flags and autonomy label.
- Skill `rf-ideate`: start from `match_query`, `finder_contradictions`, `finder_gaps`, lineage and interpretation views; record a lead only with triggers; read `prior` and say how the lead differs; name the ideation framework used; draft hypotheses with one factor, one primary metric, conditions that exist as comparability keys, a margin stated before any result, and a rule from the menu; never register. Skill `rf-critic`: review only through `hypothesis_review_next`; judge the artefact against the checklist; do not ask for or read the proposer's notes; a failing item means `revise` or `reject`.

- [ ] **Step 1: Tests.** Tool list pinned; `lead_decide` and `hypothesis_register` refused under pilot; a pass session is refused; CLI `hypotheses register` writes a human event; skills name their tools, "never register" (`rf-ideate`) and "do not read the proposer's notes" (`rf-critic`); `SKILLS` includes both.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(hypotheses): MCP tools, CLI, rf-ideate and rf-critic skills`.

## Self-review notes

- **Spec coverage.** Rulings 2, 3, 11–15; acceptance 8 (Task 1), 9 (Tasks 3–4), 10 (Task 5), 11–12 (Task 6). Evaluation, conclusion content and the registry are XP-B; experiment designs (which reference the hypothesis) are XP-A.
- **Types used later.** `HypothesisSpec`, `DecisionRule` variants, `MetricSpec`, `Prediction`, `hypothesis_version`, `falsifier_text`, `HypothesisView`, `hypothesis_view`, `list_hypotheses`, `has_confirmatory_evidence` (provider hook), `PRIOR_SOURCES` (provider hook), `cutoff_flags`, `GatePolicy`, `GateName`, `may_pass`, `effective_plan`, `LeadView`, `list_leads`, `AbandonReason`, `DiscardReason`, `HYP_ID_RE`, `LEAD_ID_RE`.
- **Tiers.** Tasks 1–6 critical; 7 Haiku (skills Sonnet).

## Later (not v1)

None: every task of this plan is in v1.

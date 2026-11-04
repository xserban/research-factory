# Human and Mixed Screening Teams Implementation Plan (slice 5, sub-plan teams-C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** teams-B is merged first, so Task 3 reuses its `full_view_allowed`. Slice M's `passes.memberships` and `refuse_shared` exist: the per-user rule is added there, as the pair-type dimension of screening's quality regime. Bumps `PROJECTION_VERSION` by one from the value it finds.

> **Dependencies.** teams-A merged (`Principal`, `ProjectRole`, `roles_of`, `Permission.PASS_JOIN_HUMAN`, `authorize`). Slice 1 plan 4 and slice 2 plan C (screening at both stages) merged. Independent of deploy-B (human passes are CLI-only in this plan); teams-B's held-out view by role is reused if merged, otherwise Task 3 adds `full_view_allowed` itself. When slice M lands, screening's quality regime gains the pair-type dimension defined here.

**Goal:** Let passes A and B be any mix of people and agents (IDEA-12), keep decision 37 independence across people as well as sessions and models, keep adjudication, calibration labelling and audit outside both passes, and report agreement per pair type.

**Architecture:** `PassJoined` gains `actor_kind` and an optional `model`; `join_pass` admits a human holding `pass:join-human`; the independence checks of `_check_join` and `screen_agreement` add a user rule. Human passes use the same `screen_next` / `screen_record` services through new CLI commands with `Channel.CLI`. Agreement gains a computed `pair_type`.

**Tech Stack:** as slice 2.

**Spec:** `docs/specs/slice-5-teams-deployment.md` ruling 15, Design "Human screening passes", R-110, check finding `pass-same-user`; acceptance 8. Decision 37 items 1, 2, 6, 9; decision 43; R-32, R-33, R-36, R-37, R-51.

## Rulings made in this plan

1. **User rule.** Let U(P) be the set of users of pass P: for a human join, the human; for an agent join, `actor.user` (the principal). A join to pass X is refused when U(other pass) contains the joining user. So the same person cannot screen both passes, in person or through agents, and two agent passes run by one person are refused too. [confirm] *Consequence:* a single researcher can no longer run both agent passes in a **hosted** project; for unhosted projects (stage 0, one person) the rule is not applied, preserving slice-1 behaviour. Alternative: apply the user rule only to human joins. Recommended as stated, because a person who configures both agent passes controls both framings.
2. **Outside both passes.** Calibration labels, disagreement resolutions and audit labels are refused to a user in U(A) ∪ U(B) of that stage, in hosted projects. [confirm]
3. **Human calibration.** `ScreeningPlan.calibrate_humans: bool = False`, omitted from the protocol hash while false; when true, a human pass passes the same calibration gate as an agent pass. [confirm]
4. **Human quotes.** Human exclusions need a verified quote in `systematic`; quotes are optional otherwise and verified when given (R-32 as R-110). [confirm]
5. **Pair type** is computed from the two passes' `actor_kind`: `agent-agent`, `human-agent`, `human-human`. A stage with mixed joins within one pass (a human and an agent both in pass A) is refused at join: a pass is all-human or all-agent. [confirm]

## Global Constraints

- Decision 37 holds unchanged for agent–agent pairs; every slice-1 and 2C screening test passes unchanged.
- A human pass is served the agent view (no seed marks, no rates, decision 43) through the CLI.
- Events are the source of truth; old `screening.pass_joined` lines read as `actor_kind = agent`.
- `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff pass; coverage ≥ 90%.

## Review Focus

1. Same person, both passes (in person; person + own agent; two own agents): all refused on a hosted project; all allowed paths of slice 1 on an unhosted project still pass (Task 2).
2. A pass member is refused calibration label, resolution and audit label (Task 4, `test_pass_member_cannot_adjudicate`).
3. The human pass sees no seed mark and no rate in any CLI output during the pass (Task 3, `test_human_pass_is_served_agent_view`).

## File Structure

- Modify `model/screening.py` (`PassJoined`), `model/protocol.py` (`ScreeningPlan.calibrate_humans`), `index/screening.py`, `services/screening.py`, `services/agreement.py`, `services/calibration.py`, `services/audit.py`, `services/methods.py`, `services/check.py`, `cli/main.py`.
- Tests: `tests/test_human_pass_model.py`, `tests/test_human_pass_join.py`, `tests/test_human_pass_cli.py`, `tests/test_pass_member_rules.py`, `tests/test_pair_types.py`, `tests/test_acceptance_teams_screening.py` (`slow`).

---

### Task 1: `PassJoined.actor_kind` and projection

*Tier: critical.*

**Files:** Modify `model/screening.py`, `index/screening.py`, `model/protocol.py`; Test `tests/test_human_pass_model.py`.

**Interfaces:**
- Produces: `PassJoined(pass_label, session, model: str | None = None, stage, actor_kind: Literal["agent", "human"] = "agent", user: str | None = None)` with a validator: `agent` requires `model`; `human` requires `user` and forbids `model`; `screening_passes` table gains `actor_kind`, `user` (NULL for old rows; read as the event's `actor.user`).
- Produces: `ScreeningPlan.calibrate_humans: bool = False` (excluded from the hash while false; test that existing `P@` ids are unchanged).

- [ ] **Step 1: Tests.** `test_old_pass_joined_reads_as_agent`, `test_human_join_requires_user_forbids_model`, `test_protocol_hash_unchanged_without_calibrate_humans`, `test_rebuild_identical`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(screening): human pass joins in the model and projection`.

### Task 2: Joining as a human; the user rule

*Tier: critical.*

**Files:** Modify `services/screening.py` (`join_pass`, `_check_join`, `_join_event`), `services/agreement.py` (`_refuse_shared_users`); Test `tests/test_human_pass_join.py`.

**Interfaces:**
- Produces: `join_pass(project, actor, label, *, stage)` admits `actor.kind == "human"` holding `pass:join-human` (via `authorize`); `pass_users(project, label, stage) -> frozenset[str]`; `_check_join` adds rulings 1 and 5 for hosted projects (`project.is_hosted()`); `screen_agreement` refuses when `pass_users(A) & pass_users(B)` (hosted only); the existing session and model rules apply to agent passes unchanged.

- [ ] **Step 1: Tests.**
```python
def test_human_joins_pass_a(hosted): join_pass(hosted, human("bea"), A); assert pass_users(hosted, A) == {"bea"}
def test_same_person_both_passes_refused(hosted): ...           # human A, human B same user
def test_person_and_own_agent_refused(hosted): ...              # human bea A; agent(user=bea) B
def test_two_own_agents_refused_when_hosted(hosted): ...
def test_two_own_agents_allowed_unhosted(unhosted): ...         # slice-1 behaviour
def test_other_persons_agent_allowed(hosted): ...               # human bea A; agent(user=ali) B
def test_mixed_pass_refused(hosted): ...                        # human and agent in pass A
def test_screener_role_required(hosted): ...                    # observer refused
```
- [ ] **Step 2–4:** Fail, implement, pass; slice-1 screening suite unchanged.
- [ ] **Step 5:** Commit `feat(screening): human passes and the user independence rule`.

### Task 3: CLI for human screeners

*Tier: standard.*

**Files:** Modify `cli/main.py`, `services/screening.py` (quote rule for humans); Test `tests/test_human_pass_cli.py`.

**Interfaces:**
- Produces CLI: `factory screen join --pass A|B [--stage title-abstract|full-text]`; `factory screen next [--stage …]` printing the batch as the agent sees it (title, abstract or pinned conversion excerpt references, criteria in the pass's framing and order) plus a JSON template; `factory screen record FILE` (the same `ScreeningItem` list as `screen_record`) and `factory screen record --interactive` (prompts per item: verdict, criterion, optional quote; quote verified immediately and re-prompted on failure). `screen_record` accepts `actor.kind == "human"` for a human pass; ruling 4 for quotes.

- [ ] **Step 1: Tests.** `test_human_pass_is_served_agent_view` (no seed id, DOI or arXiv id of a held-out seed in `next` output; no rate), `test_record_file_round_trip`, `test_interactive_reprompts_bad_quote` (CliRunner input), `test_systematic_human_exclusion_needs_quote`, `test_pilot_human_exclusion_quote_optional`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(cli): human screening commands`.

### Task 4: Adjudication, labelling and audit outside both passes

*Tier: critical.*

**Files:** Modify `services/agreement.py` (`resolve_disagreement`), `services/calibration.py`, `services/audit.py`; Test `tests/test_pass_member_rules.py`.

**Interfaces:**
- Produces: `require_outside_passes(project, user, stage) -> None` in `services/screening.py` (hosted only; `ValidationIssue("user", "this person screens pass <X> of <stage>")`), called by the three human-act services before any write.

- [ ] **Step 1: Tests.** `test_pass_member_cannot_adjudicate`, `test_pass_member_cannot_label_calibration`, `test_pass_member_cannot_audit`, `test_third_person_adjudicates`, `test_rule_is_per_stage` (a TA screener may adjudicate FT).
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(screening): adjudicator, labeller and auditor outside both passes`.

### Task 5: Agreement per pair type; methods; check; acceptance

*Tier: standard.*

**Files:** Modify `services/agreement.py` (`Agreement.pair_type`, `PassConfig.actor_kind`, `PassConfig.users`), `services/methods.py`, `services/check.py`; Test `tests/test_pair_types.py`, `tests/test_acceptance_teams_screening.py`.

**Interfaces:**
- Produces: `PairType(StrEnum)`: `AGENT_AGENT`, `HUMAN_AGENT`, `HUMAN_HUMAN`; `Agreement.pair_type: PairType`; `agreement_by_pair_type(project) -> dict[PairType, list[Agreement]]` across stages; methods text: "Pass A was screened by a human (user ids withheld in the agent view) and pass B by an agent (model …); κ = …"; check finding `pass-same-user` (error; catches logs written before this plan on a since-hosted project).

- [ ] **Step 1: Tests.** `test_pair_type_computed`, `test_methods_names_pair_type`, `test_pass_same_user_finding`; acceptance (`slow`): on a constructed hosted project, a human–agent TA pair and an agent–agent FT pair complete; a third person resolves; κ per pair type equals hand-computed values; PRISMA unchanged by pair composition.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Verification `uv run pytest -m "not network" -q && uv run mypy --strict src && uv run ruff check .`; commit `feat(screening): agreement per pair type`.

## Later (not v1)

None: every task of this plan is in v1.

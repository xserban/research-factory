# Slice 9: tiers and autonomy levels

**Status:** proposed, 2026-11-20 (lane L0 of [the plan](../plans/2026-11-20-tiers-and-autonomy.md); the researcher's direction of 2026-11-20). Not binding until the decision rows of [slice-9-decision-rows.md](slice-9-decision-rows.md) are ruled. Where this document relaxes a *Decided* entry it says so and proposes an amendment (section 11). Binding documents it builds on: [00-system.md](00-system.md), [01-rigour.md](01-rigour.md), [slice-M-modules.md](slice-M-modules.md) (gates, floors, presets), [slice-8-develop.md](slice-8-develop.md) (decision selection). Backlog: IDEA-41 (quick factory), IDEA-42 and IDEA-43 (ranker, capped snowball, both built).

Verification mark: every statement about existing behaviour carries a path:line (under `platform/src/factory/` unless stated) read on 2026-11-20 in the worktree of branch `tiers-base`. **[unverified]** marks a claim taken from the plan or from the review note `data/projects/agentic-science/ops/review-2026-11-20/gates-by-preset.md` without reading the code again.

## 1. Problem and goal

The factory has one speed (pilot: days, human gates everywhere) and one meaning of "who closes a gate" (a human, plus a handful of agent-passable gates at preset-fixed policies). A small question needs minutes, not days (IDEA-41); a large batch of studies cannot wait on a human at every gate. Two independent settings fix this without changing what a log replays to:

- **Tier**: speed and depth. Fixes the rigour mode and the plan of stages, caps and templates.
- **Autonomy level**: who closes the decision gates and with which compensating controls.

A study (a project) declares both at `factory init`. Every output states plainly what was skipped and what no human confirmed. The platform still never calls a model; each autonomous step is an outside `claude -p` process (`services/runner.py:394`, `default_launcher`).

Non-goals: programmes and studies (IDEA-71 to 74); changing the rigour modes of decision 24; weakening any gate floor by default; any change to what `attended` does today.

## 2. Vocabulary

| Term | Meaning |
|---|---|
| tier | `brief`, `deep`, `pilot`, `systematic` (`model/levels.py`, `Tier`) |
| autonomy level | `attended`, `supervised`, `autonomous` (`model/levels.py`, `AutonomyLevel`); a project-level setting |
| per-act autonomy | `human`, `audited-agent`, `agent` on one act (`modules/contract.py`, `Autonomy`); a different thing, named differently on purpose |
| rigour mode | `exploratory`, `pilot`, `systematic` (`model/project.py:10-12`); mapped from the tier by `RIGOR_OF_TIER` |
| gate | a decision gate `<module>.<act>` with a preset policy and a floor (`modules/contract.py:100-113`) |
| closing session | the session whose act closes a gate; the proposing session is the one that made the proposal |
| verifier, auditor | independent sessions (separate `claude -p` runs, hence separate MCP sessions) that confirm, respectively sample-check, an agent's closure |
| trust ledger | per-gate counts of agent closures, audited, overturned, computed from events |
| deferred review | the human's queue of agent-closed acts to confirm afterwards |

## 3. Tiers

Rigour mode per tier (`RIGOR_OF_TIER`, `model/levels.py:48-54`): `brief` and `deep` run in `exploratory`; `pilot` in `pilot`; `systematic` in `systematic`. Decision 24's modes are unchanged; the tier adds the plan on top. The mode is fixed at `factory init` (no event or command changes it, review note section 0; decision 161 proposed, `services/project.py:121-157`), so a tier is fixed too (section 10 for promotion).

| Tier | Time | Stages | Caps (defaults, set as typed data in `factory/tiers/plans.py`, [unverified: numbers are proposals]) | Template |
|---|---|---|---|---|
| `brief` | minutes to an hour | frame (light), gather (one capped search), screen (one pass, ranked, stopping rule), acquire (open access only), extract (small fixed schema), write (cited evidence note) | about 30 papers, one run per stage, minutes and run caps in `Limits` | evidence-note report template; protocol-lite |
| `deep` | hours | `brief` plus protocol-lite with an independent PRESS-lite review, one capped snowball round, sampled audit, contradiction finder, agreement on a sample | more papers; one snowball round; audit and agreement on samples | protocol-lite; evidence report |
| `pilot` | days | today's pilot: hold-out split, calibration, dual passes on a sample, human gates | as protocol | as today |
| `systematic` | weeks | today's systematic mode: dual screening, kappa floors, appraisal, full PRISMA | as protocol | as today |

Stage ids are those of `services/site_catalog.py:29-40` (`LIFECYCLE`), without `cross`: `frame, gather, screen, acquire, extract, understand, develop, write, maintain`. The plan's conductor note names stages `frame`, `search`, `acquire`, `report`; the lifecycle ids are `gather` for search and `write` for report, and the spec uses the lifecycle ids (deviation recorded for L4).

### 3.1 What each tier skips and discloses

`skipped_steps(tier)` is computed by comparing the tier's `TierPlan.stages` with `systematic`; the list is never typed twice. The proposed content, which a reader checks against the typed data:

| Step | brief | deep | pilot | systematic |
|---|---|---|---|---|
| hold-out seed split (R-20) | skipped, disclosed | skipped, disclosed | done | done |
| screening calibration (R-30) | skipped | skipped | done | done |
| dual screening | skipped (one pass, ranked, stop rule) | sample only | sample (`dual_sample`, decision 37.10) | full |
| full-text screening | skipped | optional | done | done |
| PRESS review | skipped | independent PRESS-lite session; a human confirms unless ruled (D3) | done | done |
| snowballing | skipped | one capped round | per protocol | per protocol |
| appraisal | skipped | skipped | per protocol | done |
| audit | skipped | sampled | sampled | full |
| agreement (kappa) | skipped | on a sample | done | done, floors enforced |
| PRISMA | counts only, labelled partial | partial | done | full |

Every `report_*` output and the hub overview carries the level statement (section 8) listing the skipped steps. A skipped step is a stated shortcut in the sense of R-82 and R-83: reported with its consequence (for example the number of records never screened after the stopping rule, as IDEA-42's rigour note requires).

What no tier may skip: provenance on every agent-written event; the protocol (even protocol-lite) as an event before search; the held-out rule (a held-out seed is never shown to an agent and its work is read as corpus, decision 37.9); every claim citing a resolvable source (R-01 to R-05); the platform's own computation of counts and hashes.

### 3.2 The `brief` plan end to end

frame: question record plus light frame, seeds as given (no split, disclosed); gather: one search run within `Limits.max_papers`; screen: ranked single-pass screening with the ranker's stopping rule (`services/ranking.py`, `services/ranked_queue.py` [unverified: plan section 2]); acquire: open-access full texts only; extract: one fixed small schema; write: cited evidence note from `report_evidence`. Each stage is one `claude -p` run with a stage-specific tool allow-list (`services/runner.py` stage specs; section 7).

## 4. Autonomy levels

| Level | Who closes a gate | Compensating controls |
|---|---|---|
| `attended` | a human; default; today's behaviour | none needed |
| `supervised` | an independent agent session, where the gate permits an agent | a sampled audit by a third session; measured overturn rate |
| `autonomous` | an orchestrated multi-agent run | verifier and auditor sessions, trust ledger with a stop rule, deferred human review queue, every output labelled "not human-confirmed" |

The settings are independent: a `brief` may be `autonomous`; a `pilot` may be `supervised`.

### 4.1 Base limits that no level removes

These are facts about the platform, read in the code; the levels do not and cannot change them (decision 160, proposed, documents the same):

1. The CLI writes a human actor always (`services/context.py:123-130`, `Project.human_actor` [unverified: line range from the review note]); an agent with a shell passes any CLI human act and the log says human. The platform cannot detect it.
2. MCP relay tools (`calibration_label`, `audit_record`, `decision_select`, `review_decide`, ...) write the configured human as actor (`mcp/authz.py:117-118` [unverified]; decision 37.6), barred only for sign-off and audit-label acts, only in `systematic`, only when remote or hosted (`services/human_channel.py:34-49` [unverified]).
3. Many folds drop an event unless `actor.kind == "human"`; for example `index/decisions.py:126` drops a non-human `decision.selected`. A gate whose confirming fold is human-only cannot be closed by an agent by policy alone.

Consequence: the autonomy level governs only gates that the services let an agent pass. It is a statement about which closures are labelled and controlled, not a guarantee against an agent with a shell. The level statement says so (section 8). Hard defence for `supervised` and `autonomous` is a launch discipline: the conductor starts role sessions with tool allow-lists (`mcp` only, no Bash) through `services/runner.py`.

## 5. Gates per autonomy level

### 5.1 How a policy is computed today and after this slice

Today: `effective_policy(project, gate_id)` returns the current protocol's `gate_policies` entry, else the preset of the project's rigour mode (`services/gates.py:136-151`; the preset table `modules/presets.py:34-48`). A protocol entry below the gate's `floor` is an error in every mode (`services/protocol_rules.py:620-623`); an entry weaker than the preset is an error in `systematic`, a readiness gap in `pilot`, allowed in `exploratory` (`protocol_rules.py:625-632`, decision 84.6). Strict order: `agent < agent_audit < human` (`modules/presets.py:79`). A gate not listed in a preset is `human` in every mode.

After: `modules/autonomy.py` adds (contract C4)

- `AUTONOMOUS_FLOOR: Mapping[str, GatePolicy]`: per gate, the lowest policy it may take under `autonomous`. Absent means the gate's own floor does not apply as relaxation; the gate stays at its preset.
- `profile(level, mode) -> Mapping[str, GatePolicy]`: the baseline of a mode at a level. `attended` returns `PRESETS[mode]` unchanged. `supervised` returns, per gate, the lower of the preset and the gate's `SUPERVISED` entry below (never below the gate's floor). `autonomous` returns, per gate, the lower of the preset and `AUTONOMOUS_FLOOR` (never below the gate's floor).
- `effective_policy(project, gate_id)`: rigour preset, then the autonomy profile, then the protocol's `gate_policies` entry, never below the floor. It supersedes `services/gates.py:136` as the single read path; `mcp/server.py:4008 _agent_gate`, `services/hypothesis_gates.py:59-61 gate_policy` and `:102 may_pass`, `services/gates.py:168 gate_issues`, and the link gates (`services/reference_resolve.py:709 confirmer_ruling`, which receives the policy as an argument) all read it.

Invariants (each has a test):

1. Under `attended`, every policy equals today's. `tests/test_gates_by_preset.py` (the pinned `EXPECTED` and `PRESET_KIND` tables) passes unedited.
2. No profile or protocol entry goes below a gate's `floor`. A floor is changed only by editing the gate's declaration, a code and spec change that a human reviews; no agent act changes a floor. The floor of every gate with floor `human` (about 35 gates, review note section 2) is untouched.
3. A project's level and tier are read from `project.created` (contract C2). A legacy project has `tier None` and `autonomy_level attended`; its policies are today's.
4. The profile is a baseline, not a protocol entry: a profile weaker than the preset does not raise the decision 84.6 gap or error. A protocol entry is compared with the profile of its level, not with the bare preset (amendment of decision 84.6, section 11). The protocol hash is unchanged.

### 5.2 Which gates move

Declared floors verified in `services/modules/*.py`: `hypotheses.register` (`hypotheses.py:47`), `hypotheses.lead_decide` (`:54`), `experiments.freeze_unlock` (`experiments.py:45`), `mine.resolve` (`mining.py:71`), `writing.release` (`writing.py:69`) have floor `agent`; `reference.link_confirm` (`references.py:47`), `import.resolution_confirm` (`imports.py:43`), `manuscript.citation_confirm` (`manuscripts.py:54`) have floor `agent_audit`. All other decision gates have floor `human`.

Proposed table (the preset columns are `modules/presets.py:34-48`; "E, P, S" are the modes; `A` agent, `AA` agent_audit, `H` human; `AA(0.1,20)` is `LINK_AUDIT`, the preset's fraction and minimum). The supervised and autonomous columns are proposals for D3. "Control" is what the level adds.

| Gate | Floor | Preset E / P / S | supervised (any mode) | autonomous (any mode) | Control under autonomous |
|---|---|---|---|---|---|
| `hypotheses.lead_decide` | A | A / H / H | AA(0.1,20) in P and S; E unchanged | A in all modes, session not the proposer's | verifier session; sampled audit |
| `hypotheses.register` | A | A / H / H | AA(0.1,20) in P and S | A, drafter's and lead author's sessions excluded (`services/hypotheses.py` [unverified: review note cites :476-481]) | verifier; audit; label `autonomy=agent` and never confirmatory (section 9) |
| `experiments.freeze_unlock` | A | A / H / H | unchanged | AA(0.1,20) | non-drafter session; audit |
| `mine.resolve` | A | AA / H / H | AA | A, proposer excluded | verifier; audit |
| `reference.link_confirm`, `import.resolution_confirm` | AA | H / AA / H | AA (pilot preset extended to E and S) | AA | second agent on a recorded proposal only (`services/reference_resolve.py:709-742`); audit |
| `manuscript.citation_confirm` | AA | H / AA / H | human (service refuses non-human, `services/manuscript_resolve.py:347-355`; decision 162 proposed) | human until decision 162 is ruled otherwise | none; stays human |
| `writing.release` | A | A / A / H | A with audit in S | A | verifier of record; deferred review of the release |
| every other decision gate (floor `human`): PRESS confirmation, calibration and audit labels, screening and extraction disagreements, region, label, term, consolidation, curation and lineage gates, hypothesis close, baseline, assertion, contradiction and property approvals, notice and conclusion, inbox | H | H / H / H | H | H | not movable |

Not movable under any level, whatever D3 rules about the rows above: the hold-out split draw (a platform act, not a gate; an agent never draws or sees it, `01-rigour.md` R-20 to R-22 [unverified: text not re-read]); a protocol amendment that weakens a gate (it must be a human act, section 5.4); the PRESS confirmation (an independent critic session may review, a human confirms until D3 rules otherwise; `human_queue.Gate.PRESS_CONFIRMATION`, `services/human_queue.py:40`).

Note on the preset inversion: for the three link gates the exploratory preset is human while pilot is `agent_audit` (review note section 0). The levels do not repair this; a `brief` or `deep` project at `supervised` gets `agent_audit` for the two link gates by the profile (the row above), which is one of the visible effects of the level.

### 5.3 Independent verifier

Where an agent closes a gate under `supervised` or `autonomous`, the closing session must differ from the proposing session. The existing pattern: `confirmer_ruling` refuses a session that proposed or decided on the entry (`services/reference_resolve.py:735-738`); `hypothesis_gates.may_pass` refuses a session in `proposer_sessions` (`services/hypothesis_gates.py:128-132`); `gate_issues` refuses `proposer_session` (`services/gates.py:195-196`). The slice extends the same rule to every gate the profile moves, by one shared check in `effective_policy`'s callers; the proposing sessions are read from events, never supplied by the caller where an event records them.

The audit sample is drawn by the platform, not by an agent: `gate_audit_sample` draws uniformly from a recorded seed over the gate's agent acts (`services/gates.py:381-423`), and the draw is human-only today (`audit_core.human_gate`, `gates.py:403`). **Gap:** the existing labelling act `gate_audit_record` is also human-only (`gates.py:425-465`). The plan's third-session audit therefore needs a labelled agent audit act distinct from the human label (section 6.3).

### 5.4 Protocol gate policies

A protocol's `gate_policies` entry still overrides the profile, never below the floor. Weakening a gate is a human protocol act: under `supervised` and `autonomous` the protocol amendment that lowers any entry below the level's profile is refused when its actor is an agent, even on an unhosted project where an agent may otherwise write the protocol (`services/access.py:60-64`, `AGENT_PROPOSES_ONLY` applies only when hosted). This closes the gap the review note names (recommendation 5).

## 6. Trust ledger and deferred review

### 6.1 Ledger (contract C5)

`services/gate_trust.py`: `GateTrust(gate_id, closed_by_agent, audited, overturned, overturn_rate | None, state)` and `trust_ledger(project) -> tuple[GateTrust, ...]`. Read-only; computed from events; no new table (the index is a projection; a ledger table would change state hashes).

Counting: `closed_by_agent` is the count of agent acts at the gate (the population of `gate_audit_sample`, `services/gates.py:352 _population`); `audited` the count of sampled acts with a label; `overturned` the count labelled `correct = false` (`GateAuditLabelled.correct`, `gates.py:425-465`) or reversed in the deferred queue; `overturn_rate = overturned / audited`, `None` when `audited = 0`. State: `ok`; `watch` when the rate exceeds `WATCH_RATE` (proposed 0.05) with at least `WATCH_MIN_AUDITED` (proposed 20) audited; `pause` when it exceeds `PAUSE_RATE` (proposed 0.10). The existing gate-audit error ceiling is 0.05 (`GATE_AUDIT_ERROR_CEILING`, `services/gates.py:338`), advisory in pilot and enforced in systematic by the `gate.audit_ceiling` enforcement row of `modules/presets.py:50-71`; the ledger's `watch` threshold equals it by default, so the two never disagree (D5). The constants are named module constants, not protocol fields, so no protocol hash changes (decision 37.4 precedent).

The agent view of a ledger carries no fraction, minimum, sample size, label count or error rate, as for gate status (decision 84.8, decision 37.14). The researcher's view carries them.

### 6.2 Deferred review (contract C6)

The `human_queue` (`services/human_queue.py:37-51`, `Gate` enum, `human_queue` at `:109`) gains an item kind `deferred-review`: an agent-closed act that the platform drew into the audit sample, or one at a gate whose state is `watch` or `pause`. `digest.py`'s fixed gate list (`services/digest.py:373-376`) is extended in the same change. The human decides through a CLI act `factory review deferred decide` (human actor only). A decision that overturns an act is recorded with an existing event where one fits; otherwise one new event type `gate.review_recorded` with a design note in the lane's report (rule: no new event type without a note). An overturn does not delete anything (events are never edited); it supersedes, and every dependent output is marked stale by the existing check rules [unverified: which rule; L3 to name it].

### 6.3 Agent audit by a third session

Under `supervised` and `autonomous`, the auditor session labels the sample, as a separate role run. This needs an agent-written audit label that the existing human-only `gate.audit_labelled` does not allow (`gates.py:425-465`). Proposed: the auditor's label is recorded in a new payload field or event (L3 design note), counted in the ledger as `audited` but weighted separately: the ledger reports `audited_by_agent` and `audited_by_human`, and the state machine uses human labels when at least `WATCH_MIN_AUDITED` exist, else agent labels, and says which. An agent audit alone never moves a state to `ok` for an autonomous gate whose deferred queue is not yet reviewed in part by a human (D5, option B).

## 7. The conductor

`services/conductor.py` (contract C8) runs a plan one step at a time through `services/runner.py` (capped headless `claude -p`, an allow-list of tools, a model per stage; every run is its own MCP session). It follows the pattern of `services/spar_v2.py` (a coordinator that sequences role runs, counts and derives; state is derived from events, never stored) and of `services/pipeline.py` (ordered chain, one run at a time, stops on a failed or lost run; it covers neither frame, search, acquire, develop nor write, plan section 2 [unverified]). New runner stage specs: `frame`, `gather`, `acquire`, `write` (lifecycle ids), each with an allow-list that omits what the role must not do.

Roles: proposer, verifier, auditor as separate runs (separate MCP sessions). The conductor is bookkeeping: it never judges; every judgement is a role's.

Stop rules (all computed, none typed by an agent):

1. a failed or lost run (the step is not retried silently; `advance` may retry as a new run in a new session, as `spar_v2` does);
2. the budget is spent: `Budget(max_minutes, max_runs, max_units_per_run)` from the tier's `Limits`;
3. any gate whose trust state is `pause`;
4. a floor or hold-out violation attempt, which is refused by the service and ends the run as failed;
5. a step whose gate is not movable at the project's level (section 5.2): the conductor escalates it to the deferred queue as a waiting item and stops at that step, never skipping it.

Events: `conductor.started`, `step_started`, `step_finished`, `paused`, `finished` (system actor; design note in the lane's report). Every run carries provenance (model, skill version, `input_blob`; CLAUDE.md rule). The conductor holds no model SDK and no API key; a test asserts the `platform/` import graph contains none (plan section 6).

## 8. The level statement (contract C7)

`level_statement(project) -> LevelStatement(tier, autonomy_level, rigor_mode, steps_skipped, agent_closed, human_confirmed, lines)`; `render_level_statement(s) -> str`. Every `report_*` service output (`report_prisma`, `report_evidence`, `report_methods`, `report_search`, `report_discovery`) and the hub overview carries it. A test fails when a report lacks it. The text is labelled exploratory when the tier is `brief` or `deep`.

`human_confirmed` is true only when every gate closed in the project was closed by a human actor or reversed or confirmed in the deferred queue. Text templates (stated here so a reader can check; the lane may reword within the rule that the phrases "not human-confirmed" and "steps skipped" appear verbatim where applicable):

- attended, tier known: `Tier: <tier> (rigour mode <mode>). Autonomy: attended; every decision gate was closed by a human. Steps skipped by this tier: <list or "none">.`
- supervised: `Autonomy: supervised. <n> gate acts were closed by an independent agent session; <a> were audited, <o> overturned (<rate>). These acts are not human-confirmed until reviewed. Steps skipped: <list>.`
- autonomous: `Autonomy: autonomous. <n> gate acts at <gates> were closed by an orchestrated agent run; <a> audited, <o> overturned (<rate>); <q> await human review. THIS OUTPUT IS NOT HUMAN-CONFIRMED. Steps skipped: <list>.`
- legacy project (tier unknown): `Tier: not recorded (created before tiers). Autonomy: attended.` and, where the log carries agent acts, the count from their `autonomy` fields.
- any level: `Agent attribution is not authentication: a CLI act is recorded as human whoever ran it (decision 160).` (one line, once per document).

## 9. Registered hypotheses and decisions made by agents

An agent-registered hypothesis already carries `autonomy=agent` (`model/experiments.py`, `services/hypotheses.py` [unverified: plan section 2; review note cites `services/hypotheses.py:536`]). "Never reported as confirmatory" is text only today (review note section 4, `cli/render.py:1649` [unverified]). Under `autonomous` the platform adds a computed check hit when an agent-registered hypothesis is unlocked or reported as confirmatory without a human confirmation in the deferred queue (backs R-153).

D4 (selection by an agent). `decision.selected` is a human act: the fold drops a non-human selection (`index/decisions.py:126`), and `question_record`, `seed_add`, `probe_run`, `protocol_record` require a selection in `pilot` and `systematic` (slice 8, Binding). Exploratory may skip it. So `brief` and `deep` need nothing, and `pilot` or `systematic` at `autonomous` need an agent selection. Proposed (D4, option A): a labelled selection event, the proposing session excluded, folded as a separate `selected_by` value and shown as "agent-selected, not human-confirmed" everywhere; it does not satisfy a rule that names a human selection (decision 158: a real snowball round needs a human's selection) unless a later ruling extends it. Representation (field versus event) is for the lane L3 note.

## 10. Promotion between tiers

The mode is fixed at init (decision 161, proposed), and a tier fixes the mode, so promotion is by import, not by changing a setting (D6). A `brief` becomes a `deep` or `pilot` study by creating a new project at the deeper tier and importing the brief's works and claims through the existing library import (slice 3d). The import re-verifies against the new project (R-143: an imported record names its source, is re-verified, and is never an independent pass it did not have); the deeper study's PRISMA states the brief as a source; the brief stays as an immutable record. Seeds and screening decisions of the brief are not carried as calibration or as a second pass. `check --promote-to` (`decision 161`) still lists the gaps to the stricter mode, for information.

## 11. Relaxed or amended Decided entries

| Decision | What this slice relaxes | Proposed amendment |
|---|---|---|
| 84 item 6 (a protocol entry weaker than the preset is an error or a gap) | The baseline for the comparison becomes `profile(level, mode)`, not the bare preset; with `autonomous` the baseline can be weaker than the preset by the profile, not by a protocol entry | Amend 84.6: "weaker than the baseline of the project's mode and autonomy level". At `attended` the text is unchanged in effect. |
| 84 items 4 and 5 (gate audit draws; an act is `audited-agent` when an audit was drawn later) | Audit by an agent session is added alongside the human label | Add to 84: the audit label may come from an auditor session at `supervised` and `autonomous`, counted separately. |
| 37 item 6 (human acts via CLI or MCP relay) | None; relayed acts stay | Decision 160 (proposed) extended: the levels do not authenticate. |
| 24 (rigour modes) | None; the tier maps onto the three modes | Add a line that the tier is a second setting above the mode. |
| slice-M ruling 10 (autonomy orthogonal to class) | None; project-level and per-act autonomy stay different names | none |
| decision 158 (human go-ahead for a real snowball round) | None unless D4 option extends agent selections; the proposal does not | none |

No Decided entry is contradicted: a floor is never lowered, and `attended` is byte-identical.

## 12. Requirements (proposed; numbers continue after R-143 of `01-rigour.md`)

Section Q in `01-rigour.md`, marked **proposed** until D1 to D6 are ruled. Modes: tier column as in section 3.

| ID | Requirement | Modes |
|---|---|---|
| R-150 (proposed) | **Declared level.** A project's tier and autonomy level are set at init, recorded in `project.created`, and never changed; a legacy project is `attended` with no tier; neither value changes any old log's state hash | all |
| R-151 (proposed) | **Shortcuts disclosed.** Every output of a tier below `systematic` lists the steps its tier skipped, computed from the tier plan, in the same place as the other stated shortcuts (R-82, R-83) | all |
| R-152 (proposed) | **No floor lowered.** No autonomy level, profile or agent act lowers a gate below its declared floor; floors change only by a human-reviewed change to the declaration; a protocol that weakens a gate below the level's profile is a human act | all |
| R-153 (proposed) | **Not human-confirmed is stated.** Every output that rests on an agent-closed gate says so, with the counts of acts, audited acts and overturned acts; an agent-registered hypothesis is never reported as confirmatory without a recorded human confirmation | all |
| R-154 (proposed) | **Independent closer.** An agent closes a gate at `supervised` or `autonomous` only from a session other than the proposer's, read from events; the platform, not an agent, draws the audit sample | supervised, autonomous |
| R-155 (proposed) | **Measured trust.** The overturn rate per gate is computed from audited acts; a rate above the pause threshold stops the orchestrated run; thresholds are platform constants | supervised, autonomous |
| R-156 (proposed) | **Deferred review.** An agent-closed act drawn into the sample, or at a `watch` or `pause` gate, appears in the human queue and is decided only by a human; an overturn supersedes the act and marks dependent outputs stale | supervised, autonomous |
| R-157 (proposed) | **Bounded run.** An orchestrated run has a recorded budget (minutes, runs, units per run); it stops on a failed run, a spent budget or a `pause` state; the platform calls no model | autonomous |
| R-158 (proposed) | **Promotion by import.** A deeper study built on a shallower one imports its works and claims through the library import, re-verifies them, and never counts them as passes or calibration it did not have | all |

## 13. Acceptance

Mirrors plan section 4 and 6. One automated acceptance on the test world: a `brief` project at `autonomous`, with a fake runner, advances frame to write; every stop rule fires in its own test; its evidence report carries the autonomous statement; a `pilot` project at `attended` replays all existing gate tests unedited.

Tests that must exist before merge (plan section 6): autonomous output never presented as human-confirmed; `attended` changes no existing behaviour; no agent lowers a floor; held-out handling untouched; the platform imports no model SDK; old-log state hashes unchanged (`tests/test_old_log_replay.py`, `tests/test_state_hash_tables.py` unchanged).

## 14. Open questions

1. Where agent audit labels live (new payload field on `gate.audit_labelled` or a new event type) is for lane L3's design note.
2. The contract puts `effective_policy` in `modules/autonomy.py`; today it is `services/gates.py:136`. The lane should keep `services/gates.effective_policy` as a thin re-export so existing imports and tests do not change. `modules/` importing `services/` is blocked by the import-linter configuration [unverified: not checked]; the lane checks the direction before moving code.
3. `ProjectCreated` gaining optional fields must not change the `project` table's hashed columns (`model/project.py:15-17`; the `project` table holds `rigor_mode`, read at `services/project.py:152-157`): L1 reads tier and level from the event, not from a new column.
4. Cost and token figures in the benchmark (C9) exist only where run logs hold them [unverified].

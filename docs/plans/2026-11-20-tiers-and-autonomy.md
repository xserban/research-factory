# Plan: tiers and autonomy levels of the factory (2026-11-20)

Status: **open** (researcher's direction of 2026-11-20; build tonight, lane by lane). Binding documents still apply (`docs/specs/00-system.md`, `01-rigour.md`, `docs/decisions.md`: do not contradict a *Decided* entry; propose rows). Out of scope tonight: programmes and studies (IDEA-71 to 74).

## 1. Goal

One factory that runs at several **tiers** (speed and depth) and several **autonomy levels** (who closes the decision gates). A study (a project) declares both at `factory init`; the tier fixes the plan of stages, caps and templates, the autonomy level fixes which gates an agent may close and with which compensating controls. Every output states plainly what was skipped and what no human confirmed.

| Tier | Time | What it is | Rigour mode |
|---|---|---|---|
| `brief` | minutes to an hour | question, light frame, capped search, one-pass ranked screening, about 30 open-access papers, small extraction, cited evidence note (IDEA-41) | exploratory |
| `deep` | hours | adds protocol-lite with an independent PRESS-lite review, a capped snowball round, sampled audit, contradiction finder, agreement on a sample | exploratory |
| `pilot` | days | today's pilot: hold-out split, calibration, dual passes on a sample, human gates | pilot |
| `systematic` | weeks | today's systematic mode: dual screening, kappa floors, appraisal, full PRISMA | systematic |

| Autonomy level | Who closes a gate | Compensating controls |
|---|---|---|
| `attended` | a human (today's behaviour; the default) | none needed |
| `supervised` | an independent agent session, where the gate allows `agent_audit` | sampled audit by a third session, measured overturn rate |
| `autonomous` | an orchestrated multi-agent run | independent verifier and auditor sessions, trust ledger with a stop rule, a deferred human review queue, every output labelled "not human-confirmed" |

The two settings are independent: a `brief` can be attended or autonomous; a `pilot` can be supervised.

## 2. What exists (verified in the code, 2026-11-20)

- `modules/presets.py`: per rigour mode a policy per decision gate (`human`, `agent_audit(fraction, minimum)`, `agent`), strict order `agent < agent_audit < human`; a protocol's `gate_policies` can override a gate but never go below the gate's `floor` (`modules/contract.py` `GateSpec.floor`). About 35 gates have a `human` floor.
- `modules/contract.py`: a per-act `Autonomy` enum (`human`, `audited-agent`, `agent`), recorded on hypothesis and experiment registrations. The project-level setting here is `AutonomyLevel` (different name on purpose).
- `services/runner.py`: starts a capped headless `claude -p` process per stage with an allow-list of tools and a model per stage; every run is its own MCP session, so a proposer, a verifier and an auditor can be separate runs. `services/spar_v2.py` already sequences role runs with a coordinator.
- `services/pipeline.py` (with `work_queue.advance`): the ordered ingestion chain (screen, extract, miners, appraise, contributions, intuition), one run at a time, stops on a failed or lost run. It covers neither frame, search, acquire, develop nor write.
- `services/project_stage.py`: `derive_stage(stage_facts)` computes the stage from events.
- `services/ranking.py`, `ranked_queue.py`: local ranker with a stopping rule (IDEA-42). `snowball_round` (capped, decision 158 needs a selected decision in pilot and systematic).
- `services/human_queue.py` and `services/digest.py`: the human's queue with a fixed list of gate kinds.
- Reports: `report_prisma`, `report_evidence`, `report_methods`, `report_search`, `report_discovery`.
- Registered hypotheses and experiments already record `autonomy: human|agent` (`model/experiments.py`, `services/hypotheses.py`).

## 3. Contract (shared by all lanes; names are fixed here)

C1 **Types** (done, on branch `tiers-base`): `factory/model/levels.py`: `Tier`, `AutonomyLevel`, `RIGOR_OF_TIER`.

C2 **Project attributes** (lane L1). `ProjectCreated` (in `model/project.py`) gains optional `tier: Tier | None = None` and `autonomy_level: AutonomyLevel = AutonomyLevel.ATTENDED`, both left out of the event payload while at their defaults, so no old log changes and no state hash changes (`tests/test_old_log_replay.py` and `tests/test_state_hash_tables.py` must pass unchanged; do not add a column to a hashed table). A legacy project has `tier None`. Read API: `services/project.py` `project_levels(project) -> ProjectLevels(tier, autonomy_level, rigor_mode)`. `factory init --tier T --autonomy-level A` (default tier: none; if `--tier` is given the rigour mode is `RIGOR_OF_TIER[tier]` and `--mode` is refused when it disagrees). MCP `project_status` and `factory status` show both.

C3 **Tier plans** (lane L2). New package `factory/tiers/`: `model.py` (`StagePlan(stage_id, skill, caps: dict[str, int], skipped: bool, note: str)`, `Limits(max_papers, max_minutes, max_runs)`, `TierPlan(tier, stages: tuple[StagePlan, ...], limits, protocol_template, report_template)`); `plans.py` (typed data for the four tiers); `resolve.py`: `plan_for(tier: Tier) -> TierPlan` and `skipped_steps(tier: Tier) -> tuple[str, ...]` (what the tier skips compared with `systematic`, computed from the data, never typed twice). Stage ids are `site_catalog.STAGE_IDS` without `cross`.

C4 **Gate profiles and autonomous floors** (lane L3). New `modules/autonomy.py`: `AUTONOMOUS_FLOOR: Mapping[str, GatePolicy]` (gate id to the lowest policy a gate may take under `autonomous`; absent means the gate's own floor, so the default changes nothing); `profile(level: AutonomyLevel, mode: RigorMode) -> Mapping[str, GatePolicy]`; `effective_policy(project, gate_id) -> GatePolicy` (rigour preset, then autonomy profile, then the protocol's `gate_policies`, never below the applicable floor); every existing policy consumer (`mcp/server.py _agent_gate`, `services/hypothesis_gates.may_pass`, `gate_issues`, the link gates) reads it. An independent-verifier rule: where a gate is closed by an agent under `supervised` or `autonomous`, the closing session must differ from the proposing session (the existing `confirmer_ruling` pattern), and the audit sample is drawn by the platform, not by an agent. Under `attended` nothing changes.

C5 **Trust ledger** (lane L3). `services/gate_trust.py`: `GateTrust(gate_id, closed_by_agent, audited, overturned, overturn_rate | None, state: Literal["ok","watch","pause"])`; `trust_ledger(project) -> tuple[GateTrust, ...]`; read-only, computed from events, no new table. Thresholds are named constants with the proposed defaults (decision D5): `watch` above 5% overturned with at least 20 audited, `pause` above 10%.

C6 **Deferred review** (lane L3). `human_queue` gets an item kind `deferred-review` (an agent-closed act in the audit sample or flagged by the ledger); the human decides with a CLI act `factory review deferred decide` (human actor only); a decision that overturns an act is recorded with an existing event if one fits, otherwise one new event type `gate.review_recorded` with a design note in the lane's report (rule: no new event type without a note). `digest.py`'s fixed gate list is extended in the same change.

C7 **Level statement** (lane L1). `services/level_statement.py`: `LevelStatement(tier, autonomy_level, rigor_mode, steps_skipped: tuple[str, ...], agent_closed: tuple[GateTrust, ...], human_confirmed: bool, lines: tuple[str, ...])`; `level_statement(project) -> LevelStatement`; `render_level_statement(s) -> str`. `steps_skipped` calls `tiers.resolve.skipped_steps` when it exists (until L2 merges it returns `()` for a legacy project); `agent_closed` calls `gate_trust.trust_ledger` when it exists (until L3 merges: counts of agent-written acts from `autonomy` fields). Every `report_*` service output and the hub overview carries it; a test fails if a report lacks it. Exploratory-labelled.

C8 **Conductor** (lane L4). `services/conductor.py`: `begin_conductor(project, plan: TierPlan) -> ConductorRun`, `advance(project) -> ConductorStatus`, one step at a time through `services/runner.py` (new stage specs for `frame`, `search`, `acquire`, `report`, with tool allow-lists that leave out what the role must not do), `Budget(max_minutes, max_runs, max_units_per_run)` from the plan's limits, stop rules (failed or lost run, budget spent, any gate whose trust state is `pause`), escalation to the deferred queue, role runs (proposer, verifier, auditor as separate runs, spar_v2 pattern). New system events `conductor.started|step_started|step_finished|paused|finished` (design note in the report). The platform calls no model: each step is an outside `claude -p` process.

C9 **Benchmark** (lane L5). `services/level_bench.py`: `LevelMetrics` computed from a finished study's events (counts, elapsed time, runs, known-positive seed recall through the platform's existing recall function, agreement where present, gates closed per autonomy, overturn rate, tokens or cost where the run logs hold them); `factory bench level <project> --format json|table` (read-only).

File ownership (a lane edits only its files; shared files only as stated):
- L1: `model/project.py`, `services/project.py`, `cli/main.py` (init options, status line only), `services/level_statement.py`, report services (one call each), `hub` overview payload (one field), their tests.
- L2: `factory/tiers/*`, `plugin/skills/rf-brief/`, `cli/brief.py` (new), tests.
- L3: `modules/autonomy.py`, `modules/presets.py` (read the profile), `services/gate_trust.py`, `services/human_queue.py`, `services/digest.py`, `mcp/server.py` (`_agent_gate` only), `cli/review.py` (new), tests.
- L4: `services/conductor.py`, `model/conductor.py`, `services/runner.py` (new stage specs only), `cli/conductor.py` (new), plugin skill `rf-conductor`, tests.
- L5: `services/level_bench.py`, `cli/bench.py` (new), `docs/plans/2026-11-20-tiers-and-autonomy/benchmark.md`, tests.
- L0, R: documents only.
Shared and generated files nobody edits (the controller does): `docs/MAP.md`, `docs/decisions.md`, `CLAUDE.md`.

## 4. Lanes, order and acceptance

Order of merging into `tiers-base`: C1 (done) -> L1 -> L3 and L2 (parallel) -> L4 -> L5. L0 and R run throughout. A lane codes against the contract signatures above and uses fakes where another lane's module is not merged yet; an interface that does not exist yet is imported inside the function with a clear fallback.

| Lane | Work | Acceptance |
|---|---|---|
| L0 | Spec `docs/specs/slice-9-tiers-autonomy.md` and proposed decision rows D1 to D6 | a spec a reader can implement from; rows with options and a recommendation |
| L1 | Attributes, init options, status, level statement in every report | old logs and state hashes unchanged; every report carries the statement; test that fails when one lacks it |
| L2 | Tier plans, the `brief` plan end to end, skill `rf-brief`, `factory brief` | `plan_for` for the four tiers; `skipped_steps` computed; a brief project created and its plan listed; skill names verified |
| L3 | Autonomous floors, effective policy, trust ledger, deferred queue | `attended` behaviour byte-identical (existing gate tests unchanged); supervised pins; ledger and queue tests |
| L4 | Conductor and runner stages | steps advance through a fake runner; every stop rule has a test; the platform imports no model SDK |
| L5 | Metrics and the benchmark protocol | metrics computed on a test world; protocol document |
| R | Stage-alternatives research (template per stage, read-only) | one report per stage |

## 5. Decisions needed from the researcher (proposed defaults; lanes build the mechanism so that the default changes nothing)

- D1 Tier names and the mapping to rigour modes (as in section 1).
- D2 Meaning of the three autonomy levels (as in section 1).
- D3 Autonomous floors: which gates may go below `human` under `autonomous`, with which control. Proposed: `hypotheses.lead_decide`, `hypotheses.register`, `mine.resolve`, the link and citation confirmations and `writing.release` (independent verifier plus sampled audit); NOT movable: the PRESS confirmation of the search strategy (an independent critic session may review it, a human still confirms, until ruled), the hold-out split draw (platform act), protocol amendments that weaken a gate.
- D4 An agent's selection of a decision (`decision.selected` is a human act today and the fold drops non-human selections): under `autonomous` an orchestrator session may record a labelled selection, with the proposing session excluded; representation (a field on the event, or a new event) to be ruled.
- D5 Trust thresholds and the stop rule (section 3, C5).
- D6 Promotion between tiers: a brief becomes a deeper study by importing its works and claims into a new study (the mode and tier are fixed at init).

## 6. Rigour guards (tests that must exist before merge)
Autonomous output is never presented as human-confirmed (level statement test); `attended` changes no existing behaviour; no agent can lower a floor (floors change only by a human protocol amendment); held-out handling is untouched; the platform imports no model SDK; old-log state hashes unchanged.

## 7. Working rules for every lane
TDD for `platform/`; tests run on GitHub CI, not here: locally only mypy --strict, ruff, and each new or changed test file once alone via `data/projects/agentic-science/ops/overnight/pt.sh <worktree> <file> -q -p no:warnings` (`unset FACTORY_ROOT`); never the whole suite; never the `mcp__factory__*` tools (real pilot); never `docs/pilot/heldout-seeds.md`; CLI queries only on the reflink copy `/home/obd/Documents/Projects/rf-night-copy/data-2026-11-20` (`FACTORY_ROOT`); a worktree per lane from branch `tiers-base` (`git worktree add .claude/worktrees/tiers-<lane> -b tiers/<lane> tiers-base`); commit small; no push (the controller integrates and pushes); commit trailers `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` only, never a session link; Sonnet for subagents.

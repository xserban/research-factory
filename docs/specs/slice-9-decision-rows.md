# Slice 9: proposed decision rows D1 to D6 (tiers and autonomy levels)

Status: proposed, 2026-11-20, for the researcher's ruling. Spec: [slice-9-tiers-autonomy.md](slice-9-tiers-autonomy.md). Plan: [2026-11-20-tiers-and-autonomy.md](../plans/2026-11-20-tiers-and-autonomy.md), section 5. Last number in `docs/decisions.md` is 162; the numbers below (163 to 168) are provisional and are fixed at merge. Each row is in the table format of `docs/decisions.md` (`| # | Topic | Status | Decision / options |`) and is followed by options A, B, C with the recommendation first, ready for a questionnaire. The lanes build mechanisms so that the default (recommended) option changes nothing for existing projects.

Code facts cited below are in the spec with path:line; unverified ones are marked there.

---

## Rows (paste into `docs/decisions.md`)

| 163 | Tiers of a study and their rigour modes (slice 9, D1) | Proposed (2026-11-20) | A study declares a tier at `factory init`: `brief` and `deep` run in rigour mode `exploratory`, `pilot` in `pilot`, `systematic` in `systematic` (`model/levels.py` `RIGOR_OF_TIER`). The tier fixes the plan of stages, caps and templates (`factory/tiers/`); decision 24's modes are unchanged. `--mode` is refused when it disagrees with `--tier`. A project without a tier is a legacy project; no old log or state hash changes. The tier is fixed at init (decision 161). Every output of a tier below `systematic` lists the steps its tier skipped, computed from the plan. |
| 164 | Autonomy levels of a study (slice 9, D2) | Proposed (2026-11-20) | A study declares an autonomy level at init: `attended` (a human closes every gate; today's behaviour and the default), `supervised` (an independent agent session closes the gates that permit an agent, with a sampled audit by a third session and a measured overturn rate), `autonomous` (an orchestrated multi-agent run closes them, with independent verifier and auditor sessions, a trust ledger with a stop rule, a deferred human review queue, and every output labelled "not human-confirmed"). Tier and level are independent. The level is a project-level setting and does not authenticate: the CLI writes a human actor whoever ran it (decision 160). |
| 165 | Gates that may go below `human` under `autonomous` (slice 9, D3) | Proposed (2026-11-20; relaxes 84.6, amends 84) | Under `autonomous` (and, for the first group only, under `supervised`), these gates take the policy of the spec table: `hypotheses.lead_decide`, `hypotheses.register`, `experiments.freeze_unlock`, `mine.resolve`, `reference.link_confirm`, `import.resolution_confirm`, `writing.release`, each with an independent verifier session and a platform-drawn audit sample. No gate goes below its declared floor. Not movable: the PRESS confirmation (an independent critic session may review; a human confirms), the hold-out split draw, `manuscript.citation_confirm` (human, decision 162), every other floor-`human` gate, and any protocol amendment that weakens a gate (a human act). Amendment of 84.6: a protocol entry is compared with the baseline of the mode and level, not with the bare preset. |
| 166 | An agent's selection of a decision (slice 9, D4) | Proposed (2026-11-20) | `decision.selected` stays a human act in every fold today (`index/decisions.py:126`). Under `autonomous` an orchestrator session may record a labelled selection, the proposing session excluded, shown as "agent-selected, not human-confirmed". It does not satisfy a rule that names a human selection (decision 158 snowball go-ahead). Representation (a field on the event or a new event) is for the lane's design note. |
| 167 | Trust thresholds and the stop rule (slice 9, D5) | Proposed (2026-11-20) | Per gate, the trust ledger (`services/gate_trust.py`) computes the overturn rate over audited agent closures: `watch` above 5% with at least 20 audited (the existing gate-audit error ceiling, `services/gates.py:338`), `pause` above 10%. A `pause` stops the orchestrated run and the gate's agent closures until a human reviews the deferred queue. Thresholds are named platform constants, not protocol fields. Agent audit labels and human labels are counted separately; the state uses human labels once at least 20 exist. |
| 168 | Promotion between tiers is by import (slice 9, D6) | Proposed (2026-11-20; builds on 161) | A brief becomes a deeper study by creating a new project at the deeper tier and importing its works and claims through the library import; imported records are re-verified in the new project and never count as passes or calibration they did not have (R-143). The mode and tier of an existing project are never changed. |

---

## Questionnaire

### D1 (row 163). Tier names and the mapping to rigour modes

- **A (recommended).** Four tiers: `brief` and `deep` in `exploratory`, `pilot` in `pilot`, `systematic` in `systematic`. Reason: no new rigour mode, no change to decision 24, no hashed change; `exploratory` already has the relaxed enforcement (`modules/presets.py:50-71`, protocol readiness, calibration and audit ceilings off) that a brief needs; the tier adds the plan on top.
- B. Three tiers (merge `brief` and `deep`; `deep` is `brief` with options). Fewer names, but the protocol-lite, PRESS-lite and sampled audit of `deep` then become options and the disclosure statement cannot name the tier.
- C. A new rigour mode `rapid` between `exploratory` and `pilot`. Cleaner names, but it changes decision 24 and every preset, enforcement and check table, and old projects cannot use it.
- Other.

### D2 (row 164). Meaning of the three autonomy levels

- **A (recommended).** `attended` (human, default), `supervised` (independent agent session plus sampled third-session audit), `autonomous` (orchestrated multi-agent run plus verifier, auditor, trust ledger, deferred review, "not human-confirmed" labels). Reason: each level adds controls in proportion to what it removes; `attended` is unchanged.
- B. Two levels only: `attended` and `autonomous`. Simpler; loses the useful middle case (a `pilot` where a second agent seconds the link confirmations under audit, which pilot already does in part, `services/reference_resolve.py:709`).
- C. Autonomy as a per-gate protocol setting only, with no project-level level. Already possible through `gate_policies` (decision 84), but with no level statement, no ledger stop and no conductor semantics; and weakening is a protocol-readiness gap in pilot (84.6).
- Other.

### D3 (row 165). Which gates may go below `human` under `autonomous`

- **A (recommended).** Move only the gates whose floor is already below `human`: `hypotheses.lead_decide`, `hypotheses.register`, `experiments.freeze_unlock`, `mine.resolve`, the two link confirmations, `writing.release`; each with an independent verifier and a platform-drawn sample. Keep human: PRESS confirmation (a critic session reviews, a human confirms), `manuscript.citation_confirm` (decision 162), every other floor-`human` gate, the hold-out split draw, and protocol amendments that weaken a gate. Reason: no floor is lowered; the relaxation only lifts gates from their strict preset to their declared floor and is recorded per act. Needs the amendment of decision 84.6 (section 11 of the spec).
- B. As A, and additionally let an independent critic session confirm the PRESS review in `deep` and `brief` only (exploratory tiers, where the protocol is protocol-lite). Faster for those tiers; the PRESS confirmation is a floor-`human` gate (`services/human_queue.py:40`), so this needs a floor change in the gate declaration, a human-reviewed code change.
- C. Nothing moves; `autonomous` only orchestrates the stages and leaves every gate to the deferred human queue (a queue of everything). The safest; defeats the point of an unattended run for gates the platform already allows an agent to pass in `exploratory`.
- Other.

### D4 (row 166). An agent's selection of a decision

- **A (recommended).** A labelled agent selection under `autonomous`, the proposing session excluded, shown as "agent-selected, not human-confirmed", never satisfying a rule that names a human selection (decision 158). Needed because `pilot` and `systematic` projects at `autonomous` otherwise cannot record `question`, `seed`, `probe` and `protocol` (slice 8 Binding); `brief` and `deep` need nothing (exploratory may skip the selection).
- B. No agent selection; `autonomous` is allowed only at the exploratory tiers (`brief`, `deep`), and `pilot` and `systematic` are `attended` or `supervised` only (a human selects). The simplest and the most conservative; ties the level to the tier.
- C. Agent selections count as human-equivalent when a deferred-review item is later confirmed. More flexible; mixes the audit trail (the selection would look human at the time).
- Other.

### D5 (row 167). Trust thresholds and the stop rule

- **A (recommended).** `watch` above 5% overturned with at least 20 audited; `pause` above 10%; named constants; the run stops when any gate is at `pause`. The 5% value equals the existing gate-audit error ceiling (`services/gates.py:338`).
- B. As A, with the state computed from human labels only (agent audit labels reported but never move a state to `ok`). The safer reading; the state stays `watch` on a purely agent-audited run until a human reviews a part of the queue.
- C. Stricter: `pause` above 5% with at least 20 audited, no `watch` band. Stops earlier; more human review.
- Other (give the numbers).

### D6 (row 168). Promotion between tiers

- **A (recommended).** By import: a new project at the deeper tier imports the brief's works and claims; they are re-verified; the brief stays immutable. No mode change (decision 161).
- B. In-place promotion: an event that changes the tier and mode of an existing project (a new event type and a change to every policy read). Keeps one record; contradicts decision 161 (proposed) and the state hash rule for old logs.
- C. No promotion; a deeper study is started from scratch. Simplest; loses the brief's seeds and works.
- Other.

---

## Recorded rulings by the lane (not decisions)

1. The spec uses the lifecycle stage ids (`gather`, `write`) where the plan's conductor note says `search`, `report` (`services/site_catalog.py:29-40`).
2. The plan's C4 puts `effective_policy` in `modules/autonomy.py`; it exists at `services/gates.py:136`. The spec proposes a thin re-export so existing imports and tests do not change.
3. The plan's third-session audit has no existing agent label: `gate_audit_record` and `gate_audit_sample` are human-only (`services/gates.py:403`, `:425-465`). Recorded in the spec as a gap for L3.

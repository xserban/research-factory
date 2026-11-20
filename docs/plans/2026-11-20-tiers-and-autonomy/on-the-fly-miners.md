# On-the-fly miners (lane L12, 2026-11-20)

Status: design, with a pure check (`services/miner_proposal.py`) and a skill (`rf-miner-suggest`). It changes no admission, evidence count or gate. Proposed decision rows D7 and D8 are at the end.

## 1. Purpose

For a study's question the agent may propose a miner (a typed extraction schema) while the study runs, instead of the researcher writing every schema in advance. The pieces exist and are not changed: `miner_register` (`mcp/server.py`) and `mining.register_miner` (spec validated, recorded as a blob, the proposer stored); a miner runs only when the protocol's `miners` section lists it, on its selector population, on the researcher's requests (`on_demand`, `factory mine request`) or on given layers (`layers`; `mining.py`, `work_queue.mining_needs`); admission to the evidence layer is a separate human act (`miners.admit_miner`, `factory miner admit`), so an unadmitted miner's rows are exploratory and never enter evidence counts (R-87). The 'collaborative probe' pattern (`decision_suggest`, `decision_select`) carries the tick list.

## 2. What a proposal contains

A proposal is a miner spec (`mining/spec.py`) plus a short justification. Required content:

| Part | Rule |
|---|---|
| The question it answers | one sentence naming the study question (`question_view`) and what a row adds to answering it; in the justification and in the spec `rationale` (not in the digest) |
| Fields | typed (quote, enum, number, citation, anchor); no free text (`validate_miner` refuses it); at most 8, fewer in a brief (6, the brief schema cap); each with a definition (`description`) |
| 'Not stated' | every required quote field and every enum under a quote-demanding evidence rule has an absence outcome: `evidence.absence_values` names an enum value such as `claim/not-stated`; a row carrying it is exempt from the quote rule. A schema that cannot say 'not stated' forces an invented value |
| Quote requirement | `evidence.min_quotes_per_record >= 1` and `enum_needs_quote` true unless the proposer gives a reason |
| Scope | `selector.population`, `elements`, `heading_patterns`; use as `on_demand` (requested works) or `layers` (named layers), never the whole corpus by default |
| Population cap | `selector.max_units` (works read) is mandatory in a proposal |
| Pass count | `regime.passes`: 1 for brief, 1 plus a sampled second pass for deep (section 4), 2 for the levels that validate |
| Identity | row key fields, at least one required field, `procedure` a real skill (`rf-mine`) |

The pure check `check_proposal(spec, question=None, max_fields=8)` reports: too many fields, a field without definition, no population cap, no 'not stated' outcome where one is needed, and (when the question is given) a field whose name or definition restates the question. It is a lexical screen: a reviewer still reads the schema. It is in addition to `validate_miner`, which `miner_register` already runs.

## 3. How a proposal is recorded

No new event type. Existing events carry everything:

1. `decision.suggested` (`decision_suggest`, level `protocol`, subject `miner-<slug>`): the tick list, one item per proposed miner and, where the researcher may tune it, one item per field; `grounds` names the question, a probe or the papers read. The proposer role and model are in the event provenance.
2. `miner.registered` (`miner_register`): the spec blob, with the proposing actor (the proposer is read back by `miners.proposer`). Registering an unlisted miner does nothing else.
3. The protocol's `miners` section lists the miner with its use (`protocol_record` or `protocol_amend`), which is what lets `mine_next` serve it.
4. `decision.selected` (human) closes the tick list under `attended`; under the other levels see section 4.

Under `autonomous` a selection by an agent is not recorded today (the fold drops non-human selections; plan D4). This design therefore does not need it: an agent that self-registers does so through step 2 and 3, which are agent acts today, and labels the result; no decision is selected.

## 4. Review by tier and autonomy level

The tier fixes how much a proposed miner is worked; the level fixes who reviews the schema.

| Tier, level | Review of the schema | Run | Label on every row view |
|---|---|---|---|
| any tier, `attended` | the researcher ticks the suggested fields and miners (human gate); no registration before the selection | per the tier | none beyond the tier's |
| `brief` (any level) | the proposer self-registers at most 2 miners, one pass, on the first included works within the brief's caps | one pass, no second pass, no calibration | `exploratory, unvalidated, agent-proposed` |
| `deep` | up to 3 miners; the schema is checked by a separate session (role `verifier`, another session id, another model) before the first run | one pass plus a second pass on a sample (fraction of the tier plan, else 10%) | `exploratory, sample-validated, agent-proposed` |
| `pilot`, `systematic`, `attended` | the researcher ticks; today's calibration (`miner_calibration_label`), two passes | as today | none beyond the mode's |
| `supervised`, `autonomous` | an independent session reviews the schema before it runs: it must differ from the proposing session and model (the `confirmer_ruling` pattern); a gold sample (`factory miner calibrate draw`, platform-drawn) is judged by a session and model different from the proposer's | per the tier; without a human-labelled gold set the label says `unvalidated` | `agent-proposed schema` plus the validation line below |

Admission to the evidence layer stays human in every case (`factory miner admit`) until the researcher rules (D8). Until then a self-registered miner's rows are exploratory in every level, and the level statement and the miner views name them so.

### Relaxing 'the categories are the researcher's'

Decision 120 and IDEA-50 make the categories of a taxonomy the researcher's, and agent changes proposals. For brief and autonomous runs the agent proposes a miner schema, including its categories, without a researcher selection. This is allowed only with the label: the level statement carries `miner schema agent-proposed, not researcher-confirmed` (a line computed from the miners whose proposer is an agent and which no human admitted, the proposer already being in the log), and every row view of such a miner repeats `agent-proposed schema`. A researcher's later admission or rewriting removes the label from the rows by the ordinary admission act. Taxonomies themselves are not touched: a taxonomy stays the researcher's; this design proposes miners only.

### What counts as validated

A miner's output is `validated` only when all of the following hold: a human-labelled gold sample exists for it (`miner_calibration_label`) and its calibration meets the regime's `recall_min` and `field_agreement_min`; under `supervised` and `autonomous` the judging session and model differ from the proposer's; and a human admitted the miner. Anything less is `unvalidated` (no gold), `sample-validated` (deep: a sampled second pass agrees at the regime's thresholds, no human gold) or `agent-judged` (an independent agent judged the gold). The level statement of lane L11 prints the one that applies, computed from what ran. A claim in a report that rests on a miner is worded by that label.

## 5. Failure modes and their counters

| Failure | Counter |
|---|---|
| Vague schema (fields that any text satisfies; no definition) | definitions are required by `check_proposal`; the independent reviewer rejects a field it cannot apply to a given paragraph; calibration measures field agreement |
| Leakage of the question into the fields (a field that is the question, so the miner returns the answer the proposer wants) | `check_proposal` flags a field whose name or definition restates the question; the reviewer reads for fields that ask 'does X hold' rather than 'what does the work state about X'; every row needs a quote |
| A schema that cannot say 'not stated' | required: an absence value; a calibration on works known not to state the fact (the gold sample is drawn across the population, so it includes them) |
| Proposer judges its own work | the independent-session and model rule (D8); the platform draws the sample, no agent does |
| Population creep (a miner run on the whole corpus) | the mandatory `max_units` cap and the on-demand or layers use |
| Agent rows read as evidence | R-87: nothing unadmitted reaches evidence counts; the label on every view; admission is a human act |
| Schema churn (a new version for each paper) | a change is a new version (existing rule), and the tier caps the number of proposed miners |

## 6. Wiring left to the controller

`check_proposal` is a pure service and no tool or CLI calls it yet; the lane may not edit `mcp/server.py` or `cli/main.py`. The proposed wiring, small: run it inside `register_miner` for an agent actor when the project has a tier (a refusal with the same located issues), or expose `factory miner check <spec.json> [--question]`. Until then the independent reviewer applies the checklist of section 2 by hand, and the skill says so. The validation label lines of section 4 are the L11 level statement's.

## 7. Proposed decision rows

- **D7** Relax 'the categories are the researcher's' (decision 120) for the proposal of miner schemas under tiers `brief` and `deep` and under level `autonomous`, with the label `agent-proposed schema` on the level statement and every row view; taxonomies stay the researcher's. Options: (a) as proposed; (b) only after an attended tick list (no relaxation); (c) relax for brief only. Recommended: (a).
- **D8** Independent review of a miner schema: under `supervised` and `autonomous` (and for `deep`) a session and model other than the proposer's reviews the schema before the first run, and a gold sample is judged by such a session; admission to the evidence layer stays a human act until ruled. Options: (a) as proposed; (b) also allow audited admission by an independent judge after a measured overturn rate; (c) no review below `supervised`. Recommended: (a), revisit (b) after a benchmark run (L5).

# Hypothesis engine v1: code check (job J0, 2026-11-19)

Status: read-only code reading of the worktree `hypothesis-engine` (base 5154a953). No test run, nothing executed, no product code changed, no event written. The real pilot was read only for the rigor mode and event types (`grep` over its event files). All paths are under `platform/src/factory/` unless stated. This note answers the "to check" items of `2026-11-19-hypothesis-engine-techniques.md` (section 3, task 0, section 5) and fills its section 8.

## 0. Summary

- **Miner rows are cited with `item` (`ext_...`), not with `row` (`rk_...`).** `item` resolves for a row of any scope; `row` resolves only for an evidence-scope cell with a field named `value`, so a miner row is refused `triggers.i: unknown`.
- **The critic sees no quote for a miner row.** `ref_quote` reads claims and contribution items only.
- `claims_digest` rows expose `rk_` row keys, not `ext_` ids; the new candidate service must read the miner rows itself.
- `lead_decide` and `hypothesis_register` are human in the `pilot` mode (the pilot has no `gate_policies`).
- A literature hypothesis can be drafted, reviewed and registered in the review project; it cannot be evaluated (`incomplete`, `method-unresolved`), and `insufficient-evidence` is not what the plan says it is (section 2.4).
- No new event type or TriggerKind is needed for slice 1. Two small code changes are advisable (section 4: B1, B2).

## 1. Leads

### 1.1 Model (`model/hypotheses.py`)

- `TriggerKind` (l.62-77): work, row, claim, item, idea, interpretation, concept, card, match, conflict, gap, contradiction, lead, hypothesis, direction.
- `Trigger` (l.108-121): `kind`, `ref` (1-200 chars), `row` (dict or None). The ref must `fullmatch` `_REF_PATTERNS[kind]` (l.82-98). Builder kinds (`match`, `conflict`, `gap`, `BUILDER_KINDS` l.100) must carry `row`; every other kind must not (`row` given gives "a work trigger carries no row").
- `LeadInput` (l.124-129): `text` non-blank, at most `MAX_LEAD_TEXT = 600` (l.52); `triggers` 1 to `MAX_TRIGGERS = 20` (l.53); `framework` non-blank, at most 80, optional. No state, id or autonomy field.
- Id formats: work `^rf:\S+-[0-9a-f]{8}$` (`model/work_ids.py:15`); row `^rk_[0-9a-f]{12}$` (`model/cards.py:36`); claim `clm_<ULID>` and item `ext_<ULID>` (`model/extraction.py:46-47`); idea `IDEA_ID_RE`; interpretation `int_<ULID>`, concept `cpt_<ULID>` (hypotheses.py:46-47); card `^(mcd|pbd)_<ULID>$`; match and gap `^[0-9a-f]{16}$`; conflict `^grp_[0-9a-f]{12}$`; contradiction, lead `led_<ULID>`, hypothesis `hyp_<ULID>`, direction `dir_<ULID>`.

### 1.2 Resolution (`services/leads.py:187-208`, `trigger_issues`)

Three routes, all inside `record_lead` under `project.index.exclusive()` (l.309):

| Kind | Route | What "resolves" means | Result for a miss |
|---|---|---|---|
| work | `dangling_refs` (`_TRACE_KINDS` l.46-56) | `trace._work` (trace.py:1004): a row in `works`, else a work only a reference names (`_no_source_work`). Before that `_works_as_stored` (l.290) maps an NFC spelling to the stored id (`work_ref.resolve_work_id`) | `triggers.i: unknown` |
| item | `dangling_refs`, pattern `EXTRACTION_ID_RE` -> kind `extraction` | `trace._extraction` (trace.py:1107): `SELECT ... FROM extraction_rows WHERE extraction_id = :e`, **no scope filter, superseded rows included** | `unknown` |
| claim | `dangling_refs`, kind `claim` | `trace._claim` (trace.py:1157): `extraction_claims.claim_id`. These are the claims of the evidence extraction pack (minted `services/extraction.py:1437`), **not** m-claims rows | `unknown` |
| row | `dangling_refs`; `rk_...` matches `_CELL_RE` (trace.py:154), so kind `cell`, field defaults to `value` (`_split_cell`, trace.py:537) | `trace._cell` (trace.py:1226): `extraction_rows r JOIN extraction_fields f ... WHERE r.row_key = :k AND f.field = 'value' AND r.scope = 'evidence'`. **A miner row (scope = miner name) never resolves under `row`** | `unknown` |
| idea, interpretation, concept | `dangling_refs` (idea pattern trace.py:165; layer patterns `layer_trace.py:42-49`) | the idea or layer row exists | `unknown` |
| card, contradiction, lead, hypothesis | `_TABLE_KINDS` (l.57-62): `SELECT 1 FROM cards / contradictions / leads / hypotheses` | row exists (any state) | `unknown` |
| match, conflict, gap | `_builder_row_current` (l.109): re-runs `matching.match`, `finders.find_conflicts`, `finders.find_gaps` and compares the stored row | the builder still returns the identical row; `_gap_current` accepts only the six keys `rows_axis, columns_axis, filters, row, column, count` (l.64, 162) | `trigger-stale` |
| direction | `DIRECTION_RESOLVERS` filled by `services/directions.py:277-278` | a closed direction exists | `unknown` |

Important detail: `dangling_refs` (trace.py:494-508) only judges refs whose pattern `_parse` recognises. All `_TRACE_KINDS` patterns are recognised, so none can pass by being unparsed. A ref that is well formed but unknown is dangling.

**Where miner ids are minted.** `ext_` ids: `services/extraction.py:1345` (`project.ids.new("ext")`, every pass row of every scope, evidence, contribution and miner) and `services/shared_mining.py:924` (imported rows). `rk_` keys are content hashes of a row's fields (`row_key` column of `extraction_rows`, indexed). One `rk_` can have several `ext_` (pass A, pass B, imports).

**Answer to the plan's first test.** `ext_` of a miner row resolves under `item` (any scope, live or superseded). `rk_` of a miner row does **not** resolve under `row`. The technique rows' `UseRow.extraction_id` (technique_graph.py `RawRow.extraction_id`, from `live_rows(..., scope=MinerScope(miner))`, l.304-318) is therefore a valid `item` ref. `item` resolving a superseded row is a looseness: the queue should check liveness itself (`live_rows` / `recorded_row`).

### 1.3 `lead_record`

- Service: `record_lead(project, actor, item: LeadInput) -> str` (leads.py:302). Refused with nothing written: actor kind not agent or human (`actor`); a trigger that does not resolve (`triggers.<i>: unknown` or `trigger-stale`); an NFC-ambiguous work id (`triggers.<i>`). A malformed trigger, an empty trigger list, text over 600 fail `LeadInput` at the boundary. It writes `lead.recorded` with `prior`, `prior_total`, `keys` computed at write time; `input_blob` for an agent actor; `refs = [lead_id] + non-builder trigger refs`.
- MCP (`mcp/server.py:3866`): `lead_record(project, text, triggers: list[dict], role, model, skill, framework=None)`. It calls `_refuse_pass_session` (session that joined a screening or extraction pass is refused) and `_require_pass_opened` (`services/agent_view.py:106`: refused with "not available yet" until a screening pass has opened; the pilot has `pass.opened` events, so open there). Returns `{lead_id, prior, prior_total}`, scrubbed with `_withheld`.
- CLI: there is **no** `factory leads record`; `leads_app` (cli/main.py:391) has `list`, `promote`, `park`, `discard` only (l.7049-7107). Leads are recorded by agents through MCP.
- Permission rows (`services/access.py`): `lead_record` WORK_RUN (l.241), `lead_list` PROJECT_READ (l.292), `lead_decide` HUMAN_CONFIRM (l.254) but `lead_decide` is in `GATED_AGENT_ACTS` (l.67) so the gate policy decides; `cli:leads promote|park|discard` HUMAN_CONFIRM (l.501-503); `cli:leads list` is in `CLI_READS` (cli_access.py:92).

### 1.4 Prior and list behaviour

- `lead_keys` (l.235): every trigger `ref`, plus for a `card`/`match` the card, its subject, property keys and idea, plus both rows of a `conflict`. **Every `work` or `item` ref is a key**, so two leads citing the same work share a key.
- `prior_for` (l.258): ids of leads with state `parked` or `discarded` sharing any key (`lead_keys` table), plus hypotheses in any state (`hypothesis_prior`: via `hypothesis_keys`), plus `PRIOR_SOURCES` (the failed-directions registry), sorted, capped at `PRIOR_CAP = 50`, with `prior_total`. Open and promoted leads are **not** in the prior. Consequence for M7: a lead citing a work that any parked or discarded lead cited gets that lead in its prior, which is broad; the queue should narrow on shared `item` keys or on the same approach if it wants sharper flags.
- `list_leads` (l.364): all leads in id order, state filtered in Python after reading every row (`SELECT * FROM leads`). `agent_leads` (l.388) is the agent path: `text` is `None` unless the reading session is the author's (R-51). The MCP `lead_list` pages it; empty with a notice before a pass opens (`_before_any_pass`).

### 1.5 States, actors, gates

- `LeadState` = open, promoted, parked, discarded (l.44). `decide_lead` (l.408): service-level it accepts agent or human actors but passes `may_pass(project, actor, "hypotheses.lead_decide", proposer_sessions={author_session})`; under a `human` policy only a human passes; under `agent`/`agent_audit` any session other than the lead author. Discard needs a `DiscardReason`; `other` needs a note (at most 300). A decision supersedes the earlier one (latest wins in the projection).
- An **agent actor can record leads** (kind agent or human). The agent MCP `lead_decide` additionally refuses first with `_agent_gate` (server.py:3857) when the policy is `human`.
- Presets (`modules/presets.py:33-52`): `hypotheses.lead_decide`, `hypotheses.register`, `experiments.freeze_unlock` are `AGENT` in **exploratory** mode only; **pilot** has none of them (so default `human`); systematic none. The agentic-science project event stream holds `"rigor_mode":"pilot"` and `"gate_policies":null`, `"hypothesis_plan":null`. So in the pilot: lead_decide human, register human, as the plan says. `effective_plan` (`services/hypothesis_gates.py:67`): pilot gives `min_seeds` 3, `require_lead` true (a lead is required for a draft), `critic_distinct_model` false.
- The CLI promotes through `project.human_actor()` (main.py:7080), so the researcher at the terminal is the gate.

## 2. Hypotheses

### 2.1 `hypothesis_draft` (`services/hypotheses.py:~182-276`, MCP server.py:3952)

Signature: `draft_hypothesis(project, actor, spec: HypothesisSpec, *, supersedes=None) -> (hyp_id, H@)`. Checks (`_spec_issues`): actor agent or human; `lead` present when `plan.require_lead` (pilot: yes), the lead exists and its state is `promoted` (`lead-not-promoted`); each method ref: card must exist and be of kind `method`, idea must exist, `row_key` must be a **final** evidence row (`final_rows`, `not-a-final-row`); `conditions` keys must be comparability keys of the evidence schema (`not-a-comparability-key`; if there is no extraction schema `_comparability_keys` returns the empty set, so **any condition is refused**, `conditions` must be `{}`); `alternatives` must be existing hypotheses; `supersedes` rules.

Spec model (`HypothesisSpec`, hypotheses.py:~232): `kind` experiment|literature; `statement` (<= 600); `lead`; `treatment`, `baseline` (`MethodRef`: exactly one of `card`, `idea`, `name` <= 120, optional `row_key`); `metric` (`name`, `direction` higher|lower, `unit_family` in score|count|other|none, optional `unit`); `conditions` dict; `prediction` (`direction` treatment-better|no-worse, `margin` decimal string, `unit`); `decision_rule`; `test`; `alternatives`; `rationale` (<= 2000). Consistency: `kind == test.kind`; literature iff rule `literature-direction`; `no-worse` iff `non-inferiority`.

- **kind `literature`**: `test = {kind: "literature", window_start: <date>, sources: [<strings, <=120>...]}`; `decision_rule = {rule: "literature-direction", n_min >= 1, q in (0.5, 1]}`; prediction `treatment-better` with a `margin`. **There is no comparability-key requirement on the window beyond `conditions`, no search spec and no evidence-source check at draft**: `sources` is free text ("the search runs or protocol versions that define later literature"). `H@` hashes kind, treatment, baseline, metric, conditions, prediction, rule, test (sources sorted); the statement does not enter.
- **kind `experiment`**: `test = {kind: "experiment"}`, rule `superiority` or `non-inferiority`. Draft needs no design; a frozen design (`experiments.freeze_unlock`, exploratory AGENT, otherwise human) comes later via `experiment_design`.
- The platform prints the falsifier (`falsifier_text`, hypotheses.py): for a literature rule "Refuted if at least q% of at least n_min later-literature comparisons of treatment and baseline on <metric>(<conditions>) favour the baseline."

### 2.2 Draft, review and register in a REVIEW project

Yes for all three. Nothing in draft, `review_next`, `record_review` or `register_hypothesis` reads an experiment-design pack or evidence rows when the methods are given by `name` and `conditions` is `{}`. Registration (`register_hypothesis`, hypotheses.py:~490): state draft/reviewed; in pilot an eligible review recommending `register` is required (`review-required`/`not-recommended`; exploratory: optional); human gate in the pilot; systematic mode also refuses `cutoff-unknown`/`contaminated` flags. Cut-off flags (R-53) come from `cutoff_flags_of` and a human's `model.cutoff_declared`; these are warnings in pilot (`modules/hypotheses.py`).

### 2.3 Critic (`services/hypothesis_review.py`, MCP `hypothesis_review_next`, server.py:4019)

- Served `ReviewTask` (model l.~340): `hypothesis_id`, `h_version`, `spec_without_prose` (only the `HASHED_FIELDS`: kind, treatment, baseline, metric, conditions, prediction, decision_rule, test), `statement`, `triggers` (kind, ref, builder `row`, and `quote`), computed `prior` and `prior_total`, `checklist` (falsifiable, measurable, single-factor, baselines-named, rule-complete, prior-addressed, conditions-in-evidence). **Never** the lead text, the lead's `input_blob`, or the rationale (R-51).
- `quote` comes from `finders.ref_quote` (hypothesis_review.py `_triggers`, only for `claim` and `item`): `_lookup` (finders.py:220) reads `extraction_claims` for `clm_` and `contribution_item` (contributions.py:481, **scope CONTRIBUTION only**) for `ext_`. **For a miner row `ext_` the quote is `None`.** The critic therefore sees a bare id for every technique or m-claims trigger.
- Refusals (`critic_refusal`): not agent/human; session equal to the drafter's or to the lead author's (`drafter-session`, `lead-author-session`); with `critic_distinct_model` (systematic) the same model (`same-model`). Needs the task budget (`require_for`, a refusal only when a budget is set and exhausted). Tasks are `hyp_review` tasks, one per version, oldest draft first; a failing item allows only `revise`/`reject` (`inconsistent`).
- A review is "eligible" in the projection only when the critic's session is neither the drafter's nor the lead author's (index/hypotheses.py:435). Three sessions are therefore needed (lead author may equal drafter).

### 2.4 Evaluation and `insufficient-evidence`

- `insufficient-evidence` is a flag of `apply_literature_rule` (hypotheses/rules.py:79): added when `n < n_min`, where `n` is the number of works that compare the two methods in an evidence group meeting the conditions and metric, published on or after `window_start`. Outcome `inconclusive`.
- It is **not** returned when the methods cannot be found in evidence at all: `_recompute_literature` (evaluation.py:152-223) then sets `method-unresolved`, outcome `incomplete`, and `evaluate_hypothesis` refuses with `method: method-unresolved` unless `request_incomplete=True`. Evaluation reads `evidence_report` groups, i.e. extraction rows of **evidence scope** with the pack's `method_name` field; miner rows and contribution rows are not evidence.
- In agentic-science (no comparability-keyed evidence rows per the plan) a registered literature hypothesis evaluates to `incomplete` / `method-unresolved`, not `insufficient-evidence`. The plan's sentence ("evaluation would give `insufficient-evidence`") is wrong in that respect; the honest forecast is "unresolved until an evidence schema with a `method_name` field and comparability keys exists".

## 3. Input sources

### 3.1 Technique service (`services/technique_graph.py`, `model/technique_graph.py`)

- `read_inputs(project) -> Inputs` (l.184): memoised per last folded event; `Inputs.rows: tuple[RawRow]` with `approach, stage, work_id, extraction_id, status, evidence, described_as, quote, anchor, parameters`; `Inputs.works` (title, date, year, layer) and `cites`. `RawRow.extraction_id` is a live pass-A row id of a technique miner at the listed version (stale rows and works outside the miner population are dropped, l.296-306).
- `UseRow` (model l.101): `approach, stage, work_id, extraction_id, status, evidence, described_as, quote, anchor, parameters`. `Labelled`/exploratory marker on nodes and candidates; `Candidates.klass == "interpretation"`, `exploratory True`, `notice`.
- `ChallengeCandidate` (l.261): `approach` (`Approach`, with `.id`), `failed: tuple[UseRow]`, `supported: tuple[UseRow]`, `statement`. All rows listed (no cap): the triggers are `item` = each `extraction_id`, plus `work` of each `work_id`. At most 20 triggers per lead: a challenge with many rows must be cut deterministically (e.g. one best quote row per work, `_quote_row` ordering, technique_graph.py:703).
- `CombinationCandidate` (l.245): `a`, `b`, `co_works` (all), `works_a`, `works_b`, `support_a`/`support_b` (work ids, capped at `SUPPORT_CAP = 10`), `quote_a`/`quote_b` (a `UseRow` each, with `extraction_id`). Triggers: `item` of both quote rows, `work` of `co_works` (or none: gap-like combinations have `max_co_works` 0 default, so `co_works` is empty by default, use the `support_*` work ids instead).
- `GapCandidate` (l.232): `approach`, `from_stage`, `to_stage`, `works` (work ids of the approach at the from stage), `works_with_to_stage`, `quote` (a `UseRow`, only for the first few). Triggers: `item` of `quote.extraction_id` when present, `work` of `works` (cap 20 total).
- Public functions: `technique_challenges(project, *, layer="core", limit=100)`, `technique_combinations(project, min_works, max_co_works, stage, layer, limit, rank_by, top)`, `technique_gaps(project, *, from_stage, to_stage, min_works=3, max_to_share=0.0, layer, limit, rank_by, top)` returning `Candidates`.

### 3.2 `claims_digest` (`services/claims_digest.py`)

- `claims_digest(project, spec: SelectionSpec, *, miner="m-claims") -> ClaimsDigest` (l.168); `ClaimsDigest.papers: tuple[DigestPaper]` with `code, work_id, title, rows: tuple[ClaimRow], gap, served_version`.
- `ClaimRow` (l.78): `row_key` (**`rk_`**), `status` (`final`, `pass-a-only`, `gold`, `calibration`), `version`, `claim_type`, `about`, `direction`, `evidence_type`, `strength`, `claim_quote`, `claim_anchor`, `conditions`, `conditions_anchor`. Claim types ordered limitation, negative-result, failure-analysis, finding, mechanism, `no-limitation-stated` (`ABSENCE_TYPE`, l.57), others after. `gap` values: `reviewed-empty`, `newer-version-only`, `no-rows`, `absence-only`.
- **No `extraction_id` is exposed** (`RawMinerRow` has `status, row_key, fields, version` only, paper_profile.py:207). The `rk_` cannot be used as a trigger. To obtain an `ext_` for a limitation row, read `live_rows(project, PassLabel.A, scope=MinerScope("m-claims"))` (`services/extraction.py`, as technique_graph.py:304 does) and match `row_key` and `fields["claim_type"]`; a final row from pass B/resolution carries `FinalField.extraction_id` per field (`extraction_agreement.py:239`, `final_rows(project, scope=...)`). `gold` rows (the researcher's labels) have no `ext_`; skip them as trigger sources and say so.
- The digest scrubs held-out tokens in titles, values and quotes (`held_out_tokens(include_work_ids=False)`), work ids are not scrubbed. It needs a `SelectionSpec` and a pinned selection (`resolve_selection_cached`) and a listed miner (`miner` not in protocol: `FactoryValidationError` on `miner`).

### 3.3 `corpus_search` (`services/corpus_search.py:230`)

`corpus_search(project, queries: Sequence[str], spec: SelectionSpec, *, limit=20, per_work_limit=3, kinds=None, method="keyword", embedder=None) -> SearchResult(hits, digest, index, method, note)`. Callable from any service with a `Project`; no MCP session. It needs the pinned conversions of the selection (`resolve_selection_cached`), builds or extends the passage sidecar (`passage_index.ensure_indexed`; the sidecar is the only thing written, never an event), 1 to `MAX_QUERIES` (10) queries. Embeddings are optional: `keyword` needs none; `vector` needs passage vectors (embedded on demand when at most `ON_DEMAND_MAX` = 300 are missing, else refused naming `factory passages embed`; unavailable model gives a refusal for `vector`, a keyword fallback with `note` for `hybrid`). `Hit` carries `work_id, title, passage_id, anchors, section_path, text, rank, keyword_rank, vector_rank, conversion_id, section_kind`. Hits are scrubbed of held-out tokens (work ids are not). The MCP tool wrapper adds only `_refuse_pass_session` and `_withheld`. For M5 (corpus overlap) a keyword run is deterministic and offline; the sidecar build is the cost (first call on a selection indexes every pinned conversion).

## 4. What blocks or reshapes slice 1 (tasks 1 to 6)

| # | Finding | Affects | Minimal adjustment | Needs a decision? |
|---|---|---|---|---|
| B1 | The critic gets `quote = None` for a miner `item` (ref_quote reads contribution scope only), so a technique or m-claims lead reaches the critic as bare ids; the lead text is hidden from it (R-51). The plan's task 4 assumes the critic reads exploratory rows. | tasks 4, 6 | Extend `finders._lookup`/`ref_quote` to fall back to `extraction_rows` + `extraction_fields` (any scope; the verified `quote` field of the row) when `contribution_item` is None, and label the scope in `ReviewTrigger`. No event, no TriggerKind. Smallest alternative without code: the drafter copies the verified quotes into the hypothesis `statement` (<= 600, visible to the critic), which is weak (the critic cannot verify them). | A one-line note under the decision row for "triggers may cite miner rows": the critic sees miner-row quotes. R-51 is unchanged (the quote is evidence, not proposer prose). |
| B2 | `row` (`rk_`) is not a valid trigger for miner rows (resolves only as an evidence `value` cell); the plan (section 3a, 5) says "`item` or `row`". | tasks 1, 3, 4 | Use `item` only. The candidate service must never emit `row` for miner rows; test 9 (made-up `item` refused) stays; add a test that a miner `rk_` as `row` is refused so nobody "fixes" it. | None |
| B3 | `claims_digest` has no `ext_` id; its `rk_` cannot be a trigger. | task 1 | Read m-claims rows with `live_rows(..., scope=MinerScope("m-claims"))` (and `final_rows` where a final row exists), reuse `claims_digest._rank`/`CLAIM_ORDER` and the held-out scrub; do not call `claims_digest` for the id. | None |
| B4 | A lead holds at most 20 triggers; challenges can list many rows; `lead_keys` makes every cited work a prior key, so M7 flags any lead sharing a work with a parked/discarded lead. | tasks 1, 2 | Cap triggers per candidate (best quote row per work via `_quote_row` order, then work ids) and state the cut in the item; compute M7 on shared `item` ids and approach id, show shared-`work` hits separately. | None |
| B5 | `item` resolves superseded or stale miner rows (`trace._extraction` has no liveness filter), so `record_lead` will accept a trigger the miner has since replaced. | tasks 1, 2 (M9) | The candidate service lists only live, non-stale rows (same filters as technique_graph.py:296-306); M9 recomputes liveness for open leads. | None |
| B6 | The plan forecasts `insufficient-evidence` for registered literature hypotheses in this project; the real result is `incomplete`/`method-unresolved` (section 2.4). | section 5 table, task 6, researcher choice 4 | Correct the wording. The first-run success measure should read "registered, evaluation incomplete: method-unresolved (no evidence-scope rows)". | Choice 4 stays the researcher's; the platform behaves as designed (D2). |
| B7 | `conditions` must be `{}` in this project (no extraction schema, so no comparability keys) and `unit_family` must be chosen from score, count, other, none (technique hypotheses will mostly use `none` or `other`). | task 4 (skill text) | State both in `rf-ideate`/`rf-hypothesis-engine`; the critic checklist item `conditions-in-evidence` is then `n/a`. | None |
| B8 | A lead needs a human promote (pilot): CLI `factory leads promote`; MCP `lead_decide` refuses an agent. `hypothesis_draft` refuses `lead-not-promoted`. The acceptance run cannot be fully unattended. | task 6 | The run note lists promote as a researcher step; for an unattended rehearsal use a copy with a promote done by the CLI `human_actor` (a copy of the pilot, never the pilot). | None |
| B9 | No CLI `leads record` exists; `lead_candidates` hands the agent the exact trigger list and the agent calls MCP `lead_record`. | task 3 | As planned; do not add a CLI record command in slice 1. | None |
| B10 | `lead_list` reads and parses every lead (`SELECT *`, Python filter), `hypothesis_prior` lists every hypothesis for every `record_lead`. Fine for hundreds of leads, not for thousands. | tasks 2, 5 | `lead_queue`/`lead_stats` read `leads`, `lead_keys`, `lead_triggers` by SQL once per call. Do not call `prior_for` per candidate (it syncs the index and lists hypotheses). | None |

No change needs a new event type or a new `TriggerKind`. Option B of section 3b (a `technique-candidate` kind) is not required by any finding above.

## 5. Implementation notes for the builders

**Services to call**
- Candidates: `technique_graph.technique_challenges / technique_combinations / technique_gaps` (layer `core`), `technique_graph.read_inputs` for rows and works; m-claims rows via `services.extraction.live_rows(project, PassLabel.A, scope=MinerScope("m-claims"))`, `stale_extractions(project, scope=...)`, `paper_profile.listed_miner_versions(project)` (miner version, listed miners only), `extraction_agreement.final_rows(project, scope=...)`. Claim ordering/absence: `claims_digest.CLAIM_ORDER`, `ABSENCE_TYPE` (absence rows never become triggers; count only).
- Trigger check: `leads.trigger_issues(project, triggers)` (empty list means `record_lead` would accept; it runs `dangling_refs` once for all trace kinds). Do not copy its logic.
- Queue: `leads.list_leads(project, states=...)` or SQL on `leads`, `lead_triggers`, `lead_keys` (index/hypotheses.py tables); `leads.prior_for(project, keys, exclude=...)` for one lead at a time only; `directions.registry_query` and `hypotheses.list_hypotheses` for M7; `corpus_search.corpus_search(project, queries, SelectionSpec(...), method="keyword")` for M5; `work_layers.layers_for`, `search.works_by_ids` for work metadata; cites from `technique_graph.Inputs.cites` or `references_list` for M1/M2.
- Stats: events and tables of leads, hypotheses (`list_hypotheses` states), registrations, reviews; `directions` rows for refusals; counts are computed and printed with denominators.

**Conventions**
- Read-only: services take `Project`, never write an event, call `project.index.sync()` first. Wrap multi-read derivations in `with project.index.snapshot(), call_memo.entering():` only for short scans (claims_digest.py:177); `snapshot` blocks writers and refuses `exclusive()`. For long scans follow `technique_graph.read_inputs`: no index lock held across the scan, memo keyed by project dir and `index.last_event_id()`, a `_GUARD` lock for the dict and per-key locks so concurrent misses share one scan, `_stable` rebuild when events arrive mid-scan, a small bounded cache (`_CACHE_MAX = 4`). Resolve selections before the snapshot (`resolve_selection_cached`, claims_digest.py:172).
- Models: frozen pydantic `StrictModel` (`model/base.py`); candidate models in `model/lead_candidates.py` with the exploratory label and miner version as non-optional fields (as `Candidates` in `model/technique_graph.py`: `klass: Literal["interpretation"]`, `exploratory: Literal[True]`, `notice`).
- Errors: `FactoryValidationError([ValidationIssue(field, reason)])`; validate at the boundary.
- Held-out: no masking in services (decision 37.9); the MCP wrapper calls `_withheld(opened, data, include_work_ids=False)`; refuse pass sessions with `_refuse_pass_session`; `_require_pass_opened(opened, "<field>")` before naming works.
- Import layering: evidence-side modules do not import the intuition layer (separation scan, hypotheses.py:41-44); `services.hypotheses` imports `services.leads`, which imports `services.directions` lazily; avoid an import of `services.hypotheses` from `lead_candidates` at module level (cycle risk: leads <-> hypotheses <-> directions).

**MCP registration**
- Tool in `mcp/server.py`: `@server.tool()` inside `build_server`; open with `open_project(settings, project, session=session, clock=clock)`, `_refuse_pass_session`, `_require_pass_opened`, return `_reply(project, fn, include_work_ids=False)` with `_withheld`; the read-only technique pattern is `_technique_reply` (server.py:3106, labels refusals with the exploratory notice). New work-id parameters must be listed in `tests/test_mcp_work_params_guard.py` (`RESOLVES` or `EXEMPT`).
- Permission: a row in `TOOL_PERMISSIONS` (`services/access.py`): `lead_candidates` and `lead_queue` `Permission.PROJECT_READ` (next to `lead_list`, l.292). A tool without a row is refused by `command_permission`.
- Site catalogue (`services/site_catalog.py`): `_READ_ONLY` list (l.~60-90) takes the two new read tools; tools no skill names are flagged `orphan-tool` until `rf-hypothesis-engine`/`rf-ideate` cite them.

**CLI**
- `leads_app` commands in `cli/main.py` (after `leads list`, l.7049): `leads candidates`, `leads queue`, `leads stats`; render helpers in `cli/render.py`. Each read command must appear in `CLI_READS` (`services/cli_access.py:34-`) as `"leads candidates"`, `"leads queue"`, `"leads stats"` (the entries are `cli:<command>`; existing: `"leads list"`, l.92), or the command is refused on a server root.

**Tests that list tools or gates**
- `tests/test_mcp_server.py` (tool-name list around l.100-200: add `lead_candidates`, `lead_queue`), `tests/test_mcp_hypotheses.py` (`TOOLS` l.38-50; session and actor helpers `tests/hypothesis_helpers.py`: `agent_actor`, `promoted_lead`, `make_spec`), `tests/test_mcp_work_params_guard.py`, `tests/test_registry_ownership.py::test_gate_floors_reproduce_the_decided_entries` (the plan's "test_gate_floor_table": it lists gates by floor; nothing changes when no gate is added), `tests/test_gate_acts_refuse_non_humans.py` (lead_decide/register stay human), `tests/test_site_catalog.py` and `tests/test_site_catalog_map.py` (stage map counts: every tool lands in a stage; new tools need a stage through the skills that name them), `tests/test_plugin.py` (skill tool lists, l.191-342: a skill that names a tool must be in the allowed list; `rf-hypothesis-engine` must follow it), `tests/test_runner_skill_tools.py` (every tool a skill names is allowed or excluded with a reason), `tests/test_cli_technique.py` (CLI read pattern with `CLI_READS`).
- Gate tests: no new gate, so nothing to add to `modules/presets.py` or `services/modules/hypotheses.py`.

## 6. Wrong or uncertain statements in the plans

1. Techniques plan 3a and task 0: "citable as `item` or `row`": only `item` works for miner rows (1.2, B2).
2. Techniques plan section 5 table and "test-kind question": `insufficient-evidence` is the wrong forecast; `incomplete` with `method-unresolved` is the actual result when no evidence rows name the methods (2.4, B6).
3. Techniques plan task 4: "the critic reads ... every cited exploratory row appears as exploratory in the statement" is satisfiable only through the statement (the lead text is hidden); the critic sees no miner quote (B1).
4. Techniques plan 3b Option A: "the lead stores the miner version in its text": the text is capped at 600 characters and invisible to the critic and to other sessions (only the author's session reads it, `agent_leads`); the queue must store or recompute the miner version itself.
5. Task 1 says candidates are omitted "with fewer than one resolvable trigger": `trigger_issues` is the right test, but note that it does not test liveness (B5).
6. Task 6 "The proposer session must not have run a screening, extraction or contribution pass (the platform refuses it)": true as a tool-level refusal (`_refuse_pass_session`); the eligibility rule for the critic is session based (drafter, lead author), not model based in pilot (`critic_distinct_model` false).
7. Plan claim "`gap` check ... a technique candidate cannot reuse `gap`": confirmed (leads.py:159-184, six keys and a `find_gaps` re-run).
8. Everything else I checked in sections 3 and 5 of the techniques plan (trigger kinds, `dangling_refs` kinds, builder kinds' keys, pilot human gates, require_lead, no `leads record` CLI) is consistent with the code.

## 7. Not verified

- No test or code was executed. The pilot has no lead events (`grep`), so `record_lead` against real miner rows is unrun. `trace._extraction` resolution of an `ext_` of a real m-claims or technique row follows from the SQL (no scope filter) and should be confirmed by the first test of task 1 (test 9 of the TDD list).
- Whether a project budget would refuse `hypothesis_review_next` (`require_for`): not checked beyond the call site.
- Whether the pilot's index currently has the full set of tables (the stale `index.sqlite` has no `project` table; the rigor mode was read from the event stream instead).

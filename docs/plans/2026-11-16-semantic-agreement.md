# Semantic agreement for miners: stable row alignment, secondary labels as sets, an equivalence judge

Status: plan for the researcher's validation (2026-11-16). Nothing built, nothing run. Backlog: IDEA-53; builds on IDEA-52 (evidence overlap), IDEA-68 (unit ignored), IDEA-69 (unmatched rows in the rate), IDEA-50 and 51 (versioned miner specs, `miner add`), IDEA-64 (design choices explicit), IDEA-37 (miners).
Depends on: `services/extraction_agreement.py`, `mining/score.py`, `mining/spec.py` and `mining/compile.py`, the `mine agreement`, `mine status` and `miner calibrate` commands, `services/site_agreement.py` (hub product), the projector and the event registry (a new event is proposed, so decision 132 below).
Binding: `00-system.md` (events append-only, index a projection, MCP conventions), decision 37 (independence of passes), decisions 86 and 91 (miner spec and calibration), R-xx on dual extraction and agreement.

## 1. Goal and non-goals

Goal. The agreement reported for a miner measures whether two passes found the same thing, not whether they pointed at the same words or wrote the same row key. Three corrections, each declared in the miner version before its run:

1. rows are aligned on the work (one-row miners) or on an enum key (multi-row miners), never on a quote;
2. optional secondary labels are compared as sets with the primary, and a label only one pass gave is a completeness figure, not a disagreement;
3. free-text and quote fields that differ in wording are judged by an agent outside both passes, who records `same`, `partial` or `different` with a reason; the platform counts the verdicts.

Quotes stay mandatory as evidence for every value (verified against the text as today); they are never the measure of meaning.

Non-goals.
- The platform calls no model. The judge is a Claude session working through MCP tools; its verdicts are events.
- No change to which pass is right: gold labels (calibration) and the audit stay the arbiter. Agreement is a consistency measure.
- Calibration scoring against gold keeps exact and IDEA-52 comparison for text fields in v1 (the gold is a person's label; judging it by a model is a separate decision). Alignment is not changed there (gold rows already carry the key).
- Disagreement review feeding new miner versions (IDEA-53 item 5) is not built; the judged `different` pairs make that review possible later.
- Enum, number, anchor and work-reference fields keep exact comparison.
- No re-run of any recorded pass; no event is edited or removed.

## 2. Current behaviour

Alignment (`services/extraction_agreement.py`):
- `_read_state` groups eligible rows by `(work_id, pass, row_key)` (line 638) and makes one `_Pair` per `(work, row_key)` (639). `_Pair.aligned` (508) is true only when the work is dual and each pass holds exactly one row under that key.
- The row key comes from the miner's `row_key_fields` (`pack_row_key`). For a field of kind quote or anchor the key holds a sentence or location, so a correct row written with another span is "unmatched" (IDEA-52 why; `m-descriptors` v3: 10 aligned, 37 unmatched). `compile.keyed_on_work` (`mining/compile.py:79`) already keys a derived single-dimension miner on the work (IDEA-69 (1)); hand-written miners with an enum key (`m-classification`, `m-mapping`, `m-summary`, `m-descriptors`) are not covered.

Comparison:
- `_same` (394) and `same_field` (409): equal `reported_in` and `reproduced`, and equal `_normalised` value and unit (IDEA-68: unit ignored where the kind carries none). `_compare` (421) runs it over declared compared fields of an aligned pair. With the opt-in `evidence_overlap` threshold, a free-quote field also agrees on same anchor, token containment or token Jaccard (`evidence_overlaps`, 359; IDEA-52).
- `mining/score.py` `score` (75) uses `same_field` (119) for gold against agent, aligned on `row_key` only (102).
- A field present in one pass only is `kind="missing"` and counts as compared and not agreed (`_compare`).
- A `*_secondary` field has no special rule in the platform; the hub implements one separately.

Rates:
- `_tally` (889): `overall` = agreed over compared values of aligned pairs; `overall_all_rows` adds the compared values of unmatched slots (`_unmatched`, 869; IDEA-69 (2)). Both are returned by `extraction_agreement` (969), `agreement_overall` (932), and shown by `mine agreement` and `mine status` (`agreement_aligned` is the aligned rate, `services/mining.py:908`).
- The 0.90: `Regime.field_agreement_min` (default 0.9, `mining/spec.py:137`), raised to a rigour-mode floor (`mining/calibration.py:23-40`). It gates the calibration score's aligned `field_agreement`, not the production agreement, which is reported and withheld while units are open (`agreement_overall`).

Hub (`services/site_agreement.py`): a second, separate implementation, the "fairer measure" (`measure`, 83): rows per work or on an enum key (heuristic `MULTI_ROW_RATIO` 1.3, line 37, inferred from the observed rows), enum values by value, `*_secondary` as sets by name suffix (135-142), one-sided secondary counted as `one_sided`, text pairs listed for a judge "in a later step" (159). It is display only; it feeds nothing the gate reads. Two implementations of one idea can drift.

Recomputed numbers (IDEA-69, on a copy of the pilot events): aligned → all rows → if aligned by work: `m-classification` v1 0.576 → 0.248 → 0.588; `m-descriptors` v3 0.347 → 0.121 → 0.198; `m-mapping` v2 0.636 → 0.239 → 0.614; `m-summary` v2 0.639 → 0.271 → 0.707. Hub on enum values: `data_secondary` 0/5 and `field_secondary` 0/6 (filled by one pass only).

## 3. Design

All three parts are declared in the miner spec before a run and are part of the version. Spec block (new, optional; omitted means today's rules, so existing spec blobs and digests do not change, as for `taxonomy`):

```
agreement:
  alignment: key | work            # default key
  label_sets: [{primary: F1, secondary: F2}, ...]   # default none
  judge: {fields: [F3, F4], partial_weight: 0}      # default none
```

Registration (`validate.py`, also run by `miner add --check`) refuses: `alignment: work` with a spec whose `row_key_fields` is more than a single enum or empty; `alignment: key` declared by a new version whose key fields include a quote or anchor field (default key remains allowed for old versions only: the check applies to a spec that has an `agreement` block); a `label_sets` entry whose fields are not enums of the same allowed values; a `judge` field that is not a free quote or `TEXT` without `allowed`. The block is recorded in the miner's registration event and shown by `miner list` and the hub, as the regime is.

### Part 1. Row alignment

Data model. No stored change: pairs are computed at read time. `_Pair` gains `row_key_b` (pass B's key, equal to `row_key` unless work-aligned) and `slot` (the aligned identity).

Algorithm (`services/agreement_align.py`, pure, new):
```
slot(pack, row) =
  "" (the work)                       if pack.agreement.alignment == work
  join("|", normalise(v) for each enum key field value of row)   if alignment == key and all key fields are enum
  row.row_key                         otherwise (legacy: unchanged behaviour)
align(work, rows_a, rows_b, pack) -> list of pairs
  group rows of each pass by slot
  for each slot in sorted(slots_a | slots_b):
     pair is aligned iff the work is dual and exactly one row of each pass is in the slot
     otherwise it is unmatched (a pass holding the slot twice, or one pass only)
  pair.row_key = pass A's row_key if present else B's
```
Work alignment: if either pass holds more than one live row for the work, the work is one unmatched slot (never a silent choice of row); `mine disagreements` shows it as a `row` disagreement as now. `_unmatched` (slots and values of IDEA-69 (2)) is unchanged and uses the new pairs.

Resolutions (`mine.resolve`) name `(work, row_key, field)`. The pair's `row_key` is pass A's key, which is what an existing resolution of a legacy-aligned pair already names; a resolution that no longer names a pair (possible only after a version re-registers with a new alignment, which makes a new version with its own rows) is listed as orphaned in `check`, not applied.

Effect on rates. For a work-aligned miner, rows the legacy key left unmatched become aligned: the denominator of `overall` grows by their compared values and agreement is the rate on the real overlap; `overall_all_rows` falls less because fewer slots are unmatched. The gate (below) reads the figure under the declared rules.

### Part 2. Secondary labels as sets

Data model. `label_sets` pairs a primary and a secondary enum field of one dimension. (Choice Q2: by declaration, not by the name suffix the hub uses.)

Algorithm (`services/agreement_rules.py`, pure, new; `_compare` and `score` call it). For a set `(P, S)` on an aligned pair with `PA, SA` the values of pass A (absent = None) and `PB, SB` of pass B, and `setA = {PA, SA} \ {None}`, `setB` likewise:
- `P` is compared strictly as an ordinary enum: compared when present in either pass, agreed iff `PA == PB` (both present). A swapped primary (`PA == SB` and `PB == SA`) is still a disagreement and is counted as `swapped` in the report.
- `S` is compared only when both passes gave it: agreed iff `SA in setB or SB in setA`; otherwise a disagreement of kind `value`.
- `S` given by exactly one pass: not compared (no disagreement, not in the denominator); counted in a completeness record `{field, both, a_only, b_only}`.
- Absent in both: skipped, as now.
`reported_in` and `reproduced` must still match for a compared field, as in `_same`.

Effect on rates. A one-sided secondary leaves the denominator, so the rate rises where the legacy rule counted `missing`; a both-given secondary that equals the other pass's primary now agrees. The completeness figure is reported beside the rate so that a pass that leaves secondaries empty is visible, not hidden. Primary agreement is unchanged.

### Part 3. Equivalence judge

Which pairs. For each aligned pair and each `judge.fields` field: if `_normalised` values are equal (and `reported_in`, `reproduced` match), the pair agrees without a judge. Otherwise it needs a verdict. Where a judge is declared, the IDEA-52 `evidence_overlap` shortcut is not applied to those fields (same anchor is not same meaning; Q10). Fields not in `judge.fields` keep exact comparison.

Event (proposed, decision 132): `extraction.pair_judged`.
```
miner, version, scope, work_id, slot, field,
pair_digest = sha256(canonical json of: miner, version, work_id, slot, field,
              a_extraction_id, a_normalised_value, a_normalised_quote,
              b_extraction_id, b_normalised_value, b_normalised_quote)
verdict: same | partial | different,  reason (required, non-empty)
provenance: model, skill version, input_blob (the task blob shown to the judge), actor/session
```
Latest event per `pair_digest` wins (supersession; no edit). A judgement is current iff its `pair_digest` equals the digest of the pair now computed; a changed row (re-extraction, supersession) makes the digest differ and the pair pending again. Projection table `pair_judgements` (rebuildable) holds the latest verdict per digest.

A second event, `extraction.judgement_audited` (researcher label: agree | overturn, with the researcher's verdict and a note, by `pair_digest`), supports the audit of the judge (below). Both are in decision 132.

Service (`services/pair_judge.py`, new):
- `judge_next(project, actor, miner, limit)`: pending pairs of dual works in a deterministic order (sha256 of `pair_digest`), each as a task: work id, slot, field name and definition (description, allowed form), the two values and quotes and anchors, `input_blob` of the task. Side order is blinded: side "1" is A when `sha256(pair_digest)[0]` is even, else B; the mapping is recomputed by the platform, never sent. The tool carries no rate.
- `judge_record(project, actor, task_ref, verdict, reason)`: validates at the boundary (pair still pending and digest unchanged, verdict in the enumeration, reason non-empty, session independent), writes one event; invalid input writes nothing and returns structured errors.
- Independence: the judge session must not have joined either extraction pass of this miner (`is_extraction_session`, as `extraction_agreement` already refuses) and must not be a resolver of the same pair. Model rule per Q5.
- `pair_verdicts(project, miner)`: read-only map digest → verdict, with counts.

Rubric (in the judge skill, `rf-agreement-judge`, versioned; the skill version is the provenance): `same` = the two values state the same fact about the work so that the researcher would use either interchangeably; `partial` = one is a part of the other or they overlap but one adds or omits a point that matters for the field's purpose; `different` = they state different facts or contradict. The judge reads the field's description; it does not decide which is right, and does not read the other fields of the row unless the task includes them.

Effect on rates. Verdict weight `w`: same = 1, partial = `partial_weight` (default 0), different = 0. A judged field adds 1 to the compared count and `w` to the agreed count. A pair with no current verdict is pending. While any judged-field pair is pending, `overall` and `overall_all_rows` are withheld (None) with `pending_judgements` stated, as the rate is withheld while units are open (Q4). The report also gives `overall_strict` (every judged field compared exactly, i.e. what the legacy rule would say under the declared alignment and label sets) beside the gated figure, so the effect of the judge is always visible.

### The 0.90 gate and the aligned rate

- Today the 0.90 gates only the calibration `field_agreement` (aligned, exact). Part 1 and 2 apply to the calibration score too for label sets (gold secondary against agent secondary by the same set rule); calibration alignment and judge are unchanged (Non-goals).
- For production agreement the declared rule produces `overall` (aligned pairs; Part 2 and 3 applied) and `overall_all_rows` (plus unmatched slots; IDEA-69). `field_agreement_min` is compared to `overall_all_rows` under the declared rules (Q9), so unmatched rows never flatter the gate and the semantic rules cannot be chosen after the result because they are in the digest. `mine status` shows: strict (legacy rules), declared-rules aligned, declared-rules all rows, pending judgements, completeness, judge audit.
- Rates are never compared across versions that declared different rules without saying so: the hub labels each figure with its rule set.

### Backwards compatibility with recorded runs

- Nothing recorded changes: rows, resolutions and miner registrations stay as they are; no event is rewritten.
- A spec without an `agreement` block computes the legacy figures to the digit (a test pins `m-layer`, the layer case of IDEA-69, and the `test_agreement_evidence_overlap` cases).
- The existing hand-written miners cannot gain a declared rule without a new version (the digest changes, so passes must be re-run). To measure them under the new rules without re-running, `mine agreement MINER --recompute alignment=work` and the hub give a labelled, non-gating recomputation (shown as "recomputed, not declared"), computed by the same service and recorded in the result (as `evidence_overlap` is). The hub's present "fairer measure" becomes this service call, so the two implementations are one.
- `ExtractionAgreement`, `AgreementOverall` and `CalibrationScore` gain optional fields with defaults; consumers that ignore them (briefing, methods, evidence report, dashboard) are unchanged and keep reading `overall`.
- The projector gains one table; a rebuild from events reproduces it.

## 4. Test list (TDD; written first, not run while testing is paused)

Alignment (`test_agreement_align.py`):
1. legacy: spec without block, quote-keyed rows, pairs identical to the present (`m-layer` 34 aligned, 12 unmatched, 0.850 all rows).
2. work alignment: two passes with different row keys, one row each, become one aligned pair; row_key is A's.
3. work alignment, a pass with two rows: one unmatched slot, no aligned pair, `row` disagreement.
4. enum key alignment: key `stage`, keys equal ignoring case/whitespace align; a pass holding a key twice is unmatched.
5. single-pass (non-dual) work never aligns; unmatched slot counting (IDEA-69) unchanged.
6. registration refuses `work` alignment with a multi-field key; refuses key alignment on a quote key field in a block-bearing spec.
7. resolution recorded under the legacy pair still applies; an orphaned resolution is listed.

Label sets (`test_agreement_label_sets.py`):
8. secondary equal to the other pass's primary agrees; secondary in the other's secondary agrees.
9. one-sided secondary: not compared, completeness counts a_only/b_only; rate denominator excludes it.
10. both given, different, neither in the other's set: disagreement kind `value`.
11. swapped primaries: primary disagrees, `swapped` counted.
12. refuses a set whose fields have different allowed values; set absent from the compared list.
13. calibration `score` applies the set rule; unchanged without a block.

Judge (`test_pair_judge.py`, `test_pair_judge_projection.py`):
14. identical normalised value: agrees without a task; different wording: appears in `judge_next`.
15. task order deterministic; side order blinded and reproducible; no rate or pass label in the payload.
16. `judge_record` writes one event with provenance (model, skill version, input_blob) and refuses: unknown pair, stale digest, empty reason, bad verdict, a session that joined a pass, a session that was already a resolver of the pair; nothing written on refusal.
17. a second verdict on the same digest supersedes; a changed row (new digest) makes the pair pending again; the old verdict is kept in the events.
18. rate arithmetic: same 1, partial `partial_weight` (0, 0.5), different 0; pending withholds the rate and reports the count; `overall_strict` equals the legacy rule.
19. IDEA-52 `evidence_overlap` is ignored for judged fields and recorded as ignored; still applies to unjudged free-quote fields.
20. projection rebuild equals the live table; audit events counted (agree/overturn), overturn rate reported.
21. the hub measure and the service give equal figures on one fixture (replaces the duplicate implementation).
22. the judge MCP tools take no `project` that is not open, honour the held-out rules (no change to held-out handling), and the CLI lines render deterministically.

## 5. Tasks (branch `semantic-agreement`; 1 to 3 hours each; one commit each)

0. Decision 132 proposed (events `extraction.pair_judged`, `extraction.judgement_audited`; the spec `agreement` block; the gate reads the declared-rules all-rows rate). Files: `docs/decisions.md`, `docs/specs/00-system.md` event list. Docs only, 1 h. Blocks 4, 5.
1. Spec block: `AgreementDecl` dataclass, parse, digest only when non-default, validation, `miner add --check` output. Files: `mining/spec.py`, `mining/validate.py`, `mining/compile.py` (`Pack.agreement`), `services/miner_add.py`. Tests 6, 12 (registration parts). rf-builder-critical (spec digest). 2.5 h. Depends on 0.
2. Alignment: `services/agreement_align.py`, use in `_read_state`, `_Pair.row_key_b`, resolution matching and orphan listing. Files: `services/extraction_agreement.py`, new module. Tests 1–5, 7. rf-builder-critical (agreement core). 3 h. Depends on 1.
3. Label sets: `services/agreement_rules.py`, `_compare`, `_tally` completeness record, `score`. Files: `services/extraction_agreement.py`, `mining/score.py`. Tests 8–13. rf-builder-critical. 3 h. Depends on 1; independent of 2 (merge order 2 then 3).
4. Judge events and projection: event models and validators with provenance, projector table `pair_judgements`, `judgement_audited`. Files: `model/events/`, `index/` projector and schema, event registry. Tests 17 (projection part), 20. rf-builder-critical. 3 h. Depends on 0.
5. Judge service: `pair_judge.py` (`judge_next`, `judge_record`, `pair_verdicts`, independence), pending set, digest. Tests 14–17. rf-builder-critical. 3 h. Depends on 2, 4.
6. Rates: tally integrates verdicts, `partial_weight`, pending withholding, `overall_strict`, ignored overlap, new result fields, gate comparison in `miner` status. Files: `services/extraction_agreement.py`, `services/mining.py`, `mining/calibration.py` reading point. Tests 18, 19. rf-builder-critical. 3 h. Depends on 3, 5.
7. MCP and CLI: `mine_judge_next`, `mine_judge_record`, `factory mine judge next|record|audit|status`, `mine agreement --recompute alignment=work`, rendering. Files: `mcp/server.py`, `cli/main.py`, `cli/render.py`. Thin wrappers. rf-builder. 2.5 h. Depends on 5, 6.
8. Judge skill `rf-agreement-judge` (rubric above; version recorded in provenance) and the audit sampler (deterministic sample by `sha256(pair_digest)`, size per Q6). Files: skill file in the plugin directory, `services/pair_judge.py`. Test 16 (skill version). rf-builder. 2 h. Depends on 5.
9. Hub: `site_agreement.py` replaced by service calls; columns strict / declared rules / recomputed, judge counts, audit, completeness; labelled rule set per figure. Test 21. rf-builder. 3 h. Depends on 6.
10. `factory check` rules: stale judgement (digest no longer current), orphaned resolutions, pending judgements for a miner marked done. Files: `services/check.py`. rf-builder. 1.5 h. Depends on 5.
11. Landing: `gen_map.py` regeneration, backlog status, one Sonnet review (guard mutation on tasks 2, 3, 5, 6 per the build-review lessons). Done by the lander, not on this branch's plan commit. 2 h.

Tests are written first with each task but not run while the testing pause holds; mypy and ruff must pass.

## 6. Risks

- Judge drift and leniency: a model that finds most pairs `same` inflates agreement. Mitigation: blinded sides, rubric with a `partial` category, audit sample with overturn rate reported beside every judged rate, strict rate always shown, judge model recorded.
- Circularity: models judging models. The judge never decides which value is right; gold labels and the researcher's audit stay the arbiter.
- Cost: `m-descriptors` v3 had about 199 fields filled by both passes, 28% equal exactly, so about 140 pairs to judge for 28 works; a layer-wide run is a few thousand tasks. Mitigation: only judge-declared fields, batches, deterministic order, Haiku allowed if Q5 permits.
- Withholding the rate while judgements are pending can block a hub page or a release. Mitigation: pending count shown; the strict rate is always available.
- Denominator shifts make figures incomparable across versions that declare different rules; mitigated by labelling, not solved.
- Spec change: the `agreement` block must stay out of the digest when default, or every registered version changes; a test pins this.
- Work alignment can hide real multi-row structure (two rows of one work). It is refused (one unmatched slot), not merged.
- Same-anchor shortcut (IDEA-52) disagrees with meaning; ignored where a judge is declared.
- Blinding is partial: values and quotes can reveal the pass's model style. Accepted; recorded.
- Two implementations (platform and hub) until task 9; do not merge task 9 before 6.

## 7. Open choices for the researcher

Q1. Existing miners (`m-classification`, `m-descriptors`, `m-mapping`, `m-summary`) have recorded passes under legacy rules. What do they get?
- A (recommended): new rules apply to new versions only (declared in the spec); existing runs get a labelled, non-gating "recomputed" figure by the same service.
- B: new versions only; no recomputation of existing runs.
- C: re-register the four as new versions with the declared rules and re-run the passes (cost: full re-mining).

Q2. How are primary and secondary labels paired?
- A (recommended): declared in the spec (`label_sets`), part of the digest.
- B: by the `_primary` / `_secondary` name suffix, as the hub does now (no spec change; brittle).

Q3. What does `partial` count as in the gated rate?
- A (recommended): 0 (conservative); a lenient figure at 0.5 is shown beside it.
- B: 0.5.
- C: excluded from the denominator and reported as its own count.

Q4. A judged-field pair without a verdict yet:
- A (recommended): the rate is withheld with the pending count (strict rate still shown).
- B: counted as a disagreement provisionally, the rate marked "provisional".
- C: counted as agreement on the strict rule only if the quotes overlap (IDEA-52), else pending.

Q5. Judge independence:
- A (recommended): a session that joined neither pass and did not resolve the pair; any model, recorded.
- B: also a model different from both passes' models.
- C: the researcher judges a first sample per miner version; an agent judge is used only after the agent's verdicts match the researcher's at a declared rate.

Q6. Audit of the judge and its consequence:
- A (recommended): a deterministic 10% sample, at least 20 verdicts per miner version, all `partial` verdicts included; overturn rate reported, no automatic block.
- B: the same sample, and an overturn rate above 10% blocks the version's agreement from being reported as passed.
- C: 20 verdicts per version, no `partial` oversampling.

Q7. Judge scope:
- A (recommended): free-quote and text fields only, declared in `judge.fields`.
- B: also enum fields flagged `judgeable` in the spec (for near-synonym labels).

Q8. Where the rules are declared:
- A (recommended): a new spec block `agreement` next to the regime (digest unchanged when omitted).
- B: inside the existing `regime` (changes `regime` serialisation and defaults).
- C: in the protocol, per miner (amendment per change).

Q9. What the 0.90 (`field_agreement_min`) is compared to for production agreement:
- A (recommended): the declared-rules rate over all rows (unmatched rows count against it).
- B: the declared-rules rate over aligned rows only (today's meaning).
- C: both must reach it.

Q10. IDEA-52 `evidence_overlap` on a field with a declared judge:
- A (recommended): ignored; the judge decides, the setting is recorded as ignored.
- B: applied first as a shortcut to `same`, the judge sees only the rest.
- C: refuse the combination at registration.

Q11. Calibration scoring (gold against agent):
- A (recommended): label sets apply; alignment and judge do not (v1).
- B: nothing changes in calibration.
- C: label sets and judge apply, the researcher's gold text judged by an agent judge.

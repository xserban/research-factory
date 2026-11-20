# Schema, Extraction, Verification, Dual Extraction, Agreement and Audit Implementation Plan (slice 2, sub-plan D)

Status: merged (plan 2D, implemented per CLAUDE.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Dependencies.** Plan C (full-text screening, branch `plan-2c-fulltext-screening`) must be merged first: this plan reads the full-text stage (`final_outcomes(project, stage=FULL_TEXT)`, `fulltext_queue`, the `stage` column, `screening_plan`). **Decision 49 (converters for LaTeX and PDF) is still pending.** Extraction must work on any converted document, whatever the converter: it reads only the manifest and Markdown through `resolve_anchor` / `conversion_manifest`, never converter-specific structure. Tests build documents from the existing HTML fixture and from hand-written Markdown with anchors (`tests/document_helpers.py`), not from a particular converter.

**Goal:** For each work included at full text, let Claude extract schema-driven rows (and atomic claims) from a pinned conversion, have the platform verify every quote, number and table cell, run dual extraction with field-level agreement, human resolution and a human audit of agreed values.

**Architecture:** The protocol gains an amendable, hashed `extraction_schema` section that names a versioned in-repo domain pack (`ml-benchmark`) and the fields used. Extraction mirrors screening's machinery with its own small event family: passes A and B (independent sessions and models, decision 37), one task per (work, pass) pinned to a conversion, a verifying `extract_record` that writes valid rows and reports invalid ones, supersession for corrections, amendment-driven staleness, agreement by field, human choice between verified alternatives, and an audit of agreed values. Pure helpers (number normalisation, citation markers, verification) live in `factory/extraction/`; services wire them to the index and library; `mcp/` and `cli/` only parse and format.

**Tech Stack:** as plans A-C; `decimal.Decimal` for numbers; no new dependencies.

**Spec:** `docs/specs/slice-2.md` (Extraction schema `ml-benchmark`; Verification; Comparability, interfaces only; Extraction quality; acceptance 5-11 and 14 in part; 12 and 12a are plan E, D supplies their inputs). `docs/specs/01-rigour.md` R-13-R-15, R-40, R-42 (inputs), R-43-R-47. Decisions 37, 39, 40, 46-48, 50 (Proposed). Backlog IDEA-23 (copied-result consistency check) is out of scope.

## Rulings made in this plan

Rulings marked **[confirm]** go beyond the spec or decide an ambiguity; the researcher confirms them at plan review. Task 12 records the ones that need a decision as decision 51 (*Proposed*).

**Consumers.** Plan E (evidence report, `2026-11-04-evidence-report.md`) uses `final_rows`, `grouped_rows`, `independence_counts`, `agreement_overall`, `live_claims` / `ClaimRow`, `unit_states` and the projection columns `extraction_rows.row_key` / `extraction_fields.field` (rulings 16 and 18).

1. **Schema location.** `ProtocolSpec.extraction_schema: ExtractionSchema | None = None`, an amendable hashed field in `AMENDABLE_FIELDS`, left out of every hash while `None` (as plan C did for `full_text_screening`), so existing `P@` ids are unchanged. `ExtractionSchema` = `pack`, `pack_version`, `fields` (the declared subset of the pack's fields), `comparability_keys` (subset of `fields`; pack default), `dual_extract_sample` (`None` = every work), `audit_fraction` (0.02), `audit_minimum` (50), `claims` (true). Extraction is refused until it is declared (acceptance 5); readiness rules are checked against the pack.
2. **Domain pack.** `factory/packs/` holds frozen dataclasses (`Pack`, `FieldDef`) and `ml_benchmark.py` (version 1), pure data: field name, group, kind (`text|number|integer|bool`), unit family (`score|count|other|none`), allowed units, check (`number|text-in-quote|none`), normaliser. Required fields: `method_name`, `task`, `dataset`, `metric`, `value`. Default comparability keys: `task, dataset, split, metric, input_resolution, pretraining_data`. Any change to a pack is a new `pack_version`. Plan E extends the pack module with report details.
3. **Fields beyond the spec's table. [confirm]** (a) The spec's "FLOPs/MACs" becomes two fields, `flops` and `macs`, because the two are routinely conflated and the frontier choice is plan E's. (b) Every field with check `number` or `text-in-quote` needs `anchor` and `quote` when present; the other fields may carry them and they are verified if given. (c) `input_resolution` has a normaliser: `224`, `224²`, `224^2`, `224x224`, `224 × 224` all become `224x224`; other values are compared as text.
4. **A record is a row; provenance is per field.** One `extraction.recorded` event is one row of one work in one pass: `fields: {name: StoredField}`. Each `StoredField` carries `value`, `unit`, `anchor`, `cell`, `quote`, `reported_in` (`own|cited`), `reproduced`, optional agent-declared `cited_work`, and platform-computed `canonical`, `copy_marker`. A row's identity for agreement is its `row_key` (ruling 10).
5. **Pinning, units and population.** The population is the works whose full-text final outcome is `INCLUDED` (`extract_next` refuses via `screening_plan(..., FULL_TEXT)` when no full-text plan is declared). One task per (work, pass), kinds `extract_a` / `extract_b`. The task pins `(document_id, conversion_id)`: the pin of the work's latest task while its document is still the work's current document, else the current default conversion; both passes therefore share a pin. A newer *document* version (new source) makes the work's rows stale and re-queues it (spec: version rule); a new *conversion* of the same document only raises a `check` warning.
6. **Verification (R-44, acceptance 6, 7).** For each field: the anchor resolves in the pinned conversion; the quote is verbatim, after the B2 normalisation, in the anchored element (`quote_in_element`); a `cell` must resolve to exactly one cell whose table is the anchor (or is the anchor itself when the anchor is a cell); a number field whose anchor is a whole table needs a `cell`. For `check = number` the printed value, as a number (`82.4 = 82.40`), must occur as a numeric token in the quote or in the cell text; when a cell is given it must occur in the cell text. A token's suffix must agree with the declared unit (`%` only for score fields, `K/M/G/T/B` only for count fields; a token with a different suffix does not match). For `check = text-in-quote` the normalised, case-folded value must occur in the quote or cell text. Number tokens are matched whole (`82.4` never matches inside `182.45`). Rejection is per row; reasons never contain document text.
7. **Numeric normalisation (declared).** `value` is the printed number (JSON number or numeric string, no suffix or `%`); `unit` carries `%`, `fraction`, `K`, `M`, `G`, `T` or `B` (`B` = `G`). Canonical value = printed number times the unit multiplier for count fields (params, flops, macs), unchanged otherwise, as a plain decimal string without trailing zeros. A fraction is never rescaled to a percentage: units are compared, not converted.
8. **Copied results (acceptance 8). [confirm]** The platform detects citation markers deterministically in the text of every cell of the value cell's table row, or in the quote when no cell is given: bracketed numeric references (`[41]`, `[12, 14]`, `[3-5]`), parenthesised author-year (`(Wang et al., 2021)`) and bare `Author et al., 2021`, and `\cite` leftovers. The agent also declares `reported_in`. A field is *effectively cited* when either says so; a marker with an agent `own` is stored as `own` with `copy_marker = true` and counts as copied. This fails safe (false positives lower independent counts, never raise them) and is listed for the audit. `cited_work` (optional) is the agent's declared link to a corpus work and is validated to exist; the platform does not parse bibliographies. IDEA-23 stays out.
9. **Dual extraction. [confirm]** Passes A and B, one session each, different models, same checks as decision 37 items 1, 2, 6, 7, 15 (join refusals, `extract_agreement` refusal while any task is open, pass sessions refused from agreement, audit, report, check and trace). Pass B serves the schema fields in reversed order. Pass B covers `dual_extract_sample`: a work is in the sample when `sha256(f"{seed}:{work_id}")` read as a fraction of 2^256 is below the fraction; the seed is recorded on `extraction.pass_opened`. Membership is monotone in the fraction and stable when works arrive, so no extension events exist; the realised size varies around the fraction and is reported. `None` means every work. Protocol gaps: `pilot` requires a fraction; `systematic` requires `None` or `1.0`; both require `audit_fraction >= 0.02` and `audit_minimum >= 50`. Works outside the sample are single-extraction and listed (promotion gap).
10. **Agreement and resolution. [confirm]** Rows of the two passes align on `row_key` = `rk_` + first 12 hex of sha256 of the pinned conversion id and the value field's location (its cell, else its anchor and canonical value). A row present in one pass only is a disagreement of kind `row`. For aligned rows each declared field except `anchor`, `quote`, `cell` is compared: text normalised (NFKC, case-folded, whitespace collapsed; `input_resolution` by its normaliser), numbers by canonical value and unit exactly, booleans equal, `reported_in` and `reproduced` equal; present in one row only is `missing`. Agreement rate is reported per pack group. Disagreements are listed with both values and are never auto-resolved. The human resolves each field or row by **choosing** `a`, `b` or `neither` (event `extraction.resolved`); a human never types a value, so every final value stays verified. `neither` drops the field or row from final output and lists it; a corrected value then needs a new agent record.
11. **Audit of agreed values. [confirm]** The unit is one agreed field value of an aligned dual-extracted row. Size `min(N, max(ceil(audit_fraction * N), audit_minimum))` over N agreed field values (decision 37 item 3, `audit_size`), drawn at random with a recorded seed, no strata. The human sees the value, quote, anchor and the text of the cited element or cell and answers `correct` / `incorrect`. Error rate = incorrect / labelled. The ceiling is a platform constant `EXTRACTION_ERROR_CEILING = 0.05` (analogous to decision 37 item 4; **new value**), advisory in `pilot`, a `check` error in `systematic`; above it the report says to amend the schema or the skill.
12. **Corrections and staleness (acceptance 11, 5).** A corrected row or claim is a new record with `supersedes`; both stay in the log; live = not superseded. An amendment records `ProtocolAmended.extraction_stale` (computed by the platform): schema removed, pack or pack version changed, or a field added => all rows; field removed => rows carrying it; changes to `comparability_keys`, `dual_extract_sample`, audit settings or `claims` => none. A live row recorded before such an amendment is stale; a stale row is not final and its (work, pass) unit is served again. Stale and superseded rows remain readable.
13. **Closing a unit, empty works.** `extract_record(..., finish=true)` writes `extraction.closed` (computed row and claim counts, optional `reason`) and completes the task when no item in the call was rejected. A close with zero live rows and zero claims needs a `reason` (a paper with no extractable result is legitimate, not stuck).
14. **Claims. [confirm]** `extraction.claim_recorded`: `statement`, `claim_type` (`finding|mechanism|limitation|negative-result`), `evidence_type` (`experiment|ablation|theory|reported-elsewhere|author-assertion`), `strength` (`strong|moderate|weak`, the agent's judgement, stated as such), `anchor`, `quote` verified like a field quote. Claims are single-extraction (pass A only) and take no part in agreement or audit; the evidence-type and strength vocabularies are this plan's proposal.
15. **Document access.** A session in an extraction pass reads, through `document_read`, only the works of tasks it holds or completed, at the pinned conversion (the plan C gate, extended); an extraction session cannot also have joined a screening pass.
16. **Interfaces for plan E.** `final_rows(project) -> list[FinalRow]` (verified rows with status `agreed|resolved|single`, per-field provenance and `independent`), `grouped_rows(project) -> Grouped` (rows keyed by the schema's comparability keys, plus `ungrouped` and `unresolved`), `independence_counts(rows)`. Grouping never ranks; frontiers, cost axes and the report are plan E. Plan E's further requests are ruling 18.
17. **Out of scope.** Evidence report, frontiers, cost-axis rules (12, 12a), appraisal (IDEA-21), the consistency check of copied results (IDEA-23), bibliography parsing, re-extraction automation beyond ruling 12, figures as data.
18. **Further interfaces for plan E (accepted).** (a) `agreement_overall(project) -> AgreementOverall` is non-refusing and actor-free: `overall` is `None` while any extraction task is open or claimed, or when there is no schema or no pass; `dual` and `single` counts are always computed (zero without a schema). `extraction_agreement` and the methods statement use it. (b) `live_claims` returns `ClaimRow` models. (c) `unit_states` lists every included work, `queued` when never served. (d) `extraction_rows.row_key` and `extraction_fields.field` are indexed, because plan E's cell trace queries them directly.

## Global Constraints

- All plan A-C constraints hold. The platform never calls a model; no key, no SDK. Events are the source of truth; the index is rebuilt by the projector alone and the projection never reads the library.
- Every agent-written event carries model, skill reference and `input_blob` (the validated input of the call). Verification results (`canonical`, `copy_marker`, `verifier`) are computed by the platform and stored in the event, so replay needs no library.
- Quotes (already allowed in decision events) are the only document text in events; no document text appears in any error, warning or finding message.
- Invalid input writes nothing and returns structured errors; in a batch each row/claim is validated alone and valid ones are written. Business logic in `services/` (pure helpers in `factory/extraction/`); `mcp/` and `cli/` parse, call, format.
- Slice-1 and plans A-C behaviour unchanged: every earlier test passes without edits except the one `PROJECTION_VERSION` pin (Task 3). A log without `extraction_schema` replays to identical `P@` ids.
- `uv run pytest -m "not network"`, `mypy --strict` (new and changed files), ruff pass; coverage >= 90% for `services/` and `model/`.

## Review Focus

1. Number matching: `182.45` does not satisfy `82.4`; `82.40` does; a value that is only in the quote while the cited cell shows another number is rejected; `22.1M` in the cell with declared unit `G` is rejected; a `%` token never matches a count field (Tasks 1, 4).
2. Cell anchors: a numeric field citing a whole table without `cell`, a cell of a different table, an unknown cell, and a quote spanning two cells are each rejected; the other rows of the same call are written (Tasks 4, 6).
3. Independence: a pass-B session cannot claim A's task, read A's rows, read a work outside its queue, or share a model with A; `extract_agreement` refuses while any task is open and to pass sessions (Tasks 5, 8, 11).
4. Amendments: removing a field stales only rows carrying it, adding one stales all, changing comparability keys stales none, a record made before and one after an amendment are told apart by event order, and a log with no schema keeps its `P@` ids (Tasks 2, 7).
5. Copy handling and closure: a row whose table row carries `[41]` but is declared `own` counts as copied; a paper with no results closes with a reason; a zero-row close without one is refused; rebuilding the index from events gives the same state hash (Tasks 4, 6, 12).

## File Structure

- Create `factory/packs/__init__.py`, `factory/packs/ml_benchmark.py`; `factory/extraction/__init__.py`, `numbers.py`, `citations.py`, `verify.py` (pure).
- Modify `model/protocol.py` (`ExtractionSchema`, `ExtractionStale`, field, hash rule, `ProtocolAmended.extraction_stale`); create `model/extraction.py` (events, vocab); modify `events/catalog.py`.
- Create `index/extraction.py`; modify `index/default.py`.
- Modify `services/protocol.py` (stale computation on amend), `services/protocol_rules.py` (errors, gaps, `extraction_stale`).
- Create `services/extraction.py` (population, passes, tasks, record, staleness, queries), `services/extraction_agreement.py` (agreement, resolve, final rows, grouping), `services/extraction_audit.py`.
- Modify `services/document_read.py` (gate), `services/check.py`, `services/trace.py`, `services/methods.py`, `mcp/server.py`, `mcp/conventions.py` if needed, `cli/main.py`, `cli/render.py`.
- Create plugin skill `plugin/skills/rf-extract/SKILL.md`; modify `tests/test_plugin.py` (`SKILLS`).
- Tests: `test_packs.py`, `test_extraction_numbers.py`, `test_extraction_schema.py`, `test_extraction_model.py`, `test_extraction_index.py`, `test_extraction_verify.py`, `test_extraction_next.py`, `test_extraction_record.py`, `test_extraction_stale.py`, `test_extraction_agreement.py`, `test_extraction_audit.py`, `test_extraction_check_trace.py`, `test_mcp_extraction.py`, `test_cli_extraction.py`, `test_acceptance_extraction.py`; helper `tests/extraction_helpers.py` (a project with `n` full-text-included works, each converted from hand-written Markdown with one results table `t1`, a pilot protocol declaring the schema, and `row(...)` / `field(...)` builders).

---

### Task 1: Domain pack and pure helpers (numbers, citation markers)

*Tier: critical (normalisation decides what counts as a match).*

**Files:** Create `packs/__init__.py`, `packs/ml_benchmark.py`, `extraction/__init__.py`, `extraction/numbers.py`, `extraction/citations.py`; Test `tests/test_packs.py`, `tests/test_extraction_numbers.py`.

**Interfaces:**
- Produces (`factory.packs`): `class FieldKind(StrEnum)`: `TEXT`, `NUMBER`, `INTEGER`, `BOOL`; `UnitFamily`: `SCORE`, `COUNT`, `OTHER`, `NONE`; `Check`: `NUMBER`, `TEXT_IN_QUOTE`, `NONE`; `@dataclass(frozen=True) FieldDef(name: str, group: str, kind: FieldKind, unit_family: UnitFamily, check: Check, units: tuple[str, ...] = (), normaliser: str | None = None)`; `@dataclass(frozen=True) Pack(name: str, version: int, fields: tuple[FieldDef, ...], required: tuple[str, ...], default_comparability_keys: tuple[str, ...], citation_patterns: tuple[str, ...])` with `field(name) -> FieldDef | None`; `get_pack(name: str, version: int) -> Pack | None`; `ML_BENCHMARK_V1`. Groups: `identity`, `task`, `result`, `cost`, `regime`.
- Produces (`factory.extraction.numbers`): `@dataclass(frozen=True) NumberToken(value: Decimal, suffix: str | None)`; `numbers_in(text: str) -> list[NumberToken]` (whole tokens: optional sign incl. U+2212, thousands separators `1,234`, decimals, exponent; suffix one of `%`, `K M G T B` not followed by a letter); `parse_printed(value: str | int | float) -> Decimal | None` (None unless it is a bare number); `canonical(printed: Decimal, unit: str | None, family: UnitFamily) -> str`; `normalise_text(s: str) -> str` (NFKC, casefold, collapse whitespace); `normalise_resolution(s: str) -> str`; `normalise_for(field: FieldDef, s: str) -> str`.
- Produces (`factory.extraction.citations`): `citation_markers(text: str, patterns: Sequence[str]) -> list[str]` (matched markers, in order; deterministic).

- [ ] **Step 1: Tests (`test_extraction_numbers.py`, `test_packs.py`).**
```python
def test_decimal_equality_ignores_trailing_zero():
    assert parse_printed("82.40") == parse_printed(82.4) == Decimal("82.4")
def test_canonical_count_units():
    assert canonical(Decimal("22.1"), "M", UnitFamily.COUNT) == "22100000"
    assert canonical(Decimal("4.6"), "B", UnitFamily.COUNT) == canonical(Decimal("4.6"), "G", UnitFamily.COUNT) == "4600000000"
    assert canonical(Decimal("82.40"), "%", UnitFamily.SCORE) == "82.4"
    assert canonical(Decimal("0.824"), "fraction", UnitFamily.SCORE) == "0.824"   # never rescaled
def test_tokens_are_whole():
    assert [t.value for t in numbers_in("top-1 182.45 and 82.40%")] == [Decimal("182.45"), Decimal("82.40")]
    assert numbers_in("22.1M params")[0].suffix == "M" and numbers_in("12 ms")[0].suffix is None
    assert numbers_in("1,234 imgs")[0].value == Decimal("1234") and numbers_in("−3.5")[0].value == Decimal("-3.5")
def test_parse_printed_rejects_suffix_and_percent():
    assert parse_printed("82.4%") is None and parse_printed("22M") is None and parse_printed("abc") is None
@pytest.mark.parametrize("raw", ["224", "224²", "224^2", "224x224", "224 × 224"])
def test_resolution_normaliser(raw): assert normalise_resolution(raw) == "224x224"
def test_resolution_rectangular_and_other_text_unchanged():
    assert normalise_resolution("384X256") == "384x256" and normalise_resolution("Native") == "native"
def test_citation_markers():
    p = ML_BENCHMARK_V1.citation_patterns
    assert citation_markers("DeiT-S [41]", p) == ["[41]"] and citation_markers("PVT [12, 14]", p) == ["[12, 14]"]
    assert citation_markers("Swin (Liu et al., 2021)", p) and citation_markers("Wang et al., 2021", p)
    assert citation_markers("Ours [ours]", p) == [] and citation_markers("ViT-B/16", p) == []
```
`test_packs.py`: `required` fields are all in `fields`; default keys are fields; `get_pack("ml-benchmark", 1)` is `ML_BENCHMARK_V1`, `get_pack("ml-benchmark", 2)` and `get_pack("x", 1)` are `None`; `flops` and `macs` are separate COUNT fields; every field with `check != NONE` has kind TEXT/NUMBER/INTEGER; field names are unique and match `^[a-z][a-z_]*$`.
- [ ] **Step 2:** Run; expect FAIL (modules missing). **Step 3:** Implement per Interfaces; pack fields as in ruling 2-3 (identity: `method_name`, `variant`, `is_proposed`; task: `task`, `dataset`, `split`, `input_resolution`; result: `metric`, `value`, `higher_is_better`, `variance_reported`, `variance_value`; cost: `params`, `flops`, `macs`, `throughput`, `latency`, `memory`, `hardware`, `batch_size`, `precision`; regime: `pretraining_data`, `training_epochs`, `distillation`, `extra_data`); `value` and `variance_value` are SCORE with units `%`, `fraction`, `""`; `params/flops/macs` COUNT with units `K M G T B ""`; `throughput/latency/memory` OTHER; `method_name`, `dataset`, `metric` check TEXT_IN_QUOTE; all other number fields check NUMBER; the rest NONE. **Step 4:** Tests, `mypy --strict`, ruff pass. **Step 5:** Commit `feat(extraction): ml-benchmark pack, number normalisation, citation markers`.

### Task 2: Protocol section, readiness rules and amendment staleness

*Tier: critical (protocol hash, amendments).*

**Files:** Modify `model/protocol.py`, `services/protocol_rules.py`, `services/protocol.py`; Test `tests/test_extraction_schema.py`.

**Interfaces:**
- Consumes: `get_pack`, `ScreeningPlan`, `AMENDABLE_FIELDS`, `_OMITTED_WHEN_NONE`.
- Produces (`model/protocol.py`): `class ExtractionSchema(StrictModel)`: `pack: str`, `pack_version: int = Field(ge=1)`, `fields: tuple[str, ...]` (non-empty, unique), `comparability_keys: tuple[str, ...]` (unique), `dual_extract_sample: float | None = Field(default=None, gt=0, le=1)`, `audit_fraction: float = Field(default=0.02, ge=0, le=1)`, `audit_minimum: int = Field(default=50, ge=0)`, `claims: bool = True`; `ProtocolSpec.extraction_schema: ExtractionSchema | None = None` added to `AMENDABLE_FIELDS` and `_OMITTED_WHEN_NONE`; `class ExtractionStale(StrictModel)`: `all_records: bool`, `fields: tuple[str, ...] = ()`; `ProtocolAmended.extraction_stale: ExtractionStale | None = None`.
- Produces (`protocol_rules.py`): `extraction_stale(old: ExtractionSchema | None, new: ExtractionSchema | None) -> ExtractionStale | None` per ruling 12 (`None` when old is `None` or nothing stales); `_errors` adds, for a declared schema: unknown pack or version (`extraction_schema.pack`), a field not in the pack (`extraction_schema.fields[i]`), a pack-required field not declared (`extraction_schema.fields`), a comparability key not in `fields` (`extraction_schema.comparability_keys[i]`); `_gaps` adds the pilot/systematic rules of ruling 9 (`extraction_schema.dual_extract_sample`, `.audit_fraction`, `.audit_minimum`).
- `amend_protocol` stores `extraction_stale=extraction_stale(current.spec.extraction_schema, spec.extraction_schema)` on the event.

- [ ] **Step 1: Tests.**
```python
def test_p_id_unchanged_without_schema():
    assert protocol_version(spec_without_schema) == PINNED_P_ID   # literal computed on the current branch before the change
def test_p_id_changes_with_schema(): assert protocol_version(spec_with_schema) != PINNED_P_ID
def test_unknown_pack_field_and_missing_required_are_errors():
    errs = {i.field for i in protocol_issues(bad_spec, **ctx).errors}
    assert {"extraction_schema.pack", "extraction_schema.fields[0]", "extraction_schema.fields"} <= errs
def test_comparability_key_must_be_declared_field(): ...   # error on extraction_schema.comparability_keys[0]
def test_pilot_needs_fraction_systematic_needs_all():
    assert gap_fields(pilot, dual_extract_sample=None) >= {"extraction_schema.dual_extract_sample"}
    assert gap_fields(systematic, dual_extract_sample=0.5) >= {"extraction_schema.dual_extract_sample"}
    assert not gap_fields(systematic, dual_extract_sample=1.0)
def test_extraction_stale_rules():
    assert extraction_stale(None, S) is None
    assert extraction_stale(S, S_plus_field) == ExtractionStale(all_records=True)
    assert extraction_stale(S, S_minus("latency")) == ExtractionStale(all_records=False, fields=("latency",))
    assert extraction_stale(S, S.model_copy(update={"comparability_keys": other})) is None
    assert extraction_stale(S, S.model_copy(update={"dual_extract_sample": 1.0, "audit_minimum": 60})) is None
    assert extraction_stale(S, None) == ExtractionStale(all_records=True)
    assert extraction_stale(S, S.model_copy(update={"pack_version": 2})) == ExtractionStale(all_records=True)
def test_amend_records_extraction_stale_and_reports_other_change():
    result = amend_protocol(...)              # remove "latency"
    amended = list_amendments(project)[-1]
    assert amended.extraction_stale == ExtractionStale(all_records=False, fields=("latency",))
    assert "extraction_schema" in amended.other_changes and amended.semantic is True
def test_old_amendment_event_validates_without_extraction_stale(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Whole existing protocol and amendment suites still pass unedited, mypy, ruff. **Step 5:** Commit `feat(protocol): extraction schema section, readiness rules, amendment staleness`.

### Task 3: Events and projection

*Tier: critical (events, index).*

**Files:** Create `model/extraction.py`, `index/extraction.py`; modify `events/catalog.py`, `index/default.py`; Test `tests/test_extraction_model.py`, `tests/test_extraction_index.py`; update the single pin in `tests/test_fulltext_index.py` (`PROJECTION_VERSION == "20"`).

**Interfaces:**
- Produces (`model/extraction.py`), ids `EXTRACTION_ID_RE = ^ext_ULID$`, `CLAIM_ID_RE = ^clm_ULID$`, `EXTRACT_AUDIT_ID_RE = ^xau_ULID$`, `ROW_KEY_RE = ^rk_[0-9a-f]{12}$`, `VERIFIER_VERSION = 1`; `ReportedIn(StrEnum)`: `own`, `cited`; `ClaimType`, `EvidenceType`, `Strength` (ruling 14); `FieldInput(StrictModel)`: `value: str | int | float | bool`, `unit: str | None = None`, `anchor: Anchor = None` (the screening `Anchor` annotation: document or cell anchor form), `cell: str | None` (pattern `CELL_ANCHOR_RE`), `quote: str | None`, `reported_in: ReportedIn = own`, `reproduced: bool = False`, `cited_work: str | None`; `StoredField(FieldInput)` adds `canonical: str | None`, `copy_marker: bool`; `ExtractedRowInput(StrictModel)`: `fields: dict[str, FieldInput]` (non-empty); `ClaimInput`: `statement`, `claim_type`, `evidence_type`, `strength`, `anchor`, `quote` (all required, non-blank); event payloads (all `StrictModel`):
  - `ExtractionPassOpened(pass_label: PassLabel, random_seed: int, field_order: Literal["schema", "reversed"])`
  - `ExtractionPassJoined(pass_label, session, model)`
  - `ExtractionRecorded(extraction_id, work_id, pass_label, task_id, protocol_id, schema_ref: str, document_id, conversion_id, row_key, fields: dict[str, StoredField], supersedes: str | None, verifier: int)`
  - `ClaimRecorded(claim_id, work_id, pass_label, task_id, protocol_id, document_id, conversion_id, statement, claim_type, evidence_type, strength, anchor, quote, supersedes)`
  - `ExtractionClosed(work_id, pass_label, task_id, rows: int, claims: int, reason: str | None)`
  - `ExtractionResolved(work_id, row_key, field: str | None, choice: Literal["a", "b", "neither"], reason: NonBlank, channel: Channel, protocol_id)` (`field` None = the whole row)
  - `ExtractionAuditSampled(audit_id, items: tuple[AuditItemRef, ...], random_seed, population: int, population_digest: str, protocol_id)`, `AuditItemRef(work_id, row_key, field)`
  - `ExtractionAuditLabelled(audit_id, work_id, row_key, field, correct: bool, note: str = "", channel)`
  Event types: `extraction.pass_opened`, `.pass_joined`, `.recorded`, `.claim_recorded`, `.closed`, `.resolved`, `.audit_sampled`, `.audit_labelled`, schema 1.
- Produces (`index/extraction.py`): tables `extraction_passes(pass_label PK, random_seed, field_order, event_id)`, `extraction_sessions(session PK, pass_label, model)`, `extraction_rows(extraction_id PK, work_id, pass_label, task_id, protocol_id, schema_ref, document_id, conversion_id, row_key, supersedes, superseded_by, event_id)`, `extraction_fields(extraction_id, field, value, unit, canonical, anchor, cell, quote, reported_in, copy_marker, reproduced, cited_work; PK (extraction_id, field))`, `extraction_claims(...payload columns..., superseded_by, event_id)`, `extraction_closures(task_id PK, work_id, pass_label, rows, claims, reason, event_id)`, `extraction_resolutions(work_id, row_key, field, choice, reason, event_id; PK (work_id, row_key, field); a whole-row resolution stores field `*`; last write wins)`, `extraction_audits(audit_id PK, random_seed, population, population_digest, protocol_id, event_id)`, `extraction_audit_items(audit_id, work_id, row_key, field, correct NULL, note; PK (audit_id, work_id, row_key, field))`. Indexes: `extraction_rows(row_key)`, `extraction_rows(work_id, pass_label)`, `extraction_fields(field)` (the `(extraction_id, field)` primary key does not serve a lookup by `field`); plan E's trace SQL relies on `row_key` and `field`. A new row with `supersedes` sets `superseded_by` on the prior row (and likewise claims). Handlers are total: unknown references are stored, a repeated pass/join/close is first-write-wins.

- [ ] **Step 1: Tests.** Model: `test_field_input_rejects_unknown_key`, `test_cell_form_is_checked` (`"t2.r5.c3"` ok, `"t2.r5"` rejected), `test_agent_event_needs_input_blob` (envelope), `test_unknown_claim_type_rejected`, `test_stored_field_requires_copy_marker`. Index: `test_supersession_sets_superseded_by` (row 2 supersedes row 1: row 1 `superseded_by == ext2`, both rows present, `extraction_fields` rows for both), `test_fields_projected_per_field`, `test_resolution_last_write_wins`, `test_audit_label_sets_correct`, `test_rebuild_state_hash_stable` (replay a scripted event list twice; equal hashes), `test_slice1_and_2c_logs_unchanged` (state of every earlier table identical after replay of an existing fixture log), `test_projection_version_is_20`, `test_row_key_and_field_columns_exist_and_are_indexed` (`PRAGMA table_info` shows `extraction_rows.row_key` and `extraction_fields.field`; `PRAGMA index_list` / `index_info` shows an index whose first column is each, and `EXPLAIN QUERY PLAN SELECT extraction_id FROM extraction_rows WHERE row_key = ?` and `... FROM extraction_fields WHERE field = ?` mention `USING INDEX`).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement and register; bump `PROJECTION_VERSION` to `"20"`. **Step 4:** Tests (index suites), mypy, ruff. **Step 5:** Commit `feat(extraction): events and projection`.

### Task 4: Verification

*Tier: critical (the number check and cell checks are the platform's guarantee).*

**Files:** Create `extraction/verify.py`, `services/extraction_verify.py`; Test `tests/test_extraction_verify.py`.

**Interfaces:**
- Consumes: Task 1 helpers and pack; `conversion_manifest(project, conversion_id) -> Manifest`; `quote_in_element`; `Manifest.get`, `Anchor.kind/text/parent`.
- Produces (`extraction/verify.py`, pure): `@dataclass(frozen=True) VerifiedField(stored: StoredField)`; `verify_field(pack: Pack, field: FieldDef, entry: FieldInput, manifest: Manifest) -> VerifiedField | list[str]` returns the stored field (canonical and `copy_marker` filled) or the reasons (fixed vocabulary, no document text); `row_key(conversion_id: str, value: StoredField) -> str`; `cell_row(manifest: Manifest, cell_id: str) -> list[Anchor]` (the cells of the same table row).
- Produces (`services/extraction_verify.py`): `verify_row(project: Project, pack: Pack, schema: ExtractionSchema, row: ExtractedRowInput, conversion_id: str) -> tuple[StoredRow, list[ValidationIssue]]`-shaped result `RowVerdict(fields: dict[str, StoredField] | None, row_key: str | None, issues: list[ValidationIssue])`. Issue fields are `fields.<name>.<attr>`; one row is accepted only if it has no issue. Row-level rules: an undeclared field -> `fields.<name>` "not declared in the protocol's extraction schema" (acceptance 5); a missing pack-required field -> `fields.<name>` "required"; kind errors (`value` not parseable for number/integer, bool not bool, unit not in the field's units, integer not integral); evidence rules of ruling 6; `cited_work` must be a corpus work (`list_works`). Reasons: `quote-not-in-anchor`, `anchor-unknown`, `cell-unknown`, `cell-not-in-anchor-table`, `number-needs-cell`, `number-not-in-text`, `number-not-in-cell`, `unit-suffix-mismatch`, `text-not-in-quote`.

- [ ] **Step 1: Tests** (manifest from hand-written Markdown: table `t1` with header row `Method | Top-1 | Params`, row `DeiT-S [41] | 79.8 | 22.1M`, row `Ours | 82.40 | 25M`, and paragraph `s1.p1` "Our model reaches 82.4% top-1 accuracy on ImageNet-1K.").
```python
def test_number_in_cell_accepted_and_canonical():
    r = verify_row(project, PACK, SCHEMA, row(value=("82.4", "%", "t1", "t1.r3.c2", "82.40")), cnv)
    assert r.issues == [] and r.fields["value"].canonical == "82.4"
def test_number_absent_from_quote_and_cell_rejected():     # acceptance 6
    assert reasons(row(value=("82.5", "%", "t1", "t1.r3.c2", "82.40"))) == {"fields.value.value": "number-not-in-cell"}
def test_number_matched_as_whole_token():
    assert "number-not-in-text" in reasons(row(value=("82.4", "%", "s1.p1", None, "reaches 182.45 top-1")))   # quote verbatim needed too
def test_quote_in_paragraph_without_cell_ok(): ...         # "82.4% top-1" in s1.p1
def test_table_anchor_without_cell_rejected():            # Review Focus 2
    assert "number-needs-cell" in reasons(row(value=("82.4", "%", "t1", None, "82.40")))
def test_cell_resolves_to_exactly_one_cell_and_text_checked():     # acceptance 7
    assert "cell-unknown" in reasons(cell="t1.r9.c9") and "cell-not-in-anchor-table" in reasons(cell="t2.r1.c1", anchor="t1")
    assert "number-not-in-cell" in reasons(value="79.8", cell="t1.r3.c2", quote="Ours | 82.40")   # quote has no 79.8; cell shows 82.40
def test_quote_spanning_two_cells_rejected(): assert "quote-not-in-anchor" in reasons(quote="Ours 82.40")
def test_unit_suffix_mismatch():
    assert "unit-suffix-mismatch" in reasons(params=("22.1", "G", "t1", "t1.r2.c3", "22.1M"))
    assert reasons(params=("22.1", "M", "t1", "t1.r2.c3", "22.1M")) == {} and canonical == "22100000"
def test_percent_token_does_not_match_count_field(): ...
def test_undeclared_field_rejected_valid_fields_reported(): assert "fields.depth" in reasons(depth=3)   # acceptance 5
def test_missing_required_field_rejected(): ...
def test_copy_marker_from_row_cells():                    # Review Focus 5
    f = verify_row(... DeiT-S row declared own ...).fields["value"]
    assert f.copy_marker is True and f.reported_in == "own"
    assert verify_row(... Ours row ...).fields["value"].copy_marker is False
def test_copy_marker_from_quote_when_no_cell(): ...       # quote "DeiT-S [41] reaches 79.8%"
def test_cited_work_must_exist_in_corpus(): ...
def test_ligature_and_nbsp_quote_accepted(): ...
def test_reasons_never_contain_document_text(): assert all(DOC_TEXT not in str(i) for i in issues)
def test_row_key_equal_across_passes_and_depends_on_conversion(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement `verify_field` (anchor -> `quote_in_element(anchor.text, quote)`; cell checks; number matching with `numbers_in` and suffix rules; copy markers via `cell_row` joined text or quote) and `verify_row`. `row_key` per ruling 10. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(extraction): verification of quotes, numbers and cells`.

### Task 5: Passes, population, tasks and `extract_next`

*Tier: critical (dual independence).*

**Files:** Create `services/extraction.py`; modify `services/document_read.py` (`_gate`, `_held_pins` take the extraction kinds); Test `tests/test_extraction_next.py`, `tests/test_document_read_gate.py` (extend).

**Interfaces:**
- Consumes: Task 3 events; `final_outcomes`, `Outcome`; `default_conversion`; `create`/`claim_next`/`build_task_events`; `screening_plan`-style refusal; `current_protocol`; `make_agent_actor` (MCP layer).
- Produces (`services/extraction.py`): `EXTRACT_KINDS = {A: "extract_a", B: "extract_b"}`; `extraction_population(project) -> list[str]` (full-text `INCLUDED` works, sorted; raises `FactoryValidationError` on field `full_text_screening` when undeclared); `require_schema(project) -> tuple[ProtocolVersion, ExtractionSchema, Pack]` (refuses on field `extraction_schema` "declare the extraction schema in the protocol first (R-13)", on `protocol` when not ready, on `extraction_schema.pack` for an unknown pack); `in_dual_sample(seed: int, work_id: str, fraction: float | None) -> bool` (ruling 9; pure); `class ExtractBatchContent(StrictModel)`: `pass_label`, `instructions`, `protocol_id`, `schema_ref`, `fields: list[dict[str, str | list[str] | None]]` (name, group, kind, unit_family, units, check; pass B reversed), `required: list[str]`, `claims: bool`, `records: list[dict[str, str]]` (exactly one: `work_id, title, document_id, conversion_id`); `ExtractBatch(ExtractBatchContent)` + `task_id`; `ExtractNext(batch: ExtractBatch | None, blocked: list[str], remaining: int)`; `join_extraction_pass(project, actor, label) -> None` and `extract_next(project, actor, label) -> ExtractNext`; `is_extraction_session(project, session) -> bool`; `pass_config(project, label)`; `unit_pin(project, work_id) -> tuple[str, str] | None` (ruling 5).
- Behaviour: `extract_next` (inside `project.index.exclusive()`) refuses a non-agent, pass B under no dual sample (`blocked`), joins the session (refusals as decision 37: other pass of the same session, same model as the other pass, a session that joined any screening pass, a session that relayed an extraction label over MCP), opens the pass once (seed `secrets.randbits(32)`; B records `field_order = "reversed"`), enqueues one task per work in the pass's queue lacking a current unit (Task 7 defines "current"; until then: lacking a completed or open task), claims the next. Pass A queue = population; pass B queue = population filtered by `in_dual_sample`.

- [ ] **Step 1: Tests.**
```python
def test_refused_until_schema_declared():       # acceptance 5
    with pytest.raises(FactoryValidationError) as e: extract_next(project_no_schema, agent_a, PassLabel.A)
    assert e.value.issues[0].field == "extraction_schema"; assert no_extraction_events_written(project_no_schema)
def test_refused_without_full_text_plan(): ...   # field "full_text_screening"
def test_only_full_text_included_works_are_queued(): ...      # excluded and pending works never served
def test_task_pins_current_conversion_and_both_passes_share_it(): ...
def test_pass_b_serves_fields_reversed():
    assert [f["name"] for f in batch_b.fields] == [f["name"] for f in batch_a.fields][::-1]
def test_session_cannot_join_both_passes(): ...      # field "pass"
def test_same_model_cannot_serve_both_passes(): ...  # field "model"
def test_screening_session_cannot_extract(): ...
def test_dual_sample_is_monotone_and_stable():
    small = {w for w in WORKS if in_dual_sample(7, w, 0.3)}; large = {w for w in WORKS if in_dual_sample(7, w, 0.6)}
    assert small <= large and in_dual_sample(7, "rf:x", None)
    assert all(in_dual_sample(7, w, 1.0) for w in WORKS)
def test_pass_b_queue_is_the_recorded_sample_only(): ...   # b tasks == {w in population if in_dual_sample(seed, w, fraction)}
def test_pass_opened_event_carries_seed_and_agent_provenance(): ...  # model, skill, input_blob
def test_extract_next_idempotent_when_task_held(): ...
```
`test_document_read_gate.py`: `test_extraction_session_reads_own_queue_pinned_conversion`, `test_extraction_session_refused_other_work`, `test_extraction_session_refused_other_conversion`, `test_pass_b_session_cannot_read_a_only_work`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement; instructions text: extract only what the pinned document states, quote verbatim, give numbers as printed with the unit in `unit`, declare `reported_in = cited` for values copied from other papers, never compute or convert. **Step 4:** Tests, the plan C gate suite unchanged, mypy, ruff. **Step 5:** Commit `feat(extraction): passes, population, pinned tasks, extract_next`.

### Task 6: `extract_record`, claims, corrections, closing

*Tier: critical (recording, supersession).*

**Files:** Modify `services/extraction.py`; Test `tests/test_extraction_record.py`.

**Interfaces:**
- Consumes: Task 4 `verify_row`; `require_holder`, `complete_task`; `ClaimInput`.
- Produces: `class ExtractResult(StrictModel)`: `rows: BatchResult[str]`, `claims: BatchResult[str]`, `completed: bool`; `extract_record(project: Project, actor: Actor, task_id: str, rows: Sequence[ExtractedRowInput], claims: Sequence[ClaimInput] = (), *, finish: bool = False, reason: str | None = None, supersedes: Mapping[int, str] | None = None) -> ExtractResult`. `supersedes` maps a row index to the id of a live row of this session's pass and work that the new row corrects; a target of another pass, work or an already-superseded row is an `ItemError` (`rows.<i>.supersedes`).
- Behaviour: refusals (nothing written) for non-agent, a task not held, a task that is not an extraction task, a session not in the task's pass, a protocol no longer current (`task protocol` vs lineage: the schema must be the one the task served: same `schema_ref`; a stale task is refused). Each row verified alone against the task's pinned conversion; valid rows written in one append with the validated input as `input_blob`; claims only when `schema.claims` and only from pass A (`claims.<i>`: "claims are recorded by pass A only"), quote verified like a field quote. `finish`: refused (no event) while any item of the call is rejected; when the unit would have zero live rows and zero claims a non-blank `reason` is required (`reason`); otherwise writes `extraction.closed` with computed counts and completes the task with the live row and claim ids as results.

- [ ] **Step 1: Tests.**
```python
def test_valid_rows_written_invalid_reported():      # acceptance 6
    res = extract_record(project, a, task.task_id, [good_row, bad_number_row, good_row2])
    assert len(res.rows.written) == 2 and [e.index for e in res.rows.rejected] == [1]
    assert res.rows.rejected[0].issues[0].field == "fields.value.value"
def test_undeclared_field_rejects_row_only(): ...                  # acceptance 5
def test_correction_supersedes_and_both_remain():                    # acceptance 11
    new = extract_record(..., [corrected], supersedes={0: old_id}).rows.written[0]
    assert live_rows(project, PassLabel.A) == [new] and old_id in all_extraction_ids(project)
    assert row_event(old_id) is not None and row_event(new).payload["supersedes"] == old_id
def test_cannot_supersede_other_pass_or_work(): ...
def test_finish_completes_task_with_results(): ...
def test_finish_refused_while_items_rejected(): assert res.completed is False and task_status == CLAIMED
def test_zero_result_paper_closes_only_with_reason():                # Review Focus 5
    with pytest.raises(FactoryValidationError) as e: extract_record(..., [], finish=True)
    assert e.value.issues[0].field == "reason"
    assert extract_record(..., [], finish=True, reason="theory paper; no benchmark results").completed
def test_claims_pass_a_only_and_quote_verified(): ...
def test_claims_refused_when_schema_disables_them(): ...
def test_pass_b_session_cannot_record_on_pass_a_task(): ...   # field "task_id"/"pass"
def test_event_carries_provenance(): ...   # model, skill ref, input_blob holding the call input
def test_nothing_written_on_refusal(): ...
def test_recorded_row_stores_computed_fields(): ...   # canonical, copy_marker, verifier == 1
def test_live_claims_returns_claim_rows():            # plan E interface
    c = live_claims(project, PassLabel.A, work_id=w)[0]
    assert isinstance(c, ClaimRow) and c.claim_type == "finding" and c.conversion_id == cnv and c.claim_id.startswith("clm_")
    assert set(ClaimRow.model_fields) == {"claim_id", "work_id", "pass_label", "claim_type", "evidence_type", "strength", "statement", "anchor", "quote", "conversion_id", "event_id"}
    # a superseded claim is absent from live_claims
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement; `live_rows(project, pass_label=None, *, work_id=None) -> list[ExtractionRow]` and `live_claims(project, pass_label=None, *, work_id=None) -> list[ClaimRow]` read the projection (`ExtractionRow(StrictModel)`: extraction_id, work_id, pass_label, task_id, protocol_id, conversion_id, document_id, row_key, fields: dict[str, StoredField], event_id; `ClaimRow(StrictModel)`: claim_id, work_id, pass_label, claim_type, evidence_type, strength, statement, anchor, quote, conversion_id, event_id; superseded claims are excluded). **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(extraction): verified recording, claims, corrections, closing`.

### Task 7: Staleness and re-queue

*Tier: critical (amendments, R-15).*

**Files:** Modify `services/extraction.py`; Test `tests/test_extraction_stale.py`.

**Interfaces:**
- Consumes: `amendments_with_events(project)`, `ProtocolAmended.extraction_stale`, `default_conversion`.
- Produces: `stale_extractions(project) -> set[str]` (live row ids made stale by an amendment recorded after the row, ruling 12; compared by event id as `model/staleness.py` does); `UnitState(StrictModel)`: `work_id`, `pass_label`, `state: Literal["open", "current", "stale", "queued"]`, `reason: str | None`; `unit_states(project) -> list[UnitState]` lists one unit per (included work, pass in use) for **every** work in `extraction_population` (full-text outcome `INCLUDED`); a unit never served (no task) is `queued` (reason `None`), and an empty list only when there is no schema or no full-text plan (no refusal); a unit is *current* when its latest task is completed, was completed after the last amendment whose `extraction_stale` touches any live row of the unit (or is `all_records`), and pins the work's current document; *stale* otherwise (reason `schema` or `document-version`); `_enqueue` (Task 5) creates a task for every non-current, non-open unit under the current protocol; `stale_documents(project) -> list[str]` (works whose live rows pin a conversion that is not the work's current default but whose document is the current one: warning input).

- [ ] **Step 1: Tests.**
```python
def test_removed_field_stales_only_rows_carrying_it():      # Review Focus 4
    amend(remove_field="latency")
    assert stale_extractions(project) == {row_with_latency}
def test_added_field_stales_all_rows(): ...
def test_comparability_key_and_sample_change_stale_nothing(): ...
def test_row_recorded_after_amendment_is_not_stale(): ...   # event-order comparison
def test_stale_unit_is_served_again_and_old_rows_stay_readable(): ...
def test_new_document_version_requeues_work_and_marks_rows_stale(): ...   # spec version rule
def test_new_conversion_of_same_document_only_warns():
    assert stale_documents(project) == [work] and stale_extractions(project) == set() and unit_state == "current"
def test_pin_follows_new_document_for_both_passes(): ...
def test_reverted_amendment_keeps_order_semantics(): ...   # A -> B -> A
def test_stale_rows_excluded_from_final_rows(): ...         # asserted again in Task 8
def test_unit_states_lists_every_included_work():             # plan E interface
    states = unit_states(project)           # 3 included works, one served by pass A, none by B; 1 excluded work
    assert {s.work_id for s in states} == set(INCLUDED_WORKS) and EXCLUDED_WORK not in {s.work_id for s in states}
    assert {s.state for s in states if s.work_id in UNSERVED} == {"queued"}
    assert unit_states(project_without_schema) == []
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(extraction): staleness by amendment and document version`.

### Task 8: Agreement, resolution, final rows and plan E interfaces

*Tier: critical (dual independence, agreement).*

**Files:** Create `services/extraction_agreement.py`; Test `tests/test_extraction_agreement.py`.

**Interfaces:**
- Consumes: `live_rows`, `stale_extractions`, `in_dual_sample`, pack, `normalise_for`.
- Produces: `class FieldDisagreement(StrictModel)`: `work_id`, `row_key`, `field: str | None`, `kind: Literal["value", "missing", "row"]`, `a: FieldView | None`, `b: FieldView | None` (`FieldView`: value, unit, canonical, anchor, cell, quote, extraction_id); `class GroupRate(StrictModel)`: `group`, `compared: int`, `agreed: int`, `rate: float | None`; `class ExtractionAgreement(StrictModel)`: `passes: list[PassConfig]` (sessions, models, seed, field order), `dual_works: int`, `rows_aligned: int`, `rows_unmatched: int`, `rates: list[GroupRate]`, `overall: float | None`, `disagreements: list[FieldDisagreement]` (unresolved only), `resolved: int`, `single_extraction: list[str]`; `class AgreementOverall(StrictModel)`: `overall: float | None`, `dual: int`, `single: int`; `agreement_overall(project) -> AgreementOverall` (read-only, **no actor, never raises**: `dual` = population works in the dual sample, `single` = the rest, both from the recorded seed and fraction and `0` without a schema or pass; `overall` = agreed over compared field values across all aligned live rows, computed by the same function `extraction_agreement.overall` uses, and `None` while any extraction task is open or claimed, when pass B is unopened under a dual plan, or when nothing is compared; it does not check session or model independence, which only `extraction_agreement` enforces); `extraction_agreement(project, actor) -> ExtractionAgreement` (read-only; refuses on field `passes` while any extraction task is open or claimed, when a session joined both passes, when the passes share a model, when pass B is unopened under a dual plan); `resolve_extraction(project, actor, work_id, row_key, field: str | None, choice: Literal["a","b","neither"], reason: str, channel: Channel) -> str` (human only; refuses unknown row/field, a pair that is not a disagreement, an MCP-relayed resolution from a pass session); `class FinalField(StrictModel)` (value, unit, canonical, anchor, cell, quote, reported_in effective, copy_marker, reproduced, cited_work, extraction_id) and `class FinalRow(StrictModel)`: `work_id`, `document_id`, `conversion_id`, `row_key`, `status: Literal["agreed","resolved","single"]`, `fields: dict[str, FinalField]`, `independent: bool` (the `value` field is effectively own); `final_rows(project) -> list[FinalRow]`; `GroupKey = tuple[tuple[str, str], ...]`; `class Grouped(StrictModel)`: `groups: dict[GroupKey, list[FinalRow]]`, `ungrouped: list[FinalRow]` (a comparability key missing), `unresolved: list[FieldDisagreement]`; `grouped_rows(project) -> Grouped` (values normalised with `normalise_for`; `input_resolution` normalised; keys in the schema's order; no ordering across groups); `independence_counts(rows) -> IndependenceCounts(independent: int, copied: int)`.
- Rules: stale and superseded rows never enter; a dual row is `agreed` when every compared field agrees (final field values taken from pass A), `resolved` after the human's choices (`a`/`b` take that pass's field, `neither` drops the field, a `neither` on the row drops it); an unresolved disagreement keeps the row out of `final_rows` and in `unresolved`; works outside the sample are `single` (pass A rows, listed in `single_extraction`).

- [ ] **Step 1: Tests.**
```python
def test_agreement_refused_while_tasks_open():            # decision 37 item 7
    with pytest.raises(FactoryValidationError) as e: extraction_agreement(project, human)
    assert e.value.issues[0].field == "passes"
def test_agreement_refused_when_passes_share_model_or_session(): ...
def test_agreement_overall_never_refuses():                   # plan E interface; methods (Task 10) uses it
    assert agreement_overall(project_no_schema) == AgreementOverall(overall=None, dual=0, single=0)
    assert agreement_overall(project_open_tasks).overall is None and agreement_overall(project_open_tasks).dual == N_DUAL
    done = agreement_overall(project_complete)       # needs no actor
    assert done.overall == extraction_agreement(project_complete, human).overall and done.single == N_SINGLE
def test_numbers_must_match_exactly_after_normalisation():
    a = row(value="82.40", unit="%"); b = row(value="82.4", unit="%")      # equal
    c = row(value="82.5", unit="%")
    assert disagreements(a, b) == [] and kinds(disagreements(a, c)) == ["value"]
def test_unit_difference_is_a_disagreement(): ...           # "%" vs "fraction"; 22.1 M vs 22100000 "" are equal
def test_text_field_compared_normalised_not_fuzzy(): ...    # "ImageNet-1K" == "imagenet-1k"; "DeiT-S" != "DeiT-Small"
def test_provenance_fields_do_not_disagree(): ...           # different quote/anchor, same values
def test_unmatched_row_is_a_row_disagreement(): ...
def test_per_group_rates_and_overall(): ...                 # computed, not typed
def test_disagreements_never_auto_resolved():               # acceptance 9
    ag = extraction_agreement(project, human); assert len(ag.disagreements) == 2 and ag.resolved == 0
    assert final_rows(project) == [only_the_agreed_row]
def test_human_choice_resolves_and_final_value_is_the_chosen_verified_one():
    resolve_extraction(project, human, w, key, "value", "b", "pass B read the table correctly", Channel.CLI)
    assert final_by_key(key).fields["value"].canonical == B_CANONICAL and final_by_key(key).status == "resolved"
def test_neither_drops_field_and_lists_it(): ...
def test_agent_cannot_resolve_and_pass_session_cannot_relay(): ...
def test_sample_recorded_with_seed_and_single_extraction_listed(): ...   # acceptance 9
def test_stale_and_superseded_rows_excluded(): ...
def test_grouped_rows_use_comparability_keys_only():
    g = grouped_rows(project)
    assert list(g.groups) == [(("task", "image classification"), ("dataset", "imagenet-1k"), ("split", "val"), ("metric", "top-1 accuracy"), ("input_resolution", "224x224"), ("pretraining_data", "none"))]
    assert row_missing_split in g.ungrouped
def test_resolution_variants_group_together(): ...        # "224" and "224x224"
def test_copied_result_not_counted_independent():            # acceptance 8
    assert independence_counts(final_rows(project)) == IndependenceCounts(independent=1, copied=2)   # one cited, one marker-flagged
def test_throughput_never_part_of_group_key(): ...         # plan E input for 12a
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(extraction): field-level agreement, resolution, final and grouped rows`.

### Task 9: Audit of agreed values

*Tier: critical (audit size and rates).*

**Files:** Create `services/extraction_audit.py`; Test `tests/test_extraction_audit.py`.

**Interfaces:**
- Consumes: Task 8 agreement; `audit_size`, `population_digest`; `schema.audit_fraction/minimum`.
- Produces: `EXTRACTION_ERROR_CEILING = 0.05`; `agreed_values(project) -> list[AuditItemRef]` (agreed or resolved-to-`a`/`b` field values of aligned dual rows, sorted); `extraction_audit_sample(project, actor, *, random_seed: int | None = None) -> ExtractionAuditSampled` (human only; refused until `extraction_agreement` succeeds and no disagreement is unresolved; refused while an audit of the current agreed set is open; seed in `0..2**32-1`); `AuditEvidence(StrictModel)`: `item: AuditItemRef`, `value`, `unit`, `quote`, `anchor`, `cell`, `element_text: str` (the cited cell or element text from the pinned conversion, for the human), `extraction_id`; `audit_evidence(project, audit_id) -> list[AuditEvidence]`; `extraction_audit_record(project, actor, audit_id, work_id, row_key, field, correct: bool, note: str, channel: Channel) -> str` (human; item must be in the sample; an MCP-relayed label refused from a pass session); `class ExtractionAuditReport(StrictModel)`: `audit_id`, `sample_size`, `labelled`, `incorrect`, `error_rate: float | None`, `ceiling`, `above_ceiling`, `enforced`, `by_group: dict[str, float | None]`; `extraction_audit_report(project) -> ExtractionAuditReport | None`; `extraction_audit_outstanding(project) -> bool`.

- [ ] **Step 1: Tests.**
```python
@pytest.mark.parametrize("n,fraction,minimum,expected", [(30, 0.02, 50, 30), (300, 0.02, 50, 50), (4000, 0.02, 50, 80), (2500, 0.02, 50, 50)])
def test_sample_size_is_decision_37_rule(n, fraction, minimum, expected): ...   # built from n agreed values
def test_sample_recorded_with_seed_and_reproducible(): ...    # same seed -> same items
def test_refused_before_agreement_or_with_unresolved_disagreements(): ...
def test_agent_cannot_sample_or_label(): ...
def test_second_sample_refused_until_agreed_set_changes(): ...
def test_error_rate_computed_from_labels():          # acceptance 10
    label 3 of 40 incorrect -> report.error_rate == 0.075 and report.above_ceiling is True
def test_ceiling_advisory_in_pilot_error_in_systematic(): ...   # check finding severity (asserted again in Task 10)
def test_evidence_shows_cited_element_text_from_pinned_conversion(): ...
def test_report_none_before_any_sample(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(extraction): audit of agreed values`.

### Task 10: `check` findings, trace, methods

*Tier: standard (Sonnet implement, Haiku review); trace and check are read-only.*

**Files:** Modify `services/check.py`, `services/trace.py`, `services/methods.py`; Test `tests/test_extraction_check_trace.py`.

**Interfaces:**
- Produces `check` codes and severities (exploratory/pilot/systematic, as the table in `check.py`): `extraction-pending` (warning, warning, warning; included works without a current unit), `extraction-single` (None, warning, error; works outside the dual sample: promotion gap), `extraction-unresolved` (None, warning, error; unresolved disagreements), `extraction-audit-missing` (None, warning, error), `extraction-error-high` (None, warning, error; message states no rate for agents, as `audit-error-high`), `extraction-schema-stale` (warning x3; stale rows exist), `extraction-library-missing` (warning x3; a pinned conversion's blobs absent), `extraction-document-stale` (warning x3; ruling 5, `stale_documents`), `extraction-copy-flag` (warning x3 when markers contradict an `own` declaration, listing the work ids). Agent view of `extraction-error-high` carries no rate.
- Trace: node kinds `extraction` (`ext_…`, plus `row_key` lookups not needed) and `claim` (`clm_…`) added to `KINDS` after `decision`, patterns in `_PATTERNS`; edges up from an extraction: its work, its protocol, the anchors it cites (`<conversion_id>/<anchor-or-cell>` nodes, which already lead to conversion, document, attempt and work), the task's full-text decisions of the work (as `_edges_decision` links to decisions), `supersedes`; edges down from a cell or anchor node: the extractions and claims citing it. `trace` stays refused to extraction pass sessions (Task 11 wiring).
- `methods_report` adds `extraction_pack`, `extraction_fields`, `extraction_passes`, `extraction_dual_sample`, `extraction_sessions`, `extraction_models`, `extraction_agreement` (overall, from `agreement_overall`, so it is `None` rather than a refusal while tasks are open), `extraction_audit_n`, `extraction_error_rate` (all `None`/0 without a schema), computed.

- [ ] **Step 1: Tests.** One test per code (positive and absent case), `test_agent_view_hides_error_rate`, `test_trace_extraction_back_reaches_question` (extraction -> anchor -> conversion -> document -> attempt -> work -> full-text decision -> protocol -> question), `test_trace_cell_forward_lists_extractions`, `test_trace_superseded_row_links_prior`, `test_methods_without_schema_unchanged` (existing `test_methods.py` passes unedited), `test_methods_states_extraction_plan_and_sessions`, `test_methods_agreement_none_while_tasks_open` (no refusal).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, existing check/trace/methods suites unedited, mypy, ruff. **Step 5:** Commit `feat(extraction): check findings, trace nodes, methods statement`.

### Task 11: MCP tools, CLI commands and the `rf-extract` skill

*Tier: Haiku for implementation and review (surfaces, docs); service behaviour is already covered.*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`, `tests/test_plugin.py` (`SKILLS`); Create `plugin/skills/rf-extract/SKILL.md`; Test `tests/test_mcp_extraction.py`, `tests/test_cli_extraction.py`, `tests/test_skills.py` (extend).

**Interfaces:**
- MCP (parse, call a service, `_reply`; replies through `_withheld` as `document_read`):
  - `extract_next(project, pass_label, role, model, skill)` -> `ExtractNext`.
  - `extract_record(project, task_id, rows: list[dict], role, model, skill, claims: list[dict] = [], finish: bool = False, reason: str | None = None, supersedes: dict[str, str] = {})` -> `ExtractResult`; an item that fails shape validation is an `ItemError` by index (the screening `_parse_items` pattern); other items are written.
  - `extract_agreement(project)` -> `ExtractionAgreement`; `extract_audit_sample(project)` -> audit id, items with `AuditEvidence`, counts; `extract_audit_record(project, audit_id, work_id, row_key, field, correct, note="")` -> event id (human actor, channel `mcp`). The three are refused to a session that joined an extraction or screening pass; `report_*`, `check` and `trace` likewise (`_refuse_pass_session` also tests `is_extraction_session`); `document_read` keeps its own gate.
- CLI group `factory extract`: `status` (per-pass unit states and counts), `agreement`, `resolve WORK ROW_KEY [--field F] --choice a|b|neither --reason TEXT`, `audit-sample`, `audit-label AUDIT WORK ROW_KEY FIELD --correct/--incorrect [--note]`, `audit-report`. Human acts use the human actor and channel `cli`; `render` prints disagreements with both values, quote and anchor, and the audit evidence element text.
- Skill `rf-extract` (prose, concise, no marketing): independence section as `rf-screen` (one pass per fresh session, pass B uses a different model, never read the other pass's rows, human labels or audit); procedure: `extract_next`, read the pinned conversion only through `document_read` (page, then anchors/cells), record rows with printed numbers and `unit`, quote verbatim from the anchor, give `cell` for table values, declare `reported_in = cited` and `cited_work` for values attributed to other papers, never compute, convert or average, record each row separately, correct a rejected row by resubmitting a fixed one (never edit a quote to pass), claims (pass A only), `finish` with a `reason` for papers with no results, stop when `batch` is null; human steps (agreement, resolution, audit) are not the skill's.

- [ ] **Step 1: Tests.** MCP: tool list pinned with the five new names and no others; `extract_next` -> batch with pinned conversion and no other-pass data; `extract_record` partial success returns `rejected` by index and writes valid rows; an unknown pass label returns a structured error and writes nothing; `extract_agreement` refused to a pass-B session and to a screening-pass session; `extract_audit_record` writes a human event with channel `mcp`; `check`/`trace`/`report_prisma` refused to an extraction session. CLI: `resolve` records a human event, `--choice x` is refused, `audit-label` for a work outside the sample is refused, `agreement` prints disagreements and the per-group rates, `status` prints counts. Skills: `rf-extract` exists with frontmatter name and description and names `extract_next`, `document_read`, `finish`, "verbatim", "never compute"; it forbids reading the other pass; `SKILLS` in `test_plugin.py` includes `rf-extract`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement (skill text by a Sonnet implementer). **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(extraction): MCP tools, CLI commands, rf-extract skill`.

### Task 12: Acceptance and docs

*Tier: Haiku.*

**Files:** Test `tests/test_acceptance_extraction.py`; modify `docs/specs/slice-2.md` ("Implemented in plan 2D" paragraph), `docs/decisions.md` (decision 51, *Proposed*), `CLAUDE.md` status line.

- [ ] **Step 1: Tests (acceptance 5-11, 14 in part).** `test_extraction_refused_without_schema_then_allowed` (5); `test_schema_amendment_stales_affected_extractions` (5); `test_number_check_rejects_and_batch_survives` (6); `test_cell_anchor_resolves_to_one_cell_and_text_checked` (7); `test_copied_results_flagged_and_not_independent` (8); `test_dual_sample_seed_recorded_and_disagreements_listed` (9); `test_audit_size_rule_and_error_rate` (10); `test_corrections_supersede_both_in_log` (11); `test_trace_from_row_reaches_question` (14, extraction -> question); `test_rebuild_matches` (state hash after `index.rebuild()` equals the incremental one; `final_rows` and `grouped_rows` equal before and after); `test_earlier_acceptance_suites_unchanged` (slice 1, plans A-C acceptance modules pass without edits).
- [ ] **Step 2:** Run; fix until PASS. **Step 3:** Docs: the slice-2 paragraph states what plan D implemented, the MCP tools and CLI commands; decision 51 (*Proposed*): "Extraction rulings of plan 2D: per-field provenance, flops and macs split, evidence required for checked fields, resolution normaliser, union rule for copied-result detection, hash-threshold dual sample with reversed pass-B field order, agreement by value-evidence location, human chooses between verified values and never types one, audit unit and `EXTRACTION_ERROR_CEILING = 0.05`, claims vocabularies and pass-A-only claims. Needs the researcher's confirmation." **Step 4:** Full suite, mypy, ruff, coverage >= 90% for `services/` and `model/`. **Step 5:** Commit `test(extraction): plan 2D acceptance; docs`.

## Self-review notes

- **Spec coverage.** Schema in protocol and pack (ruling 1-3, Tasks 1-2); declare-before-extract and undeclared-field rejection, acceptance 5 (Tasks 2, 5, 6, 7, 12); quote, number, cell checks, acceptance 6-7 (Task 4); copied-result flag, acceptance 8 (Tasks 4, 8); dual extraction, seed, agreement, no auto-resolution, acceptance 9 (Tasks 5, 8); audit and ceiling, acceptance 10 (Tasks 9, 10); supersession, acceptance 11 (Task 6); trace to extraction and cell, acceptance 14 in part (Task 10; the report-side cell trace is plan E); R-40 claims (Task 6), R-43 one pinned version (Task 5, 7), R-44 (Task 4), R-45 keys declared in the protocol and applied by `grouped_rows` (Tasks 2, 8), R-46 (Tasks 8, 9). Acceptance 12 and 12a and the evidence report are plan E; D supplies `grouped_rows`, `final_rows`, `independence_counts` and keeps throughput, latency and memory out of the group key.
- **Types.** `StoredField`, `ExtractedRowInput`, `row_key`, `ExtractBatchContent`, `live_rows`, `stale_extractions`, `unit_states`, `final_rows`, `AuditItemRef`, `EXTRACTION_ERROR_CEILING` are used with the same names in Tasks 3-12.
- **Rulings needing the researcher** are the ones marked **[confirm]**: 3, 8, 9, 10, 11, 14; the others follow the spec or earlier plans.
- **Risk.** Tasks 2, 3 touch the protocol hash and the projection; their regression gate is the unchanged earlier suites and the pinned `P@` literal. Tier: Tasks 1-9 critical (Sonnet task reviews; Tasks 4, 5, 8 get a second look on independence and verification), Task 10 standard, Tasks 11-12 Haiku. The converter decision (49) affects none of these tasks.

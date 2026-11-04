# Miner Specification, Field Kinds and the Generic Mine Path Implementation Plan (slice M, sub-plan M-C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** If Task 6 adds a `miners` table it bumps `PROJECTION_VERSION` by one from the value it finds (the spec named only M-B, M-D and M-E; the rule of the build-order plan governs).

> **Dependencies.** Plan M-A merged; plan M-B merged (Task 7 calls `require_gate` for `mine.resolve`); plan G1 merged (`current_extraction`, link states); plan G2-A merged (consumes `Scope`, `scope_of_pack`, `scope_of_schema_ref`, `next_unit`, `record_unit`, `ExtraCheck`, `ExtraVerdict`, `UnitPin`, `CloseCheck`, `pack_row_key`, `FieldDef.allowed`, `Conditional`, `Pack.row_key_fields/row_anchor_fields/compared_fields`, and the `scope=` keyword on plan-D reads). Plan M-D consumes this plan's registration and `mine_*` interfaces.

**Goal:** Turn the plan-D/G2-A extraction engine into a miner engine: a `MinerSpec` with verifiable field kinds compiles to a `Pack` plus kind checks; built-in packs round-trip through it; a miner is registered by event and listed in the protocol before tasks; `mine_next`/`mine_record` serve any listed miner on the existing `extraction.*` family, discriminated by the miner name.

**Architecture:** Pure `factory/mining/` (spec, validation, compilation, digest, selectors over a manifest) and `services/mining.py` (registration, population, `mine_next`, `mine_record`) over G2-A's scope-parameterised services. A third scope kind, `MinerScope(name)`, sits beside `Scope.EVIDENCE` and `Scope.CONTRIBUTION`; its `.value` is the miner name, which is what the projection's existing `scope` column stores.

**Tech Stack:** as M-A; no new dependencies.

**Spec:** `docs/specs/slice-M-modules.md` rulings 2, 11–15; *Miner specification*; *Generic mine path*; events `miner.registered`; acceptance 9–11, 13.

## Rulings made in this plan

1. **`MinerScope` is a value type, not an enum member [confirm].** `@dataclass(frozen=True) MinerScope(name: str)` with `value` property; `ScopeKey = Scope | MinerScope`; `scope_of_pack(pack)` returns `MinerScope(pack)` for names matching `MINER_NAME_RE = r"^m-[a-z0-9]+(?:-[a-z0-9]+)*$"`, else as G2-A. Every G2-A function that takes `scope: Scope` is widened to `ScopeKey`; defaults stay `Scope.EVIDENCE`.
2. **Digest over the hashed spec only [confirm].** `miner_digest` = first 16 hex of SHA-256 over `canonical_json(strip_prose(spec_json))`, where prose is `rationale` and every field `description`; the procedure skill is hashed by name only (its text hash is recorded per event as `actor.skill`, R-04).
3. **Selector heading match on normalised text [confirm].** A heading pattern matches the `normalise_text` of the enclosing `SECTION` anchor's text (`extraction/numbers.py::normalise_text`), case-insensitive, with `re.search` (a pattern need not cover the whole heading); patterns are compiled at validation and a pattern that fails to compile is refused.
4. **Kind checks run after plan-D verification [confirm].** A row that fails plan-D verification reports only those issues; kind checks run on rows that passed, through G2-A's `ExtraCheck`; issues use field `fields.<name>` and reasons `no-citation-marker`, `anchor-not-found`, `anchor-kind`, `entry-not-found`, `work-not-found`, `too-few-quotes`, `enum-needs-quote`.
5. **Registration is project-local in M-C [confirm].** `miner.registered` lives in the project's log; M-E adds cross-project lookup by digest. A second registration of an existing `(name, version)` with a different digest is refused; with the same digest it is a no-op returning the existing `miner_id`.

## Global Constraints

- All M-A and M-B constraints hold; the platform never calls a model.
- New event type: `miner.registered` (schema 1). No change to any `extraction.*` payload: registered miners write `pack = <name>` and `schema_ref = <name>@<version>`, as G2-A defines those fields. `PROJECTION_VERSION` bumps once (Task 5).
- Plan-E reads (`final_rows` default scope, `grouped_rows`, `independence_counts`, `live_claims`, the evidence report) never see a registered miner's rows.
- Selectors and task contents never carry document text; tasks carry anchor ids only.

## Review Focus

1. Built-in round trip: `compile_miner(miner_of_pack(p, …)) == p` for both packs (Task 2).
2. Each field kind's verifier is the existing code, not a reimplementation (Task 3: tests call through to `quote_in_element`, `numbers_in`, `citation_markers`, `Manifest`, `current_extraction`, `match_title` with spies).
3. Separation from the evidence table (Task 7, `test_registered_miner_rows_invisible_to_evidence`).
4. A legacy log (no `m-` packs) replays to identical extraction tables (Task 5).

## File Structure

- Create `src/factory/mining/__init__.py`, `mining/spec.py`, `mining/validate.py`, `mining/compile.py`, `mining/select.py`; `src/factory/model/miners.py`; `src/factory/index/miners.py`; `src/factory/services/mining.py`; `src/factory/services/modules/mining.py`.
- Modify `model/extraction.py` (`MinerScope`, `ScopeKey`, `scope_of_pack`), `services/extraction.py`, `services/extraction_agreement.py`, `services/extraction_audit.py` (type widening only), `model/protocol.py` (`miners` section), `services/protocol_rules.py`, `events/catalog.py`, `index/default.py`, `index/extraction.py` (no column change; scope value), `services/modules/__init__.py`, `mcp/server.py`, `cli/main.py`.
- Tests: `tests/test_miner_spec.py`, `tests/test_miner_compile.py`, `tests/test_miner_kinds.py`, `tests/test_miner_select.py`, `tests/test_miner_registration.py`, `tests/test_miners_protocol.py`, `tests/test_mine_path.py`; helper `tests/miner_helpers.py` (a G1-ready project from `tests/contribution_helpers.py`, a `VISION_RESULT_V1` spec builder, `mine_rows(...)` builders).

---

### Task 1: Miner specification types and validation

*Tier: critical (the shape every registered miner takes).*

**Files:** Create `mining/spec.py`, `mining/validate.py`; Test `tests/test_miner_spec.py`.

**Interfaces:**
- Produces (`mining/spec.py`): the spec's dataclasses `NumberKind`, `IntegerKind`, `EnumKind`, `QuoteKind`, `CitationKind`, `AnchorKindRef`, `WorkRefKind`, `Unverified`, `FieldKindSpec`, `MinerField(name, group, kind, required=False, description="")`, `Population(StrEnum)` (`INCLUDED_FINAL = "included-final"`, `INCLUDED_TA = "included-ta"`, `INCLUDED_FT = "included-ft"`, `WITH_REFERENCES = "with-references"`, `CORPUS = "corpus"`), `Selector`, `EvidenceRule`, `MinerRegime(passes, calibration_size=10, recall_min=0.8, field_agreement_min=0.9)`, `MinerSpec`; `MINER_NAME_RE`; `spec_to_json(spec) -> dict[str, JsonValue]`, `spec_from_json(value) -> MinerSpec` (raises `FactoryValidationError` with dotted fields).
- Produces (`mining/validate.py`): `validate_miner(spec: MinerSpec, *, built_in: bool = False) -> list[ValidationIssue]`: name pattern (registered only), unique field names, `row_key_fields`/`row_anchor_fields`/conditionals name fields, `Unverified` refused unless `built_in`, `EnumKind.values` non-empty and unique, `CitationKind.patterns` compile, heading patterns compile, `max_units ≥ 1`, regime values in (0, 1], `calibration_size ≥ 1`, at least one `QuoteKind`/`CitationKind`/`WorkRefKind(title)` field when `evidence.min_quotes_per_record ≥ 1`.

- [ ] **Step 1: Tests.** `test_json_round_trip`; `test_free_text_refused_for_registered`; `test_name_outside_namespace_refused` (`vision-result`, `ml-benchmark`); `test_bad_heading_pattern_refused`; `test_enum_needs_values`; `test_quote_field_required_by_evidence_rule`; `test_conditional_names_unknown_field`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** mypy; ruff. **Step 5:** Commit `feat(mining): miner specification and validation`.

### Task 2: Compilation, digest and built-in miners

*Tier: critical (round trip with plan-D packs).*

**Files:** Create `mining/compile.py`; Test `tests/test_miner_compile.py`.

**Interfaces:**
- Consumes: `Pack`, `FieldDef`, `FieldKind`, `Check`, `UnitFamily`, `canonical_json`, `strip_prose` (`model/protocol.py`).
- Produces: `compile_miner(spec: MinerSpec) -> Pack` (spec table of field kinds; `required` = fields with `required=True`; `default_comparability_keys=()`, `citation_patterns` = union of `CitationKind.patterns`, `compared_fields` = all field names except `QuoteKind` fields used only as evidence (those marked `group="evidence"`)); `miner_of_pack(pack: Pack, selector: Selector, regime: MinerRegime) -> MinerSpec` (inverse: `(NUMBER, NUMBER)` → `NumberKind`, `(INTEGER, NUMBER)` → `IntegerKind`, `(TEXT, TEXT_IN_QUOTE)` → `QuoteKind`, `(TEXT, NONE, allowed)` → `EnumKind`, `(INTEGER, NONE)` named in a `WORK_REF_FIELDS` table (`contribution.cited_entry`) → `WorkRefKind("entry")`, any other `NONE` → `Unverified`); `miner_digest(spec) -> str` (ruling 2); `BUILT_IN_MINERS: Mapping[str, MinerSpec]` keyed `ml-benchmark@1`, `contribution@1`.

- [ ] **Step 1: Tests.** `test_built_in_round_trip` (both packs, field order, units, allowed, conditionals, row-key fields, compared fields; `ReportSpec` carried by reference since it is outside equality); `test_digest_ignores_prose_and_order_of_json_keys`; `test_digest_changes_with_any_field_kind`; `test_unverified_fields_listed_for_ml_benchmark` (the free text fields named, for `factory modules`).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Pack suites unedited; mypy; ruff. **Step 5:** Commit `feat(mining): compile miners to packs; built-in miners; digest`.

### Task 3: Kind checks over the existing verifiers

*Tier: critical (verification).*

**Files:** Modify `mining/compile.py` (`kind_checks`); Test `tests/test_miner_kinds.py`.

**Interfaces:**
- Consumes: G2-A `ExtraCheck`, `ExtraVerdict`, `UnitPin`; `citation_markers` (`extraction/citations.py`), `Manifest.get` and `AnchorKind` (`document/anchors.py`), `services/references.py::current_extraction` and the G1 entry/link reads, `references/match.py::match_title` and `Candidate`.
- Produces: `kind_checks(spec: MinerSpec) -> ExtraCheck` (ruling 4) and `close_checks(spec) -> CloseCheck` (`EvidenceRule.min_quotes_per_record` per row); for `WorkRefKind("entry")` an accepted row stores `cited: CitedEntry` as G2-A does, and the link state is reported as `stated` (resolved or confirmed link) or `inferred`; for `WorkRefKind("title")` the quote is matched with `match_title` against corpus works (`Candidate` list from the works table, bounded by year ± 1 and surname key, never the full corpus in memory) and `title-fuzzy` is accepted as `inferred`.

- [ ] **Step 1: Tests.** One accept and one reject per kind (spec acceptance 10), each asserting the reason string and that the existing verifier was called (spy); `test_failed_plan_d_row_reports_only_plan_d_issues`; `test_title_ref_candidate_query_is_bounded` (SQL spy: a `WHERE year BETWEEN` clause, no unbounded `SELECT` of works).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** mypy; ruff. **Step 5:** Commit `feat(mining): field-kind checks on the existing verifiers`.

### Task 4: Selector evaluation

*Tier: standard (implementer sonnet, review sonnet).*

**Files:** Create `mining/select.py`; Modify `services/mining.py` (population); Test `tests/test_miner_select.py`.

**Interfaces:**
- Consumes: `Manifest`, `Anchor`, `AnchorKind`; `agreement.final_outcomes(project, stage=…)`, G1 `included_works`, `current_extraction`, `extraction.unit_pin`/default conversion lookup.
- Produces (pure, `mining/select.py`): `selected_anchors(manifest: Manifest, selector: Selector) -> tuple[str, ...]` (anchors of the listed kinds whose enclosing section heading matches a pattern; all anchors of the kinds when no pattern; all when both empty). Produces (`services/mining.py`): `population(project, selector) -> Iterator[tuple[str, str]]` yielding `(work_id, conversion_id)` in work-id order from SQL, truncated at `max_units`.

- [ ] **Step 1: Tests.** `test_heading_pattern_selects_results_tables` (hand-written Markdown fixture with "Experiments" and "Related work"); `test_anchor_ids_differ_across_converter_versions_but_selection_holds` (two conversions of one document whose `b<n>`/section ids differ; same heading-selected element texts); `test_population_names` (each `Population` value on a fixture project); `test_population_streams` (generator; `max_units` respected).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** mypy; ruff. **Step 5:** Commit `feat(mining): selectors over populations and manifests`.

### Task 5: `MinerScope` through the extraction engine

*Tier: critical (events, index; replay).*

**Files:** Modify `model/extraction.py`, `index/extraction.py`, `index/default.py`, `services/extraction.py`, `services/extraction_agreement.py`, `services/extraction_audit.py`, `services/stages.py`/`services/modules/__init__.py` (task kinds `mine_a`, `mine_b`); Test `tests/test_mine_path.py` (scope part).

**Interfaces:**
- Produces: `MinerScope`, `ScopeKey`, `MINER_NAME_RE`, `scope_of_pack` (ruling 1); task kinds `mine_a`, `mine_b` registered for module `mining`, scope `None` (the miner is in the task content: `MineBatchContent(miner: str, version: int, digest: str, anchors: tuple[str, ...], calibration_id: str | None = None)` extending G2-A's batch content); `PROJECTION_VERSION` bump; G2-A signatures widened from `Scope` to `ScopeKey`.

- [ ] **Step 1: Tests.** `test_legacy_log_replays_identically` (fixture logs of plan D and G2-A: every extraction table row-equal); `test_m_pack_projects_to_miner_scope`; `test_scope_key_value_is_name`; `test_session_cannot_cross_miner_scopes` (G2-A ruling 2 extended).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Plan-D, G2-A and plan-E suites unedited; mypy; ruff. **Step 5:** Commit `feat(extraction): miner scopes on the plan-D engine`.

### Task 6: `miner.registered` and the protocol `miners` section

*Tier: critical (pre-registration, protocol hash).*

**Files:** Create `model/miners.py`, `index/miners.py`; Modify `events/catalog.py`, `index/default.py`, `model/protocol.py`, `services/protocol_rules.py`, `services/mining.py`; Test `tests/test_miner_registration.py`, `tests/test_miners_protocol.py`.

**Interfaces:**
- Produces (`model/miners.py`): `MinerRegistered(miner_id: str (mnr_<ULID>), name, version: int ≥ 1, digest, spec_blob, proposer_kind: ActorKind, imported_from: ImportedFrom | None = None)`; `MinerUse(StrictModel)`: `name`, `version`, `dual_extract_sample: float | None`, `audit_fraction: float = 0.02`, `audit_minimum: int = 50`, `evidence: bool = False`, `imports: Literal["allow", "deny", "audit"] = "deny"`.
- Produces (`model/protocol.py`): `ProtocolSpec.miners: tuple[MinerUse, ...] | None = None` (omitted while None; amendable; sorted by `(name, version)` in the hash); `ProtocolAmended.miner_stale: tuple[MinerStale, ...] = ()` computed per miner by plan D's `extraction_stale` on the compiled packs.
- Produces (`services/mining.py`): `register_miner(project, actor, spec_json: JsonValue) -> MinerRegistered` (validates, stores spec blob, ruling 5); `registered_miner(project, name, version) -> MinerSpec | None`; `require_listed(project, name, version) -> tuple[ProtocolVersion, MinerUse, MinerSpec]` (field `miners`).
- Protocol rules: a `MinerUse` naming an unregistered miner is an error (`miners.<i>.name`); `evidence: true` is an error until M-D (`miners.<i>.evidence`, "calibrate the miner first"); dual-sample and audit rules as plan-D ruling 9 by mode.

- [ ] **Step 1: Tests.** `test_register_validates_and_records`; `test_same_digest_is_idempotent`; `test_different_digest_same_version_refused`; `test_p_id_unchanged_without_miners`; `test_unregistered_miner_listed_is_error`; `test_evidence_true_refused`; `test_amending_one_miner_stales_only_its_rows`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Protocol suites unedited; mypy; ruff. **Step 5:** Commit `feat(mining): miner registration and the protocol miners section`.

### Task 7: `mine_next`, `mine_record`, `mine_status`; module declaration

*Tier: critical (agent surface; separation).*

**Files:** Modify `services/mining.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`; Create `services/modules/mining.py`; Test `tests/test_mine_path.py`.

**Interfaces:**
- Consumes: G2-A `next_unit`, `record_unit`; Tasks 2–6; M-B `require_gate`.
- Produces: `mine_next(project, actor, name: str, version: int, label: PassLabel) -> ExtractNext` (refused on `miners` until listed; population from the selector; content `MineBatchContent`); `mine_record(project, actor, task_id, rows, *, finish=False, reason=None, supersedes=None) -> ExtractResult` (compiled pack, `kind_checks`, `close_checks`); `MineStatus(name, version, digest, units, open, closed, rows, stale, agreement: float | None)`; `mine_status(project) -> list[MineStatus]`; MCP `mine_next`, `mine_record`, `mine_status`, `miner_register`, `miner_list`; CLI `factory miner register|list`, `factory mine status`. `resolve_extraction` on a miner scope calls `require_gate(project, actor, "mine.resolve")`. Module `mining` (kind `miner`): owns `miner.registered`, task kinds `mine_*`, section `miners`, gate `mine.resolve` (act event `extraction.resolved` with `pack` matching `MINER_NAME_RE`; the `extraction` module's `extraction.resolve` gate excludes those acts), checks `mine-pending` (warning ×3), `mine-single` (None, warning, error).

- [ ] **Step 1: Tests.** `test_mine_next_refused_until_listed`; `test_full_dual_run_of_vision_result_miner` (two sessions, two models; rows verified; agreement; resolution by a human); `test_registered_miner_rows_invisible_to_evidence` (spec acceptance 13: `final_rows(p)`, `grouped_rows(p)`, `independence_counts`, rendered evidence report byte-equal before and after); `test_task_content_has_anchor_ids_not_text`; `test_mcp_mine_tools_refuse_invalid_input_and_write_nothing`; `test_registry_ownership_still_exhaustive`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full suite; mypy; ruff; coverage. **Step 5:** Commit `feat(mining): generic mine_next and mine_record over registered miners`.

## Self-review notes

- **Spec coverage.** Ruling 2 (Tasks 5, 7), 11 (Tasks 1, 2), 12 (Task 3), 13 (Task 4), 14 (Tasks 2, 5), 15 (Task 6); acceptance 9 (Task 2), 10 (Task 3), 11 (Tasks 1, 6, 7), 13 (Task 7).
- **Types used later.** `MinerSpec`, `MinerRegime`, `Selector`, `compile_miner`, `miner_digest`, `kind_checks`, `MinerScope`, `ScopeKey`, `MinerRegistered`, `MinerUse`, `register_miner`, `registered_miner`, `require_listed`, `mine_next`, `mine_record`, `MineBatchContent.calibration_id`, `population`.
- **Tiers.** Tasks 1–3, 5–7 critical; Task 4 standard.

## Later (not v1)

None: every task of this plan is in v1.

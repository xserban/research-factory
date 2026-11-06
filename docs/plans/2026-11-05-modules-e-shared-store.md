# Shared Mining Store and Cross-Project Import Implementation Plan (slice M, sub-plan M-E)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** The whole plan is Later (slice-M v1 scope: single-project). The mining import id is `mim_<ULID>` (draft `imp_`, which slice 3d uses); the store root is `<root>/.mining/`, which slice 5 adopts.

> **Dependencies.** Plans M-A to M-D merged (consumes `MinerRegistered`, `MinerUse.imports`, `registered_miner`, `register_miner`, `miner_digest`, `compile_miner`, `kind_checks`, `MinerScope`, plan-D `verify_row_in`, `final_rows(..., scope=…)`, `independence_counts`, `audit_core.*`). Built-in miners (`ml-benchmark@1`, `contribution@1`) are importable as well: their digest is `miner_digest(BUILT_IN_MINERS[...])`.

**Goal:** Let a project reuse records that another project has mined, without copying them silently: a read-only, rebuildable store projected from every project's events; an import that is an event in the importing project, carries the records it imports, and re-verifies each against the importer's own conversion; separate accounting of imported records; and a `source-superseded` flag when the source later corrects a record.

**Architecture:** `services/shared_mining.py` owns a second SQLite projection (`<projects_root>/../.mining/shared.sqlite`, git-ignored) with its own schema, version and per-file sync offsets, folded from `miner.registered`, `extraction.*` and `mine.imported` events of every project under the projects root. It is never written except by its projector. The importing project's `mine.imported` event is self-contained (rows inside), so the importer's replay never reads the shared store or another project's log; only the read-time `source-superseded` flag consults the store.

**Tech Stack:** as M-A; SQLite via SQLAlchemy (decision 3); no new dependencies.

**Spec:** `docs/specs/slice-M-modules.md` rulings 14, 18–20; event `mine.imported`; check findings `mine-source-superseded`, `mine-import-unverified`; acceptance 14, 15; R-143. Backlog IDEA-36 rigour notes.

## Rulings made in this plan

1. **Location and scope [confirm].** The store lives at `<root>/.mining/shared.sqlite` where `<root>` is the parent of the configured projects directory (`Settings`); it folds every project directory that has an `events/` folder. A project may opt out of being a source with a file `projects/<slug>/.no-share` (checked at sync); the opt-out is reported by `factory shared status`.
2. **What the store holds [confirm].** Per record: source project, miner name, version, digest, conversion id, work id, row key, extraction ids, pass labels and models, final status (`agreed`, `resolved`, `single`, `superseded`, `stale`) and field digests (SHA-256 of the canonical stored field), never values, quotes or anchors' text. Values are read from the source project's log at import time through its own `Project` context, so the store stays text-free (I9) and small.
3. **Status computed at sync, not at import [confirm].** The shared projector computes final status per source project by calling that project's `final_rows(…, scope=…)` and `stale_extractions(…)` read-only after syncing the source's own index; it stores the result with the source's last event id. A source whose index cannot sync is skipped and reported.
4. **Import granularity is the unit [confirm].** An import takes whole units `(work_id, conversion_id)` for one miner version; partial units are refused, so closure rules (plan-D zero-row and G2-A close checks) hold for imported units.
5. **Imported units satisfy the dual-extraction obligation only when the source had two agreeing passes [confirm].** Otherwise they count as single-pass and `extraction-single`/`mine-single` reports them as in any single-pass unit; `imports = "audit"` adds every imported value to the audit population.

## Global Constraints

- All M-A to M-D constraints hold. New event type: `mine.imported` (schema 1). `PROJECTION_VERSION` bumps once (Task 3). The shared store has `SHARED_PROJECTION_VERSION` and its own rebuild-determinism test.
- No document text, quote or value enters the shared store; imported quotes enter only the importer's own `mine.imported` event, as on `extraction.recorded`.
- Scale: sync is incremental per event file (offsets as `Index.sync`); lookups use the composite index `(miner, version, digest, conversion_id)`; no service materialises all shared records (iterators, `LIMIT`-paged queries). Tested at 10^5 records over 20 projects (`slow`).

## Review Focus

1. Re-verification uses the importer's own library copy and the existing verifiers; a forged quote fails (Task 3, `test_import_reverifies_against_own_conversion`).
2. Importer replay is independent of the source (Task 3, `test_importer_rebuild_without_source_project`).
3. Independence accounting does not inflate dual counts (Task 4).
4. The store never contains document text (Task 1, `test_shared_store_has_no_text_columns`).

## File Structure

- Create `src/factory/services/shared_mining.py`, `src/factory/index/shared.py` (schema and handlers of the shared projection), `src/factory/model/imports.py`, `src/factory/index/imports.py`.
- Modify `config.py` (`shared_store_path`), `events/catalog.py`, `index/default.py`, `index/extraction.py` (rows gain `origin` `local|imported`, default `local`), `services/extraction.py` and `services/extraction_agreement.py` (origin-aware live rows and independence), `services/modules/mining.py` (owns `mine.imported`, checks), `services/methods.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`, `.gitignore` (`/.mining/`).
- Tests: `tests/test_shared_store.py`, `tests/test_shared_lookup.py`, `tests/test_mine_import.py`, `tests/test_import_accounting.py`, `tests/test_source_superseded.py`, `tests/test_shared_scale.py` (`slow`); helper `tests/shared_helpers.py` (two or more projects under one temporary root sharing conversions by hash).

---

## Self-review notes

- **Spec coverage.** Ruling 18 (Tasks 1, 2), 19 (Tasks 3, 4), 20 (Task 5; calibration non-transfer is M-D Task 6); acceptance 14 (Tasks 3, 5, 6), 15 (Task 6).
- **Open risk.** Ruling 3 calls each source project's services during shared sync; a source on a newer projection version than the running platform cannot be read. The skip-and-report path covers it; a versioned read contract may be needed in slice 5.
- **Tiers.** Tasks 1, 3, 4 critical; 2, 5, 6 standard.

## Later (not v1)

Moved here by the v1 cut of 2026-11-04 (decision 74); built after the v1 plans of the build order (`2026-11-05-build-order.md`), in the order listed. Task text is unchanged; references to "Task N" inside a moved task use the plan's original numbering.

### Later L1 (was Task 1): Shared projection and incremental sync

*Tier: critical (projection discipline across projects).*

**Files:** Create `index/shared.py`, `services/shared_mining.py`; Modify `config.py`, `.gitignore`, `cli/main.py`; Test `tests/test_shared_store.py`.

**Interfaces:**
- Produces: `SHARED_PROJECTION_VERSION = "1"`; tables `shared_projects(slug, last_event_id, status)`, `shared_sync_state(project, file, offset)`, `shared_miners(project, name, version, digest, miner_id)`, `shared_records(project, miner, version, digest, conversion_id, work_id, row_key, status, extraction_ids, pass_labels, models, field_digests, source_last_event)` with index `ix_shared_lookup(miner, version, digest, conversion_id)`; `class SharedStore` with `sync() -> SharedSyncResult(projects, applied, skipped: list[str])`, `rebuild()`, `state_hash() -> str`, `connect()`; `shared_store(settings) -> SharedStore`; CLI `factory shared rebuild|status`.

- [ ] **Step 1: Tests.** `test_sync_folds_two_projects`; `test_second_sync_applies_only_new_files`; `test_rebuild_determinism` (two rebuilds, same `state_hash`); `test_opt_out_project_skipped_and_reported`; `test_shared_store_has_no_text_columns` (schema scan: no column named `value`, `quote`, `text`, `anchor_text`); `test_unsyncable_source_is_skipped`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement (ruling 3: status via each source's services, read-only). **Step 4:** mypy; ruff. **Step 5:** Commit `feat(shared): cross-project mining projection with incremental sync`.

### Later L2 (was Task 2): Lookup

*Tier: standard (implementer sonnet, review sonnet).*

**Files:** Modify `services/shared_mining.py`; Test `tests/test_shared_lookup.py`.

**Interfaces:**
- Produces: `@dataclass(frozen=True) SharedUnit(project, miner, version, digest, work_id, conversion_id, status: Literal["agreed", "resolved", "single", "mixed"], rows: int, dual: bool)`; `available_units(store, importer: Project, miner: str, version: int, digest: str, *, source: str | None = None, page: int = 0, page_size: int = 200) -> list[SharedUnit]` (units whose conversion id the importer's library holds; excludes the importer itself and superseded or stale records); `mine import --list` CLI.

- [ ] **Step 1: Tests.** `test_lookup_filters_by_digest`; `test_lookup_requires_importer_conversion`; `test_lookup_excludes_superseded_and_stale`; `test_lookup_pages`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** mypy; ruff. **Step 5:** Commit `feat(shared): lookup of importable units`.

### Later L3 (was Task 3): `mine.imported` with re-verification

*Tier: critical (events, verification, replay independence).*

**Files:** Create `model/imports.py`, `index/imports.py`; Modify `events/catalog.py`, `index/default.py`, `index/extraction.py`, `services/shared_mining.py`, `services/modules/mining.py`, `mcp/server.py`, `cli/main.py`; Test `tests/test_mine_import.py`.

**Interfaces:**
- Consumes: `registered_miner`, `register_miner` (`imported_from`), `compile_miner`, `kind_checks`, `verify_row_in`, the importer's `library`.
- Produces: `MineImported(import_id: str (mim_<ULID>), source_project, miner, version, digest, units: tuple[ImportedUnit, ...])`, `ImportedUnit(work_id, conversion_id, source_status, source_passes: tuple[ImportedPass, ...], rows: tuple[ImportedRow, ...])`, `ImportedRow(source_extraction_ids: tuple[str, ...], row_key, fields: Mapping[str, StoredField])`; `mine_import(project, actor, source: str, miner: str, version: int, units: Sequence[tuple[str, str]] | None = None) -> BatchResult[str]` (preconditions of spec ruling 19 and plan ruling 4; per-unit partial success; each row re-verified against the importer's conversion; a unit with any failing row is refused with `mine-import-unverified` reasons; `MinerUse.imports == "deny"` refuses on field `miners`); projection writes imported rows into the extraction tables with `origin = "imported"` under the miner's scope; `PROJECTION_VERSION` bump.

- [ ] **Step 1: Tests.** `test_import_refused_without_same_digest`; `test_import_refused_without_conversion`; `test_import_reverifies_against_own_conversion` (a source row whose quote was altered in the source log fails re-verification in the importer); `test_import_denied_by_protocol`; `test_partial_success_per_unit`; `test_importer_rebuild_without_source_project` (delete the source project directory; importer rebuild gives the same state hash); `test_import_event_carries_provenance` (source project, extraction ids, pass identities).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Full suite; mypy; ruff. **Step 5:** Commit `feat(shared): import of mined units with re-verification`.

### Later L4 (was Task 4): Accounting of imported records

*Tier: critical (independence counts, R-05).*

**Files:** Modify `services/extraction.py`, `services/extraction_agreement.py`, `services/extraction_audit.py`, `services/methods.py`; Test `tests/test_import_accounting.py`.

**Interfaces:**
- Produces: `ExtractionRow.origin: Literal["local", "imported"] = "local"`; `FinalRow.origin`; an imported unit with `source_status` dual-agreed counts as `agreed` in `final_rows` and as `imported-dual` in `IndependenceCounts.imported_dual: int = 0`; otherwise `single` and `IndependenceCounts.imported_single: int = 0`; `imports = "audit"` adds imported values to `agreed_values`; methods report gains `imported_units`, `imported_rows`, `imported_sources: list[str]` (rendered only when non-zero, so existing outputs are byte-identical).

- [ ] **Step 1: Tests.** `test_single_pass_source_counts_single`; `test_dual_source_counts_imported_dual_not_local_dual`; `test_audit_mode_includes_imported_values`; `test_methods_states_imports`; `test_methods_unchanged_without_imports` (golden).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Plan-D/E suites unedited; mypy; ruff. **Step 5:** Commit `feat(shared): separate accounting of imported records`.

### Later L5 (was Task 5): `source-superseded` propagation

*Tier: standard (implementer sonnet, review opus).*

**Files:** Modify `services/shared_mining.py`, `services/modules/mining.py`; Test `tests/test_source_superseded.py`.

**Interfaces:**
- Produces: `source_superseded(project, store: SharedStore | None = None) -> list[str]` (imported extraction ids whose source record is now `superseded` or `stale`, read-only; a deleted source project is reported by `mine-source-unavailable` only); check `mine-source-superseded` (warning, warning, error) and `mine-source-unavailable` (warning ×3) when the store is absent or the source is missing; nothing in the importer changes until re-import or re-mining.

- [ ] **Step 1: Tests.** `test_source_correction_flags_importer_after_sync`; `test_no_store_gives_unavailable_warning_not_error`; `test_reimport_clears_flag`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** mypy; ruff. **Step 5:** Commit `feat(shared): flag imports whose source was corrected`.

### Later L6 (was Task 6): Scale and acceptance (slow)

*Tier: standard (implementer sonnet, review opus).*

**Files:** Create `tests/test_shared_scale.py` (marked `slow`); extend `tests/test_acceptance_miners.py` with an import scenario.

- [ ] **Step 1: Tests.** `test_sync_scales_incrementally` (20 synthetic projects, 10^5 `extraction.recorded` events generated without documents through a fixture writer; first sync within a stated bound on the developer machine recorded in the test docstring, second sync after one new file touches one file only; peak RSS below 500 MB via `resource.getrusage`); `test_lookup_uses_index` (`EXPLAIN QUERY PLAN` contains `ix_shared_lookup`); `test_acceptance_import_into_second_project` (M-D acceptance project as source; second project with the same conversions; registers the same miner digest; imports; re-verifies; counts; source corrects a row; `check` flags it).
- [ ] **Step 2:** Run `uv run pytest -m slow tests/test_shared_scale.py tests/test_acceptance_miners.py`; FAIL until Tasks 1–5. **Step 3:** Fix with unit tests. **Step 4:** Full suite incl. `slow`; mypy; ruff; coverage. **Step 5:** Commit `test(shared): scale and import acceptance`.

# Import C: Coverage Audit, Read Tools, Check, Trace and Acceptance — Implementation Plan (slice 3d)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Coverage bucket `found-supplementary` counts `citation-chase`, `seed-admission` and `hand-search` only; a work whose only non-import provenance is `supplied` is not found (spec reconciliation item 2); add `test_supplied_only_is_not_found` to Task 1. Regions-A is merged first in the build order, so Task 5's `import` region rule is added in Regions-A, not here.

> **Dependencies.** Import-A and Import-B merged. If Regions-A is merged first, Task 5 adds the `import` region rule there instead of here (spec, Proposed sub-plans).

**Goal:** Compute, for every resolved record of an import, whether the systematic search found it and why not, report search sensitivity and corpus coverage on the development and held-out parts, suggest missing query terms, expose read-only views to agents under the held-out rules, and extend `check`, `trace` and the methods text.

**Architecture:** `services/coverage.py` is a builder: it reads the import projection, provenance, queries, protocol limits and final outcomes, and returns a `CoverageReport`; it writes no event. Limit checks are a pure function in `factory/imports/limits.py`. MCP read tools filter by part per decision 43.

**Tech Stack:** as Import-A.

**Spec:** `docs/specs/slice-3d-regions-import.md` rulings 23, 25; acceptance 13, 16, 17; check findings (import part).

## Rulings made in this plan

1. **Record to work.** A record's work is its confirmed or resolved `work_id`, mapped through dedup to the canonical id (absorbed ids included). Records resolving to the same canonical work count once per import, in the lowest ordinal's part.
2. **"In a declared source".** Known when a resolution lookup against that source returned the record (lookup run of the source with the record's identifier or a title match). A declared source with no lookup for the record gives `source-unchecked`. arXiv-only works are `not-in-sources` for an OpenAlex-only protocol only if the OpenAlex lookup ran and returned nothing.
3. **Limits.** Year range, language and work type from `ProtocolSpec.limits` of the current `P@`; a record lacking the field is not outside the limit (unknown counts as within).
4. **Figures.** `sensitivity = found_database / (found_database + found_supplementary + query_miss)`, `coverage = (found_database + found_supplementary) / resolved`, both `None` with a zero denominator; reported with numerator and denominator, never alone (R-05).
5. **Labels.** `held-out` when a split was drawn; `post-search` when the split mode is `post-search`; `optimistic` when the researcher declined the split of a pre-search import (Import-A, split mode `declined`).

## Global Constraints

- As Import-A. The builder never writes; MCP views never reveal held-out ordinals, titles of held-out records or held-out figures before a screening pass is opened; CLI shows all.
- Messages carry ids and counts, never document text.

## Review Focus

1. Every resolved record falls in exactly one bucket; bucket counts sum to `resolved` (Task 1, `test_buckets_partition_resolved`).
2. `library-import` provenance never makes a record `found-*` (Task 1, `test_import_provenance_not_found`).
3. Over MCP, held-out figures are absent before a pass is opened and present after; held-out record titles never appear (Task 3, `test_mcp_withholds_held_out`).

## File Structure

- Create `imports/limits.py`, `services/coverage.py`; modify `services/check.py`, `services/trace.py`, `services/methods.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- Tests: `test_coverage_buckets.py`, `test_coverage_figures.py`, `test_import_mcp.py`, `test_import_check_trace.py`, `test_acceptance_import.py`.

---

### Task 1: Buckets

*Tier: critical (reported figures).*

**Files:** Create `imports/limits.py`, `services/coverage.py`; Test `tests/test_coverage_buckets.py`.

**Interfaces:**
- Consumes: `import_records`, `record_states`, `canonical_works`, `active_merges`, `final_outcomes`, `ProtocolSpec.limits`, `OTHER_METHODS`, the `provenance` and `queries` tables.
- Produces (`imports/limits.py`): `outside_limits(fields: ImportFields, limits: Sequence[Limit]) -> tuple[str, ...]` (names of violated limits; empty when within).
- Produces (`services/coverage.py`): `Bucket(StrEnum)`: `FOUND_DATABASE`, `FOUND_SUPPLEMENTARY`, `OUTSIDE_LIMITS`, `NOT_IN_SOURCES`, `SOURCE_UNCHECKED`, `QUERY_MISS`; `class RecordCoverage(StrictModel)`: `ordinal`, `work_id`, `part`, `bucket`, `limits_violated`, `sources_found: list[str]`, `outcome: Outcome | None`, `excluded_by: list[str]` (criterion ids); `record_coverage(project, import_id) -> list[RecordCoverage]` (unresolved and unconfirmed records omitted; counted in the report).

- [ ] **Step 1: Tests.** `test_buckets_partition_resolved` (Review Focus 1), `test_found_database_requires_search_purpose`, `test_found_supplementary_via_chase`, `test_import_provenance_not_found` (Review Focus 2), `test_outside_limits_year`, `test_unknown_field_within_limits`, `test_not_in_sources_needs_lookup`, `test_source_unchecked`, `test_query_miss`, `test_duplicate_records_count_once`, `test_absorbed_id_resolves`.
- [ ] **Step 2–5:** Run, FAIL; implement with SQL reads, streaming records; tests, mypy, ruff; commit `feat(coverage): bucket each imported record against the search`.

### Task 2: Report, figures and suggestions

*Tier: critical.*

**Files:** Modify `services/coverage.py`, `services/methods.py`; Test `tests/test_coverage_figures.py`.

**Interfaces:**
- Consumes: `suggest_terms(missed, all_seeds, query, top=8)` (`services/vocabulary.py`), planned queries of the protocol.
- Produces: `class PartCoverage(StrictModel)`: `part`, `counts: dict[Bucket, int]`, `unresolved: int`, `unconfirmed: int`, `resolved: int`, `sensitivity: Ratio | None`, `coverage: Ratio | None` (`Ratio(numerator, denominator, value)`), `outcomes: dict[str, int]`, `excluded: list[str]` (work ids); `class CoverageReport(StrictModel)`: `import_id`, `label: Literal["held-out", "post-search", "optimistic"]`, `parts: list[PartCoverage]`, `included_not_in_library: int`, `suggestions: list[TermSuggestion]` (computed from development `query-miss` records only), `protocol_id`, `as_of`; `coverage_report(project, import_id) -> CoverageReport`; methods text gains one sentence per import (counts and figures, held-out first).

- [ ] **Step 1: Tests.** `test_figures_hand_computed` (constructed project with 3 found-database, 1 found-supplementary, 2 query-miss: sensitivity 3/6, coverage 4/6), `test_zero_denominator_none`, `test_parts_reported_separately`, `test_suggestions_from_development_only`, `test_excluded_list_has_no_verdict_field`, `test_included_not_in_library_count`, `test_methods_sentence`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(coverage): coverage report, figures and term suggestions`.

### Task 3: MCP read tools and the CLI

*Tier: critical (held-out leakage).*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`; Test `tests/test_import_mcp.py`.

**Interfaces:**
- Produces MCP: `import_status()` (imports, counts by resolution state and bucket, development part only, paginated), `import_coverage(import_id)` (development part always; held-out part only when a screening pass has been opened, decision 43; never ordinals or titles of held-out records). Both refused to pass sessions (decisions 37, 43, 48).
- Produces CLI: `factory import coverage IMP [--json]`, full report.

- [ ] **Step 1: Tests.** `test_mcp_withholds_held_out` (Review Focus 3), `test_mcp_refused_to_pass_session`, `test_mcp_status_paginated`, `test_cli_coverage_shows_all_parts`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(mcp): import status and coverage views`.

### Task 4: Check and trace

*Tier: standard.*

**Files:** Modify `services/check.py`, `services/trace.py`; Test `tests/test_import_check_trace.py`.

**Interfaces:**
- Produces findings: `import-unresolved`, `import-unconfirmed`, `import-attachment-missing`, `import-identity-unchecked`, `import-undeclared` (promotion gap), `import-coverage-optimistic`; severities as spec (advisory except `import-undeclared` in pilot/systematic, error).
- Produces trace: kind `import` (`imp_…`) and record key (`imp_…:n`): import → file hash, parser, record hash, resolution (method, lookup run), decision, admission query and run, work, screening decisions; forward from a work lists the import records that produced or matched it.

- [ ] **Step 1: Tests.** One per finding in a constructed case; `test_trace_record_to_work_and_back`; `test_findings_carry_no_text`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(check): import findings and trace`.

### Task 5: Acceptance

*Tier: standard.*

**Files:** Create `tests/test_acceptance_import.py` (marked `slow` where it rebuilds large fixtures).

- [ ] **Step 1: Tests**, one per spec acceptance criterion 11–17 (import part): parse fixtures; no private text in git-tracked paths; resolver parity; split and MCP visibility; admission gate and PRISMA identity; attachments after promotion; buckets and figures; rebuild gives the same state hash; trace chain. Plus `test_import_scale` (`slow`): 50,000 BibTeX records parse, record, resolve against a fake source and bucket within the time recorded in the test, without loading all records into memory at once in the builder (records streamed by ordinal ranges).
- [ ] **Step 2:** Run; fix only defects found (each fix its own commit with a test). **Step 3:** `uv run pytest -m "not network"` including `slow`; mypy; ruff. **Step 4:** Commit `test(imports): slice-3d import acceptance`.

**Verification for the plan:** `cd platform && uv run pytest -m "not network" && uv run mypy --strict src && uv run ruff check`.

## Later (not v1)

None: every task of this plan is in v1.

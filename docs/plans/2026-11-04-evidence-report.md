# Evidence Report, Frontiers, Trace Extensions and Pack Completion Implementation Plan (slice 2, sub-plan E)

Status: merged (plan 2E, implemented per CLAUDE.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Dependencies.** Plans C (full-text screening, `plan-2c-fulltext-screening`) and D (extraction, `docs/plans/2026-11-04-extraction.md`) must be merged first: this plan consumes D's `final_rows`, `grouped_rows`, `independence_counts`, `live_claims`, `unit_states`, `stale_extractions`, the `ml-benchmark` pack and the extraction projection tables, and C's `res:full-text:<work>` and conversion/anchor trace nodes. It redefines none of them. **Decision 49 (converters for LaTeX and PDF) is still pending**: the report reads only extracted rows, and the trace walks anchor, conversion and document nodes by id, so no task depends on a converter.

**Goal:** Derive, from extracted and verified rows, an evidence/benchmark report that groups results only by identical comparability keys, never ranks across groups, shows per-group tables with row provenance, Pareto frontiers on hardware-independent cost axes, independent versus copied counts, within-paper speed ratios and an explicit statement of what the corpus does not support; extend `trace` to evidence cells and claims; extend `check` and the methods statement; prove the chain on a synthetic pilot-shaped fixture.

**Architecture:** The report is a pure read model over the projection (`services/evidence.py`), recomputed on every call and never stored as events (R-05): groups come from D's `grouped_rows`; deterministic helpers in `factory/evidence/` compute the Pareto frontier and speed ratios; the `ml-benchmark` pack gains a small `ReportSpec` (metric directions, cost axes, speed fields). Renderers (Markdown, CSV) are formatting only and draw no charts. `mcp/` and `cli/` parse, call and format.

**Tech Stack:** as plans A-D; `decimal.Decimal` for all arithmetic; no new dependencies.

**Spec:** `docs/specs/slice-2.md` (Comparability and evidence report; cost axes of decision 42 item 3; Extraction schema; acceptance 12, 12a, 14, 16; Pilot end-to-end). `docs/specs/01-rigour.md` R-05, R-42, R-44, R-45, R-47. Decisions 41, 42, 43, 47, 50 (Proposed); backlog IDEA-06 (accepted); IDEA-07 (contradiction finder) and IDEA-23 stay out.

## Rulings made in this plan

Rulings marked **[confirm]** go beyond the spec or decide an ambiguity; the researcher confirms them at plan review. Task 9 records them as decision 52 (*Proposed*; D uses 51).

1. **The report is a derived read model.** `evidence_report(project, *, expect=()) -> EvidenceReport` reads the projection only (no library, no event written). It is recomputed per call, so it can never be stale; instead it excludes what is not final and says so (ruling 11). Every number is computed (R-05).
2. **Groups.** One group per distinct key of `grouped_rows(project).groups`, i.e. identical values of the protocol's `comparability_keys` (defaults: task, dataset, split, metric, input_resolution, pretraining_data). Groups are listed in lexicographic order of their key and are given a stable `group_id = "grp_" + first 12 hex of sha256(json of the key pairs)`. No order, score or comparison crosses groups; the models have no field that could hold one. Rows missing a key are `ungrouped` and listed.
3. **Per-group table.** One `EvidenceRow` per final row, sorted by (normalised method name, work id, row key) — deliberately not by value. Each carries provenance for the value and for every shown cost cell: printed value, unit, canonical, anchor, cell, verbatim quote, `reported_in`, `copy_marker`, `reproduced`, `cited_work`, `extraction_id`, and a `trace_id` (`<row_key>/<field>`, ruling 9). Row `status` (`agreed|resolved|single`) is shown.
4. **Counts and source flags.** Per group: `independent` and `copied` from D's `independence_counts`, distinct `works`, `independent_works`. Flags (stated in the group's `statements`): `single-paper` (one work), `single-independent-source` (at most one work with an independent row), `no-independent-results` (only copied rows). A group never silently looks stronger than its sources.
5. **Metric direction and units.** The direction of a group is `higher_is_better` as declared by its rows; if no row declares it, the pack's `ReportSpec.metric_directions` default for the normalised metric; if neither, it is unknown. Declared values that disagree with each other or with the pack default are a `direction-conflict`; an unknown direction gives `direction-unknown`. In both cases the group's table is shown and **no frontier is computed**. Units are compared, never converted (D ruling 7): a group whose value rows mix `%` and `fraction` gets one frontier partition per unit (ruling 6). **[confirm]** (the alternative, a declared exact conversion in the pack, would contradict D's "never rescaled").
6. **Frontiers (acceptance 12, 12a).** Per group, one frontier per hardware-independent cost axis, `params`, `flops`, `macs` (`ReportSpec.frontier_costs`), computed over **independent rows** only (copied rows are shown and marked, not plotted). `flops` and `macs` are separate axes and never merged. The frontier is further partitioned by value unit and, when `input_resolution` is not one of the group's keys, by resolution, so a frontier is always "at the group's resolution". Throughput, latency and memory never enter a frontier, a group key or a group table (ruling 7). **[confirm]** independent-only frontiers; separate flops and macs axes.
7. **Speed (acceptance 12a).** Throughput and latency (`ReportSpec.speed_fields`) appear only in a section `speed_ratios`, organised by work and never inside a group table or a frontier. A ratio is formed inside one work between a proposed row (`is_proposed = true`) and each baseline row (`is_proposed = false`) of the same work and document, when both speed values are effectively own (not cited, no copy marker), have the same unit, equal normalised `hardware` (present), and equal `batch_size` and `precision` (equal or both absent). Throughput ratio = proposed / baseline; latency ratio = baseline / proposed (both read "x times faster"); Decimal, rounded half-even to 2 places, stored as a string. Each ratio shows baseline, hardware, batch size, precision and both provenances. Pairs that fail are counted in `speed_unpaired` with a reason (`no-baseline`, `hardware-missing`, `hardware-differs`, `context-differs`, `unit-differs`, `not-own`). Absolute speed values are shown only inside a ratio's provenance. **[confirm]** (spec says "extracted and shown"; this keeps them out of group tables so no cross-paper reading is invited). *Amended 2026-11-04 (final review; decision 52):* pairing is driven by `ReportSpec.speed_context` (for `ML_BENCHMARK_V1`: hardware, batch size, precision and input resolution; `hardware` must be present, the others equal or both absent) and is formed only between rows of the same group (identical comparability key); further reasons `group-differs` and `key-missing` (a row in no group). Each ratio also carries `context`, the proposed row's printed context values, and the rendered table shows the resolution. Ratios are deduplicated on (work, field, method, variant, baseline, baseline variant, group, context values).
8. **Pareto computation** (deterministic, `factory/evidence/pareto.py`). Points have positive cost and a metric `Decimal`. Sort by (cost ascending, metric best-first, method name, work id, row key). A point `p` is dominated iff another point `q` has `q.cost <= p.cost`, a metric at least as good, and at least one strictly better. Equal-cost-equal-metric points do not dominate each other and all stay on the frontier. Implementation: sweep cost groups; `p` is on the frontier iff its metric equals the best of its cost group and is strictly better than the best metric among strictly cheaper points. Dominated points are returned with `dominated_by` = the first dominating point in sorted order. A row lacking the cost, or whose cost is not positive, is not a point; it is counted per axis with a reason (`cost-missing`, `cost-not-positive`). A partition with fewer than two points states that no frontier can be drawn.
9. **Trace to cells and claims (acceptance 14).** New node kind `cell`, id `<row_key>/<field>` (bare `<row_key>` means `value`), shown by evidence-report tables. Back from a cell: cell -> its extraction(s) (both passes, live and superseded) -> D's edges (work, protocol, cited anchors -> conversion -> document version -> retrieval attempt -> work, full-text decisions -> protocol -> question). Forward from a cell: nothing new. A claim id traces back as D defines it; the report lists claim ids so they can be traced. **[confirm]** the id form and the bare-row alias.
10. **Claims and R-42.** The report lists live pass-A claims of included works grouped by claim type (finding, mechanism, limitation, negative-result), unmerged and unranked, with the agent's strength stated as the agent's judgement. Within a group, two independent rows for the same normalised (method, variant) with different canonical values are listed as `method_conflicts` with both provenances, never averaged. No contradiction analysis between claims is done (IDEA-07); the limits state that.
11. **Limits statement (R-42).** `limits` is a list of `Limit(code, text, subject)` generated by the platform, never typed, and never containing document text: empty expectations, single-paper and single-independent-source groups, copied-only groups, direction problems, frontier partitions with fewer than two points, ungrouped rows, rows excluded because a disagreement is unresolved or the row is stale (counted by reason), included works with no final row, works outside the dual sample (single extraction), audit missing or above ceiling, and a fixed sentence that claims are not cross-checked. The report is `provisional` while any unit is not current or any disagreement is unresolved.
12. **Expectations. [confirm]** "Empty groups" cannot arise from rows alone, so `expect` is a list of partial keys (e.g. `{"task": "image classification", "dataset": "imagenet-1k"}`), matched to groups on the normalised values given. An expectation matching no group yields `expectation-empty`; one matching groups lists their ids. Expectations are call parameters, not protocol fields (no hash change), and appear in the output.
13. **Outputs.** `EvidenceReport` (pydantic) is the only source; renderers are `evidence_markdown` and two CSV exports (`points_csv`: one line per frontier point for plotting; `rows_csv`: one line per table row). The platform renders no chart. Over MCP the result is JSON only.
14. **Surfaces.** MCP `report_evidence(project, expect=[])` and CLI `factory report evidence [--expect KEY=VALUE,KEY=VALUE ...] [--format md|json|csv-rows|csv-points] [--output PATH]`. Read-only. Refused to any session that joined a screening or extraction pass (as `report_prisma`, decision 43). The agent view omits the audit error rate and ceiling flag (label-derived, decision 43); the CLI shows them.
15. **Pack report details. [confirm]** `ReportSpec` is derivation-only code in the pack module, not part of any event or hash, so `pack_version` stays 1; the report records `pack`, `pack_version` and `REPORT_VERSION = 1` so a result is reproducible.
16. **Pilot end-to-end (acceptance 16).** Slice 2 is built without pilot data (decision 47), so the platform test is a synthetic fixture of the pilot's shape (Task 9). The run on the real linear-attention pilot, including the conversion-quality comparison to the bake-off, is a later manual step added to `docs/runbook-fulltext-usecase.md`.
17. **Out of scope.** Charts, ranking across groups, composite scores, cross-paper speed comparison, contradiction/gap finder (IDEA-07), copied-result consistency check (IDEA-23), appraisal (IDEA-21), prose synthesis.

## Interface requests to plan D

D is not changed by this plan; these are what E needs and D does not yet state.

1. **Non-refusing agreement summary.** `agreement_overall(project) -> float | None` (and the dual/single counts) readable without an actor and returning `None` instead of refusing while tasks are open. `extraction_agreement` refuses; the report must degrade to "not yet computed". D's methods extension needs the same.
2. **Claim row model.** `live_claims(project, pass_label=None, *, work_id=None) -> list[ClaimRow]` with `ClaimRow(StrictModel)`: `claim_id, work_id, pass_label, claim_type, evidence_type, strength, statement, anchor, quote, conversion_id, event_id`.
3. **Unit states for included works.** `unit_states(project)` must list every included work (state `queued` when never served), so "included works with no final row" is computable.
4. **Row lookup.** `extraction_ids_for_row(project, row_key, field) -> list[str]`-equivalent: the projection columns `extraction_rows.row_key` and `extraction_fields.field` exist (D Task 3), so trace SQL needs no service; confirm `row_key` is indexed.

## Global Constraints

- All plan A-D constraints hold. The platform never calls a model. The report reads the projection only; the projection never reads the library. Business logic in `services/` and `factory/evidence/`; `mcp/` and `cli/` parse, call, format.
- Every number in the report is computed from events (R-05). No document text appears in any `Limit`, finding or error; quotes appear only as the verified quotes stored in rows.
- Slice-1 and plans A-D behaviour unchanged: earlier tests pass without edits. No event type is added; `PROJECTION_VERSION` is not bumped. Existing `trace` ids and MCP tool lists change only by the additions named here.
- `uv run pytest -m "not network"`, `mypy --strict` (new and changed files), ruff pass; coverage >= 90% for `services/` and `model/`.

## Review Focus

1. Two groups differing in one key (resolution 224 vs 384, or pretraining none vs ImageNet-21K) never share a table, a frontier or a count, and the report has no field comparing them (Tasks 2, 3).
2. A copied row ("DeiT-S [41]") appears in its group table marked copied, is excluded from the frontier and from the independent count, and a method appearing only as copied does not make a group look multi-source (Tasks 2, 3).
3. Throughput and latency never appear in a group table, a frontier, a CSV of points or the Markdown group sections; a ratio needs the same work, hardware, batch size, precision and unit, and a ratio against a cited or other-hardware baseline is not produced (Tasks 4, 5).
4. Pareto edge cases: equal points both kept, equal cost with different metric, missing and non-positive costs, lower-is-better metrics, one point, mixed `%` and `fraction`, conflicting or unknown direction yields no frontier (Tasks 1, 3).
5. A report requested while a disagreement is unresolved or a row is stale excludes those rows, says how many and why, and is `provisional`; a corpus with no extraction schema returns an empty report with the limit, not an error (Tasks 2, 7).

## File Structure

- Create `factory/evidence/__init__.py`, `factory/evidence/pareto.py` (pure Pareto, speed ratio); modify `factory/packs/__init__.py` (`ReportSpec`, `Pack.report`), `factory/packs/ml_benchmark.py`.
- Create `services/evidence.py` (models, groups, frontiers, ratios, claims, limits, `evidence_report`, `agent_evidence`), `cli/evidence_render.py` (Markdown and CSV renderers).
- Modify `services/trace.py` (kind `cell`), `services/check.py`, `services/methods.py`, `mcp/server.py`, `cli/main.py`, `docs/runbook-fulltext-usecase.md`, `docs/specs/slice-2.md`, `docs/decisions.md`, `CLAUDE.md`.
- Tests: `test_evidence_pareto.py`, `test_evidence_groups.py`, `test_evidence_frontier.py`, `test_evidence_speed.py`, `test_evidence_render.py`, `test_evidence_trace.py`, `test_evidence_check_methods.py`, `test_mcp_evidence.py`, `test_cli_evidence.py`, `test_acceptance_evidence.py`; helper `tests/evidence_helpers.py` (builds on D's `tests/extraction_helpers.py`: a pilot-shaped project with several included works, tables, copied rows, throughput rows, both passes recorded and agreed).

---

### Task 1: Pareto and ratio helpers (pure)

*Tier: critical (frontier correctness).*

**Files:** Create `factory/evidence/__init__.py`, `factory/evidence/pareto.py`; Test `tests/test_evidence_pareto.py`.

**Interfaces:**
- Produces: `@dataclass(frozen=True) Point(row_key: str, cost: Decimal, metric: Decimal, method: str, work_id: str)`; `@dataclass(frozen=True) ParetoResult(frontier: tuple[Point, ...], dominated: tuple[tuple[Point, Point], ...])` (dominated pairs are `(point, dominating point)`); `pareto(points: Sequence[Point], *, higher_is_better: bool) -> ParetoResult` (raises `ValueError` on a non-positive cost; ruling 8); `speed_ratio(proposed: Decimal, baseline: Decimal, *, higher_is_faster: bool) -> Decimal | None` (ruling 7; `None` when either is not positive; quantised to 2 places, half-even).

- [ ] **Step 1: Tests.**
```python
def P(k, cost, metric): return Point(k, Decimal(cost), Decimal(metric), "m", "rf:w")
def test_dominated_point_is_listed_with_its_dominator():
    r = pareto([P("a", "22", "79.8"), P("b", "25", "78.0"), P("c", "50", "83.0")], higher_is_better=True)
    assert [p.row_key for p in r.frontier] == ["a", "c"] and [(p.row_key, q.row_key) for p, q in r.dominated] == [("b", "a")]
def test_equal_cost_better_metric_dominates(): ...          # same cost 25: 78.0 dominated by 79.0
def test_identical_points_both_on_frontier():
    assert {p.row_key for p in pareto([P("a","22","79.8"), P("b","22","79.8")], higher_is_better=True).frontier} == {"a", "b"}
def test_same_metric_higher_cost_is_dominated(): ...         # (22, 79.8) dominates (30, 79.8)
def test_lower_is_better_flips_metric_order(): ...           # perplexity / error rate
def test_single_point_and_empty():
    assert [p.row_key for p in pareto([P("a","1","1")], higher_is_better=True).frontier] == ["a"] and pareto([], higher_is_better=True).frontier == ()
def test_non_positive_cost_raises(): ...                     # 0 and -1 -> ValueError
def test_output_order_is_deterministic_under_input_permutation(): ...   # every permutation of 6 points gives equal ParetoResult
def test_dominator_is_first_in_sorted_order(): ...
def test_speed_ratio():
    assert speed_ratio(Decimal("1800"), Decimal("1000"), higher_is_faster=True) == Decimal("1.80")
    assert speed_ratio(Decimal("10"), Decimal("18"), higher_is_faster=False) == Decimal("1.80")   # latency: baseline / proposed
    assert speed_ratio(Decimal("0"), Decimal("1"), higher_is_faster=True) is None
```
- [ ] **Step 2:** Run `uv run pytest tests/test_evidence_pareto.py -v`; FAIL. **Step 3:** Implement per ruling 8 (sweep by cost groups; sort key `(cost, -metric if higher else metric, method, work_id, row_key)`). **Step 4:** Tests, mypy, ruff pass. **Step 5:** Commit `feat(evidence): deterministic Pareto frontier and speed ratio`.

### Task 2: Report model, groups, counts, claims, limits

*Tier: critical (grouping and independence).*

**Files:** Modify `packs/__init__.py` (`ReportSpec`, `Pack.report: ReportSpec | None = None`), `packs/ml_benchmark.py`; Create `services/evidence.py`; Test `tests/test_evidence_groups.py`, `tests/evidence_helpers.py`.

**Interfaces:**
- Consumes (D): `grouped_rows(project) -> Grouped`, `final_rows`, `independence_counts`, `FinalRow/FinalField`, `live_claims`, `stale_claims`, `unit_states`, `stale_extractions`, `require_schema`, `normalise_text`, `normalise_for`; `extraction_audit_report`; interface requests 1-3. Claims shown in the report are `live_claims(project, PassLabel.A)` minus `stale_claims(project)` minus claims of works outside the extraction population; the claim trace and claim counts use the same filter.
- Produces (`packs`): `@dataclass(frozen=True) ReportSpec(value_field: str, direction_field: str, metric_directions: Mapping[str, bool], frontier_costs: tuple[str, ...], speed_fields: Mapping[str, bool], speed_context: tuple[str, ...], proposed_field: str, display_costs: tuple[str, ...])`; `ML_BENCHMARK_V1.report`: `value`, `higher_is_better`, directions for normalised `top-1 accuracy`/`top-5 accuracy`/`miou`/`box ap`/`mask ap`/`accuracy` true and `perplexity`/`top-1 error`/`error rate`/`fid` false, `("params","flops","macs")`, `{"throughput": True, "latency": False}` (value = higher is faster), `("hardware","batch_size","precision")`, `is_proposed`, `("params","flops","macs")`. `REPORT_VERSION = 1` in `services/evidence.py`.
- Produces (`services/evidence.py`, all `StrictModel`): `Provenance(field, value, unit, canonical, anchor, cell, quote, reported_in, copy_marker, reproduced, cited_work, extraction_id, trace_id)`; `EvidenceRow(row_key, work_id, title, document_id, conversion_id, status, independent, method_name, variant, is_proposed, value: Provenance, costs: dict[str, Provenance], regime: dict[str, str])`; `Limit(code, text, subject: str | None)`; `GroupCounts(independent, copied, works, independent_works)`; `MethodConflict(method, variant, rows: list[str])`; `GroupReport(group_id, key: list[tuple[str, str]], rows: list[EvidenceRow], counts: GroupCounts, direction: bool | None, direction_status: Literal["declared","pack-default","conflict","unknown"], frontiers: list[FrontierAxis] = [], method_conflicts, statements: list[Limit])`; `ClaimEntry(claim_id, work_id, claim_type, evidence_type, strength, statement, anchor, quote, trace_id)`; `Excluded(reason: Literal["unresolved","stale","no-final-row"], count: int, works: list[str])`; `Quality(dual_works, single_extraction_works, agreement_overall: float | None, audit_n, audit_error_rate: float | None, audit_above_ceiling: bool | None)`; `EvidenceReport(project_protocol_id, pack, pack_version, report_version, comparability_keys, provisional, groups, ungrouped: list[EvidenceRow], claims: dict[str, list[ClaimEntry]], speed_ratios: list[WithinPaperRatio] = [], speed_unpaired: dict[str, int] = {}, excluded: list[Excluded], expectations: list[ExpectationResult], quality, limits: list[Limit])`; `evidence_report(project: Project, *, expect: Sequence[Mapping[str, str]] = ()) -> EvidenceReport`. `FrontierAxis`, `WithinPaperRatio` are defined in Tasks 3 and 4 (declare them there; this task leaves the lists empty).
- Without a declared schema or any final row, the report is empty with limit `no-extraction` (no error).

- [ ] **Step 1: Tests** (helper: five included works; one group G1 = imagenet-1k / top-1 / 224 / none with rows from three works, one copied by cited marker and one by `own`+marker; a 384 group; a single-paper ADE20K group; one row missing `split`).
```python
def test_groups_only_by_identical_keys():
    r = evidence_report(project)
    assert [g.key for g in r.groups] == sorted(g.key for g in r.groups)       # lexicographic, not by size or value
    assert not any(row_in(g224, w384) for w384 in g384.rows)
def test_resolution_variants_group_together(): ...          # "224" and "224x224"
def test_counts_independent_vs_copied_from_d():
    g = group(r, "imagenet-1k", 224); assert (g.counts.independent, g.counts.copied) == (2, 2) and g.counts.works == 4
def test_single_paper_and_single_source_flags():
    assert {s.code for s in group(r, "ade20k").statements} >= {"single-paper", "single-independent-source"}
def test_copied_only_group_states_no_independent_results(): ...
def test_group_id_is_stable_and_report_has_no_cross_group_field():
    assert group(r, "ade20k").group_id == group(evidence_report(project), "ade20k").group_id
    assert not {"rank", "score", "best", "winner"} & set(EvidenceReport.model_fields) | set(GroupReport.model_fields)
def test_row_provenance_complete(): ...                      # value.quote, anchor, cell, extraction_id, trace_id == f"{row_key}/value"
def test_table_order_is_not_by_value(): ...
def test_method_conflict_listed_not_averaged(): ...          # same method, two works, 79.8 vs 80.1, both independent
def test_direction_declared_pack_default_conflict_unknown(): ...   # four cases of ruling 5
def test_ungrouped_rows_listed_and_limit_stated(): ...
def test_unresolved_and_stale_rows_excluded_and_provisional():     # Review Focus 5
    assert {(e.reason, e.count) for e in r.excluded} == {("unresolved", 1), ("stale", 1)} and r.provisional
def test_included_work_without_rows_listed(): ...            # reason no-final-row
def test_claims_grouped_by_type_unmerged_with_trace_ids(): ...
def test_expectations():                                     # ruling 12
    r = evidence_report(project, expect=[{"dataset": "imagenet-1k"}, {"dataset": "coco"}])
    assert r.expectations[0].group_ids and r.expectations[1].group_ids == [] and "expectation-empty" in codes(r.limits)
def test_no_schema_returns_empty_report_with_limit(): ...
def test_quality_block_computed_not_typed(): ...
def test_limits_contain_no_document_text(): ...
def test_report_unchanged_after_index_rebuild_and_without_library(): ...   # delete the library dir; equal model_dump
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement `evidence_report` (group id by sha256 of `json.dumps(key)`; value/cost provenance from `FinalField`; direction per ruling 5; limits per ruling 11; titles from the works service; expectations match on normalised partial keys). **Step 4:** Tests, D's pack tests unchanged, mypy, ruff. **Step 5:** Commit `feat(evidence): evidence report model, groups, counts, claims, limits`.

### Task 3: Frontiers per group and cost axis

*Tier: critical (acceptance 12, 12a).*

**Files:** Modify `services/evidence.py`; Test `tests/test_evidence_frontier.py`.

**Interfaces:**
- Consumes: Task 1 `pareto`, `Point`; Task 2 `GroupReport`, `ReportSpec`.
- Produces: `FrontierPoint(row_key, work_id, method_name, cost, metric, on_frontier: bool, dominated_by: str | None, trace_id)` (cost and metric as canonical decimal strings); `FrontierPartition(unit: str | None, resolution: str | None, points: list[FrontierPoint], statement: str | None)`; `FrontierAxis(axis: str, partitions: list[FrontierPartition], missing: dict[str, list[str]])` (`missing` maps `cost-missing` / `cost-not-positive` to row keys). `GroupReport.frontiers` is filled for every `ReportSpec.frontier_costs` axis declared in the protocol's fields, empty (with a `direction-*` statement) when the direction is not `declared|pack-default`.

- [ ] **Step 1: Tests.**
```python
def test_frontier_points_trace_to_their_rows():              # acceptance 12
    ax = axis(group(r, "imagenet-1k", 224), "params")
    assert all(p.trace_id == f"{p.row_key}/value" and row_exists(p.row_key) for part in ax.partitions for p in part.points)
def test_frontier_uses_only_cost_axes_of_decision_42():      # acceptance 12a
    assert {a.axis for g in r.groups for a in g.frontiers} <= {"params", "flops", "macs"}
def test_flops_and_macs_are_separate_axes(): ...
def test_copied_rows_are_not_plotted(): ...                  # Review Focus 2
def test_missing_and_non_positive_cost_counted_not_plotted(): ...
def test_lower_is_better_group(): ...
def test_conflicting_or_unknown_direction_gives_no_frontier_and_a_statement(): ...
def test_percent_and_fraction_are_separate_partitions(): ...   # never converted
def test_resolution_partitions_when_not_a_key(): ...         # schema drops input_resolution from the keys
def test_single_point_partition_states_no_frontier(): ...
def test_frontiers_identical_for_permuted_event_order(): ...
def test_no_speed_value_in_any_frontier_structure():
    assert "throughput" not in r.model_dump_json(include={"groups": {"__all__": {"frontiers"}}})
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement (points from independent rows with both the canonical value and cost parsed by `Decimal`; partition by unit and conditionally resolution; `higher_is_better` from the group). **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(evidence): per-group Pareto frontiers on hardware-independent cost axes`.

### Task 4: Within-paper speed ratios

*Tier: critical (acceptance 12a).*

**Files:** Modify `services/evidence.py`; Test `tests/test_evidence_speed.py`.

**Interfaces:**
- Produces: `WithinPaperRatio(work_id, document_id, field: Literal["throughput","latency"], method, baseline_method, ratio: str, unit, hardware, batch_size: str | None, precision: str | None, proposed: Provenance, baseline: Provenance)`; `EvidenceReport.speed_ratios` sorted by (work id, field, method, baseline); `EvidenceReport.speed_unpaired: dict[str, int]` (reason -> count; reasons of ruling 7). Pairing uses the final rows of one work and one document; ratios are deduplicated on (work, field, method, variant, baseline, hardware, batch size, precision).

- [ ] **Step 1: Tests.**
```python
def test_ratio_with_baseline_hardware_and_context():          # "1.8x faster than DeiT-S on A100, batch 64"
    x = ratio(r, "ours", "deit-s"); assert (x.ratio, x.hardware, x.batch_size, x.baseline_method) == ("1.80", "a100", "64", "DeiT-S")
def test_latency_ratio_is_baseline_over_proposed(): ...
def test_no_ratio_across_papers(): ...                         # proposed in work A, baseline only in work B: no ratio, unpaired no-baseline
def test_no_ratio_when_hardware_differs_or_missing(): ...      # hardware-differs, hardware-missing
def test_no_ratio_when_batch_or_precision_differs(): ...       # context-differs
def test_no_ratio_when_baseline_is_cited_or_copy_marked(): ... # not-own
def test_unit_mismatch_not_paired(): ...                       # img/s vs ms
def test_speed_values_absent_from_group_tables_and_points():   # acceptance 12a
    assert all(f not in row.costs for g in r.groups for row in g.rows for f in ("throughput", "latency", "memory"))
def test_ratios_are_computed_with_decimal_and_rounded_half_even(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement with Task 1 `speed_ratio`; hardware compared with `normalise_text`. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(evidence): within-paper speed ratios`.

### Task 5: Renderers

*Tier: standard (Sonnet implement, Haiku review); formatting only.*

**Files:** Create `cli/evidence_render.py`; Test `tests/test_evidence_render.py`.

**Interfaces:**
- Consumes: `EvidenceReport`. Produces: `evidence_markdown(report: EvidenceReport, *, show_audit: bool = True) -> str`; `points_csv(report) -> str` (header `group_id,axis,unit,resolution,row_key,work_id,method,cost,metric,on_frontier,dominated_by`); `rows_csv(report) -> str` (header `group_id,row_key,work_id,method,variant,value,unit,canonical,independent,status,params,flops,macs,anchor,cell,extraction_id`). Both CSVs are the stdlib `csv` module with `\n` line ends and a fixed row order (the report's order).

- [ ] **Step 1: Tests.**
```python
def test_markdown_has_one_section_per_group_and_no_cross_group_text(): ...    # no "best overall", no table spanning groups
def test_markdown_group_section_shows_counts_flags_frontier_and_provenance_ids(): ...
def test_markdown_lists_limits_expectations_excluded_and_provisional_banner(): ...
def test_markdown_speed_only_in_ratio_section_with_baseline_and_hardware():   # acceptance 12a
    md = evidence_markdown(r); head, speed = md.split("## Within-paper speed ratios"); assert "img/s" not in head and "A100" in speed
def test_csv_points_have_no_speed_columns_and_are_stable(): ...
def test_audit_rate_hidden_when_show_audit_false(): ...
def test_render_is_deterministic(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement; sections: header (protocol, pack, keys), limits, per group (key, counts, statements, table, frontiers), method conflicts, ungrouped, within-paper speed ratios, claims by type, excluded, quality. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(evidence): Markdown and CSV renderers`.

### Task 6: Trace to cells and claims

*Tier: critical (acceptance 14).*

**Files:** Modify `services/trace.py` (`KINDS` gains `cell` after `claim`; `_PATTERNS` gains `(r"^rk_[0-9a-f]{12}(?:/[a-z][a-z_]*)?$", "cell")`; `_describers`, `_EDGES`, `_cell`, `_edges_cell`); Test `tests/test_evidence_trace.py`.

**Interfaces:**
- Consumes: D's `extraction` and `claim` kinds and edges; projection tables `extraction_rows`, `extraction_fields`, `decisions`.
- Produces: describer label `"<field> cell of <work>"`; event = the earliest extraction's event; `_edges_cell(ident)`: up = every `extraction` with that `row_key` carrying that field (bare id = `value`), down = none. A cell whose key matches no row is a dangling leaf as for other kinds; `dangling_refs` reports it.

- [ ] **Step 1: Tests** (acceptance 14).
```python
def test_trace_from_report_cell_reaches_question():
    kinds = chain_kinds(trace(project, f"{row_key}/value"))
    assert kinds >= ["cell", "extraction", "anchor", "conversion", "document", "attempt", "work", "decision", "protocol", "question"]
def test_chain_passes_through_document_version_and_retrieval_attempt(): ...      # ids equal the fixture's document and attempt
def test_bare_row_key_means_value_cell(): ...
def test_both_passes_listed_and_superseded_row_linked(): ...
def test_cost_cell_traces_to_its_own_anchor(): ...
def test_claim_traces_back_to_question():
    assert "question" in chain_kinds(trace(project, claim_id))
def test_unknown_cell_is_unknown_id_error(): ...             # FactoryValidationError field "ref"
def test_agent_trace_works_for_cells_and_hides_seed_nodes(): ...
def test_slice1_and_plan_c_traces_unchanged(): ...           # existing test_trace suites pass unedited
def test_every_report_trace_id_resolves(): ...               # for all rows/points/claims in the report
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests plus all trace suites unedited, mypy, ruff. **Step 5:** Commit `feat(trace): evidence cells and claims`.

### Task 7: `check` findings, methods statement, agent view

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Modify `services/check.py`, `services/methods.py`, `services/evidence.py` (`agent_evidence`); Test `tests/test_evidence_check_methods.py`.

**Interfaces:**
- `check` codes (warning in all modes): `evidence-excluded-rows` (the report omits rows for an unresolved disagreement or staleness; message gives counts and work ids only), `evidence-ungrouped` (rows missing a comparability key), `evidence-direction` (a group with `direction-conflict` or `direction-unknown`, listing group ids). Each has no finding without a schema.
- `MethodsReport` gains `evidence_groups: int = 0`, `evidence_multi_source_groups: int = 0`, `evidence_rows: int = 0`, `evidence_independent: int = 0`, `evidence_copied: int = 0`, `evidence_comparability_keys: list[str] = []`, `evidence_frontier_costs: list[str] = []`; `render_methods` adds a paragraph: results are grouped only by the declared keys, never ranked across groups; copied results are flagged and not counted as independent; frontiers use params, FLOPs and MACs only; throughput and latency appear only as within-paper ratios; counts as computed. Absent without a schema (existing methods tests pass unedited).
- `agent_evidence(report: EvidenceReport) -> EvidenceReport`: `quality.audit_error_rate = None`, `audit_above_ceiling = None`, and the `audit-above-ceiling` limit replaced by `audit-reported-to-researcher`.

- [ ] **Step 1: Tests.** One positive and one absent case per code; `test_check_findings_name_no_document_text`; `test_methods_without_schema_unchanged`; `test_methods_counts_equal_report_counts` (computed, one source); `test_methods_text_states_cost_axes_and_no_ranking`; `test_agent_view_hides_audit_rate_and_flag`; `test_cli_view_shows_audit_rate`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement (check and methods call `evidence_report`; one call per `check`). **Step 4:** Existing check and methods suites unedited, mypy, ruff. **Step 5:** Commit `feat(evidence): check findings, methods statement, agent view`.

### Task 8: MCP `report_evidence` and CLI `factory report evidence`

*Tier: Haiku for implementation and review (surfaces); behaviour is covered by Tasks 2-7.*

**Files:** Modify `mcp/server.py`, `cli/main.py`; Test `tests/test_mcp_evidence.py`, `tests/test_cli_evidence.py`; extend the pinned MCP tool-list test.

**Interfaces:**
- MCP: `report_evidence(project: str, expect: list[dict[str, str]] = []) -> dict[str, JsonValue]`: opens the project, `_refuse_pass_session` (screening and extraction sessions, D's extension), `agent_evidence(evidence_report(opened, expect=expect))`, `_withheld(opened, data, include_work_ids=False)`; a malformed `expect` item is a structured error and writes nothing (nothing is written anyway).
- CLI: `@report_app.command("evidence")` with `--expect TEXT` (repeatable, `key=value,key=value`), `--format [md|json|csv-rows|csv-points]` (default `md`), `--output PATH` (write instead of echo); full view (audit rate shown); an unparseable `--expect` exits non-zero with a message; `report_app` help updated.

- [ ] **Step 1: Tests.** MCP: tool list gains exactly `report_evidence`; refused to a screening-pass session and to an extraction-pass session; held-out seed identifiers withheld; agent view has no audit rate; `expect` returns expectation results; read-only (event count unchanged). CLI: `md` default contains group sections; `json` equals `evidence_report(...).model_dump_json()`; `csv-points` header exact; `--expect dataset=coco` yields `expectation-empty`; `--output` writes the file; bad `--expect` is refused.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(evidence): report_evidence over MCP and CLI`.

### Task 9: Pilot-shaped acceptance test, runbook and docs

*Tier: test by Sonnet (critical review of the fixture's independence from implementation), docs by Haiku.*

**Files:** Test `tests/test_acceptance_evidence.py`; modify `docs/runbook-fulltext-usecase.md` (new steps), `docs/specs/slice-2.md` ("Implemented in plan 2E" paragraph), `docs/decisions.md` (decision 52, *Proposed*), `CLAUDE.md` (status line: sub-plan 2E).

- [ ] **Step 1: Tests** (acceptance 12, 12a, 14, 16 on the synthetic fixture of `evidence_helpers`: seven included works hand-built from Markdown with results tables; ImageNet-1K / image classification / top-1 / 224 / no pretraining group with independent rows from at least three works and two copied rows; a 384 group; a single-paper ADE20K segmentation group; throughput rows with hardware, batch size and a baseline in two works; both passes recorded and agreed, one disagreement human-resolved, one human audit labelled).
```python
def test_pilot_shaped_run_reaches_evidence_report_with_imagenet_group():     # acceptance 16
    r = evidence_report(project, expect=[{"task": "image classification", "dataset": "imagenet-1k"}])
    g = group(r, "imagenet-1k", 224); assert g.counts.independent >= 3 and g.frontiers and r.expectations[0].group_ids == [g.group_id] and not r.provisional
def test_report_is_reproducible_from_events_alone():
    first = evidence_report(project).model_dump_json(); project.index.rebuild(); shutil.rmtree(project.paths.library_dir)
    assert evidence_report(project).model_dump_json() == first        # events plus index; the library is not read
def test_no_ranking_across_groups_and_empty_single_groups_stated():      # acceptance 12
    assert "single-paper" in codes(group(r, "ade20k").statements) and "expectation-empty" in codes(evidence_report(project, expect=[{"dataset": "coco"}]).limits)
def test_cost_axes_only_params_flops_macs_and_speed_only_as_ratio():       # acceptance 12a
def test_every_frontier_point_cell_and_claim_traces_to_the_question():    # acceptance 14
    for pid in all_trace_ids(r): assert "question" in chain_kinds(trace(project, pid))
def test_cli_markdown_and_csv_are_deterministic_and_consistent_with_json(): ...
def test_earlier_acceptance_suites_unchanged(): ...
```
- [ ] **Step 2:** Run; fix until PASS. **Step 3:** Docs. Slice-2 paragraph: what plan E implemented (`report_evidence`, `factory report evidence`, trace kind `cell`, check codes, methods fields). Runbook: add step 15 "Extraction passes, agreement, resolution and audit [A/H]" and step 16 "Evidence report [H]: `factory report evidence --expect task=...,dataset=imagenet-1k`, `check`, `trace` of a cell id", a checklist item for each of acceptance 12, 12a, 14 on real data, and a conversion-quality item: compare the included works' conversion results (`factory document status`) to `experiments/converter-bakeoff/results/` (acceptance 16, decision 47). Decision 52 (*Proposed*): "Evidence-report rulings of plan 2E: independent-only frontiers; separate flops and macs axes; unit partitions without conversion; no frontier when direction conflicts or is unknown; speed only in a within-paper section with strict pairing; expectations as call parameters for empty groups; trace kind `cell` with id `<row_key>/<field>`; derivation-only `ReportSpec` without a pack version bump; agent view withholds audit error rate. Needs the researcher's confirmation." **Step 4:** Full suite, mypy, ruff, coverage >= 90% for `services/` and `model/`. **Step 5:** Commit `test(evidence): plan 2E acceptance; runbook and docs`.

## Self-review notes

- **Spec coverage.** Comparability keys, grouping by identical keys, no ranking, acceptance 12 (rulings 2-4, Tasks 2, 3); cost axes and within-paper ratios, 12a (rulings 6-7, Tasks 3, 4, 5); per-group table, Pareto, independent/copied, single-source flags (Tasks 1-3); empty and single-paper statements, R-42 (rulings 4, 10-12, Task 2); report outputs (ruling 13, Task 5); `report_evidence`, trace to cells and claims, acceptance 14 (Tasks 6, 8); methods and check extensions (Task 7); acceptance 16 as a synthetic fixture with the real run documented in the runbook (ruling 16, Task 9); IDEA-06 frontier view delivered, its coverage matrix is covered by `expect` and group listing; R-05 by construction (no stored report). Decision 49 touches nothing here.
- **Type consistency.** `Provenance`, `EvidenceRow`, `GroupReport`, `FrontierAxis`, `WithinPaperRatio`, `Limit`, `EvidenceReport`, `evidence_report`, `agent_evidence`, `ReportSpec`, `REPORT_VERSION`, `pareto`, `Point`, `speed_ratio` carry the same names in Tasks 1-9; D names used exactly as D states them (`grouped_rows`, `final_rows`, `independence_counts`, `live_claims`, `unit_states`, `stale_extractions`, `FinalRow`, `FinalField`).
- **Proportion.** Nine tasks, the pure algorithm and the trace edge are the only places with specified logic; the rest is signatures and tests.
- **Rulings needing the researcher** are those marked **[confirm]**: 5, 6, 7, 9, 12, 15, plus ruling 14's agent-view withholding (follows decision 43). The four interface requests to D must be answered before Task 2 starts.
- **Tiers.** Critical (Sonnet implement, per-task review, second look on Tasks 1, 3, 4, 6): 1, 2, 3, 4, 6. Standard: 5, 7. Haiku: 8, 9 docs.

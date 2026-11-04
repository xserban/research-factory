# Regions A: Rules, Evaluation, Snapshots, Review and Foci — Implementation Plan (slice 3d)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Import-A is merged first in the build order, so Task 2 adds the `import` rule kind. Gates `regions.review` and `regions.member_decide` are declared as slice-M decision gates (floor `human`) in `services/modules/regions.py` (kind `proposal`). Bumps `PROJECTION_VERSION` by one from the value it finds; Task 6's scale test stays in this task.

> **Dependencies.** Slice 3b plans G2-C and G2-D merged (ideas, relations, `graph_edges`, `lineage/paths.py` neighbour-lookup helpers, `GraphFilter`); slice 3c plan G3-B merged (concepts, `concept_uses`). Import-A optional (the `import` rule kind, Task 2, is added only if `import_records` exists; else Import-C adds it). Regions-B and Regions-C consume this plan's Interfaces. Every earlier test passes unchanged except the `PROJECTION_VERSION` pin.

**Goal:** Let a human or an agent define a region (or a focus bound to a question slot) by typed rules, evaluate the rules deterministically and within bounds over the index, pin the result as a hashed version `R@`, report drift, and let a human review each version.

**Architecture:** Pure rule models and canonical hashing in `factory/regions/` (`rules.py`, `version.py`); evaluation in `regions/evaluate.py`, one evaluator per rule kind taking an SQLAlchemy connection and writing into a temporary table, combined by set algebra in SQL; services in `services/regions.py`; projection in `index/regions.py`. Snapshots store the member set as a deterministic gzip blob. The evaluation is a builder in the sense of `docs/10-abstractions.md` §3.7 and moves behind the slice-M builder contract when it lands.

**Tech Stack:** as slice 3b; standard-library `gzip` with `mtime=0`.

**Spec:** `docs/specs/slice-3d-regions-import.md` rulings 1–8, 26; acceptance 1–5, 17 (region part).

## Rulings made in this plan

1. **Canonical rule form.** A rule is canonicalised by sorting list parameters, dropping defaults, and serialising with `canonical_json`; the rule set is `{"include": sorted, "exclude": sorted, "within": rule | null}` by canonical text. `rules_hash = sha256(canonical_json(rule set))`.
2. **Version hash.** `R@` = first 8 hex digits of `sha256(canonical_json({"region": region_id, "kind", "facet", "rules_hash", "decisions": sorted decision event ids in effect, "members_hash"}))`. `members_hash = sha256` of the uncompressed member text (one `type\tid` line per member, sorted). The definition text, name and author are not hashed (spec ruling 1).
3. **Evaluation scope.** `corpus` rules read final outcomes through `final_outcomes(project, stage=...)`, cached into a temporary table once per evaluation. `lineage`, `idea`, `concept` read the slice-3b/3c projections with their default status filters (stated and confirmed; reviewed, approved concepts) and apply idea and concept merges at read time as `services/lineage.py` does. Work members are mapped to canonical ids through `active_merges`.
4. **Bounds.** `REGION_MAX_MEMBERS = 200_000` per rule result and per region; a `lineage` rule whose traversal reports `truncated` refuses; the refusal is a `FactoryValidationError` naming `rules.include[i]` (or `exclude`, `within`) with reason `over-bound` and the count reached; nothing is written.
5. **Snapshot actor.** Any actor may take a snapshot (deterministic). An agent snapshot carries provenance (model, skill, `input_blob` = the region id and the definition event id).
6. **Focus.** `kind = focus` requires `facet = (question_id, slot)`; the slot must exist in that `Q@`'s `QuestionSpec.slots`; a second live focus on the same `(question lineage, slot)` is refused.

## Global Constraints

- The platform never calls a model; the projector alone writes the index; services compute live membership on read.
- No full-graph load: every evaluator issues indexed SQL and bounded frontier expansions (G2-D scale ruling).
- Region tables are separate from evidence, graph and layer tables; no evidence module imports `factory.regions` or `services.regions` (architecture test lands in Regions-C).
- Seed status, held-out status and pass internals are not selectable; no rule kind reads `seeds` or `screening_passes` tables.
- `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff pass; coverage ≥ 90% for `services/` and `model/`.

## Review Focus

1. Reordering rules leaves `R@` unchanged; editing the definition text leaves `R@` unchanged; adding one included work changes it (Task 3, `test_version_hash_sensitivity`).
2. A `lineage` rule that the G2-D traversal truncates refuses the snapshot and writes nothing (Task 2, `test_truncated_lineage_refuses`).
3. A rule over a pinned `R@` ignores that region's later snapshot (Task 2, `test_region_rule_reads_pinned_version`).
4. No evaluator query touches a seed or pass table (Task 2, `test_no_seed_tables_read`, an SQL-capture test).

## File Structure

- Create `regions/__init__.py`, `regions/rules.py`, `regions/version.py`, `regions/evaluate.py`; `model/regions.py`; `services/regions.py`; `index/regions.py`.
- Modify `events/catalog.py`, `index/default.py`, `cli/main.py`, `cli/render.py`.
- Tests: `test_region_rules.py`, `test_region_evaluate.py`, `test_region_snapshot.py`, `test_region_review.py`, `test_region_focus.py`, `test_cli_regions.py`, `test_region_scale.py` (`slow`); helper `tests/region_helpers.py` (a G2-ready project with included works, `cites` links, stated relations, a confirmed idea and an approved concept, built with the G2/G3 helpers).

---

### Task 1: Rule models and canonical form

*Tier: critical (hash basis).*

**Files:** Create `regions/rules.py`, `regions/version.py`; Test `tests/test_region_rules.py`.

**Interfaces:**
- Produces (`regions/rules.py`): `MemberType(StrEnum)`: `WORK = "work"`, `IDEA = "idea"`, `CONCEPT = "concept"`; rule models (`StrictModel`, discriminator `kind`): `CorpusRule(outcome: Literal["included", "screened", "all"], stage: ScreeningStage = TA)`, `RunRule(run_id: str | None, query_id: str | None)` (exactly one), `ImportRule(import_id: str, part: Literal["development", "all"] = "development")`, `LineageRule(node: str, direction: Literal["ancestors", "descendants"], depth: int, edge_types: tuple[Literal["builds-on", "improves-on"], ...] = ("builds-on", "improves-on"), include_inferred: bool = False)`, `CitesRule(base: str, direction: Literal["citing", "cited"], min_k: int = 1)` (`base` matches `REGION_VERSION_RE = r"^R@[0-9a-f]{8}$"`), `IdeaRule(idea_id: str)`, `ConceptRule(concept_id: str)`, `TermRule(term_id: str)` (accepted by the model; refused by evaluation until Regions-C), `RegionRule(version: str)`, `TextRule(blocks: tuple[tuple[str, ...], ...])` (1–8 blocks of 1–20 terms); `Rule = Annotated[Union[...], Field(discriminator="kind")]`; `class RuleSet(StrictModel)`: `include: tuple[Rule, ...]` (min 1), `exclude: tuple[Rule, ...] = ()`, `within: Rule | None = None`.
- Produces (`regions/version.py`): `canonical_rules(rules: RuleSet) -> JsonValue`; `rules_hash(rules: RuleSet) -> str`; `members_text(members: Iterable[tuple[MemberType, str]]) -> bytes`; `members_hash(text: bytes) -> str`; `compress(text: bytes) -> bytes` (gzip, `mtime=0`, level 9); `region_version(region_id: str, kind: str, facet: Facet | None, rules_hash: str, decisions: Sequence[str], members_hash: str) -> str`.

- [ ] **Step 1: Tests.** `test_rule_discriminator_round_trip`, `test_lineage_depth_bounds` (1..`MAX_DEPTH`), `test_run_rule_exactly_one`, `test_text_rule_bounds`, `test_canonical_order_independent`, `test_defaults_dropped_from_canonical`, `test_compress_deterministic` (two calls byte-identical), `test_version_ignores_definition` (signature has no text parameter; meta-assert).
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(regions): rule models and canonical hashing`.

### Task 2: Evaluators

*Tier: critical (membership correctness, scale).*

**Files:** Create `regions/evaluate.py`; Test `tests/test_region_evaluate.py`.

**Interfaces:**
- Consumes: `final_outcomes`, `active_merges`, `lineage/paths.py` neighbour-lookup traversal (`ancestors`/`descendants` taking a lookup function; G2-D ruling 10), `graph_edges`, `ideas`, `idea_members`, `concept_uses`, `region_snapshots` (Task 3; for `RegionRule` and `CitesRule.base`, the member blob of the pinned version), `import_records` (if present).
- Produces: `REGION_MAX_MEMBERS = 200_000`; `@dataclass(frozen=True) Evaluation(members: tuple[tuple[MemberType, str], ...], basis: Mapping[tuple[MemberType, str], tuple[int, ...]], counts: Mapping[MemberType, int])`; `evaluate(conn: Connection, project: Project, rules: RuleSet, *, adds: Sequence[tuple[MemberType, str]] = (), removes: Sequence[tuple[MemberType, str]] = ()) -> Evaluation`; raises `FactoryValidationError` per ruling 4. Members sorted by (type, id).

- [ ] **Step 1: Tests.**
```python
def test_corpus_included(region_project): assert ids(evaluate(..., RuleSet(include=(CorpusRule(outcome="included"),)))) == region_project.included
def test_lineage_ancestors_stated_only(region_project): ...   # inferred edge not followed unless include_inferred
def test_truncated_lineage_refuses(big_lineage): ...           # Review Focus 2
def test_cites_min_k(region_project): ...                      # works citing >= 2 members of base
def test_region_rule_reads_pinned_version(region_project): ... # Review Focus 3
def test_idea_rule_includes_idea_node_and_members(...): ...
def test_concept_rule_stated_or_confirmed_uses(...): ...
def test_text_rule_and_of_ors(...): ...
def test_exclude_and_within(...): ...
def test_human_adds_and_removes_override(...): ...
def test_merged_work_maps_to_canonical(...): ...
def test_basis_lists_rule_indices(...): ...
def test_term_rule_refused_until_regions_c(...): ...
def test_no_seed_tables_read(region_project, sql_capture): ...  # Review Focus 4
```
- [ ] **Step 2–5:** Run, FAIL; implement (temporary tables `_rm_<i>`; `INSERT … SELECT` per rule; combination by `UNION`/`EXCEPT`/`INTERSECT`); tests, mypy, ruff; commit `feat(regions): deterministic bounded rule evaluation`.

### Task 3: Definitions, snapshots and drift

*Tier: critical.*

**Files:** Create `model/regions.py`, `services/regions.py`, `index/regions.py`; modify `events/catalog.py`, `index/default.py`; Test `tests/test_region_snapshot.py`.

**Interfaces:**
- Produces (`model/regions.py`): ids `REGION_ID_RE = r"^reg_[0-9A-HJKMNP-TV-Z]{26}$"`, `REGION_VERSION_RE`; `RegionKind(StrEnum)`: `FOCUS`, `REGION`; `class Facet(StrictModel)`: `question_id`, `slot`; `class RegionDefined(StrictModel)`: `region_id`, `kind`, `facet: Facet | None`, `name` (1–120), `definition` (1–600, `REGION_DEFINITION_MAX_CHARS = 600`), `rules: RuleSet`, `supersedes: str | None` (previous definition event id), `author: Literal["agent", "human"]`; `class RegionSnapshotTaken(StrictModel)`: `region_id`, `version`, `definition_event`, `rules_hash`, `decisions: tuple[str, ...]`, `members_blob`, `members_hash`, `basis_blob`, `counts: dict[MemberType, int]`, `as_of: str` (event id).
- Produces (`services/regions.py`): `define_region(project, actor, *, kind, name, definition, rules, facet=None, region_id=None) -> str` (new region, or a new definition of `region_id`); `snapshot_region(project, actor, region_id) -> str` (returns `R@`; idempotent: an unchanged evaluation returns the existing version and writes nothing); `class RegionState(StrictModel)`: `region_id`, `kind`, `name`, `latest_version`, `review_state`, `live_counts`, `drift_added: int`, `drift_removed: int`, `definition_author`; `region_state(project, region_id) -> RegionState`; `region_members(project, version, *, offset=0, limit=500) -> list[tuple[MemberType, str]]` (from the projection for latest versions, else from the blob).
- Projection: `regions`, `region_definitions`, `region_snapshots`, `region_members(region_id, version, member_type, member, basis)` for the latest version per region only; index on `member`.
- `as_of` accessor: `Index.last_event_id() -> str | None` (added to `index/index.py` if absent: the greatest folded event id).

- [ ] **Step 1: Tests.** `test_version_hash_sensitivity` (Review Focus 1), `test_snapshot_idempotent`, `test_drift_after_new_inclusion`, `test_projection_keeps_latest_only`, `test_old_version_members_from_blob`, `test_rebuild_identical`, `test_agent_definition_has_provenance`, `test_definition_too_long_refused`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(regions): definitions, snapshots and drift`.

### Task 4: Review

*Tier: critical (R-51).*

**Files:** Modify `model/regions.py`, `services/regions.py`, `index/regions.py`; Test `tests/test_region_review.py`.

**Interfaces:**
- Produces: `class RegionReviewed(StrictModel)`: `version`, `state: Literal["reviewed", "wrong"]`, `note: str | None` (required for `wrong`), `self_reviewed: bool`; `review_region(project, actor, version, state, note=None) -> None` (human only; refused when the reviewer is the definition's human author and another human has acted in the project, else `self_reviewed = True`, slice-3c ruling 8); `review_state(project, version) -> Literal["unreviewed", "reviewed", "wrong", "superseded"]` (`superseded` when a later version of the region exists).

- [ ] **Step 1: Tests.** `test_agent_cannot_review`, `test_wrong_needs_note`, `test_self_review_flagged`, `test_repeat_review_supersedes`, `test_new_snapshot_supersedes_old_version_state`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(regions): human review of region versions`.

### Task 5: Foci

*Tier: standard.*

**Files:** Modify `services/regions.py`; Test `tests/test_region_focus.py`.

**Interfaces:**
- Consumes: question projection (`QuestionSpec.slots`, `Q@` lineage via `supersedes`).
- Produces: focus validation in `define_region` (ruling 6); `foci(project) -> list[RegionState]`; `focus_slot_missing(project) -> list[str]` (region ids whose slot is absent from the current `Q@`).

- [ ] **Step 1: Tests.** `test_focus_needs_existing_slot`, `test_second_focus_on_slot_refused`, `test_focus_slot_missing_after_question_change`, `test_region_kind_needs_no_facet`.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(regions): foci bound to question slots`.

### Task 6: CLI and scale test

*Tier: standard.*

**Files:** Modify `cli/main.py`, `cli/render.py`; Test `tests/test_cli_regions.py`, `tests/test_region_scale.py` (`slow`).

**Interfaces:** `factory regions define --name N --kind focus|region [--facet Q@x:slot] --definition TEXT --rules FILE.json`, `factory regions revise REG …`, `factory regions snapshot REG`, `factory regions review R@ --reviewed|--wrong [--note]`, `factory regions list`, `factory regions show REG|R@ [--members] [--offset --limit]`, `factory regions diff R@a R@b`.

- [ ] **Step 1: Tests.** `test_cli_define_and_snapshot`, `test_cli_review_human_actor`, `test_cli_diff_counts`; `test_region_scale` (`slow`): a synthetic index of 50,000 works, 500,000 `cites` and 20,000 lineage edges built directly in the tables (G2-D scale fixture); a `lineage` rule at `MAX_DEPTH` and a `cites` rule with `min_k = 2` over a 1,000-member base evaluate within 5 s each, and peak Python memory (tracemalloc) stays below 200 MB.
- [ ] **Step 2–5:** Run, FAIL; implement; tests, mypy, ruff; commit `feat(cli): factory regions`.

**Verification for the plan:** `cd platform && uv run pytest -m "not network and not slow" && uv run pytest -m slow tests/test_region_scale.py && uv run mypy --strict src && uv run ruff check`.

## Later (not v1)

None: every task of this plan is in v1.

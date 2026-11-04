# Outline, Drafts, Supports and Write-Time Checks Implementation Plan (slice 7b, sub-plan W-A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Status: draft — rulings recommended; awaiting the researcher's review before any build.

> **Dependencies.** V-B merged (`group_index`, `rows_of_group`, `view_meta`, `Index.head`). Plans D and 2E (`live_claims`, `final_rows`, `group_id`, `numbers_in`, `CITATION_PATTERNS`), G1 (`surname_key`), G2-A–E (contribution rows, relations, ideas, `RelationView.effective`, `no_stated_base`, trace kinds), G3-A–C (interpretation and concept review states, the separation architecture test) merged. W-B consumes this plan's Interfaces exactly. When slice M lands, drafting becomes an authoring module whose quality regime is W-B's verifier; no event changes.

**Goal:** Let Claude (or a human) write a draft sentence by sentence against a deterministic outline of verified material, where every sentence declares a class and typed supports, and the platform refuses ineligible supports, unsupported numbers and malformed sentences and flags risky wording, all recorded as events with provenance.

**Architecture:** `model/drafts.py` defines ids, classes, supports and event payloads. `services/supports.py` resolves a support reference to its eligibility, works, spans, numbers and groups by calling the owning services (extraction, evidence groups, lineage, interpretations). `writing/stats.py` is the closed registry of `stat` kinds; `writing/checks.py` holds the pure lexical checks. `services/outline.py` builds the outline; `services/drafts.py` creates drafts, serves slots (`draft_next`, a leased task with `input_blob`) and records sentences with partial acceptance. `index/drafts.py` projects. `mcp/`, `cli/` parse and format.

**Tech Stack:** as plans D/2E; no new dependency.

**Spec:** `docs/specs/slice-7b-views-writing.md` rulings 8–11, 15, 16, 25; acceptance 5, 6, 9 (staleness inputs). R-04, R-42, R-44, R-45, R-51; decision 41.

## Rulings made in this plan
1. **Ids.** `drf_<ULID>` drafts, `snt_<ULID>` sentences, `sec_<nn>` section ids local to a draft, outline `OL@<sha8>` = first 8 hex of sha256 of the outline's canonical JSON (V-A `to_json`). The outline JSON is stored as a text blob on `draft.created` (ids only, no quote text).
2. **Support grammar [confirm].** `claim:clm_…`, `cell:rk_…/<field>` (bare `rk_…` means `value`), `item:<contribution row id>`, `edge:rel_…` or `edge:cit:<rex>:<n>`, `group:grp_…`, `stat:<kind>:<arg>[:<arg>]`, `interp:int_…` or `interp:cpt_…`. A support is eligible when: claim live, pass A, work `INCLUDED`, unit not stale; cell in a current final row (`rows_of_group` membership) of an included work; item live and final (G2-B); edge effective status `stated` or `confirmed`; group exists; stat kind registered and its arguments resolve; interp `reviewed` (G3) and only on `interpretive` sentences. Every refusal reason is one of `unknown`, `superseded`, `stale`, `not-included`, `not-final`, `inferred`, `rejected`, `unreviewed`, `class-not-allowed`.
3. **Stat registry v1 [confirm].** `group-works:<grp>`, `group-independent:<grp>`, `group-rows:<grp>`, `idea-members:<ida>`, `ideas-confirmed`, `included-works`, `prisma:<field>` (fields of `PrismaFlow` and `included_in_review`), `records:<grp>:<year>`, `not-stated-count`. Each returns an `int`; the value at write time is stored in `stat_values`. New kinds need a new registry version (`STATS_VERSION`, recorded on the sentence).
4. **Number check (spec ruling 11) [confirm].** Tokens from `numbers_in(text)`; a token is supported when its `Decimal` equals a number token in any support span (claim quote, cell quote, item quote, edge basis quote), the canonical value of a cited cell (compared after the cell's unit canonicalisation and also as printed), a stored stat value, or the publication year of a support work. Percent forms `85.2%` and `85.2` are equal; nothing else is normalised. Unsupported → refusal `number-unsupported` naming the token position (not its text).
5. **Single sentence.** Refused when, after masking abbreviations (`et al.`, `e.g.`, `i.e.`, `cf.`, `Fig.`, `Eq.`, `vs.`, single capital initials), the text has a `.`, `?` or `!` followed by whitespace and an uppercase letter or digit. `SENTENCE_MAX_CHARS = 400`; `MAX_SUPPORTS = 6`.
6. **Structural sentences.** Refused when they contain a number token, a `CITATION_PATTERNS` match, a first-author surname of any work supporting any live sentence of the draft followed within 20 characters by a 4-digit year, or the normalised `method_name` of any cell support in the draft.
7. **Flags (stored, not refusals).** `citation-mismatch`, `quantifier-without-statistic` (closed list `QUANTIFIERS`, word-boundary, case-insensitive), `cross-group` (a comparative `better|worse|outperform\w*|higher|lower|faster|slower|best|worst` with cell supports from more than one group), `single-source-generalisation` (`synthesis` whose supports come from one work), `off-outline` (a support absent from the pinned outline).
8. **Slots.** An outline section is a slot. `draft_next` serves the next section of the draft that has no live sentence, or a named section; the task content lists the section's supports with their spans (quotes from extraction events, cell value and quote, edge basis quote, stat value) and is stored as `input_blob`. Draft sentences outside a slot task are allowed (human CLI) and carry `task_id = None`.
9. **Separation (G3).** `services/supports.py` is added to the G3 architecture test's allowed importers of `services/interpretations.py`; no evidence output imports `services/drafts.py` or `services/supports.py` (the architecture test gains this rule).

## Global Constraints
- The platform never calls a model and never writes prose; the outline holds ids only.
- Sentence events carry no quote text; quotes enter task content (blob) and renderings only, read from existing extraction events (R-47: no library read).
- Invalid input writes nothing and returns structured errors without document text; batches accept partial success.
- Every agent-written event carries model, skill reference (`rf-write@<hash>`) and `input_blob` (R-04).
- Tools refused to pass sessions (decisions 37, 43, 48); a session that has verified any sentence of a draft (W-B) cannot write in it (checked here once W-B's table exists; this plan reserves the check function).
- TDD; `uv run pytest -m "not network and not slow"`; `mypy --strict`; ruff; coverage ≥ 90%.

## Review Focus
1. A sentence with one ineligible support among valid ones is refused whole; another valid sentence in the same batch is written (Task 5, `test_partial_acceptance_per_sentence`).
2. The number check accepts `85.2` against a quote "85.2 %" and refuses `85.3` (Task 3, `test_number_check`).
3. A structural sentence naming "Performer (2021)" is refused (Task 3, `test_structural_refusals`).
4. Outline determinism: identical `OL@` after rebuild; method conflicts appear as slots (Task 4, `test_outline_deterministic`, `test_conflicts_are_slots`).
5. No quote text in any `draft.*` event or in the outline blob (Task 5, `test_no_quote_text_in_events`).

## File Structure
- Create `model/drafts.py`, `writing/__init__.py`, `writing/stats.py`, `writing/checks.py`, `services/supports.py`, `services/outline.py`, `services/drafts.py`, `index/drafts.py`, `plugin/skills/rf-write/SKILL.md`.
- Modify `index/default.py` (register handlers), `events` catalog registration (as other plans), `mcp/server.py`, `cli/main.py`, the G3 architecture test.
- Tests: `tests/test_drafts_model.py`, `tests/test_supports.py`, `tests/test_writing_checks.py`, `tests/test_writing_stats.py`, `tests/test_outline.py`, `tests/test_drafts_service.py`, `tests/test_drafts_projection.py`, `tests/test_drafts_cli_mcp.py`.

### Task 1: Model and events

*Tier: critical (event schemas).*

**Files:** Create `model/drafts.py`; Modify the event catalog; Test `tests/test_drafts_model.py`.

**Interfaces:**
- Produces: `DRAFT_ID_RE = rf"^drf_{ULID_RE}$"`, `SENTENCE_ID_RE`, `OUTLINE_ID_RE = r"^OL@[0-9a-f]{8}$"`; `class SentenceClass(StrEnum): CLAIM, SYNTHESIS, INTERPRETIVE, STRUCTURAL`; `class DraftKind(StrEnum)` (spec events table); `class SupportKind(StrEnum): CLAIM, CELL, ITEM, EDGE, GROUP, STAT, INTERP`; `class SupportRef(StrictModel): kind: SupportKind; ref: str` with `parse_support(s: str) -> SupportRef` (ruling 2 grammar); `class SentenceFlag(StrEnum)` (ruling 7); payloads `DraftCreated(draft_id, title, kind, outline_ref, outline_blob, sections: list[SectionDef])`, `SectionDef(section_id, heading, outline_section: str | None)`, `DraftOutlineRepinned`, `SentenceRecorded(sentence_id, draft_id, section_id, order: int, cls, text, supports: list[SupportRef], stat_values: dict[str, int], stats_version: int, flags: list[SentenceFlag], author: Literal["agent", "human"], task_id: str | None, supersedes: str | None)`, `SentenceWithdrawn(sentence_id, reason)`, `DraftReordered(draft_id, section_id, order: list[str])`; event types `draft.created`, `draft.outline_repinned`, `draft.sentence_recorded`, `draft.sentence_withdrawn`, `draft.reordered` (schema 1).

- [ ] **Step 1: Tests.** `test_parse_support_grammar` (each kind; bare `rk_` → field `value`; malformed → `ValueError`); `test_text_bounds` (> 400 chars invalid); `test_supports_bounds` (> 6 invalid); `test_structural_has_no_supports`; `test_catalog_registers_types`; `test_agent_event_requires_provenance` (envelope rule holds for `draft.sentence_recorded`).
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): draft and sentence models and events`.

### Task 2: Support resolution and stat registry

*Tier: critical (eligibility is the boundary between verified and unverified material).*

**Files:** Create `services/supports.py`, `writing/stats.py`; Test `tests/test_supports.py`, `tests/test_writing_stats.py`.

**Interfaces:**
- Consumes: `live_claims`, plan-D unit staleness, `final_outcomes`/`included_works`, `rows_of_group`/`group_index`, G2-B contribution final rows, G2-C `RelationView.effective`, G2-D cites edges, G3 `interpretation` and concept review state, `prisma_flow`, V-B `timeline_view`.
- Produces (`writing/stats.py`): `STATS_VERSION = 1`; `STAT_KINDS: tuple[str, ...]`; `compute_stat(project: Project, kind: str, args: Sequence[str]) -> int` (ruling 3; unknown → `FactoryValidationError` field `supports`, reason `unknown`).
- Produces (`services/supports.py`): `@dataclass(frozen=True) ResolvedSupport(ref: SupportRef, eligible: bool, reason: str | None, work_ids: tuple[str, ...], spans: tuple[str, ...], numbers: tuple[Decimal, ...], group_ids: tuple[str, ...], stat_value: int | None, first_authors: tuple[str, ...], years: tuple[int, ...], method_names: tuple[str, ...])`; `resolve_supports(project: Project, refs: Sequence[SupportRef], *, cls: SentenceClass) -> list[ResolvedSupport]` (batched per kind; no library read).

- [ ] **Step 1: Tests.** One test per eligibility rule and refusal reason of ruling 2 (`test_superseded_claim_refused`, `test_claim_of_excluded_work_refused`, `test_inferred_edge_refused`, `test_unreviewed_interp_refused`, `test_interp_only_for_interpretive`, `test_cell_not_final_refused`, …); `test_cell_numbers_include_canonical_and_printed`; `test_stat_values` (each kind against hand counts); `test_resolution_reads_no_library` (library read patched to raise).
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): support resolution and stat registry`.

### Task 3: Pure write-time checks

*Tier: critical.*

**Files:** Create `writing/checks.py`; Test `tests/test_writing_checks.py`.

**Interfaces:**
- Consumes: `numbers_in`, `parse_printed` (`extraction/numbers.py`), `CITATION_PATTERNS` (`packs/ml_benchmark.py`), `surname_key` (`references/match.py`), `ResolvedSupport`.
- Produces: `QUANTIFIERS: tuple[str, ...]`; `COMPARATIVES: tuple[str, ...]`; `@dataclass(frozen=True) CheckOutcome(refusals: tuple[ValidationIssue, ...], flags: tuple[SentenceFlag, ...])`; `check_sentence(text: str, cls: SentenceClass, supports: Sequence[ResolvedSupport], *, draft_context: DraftContext, outline_refs: frozenset[str]) -> CheckOutcome`; `DraftContext(first_authors: frozenset[str], method_names: frozenset[str])`.

- [ ] **Step 1: Tests.**
```python
def test_number_check():                                          # Review Focus 2
    s = sup(spans=("reaches 85.2 % top-1",))
    assert not check_sentence("X reaches 85.2% top-1 accuracy", CLAIM, [s], ...).refusals
    assert check_sentence("X reaches 85.3% top-1 accuracy", CLAIM, [s], ...).refusals[0].reason == "number-unsupported"
def test_year_of_support_work_allowed(): ...
def test_stat_value_supports_number(): ...
def test_two_sentences_refused(): ...                              # "A works. B fails."
def test_abbreviations_do_not_split(): ...                         # "Katharopoulos et al. show …", "e.g. Performer"
def test_structural_refusals(): ...                                # Review Focus 3: number, citation, "Performer (2021)", method name
def test_interpretive_without_numbers(): ...
def test_claim_needs_support_synthesis_needs_stat_or_group(): ...
def test_citation_mismatch_flag(): ...                             # "Choromanski et al. (2021)" with supports by Katharopoulos only
def test_quantifier_flag_and_stat_clears_it(): ...
def test_cross_group_flag(): ...
def test_single_source_generalisation_flag(): ...
def test_off_outline_flag(): ...
def test_no_text_in_issues(): ...                                  # issue messages carry positions, not sentence or quote text
```
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): deterministic write-time sentence checks`.

### Task 4: Outline builder

*Tier: standard.*

**Files:** Create `services/outline.py`; extend `model/drafts.py`; Test `tests/test_outline.py`.

**Interfaces:**
- Consumes: G2 confirmed ideas, members, idea edges (derived, G2-D ruling 7), contribution items by work, `group_index`, `rows_of_group`, the 2E conflict computation (`method_conflicts` of `evidence_report`; this task calls the evidence-report builder once per group through a new public `group_conflicts(project, group_id) -> list[MethodConflict]` added to `services/evidence_report.py` with a behaviour-preserving test), `live_claims`, 2E `limits`, G2-D `no_stated_base`.
- Produces (`model/drafts.py`): `OutlineSection(section_ref: str, kind: Literal["idea", "group", "claims", "limits"], title_ref: str, supports: list[str], conflicts: list[list[str]], notes: list[str])` (`notes` are platform codes, never prose); `Outline(outline_id, scope: dict[str, JsonValue], as_of, sections)`.
- Produces (`services/outline.py`): `OutlineScope(works: Literal["included"] | tuple[str, ...] = "included", ideas: tuple[str, ...] | None = None, groups: tuple[str, ...] | None = None)`; `build_outline(project: Project, scope: OutlineScope = OutlineScope()) -> Outline`; `outline_json(outline) -> str`.

- [ ] **Step 1: Tests.** `test_idea_sections_in_lineage_order` (topological, ties by origin date then id); `test_group_sections_need_two_works`; `test_conflicts_are_slots` (Review Focus 4); `test_unattached_claims_by_type`; `test_limits_section_lists_codes`; `test_outline_deterministic` (same `OL@` after rebuild; Review Focus 4); `test_outline_has_no_quote_text`; `test_scope_restricts_sections`; `test_cycle_in_idea_edges_broken_by_id` (a cycle cannot occur in stated edges, but the order is defined anyway).
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): deterministic outline of verified material`.

### Task 5: Projection and drafts service

*Tier: critical (partial acceptance, provenance).*

**Files:** Create `index/drafts.py`, `services/drafts.py`; Modify `index/default.py`; Test `tests/test_drafts_projection.py`, `tests/test_drafts_service.py`.

**Interfaces:**
- Produces (tables): `drafts`, `draft_sections`, `draft_sentences` (`sentence_id`, `draft_id`, `section_id`, `ord`, `cls`, `text`, `author`, `session`, `model`, `superseded_by`, `withdrawn`, `event_id`), `sentence_supports` (`sentence_id`, `kind`, `ref`; index on `ref`), `sentence_flags`, `sentence_stats`.
- Produces (`services/drafts.py`): `create_draft(project, *, title: str, kind: DraftKind, scope: OutlineScope, actor: Actor) -> str`; `repin_outline(project, draft_id, scope) -> str`; `SentenceInput(section_id: str, order: int | None, cls: SentenceClass, text: str, supports: list[str], supersedes: str | None = None)`; `write_sentences(project, draft_id, items: Sequence[SentenceInput], *, actor: Actor, input_blob: str | None, task_id: str | None) -> BatchResult[str]`; `withdraw(project, sentence_id, reason, actor) -> str`; `reorder(project, draft_id, section_id, order: Sequence[str], actor) -> str`; `draft_next(project, draft_id, *, section_id: str | None = None, actor: Actor) -> SlotTask | None` (creates a leased task, stores content as `input_blob`); `live_sentences(project, draft_id) -> list[SentenceRow]`; `verifier_sessions(project, draft_id) -> frozenset[str]` (empty until W-B; used by the independence check).

- [ ] **Step 1: Tests.** `test_partial_acceptance_per_sentence` (Review Focus 1); `test_supersede_marks_old_and_keeps_order`; `test_withdraw_and_reorder`; `test_slot_task_content_has_spans_and_is_input_blob`; `test_no_quote_text_in_events` (scan every `draft.*` payload and the outline blob for every stored quote; Review Focus 5); `test_pass_session_refused`; `test_human_sentence_has_no_model`; `test_rebuild_identical_tables`; `test_off_outline_after_repin`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): drafts, slots and sentence recording`.

### Task 6: MCP tools, CLI and skill `rf-write`

*Tier: standard.*

**Files:** Modify `mcp/server.py`, `cli/main.py`; Create `plugin/skills/rf-write/SKILL.md`; Modify the G3 architecture test (ruling 9); Test `tests/test_drafts_cli_mcp.py`.

**Interfaces:**
- MCP: `writing_outline(project, scope_works: list[str] | None = None, ideas: list[str] | None = None, groups: list[str] | None = None) -> dict` (read); `draft_create(project, title, kind, ...) -> {"draft_id"}`; `draft_next(project, draft_id, section_id: str | None = None) -> dict | None`; `draft_write(project, draft_id, task_id: str | None, sentences: list[dict]) -> BatchResult`; `draft_status(project, draft_id) -> dict` (sentences with class, flags; status is W-B's; until then `unchecked`).
- CLI: `factory draft create --title --kind [--idea ID]… [--group ID]…`, `factory draft list|show DRAFT`, `factory draft write DRAFT --section S --class C --text T --support REF…` (human author), `factory draft withdraw SENTENCE --reason`, `factory outline [--json]`.
- Skill `rf-write`: one sentence per call item; choose the class; cite only supports shown in the slot; never type citations or numbers not in a span; prefer `synthesis` with a `stat` for any count or "most"; state disagreement where the slot lists conflicts; write "the corpus does not support …" sentences from the limits slot.

- [ ] **Step 1: Tests.** Tool list pinned; each mutating tool refused to pass sessions; structured errors for unknown draft or section; CLI human write produces `author = human`; the architecture test fails when an evidence service imports `services/drafts.py`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): writing tools, CLI and rf-write skill`.

## Self-review notes
- Status (`supported`, `flagged`, `stale`) is W-B's; this plan computes and stores only refusals and flags.
- `group_conflicts` and `group_direction` (V-B) are promotions of 2E internals with behaviour-preserving tests; the evidence report output is unchanged (2E snapshot test).

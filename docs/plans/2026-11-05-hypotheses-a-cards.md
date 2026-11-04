# Property Vocabulary, Method Cards and Problem Descriptions Implementation Plan (slice 6, sub-plan H-A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** v1 cut: cross-project card import moved to Later; the former Task 5 is Later L1, the former Task 6 is now Task 5, and Review Focus item 4 applies only when the Later task is built. Task 1 still defines the `card.imported` event type (unused in v1). Cards are a `miner` module and the vocabulary a `proposal` module for slice M; `hypotheses.property_approve` and `hypotheses.assertion_confirm` are slice-M gates (floor `human`). Vocabulary scope is the project in v1. Bumps `PROJECTION_VERSION` by one from the value it finds.

> **Dependencies.** Plans 2D and 2E merged (verifiers, `final_rows`, `evidence_report`); slice 3b plans G2-A–G2-C merged (`IdeaView`, `resolve_idea`, `list_ideas`). Slice 3d (regions) is *not* required: the vocabulary scope is the project until 3d lands (spec ruling 4); Task 1 keeps a `scope` field so a region scope can be added without a new event type. This plan ends with every earlier test passing unchanged except the projection-version pin.

**Goal:** Let the researcher approve a typed property vocabulary, and let Claude draft method cards (for confirmed lineage ideas or works) and problem descriptions (for the project's question) as sets of property assertions, each verified against a quote or an evidence row or marked inferred until a human confirms; cards can be imported from another project with recorded provenance.

**Architecture:** New event families `vocabulary.*` and `card.*` in `model/cards.py`, folded by `index/cards.py` into `properties`, `property_merges`, `cards`, `card_assertions` and the match-oriented `card_props`. `services/properties.py` owns the vocabulary and `V@`; `services/cards.py` validates and classifies assertions with the existing verifiers (`resolve_anchor`, `conversion_document`, `quote_in_element`, `numbers_in`) and the plan-D final rows. Staleness and effective status are computed on read. Decisions are human-only service calls reached only from the CLI.

**Tech Stack:** as plan D; no new dependencies.

**Spec:** `docs/specs/slice-6-hypotheses.md` rulings 4, 5, 8; Design "Property vocabulary", "Method cards and problem descriptions"; events `vocabulary.*`, `card.*`; MCP `vocabulary_propose`, `card_create`, `card_assert`, `card_view`; CLI `vocabulary`, `cards`; acceptance 1–4. `01-rigour.md` R-04, R-26, R-40, R-44, R-51.

## Rulings made in this plan (recommended; [confirm])

1. **Keys.** Property keys match `^pr:[a-z0-9][a-z0-9-]{1,47}$`; enum and set values match `^[a-z0-9][a-z0-9.-]{0,47}$`; aliases are free strings (≤ 80 characters), compared after `normalise_quote` and case folding. [confirm]
2. **`V@`.** `sha256` over the canonical JSON of the live approved definitions sorted by key, with `description` stripped, first 8 hex digits. An empty vocabulary has `V@00000000`. [confirm]
3. **Value checks per kind.** `enum`: value in `allowed`; `set`: non-empty subset of `allowed`, stored sorted; `bool`; `number`: a decimal string with a unit valid for the property's `UnitFamily`, canonicalised by the plan-D unit rules. [confirm]
4. **Quote basis for non-numeric values.** `enum` and `set`: each value, or one of the property's aliases mapped to that value (`PropertyDef.value_aliases: dict[value, tuple[str, ...]]`), must occur in the normalised quote; `bool`: an alias of the property itself must occur (the platform cannot verify negation, so `false` is only accepted with `inferred` or `researcher` basis). [confirm]
5. **Card subjects.** Method card: a confirmed, live lineage idea (resolved through merges) or a work id known to the index; problem description: the current `Q@` or a task name (≤ 120 characters) under it. A subject has at most one live card per kind; a second `card_create` returns the existing id. [confirm]
6. **Audit sample.** Stated `quote` assertions are sampled for human audit with plan-D `audit_size` and `EXTRACTION_ERROR_CEILING`; the sample and labels reuse the plan-D audit events with scope `card` (one new `Scope` member). [confirm] *Alternative:* no audit in this slice, only the check finding on unconfirmed inferred assertions.

## Global Constraints

- The platform never calls a model; agents never set a status, hash or id (input models forbid `status`).
- Every agent-written event carries model, skill reference and `input_blob`; human events carry the human actor.
- Quotes are the only document text in events; no document text in any error or finding.
- Invalid input writes nothing and returns structured errors; batches accept partial success.
- Business logic in `services/`; pure helpers in `factory/hypotheses/`; `mcp/` and `cli/` parse and format.
- TDD; `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff; coverage ≥ 90% for `services/` and `model/`.

## Review Focus

1. An assertion recorded under `V@a` on a property that is later changed (new definition) is `stale` and leaves `card_props`-based views; re-asserting restores it (Task 4, `test_definition_change_stales_assertion`).
2. A `card.assertion_decided` event with an agent actor written by hand does not change the projection (Task 3, `test_projector_ignores_agent_decisions`).
3. A `row` assertion whose evidence row is later re-resolved to another value becomes stale, not silently updated (Task 4, `test_row_basis_follows_final_row`).
4. An imported assertion is stated only when the same conversion is present and the quote re-verifies (Task L1 (Later), `test_import_reverifies_or_labels`).

## File Structure

- Create `model/cards.py`, `index/cards.py`, `services/properties.py`, `services/cards.py`, `services/card_import.py`, `factory/hypotheses/__init__.py`, `factory/hypotheses/values.py`, `plugin/skills/rf-cards/SKILL.md`.
- Modify `events/catalog.py`, `index/default.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`, `model/extraction.py` (`Scope.CARD`), `services/extraction_audit.py` (scope `card` population).
- Tests: `test_cards_model.py`, `test_cards_index.py`, `test_properties.py`, `test_card_values.py`, `test_cards.py`, `test_card_import.py`, `test_mcp_cards.py`, `test_cli_cards.py`; helper `tests/card_helpers.py` (a plan-E project with final rows, one confirmed `ida_` from G2 helpers, an approved four-property vocabulary, builders `prop(...)`, `quote_basis(...)`, `row_basis(...)`).

---

### Task 1: Vocabulary and card events, projection

*Tier: critical (events, index).*

**Files:** Create `model/cards.py`, `index/cards.py`; Modify `events/catalog.py`, `index/default.py`; Test `tests/test_cards_model.py`, `tests/test_cards_index.py`.

**Interfaces:**
- Consumes: `StrictModel`, `ULID_RE`, `UnitFamily`, `CONVERSION_ID_RE`, `QUESTION_ID_RE`, `IDEA_ID_RE`.
- Produces (`model/cards.py`): `PROPERTY_KEY_RE`, `VALUE_RE`, `CARD_ID_RE = rf"^(mcd|pbd)_{ULID_RE}$"`, `ASSERTION_ID_RE = rf"^pas_{ULID_RE}$"`, `VOCAB_VERSION_RE = r"^V@[0-9a-f]{8}$"`; `PropertyKind(StrEnum)`: `ENUM`, `SET`, `BOOL`, `NUMBER`; `MatchRule(StrEnum)`: `EQUAL`, `COVERS`, `AT_MOST`, `AT_LEAST`; `AppliesTo = Literal["method", "problem", "both"]`; `PropertyDef(StrictModel)`: `key`, `kind`, `allowed: tuple[str, ...] = ()`, `unit_family: UnitFamily | None = None`, `match: MatchRule`, `applies_to`, `aliases: tuple[str, ...] = ()`, `value_aliases: dict[str, tuple[str, ...]] = {}`, `scope: str = "project"`, `description: str = ""` (validators: `allowed` non-empty iff kind in {enum, set}; `unit_family` set iff number; `match` compatible with kind: `covers` only for set, `at-most`/`at-least` only for number); `CardKind = Literal["method", "problem"]`; `BasisKind(StrEnum)`: `QUOTE`, `ROW`, `RESEARCHER`, `INFERRED`, `IMPORTED`; `QuoteBasis(work_id, conversion_id, anchor, quote)`, `RowBasis(row_key, field)`, `InferredBasis(note: str ≤ 500, supports: tuple[QuoteBasis, ...] = ())`; `AssertionStatus = Literal["stated", "inferred", "imported-unverified"]`; payloads `PropertyProposed(definition, supersedes: str | None)`, `PropertyDecided(key, decision: Literal["approve", "reject"], rationale)`, `PropertyMerged(from_key, into, reason)`, `PropertyUnmerged(from_key, into, reason)`, `CardCreated(card_id, kind, subject, owner)`, `CardAsserted(assertion_id, card_id, property, value: str | tuple[str, ...] | bool, unit: str | None, canonical: str | None, basis_kind, basis: QuoteBasis | RowBasis | InferredBasis | None, status: AssertionStatus, vocabulary_version, supersedes: str | None, imported_from: str | None)`, `AssertionDecided(assertion_id, decision: Literal["confirm", "reject"], rationale)`, `CardImported(card_id, source_project, source_card_id, source_event_ids: tuple[str, ...])`. Event types `vocabulary.property_proposed`, `vocabulary.property_decided`, `vocabulary.property_merged`, `vocabulary.property_unmerged`, `card.created`, `card.asserted`, `card.assertion_decided`, `card.imported`, schema 1.
- Produces (`index/cards.py`): tables `properties(key pk, definition_json, state proposed|approved|rejected, event_id)`, `property_merges(event_id pk, kind, from_key, into)`, `cards(card_id pk, kind, subject, owner, imported_from, event_id)`, `card_assertions(assertion_id pk, card_id, property, value_json, canonical, basis_kind, basis_json, status, vocabulary_version, supersedes, superseded_by, decision, decision_event_id, event_id)`, `card_props(assertion_id pk, card_id, property_key, value_norm, number_canonical, status)` (one row per set member; indexes `(property_key, value_norm)`, `(card_id)`). Decisions fold only when the actor is human; first-write-wins on ids.

- [ ] **Step 1: Tests.** Model: `test_property_def_kind_rules` (enum without `allowed` rejected; `covers` on number rejected), `test_assertion_input_forbids_status`, `test_inferred_basis_needs_note`, `test_card_id_prefix_matches_kind` (`mcd_` with kind problem rejected). Index: `test_supersession_sets_superseded_by`, `test_projector_ignores_agent_decisions`, `test_set_values_expand_to_card_props`, `test_merge_unmerge_fold`, `test_rebuild_state_hash_stable`, `test_projection_version_bumped`.
- [ ] **Step 2:** `uv run pytest -m "not network and not slow" tests/test_cards_model.py tests/test_cards_index.py` — FAIL. **Step 3:** Implement. **Step 4:** Tests pass; full suite; `uv run mypy --strict src`; `uv run ruff check`. **Step 5:** Commit `feat(cards): vocabulary and card events and projection`.

### Task 2: Vocabulary service and `V@`

*Tier: critical (hash).*

**Files:** Create `services/properties.py`; Test `tests/test_properties.py`.

**Interfaces:**
- Consumes: Task 1 models and tables; `strip_prose`.
- Produces: `propose_property(project, actor, definition: PropertyDef, *, supersedes: str | None = None) -> str` (agent or human; refuses a key already approved unless `supersedes` names it: `key`, `exists`); `decide_property(project, actor, key, decision, rationale) -> str` (human only: `actor`, `human-only`); `merge_properties(project, actor, from_key, into, reason) -> str` and `unmerge_property(project, actor, from_key, reason) -> str` (human; kinds must match: `into`, `kind-differs`; cycles refused); `vocabulary_version(project) -> str` (ruling 2); `resolve_property(project, key) -> PropertyDef | None` (follows merges; approved only); `list_properties(project, *, include_proposed: bool = False) -> list[PropertyView]` with `PropertyView(key, definition, state, merged_into, event_id)`.

- [ ] **Step 1: Tests.** `test_agent_proposal_is_unapproved`, `test_human_only_decides`, `test_v_hash_ignores_description` (acceptance 1), `test_v_hash_changes_with_allowed`, `test_empty_vocabulary_hash`, `test_merge_requires_same_kind`, `test_merge_and_unmerge_restore_resolution` (acceptance 1), `test_superseding_definition_replaces_live`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(cards): property vocabulary service and V@ hash`.

### Task 3: Pure value checks

*Tier: standard.*

**Files:** Create `factory/hypotheses/values.py`; Test `tests/test_card_values.py`.

**Interfaces:**
- Consumes: `PropertyDef`, `normalise_quote`, `numbers_in`, plan-D unit canonicalisation (`extraction/numbers.py`).
- Produces: `@dataclass(frozen=True) ValueVerdict(ok: bool, reason: str | None, canonical: str | None, value_norm: tuple[str, ...])`; `check_value(defn: PropertyDef, value: str | Sequence[str] | bool, unit: str | None) -> ValueVerdict` (ruling 3; reasons `value-not-allowed`, `empty-set`, `unit-invalid`, `not-a-number`); `value_in_quote(defn: PropertyDef, value, quote: str) -> bool` (ruling 4; numbers via `numbers_in` with the plan-D equality rule).

- [ ] **Step 1: Tests.** Parametrised `test_check_value` (each kind, valid and invalid); `test_set_is_sorted_and_deduplicated`; `test_number_canonical_matches_plan_d`; `test_enum_alias_in_quote` ("irregularly sampled" alias of `irregular`); `test_bool_false_never_in_quote`; `test_number_in_quote_uses_tokenizer` ("1.2B" and "1,200M" both match `1.2e9` only when the plan-D tokenizer says so).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(cards): pure property value checks`.

### Task 4: Cards and assertions service

*Tier: critical (verification, provenance).*

**Files:** Create `services/cards.py`; Modify `model/extraction.py` (`Scope.CARD`), `services/extraction_audit.py`; Test `tests/test_cards.py`.

**Interfaces:**
- Consumes: Tasks 1–3; `resolve_anchor`, `conversion_document`, `quote_in_element`, `final_rows`, `resolve_idea`, `idea_view`; plan-D `audit_size`.
- Produces: `AssertionInput(StrictModel)`: `property`, `value`, `unit: str | None = None`, `basis_kind: Literal["quote", "row", "researcher", "inferred"]`, `basis: QuoteBasis | RowBasis | InferredBasis | None` (`researcher` only for human actors: `basis_kind`, `human-only`); `create_card(project, actor, kind: CardKind, subject: str, owner: str) -> str` (ruling 5; reasons `subject-unknown`, `idea-not-confirmed`); `AssertResult(accepted: list[tuple[int, str, AssertionStatus]], rejected: list[tuple[int, list[ValidationIssue]]])`; `assert_properties(project, actor, card_id, items: Sequence[AssertionInput]) -> AssertResult` (each item alone: property approved and applicable to the card kind (`property`, `not-applicable`); value checked; `quote` basis: anchor resolves in the conversion, the conversion belongs to the work, quote verbatim, value in quote — else rejected with reasons `anchor-unknown`, `quote-not-verbatim`, `value-not-in-quote`; `row` basis: a final row with the field whose canonical value equals the assertion's — `row-unknown`, `value-differs`; stated or inferred status computed; a live assertion of the same (card, property) is superseded); `decide_assertion(project, actor, assertion_id, decision, rationale) -> str` (human; confirm only inferred or `imported-unverified`); `CardView(card_id, kind, subject, owner, assertions: list[AssertionView], hidden_counts: dict[str, int])`, `AssertionView(assertion_id, property, value, unit, basis_kind, status, effective: Literal["stated", "confirmed", "inferred", "imported-unverified", "stale", "rejected"], stale_reasons: tuple[str, ...], event_id)`; `card_view(project, card_id, *, include_inferred: bool = False) -> CardView | None`; `list_cards(project, kind: CardKind | None = None) -> list[CardSummary]`; `effective_card_props(project, property_keys: Collection[str], statuses) -> Iterator[CardPropRow]` (stream from `card_props`, staleness applied; consumed by H-B). Stale reasons: `definition-changed` (the property's live definition differs from the one in force at `vocabulary_version`), `property-rejected`, `row-changed` (the final row's canonical value differs or the row is gone), `document-superseded` (a newer default conversion of the work exists), `idea-not-live`.

- [ ] **Step 1: Tests.**
```python
def test_quote_assertion_stated(project):                  # acceptance 2-3
    r = assert_properties(project, AGENT, card, [quote_item("pr:sampling", "irregular", quote="irregularly sampled points")])
    assert r.accepted[0][2] == "stated"
def test_rejections_and_partial_acceptance(project):      # acceptance 2
    r = assert_properties(project, AGENT, card, [good, not_verbatim, number_absent, enum_absent])
    assert [i for i, *_ in r.accepted] == [0] and {reason(x) for x in r.rejected} == {"quote-not-verbatim", "value-not-in-quote"}
    assert no_document_text_in(r.rejected)
def test_row_basis_follows_final_row(project): ...          # Review Focus 3
def test_inferred_excluded_until_confirmed(project): ...    # acceptance 3
def test_agent_cannot_confirm(project): ...
def test_researcher_basis_human_only(project): ...
def test_definition_change_stales_assertion(project): ...   # Review Focus 1
def test_new_assertion_supersedes_same_property(project): ...
def test_card_subject_must_be_confirmed_idea(project): ...
def test_card_audit_population_is_stated_quotes(project): ...  # ruling 6
def test_event_provenance(project): ...                     # model, skill, input_blob
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass, including the unedited plan-D audit suite; mypy; ruff. **Step 5:** Commit `feat(cards): verified property assertions, human confirmation, staleness`.

### Task 5: MCP tools, CLI and the `rf-cards` skill

*Tier: Haiku implement and review (surfaces); the skill by Sonnet.*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`, `tests/test_plugin.py`; Create `plugin/skills/rf-cards/SKILL.md`; Test `tests/test_mcp_cards.py`, `tests/test_cli_cards.py`, extend `tests/test_skills.py`.

**Interfaces:**
- MCP: `vocabulary_propose(project, definition: dict, role, model, skill)` -> key; `card_create(project, kind, subject, owner, role, model, skill)` -> card id; `card_assert(project, card_id, items: list[dict], role, model, skill)` -> `AssertResult`; `card_view(project, card_id, include_inferred: bool = False)` -> `CardView`. All refused to screening and extraction pass sessions (`_refuse_pass_session`, `is_extraction_session`). No MCP tool reaches `decide_property`, `merge_properties`, `decide_assertion`, `import_card`.
- CLI: `factory vocabulary list [--all]|approve KEY|reject KEY|merge FROM INTO|unmerge FROM` (each with `--rationale`/`--reason`); `factory cards list [--kind K]|show ID [--inferred]|assert ID --property K --value V [--unit U] --researcher` (human `researcher` basis)`|confirm PAS|reject PAS|import --from SLUG CARD`.
- Skill `rf-cards`: read cards' sources through `document_read`; prefer `row` basis for numbers in the evidence table; one assertion per property; quote the sentence that states the property; record `inferred` only with a note and say so to the researcher; never confirm; propose properties sparingly and only when no approved key fits.

- [ ] **Step 1: Tests.** MCP tool list pinned with the four names and no `*_confirm`, `*_approve`, `*_import`; an extra `status` argument is a structured error; a pass session is refused. CLI: `vocabulary approve` writes a human decision; `cards import` prints counts; `cards show` labels inferred and stale rows. Skill: names the tools and "never confirm"; `SKILLS` includes `rf-cards`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(cards): MCP tools, CLI and rf-cards skill`.

## Self-review notes

- **Spec coverage.** Rulings 4, 5, 8; acceptance 1–3 (Tasks 2, 4) and 4 (Later L1). Matching and its `card_props` reads are H-B.
- **Types used later.** `PropertyDef`, `PropertyKind`, `MatchRule`, `CARD_ID_RE`, `ASSERTION_ID_RE`, `vocabulary_version`, `resolve_property`, `card_view`, `list_cards`, `effective_card_props`, `CardPropRow(card_id, card_kind, subject, property_key, value_norm, number_canonical, effective)`, tables `cards`, `card_props`.
- **Tiers.** Tasks 1, 2, 4 critical; 3 standard; 5 Haiku; Later L1 standard.

## Later (not v1)

Moved here by the v1 cut of 2026-11-04 (decision 74); built after the v1 plans of the build order (`2026-11-05-build-order.md`), in the order listed. Task text is unchanged; references to "Task N" inside a moved task use the plan's original numbering.

### Later L1 (was Task 5): Cross-project card import

*Tier: standard (provenance).*

**Files:** Create `services/card_import.py`; Test `tests/test_card_import.py`.

**Interfaces:**
- Consumes: the source `Project` from `services/context.py::open_project(settings, slug, session=..., clock=...)` (used for reading only), `card_view`, `conversion_document`, `quote_in_element`, Task 4 checks.
- Produces: `ImportResult(card_id, stated: int, unverified: int, skipped: list[tuple[str, str]])`; `import_card(target: Project, actor, source: Project, source_card_id: str) -> ImportResult` (human only; the source card must have stated or confirmed assertions; properties are mapped by key through the target vocabulary: a key unknown or of a different kind in the target is skipped with reason `property-unknown` / `kind-differs`; each copied assertion is written as `card.asserted` with `basis_kind = imported`, `imported_from = "<slug>/<pas_id>"`, and `status = stated` when the conversion id exists in the target and the quote re-verifies, else `imported-unverified`; `inferred` source assertions are never imported; one `card.imported` event lists the source event ids). The source project is read through its index only; nothing is written to it.

- [ ] **Step 1: Tests.** `test_import_reverifies_or_labels` (Review Focus 4; acceptance 4), `test_import_skips_unknown_property`, `test_import_never_copies_inferred`, `test_source_project_unchanged` (state hash before and after), `test_import_is_human_only`, `test_import_records_source_events`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Pass; mypy; ruff. **Step 5:** Commit `feat(cards): recorded cross-project card import`.

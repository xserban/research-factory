# Contribution Pack, `contribution_schema` and Plan-D Generalisation Implementation Plan (slice 3b, sub-plan G2-A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: ready — rulings adopted 2026-11-04; depends on G1 (slice 3a) being built.** G1 ruling 14 is adopted as option (b) (parsed fields plus `entry_sha256`, no raw entry text in events); this plan reads no reference entry text.

> **Dependencies.** Plan D (extraction) and plan E (evidence report) merged; plan G1 (`2026-11-04-references-snowballing.md`) merged, because the contribution population is G1's `included_works` and contribution staleness reads G1's `current_extraction`. Sub-plans G2-B to G2-E consume this plan's Interfaces blocks exactly. This plan ends in a state where every slice-1, slice-2 and G1 test passes unchanged except the `PROJECTION_VERSION` pin.

**Goal:** Make the plan-D extraction machinery serve a second, independent schema (pack `contribution`, declared in a new protocol section `contribution_schema`) without changing anything the evidence table, the evidence report or their tests see.

**Architecture:** A `Scope` discriminator (`evidence` | `contribution`) is derived from the pack name and carried by every extraction event (rows already carry it in `schema_ref`). Plan-D services take a keyword `scope` that defaults to `evidence`, so every existing call keeps its meaning; the pack model gains five declarative attributes (`allowed`, `conditionals`, `row_key_fields`, `row_anchor_fields`, `compared_fields`) that the generic verifier and agreement read. The contribution pack is pure data in `factory/packs/contribution.py`.

**Tech Stack:** as plan D; no new dependencies.

**Spec:** `docs/specs/slice-3b-lineage.md` rulings 2, 5, 6, 7, 9 (population), 12 (amendment part); acceptance 1, 7 (unit level; full acceptance in G2-E), 19. `docs/specs/01-rigour.md` R-13–R-15, R-45. Plan D rulings 1, 5, 9–12 (generalised, not changed).

## Rulings made in this plan

Marked **[adopted 2026-11-04]** where they go beyond the spec: Adopted 2026-11-04 (researcher's standing approval of the recommendation). G2-E records them in the *Proposed* decision when built.

1. **Scope. [adopted 2026-11-04]** `Scope(StrEnum)`: `EVIDENCE = "evidence"`, `CONTRIBUTION = "contribution"`. Pack `contribution` is valid only in `contribution_schema`, and `contribution_schema.pack` must be `contribution`; so scope is a function of the pack name (`scope_of_pack`). Events of the plan-D family that do not carry `schema_ref` gain `pack: str | None = None`; `None` (every event written before this plan) means evidence. `extraction.recorded` needs no new pack field: `schema_ref` (`contribution@1`) already names it.
2. **One session, one pass, one scope. [adopted 2026-11-04]** A session that joined any pass of either scope cannot join another pass of either scope (decision 37 independence extended across scopes). Task kinds `contrib_a`, `contrib_b`.
3. **Pack attributes (spec ruling 7).** `FieldDef.allowed: tuple[str, ...] = ()` (an enumeration; empty = free); `Pack.conditionals: tuple[Conditional, ...] = ()` with `Conditional(field, when, values, rule: "required" | "forbidden")`; `Pack.row_key_fields: tuple[str, ...] = ()`; `Pack.row_anchor_fields: tuple[str, ...] = ()` (the fields whose anchor locates the row, in order); `Pack.compared_fields: tuple[str, ...] | None = None` (`None` = plan-D rule: every declared field). `ML_BENCHMARK_V1` keeps all five at their defaults, so its digest and behaviour are unchanged.
4. **Row key for keyed packs. [adopted 2026-11-04]** When `row_key_fields` is non-empty, `row_key = "rk_" + sha256(conversion_id \x1f anchor \x1f v1 \x1f v2 …)[:12]` where `anchor` is the anchor of the first field in `row_anchor_fields` that is present with an anchor (`-` when none, as for `not-stated`) and `vi` is `normalise_for(field, value)` of each key field or `""` when absent. Otherwise plan D's `row_key(conversion_id, value_field)` is unchanged.
5. **Pack `contribution` v1. [adopted 2026-11-04]** Fields in this order (group, kind, check): `item_kind` (item, text, none; allowed `base-idea|addition|result|limitation|not-stated`), `absent_kind` (item, text, none; allowed `base-idea|limitation`), `name` (content, text, text-in-quote), `statement` (content, text, text-in-quote), `compared_to` (content, text, text-in-quote), `cited_entry` (link, integer, none), `metric` (result, text, text-in-quote), `value` (result, number, number; unit family score, units `%`, `fraction`, `""`), `result_row` (link, text, none). `unit` is the plan-D `FieldInput.unit` of `value`, not a field. Required: `item_kind`. `row_key_fields = ("item_kind", "absent_kind", "name")`; `row_anchor_fields = ("name", "statement", "compared_to")`; `compared_fields = ("item_kind", "absent_kind", "name", "cited_entry", "value")` (quote, anchor and `statement` are never compared: spec, Dual extraction); `default_comparability_keys = ()`; `citation_patterns = ()` (copy markers do not apply; cited entries are checked through G1 in G2-B). Conditionals:
   - `absent_kind` required when `item_kind = not-stated`, forbidden otherwise;
   - `name`, `statement`, `compared_to`, `cited_entry`, `metric`, `value`, `result_row` forbidden when `item_kind = not-stated`;
   - `statement` required when `item_kind ∈ {base-idea, addition, result, limitation}`; `name` required when `item_kind ∈ {base-idea, addition}`;
   - `metric`, `value` required when `item_kind = result`; `metric`, `value`, `result_row` forbidden when `item_kind ∈ {base-idea, addition, limitation}`;
   - `compared_to` forbidden when `item_kind ∈ {base-idea, limitation}`; `cited_entry` forbidden when `item_kind = limitation`.
6. **Contribution schema (spec ruling 5).** `ProtocolSpec.contribution_schema: ExtractionSchema | None = None`, amendable, hashed, omitted while `None`. Errors: pack not `contribution` (`contribution_schema.pack`), `claims` true (`contribution_schema.claims`), non-empty `comparability_keys` (`contribution_schema.comparability_keys`), a field outside the pack or a pack-required field missing (as plan D); `extraction_schema.pack == "contribution"` is an error (`extraction_schema.pack`). Gaps: plan-D ruling 9 rules on `contribution_schema.dual_extract_sample`, `.audit_fraction`, `.audit_minimum`. `ProtocolAmended.contribution_stale: ExtractionStale | None = None`, computed by the existing `extraction_stale(old, new)`.
7. **Population (spec ruling 9).** Contribution population = G1 `included_works(project)` (final outcome `INCLUDED` at the last declared stage with a pinned default conversion). A work without a current G1 extraction is in the population; G2-B lists it `no-references`.
8. **Contribution staleness (spec rulings 9, 12).** A contribution row is stale (unit reason `references`) when it carries `cited` and `cited.reference_extraction_id` is not `current_extraction(project, work_id)`. Amendment and document-version staleness are plan D's, applied per scope with `contribution_stale`.
9. **Separation (spec ruling 6, acceptance 7).** Every plan-D/E read defaults to `scope=EVIDENCE`; `grouped_rows`, `independence_counts`, `live_claims` and the evidence report never see a contribution row. Plan-D check findings stay evidence-only; contribution findings are G2-E's.

## Global Constraints

- All plan A–E and G1 constraints hold. The platform never calls a model; no key, no SDK. Events are the source of truth; the index is written by the projector alone; the projection never reads the library.
- Every agent-written event carries model, skill reference and `input_blob`. Verification results are computed by the platform and stored in the event.
- Quotes are the only document text in events; no document text in any error, warning or finding.
- Invalid input writes nothing and returns structured errors; in a batch each row is validated alone.
- Business logic in `services/`; pure helpers in `factory/extraction/`, `factory/packs/`; `mcp/`, `cli/` untouched by this plan.
- A log without `contribution_schema` replays to identical `P@` ids; a log with no contribution events gives an identical state hash except the projection version.
- `uv run pytest -m "not network"`, `mypy --strict`, ruff pass; coverage >= 90% for `services/` and `model/`.

## Review Focus

1. A plan-D log (events without `pack`) replays into scope `evidence` with the same rows, passes, sessions, resolutions and audits as before (Task 3, `test_legacy_log_projects_to_evidence`).
2. A session that joined evidence pass A tries to join contribution pass B (or A): refused, nothing written (Task 4, `test_session_cannot_cross_scopes`).
3. An evidence agreement/resolution/audit call while contribution tasks are open is not blocked by them, and vice versa (Task 5, `test_open_contribution_task_does_not_block_evidence_agreement`).
4. A contribution row whose `name` differs only by case and whitespace between passes aligns (same `row_key`), while the same name at a different anchor does not (Task 1, `test_row_key_normalises_name_and_uses_anchor`).
5. Amending only `contribution_schema` stales no evidence row and vice versa (Task 2, `test_amendments_are_scope_local`).

## File Structure

- Modify `packs/model.py` (`FieldDef.allowed`, `Conditional`, `Pack.conditionals/row_key_fields/compared_fields`), `packs/__init__.py` (register); create `packs/contribution.py`.
- Modify `extraction/verify.py` (`pack_row_key`), `services/extraction_verify.py` (allowed, conditionals, keyed row key).
- Modify `model/protocol.py`, `services/protocol_rules.py`, `services/protocol.py`.
- Modify `model/extraction.py` (`Scope`, `scope_of_pack`, `pack` fields, `CitedEntry`, `ExtractionRecorded.cited`, `EntryBrief`, `UnitReferences`, `ContributionBatchContent`), `index/extraction.py`, `index/default.py`.
- Modify `services/stages.py`, `services/extraction.py`, `services/document_read.py`, `services/extraction_agreement.py`, `services/extraction_audit.py`.
- Tests: `test_packs_contribution.py`, `test_contribution_schema.py`, `test_extraction_scope_index.py`, `test_extraction_scope.py`, `test_extraction_scope_agreement.py`; helper `tests/contribution_helpers.py` (a G1-ready project: `n` included works converted from hand-written Markdown with a References section and `b<n>` anchors, a current G1 extraction per work built with G1's helpers, a pilot protocol declaring both schemas, and `item(...)` builders for each kind).

---

### Task 1: Pack attributes, contribution pack v1 and generic verification

*Tier: critical (verification and row identity).*

**Files:** Modify `packs/model.py`, `packs/__init__.py`, `extraction/verify.py`, `services/extraction_verify.py`; Create `packs/contribution.py`; Test `tests/test_packs_contribution.py`, extend `tests/test_extraction_verify.py` only by new tests.

**Interfaces:**
- Consumes: `FieldDef`, `Pack`, `get_pack`, `normalise_for`, `row_key(conversion_id, value)`, `verify_row_in(pack, declared, row, conversion_id, manifest, corpus) -> RowVerdict`.
- Produces (`packs/model.py`): `FieldDef.allowed: tuple[str, ...] = ()`; `@dataclass(frozen=True) Conditional(field: str, when: str, values: tuple[str, ...], rule: Literal["required", "forbidden"])`; `Pack.conditionals: tuple[Conditional, ...] = ()`, `Pack.row_key_fields: tuple[str, ...] = ()`, `Pack.row_anchor_fields: tuple[str, ...] = ()`, `Pack.compared_fields: tuple[str, ...] | None = None`.
- Produces (`packs/contribution.py`): `CONTRIBUTION_PACK = "contribution"`; `ITEM_KINDS = ("base-idea", "addition", "result", "limitation", "not-stated")`; `ABSENT_KINDS = ("base-idea", "limitation")`; `CONTRIBUTION_V1: Pack` (ruling 5); `get_pack("contribution", 1) is CONTRIBUTION_V1`.
- Produces (`extraction/verify.py`): `pack_row_key(pack: Pack, conversion_id: str, fields: Mapping[str, StoredField]) -> str` (ruling 4; delegates to `row_key` when `pack.row_key_fields` is empty).
- Produces (`services/extraction_verify.py`): `verify_row_in` additionally rejects a value outside `allowed` (`fields.<name>.value`, reason `value-not-allowed`), a conditional `required` field absent (`fields.<name>`, `required`) and a conditional `forbidden` field present (`fields.<name>`, `not-allowed-for-kind`); `RowVerdict.row_key` comes from `pack_row_key`.

- [ ] **Step 1: Tests.**
```python
def test_ml_benchmark_unchanged():
    assert ML_BENCHMARK_V1.row_key_fields == ML_BENCHMARK_V1.row_anchor_fields == () and ML_BENCHMARK_V1.compared_fields is None
    assert ML_BENCHMARK_V1.conditionals == () and all(f.allowed == () for f in ML_BENCHMARK_V1.fields)
def test_contribution_pack_shape():
    p = get_pack("contribution", 1)
    assert [f.name for f in p.fields] == ["item_kind", "absent_kind", "name", "statement", "compared_to", "cited_entry", "metric", "value", "result_row"]
    assert p.required == ("item_kind",) and p.field("item_kind").allowed == ITEM_KINDS
    assert p.field("value").check is Check.NUMBER and p.field("name").check is Check.TEXT_IN_QUOTE
    assert set(p.compared_fields) <= {f.name for f in p.fields} and "statement" not in p.compared_fields
def test_conditional_fields_name_existing_fields(): ...   # every Conditional.field/when is a pack field
def test_value_not_allowed(): assert reasons(item_kind="improvement") == {"fields.item_kind.value": "value-not-allowed"}
def test_not_stated_needs_absent_kind_and_forbids_content():
    assert "fields.absent_kind" in reasons(item_kind="not-stated")
    assert reasons(item_kind="not-stated", absent_kind="base-idea", name=Q("Linformer")) == {"fields.name": "not-allowed-for-kind"}
def test_absent_kind_refuses_addition_and_result():      # acceptance 4
    assert reasons(item_kind="not-stated", absent_kind="addition")["fields.absent_kind.value"] == "value-not-allowed"
def test_result_needs_metric_and_value(): ...
def test_base_idea_needs_name_and_statement(): ...
def test_row_key_normalises_name_and_uses_anchor():      # Review Focus 4
    k1 = pack_row_key(CONTRIBUTION_V1, CNV, stored(item_kind="base-idea", name=("Linear Attention", "s2.p1")))
    k2 = pack_row_key(CONTRIBUTION_V1, CNV, stored(item_kind="base-idea", name=("linear  attention", "s2.p1")))
    k3 = pack_row_key(CONTRIBUTION_V1, CNV, stored(item_kind="base-idea", name=("Linear Attention", "s3.p2")))
    assert k1 == k2 != k3 and re.fullmatch(ROW_KEY_RE, k1)
def test_not_stated_row_key_has_no_anchor(): ...          # anchor "-"; base-idea and limitation keys differ
def test_ml_benchmark_row_key_unchanged(): ...             # equals plan-D row_key for the same value field
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement per Interfaces; conditionals evaluated on the normalised `item_kind` value after the `allowed` check (a row failing `allowed` reports only that). **Step 4:** New tests and the whole plan-D verify suite unedited; mypy; ruff. **Step 5:** Commit `feat(packs): contribution pack v1, allowed values, conditionals, keyed row key`.

### Task 2: `contribution_schema` protocol section and scope-local amendment staleness

*Tier: critical (protocol hash, amendments).*

**Files:** Modify `model/protocol.py`, `services/protocol_rules.py`, `services/protocol.py`; Test `tests/test_contribution_schema.py`.

**Interfaces:**
- Consumes: `ExtractionSchema`, `ExtractionStale`, `extraction_stale`, `AMENDABLE_FIELDS`, `_OMITTED_WHEN_NONE`.
- Produces: `ProtocolSpec.contribution_schema: ExtractionSchema | None = None` in `AMENDABLE_FIELDS` and `_OMITTED_WHEN_NONE`; `ProtocolAmended.contribution_stale: ExtractionStale | None = None`; `amend_protocol` stores `contribution_stale=extraction_stale(old.contribution_schema, new.contribution_schema)`; `_errors` and `_gaps` per ruling 6.

- [ ] **Step 1: Tests.**
```python
def test_p_id_unchanged_without_contribution_schema():
    assert protocol_version(spec_with_evidence_schema_only) == PINNED_P_ID   # literal computed on the base branch
def test_p_id_changes_with_contribution_schema(): ...
def test_contribution_schema_errors():
    errs = fields_of(protocol_issues(spec(contribution=S(pack="ml-benchmark")), **ctx).errors)
    assert "contribution_schema.pack" in errs
    assert "contribution_schema.claims" in fields_of(errors(contribution=S(claims=True)))
    assert "contribution_schema.comparability_keys" in fields_of(errors(contribution=S(comparability_keys=("name",))))
    assert "extraction_schema.pack" in fields_of(errors(evidence=E(pack="contribution")))
def test_contribution_gaps_follow_plan_d_rules(): ...       # pilot needs a fraction; systematic needs None or 1.0
def test_amendments_are_scope_local():                      # Review Focus 5
    a = amend(contribution=S_minus("compared_to")); assert a.contribution_stale == ExtractionStale(all_records=False, fields=("compared_to",)) and a.extraction_stale is None
    b = amend(evidence=E_minus("latency")); assert b.contribution_stale is None
def test_old_amendment_event_validates_without_contribution_stale(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Protocol and amendment suites unedited; mypy; ruff. **Step 5:** Commit `feat(protocol): contribution_schema section, readiness rules, scope-local staleness`.

### Task 3: Scope on events and in the projection

*Tier: critical (events, index).*

**Files:** Modify `model/extraction.py`, `index/extraction.py`, `index/default.py`; Test `tests/test_extraction_scope_index.py`; update the `PROJECTION_VERSION` pin test.

**Interfaces:**
- Produces (`model/extraction.py`): `Scope(StrEnum)`; `scope_of_pack(pack: str | None) -> Scope`; `scope_of_schema_ref(ref: str) -> Scope`; optional `pack: str | None = None` on `ExtractionPassOpened`, `ExtractionPassJoined`, `ExtractionClosed`, `ExtractionResolved`, `ExtractionAuditSampled`, `ExtractionAuditLabelled`; `MarkerCheck = Literal["matched", "mismatch", "absent"]`; `class CitedEntry(StrictModel)`: `reference_extraction_id: str` (G1 `REX_ID_RE`), `ordinal: int = Field(ge=1)`, `marker: MarkerCheck`; `ExtractionRecorded.cited: CitedEntry | None = None`; `class EntryBrief(StrictModel)`: `ordinal: int`, `anchor: str`, `label: str | None`, `title: str | None`, `first_author: str | None`, `year: int | None`, `doi: str | None`, `arxiv: str | None`; `class UnitReferences(StrictModel)`: `status: Literal["current", "none", "other-conversion"]`, `extraction_id: str | None`, `entries: list[EntryBrief]`; `class ContributionBatchContent(ExtractBatchContent)`: `references: UnitReferences`, `item_rules: list[str]` (the conditional rules as fixed sentences derived from the pack).
- Produces (`index/extraction.py`): column `scope` (not null) on `extraction_passes`, `extraction_sessions`, `extraction_rows`, `extraction_closures`, `extraction_resolutions`, `extraction_audits`, `extraction_audit_items`; `extraction_rows.pack` (indexed, `ix_extraction_rows_pack`) and `cited_extraction_id`, `cited_ordinal`, `cited_marker`; primary keys `extraction_passes(scope, pass_label)`, `extraction_resolutions(scope, work_id, row_key, field)`; `extraction_sessions` keeps `session` as key (ruling 2). Handlers compute `scope` with `scope_of_pack` / `scope_of_schema_ref`. `PROJECTION_VERSION` = base value + 1.

- [ ] **Step 1: Tests.** `test_legacy_log_projects_to_evidence` (replay a plan-D fixture log: every row has `scope = "evidence"`, all other columns as before; Review Focus 1); `test_two_scopes_have_independent_passes` (pass A opened in both scopes: two rows in `extraction_passes`); `test_resolution_keys_are_scope_local`; `test_cited_entry_projected`; `test_pack_column_indexed` (`EXPLAIN QUERY PLAN ... WHERE pack = ?` uses an index); `test_cited_entry_shape` (ordinal >= 1, id pattern); `test_rebuild_state_hash_stable_with_both_scopes`; `test_projection_version_bumped`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Index suites, plan-D index tests unedited except the version pin; mypy; ruff. **Step 5:** Commit `feat(extraction): scope discriminator on events and projection`.

### Task 4: Scope through passes, tasks, recording, staleness and reads

*Tier: critical (dual independence, recording).*

**Files:** Modify `services/stages.py`, `services/extraction.py`, `services/document_read.py`; Test `tests/test_extraction_scope.py`.

**Interfaces:**
- Consumes: Task 3 models; G1 `included_works(project) -> list[str]`, `current_extraction(project, work_id) -> str | None` (`services/references.py`).
- Produces (`services/stages.py`): `CONTRIB_KINDS: dict[PassLabel, str] = {A: "contrib_a", B: "contrib_b"}`; `kinds_for(scope: Scope) -> dict[PassLabel, str]`; `scope_of_kind(kind: str) -> Scope | None`.
- Produces (`services/extraction.py`), every new parameter keyword-only with default `Scope.EVIDENCE` unless stated:
  - `require_schema(project, *, scope)` (contribution refusal on field `contribution_schema`: "declare the contribution schema in the protocol first (R-13)");
  - `scope_population(project, scope: Scope) -> list[str]` (no default; evidence = `extraction_population`, contribution = `included_works`);
  - `join_extraction_pass(project, actor, label, *, scope)`; `pass_config(project, label, *, scope)`; `unit_pin(project, work_id, *, scope)`; `session_scope(project, session: str) -> Scope | None`; `is_extraction_session(project, session)` true for either scope;
  - `ContentHook = Callable[[Project, ExtractBatchContent], ExtractBatchContent]`; `next_unit(project, actor, label, *, scope: Scope, content: ContentHook | None = None) -> ExtractNext` (the hook runs when a task is created; its result is the stored task content); `extract_next(project, actor, label)` is `next_unit(..., scope=EVIDENCE)`; task content is parsed with `ContributionBatchContent` for `contrib_*` kinds;
  - `@dataclass(frozen=True) UnitPin(task_id: str, work_id: str, pass_label: PassLabel, scope: Scope, document_id: str, conversion_id: str)`; `@dataclass(frozen=True) ExtraVerdict(cited: CitedEntry | None, issues: list[ValidationIssue])`; `ExtraCheck = Callable[[Project, UnitPin, Mapping[str, StoredField], Sequence[ExtractionRow]], ExtraVerdict]` (the last argument: the unit's live rows plus rows accepted earlier in the same call, as `ExtractionRow`s); `CloseCheck = Callable[[Project, UnitPin, Sequence[ExtractionRow], str | None], list[ValidationIssue]]`;
  - `record_unit(project, actor, task_id, rows, claims=(), *, finish=False, reason=None, supersedes=None, extra_check: ExtraCheck | None = None, close_check: CloseCheck | None = None) -> ExtractResult` (issues from `extra_check` reject the row like verification issues; `cited` is stored on the event; `close_check` issues refuse the close as plan D's zero-row rule does); `extract_record(...)` is `record_unit` without hooks and refuses a `contrib_*` task on field `task_id` ("use contribution_record");
  - `ExtractionRow.cited: CitedEntry | None = None`; `live_rows(project, pass_label=None, *, work_id=None, scope)`; `live_claims(...)` evidence only; `stale_extractions(project, *, scope)`, `unit_states(project, *, scope)`, `stale_documents(project, *, scope)`; `UnitState.reason` gains `references` (ruling 8).
- `document_read` gate: a contribution session reads only its held or completed `contrib_*` works at the pinned conversion, as plan D.

- [ ] **Step 1: Tests.**
```python
def test_contribution_refused_until_schema_declared():   # acceptance 1
    with pytest.raises(FactoryValidationError) as e: next_unit(project_evidence_only, agent_a, PassLabel.A, scope=Scope.CONTRIBUTION)
    assert e.value.issues[0].field == "contribution_schema" and no_events_written()
def test_contribution_population_is_g1_included_works(): ...   # includes a work with no G1 extraction
def test_session_cannot_cross_scopes(): ...                     # Review Focus 2: field "pass"
def test_contribution_tasks_use_contrib_kinds_and_content_hook():
    nxt = next_unit(project, agent_a, PassLabel.A, scope=Scope.CONTRIBUTION, content=add_refs)
    assert task_kind(nxt.batch.task_id) == "contrib_a" and isinstance(stored_content(nxt), ContributionBatchContent)
def test_extract_record_refuses_contribution_task(): ...
def test_extra_check_rejects_row_and_stores_cited(): ...         # a stub ExtraCheck; partial acceptance kept
def test_close_check_refuses_finish(): ...
def test_evidence_reads_exclude_contribution_rows():
    assert live_rows(project) == EVIDENCE_ROWS and all(r.pass_label for r in live_rows(project, scope=Scope.CONTRIBUTION))
def test_cited_row_stale_when_g1_extraction_replaced():           # ruling 8
    new_g1_extraction(project, w); assert row_id in stale_extractions(project, scope=Scope.CONTRIBUTION)
    assert unit_reason(project, w, Scope.CONTRIBUTION) == "references" and stale_extractions(project) == set()
def test_new_document_version_stales_both_scopes(): ...
def test_contribution_session_reads_only_its_queue(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement by threading `scope` through `_queue`, `_enqueue`, `_ledger`, `_kind_tasks`, `_joined_pass` (any scope), `_check_join`; never branch on the pack name outside `scope_of_*`. **Step 4:** The plan-D suites (`test_extraction_*`) and the document-read gate suite pass unedited; mypy; ruff. **Step 5:** Commit `feat(extraction): scope-parameterised passes, tasks, recording hooks and staleness`.

### Task 5: Agreement, resolution, final rows and audit by scope; plan-E separation

*Tier: critical (agreement, audit, separation from the evidence table).*

**Files:** Modify `services/extraction_agreement.py`, `services/extraction_audit.py`; Test `tests/test_extraction_scope_agreement.py`.

**Interfaces:**
- Consumes: Task 4 reads; `Pack.compared_fields`.
- Produces (keyword `scope`, default `Scope.EVIDENCE`): `extraction_agreement(project, actor, *, scope)`, `agreement_overall(project, *, scope)`, `resolve_extraction(project, actor, work_id, row_key, field, choice, reason, channel, *, scope)` (writes `pack` on the event), `final_rows(project, *, scope)`; `grouped_rows(project)` and `independence_counts(rows)` unchanged (evidence only); `agreed_values(project, *, scope)`, `extraction_audit_sample(project, actor, *, random_seed=None, scope)`, `audit_evidence(project, audit_id)` and `extraction_audit_record(...)` take the scope from the audit, `extraction_audit_report(project, *, scope)`, `extraction_audit_outstanding(project, *, scope)`. Compared fields = `pack.compared_fields` when set, else plan D's rule. `AuditEvidence` for an anchorless field has `anchor None` and `element_text ""`. The open-task refusal counts only the scope's tasks.

- [ ] **Step 1: Tests.**
```python
def test_open_contribution_task_does_not_block_evidence_agreement(): ...   # Review Focus 3, both directions
def test_statement_and_quote_not_compared():
    a = item(kind="addition", name="gated linear attention", statement="we add a gate"); b = item(..., statement="a gate is added")
    assert extraction_agreement(project, human, scope=Scope.CONTRIBUTION).disagreements == []
def test_cited_entry_difference_is_a_disagreement(): ...
def test_not_stated_items_are_audited(): assert any(i.field == "item_kind" for i in agreed_values(project, scope=Scope.CONTRIBUTION))
def test_separation_from_evidence_table():                  # acceptance 7 (unit level)
    before = (final_rows(p), grouped_rows(p), independence_counts(final_rows(p)), live_claims(p), agreement_overall(p), extraction_audit_report(p))
    record_contribution_units_both_passes(p)
    assert (final_rows(p), grouped_rows(p), independence_counts(final_rows(p)), live_claims(p), agreement_overall(p), extraction_audit_report(p)) == before
def test_evidence_report_unchanged_by_contribution_rows(): ...   # rendered plan-E report text byte-equal
def test_resolution_and_audit_events_carry_pack(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Plan-D agreement/audit suites, plan-E evidence-report suites and `check` suites unedited; full suite; mypy; ruff; coverage. **Step 5:** Commit `feat(extraction): agreement, resolution and audit by scope; evidence separation`.

## Self-review notes

- **Spec coverage.** Rulings 2 and 7 (Task 1), 5 (Task 2), 6 (Tasks 3–5), 9 population (Task 4), 12 amendment and G1-change staleness (Tasks 2, 4); acceptance 1 (Tasks 2, 4), 7 unit level (Task 5). Recording-specific checks (`cited_entry`, markers, `result_row`, closure) are G2-B.
- **Types used later.** `Scope`, `CitedEntry`, `MarkerCheck`, `EntryBrief`, `UnitReferences`, `ContributionBatchContent`, `UnitPin`, `ExtraVerdict`, `ExtraCheck`, `CloseCheck`, `next_unit`, `record_unit`, `live_rows(..., scope=)`, `final_rows(..., scope=)`, `stale_extractions(..., scope=)`, `unit_states(..., scope=)`, `CONTRIBUTION_V1`, `CONTRIBUTION_PACK`, `ITEM_KINDS`, `ABSENT_KINDS`.
- **Tiers.** All five tasks critical (spec acceptance 19: plan-D generalisation by subagent-driven development); Sonnet task reviews; the final branch review checks that no earlier test was edited apart from the projection pin.

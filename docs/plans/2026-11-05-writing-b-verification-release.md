# Sentence Verification, Audit, Rendering and Release Implementation Plan (slice 7b, sub-plan W-B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Slice M is merged first: the release gate is the slice-M gate `writing.release` (draft `draft-released`; floor `agent`; presets exploratory `agent`, pilot `agent` once the audit is labelled, systematic `human`), declared here and checked with `require_gate`; the verdict audit label is `writing.audit_label` (floor `human`). Task 7's acceptance uses a pilot-shaped fixture and stays in v1. Bumps `PROJECTION_VERSION` by one from the value it finds.

> **Dependencies.** W-A merged (Interfaces consumed exactly: `SupportRef`, `resolve_supports`, `live_sentences`, `verifier_sessions`, tables `draft_sentences`, `sentence_supports`). X-A merged (`assign_keys`, `bibtex`, `select_works`). Plan 5b `trace`/`check` and their 2E/G2-E/G3-C extensions merged. When slice M lands, the release gate's policy moves from `RigorMode` to the declared gate policy `writing.release`; events are unchanged.

**Goal:** Judge every claim-bearing sentence by an independent verifier session that sees only the sentence and its spans, audit a sample of positive verdicts, compute each sentence's status on read, render drafts with visible markers for anything not supported, and release a draft only through a mode-dependent gate; extend `trace` and `check`.

**Architecture:** `model/drafts.py` gains verdict, audit and release payloads. `services/draft_verify.py` serves verification units (leased tasks whose content holds the sentence, the preceding sentence as context and the support spans) and records verdicts after verifying their substrings. `services/drafts.py` gains `sentence_status` (computed, never stored). `services/draft_audit.py` draws and labels the audit. `writing/render.py` renders review and clean Markdown. `services/draft_release.py` applies the gate. `services/trace.py` and `services/check.py` gain the new kinds and findings.

**Tech Stack:** as W-A.

**Spec:** `docs/specs/slice-7b-views-writing.md` rulings 12–14, 16, 18 (`draft:` scope), 25; Trace; Check findings; acceptance 7–11, 15, 16, 18. R-01, R-04, R-05, R-39, R-51; decision 37 (independence pattern, 37.14 withheld rates), 43.

## Rulings made in this plan
1. **Unit and independence [confirm].** A verification unit is one live `claim` or `synthesis` sentence without a verdict on its current version. `draft_verify_next` refuses a session that recorded any sentence of the draft; `draft_write` (W-A `verifier_sessions`) refuses a session that recorded any verdict of the draft. In `systematic`, a verifier whose reported model equals the writer's model of that sentence is refused; in `pilot` the pair is recorded and `report` shows it.
2. **Unit content.** `{sentence_id, text, cls, context_previous: text | None, supports: [{ref, kind, spans: [quote…], value?, unit?, stat_value?}]}`. No writer identity, no flags, no outline, no `input_blob` of the writer. Stored as the verifier's `input_blob`.
3. **Verdict checks.** `sentence_span` is a non-empty substring of the sentence text (exact, after whitespace collapsing), required unless `supported`; each `support_spans[i].substring` is a substring of one span of the named support (quote normalisation as `normalise_quote`), at least one required for `supported`, `partial`, `contradicted`, `overstated`; `unsupported` may have none. A ref not among the sentence's supports is refused. `note` ≤ 300 characters.
4. **Status (computed on read).** Precedence: `stale` (any support ineligible now, or a stat recomputes differently) > `flagged` (latest verdict not `supported`, or latest audit label `incorrect`) > `supported` (latest verdict `supported`) > `unchecked`. `structural` and `interpretive` sentences have those statuses unless stale (an interpretive sentence whose `interp` support turned `wrong` is `stale`).
5. **Audit [confirm].** Per draft, drawn once per release attempt from `supported` verdicts not yet audited: n = min(N, max(ceil(0.1·N), 20)); random seed recorded (`draft.audit_drawn`, system). Labels `correct|incorrect` by a human (CLI, or MCP relayed answer with `channel = mcp` as decision 37.6). Error rate = incorrect / labelled; `DRAFT_VERIFY_ERROR_CEILING = 0.05`. The rate is withheld from agent views (decision 37.14 pattern).
6. **Release gate (spec ruling 13).** `exploratory`: any actor; no conditions beyond a non-empty draft. `pilot`: any actor; audit drawn and fully labelled; zero `stale`. `systematic`: human actor equal to the protocol's reviewer of record; zero `stale`, `flagged`, `unchecked` claim-bearing sentences; audit rate ≤ ceiling. A refusal lists the blocking counts (never text).
7. **Markers.** Exactly as spec ruling 14: `[[UNSUPPORTED: <status>; <reason>]] … [[/]]` and `[[INTERPRETATION]] … [[/]]`; `<reason>` is the verdict or the stale reason code. Citation keys appended after each sentence as `[@key1; @key2]` (pandoc form) from X-A `assign_keys` over the works of the rendered sentences, in support order, de-duplicated.
8. **Bibliography scope `draft:<drf_…>`.** The works of supports of live sentences that are `supported`, `interpretive`, or rendered with a marker; X-A `select_works` gains this scope.

## Global Constraints
- The platform never judges support; it checks substrings, independence, eligibility and counts.
- No document text in errors or findings; quotes appear only in task content and review renderings, taken from existing events.
- Every agent verdict carries model, `rf-verify@<hash>` and `input_blob`.
- Status is never stored; rebuild determinism holds for all new tables.
- TDD; `uv run pytest -m "not network and not slow"`; `mypy --strict`; ruff; coverage ≥ 90%.

## Review Focus
1. Writer and verifier sessions cannot cross in either direction (Task 1, `test_independence_both_directions`).
2. A `supported` verdict citing a substring absent from the support span is refused (Task 1, `test_support_substring_verified`).
3. A claim superseded after verification makes the sentence `stale` and blocks pilot release (Tasks 2, 5, `test_superseded_claim_stales_sentence`, `test_pilot_release_refused_when_stale`).
4. Clean rendering of a draft with one flagged sentence contains exactly one marker pair (Task 4, `test_clean_marks_flagged`).
5. The agent view of `draft_status` and `check` carries no audit rate (Task 3, `test_rate_withheld_from_agent`).

## File Structure
- Create `services/draft_verify.py`, `services/draft_audit.py`, `services/draft_release.py`, `writing/render.py`, `plugin/skills/rf-verify/SKILL.md`.
- Modify `model/drafts.py`, `index/drafts.py`, `services/drafts.py`, `services/exports.py`, `services/trace.py`, `services/check.py`, `mcp/server.py`, `cli/main.py`.
- Tests: `tests/test_draft_verify.py`, `tests/test_draft_status.py`, `tests/test_draft_audit.py`, `tests/test_writing_render.py`, `tests/test_draft_release.py`, `tests/test_trace_drafts.py`, `tests/test_check_drafts.py`, `tests/test_drafts_b_cli_mcp.py`, `tests/test_writing_acceptance.py` (`slow`).

### Task 1: Verdicts and verification units

*Tier: critical (independence, R-51).*

**Files:** Create `services/draft_verify.py`; Modify `model/drafts.py`, `index/drafts.py`; Test `tests/test_draft_verify.py`.

**Interfaces:**
- Produces (`model/drafts.py`): `VERDICT_ID_RE = rf"^svd_{ULID_RE}$"`; `class Verdict(StrEnum): SUPPORTED, PARTIAL, UNSUPPORTED, CONTRADICTED, OVERSTATED`; `SupportSpan(ref: str, substring: str)`; `SentenceVerified(verdict_id, sentence_id, verdict, sentence_span: str | None, support_spans: list[SupportSpan], note: str | None)`; event `draft.verified`.
- Produces (tables): `sentence_verdicts` (`verdict_id`, `sentence_id`, `verdict`, `session`, `model`, `event_id`).
- Produces (`services/draft_verify.py`): `VerifyUnit` (ruling 2); `verify_next(project, draft_id, *, actor: Actor) -> VerifyUnit | None`; `VerdictInput(sentence_id, verdict, sentence_span, support_spans, note)`; `verify_record(project, task_id: str, item: VerdictInput, *, actor: Actor, input_blob: str) -> str`.

- [ ] **Step 1: Tests.**
```python
def test_independence_both_directions(draft): ...            # Review Focus 1: writer session refused at verify_next; verifier session refused at draft_write
def test_systematic_same_model_refused(draft_sys): ...
def test_unit_content_has_no_writer_material(draft): u = verify_next(...); assert set(u.model_dump()) == {"sentence_id", "text", "cls", "context_previous", "supports", "task_id"}
def test_sentence_span_must_be_substring(draft): ...
def test_support_substring_verified(draft): ...              # Review Focus 2
def test_ref_outside_supports_refused(draft): ...
def test_structural_and_interpretive_not_served(draft): ...
def test_superseding_sentence_needs_new_verdict(draft): ...
def test_no_text_in_errors(draft): ...
```
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): independent sentence verification`.

### Task 2: Status and staleness

*Tier: critical.*

**Files:** Modify `services/drafts.py`; Test `tests/test_draft_status.py`.

**Interfaces:**
- Consumes: `resolve_supports`, `compute_stat`, verdict and audit rows.
- Produces: `SentenceStatus = Literal["structural", "interpretive", "unchecked", "supported", "flagged", "stale"]`; `@dataclass(frozen=True) StatusRow(sentence_id, section_id, order, cls, status, reason: str | None, flags: tuple[str, ...])`; `sentence_status(project, draft_id) -> list[StatusRow]` (batched resolution of all supports of the draft; one call per support kind); `status_counts(rows) -> dict[str, int]`.

- [ ] **Step 1: Tests.** `test_precedence` (stale over flagged over supported); `test_superseded_claim_stales_sentence` (Review Focus 3); `test_excluded_work_stales`; `test_rejected_edge_stales`; `test_stat_change_stales` (add an included work, `included-works` changes); `test_interp_wrong_stales_interpretive`; `test_audit_incorrect_flags`; `test_counts_derived`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): computed sentence status and staleness`.

### Task 3: Audit

*Tier: critical (error-rate reporting).*

**Files:** Create `services/draft_audit.py`; Modify `model/drafts.py`, `index/drafts.py`; Test `tests/test_draft_audit.py`.

**Interfaces:**
- Produces: events `draft.audit_drawn` (`audit_id` `dau_<ULID>`, `draft_id`, `seed`, `verdict_ids`), `draft.audited` (`audit_id`, `verdict_id`, `label`, `note`); `DRAFT_VERIFY_ERROR_CEILING = 0.05`; `draw_audit(project, draft_id) -> str`; `record_audit(project, audit_id, verdict_id, label, note, *, actor: Actor, channel: Literal["cli", "mcp"] = "cli") -> str` (human only); `DraftAuditReport(drawn: int, labelled: int, incorrect: int, rate: float | None, above_ceiling: bool | None)`; `audit_report(project, draft_id) -> DraftAuditReport`; `agent_audit_report(report) -> DraftAuditReport` (rate and ceiling flag set to `None`).

- [ ] **Step 1: Tests.** `test_sample_size_rule` (N = 5, 50, 300); `test_seed_recorded_and_draw_reproducible`; `test_only_supported_unaudited_verdicts_drawn`; `test_agent_cannot_label`; `test_mcp_relay_records_channel`; `test_rate_withheld_from_agent` (Review Focus 5).
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): human audit of supported verdicts`.

### Task 4: Rendering and the `draft:` bibliography scope

*Tier: standard.*

**Files:** Create `writing/render.py`; Modify `services/exports.py`, `services/drafts.py`; Test `tests/test_writing_render.py`.

**Interfaces:**
- Produces (`writing/render.py`): `render_review(draft: DraftView, statuses: Sequence[StatusRow], spans: Mapping[str, Sequence[str]]) -> str` (each sentence with `{status}` tag, flags, supports and their quotes); `render_clean(draft: DraftView, statuses, keys: Mapping[str, str]) -> str` (ruling 7); `RENDER_VERSION = 1`.
- Produces (`services/drafts.py`): `DraftView` (title, sections with ordered live sentences, works per sentence); `draft_render(project, draft_id, mode: Literal["review", "clean"]) -> str` (clean output ends with a "Bibliography" note naming the BibTeX export command and a methods paragraph with derived counts by status and the audit summary).
- Produces (`services/exports.py`): `select_works(..., draft: str | None = None)` (ruling 8).

- [ ] **Step 1: Tests.** `test_clean_marks_flagged` (Review Focus 4); `test_clean_without_markers_when_all_supported`; `test_interpretive_labelled`; `test_citation_keys_in_support_order`; `test_review_shows_quotes_from_events_only` (library read patched to raise); `test_bibliography_scope_draft`; `test_render_deterministic`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): review and clean renderings with markers`.

### Task 5: Release gate

*Tier: critical (gate).*

**Files:** Create `services/draft_release.py`; Modify `model/drafts.py`, `index/drafts.py`; Test `tests/test_draft_release.py`.

**Interfaces:**
- Consumes: `RigorMode` of the project, the protocol's reviewer of record (R-39 field as slice 1 defines it), `sentence_status`, `audit_report`, `Index.head`.
- Produces: event `draft.released` (`draft_id`, `as_of`, `policy`, `counts`, `audit: DraftAuditReport`); `release(project, draft_id, *, actor: Actor) -> str` (ruling 6; refusal → `FactoryValidationError` with one issue per blocking condition, counts only).

- [ ] **Step 1: Tests.** One per mode and condition: `test_exploratory_releases_with_flags`; `test_pilot_release_refused_when_stale` (Review Focus 3); `test_pilot_requires_labelled_audit`; `test_systematic_requires_reviewer_of_record`; `test_systematic_refuses_flagged_unchecked`; `test_systematic_refuses_rate_above_ceiling`; `test_release_records_counts_and_as_of`; `test_agent_cannot_release_systematic_over_mcp`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): release gate by rigor mode`.

### Task 6: Trace and check

*Tier: standard.*

**Files:** Modify `services/trace.py`, `services/check.py`; Test `tests/test_trace_drafts.py`, `tests/test_check_drafts.py`.

**Interfaces:**
- `services/trace.py`: `KINDS` gains `draft`, `sentence`, `verdict` (after `claim`, `cell` in chain order); patterns for `drf_`, `snt_`, `svd_`; back from a sentence → its supports (claim, cell, item, edge, group, stat as a leaf node, interp) → existing chains; forward from claim, cell, item, edge → sentences (via `sentence_supports.ref` index) → draft. `agent_trace` unchanged in its withholding rules.
- `services/check.py`: findings `draft-sentence-unchecked`, `draft-sentence-flagged`, `draft-sentence-stale` (warnings; errors in `systematic` for released drafts), `draft-audit-missing`, `draft-verify-error-high` (added to `_RATE_CODES`), `draft-writer-verified` (error, all modes).

- [ ] **Step 1: Tests.** `test_trace_sentence_to_question_for_each_support_kind`; `test_forward_from_claim_lists_sentences`; `test_stat_support_is_leaf`; each finding in a constructed case; `test_findings_have_no_text`; `test_agent_view_withholds_rate`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): trace and check for drafts`.

### Task 7: Tools, CLI, skill `rf-verify`, acceptance

*Tier: standard.*

**Files:** Modify `mcp/server.py`, `cli/main.py`; Create `plugin/skills/rf-verify/SKILL.md`; Test `tests/test_drafts_b_cli_mcp.py`, `tests/test_writing_acceptance.py` (`slow`).

**Interfaces:**
- MCP: `draft_verify_next(project, draft_id)`, `draft_verify_record(project, task_id, verdict, sentence_span=None, support_spans=None, note=None)`, `draft_render(project, draft_id, mode="review")`, `draft_status` (W-A) now returns computed status. `draft_release` over MCP only in `exploratory`/`pilot`.
- CLI: `factory draft status|render DRAFT [--review|--clean] [--out PATH]|audit DRAFT [--draw]|label AUDIT VERDICT --correct|--incorrect [--note]|release DRAFT`.
- Skill `rf-verify`: judge only from the spans shown; `overstated` when scope, hedging or quantifier exceed the spans; always quote the sentence part and the span part; never use outside knowledge (R-32 spirit).

- [ ] **Step 1: Tests.** Tool list pinned; pass sessions refused; acceptance fixture (pilot-shaped: 3 ideas, 2 groups, 15 sentences scripted for writer and verifier sessions) runs end to end: outline → write → verify → audit → release in pilot; counts by status reported; BibTeX of the draft scope exported.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(writing): verification tools, CLI, rf-verify skill and acceptance`.

## Self-review notes
- The verifier's independence is engineered as for screening (sessions, models) but with one pass; spec ruling 12 leaves dual verification as a later option if the audit rate exceeds the ceiling.
- Status is computed per call with batched support resolution; a 200-sentence draft resolves at most 1,200 supports in 7 queries.

## Later (not v1)

None: every task of this plan is in v1.

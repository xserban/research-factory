# Screening, Calibration, Agreement and Audit Implementation Plan (slice 1, sub-plan 4 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The corpus is screened at title/abstract by two independent Claude passes through `screen_next` / `screen_record`, after a human-labelled calibration set has passed; Cohen's κ is computed overall and per criterion; disagreements and `unsure` go to the human; and the human audits a stratified random sample of agreed decisions, with error rates reported. Amendments mark earlier decisions stale and re-queue them.

**Architecture:** As in plans 1–3: every change is an event, the projection is the only read model, services hold the logic, and statistics are pure functions. A **pass** (`A` or `B`) is opened once per project with a platform-fixed framing, criterion order and recorded random seed. A Claude Code **session joins exactly one pass for life**; this is the independence boundary (session identity ruling below). Screening work is a queue of `Task`s of kind `screen_a` / `screen_b`, each a batch of ≤ 10 records in randomised order, enqueued on demand for every corpus work without a live, non-stale decision in that pass. Calibration items are screened first in each pass; until the human has labelled the calibration set and the pass's calibration sensitivity reaches the mode threshold under the current protocol version, `screen_next` serves no ordinary batch.

**Tech Stack:** as plans 1–3 (Python 3.12, uv, pydantic 2, SQLAlchemy Core, typer, mcp 2.x).

**Spec:** `docs/specs/00-system.md` (§3 `dec_` IDs, §4.2 provenance, §7 session note, §8 queue), `docs/specs/01-rigour.md` (R-16, R-30–R-38, R-39 roles), `docs/specs/slice-1.md` (flow 8–9; acceptance 5, 8, 11, 16, 17, 18, 20 data side, 22; open questions on κ floor, pass independence and session identity). Old spec: `docs/reference/research-factory-old-spec/stages/04-screen.md` (if present) and `RIGOR-MODES.md`. Code origin: `~/Projects/research-factory-old/src/rf/screening.py` (verdicts, `promotes`, qualified criteria, `applicable(stage)`, `validate_answers`, `render_task`) with `tests/test_screening.py`, adapted to events.

## Rulings made in this plan (recorded in `docs/decisions.md`, Task 1)

1. **Session identity — separate sessions, enforced.** A session that has joined pass A can never claim, record or read pass-B work, and vice versa; `screen_agreement` refuses when the two passes share any session or any model. No per-agent claim token. Subagents of one session therefore cannot serve both passes.
2. **Framing and order are fixed by the pass, not chosen.** A: inclusion framing ("does it meet every inclusion criterion?"), criteria in protocol order (inclusions then exclusions by priority). B: exclusion framing ("is there a reason to exclude?"), the same list reversed. The configuration recorded per pass is `(framing, criterion_order, random_seed, sessions, models)`. Because framing differs by construction, "identical configuration" (acceptance 17) means a shared session or a shared model, and both refuse.
3. **Audit minimum** (the requested answer): sample size `n = min(N, max(ceil(audit_fraction · N), audit_minimum))` over the `N` agreed, dual-coded decisions — so every agreed decision is audited when `N ≤ audit_minimum`, and the pilot (≤ 300 records) audits 50 or all. In `pilot` and `systematic`, `protocol_issues` rejects `audit_fraction < 0.02` or `audit_minimum < 50`; `exploratory` may declare less. Strata: `round(0.75 n)` agreed exclusions and the rest agreed inclusions; a short stratum is filled from the other.
4. **Audit error ceiling:** a platform constant, 0.05 false-exclusion rate (`AUDIT_ERROR_CEILING`), advisory in `pilot`, a gate in `systematic` (plan 5 `check`). Not a protocol field: adding a field to `ScreeningPlan` would change every existing `P@` hash.
5. **Calibration thresholds:** sensitivity ≥ 0.9 in `pilot`, ≥ 0.95 in `systematic`, none in `exploratory` (no calibration required). Specificity is reported, never gated (R-31). Calibration is per pass **and protocol version**: an amendment requires recalibration.
6. **Human acts** (calibration labels, disagreement resolution, audit labels) are human-actor events. They enter through the CLI, and `calibration_label` / `audit_record` also accept them over MCP as relayed answers: the event's actor is the configured human with `payload.channel = "mcp"`, and the calling session is barred from joining a pass (and a pass session is barred from these tools), so a screener never sees the answer key.
7. **Visibility:** while either pass has unfinished tasks, `screen_agreement` refuses; afterwards it returns κ and the disagreement list (both verdicts per disputed work). This is the only route by which a pass's decisions reach the other side, and it opens only after both are done (acceptance 8).
8. **Agreement unit:** a work's binary outcome is `promote` (`include`, `cannot-assess`) or `exclude`. `unsure` in either pass, or differing outcomes, is a disagreement routed to the human. Two exclusions citing different criteria agree on the outcome and lower only the per-criterion κ.
9. **Held-out seeds are screened like any record.** Screening tools withhold seed IDs and identifiers but not held-out works' `rf:` IDs, titles or abstracts, which are needed to screen them; nothing in a task marks a work as a seed (worked examples are development seeds only).
10. **Partial dual coding (pilot):** pass B's task set is a recorded random sample of `dual_sample · |corpus|` works (ceil); works outside it stand on pass A alone and are listed as single-pass (promotion gap for plan 5).

## Global Constraints

- All plan-1–3 constraints hold: no model calls; logic in services; append-only events; the projector is the only index writer and handlers are total; validate before writing; `mypy --strict` and ruff pass; coverage ≥ 90 % for `factory.services` and `factory.model`; offline tests, live ones marked `network`.
- Every agent-written event carries model, platform-computed skill (`skill_ref`) and `input_blob` = canonical JSON of the validated tool input (R-04; acceptance 11). Task content blobs are the exact text the agent saw.
- Verdicts: `include`, `exclude`, `cannot-assess`, `unsure` (R-30). Stage for this plan: `title_abstract`; a criterion applies when its `applies_at` is `title_abstract` or `either`.
- Batch size `SCREEN_BATCH = 10`. Lease as in plan 1 (30 min).
- Held-out seeds: never a worked example, never in the calibration set, never named (seed ID, DOI, arXiv ID) in screening-tool output (R-20, acceptance 22).
- Any task that changes tables or handlers increments `PROJECTION_VERSION` by one.
- Branch `plan-4-screening`; commit after each task; stage only your own files; trailer `Co-Authored-By: Claude <Model> 5.5 <noreply@anthropic.com>`.
- Commands run from `platform/` unless stated.

## Review Focus

1. **A held-out seed vanishes from screening because the MCP scrub removes its work ID**, or, conversely, a task reveals that a record is a seed. Expected: the held-out work appears in a batch with its title and abstract; no seed ID, seed DOI/arXiv form or "seed" label appears. → Task 8 `test_held_out_seed_is_screened_without_being_named`.
2. **One Claude Code session (or its subagents) tries to serve both passes**, or a pass-B session calls `screen_agreement` mid-screening to read pass A. Expected: refused with a structured error, nothing written. → Task 4 `test_session_cannot_join_both_passes`; Task 6 `test_agreement_refused_while_tasks_open`.
3. **A quote differs from the abstract only in whitespace, case or a Unicode dash**, or comes from outside knowledge. Expected: whitespace runs are normalised on both sides; everything else must match exactly; a quote not in title or abstract is rejected, and the rest of the batch is recorded. → Task 5 `test_quote_whitespace_normalised_but_case_exact`, `test_batch_records_valid_items_only`.
4. **The protocol is amended mid-screening.** Expected: decisions made stale by the amendment are re-queued in both passes, calibration under the new version is required before further ordinary batches, κ and audit use live non-stale decisions only. → Task 5 `test_amendment_requeues_stale_decisions`; Task 3 `test_amendment_requires_recalibration`.
5. **A work has no abstract.** Expected: the only valid quote source is the title; `cannot-assess` (citing the criterion that cannot be judged) promotes it; it is never silently excluded. → Task 5 `test_missing_abstract_allows_title_quote_and_cannot_assess`.

---

## File Structure

```
platform/src/factory/
  model/screening.py         Verdict, PassLabel, Framing, ScreeningPhase, ScreeningItem, payloads:
                             PassOpened, PassJoined, DecisionRecorded, CalibrationDrawn,
                             CalibrationLabelled, DisagreementResolved, AuditSampled, AuditLabelled
  index/screening.py         tables passes, pass_sessions, decisions, calibration, resolutions, audit
  services/screening_stats.py  pure: cohen_kappa, kappa_by_criterion, sensitivity_specificity,
                             audit_size, draw_audit, audit_error_rates, quote_in
  services/calibration.py    draw_calibration, label_calibration, calibration_status
  services/screening.py      open_pass, join_pass, screen_next, screen_record, live_decisions,
                             stale_screening_decisions
  services/agreement.py      screen_agreement, resolve_disagreement, final_outcomes
  services/audit.py          audit_sample, audit_record, audit_report
  services/protocol_rules.py + audit floor rules (pilot/systematic)
  mcp/server.py              + calibration_label, screen_next, screen_record, screen_agreement,
                               audit_sample, audit_record; narrower scrub for screening tools
  cli/main.py                + calibrate [draw|label], screen [disagreements|resolve], audit [sample|label]
plugin/skills/rf-screen/SKILL.md
```

---

### Task 1: Rulings, screening model and events (pure)

**Files:**
- Modify: `docs/decisions.md` (new entry #37 "Screening independence and audit", status Proposed, rulings 1–10 one line each), `docs/specs/slice-1.md` (mark the κ-floor, pass-independence and session-identity open questions "resolved in plan 4 → decision #37")
- Create: `platform/src/factory/model/screening.py`
- Modify: `platform/src/factory/events/catalog.py` (register the payloads)
- Test: `platform/tests/test_screening_model.py`

**Interfaces:**
- Produces:
  - `class Verdict(StrEnum)`: `INCLUDE="include"`, `EXCLUDE="exclude"`, `CANNOT_ASSESS="cannot-assess"`, `UNSURE="unsure"`; property `promotes -> bool` (include, cannot-assess).
  - `class PassLabel(StrEnum)`: `A`, `B`; `class Framing(StrEnum)`: `INCLUSION`, `EXCLUSION`; `class ScreeningPhase(StrEnum)`: `CALIBRATION`, `SCREENING`; `class Channel(StrEnum)`: `CLI`, `MCP`.
  - `class ScreeningItem(StrictModel)`: `work_id: str`, `verdict: Verdict`, `criterion: str | None` (bare CID, e.g. `EX03`), `quote: str` (min 1), `rationale: str = ""`.
  - Payloads (event types in brackets): `PassOpened(pass_label, framing, criterion_order: Literal["protocol","reversed"], random_seed: int, sample: tuple[str, ...] | None)` [`screening.pass_opened`]; `PassJoined(pass_label, session, model)` [`screening.pass_joined`]; `DecisionRecorded(decision_id, work_id, pass_label, phase, stage, verdict, criterion: str | None` (qualified `P@…:EX03`)`, quote, rationale, protocol_id, task_id, supersedes: str | None)` [`screening.decision_recorded`]; `CalibrationDrawn(protocol_id: str | None, work_ids, random_seed)` [`calibration.drawn`]; `CalibrationLabelled(work_id, verdict: Literal["include","exclude"], criterion: str | None, channel)` [`calibration.labelled`]; `DisagreementResolved(work_id, verdict: Literal["include","exclude"], criterion: str | None, reason: str, channel)` [`screening.disagreement_resolved`]; `AuditSampled(audit_id, work_ids, random_seed, population: int, exclusions: int, inclusions: int)` [`audit.sampled`]; `AuditLabelled(audit_id, work_id, verdict: Literal["include","exclude"], criterion: str | None, channel)` [`audit.labelled`].
  - `DECISION_ID_RE = rf"^dec_{ULID_RE}$"`, `AUDIT_ID_RE = rf"^aud_{ULID_RE}$"`.

- [ ] **Step 1: Write failing tests** — `test_promotes` (`include`/`cannot-assess` True, `exclude`/`unsure` False); `test_exclude_item_needs_criterion_and_rationale` (a `ScreeningItem` model validator: `exclude` with `criterion=None` or `rationale=""` raises; `cannot-assess` with `criterion=None` raises; `unsure` with empty rationale raises; `include` with `criterion` starting `EX` raises); `test_decision_criterion_is_version_qualified` (`DecisionRecorded(criterion="EX03")` raises; `"P@1a2b3c4d:EX03"` passes); `test_payloads_registered` (every type name above is in `default_catalog()`).
- [ ] **Step 2: Run** `uv run pytest tests/test_screening_model.py -v` — FAIL (import error).
- [ ] **Step 3: Implement** the module and catalog registrations; port `Verdict.promotes` from old `screening.py`.
- [ ] **Step 4: Run** — PASS; `uv run mypy --strict src && uv run ruff check`.
- [ ] **Step 5: Commit** — `git commit -m "feat(screening): verdicts, pass and decision events; decision #37"`

---

### Task 2: Screening statistics (pure)

**Files:**
- Create: `platform/src/factory/services/screening_stats.py`
- Test: `platform/tests/test_screening_stats.py`

**Interfaces:**
- Produces:
  - `quote_in(quote: str, title: str, abstract: str | None) -> bool` — whitespace runs collapsed to one space and ends stripped on both sides; otherwise exact (case, punctuation).
  - `cohen_kappa(pairs: Sequence[tuple[bool, bool]]) -> float | None` — `None` when `pairs` is empty or expected agreement is 1.
  - `kappa_by_criterion(pairs: Sequence[tuple[str | None, str | None]], criteria: Sequence[str]) -> dict[str, float | None]` — for each CID, κ over "this pass excluded citing CID".
  - `class Rates(StrictModel)`: `sensitivity: float | None`, `specificity: float | None`, `n_positive: int`, `n_negative: int`; `sensitivity_specificity(pairs: Sequence[tuple[bool, bool]]) -> Rates` with pairs `(human_include, pass_promotes)`.
  - `audit_size(population: int, fraction: float, minimum: int) -> int` — ruling 3.
  - `draw_audit(exclusions: Sequence[str], inclusions: Sequence[str], n: int, rng: random.Random) -> list[str]` — sorted output; exclusions target `math.floor(0.75 * n + 0.5)` (not `round`, which rounds half to even), inclusions the rest, a short stratum backfilled from the other.
  - `class AuditRates(StrictModel)`: `false_exclusion: float | None`, `false_inclusion: float | None`, `weighted: float | None`, `labelled: int`; `audit_error_rates(rows: Sequence[tuple[bool, bool]], pop_exclusions: int, pop_inclusions: int) -> AuditRates` with rows `(agreed_include, human_include)`; `weighted` = stratum rates weighted by population shares.
  - `AUDIT_ERROR_CEILING = 0.05`; `CALIBRATION_SENSITIVITY: dict[RigorMode, float | None] = {exploratory: None, pilot: 0.9, systematic: 0.95}`.

- [ ] **Step 1: Write failing tests**

```python
def test_kappa_textbook_value():
    pairs = [(True, True)] * 20 + [(True, False)] * 5 + [(False, True)] * 10 + [(False, False)] * 15
    assert cohen_kappa(pairs) == pytest.approx(0.4)

def test_kappa_undefined_when_no_variation():
    assert cohen_kappa([(True, True)] * 5) is None and cohen_kappa([]) is None

def test_audit_size_minimum_and_cap():
    assert audit_size(300, 0.02, 50) == 50
    assert audit_size(5000, 0.02, 50) == 100
    assert audit_size(30, 0.02, 50) == 30

def test_draw_audit_three_to_one_with_backfill():
    rng = random.Random(7)
    exc, inc = [f"e{i}" for i in range(100)], [f"i{i}" for i in range(100)]
    drawn = draw_audit(exc, inc, 40, rng)
    assert sum(d.startswith("e") for d in drawn) == 30
    assert len(draw_audit(exc[:5], inc, 40, random.Random(7))) == 40   # short stratum filled

def test_quote_whitespace_normalised_but_case_exact():
    assert quote_in("linear  attention\nfor", "Linear attention for ViT", "We study linear attention for vision.")
    assert not quote_in("Linear Attention", "x", "We study linear attention.")
    assert quote_in("ViT", "Linear attention for ViT", None)
```

  plus `test_sensitivity_specificity` (4 human-include of which 3 promoted → 0.75; empty side → `None`) and `test_audit_error_rates_weighted` (exclusion stratum 1/30 wrong, inclusion 0/10, populations 150/50 → weighted `(150*(1/30)+0)/200`).
- [ ] **Step 2: Run** `uv run pytest tests/test_screening_stats.py -v` — FAIL.
- [ ] **Step 3: Implement.** `draw_audit` samples each stratum with `rng.sample` over the **sorted** inputs so the draw is reproducible from the seed.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(screening): kappa, calibration rates, audit sizing and draw"`

---

### Task 3: Projection tables and calibration (critical: Sonnet review)

**Files:**
- Create: `platform/src/factory/index/screening.py`, `platform/src/factory/services/calibration.py`
- Modify: `platform/src/factory/index/default.py` (register handlers; bump `PROJECTION_VERSION`)
- Test: `platform/tests/test_calibration.py`

**Interfaces:**
- Consumes: `seeds_service.agent_seeds`, `split_is_drawn`, `SeedRole`; `search.list_works()` (corpus); `current_protocol`; Task 1 payloads; Task 2 `sensitivity_specificity`, `CALIBRATION_SENSITIVITY`.
- Produces:
  - Tables: `passes(pass_label PK, framing, criterion_order, random_seed, sample JSON NULL)`, `pass_sessions(session PK, pass_label, model)`, `decisions(decision_id PK, work_id, pass_label, phase, stage, verdict, criterion, quote, rationale, protocol_id, task_id, supersedes, superseded_by NULL, event_id)`, `calibration_items(work_id PK, protocol_id_drawn)`, `calibration_labels(work_id PK, verdict, criterion, channel, event_id)` (last label wins), `resolutions(work_id PK, verdict, criterion, reason, channel, event_id)`, `audits(audit_id PK, random_seed, population, exclusions, inclusions)`, `audit_items(audit_id, work_id, agreed_verdict NULL, human_verdict NULL, criterion, PK(audit_id, work_id))`, `label_sessions(session PK)` (sessions that relayed human labels over MCP).
  - `WORKED_EXAMPLES = 2` per kind. `worked_examples(project) -> list[SeedView]` — the lowest-ID `WORKED_EXAMPLES` development positives and negatives that resolved to corpus works.
  - `draw_calibration(project: Project, actor: Actor, *, random_seed: int | None = None) -> list[str]` — once per project (a second call returns the existing set): resolved development seeds that are not worked examples, plus resolved negative seeds, plus random corpus works to `screening.calibration_size`; held-out seeds' works are never chosen (also not as random fill).
  - `label_calibration(project, actor: Actor, work_id: str, verdict: str, criterion: str | None, channel: Channel) -> str` (event id); refuses a work outside the set, an `EX` criterion absent from the current protocol, and (for `channel=MCP`) a session present in `pass_sessions`.
  - `class CalibrationStatus(StrictModel)`: `drawn: int`, `labelled: int`, `required: bool`, `per_pass: dict[str, Rates]`, `passed: dict[str, bool]`; `calibration_status(project) -> CalibrationStatus` — rates use live `phase=calibration` decisions **under the current protocol version**; `passed[p]` is True when every item is labelled, the pass has a live decision on every item, and sensitivity ≥ threshold (or no threshold).

- [ ] **Step 1: Write failing tests** — `test_calibration_set_includes_dev_seeds_excludes_held_out_and_examples`; `test_calibration_set_size_and_seed_recorded` (size = `calibration_size` when the corpus allows; rebuild yields identical set); `test_label_rejects_unknown_work_and_unknown_criterion` (nothing written); `test_mcp_label_refused_for_pass_session`; `test_calibration_passes_only_above_threshold` (pilot, 10 human includes, pass promotes 9 → passed; 8 → not); `test_amendment_requires_recalibration` (after a semantic amendment `passed["A"]` is False until new calibration decisions exist); `test_exploratory_calibration_not_required`; `test_rebuild_determinism_with_screening_events` (use `tests/helpers.py` rebuild helper).
- [ ] **Step 2: Run** `uv run pytest tests/test_calibration.py -v` — FAIL.
- [ ] **Step 3: Implement** tables and handlers (handlers total: an event for an unknown work is stored, not raised), then the service.
- [ ] **Step 4: Run** — PASS, plus the full suite (projection version bump).
- [ ] **Step 5: Commit** — `git commit -m "feat(screening): projection tables and calibration set"`

---

### Task 4: Passes, session binding and `screen_next` (critical: Sonnet review)

**Files:**
- Create: `platform/src/factory/services/screening.py`
- Test: `platform/tests/test_screening_next.py`

**Interfaces:**
- Consumes: `tasks.create_tasks`, `claim_next`, `TaskSpec`; `current_protocol` (`.ready`, `.spec`, `.protocol_id`); Task 3 `worked_examples`, `calibration_status`, calibration items; `protocol_rules.stale_decisions`, `DecisionRef`, `list_amendments`, `protocol_lineage`.
- Produces:
  - `TASK_KIND = {PassLabel.A: "screen_a", PassLabel.B: "screen_b"}`; `SCREEN_BATCH = 10`.
  - `open_pass(project, actor, label: PassLabel) -> None` — idempotent; framing/order per ruling 2; `random_seed` from `secrets.randbits(32)`; for B with `dual_sample < 1`, `sample` = sorted random draw of `ceil(dual_sample·|corpus|)` works (calibration works always included).
  - `join_pass(project, actor, label) -> None` — writes `PassJoined` once per (session, label); refuses when the session joined the other pass or is in `label_sessions`.
  - `class ScreenBatch(StrictModel)`: `task_id`, `pass_label`, `framing`, `instructions: str`, `protocol_id`, `criteria: list[dict[str, str]]` (id, statement, rule, kind, in pass order, title/abstract-applicable only), `worked_examples: list[dict[str, str]]` (title, abstract, expected verdict, no seed IDs), `records: list[dict[str, str | None]]` (work_id, title, abstract), `phase: ScreeningPhase`.
  - `class ScreenNext(StrictModel)`: `batch: ScreenBatch | None`, `blocked: list[str]` (reasons), `remaining: int`.
  - `screen_next(project, actor, label: PassLabel) -> ScreenNext` — order of checks: protocol ready (R-16) else blocked; `open_pass` + `join_pass`; enqueue (calibration items first, then remaining corpus/sample works lacking a live non-stale decision under any version in this pass and lacking an open/claimed task), each task's records shuffled with `random.Random(f"{random_seed}:{task_index}")`; if calibration is required and not passed for this pass, only calibration tasks are claimable, and `blocked` names why (unlabelled count or sensitivity vs. threshold — rates only, never per-item labels); claim the next task of the pass's kind. Task content (the `ScreenBatch` dump) is the `input_blob`.
  - `live_decisions(project, label: PassLabel | None = None) -> list[DecisionRecorded]` — not superseded; `stale_screening_decisions(project) -> set[str]` via `stale_decisions`.

- [ ] **Step 1: Write failing tests** — `test_screen_next_refused_until_protocol_ready`; `test_session_cannot_join_both_passes` (same session: A then B → structured error, no `pass_joined` for B); `test_label_session_cannot_join_pass`; `test_pass_b_reverses_criterion_order_and_uses_exclusion_framing`; `test_calibration_batches_served_first_and_block_ordinary_batches` (blocked reason mentions labels/sensitivity); `test_batch_order_is_randomised_and_reproducible` (two projects with the same recorded seed give the same order; it differs from sorted order); `test_worked_examples_are_development_seeds_without_ids` (no `SEED`/`NEG` token, no held-out work); `test_pass_b_sample_respects_dual_sample` (pilot 0.2 over 50 works → 10 + calibration works); `test_task_content_is_input_blob` (claimed event's blob equals the batch dump); `test_no_decision_of_other_pass_in_batch`.
- [ ] **Step 2: Run** `uv run pytest tests/test_screening_next.py -v` — FAIL.
- [ ] **Step 3: Implement.** Instructions text per framing is a module constant (exact copy: A — "For each record decide whether it meets every inclusion criterion. When in doubt, include."; B — "For each record look for a reason to exclude it under the exclusion criteria. When in doubt, include."), both followed by "Quote the title or abstract span you rely on; do not use knowledge of the authors, venue or paper beyond this text."
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(screening): passes bound to sessions; screen_next with calibration gate"`

---

### Task 5: `screen_record` — validation, supersession, completion, staleness (critical: Sonnet review)

**Files:**
- Modify: `platform/src/factory/services/screening.py`
- Test: `platform/tests/test_screening_record.py` (port the applicable cases of old `tests/test_screening.py`: unknown criterion, exclusion without criterion, promotion of `cannot-assess`, supersede-not-edit)

**Interfaces:**
- Consumes: Task 4 batch content (from the task's blob), `complete_task`, `skill_ref` via actor, Task 2 `quote_in`.
- Produces: `screen_record(project, actor, task_id: str, items: Sequence[ScreeningItem]) -> BatchResult[str]` (decision IDs). Per item: work is in the task; criterion exists in the task's protocol version and is in the batch's criteria list (applicable at title/abstract); kinds match (exclude → `EX`, include → none or `IN`, cannot-assess → any listed CID); quote passes `quote_in`; Task 1 item rules. The task must be held by this session (pass binding implied). A second decision for the same work and pass sets `supersedes` to the live one. The task completes when every record in it has a live decision under the task's protocol version; `result_refs` = the decision IDs.

- [ ] **Step 1: Write failing tests** — `test_unknown_criterion_rejected_nothing_written` (acceptance 5); `test_exclusion_without_criterion_or_rationale_rejected`; `test_batch_records_valid_items_only` (2 valid + 1 bad → 2 written, `rejected[0].index == 2`); `test_quote_not_in_record_rejected` (acceptance 16); `test_missing_abstract_allows_title_quote_and_cannot_assess`; `test_criterion_not_applicable_at_title_abstract_rejected`; `test_rerecord_supersedes`; `test_task_completes_when_all_records_decided`; `test_record_refused_for_task_of_other_pass_or_session`; `test_agent_decision_carries_model_skill_input_blob` (acceptance 11); `test_amendment_requeues_stale_decisions` (loosen `EX03` → earlier `EX03` exclusions are stale; next `screen_next` serves those works again under the new version).
- [ ] **Step 2: Run** `uv run pytest tests/test_screening_record.py -v` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(screening): screen_record with boundary validation and stale re-queue"`

---

### Task 6: Agreement, κ and human resolution (critical: Sonnet review)

**Files:**
- Create: `platform/src/factory/services/agreement.py`
- Test: `platform/tests/test_agreement.py`

**Interfaces:**
- Consumes: Task 4 `live_decisions`, `stale_screening_decisions`; Task 2 `cohen_kappa`, `kappa_by_criterion`; protocol `screening.kappa_floor`, `kappa_enforced`; `task_counts`-style query of open/claimed tasks per kind.
- Produces:
  - `class PassConfig(StrictModel)`: `pass_label`, `framing`, `criterion_order`, `random_seed`, `sessions: list[str]`, `models: list[str]`.
  - `class Disagreement(StrictModel)`: `work_id`, `a: DecisionView`, `b: DecisionView` (`verdict`, `criterion`, `quote`, `rationale`), `reason: Literal["outcome","unsure"]`.
  - `class Agreement(StrictModel)`: `passes: list[PassConfig]`, `n_dual: int`, `kappa: float | None`, `kappa_by_criterion: dict[str, float | None]`, `kappa_floor: float | None`, `below_floor: bool`, `enforced: bool`, `disagreements: list[Disagreement]` (unresolved only), `single_pass: list[str]`, `cannot_assess_rate: dict[str, float]` (R-38, per criterion over pass decisions).
  - `screen_agreement(project, actor) -> Agreement` — refuses (structured errors) when: either pass has open or claimed screening tasks or unscreened works remain (so no pass session can read the other pass mid-screening); passes share a session; passes share a model (ruling 1). Only live, non-stale `phase=screening` decisions of the current protocol version count; calibration decisions are excluded.
  - `resolve_disagreement(project, actor, work_id, verdict, criterion, reason, channel) -> str` — human actor only; work must be in the unresolved list (or `unsure` in a single-pass work); exclusion needs an `EX` criterion of the current protocol.
  - `class Outcome(StrEnum)`: `INCLUDED`, `EXCLUDED`, `PENDING`; `final_outcomes(project) -> dict[str, Outcome]` — resolution, else agreed outcome, else single-pass A outcome (`unsure` → pending). Plan 5's PRISMA reads this.

- [ ] **Step 1: Write failing tests** — `test_agreement_refused_while_tasks_open` (acceptance 8 isolation); `test_agreement_refused_when_passes_share_session_or_model` (acceptance 17; build the shared state by writing `PassJoined` events directly through `project.record`, since the service already prevents it); `test_kappa_and_disagreements_listed` (acceptance 8: 4 works, one outcome disagreement, one `unsure` → 2 disagreements, κ matches `cohen_kappa`); `test_different_exclusion_criteria_agree_on_outcome`; `test_below_floor_flagged_advisory_in_pilot`; `test_resolution_removes_disagreement_and_sets_outcome`; `test_resolution_requires_human_actor`; `test_single_pass_works_listed`; `test_cannot_assess_rate_per_criterion`.
- [ ] **Step 2: Run** `uv run pytest tests/test_agreement.py -v` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(screening): agreement, kappa per criterion, human resolution"`

---

### Task 7: Audit sample, labels, error rates, and audit floor rules

**Files:**
- Create: `platform/src/factory/services/audit.py`
- Modify: `platform/src/factory/services/protocol_rules.py` (pilot and systematic gaps: `screening.audit_fraction` < 0.02, `screening.audit_minimum` < 50)
- Test: `platform/tests/test_audit.py`, `platform/tests/test_protocol_rules.py` (+2 cases)

**Interfaces:**
- Consumes: Task 6 agreed dual-coded works (both passes agree, no resolution needed); Task 2 `audit_size`, `draw_audit`, `audit_error_rates`, `AUDIT_ERROR_CEILING`.
- Produces:
  - `audit_sample(project, actor, *, random_seed: int | None = None) -> AuditSampled` — refused until `screen_agreement` would succeed; one open audit at a time (a new one only after a protocol amendment changes the agreed set); `audit_id` `aud_…`.
  - `audit_record(project, actor, audit_id, work_id, verdict, criterion, channel) -> str` — human actor; work must be in the sample; MCP channel barred for pass sessions (as calibration).
  - `class AuditReport(StrictModel)`: `audit_id`, `sample_size`, `labelled`, `rates: AuditRates`, `ceiling: float`, `above_ceiling: bool`, `enforced: bool` (systematic), `criteria_implicated: list[str]` (agreed-exclusion criteria the human overturned); `audit_report(project) -> AuditReport | None`.

- [ ] **Step 1: Write failing tests** — `test_audit_draws_minimum_fifty_three_to_one` (acceptance 18: 120 agreed exclusions + 40 agreed inclusions → 50 drawn, 38 exclusions); `test_audit_all_when_fewer_than_minimum`; `test_audit_refused_before_agreement`; `test_audit_record_rejects_work_outside_sample`; `test_error_rates_reported_and_ceiling_flagged` (2 overturned exclusions of 38 → above 0.05, `criteria_implicated` lists their CIDs); `test_audit_sample_reproducible_on_rebuild`; protocol rules `test_pilot_rejects_audit_minimum_below_50`, `test_exploratory_allows_small_audit`.
- [ ] **Step 2: Run** `uv run pytest tests/test_audit.py tests/test_protocol_rules.py -v` — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(audit): stratified audit sample, human labels, error rates"`

---

### Task 8: MCP tools, CLI, status and acceptance

**Files:**
- Modify: `platform/src/factory/mcp/server.py`, `platform/src/factory/cli/main.py`, `platform/src/factory/services/project.py` (status lines)
- Test: `platform/tests/test_mcp_screening.py`, `platform/tests/test_cli.py` (+cases), `platform/tests/test_acceptance_screening.py`

**Interfaces:**
- MCP (all take `project`; agent tools also `role`, `model`, `skill`, built into the actor by `make_agent_actor`):
  - `screen_next(project, pass_label: "A"|"B", role, model, skill)` → `ScreenNext`.
  - `screen_record(project, task_id, items: list[dict], role, model, skill)` → `BatchResult`.
  - `screen_agreement(project)` → `Agreement`.
  - `calibration_label(project, work_id: str | None, verdict: str | None, criterion: str | None)` → with no `work_id`: the next unlabelled calibration record (work_id, title, abstract) and counts; with one: records the human's label (`channel=mcp`, human actor) — draws the set on first use.
  - `audit_sample(project)` → sample (work IDs, titles, the agreed verdict) and counts; `audit_record(project, audit_id, work_id, verdict, criterion)` → event id.
- Scrub: screening tools (`screen_next`, `screen_record`, `screen_agreement`) withhold only held-out seed IDs and stated/normalised identifiers (DOI, arXiv, OpenAlex), **not** `seed.work_id` (ruling 9); every other tool keeps `_held_out_tokens`. Implement as `_held_out_tokens(project, include_work_ids: bool = True)`.
- CLI: `factory calibrate draw|label <work> <verdict> [--criterion]`, `factory screen disagreements`, `factory screen resolve <work> <verdict> [--criterion] --reason`, `factory audit sample|label <audit> <work> <verdict> [--criterion]|report`. Status adds: calibration labelled/drawn and pass result, per-pass decided/remaining, κ (when available), unresolved disagreements, stale decisions, audit labelled/sample and false-exclusion rate.

- [ ] **Step 1: Write failing tests** — `test_held_out_seed_is_screened_without_being_named` (held-out seed's work appears in some batch with title/abstract; no seed ID or seed DOI/arXiv form in any response); `test_screen_tools_require_model_and_skill` (unknown skill → structured error); `test_screen_record_partial_success_over_mcp`; `test_calibration_label_flow_over_mcp`; `test_cli_resolve_and_audit_label`; and `test_acceptance_screening.py`: one fixture project (pilot, ~40 works, protocol ready) driven through two server instances (two sessions) with scripted verdicts — calibration → both passes → `screen_agreement` (acceptance 8, 17) → resolve → `audit_sample` / `audit_record` (acceptance 18) → `factory rebuild` gives the same state hash (acceptance 1).
- [ ] **Step 2: Run** `uv run pytest tests/test_mcp_screening.py tests/test_acceptance_screening.py tests/test_cli.py -v` — FAIL.
- [ ] **Step 3: Implement** thin tool/CLI bodies (parse → service → format), as in existing tools.
- [ ] **Step 4: Run** the full suite, `uv run mypy --strict src`, `uv run ruff check`, coverage `uv run pytest --cov=factory.services --cov=factory.model --cov-fail-under=90`.
- [ ] **Step 5: Commit** — `git commit -m "feat(mcp): screening, calibration and audit tools; CLI and status"`

---

### Task 9: Plugin skill `rf-screen`

**Files:**
- Create: `plugin/skills/rf-screen/SKILL.md`
- Modify: `platform/tests/test_plugin.py` (add `"rf-screen"` to the resolved-skill list)

Content (prose; consult superpowers:writing-skills): run one pass per Claude Code session and say which; never start pass B in a session (or subagent) that ran pass A or relayed human labels; use a different model for pass B; loop `screen_next` → judge each record only from its title and abstract → `screen_record`; quote the exact span; `cannot-assess` when the text lacks the information, `unsure` only when genuinely borderline; never retry a rejected item by paraphrasing the quote — re-read the text; stop when `remaining` is 0 or `blocked` is non-empty, and report blocked reasons to the researcher (calibration is a human step).

- [ ] **Step 1–4:** extend the test → fail → write the skill → pass.
- [ ] **Step 5: Commit** — `git commit -m "feat(plugin): rf-screen skill"`

---

## Self-review notes

- **Spec coverage:** four verdicts, promotion (R-30, R-31) → Tasks 1, 5; verified quotes (R-32, AC 16) → Tasks 2, 5; two passes with engineered, recorded independence (R-33, AC 8, 17) → Tasks 4, 6; statelessness, randomised order, worked examples (R-34) → Task 4; calibration gate (R-35, AC 18) → Tasks 3, 4; κ per criterion, floor advisory/enforced, disagreements to human (R-36) → Task 6; audit ≥ 2 % min. 50, 3:1, error rates (R-37, AC 18) → Tasks 2, 7; `cannot-assess` rate (R-38) → Task 6; protocol must be ready (R-16) → Task 4; stale decisions applied (deferred from plan 3) → Tasks 4–5; boundary validation (AC 5) → Task 5; agent provenance (AC 11) → Task 5; held-out seeds (AC 22) → Tasks 3, 4, 8; skill → Task 9.
- **Deferred to plan 5:** `check` gates on κ floor (systematic), audit ceiling, single-pass works and missing audit (AC 20); PRISMA screening counts from `final_outcomes`; `report_methods` disclosure of pass configuration, agent-reported `model`, MCP-relayed human labels; `search_chase`; R-35's per-batch recalibration beyond "per protocol version".
- **Review tiers** (memory `sdd-review-tiers`): Tasks 3–6 are critical (screening) → Sonnet review; others Haiku; Task 9 Sonnet-written, final review only.

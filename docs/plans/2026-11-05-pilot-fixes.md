# Pilot Fixes Implementation Plan (backlog triage, plan PF)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Proposed 2026-11-05 (backlog triage, `2026-11-05-backlog-triage.md`).** Items marked [confirm] await the researcher.

> **Dependencies.** Base `d66387f` or later. Independent of PI and MS. Paths are relative to `platform/`.

**Goal:** Fix the parked findings that a first real run is likely to hit: wrong, silent or stuck behaviour at a few hundred works. Scale-only and cosmetic findings are in plan SH.

**Basis:** Each finding was checked against the code on 2026-11-05; the row ids are those of the triage table. Iterate lines 5, 9, 10, 13, 16c, 17a, 26, 28 to 31, 33, 40, 51, 61, 65, 84, 113 to 118, 123 to 125, 127; I18f, I18r; IDEA-20. Decisions 37, 38, 52, 77, 79, 84, 86, 91, 92, 95, 96. R-05, R-15, R-24, R-25, R-51.

**Projection:** Task 3 bumps `PROJECTION_VERSION` only if the recommended option adds a table; as written it does not. Task 2 adds one event, with a fold on an existing table, and bumps by one.

## Rulings made in this plan

1. **Merged twins in screening (IDEA-20) [confirm].** The finding is wider than the backlog says: `stage_population` reads `corpus_work_ids`, which ignores merges, so an absorbed record stays queued and sampleable even when `dedup_run` is current, and `final_outcomes` then reads the primary only. Both twins cost a screening decision, which decides nothing. Options: (a) record the condition only; (b) make the extension a no-op until dedup is current, which alone does not fix the queue; (c) leave absorbed works out of `stage_population`, and hold both the extension and new batches until `dedup_run` is current. **Recommended: (c).** Decisions already recorded on an absorbed work stay, and `merge-verdict-conflict` keeps reporting them. A reverted merge returns the work to the population.
2. **Verdict spans (iterate line 127) [confirm].** The verdict fold reads `in_spans`, so tightening it would stop old events folding. The minimum length of 12 characters applies at write time only, in `verdict_issues`' caller, and the fold is untouched. The same rule holds for `is_single_sentence` (line 113).
3. **Verifier reads (line 125) [confirm].** A session holding a verification task is refused `draft_status` and `draft_render` for that draft. Its unit holds the sentence and spans (R-51).
4. **Audited-agent wording.** Decision 84 item 5 rules `audited-agent` on the population, so a drawn audit marks earlier acts as audited though none need be sampled or labelled. The behaviour stays; the `autonomy_of` docstring, which says "whose audit sample contains the act", and the methods sentence are corrected to say "after an audit was drawn at the gate".

## Global Constraints

- Corrections supersede; nothing here rewrites an event. A fold change that alters old logs needs a version or stays at write time.
- Held-out rules as in the handoff. Neither Task 1 nor Task 3 filters a work by held-out status.
- Each task names its tests below; they are written when the plan's test pass runs.

## Review Focus

1. Task 3: population changes must not shift pass seeds for a project with no merges (golden).
2. Task 2: a re-resolve keeps the extraction id, and a rejection carried across it applies only to the same work.
3. Task 5: a report for a project with no notices is byte-identical.

## File Structure

Modify `inbox/links.py`, `model/inbox.py`, `services/references.py`, `services/reference_resolve.py`, `services/snowball.py`, `services/trace.py`, `services/check.py` (rule calls), `services/modules/retrieval.py`, `services/screening.py`, `services/calibration.py`, `services/evidence_report.py`, `services/methods.py`, `services/gates.py`, `services/finders.py`, `regions/evaluate.py`, `mining/kinds.py`, `services/miner_report.py`, `services/hypothesis_review.py`, `writing/checks.py`, `services/drafts.py`, `services/supports.py`, `services/draft_verify.py`, `mcp/server.py` (Task 7 guards and Task 8's resume, in place, no new tool), `cli/main.py` (`references_app` only).

### Task 1: Link parsing

*Tier: standard.*

**Files:** `inbox/links.py`, `model/inbox.py`.

**Changes:** A bare DOI drops `?` and `#` tails as a URL does. Percent-encoded DOIs are decoded once before the pattern, and the ad hoc `rstrip` becomes the shared `_TRAILING_PUNCTUATION` rule. `_OLD_ARXIV` requires a known archive prefix. The stored link drops query tokens. `identifier_version` is refused for non-arXiv kinds; `identifier_value` is bounded; the `anchor` note's docstring states that it is not a quote.

- [ ] **Step 1:** Implement. **Step 2:** Commit `fix(inbox): consistent link normalisation`.

**Tests (later):** table of link forms, including `%2F`, `?utm=`, path-like strings; old items replay unchanged.

### Task 2: Reference retries and silent gaps

*Tier: critical (links, snowball rounds). Bumps the projection.*

**Files:** `services/references.py`, `services/reference_resolve.py`, `services/snowball.py`, `services/trace.py`, `services/check.py`, `services/modules/retrieval.py`, `cli/main.py`, `mcp/server.py` (nothing new beyond `references_extract`'s reply).

**Interfaces:**
- Event `reference.re_resolved` (`extraction_id`, `matcher_version`, `ordinals`), human or agent; `re_resolve(project, actor, *, work_ids=None, states=("source-error",)) -> ReResolveSummary`. Keeps the extraction id. A new `MATCHER_VERSION` is served the same way (line 29). CLI `factory references re-resolve [--work W …] [--state S]`. `references_extract` with a `re_resolve` flag is the agent's route.
- A carried rejection applies only when the new link names the rejected work (line 30).
- `_has_document` treats a raw-missing document as `no-document`, listed and counted, so a round is not blocked (line 26).
- Check `chase-declared-not-run` when the plan declares a round and none ran (line 31).
- `trace._work` falls back to `reference_links` for an unretrieved no-source work (line 28).

- [ ] **Step 1:** Implement, bump. **Step 2:** Commit `fix(references): retry source errors; carried rejections name their work; declared rounds are checked`.

**Tests (later):** source-error link retried and resolved; rebuild identical; rejection not carried to another work; raw-missing round settles; finding fires and clears; trace of a no-source work.

### Task 3: Merged records in screening

*Tier: critical (screening, PRISMA, decision 37). Ruling 1 [confirm].*

**Files:** `services/calibration.py`, `services/screening.py`.

**Interfaces:** `stage_population` subtracts `active_merges`' absorbed ids. `dedup_current(project) -> bool`: no corpus work is newer than the last `dedup_run`. `screen_next` returns `blocked: "run dedup_run"` and `_extend_sample` writes nothing while it is false. `screen_record` validates every item before marking the answered set (I18f).

- [ ] **Step 1:** Implement. **Step 2:** Commit `fix(screening): an absorbed record is not screened; batches wait for dedup`.

**Tests (later):** near-duplicate served once; a revert returns it; extension waits; golden seeds without merges; PRISMA unchanged; `test_chased_duplicate_is_merged_not_rescreened` extended past identity collapse.

### Task 4: Evidence report

*Tier: standard.*

**Files:** `services/evidence_report.py`.

**Changes:** Direction is resolved per metric, not per group, so two metrics with stated directions do not read `direction-unknown` (line 13c). The neutral markers of the report and `check` fire on one shared condition (13a). A kept retraction with a pending correction leaves frontiers until assessed (33a). A claims-only excluded work is listed, and an expression of concern reads as a concern, not a retraction (33b).

- [ ] **Step 1:** Implement. **Step 2:** Commit `fix(evidence): direction per metric; excluded works listed with their reason`.

**Tests (later):** one case per change; report golden without notices.

### Task 5: Methods wording

*Tier: light.*

**Files:** `services/methods.py`, `services/gates.py`, `services/prisma.py`.

**Changes:** The "Screening decisions" sentence lists the models of screening events only, with a separate sentence for the rest (I18r). `recall_held_out_admitted` becomes `int | None`, withheld as `None` (line 5). Ruling 4's wording. `mechanisms.get(first, CHASE_BACKWARD)` raises a `check` finding rather than defaulting (line 17a).

- [ ] **Step 1:** Implement. **Step 2:** Commit `fix(methods): each sentence names what it counts`.

**Tests (later):** models per sentence; withheld reads as null in JSON; golden for a slice-1 project updated only where the sentence was wrong.

### Task 6: Finders, regions and miners

*Tier: standard.*

**Files:** `services/finders.py`, `regions/evaluate.py`, `mining/kinds.py`, `services/miner_report.py`, `services/extraction.py`.

**Changes:** A gap cell states the comparability keys it aggregates (line 40c). Confirmation refuses any session that proposed the pair, not only the first (40b). `_cites` joins the corpus, so a `cited` region holds no probe-only work: first confirm whether such targets reach `graph_edges` (line 51; reported unverified). A title reference with no year in its quote widens by the citing work's year (line 61). `verification_rate` counts rejected submissions, through a count on an existing event if one fits, else a small new event, which then bumps the projection (line 84).

- [ ] **Step 1:** Implement. **Step 2:** Commit `fix(finders,mining): gap keys stated; re-proposer cannot confirm; rate counts rejections`.

**Tests (later):** one case each.

### Task 7: Drafts

*Tier: standard (R-51). Rulings 2, 3 [confirm].*

**Files:** `writing/checks.py`, `services/drafts.py`, `services/supports.py`, `services/draft_verify.py`, `mcp/server.py`.

**Changes:** `_QUANTIFIER_RE` catches hyphenated forms such as `best-performing` (line 114). A slot task accepts sentences of its own section only (115). `_refuse` carries group ids and authors, so a stale cell reads as stale and a stale support still guards structural sentences (117, 118). A blob is stored only after one item passes (116). Over-long titles and reasons are refused, not cut (123). `[[/]]`, `[[UNSUPPORTED` and `[@key]` are refused in sentence text (124). Masking of initials before `et al.` keeps the boundary, at write time only (113). Rulings 2 and 3.

- [ ] **Step 1:** Implement. **Step 2:** Commit `fix(writing): stale supports read as stale; slot and marker guards; verifier reads`.

**Tests (later):** each case; a new replay test proves old logs fold unchanged; guard-removal proof for ruling 3.

### Task 8: Critic resume

*Tier: light.*

**Files:** `services/hypothesis_review.py`, `mcp/server.py`.

**Changes:** `hypothesis_review_next` re-serves a task the session already holds, removing the 30-minute wait (line 65).

- [ ] **Step 1:** Implement. **Step 2:** Commit `fix(hypotheses): a critic resumes its held review`.

**Tests (later):** resume returns the same task; another session still gets none.

## Self-review notes

- Line 22 (import) and line 80 are in PI; line 109 and 121 are in MS; line 89b is in EQ.
- Line 16c (incremental dedup against blocked pairs) was reported unverified. If the test written for Task 3 shows a difference, it joins this plan.
- Task 2's `mcp/server.py` edit changes one tool's arguments, not the tool list.

## Later (not v1)

None.

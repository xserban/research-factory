# Plan: slice 8, suggest and select, with the pilot's factory gaps

**Spec:** `docs/specs/slice-8-develop.md` (draft accepted 2026-11-07). **Backlog:** IDEA-42 (ranker), IDEA-43 (capped forward snowballing). **Pilot record:** `~/Documents/research-factory-pilot/demo-log.md`, `review-protocol.md` v1.0.
**Status:** validated by the researcher, 2026-11-07: all phases, base `land-wave2`, ranker with embeddings now; phase A started.

## Base and working method

- **Branch** `plan-8-suggest-select` from `land-wave2` (03ff593), which holds the human channel (`index/human_channel.py`) and MCP elicitation (`mcp/elicit.py`) this slice needs. Cherry-pick 8c6da39 (probe fixes) first. `land-wave2` is unmerged and unrun; this branch inherits that.
- **Agents:** Sonnet at most, never Opus; `model` set on every call; 2 or 3 at a time; one worktree per task group. `rf-builder` (Haiku) for data and wiring tasks, `rf-builder-critical` (Sonnet) for events, folds, screening, probe and held-out handling, `rf-reviewer` (Sonnet) once per phase.
- **Testing is paused** by the researcher: every task writes its tests, runs `ruff` and `mypy --strict` only, and is listed in `untested-work-during-pause`. The acceptance in phase G is a live run on the pilot, not the test suite.
- **Landing checklist** per task: `@server.tool()` tails, tool pin, `OMITTED_WHEN_EMPTY`, module list, `presets.py`, catalog, check rules, `TOOL_PERMISSIONS` in `services/access.py`; record sites inside `project.writing()`, no network inside the lock.
- **Decisions** (proposed, numbered at merge): suggest and select (events, binding, human channel); ranker uses a local embedding model (researcher, 2026-11-07); forward snowballing cap.

## Phase A: suggest and select (critical)

| Task | What | Tier |
|---|---|---|
| A1 | Model: `DecisionSuggested` (`decision_id`, `level`, `subject`, `explanation`, `items[]` with `item_id`, `text`, `grounds[]`, `recommended`), `DecisionSelected` (`selected[]`, `added[]`, `note`, `reconstructed`), `DecisionSuperseded`. Levels: goal, questions, plan, seeds, probe, protocol. Unique item ids; `recommended` refused on research subjects. | critical |
| A2 | Catalog, fold and index: tables `decisions`, `decision_items` (status Proposed, Validated, Rejected, Added). Guards: a selection whose actor is not human, or forged through the elicit channel, changes nothing; a selection naming an unknown item changes nothing; a superseded set keeps its rows. | critical |
| A3 | Service `services/decisions.py`: suggest, select, supersede, list, view; validation at the boundary; held-out seeds never appear in items (R-20). | critical |
| A4 | MCP: `decision_suggest` (agent), `decision_select` (human, through elicitation; refused without it), `decision_list`, `decision_view`; permissions rows. | builder |
| A5 | CLI: `factory decide list`, `show`, `select` (tick by item id, add text, note); `--reconstructed` for backfill. | builder |
| A6 | `QuestionSpec.sub_questions` (`SQ1`...), optional with a default so old events fold unchanged; criteria `parent` may name an `SQn`; `rf-frame` writes them. | critical |
| A7 | Binding: `question_record`, `seed_add`, `probe_run`, `protocol_record` take `decision_id`; in `pilot` and `systematic` they are refused unless that decision has a selection at the matching level. Whether the act matches the selection is a check rule, not a refusal. | critical |
| A8 | Check rules: `record-without-selection`, `selection-not-acted`, `ungrounded-item`, and the computed share of selections that followed a recommendation. | builder |
| A9 | Render: `factory develop render --level <level>` writes Markdown from the events; `document.rendered` records the blob. Goal and plan, which have no other record, live only here. | builder |
| A10 | Skills: new `rf-develop` (goal as OKR, questions, plan, one level at a time); `rf-frame`, `rf-probe`, `rf-protocol` and `rf-run` use the loop: explain the step, suggest grounded items, wait for the selection. | builder |

## Phase B: probe gaps found in the pilot

| Task | What | Tier |
|---|---|---|
| B1 | Recall over testable seeds: untestable seeds are listed, not counted as misses, per source and pooled. Threshold logic unchanged otherwise. | critical |
| B2 | Sample titles: each measured query archives a small random sample (default 20) of titles, outside the corpus and PRISMA. | critical |
| B3 | Overlap estimate for OpenAlex and arXiv: OpenAlex hits hosted on arXiv, reported beside the per-source counts. | builder |
| B4 | Term suggestions drop generic academic words ("introduce", "driven", "demonstrate"...). | builder |
| B5 | The probe accepts `listed_since` for arXiv, as the watch does. | builder |

## Phase C: extraction pack

| Task | What | Tier |
|---|---|---|
| C1 | Pack `ai-research-system` v1: one row per system and stage; the 15 fields of protocol section 7 and `self_reported`; evidence grade as an enum A to F; row key fields `system`, `stage`. | builder |

## Phase D: ranker v1 (IDEA-42)

| Task | What | Tier |
|---|---|---|
| D0 | Decision entry (proposed): a local embedding model may rank, never judge or exclude; it runs offline from supplied weights (as docling, decision 49), behind an optional extra; model name, version and weights hash are recorded. Choice of model by the researcher. | builder |
| D1 | Embedding similarity of title and abstract to the development seeds only (never held-out, R-20), deterministic for fixed weights. Event `ranking.computed` (corpus snapshot, model and weights hash, parameters, order). | critical |
| D2 | `screen_next` serves in ranked order when a ranking exists; the protocol's screening plan gains a stopping rule (`stop_after_consecutive_excludes`); PRISMA reports records left unscreened after the stop. | critical |

## Phase E: capped forward snowballing (IDEA-43)

| Task | What | Tier |
|---|---|---|
| E1 | `SnowballPlan` gains `forward_core_only`, `forward_topic_filter`, `forward_max_per_work`; human event marking a work core. | critical |
| E2 | A forward round queries `cites:W` plus the topic filter per core work, ranks citing works with D1, takes at most N each, and reports the number not taken. | critical |

## Phase F: backfill

| Task | What | Tier |
|---|---|---|
| F1 | From the demo log, prepare the pilot's decisions as suggestion sets (agent) and a checklist of `factory decide select --reconstructed` commands for the researcher. | builder |

## Phase G: acceptance on the pilot

1. Researcher runs the backfill checklist.
2. Record the protocol v1.0 through the loop, with the new pack, the ranker and the forward cap.
3. PRESS review by an independent Sonnet agent; the researcher answers each finding; freeze.

## Order

A1 to A3 in sequence; then A4 to A10, B, C and D1 in parallel groups of 2 or 3; D2 after D1; E after D1; F after A; G last. One review per phase.

## Not in this plan

merging `land-wave2` to `main` (needs the researcher's approval); running the test suite (paused).

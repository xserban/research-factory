# Papers chat: ask and spar with a selection of papers, with verified citations (IDEA-88)

Status: plan, revised 2026-11-18 after the researcher's rulings of 2026-11-17/18; not started. Replaces the first version of this file (2026-11-17, Ask only).
Design note: `docs/design-note-corpus-search-2026-11-17.md` (main working tree; to be committed with this plan). Test sets: `data/projects/agentic-science/ops/testset-b-2026-11-17/` (B1, B2), `docs/testset-b3-drafts-2026-11-17.md` (B3).
Depends on: `document/quotes.py` (`quote_in_element`; IDEA-85 first), `document/anchors.py`, `services/document_read.py`, `services/work_layers.py`, `services/site_explorer_page.py`, `services/site_server.py` (write path with token, as `site_feed.py` and `site_queue.py`), `services/mining.py` (final mined rows), the lineage graph services, `mcp/server.py`. Decisions 37 (5, 9), 49, 83, 116, 120, 127. Backlog: IDEA-88 (this), IDEA-85, IDEA-53, IDEA-87.

## 1. What the researcher gets

A **Chat** page in the hub. The researcher picks papers (in the explorer: a layer, a filter, a hand-picked list), types in a chat box, and a running Claude Code session answers on the page. Two kinds of message:

- **Ask** (NotebookLM-like): "Which systems let the human steer at ideation?" The answer cites each statement with paper, anchor and a quote the platform has checked.
- **Spar**: "LLM judges are reliable enough to replace expert review of research ideas." The answer is an **argument sheet**: arguments against (first), for, and qualifying, each with checked quotes; a coverage line (which papers were read in full, which by profile, which sources were unavailable); Claude's balance, labelled as judgement.

Before reading, Claude suggests papers outside the selection that bear on the message (from the paper profiles and the text index), with the reason; the researcher adds or skips them. The selected papers are then read **in full**.

The platform never calls a model: the page posts the message, the Claude Code session reads it through an MCP tool, works with the factory's tools and posts the reply back.

## 2. Rulings (researcher, 2026-11-17 and 2026-11-18)

| # | Ruling |
|---|---|
| 1 | Not retrieval alone: profiles of all mined data + an index of all core text **suggest** papers; the chosen papers are **read in full**; arguments carry checked quotes. |
| 2 | Spar: arguments **against** are written first; when a sheet feeds a lead, a **separate session** writes the case for. |
| 3 | Spar modes: **Explore** (at most 15 papers read in full, then Claude asks) and **Prepare** (every candidate in full, cost estimate first). |
| 4 | Default scope: the **core** layer. |
| 5 | Ask: same pipeline, lighter; not recorded unless the researcher saves it. |
| 6 | Paper profile = all mined rows of a paper (m-summary, label miners, the eight technique miners, **m-claims**), compact. |
| 7 | **m-claims** (registered 2026-11-18): findings, mechanisms, limitations, negative results, failure analyses each paper establishes from its own work; ≤ 12 per paper, limits always kept; absence row; pass A Sonnet + audit; second pass after IDEA-53; a core miner reusable by other products. |
| 8 | Hypothesis → miner categories: Claude proposes a tick list with counts, the researcher ticks. |
| 9 | Text index v1: **keyword** (FTS5) over **passages** (not single anchors; 52 % of anchored paragraphs have < 15 words); meaning-based search later, after evaluation. |
| 10 | Tiers: 1 full text (selected, ticked category, or ≥ 2 sources), 2 partial (one source), 3 profile only (every other in-scope paper; promoted if relevant). |
| 11 | UI: **hub chat page** forwarding to a running Claude Code session; Claude suggests unselected papers, the researcher decides. |
| 12 | Evaluation: B1 (50 known items), B2 (12 planted contradictions), B3 (researcher, 10–15); target ≥ 80 % of expected papers among candidates, per part; researcher rates ~30 arguments. |

## 3. Pieces reused

- **Anchored text** and `document_read` (pages, stable anchors, pinned conversion).
- **Quote check** `quote_in_element` (normalised substring of one block). Agents copy Markdown, the check compares plain text: IDEA-85 must be fixed first (observed again 2026-11-17 on `&amp;`).
- **Layers** (`layer_of`, explorer dimension zero) and the explorer's filters.
- **Mined rows** (final rows per miner and work, with anchors and quotes); technique miners carry `status`, `evidence`, `parameters` per technique.
- **Lineage graph** (stated/confirmed edges) for neighbours of candidates.
- **Hub server write path**: token-gated POST endpoints already used by the feed and queue pages.
- **Held-out handling** (decision 37.9, `held_out_tokens`): works are corpus; seed identity is withheld.

## 4. Architecture

### 4.1 Selection
`SelectionSpec {layers, filters, include, exclude, population}` → `resolve_selection` returns works with a default conversion (sorted), exclusions with reasons, size (characters, estimated tokens, stated constant) and a digest. The hub chat page saves the current explorer selection as a **named selection** (sidecar, see 4.7) so the session can resolve it; a saved sheet stores the spec and digest.

### 4.2 Paper profile
`paper_profile(work_ids)`: per work, a compact computed view of final rows only: title line; m-summary fields; one line per label miner; technique names per stage with status and evidence; m-claims statements as quotes with type, about, direction, evidence type, strength. Quotes of label and technique rows are omitted (fetched when cited). The size per work is measured on the pilot (raw mined output today: median ~52k characters per work, including both passes and superseded rows); if the core layer's profiles exceed one context, profile reading is batched.

### 4.3 Text index (keyword v1)
A rebuildable sidecar file (not the events index; its input is blobs): passages = runs of consecutive elements inside one section, packed to N words (start 250, set by evaluation), never across a heading; each passage records its anchors; indexed text = `title › section path` (own column) + passage text. Excluded: number-only elements, a fixed boilerplate list, bibliography entries. Keyed by `markdown_hash` and chunker version; stale conversions dropped. `corpus_search(selection|scope, queries[], limit, per_work_limit)`: ranked passages with work, anchors, section path, text and rank; query syntax validated; ties by work id then anchor. Search ranks, never judges.

### 4.4 Candidate suggestion (the funnel)
`chat_candidates(message_kind, scope, selection, ticked_categories[], queries[], claim_filter?)`: the union of works proposed by (a) the selection, (b) ticked miner categories, (c) lineage neighbours (depth 1) of (a)+(b), (d) keyword hits, (e) m-claims rows matching the claim filter; each work with the sources that proposed it and its computed tier (ruling 10); the works outside the selection listed as **suggestions** with their reasons. Claude reads the profiles of tier-3 works and may promote them (recorded with a reason). Sources not available (no index, a work not yet mined by m-claims) are named.

### 4.5 Reading and verification tools
`chat_sections(work_id)` (outline), `chat_read` (= `document_read`), `chat_mined(selection, miner|taxonomy, category?)` (final rows with anchors and quotes, calibration state, exploratory mark), `chat_verify(items)` (each `{work_id, anchor, quote}` → accepted, or `anchor-missing`, `quote-not-in-anchor`, `no-conversion`; conversion id and markdown hash used).

### 4.6 Argument sheets (Spar)
Events (names provisional; decision row needed): `sheet.opened` (hypothesis text and version, mode, scope, selection spec and digest, ticked categories with miner versions, queries), `sheet.candidates_recorded` (the computed candidate table plus promotions and researcher's add/skip of suggestions), `sheet.argument_recorded` (stance against/for/qualifies; kind finding/mechanism/analogy/limitation/conflicting-result; claim; conditions; anchors and quotes, each re-verified at the boundary and refused if unverified; strength as judgement; optional m-claims row id), `sheet.section_closed` (against closes before for opens; in Prepare, or when the sheet feeds a lead, the for section is refused to the session that wrote against), `sheet.balance_recorded` (Claude's balance, labelled; optional researcher assessment, human-only). **Coverage is computed**, never typed: works per tier, per source, unavailable sources, works without m-claims rows; absence asserted only over mined fields with an absence policy. Every agent event carries model, skill version and `input_blob`. Explore enforces the 15-work tier-1 cap (refusal names the remedy: continue explicitly, or switch to Prepare).

Ask answers are not events unless saved: `chat.answer_saved` (human gate "save this"): question, selection digest, answer text, claims with verified quotes. A saved answer is a note, never evidence.

### 4.7 Hub chat page and bridge
- **Page** `chat.html` per project: selection picker (from the explorer, saved by name), mode (Ask / Spar Explore / Spar Prepare), message box, thread view (rendered Markdown, citations linked to the explorer's reading panel at the anchor), suggestion list with add/skip buttons, a session indicator (is a Claude Code session attached).
- **Thread store**: a sidecar file per project (`chat/threads.jsonl`), not events: the conversation is exploratory (ruling 5). Saved answers and sheets are events (4.6).
- **Write path**: token-gated `POST /api/chat/message` and `POST /api/chat/suggestion` on the hub server (same pattern as the feed page); `GET /api/chat/thread` for polling.
- **Session side**: MCP tools `chat_inbox_next` (the oldest unanswered message, its selection resolved, or "none"), `chat_reply` (posts Markdown with structured citations; every citation re-verified; unverified ones are refused and listed), `chat_suggest` (posts the suggestion list). The researcher attaches a session by starting the `rf-chat` skill, which waits on the inbox (a Monitor on `chat_inbox_next`, or a short loop).
- No model call anywhere in the platform; the page works only while a session is attached and says so.

### 4.8 Skill `rf-chat`
Rules: state the selection and its size; for Spar, propose the category tick list and wait; compute candidates, read tier-3 profiles, post suggestions and wait; read tier 1 in full; write against first, then for (or hand over to a second session when required), then qualifies; verify every quote before posting; separate verified statements from inference; never assert absence beyond computed coverage; Ask uses the same tools without the stance split and with no sheet.

### 4.9 Inquiry (miner on the fly), later
As in the first version of this plan (option A): an ad-hoc question becomes a temporary miner spec run once over a selection, rows labelled `uncalibrated, exploratory`, promotable through `factory miner add`. Prepare mode may use it to read every candidate with one fixed question. Built after the evaluation.

## 5. Tasks (TDD; testing is paused by the researcher, so tests are written and not run until it is lifted)

| # | Task | Files | Depends |
|---|---|---|---|
| D1 | **Data, not platform:** m-claims calibration (5 papers, researcher reviews), then pass A on the core layer (Sonnet) and audit. Started 2026-11-18. | pilot | — |
| T0 | IDEA-85: one unescaping rule on both sides of quote verification. | `document/quotes.py`, tests | — |
| T1 | Selection: spec, resolve, digest, exclusions; shared explorer-filter evaluation; named selections in the chat sidecar. | `services/selection.py`, `services/site_explorer_page.py`, tests | — |
| T2 | Size report per work, layer, selection (`factory selection size`). | `services/selection.py`, `cli/`, tests | T1 |
| T3 | Passage index sidecar (FTS5), `corpus_search`. | `document/passage_index.py`, `services/corpus_search.py`, tests | T1 |
| T4 | Read and verify tools: `chat_sections`, `chat_read`, `chat_mined`, `chat_verify`; held-out scrub of snippets. | `services/chat_read.py`, `mcp/server.py`, tests | T0, T1 |
| T5 | Paper profile view and its size measurement on the pilot. | `services/paper_profile.py`, `mcp/server.py`, tests | T4 |
| T6 | Candidate suggestion and tiers (`chat_candidates`). | `services/chat_candidates.py`, tests | T3, T5 |
| T7 | Argument sheets: events, folds, tools, computed coverage, against-before-for and session-split guards; `chat.answer_saved`; decision row. | `model/sheets.py`, `services/sheets.py`, `index/sheets.py`, `mcp/server.py`, tests | T4, T6 |
| T8 | Hub chat page, thread sidecar, POST/GET endpoints, `chat_inbox_next`, `chat_reply`, `chat_suggest`. | `services/site_chat_page.py`, `services/site_server.py`, `services/chat_thread.py`, `mcp/server.py`, tests | T1, T4 |
| T9 | Skill `rf-chat` (Ask, Spar Explore, Spar Prepare). | `plugin/skills/rf-chat/` | T6, T7, T8 |
| T10 | Evaluation harness (outside `platform/`): B1, B2, B3 through `chat_candidates`; search component on the miner-quote set; metrics; result note. | `scripts/` or `ops/`, result note | T6 |
| T11 | Meaning-based search (conditional on T10): vector sidecar, hybrid fusion, weights hash (decision 116 rules). | `services/corpus_embed.py`, tests | T10 |
| T12 | Inquiry objects (4.9). | `services/inquiry.py`, tests | T10 |

**Tests to write first (selection):** T0 escapes accepted, no previously accepted quote rejected; T3 passages never cross headings, record their anchors, stale conversions dropped, ties ordered; T5 final rows only, superseded rows absent; T6 tier rules on a fixture, suggestion list excludes selected works, unavailable sources named; T7 unverified quote refused, for-section refused before against closes, for-section refused to the against session in Prepare, coverage computed equals fixture counts, balance labelled; T8 POST without token refused, reply with an unverified citation refused, thread never written as events.

## 6. Evaluation (T10) and stop rules

- **B1** (50, known single papers) and **B2** (12, the paper against a hypothesis): share of expected papers among candidates; share reaching tier 1; source credit (which source proposed each expected paper). Target ≥ 80 % per part.
- **B3** (researcher's 10–15): same measures; stance recall where the researcher listed supporting and undermining papers.
- **Argument quality:** the researcher rates ~30 arguments (correct / misread / irrelevant).
- **Explore vs Prepare** on 3–5 hypotheses: what Explore missed; decides whether the 15-paper cap is safe.
- **Search component:** recall at k on the miner-quote set (category definitions as queries); meaning-based search is built only if it raises recall at 20 by ≥ 0.10 over the best keyword configuration.

## 7. Held-out handling
Works are corpus (decision 37.9): no tool hides a held-out seed's work; snippets and replies are scrubbed of seed identification with `held_out_tokens`; `docs/pilot/heldout-seeds.md` is never opened; chat sessions may not claim screening, calibration or audit tasks.

## 8. Risks
- A verified quote is not a correct reading: the skill separates quote from inference; the researcher rates arguments.
- Profiles inherit miner errors (enum agreement 0.5–0.7 in the pilot): suggestions are a union of sources, and tier 1 is full reading.
- m-claims misses a finding: the text index is the safety net; coverage names works without m-claims rows.
- The bridge needs an attached session; the page says when none is attached.
- Token budgets: sizes shown first; Explore cap; Prepare estimate.
- Scope creep into a general notebook product: IDEA-87 stays the export path.

## 9. Open choices for the researcher
1. Passage size N and whether code and display math are indexed (set by T10).
2. First index scope: core only, or all converted works.
3. Line-number defect (number-only elements): fix in conversion, or filter at indexing.
4. Do argument sheets feed the lineage graph (claim–hypothesis relations), or only leads?
5. Living loop: which open sheets become stale when a work enters the core layer.
6. Build order: recommended T0 → T1 → T4 → T5 → T3 → T6 → T7 → T8 → T9, then T10; or the hub page (T8) earlier for a first visible chat over full reading only.

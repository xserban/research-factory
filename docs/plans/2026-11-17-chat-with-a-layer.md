# Chat with a layer or a selection of papers, with verified citations and miners on the fly (IDEA-88)

Status: draft for the researcher's validation (2026-11-17). Not started. Plan only; nothing was run against the pilot data, so every size figure below is a method, not a measurement.
Depends on: `document/quotes.py` (`quote_in_element`, IDEA-85 fix first), `document/anchors.py` (`Manifest`, `Anchor`), `services/document_read.py` (`document_read`, `default_conversion`), `services/work_layers.py` (`layer_of`, `layers_of`), `services/site_explorer_page.py` (explorer filters, data model), `mining/spec.py` (`MinerSpec`, `Selector`, `Population`), `mining/select.py`, `mining/validate.py`, `services/mining.py` (`mine_next`, `mine_record`, `miner_population`, `use_is_exploratory`), `services/miner_add.py` (`factory miner add`), `services/taxonomies.py`, `services/withholding.py`, `mcp/server.py`. Decisions 37 (items 5 and 9), 49, 83, 116, 120, 123, 129. Backlog: IDEA-88 (this), IDEA-87 (export), IDEA-37, 50, 51, 53, 85, 57.

## 1. Goal and non-goals

**Goal.** The researcher chooses a set of papers (a layer such as `core`, an explorer filter, or a hand-picked list) and asks Claude questions about it. Every statement of an answer that rests on a paper carries a work id, an anchor and a verbatim quote that the platform has checked against the stored text. A good ad-hoc question can become a durable miner or a note, and until then its rows are labelled exploratory.

**Key results.**
1. A selection (layer, filter, list) resolves to a computed set of works with a default conversion; its size in characters and approximate tokens is shown before any reading.
2. Three modes over one selection: read-whole, search-and-read, miner-on-the-fly (section 5).
3. A quote verifier tool returns, for each claimed `(work, anchor, quote)`, accepted or the refusal reason, using `quote_in_element`; an answer is "verified" only for statements whose quotes were accepted.
4. Miner-on-the-fly rows are marked `uncalibrated, exploratory` everywhere they are shown, never counted by agreement, PRISMA, evidence reports or any calibrated figure, and can be promoted through the existing `factory miner add` path.
5. The search layer is evaluated against the free test set of IDEA-88 before it is trusted (section 10), with a stop rule.

**Non-goals.**
- No model call in `platform/`: embeddings, if any, follow decision 116 (local weights, optional extra); all reading and judgement is Claude's, through MCP tools.
- No "chat history store" for its own sake: a chat is not a record unless the researcher saves an answer (open choice 4).
- No replacement of the screening, extraction or miner calibration rules; an ad-hoc row is never evidence for a report.
- No export to external tools (IDEA-87 stays separate), no web access, no new converter.
- No change to a Decided entry. New events and rows are listed in section 8 as proposals.

## 2. Existing pieces this plan reuses

- **Anchored text.** Each converted work is Markdown with a manifest of anchors (sections, paragraphs, tables, cells). `document_read(work_id, after=, anchor=, limit=, max_chars=)` serves segments with stable anchors; `ANCHOR_MAX_CHARS` bounds one anchor. A work must be promoted and have a conversion.
- **Quote verification.** `quote_in_element(element_markdown, quote)`: the normalised quote must be a substring of the normalised plain text of one block (a quote never spans blocks). Known defect: Markdown escapes (IDEA-85). It must be fixed before this plan relies on verification (task T0).
- **Layers.** `layer_of(project, work)` (the researcher's `work.layer_set`, else the layer miner's final row, else pending); `layers_of`; the hub explorer carries `layer` as dimension zero, with counts and facets over the whole data model (`DIMS`, `LAYERS` in `site_explorer_page.py`), so the explorer already computes "works matching a filter" client-side from a data blob.
- **Miners.** `MinerSpec` is data (fields, `Selector(population, elements, heading_patterns, max_units)`, evidence rule, regime); `validate_miner` checks meaning; `mine_next` serves a task (anchors selected by `selected_anchors`), `mine_record` verifies quotes and writes rows; `Population` is a closed enum of computed sets (`included-final`, `corpus`, ...), and a use may be layer-filtered and `on_demand` per work or layer (decision 120, Q11). A listed use may be declared `exploratory` by protocol amendment (IDEA-69): no quality claim. Taxonomies are registered objects from which classification miners are derived (`mining/derive.py`).
- **Search in the index.** None. A grep of `platform/src/factory` finds no FTS5 use; the SQLite index holds events' projections, not paragraph text, which lives in blobs (Markdown). SQLite 3.54 with FTS5 is available in the development environment (checked locally: an FTS5 table can be created); to verify on the runtime that serves the pilot.
- **Embeddings.** Decision 116: local weights named by `FACTORY_RANKER_MODEL`, optional extra `ranker`, lazy import, tree hash of the weights recorded, determinism with ties broken by id. `ranking_model.py` is title-and-abstract only (SPECTER2).
- **Held-out handling.** Decision 37.9 and `held_out_tokens(project, include_work_ids=False)`: a held-out seed's work is read as corpus, never hidden or masked; what must not appear in agent views is the identification of the seed as a seed (its identifier tokens).

## 3. User stories

1. **Ask a layer.** "In the `core` layer, which papers report a team size, and what is it?" The researcher names the layer and the question in Claude Code; Claude sees how large the layer is, chooses read-whole or search-and-read, and answers with work, anchor and quote per statement; refused quotes are repaired or dropped before the answer is shown as verified.
2. **Ask a hand-picked selection.** The researcher selects works in the explorer (or lists ids or slugs), and asks the same kinds of question. The selection is shown back (count, size, any works without a conversion, reported as excluded).
3. **Turn an answer into something durable.** (a) *Miner*: the question's fields and quotes become a miner spec file, checked with `factory miner add FILE --check`, and registered by the researcher, after which the normal calibration route applies. (b) *Note*: the answer with its verified quotes is saved as a note or idea (open choice 4). (c) *Taxonomy proposal*: recurring categories found in an answer go to `taxonomy.change_proposed`, as agents already may.
4. **Check my reading.** The researcher pastes a claim and an anchor; the verifier says whether the quote is in that anchor.

## 4. State of the art for a bounded corpus (about 100 to 2,000 papers)

Stated in general terms, as established practice, without claims about particular models or benchmarks. Anything about a named model, a context size, a price or a measured gain is marked **to verify**, and is not a premise of this plan.

**Established practice (general).**
- *Long-context reading.* When the material fits the model's context, giving whole papers is simple and avoids retrieval misses; its costs are tokens per question and a known tendency of models to use long inputs unevenly (position and distraction effects). It scales with selection size times questions asked.
- *Agentic search.* The model is given search and read tools (keyword or hybrid search, open a document, open a section), issues several queries, reads what it finds and decides when to stop. It handles multi-step and comparative questions better than a single retrieval, at the cost of more calls. The user's feeling that "classic RAG is old" is consistent with this shift: single-shot retrieve-then-generate over fixed chunks is the baseline, not the practice for hard questions.
- *Hybrid retrieval.* Keyword (BM25-type) scoring and embedding similarity find different things (exact terms, acronyms and numbers versus paraphrase); combining the two rankings is standard.
- *Contextualised chunks.* A chunk is embedded or indexed together with its context (paper title, section heading path, and sometimes a short generated summary); the cheap, deterministic part is the title and heading path, which our anchors already provide.
- *Reranking.* A second, more expensive scorer reorders a short candidate list. Here the reranker is Claude's own reading of the candidates, so no extra component is needed in v1.
- *Structured extraction as an index.* Rows mined with quotes (taxonomies, miners) answer recurring questions directly and cheaply; they are the "checked semantic index" of IDEA-88.

**Fit to this platform.** The corpus is small enough that a keyword index over anchored paragraphs is cheap and exact; Claude supplies synonyms and re-queries; the anchor structure replaces arbitrary chunking (a paragraph or table cell is the unit, with its section path as context). Embeddings are an optional later layer judged by the evaluation, not a premise.

**To verify before any decision rests on it.**
- The context size and price of the Claude model the researcher will use, and how many tokens a converted paper occupies (a character-based estimate is used below).
- Whether any named embedding model (IDEA-88 lists EmbeddingGemma and a second version, SPECTER2) outperforms keyword search on our paragraphs, its licence, and its input length; only the local evaluation (section 10) decides.
- Whether long-context reading beats agentic search on our questions at equal cost; this is measured on the same question set (section 10), not assumed.

## 5. Architecture

**Principle.** The platform offers deterministic, read-only tools; Claude reads and judges; the platform verifies every quote and records what was verified. Search ranks and proposes, never judges.

### 5.1 Selection

A *selection spec* is data: `{layers: [...], filters: [...explorer dimension/value...], include: [work ids], exclude: [work ids], population: included-final|corpus}`. `resolve_selection(project, spec)` returns the works with a default conversion (sorted by work id), the works dropped for lack of a conversion with the reason, the size (characters and approximate tokens = characters divided by a stated constant, default 4, shown as an estimate), and a digest of the sorted `(work_id, conversion_id)` pairs. Layers use `layer_of`; explorer filters reuse one shared function that the explorer page and the service both call (the page currently evaluates filters in the browser from its data blob; T1 extracts the dimension values so the service can evaluate the same filters on the server, with a test that both agree on one fixture).

The selection is **ephemeral by default**: it is passed to each tool call and identified by its digest. It is stored only when a record is made (section 7), as the spec plus the digest, so any record can re-resolve it and report works that changed since (a conversion superseded, a layer move). No new event for exploration alone.

### 5.2 Mode 1: read-whole

For selections that fit. `selection_size` reports the total and the per-work size; `chat_read(work_id, ...)` is `document_read` for a chat session (same pages, same anchors). The rule of use, shown in the skill: read whole papers only while the total fits a stated budget share (default: at most half of the context budget the researcher declares), else switch to mode 2. How many tokens `core` is, is **computed, not assumed**: task T2 adds a read-only report (works, characters, estimated tokens, per layer) over the default conversions. Until it is run on the pilot, this plan states no figure. The decision to read whole is then arithmetic on that report.

### 5.3 Mode 2: search and read

Tools (all read-only, all take a selection spec):
- `chat_search(selection, query, mode=keyword|hybrid, limit, per_work_limit)`: ranked anchored paragraphs with work id, title, anchor id, section path, a snippet, the score and the rank source. Keyword is SQLite FTS5 (`bm25`) over anchored paragraphs and table cells; query syntax is validated and phrase and prefix queries are supported. Hybrid (later) fuses the FTS rank with an embedding rank by reciprocal rank fusion, both ranks displayed.
- `chat_sections(work_id)`: the outline (section anchors, headings, paragraph counts) of a work, so Claude can open the right section.
- `chat_read(work_id, anchor|after, ...)`: as `document_read`.
- `chat_mined(selection, miner|taxonomy, category?)`: the final mined rows with their anchors and quotes for the selection's works, with calibration state and the `exploratory` mark; this is the first stop for a recurring question.
- `chat_verify(items)`: for each `{work_id, anchor, quote}`, `quote_in_element` against the work's current default conversion; returns accepted or a reason (`anchor-missing`, `quote-not-in-anchor`, `no-conversion`), and the conversion id and markdown hash used.

**Index.** The paragraph index is a rebuildable sidecar built from the default conversions' manifests, not from events. It keeps `(conversion_id, anchor_id, work_id, section_path, text)` and an FTS5 table. It is keyed by `markdown_hash`, so a changed conversion is re-indexed and an old one dropped. Placement is open choice 3: a table of the events index (rebuilt by the projector, bumps the projection version, consistent with "index is only written by the projector") or a separate file under the project (rebuilt on demand, no projection bump). Recommended: the separate file, because its input is blobs and not events, which the index rule does not cover and which would otherwise make the projector read documents.

**Embeddings (optional, later).** One vector per anchored paragraph with its title and section path prepended (contextualised); a rebuildable sidecar keyed by the weights' tree hash and the conversion hash, as decision 116; ties broken by anchor id; never a gate. Built only if the evaluation (section 10) shows keyword search misses paragraphs that a model finds at an acceptable cost; the model is chosen by that evaluation.

### 5.4 Mode 3: miner on the fly

An ad-hoc question ("for each paper in `core`, what loss function is used, and where is it said?") is turned by Claude into a **temporary miner spec**: a `MinerSpec` with a few fields, the existing field kinds (enum, quote, number, anchor), a selector, and the evidence rule (every value needs an anchor and a verbatim quote, absence values for "not stated"). It is validated by `validate_miner`, which writes nothing. It is run over the selection by the same task loop (`mine_next` and `mine_record`: the task serves the selected anchors, the record verifies quotes and fields, nothing unverified is stored).

The existing machinery is bound to a registered miner listed in the protocol, with populations from a closed enum. Three ways to meet that, which is the one real design choice of this plan (open choice 1):
- **A. Inquiry objects (recommended for v1 build after mode 2).** A new object, `inquiry`, holds a spec (as `MinerSpec` JSON), a selection spec and digest, one pass, and its rows in separate tables (as decision 83 did for layer rows). It reuses `validate_miner`, the task serving and the verification code, not the registered-miner state. It never enters the protocol, calibration, agreement, PRISMA or reports. Rows carry `status: uncalibrated-exploratory`, the question text, the spec digest and the selection digest.
- **B. Registered ad-hoc miners.** Register `m-adhoc-N`, list it in the protocol by amendment as `exploratory: true`, run with `layers`/`on_demand`. Reuses everything unchanged, but every question is a protocol amendment (which has staleness and review effects), the population cannot express a hand-picked list without an `on_demand` request per work, and the protocol accumulates scratch miners.
- **C. No platform object.** Claude reads and answers in mode 1 or 2, rows exist only in the chat and are verified by `chat_verify`. Cheapest, but no rows to promote and no reuse.

Single pass by default (`regime.passes` not enforced): independence between passes (decision 37) needs two sessions and is the very thing an exploratory run gives up; the output says so on every row ("one reader, no calibration, no agreement"). A second pass can be requested later by the same task path if the researcher wants an agreement figure.

**Promotion.** `inquiry promote ID` writes the spec as a file in the form `factory miner add FILE --check` takes (`miner_add.py`), naming the intended miner name and use settings as placeholders to complete; the researcher then registers, lists it and runs calibration by the normal route. Nothing is promoted automatically, and the inquiry's rows are never relabelled as calibrated.

### 5.5 Prompting and skill

A Claude Code skill `rf-chat` (the platform's `skills/` convention) carries the rules: state the selection and its size first; prefer `chat_mined` for recurring questions; search with several phrasings and with synonyms Claude supplies; read the passage before quoting it; call `chat_verify` on every quote before presenting it as evidence; separate "verified statement" from "my inference"; report what the search did not find as "no passage found by these queries", never as absence in the paper; mark exploratory rows.

## 6. Interface options

1. **MCP tools and skill only (recommended for v1).** The conversation is in Claude Code; the tools are the ones above. No server work.
2. **Hub page, read-mostly (v2).** `factory site build` gets a "Selection" view: the selection spec and its resolved works, the size report, the saved answers and inquiries with their verified quotes and exploratory marks, and links to the explorer panel of each work. It shows what was recorded, it does not run the chat (the platform calls no model).
3. **Hub page with a live chat box.** Would need the page to reach a model; excluded by the platform rule unless the page only forwards to a Claude Code session; not proposed.

## 7. How answers are recorded (options)

- **None (default).** A chat leaves no record; `chat_verify` results exist only in the conversation. Nothing is lost that was not asserted as a record.
- **On request: `chat.answer_recorded`.** An event written by Claude with a human gate (the researcher says "save this"): question, selection spec and digest, the answer text, and a list of claims each with `{work_id, anchor, quote, conversion_id, markdown_hash}`; every claim is re-verified at record time and an unverified claim is refused. Provenance as usual (model, skill version, `input_blob` holding the tool trace). The record is a note: it feeds no evidence report; it can be cited by an idea (`idea_propose`) or graph item only through its verified claims.
- **Every turn recorded.** Full audit, but large, noisy, and it makes exploratory text look like record; not proposed.

Needs a decision row for any new event type (section 8). The `trace` tool would show a recorded answer's claims like any quote source.

## 8. Events, projections, decisions

- **No new event** for selections, searching, size reports, verification and mode 1 and 2 reading (all computed, read-only).
- **Proposed new events**, only if the researcher takes the corresponding options: `inquiry.created`, `inquiry.pass_recorded` (rows; or reuse of `mine.recorded` with an `inquiry_id`, to be decided at T6) for option A of open choice 1; `chat.answer_recorded` for the on-request option of open choice 4. Tables: `inquiry_rows`, `chat_answers` (projector only).
- **Sidecars (not events index):** `paragraph_fts` and, later, `paragraph_vectors`, rebuildable.
- **Decision row (proposed, number to be assigned at merge):** "Chat over a selection: read-only tools, verified quotes, exploratory inquiries". Content: (1) selection is computed and ephemeral; (2) a quote is verified by `quote_in_element` against the pinned conversion or it is not evidence; (3) search ranks, Claude judges; (4) inquiries are single-pass, uncalibrated, exploratory, outside the protocol and every report; promotion goes through `miner add`; (5) a saved answer is a note, never evidence; (6) embeddings only per decision 116's rules, chosen by the section 10 evaluation; (7) held-out seeds' works are corpus, their seed identity is withheld. No Decided entry is contradicted; decision 120 (miners registered and listed) is untouched because inquiries are not miners until promoted. If the researcher picks option B of open choice 1, decision 120's listing rule is used as it stands and no new object is needed, but each question is a protocol amendment.

## 9. Held-out handling

- Works are corpus (decision 37.9): chat tools never hide or mask a held-out seed's work, its text or its mined rows.
- Chat results that name works use `held_out_tokens(project, include_work_ids=False)` to scrub seed-identification (identifier values, seed lists, "this is a held-out seed"), as other tools naming corpus works do. The scrub runs on search snippets and answers' metadata, and is tested with a fixture that contains a held-out identifier in a title.
- `docs/pilot/heldout-seeds.md` is never opened by any task here; tests build their own fixture seeds.
- Chat sessions are not screening, calibration or audit sessions: they may not claim screening, calibration or audit tasks, and the screening gates on `document_read` for those sessions are unchanged. Chat reading of a work leaves no trace that screening or extraction could read.

## 10. Evaluation plan (before trusting search)

**Free test set (IDEA-88).** From the 2026-11-16 technique-miner run: each taxonomy category definition is a query; the anchored quotes mined for that category are the paragraphs a good search must find (relevant = the anchor holding an accepted quote). Built read-only from final mined rows and the taxonomy versions; a script outside `platform/` is enough. Only rows whose quote verifies are used. Rows that are paraphrases of one paragraph are one relevant item per `(work, anchor)`.

**Systems compared, on the same queries and the same pool (works of the miner's population).**
1. Keyword FTS5, query = the category's name and cue words (no model).
2. Keyword with Claude-written query variants (synonyms), by a fixed script of three variants per category written once and frozen before scoring.
3. Hybrid with each candidate embedding model, if installed (weights supplied locally; none downloaded by the platform).
4. Embedding only, as a diagnostic.
5. Whole-selection reading is compared separately on a small question set (mode 1 versus mode 2).

**Metrics (computed, never typed).** Recall at k (k = 10, 20, 50) at anchor level and at work level; mean reciprocal rank of the first relevant anchor; share of queries with zero relevant in the top 50; index build time and size; per-query latency; for mode comparison, the share of claims whose quotes verify and the number of tool calls and tokens read.

**Bias note.** The relevant set comes from a miner that read those papers, not from an independent labelling, so it misses true positives the miner did not record (recall is a lower bound, precision is not estimated). A small hand-labelled sample (the researcher labels 20 query-paragraph pairs from the unrecorded top results) estimates precision. Results are reported per category with the number of relevant anchors; categories with fewer than five are listed, not averaged.

**Stop rule (fixed before the first scoring run).** Keyword-only is adopted for v1 if its recall at 20 is at least 0.7 at work level and at least 0.5 at anchor level on categories with five or more relevant anchors, and the variant script (system 2) reaches at least 0.85 at work level. An embedding model is built into hybrid only if it raises recall at 20 by at least 0.10 absolute over the best keyword system, with no worse mean reciprocal rank, at a build time the researcher accepts. If neither threshold is met, stop and take the findings back to the researcher; thresholds are proposals for open choice 6, and are recorded in the plan's result note before any run.

## 11. Ordered task list (1 to 3 hours each; TDD first; testing is paused until the researcher lifts it, so the tests are written and not run)

| # | Task | Files | Depends |
|---|---|---|---|
| T0 | Fix IDEA-85: one unescaping rule on both sides of quote verification; count past `quote-not-in-anchor` rejections with a backslash. | `document/quotes.py`, `tests/test_quotes_escapes.py` | none |
| T1 | Selection: `SelectionSpec`, `resolve_selection`, digest, exclusions with reasons; shared explorer-filter evaluation extracted from `site_explorer_page.py` data building. | `services/selection.py` (new), `services/site_explorer_page.py`, `tests/test_selection.py` | T0 not needed |
| T2 | Size report: characters and estimated tokens per work, layer and selection; read-only CLI `factory selection size`. | `services/selection.py`, `cli/`, `tests/test_selection_size.py` | T1 |
| T3 | Paragraph index sidecar with FTS5: build from manifests, key by `markdown_hash`, incremental refresh, drop of stale conversions; `search_paragraphs(selection, query, limit, per_work_limit)` with query validation. | `document/paragraph_index.py` (new), `services/chat_search.py` (new), tests | T1 |
| T4 | Verifier and read tools: `chat_verify`, `chat_sections`, `chat_read` (a wrapper of `document_read`), `chat_mined`; held-out scrub on snippets. | `services/chat_read.py`, `mcp/server.py`, tests | T0, T1, T3 |
| T5 | Skill `rf-chat` and MCP wiring/docs (tool descriptions state "search ranks, Claude judges"). | `skills/rf-chat/`, `mcp/server.py`, `docs/` | T4 |
| T6 | Evaluation harness (outside `platform/`, a script reading final mined rows and taxonomy versions, writing a result file), the frozen variant queries, the metrics; result note appended to this plan. | `scripts/` (new), result note | T3 |
| T7 | Inquiry (option A): spec check reuse, task serving over a selection population, row verification, separate tables, labels, `inquiry promote` file writer; decision row. | `services/inquiry.py` (new), `index/inquiry.py`, `mcp/server.py`, `cli/`, tests | T1, T4, decision row |
| T8 | Saved answer (on-request option): event, re-verification at record, `trace` hook. | `services/chat_answers.py`, `index/`, tests | T4, decision row |
| T9 | Hub "Selection" view (read-only): selection, size, inquiries and answers with verified quotes. | `services/site_selection_page.py`, `services/site_hub.py`, tests | T7, T8 |
| T10 | Embeddings (conditional on T6's stop rule): vector sidecar, hybrid rank fusion, weights hash recorded, optional extra. | `services/chat_embed.py`, tests | T6 |

**TDD list (tests to write first).**
- T0: a quote with `\_`, `\*`, `\[` verifies against text read with escapes; no previously accepted fixture quote is rejected.
- T1: a layer selection equals the explorer's filter on one fixture; works without a conversion are excluded with a reason; the digest is stable under input order and changes when a conversion changes; an unknown layer or dimension is refused on its field, nothing written.
- T2: size equals the sum over manifests; the estimate constant is reported.
- T3: a phrase query, a prefix query and an unbalanced-quote query (refused with a structured error); table cells are indexed and a quote spanning two blocks is not found as one; re-index after a conversion changes drops old rows; per-work limit holds; ties are ordered by work id then anchor id.
- T4: accepted and each refusal reason of `chat_verify`; the verifier uses the pinned conversion, not a newer one; a held-out identifier in a snippet is scrubbed while the work's text is not hidden; a chat session cannot claim a screening task.
- T7: a spec with an unverifiable field kind is refused; rows with a failing quote are not stored; rows carry the exploratory label and never appear in agreement, PRISMA or evidence report (negative tests); promotion output passes `miner add --check`.
- T8: an unverified claim is refused at record; a saved answer re-resolves its selection and lists changed works.

## 12. Risks

- **A verified quote is not a correct inference.** `quote_in_element` proves the words are in the paragraph, not that they support the claim. The skill separates quote from inference; the researcher can audit a sample of saved answers by the existing audit habits.
- **Search misses are silent.** A paragraph that no query finds is not in the answer. Reports say what was searched; evaluation measures recall; absence is never asserted.
- **Conversion quality.** Anchors and tables inherit converter errors; low-quality conversions are flagged in `resolve_selection` output (`quality` is in the conversion row).
- **Token budgets.** Mode 1 can overrun context; size is shown first and the skill refuses to read whole above the declared share.
- **Exploratory drift.** Inquiry rows could be mistaken for mined rows; labels, separate tables and negative tests guard this; promotion is the only way in.
- **Escapes and quote normalisation** (IDEA-85): fixed first (T0); tables and cells need their own tests.
- **Index staleness.** A conversion changes while a chat runs; the pinned `markdown_hash` is returned with each result and verification names it.
- **Held-out leakage** through snippets or saved answers; scrub and test (section 9).
- **Embedding choice.** Licence, input length and the optional-extra footprint on a 13 GB machine; decided only by the evaluation.
- **Scope creep** into a general notebook product (IDEA-87 is the export path for that need).

## 13. Open choices for the researcher

1. **Miner on the fly: what object runs it?**
   a. (recommended) Inquiry objects: separate, single-pass, exploratory rows reusing spec validation, task serving and quote checks; promotion writes a `miner add` file (new events, a decision row).
   b. Registered ad-hoc miners listed `exploratory` by protocol amendment (no new object; every question is an amendment).
   c. No platform object: Claude reads and answers, `chat_verify` only.
2. **Build order.**
   a. (recommended) T0, T1, T2, T3, T4, T5 (modes 1 and 2 with skill), then T6 evaluation, then T7 inquiry.
   b. Inquiry (mode 3) first, since it is the wish most unlike a classic search.
   c. Evaluation harness first (T6 on a throwaway index) before any tool is built.
3. **Where the paragraph index lives.**
   a. (recommended) A separate rebuildable sidecar file keyed by `markdown_hash` (no projection bump).
   b. A table of the events index, written by the projector from blobs.
4. **Are chats recorded?**
   a. (recommended) Only on request: a saved answer is an event with verified claims, used as a note.
   b. Never: the chat leaves no record; notes are made by hand.
   c. Every turn, for audit.
5. **Selection storage.**
   a. (recommended) Ephemeral spec with digest; stored only inside a saved answer or inquiry.
   b. Named selections saved as events, re-usable by name (`selection.saved`).
   c. The explorer's current filter only (no hand-picked lists).
6. **Evaluation thresholds and stop rule** (section 10: keyword adopted at recall at 20 of 0.7 work-level and 0.5 anchor-level, variants 0.85; embeddings only for a gain of 0.10).
   a. (recommended) Adopt these as written.
   b. Stricter: 0.8, 0.6, 0.9 and a gain of 0.15.
   c. Set after seeing a pilot of the harness on three categories (thresholds still fixed before the full run).
7. **Embeddings.**
   a. (recommended) Not built unless the T6 stop rule says so; the model is chosen by that evaluation.
   b. Built in v1 with SPECTER2 (already supported by decision 116), compared with keyword.
   c. Built in v1 with a paragraph-trained model chosen now.
8. **Interface.**
   a. (recommended) MCP tools and skill `rf-chat` for v1; a read-only hub "Selection" view in v2 (T9).
   b. MCP and skill only, no hub view.
   c. Hub view in v1 with the tools.
9. **Mode 1 budget rule.**
   a. (recommended) Read whole only if the selection's estimated tokens are at most half the declared context budget, otherwise search and read.
   b. Always search-and-read, never whole papers.
   c. Researcher decides per question; the tool only reports the size.
10. **Inquiry passes (if option 1a).**
    a. (recommended) One pass, labelled "one reader, no agreement"; a second pass only on request.
    b. Two independent passes always, with an agreement figure.

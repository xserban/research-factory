# Interpretations: Model, Validation, Review Lifecycle and Separation Implementation Plan (slice 3c, sub-plan G3-A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: provisional — depends on the unconfirmed [confirm] rulings of slice-3c-intuition.md and on the G2 (slice-3b) plans.

> **Dependencies.** G1 (`2026-11-04-references-snowballing.md`) and all G2 plans (`2026-11-05-lineage-{a..e}-*.md`) merged: this plan reads G2's graph projection, ideas and contribution items, and G1's reference links. Plans D and E (extraction, evidence report) are merged. G3-B and G3-C build on this plan; it ends in a state where every earlier suite passes unchanged.

**Goal:** Let Claude record short, source-bound interpretations of why an idea or paper works, let a human review, reject or supersede them, and prove by construction that no evidence output reads them.

**Architecture:** A new layer module family: model `model/intuition.py`, pure helpers `factory/intuition/` (`validate.py`, `labels.py`), projection `index/intuition.py`, services `services/intuition_sources.py` (quote and citation verification, shared with G3-B) and `services/interpretations.py` (next, record, review, supersede, list, history). Layer nodes and `explains` edges are projected into G2's `graph_nodes` / `graph_edges` with `class = interpretation`; every G2 read is restricted to `class = evidence` in this plan so default views are unchanged before G3-C adds the opt-in filter. An AST architecture test and a differential test guard the boundary.

**Tech Stack:** as plans D, E and G2; stdlib `ast`; no new dependencies.

**Spec:** `docs/specs/slice-3c-intuition.md` (rulings 3–9, 11 in part; Design: Interpretations, Separation; events `interpretation.*`; acceptance 1–5, 8, 10, 12 for interpretations). `docs/specs/01-rigour.md` R-01, R-02, R-04, R-05, R-40, R-43, R-47, R-51; proposed R-xx(h), R-xx(i). Decisions 37, 48 (pass sessions refused).

## Rulings made in this plan

Spec rulings 1–11 are adopted as written and remain **[confirm]**. The following decide gaps; they are **[confirm]** and G3-C Task 6 records them in the *Proposed* decision.

A1. **Layer rows in the graph tables.** G2's `graph_nodes` and `graph_edges` gain `class TEXT NOT NULL DEFAULT 'evidence'` and `review_state TEXT NULL`. The G3 projector writes interpretation nodes (`node_type = interpretation`, id `int_…`) and `explains` edges (`edge_id = "explains:" + int_id`) there. Every G2 query and statistic in `services/lineage.py` reads through one predicate `class = 'evidence'` until G3-C adds the `layer` parameter.
A2. **Input seen by the writer.** `intuition_next` creates a task (kind `intuition`, one target per task) whose content (target, member works, live contribution items with quotes) is the task's `input_blob`. `interpretation.recorded` stores as `input_blob` the canonical JSON `{"task_input": <task content blob hash>, "call": <validated call input>}`. A human-written interpretation has no task and stores the call input only.
A3. **Default targets.** Without `targets`, `intuition_next` serves confirmed ideas only, in idea-id order; papers are served only when named in `targets` (spec open question 2). A target with a live interpretation or an open task is skipped.
A4. **Citation sources.** A `citation` source names either a G1 reference entry key `rex_<ULID>:<ordinal>` of a live extraction (its link state and resolved work, if any, are stored as computed fields) or a corpus work id. An entry whose link is `unresolved` is accepted and stored with `link_state = unresolved`; the reviewer sees it.
A5. **Quote sources pin a live document.** A quote source names `work_id`, `conversion_id`, `anchor`, `quote`; the conversion must belong to a non-superseded document of that work at write time; `document_id` is computed and stored. Later supersession of that document yields `source-stale` (spec ruling 9), computed at read time, never an event.
A6. **Who may supersede.** An agent may name in `supersedes` only an interpretation of the same target that is `unreviewed` or `wrong` and agent-written; superseding a `reviewed` or human-written one is a human act (CLI). The new interpretation must have the same target.
A7. **Distinct humans.** Humans are distinguished by `actor.user` of `kind = human` events. Self-review (reviewer user = author user of a human-written interpretation) is refused when the project log holds human events of more than one user; otherwise it is allowed and recorded with `self_reviewed = true`. An agent-written interpretation is reviewed by any human; `self_reviewed` is false.
A8. **Transitions.** `unreviewed → reviewed|wrong`, `reviewed ↔ wrong` (each a new event; the latest wins), any live state `→ superseded` (by a new interpretation); `superseded` is terminal and a review of it is refused. `wrong` requires a non-blank note.
A9. **Label wording** (spec open question 6). `layer_label(state) = "interpretation · " + state`; the class token is always `interpretation`.

## G2 and G1 names assumed

The G2 plans are drafted in parallel; this plan consumes the names the 3b spec states, with these assumed signatures. If a G2 plan differs, the executor adapts the call sites and records the difference in the task's commit message; the interfaces this plan produces do not change.
- `services/lineage.py`: `graph_node(project, node_id) -> GraphNode | None` (`node_id`, `node_type: Literal["paper", "idea"]`, `scope: Literal["corpus", "external"] | None`); `graph_status`, `graph_query`, `graph_export` as in spec 3b §MCP; one private SQL access layer in which the `class` predicate is added.
- `services/ideas.py`: `live_idea(project, idea_id) -> IdeaView | None` with `state` (`confirmed|proposed|rejected`), `merged_into`, `name`, `origin`, `members: list[str]`.
- `services/contributions.py`: `live_items(project, work_id) -> list[ContributionItem]` with `extraction_id`, `item_kind`, `name`, `statement`, `anchor`, `quote`, `conversion_id`.
- `index/lineage.py`: tables `graph_nodes(node_id PK, node_type, …)`, `graph_edges(edge_id PK, edge_type, source, target, status, basis, …)`; `PROJECTION_VERSION` value after G2 (call it `N`).
- G1 `index/references.py`: `reference_extractions(extraction_id, work_id, live)`, `reference_entries(extraction_id, ordinal)`, `reference_links(extraction_id, ordinal, state, work_id, confidence)`.
- Pass sessions: G2 contribution passes are plan-D extraction passes (spec 3b ruling 6), so `is_extraction_session` covers them.

## Global Constraints

- All plan D, E and G2 constraints hold. The platform never calls a model; no key, no SDK. Events are the source of truth; the index is written only by the projector, which never reads the library.
- Every agent-written event carries model, skill reference and `input_blob` (ruling A2). A human-written one carries `actor.kind = human`, no model, no skill, and `author = human` in the payload.
- `INTERPRETATION_MAX_CHARS = 600`; sources 1 to 5 (`INTERPRETATION_MAX_SOURCES = 5`); roles `supports|background`; review states `unreviewed|reviewed|wrong|superseded`.
- Quotes are the only document text in events; no document text appears in any error, finding or test fixture outside `tests/` hand-written Markdown (`tests/document_helpers.py`). No literature text in tracked files.
- Invalid input writes nothing and returns structured errors (`ValidationIssue(field, reason)`); fields are `text`, `target`, `sources`, `sources[i].<attr>`, `supersedes`, `task_id`.
- Layer modules (`factory.model.intuition`, `factory.intuition`, `factory.index.intuition`, `factory.services.intuition_sources`, `factory.services.interpretations`, and G3-B's `factory.services.concepts`) are imported only by: each other, `services/lineage.py`, `services/check.py`, `services/trace.py`, `index/default.py`, `events/catalog.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- `uv run pytest -m "not network"`, `mypy --strict`, ruff pass; coverage ≥ 90% for `services/` and `model/`. Earlier suites pass unedited except the `PROJECTION_VERSION` pin.

## Review Focus

1. A quote that is verbatim in the paper but cited at a conversion of a superseded document is refused at write time; the same quote recorded before the supersession stays `reviewed` and becomes `source-stale` afterwards (Tasks 3, 5).
2. A text of exactly 600 characters is accepted, 601 refused; length counts Unicode code points after NFC, not bytes (Task 1).
3. An idea target that was merged away, rejected or never confirmed is refused with the reason, and a paper target outside the corpus (`scope = external`) is refused (Task 4).
4. A G2 query or `graph_status` run on a project with a populated layer returns exactly what it returns without one, before G3-C exists (Tasks 2, 6).
5. Two human users: the author of a human-written interpretation is refused as reviewer; with one human user the review is recorded `self_reviewed` (Task 5).

## File Structure

- Create `model/intuition.py`; `factory/intuition/__init__.py`, `validate.py`, `labels.py`; `index/intuition.py`; `services/intuition_sources.py`, `services/interpretations.py`; `plugin/skills/rf-intuition/SKILL.md`.
- Modify `events/catalog.py`, `index/default.py`, `index/lineage.py` (G2: two columns), `services/lineage.py` (G2: evidence predicate), `services/fulltext.py` (public `document_superseded`), `mcp/server.py`, `tests/test_plugin.py` (`SKILLS`).
- Tests: `test_intuition_model.py`, `test_intuition_index.py`, `test_intuition_sources.py`, `test_interpretations_record.py`, `test_interpretations_review.py`, `test_intuition_separation.py`, `test_mcp_intuition.py`; helper `tests/intuition_helpers.py` (a G2 fixture project with two confirmed ideas, three corpus papers converted from hand-written Markdown, live contribution items, one G1 extraction with a resolved and an unresolved entry; `quote_src(...)`, `cite_src(...)` builders; `populate_layer(project)` writing a fixed set of layer events).

---

### Task 1: Model and pure validation

*Tier: critical (the shape rules are the reviewer's guarantee of checkability).*

**Files:** Create `model/intuition.py`, `intuition/__init__.py`, `intuition/validate.py`, `intuition/labels.py`; Test `tests/test_intuition_model.py`.

**Interfaces:**
- Produces (`model/intuition.py`): `INTERPRETATION_ID_RE = rf"^int_{ULID_RE}$"`, `CONCEPT_ID_RE = rf"^cpt_{ULID_RE}$"`, `CONCEPT_LINK_ID_RE = rf"^cul_{ULID_RE}$"` (the last two used by G3-B), `ENTRY_KEY_RE = rf"^rex_{ULID_RE}:[1-9][0-9]*$"`, `INTERPRETATION_MAX_CHARS = 600`, `INTERPRETATION_MAX_SOURCES = 5`, `VERIFIER_VERSION = 1`; `LayerClass(StrEnum)`: `EVIDENCE = "evidence"`, `INTERPRETATION = "interpretation"`; `ReviewState(StrEnum)`: `unreviewed`, `reviewed`, `wrong`, `superseded`; `Author(StrEnum)`: `agent`, `human`; `SourceRole(StrEnum)`: `supports`, `background`; `QuoteSourceInput(StrictModel)`: `kind: Literal["quote"]`, `role`, `work_id`, `conversion_id`, `anchor` (the screening `Anchor` form), `quote: NonBlank`; `CitationSourceInput(StrictModel)`: `kind: Literal["citation"]`, `role`, `reference: str | None` (pattern `ENTRY_KEY_RE`), `work_id: str | None` (exactly one of the two); `SourceInput = Annotated[QuoteSourceInput | CitationSourceInput, Field(discriminator="kind")]`; `StoredSource(StrictModel)`: the input fields plus computed `document_id: str | None`, `link_state: str | None`, `resolved_work: str | None`; `InterpretationInput(StrictModel)`: `target: str`, `text: str`, `sources: tuple[SourceInput, ...]`, `supersedes: str | None` (pattern `INTERPRETATION_ID_RE`); payloads `InterpretationRecorded(interpretation_id, target, target_kind: Literal["idea", "paper"], text, sources: tuple[StoredSource, ...], author: Author, supersedes: str | None, task_id: str | None, verifier: int)` and `InterpretationReviewed(interpretation_id, state: Literal["reviewed", "wrong"], note: str, self_reviewed: bool, channel: Channel)`; read model `InterpretationHidden(StrictModel)`: `wrong: int`, `superseded: int` (kept in the model module so G3-C's pure export can take it). The models check shape only (types, patterns, discriminator); bounds are `validate.py`'s, so one function reports all of them together.
- Produces (`intuition/validate.py`, pure): `text_length(text: str) -> int` (code points after NFC); `shape_issues(entry: InterpretationInput) -> list[ValidationIssue]`: `text` blank or `> INTERPRETATION_MAX_CHARS` ("at most 600 characters"), `sources` empty ("at least one source is required") or more than 5, a duplicate source (same kind and locator) at `sources[i]`.
- Produces (`intuition/labels.py`, pure): `layer_label(state: str) -> str` (ruling A9); `interpretation_visible(state: ReviewState) -> bool` (`unreviewed`, `reviewed`); `LAYER_CLASS = "interpretation"`.

- [ ] **Step 1: Tests.**
```python
def test_600_accepted_601_refused():
    assert shape_issues(entry(text="a" * 600)) == []
    assert [i.field for i in shape_issues(entry(text="a" * 601))] == ["text"]
def test_length_counts_code_points_after_nfc(): assert text_length("é" * 600) == 600
def test_sources_required_and_bounded():
    assert [i.field for i in shape_issues(entry(sources=()))] == ["sources"]
    assert "sources" in {i.field for i in shape_issues(entry(sources=(q,) * 6))}
def test_duplicate_source_reported_by_index(): assert "sources[1]" in fields(entry(sources=(q, q)))
def test_citation_needs_exactly_one_locator():
    with pytest.raises(ValidationError): CitationSourceInput(kind="citation", role="supports", reference=None, work_id=None)
def test_entry_key_pattern(): ...           # "rex_<ULID>:12" ok; "rex_<ULID>:0", "rex_x:1" refused
def test_unknown_source_kind_refused(): ...
def test_label_and_visibility():
    assert layer_label("unreviewed") == "interpretation · unreviewed"
    assert {s for s in ReviewState if interpretation_visible(s)} == {ReviewState.unreviewed, ReviewState.reviewed}
def test_reviewed_payload_states_limited(): ...   # "superseded" and "unreviewed" are not reviewable states
```
- [ ] **Step 2:** Run `uv run pytest tests/test_intuition_model.py -v`; expect FAIL (modules missing). **Step 3:** Implement per Interfaces. **Step 4:** Tests, `mypy --strict`, ruff pass. **Step 5:** Commit `feat(intuition): interpretation model and shape validation`.

### Task 2: Events, projection and the evidence predicate

*Tier: critical (events, index, the boundary in G2 reads).*

**Files:** Create `index/intuition.py`; modify `events/catalog.py`, `index/default.py`, `index/lineage.py`, `services/lineage.py`; Test `tests/test_intuition_index.py`; update the `PROJECTION_VERSION` pin test.

**Interfaces:**
- Consumes: Task 1 payloads; G2 `graph_nodes`, `graph_edges`.
- Produces: event types `interpretation.recorded`, `interpretation.reviewed`, schema 1. Tables (`index/intuition.py`): `interpretations(interpretation_id PK, target, target_kind, text, author, author_user, writer_session, writer_model, task_id, supersedes, superseded_by, review_state, self_reviewed, last_review_event, input_blob, event_id)`; `interpretation_sources(interpretation_id, position, role, kind, work_id, conversion_id, document_id, anchor, quote, reference, link_state, resolved_work; PK (interpretation_id, position))`; `interpretation_reviews(event_id PK, interpretation_id, state, note, reviewer_user, self_reviewed, channel)`; view `layer_hidden(item, reason, n)` with rows (`interpretation`, `wrong` | `superseded`, count). Handlers: `recorded` inserts the row (`review_state = unreviewed`) and, when `supersedes` is set, sets the prior row's `superseded_by` and `review_state = superseded`; `reviewed` appends history and sets `review_state` and `self_reviewed` unless the row is `superseded` (stored in history, state unchanged). Each handler also upserts the graph row: node `(int_id, node_type = "interpretation", class = "interpretation", review_state)` and edge `("explains:" + int_id, edge_type = "explains", source = int_id, target, status = NULL, basis = int_id, class = "interpretation", review_state)`. Handlers are total: an unknown target or prior id is stored as given.
- Produces (`index/lineage.py`, G2): columns `class TEXT NOT NULL DEFAULT 'evidence'` and `review_state TEXT` on both graph tables, indexed on `class`. (`services/lineage.py`, G2): every read of the graph tables adds `class = 'evidence'` through one helper `_evidence_only(sql)` (ruling A1). `PROJECTION_VERSION = N + 1`.

- [ ] **Step 1: Tests.**
```python
def test_record_projects_row_sources_and_graph_rows():
    replay([recorded(int1, target=IDEA, sources=[q1, c1])])
    assert row(int1).review_state == "unreviewed" and n_sources(int1) == 2
    assert graph_node(int1) == ("interpretation", "interpretation", "unreviewed")
    assert graph_edge("explains:" + int1)[:3] == (int1, IDEA, "interpretation")
def test_review_fold_latest_wins_and_history_kept():
    replay([recorded(int1), reviewed(int1, "reviewed"), reviewed(int1, "wrong", note="misreads eq. 3")])
    assert row(int1).review_state == "wrong" and len(history(int1)) == 2
def test_supersession_marks_prior_and_both_remain(): ...
def test_review_of_superseded_row_kept_in_history_state_unchanged(): ...
def test_layer_hidden_view_counts(): assert hidden() == {("interpretation", "wrong"): 1, ("interpretation", "superseded"): 1}
def test_rebuild_state_hash_stable(): ...          # replay twice, equal hashes
def test_g2_reads_exclude_layer_rows():             # Review Focus 4
    base = g2_outputs(project)                      # graph_status, every graph_query kind, both exports
    populate_layer(project); assert g2_outputs(project) == base
def test_earlier_tables_unchanged_by_layer_events(): ...
def test_projection_version_bumped(): assert PROJECTION_VERSION == str(int(G2_VERSION) + 1)
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement and register handlers; add columns and the predicate; bump the version. **Step 4:** Tests, all G2 suites unedited, mypy, ruff. **Step 5:** Commit `feat(intuition): interpretation events, projection, evidence predicate on graph reads`.

### Task 3: Source verification and stale sources

*Tier: critical (verified quotes are the layer's link to evidence, R-01, R-40).*

**Files:** Create `services/intuition_sources.py`; modify `services/fulltext.py`; Test `tests/test_intuition_sources.py`.

**Interfaces:**
- Consumes: `conversion_manifest`, `resolve_anchor`, `quote_in_element` (`factory/document/quotes.py`), `list_works`, G1 reference tables.
- Produces (`services/fulltext.py`): `document_superseded(project: Project, document_id: str) -> bool` (public wrapper over `_document`).
- Produces (`services/intuition_sources.py`): `@dataclass(frozen=True) SourceVerdict(stored: tuple[StoredSource, ...], issues: list[ValidationIssue])`; `verify_sources(project: Project, sources: Sequence[SourceInput], *, field: str = "sources") -> SourceVerdict` (all-or-nothing: `stored` is empty when any issue). Quote rules (ruling A5): work is a corpus work (`work-unknown`); conversion exists and belongs to that work (`conversion-not-of-work`); its document is not superseded (`document-superseded`); anchor resolves (`anchor-unknown`); quote verbatim after B2 normalisation (`quote-not-in-anchor`). Citation rules (ruling A4): an entry key must exist in a live G1 extraction (`entry-unknown`, `extraction-not-live`), stored with the link's `state` and `work_id`; a work id must be a corpus work (`work-unknown`). Reasons are a fixed vocabulary at `<field>[i].<attr>`; never document text. `entry_link(project, entry_key) -> tuple[str, str | None] | None` (link state, resolved work). `stale_sources(project: Project) -> dict[str, tuple[str, ...]]`: interpretation id → document ids of its quote sources that are now superseded (G3-B extends the same mapping to concept quotes under `cpt_` keys).

- [ ] **Step 1: Tests** (fixture: paper P1 Markdown with paragraph `s1.p2` "We replace the softmax kernel with a positive random-feature map."; G1 extraction of P1 with entry 4 resolved to P2 and entry 7 unresolved).
```python
def test_verbatim_quote_accepted_and_document_pinned():
    v = verify_sources(project, [quote_src(P1, CNV1, "s1.p2", "positive random-feature map")])
    assert v.issues == [] and v.stored[0].document_id == DOC1
def test_non_verbatim_quote_refused_without_text():
    v = verify_sources(project, [quote_src(P1, CNV1, "s1.p2", "positive random features")])
    assert reasons(v) == {"sources[0].quote": "quote-not-in-anchor"} and "random" not in str(v.issues)
def test_conversion_of_other_work_refused(): ...
def test_superseded_document_refused_at_write(): ...          # Review Focus 1
def test_entry_key_stores_link_state():
    v = verify_sources(project, [cite_src(f"{REX1}:4"), cite_src(f"{REX1}:7")])
    assert [(s.link_state, s.resolved_work) for s in v.stored] == [("resolved", P2), ("unresolved", None)]
def test_entry_of_superseded_extraction_refused(): ...
def test_unknown_work_citation_refused(): ...
def test_all_or_nothing(): assert verify_sources(project, [good, bad]).stored == ()
def test_stale_sources_after_new_document_version():         # Review Focus 1, acceptance 10
    record_reviewed_interpretation(); supersede_document(DOC1)
    assert stale_sources(project) == {INT1: (DOC1,)} and row(INT1).review_state == "reviewed"
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(intuition): quote and citation source verification, stale sources`.

### Task 4: `intuition_next` and recording (agent and human authorship)

*Tier: critical (provenance, R-04; refusal writes nothing).*

**Files:** Create `services/interpretations.py`; Test `tests/test_interpretations_record.py`.

**Interfaces:**
- Consumes: Task 3 `verify_sources`; Task 1 `shape_issues`; G2 `graph_node`, `live_idea`, `live_items`; task services (`create`, `claim_next`, `require_holder`, `complete_task`); `blobs.put`.
- Produces: `INTUITION_KIND = "intuition"`; `class IntuitionBatch(StrictModel)`: `task_id`, `instructions`, `target`, `target_kind`, `target_name: str | None`, `members: list[str]`, `items: list[ServedItem]` (`ServedItem`: `work_id`, `extraction_id`, `item_kind`, `name`, `statement`, `anchor`, `quote`, `conversion_id`), `max_chars: int`, `max_sources: int`; `IntuitionNext(batch: IntuitionBatch | None, skipped: list[TargetSkip], remaining: int)` (`TargetSkip(target, reason)`, reasons `has-live-interpretation`, `task-open`, `not-confirmed`, `merged`, `external`, `unknown`); `intuition_next(project: Project, actor: Actor, *, targets: Sequence[str] | None = None) -> IntuitionNext` (ruling A3; agents only; inside `project.index.exclusive()`); `target_issue(project, target) -> ValidationIssue | None` (exists, `class = evidence`, idea confirmed and not merged, paper `scope = corpus`); `record_interpretation(project: Project, actor: Actor, entry: InterpretationInput, *, task_id: str | None = None) -> str` returns the `int_` id. Agents must pass the held task (`task_id`) whose target equals `entry.target`; humans pass none. Order: shape issues, target issue, supersedes rule (ruling A6: same target, live, and for agents unreviewed-or-wrong and agent-written), `verify_sources`; any issue raises `FactoryValidationError` with all issues and writes nothing. On success one append: `interpretation.recorded` (`author` from `actor.kind`, `input_blob` per ruling A2) and, for an agent, `task.completed`.

- [ ] **Step 1: Tests.**
```python
def test_next_serves_confirmed_ideas_with_member_items():
    b = intuition_next(project, agent).batch
    assert b.target == IDEA1 and b.members == [P1, P2] and {i.item_kind for i in b.items} <= {"base-idea", "addition", "result", "limitation"}
    assert task_blob(b.task_id)["items"][0]["quote"] == b.items[0].quote
def test_next_skips_targets_with_live_interpretation_or_open_task(): ...
def test_named_targets_and_their_refusals():                 # Review Focus 3
    n = intuition_next(project, agent, targets=[P3, MERGED_IDEA, EXTERNAL_PAPER, "ida_unknown"])
    assert n.batch.target == P3 and {s.reason for s in n.skipped} == {"merged", "external", "unknown"}
def test_record_writes_one_event_with_provenance():          # acceptance 1
    iid = record_interpretation(project, agent, entry(target=IDEA1), task_id=b.task_id)
    ev = event_of(iid); assert ev.actor.model and ev.actor.skill.startswith("rf-intuition@")
    assert blob(ev.input_blob) == {"task_input": task_input_hash(b.task_id), "call": entry_json}
def test_refusals_write_nothing():                            # acceptance 2
    for bad in [entry(sources=()), entry(text="a" * 601), entry(target="ida_unknown"), entry(sources=[nonverbatim]), entry(sources=[cite_src("rex_X:99")])]:
        with pytest.raises(FactoryValidationError): record_interpretation(project, agent, bad, task_id=t)
    assert layer_event_count(project) == 0
def test_all_issues_reported_together(): ...                 # text too long and a bad source in one error
def test_agent_needs_held_task_matching_target(): ...       # field "task_id"
def test_human_writes_without_task_author_human():
    iid = record_interpretation(project, human, entry(target=P1))
    assert event_of(iid).actor.model is None and event_of(iid).payload["author"] == "human"
def test_agent_supersedes_own_unreviewed_only():              # ruling A6
    assert refused(agent, supersedes=REVIEWED_INT) and refused(agent, supersedes=HUMAN_INT)
    new = record_interpretation(project, agent, entry(supersedes=UNREVIEWED_INT), task_id=t)
    assert state(UNREVIEWED_INT) == "superseded" and state(new) == "unreviewed"
def test_supersedes_must_share_target(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement; instructions text: explain why the idea works in at most 600 characters, from the served items and quotes; cite 1–5 sources; quote verbatim; mark a source `background` when it is context, not support; write nothing you cannot ground (record the thought in the session instead). **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(intuition): intuition_next and verified interpretation recording`.

### Task 5: Review lifecycle, supersession by a human, listing and history

*Tier: critical (R-51; review states).*

**Files:** Modify `services/interpretations.py`; Test `tests/test_interpretations_review.py`.

**Interfaces:**
- Consumes: Tasks 2–4; `Channel`; `stale_sources`.
- Produces: `review_interpretation(project: Project, actor: Actor, interpretation_id: str, state: Literal["reviewed", "wrong"], note: str, channel: Channel) -> str` (event id; human only, field `actor`; unknown id; `superseded` target refused, field `interpretation_id`; `wrong` needs a note, field `note`; self-review per ruling A7, field `reviewer`); `supersede_interpretation(project, actor, interpretation_id: str, text: str, sources: Sequence[SourceInput]) -> str` (human only; records a human-authored interpretation of the same target with `supersedes`; any live prior state); `class InterpretationView(StrictModel)`: `interpretation_id`, `class_: str` (serialised `class`), `label`, `target`, `target_kind`, `text`, `sources: list[StoredSource]`, `author`, `writer: str` (actor id, plus model for agents), `review_state`, `self_reviewed`, `source_stale: list[str]`, `input_blob: str | None`; `class InterpretationList(StrictModel)`: `items: list[InterpretationView]`, `hidden: InterpretationHidden`, `next_cursor: str | None`; `list_interpretations(project, *, target: str | None = None, states: Collection[ReviewState] | None = None, cursor: str | None = None) -> InterpretationList` (default states = visible ones, ruling 7; hidden counts always reported, over the same target filter); `class HistoryEntry(StrictModel)` (defined in `model/intuition.py` so `services/concepts.py` can reuse it without importing this module): `event_id`, `kind: Literal["recorded", "reviewed", "superseded-by"]`, `state: str | None`, `actor: str`, `note: str`, `self_reviewed: bool`; `interpretation_history(project, interpretation_id) -> list[HistoryEntry]`; `review_counts(project) -> dict[ReviewState, int]` (computed; G3-C reports it).

- [ ] **Step 1: Tests.**
```python
def test_agent_cannot_review():                              # acceptance 4
    with pytest.raises(FactoryValidationError) as e: review_interpretation(project, agent, INT1, "reviewed", "", Channel.MCP)
    assert e.value.issues[0].field == "actor" and layer_event_count(project) == 1
def test_wrong_needs_note_and_is_hidden_but_traceable():   # acceptance 5
    review_interpretation(project, human, INT1, "wrong", "conflates kernel and feature map", Channel.CLI)
    assert INT1 not in ids(list_interpretations(project)) and list_interpretations(project).hidden.wrong == 1
    assert [h.kind for h in interpretation_history(project, INT1)] == ["recorded", "reviewed"]
def test_repeated_review_supersedes_previous(): ...         # acceptance 3: reviewed then wrong; live = wrong; history 3 entries
def test_superseded_is_terminal(): ...
def test_human_supersede_writes_human_replacement():
    new = supersede_interpretation(project, human, REVIEWED_INT, "…", [quote_src(...)])
    assert state(REVIEWED_INT) == "superseded" and view(new).author == "human"
def test_self_review_one_human_flagged_two_humans_refused():   # Review Focus 5, ruling A7
    assert view(review_own(single_human_project)).self_reviewed is True
    with pytest.raises(FactoryValidationError) as e: review_own(two_human_project)
    assert e.value.issues[0].field == "reviewer"
def test_unreviewed_items_carry_label(): assert view(INT2).label == "interpretation · unreviewed" and view(INT2).class_ == "interpretation"
def test_source_stale_does_not_change_state(): ...           # acceptance 10
def test_list_paginates_and_hidden_counts_follow_target_filter(): ...
def test_review_counts_are_computed(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(intuition): review lifecycle, human supersession, listing and history`.

### Task 6: Separation tests (architecture and differential)

*Tier: critical (R-xx(h); spec says subagent-driven).*

**Files:** Create `tests/test_intuition_separation.py`; complete `tests/intuition_helpers.py::populate_layer`.

**Interfaces:**
- Consumes: `final_rows`, `grouped_rows`, `independence_counts`, `live_claims`, `evidence_report`, `prisma_flow`, `search_report`, `methods_report`, G2 `graph_status`, `graph_query` (every kind), `graph_export` (`json`, `dot`).
- Produces (test helpers, reused by G3-B and G3-C): `LAYER_MODULES: frozenset[str]` (the module names of the Global Constraints, including `factory.services.concepts` ahead of G3-B); `ALLOWED_IMPORTERS: frozenset[str]`; `LAYER_TABLES = ("interpretations", "interpretation_sources", "interpretation_reviews", "layer_hidden")` (G3-B appends its tables); `evidence_outputs(project) -> dict[str, str]` (each output's canonical JSON); `twin_projects(tmp_path) -> tuple[Project, Project]` (builds the G2 fixture once, copies the project directory, runs `populate_layer` on the copy, rebuilds both indexes).

- [ ] **Step 1: Tests.**
```python
def test_no_evidence_module_imports_the_layer():              # acceptance 8
    offenders = [(m, imp) for m, imp in imports_of(package_modules("factory")) if imp in LAYER_MODULES and m not in ALLOWED_IMPORTERS | LAYER_MODULES]
    assert offenders == []
def test_no_sql_outside_layer_names_layer_tables():
    assert [m for m in modules_with_string_literals(LAYER_TABLES) if m not in LAYER_MODULES | {"factory.services.lineage", "factory.services.check", "factory.services.trace"}] == []
def test_scanner_catches_a_planted_import(tmp_path): ...       # a synthetic module importing factory.services.interpretations is reported
def test_evidence_outputs_byte_identical_with_and_without_layer(tmp_path):
    plain, layered = twin_projects(tmp_path)
    assert layer_event_count(layered) > 0 and evidence_outputs(plain) == evidence_outputs(layered)
def test_differential_detects_a_leak(tmp_path, monkeypatch): ...   # patch final_rows to append an int_ id; outputs differ
```
- [ ] **Step 2:** Run; the differential test fails only if Task 2's predicate missed a read; the scanner tests fail until the helpers exist. **Step 3:** Implement the helpers (AST walk over `platform/src/factory/**/*.py`, resolving relative imports). **Step 4:** Tests pass. **Step 5:** Commit `test(intuition): architecture and differential separation tests`.

### Task 7: MCP tools and the `rf-intuition` skill

*Tier: standard (surfaces); service behaviour is covered.*

**Files:** Modify `mcp/server.py`, `tests/test_plugin.py`; Create `plugin/skills/rf-intuition/SKILL.md`; Test `tests/test_mcp_intuition.py`, `tests/test_skills.py` (extend).

**Interfaces:**
- MCP (parse, call, `_reply`, replies through `_withheld`): `intuition_next(project, role, model, skill, targets: list[str] = [])` → `IntuitionNext`; `interpretation_record(project, task_id, target, text, sources: list[dict], role, model, skill, supersedes: str | None = None)` → `{"interpretation_id": …}`; `interpretation_list(project, target: str | None = None, states: list[str] = [], cursor: str | None = None)` → `InterpretationList`. All three are refused to a session that joined a screening or extraction pass (`_refuse_pass_session` extended with `is_extraction_session`). No MCP tool reviews or supersedes as a human.
- Skill `rf-intuition` (concise, academic): what an interpretation is and is not (not evidence; never cited as a result); procedure: `intuition_next`, read the served items, open the papers through `document_read` when a quote beyond the items is needed, write ≤ 600 characters, 1–5 sources, verbatim quotes, `background` vs `supports`, stop when `batch` is null; do not record what cannot be grounded; never review, never supersede a reviewed item; corrections of a rejected call are resubmissions, never edited quotes. G3-B adds the concept section.

- [ ] **Step 1: Tests.** Tool list pinned with the three new names; `interpretation_record` with a non-verbatim quote returns the structured error and writes nothing; a pass-A screening session and an extraction session are refused all three; `interpretation_list` labels every item; skill file exists with frontmatter, names `intuition_next`, `interpretation_record`, "600", "verbatim", "not evidence"; `SKILLS` includes `rf-intuition`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement (skill text by a Sonnet implementer). **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(intuition): MCP tools and rf-intuition skill`.

## Self-review notes

- **Spec coverage.** Interpretation shape and sources (rulings 4, 5; Tasks 1, 3, 4); node class (ruling 3; Task 2); review states, human-only review, supersession, self-review (rulings 6, 8; Task 5); default visibility and hidden counts for interpretations (ruling 7; Tasks 2, 5); stale sources (ruling 9; Tasks 3, 5); separation 1–3 and 5 (Tasks 2, 6); provenance and `input_blob` (Task 4); MCP tools `intuition_next`, `interpretation_record`, `interpretation_list` and pass refusal (Task 7). Concepts, `uses`, merge are G3-B; layer filter, `graph_status` layer counts, export, check, trace and CLI are G3-C.
- **Types.** `InterpretationInput`, `StoredSource`, `verify_sources`, `stale_sources`, `ReviewState`, `layer_label`, `InterpretationView`, `InterpretationHidden`, `evidence_outputs`, `LAYER_MODULES` keep these names in G3-B and G3-C.
- **Risk.** Task 2 touches G2's tables and reads; its gate is the unchanged G2 suites plus the differential test. Tiers: Tasks 1–6 critical, Task 7 standard.

# Background Concepts, Approved Sources and `uses` Links Implementation Plan (slice 3c, sub-plan G3-B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Status: ready — rulings adopted 2026-11-04; depends on G1 and G2 being built.

> **Dependencies.** G3-A (`2026-11-05-intuition-a-interpretations.md`) merged: this plan reuses its model module, `verify_sources`, `stale_sources`, `layer_label`, the self-review rule A7, the layer graph tables `layer_nodes` / `layer_edges` and the separation harness. G1 and G2 merged (reference links; paper and idea nodes). It ends in a state where every earlier suite, including G3-A's, passes unchanged.

**Goal:** Record background concepts (an outside idea, a short explanation and a researcher-approved source), link papers, ideas and other concepts to them by `uses` edges that the platform classifies as stated or inferred, let only a human approve sources, review concept definitions and confirm links, and support reversible merges without cycles.

**Architecture:** Concept events extend `model/intuition.py`; the stated/inferred rule and the cycle test are pure functions in `factory/intuition/classify.py`; `services/concepts.py` validates and writes; `index/intuition.py` gains the concept tables and recomputes the affected concept nodes and `uses` edges in the layer's own `layer_nodes` / `layer_edges` after every concept event, so a merge and its reversal leave the same rows. Concept visibility depends on an approval bound to the source's digest and on the human review of the live definition (`concept.reviewed`). G2's graph tables and views are untouched (G3-A ruling A1); the opt-in view is G3-C.

**Tech Stack:** as G3-A; no new dependencies.

**Spec:** `docs/specs/slice-3c-intuition.md` (rulings 1, 2, 3, 7, 10; Design: Concepts, node and edge types; events `concept.*`; acceptance 1, 6, 7, 11, 12 for concepts; open questions 3 and 4). `docs/specs/01-rigour.md` R-01, R-02, R-04, R-40, R-51; proposed R-xx(j).

## Rulings made in this plan

Spec rulings are adopted. These decide gaps; all were Adopted 2026-11-04 (researcher's standing approval of the recommendation), B2 extended by the controller ruling of the same day (human review of concept definitions); G3-C Task 6 records them in the *Proposed* decision when built.

B1. **Approval binds to a digest.** `source_digest = "src_" + sha256(canonical JSON of {kind, citation, work_id})[:16]`. A concept's `source_state` is `approved` iff the latest `concept.source_decided` for the live definition's digest is `approve` (`none` without a source, `proposed` without a decision, `rejected` when the latest decision rejects). A redefinition that keeps the source keeps the approval; one that changes it returns `source_state` to `proposed` (hidden). Replacing a source is a human redefinition (`factory concepts source`), written together with its approval.
B2. **Concept states and definition review.** Every live definition (agent- or human-written) is reviewed by a human through `concept.reviewed(concept_id, definition, state: reviewed|wrong, note, self_reviewed, channel)`, where `definition` is the event id of the live `concept.defined`; the latest review of the live definition wins, `wrong` needs a note, a review of a superseded definition is refused (`definition`, `not-current-definition`), and a redefinition (B5) starts `unreviewed`. Writer and self-review rules are G3-A's A7 (distinct `actor.user`; an agent-written definition is reviewed by any human). Node `review_state ∈ {unreviewed, reviewed, wrong, merged}`: `merged` when merged, else the live definition's review state. A concept is **visible** iff `source_state = approved`, it is not merged, and `review_state ∈ {unreviewed, reviewed}` (an unreviewed one is labelled `interpretation · unreviewed`). Hidden reasons, in this precedence: `merged`, `unapproved`, `wrong`. `uses` edges carry their link status (`stated|inferred|confirmed|rejected`) as `review_state`, so `layer_label` gives `interpretation · stated` and the like.
B3. **Sources without full text** (spec open question 3, recommendation adopted). A source with no `work_id` is `verifiable = false`; its definition may carry no quotes and its view carries the flag `unverifiable-source`. A source with a `work_id` (any kind) must name a corpus work; quotes (0–5) must come from that work and pass `verify_sources`.
B4. **Identity.** Names and aliases are folded with `normalise_text` (NFKC, case-fold, whitespace collapsed). A proposal whose name or alias equals a folded name or alias of a live, unmerged concept (including aliases gained by merge) is refused at field `name` or `aliases[i]` with reason `concept-exists` and the existing id in `refs`. Name ≤ 120 characters, at most 10 aliases, text ≤ `INTERPRETATION_MAX_CHARS` (optional: a concept may be named before its text is drafted).
B5. **Redefinition.** A new `concept.defined` with an existing `concept_id` must name in `supersedes` the event id of the live definition (`not-current-definition` otherwise). An agent may redefine only an agent-written concept; a human may redefine any.
B6. **`uses` rule** (spec flow 4, acceptance 7). Stated when (a) the basis quote is verified, its work is the from-paper (or a member of the from-idea), and a folded name or alias of the concept occurs in the folded quote bounded by non-word characters (`name-in-quote`); or (b) the basis reference is an entry of a live G1 extraction of that work whose link is `resolved` or `confirmed` and whose work equals the concept's approved source work (`cites-approved-source`). Otherwise inferred, with one reason: `name-not-in-quote`, `citation-unresolved`, `citation-not-approved-source`, `source-unapproved`, `source-not-in-corpus`, `concept-to-concept`, `no-basis`. A link with no basis must carry a `note` (labelled `agent-note`, never counted). Links between concepts are always inferred (`concept-to-concept`) and need a human.
B7. **Idempotence and re-proposal.** A proposal equal in (from, concept, basis digest) to a non-rejected link whose computed status is the same returns that link and writes nothing; a different computed status (for example after the source was approved) records a new link. Every link is its own edge (`edge_id = "uses:" + link_id`).
B8. **Cycles.** Over concept→concept links that are not rejected (inferred included), after merge resolution: a proposal or merge that would close a cycle or a self-link is refused (`cycle`). `concept-cycle` in G3-C is the broken-invariant check.
B9. **Merge.** Human only. `into` and `from` must be live, distinct and unmerged; `from` must have no concepts merged into it; a merge that would create a cycle is refused. A merge re-points `from`'s links and aliases to `into` in the projection; `concept.unmerged` restores them; the raw link rows never change.

## G2 and G1 names consumed

As G3-A ("G2 and G1 names consumed"): G2-D `load_graph`, `GraphFilter`, `Graph.node`, `GraphNode.scope`; G2-C `idea_view` (`state`, `merged_into`, `effective_members`), `resolve_idea`, `IDEA_ID_RE`; G2-B `reference_view`, `reference_view_of`, `is_live_reference_extraction`, `EntryView.link_state` / `link_work`; G3-A `entry_link`. The from-idea rule of B6 reads `IdeaView.effective_members` (members after merges). A G1 link counts as resolved for B6 when `EntryView.link_state == LinkState.RESOLVED` (any confidence, so human- or agent-confirmed links included). Renamed from the draft: `graph_node` → `load_graph(...).node`; `live_idea` → `idea_view`; `members` → `effective_members`; G1 reference tables → G2-B reference view; G2 graph tables → G3-A layer tables.

## Global Constraints

- All G3-A constraints hold (layer module list, allowed importers, `INTERPRETATION_MAX_CHARS`, no document text in messages, provenance, all-or-nothing refusals).
- No MCP tool approves a source, reviews a concept definition, confirms or rejects a link, merges or unmerges (R-51, spec ruling 1); the services refuse any actor whose `kind` is not `human` (field `actor`).
- Event types `concept.defined`, `concept.source_decided`, `concept.reviewed`, `concept.link_proposed`, `concept.link_decided`, `concept.merged`, `concept.unmerged`, schema 1.
- `PROJECTION_VERSION` = G3-A's value + 1 (`N + 2`, N = value after G2-D); earlier suites unedited except that pin.

## Review Focus

1. Alias collisions after a merge: proposing a concept named like an alias that arrived by merge is refused; after unmerge the alias belongs to the restored concept again, and a proposal that collided only through the merge succeeds (Tasks 3, 5).
2. Name matching is whole-word after folding: "kernel" does not state a link from a quote containing "kernels"; "Random Features" matches "random  features" (Task 1).
3. An agent redefines an approved concept with a new source: the concept disappears from default views and its `uses` edges become endpoint-hidden, without any edit to earlier events; a redefinition that keeps the source stays visible but returns to `unreviewed`, and a review naming the superseded definition is refused (Tasks 2, 3, 6).
4. A link proposed while the source was unapproved stays `inferred`; re-proposing after approval with the same citation records a new `stated` link and both stay listed (Task 4).
5. A merge whose `from` concept has a link to `into` (or the reverse) is refused as a self-link; an unmerge of a concept that is not merged is refused (Task 5).

## File Structure

- Modify `model/intuition.py`, `index/intuition.py`, `events/catalog.py`, `index/default.py`, `services/intuition_sources.py` (concept quotes in `stale_sources`), `services/interpretations.py` (concepts in the batch), `mcp/server.py`, `plugin/skills/rf-intuition/SKILL.md`, `tests/intuition_helpers.py` (`populate_layer` adds concepts and links; `LAYER_TABLES` appended).
- Create `intuition/classify.py`, `services/concepts.py`.
- Tests: `test_concepts_model.py`, `test_concepts_classify.py`, `test_concepts_index.py`, `test_concepts_define.py`, `test_concepts_review.py`, `test_concepts_links.py`, `test_concepts_merge.py`, `test_mcp_concepts.py`; extend `test_intuition_separation.py`.

---

### Task 1: Concept model and pure rules (classification, cycles)

*Tier: critical (the stated/inferred rule).*

**Files:** Modify `model/intuition.py`; Create `intuition/classify.py`; Test `tests/test_concepts_model.py`, `tests/test_concepts_classify.py`.

**Interfaces:**
- Produces (`model/intuition.py`): `CONCEPT_NAME_MAX = 120`, `CONCEPT_MAX_ALIASES = 10`; `ConceptSourceKind(StrEnum)`: `textbook`, `survey`, `corpus-paper`, `other`; `ConceptSourceInput(StrictModel)`: `kind`, `citation: NonBlank` (≤ 500), `work_id: str | None` (required for `corpus-paper`); `StoredConceptSource(ConceptSourceInput)` + `digest: str`, `verifiable: bool`; `ConceptInput(StrictModel)`: `name`, `aliases: tuple[str, ...] = ()`, `text: str | None = None`, `source: ConceptSourceInput | None = None`, `quotes: tuple[QuoteSourceInput, ...] = ()`, `concept_id: str | None = None`, `supersedes: str | None = None`; `UseBasisInput(StrictModel)`: `quote: QuoteSourceInput | None = None`, `reference: str | None = None` (pattern `ENTRY_KEY_RE`; at most one of the two); `LinkStatus(StrEnum)`: `stated`, `inferred`, `confirmed`, `rejected`; `ConceptState(StrEnum)`: `unreviewed`, `reviewed`, `wrong`, `merged`; `SourceState = Literal["none", "proposed", "approved", "rejected"]`; payloads `ConceptDefined(concept_id, name, aliases, text, source: StoredConceptSource | None, quotes: tuple[StoredSource, ...], author: Author, supersedes: str | None)`, `ConceptSourceDecided(concept_id, decision: Literal["approve", "reject"], source_digest, note: str, channel: Channel)`, `ConceptReviewed(concept_id, definition: str, state: Literal["reviewed", "wrong"], note: str, self_reviewed: bool, channel: Channel)` (ruling B2; `wrong` ⇒ non-blank note), `ConceptLinkProposed(link_id, from_node, from_kind: Literal["paper", "idea", "concept"], concept_id, basis_kind: Literal["quote", "citation", "none"], quote: StoredSource | None, reference: str | None, cited_work: str | None, basis_digest, status: Literal["stated", "inferred"], status_reason, note: str | None)`, `ConceptLinkDecided(link_id, decision: Literal["confirm", "reject"], rationale: NonBlank, channel)`, `ConceptMerged(into, from_concept, reason: NonBlank)`, `ConceptUnmerged(into, from_concept, reason: NonBlank)`; read model `ConceptHidden(StrictModel)`: `unapproved: int`, `wrong: int`, `merged: int`, `links_inferred: int`, `links_rejected: int`; G3-A's `HistoryEntry.kind` gains `source-decided`.
- Produces (`intuition/classify.py`, pure): `fold(s: str) -> str`; `name_in_text(names: Collection[str], text: str) -> bool` (folded, bounded by `(?<!\w)` / `(?!\w)`); `source_digest(source: ConceptSourceInput) -> str` (ruling B1); `classify_use(*, from_kind: str, names: Collection[str], quote: str | None, cited_work: str | None, link_resolved: bool | None, source_work: str | None, source_approved: bool) -> tuple[Literal["stated", "inferred"], str]` (ruling B6); `would_cycle(edges: Collection[tuple[str, str]], new: tuple[str, str]) -> bool`.

- [ ] **Step 1: Tests.**
```python
def test_name_in_quote_whole_word_folded():                       # Review Focus 2
    assert name_in_text(["Random Features"], "we use random  features to approximate")
    assert not name_in_text(["kernel"], "positive kernels only")
    assert name_in_text(["kernel trick", "RFF"], "via RFF.")
def test_classify_quote_and_citation():
    assert classify_use(from_kind="paper", names=["random features"], quote="…random features…", cited_work=None, link_resolved=None, source_work=None, source_approved=False) == ("stated", "name-in-quote")
    assert classify_use(from_kind="paper", names=["x"], quote=None, cited_work=P9, link_resolved=True, source_work=P9, source_approved=True) == ("stated", "cites-approved-source")
@pytest.mark.parametrize("kw,reason", [
    (dict(quote="no name here"), "name-not-in-quote"), (dict(cited_work=None, link_resolved=False), "citation-unresolved"),
    (dict(cited_work=P8, source_work=P9, source_approved=True), "citation-not-approved-source"),
    (dict(cited_work=P9, source_work=P9, source_approved=False), "source-unapproved"),
    (dict(cited_work=P9, source_work=None, source_approved=True), "source-not-in-corpus"), (dict(), "no-basis")])
def test_inferred_reasons(kw, reason): assert classify_use(**base(kw)) == ("inferred", reason)
def test_concept_to_concept_always_inferred(): assert classify_use(**base(dict(from_kind="concept", quote="random features")))[1] == "concept-to-concept"
def test_would_cycle():
    assert would_cycle({("a", "b"), ("b", "c")}, ("c", "a")) and would_cycle(set(), ("a", "a")) and not would_cycle({("a", "b")}, ("a", "c"))
def test_digest_stable_and_kind_sensitive(): ...
def test_corpus_paper_source_needs_work_id(): ...
def test_basis_quote_and_reference_exclusive(): ...
def test_concept_reviewed_wrong_needs_note(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(concepts): concept model, uses classification, cycle test`.

### Task 2: Concept projection and merge-aware graph rows

*Tier: critical (projection; merge reversibility, acceptance 11–12).*

**Files:** Modify `index/intuition.py`, `events/catalog.py`, `index/default.py`; Test `tests/test_concepts_index.py`.

**Interfaces:**
- Produces tables: `concepts(concept_id PK, name, name_folded, text, author, author_user, writer_model, definition_event, source_kind, source_citation, source_work, source_digest, source_verifiable, source_state, review_state, self_reviewed, merged_into, input_blob, event_id)`; `concept_aliases(concept_id, alias, alias_folded; PK (concept_id, alias_folded))`; `concept_definitions(event_id PK, concept_id, supersedes)`; `concept_reviews(event_id PK, concept_id, definition, state, note, reviewer_user, self_reviewed, channel)` (history; only rows whose `definition` is the live one count for `review_state`); `concept_quotes(concept_id, position, work_id, conversion_id, document_id, anchor, quote; PK (concept_id, position))` (the live definition's); `concept_source_decisions(event_id PK, concept_id, decision, source_digest, reviewer_user, note)`; `concept_uses(link_id PK, from_node, from_kind, concept_id, basis_kind, basis_work, basis_conversion, basis_document, basis_anchor, basis_quote, reference, cited_work, basis_digest, status, status_reason, note, decision, decided_by, decision_event, event_id)` (`status` folds the latest decision: `confirmed` or `rejected`); `concept_merges(from_concept PK, into, active, merge_event, unmerge_event)`; `layer_hidden` view extended with (`concept`, `merged` | `unapproved` | `wrong`) and (`concept_link`, `inferred` | `rejected`).
- Behaviour: after every concept event the handler calls `_refresh_concepts(conn, concept_ids)`, which recomputes, from the tables above only, each affected concept's `source_state` and `review_state` (rulings B1, B2), its `layer_nodes` row (`node_type = "concept"`, `class = interpretation`, `review_state`) and every `layer_edges` `uses` row touching it (`source` and `target` resolved through active merges; `review_state` = link status). Raw `concept_uses` rows are never re-pointed; G2's `graph_nodes` / `graph_edges` are never written.

- [ ] **Step 1: Tests.**
```python
def test_definition_without_approval_is_unreviewed_and_hidden(): ...
def test_approval_bound_to_digest():                              # ruling B1
    replay([defined(C1, source=S1), decided(C1, "approve", S1)]); assert source_state(C1) == "approved"
    replay([defined(C1, source=S2, supersedes=ev1)]);             assert source_state(C1) == "proposed"
    replay([defined(C1, source=S1, supersedes=ev2)]);             assert source_state(C1) == "approved"
def test_review_binds_to_live_definition():                       # ruling B2
    replay([defined(C1, source=S1), decided(C1, "approve", S1), reviewed(C1, ev1, "reviewed")]); assert state(C1) == "reviewed"
    replay([defined(C1, source=S1, supersedes=ev1)]);             assert state(C1) == "unreviewed" and visible(C1)
    replay([reviewed(C1, ev3, "wrong", note="misstates the bound")]); assert state(C1) == "wrong" and not visible(C1)
def test_link_decision_folds_latest(): ...                        # confirm then reject -> rejected
def test_merge_then_unmerge_restores_tables_exactly():           # acceptance 11
    before = dump(["concepts", "concept_aliases", "concept_uses", "layer_nodes", "layer_edges"])
    replay([merged(C1, C2), unmerged(C1, C2)]); assert dump([...]) == before
def test_merge_repoints_edges_and_marks_node(): ...                # edge target C1, node C2 review_state "merged"
def test_layer_hidden_counts_concepts_and_links(): ...
def test_rebuild_state_hash_stable_with_concepts(): ...           # acceptance 12
def test_g2_outputs_unchanged_with_concepts(): ...                # G3-A helper, with concepts populated; graph_nodes/graph_edges rows unchanged
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement; bump `PROJECTION_VERSION`. **Step 4:** Tests, G3-A suites unedited, mypy, ruff. **Step 5:** Commit `feat(concepts): concept events and merge-aware projection`.

### Task 3: Defining concepts, deciding sources and reviewing definitions

*Tier: critical (R-xx(j), R-51).*

**Files:** Create `services/concepts.py`; modify `services/intuition_sources.py`; Test `tests/test_concepts_define.py`, `tests/test_concepts_review.py`.

**Interfaces:**
- Consumes: `verify_sources`, `source_digest`, `fold`, `list_works`.
- Produces: `define_concept(project: Project, actor: Actor, entry: ConceptInput, *, approve_source: bool = False) -> str` (returns `cpt_` id; agent or human; `approve_source` only for a human with a source, appending `concept.source_decided(approve)` in the same write; validation per rulings B3–B5, length via `text_length`, all issues together, nothing written on failure; agent events carry the validated input as `input_blob`); `decide_concept_source(project, actor, concept_id: str, decision: Literal["approve", "reject"], note: str, channel: Channel) -> str` (human only; the live definition must have a source, field `source`; `reject` needs a note); `review_concept(project, actor, concept_id: str, state: Literal["reviewed", "wrong"], note: str, channel: Channel) -> str` (ruling B2; human only, field `actor`; writes `concept.reviewed` naming the live definition; `wrong` needs a note, field `note`; merged concept refused, field `concept_id`; self-review per G3-A ruling A7, field `reviewer`); `class ConceptView(StrictModel)`: `concept_id`, `class_`, `label`, `name`, `aliases`, `text`, `source: StoredConceptSource | None`, `source_state: SourceState`, `flags: list[str]` (`unverifiable-source`, `source-stale`, `self-reviewed`), `quotes: list[StoredSource]`, `author`, `writer`, `review_state: ConceptState`, `visible: bool`, `merged_into`; `ConceptBrief(StrictModel)`: `concept_id`, `name`, `aliases`; `concept_view(project, concept_id) -> ConceptView | None`; `list_concepts(project, *, include_hidden: bool = False, cursor: str | None = None) -> ConceptList(items, hidden: ConceptHidden, next_cursor)`; `visible_concepts(project) -> list[ConceptBrief]`; `concept_history(project, concept_id) -> list[HistoryEntry]` (G3-A model: `recorded` for definitions, `superseded-by` for replaced definitions, `reviewed` for `concept.reviewed`, `source-decided` for source decisions with `state` = decision); `concept_review_counts(project) -> dict[ConceptState, int]` (computed; G3-C reports it). `stale_sources` additionally maps `cpt_` ids to superseded documents of their quotes.

- [ ] **Step 1: Tests.**
```python
def test_agent_proposal_with_own_source_stays_hidden():           # acceptance 6
    cid = define_concept(project, agent, concept(name="random features", source=TEXTBOOK))
    assert concept_view(project, cid).review_state == "unreviewed" and cid not in ids(list_concepts(project))
    assert list_concepts(project).hidden.unapproved == 1
def test_agent_cannot_approve():
    with pytest.raises(FactoryValidationError) as e: decide_concept_source(project, agent, cid, "approve", "", Channel.MCP)
    assert e.value.issues[0].field == "actor"
def test_human_define_with_approval_is_visible_and_human_authored(): ...
def test_unverifiable_source_refuses_quotes_and_is_flagged():     # ruling B3
    with pytest.raises(FactoryValidationError) as e: define_concept(project, agent, concept(source=TEXTBOOK, quotes=[q]))
    assert e.value.issues[0].field == "quotes"
def test_corpus_source_quotes_must_come_from_source_work(): ...    # field "quotes[0].work_id", reason "not-source-work"
def test_name_or_alias_collision_refused_with_existing_id(): ...  # ruling B4
def test_redefinition_must_name_live_definition(): ...           # ruling B5
def test_agent_redefinition_with_new_source_hides_concept(): ...  # Review Focus 3
def test_text_over_600_refused_and_nothing_written(): ...
def test_reject_needs_note_and_keeps_concept_hidden(): ...
def test_concept_quote_source_stale_flag(): ...
# tests/test_concepts_review.py (ruling B2)
def test_agent_cannot_review_concept():
    with pytest.raises(FactoryValidationError) as e: review_concept(project, agent, cid, "reviewed", "", Channel.MCP)
    assert e.value.issues[0].field == "actor"
def test_approved_agent_concept_shown_unreviewed_until_reviewed():
    assert concept_view(project, cid).label == "interpretation · unreviewed" and cid in ids(list_concepts(project))
    review_concept(project, human, cid, "reviewed", "", Channel.CLI); assert concept_view(project, cid).review_state == "reviewed"
def test_wrong_hides_concept_and_needs_note(): ...                # hidden.wrong == 1; history keeps both events
def test_redefinition_resets_review(): ...
def test_self_review_one_human_flagged_two_humans_refused(): ...  # A7 applied to human-written definitions
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(concepts): definition, identity, source approval, definition review`.

### Task 4: `uses` links: proposal, classification, cycles, human decisions

*Tier: critical (stated/inferred, R-51).*

**Files:** Modify `services/concepts.py`; Test `tests/test_concepts_links.py`.

**Interfaces:**
- Consumes: Task 1 `classify_use`, `would_cycle`; `verify_sources`; `entry_link`; G3-A `target_issue` (paper and idea rule); G2-C `idea_view` (`effective_members`); G2-B `is_live_reference_extraction`, `reference_view_of`.
- Produces: `class LinkResult(StrictModel)`: `link_id`, `status`, `status_reason`, `existing: bool`; `propose_concept_link(project: Project, actor: Actor, from_node: str, concept_id: str, basis: UseBasisInput, note: str | None = None) -> LinkResult` (agent or human; from-node a paper or idea accepted by G3-A `target_issue` (corpus paper node; confirmed, unmerged idea), or a live unmerged concept; concept live and unmerged, `merged` reason names `into`; self-link refused; quote basis verified and of the from-paper or a member in the from-idea's `effective_members` (`basis.quote.work_id`, `not-from-work`); reference basis an entry of a live G1 extraction of that work (`basis.reference`, `not-from-work`), not allowed from a concept; no basis needs `note`; cycle refused (ruling B8); idempotence per ruling B7); `decide_concept_link(project, actor, link_id: str, decision: Literal["confirm", "reject"], rationale: str, channel: Channel) -> str` (human only; `confirm` only an inferred link, field `decision`); `class ConceptLinkView(StrictModel)`: `link_id`, `class_`, `label`, `from_node`, `from_kind`, `concept_id` (effective), `raw_concept_id`, `basis_kind`, `quote: StoredSource | None`, `reference`, `status`, `status_reason`, `note`, `decided_by`; `list_concept_links(project, *, statuses: Collection[LinkStatus] | None = None, concept_id: str | None = None, cursor: str | None = None) -> ConceptLinkList(items, hidden: ConceptHidden, next_cursor)` (default statuses `stated`, `confirmed`).

- [ ] **Step 1: Tests.**
```python
def test_quote_with_name_is_stated():                              # acceptance 7
    r = propose_concept_link(project, agent, P1, C_RF, UseBasisInput(quote=quote_src(P1, CNV1, "s1.p2", "positive random-feature map")))
    assert (r.status, r.status_reason) == ("stated", "name-in-quote")   # alias "random-feature map"
def test_citation_of_approved_source_is_stated(): ...
def test_other_links_inferred_and_absent_from_default(): ...        # acceptance 7
def test_reproposal_after_approval_records_new_stated_link():     # Review Focus 4
    first = propose(...); approve(C_RF); second = propose(...)
    assert (first.status, second.status, second.existing) == ("inferred", "stated", False)
def test_identical_proposal_is_idempotent(): assert propose(...).existing is True and event_count_unchanged()
def test_quote_from_another_work_refused(): ...
def test_merged_concept_target_refused_with_into(): ...
def test_concept_cycle_refused():                                  # acceptance 7
    link(C1, C2); link(C2, C3)
    with pytest.raises(FactoryValidationError) as e: link(C3, C1)
    assert e.value.issues[0].reason == "cycle"
def test_only_human_confirms_and_reject_supersedes(): ...          # R-51; confirm then reject -> rejected, hidden
def test_confirm_of_stated_link_refused(): ...
def test_no_basis_needs_note(): ...
def test_agent_event_provenance(): ...                             # acceptance 1
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(concepts): uses links with stated/inferred rule, cycle refusal, human decisions`.

### Task 5: Merge and unmerge

*Tier: critical (reversibility, acceptance 11).*

**Files:** Modify `services/concepts.py`; Test `tests/test_concepts_merge.py`.

**Interfaces:**
- Produces: `merge_concepts(project: Project, actor: Actor, into: str, from_concept: str, reason: str) -> str` and `unmerge_concepts(project, actor, into: str, from_concept: str, reason: str) -> str` (human only; refusals of ruling B9; unmerge needs an active merge `into ← from_concept`); `effective_concept(project, concept_id) -> str` (follows the active merge; one level by B9).

- [ ] **Step 1: Tests.**
```python
def test_merge_unions_aliases_and_repoints_links(): ...
def test_alias_collision_through_merge_and_after_unmerge():        # Review Focus 1
    merge(C1, C2)   # C2 has alias "RFF"
    assert refused(define("RFF")); unmerge(C1, C2); assert refused(define("RFF")).refs == [C2]
def test_merge_unmerge_restores_projection_exactly(): ...          # acceptance 11 via the service
def test_self_link_merge_refused(): ...                            # Review Focus 5
def test_merge_creating_cycle_refused(): ...
def test_chain_merges_refused(): ...                               # into merged, or from has members
def test_unmerge_without_merge_refused(): ...
def test_agent_cannot_merge(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(concepts): reversible merge and unmerge`.

### Task 6: Wiring: batch, separation, MCP tools, skill

*Tier: standard for the tools and skill; the separation extension is critical.*

**Files:** Modify `services/interpretations.py`, `mcp/server.py`, `plugin/skills/rf-intuition/SKILL.md`, `tests/intuition_helpers.py`, `tests/test_intuition_separation.py`; Test `tests/test_mcp_concepts.py`.

**Interfaces:**
- `IntuitionBatch` gains `concepts: list[ConceptBrief] = []` (visible concepts, so the writer can link and cite them).
- MCP: `concept_propose(project, name, role, model, skill, aliases: list[str] = [], text: str | None = None, source: dict | None = None, quotes: list[dict] = [], concept_id: str | None = None, supersedes: str | None = None)` → `{"concept_id", "source_state", "review_state"}`; `concept_link(project, from_node, concept_id, role, model, skill, quote: dict | None = None, reference: str | None = None, note: str | None = None)` → `LinkResult`. Both refused to pass sessions as G3-A's tools. No MCP tool for source decisions, concept reviews, link decisions, merge or unmerge.
- `populate_layer` adds three concepts (one approved and reviewed, one approved and reviewed `wrong`, one unapproved), a stated, an inferred and a rejected link, a concept-to-concept link, and a merge; `LAYER_TABLES` gains the Task 2 tables (including `concept_reviews`).
- Skill section "Concepts": propose a concept only for an outside idea a paper relies on; give the source the paper itself cites when possible; draft text from the approved source with verbatim quotes, ≤ 600 characters; never quote a source without a document; propose `uses` links with a quote that names the concept or with the citing reference entry; a drafted definition is shown `unreviewed` until the researcher reviews it; never approve, review, confirm or merge.

- [ ] **Step 1: Tests.** Tool list pinned with the two new names; `concept_propose` with a quote from a non-source work returns the structured error and writes nothing; an extraction-pass session is refused both; the batch lists only visible concepts; the differential test (G3-A helper, now with concepts) still shows byte-identical evidence outputs; the architecture test covers `factory.services.concepts`; skill names `concept_propose`, `concept_link`, "approved source", "never approve".
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Full suite, mypy, ruff. **Step 5:** Commit `feat(concepts): MCP tools, batch concepts, separation extended, skill section`.

## Open questions

None. The former question (no human review of agent-drafted concept text) was closed on 2026-11-04 by adding `concept.reviewed` (ruling B2).

## Self-review notes

- **Spec coverage.** Concept nodes, sources and definition review (ruling 2; Tasks 1–3); `uses` rule, human confirmation, cycle refusal (rulings 1, 3; Tasks 1, 4); identity and merge (ruling 10; Tasks 3, 5); hidden counts for concepts (ruling 7; Task 2); rebuild (acceptance 12; Task 2); MCP `concept_propose`, `concept_link` (Task 6). CLI, check, trace and layer views are G3-C.
- **Types.** `ConceptInput`, `UseBasisInput`, `LinkStatus`, `ConceptState`, `SourceState`, `ConceptHidden`, `ConceptView`, `ConceptBrief`, `ConceptLinkView`, `propose_concept_link`, `decide_concept_source`, `review_concept`, `concept_history`, `concept_review_counts`, `decide_concept_link`, `merge_concepts`, `unmerge_concepts` are used under these names in G3-C.
- **Risk.** Task 2's recompute-from-tables is what makes acceptance 11 hold; it is reviewed with the merge tests. Tiers: Tasks 1–5 critical, Task 6 standard.

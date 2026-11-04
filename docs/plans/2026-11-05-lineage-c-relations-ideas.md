# Relations, Ideas, Human Confirmation and Staleness Implementation Plan (slice 3b, sub-plan G2-C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: provisional — depends on the unconfirmed [confirm] rulings of slice-3b-lineage.md and on G1 ruling 14 (reference text in events; recommended: parsed fields plus a hash).** Classification reads only G1 link states and work ids, never entry text.

> **Dependencies.** G2-A and G2-B merged (Interfaces consumed exactly); G1 merged. This plan ends with every earlier test passing unchanged except the `PROJECTION_VERSION` pin.

**Goal:** Let Claude propose `builds-on` / `improves-on` relations and named ideas from verified contribution items; the platform classifies each relation as `stated` or `inferred` by a deterministic rule, only a human confirms or rejects, ideas merge reversibly, and anything resting on a superseded or stale basis is marked stale.

**Architecture:** A pure classifier (`lineage/classify.py`) turns the basis item, the G1 link of its cited entry and the proposed target into a status, a reason and flags. `services/relations.py` and `services/ideas.py` validate, classify and write a new event family (`relation.*`, `idea.*`) folded by `index/lineage.py`. Staleness and effective status are computed on read from the extraction ledger and G1 liveness, as plan D computes stale rows. Decisions are human-only service calls reached only from the CLI.

**Tech Stack:** as plan D; no new dependencies.

**Spec:** `docs/specs/slice-3b-lineage.md` User flow 4–5; rulings 1, 3, 10, 11, 12, 13, 14 (status vocabulary); Design "Relations", "Ideas"; Events `relation.*`, `idea.*`; MCP `relation_propose`, `idea_propose`; CLI `relations`, `ideas`; skill `rf-lineage`; acceptance 8, 9, 10 (relations part), 11 (relations part), 12. `01-rigour.md` R-26, R-51; proposed R-xx(e), R-xx(f).

## Rulings made in this plan

1. **Classification order (spec ruling 11).** `no-basis` (no basis item) → `no-cited-entry` (basis has no `cited_entry`, or its work had no usable G1 extraction) → `link-unconfirmed` (the link of that entry in the extraction named by the item's `cited` is not `resolved`) → `target-differs` (the link's work is not the proposed target, or the target is an idea) → `stated`. `CLASSIFIER_VERSION = "1"` is recorded on every proposal. Flag `uncited-base`: the target is a work and no entry of the source work's current G1 extraction resolves to it.
2. **Idea targets. [confirm]** A relation to an idea is always `inferred` (reason `target-differs`); only a human confirmation makes it count.
3. **Basis.** `basis_item` must be a recorded contribution row of `source_work`, live (not superseded), not stale, of kind `base-idea` or `addition` (`basis_item`, reasons `basis-unknown`, `basis-other-work`, `basis-not-live`, `basis-stale`, `basis-kind`). Without a basis a non-blank `note` (≤ 500 characters, labelled `agent-note`) is required (`note`).
4. **Idempotence and supersession. [confirm]** For the same (source, target, type): an existing live relation with the same `basis_item` is returned, nothing written; one with a different basis is superseded by the new proposal (`supersedes`), and its decision does not carry over, unless it was rejected by a human, in which case the proposal is refused (`target`, `rejected-by-human`). A stale live relation is always superseded by a new proposal.
5. **Decisions (spec rulings 3, 14; acceptance 9).** `decide_relation` refuses any actor whose kind is not `human` (field `actor`). `confirm` applies only to `inferred` relations; `reject` applies to any live relation. A decision supersedes the previous decision of the relation. No MCP tool decides. The projector folds a `relation.decided` or `idea.decided` event only when its actor kind is `human` (defence in depth).
6. **Effective status (spec rulings 12, 14).** `rejected` if the latest decision rejects; else `stale` if any stale reason holds; else `confirmed` if the latest decision confirms; else the proposal status. Stale reasons: `basis-superseded`, `basis-stale` (the basis row is in `stale_extractions(scope=CONTRIBUTION)`), `references-superseded` (`reference_extraction_id` is not live), `link-changed` (a `stated` relation whose link is no longer `resolved` to the target). Effective statuses: `stated|confirmed|inferred|stale|rejected`.
7. **Ideas (spec rulings 1, 13). [confirm]** `idea.proposed` is written by `propose_idea` for an agent and for a human (`idea_define`); both require `name_item`: a live, non-stale contribution row of `origin` with a `name` field whose quote contains the normalised idea name (`name`, `name-not-in-quote`). `members` are work ids known to the index (corpus works or G1 link targets), unique, include `origin`, stored sorted. A revised grouping is a new proposal with `supersedes`. Confirm and reject are human only.
8. **Merges (R-26 spirit). [confirm]** `idea.merged(from_idea, into, reason)` and `idea.unmerged(from_idea, into, reason)`, human only. Both ideas must be live and not rejected; a merge that would create a cycle is refused; `unmerge` reverts the latest merge of `from_idea`. Views resolve merges transitively: the merged idea is not drawn, its members join `into`'s effective members, and relations targeting it point to `into`. The spec's payload key `from` is `from_idea` (a Python keyword otherwise).
9. **Candidates (spec ruling 13).** `idea_candidates` lists works with a live item whose normalised `name` equals the idea name (reason `name-in-item`) and works with a `stated` or `confirmed` `builds-on` relation to the origin (reason `builds-on-origin`). Listing only; the human confirms members.

## Global Constraints

- All G2-A/G2-B constraints hold. The platform never calls a model; the agent never sets a status, count, hash or id (the input models forbid `status`).
- Every agent-written event carries model, skill reference and `input_blob`; human events carry the human actor and channel.
- `relation.*` and `idea.*` events carry no document text; `note` is the only free agent text, never counted and never in default exports.
- Business logic in `services/`; the classifier is pure. `mcp/` and `cli/` parse and format.
- TDD; `mypy --strict`, ruff; coverage >= 90% for `services/` and `model/`.

## Review Focus

1. The G1 link of a stated relation's entry is rejected by a human after the relation was stated: the relation becomes `stale` (`link-changed`), leaves default views and returns only when re-proposed (Task 4, `test_link_rejection_stales_stated_relation`).
2. An agent re-proposes a relation a human rejected, with a different basis: refused, nothing written (Task 3, `test_rejected_triple_cannot_be_reproposed`).
3. A `relation.decided` event with an agent actor written to the log by hand does not change the projection (Task 1, `test_projector_ignores_non_human_decisions`).
4. Merge A into B, then B into C, then unmerge A: A's members return to A and C keeps B's; an A-into-C merge while C is merged into A is refused as a cycle (Task 5, `test_chained_merge_and_cycle`).
5. A relation whose basis item is corrected (superseded) keeps its id in the log, is `stale`, and re-proposing from the new item writes a new relation that supersedes it (Task 4, `test_basis_correction_stales_and_reproposal_restores`).

## File Structure

- Create `model/lineage.py`, `index/lineage.py`, `lineage/classify.py`, `services/relations.py`, `services/ideas.py`.
- Modify `events/catalog.py`, `index/default.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`, `tests/test_plugin.py`; create `plugin/skills/rf-lineage/SKILL.md`.
- Tests: `test_lineage_model.py`, `test_lineage_index.py`, `test_lineage_classify.py`, `test_relations.py`, `test_relation_staleness.py`, `test_ideas.py`, `test_mcp_lineage.py`, `test_cli_lineage.py`; helper `tests/lineage_helpers.py` (G2-B project with final contribution items, G1 links in each state, and builders `propose(...)`, `confirm(...)`).

---

### Task 1: Lineage events and projection

*Tier: critical (events, index).*

**Files:** Create `model/lineage.py`, `index/lineage.py`; Modify `events/catalog.py`, `index/default.py`; Test `tests/test_lineage_model.py`, `tests/test_lineage_index.py`; update the `PROJECTION_VERSION` pin.

**Interfaces:**
- Produces (`model/lineage.py`): `REL_ID_RE = rf"^rel_{ULID_RE}$"`, `IDEA_ID_RE = rf"^ida_{ULID_RE}$"`; `EdgeType(StrEnum)`: `CITES = "cites"`, `BUILDS_ON = "builds-on"`, `IMPROVES_ON = "improves-on"`; `RelationType = Literal["builds-on", "improves-on"]`; `ProposalStatus = Literal["stated", "inferred"]`; `EdgeStatus(StrEnum)`: `STATED`, `CONFIRMED`, `INFERRED`, `STALE`, `REJECTED` (values lower-case); `DEFAULT_STATUSES = frozenset({EdgeStatus.STATED, EdgeStatus.CONFIRMED})`; `StatusReason(StrEnum)`: `NO_BASIS = "no-basis"`, `NO_CITED_ENTRY = "no-cited-entry"`, `LINK_UNCONFIRMED = "link-unconfirmed"`, `TARGET_DIFFERS = "target-differs"`; `LineageDecision(StrEnum)`: `CONFIRM`, `REJECT`; `RelationProposal(StrictModel)` (agent input): `source_work: str`, `target: str`, `edge_type: RelationType`, `basis_item: str | None = None` (`EXTRACTION_ID_RE`), `note: str | None = Field(default=None, max_length=500)`; payloads `RelationProposed(relation_id, source_work, target, edge_type, basis_item, note, status: ProposalStatus, status_reason: StatusReason | None, resolved_target: str | None, reference_extraction_id: str | None, cited_entry: int | None, flags: tuple[str, ...], classifier: str, supersedes: str | None)` (validators: `stated` ⇒ `basis_item`, `reference_extraction_id`, `cited_entry` set, `resolved_target == target`, reason `None`; `inferred` ⇒ reason set; no basis ⇒ reason `no-basis` and non-blank note), `RelationDecided(relation_id, decision: LineageDecision, rationale: NonBlank)`, `IdeaProposed(idea_id, name: str (1..200, non-blank), name_item: str, origin: str, members: tuple[str, ...], supersedes: str | None)` (members unique, sorted, contain origin), `IdeaDecided(idea_id, decision, rationale: NonBlank)`, `IdeaMerged(from_idea, into, reason: NonBlank)`, `IdeaUnmerged(from_idea, into, reason: NonBlank)` (`from_idea != into`). Event types `relation.proposed`, `relation.decided`, `idea.proposed`, `idea.decided`, `idea.merged`, `idea.unmerged`, schema 1.
- Produces (`index/lineage.py`): `relations(relation_id pk, source_work, target, edge_type, basis_item, status, status_reason, resolved_target, reference_extraction_id, cited_entry, flags, note, supersedes, superseded_by, decision, decision_event_id, event_id)` (indexes on `(source_work, target, edge_type)`, `basis_item`, `target`); `ideas(idea_id pk, name, name_item, origin, supersedes, superseded_by, decision, decision_event_id, merged_into, event_id)`; `idea_members(idea_id, work_id; pk both)`; `idea_merges(event_id pk, kind merged|unmerged, from_idea, into)`. `merged_into` folds the latest merge/unmerge of `from_idea` in event order. Handlers total; first-write-wins on ids.

- [ ] **Step 1: Tests.** Model: `test_agent_cannot_send_status` (`RelationProposal(status="stated", ...)` rejected as extra), `test_stated_requires_basis_and_matching_target`, `test_inferred_requires_reason`, `test_no_basis_requires_note`, `test_idea_members_contain_origin_sorted_unique`, `test_merge_into_self_rejected`. Index: `test_supersession_sets_superseded_by`, `test_decision_latest_wins`, `test_projector_ignores_non_human_decisions` (Review Focus 3), `test_merge_unmerge_fold`, `test_rebuild_state_hash_stable`, `test_projection_version_bumped`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement and register. **Step 4:** Index suites; mypy; ruff. **Step 5:** Commit `feat(lineage): relation and idea events and projection`.

### Task 2: Stated/inferred classifier (pure)

*Tier: critical (the stated rule is R-xx(e)).*

**Files:** Create `lineage/classify.py`; Test `tests/test_lineage_classify.py`.

**Interfaces:**
- Produces: `CLASSIFIER_VERSION = "1"`; `@dataclass(frozen=True) BasisFacts(item_kind: str, cited_entry: int | None, reference_extraction_id: str | None)`; `@dataclass(frozen=True) LinkFacts(state: LinkState, work_id: str | None)`; `@dataclass(frozen=True) Classification(status: ProposalStatus, reason: StatusReason | None, resolved_target: str | None, flags: tuple[str, ...])`; `classify(basis: BasisFacts | None, link: LinkFacts | None, target: str, *, target_is_idea: bool, target_cited: bool) -> Classification` (ruling 1; `resolved_target` is the link's work when the link is resolved, else `None`; flag `uncited-base` when `not target_is_idea and not target_cited`).

- [ ] **Step 1: Tests** (acceptance 8; table-driven).
```python
@pytest.mark.parametrize("basis,link,target,idea,expected", [
    (None, None, "rf:b", False, ("inferred", "no-basis")),
    (B(cited=None), None, "rf:b", False, ("inferred", "no-cited-entry")),
    (B(cited=5), L("unconfirmed", "rf:b"), "rf:b", False, ("inferred", "link-unconfirmed")),
    (B(cited=5), L("ambiguous", None), "rf:b", False, ("inferred", "link-unconfirmed")),
    (B(cited=5), L("resolved", "rf:c"), "rf:b", False, ("inferred", "target-differs")),
    (B(cited=5), L("resolved", "rf:b"), "ida_X", True, ("inferred", "target-differs")),
    (B(cited=5), L("resolved", "rf:b"), "rf:b", False, ("stated", None)),
])
def test_classification(basis, link, target, idea, expected): ...
def test_uncited_base_flag(): assert "uncited-base" in classify(None, None, "rf:b", target_is_idea=False, target_cited=False).flags
def test_resolved_target_reported_even_when_differs(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(lineage): stated/inferred classifier`.

### Task 3: Relation proposals and human decisions

*Tier: critical (R-51, classification wiring).*

**Files:** Create `services/relations.py`; Test `tests/test_relations.py`.

**Interfaces:**
- Consumes: Task 1, Task 2; G2-B `contribution_item`, `reference_view`, `reference_view_of`, `is_live_reference_extraction`; G2-A `stale_extractions(..., scope=Scope.CONTRIBUTION)`; `canonical_works`; `require_agent`-style actor checks.
- Produces: `class ProposeResult(StrictModel)`: `relation_id: str`, `status: ProposalStatus`, `status_reason: StatusReason | None`, `flags: tuple[str, ...]`, `written: bool`; `propose_relation(project, actor, proposal: RelationProposal) -> ProposeResult` (agent or human actor; rulings 1, 3, 4; target must be a known work id or a live, non-rejected idea id, field `target`, reason `target-unknown`; `source_work` must be in the contribution population, `source_work`, `not-in-population`; nothing written on refusal); `decide_relation(project, actor, relation_id: str, decision: LineageDecision, rationale: str) -> str` (ruling 5; returns the event id).

- [ ] **Step 1: Tests.**
```python
def test_stated_when_cited_entry_resolves_to_target(project):           # acceptance 8
    r = propose_relation(project, agent, P(source=W1, target=W0, type="builds-on", basis=BASE_CITING_5))
    assert (r.status, r.status_reason, r.written) == ("stated", None, True)
def test_inferred_when_target_differs_link_unconfirmed_or_no_basis(project): ...
def test_no_basis_needs_note(project): ...
def test_basis_must_be_live_base_or_addition_of_source(project): ...    # each reason
def test_idempotent_same_basis(project): assert propose(...).relation_id == first.relation_id and not propose(...).written
def test_new_basis_supersedes_and_drops_decision(project): ...
def test_rejected_triple_cannot_be_reproposed(project): ...             # Review Focus 2
def test_agent_cannot_decide(project):                                   # acceptance 9
    with pytest.raises(FactoryValidationError) as e: decide_relation(project, agent, rid, LineageDecision.CONFIRM, "x")
    assert e.value.issues[0].field == "actor" and no_new_events(project)
def test_confirm_only_inferred_reject_any(project): ...
def test_reject_after_confirm_supersedes(project): ...
def test_event_provenance(project): ...                                  # model, skill, input_blob; classifier "1"
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(lineage): relation proposals, classification and human decisions`.

### Task 4: Relation views, effective status and staleness

*Tier: critical (staleness, default views).*

**Files:** Modify `services/relations.py`; Test `tests/test_relation_staleness.py`.

**Interfaces:**
- Produces: `class RelationView(StrictModel)`: `relation_id`, `source_work`, `target`, `edge_type: RelationType`, `basis_item: str | None`, `proposal_status: ProposalStatus`, `status_reason: StatusReason | None`, `decision: LineageDecision | None`, `effective: EdgeStatus`, `stale_reasons: tuple[str, ...]`, `flags: tuple[str, ...]`, `reference_extraction_id: str | None`, `cited_entry: int | None`, `has_note: bool`, `event_id: str`; `relation_view(project, relation_id) -> RelationView | None`; `list_relations(project, *, statuses: Collection[EdgeStatus] = DEFAULT_STATUSES, work_id: str | None = None) -> list[RelationView]` (live relations only, i.e. not superseded; sorted by `(source_work, edge_type, target, relation_id)`; `work_id` matches source or target); `relation_counts(project) -> dict[str, dict[str, int]]` (edge type -> effective status -> count, every status present).

- [ ] **Step 1: Tests** (acceptance 11, relations part).
```python
def test_basis_correction_stales_and_reproposal_restores(project): ...   # Review Focus 5
def test_amendment_removing_field_stales_relation(project):
    amend_contribution(remove="compared_to"); assert relation_view(project, rid).stale_reasons == ("basis-stale",)
def test_new_document_version_stales_relation(project): ...
def test_new_g1_extraction_stales_relation(project): ...                 # references-superseded
def test_link_rejection_stales_stated_relation(project): ...             # Review Focus 1
def test_default_list_excludes_inferred_stale_rejected(project):          # acceptance 9
    assert {r.effective for r in list_relations(project)} <= {EdgeStatus.STATED, EdgeStatus.CONFIRMED}
def test_confirmed_relation_appears_in_default_list(project): ...
def test_counts_cover_every_status(project): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement (ruling 6; one pass over the live relations with the stale sets loaded once). **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(lineage): effective relation status and staleness`.

### Task 5: Ideas: proposal, definition, decision, merge and candidates

*Tier: critical (R-26, R-51).*

**Files:** Create `services/ideas.py`; Test `tests/test_ideas.py`.

**Interfaces:**
- Consumes: Task 1; G2-B `contribution_item`, `live_items`; Task 4 `list_relations`; `normalise_text`.
- Produces: `propose_idea(project, actor, name: str, origin: str, name_item: str, members: Sequence[str], *, supersedes: str | None = None) -> str` (agent or human; ruling 7); `decide_idea(project, actor, idea_id, decision: LineageDecision, rationale: str) -> str` (human); `merge_ideas(project, actor, from_idea: str, into: str, reason: str) -> str` and `unmerge_idea(project, actor, from_idea: str, reason: str) -> str` (human; ruling 8); `IdeaState = Literal["proposed", "confirmed", "rejected", "merged", "superseded"]`; `class IdeaView(StrictModel)`: `idea_id`, `name`, `origin`, `name_item`, `members: tuple[str, ...]`, `effective_members: tuple[str, ...]`, `state: IdeaState`, `merged_into: str | None`, `event_id`; `idea_view(project, idea_id) -> IdeaView | None`; `list_ideas(project, *, include_unconfirmed: bool = False) -> list[IdeaView]` (default: confirmed, not merged, not superseded; by idea id); `resolve_idea(project, idea_id) -> str` (follows merges); `class IdeaCandidate(StrictModel)`: `work_id`, `reasons: tuple[Literal["name-in-item", "builds-on-origin"], ...]`; `idea_candidates(project, origin: str, name: str) -> list[IdeaCandidate]` (ruling 9; by work id).

- [ ] **Step 1: Tests** (acceptance 12).
```python
def test_name_must_be_in_verified_quote(project):
    with pytest.raises(FactoryValidationError) as e: propose_idea(project, agent, "Gated Linear Attention", W1, ITEM_WITHOUT_NAME, [W1])
    assert e.value.issues[0].field == "name"
def test_human_define_needs_quote_too(project): ...
def test_unconfirmed_idea_not_listed_by_default(project): ...
def test_agent_cannot_confirm_merge_or_unmerge(project): ...
def test_merge_and_unmerge_restore_views_exactly(project):
    before = list_ideas(project); merge_ideas(project, human, A, B, "same method, two names"); unmerge_idea(project, human, A, "split again")
    assert list_ideas(project) == before
def test_chained_merge_and_cycle(project): ...                           # Review Focus 4
def test_candidates_from_names_and_builds_on(project): ...
def test_superseding_proposal_replaces_members(project): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(lineage): ideas with human confirmation and reversible merge`.

### Task 6: MCP tools, CLI and the `rf-lineage` skill

*Tier: Haiku implement and review (surfaces); the skill by Sonnet.*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`, `tests/test_plugin.py`; Create `plugin/skills/rf-lineage/SKILL.md`; Test `tests/test_mcp_lineage.py`, `tests/test_cli_lineage.py`, extend `tests/test_skills.py`.

**Interfaces:**
- MCP: `relation_propose(project, source_work, target, edge_type, role, model, skill, basis_item: str | None = None, note: str | None = None)` -> `ProposeResult`; `idea_propose(project, name, origin, name_item, members: list[str], role, model, skill)` -> idea id. Both refused to pass sessions of any scope (`_refuse_pass_session` plus `is_extraction_session`). No MCP tool reaches `decide_relation`, `decide_idea`, `merge_ideas` or `unmerge_idea`.
- CLI: `factory relations list [--status S]… [--work W]`, `factory relations confirm REL --rationale TEXT`, `factory relations reject REL --rationale TEXT`; `factory ideas list [--all]`, `factory ideas define NAME --origin W --name-item EXT --member W…`, `factory ideas candidates --origin W --name NAME`, `factory ideas confirm IDA --rationale TEXT`, `factory ideas reject IDA --rationale TEXT`, `factory ideas merge FROM INTO --reason TEXT`, `factory ideas unmerge FROM --reason TEXT`. Human actor, channel `cli`. `relations list` prints every row's effective status and reason; notes are shown labelled `agent-note`.
- Skill `rf-lineage`: propose a relation only from a recorded `base-idea` or `addition` item; one target per item; prefer the work the item's `cited_entry` resolves to; when proposing another target, say why in `note`; never claim a relation is confirmed; propose an idea only with a `name_item` whose quote contains the name; never merge; report inferred counts to the researcher for confirmation.

- [ ] **Step 1: Tests.** MCP: tool list pinned with the two new names and no `*_decide`, `*_confirm`, `*_merge`; `relation_propose` returns the platform status and ignores nothing (an extra `status` argument is a structured error); a pass session is refused. CLI: `relations confirm` writes a human `relation.decided`; `ideas merge` then `ideas unmerge` leaves `ideas list` unchanged; `relations list` prints statuses. Skill: names `relation_propose`, `idea_propose`, `basis_item`, `note`, "never confirm"; `SKILLS` includes `rf-lineage`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Tests; mypy; ruff. **Step 5:** Commit `feat(lineage): MCP proposal tools, relations and ideas CLI, rf-lineage skill`.

## Self-review notes

- **Spec coverage.** Rulings 1, 3, 10 (edge direction: source is the later work; `improves-on` stored separately), 11 (Task 2), 12 (Task 4), 13 (Task 5), 14 (status vocabulary, Task 1, 4); events (Task 1); human-only decision path (Tasks 3, 5, 6); acceptance 8, 9, 12 and the relation parts of 10, 11. Idea-level derived edges and graph views are G2-D.
- **Types used later.** `EdgeType`, `EdgeStatus`, `DEFAULT_STATUSES`, `StatusReason`, `LineageDecision`, `REL_ID_RE`, `IDEA_ID_RE`, `RelationView`, `list_relations`, `relation_view`, `relation_counts`, `IdeaView`, `list_ideas`, `idea_view`, `resolve_idea`, tables `relations`, `ideas`, `idea_members`, `idea_merges`.
- **Tiers.** Tasks 1–5 critical (Sonnet reviews; Tasks 2 and 4 get a second look on the rule tables), Task 6 Haiku.

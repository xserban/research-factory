# Link Inbox and Discovery Provenance Implementation Plan (slice 4a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: draft for the researcher's review — not to be built until accepted.** The spec `docs/specs/slice-4a-inbox-discovery.md` is itself a draft; every ruling it marks **[confirm]** must be confirmed (or changed, and this plan with it) before Task 1 starts.

> **Dependencies.** Plan `2026-11-05-cleanups-2.md` Tasks 1 and 2 merged first: Task 1 adds the projected `event_refs` table this plan reads; Task 2 links chase queries to their round by ref, which the discovery record needs to tell `chase` from `snowball` runs without text matching. G1 (`2026-11-04-references-snowballing.md`) Tasks 1–6 are merged on the base (`snowball_rounds`, `round_runs`). Paths are relative to `platform/` unless they start with `docs/` or `plugin/`.

**Goal:** Capture researcher- and agent-supplied links as inbox items, resolve them into the corpus as `supplied`-provenance candidates under a protocol gate, and compute and report each work's discovery record.

**Architecture:** A pure link parser (`factory/inbox/links.py`) normalises a link to one identifier at the boundary. `services/inbox.py` records captures, withdrawals and resolutions; a resolve is an ordinary `register_query` + `run_query` with the new purpose `supplied`, so lookup archiving, gating and dedup reuse slice-1 code unchanged. A new protocol section `supplied_links` (omitted from the hash while absent) waives the planned-query check for the accepted submitter kinds. `services/discovery.py` is a read-only builder over provenance, run starts, round tables, inbox items, outcomes and final evidence rows; PRISMA, methods, trace and check consume it.

**Tech Stack:** as slices 1–2; no new dependencies.

**Spec:** `docs/specs/slice-4a-inbox-discovery.md` rulings 1–14, acceptance 1–14. `docs/specs/01-rigour.md` R-01–R-05, R-13–R-15, R-21–R-26, R-30–R-39, R-47, R-51. Decisions 37 (items 6, 9), 38 (items 3, 6), 43, 46 (item 7), 48, 50.

## Global Constraints
- The platform never calls a model. Events are the source of truth; the index is written by the projector alone.
- Every agent-written event carries model, skill reference and `input_blob`; an agent capture's `input_blob` is the validated item as the agent sent it.
- Invalid input writes nothing and returns structured errors; `inbox_add` is a batch with partial success (00-system §7).
- No note, link or route reaches screening or extraction task content (spec ruling 8).
- A log without inbox events and without `supplied_links` replays to identical `P@` ids and an identical state hash except `PROJECTION_VERSION`.
- Business logic in `services/`; `mcp/` and `cli/` parse and format only.
- `uv run pytest -m "not network"`, `mypy --strict`, `ruff check`, `ruff format --check` pass after each task; coverage ≥ 90% for `services/` and `model/`.

## Review Focus
1. A supplied work's `screen_next` content contains no route, note or `basis` and matches a database work's shape (Task 6, `test_screen_task_is_route_blind`).
2. A session that captured a link cannot join a screening pass; a pass session is refused by every inbox tool (Tasks 5, 9).
3. PRISMA arithmetic holds with `supplied`; a work found by search and link counts under databases only (Task 8, `test_prisma_supplied_and_database_counts_database`).
4. First-surfaced is decided by event order, with capture (not resolution) as the supplied surfacing event (Task 7, `test_capture_before_search_surfaces_first`).
5. A held-out seed reached only by link is `supplied`, not `retrieved` (Task 6, `test_supplied_seed_is_not_retrieved`).

## File Structure
- Create `src/factory/inbox/__init__.py`, `src/factory/inbox/links.py`, `src/factory/model/inbox.py`, `src/factory/index/inbox.py`, `src/factory/services/inbox.py`, `src/factory/services/discovery.py`.
- Modify `model/work.py`, `model/search.py`, `sources/arxiv.py`, `sources/openalex.py`, `model/protocol.py`, `services/protocol_rules.py`, `services/protocol.py`, `events/catalog.py`, `index/default.py`, `services/screening.py`, `services/seeds.py`, `services/prisma.py`, `services/methods.py`, `services/trace.py`, `services/check.py`, `services/project.py`, `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- Modify `plugin/skills/rf-search/SKILL.md`; `docs/specs/01-rigour.md` (R-02 list), `docs/specs/slice-4a-inbox-discovery.md` (status), `docs/decisions.md` (Task 10).
- Tests: `tests/test_inbox_links.py`, `tests/test_inbox_model.py`, `tests/test_inbox_index.py`, `tests/test_supplied_links_protocol.py`, `tests/test_inbox_service.py`, `tests/test_inbox_screening.py`, `tests/test_discovery.py`, `tests/test_inbox_reports.py`, `tests/test_mcp_inbox.py`, `tests/test_cli_inbox.py`, `tests/test_acceptance_inbox.py`; helper `tests/inbox_helpers.py` (a pilot project with a ready, PRESS-confirmed protocol, a fake arXiv/OpenAlex adapter pair keyed by identifier, and `capture(...)`/`resolve(...)` shortcuts).

---

### Task 1: Link parser (pure)

*Tier: standard (pure function; implementer sonnet, review haiku).*

**Files:** Create `src/factory/inbox/__init__.py`, `src/factory/inbox/links.py`; Test `tests/test_inbox_links.py`.

**Interfaces:**
- Consumes: `normalize_doi`, `normalize_arxiv`, `arxiv_id_from_doi` (`model/work_ids.py`).
- Produces: `class IdentifierKind(StrEnum): ARXIV, DOI, OPENALEX`; `@dataclass(frozen=True) LinkIdentifier(kind: IdentifierKind, value: str, version: str | None)`; `parse_link(link: str) -> LinkIdentifier | None` (spec ruling 5; `None` = unsupported); `MAX_LINK = 500`.

- [ ] **Step 1: Tests.**
```python
@pytest.mark.parametrize("link,kind,value,version", [
    ("2103.14030", ARXIV, "2103.14030", None),
    ("https://arxiv.org/abs/2103.14030v2", ARXIV, "2103.14030", "v2"),
    ("https://arxiv.org/pdf/2103.14030v1.pdf", ARXIV, "2103.14030", "v1"),
    ("arxiv.org/html/2103.14030", ARXIV, "2103.14030", None),
    ("10.1109/ICCV48922.2021.00986", DOI, "10.1109/iccv48922.2021.00986", None),
    ("https://doi.org/10.1109/ICCV48922.2021.00986", DOI, "10.1109/iccv48922.2021.00986", None),
    ("https://openaccess.thecvf.com/x/10.1109/ICCV.2021.1", DOI, "10.1109/iccv.2021.1", None),
    ("https://doi.org/10.48550/arXiv.2103.14030", ARXIV, "2103.14030", None),   # DataCite bridge
    ("https://openalex.org/W3138516171", OPENALEX, "W3138516171", None),
])
def test_parse_supported(link, kind, value, version): ...
@pytest.mark.parametrize("link", ["https://example.org/paper", "", "  ", "not a link", "x" * 501])
def test_parse_unsupported(link): assert parse_link(link) is None
def test_parse_is_whitespace_tolerant(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement with anchored regexes (`fullmatch`, no backtracking on unbounded groups; reuse `normalize_*`). **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(inbox): link parser`.

### Task 2: `supplied` method and purpose; adapters

*Tier: standard.*

**Files:** Modify `model/work.py`, `model/search.py`, `sources/arxiv.py`, `sources/openalex.py`, `services/prisma.py` (constant only); Test extend `tests/test_prisma.py` by new tests, `tests/test_sources_methods.py` (create).

**Interfaces:**
- Produces: `ProvenanceMethod.SUPPLIED = "supplied"`; `QueryPurpose.SUPPLIED = "supplied"`; both adapters' `_METHODS[QueryPurpose.SUPPLIED] = ProvenanceMethod.SUPPLIED`; `OTHER_METHODS = (CITATION_CHASE, SEED_ADMISSION, HAND_SEARCH, SUPPLIED)` (spec ruling 6).

- [ ] **Step 1: Tests.** An id-list arXiv query of purpose `supplied` yields works with method `supplied` (fixture response, offline); OpenAlex `doi:` filter likewise; `prisma_flow` on a hand-built log with one supplied-only work puts it in `identified_other["supplied"]` and the invariants hold; a work with `database` and `supplied` provenance counts under databases.
- [ ] **Step 2:** FAIL. **Step 3:** Implement; `search_authorization` needs no change here (non-probe purposes are gated alike). **Step 4:** Whole `tests/test_prisma*.py` and source tests unedited. **Step 5:** Commit `feat(search): supplied provenance method and query purpose`.

### Task 3: Inbox events and projection

*Tier: critical (events, index).*

**Files:** Create `model/inbox.py`, `index/inbox.py`; Modify `events/catalog.py`, `index/default.py` (register; bump `PROJECTION_VERSION`); Test `tests/test_inbox_model.py`, `tests/test_inbox_index.py`.

**Interfaces:**
- Produces (`model/inbox.py`): `INBOX_ID_RE = r"inb_[0-9A-HJKMNP-TV-Z]{26}"`; `class InboxRoute(StrEnum): LINK = "link"`; `class Basis(StrictModel): kind: Literal["document", "knowledge"]; document_id: str | None; anchor: str | None` (validator: both set iff `document`); `InboxLinkAdded(item_id, route, link, identifier_kind, identifier_value, identifier_version, note: str | None (≤300), basis: Basis | None, channel: Channel)`; `InboxLinkWithdrawn(item_id, reason)`; `class ResolveStatus(StrEnum): NEW, IN_CORPUS, NOT_FOUND, AMBIGUOUS, FAILED`; `InboxLinkResolved(item_id, query_id, run_id, status, work_id: str | None, deviation_id: str | None)` (validator: `work_id` set iff status in `{NEW, IN_CORPUS}`).
- Produces (`index/inbox.py`): tables `inbox_items`, `inbox_resolutions` (spec, Index tables); handlers for the three types; `inbox_items` status: `open` → `resolved` on any non-`failed` resolution, `withdrawn` on withdrawal; a resolution or withdrawal of an unknown or closed item is ignored by the projector (the service refuses it first).

- [ ] **Step 1: Tests.** Model invariants (note > 300 refused; `basis=document` without anchor refused; `work_id` rule); catalog round-trip for each type; projection: add → open, failed → open, new → resolved, withdraw → withdrawn; rebuild determinism (two rebuilds, same state hash); a log without inbox events gives the previous state hash apart from the version pin.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Whole suite (projection version pin is the only edited assertion). **Step 5:** Commit `feat(inbox): events and projection`.

### Task 4: Protocol section `supplied_links` and its gate

*Tier: critical (protocol hash, search gate).*

**Files:** Modify `model/protocol.py`, `services/protocol_rules.py`, `services/protocol.py`; Test `tests/test_supplied_links_protocol.py`.

**Interfaces:**
- Consumes: `AMENDABLE_FIELDS`, `_OMITTED_WHEN_NONE`, `search_authorization`.
- Produces: `SuppliedLinksPlan(StrictModel): accept_from: tuple[Literal["human", "agent"], ...]` (non-empty, no duplicates); `ProtocolSpec.supplied_links: SuppliedLinksPlan | None = None`, amendable, omitted from the hash while `None`; `search_authorization(..., supplied_by: Literal["human", "agent"] | None = None)`: for purpose `supplied`, the planned-query check is waived when `supplied_by in current.spec.supplied_links.accept_from`; every other gate unchanged. A `supplied` query with `supplied_by=None` is never waived.

- [ ] **Step 1: Tests.**
```python
def test_p_id_unchanged_without_supplied_links(): assert protocol_version(base_spec) == PINNED_P_ID   # literal from the base branch
def test_p_id_changes_with_supplied_links(): ...
def test_accept_from_validation(): ...                 # empty, duplicate, unknown kind -> errors on supplied_links.accept_from
def test_gate_waives_accepted_kind():
    assert search_authorization(p, supplied_q, deviation_id=None, supplied_by="human") == []
    assert fields(search_authorization(p, supplied_q, deviation_id=None, supplied_by="agent")) == {"query"}
def test_gate_needs_plan_or_deviation_in_pilot(): ...
def test_exploratory_ungated(): ...
def test_amend_adds_section_without_staling_decisions(): ...   # other_changes lists it; no stale decisions
```
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Protocol, amendment and search suites unedited. **Step 5:** Commit `feat(protocol): supplied_links section and gate`.

### Task 5: Inbox service

*Tier: critical (corpus admission).*

**Files:** Create `services/inbox.py`; Modify `services/screening.py` (join refusal); Test `tests/test_inbox_service.py`, `tests/inbox_helpers.py`.

**Interfaces:**
- Consumes: `parse_link`, `register_query`, `run_query`, `_run_works` pattern from `services/seeds.py` (copy the three-line query, do not import a private name), `list_works`, `screening_session`, `extraction`'s `extraction_session` equivalent.
- Produces:
  - `@dataclass(frozen=True) LinkInput(link: str, note: str | None = None, basis: Basis | None = None)`.
  - `add_links(project, actor, items: Sequence[LinkInput], channel: Channel) -> BatchResult[str]` — per item: `link` (`unsupported-link`), `note` (agent may not give one; ≤ 300), `basis` (required iff agent); actor must be human or agent; a pass session is refused for the whole batch (`session`).
  - `withdraw_link(project, actor, item_id, reason) -> None` — human only; item must be `open`.
  - `resolve_links(project, actor, *, sources, item_ids: Sequence[str] | None = None, deviation_id: str | None = None) -> list[ResolveOutcome]` — open items in id order; per item: lookup `QuerySpec` built as `seeds._lookup_query` builds it (arXiv `id_list`, OpenAlex `doi:`/`openalex:` filter) with purpose `SUPPLIED`; authorisation per item with `supplied_by` = the capturing actor's kind; a refused item is returned with its issues and writes nothing; `in-corpus` = the found work had non-probe provenance before the run; one `inbox.link_resolved` per attempted item. `ResolveOutcome(item_id, status, work_id, run_id, issues)`.
  - `list_items(project, *, status=None, cursor=None, limit=50) -> Page[InboxItemView]`.
  - `inbox_sessions(project) -> set[str]` (sessions that captured a link); `services/screening._check_join` refuses them with `session: "this session supplied a link and cannot screen"`.

- [ ] **Step 1: Tests.** Acceptance 1, 2 (no adapter called during `add_links`: adapter fake raises on use), 3, 4, 5, 9 (join refusal), 12; a lookup returning two records is `ambiguous` with no `work_id`; a failed lookup leaves the item open and a second resolve retries it; resolving a withdrawn item writes nothing.
- [ ] **Step 2:** FAIL. **Step 3:** Implement; capture, withdraw and each resolution write under `project.index.exclusive()` after `sync()`; the lookup fetch runs outside the lock (as `admit_seed`). **Step 4:** Screening join suites unedited. **Step 5:** Commit `feat(inbox): capture, withdraw, resolve`.

### Task 6: Screening blindness and seed recall

*Tier: critical (R-24, R-33/34).*

**Files:** Modify `services/seeds.py`; Test `tests/test_inbox_screening.py`.

**Interfaces:**
- Produces: `SeedCheck.status: Literal["retrieved", "supplied", "explained", "missing"]`; a matched work whose non-probe provenance methods are exactly `{supplied}` gives `supplied`; `_recall` counts only `retrieved`. `check`'s seed-gap counting treats `supplied` as a miss (adjust its literal set, no new finding).

- [ ] **Step 1: Tests.** `test_screen_task_is_route_blind` (Review Focus 1: `task_content` of a supplied and a database work have identical key sets and neither contains the note text, `supplied` or `inb_`); `test_supplied_work_enters_pass_b_extension` (acceptance 8); `test_supplied_seed_is_not_retrieved` (acceptance 10); a seed found by both search and link stays `retrieved`. Add one characterisation test pinning today's behaviour for an admitted seed (`retrieved`) with a comment pointing to spec ruling 9's open point.
- [ ] **Step 2:** FAIL (status and recall tests; the blindness test may pass at once — keep it as a guard and say so in the report). **Step 3:** Implement. **Step 4:** Seed and check suites; the only edited assertions are literal sets naming statuses. **Step 5:** Commit `feat(seeds): supplied-only seeds are not retrieved`.

### Task 7: Discovery builder

*Tier: critical (derived counts, R-05).*

**Files:** Create `services/discovery.py`; Test `tests/test_discovery.py`.

**Interfaces:**
- Consumes: `canonical_works`, `final_outcomes` (both stages), G1 `snowball_rounds` and `round_runs`, `chase_rounds` and cleanups-2's round-ref query map, `inbox_items`, `event_refs`, `grouped_rows`/final evidence rows (`scope=EVIDENCE` if present on the base).
- Produces: `class Route(StrEnum)` with values `database`, `chase-backward`, `chase-forward`, `snowball-backward`, `snowball-forward`, `seed-admission`, `supplied-human`, `supplied-agent`, `supplied-agent-knowledge`; `WorkDiscovery(work_id, routes: tuple[Route, ...], sources: tuple[str, ...], first_route: Route, first_event_id: str, first_actor_kind: Literal["human", "agent", "system"])`; `discovery(project) -> list[WorkDiscovery]` (canonical works, sorted by id); `DiscoveryReport(levels: tuple[str, ...], by_first_route: dict[Route, dict[str, int]], by_first_actor: dict[str, dict[str, int]], overlaps: dict[str, int], totals: dict[str, int])`; `discovery_report(project) -> DiscoveryReport` (levels `identified`, `ta-included`, `ft-included` when a full-text plan exists, `in-evidence`). Module docstring lists the inputs (spec ruling 14).

- [ ] **Step 1: Tests.** `test_capture_before_search_surfaces_first` (Review Focus 4); `test_absorbed_work_routes_fold` (merge two works, routes unite, first is the earlier); `test_chase_and_snowball_told_apart_by_round_ref`; `test_probe_runs_never_count`; `test_actor_kind_of_run_start` (system-started run → `system`); `test_columns_sum_to_totals` and totals equal PRISMA `screened` and included counts; `test_report_is_rebuild_stable`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement with set-based SQL over `provenance`, `runs`, `events` (run-start ids), `event_refs`; no log scan. **Step 4:** mypy; ruff. **Step 5:** Commit `feat(discovery): per-work discovery record and report`.

### Task 8: PRISMA, methods, trace, check, status

*Tier: standard.*

**Files:** Modify `services/prisma.py`, `services/methods.py`, `services/trace.py`, `services/check.py`, `services/project.py`; Test `tests/test_inbox_reports.py`.

**Interfaces:**
- Produces: `PrismaFlow.identified_other` carries `supplied` (Task 2) — no other change; methods paragraph (spec, Reports); trace node kind `inbox_item` (`INBOX_ID_RE`), edges work → item (back) and item → work (forward), label `link (<identifier kind>) captured by <actor kind>`; check findings `inbox-open-after-screening`, `inbox-resolve-failed`, `supplied-without-plan` (spec); `ProjectStatus.inbox: InboxCounts(open, resolved, withdrawn)` (defaulted, so old callers keep working).

- [ ] **Step 1: Tests.** `test_prisma_supplied_and_database_counts_database` (Review Focus 3); methods paragraph present only when an inbox event exists and its numbers equal `discovery_report`; trace acceptance 13; each check finding fires on a minimal log and not on a clean one; status counts.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PRISMA, methods, trace, check and status suites; edited assertions limited to the methods-text snapshot and the status key set. **Step 5:** Commit `feat(inbox): reports, trace, check, status`.

### Task 9: MCP tools, CLI and skill text

*Tier: standard (implementer sonnet, review sonnet: refusal lists).*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`, `plugin/skills/rf-search/SKILL.md`; Test `tests/test_mcp_inbox.py`, `tests/test_cli_inbox.py`.

**Interfaces:**
- Produces: MCP `inbox_add(project, items: list[{link, note?, basis?}], role, model, skill, channel="agent"|"mcp")`, `inbox_resolve(project, item_ids?, deviation_id?, role, model, skill)`, `inbox_list(project, status?, cursor?, limit?)`, `report_discovery(project)`; all refuse pass sessions through `_refuse_pass_session`; `report_discovery`'s agent view maps `seed-admission` to `other` (spec ruling 12). CLI `factory inbox add LINK... [--note]`, `inbox list [--status]`, `inbox resolve [--item ID]... [--deviation ID]`, `inbox withdraw ID --reason`, `factory report discovery [--json]`.

- [ ] **Step 1: Tests.** Tool registration and conventions (`test_mcp_conventions` picks the new tools up); pass-session refusal for each tool; human relay over MCP records `channel = mcp`; agent call without `basis` returns a structured error; CLI round trip in a tmp root; `report discovery --json` equals `discovery_report(...).model_dump(mode="json")`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement; skill text: when to use `inbox_add`, `basis` values, that screeners never see the route. Recompute the skill hash the way existing skills are hashed (no manual edit). **Step 4:** MCP and CLI suites. **Step 5:** Commit `feat(inbox): MCP tools, CLI, skill section`.

### Task 10: Acceptance, docs, decision

*Tier: standard.*

**Files:** Create `tests/test_acceptance_inbox.py`; Modify `docs/specs/01-rigour.md` (R-02 list adds `supplied`), `docs/specs/slice-4a-inbox-discovery.md` (status line, "Implemented" note), `docs/specs/00-system.md` (§3 id table: `inb_`; §9 commands), `docs/decisions.md` (the spec's proposed entry, numbered at the next free number, status as the researcher rules), `CLAUDE.md` status line, `docs/backlog.md` (IDEA-34, IDEA-35 → `accepted`, linked).

- [ ] **Step 1:** Acceptance tests 1–13 on the synthetic pilot-shaped fixture (three links: new, in-corpus via search, also snowballed), each named `test_ac<n>_...`. **Step 2:** Run whole suite. **Step 3:** Docs. **Step 4:** Commit `test(inbox): acceptance; docs and decision`.

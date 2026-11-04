# Lab Library, Project Hosting Import and Acceptance Implementation Plan (slice 5, sub-plan deploy-C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** deploy-B's Later OAuth task is not needed: Tasks 4–5 use personal tokens. v1 cut: Task 5 keeps the automated `slow` acceptance; its manual pilot on a real lab server (Step 3) moved to Later. Bumps `PROJECTION_VERSION` by one from the value it finds.

> **Dependencies.** deploy-A, teams-A and teams-B merged (`project.hosted`, `Principal`, `roles_of`, `visibility`, `authorize`); deploy-B merged for Task 4 (authenticated push endpoint) and Task 5 (acceptance over HTTP); teams-C and teams-D merged for Task 5. Slice 2 plan A (`fulltext.*`, `Route`, restore) merged. Slice M ([slice-M-modules.md](../specs/slice-M-modules.md)) is not required: this plan stores and shares documents only; slice M's shared mining store uses the root `<root>/mining/` and the visibility rule of `services/lab_library.py::may_read_project` defined here.

**Goal:** Store literature once per lab, let a project adopt a document another project acquired with a recorded, traceable event, move stage-0 projects onto the server, and run the slice's acceptance pilot.

**Architecture:** `LabLibrary` is a `BlobStore` at `<root>/library/`; `Project.library` becomes a `ProjectLibrary` view that serves a hash only if the project's own events reference it, reading from the project-local directory first (stage 0) and the lab library second. Adoption is a new route `lab-library` with a `fulltext.adopted` event plus the ordinary `fulltext.attempted` and `fulltext.document_added` events, so PRISMA, status and restore code paths stay as they are. `factory library push` uploads blobs by hash to an authenticated endpoint mounted beside the MCP app.

**Tech Stack:** as deploy-B; `httpx` for push.

**Spec:** `docs/specs/slice-5-teams-deployment.md` rulings 18, 19; acceptance 12, 16; open question 5. Decisions 39, 46, 48.

## Rulings made in this plan

1. **Referenced-only reads.** A project reads a library hash only when one of its events references it (`fulltext.document_added`, `document.converted`, `fulltext.adopted`); otherwise `ProjectLibrary.get` raises `KeyError` as for a missing blob. This keeps project-level access control meaningful in a shared store. [confirm]
2. **Route `lab-library`.** `Route.LAB_LIBRARY = "lab-library"`, not in `ROUTE_ORDER` (never tried automatically); adoption is explicit (`library_adopt`, `factory library adopt`). [confirm] *Alternative:* try it first automatically in `fulltext_fetch`; rejected because it would make a project's acquisition depend silently on other projects.
3. **Adoption scope.** Only for works whose title/abstract outcome is `INCLUDED` (decision 48 item 1) and whose `rf:` id equals the source document's work id; the source document's conversions are adopted with it (same hashes; `document.converted` is not re-run). Re-conversion in the adopting project remains possible and is recorded as usual. [confirm]
4. **Researcher-supplied sources.** Adopting a document whose source route is `researcher-supplied` requires that the adopting project's owner has confirmed the source project once (`library.source_confirmed`, human), per spec open question 5. [confirm]
5. **Migration of an existing project-local library.** `factory library consolidate` moves files from `projects/<slug>/library/` into the lab library by hash (verify, then hard-link or copy, then remove the project copy); no event is written because no fact about the research changes; `check` verifies every referenced hash afterwards. [confirm]

## Global Constraints

- Literature never enters git; `factory commit` (deploy-A) refuses library paths.
- Every adoption is an event in the adopting project; trace crosses into the source project read-only.
- Events are the source of truth; the projection never reads the library.
- `uv run pytest -m "not network and not slow"`, `mypy --strict`, ruff pass; coverage ≥ 90%.

## Review Focus

1. Project Q cannot read P's document by hash before adopting it (Task 1, `test_unreferenced_hash_unreadable`).
2. After adoption, Q's PRISMA counts the work as retrieved and `trace` reaches P's attempt (Task 2, `test_adoption_counts_and_traces`).
3. A non-member adopting from a `private` project is refused, nothing written (Task 3, `test_private_source_refused`).
4. A pushed blob whose bytes do not match its hash is rejected and not stored (Task 4, `test_push_verifies_hash`).

## File Structure

- Create `services/lab_library.py`, `model/lab_library.py`.
- Modify `events/blobs.py` (no change to `BlobStore`; add `ProjectLibrary` wrapper in `services/lab_library.py`), `services/context.py` (`Project.library` type), `model/fulltext.py` (`Route.LAB_LIBRARY`), `events/catalog.py`, `index/fulltext.py`, `services/fulltext.py`, `services/fulltext_status.py`, `services/prisma.py`, `services/trace.py`, `services/check.py`, `services/hosting.py`, `mcp/http.py`, `mcp/server.py`, `cli/main.py`.
- Tests: `tests/test_lab_library.py`, `tests/test_adoption.py`, `tests/test_library_push.py`, `tests/test_project_host_import.py`, `tests/test_acceptance_slice5.py` (`slow`).

---

### Task 1: Lab library and project view

*Tier: critical.*

**Files:** Create `services/lab_library.py`; Modify `services/context.py`; Test `tests/test_lab_library.py`.

**Interfaces:**
- Produces: `LabLibrary(root: Path)` (a `BlobStore` at `<root>/library`); `ProjectLibrary(local: BlobStore, lab: LabLibrary | None, referenced: Callable[[str], bool])` with the `BlobStore` read and write methods used today (`put`, `put_json`, `get`, `get_json`, `exists`, `path`); writes go to the lab library when it exists, else local; `referenced_hashes(project) -> Callable[[str], bool]` backed by an indexed query; `consolidate(project) -> int` (ruling 5).

- [ ] **Step 1: Tests.** `test_stage0_library_unchanged` (no lab: reads and writes local; slice-2 suites pass), `test_writes_go_to_lab_when_present`, `test_unreferenced_hash_unreadable`, `test_consolidate_moves_and_verifies`, `test_library_not_tracked_by_git`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(library): lab library with per-project referenced view`.

### Task 2: Adoption

*Tier: critical.*

**Files:** Create `model/lab_library.py`; Modify `model/fulltext.py`, `events/catalog.py`, `index/fulltext.py`, `services/lab_library.py`, `services/fulltext_status.py`, `services/prisma.py`, `services/trace.py`; Test `tests/test_adoption.py`.

**Interfaces:**
- Produces: `FulltextAdopted(work_id, source_project, source_doc, source_attempt, sha256, licence_status, conversions: tuple[str, ...])`; `adopt(project, actor, work_id, source_project: str, source_doc: str) -> str` (new `doc_` id) writing, under `project.writing()`, `fulltext.fetch_started`, `fulltext.attempted` (route `lab-library`, outcome retrieved), `fulltext.document_added` and `fulltext.adopted`; `adoptable(project, work_id) -> list[AdoptionCandidate]` listing documents for the same `rf:` id in other projects the principal may read; trace node kind `adoption` linking to `(source_project, source_attempt)`.

- [ ] **Step 1: Tests.** `test_adoption_counts_and_traces`, `test_adoption_requires_included`, `test_work_id_must_match`, `test_conversions_adopted_with_document`, `test_status_shows_route_lab_library`, `test_restore_by_adoption_reads_lab` (restore of an adopted doc verifies by hash from the lab library).
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(library): adoption of lab-library documents`.

### Task 3: Access rules for adoption

*Tier: standard.*

**Files:** Modify `services/lab_library.py`, `events/catalog.py`, `mcp/server.py`, `cli/main.py`, `services/check.py`; Test `tests/test_adoption.py`.

**Interfaces:**
- Produces: `may_read_project(source, principal) -> bool` (`lab` visibility or membership); event `library.source_confirmed` `SourceConfirmed(source_project, reason)` (owner of the adopting project; ruling 4); MCP `library_adopt(project, work_id, source_project, source_doc, role, model, skill)` (`work:run`); CLI `factory library adopt|status|consolidate`; check `adoption-source-missing`.

- [ ] **Step 1: Tests.** `test_private_source_refused`, `test_member_may_adopt_from_private`, `test_researcher_supplied_needs_owner_confirmation`, `test_adoption_source_missing_finding`, `test_adopt_refused_to_pass_session`.
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(library): adoption access rules`.

### Task 4: Library push and project hosting import

*Tier: standard.*

**Files:** Modify `mcp/http.py` (route `PUT /library/sha256/{hash}`), `services/lab_library.py`, `services/hosting.py`, `cli/main.py`; Test `tests/test_library_push.py`, `tests/test_project_host_import.py`.

**Interfaces:**
- Produces: endpoint accepting a blob body, authenticated by the same verifier, permission `work:run` on at least one project referencing the hash after import (checked after the events arrive) or `lab:admin`; body hash verified before storing; `push_library(settings, slug, server_url, token) -> PushReport(sent, skipped, failed)` (HEAD first, then PUT); `host_project` extended: `factory project host <slug> --owner U` on the server after the events have been pulled by git, writing `project.hosted` and `member.granted(U, owner)`.

- [ ] **Step 1: Tests.** `test_push_verifies_hash`, `test_push_skips_present`, `test_push_requires_auth`, `test_host_import_grants_owner`, `test_host_import_then_check_clean` (every referenced hash present after push).
- [ ] **Step 2–4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(hosting): library push and project hosting import`.

### Task 5: Slice acceptance

*Tier: standard.*

**Files:** Create `tests/test_acceptance_slice5.py` (`slow`); Modify nothing else unless a test reveals a defect (fix under its own commit, with a test).

**Interfaces:** consumes every plan of slice 5.

- [ ] **Step 1: Test** (`slow`, ASGI client, offline sources): admin initialises the lab and registers `pi`, `ana`, `ben`; issues tokens; hosts a project with owner `pi`, grants `ana` contributor and screener, `ben` contributor and screener, sets a weekly `tasks:screen_b` budget; `ana` (HTTP, agent) files a protocol amendment request, `pi` approves, `pi` amends with the request id; `ben` joins TA pass A in person by CLI; `ana`'s agent joins TA pass B over HTTP; `ben`'s agent joining pass B is refused; both passes finish; `pi` resolves disagreements (elicited); κ per pair type is reported; a second project adopts one included work's document; the ledger lists `pi`, `ana`, `ben` and the agent roles; each confirms; `check` is clean except advisory findings; rebuilding both indexes reproduces their state hashes; the access log has one line per call. Assertions mirror spec acceptance 1–15.
- [ ] **Step 2:** Run `uv run pytest tests/test_acceptance_slice5.py -m slow -q`; fix defects test-first.
- [ ] **Step 3:** Verification `uv run pytest -m "not network" -q && uv run mypy --strict src && uv run ruff check .`; commit `test(slice5): acceptance`.

## Later (not v1)

Moved here by the v1 cut of 2026-11-04 (decision 74); built after the v1 plans of the build order (`2026-11-05-build-order.md`), in the order listed. Task text is unchanged; references to "Task N" inside a moved task use the plan's original numbering.

### Later L1: Pilot on a real lab server (was Task 5 Step 3; manual, `network`): the pilot of spec acceptance 16 with Claude Code and claude.ai; outcomes recorded in the plan's completion notes.

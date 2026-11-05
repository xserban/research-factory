# Full-text Lifecycle Implementation Plan (backlog triage, plan FL)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Proposed 2026-11-05 (backlog triage, `2026-11-05-backlog-triage.md`).** Items marked [confirm] await the researcher.

> **Dependencies.** Base `d66387f` or later. Task 2 depends on Task 1. Paths are relative to `platform/`.

**Goal:** A corpus whose sources changed or disappeared can reach a clean `check`, and `restore` and `refresh` finish on a real library.

**Basis:** IDEA-25, 27, 28, 29, all confirmed not built on the base. `fulltext.source_changed` has no resolving event and `source-changed` stays a warning for good. `factory fulltext restore --missing` builds every result before printing (`cli/main.py:2232`). `_targets` slices `chosen[:limit]` from the same sorted head on every call (`services/fulltext.py:266`). `restore_document` compares hashes only. Decisions 46 items 8 and 9, 48 items 4 and 5; R-01, R-03, R-04.

**Projection:** Task 1 bumps `PROJECTION_VERSION` by one (`fulltext_source_changes` gains a resolution). Tasks 2 to 4 do not.

## Rulings made in this plan

1. **Resolving a changed source (IDEA-25) [confirm].** Options: (a) acceptance supersedes the document with the new bytes; (b) a recorded mark on the existing document, the original staying the reference. **Recommended: (b).** Event `fulltext.source_resolved` (`document_id`, `observed_hash`, `decision: keep-original|accept-new-version`, `rationale`), human only. `keep-original` closes the finding. `accept-new-version` closes it and records a new document for the observed hash under the existing rule that a new version supersedes (decision 46 item 3), so pinned quotes stay valid against their conversion.
2. **Restore skips a document with an unresolved change (IDEA-27 open question) [confirm].** It is listed `source-changed-unresolved`, and no new request is made. An `unavailable` result is requested again, since that is the point of retrying, but the report states the count.
3. **Refresh rotation (IDEA-28) [confirm].** Options: cursor on the tool; rotation by last attempt. **Recommended: rotation.** With `refresh`, works are ordered by last attempt time, oldest first, then id. It needs no state in the caller, is deterministic from the log, and `fulltext.fetch_started` records the chosen ids as today.
4. **Same bytes, other version string (IDEA-29) [confirm].** A separate attempt reason, not a `source-changed` variant, since nothing changed in content: outcome `restored` with `version_differs: <observed>`. The document's recorded version is not rewritten. `check` lists it as `source-version-differs` (warning in every mode).

## Global Constraints

- Original bytes stay referenced; nothing is overwritten silently (decision 46 item 8).
- Each document gets its own outcome in the report.
- `cli/main.py` changes stay within `fulltext_app`.

## Review Focus

1. A forged `fulltext.source_resolved` from an agent changes nothing, on rebuild too.
2. `accept-new-version` leaves earlier extractions pinned to their conversion and marks them by the existing staleness rule only.

## File Structure

Modify `model/fulltext.py`, `events/catalog.py`, `index/fulltext.py`, `index/default.py`, `services/fulltext.py`, `services/check.py` (rule calls), `services/modules/fulltext.py`, `cli/main.py`, `cli/render.py`.

### Task 1: Resolve a changed source

*Tier: critical (provenance). Bumps the projection.*

**Interfaces:** `FulltextSourceResolved` (ruling 1); `resolve_source_change(project, actor, document_id, observed_hash, decision, *, rationale) -> str | None` (the new document id for `accept-new-version`). `factory fulltext resolve DOC HASH keep-original|accept-new-version --rationale R`. `fulltext status` and `check` read only unresolved changes. Declared in `services/modules/fulltext.py`.

- [ ] **Step 1:** Implement, bump. **Step 2:** Commit `feat(fulltext): a human resolves a changed source`.

**Tests (later):** finding clears; both decisions; agent refused; unknown hash refused; forged event; rebuild identical; missing bytes refuse `accept-new-version`.

### Task 2: Restore that finishes

*Tier: standard.*

**Interfaces:** `restore_missing(project, routes, actor) -> Iterator[RestoreOutcome]`, in `services/fulltext.py` (moves the loop out of the CLI). Each document is caught on its own, an unexpected exception giving `failed: <class name>`, with no message text. The CLI prints as it goes and ends with counts. Ruling 2.

- [ ] **Step 1:** Implement. **Step 2:** Commit `fix(fulltext): restore reports each document as it goes`.

**Tests (later):** an exception in one document leaves the rest reported; a second run makes no request for a changed source; unavailable counted.

### Task 3: Refresh reaches the whole corpus

*Tier: standard.*

**Interfaces:** `_targets` with `revisit` orders by last attempt (ruling 3). The refusal of explicit ids beyond `limit` stays.

- [ ] **Step 1:** Implement. **Step 2:** Commit `fix(fulltext): refresh rotates through the corpus`.

**Tests (later):** three calls of limit 2 over five works reach all five; deterministic; `fetch_started` lists the choice.

### Task 4: Version mismatch with identical bytes

*Tier: standard.*

**Interfaces:** Ruling 4. `version_differs: str | None` on the restored attempt payload (default None, so old events replay). Check `source-version-differs`.

- [ ] **Step 1:** Implement. **Step 2:** Commit `fix(fulltext): restore records a version that differs`.

**Tests (later):** same hash, other version recorded and listed; same version writes as before.

## Self-review notes

- A researcher-supplied document stays restored by re-import (decision 46 item 9). An attachment's bytes stay in the library by hash.

## Later (not v1)

None.

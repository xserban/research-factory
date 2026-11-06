# Cross-project and Living Extras Implementation Plan (backlog triage, plan XL)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Proposed 2026-11-05 (backlog triage, `2026-11-05-backlog-triage.md`).** Items marked [confirm] await the researcher.

> **Dependencies.** Base `d66387f` or later. Task 3 reads M-E's shared projection if merged (`plan-modules-e`) and otherwise opens each project read-only. Task 6 after PF Task 1 only by file. Paths are relative to `platform/`. A single-project pilot needs none of this: it comes after the plans a pilot uses.

**Goal:** Let one project learn from another through recorded acts (IDEA-04; region adoption; card import), and finish the Later items of slices 3d, 4a, 4b and 7b that no plan is building.

**Basis:** `region.adopted` and `card.imported` do not exist. Their task text is already written, and this plan schedules it rather than repeats it: `2026-11-05-regions-b-members-links-adoption.md` Later L1 and `2026-11-05-hypotheses-a-cards.md` Later L1. IDEA-04 has no spec; slices 3b, 3d, 4a, 4b and 7a each exclude it. Decisions 9 (embeddings, open), 59, 62, 68; R-34.

**Projection:** Tasks 1 and 2 bump as their source plans say, one each. Task 5 bumps by one if the recommended option holds. Others do not.

## Proposed decisions (numbers fixed at merge)

**PD-9. Cross-project suggestions [confirm].** A suggestion is a computed, read-only hint with a stated reason, never a write into the other project. Signals: same work (by identifier) in both corpora; a reviewed region's promoted term on the work's labels; a citation from an included work. No embeddings (decision 9 stays open). It enters the other project only as an inbox item the researcher adds, through that project's protocol. Options: (a) computed on request; (b) in the digest. **Recommended: (a).**

**PD-10. Priority hints [confirm].** Living-B Later L1 needs a ruling against R-34 (randomised order). Options: (a) drop them; (b) a hint orders only the researcher's inbox listing, never a screening batch; (c) a declared protocol rule that reorders batches. **Recommended: (b).** Screening order stays as R-34 requires, and the hint is recorded (`inbox.prioritised`).

## Global Constraints

- A source project is never written: mtime and event listing unchanged.
- Adoption and imports are human acts on the CLI.
- Cross-project reads respect `private` once teams-A is merged.

## Review Focus

1. No held-out data of one project leaves it through a suggestion: a suggestion reads corpus works and reviewed regions only, through agent-safe reads.
2. Priority never reaches `screen_next`.

## File Structure

As the two source plans, plus Create `services/suggestions.py`, `exports/update_flow_svg.py`. Modify `services/notices.py`, `services/digest.py`, `model/watch.py`, `services/inbox.py`, `services/imports.py`, `services/regions.py`, `cli/main.py`.

### Task 1: Region adoption

*Tier: standard. Bumps the projection.*

Build Regions-B Later L1 as written (`adopt_region`, `adoption_outdated`, `factory regions adopt`), plus the check `region-adoption-outdated` and the `adopted_from` of `regions_of`, which returns None today (iterate lines 52, 70). Commit `feat(regions): adopt a reviewed region from another project`. **Tests (later):** as listed there.

### Task 2: Card import

*Tier: standard (provenance). Bumps the projection.*

Build H-A Later L1 as written (`import_card`, `factory cards import --from SLUG MCD`). Commit `feat(cards): recorded cross-project card import`. **Tests (later):** as listed there.

### Task 3: Suggestions

*Tier: standard. PD-9 [confirm].*

**Interfaces:** `suggestions(settings, target_slug) -> list[Suggestion(work, from_project, reason)]`, capped, deterministic; `factory suggest [--project SLUG]`. Reason text is a fixed template, per signal.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(portfolio): computed cross-project suggestions`.

**Tests (later):** each signal; no write in either project; a private project is skipped; review focus 1.

### Task 4: `notices check --all` and per-region digests

*Tier: standard.*

**Interfaces:** `factory notices check --all` (spec open question 2: an explicit, budgeted command over every corpus work; reports what it could not check). `digest_build(project, region=None)`, `factory digest --region RGN`: the digest restricted to a region's pinned members.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(living): notice check of the whole corpus; digests per region`.

**Tests (later):** budget honoured; region filter; digest golden without it.

### Task 5: Priority hints

*Tier: standard. PD-10 [confirm]. Bumps the projection.*

**Interfaces:** `inbox.prioritised`, `prioritise`, `factory inbox prioritise ITEM`; `inbox list` sorts by it.

- [ ] **Step 1:** Implement, bump. **Step 2:** Commit `feat(inbox): priority hints order the listing only`.

**Tests (later):** review focus 2.

### Task 6: Zotero collections and the update-flow SVG

*Tier: light.*

**Interfaces:** `factory regions define --from-import IMP` drafts a region from one import's development part (slice 3d open question 3; a draft, reviewed like any other). `export prisma --update` renders the update flow as SVG (slice 7b Later), from `compute_update`.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(regions,exports): draft a region from an import; update-flow SVG`.

**Tests (later):** an `all`-part rule stays refused to agents (decision 88); SVG golden.

## Self-review notes

- IDEA-36 is M-E, not here. Region-scoped vocabularies, region-based transfer and additional decision rules (slice 6 Later) wait for a project that needs them, and the table lists them so.

## Later (not v1)

- Region-scoped vocabularies; region-based transfer; additional decision rules; a suggestions line in the digest.

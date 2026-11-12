# Plan: unify the code lines into one (integration branch `unify`)

Date: 2026-11-12 · Status: analysis done (read-only test merges); nothing merged · Origin: pilot `agentic-science`

## Situation (measured 2026-11-12)
- `main` is at the 5 November handoff commit (8e68849). Every line is 359 to 438 commits ahead of it and none is behind.
- Two chains split at the site-hub commit `a67690b` (11 Nov 09:03):

| Chain | Branches | Commits since the split |
|---|---|---|
| A | `plan-8-suggest-select` is inside `plan-reference-layers` | 42 |
| B | `plan-feed` is inside `plan-feed-hub`; `plan-restart-costs` and the index deadlock fix (6935a07) are already inside `plan-feed-hub` | 100 |

- A plain merge of A and B conflicts in 13 files. **The cause**: chain B holds a copy of the first reference-layers commits (cherry-picked on 11 Nov 09:15 to 10:15, with other hashes). The copy equals reference-layers commit `93ad7ee` (11 Nov 10:39) exactly for `reference_layers.py` and `reference_items.py`. Chain A then went on (12 Nov, rules v4, aliases, inner sample, seed version). So most of the 13 conflicts are add/add conflicts against an older snapshot, not real disagreements.
- **Use `93ad7ee` as the merge base for the shared files.** With it, `cli/main.py` and `cli/render.py` merge with no conflict (0 hunks), and only four real conflicts remain.

## Resolution table (A = `plan-reference-layers`, B = `plan-feed-hub`)

| File | A since import | B since import | Resolution |
|---|---|---|---|
| `services/reference_layers.py` | 191 lines | 0 | take A |
| `services/reference_items.py` | 286 lines | 0 | take A |
| `model/references.py` | 32 lines | 0 | take A |
| `index/references.py` | 6 lines | 0 | take A |
| `services/dedup_cascade.py` | 0 | 96 lines | take B |
| `services/trace.py` | 0 | 41 lines | take B |
| `docs/decisions.md` | 0 | 3 lines | take B |
| `cli/main.py` | 20 lines | 46 lines | 3-way merge on base `93ad7ee`: no conflict |
| `cli/render.py` | 23 lines | 35 lines | 3-way merge on base `93ad7ee`: no conflict |
| `index/default.py` | 2 lines | 8 lines | one conflict, `PROJECTION_VERSION` (A "79", B "82"): set it to **83**, higher than both, because each line changed what the index stores. Keep the registrations of both |
| `plugin/skills/rf-reference-layers/SKILL.md` | (file added on A) | (own copy) | take A and add the front-matter line `stage: [gather]` that B added |
| `docs/plans/2026-11-11-reference-layers.md` | 136 lines | 61 lines | 3-way merge on base `93ad7ee`, one conflict hunk: keep A's text and B's additions |
| `docs/backlog.md` | 9 lines | 141 lines | 3-way merge on base `93ad7ee`, one conflict hunk: keep both; numbering: restart is IDEA-59, IDEA-44 is progress |

After the merge, the code of chain B that calls the reference-item API must still compile against A's newer version (`aliases`, merged items, rules v4). `mypy --strict` finds any mismatch.

## Order
1. Freeze: the reference-layers agent and the feed-line agent stop at a clean commit and tell the integrator the commit ids. Anything committed afterwards must be merged again.
2. Cut `unify` from `plan-reference-layers` (it contains `plan-8-suggest-select`).
3. Merge `plan-feed-hub` into `unify` and resolve with the table above.
4. Merge the researcher's saved branches (they merge cleanly with A, tested): `hub-backlog-board` (the backlog board), `notes-2026-11-12` (notes, plans, backlog ideas 57 to 61 and status corrections, migration script). Cherry-pick the one commit of the miner reading prototype from `scratch-combined` (`e0ad4c8`, `document_read` with `selected`).
5. Regenerate `docs/MAP.md` (`uv run --project platform python scripts/gen_map.py`), run `ruff` and `mypy --strict` for the whole platform, then the tests of every touched file, one file at a time (never the full suite locally; testing is unpaused only for this step).
6. Decide (the researcher) to fast-forward `main` to `unify`.
7. Repoint: `.mcp.json`, `screeners/factory-mcp.json`, `screeners/factory-mcp-scratch.json`, and the `W=` lines in the screener scripts that name `scratch-combined`. Every session reconnects. Then remove the `scratch-combined` worktree and branch.

## Checks that guard the merge
- The pilot log is readable with the unified code: `factory miner list` on the pilot root (it holds `reference.layer_assigned`, `document.rendered`, the feed events and the run events). Run it on a copy of the root first.
- `PROJECTION_VERSION` is 83 or higher, and nothing else on the line sets a lower value.
- No event type was added or removed by the merge itself (compare the catalogs).
- The IDEA-44 and IDEA-59 numbering is reconciled in the backlog.

## Brief for the integrator agent
Task: build the `unify` branch as in "Order" above. Work in a new worktree and branch from `plan-reference-layers`; do not edit any other branch or worktree, and do not push or merge into `main` (the researcher decides that). Commit on `unify`. Use the resolution table; for any file not in the table that conflicts, stop and report it. Do not weaken or delete a test to make it pass: classify each failure as caused by the merge, present on its own line before the merge (run the same test there), or environment. Report: the merge commits, each conflict and how it was resolved, the `PROJECTION_VERSION` value, ruff and mypy output, the tests run and their results, and anything not verified. Do not write that tests pass unless they were run.

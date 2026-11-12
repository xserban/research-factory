# Note: the scratch-combined worktree and how to merge everything back

Date: 2026-11-12 · Status: scratch, throwaway · Origin: pilot `agentic-science`

## Why it exists
The pilot event log is shared by every code line. The `plan-reference-layers` work wrote events of type
`reference.layer_assigned` (228 events by the `layerer` session, 2026-11-12 08:35 to 08:38), which the
`plan-8-suggest-select` code does not know, so the CLI and the hub there stopped with
`EventLogCorruptError` (earlier, the main checkout failed the same way on `document.rendered`).

## What it is
- Worktree `.claude/worktrees/scratch-combined`, branch `scratch-combined`.
- Built from `plan-8-suggest-select` (aec35cf) with `plan-reference-layers` merged in (no conflicts), commit 1d1d29d.
- Used only to read and write the pilot log from one code line that knows both event types:
  `hub.sh` takes `WT=<worktree> ./hub.sh`; the CLI env is the usual one with `PYTHONPATH=<worktree>/platform/src`
  and `FACTORY_PLUGIN_DIR=<worktree>/plugin`.
- Nothing from it is merged anywhere. Do not commit feature work on it.

## Lines that each know events the others do not
| Line | Knows |
|---|---|
| main | the event types merged so far |
| `plan-8-suggest-select` | `document.rendered`, the site hub, version pairs (IDEA-56 A, B1 to B5) |
| `plan-reference-layers` | `reference.layer_assigned` and the reference layers |
| `plan-feed`, `plan-feed-hub` | the feed events; the hub's feed and work queue; the light theme |
| `plan-restart-costs` | on top of `plan-feed-hub`: resume, run costs, the usage-limit rule, the index deadlock fix (6935a07) |

## Merge-back order (proposal, for the researcher to decide)
1. `plan-8-suggest-select` into main first (it is the base of the pilot's hub).
2. `plan-reference-layers` next: its events are already in the pilot log.
3. `plan-feed` then `plan-feed-hub`, then `plan-restart-costs` (it is stacked on the feed hub).
4. After each merge: regenerate `docs/MAP.md`, run `mypy --strict` and `ruff`, and run the tests of the files the
   branch touched (testing is unpaused only per branch by the researcher).
5. Reconcile `docs/backlog.md` by hand: IDEA-44 is the restart idea in main and "Progress for long operations" on
   `plan-restart-costs` (restart is IDEA-59 there); my uncommitted main-checkout entries (IDEA-57, 58, 60, 61, the
   status corrections) must survive.
6. When the combined line is in main: point `hub.sh`, `FACTORY_ROOT` consumers and `factory-mcp.json` at main (or at
   the one-roof layout, `docs/plans/2026-11-11-one-roof.md`), then delete the scratch worktree and branch
   (`git worktree remove .claude/worktrees/scratch-combined; git branch -D scratch-combined`).

## Rule for the future
A branch that adds an event type and runs it against the shared pilot log blocks every other line that lacks it.
Either merge such a branch before running it on the pilot, or run it on a copy of the pilot root.

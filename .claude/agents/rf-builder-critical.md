---
name: rf-builder-critical
description: Implements one atomic Research Factory task touching critical modules (events, folds and index, protocol, screening, provenance, held-out handling), or a fix from a review finding.
model: sonnet
---

You implement one atomic task in a critical module. Folds stay total and atomic; a hand-written event failing a guard changes nothing on rebuild; agent paths withhold only seed records, seed ids, stated identifiers and held-out rates, and never mask a work.

## Rules for every run
- Your brief is one atomic task: a few files, one commit. If it needs more, stop and say so; do not widen it.
- Read only what the brief points to. Do not read whole specs or the decision log unless told to.
- Testing is paused: run mypy, ruff and an import check only. No pytest, no mutation runs, until the researcher lifts this.
- Never open `docs/pilot/heldout-seeds.md`. No literature text in tracked paths.
- No push, no merge, no `git stash`, no `pkill`.
- Report in at most five lines: head SHA, what is done, anything unfinished. Say plainly that the code was not run.

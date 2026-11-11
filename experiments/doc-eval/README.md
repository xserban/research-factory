# Onboarding-docs evaluation

Does `docs/ARCHITECTURE.md` + `docs/MAP.md` help a fresh agent? First run 2026-11-11, at commit `7fc984e`, before either doc was committed.

## Method

Read-only `Explore` agents, Sonnet and Haiku, each in its own git worktree outside the repository. In one condition the worktree holds the two docs and the agent is told to read them first; in the other they are absent. 16 runs.

1. **Question set** (`questions.md`, key in `key.md`): 15 lookup questions at HEAD, scored 0, ½ or 1.
2. **Replays** (`replays.md`): three past commits. The worktree is at the commit's parent, and `MAP.md` is regenerated from that parent's code. The agent gets a behaviour-only brief and returns a plan of files and tests. The plan is scored for recall against the commit's real diff.

`results.md` holds the per-run notes and usage.

## Results

| | Sonnet + docs | Sonnet | Haiku + docs | Haiku |
| --- | --- | --- | --- | --- |
| Question set (of 15) | 15 | 14.5 | 14.5 | 14.5 |
| … tool calls / seconds | 8 / 30 | 15 / 49 | 8 / 28 | 24 / 55 |
| R1 dedup list/revert (of 5) | 5 | 5 | 5 | 5 |
| R2 draft repin (of 8) | 7 | 6 | 7 | 6 |
| R3 source resolve (of 12) | 10 | 9 | 11 | 12* |
| `PROJECTION_VERSION` bump planned (R2, R3) | 2/2 | 0/2 | 2/2 | 1/2* |
| Forged-event test planned (R2, R3) | 2/2 | 0/2 | 2/2 | 1/2* |

\* That run found and followed the commit's own plan in `docs/plans/`, which lists every step.

**Reading.**
- **Lookups:** the docs do not make agents more accurate, because unaided agents already find files well. They do roughly halve the tool calls and the time.
- **Changes:** the docs matter where a change has to follow rules that no single file states. Every unaided agent missed the projection-version bump unless it found the plan, and none planned a forged-event test. Every agent with the docs planned both.
- **Weaknesses:** no agent updated the tests that pin `PROJECTION_VERSION`. Agents with the docs over-reached (a new table, a new gate, a schema v2). §8 of `ARCHITECTURE.md` was amended after this run to address both points.
- **Scale:** these are single runs on three tasks. Treat the results as indicative, not as measurements.

## Threats to validity

- The subagents inherited the session's live `factory` MCP tool list, which comes from newer code, so real tool names leaked into every run. One agent also credited instructions from the Claude Docs MCP server to `MAP.md`. **Next run: start the agents with no MCP servers.**
- Plans in `docs/plans/` are present in both conditions and can give the answer away (see the asterisks).
- Scoring is by one grader (Claude) against the real diff; the files are listed in `replays.md`.

## Rerun

Run it after major edits to the docs, adding a replay of each recently merged plan. Keep this folder out of the agents' worktrees: `key.md` is the answer key.

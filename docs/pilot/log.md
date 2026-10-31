# Pilot log — linear-attention-vision

A hand-written stand-in for the event stream. One row per action; never edit a past row — add a correcting row. Gaps noticed here feed back into `docs/specs/slice-1.md`.

Columns: date · actor (human / agent + model / system) · event type (`<area>.<past-tense verb>`) · what · refs · notes.

| # | Date | Actor | Event | What | Refs | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-31 | human (obd) | question.drafted | Raw goal: "best linear attention mechanism for vision models" | — | Decomposition pending |
| 2 | 2026-10-31 | agent (claude-opus-5-5) | seed.proposed | 15 positives, 5 negatives, 9 boundary cases; IDs checked on arXiv except NEG01, B2 | seeds.md | Seeds proposed by the agent, not the researcher — to be confirmed |
| 3 | 2026-10-31 | agent (claude-opus-5-5) | seed.split_drawn | Development/held-out split, seed 20261031, stratified by period | seeds.md, heldout-seeds.md | Drawing session had seen all candidates (limitation) |

## Next entries expected
1. `seed.confirmed` — researcher confirms or edits the seed list.
2. `question.recorded` — rulings Q0–Q4, elements and ≥ 3 non-goals.
3. `probe.run` — per candidate query and source: string, date, reported count, development-seed recall, negatives hit, new vocabulary. Fresh session; note its ID.
4. `protocol.recorded` — criteria with parents, limits, screening plan, κ floor.

# Benchmark protocol: tiers and autonomy levels (lane L5)

Status: protocol, to be run once the conductor (L4) and the tier plans (L2) are merged. Metrics come from `factory bench level <project> --format json|table` (read-only; `services/level_bench.py`). Nothing here is a result.

## 1. Question

Which tier, and which autonomy level, gives the most useful evidence per unit of cost and time on one question whose answer is known? One fixed question, one fixed ground truth, several studies that differ only in tier and autonomy level.

Ground truth: the pilot's question and its known-positive seeds (development seeds and, in the platform's own split, the held-out seeds). The question and the seed list are those of the pilot project; the benchmark copies neither into this document.

## 2. Design

Cells: tier (`brief`, `deep`, `pilot`, `systematic`) crossed with autonomy level (`attended`, `supervised`, `autonomous`). The `attended` column is the reference. Not every cell is meaningful: run first the diagonal `brief`/`autonomous`, `deep`/`supervised`, `pilot`/`attended`, `systematic`/`attended`, then add cells one factor at a time (a second tier at fixed level, then a second level at fixed tier), so that a difference has one cause.

Fixed across cells: the question text, the databases and their date cut, the model and its version per stage, the prompts and skill versions (recorded in the events), the seed list, the machine class. Varied: tier and autonomy level only.

Each study is a new project created by `factory init --tier T --autonomy-level A`; a study never reuses the corpus of another (a run starts from an empty project, with the pilot's imports not copied).

## 3. Starting a run

1. Create the project with the cell's tier and autonomy level; record the commit hash of the code and the model ids in the run sheet.
2. Enter the question and add the seeds through the platform's seed tools, as in the pilot. For tiers with a hold-out split, the platform draws it; the benchmark never chooses it.
3. `brief`, `deep` and every `autonomous` cell: start the conductor and let it run to its own stop (finished, budget spent or a gate in state `pause`). `pilot` and `systematic` with `attended`: a person performs the human gates, with the clock noted at the start and end of each sitting; the metrics report the log span, and the sitting times are added by hand to the table as "human minutes".
4. At the stop, run `factory bench level <project> --format json` and keep the file with the run sheet. Do not edit the project afterwards.

## 4. Leakage of held-out seeds

- No agent, prompt, run sheet or document of the benchmark names, lists or describes a held-out seed. The benchmark never opens the held-out list.
- Held-out recall is read only from the platform's aggregate (`recall_held_out` in the metrics, from `agent_methods`); it is `null` with `held_out_withheld: true` until a screening pass has been opened, and the table prints "withheld" then. Read it once, at the end, not between steps.
- Development recall is optimistic (those seeds informed the protocol and the screening instructions) and is reported with that label, beside, never instead of, held-out recall.
- Cells that share a held-out split give a comparable held-out figure; if a cell draws a different split, say so in the table and do not compare its held-out recall with the others.
- A repetition never reuses what a previous repetition's agents saw: each starts a new project with no copy of another run's blobs or notes.
- The benchmark is itself a run on seeds that later studies will use: the seeds are therefore consumed for this question; a later real study on the same question starts with a fresh split.

## 5. Measures

Per run, from `factory bench level`:

| Measure | Field | Note |
|---|---|---|
| Held-out seed recall | `recall_held_out` | primary effectiveness; aggregate only |
| Development seed recall | `recall_development` | optimistic, labelled |
| Included works | `included` | from the PRISMA flow |
| Elapsed span | `elapsed_seconds` | log span, plus human minutes noted by hand |
| Runner runs | `runner_runs`, `runner_runs_complete` | process count |
| Cost and tokens | `reported_cost_usd`, `*_tokens` | only where `log.jsonl` holds them; `cost_source` says which; the cost is the API-equivalent price, not a bill; a run without a log counts as missing, not zero |
| Screening kappa | `screening_kappa` | where two passes exist |
| Extraction agreement | `extraction_agreement` | where two passes exist |
| Gates closed per autonomy | `gates_closed`, `gates` | human, audited-agent, agent |
| Overturn rate | `overturn_rate`, `audited_acts`, `overturned_acts` | gate audit's human labels over labelled acts; `null` when none labelled |

Not read by the benchmark: label-derived rates the agent view withholds (calibration sensitivity, the screening audit's false-exclusion rate).

Added by hand and by a human reader after the run, blind to the cell: a usefulness grade (0 to 3) of the evidence note against the question, with the note's cited claims spot-checked (ten claims per run, share traceable to a source span). These two are judgements, not computed; they are recorded as such.

## 6. Repetitions and variance

- Three repetitions per cell at least (new project each time, same inputs). Agents are not deterministic, so a single run is an anecdote.
- Report, per cell and measure, the median and the range over repetitions, not only the mean; with three runs, the range is the variance statement.
- A difference between two cells is called a difference only when their ranges do not overlap on the primary measures; otherwise "not distinguished at this sample size".
- Order of runs is randomised across cells (one shuffle, recorded), so that source drift and time of day do not align with a cell.
- Failed or stopped runs (lost run, budget spent, `pause`) stay in the table with their stop reason; they are not repeated away, because a tier that often fails is worse for it.

## 7. What "better" means

Recall at cost, not recall alone. A cell A is better than B when, on held-out recall and at equal or lower cost and elapsed time, its range lies above B's; or when its recall is not distinguished from B's and it costs clearly less (range below). Report the frontier: for each cell, held-out recall against cost (USD where available, else runs and tokens) and against elapsed span including human minutes. Cells off the frontier are dominated.

For autonomy levels, additionally: a lower-human-effort cell is acceptable only if its recall is not distinguished from the `attended` reference of the same tier and its overturn rate stays under the ledger's `watch` threshold (5% with at least 20 audited acts, proposed default D5); otherwise the saving is not credited. An `autonomous` output stays labelled "not human-confirmed" in every case; the benchmark does not change that.

## 8. Report table

One row per cell and repetition, then one summary row per cell (median and range).

| Cell (tier/level) | Rep | Stop reason | Held-out recall | Dev. recall | Included | Elapsed (log) | Human min | Runs | Cost USD | Tokens in/out | Kappa | Extr. agr. | Gates h/a/ag | Overturn | Usefulness | Traceable claims |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

A missing figure is written "-" with the reason ("withheld", "no log", "no second pass"), never 0. The table is followed by the frontier plot data (recall, cost, time per cell), the list of deviations from this protocol and the commit hash of the code.

## 9. Limits

One question and one seed set: results do not transfer to other fields without a second question. Seeds that are known positives measure recall, not precision; included works beyond the seeds are not judged here except through the usefulness grade. Cost figures depend on what the run logs hold. Elapsed time between events includes waiting for people. Small samples (three repetitions) give ranges, not tests.

# Pilot run-cost baseline (2026-11-11)

## Method

- Read: the 768 `*.live` transcripts in the pilot screeners folder, one per headless `claude -p` run. `live.py` writes one line per tool call (`> <tool>`), one line per screened item, and a `== finished` line with the CLI's `total_cost_usd` and turn count. The `.log` files (the agent's final message) and the database were not used for any number.
- Cost figure: the price the CLI reports for each run (`total_cost_usd`), an API-equivalent price at list rates. It is not a subscription charge and not a bill. Runs without a `finished` line (killed or still running at the time of reading) have no cost and are counted separately.
- Family: the file-name prefix before the timestamp. Kind, miner and model come from the shell drivers (`*.sh`) and their prompt files; a family not in that mapping is classified from the tool calls it made, and its model is shown as not recorded.
- Units: screening and full-text runs count the verdict items they submitted (`screen_record` input). Mining runs count the rows the platform accepted (`ext_` ids in `mine_record` results). Works closed without a row are not counted, so mining cost per unit is an upper bound. Rejected `*_record` results are reported separately.
- Zero-unit runs: runs that served no unit (no `screen_record` item, or no accepted row). Mean turns and mean cost are over finished runs only.

## Totals

- Run files: 768; finished with a cost: 763; unfinished: 5
- Total reported cost: $235.84
- Mean cost per finished run: $0.31; mean turns: 37.5

## By kind

| Kind | Runs | Cost | Share of cost | Units | Cost per unit |
|---|---:|---:|---:|---:|---:|
| mining | 663 | $216.32 | 91.7% | 4662 | $0.0464 |
| full-text | 59 | $11.93 | 5.1% | 470 | $0.0254 |
| screening | 45 | $7.33 | 3.1% | 1811 | $0.0040 |
| other | 1 | $0.26 | 0.1% | 0 | n/a |

## By family

| Family | Kind | Model | Runs | Finished | Cost | Cost per run | Mean turns | Units | Cost per unit | Zero-unit runs | Rejected results |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `mine` | mining:m-descriptors | claude-sonnet-5-5 | 80 | 80 | $43.92 | $0.55 | 30.1 | 428 | $0.1026 | 8 | 142 |
| `mapA2` | mining:m-mapping | claude-haiku-5-5 | 64 | 64 | $31.47 | $0.49 | 62.8 | 356 | $0.0884 | 4 | 88 |
| `mineD` | mining:m-design-approach | claude-haiku-5-5 | 76 | 76 | $25.99 | $0.34 | 51.6 | 995 | $0.0261 | 8 | 235 |
| `sumA` | mining:m-summary | claude-haiku-5-5 | 64 | 64 | $25.57 | $0.40 | 51.6 | 361 | $0.0708 | 4 | 116 |
| `sumA2` | mining:m-summary | claude-haiku-5-5 | 64 | 60 | $24.40 | $0.41 | 56.4 | 328 | $0.0744 | 4 | 113 |
| `mineM` | mining:m-mapping | claude-haiku-5-5 | 68 | 68 | $20.32 | $0.30 | 53.2 | 362 | $0.0561 | 5 | 80 |
| `ft-main` | full-text | claude-sonnet-5-5 | 42 | 42 | $10.02 | $0.24 | 14.6 | 364 | $0.0275 | 5 | 0 |
| `clsA` | mining:m-classification | claude-haiku-5-5 | 60 | 60 | $8.51 | $0.14 | 34.2 | 365 | $0.0233 | 4 | 49 |
| `stgA` | mining:m-stages | claude-haiku-5-5 | 64 | 64 | $7.96 | $0.12 | 37.3 | 1145 | $0.0070 | 5 | 24 |
| `sumB` | mining:m-summary | claude-sonnet-5-5 | 12 | 12 | $6.69 | $0.56 | 25.1 | 40 | $0.1672 | 4 | 11 |
| `mapB` | mining:m-mapping | claude-sonnet-5-5 | 12 | 12 | $6.63 | $0.55 | 31.4 | 42 | $0.1579 | 4 | 12 |
| `dB` | mining:m-design-approach | claude-sonnet-5-5 | 8 | 8 | $3.59 | $0.45 | 28.2 | 33 | $0.1088 | 4 | 16 |
| `stgB` | mining:m-stages | claude-sonnet-5-5 | 12 | 12 | $3.24 | $0.27 | 20.4 | 94 | $0.0345 | 4 | 8 |
| `clsB` | mining:m-classification | claude-sonnet-5-5 | 12 | 12 | $3.15 | $0.26 | 13.8 | 35 | $0.0900 | 4 | 7 |
| `main` | screening | claude-haiku-5-5 | 32 | 32 | $2.95 | $0.09 | 11.2 | 1237 | $0.0024 | 13 | 18 |
| `trial-Map-1` | mining:unknown | not recorded | 1 | 1 | $1.23 | $1.23 | 136.0 | 6 | $0.2050 | 0 | 1 |
| `passB-2` | screening | not recorded | 1 | 1 | $1.09 | $1.09 | 26.0 | 120 | $0.0091 | 0 | 0 |
| `passB-m1` | screening | not recorded | 1 | 1 | $0.88 | $0.88 | 22.0 | 100 | $0.0088 | 0 | 0 |
| `passB-m2` | screening | not recorded | 1 | 1 | $0.88 | $0.88 | 22.0 | 100 | $0.0088 | 0 | 0 |
| `mineBH` | mining:m-descriptors | claude-haiku-5-5 | 12 | 12 | $0.87 | $0.07 | 15.8 | 28 | $0.0311 | 5 | 5 |
| `passB-m3` | screening | not recorded | 1 | 1 | $0.83 | $0.83 | 22.0 | 100 | $0.0083 | 0 | 0 |
| `ftB-main` | full-text | claude-haiku-5-5 | 12 | 12 | $0.79 | $0.07 | 8.2 | 60 | $0.0132 | 6 | 0 |
| `m-pilot-1` | mining:unknown | not recorded | 1 | 1 | $0.42 | $0.42 | 17.0 | 3 | $0.1400 | 0 | 3 |
| `sumA-pilot` | mining:unknown | not recorded | 1 | 1 | $0.38 | $0.38 | 34.0 | 6 | $0.0633 | 0 | 1 |
| `ft-cal-1` | full-text | not recorded | 1 | 1 | $0.36 | $0.36 | 21.0 | 11 | $0.0327 | 0 | 0 |
| `trial-Map-2` | mining:unknown | not recorded | 1 | 1 | $0.36 | $0.36 | 32.0 | 6 | $0.0600 | 0 | 3 |
| `passB-1` | screening | not recorded | 1 | 1 | $0.33 | $0.33 | 9.0 | 30 | $0.0110 | 0 | 0 |
| `trial-Sum-1` | mining:unknown | not recorded | 1 | 1 | $0.33 | $0.33 | 119.0 | 6 | $0.0550 | 0 | 1 |
| `trial-Sum-2` | mining:unknown | not recorded | 1 | 1 | $0.30 | $0.30 | 108.0 | 6 | $0.0500 | 0 | 1 |
| `passB-last` | screening | not recorded | 1 | 1 | $0.29 | $0.29 | 9.0 | 30 | $0.0097 | 0 | 0 |
| `ft-cal-2` | full-text | not recorded | 1 | 1 | $0.26 | $0.26 | 15.0 | 10 | $0.0260 | 0 | 0 |
| `ft-cal-3` | full-text | not recorded | 1 | 1 | $0.26 | $0.26 | 23.0 | 10 | $0.0260 | 0 | 0 |
| `x-pilot-1` | other | not recorded | 1 | 1 | $0.26 | $0.26 | 9.0 | 0 | n/a | 1 | 4 |
| `close-m-mapping-B` | mining:m-mapping | claude-sonnet-5-5 | 5 | 5 | $0.25 | $0.05 | 2.8 | 1 | $0.2500 | 4 | 1 |
| `ftB-cal-1` | full-text | not recorded | 1 | 1 | $0.13 | $0.13 | 14.0 | 11 | $0.0118 | 0 | 0 |
| `map-pilot-1` | mining:unknown | not recorded | 1 | 1 | $0.12 | $0.12 | 22.0 | 3 | $0.0400 | 0 | 0 |
| `ft-main-last` | full-text | not recorded | 1 | 1 | $0.11 | $0.11 | 9.0 | 4 | $0.0275 | 0 | 0 |
| `close-m-stages-B` | mining:m-stages | claude-sonnet-5-5 | 3 | 3 | $0.09 | $0.03 | 3.0 | 0 | n/a | 3 | 0 |
| `d-pilot-1` | mining:unknown | not recorded | 1 | 1 | $0.09 | $0.09 | 15.0 | 8 | $0.0112 | 0 | 1 |
| `close-m-design-approach-B` | mining:m-design-approach | claude-sonnet-5-5 | 2 | 2 | $0.08 | $0.04 | 3.0 | 0 | n/a | 2 | 0 |
| `close-m-classification-B` | mining:m-classification | claude-sonnet-5-5 | 2 | 2 | $0.07 | $0.03 | 3.0 | 0 | n/a | 2 | 0 |
| `close-m-summary-B` | mining:m-summary | claude-sonnet-5-5 | 4 | 3 | $0.06 | $0.02 | 1.7 | 1 | $0.0600 | 3 | 1 |
| `closeA2` | mining:unknown | not recorded | 1 | 1 | $0.06 | $0.06 | 3.0 | 0 | n/a | 1 | 0 |
| `close-m-summary-A` | mining:m-summary | claude-haiku-5-5 | 4 | 4 | $0.05 | $0.01 | 10.0 | 1 | $0.0500 | 3 | 0 |
| `closeA3` | mining:unknown | not recorded | 1 | 1 | $0.04 | $0.04 | 5.0 | 0 | n/a | 1 | 0 |
| `cls-pilot-1` | mining:unknown | not recorded | 1 | 1 | $0.03 | $0.03 | 13.0 | 3 | $0.0100 | 0 | 0 |
| `passA-recal` | screening | not recorded | 1 | 1 | $0.03 | $0.03 | 11.0 | 31 | $0.0010 | 0 | 0 |
| `close-m-mapping-A` | mining:m-mapping | claude-haiku-5-5 | 5 | 5 | $0.02 | $0.00 | 3.0 | 0 | n/a | 5 | 0 |
| `close-m-design-approach-A` | mining:m-design-approach | claude-haiku-5-5 | 2 | 2 | $0.01 | $0.01 | 4.0 | 0 | n/a | 2 | 0 |
| `closeB2` | mining:unknown | not recorded | 1 | 1 | $0.01 | $0.01 | 8.0 | 0 | n/a | 1 | 1 |
| `closeB3` | mining:unknown | not recorded | 1 | 1 | $0.01 | $0.01 | 12.0 | 0 | n/a | 1 | 0 |
| `last-1` | screening | not recorded | 1 | 1 | $0.01 | $0.01 | 9.0 | 15 | $0.0007 | 0 | 5 |
| `test-s1` | screening | not recorded | 1 | 1 | $0.01 | $0.01 | 9.0 | 15 | $0.0007 | 0 | 5 |
| `test-s2` | screening | not recorded | 1 | 1 | $0.01 | $0.01 | 4.0 | 10 | $0.0010 | 0 | 0 |
| `test-s3` | screening | not recorded | 1 | 1 | $0.01 | $0.01 | 4.0 | 11 | $0.0009 | 0 | 0 |
| `test-s4` | screening | not recorded | 1 | 1 | $0.01 | $0.01 | 4.0 | 12 | $0.0008 | 0 | 0 |
| `close-m-classification-A` | mining:m-classification | claude-haiku-5-5 | 2 | 2 | $0.00 | $0.00 | 4.0 | 0 | n/a | 2 | 0 |
| `close-m-stages-A` | mining:m-stages | claude-haiku-5-5 | 3 | 3 | $0.00 | $0.00 | 3.7 | 0 | n/a | 3 | 0 |
| `closeA` | mining:unknown | not recorded | 1 | 1 | $0.00 | $0.00 | 2.0 | 0 | n/a | 1 | 0 |
| `closeB` | mining:unknown | not recorded | 1 | 1 | $0.00 | $0.00 | 3.0 | 0 | n/a | 1 | 0 |
| `last-2` | screening | not recorded | 1 | 1 | $0.00 | $0.00 | 3.0 | 0 | n/a | 1 | 0 |
| `mapB2` | mining:m-mapping | claude-sonnet-5-5 | 4 | 4 | $0.00 | $0.00 | 1.0 | 0 | n/a | 4 | 0 |
| `sumB2` | mining:m-summary | claude-sonnet-5-5 | 4 | 4 | $0.00 | $0.00 | 1.0 | 0 | n/a | 4 | 0 |

## Top five families by cost

1. `mine` (mining, claude-sonnet-5-5): $43.92 over 80 finished runs; 428 units, $0.1026 per unit
2. `mapA2` (mining, claude-haiku-5-5): $31.47 over 64 finished runs; 356 units, $0.0884 per unit
3. `mineD` (mining, claude-haiku-5-5): $25.99 over 76 finished runs; 995 units, $0.0261 per unit
4. `sumA` (mining, claude-haiku-5-5): $25.57 over 64 finished runs; 361 units, $0.0708 per unit
5. `sumA2` (mining, claude-haiku-5-5): $24.40 over 60 finished runs; 328 units, $0.0744 per unit

## Observations (facts from the numbers above)

- The most expensive family is `mine` at $43.92, 18.6% of the total.
- full-text: $11.93 for 470 units, $0.0254 per unit.
- mining: $216.32 for 4662 units, $0.0464 per unit.
- screening: $7.33 for 1811 units, $0.0040 per unit.
- Among families with at least 10 units, cost per unit runs from $0.0007 (`last-1`) to $0.1672 (`sumB`).
- 136 of 768 run files served no unit.
- 152 run files record at least one `(no batch served)` result.
- 5 run files have no finished line and contribute no cost.
- Finished subtypes: success 763.

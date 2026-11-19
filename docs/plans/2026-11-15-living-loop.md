# Living loop: from the frozen rapid review to a weekly, traceable update cycle

Status: draft for the researcher's validation · 2026-11-15 · Project: agentic-science
Builds on: slice 4a (inbox), 4b (living corpus: watch cycles, snapshots, update flows, digest),
4c (feed), slice 6 (ideas, hypotheses), IDEA-81 (capture hints), IDEA-78 (graph of ideas).

## Goal

Keep the agentic-science corpus current without re-running the review, and make every change
traceable: what entered, when, by which route, with which verdicts, and what it changed.
The rapid review (v1) stays frozen and reproducible; everything after it is an update.

## Researcher rulings so far (2026-11-15)

1. Links the researcher supplies are planned lookups (`supplied_links.accept_from: [human]`,
   amendment to `P@56a59c99`); agent-proposed links still need a deviation.
2. One project in living mode; no second project.
3. Freeze v1 first. Before the snapshot, close the open records (1 title/abstract, 2 full text,
   3 full-text cannot-assess); 8 unconverted PDFs and 13 version pairs are declared, not closed.
4. Zubeldia 2026 (arXiv 2611.17052, supplied today, included at title/abstract) counts in v1 as
   one supplied record at title/abstract only (the snapshot cut-off cannot be earlier than now);
   its full-text step belongs to the first update.
5. No full re-run of the search: a weekly window and a daily feed.

## Steps

| # | Step | Kind | State |
|---|---|---|---|
| 1 | Close v1: fix `document_read` for merged works (merged, main 3cc0f80), screen the 2 full-text records (both included), researcher rules the 3 cannot-assess (Mungall exclude EX01; ASTRA exclude EX06 under deviation dev_01M7FDFJ0JMX7PPE1BZ65S736W; MPDS include), then `factory living snapshot` | fix + run | done: snp_01M7FDGHSRY0CMBDABKE0HGNPE at ev_01M7FDG711BDTBW770PD1R8WZ0; 365 included, 1 report pending (Zubeldia, first update) |
| 2 | Weekly watch: `watch_plan` amendment (both main queries, window mode, 7-day cadence, end date); proposals ranked by SPECTER2 against the included set | protocol + config | arXiv bound opened (P@2812ff83, PRESS prs_01M7FXYTJB7HS3ZGMTGZ9ZP1HE confirmed); settings form built (Updates page, merged 5015ff9); researcher to save the plan |
| 3 | Daily feed live: researcher selects in the hub; a selection becomes an inbox item (planned route) | first live use | to do |
| 4 | Capture hints and origin tag (IDEA-81): computed origin (`watch`, `feed`, `inbox`), researcher's layer hint and notes, blind to screeners | code | to do |
| 5 | Per-work chain for selected works: screen, acquire, convert, full-text screen, automatic miners on core works ("Process all") | run | to do |
| 6 | Weekly digest and snapshot: new works by route and layer, what changed in the graph and in registered conclusions | config + skill | to do |
| 7 | Corpus growth page in the hub: one point per snapshot (cumulative included, new by route and by layer), table of update flows; computed from snapshot blobs only | code | built as the Updates page (merged 5015ff9, untested); by-layer growth not yet |
| 8 | Ideas from the deltas: contradictions, filled gaps, technique transfers between layers proposed as ideas with their basis works; researcher accepts or rejects; rejections are kept | code + skill | after 2–3 cycles |

## Traceability

- Each update is bounded by two snapshots (`living.snapshot_recorded`); each snapshot pins the
  cumulative PRISMA flow, the included ids and the update flow it closes, in a content-addressed
  blob. Numbers are computed, never typed (R-05).
- Each work's trail (discovery route, verdicts, documents, miner rows) is already queryable
  (`flow_trail`, `trace`).
- The growth page (step 7) reads only snapshot blobs, so a past point never changes.

## Rigour notes

- Screeners never see origin, hints or feed rank (slice 4a blinding).
- The weekly window and the feed are recorded searches or recorded discovery; nothing enters the
  corpus without a recorded event.
- Ideas are proposals; the platform never judges them, and a proposer is not its evaluator.

## Open questions for the researcher

- Watch end date and whether arXiv and OpenAlex both run weekly.
- Whether the feed and the weekly list are one page or two.
- Whether miners see the researcher's layer hint (anchoring) or only the agreement report uses it.

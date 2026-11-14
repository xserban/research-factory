---
name: rf-probe
description: Use when a recorded question must be checked for searchability before a protocol is drafted, using known in-scope and out-of-scope papers (seeds) and candidate queries.
stage: [frame]
---

# rf-probe

Checks that the question is searchable, using known papers as targets. Source: research-factory-old
`stages/01-scope.md`.

## Procedure

0. Follow `rf-develop` at levels `seeds` and `probe`. Every choice of the researcher's below is a
   suggestion set they tick (`decision_suggest`, then `decision_select` or the printed `factory
   decide select` command), and `seed_add` and `probe_run` cite it with `decision_ids`. Explain
   each step and why first; ground each item; no `recommended` flag on research subjects; every
   multiple-choice question has an Other answer. Render each level with `develop_render`.
1. Collect seeds. Ask the researcher for papers they already know are in scope (positive seeds)
   and papers a naive query would catch but they do not want (negative seeds). Aim for three
   positive seeds at minimum and five if possible, and at least one negative seed. Each seed
   needs a `cite` and an identifier (`doi`, `arxiv`, `openalex` or `pmid`). Sources when memory is thin:
   the reference list of the newest review in the area, the researcher's own citations, or the
   "cited by" list of one well-known paper.
   Suggest seeds as lists to tick: positive seeds, negative seeds, and scope rulings (benchmarks,
   surveys: in scope or not). Ground each in where it was found.
2. Add seeds with `seed_add`, citing the seeds decision. Read the
   accepted and rejected items it returns; fix and re-add the rejected ones. Read the current
   list with `seed_list` when needed.
3. Never ask which seeds are held out, and never try to see them. The platform draws the
   hold-out split at the first probe. Seeds that are held out are never returned to you, and you
   must not infer them.
4. Suggest the term blocks and their terms, each term grounded in a slot of the question, a
   seed or sample titles. Skip generic academic words. Then draft two candidate queries per source: one narrow and one broad, so the yield curve between
   them is visible. Each query is term blocks joined by AND, each block a set of synonyms joined
   by OR, and each block traceable to a slot of the question.
5. Run `probe_run` with `queries` set to a list of `{source, query, kind, filters}` items. `kind`
   is the query kind: `keyword` for term queries (or omit it), `filter` for a source-native filter,
   or `id_list` for explicit IDs. Breadth is a property of the query text, so state a narrow and a
   broad query as separate items. The probe is metadata only: counts and seed matching, with no
   full text and no records retrieved for reading.
6. Read the result. For each source and pooled, seed recall is retrieved positive seeds over total
   positive seeds. Negative seed hits are expected; they become exclusion candidates, not query
   changes.
7. Iterate, one round per decision. After each round show the researcher the counts, the unique
   estimate across sources (per-source counts double-count shared records), the sample titles
   of each query (to judge noise) and the overlap. Recall is over testable seeds; list the
   untestable seeds separately and do not count them as misses. Then suggest the next change as
   items to tick (a synonym block a missed seed implies, a term to drop for noise, a filter),
   each grounded in a sample title, a missed seed or a count. Dates go in the filter, not the
   query text, where the source allows (the arXiv probe takes `listed_since`). Two or three
   rounds usually converge. Stop when further rounds stop changing recall.
8. Close the probe as its own decision: items proceed, amend, reframe, each with its grounds
   (recall, counts, noise). The researcher chooses. Route the result. The thresholds are 0.6 for `exploratory`, 0.9 for `pilot` and 1.0 for
   `systematic`. Then state exactly one outcome:
   - **proceed** when pooled recall meets the threshold and the counts are workable;
   - **amend** when the counts are too large or too small, or slots are still open: return to
     `rf-frame` and record a new question version with its reason;
   - **reframe** when no query reaches the threshold: the question is not answerable by topic
     search, so consider citation chasing or a narrative review.

## PubMed queries

- Write the query in PubMed syntax; it is sent verbatim. Use field tags (`[tiab]`, `[mh]`, `[pt]`)
  and combine a MeSH block with a free-text block, since recent records are not yet indexed with
  MeSH.
- PubMed takes no filters: dates go in the query (`2015:2026[dp]`). Record that in the round.
- The sample is the first relevance page (`top`), not a random sample; say so when judging noise.
- A seed is testable on PubMed only if it has a PMID (given as `pmid`, or supplied by OpenAlex).
- A query over 9,999 records cannot be retrieved in one run; split it by `[dp]` before the protocol.

## Tool arguments

Every mutating tool also takes `project` (the project slug), `role`, and `model` (your own model id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do not send one. Pass `rf-probe` as `skill`.

## Human steps

Tell the researcher that `factory seeds` lists the seeds with their identifiers, and that
`factory seeds explain` records a reason when a seed is missed. Do not perform these yourself.

## Done when

Seeds are recorded, the probe results are recorded, and the routing outcome is stated.

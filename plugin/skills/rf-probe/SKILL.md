---
name: rf-probe
description: Use when a recorded question must be checked for searchability before a protocol is drafted, using known in-scope and out-of-scope papers (seeds) and candidate queries.
---

# rf-probe

Checks that the question is searchable, using known papers as targets. Source: research-factory-old
`stages/01-scope.md`.

## Procedure

1. Collect seeds. Ask the researcher for papers they already know are in scope (positive seeds)
   and papers a naive query would catch but they do not want (negative seeds). Aim for three
   positive seeds at minimum and five if possible, and at least one negative seed. Each seed
   needs a `cite` and an identifier (`doi`, `arxiv` or `openalex`). Sources when memory is thin:
   the reference list of the newest review in the area, the researcher's own citations, or the
   "cited by" list of one well-known paper.
2. Add seeds with `seed_add`. Read the
   accepted and rejected items it returns; fix and re-add the rejected ones. Read the current
   list with `seed_list` when needed.
3. Never ask which seeds are held out, and never try to see them. The platform draws the
   hold-out split at the first probe. Seeds that are held out are never returned to you, and you
   must not infer them.
4. Draft two candidate queries per source: one narrow and one broad, so the yield curve between
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
7. Iterate on suggestions. For a missed seed, inspect its title, author keywords and MeSH terms,
   add the synonym block it implies, and probe again. Two or three rounds usually converge.
   Stop when further rounds stop changing recall.
8. Route the result. The thresholds are 0.6 for `exploratory`, 0.9 for `pilot` and 1.0 for
   `systematic`. Then state exactly one outcome:
   - **proceed** when pooled recall meets the threshold and the counts are workable;
   - **amend** when the counts are too large or too small, or slots are still open: return to
     `rf-frame` and record a new question version with its reason;
   - **reframe** when no query reaches the threshold: the question is not answerable by topic
     search, so consider citation chasing or a narrative review.

## Tool arguments

Every mutating tool also takes `project` (the project slug), `role`, and `model` (your own model id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do not send one. Pass `rf-probe` as `skill`.

## Human steps

Tell the researcher that `factory seeds` lists the seeds with their identifiers, and that
`factory seeds explain` records a reason when a seed is missed. Do not perform these yourself.

## Done when

Seeds are recorded, the probe results are recorded, and the routing outcome is stated.

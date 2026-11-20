# Plan: reference parser v2 (initials-first authors) and a better Crossref title query

Status: merged (IDEA-89 follow-up, decision 131; backlog statuses to be confirmed)

Date: 2026-11-17 · Branch: `refparse-v2` · Follows: IDEA-89, decision 130 · Decision: 131 (proposed)

## Goal
Two findings from the live test of 2026-11-16 (researcher approved building both):

A. **Parser.** `factory/references/parse.py` (`PARSER_VERSION` "1") splits an entry at the first
`". "`, so initials-first author lists break: "I. Alabdulmohsin and A. P. Steiner A tale of two
structures: … In ICML …" is stored as `title='I'`, the rest in `venue`. On the pilot, 140 of 349
live extractions have ≥80% flagged titles; 6,474 of 18,268 entries are `too-short` (single
initials), 835 `author-list`, 344 `et-al`. Examples (title | venue as stored):
- `'J'` | `'Baek, S. K. Jauhar, S. Cucerzan, and S. J. Hwang ResearchAgent: iterative research idea generation … In Proceedings of …'`
- `'V'` | `'Akinwande and J. Z. Kolter. Acceleratedlingam: Learning causal dags at the speed of gpus. arXiv preprint'`
- `'C'` | `'F. Aliferis, I. Tsamardinos, and A. Statnikov. Hiton: a novel markov blanket algorithm … In AMIA annual symposium proceedings, volume , page 21'`
Note the source text sometimes drops the period after the author block (LaTeXML output:
"Steiner A tale of …"). Read the real entry texts on the pilot (read-only: index
`data/projects/agentic-science/.index/factory.sqlite`, tables `reference_entries`,
`reference_extractions`; and the converted documents) to build realistic fixtures; never write to
`data/`.

B. **Crossref title query.** `sources/crossref.py` sends `query.bibliographic=<title>` only. For
"Highly accurate protein structure prediction with AlphaFold" the top 10 are all "Faculty Opinions
recommendation of …" (`type: dataset`); for "Visualizing and understanding convolutional networks"
the right chapter is not in the top 10. Across 71 runs, ~1 in 6 items were `peer-review`,
`dataset`, `component`, `grant`.

## Tasks (TDD)

### T1 Parser v2: author block with initials
In `references/parse.py`: recognise an author block of initials-first or surname-first names
(`A. B. Surname`, `Surname, A. B.`, lists joined by `,`, `and`, `&`, ending with `et al.`) and
split the title after the author block, whether or not a period follows it. Keep v1 behaviour for
entries it parses well (regression tests on existing fixtures). Fill `first_author` (surname)
when found. Bump `PARSER_VERSION` to "2" (a new extraction then supersedes the old one, as the
service already does). Tests: the three examples above, a period-less LaTeXML case, an
`et al.` case, a surname-first case, a numeric-label case, and every existing parser test
unchanged. Report, on a read-only sample of 200 pilot entries from the bad extractions, how many
titles v2 recovers (no longer flagged by `reference_items.flags_for`) — as a printed number from
a throwaway script, not a test.

### T2 Crossref title query with author and year, paper types only
`reference_resolve` passes the entry's first author and year with a title lookup (the QuerySpec
gains optional fields, or the text carries them in a documented form; keep the OpenAlex path
unchanged). `CrossrefSource` sends `query.bibliographic=<title>` plus `query.author=<surname>`
when known, and `filter=type:journal-article,type:proceedings-article,type:posted-content,type:book-chapter,type:report`
(verify Crossref filter syntax for several values of one filter: repeated `type:` values are ORed).
Year is not a hard filter (preprint vs published year differ); the matcher already scores years.
Tests: params built for title+author, title only, filter present; the archived page is unchanged
in shape.

### T3 Docs
Decision 131 (Proposed): reference parser v2; Crossref title query with author and type filter.
Backlog IDEA-89 note. Do not regenerate MAP (after merge).

## Testing
Only touched modules' tests (`test_refparse*`/`test_references_*`, `test_crossref*`,
`test_references_resolve`, `test_references_extract`, snowball and pipeline tests that use the
parser) with `--basetemp` outside `/tmp`; mypy --strict and ruff on changed files. Pre-existing
failure on main: `test_mcp_work_params_guard::test_every_work_parameter_is_listed`.

## After merge (with the researcher, not in this branch)
Re-extract the 140+ affected papers (`references extract --corpus-only --work …`, local), then
re-resolve with Crossref.

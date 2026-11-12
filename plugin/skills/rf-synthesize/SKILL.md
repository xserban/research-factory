---
name: rf-synthesize
description: Use when a synthesis page about the corpus (one technique, one lifecycle stage, one field of science, or the whole corpus) must be written from the project's recorded, quoted miner rows and recorded in the project, in a Claude Code session that did not run a screening or extraction pass.
stage: [understand]
---

# rf-synthesize

Writes one page about a part of the corpus from a brief the platform computes, then records it. The
platform computes the statistics and the digest of quoted rows; you write; the platform checks the
page and refuses what it cannot verify. The page is an interpretation, shown everywhere as
model-written; it is never evidence and enters no count.

## Independence

Use a session that has not joined a screening, extraction or miner pass. The platform refuses these
tools to a session that did; do not work around the refusal. Do not read the audit samples, gold
labels or held-out seeds.

## Procedure

1. Call `page_list` to see which scopes already have a page and which are stale (the rows changed
   since the page was written). A scope is `overview`, `technique=<value>`, `stage=<value>` or
   `field=<value>`, with a value of the project's taxonomy.
2. Call `page_brief` for the scope, part 0, then every further part (`parts` tells how many). Part 0
   carries the STATS and the RULES; every part carries a slice of the DIGEST. Read all of it.
3. Write the page in Markdown, about 500 to 800 words, following the RULES of the brief exactly:
   - end every sentence about papers with `[[works/<slug>]]` citations copied from the digest;
   - quote only text shown under the cited work, in double quotes, at most 30 words;
   - use only numbers from the STATS block, years from the digest, or numbers inside a quotation you
     cite; never compute a share or round;
   - say what the corpus record does not show instead of using outside knowledge;
   - state disagreements between papers; do not average them.
4. Call `page_record` with the scope, a title, the text, and `supersedes` when the scope already has
   a page. Read the reply: `check.flags` lists generalisations the platform flagged (a sentence with
   "most" or "few" and no number or citation). Rewrite flagged sentences when you can and record a
   revision that supersedes the first.
5. A refusal names the sentence and the reason (an unknown work, a quotation that is not verbatim in
   a cited work, a number that is not a statistic). Fix exactly that sentence and record again. Do
   not argue with the check and do not paste text that you did not take from the digest.

## Never

- Never state a count, share or year that is not in the brief; never cite a work that is not in the
  digest; never present a flag as resolved when it is not.
- Never edit a recorded page: a revision is a new page that supersedes the old one.
- Never use outside knowledge of a paper, its authors or its results.

## Tool arguments

Every call takes `project` (the project slug). `page_record` also takes `role`, `model` (your own
model id) and `skill` (pass `rf-synthesize`); `page_brief` and `page_list` take neither.

## Done when

The scope has a recorded page whose flags you have read and either fixed or reported, and `page_list`
shows it as current (not stale).

---
name: rf-references
description: Use when works have been included after full-text screening and converted to Markdown, and their reference lists must be extracted, linked to the corpus, and snowballed for further candidates.
stage: [gather]
---

# rf-references

Takes the reference list of each included, converted document into the corpus. The platform
parses the bibliography, links every in-text marker to its entry, resolves each entry against
the corpus and the sources, and records every link state. This skill extracts, reads the pairs
the platform could not settle, proposes (never decides) a link, and asks for snowball rounds
once the researcher agrees.

## When to extract

- The work is included at the last declared screening stage and has a converted document
  (`document_read` shows a conversion). Without a conversion the work is reported as skipped;
  report it, do not work around it.
- Call `references_extract` with no `work_ids` to take every included work not yet extracted.
  Pass `work_ids` only for a named work. A batch is partial-success: works that cannot be
  extracted come back under `skipped` with a reason, the rest are recorded. A malformed id
  refuses the whole call.
- Call `references_status` and report its counts as returned: entries, resolved, unconfirmed,
  ambiguous, unresolved, no-source-record, in corpus, new candidates. The four link states sum
  to the entries. Report any parse flag (`parse-incomplete`, `marker-gap`) of an extraction as
  it stands; do not repair a list by hand.

## How to read an ambiguous or unconfirmed pair

`references_list` with `state` set to `ambiguous` or `unconfirmed` pages through the entries
that need a human decision (`after` is the number of items already seen, `limit` at most 100).
Each item shows the entry's parsed fields (title, first author, year, DOI, arXiv) and the
candidate work or works with their scores.

1. Compare the entry's title, first author and year with each candidate's. Use only these
   fields. Do not use outside knowledge of the papers, and do not look anything up.
2. An entry that names a version, a subtitle or a venue the candidate lacks may still be the
   same paper. Two candidates with near-equal titles are different papers until the fields show
   otherwise. When the fields do not decide it, propose nothing and say so.
3. Never decide on a title alone when the year or first author contradicts it.

## The proposal format

Call `reference_decide` with `decision` set to `propose-confirm` or `propose-reject`, never
`confirm` or `reject`:

- `extraction_id` and `ordinal` from the list item; `work_id` set to the candidate you mean
  (required for an ambiguous link).
- `rationale`: one or two sentences naming the fields that agree or differ.
- `quotes`: exactly two strings, in this order: a span copied character for character from the
  entry's text, then a span copied character for character from the candidate's title or author
  line. The platform checks both against the stored sources and refuses a paraphrase.

A refusal is reported to the researcher as returned. Do not retry with an altered quote.

## Never

- Never confirm or reject a link. A binding decision is the researcher's
  (`factory references decide`). A proposal changes nothing about the corpus; the link feeds
  candidates only after the researcher confirms it.
- Never write a snowball query by hand or pass one to `search_run`. The platform builds every
  query from the stored links and records the round before any query runs.
- Never name a seed, a DOI or a citation to look for. Held-out seeds are not part of this
  step.
- Never run `snowball_round` with `dry_run` false before the researcher has seen the dry run
  and said to go ahead.

## Snowball rounds

1. Call `snowball_round` with `direction` set to `backward` and `dry_run` left true (the
   default). Show the researcher `state` (whether the protocol's `snowball_plan` allows the
   round and why not), the ranked `candidates` with how many included works cite each, the
   `queries`, and the works `unextracted` or `unqueryable`.
2. Only when the researcher agrees, call it again with `dry_run` false. Read the reply:
   `round_id`, one run summary per query, `new_works`. A run that is `partial` or `failed` is
   reported with its note.
3. Call `dedup_run`, then return to screening (`rf-screen`): the new works are pending and are
   never included by this step.
4. After they are screened, `snowball_compare` with the `round_id` lists the references found
   only by the document list, only by the metadata chase, and by both. Report the three counts;
   they are a check on each mechanism, not a selection.
5. A forward round (`direction` `forward`) follows the same dry run, go-ahead and screening. A
   round beyond the plan's maximum, or after a round with no new included work, is refused;
   report the refusal as returned.
6. Report the yield of each round as the platform gives it: new after deduplication and
   included. Do not compute or estimate it.

## Tool arguments

Every tool call also takes `project` (the project slug). The tools that write also take `role`,
`model` (your own model id) and `skill`, the bare skill name `rf-references`; the platform
computes the skill hash, so do not send one. `references_status`, `references_list` and
`snowball_compare` are read-only. These tools are refused to a session that has joined a
screening or extraction pass.

## Done when

Every included work with a conversion is extracted, the unsettled pairs have a proposal or a
stated reason for none, and each round has been reported with its yield, or a refusal has been
reported to the researcher.

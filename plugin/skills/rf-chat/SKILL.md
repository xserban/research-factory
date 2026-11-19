---
name: rf-chat
description: Use when the researcher wants to talk to a selection of papers about a hypothesis (a spar): find the papers that argue against and for it, read them, and record a checked argument sheet. Explore is the default; Prepare is for a result that may feed a lead.
stage: [develop]
---

# rf-chat

Drives one spar over a selection of papers. The platform resolves the selection, checks every quote
and computes tiers and coverage; the reading, the choice of candidates and the strength of each
argument are yours. Before each step, tell the researcher what you are about to do and why, then do it.

## Procedure

1. Agree three things with the researcher, and wait for the answer: the hypothesis wording; the
   selection (`layers`, `include`, `exclude`); the mode. Explore is the default (tier 1 capped at 15
   papers, one session writes both sides). Prepare is for a result that may feed a lead: no cap, and
   the case for is written by a separate session.
2. Call `selection_resolve` and report the works, the exclusions and `est_tokens`. Call
   `claims_digest` and read `markdown` whole, never skimmed (about 54k tokens for the core layer).
   Name the `gaps` (papers with no m-claims rows): the digest cannot speak for them.
3. From the digest, list candidates against and for, each with the claim quoted (source `claims`).
   Then call `corpus_search` twice with 2 to 4 phrasings of the hypothesis and of its negation,
   written as sentences, each with `limit: 20`: once with `method: "keyword"` and once with
   `method: "vector"` (meaning-based). Propose from both lists, side by side, tagging each
   proposal with its source, `keyword` or `vector`, and quoting the passage. If `vector` refuses
   or its reply notes missing vectors or an unavailable model, say so (`factory passages embed`
   fills the vectors) and continue with keyword. Do not use `hybrid`: in the matching test the
   rank fusion dropped a contradicting paper that the vector list found. Reading the whole digest
   found the contradicting paper 11 times in 12, keyword search 8, vector search 5; the union of
   both lists 9: use all. Show the
   researcher the list and let them add or drop papers (source `researcher`). Call `chat_candidates`
   and show the tiers and the coverage. Fix any located issue it returns.
4. Read the relevant sections of every tier-1 paper (`chat_sections`, then `document_read`) and
   confirm each argument in the full text. Copy quotes exactly. Run `chat_verify` on every quote
   before recording it.
5. Call `sheet_open` with the hypothesis, the proposals and the mode. Then `sheet_argue` the case
   against, strongest first, each argument with its `claim` and a
   strength. When an argument rests on a digest claim, pass that claim's row key as
   `claim_row_key`: copy the text after `key=` in its digest line (`[P07.c3 key=rk_...]`)
   exactly; leave it out only for an argument found by search or reading that no digest claim
   states; then `sheet_close` section `against`. Then the case for: in Prepare, stop here and tell
   the researcher to start a separate session for it; in Explore, `sheet_argue` for and
   `sheet_close` `for`.
6. Call `sheet_view` and present it briefly: each argument with paper, quote and why; the coverage
   (tier-1 papers without an argument, gaps, unavailable sources). Tell the researcher how to rate:
   `factory sheets rate <arg_id> sound|weak|wrong --note "..."`. You never rate.

## Tool arguments

Writing tools (`sheet_open`, `sheet_argue`, `sheet_close`) take `project`, `role`, `model` (your own
model id) and `skill`, the bare name `rf-chat`; the platform computes the skill hash.

## Never

- Never invent or paraphrase a quote; an argument rests only on text you have read.
- Never judge the balance of the evidence or give a verdict: that is not built.
- Never assert absence beyond the computed coverage.
- Never name a work as held-out; held-out works are read as corpus (decision 37.9).
- Never rate your own arguments; strengths are your judgement and are labelled so.

## Done when

The sheet is shown with its coverage and the researcher knows how to rate it, or, in Prepare, the
case against is closed and the hand-over to a separate session is stated.

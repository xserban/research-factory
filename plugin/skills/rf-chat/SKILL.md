---
name: rf-chat
description: Use when the researcher wants to talk to a selection of papers about a hypothesis (a spar): find the papers that argue against and for it, read them, and record a checked argument sheet. Explore is the default; Prepare is for a result that may feed a lead. Also use when the researcher asks a question of a selection of papers (Ask): answer it sentence by sentence, each sentence resting on a verified quote. Contradictions mode: read the claims digest and propose pairs of conflicting claims from different papers for the researcher to decide.
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
7. At the end of a spar (both sections closed), tell the researcher to write the balance of the
   evidence themselves: `factory sheets balance <sht_id> --text "..." [--lean
   against|mixed|for|undecided] [--note "what further evidence is needed"]` (or, later, on the
   hub page). Say no more about it: you do not write, draft, compute or suggest the balance or a
   lean. Only a Prepare sheet with both sections closed and the researcher's balance may be cited
   by a lead (a `sheet` trigger of `lead_record`).

## Ask

Use this mode when the researcher asks a question of the papers rather than testing a hypothesis. The
answer is a proposal: the researcher rates it, you never do. The platform checks every quote and
the selection; what each sentence says, and what the papers leave open, is your reading.

1. Agree the question wording and the selection (`layers`, `include`, `exclude`), and wait for the
   answer. If the researcher is following up an earlier answer or sheet, note its id for `parent`.
2. Call `selection_resolve`; report the works, the exclusions and `est_tokens`, and keep its
   `digest`. Call `claims_digest` and read `markdown` whole, never skimmed. Name the `gaps`.
3. Call `corpus_search` twice with 2 to 4 phrasings of the question written as sentences, each with
   `limit: 20`: once with `method: "keyword"` and once with `method: "vector"`. Keep the two lists
   side by side; do not use `hybrid`. If `vector` refuses, say so and continue with keyword.
4. Read the relevant paragraphs in full (`chat_sections`, then `document_read`) before writing a
   sentence about them. Do not rely on the digest or a search snippet alone.
5. Write the answer sentence by sentence (at most 600 characters each). Each sentence names one
   work, one anchor and a quote copied exactly from that paragraph; run `chat_verify` on every
   quote first. A sentence you cannot support with a quote is not written. Answer only from the
   papers of the selection, never from what you know otherwise.
6. Say plainly what the papers do not answer: put it in `unanswered`, not in a sentence, and do not
   assert absence beyond the computed coverage (the gaps of the digest, unread tiers).
7. Call `answer_record` with the question, the selection spec, the `selection_digest` from step 2,
   the sentences, `unanswered` and `parent` when following up. A refusal is located
   (`sentences[2].quote`): fix it and call again; a stale selection means resolve and ask again.
8. Show the answer from the reply, each sentence with its quote and its full paragraph, then the
   counts. Tell the researcher how to rate, a sentence or the whole:
   `factory answers rate <ans_id> sound|weak|wrong [--sentence N] --note "..."`. You never rate.

## Contradictions

Use this mode when the researcher asks which papers of a selection contradict each other. You propose
pairs; the researcher decides, from the Contradictions page of the hub or with
`factory contradictions confirm|reject <ctr_id> --rationale "..."`. You never decide, and a pair you
propose stays "proposed" until then.

1. Agree the selection (`layers`, `include`, `exclude`) and wait for the answer. Call
   `selection_resolve`; report the works and `est_tokens`. Call `claims_digest` and read `markdown`
   whole, never skimmed. Name the `gaps`.
2. Look for pairs of claims from different papers that conflict on the same topic: the same
   `about` (the same subject), an opposite `direction`, or findings that cannot both hold under
   the stated conditions. Two claims of one paper are never a pair. A difference of wording or
   scope is not a contradiction; say what makes it one.
3. For each candidate pair, read both paragraphs in full (`chat_sections`, then `document_read`)
   before you propose it. Run `chat_verify` on each side's quote with the anchor shown in the digest.
4. Record each pair with `contradiction_propose`. Its `ref_a` and `ref_b` are
   `row:<work_id>#<row_key>`: the work id of the paper and the text after `key=` of the digest line,
   copied exactly. Put in `note` (at most 500 characters) what the two quotes say that cannot both
   hold. The platform checks both quotes against their anchors and refuses a row that is not served
   or a quote that is not in its paragraph; fix it and call again, do not rephrase a quote.
5. Report the pairs you proposed, each with its two quotes and your note, the pairs you looked at
   and dropped (and why), and how the researcher decides. Do not say which side is right.

## Unattended run

A headless run (stage `spar` or `ask`, started by the runner) has no researcher to talk to. The
researcher ordered the work beforehand as a recorded request, and one run answers one request.

1. Call `chat_request_next`. It serves the oldest open request of your kind and marks it taken.
   If `batch` is null, say so and stop. Never ask the researcher anything and never wait for a
   reply: the request holds what the agreeing steps would have settled: the hypothesis or the
   question, the selection (`layers`, `include`, `exclude`), the mode and a note.
2. Follow the Procedure (spar) or Ask with the request's own selection, hypothesis or question.
   Skip the steps that show a list to the researcher for additions; the researcher rates the
   result afterwards. Explore unless the request says `prepare`.
3. In Prepare, one run writes one side. A request with no `parent` is the case against: open the
   sheet in mode `prepare`, write the case against, close `against` and stop. A request whose
   `parent` is a sheet with `against` closed is the case for: do not open a sheet; read it with
   `sheet_view`, `sheet_argue` the case for into it, and close `for`, passing `request_id`. The
   researcher orders that second request (`factory chat request spar ... --parent <sht_ id>
   --mode prepare`); this run is a session that wrote no argument against, as the platform
   requires.
   One run answers one request: a second `chat_request_next` is refused, and a chat run is not
   resumed (the researcher orders it again). A result links to the request only from the session
   that took it, while the run is open; a Prepare follow-up never opens a sheet.
4. Pass the served `request_id` to `sheet_open` (or, for the case for, to `sheet_close`) and to
   `answer_record`, so the result is linked to its request. A `parent` that is an earlier sheet or
   answer is read first (`sheet_view`, `answer_view`) and taken into account; an Ask passes it
   as `parent`.
5. End with a short summary: the request id, the sheet or answer id, how many arguments or
   sentences, the gaps and any refusal verbatim. You never rate, and you never write the balance
   of the evidence: the researcher rates and writes the balance later.

## Tool arguments

Writing tools (`sheet_open`, `sheet_argue`, `sheet_close`, `answer_record`, `contradiction_propose`) take `project`, `role`, `model` (your own
model id) and `skill`, the bare name `rf-chat`; the platform computes the skill hash.

## Never

- Never ask a question in an unattended run; take the request and decide by the skill.
- Never invent or paraphrase a quote; an argument rests only on text you have read.
- Never judge the balance of the evidence, give a verdict or suggest a lean: the balance is the
  researcher's (`factory sheets balance`); no tool lets you write it.
- Never decide a contradiction: you propose it, the researcher confirms or rejects it.
- Never assert absence beyond the computed coverage.
- Never name a work as held-out; held-out works are read as corpus (decision 37.9).
- Never rate your own arguments or answers; strengths are your judgement and are labelled so.
- Never answer from outside the papers; an answer sentence without a verified quote is not written.

## Done when

The sheet is shown with its coverage and the researcher knows how to rate it, or, in Prepare, the
case against is closed and the hand-over to a separate session is stated. In Ask, the answer is
shown with paragraphs and the researcher knows how to rate it.

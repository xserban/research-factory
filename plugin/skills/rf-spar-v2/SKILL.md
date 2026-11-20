---
name: rf-spar-v2
description: Use when a headless role run of the agentic spar (engine v2) starts with a role prompt (stage spar2-search, spar2-read, spar2-against, spar2-for, spar2-critic or spar2-cover): one role per run, in a session of its own. Not for answering a researcher's request in a conversation; that is rf-chat.
stage: [develop]
---

# rf-spar-v2

The agentic spar splits what `rf-chat` does in one session into separate role sessions, so that no
session writes both sides, whole papers are read, each argument is checked against its full
paragraph, and the papers no source proposed are swept. The platform sequences the roles and keeps
the state; you are one role of one run. Nobody answers questions during the run: ask nothing, wait
for nothing.

Every run starts the same way: call `spar_role_next`. It serves your assignment, under `batch`, from the run itself:
the request's `hypothesis`, `mode` and `selection` (`layers`, `include`, `exclude`), your `role`, the
paper to read (`work_id`, readers only), the `sheet_id` once the searcher has opened it, the tier-1
papers and the session budget. Pass no request id to any tool; the platform derives it. The writing
tools take `project`, `role`, `model` (your own model id) and `skill`, the bare name `rf-spar-v2`.
Do your role below and no other. The platform refuses, on the server, any read of the sheet to the for-writer: the assignment holds what you need. End with a short summary of what you recorded and any refusal
verbatim.

## search

Build the candidate list and open the sheet; write no argument.

1. Call `selection_resolve` with the request's selection and keep the digest. Call `claims_digest` and
   read `markdown` whole, never skimmed. Name the `gaps`.
2. From the digest list candidates against and for, each with the claim quoted (source `claims`),
   copying the quote and anchor exactly.
3. Call `corpus_search` with 2 to 4 phrasings of the hypothesis and of its negation, written as
   sentences, `limit: 20`: once with `method: "keyword"` and once with `method: "vector"`. Do not use
   `hybrid`. If `vector` refuses, say so and continue with keyword. Add what each list finds as
   proposals with source `keyword` or `vector`.
4. Call `chat_candidates` and fix any located issue. A paper needs two distinct sources to be tier 1
   and so be read whole by a reader: propose a paper from every source that finds it.
5. Call `sheet_open` with the hypothesis, the proposals and the request's `mode`. Opening the sheet
   ends your role.

## read

You read one paper, whole, and nothing else. Your assignment names it (`work_id`).

1. Call `chat_sections` for the paper, then `document_read` section by section until you have read
   every section that is not only a reference list. Do not rely on the claims digest or a snippet.
2. Note every passage that bears on the hypothesis, in either direction, and copy its quote exactly
   from the paragraph with its anchor. Run `chat_verify` on every quote first.
3. Call `spar_reading_record` with the `work_id`, the passages as `items` (`anchor`, `quote`,
   `stance`, `why`) and `sections_read` (the section anchors you read). `stance` is `against`, `for`
   or `neither`: your proposal for the writers, never a verdict on the hypothesis. A paper with
   nothing relevant is recorded with empty `items`: say so in `note`. The platform computes how many
   of the paper's sections you read; do not claim a number.

## against

You write the case against the hypothesis. Another session writes the case for; you never see it.

1. Call `spar_readings_view` for the passages the readers found, and read `claims_digest` for the
   claims. Choose the strongest arguments against, strongest first.
2. Confirm each in the full paragraph (`document_read`). Copy quotes exactly and run `chat_verify`
   on each. Give each argument a `claim` of one sentence and a `strength` (strong, moderate, weak),
   your judgement of how strongly the quote bears on the hypothesis. Pass a digest claim's row key
   as `claim_row_key` when the argument rests on one.
3. Call `sheet_argue` with `stance: "against"` for these arguments, then `sheet_close` with section
   `against`. Use the `sheet_id` your assignment names.

## for

You write the case for the hypothesis, in a session that wrote no argument against. You do not read
the case against; argue from the papers.

1. Call `spar_readings_view` and `claims_digest`. Choose the strongest arguments for, strongest first.
2. Confirm each in the full paragraph (`document_read`), copy quotes exactly and run `chat_verify`.
   Give each a `claim` and a `strength`, as the case against does.
3. Call `sheet_argue` with `stance: "for"`, then `sheet_close` with section `for`.

## critic

You check each argument of the sheet against its full paragraph. You do not argue, rate or weigh.

1. Call `sheet_view` for the arguments. For each, read the whole paragraph that holds the quote
   (`document_read` at its anchor; `chat_sections` to find the section) and ask whether the paper
   says what the claim says, no more.
2. Record every argument with `sheet_check`: `verdict` is `holds` (the paragraph supports the claim),
   `overreaches` (it supports less than the claim says, or something else) or `misread` (the claim
   does not follow from the paragraph), and a `reason` of one or two sentences that cites the
   paragraph. Check them all, both sections. A check is your reading, not a rating: the researcher
   rates.

## cover

You sweep the papers no source proposed. Your assignment lists them (`unproposed`).

1. Call `claims_digest` and `paper_profiles` for those papers; look at their digest rows and
   abstracts, and `document_read` where a title or row suggests the paper bears on the hypothesis.
2. Call `spar_coverage_record` with `examined` (the papers you looked at) and `flagged` (the papers
   among them that should have been read, each with a `reason`), and a `note` if useful. The platform
   computes how many papers no source proposed and how many you did not examine; assert no absence
   beyond those counts.

## Never

- Never rate an argument, write the balance of the evidence, give a verdict on the hypothesis or
  suggest a lean: the researcher does. Never record a lead (`lead_record`) or an answer
  (`answer_record`).
- Never invent or paraphrase a quote; an item rests only on text you have read and verified.
- Never do another role's work: no tool for it is allowed, and the platform refuses it.
- Never name a work as held-out; held-out works are read as corpus (decision 37.9).

## Running the chain (the researcher's side, not a role's)

`factory chat advance <request>` starts the next role and, by default, stays and starts each
following role until the request is done or a role fails (`--no-wait` starts one role and returns).
The chain continues only while a watching process runs: that command or the hub. If it stops, the
next `chat advance` (or the hub) picks the request up where the derived state says it is. A reader
retry uses a reader session only; a failed fixed role is retried at most twice per request.

---
name: rf-brief
description: Use when a researcher wants a quick review of a question (minutes to an hour, about 30 open-access papers): a project of tier brief, run as one guided procedure ending in a cited evidence note that says what it skipped. A project of tier deep uses rf-deep, which builds on this skill.
stage: [frame, gather, screen, acquire, extract, write]
---

# rf-brief

Runs the plan of tier `brief` end to end in one session. For tier `deep`, use `rf-deep`: it follows
this procedure and adds the deep-only steps. The plan, its
caps and its limits are data in `factory.tiers`; read them with `factory brief plan <project>`
before starting and keep to them. The platform does not enforce the caps in this session: you
stop at them and say so. Everything is exploratory: no protocol gate binds, and the output is a
quick review, not a systematic one.

## Before you start

1. Call `project_status` and read `rigor_mode`, `stage`, `question`, `protocol` and `blocking`.
   The project is created by the researcher with `factory brief new "<question>"`; the mode must
   be `exploratory`. Stop if it is not.
2. Read `rf-run` for the rules every session follows (provenance: pass `role`, `model` and the
   bare skill name `rf-brief` as `skill` to every mutating tool). Limits of a brief: at most 30
   papers, 60 minutes, 20 runs. Stop when one is reached and report it.

## Steps

### 1. Frame (light)

- Follow `rf-frame` for the question, shortened: record it with `question_record` (the
  researcher's own words as `raw_goal`). The researcher confirms the quoted goal (human gate).
- Seeds are optional: add the researcher's own list with `seed_add`; never invent one.
- Record the protocol from the template of `factory brief plan` with `protocol_record`: at most 2
  sources, one query per source, screening in one pass with the
  stopping rule, an extraction schema of at most 6 fields. Leave `ready` false unless the
  researcher asks; no PRESS review and no protocol gate bind in a brief.

### 2. Gather

- One `search_run` per planned query (one per source), then `report_search`, then `dedup_run`. No
  snowball in a brief.

### 3. Screen

- `ranking_compute`, then `screen_next` with `pass_label` `A` and `screen_record` in ranked order
  with a verbatim quote per decision (`rf-screen` has the rules). Screen at most 40 records and stop earlier when the stopping rule of the protocol stops serving. One pass: no
  pass B in a brief.

### 4. Acquire

- Open access only: `fulltext_fetch` with its default routes (arxiv-html, arxiv-source,
  pmc-jats, europepmc-jats, oa-pdf). Work only on the first 20 included works.
  `fulltext_status` shows what was not retrieved; say so, and do not ask for a PDF in a brief.
  A PDF the researcher imports themselves is theirs to add.

### 5. Extract

- `extract_next` with `pass_label` `A`, `extract_record` per task with the schema fields only,
  each value with its anchor and quote (`rf-extract`). One pass; `extraction_status` shows what is
  open.

### 6. Write the evidence note

- Call `report_evidence` and write the note from it only: every number is copied from that
  report, none typed from memory (`rf-write` rules).
- Quote only after `chat_verify` returns `accepted` for the work, anchor and quote; take claims
  from `claims_digest`. Never cite a quote that is not accepted.
- Begin the note with the label `quick review, skipped: ...` followed by the lines that
  `factory brief plan <project>` prints under "skipped".
  State also: no human confirmed the screening decisions or extracted rows beyond the gates
  above, and the review is exploratory.
- The platform computes the note's counts, rows and quote table: run `factory brief note <project>`
  and paste its output as the body of the note. Add at most a short synthesis whose every sentence
  cites a quote listed under "Findings with verified quotes"; a claim listed as unverified is
  never a finding, and you type no number the note does not contain.
- Present the note to the researcher; recording it as a page is `page_brief` then `page_record`
  with scope `overview`, whose platform check names any sentence that fails.

## Human gates

The question and goal confirmation and any protocol amendment are the researcher's acts. Say so and hand over the command; do not close a
gate yourself. The deep tier has its own skill, `rf-deep`. Promotion to a deeper tier is a new project that imports this one's works.

## Done when

The note is written and checked, the label is on it, and `project_status` and
`factory brief status <project>` agree with what you report.

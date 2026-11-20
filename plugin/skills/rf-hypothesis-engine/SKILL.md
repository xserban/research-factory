---
name: rf-hypothesis-engine
description: Use when the researcher wants a guided, step-by-step run of the hypothesis generation engine on the project's corpus products (claims digest, technique candidates, lineage), from grounding and lead generation to critique, overlap and prior check, ordering, then drafting and review of hypotheses, with a human decision at every gate, in a Claude Code session that did not read a screening, extraction or mining pass.
stage: [develop]
---

# rf-hypothesis-engine

A guided, human-in-the-loop procedure for engine v1 (steps 1 to 6 and 10 of
`docs/plans/2026-11-19-hypothesis-engine-recipe.md`). It composes tools and skills that already
exist; it adds no rule and no tool.

## The engine in plain words

- Input: the corpus products: the claims digest (miner `m-claims`), the technique candidates
  (gaps, combinations, challenges, neighbours), the lineage and cards where the project has them,
  and `corpus_search` over the papers.
- Output: reviewed hypothesis drafts, each with a falsifier sentence printed by the platform, and
  the record of every lead decided or dropped. Nothing is registered by you.
- A lead candidate is an observation drawn from those products. It is not recorded and is not
  evidence.
- A lead is a short note of at most 600 characters, with at least one trigger that resolves
  (R-120). The researcher promotes, parks or discards it.
- A hypothesis is drafted only from a promoted lead.

Steps 7 to 9 of the recipe (running the test, analysis, verification) are not part of v1: the
existing gates, search and screening tools, evaluation and `check` cover them, and the researcher
runs them by hand.

## Independence

- Use a Claude Code session that has not run a screening, extraction, contribution or mining
  pass. The platform refuses these tools to a session that did; do not work around the refusal.
- You propose. You never decide a lead (`lead_decide` is the researcher's act on the command
  line, `factory leads`), never register (`hypothesis_register` is a human gate), and never
  review a draft or a lead you wrote. The critic is a fresh session (step 3).
- Do not read or ask for the held-out seeds, the audit samples or the answer key. A held-out
  seed's work is a work like any other in the corpus (decision 37.9): do not hide it, and do not
  treat it differently; do not open the held-out seeds file.

## Rigour rules (they hold at every step)

- Everything from miner rows, technique candidates and the claims digest is exploratory, from
  uncalibrated miners (pass A rows where no final rows exist). It is an interpretation, never
  evidence, and no figure from it enters a report (R-87, R-142). Label every count, ranking, gap
  or combination: "exploratory, pass A of <miner>, core layer, n works". Name the lens the tool
  printed.
- Quotes are verbatim. Verify each quote with `chat_verify` (work, anchor, quote: status must be
  `accepted`) or read the anchor with `document_read` before you cite it. A row whose quote you
  cannot verify is dropped from your argument and reported.
- Never claim novelty. The novelty wording is fixed: "found / not found in this corpus
  (exploratory, pass-A rows)", with the passages. "Not found in this corpus" is not "absent from
  the field". Never write "novel", "first" or "never explored".
- Do not use scalar scores of ideas, and do not use a critic's output as a reward for your own
  generation. Scores shown by the tools are components of a computed order, not a judgement.
- A free-form analysis you choose yourself after seeing data may appear only as an exploratory
  note, labelled so. It never sets an outcome.

## Procedure

Before step 1, ask the researcher for the runtime knobs (next section) and state the defaults you
will use for any left open. Say each step and why before doing it. Keep a short running list
(candidates kept, dropped, with the reason) to report at the end.

### Step 1. Ground (HUMAN DECISION POINT H1: sources and technique for this run)

1. Technique candidates (exploratory): `technique_gaps` (`from_stage`, `to_stage`, `min_works`,
   `max_to_share`, `layer`, `rank_by`, `top`), `technique_combinations` (`min_works`,
   `max_co_works`, `stage`, `rank_by`, `top`), `technique_challenges` (`layer`, `limit`),
   `technique_neighbors` for one approach. Read the score components and flags
   (`lookalike-across-stages`, `same-name-across-stages`, `shares-works-with-<id>`) as in
   `rf-technique-bounce`; a flagged pair may be one technique listed twice.
2. Claims: `selection_resolve` (`layers`, `include`, `exclude`) fixes the papers; `claims_digest`
   (same spec, `miner` default `m-claims`) returns the digest: read it whole. Limitation,
   negative-result and failure-analysis rows are the usual starting points. A
   `no-limitation-stated` row is an absence row and is not a trigger on its own. Rows marked
   `(pass-a-only)` stay labelled exploratory; the `gaps` list names papers the digest cannot
   speak for.
3. Passages: `corpus_search` (`queries`, selection spec, `method` `keyword`, `vector` or
   `hybrid`, `limit`, `per_work_limit`). To find papers for and against a claim run `keyword` and
   `vector` as two separate searches and read both lists (decision 140). Tell the researcher when
   the answer carries a `note`.
4. Verify and read every quote you will rely on: `chat_verify`, then `document_read` (`work_id`,
   `anchor`) for context.
5. Other sources the project may have (cards `match_query`, `finder_gaps`, `finder_contradictions`,
   lineage views, seeds, inbox): use them only if the researcher ticks them.

Show the researcher a tick list of candidate observations with their source and counts; the
researcher ticks the ones to take forward.

### Step 2. Generate (HUMAN DECISION POINT H2: pool size and generation technique)

Word a bounded pool of candidate leads from the ticked observations. Each candidate cites its
trigger(s) and states in at most 600 characters what the observation suggests, what would have to
be true, and that it is an exploratory row. Generation techniques the researcher may choose:
combination (from `technique_combinations`), challenge (from `technique_challenges`), gap (from
`technique_gaps` or `finder_gaps`), cross-field transfer, a limitation row left unaddressed
(claims digest), or free sparring in `rf-chat`. Stop at the pool size set by the researcher
(default: at most 12 candidates; the corpus gives no evidence for a best number).

Do not record anything yet. Candidates are text in the session until step 5.

### Step 3. Critique (HUMAN DECISION POINT H3: which critic, rounds, test plan too)

The independent critic reviews hypothesis drafts, not leads (the platform has no lead review):
`hypothesis_review_next` serves the oldest draft without an independent review to a FRESH
session that sees the artefact only, and `hypothesis_review` records the review. You are not
that session. At this step:

- Review your own candidates against the plain checklist before showing them: one factor changes;
  the statement can be refuted; the trigger rows say what the text says; nothing is called
  novel; each cited exploratory row is called exploratory.
- Tell the researcher that the independent review happens after step 6, in another session
  started for that purpose (`rf-critic`), and ask which critic to use (default: a fresh session
  on the artefact only, model recorded; the runtime option is a second model; the researcher
  sets the number of rounds, default one, and whether the test plan is reviewed too). The
  protocol may require a distinct critic model; the platform enforces it.
- A revision is a new draft that supersedes the old one, never an edit.

### Step 4. Novelty and prior check (HUMAN DECISION POINT H4: accept the overlap reading, merge or discard duplicates)

For each remaining candidate:

1. `lead_list` (optionally `state`): read the prior list of open, promoted, parked and discarded
   leads with their triggers. The text of a lead is shown to its author's session only; compare
   by triggers and discard reasons. For earlier hypotheses use `hypothesis_list` and
   `hypothesis_view`.
2. `corpus_search` the candidate's claim as a sentence (`vector`) and as keywords (`keyword`),
   two searches, and `technique_neighbors` for its approaches. Read the nearest passages with
   `document_read`.
3. Report in the fixed wording: "found / not found in this corpus (exploratory, pass-A rows)",
   with the passages (verified quotes) that overlap, and how the candidate differs from each
   prior lead. Do not say "novel".
4. The researcher accepts the reading, merges two candidates, or discards one (dropped here, in
   the session; a discard recorded with a reason is made at `lead_decide`).

### Step 5. Rank and select (HUMAN DECISION POINT H5: ordering measure; promote, park or discard)

1. Order the surviving candidates by a measure the researcher chooses (default, computed from what
   the tools returned, printed with its components, no weighted sum): the number of distinct works
   behind the triggers, then whether the works cite each other (independence), then the share of
   cited rows whose quote you verified, then least overlap with promoted leads, then date. Show the
   components; an order is not a judgement of merit.
2. Record each candidate the researcher wants kept with `lead_record` (`text`, `triggers`,
   `framework` of at most 80 characters, and the usual `role`, `model`, `skill`). Read `prior` in the answer and say how
   the lead differs from each item in it, or withdraw the lead.
3. The researcher promotes, parks or discards each lead with `factory leads` on the command line.
   `lead_decide` exists as a tool, but the platform refuses an agent unless the gate
   `hypotheses.lead_decide` allows it, and it is refused to the lead's own session. In pilot and
   systematic mode this is a HUMAN act: do not call it.

#### Triggers (R-120)

A trigger is `{kind, ref}`. The kinds that exist and that this engine uses today:

- `work` (a work id `rf:...`): the paper the observation comes from. Use one `work` trigger per
  paper behind the lead; two works from two papers beat one.
- `item` (an extraction id `ext_...`): a recorded row. This is the only trigger kind that cites a
  miner row (a technique use row: the failed and the supported row of a challenge, the quote rows
  of a combination or gap; an m-claims row). Take the id from a technique tool result
  (`extraction_id` of the use row). `claims_digest` shows `rk_` row keys, not `ext_` ids, so a
  digest row cannot be cited as `item`: cite the work (`work`) and name the row in the lead text.
- `row` (`rk_...`) resolves only for an evidence-scope row; a miner row given as `row` is
  refused `triggers.N: unknown`. Never use `row` for a miner row. `claim` (`clm_...`) is a claim of
  the extraction pack, not an m-claims row.

Other kinds exist in the model (`idea`, `interpretation`, `concept`, `card`, `contradiction`,
`lead`, `hypothesis`, `direction`, and builder rows `match`, `conflict`, `gap`) and are used when
the researcher's project has them (`rf-ideate` lists them); `gap` is re-checked against
`finder_gaps` only, so a technique gap is not cited as `gap`. There is no trigger kind for a
technique candidate or a claims row as such in v1: cite what it rests on (the works and the rows)
and say in the lead text which candidate it is ("technique challenge, exploratory,
`technique_challenges` lens core").

Code check (`docs/plans/2026-11-19-hypothesis-engine-code-check.md`): a lead holds at most 20
triggers, so for a candidate with many rows keep one quote row per work and then the works, and
say in the lead text that the list was cut. `item` also resolves a row the miner has since
replaced; use only rows that a technique tool returned in this session. If `lead_record` refuses
a trigger (`triggers.N: unknown`, or `trigger-stale` for a builder row), report the refusal
verbatim, fall back to `work` triggers for the papers behind the row, and say in the lead text
which row it came from. Do not invent a reference and do not retry with altered input to obtain
a different answer. Every `work` or `item` you cite becomes a key of the lead, so two leads
citing the same paper show up in each other's `prior`: read it, do not treat it as a duplicate
by itself. The critic sees the verbatim quote of an `item` row (a technique or m-claims row) but not the
lead text, so put the exploratory label and the quote or its gist, with the anchor, in the
hypothesis `statement`.

### Step 6. Specify and design (HUMAN DECISION POINT H6: test kind, decision rule, margin)

From each promoted lead, and only from a promoted lead, call `hypothesis_draft` with a `spec`:

- A lead from the claims digest or from a claims-limitation candidate is for discussion and
  review. Draft it as a literature-direction hypothesis only if you can name a method for the
  `treatment` and a method for the `baseline`; a trade-off or a divergence between measures has
  no natural treatment and baseline, and inventing a pair (or a metric the evidence schema does
  not hold) gives a hypothesis that can never resolve. Leave such a lead a lead. Combination,
  challenge and gap leads name methods and can become hypotheses.
- `kind` and `test`: the default is a literature window (`kind` `literature`, `test`
  `{kind: literature, window_start, sources}`, decision rule `literature-direction` with `n_min`
  and `q`). An `experiment` hypothesis is recorded in the project but tested elsewhere; use it
  only if the researcher chooses it and the evidence schema has the comparability keys.
- `treatment` and `baseline` (`MethodRef`: a card, a lineage idea or a name, with an optional
  evidence row), one `metric`, `conditions` (comparability keys of the evidence schema), a
  `prediction` with a margin stated before any result, `decision_rule` from the menu
  (`superiority`, `non-inferiority`, `literature-direction`), `lead` (the promoted lead id),
  `rationale`, and `supersedes` only for a draft of your own.
- Read the falsifier sentence in the answer. For a literature hypothesis the sentence the platform
  prints does not name the methods, the margin or the direction of the metric: state all three in
  the hypothesis `statement` (the two methods by name, the margin, and whether higher or lower is
  better), so that the critic and the researcher read them. If the sentence does not say what you
  meant to risk, supersede the draft; do not argue it away. The statement holds at most 600
  characters: one or two short quotes with their anchors, the exploratory label and the claim.
  Tell the researcher plainly that, in a project with no evidence-scope rows naming the methods,
  a registered literature hypothesis cannot be evaluated: its evaluation is `incomplete` with the
  flags `cutoff-unknown`, `insufficient-evidence` and `method-unresolved`, and
  `evaluate_hypothesis` runs only with `request_incomplete`, until an evidence schema with a
  method name and comparability keys exists. Where the evidence schema is missing, `conditions` must be `{}` and the methods are
  given by `name`; a method given as a card must be a method card, and a `row_key` a final
  evidence row.
- Technique counts are never the evidence of a hypothesis.

Then stop. The independent review is not yours: tell the researcher to start a fresh session
(`rf-critic`) that calls `hypothesis_review_next` and `hypothesis_review`. You may read the
outcome later with `hypothesis_view` (it hides your own rationale from every other session, and
shows you the reviews). `hypothesis_register` is a human gate (HUMAN DECISION POINT: register or
not, in a session that neither drafted nor wrote the lead); never call it. A hypothesis with
evidence cannot be revised; report that and stop.

### Step 10. Record and feed back (HUMAN DECISION POINT H10: decide the next round)

Report to the researcher, computed from tool results and not from memory: leads recorded and how
the researcher decided each (with reasons), drafts made, reviews received and their
recommendation, registrations. For each dropped or discarded candidate, state the reason, so the
prior list serves the next round. Propose, as a suggestion only, one of: another round on the
same sources; a return to step 2 with a different technique; a return to step 1 with other
sources; stop. The researcher decides. Do not tally percentages without their denominators.

## Runtime knobs

The researcher may set or override each of these at any step; ask for them at the start, state
the default you will use, and record in the lead `framework` field or the report which values
were used.

| Knob | Step | Default |
|---|---|---|
| Sources of observations (claims digest, `technique_*` candidates, finders, cards, lineage, seeds, inbox, free sparring) | 1 | claims digest and technique candidates, layer `core` |
| Literature window and selection (`layers`, `include`, `exclude`) | 1, 4 | the full-text-included population of the current scheme |
| Number of candidates in the pool | 2 | at most 12 |
| Techniques applied at generation (combination, challenge, gap, cross-field transfer, unaddressed limitation, sparring) | 2 | combination, challenge and unaddressed limitation |
| Which critic (fresh session, second model), rounds, test plan also reviewed | 3 | fresh session on the artefact only, model recorded, one round, test plan reviewed with the draft |
| Overlap measures (keyword, vector, technique neighbours, shared triggers) | 4 | keyword and vector as two separate searches, plus neighbours |
| Novelty wording | 4 | "found / not found in this corpus (exploratory, pass-A rows)" |
| Ordering measure | 5 | distinct works, independence, verified quotes, diversity, date |
| Test kind | 6 | literature window; experiment only on request |
| Decision rule, margin, `n_min`, `q`, conditions | 6 | the researcher states them; `literature-direction` for a literature test |
| Analysis | outside v1 | exploratory free-form analysis labelled exploratory only; the registered rule decides the outcome |
| Gate policy per step (human, or off where the protocol allows) | all | the project's recorded policy; in pilot and systematic mode human |
| Loop bound (rounds, stop rule) | 3, 10 | one round, set by the researcher |

## The engine tools: lead_candidates, lead_queue, lead_stats

Three read-only tools do the bookkeeping of steps 1, 2, 4, 5 and 10 (the platform computes; you
judge). Each reply starts with the exploratory notice, is refused to a session that has joined a
pass, and shows at most 40 candidates (30 queue entries); every cited row keeps its quote (a
combination cites up to 10 rows), and only the text of a long quote is cut (marked `[cut]`);
`reply_cap` says what was left out. None of them records anything.

1. Ask the researcher for the knobs and state the defaults: `sources` (any of
   `technique-challenge`, `technique-combination`, `technique-gap`, `claims-limitation`; default
   all), `layer` (default `core`), `technique_min_works` (3) and `max_co_works` (0) for
   combinations and gaps, `order_by` (a list of measures: `support`, `independence`,
   `verification`, `supportive_share`, `overlap`, `diversity`, `prior_hits`, `narrow_prior_hits`,
   `broad_prior_hits`, `score`, `basis`; default `independence`, `support`, `narrow_prior_hits`,
   `verification`, `diversity`, `score`), `top`, `exclude_prior`, `recorded` (`after` by default,
   `first` or `hide`; see below), and `balance` (default true: the top is shared across the sources in play, so
   the many combinations do not crowd out challenges, gaps and limitations; `per_source_top` sets
   the share; `balance=false` is the plain global order). `group_claims_by_work` (default true)
   gives one claims candidate per paper (`claims-work:<work_id>`, flags `grouped` and `rows=<n>`,
   support = its limitation rows, independence 1, at most 19 rows cited); false gives one candidate
   per limitation row (CLI `--no-group-claims`).
2. Call `lead_queue` with those knobs (`lead_candidates` shows the same candidates unordered, to
   see everything one source produced). Show the researcher the ordered list as the tool returned
   it: for each entry the source, the observation, the measures (support, independence, verified
   quotes over total, diversity, overlap, score and its flag), every prior hit with what it shares
   (an `item` shared is narrow; a shared work only is broad: `broad_prior_hits` is shown and, by
   default, orders nothing, because in a corpus where the same works recur two observations that
   share a work say little about each other), the flags (`basis-stale` and the
   like sort last and are reported, never hidden), and the quotes with anchors: every cited row
   has its quote, with its `side` (for a combination the approach each quote supports),
   `described_as` (what the row calls the approach) and the miner's `evidence` class beside it.
   A challenge carries the flag `failure-quote-not-checked`: the platform cannot tell whether the
   `failed` quote states a failure (the label is the pass-A evidence class, not the quote's
   content), so read it and drop the candidate if it states a method and no failure. A gap
   candidate is one per approach with `target_stages` listing every stage no user of it has a row
   at (never `other`). A candidate that an open or decided lead already cites (the same `item`s, or
   at least half of them) carries `recorded_as` (`lead_id`, `state`) and sorts after the unrecorded
   ones; the open lead is then not listed a second time in `leads`. Do not record it again: say
   which lead it is. Say that the order
   is a printed rule over computed measures, comparable only within this call, and not a verdict.
3. The researcher picks (HUMAN DECISION POINT H5). Read each picked quote yourself (`chat_verify`
   and `document_read`) before you rely on it.
4. For each pick call `lead_record` with the candidate's `triggers` exactly as returned (`item` and
   `work`, at most 20; never edit, add or retype one, and never use `row` for a miner row), a
   `text` of at most 600 characters that names the source and says it is exploratory, and the
   knobs used in `framework`: at most 80 characters (a longer value is refused by `LeadInput`
   before the service runs; shorten it, for example `layer core; min_works 3; balanced`). Read `prior` in the answer and say how the lead differs from each
   item, or withdraw it.
5. The critic sees the hypothesis statement and, for each trigger, the verbatim quote of an
   `item` row (a technique or m-claims row), but never the lead text (R-51). Put the exploratory
   label and the quote with its anchor in the hypothesis `statement` all the same, so the critic
   reads them whichever trigger kinds the lead has.
6. Never call `lead_decide` or `hypothesis_register`: the researcher promotes, parks or discards
   with `factory leads` and registers with `factory hypotheses`.
7. At the end (step 10) call `lead_stats` and report its figures with their denominators (leads
   recorded and decided, promotion share as a use figure, discard reasons, hypotheses drafted,
   reviews, registrations, oldest undecided).

The command line shows the same tools compactly: `factory leads candidates|queue|stats` print a
line per entry (at most 110 characters wide, the first quote cut at 160 characters, `--top` 20 for
candidates); `--full` prints every quote and trigger, `--show <candidate_id>` one candidate in
full, `--format json` is complete. Tell the researcher which view you are reading from.

If a tool is refused or absent, report that verbatim. A `framework` over 80 characters is refused
as a validation error naming the field; shorten it and record again. The by-hand route is: steps 1 and 2 with
`technique_*`, `claims_digest`, `corpus_search` and `chat_verify`; step 4 with `lead_list`,
`hypothesis_list` and two `corpus_search` calls; step 5 with a hand order; step 10 counted from
`lead_list` and `hypothesis_list` and said to be counted by hand.

## Stopping

If a call is refused, report the reason verbatim and stop that action; do not retry with altered
input to obtain a different answer. Stop at every HUMAN DECISION POINT until the researcher
answers. Report at the end: the knobs used, the sources and tools called, the candidates kept and
dropped with reasons, the ids recorded, what is waiting for a human (decisions, review,
registration), and that every figure from the technique candidates and the claims digest is
exploratory and not for a report.

## Tool arguments

Every write call (`lead_record`, `hypothesis_draft`) also takes `project` (the slug), `role`,
`model` (your own model id) and `skill`, the bare skill name: pass `rf-hypothesis-engine`. The
platform computes the skill hash and records the model with every event.

## Done when

The researcher has the observations ticked, the leads recorded with resolvable triggers and
their prior, the researcher's decision on each, the drafts from promoted leads with their
falsifier sentences, the instruction for the independent review, and the next-round suggestion.

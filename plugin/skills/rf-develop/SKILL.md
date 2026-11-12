---
name: rf-develop
description: Use when the scientist's goal, research questions, plan, seeds, probe or protocol must be decided: it runs the suggest-and-select loop at each decision, one level at a time, and renders each level as a formal document.
stage: [frame]
---

# rf-develop

The develop stage and the loop every decision of the scientist's follows. It replaces drafting a
whole document and asking for approval. Specification: `docs/specs/slice-8-develop.md`.

## The loop

At every decision the scientist owns, in this order:

1. **Explain.** Say in two or three sentences what the step is and why it is taken now, so the
   process itself can be criticised. The same text goes in `explanation`.
2. **Suggest.** Call `decision_suggest` with `level`, a `subject` slug and a short list of items
   (`item_id` `I01`, `I02`, ...; `text`; `grounds`). One decision is one list of items to tick,
   never a whole document.
3. **Ask.** The scientist ticks the items to keep, adds items of their own and may leave a note.
   Where the client supports it, call `decision_select`: it asks the scientist through a form,
   and you cannot pass item ids. Otherwise tell them the exact command and wait:
   `factory decide select <decision_id> --item I01 --item I03 --add "own item" --note "why"`.
   Never record a selection yourself and never infer one from chat.
4. **Act.** Read the result with `decision_view`. Record what the decision feeds
   (`question_record`, `seed_add`, `probe_run`, `protocol_record`) and cite the decision with
   `decision_ids`. Record only what the selection covers: validated and added items, nothing
   rejected, nothing more. If the act would depart from the selection, suggest a new set with
   `supersedes` and a reason instead.
5. **Render.** When every decision of the level is selected and acted on, call `develop_render`
   with the level and show the scientist the document. The level is complete when they validate it.

## Levels, top-down, one at a time

A level is drafted only after the level above it is validated.

| Level | Decisions (one suggestion set each) | Feeds |
| --- | --- | --- |
| `goal` | scoping dimensions; Objective; Key Results; later cycles | goal document |
| `questions` | main question; one or more questions per Key Result; scope | `question_record` (`rf-frame`) |
| `plan` | study frame; review method; shortcuts; phases; evidence scale; bias controls; limits | plan document |
| `seeds` | positive seeds; negative seeds; scope rulings (benchmarks, surveys) | `seed_add` (`rf-probe`) |
| `probe` | term blocks and terms; variants per round; next change after each round; close | `probe_run` (`rf-probe`) |
| `protocol` | inclusions; exclusions; sources; snowballing; screening plan; extraction fields | `protocol_record` (`rf-protocol`) |

### Goal (OKR)

- Start from the scientist's words. Analyse them for vague terms and hidden assumptions ("best",
  "AI scientist"), and suggest scoping dimensions (end state, artefact, autonomy, meaning of the
  key word, domain, horizon), each with options to tick.
- **Objective:** a qualitative statement of the intended change, significant, ending in an end and
  not a means.
- **Key Results:** each a minimum outcome that an independent reader could confirm, an outcome and
  not an activity. Values are assessed afterwards; a missed minimum is reported as a finding.
  Activity counts (articles reviewed) belong to Initiatives, which stay indicative here.
- Later cycles are listed, not planned. Reviews follow new evidence, not a calendar.

### Questions

- One main question and one or more sub-questions, each serving a Key Result. Sub-questions go in
  `sub_questions` (`SQ1`, ...) with `serves` naming the Key Result. Scope (field, dates) is its own
  decision. Remove words the scientist does not want in the question (the pilot dropped
  "human-directed" from the main question).

### Plan

- Study frame, review method, shortcuts, phases, evidence scale, bias controls and limits are each
  a decision. The scientist may overrule the method; record theirs.
- Declare every shortcut with its consequence to be reported.

## Rules (learned in the pilot)

- **Items, not wholes.** Each item is Proposed until selected, then Validated or Rejected. Rejected
  items stay on record.
- **Grounded.** Every item names its grounds in `grounds`: a probe id, sample titles, a seed, a
  document, an earlier decision. Do not draw suggestions from templates: in the pilot, exclusions
  suggested from a template named papers no source returned. An item with no grounds is allowed
  and is flagged by `check`; say so to the scientist.
- **Neutral on research decisions.** Goal, questions, method, criteria and terms carry no
  `recommended` flag and no ordering by preference; the platform refuses it. Only technical
  subjects (`tooling`, `ordering`, `fix`, `model-choice`, `setting`) may carry `recommended`, and
  the scientist may follow or ignore it.
- **Scope, do not copy.** Documents are formal deliverables, not transcripts. Do not repeat the
  scientist's wording where it is vague; ask which reading they mean.
- **Do not overstate.** A claim that something must be fixed before reading may be wrong for the
  method (a scoping review can derive stages while charting). Check the claim against the method
  chosen before putting it in an explanation.
- **A changed selection is a new set.** Suggest again with `supersedes` and a reason. Never edit
  or hide an earlier selection.
- **No held-out seed** is named, hinted at or inferred in any suggestion. Do not ask which seeds
  are held out.
- **Multiple-choice questions always include an Other answer**, in the form and in chat.
- Pass the bare skill name `rf-develop` as `skill`; `role` and `model` as the other tools take
  them.

## Done when

Every decision of the level is selected, acted on with its record citing the decision, the level
is rendered, and the scientist has validated the document. Then take the next level down. Hand
over to `rf-frame` (questions), `rf-probe` (seeds, probe) and `rf-protocol` (protocol).

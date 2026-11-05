---
name: rf-write
description: Use when a draft (related work, review, grant background or horizon note) is to be written sentence by sentence from the verified material of a project, in a Claude Code session that did not read a screening or extraction pass.
---

# rf-write

Writes prose against a deterministic outline of verified material. The platform builds the outline
from claims, evidence rows, lineage and reviewed interpretations; you write one sentence at a time
and say what class it is and which supports it rests on. The platform refuses a sentence whose
support is not eligible, whose number is not in a support, or that is more than one sentence. It
flags risky wording. It never writes prose, and you never set a status, a flag, a count or a
citation key.

## Independence

- Use a Claude Code session that has not run a screening, extraction or contribution pass. The
  platform refuses these tools to a session that did; do not work around the refusal.
- A session that later verifies a sentence of a draft cannot write in it, and a session that wrote a
  sentence cannot verify it. Do not verify your own draft.
- Do not read or ask for the held-out seeds, the audit samples or the answer key.

## Procedure

1. Read the outline with `writing_outline` (ids and codes only). Create the draft with
   `draft_create`, choosing its kind and, if the researcher asked for one, a scope (`ideas`,
   `groups`).
2. Pull a slot with `draft_next`. Its content lists the section's eligible supports with their
   verified quotes, the numbers they contain, the stat values the platform computed, the method
   disagreements and the sentences already written there. Cite only supports shown in the slot.
3. Write with `draft_write`, one sentence per item, with the slot's `task_id`:
   - `claim`: states something about the literature. Cite at least one support and name only what
     its quote says. Prefer a `cell` or a `claim` support.
   - `synthesis`: states an aggregate (a count, a consensus, a comparison within one group). Cite a
     `stat` or a `group` support. Use `synthesis` with a `stat` for any count, and for "most",
     "all" or "none".
   - `interpretive`: your reading or explanation. Cite reviewed interpretations (`interp:`) or
     evidence; write no number.
   - `structural`: a transition or scope statement. No support, no number, no citation, no author
     and year, and no method name that the draft cites elsewhere.
4. Never type a citation or a number that is not in a span of the supports you cite. The renderer
   adds the citation keys of the support works. A number you state must be a number in a quote, the
   value of a cited cell, a `stat` value or the year of a support work.
5. Where the slot lists a disagreement between independent results, state the disagreement; do not
   average it and do not pick one.
6. Write "the corpus does not support ..." sentences from the limits slot, using its codes and the
   `stat:` supports it offers.
7. Compare across groups only with supports from one group. A comparison that cites cells of two
   comparability groups is flagged `cross-group`.
8. Read the result of each call. A rejected sentence names the field and the reason; fix that and
   write it again. A flag (`citation-mismatch`, `quantifier-without-statistic`, `cross-group`,
   `single-source-generalisation`, `off-outline`) is shown to the verifier: rewrite the sentence
   when you can. Check the draft with `draft_status`.
9. To revise a sentence, write a new one whose `supersedes` names it.

## Stopping and human steps

Verifying, auditing, rendering and releasing a draft are other steps and other sessions. If a call
is refused, report the reason verbatim and stop; do not retry with altered input to obtain a
different answer.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-write` as `skill`. `writing_outline` and `draft_status` do not take `role`, `model` or `skill`.

## Done when

Every section of the draft has the sentences the researcher asked for, each accepted by the
platform, and the flags that remain have been read and either fixed or reported.

---
name: rf-verify
description: Use when the sentences of a draft are to be checked against the spans they cite, in a Claude Code session that wrote no sentence of that draft and joined no screening or extraction pass.
---

# rf-verify

Judges, one sentence at a time, whether a sentence of a draft is supported by the spans it cites.
You see the sentence, the sentence before it as context, what each support says and the flags the
platform computed. The platform checks that what you quote is verbatim; it never judges support,
and you never set a status, a count or a label. Your verdict is what stands between a draft and an unsupported statement, so
judge the sentence as written, not as its writer may have meant it.

## Independence

- Use a Claude Code session that wrote no sentence of the draft and joined no pass. The platform
  refuses these tools to such a session; do not work around the refusal.
- Once you have recorded a verdict on a draft you cannot write in it.
- In systematic mode the writer's model cannot verify; use another model when one is available.
- Do not read the draft's rendering or the writer's outline before you judge: the unit holds all
  you need. `draft_status`, `draft_render`, `draft_next` and a `trace` reaching the draft are
  refused once you hold a unit or have recorded a verdict on it, and `check` names none of its
  sentences.
- Do not read or ask for the held-out seeds, the audit samples or the answer key.

## Procedure

1. Pull a unit with `draft_verify_next`. Its `supports` list each support's `ref`, `kind` and
   `spans`: quotes, a cell's value, a stat's computed value, the values of a group's rows.
2. Judge only from the spans shown. Never use outside knowledge, including what you recall of the
   paper. The preceding sentence is context; a sentence does not borrow its supports. A support with
   `spans_omitted` above zero shows only part of its group: when the sentence speaks of the whole
   group and the rest could matter, use `overstated` or `partial`, not `supported`. The unit's
   `flags` are the platform's own checks, such as `quantifier-without-statistic`: look harder where
   one points, but a flag is not a verdict and its absence is not support.
3. Choose one verdict:
   - `supported`: the spans say what the sentence says.
   - `partial`: part of the sentence is said, part is not.
   - `unsupported`: the spans do not speak to it.
   - `contradicted`: the spans say otherwise.
   - `overstated`: scope, hedging or quantifier exceed the spans, as when a sentence says *all*
     and a span says *some*.
4. Always quote the sentence part and the span part. Give `sentence_span` verbatim from the
   sentence, and in `support_spans` one `{ref, substring}` per support you used, verbatim from one
   of its spans. Only `supported` may leave `sentence_span` out, and only `unsupported` may leave
   `support_spans` empty.
5. Record it with `draft_verify_record`, with the unit's `task_id`. A `note` of at most 300
   characters may say why; it is for the researcher.
6. Pull the next unit until `unit` is null.

A refusal names the field and a fixed reason. Fix what you quoted and record again; do not change
the verdict to get past a refusal.

## Tool arguments

Every tool call also takes `project` (the project slug), `role`, and `model` (your own model
id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do
not send one. Pass `rf-verify` as `skill`: a verdict under another skill is refused.

## Done when

`draft_verify_next` returns `unit: null`: every sentence that can be verified has a verdict. Report
how many of each verdict you recorded. A stale sentence is not served; its writer revises it.

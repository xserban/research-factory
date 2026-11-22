---
name: rf-protocol
description: Use when a probed question must become a versioned review protocol with parented eligibility criteria, sources, search strategy and screening plan, or when a ready protocol needs an amendment or a deviation is recorded.
stage: [frame]
---

# rf-protocol

Drafts the protocol that authorises every later search and screening decision. Sources:
research-factory-old `stages/02-protocol.md` and `RIGOR-MODES.md`.

## Procedure

0. Follow `rf-develop` at level `protocol`, and only after the plan, seeds and probe levels are
   validated. Each decision below is a suggestion set the researcher ticks, never a whole protocol
   to approve: inclusions; exclusions; sources; snowballing; screening plan; extraction fields.
   Explain each step and why first. Ground each item in what the probe returned (counts, sample
   titles, seeds, missed seeds). No `recommended` flag on criteria or sources; the tooling of the
   screening plan may carry one. `protocol_record` cites the decisions with `decision_ids` and
   records only what they select. Render the level with `develop_render`.
1. Draft criteria. Every criterion has:
   - `id` (`IN01`, `EX01`, ...);
   - `parent`: a question slot or a non-goal (`NG*`). A criterion with no parent is ad hoc; either
     add its element to the question (a new question version) or drop it;
   - `statement` and `rule`. The rule is a yes/no question that can be answered from the
     paper. A description of relevance is not a rule;
   - `applies_at`: `title-abstract`, `full-text` or `either`. A title-abstract criterion must be
     answerable from title, abstract and metadata alone;
   - `priority` for exclusions: a total order with no ties, so each exclusion has one reason.
   Ground criteria in what the probe returned. Suggest an exclusion only for records that pass
   every inclusion and that a source actually returned (cite the sample title or probe); an
   exclusion for papers no source returns, or that an inclusion already removes, is not
   suggested. The pilot cut six template exclusions to three.
2. Cite examples. In `examples`, list development seeds that sort to their known verdict under
   the criteria as a whole. Do not invent seeds to fill counters. A seed that refuses to sort
   means the criteria are wrong, not the seed.
3. Declare sources with their numbers: the probe recall, the probe count and a `why`. Exclude a
   source only with a reason from the probe.
4. Write the search strategy per source with every PRISMA-S field: exact string, platform,
   filters, limits and date. Each limit carries its justification. A limit added after the probe
   counts is flagged as such.
   Snowballing: suggest the rounds per direction (`max_backward_rounds`, `max_forward_rounds`)
   and whether a direction stops when its previous round added no included work; a forward cap
   field of `SnowballPlan`, if present, is its own item. Screening: suggest passes, the sample
   double-checked and the kappa floor; the local ranker (`ranking_compute`) and its stop rule
   (`stop_after_consecutive_excludes`, title and abstract only) are items, the stop rule is a
   risk the researcher accepts and is reported. Extraction fields: one item per field, grounded
   in the Key Result or sub-question it serves.
5. Fix commitments before reading. Declare the screening plan (passes, reviewers and roles, the
   kappa floor, `kappa_enforced`, and how disagreements resolve, never automatically) and the
   extraction fields with their meanings. In `pilot` the kappa floor is advisory. In `systematic`
   it must be at least 0.7 and enforced.
6. Record the draft with `protocol_record`, passing `rf-protocol` as `skill`. A draft can be
   replaced freely. Set `ready` only when the researcher has agreed the protocol.
7. PRESS review. Run the review in a separate subagent that receives the protocol and the search
   strategy only, with no authoring context. It checks the six PRESS 2015 elements. Record its
   findings with `protocol_press_review`. Then tell the researcher to confirm each finding with
   `factory protocol confirm-press <review_id> --response "..."`, giving one `--response` per
   finding in order. Do not confirm it yourself.
8. Amend a ready protocol with `protocol_amend`, which takes `spec`, `reason`, `semantic`, and
   `effects`. The platform refuses the call and writes nothing when a check fails.
   - `effects` maps each changed criterion id to `loosened`, `tightened` or `clarified`. It must
     name exactly the changed criteria: no missing ids and no unchanged ids.
   - `semantic` is `false` only when no criterion is added or removed, no other hashed field
     changes, and every effect is `clarified`. Otherwise it is `true`. There is no justification
     mechanism; the platform checks this rule.
   - The platform computes the stale decisions from the effects.
   Use `protocol_deviation` for a protocol that was not followed. Deviations are kept separate from
   amendments and need a `reason`.
   Where the platform refuses you the amendment, the record or the deviation as something you may
   not apply alone, file it with `review_request` instead: `kind` is `protocol-amend`,
   `protocol-record` or `deviation`, and `proposal` holds what that tool takes. Approval applies
   nothing; a holder of the role then runs the tool with the `review_request_id`.
9. Search. `search_run` takes no protocol argument; the current ready protocol is implicit. In
   `pilot` or `systematic` mode, a query the protocol does not plan needs `protocol_deviation`
   first. Then pass the returned `deviation_id` to `search_run`. In `exploratory` mode no
   deviation is needed, and no ready protocol either: a project whose protocol is not ready, or
   that has none, may search freely while it is exploratory (the platform checks the rigour mode,
   not the protocol, for that; a pilot or systematic project needs a ready protocol first).

## Tool arguments

Every mutating tool also takes `project` (the project slug), `role`, and `model` (your own model id), alongside `skill`, which is the bare skill name. The platform computes the skill hash; do not send one. Pass `rf-protocol` as `skill`.

## Rules

- Never ask for, and never try to see, held-out seeds.
- Never edit a ready protocol directly.
- Pass the bare skill name as `skill`; the platform computes the hash.

## Done when

The protocol is recorded, its PRESS review is recorded, and the researcher has confirmed it. Any
later change goes through an amendment or a deviation.

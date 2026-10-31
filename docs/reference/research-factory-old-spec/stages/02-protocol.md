# Stage 02 — Protocol

> Converts a probed question into the **authorization object**. Nothing downstream may act
> without citing it: a search run names the protocol version it executed, a screening
> decision names a criterion belonging to a specific version. Produces `P@<sha>`.

## Contract

| | |
| --- | --- |
| **INPUT** | `Q@<sha>`, surviving probe, harvested vocabulary, per-source counts, negative seeds |
| **ACTOR** | agent (drafting) + human (confirmation) |
| **OUTPUT** | `01-protocol/{protocol.yaml, criteria.yaml, search-strategy.yaml, amendments.yaml, deviations.yaml, protocol.md}` |
| **GATE** | `rf gate 02` |
| **STANDARD** | PRISMA-P (17 items), PRISMA-S, Cochrane MECIR C24–C43 |

## Why this stage exists

Everything before this is preparation; everything after is execution. The protocol is what
makes the difference between the two visible. Its job is not to be correct — it is to be
**explicit, and cited by everything it authorizes**, so that when it turns out to be wrong,
the wrongness has a scope you can compute rather than a shadow you have to guess at.

## 1. Eligibility criteria

The core artifact. Each criterion carries five things, and the last two are where most
protocols quietly fail.

```yaml
# 01-protocol/criteria.yaml
IN02:
  parent: slot:Method                    # traceable to the question
  statement: "Applies self-supervised or unsupervised pretraining prior to the target task."
  rule: "Does the abstract state that the model was pretrained without task labels?"
  applies_at: title-abstract
  examples:
    include: [SEED01, SEED03]
    exclude: [SEED05]

EX03:
  parent: NG01
  statement: "Validation on phantom or simulated data only, with no in-vivo cohort."
  rule: "Does the paper report results on data acquired from living subjects?"
  applies_at: full-text
  examples:
    exclude: [SEED04]
  priority: 3
```

### `rule` — operational, not aspirational

> **A criterion is a question with a yes/no answer, not a description of relevance.**

"Relevant to coronary imaging" is not a criterion. Two reviewers applying it will disagree,
and neither will be wrong, because there is nothing to be wrong about. The `rule` field
forces the criterion into a form that can actually be applied, and the disagreement it
would have caused surfaces here — where it costs a sentence — instead of in Stage 04, where
it costs a κ failure and a re-screen.

### `applies_at` — the most common screening error

A criterion requiring information that is not in an abstract **cannot be applied at
title/abstract screening.** Excluding a paper at abstract stage on grounds you could not
possibly have assessed there is the single most common defect in real reviews, and it is
invisible afterwards: the decision log looks complete.

Declaring the stage prevents it. For every `applies_at: title-abstract` criterion, the author
asserts that the `rule` is answerable from title, abstract and metadata alone. The gate records the
assertion; it cannot verify it — that is agent-or-human judgment, and pretending otherwise would be
the same error one level up. What *is* mechanical is the consequence: Stage 04 counts "cannot
assess" verdicts per criterion, and a title-abstract criterion accumulating them is the assertion
being falsified by use.

### `examples` — the seeds earn their keep

Criteria cite the Stage 01 seeds as worked examples. `EX03` excludes `SEED04`; `IN02` includes
`SEED01`.

The requirement is on the **set, not the individual criterion**: every seed must sort to its known
verdict under the criteria as a whole. Demanding an example per criterion would be unmeetable —
five seeds cannot exercise twelve criteria — and would push the author to invent seeds to satisfy
a counter, which is exactly backwards. What matters is that no seed lands on the wrong side.

This gives the criteria a test suite, which means:

- ambiguity is caught at authoring time, when a seed refuses to sort cleanly;
- Stage 04 screening can be *calibrated* against known-correct answers rather than trusted;
- an amendment that breaks a worked example is detected immediately.

### `priority` — deterministic exclusion reasons

PRISMA requires full-text exclusions be reported **with reasons**, and a paper usually
violates several criteria at once. Without a declared order, two reviewers excluding the
same paper for two equally valid reasons produce different counts, and the flow diagram
becomes irreproducible.

So exclusion criteria carry a **total priority order**, and the recorded reason is always
the highest-priority criterion violated. Arbitrary, deterministic, and reproducible — which
is the whole requirement.

## 2. Information sources — justified by Stage 01, not by convention

Every source is included or excluded *with its numbers*:

```yaml
sources:
  include:
    - name: openalex
      seed_recall: 0.83          # from 01-scope, per source
      probe_count: 1840
      why: "Broadest coverage; retrieved 5/6 positive seeds."
    - name: arxiv
      seed_recall: 0.50
      probe_count: 210
      why: "Only source retrieving SEED03; preprint coverage is load-bearing here."
  exclude:
    - name: pubmed
      why: "Probe returned 12 records, none of them seeds. The literature is not indexed
             there — this is a methods question, not a clinical one."
```

"We searched PubMed and Scopus" is a convention, not a justification. A source earns its
place by retrieving seeds the others miss, and a source that retrieves nothing new costs
screening time for no coverage — which the per-source recall from Stage 01 makes visible.

## 3. Search strategy — PRISMA-S complete

The final query per source, in that source's own syntax, with every field PRISMA-S requires:
exact string, platform/interface, filters applied, limits, date run, expected count. Written
here, executed unchanged in Stage 03.

Limits carry their Stage 01 justification forward. A limit present here but absent from
`01-scope` was added *after* the counts were seen — which the gate determines by set difference
rather than asking the author to confess. It is flagged as such, because a cut-off chosen to make the numbers
manageable is a different act from one chosen because the technique did not exist before
then, and only the reader who can tell them apart can judge the review.

## 4. Commitments made before reading

Three things are declared now, and the reason is the same for all three: **committing before
you read is what stops the review from being shaped by what you find.**

**Screening plan** — number of passes, reviewer configuration, κ floor, and how
disagreements resolve (never automatically; see Stage 04).

**Extraction schema** — the fields to be pulled from every included work. Deciding *after* reading
which fields to extract is how a review ends up reporting exactly the outcomes that happened to
support its conclusion. This stage declares *which* fields exist and what each means; Stage 06
governs how they are filled. A field added during extraction is an amendment like any other.

**Appraisal instrument, per work type** — RoB 2 for randomised studies, ROBINS-I for
non-randomised, GRADE for certainty of the body of evidence, AACODS for grey literature.
Declared per type so that a blog post and a trial are not graded on the same scale.

## 5. Hash and commit

```
P@<sha256(criteria + sources + search strategy + limits + schemas + Q@sha)[:8]>
```

Prose is excluded from the hash, as in Stage 00. The protocol names the question version it was
built against, so `rf trace` can distinguish "the conclusion changed because the evidence
changed" from "the conclusion changed because the question did".

### Criterion references are version-qualified

A bare `EX03` is ambiguous the moment the protocol is amended, because `EX03` means something
different in `P@a1b2c3` than in `P@d4e5f6`. Every downstream reference is therefore written
`P@a1b2c3:EX03`, and this is not a formality — it is the whole reason `rf restage` can compute a
blast radius at all. Unqualified references would make a decision log that *looks* complete while
silently re-pointing at criteria that have since changed underneath it, which is worse than an
incomplete log because it cannot be detected.

## Registration — optional, and narrower than people think

In `systematic` mode the protocol should be registered before screening begins, so that its date
is attested by someone other than its author. This is the only mechanism here that a determined
author cannot forge, and it costs an afternoon.

The nuance worth knowing: **PROSPERO only accepts reviews with health-related outcomes.** A
methods review — "does self-supervised pretraining help segmentation" — will be rejected, because
the outcome is Dice, not patient benefit. The alternative is OSF Registries, which accepts any
discipline and issues a timestamped, immutable record.

`rf` writes `registration: {registry, id, date}` into `protocol.yaml` when one exists, and records
`registration: none` with a reason when it does not. Unregistered is a legitimate choice; silently
unregistered is not.

## Amendments and deviations — two different admissions

| | **Amendment** | **Deviation** |
| --- | --- | --- |
| What happened | the protocol changed | the protocol was not followed |
| When recorded | prospectively, before acting | retrospectively, on discovery |
| Normal? | yes — expected, especially in `pilot` | no — each one needs a reason |
| File | `amendments.yaml` | `deviations.yaml` |

Conflating them is how reviews launder mistakes into method. Rewriting the protocol to match
what you actually did makes a deviation *look* like an amendment, and the amendment log —
the thing a reader trusts — becomes the instrument of the deception. Keeping them apart costs
nothing and is the difference between a record and a story.

### Blast radius

An amendment invalidates some past decisions and not others. `rf restage` computes which:

```
$ rf restage --from P@a1b2c3 --to P@d4e5f6
EX02 relaxed (semantic)
  → 11 decisions cited EX02 to exclude; all 11 are stale, re-screen required
  → 0 inclusions affected (loosening cannot invalidate an inclusion)
IN04 wording clarified (semantic: false)
  → no decisions stale
```

Loosening a criterion stales the *exclusions* that cited it; tightening stales the
*inclusions* that passed it; adding one stales every record never tested against it. The
author declares whether a change is semantic; the gate requires the declaration, and a
`semantic: false` on a changed `rule` is treated as a claim needing justification, because it
is the cheapest place to hide a real change.

## Gate 02

| Check | exploratory | pilot | systematic |
| --- | --- | --- | --- |
| every criterion has an `id`, `parent`, `statement`, `rule` | ✓ | ✓ | ✓ |
| every `parent` resolves to a slot or `NG*` | ✓ | ✓ | ✓ |
| every non-goal referenced by ≥1 exclusion | warn | ✓ | ✓ |
| every *filled* slot referenced by ≥1 inclusion | warn | ✓ | ✓ |
| every criterion declares `applies_at` | ✓ | ✓ | ✓ |
| `title-abstract` criteria assert abstract-answerability | warn | ✓ | ✓ |
| exclusion `priority` is a total order, no ties | warn | ✓ | ✓ |
| every seed sorts correctly under the criteria set | — | warn | ✓ |
| every source carries recall + count + justification | ✓ | ✓ | ✓ |
| search strategy PRISMA-S complete | warn | ✓ | ✓ |
| limits added post-probe are flagged | ✓ | ✓ | ✓ |
| extraction schema non-empty | warn | ✓ | ✓ |
| appraisal instrument declared per work type | — | grey only | ✓ |
| κ floor declared | — | ✓ | ✓ |
| `P@<sha>` written, names `Q@<sha>` | ✓ | ✓ | ✓ |

## Failure modes

| Failure | Detection | Escape |
| --- | --- | --- |
| Criteria are descriptions, not rules | `rule` cannot be phrased as a yes/no question | rewrite; if it resists, the underlying slot is vague — return to Stage 00 |
| A criterion has no parent | gate | either it is smuggled scope (add it to the question and re-version) or it is not a criterion |
| Seeds refuse to sort under the criteria | worked examples contradict | the criteria are wrong, not the seeds — this is exactly what seeds are for |
| Criteria drift silently during screening | amendments with `semantic: false` on changed rules | gate flags; author must justify |
| Protocol rewritten to match what was done | deviation logged as amendment | dating: an amendment recorded after the decisions it authorises is a deviation |
| Over-specification | 20 criteria, most never cited by any decision | dead-criterion warning after Stage 04; prune and record |
| `applies_at` optimism | abstract-stage criterion needing full-text data | gate asks explicitly; Stage 04 flags "cannot assess" verdicts against it |

## Handoff to Stage 03

Stage 03 receives `P@<sha>` and executes its search strategy **unchanged**. Any difference
between the executed query and the protocol's is a deviation by construction — which is the
point of writing it here rather than there.

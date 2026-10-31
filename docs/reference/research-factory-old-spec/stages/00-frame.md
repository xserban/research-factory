# Stage 00 — Frame

> Turns a vague goal into a **versioned question object** that every downstream artifact
> can cite. Produces `Q@<sha>`.

## Contract

| | |
| --- | --- |
| **INPUT** | none required — a sentence from the researcher, or nothing at all |
| **ACTOR** | agent + human |
| **SKILLS** | `clarifying-questions-first`, `brainstorming-research-ideas`, `scientific-brainstorming`, `creative-thinking-for-research` |
| **OUTPUT** | `00-question/{question.md, framing.yaml, question.lock}` |
| **GATE** | `rf gate 00` |
| **STANDARD** | PRISMA-P items 1–4 (rationale, objectives, eligibility framing) |

## Why this stage exists

Eligibility criteria are *derived from* the question. That is the rule that makes the whole
chain hold:

> **Every criterion in Stage 02 must name the question element it derives from**
> — `IN01 ← Population`, `EX02 ← NG03`.

A criterion with no parent is ad-hoc, and ad-hoc criteria are how reviews drift toward the
answer the author already had. So the question must be decomposed into named, addressable
parts *before* criteria exist — not because decomposition is virtuous, but because those
parts are the anchor points criteria attach to.

The second job is versioning. The question is hashed, and every protocol names the question
version it was built against. Change the question later and that is a new version, so
`rf trace` can always show which conclusions rest on which framing. **Scope creep becomes
visible instead of invisible.** That is most of the scientific value of this stage.

## Procedure

### 1. Capture the raw goal verbatim

Record the researcher's own words, unedited. Do not paraphrase, tidy, or "sharpen" them
into the record. The original phrasing is the ur-artifact — every later version diffs
against it, and drift is only detectable if the origin survives.

`raw_goal` is an **append-only list**, not a single string. Researchers restate their intent
as they think ("actually, what I really care about is…"), and freezing the first throwaway
sentence is as lossy as overwriting it. Each self-stated intent is appended with a
timestamp; none is ever edited or removed.

### 2. Choose a framing scheme — provisionally

| Scheme | Slots | Use for |
| --- | --- | --- |
| `PICO` | Population, Intervention, Comparator, Outcome | clinical / interventional |
| `PECO` | Population, Exposure, Comparator, Outcome | observational / risk |
| `SPIDER` | Sample, Phenomenon, Design, Evaluation, Research type | qualitative / mixed |
| `TDMBM` | Task, Data, Method, Baseline, Metric | **method / ML reviews** |

`TDMBM` is not a standard instrument — it is ours. That is acceptable: the standards require
the framing be *declared and applied consistently*, not that it come from a fixed list.

The choice is **provisional until step 4**. You often cannot tell whether a question is
interventional or methodological until the interview has run, and a scheme picked too early
distorts the questions asked to fit it. If the slots resist filling, re-select the scheme
rather than forcing the answers, and record the switch in `scheme_rationale`.

### 3. Interview — bounded at five questions

Use `clarifying-questions-first`. Two hard rules:

- **Never ask what `raw_goal` already answers.** Re-asking is how researchers lose faith in
  a tool on its first screen.
- **Hard cap of five questions.** Whatever is unknown at five becomes an *open slot*, not a
  sixth question. Stage 01 answers those better than the researcher can anyway.

### 4. Fill slots — `open:` is a valid answer, `TBD` is not

An unfilled slot is a legitimate, recorded output that routes to the scope probe:

```yaml
Data:
  open: "Which imaging modalities are actually represented in this literature?"
  resolve_in: "01-scope"
```

The distinction matters: `open:` is a question with an owner and a destination. `TBD` is an
absence that silently survives into screening, where it becomes an arbitrary judgment call.
The gate rejects `TBD` for exactly that reason.

But `open:` has a ceiling. Stage 01 can harvest vocabulary; it cannot invent the
researcher's intent. If more than half the slots are open, the question is not
under-specified — it is *absent*, and the honest move is to say so and keep interviewing.

### 5. Write the non-goals

Minimum one (`exploratory`) or three (`pilot`, `systematic`). The test for a good non-goal:

> **a plausible-looking paper that a good query would return, that you do not want.**

"Not about cats" is useless. "Not phantom-only validation studies" is a real non-goal,
because those *will* show up and someone *will* have to decide about them.

Non-goals carry **stable IDs** (`NG01`, `NG02`, …) for the same reason slots do: a Stage 02
criterion must be able to name its parent, and `EX02 ← NG03` is only expressible if the
non-goal has an identity. A non-goal still unreferenced at the end of Stage 02 raises a
warning — either it was not really a boundary, or a criterion is missing.

### 6. Rationale and objectives

PRISMA-P 1–4: what gap, why now, primary objective, secondary objectives. Two or three
sentences each. This is not a grant application.

### 7. Hash and version

```
Q@<sha256(scheme + sorted(slot values) + primary_question + sorted(non_goals))[:8]>
```

Hash the **semantic fields only**. Prose — `scheme_rationale`, the objectives, the rationale
section — is deliberately excluded: rewording an explanation must not mint a new question
version, or the history fills with changes that mean nothing and the ones that matter stop
standing out.

Deterministic, so an unchanged question re-hashes identically. Later versions record
`supersedes` and the reason for the change.

### 8. Confirm, then propose the rigor mode

Show `raw_goal` back to the researcher, quoted, before anything else — see the gate note
below on why this step cannot be automated away.

Then infer the rigor mode from the stated purpose and timeframe, show the reasoning, offer
the override, and say it is reversible via `rf promote`. See `spec/RIGOR-MODES.md`.

## Output artifacts

```yaml
# 00-question/framing.yaml
scheme: TDMBM
scheme_rationale: "Method review of ML approaches; PICO's Intervention/Comparator
                   slots do not map onto architecture families."
slots:
  Task:     "Lumen and plaque segmentation on coronary CTA"
  Data:
    open: "Which cohort scales and vendors are represented?"
    resolve_in: "01-scope"
  Method:   "Self-supervised or foundation-model pretraining"
  Baseline: "Fully supervised training on the same architecture"
  Metric:   "Dice, or clinically-reported stenosis agreement"
non_goals:
  NG01: "Phantom-only validation with no in-vivo cohort"
  NG02: "Non-coronary vascular beds (carotid, peripheral)"
  NG03: "Pretraining studies reporting no supervised baseline"
```

```yaml
# 00-question/question.lock
id: Q@a1b2c3d4
at: 2026-09-09T22:40Z
supersedes: null
raw_goal:
  - at: 2026-09-09T22:31Z
    text: "i want to know if self-supervised pretraining is actually worth it for
           coronary CTA segmentation or if it's just hype"
rigor: pilot
rigor_rationale: "Stated intent is a decision input for next year's project scope,
                  not a publication. Dual screening on a sample is proportionate."
```

`question.md` carries the human-readable rationale, objectives, primary and secondary
questions, and the non-goals with their IDs.

## Gate 00

| Check | exploratory | pilot | systematic |
| --- | --- | --- | --- |
| `raw_goal` recorded, non-empty | ✓ | ✓ | ✓ |
| exactly one primary question | ✓ | ✓ | ✓ |
| framing scheme declared | ✓ | ✓ | ✓ |
| no slot equal to `TBD` (`open:` permitted) | ✓ | ✓ | ✓ |
| every `open:` slot names a `resolve_in` | ✓ | ✓ | ✓ |
| `open:` slots ≤ half of all slots | warn | ✓ | ✓ |
| non-goals | ≥1 | ≥3 | ≥3 |
| every non-goal has an `NG` id | ✓ | ✓ | ✓ |
| rationale + objectives non-empty | warn | ✓ | ✓ |
| `Q@<sha>` written | ✓ | ✓ | ✓ |
| rigor mode set with rationale | ✓ | ✓ | ✓ |

The gate checks **structure, never quality**. It cannot tell you the question is good. It
can tell you the question is not yet *usable*, which is the only thing a machine is
entitled to assert here.

One check is weaker than it looks and is labelled as such: the gate can detect `raw_goal`
being *edited after* it was written, but it cannot detect the agent paraphrasing at first
write. Nothing mechanical closes that gap — only the researcher reading the captured line
back. That is why step 8 quotes it.

## Failure modes

| Failure | Detection | Escape |
| --- | --- | --- |
| Question far too broad | Stage 01 returns >5k records | return here; amend; `Q@v2` records why |
| Question far too narrow | Stage 01 returns <15 records | widen a slot, or accept that a narrative review is the honest output |
| Slots unfillable — unfamiliar domain | agent cannot fill ≥2 slots | do **not** guess; mark `open:`, run 01 as vocabulary harvest, return |
| "I don't know" to most questions | interview stalls | this is a *scoping* question, not a systematic one — propose `exploratory` and a deliberately wide framing |
| Agent paraphrases the goal into something cleaner | only the researcher can catch it | step 8 quotes `raw_goal` back before anything is committed |
| Non-goals are vacuous | all fail the "plausible paper" test | reject and re-elicit; a vacuous non-goal is worse than none, because it looks like coverage |

## Open design question

Whether Stage 00 may emit **competing candidate questions** rather than one. The gate
currently forbids it (`exactly one primary question`), which keeps the trace clean but
misrepresents how research starts. Provisional answer: candidates are explored in Stage 01
as scratch probes and never committed — only the survivor gets a `Q@<sha>`. Revisit once
Stage 01 is specified.

## Handoff to Stage 01

Stage 01 receives `Q@<sha>` and every `open:` slot as its work list. It returns record
counts per candidate query plus harvested vocabulary, either resolving the open slots or
sending the question back for amendment.

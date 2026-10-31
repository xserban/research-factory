# Stage 04 — Screen

> Applies the protocol's criteria to every record, twice and independently, and records one
> decision per record per pass. The stage where the agent exercises the most judgment, and
> therefore the one with the most machinery around it.

## Contract

| | |
| --- | --- |
| **INPUT** | unscreened records; `P@<sha>` criteria; the calibration set |
| **ACTOR** | agent (verdicts) + human (disagreements, calibration labels) |
| **OUTPUT** | `04-screening/{title-abstract.yaml, full-text.yaml, calibration/, agreement.yaml}` |
| **GATE** | `rf gate 04` |
| **STANDARD** | Cochrane MECIR C39–C45; PRISMA 2020 items 8, 16 |

## Who is the reviewer

**The human is the reviewer of record. The agent is an assisting reviewer.** This is not a
courtesy — it is the only defensible position, and it has to be visible in the artifacts.

A review has authors who are accountable for its judgments. "The model decided" is not an
answer to a peer reviewer, an editor, or an ethics committee, and a corpus of 5,800 decisions
no human ever authorised is not a review anyone can stand behind. So authority and effort are
separated:

> **Every decision is authorised by the human — individually, or by a rule the human wrote.**

Most are authorised by rule. That is the point of criteria.

### Judgment is front-loaded, not delegated

The human's judgment does not enter at verdict time. It enters earlier, where it has leverage:

| Where the human decides | Affects | Cost |
| --- | --- | --- |
| the **criteria** | all 2,904 records | hours |
| the **calibration labels** | measures whether the application is correct | ~1 hour |
| the **audit sample** | detects agreed-but-wrong | ~1 hour |
| **disagreements** | 194 records | 2–3 hours |
| any **override** | 1 record | seconds |

Leverage runs strictly downward. An hour spent sharpening `EX03` changes thousands of
verdicts; an hour spent adjudicating individual records changes a few dozen. So a workflow
that pushes the human toward per-record adjudication is spending their attention at the worst
possible exchange rate.

The corollary is the useful one: **if screening feels like it needs a lot of judgment, the
criteria are bad.** Good criteria make screening an act of *application*, not decision — and
low per-criterion κ is exactly the measurement of that failure.

### Roles are declared, not assumed

```yaml
# 01-protocol/protocol.yaml
reviewers:
  - id: human:aserban
    role: reviewer-of-record
    duties: [criteria, calibration, disagreements, audit, final-inclusion]
  - id: agent:screen@v1/model-x
    role: assisting-reviewer
    duties: [pass-A]
  - id: agent:screen@v1/model-y
    role: assisting-reviewer
    duties: [pass-B]
```

Every decision names its reviewer, so the log always answers "who judged this, and under whose
authority". `rf export` emits a methods statement from this block — most journals now require
disclosure of exactly what was automated, and a record that cannot produce that statement is a
record that was not keeping it.

### The audit sample — the check κ and calibration both miss

Disagreements get human eyes by construction. **Agreed decisions do not**, and *agreed-and-wrong*
is the failure neither κ (which sees consistency) nor a pre-batch calibration set (which sees a
fixed 30 records) will catch.

So the human audits a random sample of records **both passes agreed on**:

- 2% of agreed decisions, minimum 50, drawn after screening;
- weighted **3:1 toward agreed excludes**, because a false exclude is unrecoverable and a false
  include costs twenty minutes;
- an error rate above a declared floor fails the gate and sends the criteria back to Stage 02 —
  it is evidence of systematic misapplication, not of a few unlucky records.

This is the mechanism that lets a human be accountable for 2,904 decisions they did not
individually make: they wrote the rule, measured that it was applied faithfully, and can show
the measurement.

## Two passes, and what independence actually requires

Single-reviewer screening is not accepted practice, and **an agent is a single reviewer with a
confident voice.** So every record is screened twice. The hard part is that two passes by the
same model with the same prompt are not independent — they are the same reviewer asked twice,
and their agreement measures nothing.

Independence has to be engineered:

| Mechanism | Why |
| --- | --- |
| Different prompt framing | Pass A asks "does this meet the inclusion criteria?"; Pass B asks "is there a reason to exclude this?". Framing moves verdicts on borderline records, which is the point |
| Different criterion order | first-listed criteria dominate; reversing the order decorrelates that |
| Different model where available | the strongest decorrelation, since shared training is the deepest common cause |
| No shared context | each pass runs in its own invocation and never sees the other's verdict |

Record which mechanisms were used. A κ computed over two identical passes is a number with no
meaning, and it will look reassuring.

## Statelessness, and where learning is allowed to live

**Each record is screened in a fresh context.** No accumulating history, no memory of earlier
verdicts, records presented in randomised order.

This costs something real: the agent cannot learn from the borderline cases you resolved an
hour ago. That cost is accepted deliberately, because the alternative is drift — an agent
screening 800 abstracts in one context applies subtly different standards at record 700 than
at record 20, and nothing in the log shows it. Statelessness makes screening reproducible in a way no stateful alternative can be: each verdict
depends only on one record, the criteria version, and the prompt, so it can be re-derived in
isolation.

It does not make verdicts bitwise deterministic — models are not, even at temperature 0, and
claiming otherwise would be the kind of overstatement this whole design exists to prevent. What
is guaranteed is that a verdict has no *hidden* inputs. Sampling settings and the exact model
version are recorded as part of the reviewer identity (`agent:screen-titles@v1/claude-x-2026-05`),
so an unreproducible verdict is at least an explicable one.

Learning still happens, but it is forced into the open:

> **A resolved borderline case becomes a worked example or a criterion amendment — never a
> remembered precedent.**

So the knowledge enters the *protocol*, where it is versioned, visible to both passes, and
applied to every record including the ones already screened (via `rf restage`). Implicit
learning would apply it only to records screened after the lesson, producing a corpus screened
under two different standards with no record of the boundary.

## Verdicts — four, not two

```yaml
- id: D0417
  work: rf:zhou2023-coronary-ssl
  pass: A
  stage: title-abstract
  verdict: exclude
  criterion: P@d4e5f6:EX03        # version-qualified, highest-priority violated
  rationale: "Abstract reports phantom acquisition only."
  confidence: high
  reviewer: agent:screen-titles@v1
  at: 2026-09-11T15:02Z
```

| Verdict | Meaning | Routing |
| --- | --- | --- |
| `include` | meets every inclusion criterion applicable at this stage | next stage |
| `exclude` | violates a criterion applicable at this stage | out, with the criterion named |
| `cannot-assess` | the information needed is not present at this stage | **promote**, never exclude |
| `unsure` | information is present; the judgment is genuinely borderline | route to human |

`cannot-assess` and `unsure` are different, and collapsing them loses the most useful signal
in the stage. `cannot-assess` is a fact about the *record* — an abstract that does not say
whether the cohort was in-vivo. `unsure` is a fact about the *criterion* — it does not cleanly
decide this case.

### `cannot-assess` falsifies Stage 02

Stage 02 asserted that each `applies_at: title-abstract` criterion is answerable from an
abstract. That assertion could not be verified there. Here it meets evidence: a title-abstract
criterion accumulating `cannot-assess` verdicts is the assertion being falsified by use, and
`rf gate 04` reports the rate per criterion. Above a threshold, the criterion's `applies_at`
should move to `full-text` — an amendment, recorded like any other.

## Screen for recall, not accuracy

The two error directions are not symmetric, and treating them as if they were is the most
consequential mistake available in this stage.

| | Cost | Recoverable? |
| --- | --- | --- |
| **False exclude** | a relevant paper leaves the review | **No.** It is never looked at again, and nothing downstream can detect it |
| **False include** | a full text is read unnecessarily | Yes. Stage 04b catches it, at the cost of twenty minutes |

So: **when in doubt, include.** The calibration thresholds are asymmetric for the same
reason — high sensitivity is required, moderate specificity is acceptable, and an agent tuned
for balanced accuracy is tuned wrong for this task.

## Calibration — which measures something κ cannot

Before each screening batch, both passes screen a **human-labelled calibration set** of ~30
records drawn from the corpus, including the Stage 01 seeds.

This exists because of a distinction that is easy to lose:

> **κ measures consistency. Calibration measures correctness.**

Two correlated agents can agree perfectly and both be wrong; κ would be 1.0 and the screening
worthless. Only labels produced by a human answer whether the verdicts are *right*. Both
numbers are needed, and neither substitutes for the other.

```yaml
# 04-screening/calibration/CAL2026-09-11.yaml
n: 30
sensitivity: 0.95        # of records the human included, agent included 19/20
specificity: 0.80        # of records the human excluded, agent excluded 8/10
floor: {sensitivity: 0.90, specificity: 0.60}
verdict: pass
disagreements: [rf:liu2021-..., rf:patel2022-...]
```

Calibration disagreements are the most valuable output of the stage. Each one is either an agent
error or an ambiguous criterion, and the second is far more common — which makes calibration a
criterion-debugging tool that happens to also produce a number.

That dual use creates a trap. If a disagreement prompts a criterion amendment, the calibration
set has been used to *tune* the thing it is supposed to measure, and every subsequent score on
those records is optimistic. The set is therefore **partitioned**:

- a **working** portion, whose disagreements may drive amendments;
- a **held-out** portion, never inspected, used only to produce the reported number.

An amendment derived from the working portion requires the held-out portion to be re-scored, and
a held-out score that drops after an amendment means the amendment fixed the examples rather than
the criterion. Held-out records that have been looked at are burned, and are replaced by fresh
human labels rather than reused.

## Agreement

κ is computed overall **and per criterion**. Overall κ tells you a problem exists; per-criterion
κ tells you where it is, and only the second is actionable.

This requires something of the verdict format that is easy to miss. Per-criterion κ asks "did
both passes agree that this record violates `EX03`?" — which is unanswerable if a pass only
reports the single highest-priority violation it found, and unanswerable for every included
record, where no criterion is cited at all.

So each pass **evaluates every applicable criterion** and records a per-criterion judgment; the
*reported* exclusion reason remains the highest-priority violation, per Stage 02. One is the
diagnostic record, the other is the PRISMA-facing answer, and conflating them costs the only
actionable agreement metric in the stage:

```yaml
  criteria_eval:
    P@d4e5f6:IN02: met
    P@d4e5f6:EX01: not-violated
    P@d4e5f6:EX03: violated        # highest-priority violation -> reported reason
    P@d4e5f6:EX05: cannot-assess
```

```
$ rf agreement
overall κ = 0.62   (floor 0.70)  FAIL
  EX03  κ = 0.31   ← 78% of all disagreements
  EX01  κ = 0.88
  IN02  κ = 0.91
```

> **Low κ means the criteria are ambiguous, not that the reviewers are bad.**

The response is never to re-run until the numbers improve. It is to read the disagreements on
the offending criterion, find the ambiguity, amend the criterion, and re-screen the affected
records via `rf restage`. Re-running screening unchanged in the hope of a better κ is the same
error as re-running a search until the counts agree.

## Disagreement routing — never automatic

| Pattern | Resolution |
| --- | --- |
| `include` vs `exclude` | **human**, always |
| human vs agent, on any record | the human wins, and no rationale is owed — the agent is assisting |
| `exclude` on different criteria | not a verdict disagreement; record both, report the higher-priority one |
| `cannot-assess` vs `exclude` | promote — the conservative direction |
| `cannot-assess` vs `include` | promote |
| any `unsure` | human |

A tie-break rule that resolves include/exclude automatically would make the second pass
decorative, and the κ it produces a statistic about a process nobody is running.

But "route to human" does not scale, and pretending it does produces a queue of 300 records that
quietly gets rubber-stamped. The `unsure` and disagreement rates are therefore themselves gated:
above roughly 15% of a batch, screening **stops**. A rate that high is not a workload to grind
through — it is the criteria failing to decide the corpus, and the fix is upstream in Stage 02.
Grinding through it produces 300 decisions with the reliability of a coin flip and the appearance
of a complete record.

## Blinding

Author, venue and citation count are stripped from the screening payload by default in
`systematic` mode. An agent carries the field's prestige associations from its training data
as surely as a human carries them from the corridor, and screening is exactly where that bias
does the most damage — a weak paper from a strong lab is the case the criteria exist to catch.

Recorded as `blind_fields: [authors, venue, cited_by_count]`.

Blinding here is partial and should not be oversold: abstracts leak their origin through
self-citation, cohort names, dataset access and house style, and a model with broad training
recognises a lot of that. Stripping the fields removes the loudest signal, not the bias.

## The stage runs twice

Full-text screening cannot happen before full text exists, so:

| Pass | Input | Then |
| --- | --- | --- |
| **04a** title/abstract | metadata only | survivors go to Stage 05 for acquisition |
| **04b** full text | normalised full text | survivors are the included studies |

PRISMA's "reports sought for retrieval" and "reports not retrieved" sit between them, and
belong to Stage 05.

## Cost

Dual screening of 2,000 records is ~4,000 model calls plus calibration. This is the most
expensive stage by a wide margin, and it is why `exploratory` mode screens once: the honest
trade is *fewer records screened well* over *more records screened alone*. When the budget is
tight, narrow the question rather than dropping the second pass.

## Gate 04

| Check | exploratory | pilot | systematic |
| --- | --- | --- | --- |
| every record has a verdict, every configured pass | ✓ | ✓ | ✓ |
| every `exclude` names a version-qualified criterion + rationale | ✓ | ✓ | ✓ |
| independence mechanisms recorded | — | ✓ | ✓ |
| calibration run before the batch | warn | sample | ✓ |
| calibration sensitivity ≥ floor | warn | ✓ | ✓ |
| overall κ computed | — | advisory | ≥ floor |
| per-criterion κ reported | — | ✓ | ✓ |
| every disagreement human-resolved | — | ✓ | ✓ |
| reviewer roles declared in the protocol | ✓ | ✓ | ✓ |
| audit sample of agreed decisions drawn | — | ✓ | ✓ |
| audit error rate ≤ declared floor | — | warn | ✓ |
| no `cannot-assess` left unpromoted | ✓ | ✓ | ✓ |
| `cannot-assess` rate per criterion reported | warn | ✓ | ✓ |
| decisions append-only; supersessions carry reasons | ✓ | ✓ | ✓ |

## Failure modes

| Failure | Detection | Escape |
| --- | --- | --- |
| Passes are not actually independent | κ ≈ 1.0 with no `unsure` | check the recorded mechanisms; identical prompts produce meaningless agreement |
| Agent agrees with itself and both are wrong | high κ, low calibration sensitivity | calibration is the only detector; this is why it is not optional |
| Drift across a long batch | verdicts correlate with position | statelessness prevents it by construction; randomised order detects residual effects |
| κ below floor | `rf agreement` | amend the criterion with lowest per-criterion κ; never re-run for a better number |
| Borderline resolutions applied inconsistently | records before and after a resolution decided differently | resolutions must become amendments, not precedents; `rf restage` re-applies them backwards |
| `cannot-assess` used as a soft exclude | high rate on one criterion, all promoted records later excluded on it | correct behaviour, but the criterion belongs at `full-text` |
| Human rubber-stamps disagreements | resolution rationales are empty or templated | a resolution with no rationale fails the gate |
| Both passes agree and both are wrong | the audit sample, and nothing else | this is why the audit covers *agreed* decisions; κ and calibration are both blind to it |
| Human authority becomes nominal | every audited record rubber-stamped; no overrides ever recorded | an audit that never disagrees is not evidence of accuracy, it is an unmeasured process |
| Calibration set leaks into the corpus as pre-decided | calibration records appear with human verdicts before screening | calibration labels are stored separately and never read as decisions |

## Handoff

**04a →** Stage 05 receives every `include` and every promoted `cannot-assess` as the set to
acquire full text for.
**04b →** Stage 06 receives the included studies. The excluded-with-reasons table is now
complete and PRISMA's screening block is derivable.

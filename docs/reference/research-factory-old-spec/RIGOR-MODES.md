# Rigor Modes — "Amend freely, record always"

## The distinction that matters

I earlier conflated two different things under "freeze":

- **Freeze** — a constraint on *behaviour*. You may not change the protocol. Heavy,
  restrictive, and hostile to real exploratory work.
- **Lock** — a *versioning* mechanism. The protocol is hashed, so any change is visible
  as a delta. Light. Pure bookkeeping.

The scientific property we actually want is **not** "the protocol never changed." It is
**"anyone can see exactly when it changed, why, and what that did to the conclusions."**

So: the protocol is a versioned object, not a notarised document. Amend it whenever the
evidence teaches you something. `P@v1 → P@v2` with a recorded delta and a reason costs
about fifteen seconds and buys full defensibility.

**Rigor comes from recording, not from rigidity.**

## The three modes

Declared in `protocol.yaml` as `rigor: exploratory | pilot | systematic`.

| | `exploratory` | `pilot` *(default)* | `systematic` |
| --- | --- | --- | --- |
| Protocol changes | free, versioned | free, versioned | free, versioned |
| Gates | warn only | warn, block on broken links | block |
| Screening passes | 1 | 2 on a sample | 2 on everything |
| Cohen's κ | not computed | computed, advisory | floor enforced |
| Non-goals required | 1 | 3 | 3 |
| Appraisal | optional | grey lit only (AACODS) | GRADE + RoB on all |
| Claim locators | encouraged | required | required |
| PRISMA output | counts only | full flow | full flow + PRISMA-S report |

Note what does **not** vary: the protocol is versioned in every mode, and provenance is
recorded in every mode. Those two are never optional, because they are the only things
that cannot be reconstructed after the fact.

## Retroactive promotion — why relaxed now costs nothing later

Because recording happens in every mode, a project can be upgraded after the fact:

```
rf promote --to systematic
```

This does not silently re-grade anything. It emits a **gap list** — the exact work needed
to make the existing corpus meet the higher standard:

```
Promotion exploratory -> systematic requires:
  [ ] 412 records screened by a single reviewer      -> second pass required
  [ ] 38 included works lack GRADE appraisal         -> appraise
  [ ] 6 claims lack section locators                 -> re-extract
  [ ] queries QRY02, QRY05 missing platform/filters  -> PRISMA-S fields incomplete
  [ ] no calibration set recorded                    -> label 30 records
```

This is the payoff of recording-over-restricting. Starting relaxed does not foreclose
rigor; it defers the *cost* of rigor to the point where you know the review is worth
publishing. Most surveys never reach that point, and paying PRISMA tax on all of them is
why people abandon systematic tooling.

## Amendment and staleness

Changing a criterion invalidates some past decisions but rarely all of them. `rf restage`
computes the blast radius mechanically:

- **Criterion loosened** → previously *excluded* records that cited it must be re-checked.
- **Criterion tightened** → previously *included* records that passed it must be re-checked.
- **Criterion added** → every record that was never tested against it is stale.
- **Wording clarified, semantics unchanged** → author marks `semantic: false`; nothing stales.

```yaml
# 01-protocol/amendments.yaml
- from: P@a1b2c3
  to:   P@d4e5f6
  at:   2026-09-14T11:20Z
  change: "EX02 relaxed: phantom-only studies now eligible if they report an in-vivo cohort."
  reason: "Pilot screening surfaced 11 hybrid studies that EX02 excluded on a technicality."
  semantic: true
  stale: 11 decisions        # computed, not asserted
```

Amendments are a normal part of the record, not a confession. A review with a clean
amendment log is more credible than one with none, because one with none is usually a
review whose protocol was written after the screening.

## Consequence for Stage 02

There is no `protocol.lock` and no freeze ceremony. There is `protocol.yaml` carrying a
version hash, plus `amendments.yaml`. The pilot is not a distinct phase with a boundary —
it is simply the period during which amendments are frequent, and that shows up in the log
without anyone having to declare it.

## Who chooses the mode

Not us, at design time. The factory proposes and the researcher confirms — but *when* and
*how* it asks matters, because "which rigor mode do you want?" is a bad question to put to
someone who has not started yet. They do not know. They will pick wrong, and either drown
in PRISMA tax or discover at write-up that half the record is missing.

So the factory **infers a default, states its reasoning, and offers the override**, at the
end of Stage 00 when it has actually seen the question:

```
Proposed rigor: exploratory
  You described this as "background for a grant introduction, ~2 weeks".
  That reads as a landscape scan, not a publishable review.

  exploratory   single-pass screening, no appraisal        <- proposed
  pilot         dual screening on a sample, κ advisory
  systematic    full PRISMA, dual screening, GRADE

  This is reversible: `rf promote --to <mode>` later reports exactly
  what extra work the corpus would need. Nothing you record now is wasted.
```

The last line is the point. Because recording is mode-independent, the choice is cheap and
reversible, so it can be asked lightly instead of ceremonially.

### The general rule for when the factory asks

> **Ask when the answer changes what gets recorded. Decide when it only changes convenience.**

| Ask the researcher | Decide internally |
| --- | --- |
| Rigor mode | Which PDF extractor to route to |
| Eligibility criteria | Dedup match thresholds |
| Non-goals / scope boundaries | Wiki page layout |
| Whether a borderline record is in | Retry and rate-limit policy |
| Whether an amendment is semantic | ID and hash scheme |

A factory that asks about everything is just a conversation with extra steps. A factory
that asks about nothing has quietly made the researcher's methodological decisions for
them and hidden them in code. The line above is where the boundary sits.

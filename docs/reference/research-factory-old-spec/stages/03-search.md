# Stage 03 — Search

> Executes the protocol's strategy **unchanged**, archives every response verbatim,
> deduplicates, and produces the corpus. Deterministic throughout: no stage has less
> business making judgments than this one.

## Contract

| | |
| --- | --- |
| **INPUT** | `P@<sha>` and its search strategy; the Stage 01 seed set |
| **ACTOR** | script only |
| **OUTPUT** | `02-search/runs/<run-id>/`, `03-corpus/works/`, `03-corpus/dedup-map.yaml` |
| **GATE** | `rf gate 03` |
| **STANDARD** | PRISMA 2020 identification counts; PRISMA-S items 4–16 |

## The prohibition

> **The search returns what the query returns.**

No relevance filtering, no ranking, no "top 500 most relevant", no quiet truncation. If the
protocol's query matches 1,840 records, the corpus gets 1,840 records.

This is the sharpest instance of *scripts never make judgments*. Every one of these APIs will
happily sort by relevance and hand back a convenient subset — and accepting it substitutes
**the source's** notion of relevance for **your protocol's**, at the one point in the pipeline
where no decision is supposed to be happening. The result is unreproducible (relevance
rankings change), undocumented (nothing records that it happened), and invisible downstream
(the corpus looks fine). Screening exists to make relevance judgments, with criteria, on the
record. Stage 03 exists to not.

## 1. Runs

Execution is a transaction with an identity.

```yaml
# 02-search/runs/R2026-09-11T09-14Z/run.yaml
run: R2026-09-11T09-14Z
protocol: P@d4e5f6
method: database              # database | citation-chase | seed-admission | hand-search
status: complete              # complete | partial | failed
sources:
  openalex:
    query_sent: "..."          # byte-identical to the protocol's, or this is a deviation
    reported_count: 1840       # what the API said it had
    retrieved_count: 1832      # what we actually got
    count_delta_reason: "8 records returned 404 on paging; ids recorded in gaps.yaml"
    raw: openalex.raw.jsonl
    raw_sha256: "3f9a..."
    pages: 19
    started: 2026-09-11T09:14:02Z
    finished: 2026-09-11T09:17:48Z
    status: complete
    tool_version: "rf/0.1.0 openalex-adapter/1"
```

**The executed query is recorded, not assumed.** A difference between `query_sent` and the
protocol's string is a deviation by construction — which is the entire reason the string was
written down in Stage 02 rather than composed here.

One transformation is authorised and must not read as a deviation: **partitioning** (§3). A
partitioned run sends several queries, none byte-identical to the protocol's. Identity is
therefore checked on the *base* query, with the partition facet and its values recorded
alongside:

```yaml
query_base: "..."             # byte-identical to the protocol's
partition: {facet: year, values: [2018, 2019, 2020, ...]}
```

The union of the partitions must be provably exhaustive over the base query's range — an
off-by-one in a year partition silently deletes a year of literature, and it is the kind of
error that looks like a smaller field rather than a broken search.

## 2. Archive raw before parsing

Raw payloads are written to disk and hashed **before** any parsing happens.

Parsing is a derivation and can be redone. An API response cannot be re-obtained: records get
retracted, re-indexed, re-classified, and schemas change without notice. If the parser breaks
next year, an archived payload is a bug; an unarchived one is a lost corpus.

This also makes `rf replay` meaningful — a diff against the live API is only interpretable if
you still have what the API said the first time.

## 3. Count drift and the pagination cap

Two mismatches are routine and must be recorded rather than smoothed over:

**Reported vs. retrieved.** The API claims 1,840 and yields 1,832. Both numbers are stored,
with a reason. Silently reporting the number you got is how a corpus becomes unreproducible
in a way nobody can see.

**Deep-pagination caps.** Most APIs refuse to page beyond some depth (commonly 10,000). A
query exceeding the cap is *truncated by the source*, and the truncation is invisible — you
get a full-looking final page.

The response is to **split the query, never to truncate it**: partition by year (or venue, or
another orthogonal facet) until every partition sits under the cap, then union the results.
The partitioning is recorded as part of the strategy, because a reader reproducing the search
needs it. Accepting the cap would be relevance-truncation wearing a different hat.

## 4. Partial runs are first-class

Rate limits, timeouts, and network failures are normal, and a run that dies halfway **must not
produce a corpus that looks complete.**

- Per-source `status`, not just per-run.
- A partial source records where it stopped, precisely enough to resume.
- **Resume, do not restart.** Re-running from zero against a mutating index double-counts some
  records and silently loses others, and the dedup map will hide the evidence.
- `rf gate 03` blocks on any `partial` source without either a completed resume or a written
  waiver.

Politeness is configured, not improvised: OpenAlex and Crossref polite-pool identification,
arXiv's request delay, per-source concurrency caps. An adapter that gets the project
rate-limited has cost more than it saved.

## 5. Deduplication

The cascade from `DESIGN.md`, highest confidence first — DOI, then source-native IDs, then
normalised title + first author + year, then title trigram similarity ≥ 0.92 within ±1 year. The threshold is high on purpose: it is the
knob that trades false merges against false splits, and it is set where it is because of the
asymmetry below.

Merges are **reversible**. `dedup-map.yaml` records what was absorbed into what and on which
rule, so a bad merge can be undone without re-running the search.

Two error directions, with different costs:

| | Cause | Detection | Cost |
| --- | --- | --- | --- |
| **False merge** | two distinct papers unified | a seed vanishes; author lists conflict | a paper is silently deleted from the review — the worse error |
| **False split** | one paper kept twice | a seed appears twice; near-identical titles survive | inflated counts; one record may be screened twice with different verdicts |

False merges are the dangerous ones because nothing downstream can detect them — the corpus
is simply missing a paper and says nothing. So the threshold is deliberately conservative:
**prefer a false split**, which screening will notice, over a false merge, which it will not.

### Preprint and published versions

The common case, and it is a merge with structure rather than a plain duplicate. The published
version becomes the primary record; the preprint is retained with `supersedes`, because the
preprint may carry results the published version dropped, and because the citation trail of
the field often points at the preprint.

## 6. The seed check

Stage 01 made a promise; Stage 03 settles it.

```
$ rf seeds --check
SEED01  retrieved  openalex, semanticscholar
SEED02  retrieved  openalex
SEED03  retrieved  arxiv                        <- only source; arxiv was load-bearing
SEED04  MISSED     waiver: "Indexed under 'vessel wall' only; unreachable by topic search.
                            Admitted via citation chase in R2026-09-12T11-02Z."
5/6 positive seeds retrieved · 1 waived · 0 unexplained
```

A waiver is a **promise, not a dismissal**, and it is discharged in two steps. At run time the
seed is recorded as `waived` with the planned admission route; at closure, `rf gate 03 --closed`
verifies the admission actually happened and names the run that did it. A waiver still
outstanding at closure is an unretrieved seed with a story attached, and fails.

An unexplained missed seed fails the per-run gate in `pilot` and `systematic`. This is the check
that catches a search which looked fine and wasn't, and it works precisely because the seeds were
committed before the strategy was final.

## 7. Supplementary searches — the stage is re-enterable

PRISMA's "records identified via other methods" are not an afterthought; they are usually
where the best papers come from. But most of them cannot be found until Stage 04 has produced
included studies, so Stage 03 runs more than once:

| Pass | `method` | When |
| --- | --- | --- |
| Database search | `database` | now, from `P@sha` |
| Backward chase | `citation-chase` | after Stage 04 — references of included works |
| Forward chase | `citation-chase` | after Stage 04 — works citing included works |
| Seed admission | `seed-admission` | for waived seeds, with the Stage 01 reason attached |
| Hand search | `hand-search` | specific venues, conference proceedings, a colleague's list |

**Dedup runs across the corpus, not within a run.** A citation chase re-finds records the
database search already had — that is normal and is not a finding. Such a record gains a second
provenance entry and is counted once, under the pass that found it *first*. A supplementary
pass's PRISMA contribution is therefore its **new-after-dedup** count, never its raw yield;
reporting the raw yield would inflate "identified via other methods" with records the database
search already had.

Every pass is its own run with its own provenance, and PRISMA counts them separately — which is
exactly what the flow diagram asks for. Records entering by these routes are marked, so a
reader can see how much of the review the database search actually found. When that fraction
is low, it is a finding about the search, and it belongs in the report.

## 8. Replay

```
$ rf replay --from 03
R2026-09-11T09-14Z re-executed against live sources:
  + 14 new records        (indexed since the original run)
  - 2 records gone        (1 retracted, 1 re-indexed under a new id)
  ~ 31 metadata changed   (28 cosmetic, 3 affecting eligibility fields)
```

The point is not that the corpus must be stable — it will not be. The point is that
instability becomes **an artifact with a date** instead of a silent difference between what
you reported and what a reader finds. Retractions need a route rather than a mention. A retracted record is never deleted: it is
flagged `retracted` with the notice date and source, kept in the corpus, and — if it was
*included* — raised as a finding for Stage 08, because a review whose conclusion rested on a
retracted study has something to say about that. Quietly dropping it would change the
conclusion while leaving the trace looking untouched.

## Two different questions: is this run sound, is the search closed

Stage 03 is re-enterable, so `gate 03` cannot mean "the search is finished" — the citation
chase has not happened yet, and cannot until Stage 04 exists. The two conditions are
separated:

| | `rf gate 03 --run <id>` | `rf gate 03 --closed` |
| --- | --- | --- |
| Asks | was *this run* executed and recorded soundly? | is the search complete? |
| When | after every pass | once, after supplementary passes |
| Blocks | the run entering the corpus | Stage 08 synthesis, and final PRISMA counts |

PRISMA identification numbers are **provisional until closure**, and `rf prisma` labels them
so. A flow diagram produced mid-search is a working figure, not a result.

## Gate 03

| Check | exploratory | pilot | systematic |
| --- | --- | --- | --- |
| run sealed with per-source status | ✓ | ✓ | ✓ |
| `query_sent` byte-identical to protocol, or deviation logged | ✓ | ✓ | ✓ |
| raw payload archived and hashed per source | ✓ | ✓ | ✓ |
| reported vs retrieved counts recorded; delta explained | warn | ✓ | ✓ |
| no source `partial` without resume or waiver | warn | ✓ | ✓ |
| pagination-cap partitioning recorded where used | ✓ | ✓ | ✓ |
| every `Work` has ≥1 provenance entry | ✓ | ✓ | ✓ |
| `dedup-map.yaml` written and reversible | ✓ | ✓ | ✓ |
| unexplained missed seeds | warn | 0 | 0 |
| PRISMA identification counts derivable from state | warn | ✓ | ✓ |

## Failure modes

| Failure | Detection | Escape |
| --- | --- | --- |
| Rate-limited mid-run | source `partial` | resume from recorded position; never restart |
| Counts differ between two runs of the same query | replay diff | record both. Re-running until the numbers agree is search p-hacking |
| API schema changed; parser fails | parse error, raw intact | fix the adapter and re-parse the archive — no re-fetch needed |
| Query exceeds deep-pagination cap | `retrieved_count` pinned at a round number | partition the query; never accept the truncation |
| False merge | a seed disappears; conflicting author lists | reverse via `dedup-map.yaml`; tighten the rule that fired |
| False split | a seed appears twice | merge and record; cheaper than the alternative, by design |
| Source silently returns relevance-ranked subset | `retrieved_count` ≪ `reported_count` with no paging error | adapter bug — the adapter must request exhaustive paging explicitly |
| Adapter invents a `Work` with no provenance | construction-time invariant | not a failure mode; the model refuses to build it |

## Handoff to Stage 04

Stage 04 receives every record in `03-corpus/works/` with status `unscreened`, plus the
criteria from the protocol version the run cited. Records admitted by supplementary methods
enter screening on identical terms — how a record was found is provenance, never a reason to
treat it more gently.

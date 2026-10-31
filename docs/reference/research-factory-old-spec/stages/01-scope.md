# Stage 01 — Scope probe

> Cheaply establishes that the question is **searchable** before any protocol is committed
> to. Validates candidate queries against papers you already know, harvests the field's real
> vocabulary, and estimates what screening will cost.

## Contract

| | |
| --- | --- |
| **INPUT** | `Q@<sha>`, its `open:` slots, its non-goals (`NG*`) |
| **ACTOR** | script (retrieval, counting, recall) + agent (term grouping, precision sampling) |
| **OUTPUT** | `01-scope/{seeds.yaml, probes/, vocabulary.yaml, report.md}` |
| **GATE** | `rf gate 01` |
| **STANDARD** | Cochrane MECIR C34–C38 (search development); PRISMA-S item 3 (how the strategy was developed) |

## Why this stage exists

Freezing a protocol against an unprobed question is the most expensive mistake in evidence
synthesis, and it fails in both directions: a query returning 12,000 records commits you to
weeks of screening you did not budget, and one returning 9 commits you to a review with
nothing to say. Both are discoverable in twenty minutes.

The deeper problem is vocabulary. **You do not know the terms a field uses until you look.**
A methodologically perfect protocol built on the wrong nouns retrieves the wrong literature,
and nothing downstream can detect it — screening will faithfully process a biased sample and
PRISMA will report clean numbers about the wrong corpus. This is the one failure the
traceability chain cannot catch, because everything *inside* the chain is consistent. It has
to be caught here.

## The seed set — the central mechanism

Before running anything, the researcher names papers they already know belong in scope.

> **A query that fails to retrieve a paper you know is in scope is a broken query.**

This is known-item testing, and it is how professional information specialists actually build
searches. It converts "does this query look reasonable?" — unanswerable — into a measured
recall against a known target.

```yaml
# 01-scope/seeds.yaml
seeds:
  - id: SEED01
    cite: "Zhou et al. 2023, Med Image Anal"
    doi: 10.1016/j.media.2023.xxxxx
    resolved: rf:zhou2023-coronary-ssl
    why: "The paper that prompted the question."
  - id: SEED02
    cite: "Ronneberger 2015"
    doi: 10.1007/978-3-319-24574-4_28
    resolved: rf:ronneberger2015-unet
    why: "Boundary case — should be OUT. Tests that the query is not simply 'segmentation'."
```

Two details that matter:

- **Include negative seeds.** Papers that a naive query would catch and that you do *not*
  want. They measure precision the way positive seeds measure recall, and they are usually
  more informative, because over-broad is the more common failure.
- **Sources for seeds when memory is thin:** the reference list of the most recent review in
  the area, your own citations, or a single well-known paper's "cited by" list. Three is a
  workable floor; five is better.

## Procedure

### 1. Resolve the seeds

Script. DOI → `Work`, or title match with confirmation. An unresolvable seed is itself a
finding: if a paper you know exists is not in OpenAlex or Semantic Scholar, that source
cannot be your only backbone.

### 2. Draft candidate queries

Agent, from the Stage 00 slots. One query per candidate strategy — typically a narrow one
and a broad one, so the yield curve between them is visible.

Queries are built as **term blocks joined by AND, each block a synonym set joined by OR**,
with each block traceable to a slot:

```yaml
# 01-scope/probes/PRB01.yaml
probe: PRB01
question: Q@a1b2c3d4
blocks:
  - slot: Task
    terms: ["coronary", "CTA", "CCTA", "coronary computed tomography angiograph*"]
  - slot: Method
    terms: ["self-supervised", "SSL", "pretrain*", "foundation model", "contrastive"]
  - slot: Task
    terms: ["segment*", "lumen", "plaque", "stenosis"]
```

Limits — publication years, language, document type — are declared here, each with a
justification. PRISMA-S requires them reported, and they are scoping decisions rather than
protocol decisions: a year cut-off chosen *after* seeing the counts is a different act from one
chosen because the technique did not exist before then. Only the second is defensible, and the
difference is visible only if the limit is recorded at the moment it is set.

The block-to-slot mapping is not decoration. It is what lets Stage 02 justify each criterion,
and what makes an amendment traceable: change a slot, and `rf restage` knows which query
blocks are implicated.

### 3. Run the probe — metadata only

Script. Deliberately cheap: **metadata only, no full text, no PDFs**, capped per source. The
probe must cost seconds, or it will not be re-run, and a probe you will not re-run is not a
probe.

Record per source, per PRISMA-S: exact string, platform, filters, date, count.

### 4. Measure seed recall

```
seed_recall = positive seeds retrieved / positive seeds total
```

Recall is measured **per source and pooled**. The distinction drives source selection: a
strategy can reach pooled recall 1.0 while every individual source sits at 0.4, which tells you
the sources are complementary and all of them are needed. Pooled recall alone hides that.

Recall below 1.0 is the actionable signal. Inspect what the missed seed says — its MeSH
terms, its author keywords, its title — and you will usually find a synonym block you did not
know existed. Add it, re-run, repeat. This converges in two or three iterations.

**Negative seeds retrieved** is the precision counterpart, and is expected to be non-zero;
it becomes an exclusion criterion in Stage 02 rather than a query change.

### 5. Harvest vocabulary

Script gathers, agent groups. From the seed works and the probe's top results: MeSH
descriptors, author keywords, frequent title/abstract n-grams, and the terms used by the
seeds' citing papers.

The agent groups these into candidate synonym blocks per slot, and this is what **resolves
the `open:` slots** from Stage 00 — empirically, from what the field says, rather than by
the agent guessing.

### 6. Estimate the screening burden

Take a random sample of 25 records from the largest probe. The agent screens them against
the Stage 00 **non-goals as proto-criteria** — which is what the `NG*` IDs were for, and
resolves the apparent circularity of needing criteria before Stage 02 has written any.

```
expected_includes ≈ n_records × sampled_precision
screening_hours   ≈ n_records × 30s   (title/abstract, dual pass)
```

Non-goals alone cannot do this. They are exclusion-only, and a record that violates no non-goal
is not thereby in scope. The proto-criterion is therefore two-sided: **provisionally included**
means plausibly matching every *filled* slot and violating no `NG*`. Open slots are ignored in
this test — that is what makes it provisional, and why the result is a bound rather than a
measurement.

A number stated in hours before commitment is worth more than any amount of methodological care
afterwards. The 30s/record figure is a prior, not a measurement; it is replaced by the observed
rate as soon as Stage 04 has screened anything.

### 7. Report and route

One of three outcomes, and the stage must name which:

| Outcome | Trigger | Action |
| --- | --- | --- |
| **Proceed** | recall ≥ threshold, counts workable | resolved slots written back; go to Stage 02 |
| **Amend** | counts too large or too small; slots still open | return to Stage 00; new `Q@v2` records why |
| **Reframe** | no query achieves recall on the seeds | the question is not answerable by topic search — consider citation chasing, or a narrative review |

## Competing candidate questions — resolving the Stage 00 open item

Stage 00 emits exactly one committed question, but Stage 01 is where alternatives are
allowed to compete. Candidates live here as probes against a **scratch** question ID
(`Q@draft-<n>`), never as committed versions:

- probing a candidate is cheap and leaves no trace in the corpus;
- only the survivor is written back to Stage 00 and hashed as a real `Q@<sha>`;
- the losers are retained in `report.md` with the counts that killed them.

This keeps the trace clean — one question per project — while recording that alternatives
were considered and *why they were rejected*, which is the part a reader actually wants.

## Quarantine — probe records do not enter the corpus

**Nothing retrieved during Stage 01 becomes a corpus record.** Probe results live in
`01-scope/` and are deleted or ignored by Stage 03.

The reason is PRISMA arithmetic. Records "identified" in the flow diagram must come from the
executed search, run under the committed protocol. Letting exploratory hits leak in produces
a corpus that no re-run can reproduce — the exact failure `rf replay` exists to detect.

Resolving a seed does create a `Work`, so it needs a home that is not the corpus: seeds live in
`01-scope/seeds/`, and are copied into `03-corpus/` only if the executed search retrieves them
independently. The seed set is otherwise tracked rather than admitted:

> **A seed that the Stage 03 search fails to retrieve must be explained.**

Either the search is fixed, or the seed enters through PRISMA 2020's "identified via other
methods" route with a written reason. Silently dropping a paper you knew about is the
failure mode this catches, and it is a common one.

## Gate 01

| Check | exploratory | pilot | systematic |
| --- | --- | --- | --- |
| positive seeds resolved | ≥3 | ≥3 | ≥5 |
| negative seeds present | warn | ≥1 | ≥2 |
| best probe seed recall | ≥0.6 | ≥0.8 | 1.0 *or waived* |
| every unretrieved seed carries an `unreachable:` reason | — | ✓ | ✓ |
| date / language / document-type limits declared | ✓ | ✓ | ✓ |
| every query block names a slot | ✓ | ✓ | ✓ |
| per-source counts recorded (PRISMA-S fields) | ✓ | ✓ | ✓ |
| every Stage 00 `open:` slot resolved or deferred with reason | ✓ | ✓ | ✓ |
| sampled precision + expected burden stated | warn | ✓ | ✓ |
| routing outcome declared | ✓ | ✓ | ✓ |

`systematic` demands recall 1.0 because a systematic review that provably misses a known paper
is not one — but the requirement is satisfiable two ways, and that is deliberate. Either the
query retrieves the seed, or the seed carries a written `unreachable:` justification and a plan
to admit it by citation chasing. A gate passable only by retrieval is a gate that rewards
quietly deleting inconvenient seeds, which is worse than one that can be waived in writing.

`exploratory` accepts 0.6 because a landscape scan tolerates gaps it has declared.

## Failure modes

| Failure | Detection | Escape |
| --- | --- | --- |
| No seeds — genuinely new area | researcher can name none | harvest from the newest adjacent review's reference list; if still none, record `seeds: none` with a reason — the search is weaker and the report must say so |
| Recall stuck below 1.0 | a seed resists every term block | it is usually terminologically distant. Accept, document, and plan citation chasing in Stage 03 — some papers are genuinely unreachable by topic search |
| Counts explode (>10k) | probe counts | return to Stage 00; tighten a slot, not the query — tightening only the query decouples it from the question |
| Counts collapse (<15) | probe counts | widen a slot, or accept that the honest output is a narrative review |
| Probe becomes a mini-review | agent starts reading and summarising results | hard-capped: metadata only, sample of 25, no full text |
| Vocabulary harvest returns generic terms | top n-grams are "method", "results", "deep learning" | expected; rank terms by their frequency in the seeds *relative to* their frequency in a random sample of the broad probe — a term common in both is a field-wide word, not a discriminator |

## Handoff to Stage 02

Stage 02 receives the surviving probe as its draft search strategy, the harvested vocabulary
as its synonym blocks, the per-source counts as the basis for source selection, and the
negative seeds as the first draft of the exclusion criteria.

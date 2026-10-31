# The Workflow

The stage contracts describe artifacts and gates. This describes **what it is like to run a
review** — the command sequence, where the factory stops and asks, and what you actually
touch with your hands.

Design constraint throughout: **everything is a file in the repo, edited in VS Code.** No
web app, no database, no separate UI. A review is a directory you can diff, branch and
share, and the tooling never becomes a thing you have to be running.

## The session at a glance

```
rf init coronary-ssl                  # 1  a project
rf frame                              # 2  describe the idea, refine it      [you + agent]
rf probe                              # 3  is it searchable? what vocabulary? [agent + net]
rf protocol                           # 4  criteria, sources, strategy        [you + agent]
rf search --run                       # 5  run the study                      [script]
rf screen --stage title-abstract      # 6  filter by title and abstract       [agent ×2]
rf review                             # 7  refilter manually                  [YOU]
rf fulltext --fetch                   # 8  acquire the survivors              [script]
rf screen --stage full-text           # 9  filter again, on full text
rf review                             # 10 again, on what disagrees
rf extract                            # 11 read the papers, build the notes   [agent + you]
rf wiki build                         # 12 concept pages, contradictions
rf ask "..."                          # 13 cited answers from the corpus
rf export --format pdf                # 14 the review as a document
rf prisma                             # ∞  the flow diagram, any time
```

Steps 2, 4, 7, 10 and 11 need you. Everything else runs unattended. The sequence is not
rigid — `rf status` always says what is stale and what is next.

---

## 1–2 · Describe the idea, refine it

```
$ rf init coronary-ssl && rf frame
```

`rf frame` is a bounded interview — **five questions, hard cap**. It never asks what you
already said, and anything still unknown becomes an `open:` slot for the probe to resolve
rather than a sixth question. It ends by quoting your own words back:

```
You said: "i want to know if self-supervised pretraining is actually worth it
           for coronary CTA segmentation or if it's just hype"

Framing: TDMBM (method review)
  Task      lumen/plaque segmentation on coronary CTA
  Data      open -> resolve in probe
  Method    self-supervised or foundation-model pretraining
  Baseline  fully supervised, same architecture
  Metric    Dice, or stenosis agreement

Non-goals
  NG01  phantom-only validation, no in-vivo cohort
  NG02  non-coronary vascular beds
  NG03  no supervised baseline reported

Proposed rigor: pilot    (reversible — `rf promote` later reports the gap)

Written Q@a1b2c3d4.
```

You can re-run `rf frame` any time. It versions rather than overwrites.

## 3 · Probe — before committing to anything

```
$ rf probe --seed 10.1016/j.media.2023.12345 --seed 2209.14566 --seed-negative 2301.99999
```

You name papers you already know belong. The probe drafts candidate queries, runs them
metadata-only, and reports:

```
PRB01 (narrow)   openalex 412 · arxiv 88 · pubmed 12      seed recall 4/6
PRB02 (broad)    openalex 3140 · arxiv 210 · pubmed 61    seed recall 6/6

SEED03 missed by PRB01 — indexed as "vessel wall", not "coronary".
  suggested block: Task += ["vessel wall", "arterial wall"]

Sampled precision (25 records, PRB02): 0.19
  -> expect ~600 includes, ~26h of dual title/abstract screening
```

That last line is the point of the whole stage: **a cost in hours, before you commit.**
If it says 26 hours and you have a weekend, narrow the question now, not after screening
400 records.

## 4 · Protocol

```
$ rf protocol
```

The agent drafts criteria from your slots and non-goals; you confirm them one at a time.
This is the most expensive conversation in the workflow and the one worth having — every
criterion here prevents a category of disagreement later.

```
EX03  ← NG01
  "Validation on phantom or simulated data only, with no in-vivo cohort."
  rule: Does the paper report results on data from living subjects?
  applies_at: full-text          (cannot be judged from an abstract)
  priority: 3
  worked example: excludes SEED04 ✓

  [a]ccept  [e]dit  [d]rop  [s]tage-change
```

Criteria are not frozen. Amend any time; `rf restage` tells you what it invalidates.

## 5 · Run the study

```
$ rf search --run
arxiv       88/88     complete   3 pages   12.4s
openalex    3140/3140 complete   32 pages  41.0s
pubmed      61/61     complete   1 page    2.1s
dedup       3289 -> 2904   (385 merged, map written)
seeds       6/6 retrieved
```

Unattended. Raw responses are archived verbatim before parsing, so a parser fix next year
never means re-running the search.

## 6 · Filter by title and abstract

```
$ rf screen --stage title-abstract
pass A  2904 records  ████████████ done
pass B  2904 records  ████████████ done

include     412  (both passes agree)
exclude    2298  (both passes agree)
--------------------------------
disagree    164
unsure       30
            194 records need you  (6.7%)

calibration  sensitivity 0.95  specificity 0.81   PASS
agreement    overall κ = 0.79
             lowest: EX03 κ = 0.44  ← 61% of disagreements
```

Note what happened: 2,904 records screened, **194 need a human**. That ratio is the entire
argument for dual screening — not that it is more rigorous in the abstract, but that it
tells you *which* 7% of records your criteria could not decide.

The κ line is a warning worth reading before touching the queue. `EX03` at 0.44 means the
criterion is ambiguous. Fixing the criterion may dissolve 100 of those 194 disagreements —
so **amend first, review second.** Reviewing 194 records to work around a broken criterion
is the expensive way to discover it.

---

## 7 · Refilter manually — the review worksheet

This is the part with no obvious answer, so the design is deliberate.

```
$ rf review
Wrote 04-screening/review/2026-09-14-title-abstract.md  (194 records)
Open it, fill in the verdicts, then: rf review --import
```

**The worksheet is a markdown file you edit in VS Code.** Not a TUI, not a web app. It
diffs, it survives, it needs no process running, and it works identically over SSH and in
Copilot. The criteria are repeated at the top so you never scroll away from them.

```markdown
## 12 / 194 · rf:kim2022-diffusion-adversarial-e4226e04

**Diffusion Adversarial Representation Learning for Self-supervised Vessel Segmentation**
Kim, Oh, Ye · 2022 · arXiv preprint · cs.CV, eess.IV

> We propose a diffusion-based adversarial framework for vessel segmentation without
> manual annotation. Experiments on X-ray coronary angiography and retinal fundus...

A  include  (high)   "SSL pretraining, coronary target, reports Dice vs supervised"
B  exclude  EX07     (low)   "X-ray angiography, not CTA"

⚠ disagreement · EX07 ← slot:Data  "Modality is CT angiography."

verdict:
reason:
```

Fill `verdict:` with `include` or `exclude EX07`, add a reason, save, import. Records you
leave blank stay in the queue; the import is idempotent, so you can do fifty today and the
rest on Thursday.

Three rules the worksheet enforces:

- **You only ever see what needs judgment.** Never the 2,710 records both passes agreed on.
  A queue that includes settled records is a queue nobody finishes.
- **Everything needed to decide is on screen.** Title, abstract, both verdicts, both
  reasons, the criterion and the question slot it descends from. If you have to open the
  PDF to decide at abstract stage, that is a `cannot-assess`, and the criterion belongs at
  full-text — the worksheet offers that as a verdict.
- **Your reason is not disposable.** It becomes a **worked example** on the criterion, so
  both passes apply it to every future record *and retroactively*, via `rf restage`. This
  is the mechanism that stops you answering the same borderline question forty times.

The last one is the design's answer to "refilter manually somehow": manual review is not
data entry, it is **teaching the protocol**, and the protocol is versioned.

## 8–10 · Full text, then filter again

```
$ rf fulltext --fetch
412 works sought
  pmc-xml       88   high
  arxiv-latex   64   high
  unpaywall     121  high
  local PDFs    9    high      (03-corpus/dropbox/)
  paywalled     130  NOT RETRIEVED -> reports-not-retrieved.md
```

The 130 are a PRISMA number ("reports not retrieved"), not a failure. `rf fulltext --report`
lists them with DOIs and links so you can pull what you have institutional access to and
drop the PDFs into the drop folder — re-run and they are absorbed.

Then `rf screen --stage full-text` and `rf review` again, on a much smaller queue.

## 11 · Read the papers

```
$ rf extract
```

The agent works through each included work and fills the note body: methods, data, results,
limitations, and **atomic claims with section locators**. You read the notes, not the PDFs —
and when a claim looks wrong, the locator takes you to the exact paragraph.

`03-corpus/works/<id>.md` is a normal markdown file. Edit it. Your edits survive re-runs;
that was built in at the storage layer.

## 12–13 · Wiki and answers

```
$ rf wiki build
$ rf ask "does SSL pretraining help most when labels are scarce?"
```

Answers cite claim IDs, which resolve to works and locators. The agent is required to say
**"the corpus does not support an answer"** when it does not — the single highest-value
behaviour in the system, and the easiest to lose.

## 14 · Export

```
$ rf export --format pdf        # the review, via pandoc
$ rf export --format bibtex     # or csl-json, ris
$ rf export --format prisma     # the flow diagram (mermaid or SVG)
$ rf export --format xlsx       # the evidence table
```

Markdown is the source of truth; PDF is a rendering. `pandoc` is the only external binary
the project needs, and only for this step — nothing upstream depends on it being installed.

---

## Where a human is actually required

| Step | Required? | Why |
| --- | --- | --- |
| `rf frame` | **yes** | only you know what you mean |
| `rf protocol` | **yes** | criteria are methodological commitments |
| `rf review` | **yes** | disagreements have no automatic resolution, by design |
| calibration labels | **yes** (~30) | the only measure of *correctness* rather than consistency |
| `rf extract` review | recommended | spot-check locators; the agent is good at this and not perfect |
| everything else | no | scripts, or agent work with a gate behind it |

Roughly: **a day of your attention per review**, concentrated in framing, criteria and one
or two review queues. The factory's job is to make sure that day is spent on the decisions
that actually need you.

## Build status

| | Command | State |
| --- | --- | --- |
| 1 | `rf init` | not built |
| 2 | `rf frame` | not built |
| 3 | `rf probe` | not built |
| 4 | `rf protocol` | not built |
| 5 | `rf search --run` | **arXiv + OpenAlex adapters and dedup built and live-tested**; pubmed and CLI wiring pending |
| 6 | `rf screen` | not built |
| 7 | `rf review` | not built |
| 8 | `rf fulltext` | not built |
| 11+ | extract / wiki / ask / export | not built |

Foundations done: deterministic ids, the `Work` model with its provenance invariant,
frontmatter storage with body preservation, the adapter contract, cross-source dedup with a
reversible merge map. 73 tests.

Verified live: a single query across arXiv and OpenAlex returned 101 records, which deduped
to 72 works — 29 duplicates removed, preprint/published pairs merged with `supersedes` chains
intact.

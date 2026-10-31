# Research Factory — Design

A pipeline that turns a fuzzy research goal into a defensible, citable, agent-queryable
knowledge base. Deterministic work is done by Python CLIs; judgment is done by an agent
following markdown SOPs ("skills"). Every intermediate state is a plain file on disk.

## 0. The governing principle

> **Scripts never make judgments. Agents never do bookkeeping.**

- Scripts do: fetching, ID resolution, deduplication, PDF/HTML→markdown, counting,
  link integrity, PRISMA arithmetic, file layout.
- Skills do: question framing, query design, inclusion/exclusion decisions, quality
  appraisal, claim extraction, synthesis.

Violations of this line are where these systems rot. An agent that counts records will
miscount; a script that decides relevance will be wrong silently. Every agent judgment
is written to disk with a criterion ID and a rationale, so it can be audited and replayed.

## 1. The unit of everything: `Work`

One model covers journal articles, preprints, blog posts, standards, theses, patents,
docs pages, talks, and datasets. Grey literature is not a second-class citizen — it is a
`Work` with a different `type` and a different appraisal path.

```yaml
id: rf:zhou2023-coronary-ssl-a1b2c3     # deterministic slug+hash; stable across re-runs
type: journal-article | preprint | conference-paper | blog-post | tech-report
    | documentation | thesis | patent | dataset | video | forum-post | standard
identifiers:
  doi: 10.xxxx/yyyy
  arxiv: 2301.01234
  pmid / pmcid / openalex / s2 / url / isbn: ...
title, abstract, language
authors: [{name, orcid, affiliation}]
venue: {name, publisher, volume, issue, pages}
dates: {published, updated, retrieved}

provenance:                              # PRISMA depends on this being complete
  - source: openalex
    query_id: Q03
    run: 2026-09-09T14:22Z
    raw: 02-search/runs/2026-09-09T14-22Z/openalex.raw.json#L1204
    
full_text:
  path: 03-corpus/fulltext/<id>/extracted.md
  method: pmc-xml | arxiv-latex | grobid | pymupdf | trafilatura | manual
  quality: high | partial | title-abstract-only
  license: cc-by | oa-green | publisher | local-copy

appraisal:
  peer_reviewed: true|false
  cited_by_count: 142
  aacods: {authority, accuracy, coverage, objectivity, date, significance}  # grey lit only

screening:
  title_abstract: {decision: include|exclude, criteria: [EX02], rationale: "...", at: ...}
  full_text:      {decision: include|exclude, criteria: [EX05], rationale: "...", at: ...}

relations:
  supersedes: [rf:zhou2022-...]         # preprint -> published
  cites / cited_by: [...]
```

**Storage = the note.** Each work is one file, `03-corpus/works/<id>.md`, with the above
as YAML frontmatter and the human/agent-readable extraction as the markdown body. The
record *is* the wiki note. Machines read the frontmatter; agents read the body. There is
no second copy to drift.

## 2. Source adapters

Every source implements the same interface and returns `Work` objects plus the raw payload:

```python
class Source(Protocol):
    name: str
    def search(self, query: Query, limit: int) -> Iterator[Work]: ...
    def fetch(self, ident: Identifier) -> Work | None: ...
    def fulltext(self, work: Work) -> FullText | None: ...
```

| Adapter | Role |
| --- | --- |
| `openalex` | Backbone: broadest coverage, citation graph, no key required |
| `semanticscholar` | Backbone: strong ML/CS coverage, TLDRs, references |
| `arxiv` | Preprints + LaTeX source (best-quality full text available anywhere) |
| `pubmed` / `pmc` | Biomedical metadata + open-access full-text XML |
| `crossref` | DOI truth, metadata repair |
| `unpaywall` | Legal OA full-text link discovery for a DOI |
| `dropfolder` | PDFs you already have legitimate access to |
| `url` | Anything you paste: blog, docs page, standard, preprint |
| `web` | Grey-literature discovery (deliberately last, always appraised) |

Adding a source = one file, no changes elsewhere. Full-text acquisition only ever follows
legal OA routes or files you supply; publisher paywalls are handled by you dropping the PDF.

## 3. Deduplication

The single most under-engineered step in most pipelines, and PRISMA requires the number.
Cascading match, highest confidence first:

1. DOI exact (normalized, lowercased, prefix-stripped)
2. arXiv / PMID / OpenAlex ID exact
3. Normalized title + first-author surname + year
4. Title trigram similarity ≥ 0.92 with year within ±1

Matches **merge** into one `Work` carrying the union of identifiers and *all* provenance
entries. Preprint→published pairs merge with `supersedes`. Every merge is written to
`dedup-map.yaml` so the count is reproducible and reversible.

## 4. Project layout

```
projects/<slug>/
  00-question/    question.md (versioned), framing.yaml (PICO/SPIDER)
  01-protocol/    protocol.md, criteria.yaml, queries.yaml,
                  protocol.lock (hash+timestamp), deviations.md
  02-search/      runs/<ts>/<source>.raw.json, search-log.yaml
  03-corpus/      works/<id>.md, dedup-map.yaml, fulltext/<id>/
  04-screening/   title-abstract.yaml, full-text.yaml
  05-wiki/        index.md, concepts/, claims/, by-theme/, by-method/, by-year/
  06-synthesis/   evidence-table.md, narrative.md, gaps.md
  prisma.md       # GENERATED, never hand-edited
```

The wiki is a **view layer**, not a copy: `concepts/` and `by-*/` pages link into
`03-corpus/works/`. Rebuildable from scratch at any time.

### The protocol lock

`01-protocol/protocol.lock` records a hash of the criteria and queries at freeze time.
Any later change is legal but must be recorded in `deviations.md` with a reason. This is
the difference between a systematic review and a search that got tuned until it agreed
with you.

## 5. The claim layer — why this beats a folder of PDFs

Per-work extraction produces **atomic claims**, each with a locator:

```yaml
# 05-wiki/claims/CLM-0042.md
statement: "Self-supervised pretraining on unlabeled CTA improved Dice by 4.1 pts
           over supervised-only baselines at 10% label fraction."
work: rf:zhou2023-coronary-ssl
locator: "§4.2, Table 3"
evidence: experimental | observational | theoretical | opinion | anecdote
strength: strong | moderate | weak
supports: [CLM-0011]
contradicts: [CLM-0038]
```

Concept pages aggregate claims across works and **surface disagreement explicitly**
instead of averaging it away. Every synthesized sentence traces to a claim ID, which
traces to a work ID plus a locator. That chain is the anti-hallucination spine, and it is
what lets `rf check` mechanically verify that nothing in the narrative is uncited.

## 6. Retrieval: agent-native, index-ready

No embeddings, no server. The agent navigates via `index.md`, tag frontmatter, concept
pages, and grep. This works today in Copilot and Claude Code, diffs cleanly in git, and
has zero rebuild step. The layout is designed so a local vector index can later be added
as a pure addition — `rf index build` writing `.rf/index.sqlite` — without moving a file.

## 7. Skills (portable markdown SOPs)

Each is harness-agnostic markdown: preconditions, procedure, the CLI commands to call,
the output contract, and failure modes. A thin generator emits Copilot
`.github/skills/<name>/SKILL.md` and Claude `.claude/skills/*` from the same source.

| Skill | Produces |
| --- | --- |
| `refine-question` | `question.md`, `framing.yaml` — sharpens scope, names what is *out* |
| `draft-protocol` | `criteria.yaml` with stable IDs (`IN01`, `EX03`), then freezes the lock |
| `design-queries` | per-source query strings, synonym/MeSH expansion, yield-tested |
| `screen-titles` | one logged decision per record, criterion ID mandatory |
| `screen-fulltext` | deeper pass; exclusions *must* name a reason |
| `appraise-grey` | AACODS appraisal for non-peer-reviewed works |
| `extract-work` | the note body: methods, data, results, limitations, claims |
| `build-wiki` | concept pages, cross-links, contradiction surfacing |
| `synthesize` | evidence tables, narrative, gap analysis — every sentence cited |
| `answer-from-wiki` | query-time: navigate, cite, and refuse when unsupported |
| `audit-trail` | reproducibility check + PRISMA review |

## 8. CLI surface

```
rf init <slug>              scaffold a project
rf search --run             execute queries.yaml against all sources, log raw payloads
rf dedup                    merge duplicates, write dedup-map.yaml
rf ingest <url|pdf|doi>     add one work by hand
rf fulltext --fetch         acquire + normalize full text for included works
rf status                   pipeline state: what is screened, extracted, stuck
rf prisma                   regenerate prisma.md from corpus state
rf wiki build               regenerate the view layer
rf check                    citation + link integrity; uncited claims; orphan works
rf export --format bibtex|csl|csv|docx
```

`rf prisma` derives every number from corpus state. No count is ever typed by a human or
an agent.

## 9. Known hard parts (ranked)

1. **Full-text extraction quality.** Everything downstream inherits it. arXiv LaTeX and
   PMC XML are excellent; PDF is a fight (GROBID > PyMuPDF for structure); blog HTML needs
   `trafilatura`. Tables and figure captions are where naive extraction fails worst.
2. **Screening consistency at scale.** An agent screening 800 abstracts drifts. Mitigation:
   fixed criteria IDs, a calibration set of ~30 human-labelled records scored before each
   run, and confidence flags that route borderline records to you.
3. **Dedup across preprint/published boundaries.** See §3.
4. **Grey-literature quality control.** Blogs have no peer review; AACODS is the guard,
   and grey claims must be visibly tagged as such wherever they surface.
5. **Provenance completeness.** If one adapter forgets to log provenance, PRISMA is wrong
   and you will not notice. Enforce in the model, not by convention.

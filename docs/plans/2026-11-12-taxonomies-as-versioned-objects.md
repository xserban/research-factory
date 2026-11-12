# Plan (design): taxonomies as declared, versioned objects (IDEA-50)

Date: 2026-11-12 · Status: design ruled (§8); no code · Branch:
`plan-taxonomies` (from `main` at 5bc9879) · Unblocks: IDEA-51, 52, 53, 55 (the taxonomy product),
64 · Related: reference layers (plan 2026-11-11-reference-layers; the layers themselves belong to
IDEA-57 and are not redesigned here) · Provisional decision number: 120 (fixed at landing)

## 1. Problem and evidence

The pilot's first taxonomy, `agentic-science-v0` (2026-11-09, `root/projects/agentic-science/
taxonomy.json`), was built by scripts outside the platform (`screeners/taxo_techniques.py`,
`taxo_fields.py`, `taxo_report.py`): quotes of `m-descriptors@3` pass A were matched against keyword
patterns, counts and sample quotes were shown on a page, and the researcher kept every proposed
category. The file records 8 dimensions and 69 categories (11 + `other` for technique and field,
9 + `other` for data, 7 + `other` for architecture, 3 + `other` for autonomy, 5 + `other` for human
role, 7 + `other` for evaluation, 8 + `other` for stages). Each category is a **name and a regular
expression only**: no definition, no inclusion cues, no example quotes, no cardinality, and no
`not stated` bucket. Nothing in the event log records it, its acceptance, or its version.

`m-classification@1` was then written by hand from it (5 of the 8 dimensions; autonomy, human role
and stages went to `m-mapping`). Its enums are slugs that do not match the taxonomy's names
(`multi-agent` for "multi-agent roles / collaboration / debate"), so the link between category and
enum value exists only in the agent's head. Its row key is `technique_primary` and its row anchor is
the anchor of `technique_primary`; the key therefore contains a quote location. Result on 35 dual
works: 14 rows aligned, 42 unmatched, agreement 0.576 (`screeners/agreement-m-classification.txt`).
The same work's two passes cite different sentences for the same technique and so produce two
different row keys.

## 2. Object model

### 2.1 A taxonomy version

A **taxonomy** is a named, registered specification (`t-` namespace, as miners use `m-`), versioned
by an integer and identified by a digest. One version holds:

| Part | Content | In the digest |
|---|---|---|
| `name`, `version` | `t-agentic-science`, 1 | yes |
| `dimensions[]` | ordered; each below | yes |
| `rationale` | why the version exists; the proposals it accepts or rejects (§5) | no (prose) |

A **dimension**:

| Field | Meaning | In the digest |
|---|---|---|
| `id` | stable slug, the identity rows cite (`technique`) | yes |
| `title`, `question` | display title; the question the dimension answers ("How does the system work?") | `question` yes, `title` no |
| `cardinality` | `single` (exactly one category or residual per work) or `multi` (one or more, optional `max`) | yes |
| `applies_to_layers` | the dimension-zero layers it is mined for (§4); empty = all | yes |
| `read_scope` | where its facts may sit: heading patterns or `whole-text` (IDEA-64 item 1, per dimension) | yes |
| `categories[]` | below | yes |
| `residuals` | always `other` and `not-stated` (§3.3); optionally `not-applicable` if ruled | yes |

A **category**:

| Field | Meaning | In the digest |
|---|---|---|
| `id` | stable slug within the dimension; full id `technique/multi-agent` | yes |
| `name` | display name | no (a rename alone changes nothing, §5) |
| `definition` | one or two sentences; what the classifier applies | yes |
| `include_cues`, `exclude_cues` | short phrases that signal or rule out the category | yes |
| `examples[]` | verbatim quote, work id, anchor; never a work of a calibration sample | yes |
| `pattern` | keyword regex used only to **count and propose** (§5 step 2) | no: it never classifies |
| `lineage` | `split_from`, `merged_from`, `renamed_from`: category ids of the previous version | no (computed diff is authoritative; lineage is the researcher's statement, checked against it) |

**Digest.** `sha256(canonical_json(strip_prose(spec)))[:16]`, the same rule as `miner_digest`
(`mining/compile.py`). In addition, each category has its own **category digest** (definition, cues,
examples) so that a version diff names exactly which categories changed (§5 step 6).

**Versioning.** Version N+1 is registered whole; the platform computes the diff to N (added,
removed, redefined, renamed, split, merged categories; changed cardinality or read scope). A
registration whose digest equals an existing version writes nothing (first write wins, as miners).

### 2.2 Deriving the classification miner

`derive_miner(taxonomy, version, dimensions, selector, regime) -> MinerSpec` is pure and
deterministic, so the miner is a projection of the taxonomy, never edited by hand:

- name `m-<taxonomy>-<group>` (for example `m-agentic-science-core`), version = a counter of
  derivations, `taxonomy` reference `t-agentic-science@1` and its digest in the spec;
- one row per (work, assigned category); fields: `category` (enum of full ids of the chosen
  dimensions plus `<dim>/other` and `<dim>/not-stated`), `quote` (`QuoteKind`, the evidence),
  `described_as` (`QuoteKind`, required when the category is `other`; forbidden otherwise, by a
  conditional);
- `row_key_fields = ("category",)`, `row_anchor_fields = ()`: no anchor in the key (§3.2);
- the definitions, cues and examples go into the task content the agent is served (the procedure
  text), not into the enum;
- close checks (new): every applicable dimension has at least one row; a `single` dimension has
  exactly one; `not-stated` excludes any other row of its dimension.

### 2.3 Example from `agentic-science-v0`

The v0 dimension `autonomy`, in the proposed form. The definitions and cues below are **drafts for
illustration**; v0 has none, and the categories stay the researcher's (§7).

```json
{
  "id": "autonomy",
  "title": "Autonomy level",
  "question": "How much of the research loop does the system carry out without a human?",
  "cardinality": "single",
  "applies_to_layers": ["core", "applied"],
  "read_scope": {"headings": ["abstract", "introduction", "method", "system", "discussion"]},
  "categories": [
    {"id": "end-to-end", "name": "fully autonomous / end-to-end",
     "definition": "The system runs the stated research stages from goal to output without a human decision between them.",
     "include_cues": ["fully autonomous", "end-to-end", "without human intervention"],
     "exclude_cues": ["human approves", "human selects"],
     "examples": [],
     "pattern": "fully autonom|end-to-end|autonomously|without human|no human|without intervention"},
    {"id": "human-in-loop", "name": "human-in-the-loop / supervised", "definition": "…", "…": "…"},
    {"id": "assistive", "name": "assistive / co-scientist / copilot", "definition": "…", "…": "…"}
  ],
  "residuals": ["other", "not-stated"]
}
```

Rows of the derived miner for one work (multi-label dimension `technique`, single-label `autonomy`):

| work | category (row key) | quote (evidence; not compared) |
|---|---|---|
| rf:babaei2026-mail… | `technique/iterative-loop` | "This iterative process continues without human feedback until…" |
| rf:babaei2026-mail… | `technique/memory-skills` | "…" |
| rf:babaei2026-mail… | `autonomy/end-to-end` | "…without human feedback until the final hypothesis is selected." |
| rf:babaei2026-mail… | `evaluation/not-stated` | — (read scope recorded, §3.3) |

## 3. Open questions of the backlog, as options

### 3.1 (a) Protocol section or registered object

| Option | What | For | Against |
|---|---|---|---|
| A1 | A protocol section `taxonomy`, amended like criteria | One path (`amend_protocol`); hashed with the protocol | Every refinement round is a protocol amendment; not reusable across projects; an exploratory taxonomy needs a protocol first |
| **A2 (recommended)** | A registered object (`taxonomy.registered`, `t-` names, versions, digest) listed in the protocol as `taxonomies: [{name, version}]`, exactly as `miners` lists registered miners | Mirrors miners (`register_miner`, `MinerUse`, `miner_stale`); reusable and diffable across projects; a version is in the protocol hash only when listed, i.e. when used as evidence | One more protocol field (an amendment to list it) |
| A3 | Registered, never listed; only the derived miner is listed | No protocol schema change | The protocol hash does not name the taxonomy; the rigour note "part of the protocol hash when used as evidence" is met only indirectly through the miner's spec |

### 3.2 (b) Multi-label rows and the row key

Constraint from today: no anchor or quote may enter the key, because two passes citing different
sentences then never align.

| Option | Row shape | Key | For | Against |
|---|---|---|---|---|
| B1 | One row per (work, dimension), `primary` and `secondary` enum fields (today's `m-classification`) | the primary value | Few rows | Primary disagreement unmatches the whole row; secondaries compared as fields (0/5, 0/6 filled by both, IDEA-53) |
| **B2 (recommended)** | One row per (work, category) | `category` only; `row_anchor_fields = ()` | Alignment is set comparison per dimension; a category found by one pass only is a row present in one pass, reported per category; no new field kind | More rows; the platform must check cardinality at close (new check) |
| B3 | One row per work, a new "enum set" field kind with a quote per value | the work | Natural for per-work miners | New field kind through compile, verify, agreement and the index; largest change |

Under B2 the key is still salted with the conversion id (`pack_row_key`, `extraction/verify.py`);
both passes pin the same conversion, so this is harmless, but a re-conversion between passes would
unmatch every row. The report should name that cause rather than count row disagreements.

Primary versus secondary within a `multi` dimension, if the researcher wants it: an optional `rank`
enum field (`primary`, `secondary`) outside the key, compared separately. Recommendation: leave it
out of v1 (the set is the measure, IDEA-53 item 2).

Agreement under B2 (consistent with IDEA-53): per dimension, `single` dimensions by exact category;
`multi` dimensions by per-category presence (kappa per category) and per-work Jaccard; rows where
one pass says `not-stated` and the other a category are reported as completeness, not as
disagreement, if ruled so in §3.3.

### 3.3 (c) `not stated` versus `other`

| Bucket | Meaning | Evidence | Use |
|---|---|---|---|
| `other` | The paper states something about the dimension, and it fits no category | Quote required, plus `described_as` (the paper's own words) | Source of proposals for N+1 (§5) |
| `not-stated` | The text read says nothing about the dimension | No quote; the platform records the read scope (anchors served or `whole-text`) on the row; the agent may not quote "the nearest sentence" (IDEA-64 item 3) | Completeness statistic per dimension; never a proposal source |
| `not-applicable` (optional) | The dimension does not apply to this kind of paper | — | See options |

| Option | What |
|---|---|
| **C1 (recommended)** | Two judged buckets, `other` and `not-stated`; applicability **computed** from the work's layer (`applies_to_layers`, §4): a benchmark paper is never mined for `autonomy`, and reports show it as "not applicable (layer)" without a row |
| C2 | Three judged buckets, `not-applicable` chosen by the agent per work |
| C3 | Only `other`; absence is the lack of a row (today's behaviour; conflates "not read", "not stated" and "missed") |

A further distinction the platform already has: a work with no current conversion is "not read",
never `not-stated`.

### 3.4 (d) Embeddings that suggest clusters without deciding them

The platform already embeds offline with SPECTER2 (decision 116, `ranking.computed`), from supplied
weights, never calling a model.

| Option | What | For | Against |
|---|---|---|---|
| **D1 (recommended for v1)** | No embeddings; proposals come from keyword counts, the `other` bucket and disagreements | Nothing new to validate | Misses latent groupings |
| D2 | SPECTER2 on works (title and abstract), clustered | Weights and code exist | Clusters papers by topic, mixing dimensions; useful for `field` only |
| **D3 (recommended for v2)** | SPECTER2 on the descriptor quotes of one dimension (`m-descriptors` fields), clustered per dimension | Clusters what the dimension is about; same weights | Short texts are outside SPECTER2's training; to be checked on the pilot |

Whatever the option, rules: clustering is a computed event (`clusters.computed`: model, weights hash,
algorithm, parameters, seed, input set hash, assignments as a blob), shown as candidate groups with
the quotes nearest each centre and computed keywords; an agent may name a cluster only inside a
`taxonomy.change_proposed`; a cluster never assigns a category, never appears as a category count,
and never enters agreement.

### 3.5 (e) Lessons from the first spec

| Lesson | Design response | Status |
|---|---|---|
| A required quote field blocked a general-purpose paper (`field_of_science`, PaperClaw) | `not-stated` is a legal value of every dimension and is exempt from the quote rule; the registered-miner rule "at least one quote per record" becomes "per row whose value is not an absence value" (`evidence.absence_values`) | new (validate.py, close checks) |
| `selector.max_units` caps works, not paragraphs | The derivation never sets `max_units`; rename it `max_works` in the JSON form (old key read as an alias) and, if wanted, add `max_anchors_per_work` | new; option E2 below |
| An anchor in the row key unmatched passes | `row_anchor_fields = ()` for derived miners; `validate_miner` warns when a key field's anchor is also a row anchor | new check |
| Secondary labels were compared as fields | Sets per dimension (B2) | follows from B2 |
| `MINE_INSTRUCTIONS` says "leave out a field the document does not state", contradicting the absence rule (IDEA-64) | The derived miner's task content states the residual rule; the generic instruction yields to the spec when the spec declares `absence_values` | new (text) |
| Heading selectors omit reproducibility, appendix and data sections (IDEA-64) | `read_scope` per dimension, including `whole-text` | depends on IDEA-64's whole-text mode |
| Enum slugs differed from category names | Enum values are the category ids, generated; names are display only | follows from §2.2 |
| Keyword patterns tempted use as classification | Patterns are outside the digest and only count and propose | §2.1 |

E2 options: **E2a (recommended)** rename to `max_works` with alias, no paragraph cap; E2b keep the
name, document it, add `max_anchors_per_work`; E2c both.

## 4. The layer dimension ("dimension zero")

The reference-layers scheme (pilot scheme v3: core, benchmark, applied, adjacent, background,
off-topic; rings 0–5) classifies **cited items** by title. The researcher wants the same axis for
the **corpus works**, first, before more mining.

**How it fits.** Dimension zero is a dimension whose categories are **imported by reference** from
a recorded layer scheme (`source: {layer_scheme: 3}`): its category ids are the layer ids, its
definitions are the scheme's criteria, and the taxonomy copies nothing, so the layers stay under
IDEA-57 and the reference-layers plan. The digest includes the scheme version, so a new scheme
version is a new taxonomy version. Cardinality `single`.

**How it is assigned to corpus works.**

| Option | What | For | Against |
|---|---|---|---|
| **L1 (recommended)** | A derived miner for dimension zero only (`m-<taxonomy>-layer`), read scope abstract and introduction, two passes, quote per row | Existing machinery (mine_next, agreement, resolution, calibration); quotes as evidence; no new event type | Needs conversions (the included works have them) |
| L2 | Extend `reference_layer_record` to accept work ids | Same tool as the cited items | Changes `reference.layer_assigned`'s payload (the type that broke the other line, §6); title-only judging of works whose full text exists |
| L3 | Take the layer of the matching cited item | Free | Covers only cited works; a title-stage judgement; use as a cross-check, never as the assignment |

An included work placed in `adjacent`, `background` or `off-topic` contradicts its inclusion: it is
a finding for the researcher (a screening check), never an exclusion and never a skip of screening.

**The layer of a work.** It is the researcher's move if there is one (below), otherwise the
**final** dimension-zero row (agreed, or resolved by the researcher). Until one exists the work is
"layer pending" and receives no layer-filtered miner.

**Automatic and on-demand mining (ruled 2026-11-12).** Every listed miner runs automatically on
the works of **core** and **adjacent**. Works of every other layer (benchmark, applied, background,
off-topic) are mined **only on demand**, from the hub, for one work or for a whole layer. The
protocol's miner listing gains three optional fields (new):

- `MinerUse.layers`: the layers mined automatically (`[core, adjacent]` in the pilot);
- `MinerUse.on_demand`: true allows the researcher's requests to add works beyond those layers.
  The protocol declares the rule once; each request is a recorded act, not an amendment;
- `MinerUse.order`: `by-layer` serves works by ring, then work id (a priority, never a judgement).

A miner's population is therefore computed as: included works whose layer is in `layers`, plus
works named by live `mining.requested` events. Nothing is typed by an agent.

**On-demand requests.** `mining.requested` (human only): target either a list of work ids or a
layer; the miners (default: every miner the protocol lists with `on_demand`); an optional reason. A
layer request is resolved to its work ids when recorded, and the event stores both, so the request
is reproducible and a later move does not silently widen it; "mine this layer" again picks up works
moved in since. Requested works follow the miner's regime (two passes, dual sample, audit) like any
other. Reports separate automatic from requested works per layer: requested works are a selection
by the researcher, not a sample of their layer, and no per-layer statistic treats them as one.

**Moving a work to another layer.** `work.layer_set` (human only): work id, layer scheme version,
the new layer, a reason. The latest move wins over the miner's row and is shown as "moved by the
researcher" with the miner's layer beside it. Effects, all computed:

- moved **into** an automatic layer: the work enters the miners' population and the queue;
- moved **out of** one: its existing rows are kept and count as requested (nothing is lost or made
  stale); no further miners are served unless requested;
- every move is also a gold label for the dimension-zero miner (it feeds that miner's calibration
  and audit, as `miner.calibration_labelled` does), and the methods report counts the moves per pair
  of layers.

**Hub.** Both acts are allow-listed human POST acts under decision 119 (loopback, per-start token,
the local human principal, same services as the CLI): on a work, "mine this work" and "move to
layer"; on the layer view, "mine this layer". Requested works appear in the hub's work queue at a
stage `mining`, and **Process now** starts a mining run for them (stage tools `mine_next`,
`mine_record`, `document_read`; a declared model per pass; a cap on works per run). This is the
runner IDEA-51 item 1 asks for, served through the existing runner rather than the pilot's wave
scripts. CLI equivalents: `factory mine request (--work ID… | --layer L) [--miner M…]`,
`factory layers move WORK LAYER --reason R`.

**Depth.** Within the automatic layers every listed miner runs; there is no per-layer subset of
miners or dimensions in v1. Dimensions still skip layers they do not apply to (`applies_to_layers`,
§3.3); for an on-demand request this is what makes "mine this benchmark paper" skip autonomy.

## 5. The refinement loop, mapped to existing machinery

| Step | What | Existing machinery | New |
|---|---|---|---|
| 0 | Layer assigned (§4) | derived miner on `mine_next`/`mine_record`; agreement; `extraction.resolved` | `MinerUse.layers`, `on_demand`, `order`; `mining.requested`, `work.layer_set` |
| 1 | Descriptor miner quotes how papers describe each dimension | `m-descriptors` (registered miner) | — |
| 2 | Frequency and keyword coverage: per candidate pattern, works matched, works matching nothing, sample quotes | the logic of `taxo_report.py`, today a pilot script | a service `taxonomy_coverage(project, taxonomy, version)` (computed, no event) and a hub page; port of the script |
| 3 | The researcher accepts, renames, merges or adds; version N registered | — (today a JSON file and a page with local storage) | `taxonomy.registered` (human actor only); CLI `factory taxonomy register FILE`, `factory taxonomy diff A B` |
| 4 | Classification miner runs | `miner_register`, protocol listing, `mine_next`, `mine_record`, two passes, calibration (`draw_miner_calibration`, gold labels) | `derive_miner`; close checks of §2.2; absence values |
| 5 | Proposals for N+1 from `other` rows and disagreements | `mine_disagreements` lists disagreements | `taxonomy.change_proposed` (agent: kind add / split / merge / redefine / retire, the works and rows behind it, optional cluster id); MCP `taxonomy_propose`, `taxonomy_proposals` |
| 6 | Re-classify only works whose rules changed | stale units get a new task and are re-served (`services/extraction.py`, staleness by recording order, decision 50); `miner_stale` per miner | **value-level staleness**: `ExtractionStale.values` (rows whose `category` is in a set). Today a new miner version stales all rows (`extraction_stale`: pack version changed); for two miners derived from the same taxonomy the rule comes from the taxonomy diff instead |
| 7 | Reports: counts, agreement per category, audit sample per category, lineage | `extraction_agreement`, `extract_audit_sample`, site agreement pages | per-category grouping; lineage view from the diff |

Staleness rules from the diff (step 6):

| Change | Rows made stale |
|---|---|
| rename (name only) | none |
| redefine (definition, cues or examples) | rows carrying the category, and the dimension's `other` rows |
| add | the dimension's `other` rows, and rows of categories the researcher names as donors |
| split A → A1, A2 | rows carrying A |
| merge A, B → C | none re-read: an alias in the projection maps A and B to C, marked "carried"; the researcher may instead choose re-reading |
| remove | rows carrying it |
| cardinality changed | every row of the dimension |
| layer scheme version changed | dimension-zero rows of works whose layer's criteria changed; works whose layer changes then gain or lose miners by `MinerUse.layers` |

A re-served unit re-reads the whole work for the derived miner. Deriving one miner per group of
dimensions (rather than one for all) keeps re-reading proportional to what changed (ruling Q9).

Every acceptance or rejection of a proposal is recorded in version N+1's registration
(`accepts: [proposal ids]`, `rejects: [{id, reason}]`), so no separate decision event is needed.

## 6. Events and the shared pilot log

### 6.1 Event types the design needs

| Event | Actor | Status | Payload (summary) |
|---|---|---|---|
| `taxonomy.registered` | human only | **new type** | name, version, digest, spec blob, `accepts`, `rejects`; first write wins per version |
| `taxonomy.change_proposed` | agent | **new type** | taxonomy, base version, kind, target and new category drafts, evidence rows and works, optional cluster id, rationale; provenance (model, skill version, `input_blob`) |
| `mining.requested` | human only | **new type** | target works or layer (resolved work ids stored), miners, reason |
| `work.layer_set` | human only | **new type** | work id, layer scheme version, layer, reason |
| `clusters.computed` | system | **new type, later (D3)** | as `ranking.computed`, plus assignments blob |
| `miner.registered` | as today | existing | derived miners; spec blob gains `taxonomy` ref and `evidence.absence_values` (**blob schema change**) |
| `extraction.recorded`, `.closed`, `.resolved`, audit and calibration events | as today | existing | unchanged |
| `protocol.amended` / protocol recording | human | existing | `taxonomies` listing; `MinerUse.layers`, `on_demand`, `order`; `MinerStale.rule.values` (**payload schema changes**) |

So: four new types for v1, one later, and three changes to existing payloads or blobs. Counts,
coverage lists and diffs are computed, never events.

### 6.2 Why each of these breaks a code line that lacks it

- The reader refuses an unknown type as corruption (`events/reader.py`, `_parse_line`: "unknown
  event type"); this is what `reference.layer_assigned` did to the other line.
- Payload models are `StrictModel` (`extra="forbid"`): a new optional field in `ProtocolAmended` or
  `MinerUse`, written by new code, fails validation in old code.
- `spec_from_json` rejects unknown keys: a derived miner's spec blob with `taxonomy` or
  `absence_values` fails in old code. In addition, `spec_to_json` writes every key, so adding a
  selector key with a default would change the digest of **every existing miner**; new keys must be
  written only when not default.
- Two codes with different `PROJECTION_VERSION` rebuild one index against each other (IDEA-62).

### 6.3 How to introduce them

| Option | What | For | Against |
|---|---|---|---|
| **I1 (recommended), with I3** | **Schema first.** One small commit on `main`, before any line writes the new events: event models and catalog entries (fold handlers may be no-ops), the new optional fields on existing models, the new spec keys (written only when not default), one `PROJECTION_VERSION` bump. The runtime worktree (`.claude/worktrees/runtime`) moves to that `main`; every session reconnects. Only then does the feature branch write them | No reader change; corruption detection kept; one projection bump | Requires settling the payloads before building (this plan's §6.1 is that list) |
| I2 | **Tolerant reader.** Unknown types skipped and counted (`check` finding `unknown-events`); unknown payload keys ignored | Lines can diverge | Weakens a system contract (spec 00: events are the source of truth; a skipped event silently changes projections); needs its own decision |
| **I3 (with I1)** | **Scratch copy.** Until merged, the feature branch writes only into a scratch copy of the pilot project (as reference-layers calibration did); the shared log receives the new types only from `main` | Shared log never sees an unmerged type | Pilot results produced on the scratch copy must be redone or imported |
| I4 | Avoid new types: encode proposals as `label.applied`, taxonomy as protocol section (A1) | No catalog change | Labels "select nothing" and are organisation, not decisions; proposals lose their structure |

## 7. Rigour (unchanged from IDEA-50, made concrete)

Categories are the researcher's: `taxonomy.registered` is human-only, and an agent's drafts exist only
as `taxonomy.change_proposed`. Patterns count and propose, never classify, and are outside the digest.
Every assignment row is quoted and verified like any miner row, except absence values, which carry
the read scope. Counts, coverage, diffs and staleness are computed. A taxonomy version is in the
protocol hash when listed (A2). Examples never come from a calibration sample. Held-out seeds' works
are classified like any other work (decision 37.9).

## 8. Rulings for the researcher

Each row is one decision; the recommended option is first.

| # | Question | Options (recommended first) |
|---|---|---|
| Q1 | Where a taxonomy lives (§3.1) | **A2** registered and listed · A1 protocol section · A3 registered, unlisted |
| Q2 | Row shape for multi-label (§3.2) | **B2** one row per category, key `category` · B1 primary/secondary fields · B3 enum-set kind |
| Q3 | Primary/secondary rank within a multi dimension | **none in v1** · optional `rank` field outside the key |
| Q4 | Residual buckets (§3.3) | **C1** `other` + `not-stated`, applicability computed from layer · C2 judged `not-applicable` too · C3 `other` only |
| Q5 | One pass `not-stated`, the other a category | **completeness, not disagreement** · disagreement |
| Q6 | Embeddings (§3.4) | **D1 in v1, D3 in v2** · D2 · none |
| Q7 | `max_units` (§3.5) | **E2a** rename to `max_works` · E2b keep name, add paragraph cap · E2c both |
| Q8 | Layer of corpus works (§4) | **L1** dimension-zero derived miner · L2 extend reference-layer tools · L3 cited-item layer |
| Q9 | Granularity of derived miners | **one per group of dimensions** (layer; core dimensions; human-role dimensions) · one for all · one per dimension |
| Q10 | Merge of categories | **alias, carried, not re-read** · re-read rows of both |
| Q11 | Which layers are mined, and how the rest are reached (§4) | ruled: automatic for core and adjacent; on demand per work or per layer; the researcher can move a work between layers |
| Q12 | Introducing new events (§6.3) | **I1 + I3** · I2 · I4 |
| Q13 | v0 → v1 | **the agent drafts definitions, cues and examples for the 69 categories as proposals; the researcher edits and registers v1** · the researcher writes them · register v0 as is (names and patterns only) |

### Rulings recorded (researcher, 2026-11-12)

- **Q1: A2.** "The same as miners." The researcher notes that adding taxonomy categories or a new
  miner then requires a protocol change. That follows from A2: a new category is a new taxonomy
  version, and using it as evidence means listing that version in the protocol, which is a semantic
  amendment whose stale rows are computed (§5). Making that amendment one command, without
  rewriting the protocol file, is IDEA-51 item 2 and applies to taxonomies as to miners.
- **Q2–Q10, Q12, Q13:** the recommended options are accepted ("the rest seem okay").
- **Q11 (replaces the depth table):** every listed miner runs automatically on core and adjacent
  works; every other layer is mined on demand from the hub, for one work or a whole layer, through
  the work queue and Process now; the researcher can move a work between layers (§4). A request
  runs every miner listed with `on_demand` (confirmed by the researcher).
- **Timing of the schema-first commit (I1):** when the pilot can pause, i.e. when no miner wave or
  other session is writing; the runtime worktree then moves to `main` and every session reconnects.

## 9. After the rulings (sketch, not tasks yet)

1. Schema-first commit on `main` (I1): models, catalog, spec keys, `PROJECTION_VERSION`; mypy, ruff.
2. `mining/taxonomy.py`: spec, JSON form, digest, diff (pure); `derive_miner`.
3. `services/taxonomies.py`: register, list, diff, coverage, proposals; MCP and CLI wrappers.
4. Value-level staleness in `protocol_rules.extraction_stale` / `miner_stale` for derived miners.
5. Close checks (cardinality, coverage, absence values); `MinerUse.layers` and `order` in `mine_next`.
6. Hub: taxonomy product (counts per version, agreement per category, lineage), under IDEA-55.

Critical modules (events, index, protocol) go to `rf-builder-critical`; one `rf-reviewer` review
before landing. Testing is paused (test-run policy); tests are listed per task for later.

## 10. Build tasks (2026-11-12)

Branch `plan-taxonomies`, worktree `.claude/worktrees/plan-taxonomies`. Testing is paused: each task
passes `uv run --project platform mypy --strict` on the files it touches and `ruff`; it writes no
tests and lists the tests to write in its commit message (recorded in the untested-work list).
Builders share the worktree: no `git commit --amend`, `reset` or rebase; each commits only its own
files. Nothing reaches the pilot until the branch is merged into `main` at a pause (I1, I3).

**Compatibility rule for every task.** Old logs replay identically: every new optional field on an
existing model (`MinerUse`, `ExtractionStale`, `MinerSpec` JSON) is omitted from serialisation when
it has its default (the `model_serializer(mode="wrap")` pattern of `FinalRow._local_says_nothing`
in `services/extraction_agreement.py`; `spec_to_json` writes new keys only when not default), so
existing protocol version hashes and miner digests do not change.

| # | Task | Agent | Files | After |
|---|---|---|---|---|
| T1 | Events and fold: payload models for `taxonomy.registered`, `taxonomy.change_proposed`, `mining.requested`, `work.layer_set`; catalog entries; index tables `taxonomies`, `taxonomy_proposals`, `mining_requests`, `work_layer_moves`; human-only actor guard on the three human events (as `reference.layer_scheme_recorded`); optional `MinerUse.layers`, `on_demand`, `order` and `ExtractionStale.values`, omitted when default; `PROJECTION_VERSION` 84 | rf-builder-critical | `model/taxonomies.py`, `model/miners.py`, `model/protocol.py`, `events/catalog.py`, `index/taxonomies.py`, `index/default.py` | — |
| T2 | Taxonomy spec, pure: dataclasses, JSON form (`taxonomy_from_json`, `taxonomy_to_json`), meaning checks, digest and category digests (prose, names, patterns, lineage excluded), `diff(old, new)` naming added, removed, redefined, renamed, split, merged categories and changed cardinality, read scope or layer scheme | rf-builder | `mining/taxonomy.py` | — |
| T3 | Miner spec additions and derivation, pure: `MinerSpec.taxonomy` reference and `EvidenceRule.absence_values` (JSON only when set; old blobs read unchanged); `max_works` read as an alias of `max_units`; `validate_miner` refuses a key field whose anchor is a row anchor for derived miners and exempts absence-value rows from the quote rule; `derive_miner(taxonomy, dimensions, selector, regime, version)` as §2.2 | rf-builder | `mining/spec.py`, `mining/validate.py`, `mining/derive.py` | T2 |
| T4 | Taxonomy service: register (human only, first write wins, spec blob), list, view, diff, coverage (port of `taxo_report.py`: pattern counts over a descriptor miner's live pass-A quotes, unmatched works, seeded sample quotes; computed, no event), propose (agent, provenance with `input_blob`), proposals | rf-builder-critical | `services/taxonomies.py` | T1, T2 |
| T5 | Layers and requests: `layer_of(work)` (latest `work.layer_set`, else the final dimension-zero row, else pending), `move_layer` (human), `request_mining` (human; a layer resolved to work ids at recording), and the miner population of §4 (`MinerUse.layers` ∪ live requests, `order: by-layer`) in `services/mining.py` | rf-builder-critical | `services/work_layers.py`, `services/mining.py` | T1, T3 |
| T6 | Close checks for derived miners: every applicable dimension has a row; `single` exactly one; `not-stated` excludes other rows of its dimension; dimensions skipped by `applies_to_layers`; task content carries definitions, cues, examples and the residual rule (replacing the contrary `MINE_INSTRUCTIONS` sentence for such miners) | rf-builder-critical | `mining/kinds.py`, `services/mining.py` | T3, T5 |
| T7 | Value-level staleness: for two miners derived from the same taxonomy, `miner_stale` uses the taxonomy diff (table in §5) to produce `ExtractionStale(values=…)`; staleness applies it to rows whose `category` is in the set | rf-builder-critical | `services/protocol.py`, `services/protocol_rules.py`, `model/staleness.py` | T1, T2, T3 |
| T8 | MCP and CLI wiring (parse, call, format): `taxonomy_register`, `taxonomy_view`, `taxonomy_diff`, `taxonomy_coverage`, `taxonomy_propose`, `taxonomy_proposals`; `factory taxonomy register|view|diff|coverage|proposals`, `factory mine request`, `factory layers move`; access rows | rf-builder | `mcp/server.py`, `cli/taxonomy.py`, `cli/main.py`, `services/access.py` | T4, T5 |
| T9 | Hub: POST acts `mine-work`, `mine-layer`, `move-layer` (decision 119 rules); work-queue stage `mining`; Process now runner stage `mining` (`mine_next`, `mine_record`, `document_read`) | rf-builder-critical | `services/site_server.py`, `services/work_queue.py`, `services/runner.py` | T5 |
| T10 | Agreement for derived miners: per dimension; `single` exact, `multi` per-category presence and per-work Jaccard; one pass `not-stated`, the other a category, reported as completeness | rf-builder-critical | `services/extraction_agreement.py` (or a new `services/taxonomy_agreement.py`) | T3 |
| T11 | Skill `rf-taxonomy`: classification procedure and how to write a proposal | sonnet (prose) | `plugin/skills/rf-taxonomy/SKILL.md` | T4 |
| R | One review of the branch (guard mutation reasoned, not run) | rf-reviewer | — | all |

Waves (at most three agents at once): T1 ∥ T2; then T3 ∥ T4; then T5 ∥ T7; then T6 ∥ T10 ∥ T11;
then T8 ∥ T9; then R.

## 11. Build state (2026-11-12)

T1–T11 built on `plan-taxonomies` (mypy and ruff only; nothing run under pytest; tests to write are
in each commit message). One review (`rf-reviewer`, Sonnet): no Critical finding; six Important,
fixed in rounds F1–F3: the protocol `taxonomies` listing (Q1), registration of a derived miner
checked against its registered taxonomy (and `factory taxonomy derive` to produce it), on-demand
requests honoured when a miner has no automatic layers, the layer map computed once per log state,
close checks refusing an unregistered taxonomy, `cli:mine request` a human permission, and the
proposal's `input_blob` holding the evidence it cites.

Minor findings left open (for the researcher's attention, not fixed):

- The runner's `mining` stage runs the first miner with an open need; other miners wait for the
  next run.
- A layer move after a unit closed stales nothing, although the applicable dimensions depend on the
  layer; the work keeps rows for the old layer's dimensions.
- `validate_miner` now refuses a row-key field that is also a row anchor for every registered miner,
  not only derived ones (intended: it is the cause of the 14-of-56 alignment in `m-classification`).
- Coverage reads descriptor rows of every version of the named miner (rows carry no version).

First tests when testing resumes (reviewer's order): golden replay of old protocol and miner events
(hashes and digests unchanged); agent-written human events change nothing in the index; miner
population with and without layers, requests and `max_units`; the stale rule per diff kind; close
checks per rule and the absence exemption; hub POST refusals; `layers_of` precedence.

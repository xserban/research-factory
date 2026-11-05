# Abstractions of the research factory

*Background, not binding.* Binding contracts stay in `docs/specs/` (system, rigour, slices) and `docs/decisions.md`; this document describes and links them and states no new requirement.

## 1. Purpose

The specs of slices 1–3c describe a dozen stages, each with its own events, tools, quality checks and reports. This document reduces them to a small set of concepts (artifact, event, stage module, gate, miner, quality regime, builder, project, corpus, trace) so that new slices can be brainstormed against one vocabulary. It is organised around the researcher's two proposals of 2026-11-04: miners (backlog IDEA-37) and stage modules with gate policies (IDEA-38). It records where today's code already has the shape of these abstractions and where it does not.

## 2. Invariants

Every part, built or proposed, obeys these. They are the fixed points a new abstraction may not bend.

| # | Invariant | Source |
|---|---|---|
| I1 | Events are the source of truth: append-only JSONL per project and session; the SQLite index is a rebuildable projection written only by the projector | 00-system §4.1, §4.4; decision 7; slice-1 AC 1 |
| I2 | The platform never calls a model; all judgement comes from Claude through MCP tools (conversion included) | 00-system §1; decisions 6, 40 |
| I3 | Every count, rate, hash and PRISMA number is computed from events, never typed | R-05 |
| I4 | Every agent-written event carries model, skill version (`<name>@<hash>`) and `input_blob` | R-04; 00-system §4.2 |
| I5 | Validation at the boundary: invalid input writes nothing and returns structured errors; batches accept partial success | 00-system §7 |
| I6 | Proposer ≠ evaluator; independence of passes is engineered and recorded (sessions, models, framing, order) | R-51, R-33; decision 37 |
| I7 | Pre-registration: criteria, screening plan, extraction schema and stopping rules are declared before reading; protocols are hashed over decision-relevant fields; amendments compute their blast radius | R-13, R-14, R-15, R-45, R-50; decisions 25, 50 |
| I8 | Held-out discipline: positive seeds are split before the probe; held-out seeds and label-derived rates are invisible to agents | R-20, R-24; decisions 36, 43 |
| I9 | No literature text in git: raw sources and canonical Markdown live in the git-ignored library; events carry hashes and verified quotes only | R-47; decision 39 |
| I10 | Every agent statement about a text is a verbatim quote at an anchor, checked by the platform | R-32, R-40, R-44 |
| I11 | Corrections supersede; nothing is edited or deleted | 00-system §4.1; R-40 |

## 3. Core abstractions

### 3.1 Artifact
**Definition.** A typed, identified, versioned object that a stage reads or writes, referenced only by id.
**Today.** The id table of 00-system §3 (`rf:` works, `Q@`, `P@`, `S@`, `SEED`/`NEG`, `qry_`, `run_`, `mrg_`, `dec_`, `tsk_`, `fft_`, `att_`, `doc_`), extended by the slice specs (`rex_` reference extractions, `snw_` snowball rounds, `rel_` relations, `ida_` ideas, `int_` interpretations, `cpt_` concepts) and extraction rows keyed by `row_key`. Versioning takes two forms: content hash (`Q@`, `P@`, document and conversion hashes) and supersession (decisions, rows, links, reviews).
**Generalised.** Artifact = (kind, id, version rule, epistemic class). Slice 3c ruling 3 introduces the class dimension (`evidence` versus `interpretation`); in general every artifact could carry a class (evidence, candidate, interpretation, exploratory) that builders filter on.

### 3.2 Event and projection
**Definition.** An event is an immutable, validated fact about an artifact; a projection is a deterministic fold of events into queryable tables.
**Today.** The envelope of 00-system §4.2 (`type` = `<area>.<past-tense verb>`, pydantic payload, schema version); `events/writer.py`, `events/validation.py`; `index/projection.py` and one index module per area. Slice 3b moves derived status (staleness, effective edge status) to read time in `services/lineage.py`, keeping the tables as pure event facts.
**Generalised.** Each module owns one event family and one projection; derived states are computed on read, never stored. Open: schema evolution (00-system §11).

### 3.3 Stage module (IDEA-38)
**Definition.** A step of the factory with one declared contract, runnable by a human, by a human with agent help, or by agents alone.
**Contract (IDEA-38).**

```
            +--------------------- stage module ----------------------+
 inputs --->| strategy (implementation@version, recorded in provenance)|---> outputs
 (artifact  |   events: one family        checks: findings for check |    (artifacts
  ids)      |   gates: binding decisions  methods text: for the report|     by id)
            |   quality regime: passes, agreement, audit, calibration |
            +------------------------- gate policy --------------------+
```

**Today.** Implicit. `services/` has one module per capability, and the contract parts are scattered: events in `model/`, checks in `services/check.py`, methods text in `services/methods.py`. Strategy registries already exist for full-text routes (`sources/fulltext`) and converters (`document/registry.py`); scoping has two hand-run strategies (interview by `rf-frame`, probe by `rf-probe`). `services/stages.py` covers only screening's stage dimension (title/abstract, full text).
**Generalised.** The production lines of `docs/02-production-lines.md` become compositions of modules; a new line is a new composition, not new code.

### 3.4 Gate and gate policy
**Definition.** A gate is a decision that binds later stages; a gate policy states who may pass it.
**Today.** The rigour spec numbers gates 00–04 (question, probe, protocol, search, screening: R-10, R-20, R-11–R-13, R-22–R-24, R-35–R-38); R-16 refuses screening against a draft protocol; PRESS confirmation (R-61); confirmation gates in slices 3a–3c (fuzzy reference links, inferred relations, ideas, interpretation and concept reviews). Policy is implicit in `RigorMode` (`exploratory | pilot | systematic`, 00-system §6): thresholds and advisory-versus-enforced status are coded per service (calibration sensitivity 0.9/0.95, `AUDIT_ERROR_CEILING`, κ floor).
**Generalised (IDEA-38).** Per gate: `human`, `agent + human audit (rate r)` or `agent`. Rigor modes become presets; the policy is part of the hashed protocol, changes only by amendment, and outputs carry the autonomy level under which they were produced. An autonomous factory is a policy, not separate code.

### 3.5 Miner, field kinds and verifiers (IDEA-37)
**Definition.** A miner is a declared, versioned, hashed specification that turns selected documents (or works) into typed records, each anchored to a span and checked by a deterministic verifier.
**Parts.** Selector (which works, documents, sections); output schema built from verifiable field kinds (number with unit, enum, verbatim quote, citation, anchor reference, work reference); evidence rule; procedure (skill text); quality regime.
**Today.** Extraction packs: `packs/model.py` (`Pack`, `FieldDef`, `FieldKind`, `UnitFamily`, `Check`), one registered pack `ML_BENCHMARK_V1`, selected by `ProtocolSpec.extraction_schema` (`ExtractionSchema`). Verifiers: `document/quotes.py::quote_in_element`, `extraction/numbers.py`, `extraction/citations.py`, `extraction/verify.py`, `references/match.py`. Plan G2-A runs a second pack (`contribution`) through the same plan-D machinery with a pack discriminator (slice-3b ruling 6): the first instance of "one machinery, many miners". IDEA-37 lists four hand-written miners: screening, extraction, references, contributions/concepts.
**Generalised.** A mined record keyed by (miner id, miner version, document version); agent-authored miners are registered before their first task and stay exploratory until calibrated (IDEA-37 rules 1–4).

### 3.6 Quality regime
**Definition.** The declared procedure that bounds a module's error: independent passes, agreement rule, calibration, human audit and staleness triggers.
**Today.**
- Screening: two passes with engineered independence (decision 37), `cohen_kappa` and per-criterion κ (`services/screening_stats.py`), calibration (`services/calibration.py`), audit with `audit_size` and 3:1 weighting (`services/audit.py`), `AUDIT_ERROR_CEILING = 0.05`.
- Extraction: hash-threshold dual sample, per-field agreement (`services/extraction_agreement.py`), audit with `EXTRACTION_ERROR_CEILING = 0.05` (`services/extraction_audit.py`; decision 51).
- References (spec): matcher thresholds and an unresolved ceiling (slice-3a rulings 16, 17).
- Interpretation layer (spec): review states, writer-cannot-review.
- Staleness: `model/staleness.py` (`stale_decisions`, `stale_rows`), supersession by document version, the `source-stale` flag (slice-3c ruling 9).

**Generalised.** A regime is a declared tuple (passes, independence rule, agreement unit, calibration set and threshold, audit fraction, minimum and ceiling, staleness triggers) attached to a module and instantiated by the gate policy.

### 3.7 Builder
**Definition.** A deterministic consumer of artifacts that produces a derived view and never judges.
**Today.** `services/prisma.py::prisma_flow`, the PRISMA-S search report, `services/methods.py`, `services/evidence_report.py` with `evidence/pareto.py` (groups by comparability keys, frontiers, within-paper speed ratios; decisions 41, 42), `check` and `trace`; planned: the lineage graph projection, queries and export (G2-D) and the labelled layer view (G3-C, `layer_graph`).
**Generalised.** A builder declares which artifact kinds, miner versions and status filters it reads (slice-3b ruling 14: "a statistic always names the status filter it used") and is byte-identical across rebuilds.

### 3.8 Project and protocol
**Definition.** A project is a question with its rigor mode and corpus selection; its protocol is the hashed declaration of everything that binds the stages.
**Today.** `factory init`, `RigorMode`; `Question` with elements and non-goals (R-10); `ProtocolSpec` sections `criteria`, `sources`, `queries`, `limits`, `screening`, `full_text_screening`, `extraction_schema`, `snowball_plan` (and `contribution_schema` in G2-A), `method_profile` (`MethodProfile`, R-60). Sections absent are omitted from the hash, so adding a section keeps old `P@` ids: this is the de facto extension mechanism. Amendments and deviations are separate (R-14); decisions carry along the protocol lineage (decision 50).
**Generalised (IDEA-37 project layer).** The protocol selects modules, strategies, miners and builders, sets gate policies, and states which records count as evidence.

### 3.9 Corpus
**Definition.** The works and their documents, with how each was found and how it was obtained.
**Today.** `Work` requires `Provenance` (R-02) with `ProvenanceMethod` `database | citation-chase | seed-admission | hand-search`; reversible dedup merges (R-26); documents and conversions in the project-local library, addressed by content hash; full-text routes including researcher-supplied import (decision 46 item 7). The corpus is per project.
**Generalised.** A corpus layer shared across projects (IDEA-37; documents are already project-independent by hash), with a computed discovery record per work (IDEA-35) and a single candidate inbox fed by searches, watches (IDEA-02), snowball rounds and researcher links (IDEA-34). Admission into a project always passes that project's screening.

### 3.10 Trace
**Definition.** The guarantee that every number and statement resolves backwards to a verified span and forwards to what it produced.
**Today.** `services/trace.py::trace`, `factory trace REF [--forward]`; the chain of R-01 and slice-2 AC 14 (cell → extraction → document version → retrieval attempt → work → screening decisions → protocol → question); `check` reports broken links and promotion gaps (`check --promote-to`).
**Generalised.** Each artifact kind declares its back-references; trace is a builder over those references, and `check` is the union of each module's declared checks.

```
  PROJECT LAYER   question, protocol (hashed): modules, miners, builders, gate policies, evidence rule
        |  selects
  CORPUS LAYER    works (provenance, discovery) --- documents / conversions (library, by hash)
        |  read by
  MINING LAYER    miners: selector + field kinds + verifier + procedure + quality regime --> records
        |  consumed by
  BUILDER LAYER   PRISMA, methods, evidence report, citation/lineage graph, layer view, trace, check
```

## 4. Today's pipeline mapped onto the abstractions

Statuses follow the `CLAUDE.md` status line and `docs/plans/`: plans 2D and 2E are being completed on branch `plan-2d-extraction`; G1 is in progress (models, projection, matcher and resolution committed; snowball rounds not yet); G2 and G3 plans are written and ready.

| Stage | Module kind | Inputs | Outputs (artifacts) | Gates | Quality regime | Builders fed | Status |
|---|---|---|---|---|---|---|---|
| Question, seeds, probe, protocol | Scoping (strategies: interview, probe) | Raw goal, seeds | `Q@`, `SEED`/`NEG` with split, probe runs, `P@`, PRESS review | 00, 01, 02; protocol `ready` (R-16); PRESS confirmed by human (R-61) | Dev-seed recall and negative hits; recorded split | Methods, trace, check | Built (slice 1) |
| Search, supplementary (chase, seed admission) | Retrieval | `P@`/`S@`, included works | `qry_`, `run_`, raw blobs, works with provenance, chase rounds | 03 seed check (R-24) | Reported vs retrieved (R-23); held-out recall | PRISMA identification, PRISMA-S report | Built (slice 1, plans 2, 5a) |
| Deduplication | Deterministic transform | Works | `mrg_` (reversible) | None | Seed false-merge/false-split checks (R-26) | PRISMA duplicates | Built |
| Screening TA + FT, calibration, audit | Miner (filter) | Works, `P@`; pinned conversion at FT | `dec_`, calibration labels, resolutions, audit labels | 04: calibration, κ floor, audit ceiling; disagreements and `unsure` to human | Two passes, κ, calibration, audit (decision 37) | PRISMA, methods, check | Built (plans 4, 2C) |
| Full-text acquisition | Retrieval (strategies: routes) | Works with TA outcome `INCLUDED` (decision 48) | `fft_`, `att_`, `doc_` | TA outcome | Every attempt recorded; restore by hash | PRISMA "not retrieved", `fulltext_status` | Built (2A) |
| Conversion to canonical Markdown | Deterministic transform (strategies: converters) | `doc_` | Conversion: Markdown, manifest, anchors | Converter choice (decision 49, human) | Bake-off; determinism (slice-2 AC 2, 3) | `document_read`, all verifiers | Built; decision 49 chose LaTeXML HTML, docling for PDF and pandoc for LaTeX |
| Extraction (2D) | Miner (`ml-benchmark` pack) | Pinned conversion, `extraction_schema` | Extraction rows, claims | Schema declared; human resolution; audit ceiling | Dual sample, per-field agreement, audit | Evidence report, trace, methods | Being completed |
| Evidence report (2E) | Builder | Final rows, claims, comparability keys | Report (Markdown, CSV): groups, frontiers, speed ratios, unsupported groups | None | Derived only | — | Being completed |
| References and snowballing (3a, G1) | Miner (deterministic parse, resolution) + retrieval (rounds) | Included works' conversions, `.bbl`, `snowball_plan` | `rex_`, links, resolution decisions, `snw_`, candidate works | Fuzzy-link confirmation (human; second agent in pilot); round sequencing; stopping rule | Matcher thresholds; unresolved ceiling; `snowball_compare` | PRISMA other methods, search report, `cites` edges | In progress |
| Lineage (3b, G2) | Miner (`contribution` pack) + proposal module (relations, ideas) + builder (graph) | Pinned conversions, G1 links, `contribution_schema` | Contribution rows, `rel_`, `ida_`, graph tables | Human confirmation of inferred relations and ideas (all modes) | Plan-D dual sample, agreement, audit; stated/inferred rule | Graph queries, export, trace | Planned (G2-A–E ready) |
| Intuition layer (3c, G3) | Authoring module + review gate + layer builder | Ideas, papers, contribution items, approved sources | `int_`, `cpt_`, `uses` links | Human review; human source approval; human link confirmation | Review states; writer ≠ reviewer; separation tests | Layer view, labelled export | Planned (G3-A–C ready) |

## 5. Where the code fits the abstraction, and where it does not

**Fits.**
- Event/projection discipline is uniform across every stage built so far, including rebuild determinism.
- The verified-span primitives (`quote_in_element`, the number and citation checks) are reused unchanged by full-text screening, extraction, and (in the specs) contributions and interpretations: field kinds and verifiers already exist, under other names.
- Protocol sections omitted from the hash while absent act as a module registration mechanism that never invalidates old `P@` ids.
- G2-A's pack discriminator turns plan-D extraction into a reusable miner engine without changing evidence outputs (slice-3b acceptance 7).
- Route and converter registries are strategies behind a contract.
- The stated/inferred/confirmed classification recurs in 3a, 3b and 3c: one gate pattern applied three times.

**Does not fit (yet).**
1. *Packs are hard-wired.* `packs/__init__.py` holds a literal `_PACKS` registry with one pack; the `domain-packs/` directory of 00-system §2 does not exist. `FieldKind` is `text | number | integer | bool` with a separate `Check` (`number | text-in-quote | none`), not IDEA-37's menu (enum, quote, citation, anchor reference, work reference); enum arrives as `FieldDef.allowed` and a reference as an integer `cited_entry` in G2-A. `ReportSpec`, a builder's configuration, lives on the pack.
2. *Screening is a special case.* Four verdicts, criterion citation with priorities, exclusion reasons in PRISMA, `cannot-assess` promotion and R-15 blast radius tied to criteria make its accounting stricter than any other miner (IDEA-37 open question).
3. *Quality code is duplicated per stage.* `services/agreement.py` and `services/extraction_agreement.py`, `services/audit.py` and `services/extraction_audit.py` are parallel; they share only `audit_size` from `screening_stats.py`. `_is_pass_session` is defined in both `agreement.py` and `audit.py`. Task kinds are hard-coded tables (`_KINDS`, `EXTRACT_KINDS` in `services/stages.py`).
4. *Gate policy is implicit.* `RigorMode` is tested in about a dozen service modules; no single declaration states who passes which gate. Policies are chosen per spec: G1 permits a second agent to confirm fuzzy links in pilot (slice-3a ruling 3); G2 and G3 forbid any agent confirmation in every mode.
5. *Pass-session isolation is enumerated per tool* (decisions 43, 48 and a "refused to pass sessions" list in each spec), not derived from a property of the module.
6. *Mined records are project-scoped.* Events live under `projects/<slug>/events/` and rows are pinned to a protocol's schema; IDEA-37's project-independent key (miner, version, document version) has no store yet, and library sharing is deferred to slice 5 (00-system §11).
7. *Builders read service internals.* `evidence_report.py` imports from `extraction`, `extraction_agreement` and `extraction_audit`; there is no declared input contract.
8. *Discovery provenance is spread.* `ProvenanceMethod` has four values; researcher-supplied exists only as a full-text route; snowball and chase share `citation-chase` and are told apart through round tables (slice-3a ruling 20). IDEA-35's discovery record would have to be assembled from several places.
9. *Many binding behaviours rest on Proposed decisions.* Rigor modes (24), protocol changes (25), dual screening (29), seed hold-out (36), screening independence (37) and supplementary search (38) are implemented but still *Proposed*.

## 6. Open design questions

**Contract and granularity**
1. Does screening become a miner with a stricter accounting add-on, or stay a module of its own kind? (IDEA-37)
2. How much of screening, extraction and references can move behind one contract without changing event types: a generic `mine.*` family, or per-module families behind a shared service? (IDEA-38)
3. What is a scoping module's output: the slice-1 `Q@` and `P@`, or a richer scope artifact that several strategies (interview, probe, seed-set drafting) produce comparably? (IDEA-38)

**Gates and autonomy**
4. Are gate policies per project or per run, and if hashed into `P@`, does a policy change have a blast radius over outputs produced under the old policy? (IDEA-38)
5. Is G1's second-agent confirmation the `agent + human audit (r)` policy in disguise, and does it then need the audit that slice-3a open question 2 leaves unspecified?
6. Should the autonomy label reuse the epistemic-class mechanism of slice 3c (labels, default-view exclusion, differential tests)?

**Miners and field kinds**
7. How does a selector name sections stably across converter versions, given that anchors change with the converter version (decision 53; `b<n>` from LaTeXML converter 1.1)? (IDEA-37)
8. Who labels the calibration set of an agent-authored miner, and what bounds its cost over a whole corpus? (IDEA-37)
9. How does a builder combine records from several versions of one miner: latest only, staleness, or explicit union? (IDEA-37)

**Corpus and reuse**
10. Is the shared mining store a projection across `projects/` or its own event log, and does a correction in a source project propagate as staleness to importers? (IDEA-36, IDEA-37)
11. Should the candidate inbox (IDEA-02), the link inbox (IDEA-34) and snowball candidates be one artifact with a discovery route, and what does "first surfaced" mean when several routes find a work in one session? (IDEA-34, IDEA-35)

**Later stages**
12. How do hypothesis registration and validation (R-50, R-52, R-53; IDEA-17) fit the module contract and the event model before their slice is specified?

## 7. Glossary

- **Anchor** — stable address inside a canonical document (`#s3.2.p4`, `#t2.r5.c3`, `#b12`).
- **Amendment / deviation** — planned, recorded protocol change / unplanned departure (R-14).
- **Artifact** — typed, identified, versioned object passed between stages.
- **Blast radius** — the earlier decisions an amendment makes stale (R-15).
- **Builder** — deterministic consumer producing a derived view (PRISMA, evidence report, graph).
- **Calibration** — human-labelled set screened before a batch to measure correctness (R-35).
- **Canonical Markdown** — the one converted form of every document version that agents read (decision 40).
- **Comparability keys** — declared fields that alone may group results (R-45; decision 41).
- **Epistemic class** — `evidence` or `interpretation` (slice-3c ruling 3); generalised here.
- **Field kind** — verifiable type of a mined field (number with unit, enum, quote, citation, anchor, work reference).
- **Gate** — a decision that binds later stages.
- **Gate policy** — who may pass a gate: human, agent with audit, or agent (IDEA-38).
- **Held-out seeds** — positive seeds hidden from agents and probe, used for honest recall (R-20).
- **Library** — git-ignored, content-addressed store of literature per project (decision 39).
- **Miner** — versioned specification turning documents into verified records (IDEA-37).
- **Pass** — one independent run of a miner by a separate session and model (R-33).
- **Projection** — rebuildable index state folded from events.
- **Protocol (`P@`)** — hashed declaration of everything that binds the stages.
- **Quality regime** — passes, agreement, calibration, audit and staleness rules of a module.
- **Rigor mode** — `exploratory | pilot | systematic`; a gate-policy preset in IDEA-38.
- **Stage module** — a step with one contract and interchangeable strategies (IDEA-38).
- **Stated / inferred / confirmed** — edge basis classes: platform-verified, agent-proposed, human-confirmed.
- **Strategy** — one implementation of a module, recorded in provenance.
- **Supersession** — correction by a new event that names the old one.
- **Trace** — backward and forward resolution of any artifact along R-01's chain.
- **Verifier** — deterministic check of a field against its anchored span.

# Slice 2 — Full text, extraction and evidence

Status: **approved for planning** · 2026-11-03 · Builds on [00-system.md](00-system.md) and slice 1; must satisfy [01-rigour.md](01-rigour.md) R-01–R-05, R-13–R-16, R-30–R-39 at the full-text stage, and R-40, R-42–R-47 (R-41 appraisal deferred). The converter choice is settled inside plan B by a bake-off; findings from the slice-1 pilot run that change this spec are recorded as decisions and edited in, not handled ad hoc.

## Goal
Take the works promoted at title/abstract screening to a **full-text-screened corpus with verified, schema-driven extractions**, and answer a comparative question as an **evidence table** — every number traceable to a verified span in a specific version of a specific paper.

Pilot for acceptance: **best linear attention mechanism for vision models** — output is a set of comparability groups (e.g. ImageNet-1K classification at 224², ADE20K segmentation) with an accuracy-vs-cost frontier per group (backlog IDEA-06).

## User flow
1. **Declare before reading (R-13):** the protocol gains an extraction schema (from a domain pack, e.g. `ml-benchmark`), the full-text screening plan, and the comparability keys. Changes are amendments with blast radius (R-14, R-15).
2. **Acquire:** the platform fetches full text for every work whose title/abstract outcome is `promote` (implemented as `Outcome.INCLUDED`; reconciled 2026-11-04 with decision 48), trying legal routes in a fixed order; every attempt is recorded; failures are PRISMA "not retrieved" with a reason.
3. **Normalise:** every retrieved source, whatever its format, is converted deterministically into one canonical **Markdown** document with stable anchors; raw source and Markdown are both content-addressed in the project's local library.
4. **Full-text screening:** criteria with `applies_at = full-text | either` are applied with the slice-1 machinery (two passes, calibration, κ, audit, verified quotes) — quotes now cite anchors.
5. **Extract:** for each included work, Claude extracts schema rows (results, settings) and atomic claims through `extract_next` / `extract_record`; the platform verifies every quote and every number against the anchored source.
6. **Check extraction:** dual extraction on a declared sample; field-level agreement; disagreements to the human; human audit sample of extracted values.
7. **Report:** full PRISMA 2020 flow (now including full-text boxes); evidence/benchmark report with comparability groups and frontiers; `trace` from any table cell back to the question.

## Design

### Full-text acquisition — route order
| Order | Route | Quality label | Notes |
| --- | --- | --- | --- |
| 1 | arXiv HTML (LaTeXML rendering) | `structured-html` | Sections, tables, equations preserved; not available for every paper |
| 2 | arXiv LaTeX source (e-print) | `latex` | Highest fidelity for tables; conversion harder |
| 3 | Open-access PDF via OpenAlex `best_oa_location` / Unpaywall | `pdf-text` | Licence recorded from the OA metadata |
| 4 | PubMed Central OA (JATS XML) | `structured-xml` | Not in slice 2: added with PubMed for the first biomedical project |
| 5 | Researcher-supplied PDF (folder or Zotero import) | `pdf-text` | Provenance `researcher-supplied`; matched to works by identifiers (port arxiv-miner `pdf_extractor` matching) |
| — | None succeeded | — | `not-retrieved` with per-route reasons; never an error |

Legal routes only. Each attempt records route, URL, HTTP status, retrieved_at, licence (if known), source version (arXiv `vN`, publisher DOI) and raw blob hash. Rate limiting reuses slice-1 `PoliteClient`.

**Version rule (decided 2026-11-02):** extraction applies to one recorded version — **the latest available version** at retrieval time (on the successful route: the latest arXiv `vN`, or the version the route offers; versions of record are not compared across routes by date in slice 2; reconciled 2026-11-04 with decision 46). A newer version found later is a new document, never an edit; earlier extractions stay attached to their version and are marked superseded-by-version, prompting re-extraction. Numbers in older versions are not extracted; when another paper's copied value matches only an older version, the copied-result flag notes the version mismatch.

### Canonical document
- **Everything is converted to Markdown** (decided 2026-11-03): HTML, LaTeX, JATS and PDF all end as one canonical Markdown document per document version. Agents read only this Markdown (via `document_read`); raw sources are kept for re-conversion and audit.
- **Stable anchors** are embedded in the Markdown: `#s3.2` (section), `#s3.2.p4` (paragraph), `#t2` (table), `#t2.r5.c3` (table cell), `#f4.cap` (figure caption), `#e7` (equation), `#p6` (PDF page, when only page mapping exists).
- Tables are Markdown tables; cell addresses (`#t2.r5.c3`) are derived deterministically from the table's row/column position, and the platform indexes cells for verification — the benchmark table depends on cell-level anchors.
- Conversion is **deterministic and offline**, with pinned converter name and version recorded; the same raw blob and converter version always give the same document hash. Converters may be rule-based or use fixed non-generative layout models; **no LLM is used in conversion** (platform never calls a model). Which converter per input format is chosen by a bake-off on a fixed off-topic ML test set (decision 47) and re-checked on the pilot's included works in the end-to-end run (AC 16).
- Re-conversion with a new converter version creates a new document version; old anchors remain resolvable through their version.

### Storage and licensing
Decided 2026-11-03: **literature is stored locally per project and never in git.**
- Raw sources (PDF, LaTeX archives, HTML, JATS) and canonical Markdown live in a content-addressed **library** at `projects/<slug>/library/sha256/<2>/<62>`, git-ignored as a whole, regardless of licence. Projects and sub-projects will accumulate large literature collections; git holds no literature.
- Git keeps what it holds today: events (including the **verified quotes** used as evidence, which keep decisions auditable without the full text) and the small text blobs of 00-system §4.3.
- Events carry library hashes, so integrity is checkable wherever the library is present; `check` reports missing library entries, and a missing document can be re-fetched by its recorded route and verified by hash.
- Backup of the library is the researcher's (machine backup); sharing it between machines and people is slice 5.

### Extraction schema (domain pack `ml-benchmark`, first version)
| Field group | Fields |
| --- | --- |
| Identity | work, document version, method name, variant/size, is_proposed (vs. baseline) |
| Task | task, dataset, split, input resolution |
| Result | metric, value, unit, higher_is_better, variance/seeds reported (y/n, value) |
| Cost | params, FLOPs/MACs, throughput, latency, memory, hardware, batch size, precision |
| Regime | pretraining data, training epochs, distillation (y/n), extra data |
| Provenance | anchor (table cell or paragraph), verbatim quote, reported-in (own result / copied from cited paper), reproduced (y/n) |

Plus **atomic claims** (R-40): statement, type (finding / mechanism / limitation / negative result), evidence type, strength, anchor, quote. Schema changes are protocol amendments.

### Verification (platform, deterministic)
- **Quote check:** quote occurs verbatim (after declared normalisation: whitespace, ligatures, Unicode) inside the anchored element; otherwise rejected.
- **Number check:** every numeric field value must appear in its quote or anchored table cell (declared numeric normalisation: `82.4` = `82.40`; `%` handling; `M`/`G` suffixes for params/FLOPs); otherwise rejected.
- **Copied-result flag:** a value extracted from a comparison table that cites another paper is marked `reported-in = cited`, linked to that work if in the corpus, and not counted as an independent result.

### Comparability and evidence report
- The protocol declares **comparability keys** (default for `ml-benchmark`: task, dataset, split, metric, resolution, pretraining regime). Rows are grouped only by identical keys; no ranking crosses groups.
- **Cost axes (decided 2026-11-02):** cross-paper frontiers use hardware-independent measures only (params, FLOPs/MACs, at the group's resolution). Throughput, latency and memory are extracted and shown, but **never compared across papers**; they are reported only as **within-paper ratios** against a baseline measured by the same paper on the same hardware (e.g. "1.8× faster than DeiT-S on A100, batch 64").
- Per group: table, Pareto frontier (metric vs. each comparable cost), counts of independent vs. copied results, single-source flags.
- The report states what the corpus does **not** support (empty groups, single-paper groups) (R-42).

### Appraisal (per-paper assessment)
**Deferred (2026-11-03):** appraisal instruments are project-specific, and the pilot does not need one. Slice 2 builds no appraisal tools. The design agreed on 2026-11-02 (decision 42, item 2) stands for the slice that adds it: items typed `platform` / `agent-span` / `judgement`, judgement items decided by a human, no overall score, instrument declared per project in the protocol. Backlog IDEA-21.

### Extraction quality
- **Dual extraction:** `systematic`: every included work by two independent sessions (decision 37 rules apply: separate sessions and models). `pilot`: a recorded random sample (`dual_extract_sample`, declared in the protocol).
- **Agreement:** per field; numbers must match exactly after normalisation; disagreements routed to the human; agreement rate reported per field group.
- **Audit:** human verifies a random sample of agreed values against the source (size rule as decision 37 item 3); error rate reported; above ceiling → schema or skill amendment.

## In scope
| Area | Content | Origin |
| --- | --- | --- |
| Acquisition | Route adapters (arXiv HTML, arXiv source, OA PDF, researcher-supplied), attempt events, version rule | New; arXiv PDF fetch idea from research-factory-old `fulltext.py`; matching from arxiv-miner `pdf_extractor.py` |
| Normalisation | Canonical document, anchors, structured tables, converter pinning | New |
| Full-text screening | Stage-aware tasks, anchor-cited quotes, PRISMA full-text boxes | Extend slice-1 screening |
| Protocol | Extraction schema, appraisal instrument, comparability keys, dual-extraction sample | Extend slice-1 protocol |
| Extraction | Tasks, records, verification, supersession, dual extraction, agreement, audit | New; claim model ideas from research-factory-old `claims.py` (made schema-driven) |
| Reports | Full PRISMA; evidence/benchmark report; trace to cells; methods statement extended | Extend slice-1 reports |
| Storage | Project-local library (git-ignored), missing-entry check, re-fetch by route | New |
| Domain pack | `ml-benchmark` schema, comparability keys, numeric normalisation | New |
| Plugin skills | `rf-screen` (full-text mode), `rf-extract` | New |

### MCP tools (slice 2)
`fulltext_fetch` · `fulltext_status` · `document_read` (paginated, anchored segments) · `screen_next` / `screen_record` (stage-aware) · `extract_next` · `extract_record` · `extract_agreement` · `extract_audit_sample` · `extract_audit_record` · `report_evidence` · `report_prisma` (full) · `trace` (to cells and claims). CLI: `factory fulltext import <folder>` for researcher-supplied PDFs.

*Implemented in plan 2A:* `fulltext_fetch` (an agent act, with `routes` as the route filter) and `fulltext_status` (MCP); `factory fulltext import|fetch|status|restore` (CLI; `fetch` and `restore` are the researcher's acts). The MCP tools refuse a session that has joined a pass, as `check` and `report` do.

*Implemented in plan 2B2:* `document_read` (MCP; read-only, refused to a session that has joined a pass (narrowed for full-text screeners in plan 2C)); `factory document convert|status|read` (CLI; `convert` is the researcher's act); events `document.converted` and `document.conversion_failed`; one conversion per (document, converter, version). The LaTeXML-HTML converter is registered; the LaTeX and PDF converters are registered after decision 49.

*Implemented in plan 2C:* stage-aware screening (`stage` on passes, sessions, calibration, agreement, audit, resolutions and decisions); full-text decisions cite an anchor of the pinned conversion and are verified against it; `screen_next`, `screen_agreement`, `audit_sample` and `calibration_label` take `stage`; CLI `--stage`; `document_read` for full-text screeners is limited to their own queue and pinned conversion; PRISMA full-text boxes; the `fulltext-decision-stale-document` check finding; protocol field `full_text_screening` (omitted from the version hash when absent); decision 50 (Decided 2026-11-04; reconciled with decisions.md) on decisions carrying along the protocol lineage.

*Implemented in plan 2D:* protocol field `extraction_schema` (pack, fields, comparability keys, dual-extraction sample, audit parameters) and the `ml-benchmark` pack; extraction in two independent passes with per-field provenance, verified quotes, number and table-cell checks, copied-result flags and pass-A-only claims; schema amendments stale affected rows and re-queue their units; agreement per field, human resolution (the human chooses between verified values and never types one), final and grouped rows; audit of agreed values with `EXTRACTION_ERROR_CEILING = 0.05`; `check` findings, `trace` from an extraction to the question, and a methods paragraph. MCP: `extract_next`, `extract_record`, `extract_agreement`, `extract_audit_sample`, `extract_audit_record`. CLI: `factory extract status|agreement|resolve|audit-sample|audit-label|audit-report`. Decision 51. Known limits: citations are capped at five surnames; the cell token `79.8 ± 0.2` is not split; `reproduced` is not checked; unit labels of the OTHER family match exactly (for example `MB` is not `M`).

## Out of scope
Appraisal (deferred, IDEA-21); PubMed search and PMC route (first biomedical project, IDEA-22); consistency check of copied results against the cited paper (IDEA-23); graph, regions and labels (slice 3); living updates (slice 4); shared blob store and teams (slice 5); hypotheses and reproduction experiments (slice 6); prose synthesis and related-work writing (slice 7); OCR of scanned PDFs; figures as data (plots digitised).

## Acceptance criteria
1. **Acquisition record:** every promoted work has ≥ 1 attempt event; each retrieved document records route, URL, version, licence, retrieved_at, raw hash, converter and version; each not-retrieved work lists per-route reasons.
2. **Conversion determinism:** converting the same raw blob twice with the same converter version yields identical document hash and anchors.
3. **Anchor stability:** re-conversion with a new converter version creates a new document version; quotes recorded against the old version still verify against it.
4. **Full-text screening:** decision 37 rules hold at the full-text stage; a quote that is not verbatim in the anchored element is rejected.
5. **Schema before extraction:** extraction is refused until the protocol declares a schema; a record with an undeclared field is rejected; a schema change is an amendment and stales affected extractions.
6. **Number check:** a numeric value absent from its quote or table cell (after normalisation) is rejected; valid rows in the same batch are recorded.
7. **Cell anchors:** a table-cell anchor resolves to exactly one cell, and the platform checks the cell text against the value.
8. **Copied results:** values from comparison tables citing other papers are flagged and excluded from independent-result counts.
9. **Dual extraction and agreement:** the sample is drawn with a recorded seed; agreement is per field; disagreements are listed and never auto-resolved.
10. **Audit:** sample size per decision 37 rule; error rate reported; ceiling advisory in `pilot`, gate in `systematic`.
11. **Corrections supersede:** a corrected extraction is a new record superseding the old; both remain in the log.
12. **Comparability:** `report_evidence` never ranks across groups; each frontier point traces to its rows; empty or single-source groups are stated.
12a. **Cost axes:** frontiers use only params and FLOPs/MACs; a throughput or latency value never appears in a cross-paper comparison, only as a within-paper ratio with its baseline and hardware.
13. **PRISMA:** full-text boxes (sought, not retrieved, assessed, excluded with reasons) are derived from events.
14. **Trace:** `trace` from a table cell returns cell → extraction → document version → retrieval attempt → work → screening decisions → protocol → question.
15. **Local library:** a test fails if any raw source or canonical document is written to a git-tracked path; deleting a library entry makes `check` report it, and re-fetching restores the same hash (or records a changed source).
16. **Pilot end-to-end:** the linear-attention pilot reaches an evidence report with at least the ImageNet-1K classification group populated, reproducible from committed events plus the local library. The run also reports conversion quality on the pilot's included works against the bake-off result (decision 47).
17. **Quality:** `mypy --strict` and ruff pass; coverage ≥ 90% for `services/` and `model/`.

## Proposed sub-plans
| Plan | Content |
| --- | --- |
| A | Acquisition routes, attempts, version rule, researcher-supplied import, local library |
| B | Markdown conversion: converter bake-off, anchors, tables, `document_read` |
| C | Full-text screening and full PRISMA |
| D | Schema, extraction, verification, dual extraction, agreement, audit |
| E | Evidence report, trace extensions (the `ml-benchmark` pack was built in plan D; reconciled 2026-11-04) |

## Open questions
1. **Converters:** which tool per input format (LaTeXML HTML, LaTeX source, PDF: deterministic parser such as PyMuPDF vs. layout-model tools such as Docling or GROBID) to reach Markdown. Criteria: determinism, table fidelity, offline, licence. Decided by a bake-off on a fixed off-topic ML test set (plan B, decision 47); re-checked on the pilot's included works in the end-to-end run.

Settled: version rule (latest available version), throughput (within-paper ratios only), storage (local library, no literature in git), appraisal (deferred), PubMed/PMC (moved to the first biomedical project), copied-result consistency check (later). See decisions 39–42, 44.

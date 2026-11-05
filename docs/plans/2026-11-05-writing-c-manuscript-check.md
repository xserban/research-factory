# Claim Verification of External Manuscripts Implementation Plan (slice 7b, sub-plan W-C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** The whole plan is Later (spec v1 scope). Its gates are `manuscript.citation_confirm` (presets as `reference.link_confirm`) and `manuscript.audit_label` (floor `human`).

> **Dependencies.** W-B merged (verdict vocabulary `Verdict`, audit rule and ceiling, independence pattern). G1 merged (`references/markers.py`, `references/parse.py`, `references/match.py`, resolution thresholds and the human confirmation rule of slice-3a ruling 3). Plans B/C (`document_read`, pinned conversions, `quote_in_element`). PDF manuscripts are out of this plan (decision 49 now names docling); this plan accepts Markdown, LaTeX and plain text.

**Goal:** Check each cited sentence of a manuscript the factory did not write (a paper, grant or review) against the cited source in the corpus, with verdicts anchored to verbatim quotes of the source, while the manuscript's text never enters git.

**Architecture:** `writing/segment.py` (pure, versioned) splits text into sentences with offsets; `writing/bibfile.py` (pure) reads a companion `.bib` or CSL-JSON into minimal records; `writing/cites.py` finds citation keys per sentence. `services/manuscripts.py` stores the manuscript in the library, records segmentation and resolution events, serves verification units and records verdicts. The agent reads the sentence through `manuscript_read` and the source through `document_read`; no task content contains manuscript text.

**Tech Stack:** stdlib `re`, `unicodedata`; no new runtime dependency.

**Spec:** `docs/specs/slice-7b-views-writing.md` rulings 8 (manuscripts), 12 (audit), 17; Events (manuscript rows); acceptance 12. R-32 (verified quotes), R-47, R-51; decision 39.

## Rulings made in this plan
1. **Segmenter [confirm].** `SEGMENTER_VERSION = 1`. Input normalised (NFC, LaTeX comments stripped, `\begin{…}`/`\end{…}` of figure, table, equation and bibliography environments masked, Markdown code blocks and headings masked). Sentence boundary: `.`, `?`, `!` followed by whitespace and an uppercase letter, digit, `\` or `[`, unless the preceding token is in `ABBREVIATIONS` (as W-A ruling 5 plus `al.`, `Sec.`, `Tab.`, `approx.`, `resp.`); a paragraph break always ends a sentence. Offsets are into the stored bytes decoded as UTF-8. A segmenter change is a new version; existing segmentations stay valid for their units.
2. **Citation forms.** LaTeX `\cite`, `\citep`, `\citet`, `\parencite`, `\textcite`, `\autocite` (keys split on `,`); pandoc `[@key]`, `@key`; numeric markers `[n]`, `[n–m]` mapped to entries of a reference-list section via G1 `references/markers.py` and `references/parse.py`. A sentence may carry several keys.
3. **Resolution.** Each bibliography record is matched to works with G1's matcher: identifier (DOI, arXiv) or exact title resolve; fuzzy matches above the G1 threshold are `proposed` and need `manuscript.citation_decided` by a human; below threshold or not in the corpus → `unresolved`. No second-agent confirmation (the manuscript is not the project's own evidence).
4. **Units.** One unit per (sentence, resolved cited work). A unit whose work has no pinned conversion is closed by the platform as `cannot-verify: no-full-text`; one whose key is unresolved as `cannot-verify: citation-unresolved`; a resolved work outside the corpus as `source-not-in-corpus`. These closures are system events, computed, not agent verdicts.
5. **Verdicts.** The W-B vocabulary plus the verifier's anchor and quote from the cited work's pinned conversion (checked with `quote_in_element`), and `sentence_span` as character offsets inside the sentence (not text). `supported`, `partial`, `contradicted`, `overstated` require a quote; `unsupported` may have none (the verifier read the source and found nothing). Optional advisory flag `uncited-claim` on an uncited sentence (recorded by a verifier session, never counted as a verdict).
6. **Independence.** The session that added the manuscript (CLI, human) is not an agent; verifier sessions are agents; dual verification is not required; the audit of W-B ruling 5 applies per manuscript to `supported` verdicts.

## Global Constraints
- No manuscript text in any event, blob, error, finding or task content: sentences are referenced by (manuscript id, ordinal, offsets, sha256).
- Manuscripts and companion bibliographies live in the library (`project.library`), never in git; `manuscript add` copies the bytes into the library and never moves or modifies the original file.
- Every verdict carries model, `rf-verify@<hash>`, `input_blob` (ids only).
- Tools refused to pass sessions; adding, resolving and auditing are CLI (or relayed human answers).
- TDD; `uv run pytest -m "not network and not slow"`; `mypy --strict`; ruff; coverage ≥ 90%.

## Review Focus
1. Scan every event and blob written during the acceptance fixture for any manuscript sentence: none found (Task 5, `test_no_manuscript_text_outside_library`).
2. A verdict whose quote is not in the cited work's pinned conversion is refused (Task 4, `test_quote_must_be_in_cited_conversion`).
3. Abbreviations and LaTeX environments do not split or leak sentences (Task 1, `test_segmenter_cases`).
4. A fuzzy citation does not create a unit until a human decides it (Task 3, `test_fuzzy_waits_for_human`).

## File Structure
- Create `writing/segment.py`, `writing/bibfile.py`, `writing/cites.py`, `model/manuscripts.py`, `index/manuscripts.py`, `services/manuscripts.py`.
- Modify `index/default.py`, event catalog, `services/trace.py`, `services/check.py`, `mcp/server.py`, `cli/main.py`, `plugin/skills/rf-verify/SKILL.md` (manuscript section).
- Tests: `tests/test_segment.py`, `tests/test_bibfile.py`, `tests/test_cites.py`, `tests/test_manuscripts_add.py`, `tests/test_manuscripts_resolve.py`, `tests/test_manuscripts_verify.py`, `tests/test_manuscripts_report.py`.

## Self-review notes
- PDF manuscripts: add `fmt = "pdf"` by converting with the chosen converter into canonical Markdown (stored in the library) and segmenting that; no change to events beyond a `conversion` reference.
- `uncited-claim` flags are advisory and never enter counts of verdicts.

## Later (not v1)

Moved here by the v1 cut of 2026-11-04 (decision 74); built after the v1 plans of the build order (`2026-11-05-build-order.md`), in the order listed. Task text is unchanged; references to "Task N" inside a moved task use the plan's original numbering.

### Later L1 (was Task 1): Segmenter, bibliography reader, citation finder (pure)

*Tier: standard.*

**Files:** Create `writing/segment.py`, `writing/bibfile.py`, `writing/cites.py`; Tests as listed.

**Interfaces:**
- Produces: `SEGMENTER_VERSION = 1`; `@dataclass(frozen=True) Segment(ordinal: int, start: int, end: int, sha256: str)`; `segment(text: str, fmt: Literal["markdown", "latex", "text"]) -> list[Segment]`; `@dataclass(frozen=True) BibRecord(key: str, title: str | None, authors: tuple[str, ...], year: int | None, doi: str | None, arxiv: str | None)`; `read_bib(text: str) -> list[BibRecord]` (BibTeX subset: `@type{key, field = {…} | "…" | number}`, nested braces; unknown entry types kept); `read_csl(text: str) -> list[BibRecord]`; `cite_keys(sentence: str, fmt) -> tuple[str, ...]`.

- [ ] **Step 1: Tests.** `test_segmenter_cases` (et al., e.g., decimals `85.2`, `Fig. 3`, LaTeX `\cite{a,b}.` at end, masked equation with a period, paragraph break; Review Focus 3); `test_offsets_cover_text_in_order`; `test_sha256_of_slice`; `test_read_bib_nested_braces_and_strings`; `test_read_csl_minimal`; `test_cite_keys_latex_pandoc_numeric`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(manuscripts): segmenter, bibliography reader, citation finder`.

### Later L2 (was Task 2): Adding a manuscript

*Tier: standard.*

**Files:** Create `model/manuscripts.py`, `index/manuscripts.py`, `services/manuscripts.py`; Modify `index/default.py`, event catalog; Test `tests/test_manuscripts_add.py`.

**Interfaces:**
- Produces: `MANUSCRIPT_ID_RE = rf"^msc_{ULID_RE}$"`; events `manuscript.added` (`manuscript_id`, `library_hash`, `format`, `bib_hash: str | None`, `label`) and `manuscript.segmented` (`manuscript_id`, `segmenter`, `sentences: list[{ordinal, start, end, sha256, keys}]`); tables `manuscripts`, `manuscript_sentences`; `add_manuscript(project, path: Path, *, fmt, bib: Path | None, label: str, actor: Actor) -> str` (copies bytes into `project.library`, writes both events; human actor only).

- [ ] **Step 1: Tests.** `test_add_stores_in_library_not_blobs`; `test_events_carry_no_text` (no sentence substring of length ≥ 20 appears in either payload); `test_label_is_free_text_but_bounded` (≤ 80 chars; documented as the researcher's own label); `test_rebuild_identical`; `test_agent_actor_refused`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(manuscripts): add and segment external manuscripts`.

### Later L3 (was Task 3): Citation resolution

*Tier: standard.*

**Files:** Modify `services/manuscripts.py`, `model/manuscripts.py`, `index/manuscripts.py`; Test `tests/test_manuscripts_resolve.py`.

**Interfaces:**
- Consumes: G1 matcher entry point (`references/match.py`; the implementer uses the function G1 exposes for matching a parsed entry to works, with its thresholds), numeric-marker mapping from `references/markers.py`.
- Produces: events `manuscript.citation_resolved` (`manuscript_id`, `key`, `work_id | None`, `method`, `score`, `state: resolved|proposed|unresolved`), `manuscript.citation_decided` (`manuscript_id`, `key`, `decision: confirm|reject`, human); `resolve_citations(project, manuscript_id) -> ResolutionSummary`; `decide_citation(project, manuscript_id, key, decision, *, actor) -> str`; `units(project, manuscript_id) -> list[UnitRow]` (with system closures of ruling 4 recorded as `manuscript.unit_closed` events by `resolve_citations`).

- [ ] **Step 1: Tests.** `test_identifier_and_title_exact_resolve`; `test_fuzzy_waits_for_human` (Review Focus 4); `test_unresolved_closes_unit`; `test_no_full_text_closes_unit`; `test_outside_corpus_closes_unit`; `test_numeric_markers_map_to_reference_section`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(manuscripts): resolve citations to corpus works`.

### Later L4 (was Task 4): Verification units and verdicts

*Tier: critical (quote verification, provenance).*

**Files:** Modify `services/manuscripts.py`, `model/manuscripts.py`, `index/manuscripts.py`; Test `tests/test_manuscripts_verify.py`.

**Interfaces:**
- Consumes: `Verdict` (W-B), `quote_in_element`, pinned conversion lookup (plan C/D), task queue.
- Produces: `manuscript_verify_next(project, manuscript_id, *, actor) -> MsUnit | None` (`{task_id, manuscript_id, ordinal, work_id, conversion_id}`; ids only); `manuscript_read(project, manuscript_id, ordinal, *, context: int = 1) -> SentenceText` (reads the library; returns the sentence and up to `context` neighbours, marked; refused to pass sessions); event `manuscript.verified` (`verdict_id` `mvd_<ULID>`, unit, `verdict`, `sentence_span: tuple[int, int] | None`, `anchor`, `quote`, `conversion_id`, `note`, `uncited_flag: bool`); `manuscript_verify_record(project, task_id, verdict, *, sentence_span, anchor, quote, note, actor, input_blob) -> str`; audit functions reuse `services/draft_audit.py` parameterised by subject (`draft` | `manuscript`).

- [ ] **Step 1: Tests.** `test_quote_must_be_in_cited_conversion` (Review Focus 2); `test_span_offsets_inside_sentence`; `test_unit_content_ids_only`; `test_verdict_provenance`; `test_audit_sample_for_manuscript`; `test_no_text_in_errors`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(manuscripts): verification units and anchored verdicts`.

### Later L5 (was Task 5): Report, trace, check, tools, CLI

*Tier: standard.*

**Files:** Modify `services/manuscripts.py`, `services/trace.py`, `services/check.py`, `mcp/server.py`, `cli/main.py`, `plugin/skills/rf-verify/SKILL.md`; Test `tests/test_manuscripts_report.py`.

**Interfaces:**
- `manuscript_report(project, manuscript_id) -> ManuscriptReport` (per sentence ordinal: keys, units, verdicts, closures; counts by verdict; audit summary; no text); CLI `factory manuscript report MSC [--out PATH]` joins sentence text from the library at render time.
- Trace kind `manuscript_unit` (`msc_…/<ordinal>/<work_id>`): back to verdicts → quote anchor → conversion → document → work.
- Check: `manuscript-citation-unresolved` (count; advisory), `manuscript-unverified` (units without verdict).
- MCP: `manuscript_verify_next`, `manuscript_read`, `manuscript_verify_record`. CLI: `factory manuscript add PATH --format F [--bib PATH] --label L`, `status`, `resolve MSC [--confirm KEY|--reject KEY]`, `report`, `audit`.

- [ ] **Step 1: Tests.** `test_report_counts_derived`; `test_cli_report_reads_library_text`; `test_mcp_report_has_no_text`; `test_trace_unit_to_document`; findings in constructed cases; `test_no_manuscript_text_outside_library` (Review Focus 1: walk `events/` and `blobs/` after an end-to-end fixture).
- [ ] **Step 2–4.** **Step 5:** Commit `feat(manuscripts): report, trace, check, tools and commands`.

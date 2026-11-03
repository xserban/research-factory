# Canonical Markdown and Converter Bake-off Implementation Plan (slice 2, sub-plan B1 of B1–B2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Context:** Slice 2 runs A → B → C → D → E without pilot data (decision 47). Plan A, full-text acquisition, is merged. Plan B is split into two parts:
- **B1 (this plan):** the converter-independent canonical Markdown model, our own LaTeXML-HTML converter, and a bake-off that chooses one converter per input format. It ends with decision 49.
- **B2 (written after decision 49):** wires the winning converters into the platform, records `document.converted` events, and provides `document_read`.

**Goal:** One deterministic definition of canonical Markdown with stable anchors, which every converter's output passes through. The bake-off then measures the candidate converters on a fixed off-topic set and records the choice per format.

**Architecture:**
- **In `platform/` (TDD):** `factory/document/` holds the anchor grammar and manifest, normalisation, the *anchoriser* that turns any converter's plain Markdown into canonical Markdown with `<a id>` anchors, the `Converter` contract with a reusable contract test kit, and our own LaTeXML-HTML converter. External tools never write anchors: every converter emits plain Markdown, and the anchoriser alone assigns anchors. One scheme therefore holds across formats.
- **In `experiments/converter-bakeoff/` (TDD-exempt):** the corpus list, the fetch, the external-tool adapters (pandoc, Docling, PyMuPDF4LLM, GROBID), the runner, the scoring and the report.

**Tech Stack:** as plan A, plus `lxml` and `markdown-it-py` (core platform, pure Python wheels). Bake-off only: pandoc (pinned binary), `docling`, `pymupdf4llm`, GROBID (pinned release, local Java). None of these enter the platform until B2, and then only as optional extras.

**Spec:** `docs/specs/slice-2.md` (Canonical document; Open question 1; acceptance 2, 3, 7 in part). Decisions 39, 40, 46, 47, 48 and 49 (added by Task 7). Rulings below confirmed by the researcher on 2026-11-03.

## Rulings made in this plan (recorded in decision 49 together with the bake-off result)

1. **Structure:** B1 delivers the model, our HTML converter and the bake-off. B2 delivers the platform adapters for the winners, the events and `document_read`.
2. **Candidates:**
   - HTML: our own `latexml-html` (lxml) and `pandoc`.
   - LaTeX source: `pandoc`.
   - PDF: `docling`, `pymupdf4llm`, `grobid`.
   - Not entered: Marker and MinerU (heavy, restrictive licences), local LaTeXML (needs Perl and TeX), Nougat (generative; decision 40).
3. **Dependencies:** heavy or external converters enter the platform only as optional extras or as pinned external tools probed at start-up. A missing one makes conversion report `converter-unavailable` and never crashes. Its tests skip when it is absent.
4. **Anchors** are HTML anchor tags `<a id="…"></a>` on their own line, directly before the element. Table-cell anchors (`t2.r5.c3`) are derived from position and never written into the Markdown.
5. **Anchor index:** the manifest (anchor → kind, parent, text) is derived from the canonical Markdown by `parse_manifest`. In B2 it is stored next to the Markdown in the library, and the event carries only hashes and counts. Git never holds document text.
6. **Trigger** (B2): conversion runs only through `factory document convert`. Agents never trigger it.
7. **Default document** (B2): `document_read(work)` returns the first converted live document in route order (arxiv-html > arxiv-source > oa-pdf > researcher-supplied). `document_id` overrides this.
8. **Read gate** (B2): the work is `INCLUDED` and the document is converted. The call is refused to sessions that have joined a title/abstract pass. Plan C adds the full-text stage gate and plan D adds the schema gate.

## Global Constraints

- All plan-A constraints hold. No model calls, and no LLM in conversion (decision 40).
- Canonical Markdown rules (verbatim invariants for `normalise`):
  - UTF-8, Unicode NFC and LF line endings.
  - No trailing whitespace, and at most one blank line between blocks.
  - The file ends with exactly one `\n`.
  - Tabs inside table cells become single spaces.
  - Ligatures and dashes are **kept**, because quote matching normalises them in plan C/D and not here.
- **Anchor grammar** (`ANCHOR_RE`):

  ```
  ^(?:s\d+(?:\.\d+)*(?:\.p\d+)?|p\d+|t\d+|f\d+\.cap|e\d+)$
  ```

  - Sections are `s<n>[.<n>…]`, with paragraphs `.p<k>` under them.
  - Paragraphs before the first heading go under `s0`, as `s0.p<k>`.
  - Tables are `t<n>`; cells are `t<n>.r<r>.c<c>` with a 1-based row that counts the header row as `r1`. Cells are derived only and are never written into the Markdown.
  - Figure captions are `f<n>.cap`, display equations `e<n>`, and PDF page markers `p<n>`.
  - A table's caption paragraph belongs to the table as `t<n>` text and gets no separate anchor.
- **Determinism:** the same input bytes and the same converter version give byte-identical Markdown. `anchorise` is idempotent.
- **Literature location:** no literature text in any git-tracked path. The bake-off's raw sources and outputs live in `experiments/converter-bakeoff/data/`, which is git-ignored. The committed report holds numbers and arXiv IDs only.
- **The corpus contains no linear-attention, efficient-attention or vision-transformer-efficiency papers** (decision 47), and `docs/pilot/heldout-seeds.md` is never opened.
- Branch `plan-2b1-converter-bakeoff`. Same commit trailer and model tiers as plan A. Platform commands run from `platform/`.

## Review Focus

1. **A heading has no number, or numbers that skip or repeat** (e.g. "Related Work" between "2" and "3", or two "A.1" sections in the appendices). Expected: unnumbered headings get the next ordinal at their level. The anchor id still never repeats: on a collision, append `.<k>` with k ≥ 2 to the second occurrence. → Task 2 `test_unnumbered_and_duplicate_headings`.
2. **A table with merged cells (colspan/rowspan) or a multi-row header.** Expected: the table is rectangular in Markdown, with the spanning text in the top-left cell of the span and the remaining cells empty, so `t.rN.cM` positions are stable and documented. → Task 4 `test_colspan_rowspan_rectangular`.
3. **Converter output that already contains `<a id>` tags or raw HTML.** Expected: existing anchors are stripped and recomputed, other inline HTML is kept as text, and `anchorise` is idempotent. → Task 2 `test_existing_anchors_replaced`, `test_idempotent`.
4. **A pipe character or a newline inside a table cell** (common in math, e.g. `|x|`). Expected: the pipe is escaped as `\|`, a newline becomes a space, and the column count is unchanged. → Task 2 `test_cell_pipe_and_newline`.
5. **The same paper converted on another run or machine.** Expected: an identical hash. The bake-off's determinism score runs each candidate twice in fresh processes, and any difference disqualifies the candidate for that format. → Task 6 determinism column.

---

## File Structure

```
platform/src/factory/document/__init__.py
platform/src/factory/document/anchors.py      ANCHOR_RE, AnchorKind, Anchor, Manifest, parse_manifest
platform/src/factory/document/normalise.py    normalise, escape_cell
platform/src/factory/document/anchorise.py    anchorise
platform/src/factory/document/converter.py    Converter, ConversionResult, ConverterUnavailable, convert
platform/src/factory/document/latexml_html.py LatexmlHtmlConverter
platform/tests/document/test_anchors.py, test_normalise.py, test_anchorise.py,
  test_converter_contract.py (kit: assert_converter_contract), test_latexml_html.py
platform/tests/fixtures/document/             tiny synthetic LaTeXML pages (written for the tests)
experiments/converter-bakeoff/
  pyproject.toml          own uv project; depends on ../../platform (path) + candidate tools
  README.md               how to run; pinned tool versions
  corpus.toml             arXiv ids, hard-case tags, approval line
  fetch.py, adapters/{pandoc,docling,pymupdf4llm,grobid}.py, run.py, score.py, report.py
  results/bakeoff-<date>.md   committed: numbers only
  data/                   git-ignored (raw + outputs)
.gitignore                + experiments/*/data/
docs/decisions.md         + 49
```

---

### Task 1: Anchor grammar and manifest

**Files:**
- Create: `platform/src/factory/document/{__init__,anchors}.py`
- Test: `platform/tests/document/test_anchors.py`
- Modify: `platform/pyproject.toml` (add `markdown-it-py>=3`, `lxml>=5`; `types-lxml` in dev)

**Interfaces:**
- Produces:
  - `ANCHOR_RE`.
  - `class AnchorKind(StrEnum)`: `SECTION`, `PARAGRAPH`, `TABLE`, `CELL`, `FIGURE_CAPTION`, `EQUATION`, `PAGE`.
  - `@dataclass(frozen=True) class Anchor`: `id: str`, `kind: AnchorKind`, `parent: str | None`, `text: str`. Text is the element's Markdown source without the anchor line. A cell's text is unescaped and stripped.
  - `@dataclass(frozen=True) class Manifest`: `anchors: tuple[Anchor, ...]` in document order; `get(id) -> Anchor | None`; `to_json() -> bytes` (canonical JSON).
  - `parse_manifest(markdown: str) -> Manifest` reads anchor tags with `markdown-it-py` (CommonMark plus the GFM table rule) and derives the cells of every `t<n>` table.
  - `ManifestError(FactoryError)` is raised for: duplicate id, id not matching `ANCHOR_RE`, an anchor not directly followed by an element, a paragraph whose section prefix is not an existing section, or a non-rectangular table.

- [ ] **Step 1: Write the failing tests**

```python
MD = '<a id="s1"></a>\n# 1 Intro\n\n<a id="s1.p1"></a>\nText.\n\n<a id="t1"></a>\n| a | b |\n|---|---|\n| 1 | 2 |\n'
def test_manifest_lists_sections_paragraphs_tables_and_cells():
    m = parse_manifest(MD)
    assert [a.id for a in m.anchors] == ["s1", "s1.p1", "t1", "t1.r1.c1", "t1.r1.c2", "t1.r2.c1", "t1.r2.c2"]
    assert m.get("t1.r2.c2").text == "2" and m.get("t1.r2.c2").parent == "t1"
def test_duplicate_anchor_rejected(): ...
def test_anchor_without_following_element_rejected(): ...
def test_paragraph_under_unknown_section_rejected(): ...
def test_cell_ids_never_written_in_markdown(): ...     # '<a id="t1.r1.c1">' → ManifestError
def test_manifest_json_is_canonical_and_stable(): ...
```

- [ ] **Step 2–4:** Run `uv run pytest tests/document/test_anchors.py -v` → FAIL. Implement. Run → PASS.
- [ ] **Step 5: Commit** `feat(document): anchor grammar and manifest`

---

### Task 2: Normalisation and the anchoriser

**Files:**
- Create: `platform/src/factory/document/{normalise,anchorise}.py`
- Test: `platform/tests/document/test_normalise.py`, `test_anchorise.py`

**Interfaces:**
- Produces:
  - `normalise(markdown: str) -> str`, applying the Global Constraints rules.
  - `escape_cell(text: str) -> str`: `|` becomes `\|`, a newline becomes a space, then strip.
  - `anchorise(markdown: str) -> str` returns canonical Markdown. `parse_manifest(anchorise(x))` never raises, and `anchorise(anchorise(x)) == anchorise(x)`.
- Rules (the algorithm the tests pin):
  1. Strip every existing `<a id="…"></a>` line, then `normalise`.
  2. Headings: a leading number (`3`, `3.2`, `A.1`, roman numerals are not recognised) gives the section path. An appendix letter `A` maps to `a1`… so the path stays numeric: `A.1` becomes `s101.1` (100 + letter index).
     - An unnumbered heading takes the next ordinal at its level, under its parent heading.
     - A collision takes the `.<k>` suffix (Review Focus 1).
     - `#` depth is used only for unnumbered headings.
  3. Paragraphs are numbered per section from 1, as `<section>.p<k>`.
  4. Each GFM table gets the next `t<n>`. A paragraph immediately before or after a table that starts with `Table <n>` (case-insensitive) is the table's caption: it gets no anchor and moves to directly below the table.
  5. A paragraph that starts with `Figure <n>` or `Fig. <n>` gets `f<n>.cap`, using the number from the text (falling back to an ordinal). It is kept in place.
  6. A display math block `$$…$$` gets the next `e<n>`.
  7. A form feed `\f` on its own line (emitted by PDF converters) becomes `<a id="p<n>"></a>` with no element (the page anchor is the one exception to the "followed by an element" rule). The paragraph numbering is unaffected.

- [ ] **Step 1: Failing tests:**
  - `test_normalise_rules` (each rule one assertion)
  - `test_numbered_headings_give_section_paths`
  - `test_unnumbered_and_duplicate_headings`
  - `test_appendix_letters`
  - `test_paragraphs_numbered_per_section`
  - `test_table_caption_attached`
  - `test_figure_caption_anchor_uses_text_number`
  - `test_display_math_equation_anchor`
  - `test_form_feed_page_anchor`
  - `test_existing_anchors_replaced`
  - `test_idempotent` (over all the fixtures above)
  - `test_cell_pipe_and_newline`
  - `test_preamble_paragraphs_under_s0`
- [ ] **Step 2–4:** Run → FAIL. Implement. Run → PASS.
- [ ] **Step 5: Commit** `feat(document): canonical normalisation and anchoriser`

---

### Task 3: Converter contract and contract test kit

**Files:**
- Create: `platform/src/factory/document/converter.py`; `platform/tests/document/test_converter_contract.py`
- Test: as above, plus `platform/tests/document/kit.py`

**Interfaces:**
- Produces:

```python
class ConverterUnavailable(FactoryError): ...       # tool missing; message names the tool
@dataclass(frozen=True)
class ConversionResult:
    markdown: str                    # canonical (anchorised)
    manifest: Manifest
    markdown_hash: str               # sha256:<hex> of markdown UTF-8
    converter: str                   # e.g. "latexml-html"
    converter_version: str           # converter's own version + tool version, e.g. "1.0+lxml5.3.0"
    warnings: tuple[str, ...]        # e.g. "table t3: ragged rows padded"
class Converter(Protocol):
    name: str
    accepts: frozenset[str]          # media types from plan A (text/html, application/x-eprint-tar, application/pdf …)
    def version(self) -> str: ...    # raises ConverterUnavailable when the tool is absent
    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]: ...  # plain Markdown + warnings
def convert(converter: Converter, raw: bytes, media_type: str) -> ConversionResult
```

- `convert` refuses a media type that is not in `accepts` with a `FactoryValidationError` on field `media_type`. It then applies `anchorise` and builds the manifest; a `ManifestError` propagates.
- The kit provides `assert_converter_contract(converter, samples: list[tuple[bytes, str]])`. It checks determinism (convert twice, equal hash), idempotence of anchorising the output, a valid manifest, and that the version string is non-empty.

- [ ] **Step 1: Failing tests** (a stub converter returning fixed Markdown): `test_convert_anchorises_and_hashes`, `test_unaccepted_media_type_refused`, `test_unavailable_tool_raises`, `test_kit_detects_nondeterminism` (a stub that appends a counter → the kit fails).
- [ ] **Step 2–4:** Run → FAIL. Implement. Run → PASS.
- [ ] **Step 5: Commit** `feat(document): converter contract and test kit`

---

### Task 4: Our LaTeXML-HTML converter

**Files:**
- Create: `platform/src/factory/document/latexml_html.py`; fixtures `platform/tests/fixtures/document/latexml_*.html`. These are small synthetic pages written by hand in LaTeXML's class vocabulary; no real paper is used.
- Test: `platform/tests/document/test_latexml_html.py`

**Interfaces:**
- Produces: `LatexmlHtmlConverter` with `name = "latexml-html"`, `accepts = {"text/html"}`, `version() = f"{CONVERTER_VERSION}+lxml{lxml.__version__}"` and `CONVERTER_VERSION = "1.0"`.
- Mapping (LaTeXML class → Markdown):
  - The document title `ltx_title_document` is a `#` heading with no number.
  - `ltx_section` / `ltx_subsection` / `ltx_subsubsection` / `ltx_appendix` titles become `##`/`###`/`####` headings, keeping their `ltx_tag` number as text (e.g. `## 3 Method`, `### 3.2 Setup`, `## A Proofs`).
  - `ltx_para > ltx_p` → paragraph.
  - Inline `math` → `$alttext$`; `ltx_equation` / `ltx_equationgroup` → `$$alttext$$`.
  - `ltx_tabular` → a GFM table. The first row is the header; if the table has no `thead`, its first row is the header. Spans are handled per Review Focus 2, and cell text goes through `escape_cell`.
  - A `ltx_caption` of a table becomes the paragraph `Table <n>: …`. A figure caption becomes `Figure <n>: …`. Images are dropped.
  - Bibliography (`ltx_bibliography`) → a `## References` heading with one paragraph per `ltx_bibitem`.
  - Footnotes → a paragraph at the end of their section, as `[^n] text`.
  - Everything else: text content only, never raw HTML.

- [ ] **Step 1: Failing tests:**
  - `test_contract` (the kit over all fixtures)
  - `test_sections_keep_numbers`
  - `test_inline_and_display_math_use_alttext`
  - `test_table_to_gfm_with_caption`
  - `test_colspan_rowspan_rectangular`
  - `test_bibliography_items_are_paragraphs`
  - `test_no_raw_html_in_output` (no `<` except the anchor lines)
- [ ] **Step 2–4:** Run → FAIL. Implement. Run → PASS.
- [ ] **Step 5: Commit** `feat(document): LaTeXML HTML converter`

---

### Task 5: Bake-off corpus and fetch (experiment, TDD-exempt)

**Files:**
- Create: `experiments/converter-bakeoff/{pyproject.toml,README.md,corpus.toml,fetch.py}`; modify `.gitignore` (`experiments/*/data/`)

**Steps:**
- [ ] **Step 1: Propose the corpus.** List 18 arXiv IDs from 2019–2025 in ML areas other than attention efficiency (e.g. RL, diffusion, graph learning, optimisation theory, speech, tabular, NLP evaluation). Choose by hard case, with at least 4 papers per tag:
  - `dense-tables`: large results tables with multi-row headers or spans
  - `heavy-math`: proofs, aligned equations
  - `two-column-pdf`: conference template
  - `custom-macros`: the LaTeX source defines many `\newcommand`s
  - `appendix`: long appendices with lettered sections

  Every paper must have arXiv HTML, a LaTeX source and a PDF. Record each paper as `{id, title, tags}` in `corpus.toml`.
- [ ] **Step 2: Off-topic guard.** `fetch.py --check` fails if any title or abstract (from the arXiv API) matches `/(linear|efficient|sub-?quadratic|kernel(ized)?)\s+attention|vision transformer|\bViT\b|token (pruning|merging)/i`.
- [ ] **Step 3: Researcher approval.** Show the list to the researcher. On approval, write `approved = "<name> <date>"` in `corpus.toml`. `fetch.py` refuses to run without it.
- [ ] **Step 4: Fetch.** Use `ArxivHtmlRoute`, `ArxivSourceRoute` and a direct arXiv PDF GET (`https://arxiv.org/pdf/<id>v<N>`) through `default_http`. Write `data/raw/<id>/{html,eprint,pdf}` and `data/raw/<id>/meta.json` (version and hashes). No platform project or events are involved: this is an experiment.
- [ ] **Step 5: Commit** `chore(bakeoff): corpus, guard and fetch` (no `data/`).

---

### Task 6: Candidate adapters, runner and scoring (experiment, TDD-exempt)

**Files:**
- Create: `experiments/converter-bakeoff/adapters/{pandoc,docling,pymupdf4llm,grobid}.py`, `run.py`, `score.py`

**Steps:**
- [ ] **Step 1: Adapters.** Each one implements `factory.document.converter.Converter` and returns plain Markdown. `factory.document.convert` does the anchorising.
  - **pandoc** (pinned version in the README):
    - HTML: `-f html -t gfm`.
    - LaTeX: unpack the e-print, find the main `.tex` (the one with `\documentclass`), run `-f latex -t gfm` with the archive as the working directory.
  - **docling:** `DocumentConverter` with OCR disabled; `export_to_markdown()`; page breaks emitted as `\f`.
  - **pymupdf4llm:** `to_markdown(page_chunks=True)` joined with `\f`.
  - **grobid:** pinned release run locally (`./gradlew run` or the JAR) at `localhost:8070`; `processFulltextDocument`; TEI to Markdown in the adapter (head/div → headings with `n`, p, figure[type=table] → GFM table, formula → `$$…$$`).
  - Each adapter's `version()` includes the tool version, and the model weight hash for Docling.
- [ ] **Step 2: Runner.** `run.py` converts every (paper, candidate, format) pair twice in two fresh subprocesses. It writes `data/out/<candidate>/<id>.md` and appends `results/runs.jsonl` with `{id, candidate, format, hash1, hash2, seconds, pages, warnings, error}`. A failed conversion is recorded and never retried silently.
- [ ] **Step 3: Scoring.** `score.py` computes per candidate and format:
  - (a) **determinism:** the share of papers where `hash1 == hash2`. Anything below 1.0 disqualifies the candidate.
  - (b) **seconds per page**, median and p90.
  - (c) **structure:** the section count and table count against the reference, which is the LaTeXML HTML through `latexml-html`.
  - (d) **table fidelity:** for each reference table, the best-matching candidate table, scored as the F1 of the multiset of numeric tokens (`[-+]?\d+(\.\d+)?%?`) and the exact-cell-position agreement of those numbers.
  - (e) **failures** (exceptions, empty output).

  The reference is our own converter, so (c) and (d) do not score `latexml-html` itself. Its own quality, and the human check of the reference, come from Step 4.
- [ ] **Step 4: Human spot check.** `score.py --sheet` writes `data/sheet.csv` with 30 random tables (seed 49, recorded), stratified across formats. Each row has the candidate's cells next to a link to the arXiv HTML table. The researcher marks every table `correct / minor / wrong`. The sheet stays in `data/` and only the counts go to the report.
- [ ] **Step 5: Commit** `chore(bakeoff): adapters, runner, scoring`

---

### Task 7: Bake-off report and decision 49

**Files:**
- Create: `experiments/converter-bakeoff/results/bakeoff-<date>.md`
- Modify: `docs/decisions.md` (49), `docs/specs/slice-2.md` (close open question 1)

**Steps:**
- [ ] **Step 1: Run.** Run `uv run python run.py && uv run python score.py && uv run python report.py`. The report holds a table per format (candidate × criteria a–e and the human counts), the pinned versions, the seeds, and the corpus IDs. It contains no document text.
- [ ] **Step 2: Choose a converter per format** by this rule:
  1. Exclude any candidate with determinism < 1.0.
  2. Among the rest, highest table fidelity (d) wins.
  3. Fidelity within 0.02 counts as a tie; break it by seconds per page.
  4. A licence issue (AGPL for `pymupdf4llm`, GPL for pandoc as a subprocess) is stated and accepted or rejected by the researcher in the decision.
  5. If no PDF candidate reaches fidelity 0.8, record that, and recommend for B2 that PDF-only documents be marked `quality = pdf-text-low`.
- [ ] **Step 3: Record decision 49.** It holds rulings 1–8 above, the converter per format with versions, and a pointer to the report. Close slice-2 open question 1 with a link to decision 49.
- [ ] **Step 4: Commit** `docs: decision 49 converter choice; bake-off report`

---

## Self-review notes

- **Spec coverage:**
  - "Everything is converted to Markdown": the model in Tasks 1–3 and the converters in Tasks 4–6, wired into the platform in B2.
  - The anchor kinds `#s3.2`, `#s3.2.p4`, `#t2`, `#t2.r5.c3`, `#f4.cap`, `#e7`, `#p6`: `ANCHOR_RE` and Tasks 1–2.
  - Deterministic cell addresses: Task 1 `parse_manifest`. Deterministic, offline, pinned converters: Tasks 3 and 6.
  - The bake-off (open question 1): Tasks 5–7.
  - AC 2: determinism of the model is covered in Tasks 2–3; the hash equality across a recorded event is B2.
  - AC 3 (new version on re-conversion) and AC 7 (cell resolves to exactly one cell): manifest uniqueness here, verification against values in plan D.
- **Left to B2:**
  - optional extras packaging;
  - the `document.converted` event (document, converter, version, markdown hash, manifest hash, counts);
  - the library layout for Markdown and the manifest;
  - re-conversion as a new document version;
  - `factory document convert`;
  - `document_read` (paginated by anchor, with the default document and the gate);
  - `check` for unconverted documents;
  - trace from a document to its conversion.
- **Type consistency:** `Manifest`, `Anchor`, `ConversionResult`, `Converter.to_markdown`, `convert` and `parse_manifest` are named identically in Tasks 1–6.
- **Proportion:** the platform part is four tasks; the experiment part is three tasks with steps, not code.
- **Open risk:**
  - Heading-number parsing from PDF converter output is fragile. The structure score (c) will show it, and B2 may keep a page/paragraph-only anchor fallback for PDFs (`p<n>` plus `s0.p<k>`).
  - GROBID setup on arm64 without Docker needs a pinned JDK. If it cannot run, the report says so and the candidate is dropped, not silently skipped.

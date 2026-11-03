# Converter bake-off (slice 2, plan B1)

Measures candidate converters (HTML: `latexml-html`, pandoc; LaTeX source: pandoc; PDF: docling,
pymupdf4llm, GROBID) on a fixed, off-topic arXiv corpus. Outcome: decision 49.

Experiment code, TDD-exempt. No literature text is committed: `data/` is git-ignored.

## Run

```
cd experiments/converter-bakeoff
uv sync
uv run python fetch.py --check   # off-topic guard + title check (arXiv API, one request)
uv run python fetch.py           # refuses unless corpus.toml has approved = "<name> <date>"
```

`fetch.py` writes `data/raw/<id>/{html,eprint,pdf,meta.json}` (version and sha256 per file),
through the platform's polite client (3 s arXiv throttle). A route that is unavailable is recorded
in `meta.json`, not hidden.

## Corpus

`corpus.toml` lists `{id, title, tags}`. Tags: `dense-tables`, `heavy-math`, `two-column-pdf`,
`custom-macros`, `appendix`. No linear/efficient-attention or ViT-efficiency papers (decision 47).
`custom-macros` tags are provisional until the e-prints are fetched.

## Pipeline

```
uv run python grobid_service.py start    # only for the GROBID candidate; `stop` when done
uv run python run.py                     # every pair twice, fresh subprocesses; resumable
uv run python score.py                   # results/scores.json
uv run python report.py                  # results/bakeoff-<date>.md
uv run python score.py --sheet           # data/sheet.csv, human check (seed 49), run on request
```

- `run.py` writes `data/out/<candidate>/<format>/<id>.md` (git-ignored) and appends
  `results/runs.jsonl` (hashes, seconds, pages, safe warnings, error class; no document text).
  Each conversion has a 1500 s timeout, recorded as an error. A failure is recorded, never retried;
  delete its line from `runs.jsonl` to rerun it.
- `seconds` is the conversion call only (imports and Docling's model load excluded). `pages` is the
  paper's PDF page count, used as the divisor for every format.
- Criteria (a)-(e) and the table-fidelity definition are in the `score.py` docstring.
- `sheet_marks.csv`: the researcher saves the filled `sheet.csv` as `data/sheet_marks.csv`;
  `report.py` then adds correct/minor/wrong counts per candidate.
- The `latexml-html` reference is the platform converter (`factory.document.latexml_html`). Pandoc
  `-t gfm` emits raw HTML `<table>` for tables it cannot write as pipe tables (most arXiv tables);
  those are not tables to the anchoriser, so they count against the candidate.
- GROBID: one long-lived service (started by `grobid_service.py`, `./gradlew run` under the local
  JDK) serves all requests; each "fresh process" is only the HTTP client, so its determinism
  measures the service output. CRF models only (no DeLFT), `consolidateHeader=0` and
  `consolidateCitations=0` (no outgoing requests). The TEI-to-Markdown mapping is in
  `adapters/grobid.py`. TEI carries no page breaks, so GROBID output has no page anchors.
- Docling: `do_ocr=False`, TableFormer on, models loaded from `tools/docling-models`, pages joined
  with `\f`. Its `version()` carries a sha256 over the model directory.
- PyMuPDF4LLM: `to_markdown(page_chunks=True)`, chunks joined with `\f`.
- pandoc LaTeX: the e-print is unpacked to a temporary directory (tar.gz, gz or bare `.tex`), the
  shallowest `.tex` with `\documentclass` and `\begin{document}` is converted with that directory
  as working directory.

## Seeds

Human-check sample: `random.Random(49)`, ten tables per format from the pool of every successfully
converted candidate table of that format (including `latexml-html` in the HTML pool).

## Pinned tool versions

Downloads live in the git-ignored `tools/`; nothing is installed system-wide (Gradle's own cache is
`~/.gradle`).

| tool | version | source / sha256 of the downloaded archive |
|---|---|---|
| pandoc | 3.13 (arm64 macOS) | `pandoc-3.13-arm64-macOS.zip` f436d18bebbfb3ddd326597686dacab9fac5dc23bd060495020f35a28a43a7c3 |
| JDK (for GROBID) | Eclipse Temurin 21.0.13+9 (aarch64 mac) | `OpenJDK21U-jdk_aarch64_mac_hotspot_21.0.13_9.tar.gz` bf036b35b071bfb2f54f2c0af8ee8d88afa95ee6eb3dce02c0f94cfc2524d04a |
| GROBID | 0.9.1 (source release, built with `./gradlew assemble -x test`, Gradle 9.6.1) | `grobid-0.9.1.zip` 640b33615466b7d9dc784d87212144608cf509b28c983b46ca6e36f8c8686ec9 |
| docling | 2.146.0 (docling-ibm-models 4.0.4, docling-parse 7.24.2) | `pyproject.toml` / `uv.lock`; models via `docling.utils.model_downloader.download_models` into `tools/docling-models` (layout heron, TableFormer; no OCR, code/formula or picture models) |
| pymupdf4llm | 2.1 (pymupdf 2.1) | `pyproject.toml` / `uv.lock` |

Licences as stated by the packages: pandoc GPL-2.0-or-later (run as a subprocess), PyMuPDF and
PyMuPDF4LLM AGPL-3.0 (or commercial), Docling MIT (model weights carry their own licences),
GROBID Apache-2.0.

## Known platform limits on this machine (macOS arm64)

GROBID 0.9.1 starts, but its bundled `pdfalto` (mac_arm-64) links
`/opt/homebrew/opt/fontconfig/lib/libfontconfig.1.dylib`, which is not installed. Every
`processFulltextDocument` request therefore fails with HTTP 500 (`pdfalto ... error code: 134`).

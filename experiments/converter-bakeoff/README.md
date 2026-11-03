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

## Pinned tool versions

TBD (added with the adapters in the next task).

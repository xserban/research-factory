# Runbook: a pilot on a folder of your own PDFs

Status: written 2026-11-06 against branch `plan-pdf-intake` (plan PI). Commands were checked against `platform/src/factory/cli/main.py`. Sections 2 to 7 were walked once on a temporary project outside the repository: three PDFs in `pilot` mode, `import pdfs` through `document read`, with screening driven through the services the MCP tools call. No test suite covers this path yet (testing is paused). What follows full text is in `docs/runbook-fulltext-usecase.md`.

Notation: **[H]** is your act at the terminal; **[A]** is Claude's act through an MCP tool. The folder may be anywhere on disk: the files are copied into the project's git-ignored library at import, and paths and file names stay there. Nothing is read from the folder afterwards.

## 1. Setup

```
export FACTORY_ROOT=/path/to/factory-root
export FACTORY_DOCLING_MODELS="$HOME/.local/share/research-factory/docling-models"
export FACTORY_MAILTO=you@example.org              # OpenAlex polite pool, used by import resolve
alias factory='uv run --project platform factory'       # from the repository root
factory document converters
```

On this machine Docling was installed by hand into the main checkout's `platform/.venv`. `uv run` keeps it; plain `uv sync` removes it.

`document converters` must show `docling  default ... ready`. If it says `unavailable`, the line names the remedy: the `docling` extra or `FACTORY_DOCLING_MODELS`. A missing default converter records `converter-unavailable` for each document and never falls through to another (decision 49). OCR is off, so a scanned PDF has no text; it needs a text PDF or a source file.

Start Claude Code with `claude --plugin-dir plugin`.

## 2. Project and protocol

```
factory init my-pilot --mode pilot
export FACTORY_PROJECT=my-pilot
```

**[A]** `question_record`, then `protocol_record` with `ready: true`. For a corpus that is only your library, the spec has empty `sources` and `queries` and one `library_sources` entry: `{"name": "default", "format": "pdfs", "role": "corpus"}`. Give `--collection NAME` at import and use the same name here if you want another one. This is allowed in `exploratory` and `pilot`, never in `systematic` (decision 99 item 2). `check` reports `search-none`, and methods states that no database search was run and that no recall is claimed. To add a search later, amend the protocol as usual.

**[A]** `protocol_press_review` with empty `findings`, as there is no strategy to review. **[H]** `factory protocol confirm-press prs_...`, with no `--response`.

## 3. Bring the folder in

If a reference manager holds these papers, prefer `factory import bib FILE.bib --role corpus --no-split` (or `import csl`): the export brings titles, years, abstracts and file links. The rest of this section is the same. For a bare folder:

```
factory import pdfs /path/to/papers --role corpus --no-split
factory import show IMP --researcher --hints
```

`--no-split` keeps every PDF in play. Without it, a pre-search import sends about a third of your own PDFs to a held-out part, which measures how well a later search finds your library. That is useful only if you will search. With `--no-split`, `check` reports `import-coverage-optimistic`, which is only about that coverage figure (ruling 23).

`show --researcher --hints` lists each record's ordinal, state, title, file name and, for an untitled record, the first line of its first page. The hint is read in memory, never stored, and never becomes a title. It is your output alone; do not paste it to an agent.

A title left by an authoring tool (`Microsoft Word - draft7.docx`) is dropped and the record is flagged `title-metadata-rejected`.

## 4. Say what the unnamed files are

A record with no title and no identifier cannot be admitted until you name it. One at a time:

```
factory import describe IMP 3 --title "The Title" --author "Quill, Ada" --year 2021 --rationale "read the file"
```

Or for many, a CSV with a header drawn from `ordinal,title,authors,year,doi,arxiv,venue`, authors separated by `;`. A bad row is reported and the others are applied. The CSV is not archived.

```
factory import describe IMP --csv names.csv --rationale "read the files"
```

`--abstract TEXT` gives title/abstract screening something to quote. The description is an overlay: the record keeps what the file said (R-03). A record an admission already names cannot be described.

## 5. Resolve and admit

```
factory import resolve IMP
factory import show IMP --researcher
factory import confirm IMP ORDINAL --rationale "..." [--work rf:...]    # fuzzy or ambiguous matches
factory import reject IMP ORDINAL --rationale "..."
factory import admit IMP
```

Resolve looks records up on arXiv and OpenAlex as probes outside the corpus. A record neither source knows stays `unresolved`, which is fine: admission builds its work from the record, and `check` keeps reporting it under `import-unresolved`. Admission refuses while a record is unconfirmed, ambiguous or described since its last resolution.

Admit prints `not admitted, no title: N` when records are still unnamed. Name them later and repeat:

```
factory import describe IMP 7 --title "..." --rationale "..."
factory import resolve IMP --described
factory import admit IMP
```

`--described` touches only those records, so your decisions on the others stand. A plain `resolve` redoes every record not yet admitted and clears their decisions. A later admission plans only what no earlier run retrieved, so no record enters twice. The same holds after a crash between two admission queries: run `import admit` again.

## 6. Screening

```
factory calibrate draw
factory calibrate label rf:... include          # or: exclude --criterion EX01
```

The draw needs no seeds on a library-only protocol. It prints the works; label each one. **[A]** `screen_next` and `screen_record` for pass A, and in another session and model for pass B. Run `dedup_run` first if the same paper may be in the folder twice.

A PDF with no abstract is still screenable: the verdict `cannot-assess` needs a criterion, a quote from the title and a rationale, and it promotes the work to full text. Works that a source resolved usually carry the source's abstract.

## 7. Files, conversion and reading

```
factory import attach IMP --researcher
factory document convert
factory document status
factory document read rf:... --limit 20
factory document read rf:... --anchor t1
```

`attach` records a document for each promoted work. Each record lands in one list:

- `identity unchecked`: the resolved title is not on the file's first page, so the identifier may be a citation. Open the file, then `factory import confirm IMP ORDINAL --rationale "..."`, and attach again. Or `factory import reject` it.
- `not promoted`: the work did not pass screening. Attach again after a later pass.

`convert` costs a model load, then about 1.25 s per page; three short PDFs took under two minutes on this machine. A repeat run writes nothing. **Read a sample of tables yourself**: decision 49 rests on an automated fidelity score, and no person checked tables. Methods says so, and names converter and version.

If Docling mangles a paper and the optional extra is installed:

```
factory document convert --document doc_... --converter pymupdf4llm
```

That adds a conversion beside the first one, which stays pinned, and becomes what `document read` serves. A later plain `convert` leaves that document alone. `check` reports `conversion-not-chosen`. Refused, writing nothing, when the converter cannot run here.

PDFs added after this point go through a new `import pdfs`. For a few PDFs of works already promoted, `factory fulltext import FOLDER` matches by the identifier in the file name, else on page 1. A first-page match whose title is not on that page is listed as identity unchecked; check the file, then repeat with `--accept FILE`.

## 8. What comes next

Full-text screening, extraction and the evidence report run as in `docs/runbook-fulltext-usecase.md`, from its screening section.

## If something stops you

| Message | Meaning | Do |
|---|---|---|
| `library-undeclared` | no `library_sources` entry matches the collection and format | amend the protocol |
| `draw the seed split before the calibration` | the protocol is not library-only, or seeds exist | `factory seeds split`, after three positive seeds |
| `... described since resolution` | a description awaits its lookup | `factory import resolve IMP --described` |
| `already admitted: no record is left to admit` | nothing to do | go on to screening |
| `converter-unavailable` in `document status` | Docling or its models are absent in this shell | `factory document converters`, set the variable, convert again |

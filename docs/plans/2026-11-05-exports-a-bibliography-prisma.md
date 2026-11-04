# Bibliography and PRISMA Diagram Exports Implementation Plan (slice 7b, sub-plan X-A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted).**

> **Reconciled 2026-11-04 (cross-spec reconciliation, decision 75; v1 cut, decision 74).** Task 3's SVG lists the "other methods" keys in the platform order `citation-chase`, `seed-admission`, `hand-search`, `supplied`, `library-import` (slices 4a and 3d are merged first), skipping zeros. No projection change.

> **Dependencies.** Slices 1 and 2 merged (works, dedup, `prisma_flow`, `full_text_boxes`, final outcomes). No dependency on G1–G3; the `draft:` scope is added by W-B (Task 4 there). First plan of slice 7b.

**Goal:** Export the bibliography of a scope of works as BibTeX and CSL-JSON, and the PRISMA 2020 flow as a deterministic SVG, from events only, byte-identical across rebuilds.

**Architecture:** Pure serialisers in `factory/exports/` (`keys.py`, `bibtex.py`, `csl.py`, `prisma_svg.py`) take model objects and return text. `services/exports.py` selects works for a scope with streamed SQL reads and calls the serialisers. `mcp/` adds `export_bibliography`; `cli/` adds a `factory export` group that writes to a path the researcher names (or stdout).

**Tech Stack:** stdlib only (`json`, `xml.sax.saxutils.escape`); test-only dependency `bibtexparser>=1.4,<2` to round-trip BibTeX (dev group, never imported by `platform/src`).

**Spec:** `docs/specs/slice-7b-views-writing.md` rulings 18, 19, 22, 26; acceptance 13 (bibliography and PRISMA parts), 17 (bibliography part). R-05, R-47.

## Rulings made in this plan
1. **Key derivation [confirm].** `bib_key(work_id) = work_id[3:].rsplit("-", 1)[0]` (drop `rf:` and the 8-hex suffix). Keys are assigned per export over the selected works sorted by work id; on collision every colliding work gets its full suffix form `<base>-<hash8>`. A key is ASCII; non-ASCII characters of the base are transliterated by NFKD and dropping combining marks (work ids are already ASCII in practice; the rule makes it total).
2. **Type mapping [confirm].** `journal-article` → `@article`, `conference-paper` → `@inproceedings`, `book-chapter` → `@incollection`, `thesis` → `@phdthesis`, `tech-report` → `@techreport`, `preprint` → `@misc` with `eprint`, `archivePrefix = {arXiv}` when an arXiv id exists, `dataset` → `@misc` with `howpublished = {Dataset}`, others → `@misc`. CSL types: `article-journal`, `paper-conference`, `chapter`, `thesis`, `report`, `article` (preprint), `dataset`, `document`.
3. **Fields.** `title`, `author` (`Family, Given` joined by ` and `; a name without a comma is kept as given, braced), `year` (from `dates.published`), `doi`, `url`, `journal`/`booktitle` from `venue.name`, `volume`, `number`, `pages`, `publisher`, `isbn`, `eprint`. A field absent on the work is omitted. BibTeX text is UTF-8 with `{`, `}`, `\`, `%`, `&`, `$`, `#`, `_` escaped; `--ascii` escapes non-ASCII as LaTeX accents where a table entry exists, else drops to `{\char"XXXX}`. Titles are wrapped in double braces to protect capitalisation.
4. **Scopes.** `included` (final outcome `INCLUDED` at the last declared stage: full text when declared, else title/abstract), `corpus` (canonical works after dedup), explicit `ids`. Unknown ids are a structured error; nothing is written.
5. **PRISMA SVG [confirm].** A fixed template of PRISMA 2020 "new reviews, databases, registers and other sources": left column databases (identified per source, duplicates removed, screened, excluded, sought for retrieval, not retrieved with reasons, assessed for eligibility, excluded with reasons, included), right column other methods (identified per method, sought, not retrieved, assessed, excluded). Box size fixed (`BOX_W = 260`, line height 14); text wrapped by a fixed per-character width table (`CHAR_W = 6.6` for ASCII, 9 otherwise); the box height grows with lines and later boxes shift down; arrows are straight lines between box anchors. When the full-text stage has not run, the eligibility boxes read "not run". `provisional` adds a banner "Provisional: N records pending". No CSS, no fonts beyond `font-family="sans-serif"`. Every number is read from `PrismaFlow`/`FullTextBoxes`; no arithmetic in the renderer beyond what those models expose (R-05).

## Global Constraints
- The platform never calls a model; exports read the projection and events only, never the library (R-47).
- Exports are byte-identical for the same log; output order is deterministic (works by key; JSON with sorted keys, compact separators, trailing newline).
- Business logic in `services/exports.py`; pure serialisers in `factory/exports/`; `mcp/` and `cli/` parse and format.
- MCP `export_bibliography` is refused to pass sessions (decisions 43, 48) and capped at `MCP_EXPORT_MAX_WORKS = 2000`.
- TDD; `uv run pytest -m "not network and not slow"`; `mypy --strict`; ruff; coverage ≥ 90% for `services/` and `model/`.

## Review Focus
1. Key stability: rebuild, re-export, same keys; adding a colliding work changes only the colliding keys (Task 1, `test_collision_changes_only_colliding_keys`).
2. No invented fields: a work without venue has no `journal` line (Task 2, `test_absent_fields_omitted`).
3. PRISMA SVG numbers equal `prisma_flow` exactly, including `excluded` per criterion and other-methods counts (Task 3, `test_svg_numbers_equal_flow`).
4. Streaming: a 10^5-work bibliography is produced without materialising all `Work` objects (Task 4, `test_bibliography_scale`, `slow`).

## File Structure
- Create `exports/__init__.py`, `exports/keys.py`, `exports/bibtex.py`, `exports/csl.py`, `exports/prisma_svg.py`, `services/exports.py`.
- Modify `mcp/server.py`, `cli/main.py`.
- Tests: `tests/test_export_keys.py`, `tests/test_export_bibtex.py`, `tests/test_export_csl.py`, `tests/test_export_prisma_svg.py`, `tests/test_exports_service.py`, `tests/test_exports_cli_mcp.py`.

### Task 1: Keys

*Tier: standard.*

**Files:** Create `exports/keys.py`; Test `tests/test_export_keys.py`.

**Interfaces:**
- Consumes: `WORK_ID_RE` (`model/work_ids.py`).
- Produces: `bib_key(work_id: str) -> str`; `assign_keys(work_ids: Iterable[str]) -> dict[str, str]` (ruling 1; input order irrelevant, output keyed by work id).

- [ ] **Step 1: Tests.**
```python
def test_key_drops_prefix_and_hash(): assert bib_key("rf:katharopoulos2020-transformers-are-rnns-1a2b3c4d") == "katharopoulos2020-transformers-are-rnns"
def test_assign_is_order_independent(): assert assign_keys(["rf:b2020-x-11111111", "rf:a2019-y-22222222"]) == assign_keys(reversed([...]))
def test_collision_uses_full_suffix():
    k = assign_keys(["rf:smith2020-attention-11111111", "rf:smith2020-attention-22222222"])
    assert set(k.values()) == {"smith2020-attention-11111111", "smith2020-attention-22222222"}
def test_collision_changes_only_colliding_keys(): ...        # Review Focus 1
def test_keys_are_ascii(): ...                               # NFKD transliteration
def test_invalid_work_id_raises(): ...
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** `uv run pytest tests/test_export_keys.py -q`; mypy; ruff. **Step 5:** Commit `feat(exports): stable bibliography keys`.

### Task 2: BibTeX and CSL-JSON serialisers

*Tier: standard.*

**Files:** Create `exports/bibtex.py`, `exports/csl.py`; Test `tests/test_export_bibtex.py`, `tests/test_export_csl.py`.

**Interfaces:**
- Consumes: `Work`, `WorkType`, `Author`, `Venue`, `Dates`, `Identifiers` (`model/work.py`); `assign_keys`.
- Produces: `bibtex_entry(work: Work, key: str, *, ascii_only: bool = False) -> str`; `bibtex(entries: Iterable[tuple[str, Work]], *, ascii_only: bool = False) -> Iterator[str]` (yields entries in the given order, separated by one blank line); `csl_item(work: Work, key: str) -> dict[str, JsonValue]`; `csl_json(items: Iterable[tuple[str, Work]]) -> Iterator[str]` (streams a JSON array: `[`, items joined by `,\n`, `]\n`; each item with sorted keys).

- [ ] **Step 1: Tests.**
```python
def test_article_entry_round_trips():
    text = bibtex_entry(work(type="journal-article", venue=Venue(name="JMLR", volume="21")), "k")
    db = bibtexparser.loads(text); e = db.entries[0]
    assert e["ENTRYTYPE"] == "article" and e["journal"] == "JMLR" and e["ID"] == "k"
def test_preprint_has_eprint(): ...                          # @misc, eprint, archivePrefix arXiv
def test_absent_fields_omitted(): assert "journal" not in bibtex_entry(work(venue=None), "k")   # Review Focus 2
def test_special_characters_escaped(): assert r"\&" in bibtex_entry(work(title="R&D"), "k")
def test_ascii_option_escapes_accents(): assert r"{\"u}" in bibtex_entry(work(authors=[Author(name="Müller, A.")]), "k", ascii_only=True)
def test_title_double_braced(): ...
def test_csl_item_shape():
    it = csl_item(work(type="conference-paper", dates=Dates(published=date(2020, 7, 1))), "k")
    assert it["type"] == "paper-conference" and it["issued"] == {"date-parts": [[2020, 7, 1]]} and it["id"] == "k"
def test_csl_json_is_valid_and_ordered(): assert json.loads("".join(csl_json(items)))[0]["id"] == "a"
def test_author_name_forms(): ...                            # "Family, Given" vs a single token
```
- [ ] **Step 2:** FAIL. **Step 3:** Implement rulings 2, 3. **Step 4:** tests, mypy, ruff. **Step 5:** Commit `feat(exports): BibTeX and CSL-JSON serialisers`.

### Task 3: PRISMA 2020 SVG

*Tier: standard.*

**Files:** Create `exports/prisma_svg.py`; Test `tests/test_export_prisma_svg.py`.

**Interfaces:**
- Consumes: `PrismaFlow`, `FullTextBoxes` (`services/prisma.py`).
- Produces: `PRISMA_TEMPLATE_VERSION = 1`; `prisma_svg(flow: PrismaFlow) -> str` (ruling 5; `flow.full_text` carries the full-text boxes).

- [ ] **Step 1: Tests.**
```python
def test_svg_parses_and_has_boxes(): root = ET.fromstring(prisma_svg(flow())); assert len(root.findall(".//{*}rect")) >= 9
def test_svg_numbers_equal_flow():                           # Review Focus 3
    f = flow(identified_databases={"openalex": 420, "arxiv": 80}, duplicates_removed=60, ...)
    texts = " ".join(t.text or "" for t in ET.fromstring(prisma_svg(f)).iter("{*}text"))
    assert "openalex (n = 420)" in texts and "Duplicate records removed (n = 60)" in texts
    assert f"Records screened (n = {f.screened})" in texts
def test_excluded_reasons_listed_per_criterion(): ...
def test_full_text_not_run_boxes(): ...                      # "not run"
def test_provisional_banner(): assert "Provisional: 3 records pending" in prisma_svg(flow(pending=3, provisional=True))
def test_long_source_names_wrap_and_shift(): ...             # later boxes' y > earlier boxes' y + height
def test_deterministic(): assert prisma_svg(flow()) == prisma_svg(flow())
def test_text_escaped(): ...                                 # a source name with "<"
```
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** tests, mypy, ruff. **Step 5:** Commit `feat(exports): PRISMA 2020 flow diagram as SVG`.

### Task 4: Export service

*Tier: standard.*

**Files:** Create `services/exports.py`; Test `tests/test_exports_service.py`, `tests/test_exports_scale.py` (`slow`).

**Interfaces:**
- Consumes: `canonical_works`-equivalent SQL over the works projection (the implementer reads `services/dedup.py::canonical_works` and writes a streamed variant), `final_outcomes(project, stage=...)`, `get_work`, `prisma_flow`, `full_text_boxes`, `has_full_text_plan`.
- Produces: `BibScope = Literal["included", "corpus"]`; `BibFormat = Literal["bibtex", "csl"]`; `select_works(project: Project, scope: BibScope | None = None, ids: Sequence[str] = ()) -> list[str]` (work ids sorted; exactly one of scope/ids; errors as `FactoryValidationError` field `scope`/`ids`); `iter_works(project: Project, work_ids: Sequence[str]) -> Iterator[Work]` (reads in pages of 500); `export_bibliography(project: Project, fmt: BibFormat, *, scope: BibScope | None = "included", ids: Sequence[str] = (), ascii_only: bool = False) -> Iterator[str]`; `export_prisma_svg(project: Project) -> str`.

- [ ] **Step 1: Tests.**
```python
def test_included_scope_uses_last_declared_stage(project_ft): assert select_works(project_ft, "included") == ["rf:a…"]   # FT-excluded work absent
def test_corpus_scope_follows_dedup(project): ...            # merged work appears once, as canonical id
def test_unknown_ids_rejected(project): with pytest.raises(FactoryValidationError) as e: select_works(project, ids=["rf:nope-00000000"])
def test_export_byte_identical_across_rebuilds(project):
    a = "".join(export_bibliography(project, "bibtex")); project.index.rebuild(); assert "".join(export_bibliography(project, "bibtex")) == a
def test_export_reads_no_library(project, monkeypatch): ...  # library BlobStore.read patched to raise
def test_prisma_svg_matches_flow(project): ...
@pytest.mark.slow
def test_bibliography_scale(synthetic_100k): ...             # < 5 s; peak RSS growth bounded (tracemalloc < 200 MB)
```
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** tests, mypy, ruff, coverage. **Step 5:** Commit `feat(exports): export service for bibliography and PRISMA SVG`.

### Task 5: MCP tool and CLI

*Tier: standard.*

**Files:** Modify `mcp/server.py`, `cli/main.py`; Test `tests/test_exports_cli_mcp.py`.

**Interfaces:**
- MCP (read; refused to pass sessions): `export_bibliography(project: str, format: str = "bibtex", scope: str = "included", ids: list[str] | None = None) -> dict` with `{"text": …, "count": n, "scope": …}`; more than `MCP_EXPORT_MAX_WORKS` works → structured error (field `scope`, "too large; use the CLI").
- CLI: `factory export bibtex [--scope included|corpus] [--id ID]… [--ascii] [--out PATH]`, `factory export csl [...]`, `factory export prisma [--out PATH]` (SVG); `factory report prisma --format svg` prints the same SVG.

- [ ] **Step 1: Tests.** MCP tool list pinned (adds `export_bibliography`); pass session refused; cap enforced; CLI output to `--out` equals the service text; CLI writes nothing under `projects/<slug>/` (assert the tree is unchanged); `--out` into an existing file asks no question and overwrites (documented).
- [ ] **Step 2:** FAIL. **Step 3:** Implement (parse, call, format only). **Step 4:** `uv run pytest -m "not network and not slow"`; mypy; ruff. **Step 5:** Commit `feat(exports): export_bibliography tool and factory export commands`.

## Self-review notes
- Spec ruling 18's `draft:` scope is deferred to W-B Task 4, which extends `select_works`; this plan's signature leaves room (`ids`).
- No event is written; no projection change; `PROJECTION_VERSION` untouched.

## Later (not v1)

None: every task of this plan is in v1.

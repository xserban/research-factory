# Reference Extraction, Resolution and Snowballing Implementation Plan (slice 3a, sub-slice G1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Dependencies.** Plan B2 (conversion, anchors, `document_read`; branch merged) and plan C (full-text screening: `final_outcomes(project, stage=FULL_TEXT)`, `default_conversion`) must be merged first. Plan D (extraction) is not required. **Decision 49 (converters for LaTeX and PDF) is still pending.** Reference parsing must work on any converted document: it reads only the manifest and Markdown through `conversion_manifest` / `conversion_document`, never converter-specific structure. Tests build documents from hand-written Markdown with anchors and from the existing LaTeXML HTML fixture, not from a particular future converter. Task 1 and Task 2 change plan B's anchor grammar and LaTeXML converter; they come first and must leave every plan A–C test green.

**Goal:** Parse each full-text-included paper's bibliography, link citation markers to entries, resolve entries to works with a recorded method and score, and bring missing works in through recorded snowball rounds that end at the screening protocol.

**Architecture:** Pure helpers in `factory/references/` (parse, markers, `.bbl`, match) feed services (`references.py`, `reference_resolve.py`, `snowball.py`) that write a small event family (`reference.*`, `citation.*`, `snowball.*`) folded into new index tables. Backward rounds register chase-purpose queries (OpenAlex filter chunks, arXiv `id_list`, an offline `reflist` pseudo-source) as supplementary searches; forward rounds delegate to `search_chase`. Stopping rule is a new hashed protocol section `snowball_plan`. `mcp/` and `cli/` only parse and format.

**Tech Stack:** as plans A–C; stdlib `tarfile`, `gzip`, `difflib`; no new dependencies.

**Spec:** `docs/specs/slice-3a-references.md` (all sections; rulings 1–20 provisional, marked **[confirm]**). `docs/specs/01-rigour.md` R-01–R-05, R-13–R-15, R-22–R-26, R-30–R-38, R-43, R-47, R-51. Decisions 39, 40, 42, 43, 48, 50 (Proposed). Outline: `docs/specs/outlines/lineage-graph.md` (G1 part).

## Global Constraints

- All plan A–C constraints hold. The platform never calls a model; no key, no SDK. Events are the source of truth; the index is written by the projector only, and the projection never reads the library.
- Every agent-written event carries model, skill reference and `input_blob` (the validated input of the call). Scores, methods, flags and counts are computed by the platform and stored in the event.
- Document text in events is limited to reference entry text (<= 1000 characters, spec ruling 14) and marker tokens (<= 80 characters, ruling 9). No document text appears in any error, warning or finding message.
- Invalid input writes nothing and returns structured errors; in a batch each item is validated alone and valid ones are written.
- Slice-1 and plans A–C behaviour unchanged: every earlier test passes without edits, except the `PROJECTION_VERSION` pin and the converter-version pin named in Tasks 2 and 4. A log without `snowball_plan` replays to identical `P@` ids. Existing manifests (without `b<n>`) still parse.
- `uv run pytest -m "not network"`, `mypy --strict` (new and changed files), ruff pass; coverage >= 90% for `services/` and `model/`.
- Provenance method for snowballed records is `citation-chase` (no new enum value); mechanism is told apart through the round tables.

## Review Focus

1. A document converted before this change (paragraph anchors in its References section) is parsed through the paragraph fallback, flagged, and its old quotes still verify; a bibliography with zero entries is recorded `no-bibliography`, not skipped (Tasks 1, 3).
2. Marker mapping: `[3, 5]`, `[3-6]`, `(Wang et al., 2021)` with two Wang 2021 entries (ambiguous), a marker to a missing entry (`marker-gap`), and a numeric marker above the entry count (`parse-incomplete`) are each counted and flagged, never dropped (Task 3).
3. Identity: a DOI that equals an arXiv DataCite DOI of a corpus work resolves to that work and creates no duplicate; an entry with an identifier no source returns becomes a `no-source-record` candidate only with title and year, else `unresolved` (Task 5).
4. Fuzzy links: two near-equal title matches stay `ambiguous`; an agent's confirm is refused; a proposal does not create a candidate; a rejection after a confirmation supersedes it (Tasks 5, 9).
5. Rounds: a refused round (no plan, maximum reached, previous round without yield, pending records, unextracted included work) writes nothing; a rejected or failed source query leaves the round recorded and the other queries run; a candidate is pending, never included, after the round (Tasks 6, 7).

## File Structure

- Modify `document/anchors.py` (`ANCHOR_RE`, `AnchorKind.BIBLIOGRAPHY_ENTRY`, `parse_manifest`), `document/anchorise.py`, `document/latexml_html.py` (cite links, `CONVERTER_VERSION = "1.1"`).
- Create `references/__init__.py`, `references/parse.py` (entries, fields), `references/markers.py`, `references/bbl.py`, `references/match.py` (all pure).
- Create `model/references.py` (events, value types); modify `events/catalog.py`, `model/protocol.py` (`SnowballPlan`), `services/protocol_rules.py`.
- Create `index/references.py`; modify `index/default.py`, `index/chase.py` (`round_texts`).
- Create `services/references.py`, `services/reference_resolve.py`, `services/snowball.py`, `sources/reflist.py`; modify `sources/registry.py`.
- Modify `services/prisma.py`, `services/methods.py`, `services/check.py`, `services/trace.py`, `services/seeds.py` (route label, CLI view), `mcp/server.py`, `cli/main.py`, `cli/render.py`.
- Create `plugin/skills/rf-references/SKILL.md`; modify `tests/test_plugin.py`.
- Tests: `test_anchors_bib.py`, `test_latexml_cites.py`, `test_references_parse.py`, `test_references_markers.py`, `test_references_bbl.py`, `test_references_match.py`, `test_references_model.py`, `test_references_index.py`, `test_references_extract.py`, `test_references_resolve.py`, `test_snowball_plan.py`, `test_snowball_round.py`, `test_reflist_source.py`, `test_references_reports.py`, `test_mcp_references.py`, `test_cli_references.py`, `test_acceptance_references.py`; helpers `tests/references_helpers.py` (a project with `n` included works, each converted from hand-written Markdown with a References section, a pilot protocol, fake OpenAlex/arXiv sources serving DOI/title lookups) and fixtures `tests/fixtures/references/` (hand-checked lists: LaTeXML+bbl, LaTeXML alone, other-HTML Markdown, PDF-style text, each with expected entries as JSON).

---

### Task 1: Bibliography anchors `b<n>` in the anchor grammar and the anchoriser

*Tier: critical (changes plan B's anchor grammar; every later document depends on it). Sonnet review.*

**Files:** Modify `document/anchors.py`, `document/anchorise.py`; Test `tests/document/test_anchors_bib.py` (new), existing `tests/document/` suites unchanged.

**Interfaces:**
- Produces: `ANCHOR_RE` also matches `b\d+`; `AnchorKind.BIBLIOGRAPHY_ENTRY = "bibliography_entry"`; `parse_manifest` yields `Anchor(id="b3", kind=BIBLIOGRAPHY_ENTRY, parent=<section id>, text=<paragraph source>)` for a `b<n>` anchor followed by a paragraph; `BIBLIOGRAPHY_HEADINGS: frozenset[str]` in `anchorise.py` (`references`, `bibliography`, `literature cited`, `works cited`, `reference list`).
- Consumes: `Manifest`, `parse_manifest`, `anchorise(markdown: str) -> str` (existing).

- [ ] **Step 1: Tests.**
```python
def test_b_anchor_parses():
    md = '<a id="s9"></a>\n## 9 References\n\n<a id="b1"></a>\nSmith J. A title. 2020.\n\n<a id="b2"></a>\nLee K. Another. 2021.\n'
    m = parse_manifest(md)
    assert [a.id for a in m.anchors if a.kind is AnchorKind.BIBLIOGRAPHY_ENTRY] == ["b1", "b2"]
    assert m.get("b1").parent == "s9"
def test_b_anchor_must_precede_paragraph_and_be_sequential():
    with pytest.raises(ManifestError): parse_manifest('<a id="b1"></a>\n## Heading\n')
    with pytest.raises(ManifestError): parse_manifest(PARA_B1_THEN_B3)   # gap: b1, b3
def test_old_manifest_still_parses():
    assert parse_manifest(OLD_DOC_WITH_REFERENCES_AS_PARAGRAPHS).get("s9.p2") is not None
def test_anchoriser_numbers_bibliography_entries():
    out = anchorise("# T\n\n## 1 Intro\n\nText.\n\n## References\n\nSmith J. A. 2020.\n\nLee K. B. 2021.\n\n## A. Proofs\n\nProof.\n")
    assert '<a id="b1"></a>\nSmith' in out and '<a id="b2"></a>\nLee' in out
    assert '<a id="s101.p1"></a>' in out          # later sections unaffected
    assert anchorise(out) == out                  # idempotent
@pytest.mark.parametrize("title", ["References", "5 Bibliography", "Literature Cited", "Works cited", "Reference list"])
def test_heading_variants(title): ...             # first paragraph under it is b1
def test_non_bibliography_section_keeps_paragraph_anchors(): ...   # "## 2 Related Work" -> s2.p1
```
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Extend `ANCHOR_RE`, the kind map `_ID_FORMS`-style table in `parse_manifest` (parent = enclosing section, sequential `n` check, paragraph-follows check) and `_Numbering._paragraph`: while the current section's heading text (number stripped, casefolded) is in `BIBLIOGRAPHY_HEADINGS`, number paragraphs `b<k>` with a document-wide counter and do not touch `self.paragraphs`. Only paragraphs directly in that section (not in subsections) count. **Step 4:** New and all `tests/document/` pass; `mypy --strict`; ruff. **Step 5:** Commit `feat(document): bibliography entry anchors b<n>`.

### Task 2: LaTeXML converter writes in-text citation links

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Modify `document/latexml_html.py`; Test `tests/document/test_latexml_cites.py`; existing converter tests change only for `CONVERTER_VERSION`.

**Interfaces:**
- Produces: `CONVERTER_VERSION = "1.1"`; an `ltx_cite` containing `a.ltx_ref[href="#bib.bibN"]` links to an `ltx_bibitem` is emitted as `[visible text](#b<k>)` where `k` is the 1-based ordinal of that bibitem among all `ltx_bibitem`s of the document (document order), matching the anchoriser's numbering; a cite whose target is absent stays plain text.
- Consumes: Task 1 numbering rule (bibliography paragraphs numbered by order; each `ltx_bibitem` yields exactly one paragraph).

- [ ] **Step 1: Tests.**
```python
def test_cite_becomes_link_to_b_ordinal():
    md = to_markdown(HTML_WITH_TWO_BIBITEMS_AND_CITES)
    assert "[[1]](#b1)" in md or "[Smith et al., 2020](#b1)" in md   # visible text preserved
    assert "(#b2)" in md
def test_cite_to_unknown_bibitem_is_plain_text(): ...
def test_two_cites_in_one_marker_each_linked(): ...      # "[1, 2]" -> two links, comma kept
def test_links_do_not_change_verified_text():
    assert element_plain_text(anchorised_paragraph_with_link) == "as shown in [1] earlier"
def test_end_to_end_manifest_has_b_anchors():             # convert -> anchorise -> parse_manifest
    assert {"b1", "b2"} <= {a.id for a in manifest.anchors}
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** In `_gather`, handle `ltx_cite`: build the `bib id -> ordinal` map before the walk (`_bib_ordinals(root)`), render each `a.ltx_ref` child as `[text](#b<k>)` with `text` escaped (`]`, `\` escaped), keep separators. Bump `CONVERTER_VERSION`; update the version pin in the existing converter test. **Step 4:** Converter tests, `tests/document/`, mypy, ruff. **Step 5:** Commit `feat(document): LaTeXML in-text citation links; converter 1.1`.

### Task 3: Reference parser, markers, contexts and `.bbl` reader (pure)

*Tier: standard-plus (Sonnet implement, Haiku review; accuracy is measured by the fixture set, not by review).*

**Files:** Create `references/__init__.py`, `parse.py`, `markers.py`, `bbl.py`; Test `tests/test_references_parse.py`, `test_references_markers.py`, `test_references_bbl.py`; fixtures `tests/fixtures/references/`.

**Interfaces:**
- Produces (`factory.references.parse`): `PARSER = "refparse"`, `PARSER_VERSION = "1"`; `@dataclass(frozen=True) ParsedField` -> `RefFields(doi: str|None, arxiv: str|None, url: str|None, year: int|None, first_author: str|None, title: str|None, venue: str|None)`; `@dataclass(frozen=True) Entry(ordinal: int, anchor: str, label: str|None, text: str, truncated: bool, fields: RefFields)`; `@dataclass(frozen=True) Bibliography(entries: tuple[Entry, ...], entry_anchors: Literal["b","paragraph"], flags: tuple[str, ...])`; `parse_bibliography(manifest: Manifest) -> Bibliography` (entries from `b<n>` anchors; else paragraphs of the section whose heading is in `BIBLIOGRAPHY_HEADINGS`, flag `entry-anchors-paragraph`; none -> empty with flag `no-bibliography`); `parse_entry_fields(text: str) -> RefFields`.
- Produces (`factory.references.markers`): `MarkerState = Literal["matched","unmatched","ambiguous"]`; `@dataclass(frozen=True) Context(citing_anchor: str, entry: int|None, marker: str, method: Literal["link","numeric","author-year"], state: MarkerState)`; `find_contexts(manifest: Manifest, bib: Bibliography) -> tuple[list[Context], int]` (contexts in document order and the distinct marker-token count); `completeness_flags(bib: Bibliography, contexts: Sequence[Context]) -> tuple[str, ...]` (`parse-incomplete`, `marker-gap`).
- Produces (`factory.references.bbl`): `@dataclass(frozen=True) BblEntry(key: str, text: str)`; `read_bbl(archive: bytes, *, max_bytes: int = 20_000_000) -> list[BblEntry]` (tar.gz or plain `.bbl`; only `*.bbl` members; no extraction to disk; `[]` when none/oversize); `align(bib: Bibliography, bbl: Sequence[BblEntry]) -> BblAlignment(status: Literal["absent","aligned","count-mismatch"], bib_count: int, bbl_count: int, fields: tuple[RefFields|None, ...])`.
- Consumes: `Manifest`, `Anchor`, `BIBLIOGRAPHY_HEADINGS` (Task 1).

- [ ] **Step 1: Check reuse (ruling 12):** read `docs/09-existing-assets.md`; if it lists reference-parsing code to port, port it with its tests and note it in the commit; else proceed. **Step 2: Tests** (assertions use the fixture JSON of hand-checked entries).
```python
def test_entries_from_b_anchors(): assert [e.anchor for e in parse_bibliography(m).entries] == ["b1","b2","b3"]
def test_paragraph_fallback_flags(): assert "entry-anchors-paragraph" in parse_bibliography(old_manifest).flags
def test_no_bibliography_is_recorded(): assert parse_bibliography(m_without).flags == ("no-bibliography",) and not parse_bibliography(m_without).entries
def test_fields_doi_arxiv_year():
    f = parse_entry_fields("[12] K. He et al. Deep residual learning. CVPR 2016. doi:10.1109/CVPR.2016.90.")
    assert (f.doi, f.year) == ("10.1109/cvpr.2016.90", 2016)
    assert parse_entry_fields("A. Dosovitskiy. An image is worth 16x16 words. arXiv:2010.11929v2, 2020.").arxiv == "2010.11929"
def test_truncation_flag_at_1000_chars(): ...
def test_numeric_markers():
    ctx, distinct = find_contexts(m, bib)           # text: "see [3, 5], [7-9] and [2]"
    assert [(c.entry, c.state) for c in ctx] == [(3,"matched"),(5,"matched"),(7,"matched"),(8,"matched"),(9,"matched"),(2,"matched")]
def test_linked_markers_use_link_method(): ...      # "[1](#b1)" -> method "link"
def test_author_year_unique_and_ambiguous(): ...    # two "Wang 2021" entries -> state "ambiguous", entry None
def test_marker_to_missing_entry_flags_gap(): ...   # "[40]" with 30 entries -> "unmatched"; flags has "parse-incomplete"
def test_marker_token_capped_at_80_chars(): ...
def test_bbl_alignment_by_count(): ...              # equal counts aligned; unequal -> "count-mismatch", no entries invented
def test_read_bbl_from_tar_gz_and_oversize(): ...
```
- [ ] **Step 3: Implement** per Interfaces; ordered regexes for fields; deterministic; no I/O except `read_bbl` on the passed bytes. **Step 4:** Tests (incl. fixtures), mypy, ruff. **Step 5:** Commit `feat(references): bibliography parser, markers, bbl reader`.

### Task 4: Models, events, protocol section and index tables

*Tier: critical (events, index, protocol). Sonnet review.*

**Files:** Create `model/references.py`, `index/references.py`; Modify `events/catalog.py`, `index/default.py`, `index/chase.py` (`round_texts` also returns snowball query texts), `model/protocol.py` (`SnowballPlan`, field `snowball_plan` in `AMENDABLE_FIELDS`, omitted from every hash while `None`), `services/protocol_rules.py` (gap `snowball-plan-missing`; error when `max_*` negative); Test `tests/test_references_model.py`, `tests/test_references_index.py`, `tests/test_snowball_plan.py`.

**Interfaces:**
- Produces (`model/references.py`; ids `REX_ID_RE = rf"^rex_{ULID_RE}$"`, `SNW_ID_RE = rf"^snw_{ULID_RE}$"`): `LinkState` (`resolved|unconfirmed|ambiguous|unresolved`), `Confidence` (`identifier|title-exact|title-fuzzy|confirmed`), `Decision` (`confirm|reject|propose-confirm|propose-reject`), `Direction` (`backward|forward`), `Via` (`document-reference-list|source-metadata`); event payloads `ReferenceExtracted`, `CitationContextsRecorded`, `ReferenceResolved`, `ReferenceResolutionDecided`, `SnowballRoundStarted` with the fields listed in spec section Events; each validates: entry ordinals consecutive from 1 and unique; `entry text <= 1000`; marker tokens <= 80; resolution ordinals subset of the extraction's entries (checked by the service, shape here); `state=resolved` implies `work_id` and `confidence`; `unresolved` implies `work_id is None` and a `reason`; counts are never fields (derived).
- Produces (`model/protocol.py`): `class SnowballPlan(StrictModel): max_backward_rounds: int = Field(ge=0); max_forward_rounds: int = Field(ge=0); stop_when_no_new_included: bool = True`; `ProtocolSpec.snowball_plan: SnowballPlan | None = None`.
- Produces (`index/references.py`): tables `reference_extractions(extraction_id pk, work_id, document_id, conversion_id, parser_version, entry_anchors, flags, marker_count, bbl_status, event_id, live)`, `reference_entries(extraction_id, ordinal pk, anchor, label, text, doi, arxiv, year, first_author, title)`, `reference_links(extraction_id, ordinal, state, work_id, method, confidence, score, source_blob, matcher_version, decision, confirmed_by, no_source_record)` (live row folds the latest decision event), `citation_contexts(extraction_id, citing_anchor, entry, marker, method, state)`, `snowball_rounds(round_id pk, direction, via, round_no, rule, chase_round_id, event_id)`, `snowball_queries(round_id, position, query)`, `snowball_candidates(round_id, work_key, cited_by_included, no_source_record)`; handlers are total and first-write-wins per key; `live` is 1 for the latest extraction of a work (event order), 0 for earlier ones.
- `PROJECTION_VERSION` increments (update its pin test).

- [ ] **Step 1: Tests.**
```python
def test_resolved_needs_work_and_confidence(): with pytest.raises(ValidationError): ReferenceResolved(...state="resolved", work_id=None...)
def test_entry_text_cap_and_ordinals(): ...
def test_snowball_plan_absent_keeps_protocol_id():
    assert protocol_id(spec_without_plan) == PINNED_P_AT_FROM_PLAN_D_OR_C_FIXTURE
def test_snowball_plan_changes_hash_and_is_amendable(): ...
def test_gap_when_plan_missing_in_pilot(): assert "snowball-plan-missing" in gaps(pilot_spec_without_plan)
def test_later_extraction_supersedes_links_in_projection(): ...   # live flag moves
def test_decision_overlay_latest_wins_and_reject_after_confirm(): ...
def test_round_texts_includes_snowball_queries(): ...
def test_rebuild_determinism_with_reference_events(): ...         # same state hash twice
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement models, register five event types in `events/catalog.py` (schema 1), the projector (pure SQL over `event.payload`), extend `round_texts`. **Step 4:** Whole suite (earlier tests unchanged except the pin), mypy, ruff. **Step 5:** Commit `feat(references): events, protocol snowball_plan, index tables`.

### Task 5: Matcher and resolution service, extraction orchestration, decisions

*Tier: critical (identity and provenance of links). Sonnet review.*

**Files:** Create `references/match.py`, `services/references.py`, `services/reference_resolve.py`; Test `tests/test_references_match.py`, `tests/test_references_extract.py`, `tests/test_references_resolve.py`; fixtures from Task 3.

**Interfaces:**
- Produces (`references/match.py`, pure): `MATCHER_VERSION = "1"`; constants `TITLE_FUZZY = 0.92`, `TITLE_FLOOR = 0.85`, `MARGIN = 0.03`, `YEAR_TOLERANCE = 1`; `@dataclass(frozen=True) Candidate(work_id: str, title: str, first_author: str|None, year: int|None)`; `@dataclass(frozen=True) Match(state: LinkState, confidence: Confidence|None, score: float|None, work_id: str|None, candidates: tuple[tuple[str,float],...], reason: str|None)`; `match_title(fields: RefFields, candidates: Sequence[Candidate]) -> Match` (spec ruling 16; `normalize_title` from `model/work_ids.py`; ties and near-ties give `ambiguous`; surname/year checks only when both sides present).
- Produces (`services/references.py`): `extract_references(project: Project, actor: Actor, work_ids: Sequence[str] | None, *, sources: Mapping[str, SourceFactory]) -> ExtractSummary` where `ExtractSummary(extractions: list[ExtractionResult], skipped: list[Skipped])`, `ExtractionResult(extraction_id, work_id, entries, markers, flags, states: dict[LinkState, int])`; `included_works(project) -> list[str]` (ruling 15); `current_extraction(project, work_id) -> str | None`; `reference_counts(project) -> ReferenceCounts` (states summing to the entry count of live extractions, plus `in_corpus`, `new_candidates`); `list_references(project, *, state: LinkState|None, work_id: str|None, after: int, limit: int) -> Page`.
- Produces (`services/reference_resolve.py`): `resolve_entries(project, actor, extraction_id, *, sources) -> list[Resolution]` (identifier lookup in corpus, then probe-purpose lookups in chunks <= 50 via `register_query` / `run_query` with `purpose=PROBE`; then title match: corpus first, then one probe OpenAlex `title.search:<sanitised title>` FILTER query per remaining entry; unmatched -> `unresolved` with a reason; `no-source-record` rule of ruling 8; source errors give reason `source-error` for the affected entries only); `decide_reference(project, actor, extraction_id, ordinal, decision: Decision, *, rationale: str, quotes: tuple[str, str], work_id: str | None = None) -> None` (validations: extraction live; state `unconfirmed`/`ambiguous`; `quotes` are verbatim substrings of the stored entry text and of the candidate's stored title/author line; `confirm`/`reject` refused for `actor.kind == "agent"` unless protocol mode is `pilot`, the session differs from the latest `propose-*` actor session and the link is fuzzy, recorded `confirmed_by="second-agent"`; human confirm needs no proposal).
- Consumes: Tasks 3, 4; `canonical_works`, `list_works`, `register_query`, `run_query`, `final_outcomes`, `default_conversion`, `conversion_manifest`, `conversion_document`, `work_id`, `normalize_doi`, `arxiv_id_from_doi`.

- [ ] **Step 1: Tests.**
```python
def test_title_exact_and_fuzzy_and_ambiguous():
    assert match_title(f("Attention Is All You Need", "Vaswani", 2017), [cand("Attention is all you need", "Vaswani", 2017)]).confidence == Confidence.TITLE_EXACT
    assert match_title(f(...), [cand("Attention Is All You Need.", ...,2018)]).state == LinkState.RESOLVED
    near = [cand("Efficient Vision Transformers", "Lee", 2021), cand("Efficient Vision Transformer", "Lee", 2021)]
    assert match_title(f("Efficient vision transformers v2", "Lee", 2021), near).state == LinkState.AMBIGUOUS
    assert match_title(f("Unrelated topic entirely", None, None), [cand("Attention...")]).state == LinkState.UNRESOLVED
def test_year_gap_blocks_exact(): ...
def test_extract_records_events_and_counts(project):   # 3 entries: DOI in corpus, arXiv via lookup, unresolved
    r = extract_references(project, ACTOR, [w], sources=FAKE)
    assert sum(r.extractions[0].states.values()) == r.extractions[0].entries
    assert reference_counts(project).unresolved >= 1
def test_doi_equal_to_arxiv_datacite_resolves_to_existing_work(project): assert new_works == 0
def test_identifier_not_found_with_title_year_is_no_source_record_candidate(project): ...
def test_identifier_not_found_without_title_is_unresolved(project): ...
def test_unresolved_entries_are_listed(project): assert any(e.state == "unresolved" for e in list_references(project, state=UNRESOLVED, ...).items)
def test_new_document_version_supersedes_extraction(project): ...
def test_extraction_refused_for_not_included_or_no_conversion(project): ...   # structured skipped reasons
def test_agent_cannot_confirm(project): with pytest.raises(FactoryValidationError): decide_reference(..., Decision.CONFIRM)
def test_second_agent_confirm_in_pilot_only(project): ...
def test_proposal_does_not_change_state_or_create_candidate(project): ...
def test_human_reject_after_confirm_supersedes(project): ...
def test_decision_quotes_must_be_verbatim(project): ...
def test_probe_lookups_leave_corpus_unchanged(project): assert corpus_size(project) == before
def test_pass_session_cannot_extract: (in Task 9)
```
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement `match.py` (difflib, thresholds as constants), then the two services. One `reference.extracted` + one `citation.contexts_recorded` + one `reference.resolved` event per work, written after the lookups (lookup runs are already recorded searches; their run ids go in `lookup_runs`). Bibliography text blob for `input_blob` on agent calls. **Step 4:** Tests, mypy, ruff; set the threshold constants from the Task 3 fixture scores and note any change in the commit. **Step 5:** Commit `feat(references): resolution, extraction service, decisions`.

### Task 6: Offline `reflist` source and the snowball round service (backward)

*Tier: critical (supplementary search, provenance). Sonnet review.*

**Files:** Create `sources/reflist.py`, `services/snowball.py`; Modify `sources/registry.py` (register `reflist`), `services/protocol.py` only if `search_authorization` needs no change (round texts waived through `round_texts`; do not widen the gate); Test `tests/test_reflist_source.py`, `tests/test_snowball_round.py`.

**Interfaces:**
- Produces (`sources/reflist.py`): `class ReflistSource` (`kinds = {QueryKind.ID_LIST}`) whose `run` turns stored `no-source-record` entries (read from the index by entry key `rex_…:<ordinal>` in the query text) into `Work`s of type `other` with `Provenance(source="reflist", method=CITATION_CHASE, raw_blob=<canonical JSON of the entries>, raw_ref=<entry key>)`; no network; the raw page is archived like any source.
- Produces (`services/snowball.py`): `SnowballPlanState(direction, round_no, allowed: bool, refusals: list[ValidationIssue], rule: SnowballPlan | None)`; `snowball_candidates(project, sources: Sequence[str]) -> list[RoundCandidate]` with `RoundCandidate(work_key: str, work_id: str | None, cited_by_included: int, citing_anchors: tuple[tuple[str, str], ...], no_source_record: bool)` sorted by `(-cited_by_included, work_key)`, drawn from live `resolved` links whose work is not in the corpus (no threshold); `snowball_queries(candidates: Sequence[RoundCandidate]) -> list[QuerySpec]` (chase purpose; OpenAlex `doi:a|b…` and `openalex:` chunks <= `CHASE_CHUNK`, arXiv `id_list` chunks, `reflist` ids); `plan_round(project, direction) -> RoundPlan` (dry run: state, sources, candidates, queries, `unextracted: list[tuple[str, str]]` with reasons `not-extracted | no-document`); `snowball_round(project, actor, direction, *, sources, dry_run: bool = True) -> RoundResult` (`round_id`, `candidates`, `runs: list[RunSummary]`, `new_works`, state).
- Consumes: Task 4 events and tables, Task 5 `included_works`, `current_extraction`; `register_query`, `run_query`, `query_issues`, `search_authorization(..., pending_round_texts=texts)`, `corpus_size`, `final_outcomes`, `calibration_items`.

- [ ] **Step 1: Tests.**
```python
def test_dry_run_writes_nothing_and_ranks_by_cited_by(project): ...        # sorted (-count, key); no threshold
def test_round_event_precedes_every_query(project): ...                    # event order
def test_round_refused_without_plan_in_pilot(project): ... ; test_exploratory_allowed_without_plan_rule_none(project): ...
def test_refused_at_maximum(project): ...; test_refused_when_previous_round_had_no_included_work(project): ...
def test_refused_while_pending_or_unextracted(project): ...                # lists work ids; writes nothing
def test_no_document_work_is_listed_not_blocking(project): ...
def test_candidates_are_pending_after_round_never_included(project):
    assert all(outcome is Outcome.PENDING for outcome in outcomes_of(result.candidates))
def test_prisma_s_fields_on_runs(project): ...                              # reported vs retrieved, interface, date
def test_source_error_in_one_query_leaves_others_run(project): ...
def test_reflist_creates_other_type_work_with_raw_reference_provenance(project): ...
def test_round_waives_only_its_own_texts(project): ...                      # a hand-written chase query is still gated
```
- [ ] **Step 2:** FAIL. **Step 3:** Implement. Order: validate everything (plan, pending, unextracted, direction, query fit, authorisation with the round's texts waived) -> write `snowball.round_started` -> register and run queries; a failure in a run does not stop the others (as `search_chase`). Candidate keys: `work_id` when known (corpus-absent but resolved via a lookup work), else `rex_…:<ordinal>` for `no-source-record`. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(snowball): backward rounds, reflist source, stopping rule`.

### Task 7: Forward rounds via `search_chase`, round yield and comparison

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Modify `services/snowball.py`; Test `tests/test_snowball_round.py` (extend), `tests/test_snowball_compare.py`.

**Interfaces:**
- Produces: `snowball_round(..., direction=Direction.FORWARD)` delegates to `search_chase(project, actor, [ChaseDirection.FORWARD], sources=…)`, then writes `snowball.round_started` with `via=source-metadata`, `chase_round_id`, the same `sources`, and the delegated queries (written after the delegation returns the `chs_` id; the stopping-rule and pending checks run first and write nothing on refusal). `round_yield(project, round_id) -> RoundYield(retrieved: int, new_after_dedup: int, included: int | None)` (included is `None` while any candidate is pending at the final stage; derived from provenance + `final_outcomes` at `included_works`'s stage). `snowball_compare(project, round_id) -> Comparison(document_only: list[str], metadata_only: list[str], both: list[str])` for a backward round: metadata set = works whose provenance run belongs to a backward `chase` round (index `chase_rounds`) with an overlapping `from_works`; document set = round candidates that entered the corpus.
- Consumes: Task 6, `chase_rounds`, `search_chase`.

- [ ] **Step 1: Tests.**
```python
def test_forward_round_delegates_and_obeys_plan(project): ...             # second forward round refused when max_forward_rounds == 1
def test_forward_round_ledger_via_source_metadata(project): ...
def test_forward_refused_writes_no_chase_round(project): ...              # no chs_ event on refusal
def test_yield_counts_new_after_dedup_and_included(project): ...          # included None while pending
def test_compare_lists_one_mechanism_only(project): assert cmp.document_only == [w1] and cmp.metadata_only == [w2] and cmp.both == [w3]
def test_compare_counts_match_tables(project): ...
```
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(snowball): forward rounds, yield, comparison with search_chase`.

### Task 8: PRISMA, methods, check, trace and seed route

*Tier: standard (Sonnet implement, Haiku review).*

**Files:** Modify `services/prisma.py` (`identified_other_detail`, per-round search-report rows), `services/methods.py`, `services/check.py` (findings of spec "Check findings"), `services/trace.py` (`snw_`, `rex_` ids; candidate work back to citing anchor), `services/seeds.py` (route label `found_by` in the human seed check); Test `tests/test_references_reports.py`, extend `tests/test_check*.py` minimally.

**Interfaces:**
- Produces: `PrismaFlow.identified_other_detail: dict[str, int]` (keys `chase-forward`, `chase-backward`, `snowball-backward`; sums to `identified_other["citation-chase"]` for new-after-dedup works) with `identified_other` unchanged for projects without rounds; `SearchReportRow` extended with `via`, `round_no`, `new_after_dedup`, `included`; check codes: `references-missing-extraction`, `references-stale-extraction`, `references-parse-incomplete`, `references-unresolved-ceiling` (constant `REFERENCE_UNRESOLVED_CEILING = 0.30`), `references-library-missing`, `snowball-plan-missing`, `snowball-over-plan`, `snowball-unscreened`; `seed_check` rows gain `found_by: Literal["search","chase","snowball","admission"] | None` shown by the CLI only (the MCP views drop it, decision 43).
- Consumes: Tasks 4-7; existing `Finding`, `_Hit` patterns in `check.py`.

- [ ] **Step 1: Tests.**
```python
def test_identified_other_unchanged_without_rounds(project): assert flow.identified_other == SLICE1_VALUE
def test_detail_breakdown_sums(project): assert sum(flow.identified_other_detail.values()) == flow.identified_other["citation-chase"]
def test_search_report_has_round_rows_with_yield(project): ...
@pytest.mark.parametrize("code", ALL_REFERENCE_CODES)
def test_each_finding_appears_in_constructed_case(project, code): ...
def test_findings_carry_no_document_text(project): ...
def test_trace_from_round_and_candidate(project): ...      # candidate -> anchor -> extraction -> conversion -> document -> work -> decisions -> protocol -> question
def test_seed_found_by_snowball_labelled_in_cli_only(project): ...
```
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Tests plus slice-1 reports/check suites unchanged; mypy, ruff. **Step 5:** Commit `feat(references): PRISMA other-methods detail, check findings, trace`.

### Task 9: MCP tools and CLI

*Tier: Haiku for implementation and review (surfaces); service behaviour is covered.*

**Files:** Modify `mcp/server.py`, `cli/main.py`, `cli/render.py`; Test `tests/test_mcp_references.py`, `tests/test_cli_references.py`.

**Interfaces:**
- Produces MCP: `references_extract(work_ids: list[str] | None = None, ...)`, `references_status()`, `references_list(state: str | None, work_id: str | None, after: int = 0, limit: int = 50)` (page cap 100), `reference_decide(extraction_id, ordinal, decision, rationale, quotes, work_id=None, ...)`, `snowball_round(direction: str, dry_run: bool = True, ...)`, `snowball_compare(round_id)`. Every tool refused to a session that has joined a pass (`_refuse_pass_session`); batch input to `references_extract` accepts partial success; actor model and skill follow the existing conventions.
- Produces CLI: `factory references extract [--work ID]… | status | list [--state S] | decide EXTRACTION ORDINAL --confirm|--reject --rationale TEXT` (human), `factory snowball plan|run DIRECTION|compare ROUND`.
- Consumes: Tasks 5-8.

- [ ] **Step 1: Tests.** `test_tools_registered_and_named_area_verb`; `test_pass_session_refused_for_each_tool` (parametrised over the six); `test_references_extract_partial_success`; `test_reference_decide_agent_confirm_refused`; `test_snowball_round_defaults_to_dry_run_and_writes_nothing`; `test_mcp_views_hide_seed_route_and_held_out`; CLI: `test_decide_confirm_as_human_writes_event`, `test_snowball_plan_output_lists_candidates_ranked`, `test_status_counts_sum_to_entries`. **Step 2:** FAIL. **Step 3:** Wire handlers (parse, call service, format). **Step 4:** Tests, mypy, ruff. **Step 5:** Commit `feat(mcp,cli): references and snowball tools`.

### Task 10: Skill, documentation and acceptance

*Tier: Haiku for the acceptance test and docs; the skill is written by Sonnet and checked by the final review.*

**Files:** Create `plugin/skills/rf-references/SKILL.md`; Modify `tests/test_plugin.py` (`SKILLS`), `docs/specs/slice-3a-references.md` (a short "Implemented in plan G1" note), `docs/decisions.md` (a new *Proposed* row: bibliography anchors `b<n>`, rulings 1–20 [confirm], numbered at merge), `docs/specs/01-rigour.md` (R-xx(a)–(d) as proposed rows), `CLAUDE.md` (status line); Test `tests/test_acceptance_references.py`.

- [ ] **Step 1: Acceptance test** `test_acceptance_references.py`: one project, hand-built documents (no network), covering acceptance 1, 3-12, 14-16 of the spec in one flow: extract -> status counts sum -> ambiguous link proposed by an agent, confirmed by a human -> backward round (dry run, then real) -> candidates pending -> screened -> second round refused by plan -> forward round obeys max -> compare -> PRISMA detail and report rows -> rebuild state hash identical -> scan of the events directory and blobs for document text beyond entry text and marker tokens. Acceptance 2 is the fixture-set scoring test of Task 3 (`test_parse_quality_report`, prints recall figures, asserts the PDF-style floor flag). **Step 2:** Run; FAIL where wiring is missing; fix. **Step 3:** Write the skill: when to extract, how to read an ambiguous pair, the proposal format (verbatim quotes of both entries), never confirm, run rounds only after the researcher's go-ahead, report yield; version hash via the existing skill-hash mechanism. **Step 4:** Docs edits above; full suite, mypy, ruff, coverage >= 90% for `services/` and `model/`. **Step 5:** Commit `test(references): plan G1 acceptance; docs`.

## Self-review notes

- **Spec coverage.** Anchors (T1, T2); parsing, markers, contexts, completeness, bbl (T3); resolution, link states, decisions, identity reuse, `no-source-record` (T5); events and tables (T4); protocol stopping rule and gap (T4, T6); backward rounds, PRISMA-S fields, pending candidates (T6); forward round and comparison (T7); PRISMA other-methods, search report, methods, trace, check, seed route (T8); MCP and CLI incl. pass-session refusal (T9); skill, acceptance, decisions, rigour rows (T10). Rulings 1, 2, 4, 11 (G2/G3) have no task by design; ruling 12 is Task 3 step 1; ruling 20 is Tasks 5-6.
- **Types.** `LinkState`, `Confidence`, `Decision`, `Direction`, `Via` are defined in Task 4 and used unchanged in 5-9; `Candidate` (T5, `match.py`) is a corpus title candidate; `RoundCandidate` (T6) is a snowball candidate.
- **Risk.** Tasks 1 and 4 touch the anchor grammar and the projection; their regression gate is the unchanged earlier suites and the pinned `P@` and `PROJECTION_VERSION` literals. The matcher thresholds (T5) and the unresolved ceiling (T8) are provisional and are set from the fixtures and the pilot. Tier summary: Tasks 1, 4, 5, 6 critical (Sonnet task reviews); Tasks 2, 3, 7, 8 standard (Haiku reviews; Task 3 gets a fixture-based accuracy report); Tasks 9, 10 Haiku. The final whole-branch review runs on Sonnet. Decision 49 affects none of these tasks.

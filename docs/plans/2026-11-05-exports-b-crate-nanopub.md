# RO-Crate and Nanopublication Exports Implementation Plan (slice 7b, sub-plan X-B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Status: draft — rulings recommended; awaiting the researcher's review before any build.

> **Dependencies.** X-A merged (`assign_keys`, `export_bibliography`, `export_prisma_svg`, `select_works`). W-B merged (`draft.released`, `draft_render`), because released drafts are crate members; without W-B the crate omits drafts (the task guards on the table's existence only through the service, not by feature flags). Plans 2E (`evidence_markdown`, `rows_csv`, `points_csv`), 5b (`methods_report`, `render_methods`, `search_report`), G2-D (`graph_export`) merged. Resolves Open decision 22 as proposed in the spec (D-7b-3).

**Goal:** Package a project as an RO-Crate 1.1 that a reader can audit without the factory (events, text blobs, reports, bibliography, a manifest of library documents without their content), and export claims and stated lineage edges as unsigned nanopublications in TriG.

**Architecture:** Pure helpers in `exports/rdf.py` (term escaping, sorted TriG writer), `exports/nanopub.py` (graphs per claim or edge), `exports/crate.py` (JSON-LD entities). `services/exports.py` gains `export_nanopubs` (streamed) and `export_crate` (writes a directory or zip at a path the researcher names). No event is written; the library is read only for metadata already in events (the manifest comes from full-text events).

**Tech Stack:** stdlib `json`, `zipfile`, `hashlib`; test-only `rdflib>=7` (dev group) to parse TriG and JSON-LD; no runtime dependency.

**Spec:** `docs/specs/slice-7b-views-writing.md` rulings 20, 21, 22; acceptance 13 (crate and nanopub parts). R-04, R-05, R-47; decisions 22 (Open → D-7b-3), 39.

## Rulings made in this plan
1. **Crate layout [confirm].** `ro-crate-metadata.json`; `events/` (copy of `projects/<slug>/events/`); `blobs/` (copy of the text blobs referenced by events); `protocol/protocol.json` (current `ProtocolSpec` and amendment list); `reports/prisma.md`, `reports/prisma.svg`, `reports/search.md`, `reports/methods.md`, `reports/evidence.md`, `reports/evidence-rows.csv`, `reports/evidence-points.csv`, `reports/lineage.json` (G2-D default view, when the graph exists), `reports/drafts/<drf_…>.md` (released drafts in clean form, rendered from the current log, with the release record beside it as `<drf_…>.release.json`); `bibliography/included.bib`, `bibliography/included.csl.json`; `library-manifest.json`. Nothing from `library/`, `.index/`, or any path outside the project.
2. **Manifest.** One entry per library document from full-text events: `document_id`, `work_id`, `sha256`, route, URL, source version, licence and licence status, retrieved-at; conversions with converter name and version and their hashes. A reader restores with `factory fulltext restore` or by URL and checks hashes.
3. **Entities.** Root `./` (`Dataset`, name = project slug, `description` = the question's raw goal (authored text, not literature), `datePublished` = timestamp of the last event, `license` from project settings when set); one `File` per member with `encodingFormat` and `sha256`; one `CreateAction` per generated report (`instrument` = `#factory` `SoftwareApplication` with version, `object` = `#log` with the last event id, `result` = the file); one `SoftwareApplication` per (model, skill reference) found in agent events, with `#n-events` as a `PropertyValue`; `Person` for the configured user (ORCID when set). Conforms to RO-Crate 1.1 (`conformsTo` `https://w3id.org/ro/crate/1.1`).
4. **Nanopublication shape [confirm].** Base `http://purl.org/nanopub/temp/<slug>/<id>/` per nanopub; graphs `Head`, `assertion`, `provenance`, `pubinfo`. Claim: `sub:claim a rfv:Claim; rdfs:label "<statement>"; rfv:claimType rfv:<type>; rfv:evidenceType rfv:<type>; cito:citesAsEvidence <https://doi.org/…>` (or `<https://arxiv.org/abs/…>`; a work with neither is skipped and counted). Provenance: `sub:assertion prov:wasDerivedFrom <work IRI>; rfv:anchor "<anchor>"; rfv:conversionSha256 "…"; rfv:quoteSha256 "…"; prov:wasAttributedTo sub:agent. sub:agent rfv:model "…"; rfv:skill "…"; rfv:agentStrength "<strength>"`. Edge (`--edges`): `<work A IRI> rfv:buildsOn|rfv:improvesOn <work B IRI>` with provenance `rfv:status "stated|confirmed"` and the basis row's quote hash. `pubinfo`: `dcterms:creator` (ORCID or `mailto:` absent → literal user name), `dcterms:created` = last event timestamp. `rfv:` = `https://w3id.org/research-factory/vocab#` (a placeholder namespace until the researcher registers one; configurable). `--with-quotes` adds `rfv:quote "<quote>"` to provenance.
5. **Determinism.** Triples sorted by (graph, subject, predicate, object) in N-Triples term order; prefixes fixed; literals escaped per Turtle (`\\`, `\"`, `\n`, `\r`, `\t`, `\u` for control characters); nanopubs ordered by claim id, then edge id.

## Global Constraints
- No library content in any export (R-47, decision 39); the crate test walks the output tree and compares every file hash with the library: zero matches.
- Exports are byte-identical for the same log (zip with fixed timestamps `1980-01-01`, sorted entries, `ZIP_DEFLATED` level 9).
- No network, no signing, no publication; the CLI prints how to sign with nanopub tooling, without running it.
- CLI only for crate and nanopub (spec ruling 22); writes only to `--out`.
- TDD; `uv run pytest -m "not network and not slow"`; `mypy --strict`; ruff; coverage ≥ 90%.

## Review Focus
1. No library file in the crate, even for an openly licensed document (Task 4, `test_no_library_content`).
2. Nanopubs contain no quote text by default (Task 2, `test_no_quotes_by_default`).
3. TriG parses with rdflib into exactly four named graphs per nanopub (Task 2, `test_trig_parses_four_graphs`).
4. The crate's `hasPart` lists every file and only those files (Task 4, `test_has_part_complete`).

## File Structure
- Create `exports/rdf.py`, `exports/nanopub.py`, `exports/crate.py`.
- Modify `services/exports.py`, `cli/main.py`.
- Tests: `tests/test_export_rdf.py`, `tests/test_export_nanopub.py`, `tests/test_export_crate_entities.py`, `tests/test_export_crate.py`.

### Task 1: TriG writer

*Tier: standard.*

**Files:** Create `exports/rdf.py`; Test `tests/test_export_rdf.py`.

**Interfaces:**
- Produces: `IRI = NewType("IRI", str)`; `@dataclass(frozen=True) Literal_(value: str, datatype: IRI | None = None)`; `Triple = tuple[IRI, IRI, IRI | Literal_]`; `PREFIXES: Mapping[str, str]` (`np`, `prov`, `dcterms`, `cito`, `rdfs`, `xsd`, `rfv`, `sub`); `escape_literal(s: str) -> str`; `trig(graphs: Mapping[IRI, Sequence[Triple]], *, prefixes: Mapping[str, str]) -> str` (ruling 5).

- [ ] **Step 1: Tests.** `test_escape_cases`; `test_sorted_output`; `test_iri_validation` (spaces or `<>` rejected); `test_rdflib_round_trip` (parse; same triples).
- [ ] **Step 2–4.** **Step 5:** Commit `feat(exports): deterministic TriG writer`.

### Task 2: Nanopublications

*Tier: standard.*

**Files:** Create `exports/nanopub.py`; Modify `services/exports.py`; Test `tests/test_export_nanopub.py`.

**Interfaces:**
- Consumes: `live_claims(project, PassLabel.A)`, included works, `get_work`, extraction events for conversion hashes, G2-D lineage edges in the default filter with basis rows.
- Produces (`exports/nanopub.py`): `claim_nanopub(claim: ClaimRow, work: Work, *, slug: str, creator: str, created: str, conversion_sha256: str, with_quotes: bool, vocab: str) -> dict[IRI, list[Triple]] | None` (`None` when the work has no DOI or arXiv id); `edge_nanopub(edge: GraphEdge, source: Work, target: Work, *, basis_quote_sha256: str | None, …) -> dict[IRI, list[Triple]] | None`.
- Produces (`services/exports.py`): `NanopubSummary(written: int, skipped_no_identifier: int, claims: int, edges: int)`; `export_nanopubs(project, out: Path, *, edges: bool = False, with_quotes: bool = False) -> NanopubSummary` (one `.trig` file per nanopub under `out/`, named by claim or edge id; streamed).

- [ ] **Step 1: Tests.** `test_trig_parses_four_graphs` (Review Focus 3); `test_head_links_graphs`; `test_no_quotes_by_default` and `test_with_quotes_adds_literal` (Review Focus 2); `test_agent_strength_labelled_as_agent`; `test_only_included_live_pass_a_claims`; `test_inferred_edges_excluded`; `test_skipped_counted`; `test_byte_identical_across_rebuilds`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(exports): nanopublications of claims and stated edges`.

### Task 3: Crate entities and library manifest (pure)

*Tier: standard.*

**Files:** Create `exports/crate.py`; Test `tests/test_export_crate_entities.py`.

**Interfaces:**
- Produces: `@dataclass(frozen=True) CrateFile(path: str, sha256: str, encoding_format: str, produced_by: str | None)`; `@dataclass(frozen=True) AgentEntry(model: str, skill: str, events: int)`; `ManifestEntry` (ruling 2 fields); `crate_metadata(*, slug: str, description: str, last_event: str, last_ts: str, licence: str | None, person: str, orcid: str | None, factory_version: str, files: Sequence[CrateFile], agents: Sequence[AgentEntry]) -> str` (JSON-LD, sorted keys, `@graph` sorted by `@id`); `manifest_json(entries: Sequence[ManifestEntry]) -> str`.

- [ ] **Step 1: Tests.** `test_descriptor_and_root_present` (`ro-crate-metadata.json` entity `about` `./`, `conformsTo` 1.1); `test_has_part_complete` (Review Focus 4); `test_create_action_per_report`; `test_agents_aggregated`; `test_jsonld_parses_with_rdflib`; `test_deterministic`.
- [ ] **Step 2–4.** **Step 5:** Commit `feat(exports): RO-Crate entities and library manifest`.

### Task 4: Crate assembly service and CLI

*Tier: standard.*

**Files:** Modify `services/exports.py`, `cli/main.py`; Test `tests/test_export_crate.py`.

**Interfaces:**
- Consumes: X-A services, 2E renderers, 5b reports, G2-D `graph_export`, W-B `draft_render` and release rows, full-text events (manifest), the event reader for agent aggregation (one streaming pass).
- Produces: `CrateSummary(files: int, bytes: int, documents_listed: int, drafts: int)`; `export_crate(project, out: Path, *, zip_: bool = False) -> CrateSummary` (refuses an `out` inside `projects/`; refuses a non-empty directory unless `--force`).
- CLI: `factory export crate --out PATH [--zip] [--force]`; `factory export nanopub --out DIR [--edges] [--with-quotes]` (prints the summary and the sentence "unsigned; sign and publish with nanopub tooling").

- [ ] **Step 1: Tests.** `test_no_library_content` (Review Focus 1: walk output, hash every file, none equals a library hash); `test_manifest_lists_every_document`; `test_reports_equal_service_output`; `test_zip_byte_identical`; `test_out_inside_project_refused`; `test_released_drafts_included_unreleased_not`; `test_crate_without_graph_or_drafts` (fields omitted, no error).
- [ ] **Step 2–4.** **Step 5:** Commit `feat(exports): RO-Crate export and export commands`.

## Self-review notes
- Released drafts are rendered from the current log; if a released draft has since become stale, the crate includes its release record and the current status counts so the difference is visible.
- Decision 22 is proposed for resolution in the spec (D-7b-3); this plan implements only the export direction.

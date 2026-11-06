# Slice 3d — Regions, labels and consolidation; importing an existing corpus

Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted). Decisions 59 and 60; requirements R-90–R-92.

## Cross-spec reconciliation 2026-11-04

1. **Provenance and PRISMA order.** `ProvenanceMethod` gains `library-import` after slice 4a's `supplied`; PRISMA's "other methods" precedence is `citation-chase`, `seed-admission`, `hand-search`, `supplied`, `library-import` (decision 38 item 6 unchanged: any `database` provenance wins). Ruling 22 is read with this order.
2. **Coverage buckets (ruling 25).** `found-supplementary` counts only works in the corpus through `citation-chase`, `seed-admission` or `hand-search`. A work whose only non-import provenance is `supplied` (slice 4a) was not found by any search and falls into one of the not-found buckets, as slice 4a ruling 9 treats a supplied seed. Watch runs (slice 4b) are search-purpose database runs and count as `found-database`.
3. **Query purposes.** `import` (here), `supplied` (4a) and `status` (4b) are three distinct new `QueryPurpose` values; only `import` and `supplied` runs create corpus works.
4. **Epistemic class.** `organisation` is the third class beside slice 3c's `evidence` and `interpretation`; slice 6's property vocabulary is also `organisation`, and slice 6 adds `test` (closed set, slice-M reconciliation item 7).
5. **Identifiers.** Label applications are `lbl_<ULID>` (draft `lab_`, renamed so as not to read as slice 5's lab registry). The import id stays `imp_`; slice M's mining import uses `mim_`.
6. **Gates (ruling 26).** Slice M is built before this slice (build order), so the gates are declared directly: `regions.review`, `regions.member_decide`, `labels.application_confirm`, `consolidation.decide`, `terms.promote` (floor and presets `human`) and `import.resolution_confirm` (presets as `reference.link_confirm`). The modules are `import` (`retrieval`), `regions` (`proposal`, with rule evaluation as its builder hook), `labels` (`proposal`).
7. **Requirements** R-xx(k), (l), (m) are R-90, R-91, R-92 in [01-rigour.md](01-rigour.md).
8. **Projection version.** Each plan of this slice that adds a table bumps `PROJECTION_VERSION` by one from the value it finds.
9. **Consumers.** Slice 4b's per-region digests, slice 6's region-scoped vocabulary and transfer flag, and slice 7b's onion overlay read reviewed `R@` snapshots through the Regions-B read interface; each of these is Later in its own slice.

## v1 scope

- **v1:** BibTeX, CSL JSON and PDF-folder import with archive, split, resolution, confirmation, admission under `library_sources`, attachments and coverage (Import-A, -B, -C); regions and foci with rules, snapshots, drift and review (Regions-A); member proposals, links, overlap and the MCP tools (Regions-B without adoption); labels, consolidation, terms and the `term` rule with the separation tests (Regions-C, automated acceptance).
- **Later:** cross-project adoption of region snapshots (ruling 10; Regions-B adoption task); the researcher-run pilot (acceptance 18); open question 3 (draft region per Zotero collection).

Builds on [00-system.md](00-system.md), slices 1, 2, 3a, 3b and 3c; must satisfy [01-rigour.md](01-rigour.md) R-01–R-05, R-20, R-22–R-26, R-43, R-47, R-51, plus the proposed requirements below. Covers the remainder of outline slice 3 ("Graph and regions", [README.md](README.md)) that slices 3a–3c leave open: regions and project foci; consolidation (synonym merging, label promotion); importing an existing corpus (Zotero export, BibTeX, a PDF folder) with an audit of its coverage by the systematic search (production line 3, [docs/02-production-lines.md](../02-production-lines.md)). Vocabulary: [docs/10-abstractions.md](../10-abstractions.md).

**Depends on:** slice 3b (graph projection and queries, plan G2-D), slice 3c (concepts, layer tables), slice 3a (reference resolution and the `reflist` pattern), plan 2A (`record_supplied_document`). The stage-module contract (`docs/specs/slice-M-modules.md`, written in parallel) is not required: the import and the region builder are written first as hand-written modules with their own event families, and move behind the contract when slice M lands (the import as a retrieval module with strategies per format; region evaluation as a builder; consolidation as a proposal module with a human gate). Nothing here assumes the contract's names.

## Goal

1. Give the graph a **reviewed, versioned unit of organisation above the node**: a region (and, as a special kind, a project focus) that later slices can name by a pinned id: slice 4 for alerts per region, IDEA-04 for cross-project suggestions, slice 6 for cross-region matching and hypotheses.
2. Honour decision 5 (free labels, scheduled consolidation and promotion) without reintroducing free labels into the evidence graph that slice 3b deliberately typed: labels live in their own organisation tables, are consolidated by a recorded, reversible procedure, and become usable as selectors only after promotion to a typed vocabulary term.
3. Let a researcher **start from a library they already have** (production line 3): import it with provenance, resolve each record to a work, optionally admit it to the corpus as candidates for screening, attach its PDFs, and measure how much of it the systematic search finds and why the rest was missed.

Pilot for acceptance: **best linear attention mechanism for vision models.** A focus region per question slot (for example *linear attention* and *vision backbones*), one surrounding region defined by a lineage rule from a base attention formulation, one promoted term created by merging two labels (for example `performer` and `favor+`), and a coverage audit of a small hand-built BibTeX library (researcher-supplied, not drawn from `docs/pilot/heldout-seeds.md`) against the pilot's search.

## User flow

**Import (line 3).**
1. The researcher runs `factory import bib|csl|pdfs <path> --role reference|corpus [--collection NAME]`. The platform archives the file verbatim in the library, parses it into **import records** (bibliographic fields only), and draws a recorded development/held-out split when the import precedes the first search-purpose run.
2. `factory import resolve <imp_>` resolves every record to a work identity with the slice-3a resolver: corpus identifiers, then probe-purpose lookups, then title match. Fuzzy matches wait for confirmation under the slice-3a policy.
3. For a `corpus` import, `factory import admit <imp_>` registers import-purpose queries (identifier lists against OpenAlex and arXiv for resolved records, the offline `importlist` source for the rest) and runs them. New works carry provenance method `library-import`; dedup runs as usual; every admitted work is a pending candidate and passes the protocol's screening.
4. When an imported record's work is promoted, `factory import attach <imp_>` records the PDF that the export named for it as a researcher-supplied document.
5. `factory import coverage <imp_>` (and the MCP `import_coverage`) reports, for every resolved record, whether the systematic search found it, and if not, why (outside the limits, not in a declared source, missed by the queries), with vocabulary suggestions for query misses. The held-out figure is the honest one.

**Regions.**
6. The researcher (`factory regions define`) or an agent (`region_propose`) states a region: name, kind (`focus` or `region`), a short definition, and typed **rules** over the corpus and the graph. A focus names the question slot it covers.
7. `region_status` shows the live evaluation of the rules and the drift from the last snapshot. `factory regions snapshot` (or the MCP `region_snapshot`) fixes the member set as a version `R@<sha8>`; the researcher reviews the version (`factory regions review`). Agents may propose individual members with a basis; the researcher adds or removes members explicitly.
8. Later stages name regions by `R@`: another project may adopt a reviewed snapshot read-only; slice 4, IDEA-04 and slice 6 consume reviewed snapshots.

**Labels and consolidation.**
9. Agents and the researcher attach free **labels** to works, ideas and concepts (`label_apply`); Zotero tags arrive as labels applied by the researcher. Labels are not evidence and are not drawn in the graph's default views.
10. When consolidation is due, `consolidation_next` serves deterministically computed candidate clusters (similar label keys, shared targets, idea and concept names); an agent proposes merges; the researcher decides. The researcher promotes a consolidated label to a **term** with a definition and aliases; applications of a term are stated (a verified quote contains the name or an alias) or confirmed by a human. Only terms may appear in region rules.

## Rulings

Each ruling lists options; the recommended option is marked **[confirm]**.

### What a region is

1. **Region = reviewed definition + typed rules + pinned member set.** Options: (a) an extensional set of members chosen one by one; (b) a saved query, evaluated whenever read; (c) both: a region has a definition, declared rules evaluated deterministically over the projection, explicit human member decisions, and **snapshots** that pin the resulting member set as a version `R@<sha8>`. **(c) [confirm].** A pure set does not scale past a few hundred members and records no reason for membership; a pure query drifts silently as the graph grows, so nothing downstream could cite it. Version identity follows `P@`: `R@` is the hash of the decision-relevant fields (kind, facet, rules in canonical form, explicit decisions, and the hash of the sorted member set), never of the definition prose.
2. **Members.** Options: (a) works only; (b) works, ideas (`ida_`) and concepts (`cpt_`); (c) any node including interpretations. **(b) [confirm].** Ideas and concepts are what IDEA-04 and slice 6 match across fields; interpretations are explanations of nodes, not things a field contains. Work members are stored as canonical ids at snapshot time (dedup's `canonical_works`, absorbed ids resolved); idea and concept members as their live (merge-resolved) ids.
3. **Rule language.** Options: (a) free SQL or a query language; (b) a closed set of typed rule kinds combined by include, exclude and within; (c) embedding similarity. **(b) [confirm]** (decision 9 leaves embeddings open; free SQL is unreviewable and couples regions to the index schema). Rule kinds, each deterministic and evaluated against the index:
   | Kind | Parameters | Selects |
   | --- | --- | --- |
   | `corpus` | `outcome` (`included`, `screened`, `all`), `stage` | works of this project by final outcome at a stage |
   | `run` | `run_id` or `query_id` | works retrieved by a recorded search run or query |
   | `import` | `import_id`, `part` (`development`, `all`) | works resolved from an import (agents may only name `development`) |
   | `lineage` | `node`, `direction` (`ancestors`, `descendants`), `depth` ≤ `MAX_DEPTH`, `edge_types`, `status` (default stated and confirmed) | the slice-3b traversal |
   | `cites` | `base` (a pinned `R@`), `direction` (`citing`, `cited`), `min_k` ≥ 1 | works citing (or cited by) at least `min_k` members of the base region |
   | `idea` | `idea_id` | a confirmed idea and its members |
   | `concept` | `concept_id` | nodes with a stated or confirmed `uses` link to the concept (slice 3c) |
   | `term` | `term_id` | targets with a stated or confirmed application of a promoted term |
   | `region` | a pinned `R@` | the members of that version |
   | `text` | term blocks (AND of OR-lists) | corpus works whose normalised title or abstract contains them |
   A region's membership is `(∪ include ∪ human adds) ∩ within − (∪ exclude ∪ human removes)`. References to other regions are always to pinned versions, so rule graphs are acyclic by construction and one region's new snapshot never changes another's membership silently. There is no `seed` rule: seed status, held-out membership and screening-pass internals are never selectable (I8).
4. **Evaluation bounds.** Options: (a) reuse slice-3b `MAX_RESULTS = 500`; (b) region-specific caps with refusal on overflow; (c) no caps. **(b) [confirm].** `REGION_MAX_MEMBERS = 200_000`; a rule whose evaluation exceeds it, or a `lineage` rule truncated by the G2-D bounds, refuses the snapshot with the rule index and count; a region is never silently partial. Evaluation streams through indexed SQL into a temporary table and reuses the neighbour-lookup helpers of `lineage/paths.py` with region bounds (the G2-D scale ruling: no full-graph load).
5. **Snapshots and drift.** A snapshot records the member set as a deterministic compressed blob (sorted ids, gzip with fixed header, in `blobs/`), its hash, counts by member type, per-member basis (the rule indices that selected it, or the decision id), and `as_of`, the id of the last event folded into the index when it was evaluated. Live evaluation is computed on read; `drift` (members added and removed since the last snapshot) is reported by `region_status` and `check`, never acted on automatically. Snapshots are taken on request; scheduling them is slice 4.
6. **Review.** Options: (a) no review; (b) human review of each region version, agents propose; (c) review of the definition only. **(b) [confirm].** States as slice 3c (`unreviewed`, `reviewed`, `wrong`, `superseded`), set only by a human in the CLI; the writer of a region definition does not review it (R-51; one-person projects record `self-reviewed`, slice-3c ruling 8). Consumers outside the project (adoption, IDEA-04, slice 6) accept only `reviewed` versions; inside the project, unreviewed versions are usable and labelled.
7. **Epistemic class.** Options: (a) treat regions as interpretation (slice-3c class); (b) a third class `organisation`. **(b) [confirm].** A region selects; it asserts nothing about any paper. Region, term and label tables are separate from the evidence tables and from the slice-3c layer tables; evidence services do not import their modules (architecture test); evidence outputs are byte-identical with and without regions and labels (differential test). No evidence output takes a region filter in this slice; a later slice that adds one must print the `R@` it used.

### Foci

8. **A focus is a region of kind `focus` bound to one question slot.** Options: (a) a region kind; (b) a protocol section; (c) no artifact (foci are the question's slots). **(a) [confirm].** A focus names `Q@` and a slot name (`QuestionSpec.slots[].name`); at most one live focus per slot; a new `Q@` that drops the slot marks the focus `slot-missing` in `check`. The protocol is not changed: regions do not bind screening, so they stay outside the `P@` hash. Onion and distance views are slice 7; they read foci and region snapshots.
9. **Agent member proposals.** An agent may propose a member with a basis (`region_propose_member`): a verified quote of the candidate work (anchor, verbatim, pinned conversion) or a lineage, `cites` or `uses` edge id. The platform verifies the basis; the researcher adds or rejects (`factory regions add|remove`). Proposed members never enter a snapshot until decided. Options: (a) as stated; (b) no agent proposals. **(a) [confirm]**; at scale, membership comes from rules, and proposals serve small hand-built regions.
10. **Cross-project adoption.** Options: (a) a project adopts a reviewed snapshot of another project read-only (`region.adopted` copies the member blob, verified by hash, and names the source project, region and `R@`); (b) defer everything cross-project to slices 5 and 6. **(a) [confirm].** Work ids are content-derived, so an adopted member set intersects the adopting project's corpus without mapping. Adoption never changes the adopting corpus; the newer source snapshot is reported as `region-adoption-outdated` when the source project is readable. Ownership and review of shared regions are slice 5 (IDEA-11).
11. **Region links.** `region.linked` declares `subregion-of` (verified on both snapshots: members ⊆; a violation is a `check` finding) or `related` (with a note, organisation class). Overlap between two versions is computed (shared counts by member type, Jaccard), never stored.

### Labels, consolidation, promotion (decision 5 reconciled with slice 3b)

12. **Where free labels live.** Options: (a) no free labels (slice 3b alone); (b) free labels on graph nodes in the graph tables; (c) free labels in separate organisation tables, never in `graph_nodes`, `graph_edges` or the layer tables, never evidence, consolidated and promoted before any selector may use them. **(c) [confirm].** It keeps decision 5 (Decided: free labels outside the strict core, scheduled consolidation and promotion) and slice 3b's typed graph. Free relation names on edges (also allowed by decision 5) are not introduced in this slice: no consumer needs them before slice 6, and the typed edges of 3b and 3c cover the lineage.
13. **Label application.** A label is a short free text (≤ 60 characters) applied to a work, idea or concept; its key is the case-folded, whitespace-collapsed, NFKC text. An application by a human (CLI, or Zotero tags in an import) is `confirmed`; an agent's application is `stated` when it carries a verified quote containing the label key, else `inferred` (shown labelled in label views only). Applications are superseded or withdrawn by new events, never edited.
14. **Consolidation is due, not optional.** `check` reports `consolidation-due` when, since the last completed consolidation pass, more than `CONSOLIDATION_DUE_LABELS = 50` new label keys or `CONSOLIDATION_DUE_NODES = 10` new ideas or concepts exist (platform constants, provisional). A snapshot of a region that uses a `term` rule is refused while consolidation is due in `systematic`, advisory otherwise. Options for the due rule: (a) counts as stated; (b) time-based; (c) none. **(a) [confirm]**; time-based scheduling arrives with slice 4.
15. **Candidate computation (platform) and proposals (agent).** The platform computes candidate synonym clusters deterministically, per artifact kind (label keys, ideas, concepts): string similarity of normalised names and aliases (`rapidfuzz` ratio ≥ `SYNONYM_RATIO = 0.90`), acronym match (initials of a multi-word name equal a short name), and target overlap (Jaccard of target or member sets ≥ `SYNONYM_OVERLAP = 0.5`, computed only for pairs sharing at least one target through an inverted index, so cost is bounded by co-occurrence, not by all pairs). Each cluster names the signals that produced it. `consolidation_next` serves one cluster; the agent records `consolidation.proposed` (merge, keep separate, or split) with a reason and optional verified quotes; the researcher decides. Merges of ideas and concepts use the existing `idea.merged` and `concept.merged` events, which gain an optional `proposal` reference; labels gain `label.merged` / `label.unmerged`. All merges are reversible (R-26 spirit) and restore the previous projection exactly. Options: (a) as stated; (b) automatic merges above a threshold. **(a) [confirm]** (the "Performer" / "FAVOR+" case is caught by target overlap, not string similarity, and still needs a reader).
16. **Promotion to a term.** The researcher promotes a label key (with its merged keys as aliases) to a **term** (`trm_<ULID>`): preferred name, aliases, a definition of at most 600 characters, the node types it applies to, and optionally `refers_to` an idea or concept (navigation only; a term is organisational, a concept is an interpretation, slice 3c). Promotion is human only; a suggested promotion list (label keys with at least `PROMOTION_MIN_TARGETS = 3` distinct targets) is computed. Term revisions are new versions; a retired term stays in the log. An application of a term is the live label applications whose key is the term's name or an alias, classified as in ruling 13; inferred ones wait for human confirmation (batch confirmation in the CLI). Options for who promotes: (a) human; (b) agent with audit. **(a) [confirm].**

### Import

17. **Formats.** Options: (a) BibTeX only; (b) BibTeX, CSL JSON and a PDF folder; (c) (b) plus RIS and the Zotero web API. **(b) [confirm].** Zotero exports both BibTeX (with `file` and `keywords` fields) and CSL JSON; most other managers export one of them. RIS is a later format behind the same parser registry; the Zotero web API needs stored credentials and network access and is out of scope. One file per import; a Zotero collection is imported as its own file, named by `--collection`.
18. **BibTeX parser.** Options: (a) `bibtexparser` 1.4 (pure Python, LaTeX-to-Unicode conversion; dual LGPL-3.0/BSD); (b) `pybtex` (MIT; LaTeX decoding through `pylatexenc`); (c) a parser written here. **(a) [confirm]**, pinned `bibtexparser>=1.4.1,<2`, wrapped in `factory/imports/bibtex.py` so a swap changes one module; the parser name and version are recorded on every import (as `PARSER_VERSION` in slice 3a). CSL JSON is parsed with pydantic models; the PDF-folder reader reuses `sniff_identifiers` and the PDF's metadata title.
19. **What is stored where.** The export file is archived **verbatim in the library** (git-ignored; exports carry personal notes, abstracts and local attachment paths). Events and `blobs/` hold only an allow-listed canonical JSON of each record's bibliographic fields (title, authors, year, DOI, arXiv id, URL, venue, type, abstract, tags) and `record_sha256` of the record's raw text, as slice-3a ruling 14 does for reference entries. Notes, `annote`, `file` paths and any other field are not stored outside the library; a PDF attachment is recorded by relative-path hash and content hash. This satisfies R-03 (verbatim archive before parsing) and R-47.
20. **Role.** Options: (a) every import enters the corpus; (b) a declared role: `reference` (resolved, kept outside the corpus, used for coverage and as region input) or `corpus` (admitted as candidates); (c) a separate tool per role. **(b) [confirm].** A `reference` import is allowed at any time and changes no PRISMA count. A `corpus` import in `pilot` or `systematic` requires a ready, PRESS-confirmed protocol that declares the library in a new protocol section `library_sources` (name, format, role; amendable, omitted from the hash while absent, so existing `P@` ids are unchanged); in `exploratory` it is allowed and the missing declaration is a promotion gap. Imported records are candidates, never inclusions (IDEA-34 rigour): they are screened under the protocol like every record, and the slice-1 pass-B extension (`screening.sample_extended`, decision 38 item 3) applies to them.
21. **Resolution reuses slice 3a.** Records resolve by the ordered methods of `services/reference_resolve.py` (corpus identifier, probe-purpose identifier lookup, corpus title, probe-purpose title search; matcher `refmatch` with its thresholds). `resolve_entries` is generalised to accept any entry carrying an ordinal and the `RefFields` fields, so `ReferenceEntry` and import records share it unchanged. Fuzzy and ambiguous matches are confirmed under the slice-3a ruling 3 policy (human; in `pilot`, a second agent in an unrelated session). A record with no identifier and no title above the floor is `unresolved`, listed, never dropped. Options: (a) reuse; (b) a separate resolver for imports. **(a) [confirm].**
22. **Admission surface and provenance.** Options: (a) build every work from the export's fields; (b) admit resolved records through import-purpose identifier queries on OpenAlex and arXiv (so the work carries the source's metadata and abstract for screening), and the rest through an offline `importlist` source built from the stored fields, as the slice-3a `reflist` source. **(b) [confirm].** `QueryPurpose` gains `import`; `ProvenanceMethod` gains `library-import`, appended last in PRISMA's `OTHER_METHODS` precedence, so a work also found by a database search counts as database, and projects without imports keep identical counts. PRISMA reports `library-import` under "identified via other methods" with its own line; the PRISMA-S report lists the import with file hash, format, parser version and date. Import queries are authorised by the declared `library_sources` entry, as snowball queries are by their round (`register_query(..., import_id=...)`).
23. **Development and held-out parts.** Options: (a) no split; coverage reported as is; (b) a recorded random split (development ≈ 2/3, held-out ≈ 1/3; decision 36 pattern) drawn at import time when no search-purpose run has been recorded yet, since such a library may shape the queries; no split for imports after the first search run, whose coverage is labelled `post-search`; (c) always split. **(b) [confirm].** Agents never see which records are held out: MCP lists and the `import` rule expose the development part only, held-out coverage is withheld over MCP until a screening pass is opened (decision 43), and held-out records admitted to the corpus read as any corpus work (decision 37 item 9). The researcher may decline the split of a pre-search import; its coverage is then labelled `optimistic` in every report.
24. **Attachments.** Options: (a) attach PDFs only through the existing folder import (identifier sniffing, decision 46 item 7); (b) also attach the file the export names for a record, through the record's resolved work. **(b) [confirm]**, proposed as an extension of decision 46 item 7 (CLI only; promoted works only; the document route stays `researcher`). The export's record-to-file link is stronger than first-page sniffing (IDEA-26). The file's bytes are copied into the library at import time (exports move); a document is recorded only when the work is promoted. A record whose file is missing or unreadable is listed `attachment-missing`. For a PDF-folder import, identity comes from identifiers in the filename or first page and is cross-checked: the resolved title must occur, normalised, in the first page's text, else the record is `identity-unchecked` and needs confirmation. First-page text is read in memory and never stored.
25. **Coverage buckets.** Every resolved record of an import lands in exactly one bucket, computed on read:
    | Bucket | Rule |
    | --- | --- |
    | `found-database` | its work is in the corpus with `database` provenance from a search-purpose query |
    | `found-supplementary` | in the corpus only through `citation-chase`, `seed-admission` or `hand-search` (never through `library-import` itself, nor through slice 4a's `supplied`) |
    | `outside-limits` | not found; its metadata violates a declared protocol limit (years, language, type) |
    | `not-in-sources` | not found; within limits; the resolution lookups found it in no declared source |
    | `source-unchecked` | not found; within limits; a declared source was not looked up for it |
    | `query-miss` | not found; within limits; present in a declared source |
    Unresolved and unconfirmed records are counted apart. Reported figures: search sensitivity within reach, `found-database / (found-database + found-supplementary + query-miss)`; corpus coverage, `(found-database + found-supplementary) / resolved`; counts per bucket; the screening outcome of found records (included, excluded with criterion, pending), with excluded records listed for the researcher (a list, never a verdict); and the reverse count of included works absent from the library. Development and held-out parts are reported separately; the held-out figure is the one quoted. For `query-miss` records, `services/vocabulary.py::suggest_terms` proposes missing term blocks, as the probe does for missed seeds.

### Gates

26. **Gate policy before slice M.** Region review, member decisions, label and term confirmation, merges and promotion are human in every mode; import fuzzy-match confirmation follows slice-3a ruling 3; snapshot evaluation, candidate computation and coverage are deterministic and need no gate. When the gate-policy contract lands, these become declared policies with the same defaults. Options: (a) as stated; (b) allow agent review of regions with audit in `exploratory`. **(a) [confirm].**

## Design

### Region evaluation (builder)
`regions/rules.py` holds the rule models (a pydantic discriminated union on `kind`) and their canonical form; `regions/evaluate.py` evaluates one rule to a temporary table of `(member, member_type)` through an evaluator per kind that receives a connection and the region bounds. The combination step is set algebra in SQL. The result is identical whatever the order of rules (canonical rule order is part of the hash, evaluation is not order-dependent). Evaluation never reads the library and never calls a model. Basis per member is the sorted list of include-rule indices that selected it, or the decision id of a human add.

### Region lifecycle
`region.defined` (new region or new definition version; agent or human; definition text ≤ 600 characters; rules; kind; facet) → `region.snapshot_taken` (computed fields only; any actor, since it is deterministic bookkeeping) → `region.reviewed` (human) → later definitions and snapshots supersede. `region.member_proposed` (agent, with verified basis), `region.member_decided` (human: add, remove, reject proposal). `region.linked`, `region.adopted`. Live state and drift are computed in `services/regions.py`; the projector writes only event facts and the members of the latest snapshot of each region and of each adoption.

### Labels and terms
`label.applied`, `label.withdrawn`, `label.merged`, `label.unmerged`, `label.application_decided` (human confirm or reject of an inferred application), `term.promoted`, `term.revised`, `term.retired`. Consolidation: `consolidation.pass_started` (computed candidate clusters in a blob, the signal constants), `consolidation.proposed` (agent), `consolidation.decided` (human; references the merge event it produced, if any), `consolidation.pass_completed`. Label views, term lists and the graph export with `--with-labels` print the class `organisation` on every row.

### Import
`imports/` holds pure parsers (`bibtex.py`, `csl.py`, `pdfs.py`) producing `ImportRecord` values (ordinal, allow-listed fields, `record_sha256`, optional attachment reference) and a registry by format. `services/imports.py` records the import; `services/import_resolve.py` adapts records to `resolve_entries`; `services/import_admit.py` plans and runs admission queries; `services/import_attach.py` records documents through `record_supplied_document`; `services/coverage.py` computes the buckets. The `importlist` source in `sources/importlist.py` mirrors `sources/reflist.py`: query text is a list of record keys `imp_<ULID>:<ordinal>`, its raw page is the canonical JSON of the stored fields, and each work is built from them with `source = importlist`, method `library-import`.

### Deterministic versus agent
| Platform (deterministic, tested, offline except lookups) | Agent (Claude via MCP) | Researcher (CLI) |
| --- | --- | --- |
| Parse exports; archive; split; resolve; admit; attach; compute coverage buckets and figures | — (imports are CLI only) | Run imports; confirm fuzzy matches (pilot: a second agent may) |
| Evaluate rules; snapshot; drift; overlap; verify member bases; verify `subregion-of` | Propose regions, rules and members with bases | Define, review, add or remove members, link, adopt |
| Compute candidate clusters and promotion suggestions; classify label applications | Apply labels with quotes; propose merges with reasons | Decide merges, promote and revise terms, confirm applications |
Every agent-written event carries model, skill version and `input_blob` (R-04).

## Identifiers
`reg_<ULID>` (region), `R@<sha8>` (region version), `rmp_<ULID>` (member proposal), `lbl_<ULID>` (label application), `trm_<ULID>` (term), `cns_<ULID>` (consolidation pass), `cnp_<ULID>` (consolidation proposal), `imp_<ULID>` (import), record key `imp_<ULID>:<ordinal>`. Additions to the id table of 00-system §3 are recorded with the decision.

## Events (schema 1)
| Event | Payload (summary) |
| --- | --- |
| `import.recorded` | `import_id`, `format`, `role`, `collection`, `parser`, `parser_version`, `file_hash` (library), `records_blob` (canonical JSON of allow-listed fields and `record_sha256`), counts by parse outcome, attachment hashes; human |
| `import.split_drawn` | `import_id`, random seed, development and held-out ordinals (blob), or `post-search` |
| `import.resolved` | `import_id`, per-record `Resolution` (slice-3a model), lookup run ids |
| `import.resolution_decided` | `import_id`, `ordinal`, `confirm|reject`, work id, rationale; slice-3a policy |
| `import.admission_planned` | `import_id`, query ids by source, record keys per query |
| `import.attachment_linked` | `import_id`, `ordinal`, work id, document id (written with the plan-A document events) |
| `region.defined` | `region_id`, `kind`, `facet` (`Q@`, slot), `name`, `definition`, `rules`, `supersedes`, author, provenance |
| `region.snapshot_taken` | `region_id`, `version` (`R@`), `members_blob`, `members_hash`, counts by type, `basis_blob`, `as_of`, rule hash, decisions included |
| `region.reviewed` | `version`, `reviewed|wrong`, note, reviewer, `self_reviewed` |
| `region.member_proposed` / `region.member_decided` | proposal id, region, member, basis (quote with anchor and document version, or edge id) / decision (`add|remove|reject`), human |
| `region.linked` / `region.adopted` | link type, versions, note / source project, region, version, blob hash |
| `label.*`, `term.*`, `consolidation.*` | as in Design |

## Index tables (projections, written only by the projector)
`imports`, `import_records` (fields, resolution state, split part, attachment), `import_admissions`; `regions`, `region_definitions`, `region_snapshots`, `region_members` (latest snapshot per region and per adoption only; older sets read from their blobs on demand), `region_member_proposals`, `region_links`, `region_reviews`; `labels` (applications), `label_merges`, `terms`, `term_aliases`, `consolidation_passes`, `consolidation_proposals`. Indexes on `region_members(member)` (for `regions_of`) and `labels(key)`, `labels(target)`. Rebuild determinism holds; no evidence table gains a column.

## MCP tools and CLI
| Tool | Purpose | Actor |
| --- | --- | --- |
| `import_status` | Imports with counts by resolution state and bucket; development part only | read |
| `import_coverage` | Coverage report; held-out figures withheld until a pass is opened (decision 43) | read |
| `region_propose` | Define or redefine a region (agent author; unreviewed) | agent |
| `region_propose_member` | Propose a member with a verified basis | agent |
| `region_snapshot` | Evaluate and pin a version | agent or human |
| `region_status` | Live evaluation counts, drift, last version, review state | read |
| `region_query` | `members` (paginated), `regions_of`, `overlap`, `diff` between versions | read |
| `label_apply` | Apply labels (batched; partial acceptance; quotes verified) | agent |
| `consolidation_next` / `consolidation_propose` | Serve a candidate cluster / record a proposal | agent |
| `term_list` | Terms, aliases, application counts by status | read |
No MCP tool reviews a region, decides a member, merges, promotes or confirms. Pass sessions are refused every tool of this slice (decisions 37, 43, 48): a region over corpus outcomes is a view of screening results.
CLI: `factory import bib|csl|pdfs|resolve|confirm|admit|attach|coverage|list|show`; `factory regions define|revise|snapshot|review|add|remove|link|adopt|list|show|diff|export`; `factory labels list|apply|withdraw|merge|unmerge|confirm|reject`; `factory terms promote|revise|retire|list|suggest`; `factory consolidation status|start|list|decide|complete`; `factory graph export --with-labels`; `check` and `trace` extended. Skills: `rf-regions` (defining regions and proposing members), `rf-consolidate` (reading candidate clusters, proposing merges), each with a version hash.

## Check findings
Import: `import-unresolved` (count), `import-unconfirmed`, `import-attachment-missing`, `import-identity-unchecked`, `import-undeclared` (a `corpus` import without `library_sources`: promotion gap), `import-coverage-optimistic` (unsplit pre-search import). Regions: `region-unreviewed`, `region-drift`, `region-subregion-violated`, `region-focus-slot-missing`, `region-adoption-outdated`, `region-member-proposal-pending`. Labels: `consolidation-due`, `label-application-unconfirmed`, `term-unused`, `organisation-leak` (an evidence output referencing a region, label or term id; error, all modes). Messages carry ids and counts, never document text.

## Rigour requirements
Existing, in scope: **R-01, R-02** (imported works carry provenance to file hash, record and query; region members trace to their basis); **R-03** (the export is archived verbatim before parsing); **R-04**; **R-05** (coverage, drift, overlap and all counts derived); **R-20, R-24** (the held-out part of an import is handled as held-out seeds are); **R-22, R-23, R-25** (import admission runs are recorded searches reported under other methods); **R-26** (dedup of imported works; label, idea and concept merges recorded and reversible); **R-43, R-47** (attachments are recorded attempts; literature and personal notes stay in the library); **R-51** (agents propose regions, members, labels and merges; humans decide).

Added on acceptance (numbers in [01-rigour.md](01-rigour.md)):
- **R-90 Regions are versioned selections.** A region is cited only by a pinned, hashed version whose member set is derived from declared rules and recorded decisions; drift is reported, never applied silently; a region asserts nothing and changes no evidence value. All modes.
- **R-91 Consolidation before selection.** Free labels are never evidence and never select; only promoted terms with stated or human-confirmed applications may appear in a region rule; merges and promotions are recorded, reversible and human-decided. All modes.
- **R-92 Imported libraries.** An imported record carries provenance to the archived export; it enters the corpus only as a candidate for screening; the coverage of a library by the systematic search is derived per declared bucket and reported on a held-out part when the library preceded the search. P, S (exploratory: reported, not gated).

## Decisions (recorded 2026-11-04)
1. *Decision 59: Regions, foci, labels and terms.* Rulings 1–16 and 26; reconciles decision 5 (free labels, consolidation, promotion) with slice 3b (typed graph, no free labels in graph tables) by placing labels in organisation-class tables and admitting only promoted terms to selectors.
2. *Decision 60: Importing an existing corpus.* Rulings 17–25; adds `library-import` to `ProvenanceMethod` (after `supplied`) and `import` to `QueryPurpose`; adds the protocol section `library_sources`; extends decision 46 item 7 with export-named attachments and a title cross-check for PDF-folder imports; adds `bibtexparser` as a dependency.

## In scope
Region model, rules, evaluation, snapshots, review, member proposals, links, adoption; foci; labels, consolidation passes and proposals, merges, promotion to terms; BibTeX, CSL JSON and PDF-folder import; resolution, split, admission, attachments, coverage audit; PRISMA and PRISMA-S additions; tools, CLI, check, trace; skills `rf-regions`, `rf-consolidate`.

Implemented later: plan PI (`docs/plans/2026-11-05-pdf-intake.md`, decision 99) adds record descriptions, incremental admission and file names in the researcher's view.

## Out of scope
Onion, cluster and distance views (slice 7); scheduled re-evaluation, alerts and digests per region (slice 4); ownership and review of shared regions, a shared region store (slice 5, IDEA-11); cross-project suggestions themselves (IDEA-04) and cross-region matching (slice 6); free relation names on edges; embeddings (decision 9); RIS, Zotero web API, Mendeley databases; region filters on evidence outputs; any model call by the platform.

## Acceptance criteria
1. **Rule determinism.** Each rule kind returns the expected members on a constructed project; the same rules in a different order give the same `R@`; a rule over a pinned region is unaffected by that region's later snapshot.
2. **Bounds.** A rule exceeding `REGION_MAX_MEMBERS`, or a `lineage` rule truncated by the G2-D bounds, refuses the snapshot with nothing written; a scale test (`slow`) evaluates a lineage and a `cites` rule on 50,000 works and 500,000 edges within the declared time and without loading the graph.
3. **Snapshot.** `R@` changes when rules, decisions or the member set change and not when the definition prose changes; drift after a new included work is reported; a snapshot replayed from the event prefix up to `as_of` gives the same member hash (`slow`).
4. **Review and proposals.** Only CLI events review a region or decide a member; an agent session cannot; a proposed member with an unverifiable basis is rejected; an undecided proposal is absent from snapshots.
5. **Focus.** A focus names an existing slot; a second live focus on one slot is refused; dropping the slot in a new `Q@` raises `region-focus-slot-missing`.
6. **Adoption.** An adopted snapshot's blob hash is verified; adoption changes no corpus count; an unreviewed source version is refused.
7. **Labels.** A human application is `confirmed`; an agent application with a quote containing the key is `stated`, without one `inferred`; a non-verbatim quote is rejected; no label appears in `graph_nodes`, `graph_edges` or the layer tables.
8. **Consolidation.** Candidate clusters are identical across runs and name their signals; target-overlap pairs are found without an all-pairs scan; merges of labels, ideas and concepts and their reversal restore the projection exactly; `consolidation-due` appears at the stated counts.
9. **Promotion.** A term's applications are the live applications of its keys, classified as ruling 16; a `term` rule counts only stated and confirmed ones; an agent cannot promote.
10. **Separation.** The architecture test finds no import of region, label or import-coverage modules in evidence services; the differential test gives byte-identical evidence outputs with and without regions and labels; `organisation-leak` fires on a constructed leak.
11. **Parsing.** Fixed BibTeX (with LaTeX accents, `@string`, Zotero `file` and `keywords` fields), CSL JSON and PDF-folder fixtures parse to the expected records; no note, `annote` or file path appears in any event or git-tracked blob; the export's bytes are in the library under the recorded hash.
12. **Resolution.** Records resolve by the slice-3a methods with identical results to the same fields given as reference entries; fuzzy matches wait for confirmation; unresolved records are listed.
13. **Split and visibility.** A pre-search import draws a recorded split; MCP tools show development records only and withhold held-out coverage until a pass is opened; a post-search import has no split and is labelled.
14. **Admission and PRISMA.** A `corpus` import in `pilot` without `library_sources` is refused; admitted works carry `library-import` provenance and are pending; dedup links an imported record to a searched work; PRISMA counts `library-import` under other methods; a project without imports has identical PRISMA and search-report output.
15. **Attachments.** An export-named PDF is recorded as a document only after promotion; a missing file is listed; a PDF-folder record whose title is absent from its first page is `identity-unchecked`.
16. **Coverage.** On a constructed project, every resolved record falls in exactly one bucket; the figures equal hand-computed values; vocabulary suggestions are produced for query misses; the excluded-by-screening list carries no verdict.
17. **Rebuild and trace.** Deleting the index and rebuilding gives identical tables and state hash; `trace` from an imported work returns record, import, file hash and query; from a region member, its basis and the version's review state.
18. **Pilot.** The pilot produces two focus regions, one lineage region, one promoted term from a label merge, and a coverage report of a researcher-built library with bucket counts.
19. **Quality.** `mypy --strict` and ruff pass; coverage ≥ 90% for `services/` and `model/`; TDD; region evaluation, snapshot hashing, the import provenance change and coverage by subagent-driven development.

## Dependencies
| Slice / plan | Needed for |
| --- | --- |
| Slice 3b (plans G2-C, G2-D) | Ideas, relations, `graph_edges`, bounded traversal helpers, idea merges |
| Slice 3c (plan G3-B) | Concepts, `uses` links, concept merges |
| Slice 3a (G1) | `resolve_entries`, `refmatch`, the confirmation policy, the `reflist` source pattern |
| Plans 2A, 1–5 | `record_supplied_document`, `sniff_identifiers`, search runs, dedup, PRISMA, seeds split pattern, `suggest_terms` |
| Slice M (parallel) | Later: module contract and gate policies (ruling 26) |

## Proposed sub-plans
| Plan | Content | Tier | Depends on |
| --- | --- | --- | --- |
| Import-A (`2026-11-05-import-a-parse-archive.md`) | Parsers, registry, archive, `import.recorded`, split, projection, CLI | critical | plans 1–5, 2A |
| Import-B (`2026-11-05-import-b-resolve-admit.md`) | Resolver generalisation, resolution and confirmation, `library_sources`, `importlist`, admission, provenance method, PRISMA, attachments | critical | Import-A, G1 |
| Import-C (`2026-11-05-import-c-coverage.md`) | Coverage buckets and figures, suggestions, MCP read tools, check, trace, acceptance | standard | Import-B |
| Regions-A (`2026-11-05-regions-a-rules-snapshots.md`) | Rule models, evaluation, bounds, snapshots, drift, review, foci, CLI | critical | G2-D, G3-B |
| Regions-B (`2026-11-05-regions-b-members-links-adoption.md`) | Member proposals, links, overlap, adoption, MCP tools, `rf-regions`, check, trace | standard | Regions-A |
| Regions-C (`2026-11-05-regions-c-labels-consolidation.md`) | Labels, consolidation passes, merges, terms, `term` rule, separation tests, `rf-consolidate`, acceptance | critical | Regions-A |
Import and regions are independent until Regions-A's `import` rule, which reads Import-A's tables; that rule kind is added in Regions-A only if Import-A is merged, else in Import-C.

## Open questions
1. **Region scale in git.** A 10^5-member snapshot is about 0.5 MB compressed; frequent snapshots of large regions grow the repository. Recommendation: snapshots on request only; revisit with slice 4's scheduling (a delta encoding against the previous version is a possible later change, since blobs are content-addressed).
2. **`text` rule precision.** Keyword rules over titles and abstracts are imprecise. Recommendation: allowed, labelled in every member basis; a reviewer sees the rule.
3. **Labels from Zotero collections.** A collection is imported as a file with `--collection`; should it also create a draft region? Recommendation: yes, a draft region with an `import` rule, author human, unreviewed; offered by the CLI, not automatic.
4. **Coverage when sources differ.** A library item from a source the protocol does not declare (for example PubMed) is `not-in-sources` only if the declared sources were looked up; the platform does not look it up elsewhere. Recommendation: keep; the report names the declared sources.
5. **IDEA-35 discovery record.** `library-import` becomes one more route in the discovery record; whether an imported item later found by search counts for both routes is IDEA-35's open question, not ruled here.

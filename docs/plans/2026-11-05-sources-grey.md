# Sources and Grey Literature Implementation Plan (backlog triage, plan SG)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status: Proposed 2026-11-05 (backlog triage, `2026-11-05-backlog-triage.md`).** Items marked [confirm] await the researcher. Tasks 1 and 2 are held by decision 44 until the researcher answers R12. There is no slice spec for Tasks 3 to 7, only `docs/specs/outlines/grey-literature.md`, so their rulings are this plan's proposals.

> **Dependencies.** Base `d66387f` or later; Task 5 benefits from PI Task 1 (a PDF captured from the web needs a converter). Tools land after MS. Paths are relative to `platform/`.

**Goal:** Reach literature OpenAlex and arXiv do not: PubMed and PMC (IDEA-22), declared grey sources with captured snapshots (IDEA-24), RIS exports and publisher-page links (spec Later items).

**Basis:** No PubMed or JATS code exists (only a `pmid` identifier field). IDEA-22, 24; decisions 39, 40, 44, 60 (ruling 17: RIS is a later format behind the same registry), 61; slice 4a Later (`citation_doi`); R-21 to R-26, R-41; outline `grey-literature.md`.

**Projection:** Task 3 bumps `PROJECTION_VERSION` by one, and Task 6 by one. Others do not.

## Proposed decision (number fixed at merge)

**PD-7. Grey literature v1 [confirm].** Same pipeline, new provenance methods appended after `library-import` in the other-methods precedence, so existing PRISMA counts do not move (decision 75 item 2). Declared in a new protocol section `grey_sources` (method, target, stopping rule), omitted while absent. v1 methods: structured (OpenAlex types `report`, `dissertation`), `website` (declared URL list, captured), `agent-web-search` (reported, never the only method), `expert-contact` (log). Web search is an explicit exception to R-21, with a declared stopping rule, reported under PRISMA-S. Options on agent web search: (a) recorded as above; (b) left out of v1. **Recommended: (a).** ClinicalTrials.gov, GitHub and Hugging Face adapters are Later.

## Rulings made in this plan

1. **PubMed adapter.** E-utilities `esearch` plus `efetch`, polite-rate as `sources/http.py`, no truncation (R-21), PRISMA-S fields, `FACTORY_MAILTO` as the contact. An API key is not required; none is stored.
2. **PMC route.** The OA subset, `pmc-jats`, placed before `oa-pdf` in route order; a project without PMC ids sees no change. A JATS converter is lxml-only and deterministic, as `latexml_html` (decision 40), so it enters `default_converters` without touching decision 49.
3. **Capture.** A URL is fetched once to the library with hash, timestamp and headers. Capture accepts PDF (through PI's converters) and plain HTML, the latter through a small lxml converter under the same contract.

## Global Constraints

- No literature in tracked paths; captured pages live in the library (decision 39).
- Grey evidence is labelled and never pooled silently.
- Every adapter has a recorded-fixture test and one `network` fact test.

## Review Focus

1. Precedence: a project without these methods has identical PRISMA and PRISMA-S output.
2. An agent-reported search cannot be the sole entry of a planned source.
3. Web-search runs state their stopping rule in PRISMA-S.

## File Structure

Create `sources/pubmed.py`, `sources/fulltext/pmc.py`, `document/jats.py`, `document/html_generic.py`, `model/grey.py`, `index/grey.py`, `services/grey.py`, `services/modules/grey.py`, `imports/ris.py`. Modify `sources/registry.py`, `sources/fulltext/registry.py`, `model/fulltext.py`, `model/work.py`, `model/protocol.py`, `services/protocol_rules.py`, `services/prisma.py`, `services/check.py`, `services/evidence_report.py`, `document/registry.py`, `imports/registry.py`, `inbox/links.py`, `services/inbox.py`, `cli/main.py`, `mcp/server.py`.

### Task 1: PubMed source

*Tier: standard. Held by decision 44 (R12).*

**Interfaces:** `PubMedSource(Source)`: `search(query, kind, sink)`, works with PMID, DOI, abstract. `query_issues` for PubMed syntax. Registered in `default_sources`. `probe_run` accepts it.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(sources): PubMed adapter`.

**Tests (later):** recorded pages; reported against retrieved; `network` fact test; dedup with an OpenAlex twin by DOI and PMID.

### Task 2: PMC JATS route and converter

*Tier: standard. Held by decision 44 (R12).*

**Interfaces:** `Route.PMC_JATS`; `PmcRoute`; `JatsConverter(accepts={"application/jats+xml"})`, contract kit, tables to rectangular pipe tables, `ref-list` to bibliography entries.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(fulltext): PMC open-access route and JATS converter`.

**Tests (later):** contract kit; route order; licence recorded; non-OA reported unavailable.

### Task 3: Grey sources section and provenance

*Tier: critical (protocol, PRISMA). Bumps the projection. PD-7 [confirm].*

**Interfaces:** `GreySource(method, target, stopping_rule, included)`; section `grey_sources`; `ProvenanceMethod` additions and `OTHER_METHODS` order; `QueryPurpose.GREY`; PRISMA "other methods" lines; PRISMA-S items. Gaps as for `supplied_links`.

- [ ] **Step 1:** Implement, bump. **Step 2:** Commit `feat(grey): declared grey sources and provenance methods`.

**Tests (later):** review focus 1; hash unchanged while absent.

### Task 4: Structured grey search

*Tier: light.*

**Interfaces:** OpenAlex `type:` filters on a `grey`-purpose query, authorised by the section; `search_run` unchanged in shape.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(grey): OpenAlex grey types as declared searches`.

**Tests (later):** undeclared query needs a deviation; work type recorded.

### Task 5: Capture

*Tier: standard.*

**Interfaces:** `capture_url(project, actor, url, *, source_id) -> CaptureResult` (hash, timestamp, headers to the library and an event; a work from stored fields; later publications linked through `version.linked`). `factory grey capture URL --source NAME --title T`. `HtmlGenericConverter`.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(grey): snapshot capture into the library`.

**Tests (later):** bytes in the library only; repeat capture with changed bytes is a new version, not an overwrite.

### Task 6: Reported searches and expert contact

*Tier: standard. Bumps the projection.*

**Interfaces:** events `grey.search_reported` (`engine`, `query`, `timestamp`, `urls`, `stopping_rule`), `grey.contact_logged`. MCP `grey_search_report`, CLI `factory grey contact`. Review focus 2: a check gap when an included source has only reported runs.

- [ ] **Step 1:** Implement, bump. **Step 2:** Commit `feat(grey): reported web searches and contact log`.

**Tests (later):** URLs become inbox items; not enrolled as works directly; forged events.

### Task 7: Reporting

*Tier: standard.*

**Interfaces:** `report evidence --without-grey`, with both counts stated; a `grey` label on rows and works; AACODS instrument data for plan EQ if EQ has merged.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(grey): label grey evidence; report with and without it`.

**Tests (later):** sensitivity counts derived; golden without grey.

### Task 8: RIS and publisher-page links

*Tier: light.*

**Interfaces:** `imports/ris.py` (`parse_ris`, record fields as BibTeX's; parser name and version recorded); `factory import ris`. `inbox_resolve` reads a publisher page's `citation_doi` meta tag once, the fetched page archived as a recorded lookup (slice 4a Later). If the page refuses, the item stays open.

- [ ] **Step 1:** Implement. **Step 2:** Commit `feat(imports,inbox): RIS exports and publisher-page resolution`.

**Tests (later):** fixtures; no note field stored; page lookup recorded.

## Self-review notes

- Task 8 touches `inbox/links.py`, also touched by PF Task 1. Land PF first.
- Task 5's generic HTML converter is not a candidate of decision 49, whose question covers LaTeX and PDF.

## Later (not v1)

- ClinicalTrials.gov, GitHub, Hugging Face adapters; Internet Archive links; grey items in the literature watch.

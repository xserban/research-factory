# Outline — Grey literature in the review stages

Status: **future outline, not binding** · 2026-11-03 · Backlog IDEA-24. Becomes a slice spec (or part of one) when scheduled; until then it constrains nothing. Earliest sensible point: after slice 2 (needs Markdown conversion and the local library).

## Problem
Slice 1 searches bibliographic databases (OpenAlex, arXiv) plus citation chasing and seed admission. Much relevant evidence is elsewhere, and its absence biases reviews (publication bias, time lag):
- **ML:** technical reports and model cards, code repositories (README results, released checkpoints), benchmark leaderboards, blog posts from labs, workshop papers not indexed, theses, talks/slides.
- **Medicine / computational modelling:** trial registries, regulatory documents (FDA/EMA summaries, device approvals), conference abstracts, guidelines, theses, standards (e.g. ASME V&V 40), industry white papers.

Grey literature differs from database records in four ways that the platform must handle: searches are not exhaustive or reproducible, documents change or disappear, metadata is poor, and quality varies widely.

## Principles
1. **Same pipeline, different provenance.** A grey item becomes a `Work` like any other and goes through dedup, screening, full text and extraction; only its provenance method (`grey-search`, `website`, `registry`, `repository`, `expert-contact`) and its quality labels differ.
2. **Planned in the protocol.** Grey sources, search methods, stopping rules and the screening of grey items are declared before searching (R-13, R-22); unplanned grey searching is a recorded deviation.
3. **Snapshot what was seen.** Every grey document is captured at retrieval (content hash, URL, timestamp, HTTP headers) into the local library, so later changes or deletions do not break the evidence chain.
4. **Flag, don't hide.** Grey evidence is labelled throughout; reports show results with and without it (sensitivity), and never pool it silently with peer-reviewed evidence.

## Search methods (planned per project)
| Method | Examples | Reproducibility | How it is recorded |
| --- | --- | --- | --- |
| Structured grey sources with APIs | ClinicalTrials.gov, GitHub, Hugging Face Hub, OpenAlex `type` filters (reports, dissertations), DataCite | High | Normal search run (PRISMA-S fields, reported vs. retrieved, raw payload) |
| Targeted websites | Lab and company research pages, regulator pages, conference sites | Medium | List of sites declared in the protocol; each visit is a run with captured pages |
| Web search engines | General web search with declared queries | Low | Query, engine, date, **declared stopping rule** (e.g. first N results per query) and every returned URL recorded; the cut-off is reported as a limitation |
| Agent web search | Claude's web search during a session | Low | Recorded as an agent-reported search: query, timestamp, returned URLs; never the only method for a planned source |
| Expert contact | Asking authors or domain experts for unpublished work | Low | Contact log: who, when, what was asked, what was received |

Note on R-21 (no truncation): web search engines cannot return complete result sets. Grey web searching is therefore an explicit, declared exception with a stopping rule fixed before searching, reported under PRISMA-S; it never replaces database searching.

## Rigour additions (candidates for 01-rigour.md)
- **Capture:** grey documents are snapshotted with hash and timestamp; an optional public archive link (e.g. Internet Archive) is recorded where terms allow.
- **Version linking:** a grey item later published (blog → paper, preprint → journal, registry entry → results paper) is linked, not merged away (extends R-26).
- **Appraisal:** grey items require the project's grey-literature instrument when appraisal exists (R-41 already names AACODS: authority, accuracy, coverage, objectivity, date, significance) (IDEA-21).
- **Reporting:** PRISMA 2020 "other methods" boxes per grey method; PRISMA-S items for websites, registries and other sources; a sensitivity view excluding grey evidence in the evidence report.
- **Extraction:** results from repositories or leaderboards are `reported` unless reproduced; leaderboard entries without a describing document are context, not evidence.

## Likely scope when scheduled
- Source adapters: ClinicalTrials.gov (biomedical projects), GitHub and Hugging Face Hub (ML projects), OpenAlex grey types.
- Web capture into the local library (HTML → Markdown via the slice-2 converters).
- Declared web-search runs with stopping rules; agent-reported search events; expert-contact log.
- Protocol fields: grey sources, methods, stopping rules, grey screening plan.
- Reports: grey boxes in PRISMA, PRISMA-S grey items, with/without-grey sensitivity view.

## Open questions
1. Which grey sources first: ML (GitHub, Hugging Face, lab pages) for the pilot, or registries/regulatory sources for the biomedical projects.
2. Whether agent web search counts as a search method at all or only as a discovery aid that must be re-run through a recorded method.
3. Legal and ethical limits of capture (site terms, robots rules, paywalled pages) and what is stored for items that may not be copied.
4. How the literature watch (IDEA-02) monitors grey sources (repositories and registries change often).

## Methodological references (from memory; verify before formal use)
- Godin K, et al. Applying systematic review search methods to the grey literature: a case study examining guidelines for school-based breakfast programs in Canada. *Systematic Reviews* 2015;4:138.
- Tyndall J. AACODS checklist. Flinders University, 2010.
- Paez A. Gray literature: an important resource in systematic reviews. *Journal of Evidence-Based Medicine* 2017;10(3):233–240.
- Garousi V, Felderer M, Mäntylä MV. Guidelines for including grey literature and conducting multivocal literature reviews in software engineering. *Information and Software Technology* 2019;106:101–121.
- Cochrane Handbook, chapter 4 (searching for and selecting studies), sections on grey literature and trial registers.
- PRISMA-S (M2): items on websites, registries and other sources.

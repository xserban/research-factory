# Research Factory — Stage Map

The factory is a chain of **stages**. Each stage has a written contract:

```
INPUT      which artifacts must already exist
ACTOR      agent (judgment) | script (deterministic) | human (decision)
SKILLS     which installed skills it composes
PROCEDURE  the SOP
OUTPUT     exact files written, with schema
GATE       machine-checkable exit condition (`rf gate NN`)
FAILURE    known failure modes and their escape hatches
```

The **gate** is what makes this a factory rather than a conversation. A stage is not
"done" because the agent says so; it is done when `rf gate NN` exits 0. Gates check
structure and completeness, never correctness of judgment — they cannot tell you a
screening decision was right, only that it was recorded with a criterion ID and a
rationale.

| # | Stage | Actor | Turns … into … |
| --- | --- | --- | --- |
| 00 | **Frame** | agent + human | a vague goal → one answerable question + explicit non-goals |
| 01 | **Scope probe** | script + agent | the question → evidence that it is *searchable*, plus harvested vocabulary |
| 02 | **Protocol** | agent + human | vocabulary + question → frozen criteria, sources, queries (`protocol.lock`) |
| 03 | **Search** | script | queries → raw payloads → deduplicated corpus with full provenance |
| 04 | **Screen** | agent | corpus → include/exclude decisions, each with criterion ID + rationale |
| 05 | **Acquire** | script | included works → normalized full-text markdown with stable anchors |
| 06 | **Extract & appraise** | agent | full text → work notes, atomic claims with locators, quality grades |
| 07 | **Wiki** | script + agent | works + claims → navigable views, concept pages, surfaced contradictions |
| 08 | **Synthesize** | agent | wiki → evidence tables, narrative, gap analysis — every sentence cited |
| 09 | **Serve** | agent | a question → a cited answer, or an honest refusal |
| ∞ | **Audit** | script | corpus state → PRISMA flow, integrity report, deviation log |

Stages 00–02 are cheap and high-leverage; 03–06 are where the cost is; 07–09 are what you
actually use. Stage 01 exists because freezing a protocol against an unprobed question is
the most common and most expensive mistake in evidence synthesis.

## Reuse of installed skills

Research Factory skills are **orchestrators**, not replacements. The library in
`.github/skills` already covers a large fraction of the judgment work:

| Stage | Existing skills to compose |
| --- | --- |
| 00 Frame | `clarifying-questions-first`, `brainstorming-research-ideas`, `scientific-brainstorming`, `creative-thinking-for-research` |
| 02 Protocol | `critical-analysis` (adversarial review of criteria before freeze) |
| 03 Search | `literature-search-arxiv` (working arXiv retrieval reference) |
| 05 Acquire | `markitdown` (PDF/DOCX/PPTX/HTML → markdown; the extraction backbone) |
| 06 Appraise | `scientific-critical-thinking` (GRADE, Cochrane Risk of Bias) |
| 07 Wiki | `markdown-mermaid-writing` (document + diagram standard, incl. PRISMA flow) |
| 08 Synthesize | `critical-analysis`, `section-objective-analysis-v2`, `academic-text-compressor` |
| — Authoring | `writing-skills` (use when writing every factory skill) |

Consequence for appraisal: use **GRADE / Cochrane RoB for peer-reviewed work** and
**AACODS for grey literature**, rather than one scheme for both. `scientific-critical-thinking`
already carries the former.

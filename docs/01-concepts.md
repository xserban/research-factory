# Core concepts

## Knowledge graph, not layers

The underlying model is a **graph**. The "onion" is one *view* of it.

- **Nodes:** sources (papers, preprints, datasets, code), methods, problems/tasks, datasets, metrics, claims, hypotheses, experiments, concepts.
- **Edges:** cites; applies method to problem; evaluates on dataset; reports metric value; extends / supports / contradicts; shares a property; analogous to (same problem structure, different field).
- **Claims are nodes**, linking the entities they are about, each with a source span (compatible with nanopublications).

Why a graph:
- Ideas have several centres (e.g. linear attention *and* vision; PINNs *and* TAVI).
- Seeds can be placed anywhere.
- Distance has several dimensions (citation, topic, method, application) — kept as different edge types.
- Projects overlap naturally through shared nodes.
- Fields emerge as clusters instead of being declared.
- Cross-field ideas are paths (Swanson's A–B–C); gaps are missing edges; link prediction generates hypotheses.

## Regions

A **region** is a named subgraph built and seeded on its own, e.g. "CFD methods", "PINN methods", "TAVI clinical". Regions link to each other and to project foci. Regions are shared across projects and have owners (see [06-teams.md](06-teams.md)).

## Project = focus + scope policy

- **Focus:** the research idea's facets as focal nodes, plus optional seeds (papers, a corpus, a reference library). Any region can be seeded.
- **Scope policy:** which edge types to expand along, how far, how deeply to process at each distance, and the usage budget.
- **Views:** onion (distance rings from the focus), evidence / benchmark map (problems × methods), cluster map, timeline.

Every project follows the same process regardless of domain:
1. State the idea. 2. Break it into facets. 3. Seed (none, papers, or a corpus). 4. Build the focus region systematically. 5. Build surrounding regions (agents propose, human approves). 6. Extract (shared fields + project-specific fields). 7. Synthesise (map, gaps, contradictions). 8. Hypothesise and test (literature and/or experiments). 9. Keep current.

What varies between projects: the extraction fields, how hypotheses are tested (literature vs. controlled experiments), and how regions overlap.

## Processing depth (replaces "rigour per layer")

Each node has a processing level, set by the scope policy, not by its position:

`indexed` (metadata) → `screened` → `extracted` (claims / method card) → `verified` (audited by human or critic)

Typical gradient: focus systematic and fully extracted; near regions targeted (surveys, benchmarks, key papers) with method cards; far regions purposive, triggered by gaps.

## Method cards and problem descriptions

- **Method card:** what problem class a method solves, assumptions, data requirements, maturity (e.g. TRL), code availability, evidence of where it worked.
- **Problem description:** the properties of a project task (e.g. irregular sampling, small n, multimodal, latency < 1 min, clinical metrics).
- **Matching** method properties to problem properties through a shared property vocabulary generates cross-field hypotheses, and is the interface between team members.

Rigour scales with distance: the further a combination reaches, the more falsification and plausibility checks it must pass.

## Typing: strict core, loose everything else (gradual typing)

Strict (the factory's guarantees depend on these):
- **Source** — anything citable, with stable identifiers.
- **Claim** — statement + source span.
- **Provenance** on every node and edge.

Loose:
- Nodes carry free **labels**; edges carry free **relation names**; similarity via embeddings.

Order emerges and is tidied up:
1. Emerge — agents label freely.
2. Consolidate — scheduled pass merging synonyms and duplicate entities (e.g. "Performer" / "FAVOR+"), with human review.
3. Promote — frequently used labels get definitions, vocabularies and required fields.
4. Record — merges and promotions are versioned.

Risk: loose typing fragments the graph; scheduled consolidation is mandatory, not optional.

## Shared library and parallel projects

Outer regions (e.g. general ML methods) are reused across projects. Structure: one shared graph; one focus per project; each project pinned to a version of shared regions (monorepo pattern). Domain-specific vocabularies, extraction schemas and gold sets live in pluggable **domain packs**.

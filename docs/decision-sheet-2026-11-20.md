# Decision sheet for the researcher (2026-11-20)

Scope: every entry of `docs/decisions.md` whose status is *Proposed* (75) or *Open* (8, of which 132 is a reserved number), 83 rows in all, and no other. This sheet replaces `docs/decision-sheet-2026-11-16.md` (58 Proposed entries, 7 Open). `docs/decisions.md` is not changed; a ruling is written there only after you answer. The same entries are in `docs/decision-sheet-2026-11-20.json` for the apply step.

How to read it. "Built" cites the module, test or plan that implements the entry; "Relied on by" is a grep of `platform/src`, `platform/tests` and `docs/decisions.md` for `decision(s) N` (the regex is noisy for numbers that also occur as "item N"; known false positives are marked). Code rarely cites a decision number, so for most entries the plan name or the module is the evidence; where neither could be confirmed I write "not verified". Recommendations: DECIDE as written; AMEND (say what); REVERT/WITHDRAW; KEEP OPEN. The reasoning for the 2026-10/11 entries 82 to 115 rests on each entry's status line and first rulings, as in the 2026-11-16 sheet. Nothing here says the code passes its tests; deciding confirms intent.

Changes since the 2026-11-16 sheet. Entries that are now Decided: 127 (technique taxonomies); 141 to 147 (spar night: ask mode, chat requests and runner stages, balance and lead guard, hub write routes, agentic spar, living sheets, contradiction map; accepted 2026-11-20). New Proposed since then: 130, 131, 133 to 140, 148 to 155 (25 entries; with Open 132 added). Of the 57 entries that remain from the old sheet, none changed its recommendation; 113 still carries the stale item 2 ("PubMed and PMC ... not built, held under decision 44"; they were built under Decided 124).

Conflicts with *Decided* entries: none contradicts one. Three amend Decided text: 133 (item 1 of 124, "takes no filters"), 134 (item 3 of 124, route order), and 130 (leaves imports on OpenAlex; consistent with the researcher's 2026-11-16 ruling but unresolved). 139 and 136 depend on Proposed entries (143, Decided, answers 139 item 5; 136 departs from 82 ruling 1). Decided 141 to 147 rest on Proposed 139, so deciding 139 removes a Decided-on-Proposed dependency.

## 1. Status table by theme

Within each section the order is most relied-upon first (code, test and decision citations summed). Column "11-16 sheet" says whether that sheet already recommended the entry (`same`) or the entry is new (`new`).

### Rigour and held-out

| # | Title | Date | Built (evidence) | Relied on by | Conflict with Decided | Rec. | Reason | 11-16 sheet |
|---|---|---|---|---|---|---|---|---|
| 81 | Held-out work reads as any corpus work | 2026-11-05 | platform/src/factory/services/access.py, exports.py, coverage.py, inbox.py (9 src files cite it); 8 test files | code cites it: platform/src/factory/services/access.py, platform/src/factory/services/coverage.py, platform/src/factory/services/decisions.py (+6 more); 8 test file(s) cite it; decisions citing it: 79 | none | DECIDE | Researcher-facing form of 37.9 and 43; hiding is itself an oracle. | same |
| 54 | Held-out recall counts search finds only | 2026-11-04 | platform/src/factory/services/seeds.py, methods.py, prisma_update.py; tests: 3 files cite it | code cites it: platform/src/factory/services/methods.py, platform/src/factory/services/prisma_update.py, platform/src/factory/services/seeds.py; 3 test file(s) cite it; decisions citing it: 61 | none | DECIDE | Only definition that measures the search, not the seeding. | same |
| 78 | document_read text not scrubbed (Open) | 2026-11-05 | platform/src/factory/services/document_read.py keeps the scrub; platform/tests cite 78 (3 files) | 3 test file(s) cite it; decisions citing it: 81 | none | DECIDE | Option A: keep the scrub (status quo, consistent with 37.9); the leak is a [withheld] marker 81 already lists. Closing it makes the open marker go away. | same (A) |
| 80 | Held-out size derivable from PRISMA totals | undated | platform/src/factory/services/prisma.py collapse before a pass opens; 1 test cites it | 1 test file(s) cite it; decisions citing it: 81 | none | DECIDE | A number is revealed, never a record; a misstated count is worse (R-05). | same |
| 88 | Region rulings B: withheld regions refused to agents | 2026-11-05 | platform/src/factory/services/regions.py; 88 also cites 10 (teams) | code cites it: platform/src/factory/services/regions.py | none | DECIDE | Consistent with 81: a region reaching a held-out part is refused as a whole. | same |
| 34 | Rigour requirements binding | undated | docs/specs/01-rigour.md; CLAUDE.md names it binding | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Already binding in practice; confirms the file. | same |
| 35 | Method profiles, PRESS, defence | undated | platform/src/factory/model/protocol.py profiles and services/protocol.py; PRESS: mcp tool protocol_press_review; defence stage not built (not verified in code) | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Profiles and PRESS built; defence stage stays "later". | same |
| 76 | Inbox rulings (slice 4a) | 2026-11-04 | platform/src/factory/services/inbox.py, trace.py; docs/MAP.md inbox rows; no code cites the number (plan name is the evidence) | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Route-blind screeners kept; origin tag is for human and miners only. | same |

### Gates and roles

| # | Title | Date | Built (evidence) | Relied on by | Conflict with Decided | Rec. | Reason | 11-16 sheet |
|---|---|---|---|---|---|---|---|---|
| 138 | Leftover works do not block a round (pending_tolerance) | 2026-11-18 | platform/src/factory/services/tolerance.py, model/protocol.py, services/snowball.py, agreement.py, extraction_audit.py (11 src files cite it); 4 test files | code cites it: platform/src/factory/cli/render.py, platform/src/factory/model/chase.py, platform/src/factory/model/extraction.py (+8 more); 4 test file(s) cite it | none | DECIDE | Researcher ruling; values (3, 0.03) set by later protocol amendment, so the code default is unchanged. Relaxes a block, so state the scope explicitly. | new |
| 93 | Experiment gates (freeze, unlock, baseline) | 2026-11-05 | platform/src/factory/services/experiments.py; 1 test cites it | 1 test file(s) cite it; decisions citing it: 94 | none | DECIDE | Declarations already ruled; floors question stays with the pilot (R6). | same |
| 10 | Teams: ownership and workspaces from day one | undated | Slice 5 modules (106 to 111): services/lab.py, members.py; cited by 88 | decision 88 cites it | none | DECIDE | Built; confirms. | same |
| 102 | Pilot-fix rulings (R8: dedup blocks screen_next) | 2026-11-06 | platform/src/factory/services/screening.py, dedup.py; 1 test cites it | 1 test file(s) cite it | none | DECIDE | Pilot-1 fix; merged and used. | same |
| 106 | Identity and access (teams-A) | 2026-11-05 | platform/src/factory/services/lab.py, credentials.py, members.py; cited by 107 | decisions citing it: 107 | none | DECIDE | Design confirmed; nobody has run a team through it (IDEA-84). | same |
| 107 | Review, visibility, held-out-by-role (teams-B) | 2026-11-06 | platform/src/factory/services/access.py (RoleGate); modules/contract.py; cited by 108 | decisions citing it: 108 | none | DECIDE | Alternative would add false findings to old logs. | same |
| 84 | Gate-policy rulings (M-B) | 2026-11-05 | platform/src/factory/services/gates.py, model/gates.py (gate_policies, 11 src files, 12 test files) | code cites it: platform/src/factory/services/gates.py | none | DECIDE | Gate test pins exactly these rules. | same |
| 96 | Verification, audit, release gates (W-B) | 2026-11-05 | platform/src/factory/services/draft_release.py, draft_verify.py; cited by decision 103 | decisions citing it: 103 | none | DECIDE | Gates `writing.release`, `writing.audit_label` as in the reconciliation table. | same |
| 101 | MCP and CLI surface rulings (R7) | 2026-11-06 | platform/src/factory/mcp/authz.py, mcp/sessions.py; no number cited in code (not verified line by line) | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | R7 adopted on standing approval; session boundaries. | same |
| 104 | External manuscript rulings (W-C) | 2026-11-05 | platform/src/factory/services/manuscripts.py, manuscript_verify.py; no number cited in code | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Declarations already ruled. | same |
| 108 | Human and mixed screening teams (teams-C) | 2026-11-05 | platform/src/factory/services/human_pass.py, passes.py; index pass_sessions; not verified beyond module names | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Design confirmed. | same |
| 109 | Ledger and budget rulings (teams-D) | 2026-11-06 | platform/src/factory/services/ledger.py, budgets.py; model/ledger.py (ledger.confirmed) | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Design confirmed. | same |
| 110 | Remote MCP rulings (deploy-B) | 2026-11-06 | platform/src/factory/mcp/sessions.py, authz.py (ScopedServer), services/serve_http.py | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Design confirmed. | same |
| 111 | Performance record, curation, routing | 2026-11-06 | platform/src/factory/services/performance.py, curation.py (CLI only) | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Respects 43. | same |
| 115 | Lab library and adoption (deploy-C) | 2026-11-06 | platform/src/factory/services/lab_library.py, library_push.py; mcp tools library_adopt, library_adoptable | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Design confirmed. | same |
| 87 | Leads, hypotheses, critic, registration gates | 2026-11-05 | platform/src/factory/services/leads.py, hypothesis_gates.py, hypothesis_review.py; tests/test_leads.py | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Declarations already ruled in the slice-M table. | same |
| 95 | Outline, draft, support, write-time check | 2026-11-05 | platform/src/factory/services/outline.py, drafts.py, supports.py; cited by decision 103 | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Declarations of the writing module; writing is outside pilot 2. | same |
| 97 | Hosting and sequencing (deploy-A) | 2026-11-05 | platform/src/factory/services/hosting.py; index lock; no number cited in code | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Design confirmed. | same |

### Hub and surfaces

| # | Title | Date | Built (evidence) | Relied on by | Conflict with Decided | Rec. | Reason | 11-16 sheet |
|---|---|---|---|---|---|---|---|---|
| 92 | Views (V-B) | 2026-11-05 | platform/src/factory/services/view_coverage.py, horizon.py, calibration.py; 2 test files; cited by 95, 103 | code cites it: platform/src/factory/services/calibration.py, platform/src/factory/services/fulltext_screening.py; 2 test file(s) cite it; decisions citing it: 95, 103 | none | DECIDE | Built, used by the hub. | same |
| 83 | Intuition-layer rulings (3c) | 2026-11-04 | platform/src/factory/services/interpretations.py, concepts.py (1 src cites it); index/intuition.py (layer_nodes); cited by 89 | code cites it: platform/src/factory/services/concepts.py; decisions citing it: 89 | none | DECIDE | Built. | same |
| 90 | View contract (V-A) | 2026-11-05 | platform/src/factory/services/views.py, drafts.py (1 src cites it); cited by 96 | code cites it: platform/src/factory/services/drafts.py; decisions citing it: 96 | none | DECIDE | Hub views and agent briefings use it. | same |
| 82 | Slice 3b lineage rulings | 2026-11-04 | platform/src/factory/services/ideas.py, relations.py, contributions.py, lineage.py; cited by 136 | decisions citing it: 136 | none | DECIDE | Decide before or with 136, which departs from its ruling 1. | same |
| 85 | Region rulings A (3d) | 2026-11-05 | platform/src/factory/services/regions.py, region_adoption.py; cited by 88 | decisions citing it: 88 | none | DECIDE | Built; no run-time effect. | same |
| 112 | Cross-project suggestions (option a) | 2026-11-06 | platform/src/factory/services/suggestions.py (factory suggest) | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Computed on request, as built. | same |
| 13 | Relational property graph, no graph DB | undated | platform/src/factory/lineage/, index graph tables; not cited in code | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Built. | same |
| 136 | Technique landscape as derived interpretation layer | 2026-11-18 | platform/src/factory/services/technique_graph.py, technique_rank.py, hub_landscape.py; tests test_technique_graph*.py, test_hub_landscape.py | none found (grep of platform/src, platform/tests, docs/decisions.md) | departs from Proposed 82 ruling 1 (no Decided conflict) | DECIDE | Sound derived layer; but it departs from Proposed 82 ruling 1 (no automatic clustering) for derived technique groupings, so it is decided with 82. | new |
| 149 | Status names missing full-text plan as blocking | 2026-11-20 | platform/src/factory/cli/render.py, cli/main.py (blocking list); tests: 10 files mention blocking (not verified which) | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Reports a fact; no count changes. | new |
| 150 | Undrawn calibration set is a waiting item | 2026-11-20 | platform/src/factory/services/human_queue.py, digest.py (calibration-labels); 1 test | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Names the next command; no new gate. | new |
| 151 | Exploratory mode says it has no search gate | 2026-11-20 | platform/src/factory/services/protocol.py (notice text); tests: not verified | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Honesty notice only; behaviour unchanged. | new |
| 152 | dedup pairs / dedup pair human gate reachable again | 2026-11-20 | platform/src/factory/cli/main.py:1857 (dedup pairs); platform/tests/test_cli_dedup_pairs.py | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Restores a gate lost in a merge; agent refused. | new |
| 153 | Tutorial is static text plus computed progress | 2026-11-20 | platform/src/factory/learn/, services/learn_progress.py, hub_learn.py; tests test_learn_content.py, test_learn_progress.py | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | No event, no table, judges nothing. | new |
| 154 | Tutorial spine is the nine run-map stage ids | 2026-11-20 | platform/src/factory/learn/stages.py; services/site_catalog.py STAGE_IDS; test_hub_learn.py | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Test keeps the two lists equal. | new |
| 155 | Hub opens on Learn while project is new | 2026-11-20 | platform/src/factory/services/hub_platform.py (STAGE_IDS use), hub_learn.py; test_hub_learn.py (not verified for the opening rule) | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Display default only. | new |
| 89 | Label, consolidation, term rulings (3d) | 2026-11-05 | platform/src/factory/services/labels.py, consolidation.py, terms.py | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Built. | same |
| 98 | Briefing and context pack (V-C) | 2026-11-05 | platform/src/factory/services/briefing.py, briefing_served.py; mcp tool briefing_get | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Built. | same |
| C-1 | Hub timer and the hub feed acts (provisional number) | 2026-11-14 | platform/src/factory/services/site_server.py (FeedTimer); 1 test; plan docs/plans/2026-11-13-hub-feed.md | none found (grep of platform/src, platform/tests, docs/decisions.md) | extends Decided 63 (no contradiction) | DECIDE | Keeps 63 intact (timer is a hub process). Replace the number C-1 by a real number when applying. | same |

### Miners and mining

| # | Title | Date | Built (evidence) | Relied on by | Conflict with Decided | Rec. | Reason | 11-16 sheet |
|---|---|---|---|---|---|---|---|---|
| 120 | Taxonomies as versioned objects | 2026-11-12 | platform/src/factory/services/taxonomies.py, site_taxonomy_registered.py; cited by 127 (Decided) | code cites it: platform/src/factory/services/site_taxonomy_registered.py; decisions citing it: 127 | none | DECIDE | 127 (Decided) already rests on it; confirmation is missing. | same |
| 105 | Shared mining store and import (M-E) | 2026-11-05 | platform/src/factory/services/shared_mining.py; 1 test | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | IDEA-82 builds on it. | same |
| 114 | Per-paper appraisal and admitted miners (EQ) | 2026-11-06 | platform/src/factory/model/appraisal.py, index/appraisal.py, services/appraisal*.py (11 src files mention appraisal_instrument); no test file mentions the term (not verified) | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Built. | same |
| 132 | Reserved number (semantic agreement events) (Open) | undated | Plan docs/plans/2026-11-16-semantic-agreement.md is "nothing built"; grep finds no pair_judged / judgement_audited in platform/ (verified: no hits) | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | KEEP OPEN | Number is reserved for a plan not yet built; cannot be decided before the plan is validated. | new |
| 137 | Reopen one mined work after a selector miss | 2026-11-18 | platform/src/factory/services/mine_reopen.py, mining/select.py (SELECTION_FALLBACK_BELOW), index/mine_reopen.py; tests/test_mine_reopen.py | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Guarded researcher act; rows stay in the log. | new |
| 86 | Miner-specification rulings (M-C) | 2026-11-05 | platform/src/factory/mining/, services/miners.py; no number cited in code | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Built. | same |
| 91 | Miner-calibration rulings (M-D) | 2026-11-05 | platform/src/factory/services/miner_gold.py, calibration.py; no number cited in code | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Rule the IDEA-69 guard enforces. | same |

### Search and sources

| # | Title | Date | Built (evidence) | Relied on by | Conflict with Decided | Rec. | Reason | 11-16 sheet |
|---|---|---|---|---|---|---|---|---|
| 9 | Embeddings (Open) | undated | Answered by 116 and 140: platform/src/factory/services/suggestions.py and passage_vectors.py cite it; the entry says it stays open | platform/src/factory/services/suggestions.py (comment "decision 9 stays open"); decisions 116, 140 build on it; other grep hits are "decision 37 item 9" (false positives) | none | DECIDE | Close as decided by 116 (and 140), once those are decided. | same |
| 116 | Local embedding ranker (SPECTER2) | 2026-11-07 | platform/src/factory/model/ranking.py, services/ranking_model.py, cli/main.py, mcp/server.py (8 src files cite it); cited by 135, 140 | code cites it: platform/src/factory/cli/main.py, platform/src/factory/mcp/server.py, platform/src/factory/model/protocol.py (+5 more); 1 test file(s) cite it; decisions citing it: 135, 140 | none | DECIDE | Two Proposed entries and the Open 9 rest on it. Platform still calls no remote model. | same |
| 135 | Selected backward snowball rounds, offline | 2026-11-18 | platform/src/factory/services/snowball.py, model/protocol.py, model/references.py; tests test_snowball_backward_select.py, test_snowball_backward_options.py | code cites it: platform/src/factory/cli/render.py, platform/src/factory/model/protocol.py, platform/src/factory/model/references.py (+3 more); 3 test file(s) cite it | amends slice 3a ruling 7 (Proposed 77) | DECIDE | Opt-in; protocol hashes unchanged; relies on 116 and amends Proposed 77 ruling 7. | new |
| 117 | Version pairs and identifier-less works | 2026-11-11 | platform/src/factory/services/version_pairs.py, dedup_cascade.py, prisma.py; plan docs/plans/2026-11-11-version-pairs.md | code cites it: platform/src/factory/services/dedup_cascade.py, platform/src/factory/services/modules/dedup.py, platform/src/factory/services/prisma.py (+1 more); 1 test file(s) cite it | none | DECIDE | Built; 152 restores its human gate. | same |
| 128 | Full replays only on request | 2026-11-15 | platform/src/factory/model/watch.py, living/window.py; 2 test files | code cites it: platform/src/factory/model/watch.py; 2 test file(s) cite it | none | DECIDE | Researcher ruling; amend the slice 4b spec text in the same change. | same |
| 113 | Grey literature rulings (SG) | 2026-11-06 | platform/src/factory/model/grey.py, services/grey.py (grey_sources, 11 src files) | code cites it: platform/src/factory/model/grey.py, platform/src/factory/services/grey.py | none | AMEND | Strike item 2 (still says PubMed and PMC "not built, held under 44"; Decided 124 built them); confirm agent-web-search as the explicit R-21 exception. | same |
| 140 | Meaning-based passage search (SPECTER2 vectors) | 2026-11-19 | platform/src/factory/services/passage_vectors.py, corpus_search.py, mcp/server.py; 2 test files | code cites it: platform/src/factory/mcp/server.py, platform/src/factory/services/passage_vectors.py | none | DECIDE | Researcher ruling; local computation as in 116. Answers the Open 9 for passages too. | new |
| 99 | PDF intake rulings (PI) | 2026-11-06 | platform/src/factory/services/import_describe.py; index/imports.py (import_descriptions) | code cites it: platform/src/factory/services/import_describe.py | none | DECIDE | Adopted under standing approval. | same |
| 100 | Full-text lifecycle rulings (FL) | 2026-11-06 | platform/src/factory/events/catalog.py, index/fulltext.py (fulltext.source_resolved); 1 test | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Same. | same |
| 126 | Anchored list items; re-anchoring | 2026-11-15 | platform/src/factory/document/anchorise.py (ANCHOR_VERSION), services/reanchor.py; number not cited in code | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Merged and reviewed per 2026-11-16 sheet; measured gain. | same |
| 130 | Reference lookup through Crossref, not OpenAlex | 2026-11-16 | platform/src/factory/references/ (Crossref adapter; crossref in 13 src files), sources; tests: 27 files mention crossref; plan docs/plans/2026-11-16-reference-lookup-crossref.md | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Researcher ruling. Item 1 leaves import resolution on OpenAlex "until ruled otherwise"; ask whether that stays. | new |
| 131 | Reference parser v2/v3, narrower Crossref query | 2026-11-17 | platform/src/factory/references/parse.py (refparse); 5 test files; plan docs/plans/2026-11-17-refparse-initials-crossref-query.md | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Measured on pilot sample (323 of 500 flagged titles recovered). | new |
| 133 | PubMed date slicing, window filter, PMID admission | 2026-11-15 | platform/src/factory/services/pubmed_slices.py, cli/main.py, mcp/server.py; tests test_pubmed_slices.py, test_pubmed_window.py | none found (grep of platform/src, platform/tests, docs/decisions.md) | amends Decided 124 item 1 (and extends item 2) | DECIDE | Agent rulings; amends items 1 of Decided 124 ("takes no filters"). Decide with 134. | new |
| 134 | Europe PMC JATS route; MeSH suggestions | 2026-11-15 | platform/src/factory/model/fulltext.py (europepmc-jats), services/mesh_suggestions.py; tests/test_fulltext_routes_europepmc.py | none found (grep of platform/src, platform/tests, docs/decisions.md) | amends Decided 124 item 3 (route order) | DECIDE | Agent rulings; amends route order of Decided 124 item 3. | new |
| 28 | Scope probe stage | undated | platform/src/factory/services/probe.py; mcp tool probe_run | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Built. | same |
| 77 | References and snowballing (G1) | 2026-11-04 | platform/src/factory/services/references.py, snowball.py; mcp references_*, snowball_* | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Implemented, reviewed. | same |
| 79 | G1 final-review rulings | 2026-11-05 | platform/src/factory/services/snowball.py; item 2 withdrawn by 81 | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Item 2 stays recorded as withdrawn. | same |

### Hypothesis engine and spar

| # | Title | Date | Built (evidence) | Relied on by | Conflict with Decided | Rec. | Reason | 11-16 sheet |
|---|---|---|---|---|---|---|---|---|
| 94 | Evaluation, multiverse, benchmark ledger, directions (XP-B) | 2026-11-05 | platform/src/factory/services/evaluation.py, multiverse.py, benchmark_ledger.py, directions.py (8 src files cite it); cited by 103 | code cites it: platform/src/factory/mcp/server.py, platform/src/factory/services/agent_view.py, platform/src/factory/services/benchmark_ledger.py (+5 more); decisions citing it: 103 | none | DECIDE | Built; hooks. | same |
| 139 | Argument sheets of the papers chat | 2026-11-18 | platform/src/factory/services/sheets.py, chat_candidates.py, hub_chat.py; tests test_chat_requests.py, test_sheet_diff.py | decisions citing it: 143 | none | AMEND | Decided 141 to 147 (2026-11-20) are built on it; item 5 (sheet feeding a lead needs a ruling) is answered by Decided 143 (lead guard); strike or point item 5 at 143. | new |
| 148 | Lead triggers may cite miner rows as item | 2026-11-19 | platform/src/factory/services/finders.py, leads.py, hypothesis_review.py; tests test_lead_engine_integration.py, test_mcp_lead_engine.py | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Keeps the critic blind to lead text (R-51). | new |

### CI and process

| # | Title | Date | Built (evidence) | Relied on by | Conflict with Decided | Rec. | Reason | 11-16 sheet |
|---|---|---|---|---|---|---|---|---|
| 14 | Manual pilot before building | undated | Not followed: slice 1 was built first (decision 33; CLAUDE.md status) | none: grep hits for "14" are "37.14" or other numbers (false positives) | none | REVERT/WITHDRAW | The log states a rule the project did not follow; mark Superseded by 33 and the pilot direction.  | same |
| 11 | Monorepo layout | undated | repository layout: platform/, plugin/, docs/, experiments/ (verified by ls; domain-packs not verified) | decisions 95, 103 cite it | none | DECIDE | Built. | same |
| 12 | Shared Claude Code plugin | undated | plugin/ directory | decisions citing it: 94 | none | DECIDE | Built. | same |
| 15 | Pilot idea (Open) | undated | Pilot 2 is biomedical (docs/plans/2026-11-14-pilot-2.md) | 1 test file(s) cite it | none | DECIDE | Record the pilot 2 domain as the answer and close. | same |
| 16 | Thesis case study (Open) | undated | none | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | KEEP OPEN | A product choice, not a build item. | same |
| 19 | Workflow (Open) | undated | none | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | KEEP OPEN | Outside this build. | same |
| 20 | Team plan (Open) | undated | none | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | KEEP OPEN | Outside this build. | same |
| 21 | Experiment tracker (Open) | undated | none | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | KEEP OPEN | Outside this build. | same |
| 27 | Reuse of research-factory-old | undated | CLAUDE.md "Reuse" section | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Built. | same |
| 30 | Development methodology (superpowers, TDD) | undated | CLAUDE.md "Development process" | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Standing process. | same |
| 31 | Skill sourcing | undated | plugin/ (provenance manifest not verified) | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Built. | same |
| 33 | First slice | undated | docs/specs/slice-1.md; slice 1 implemented (CLAUDE.md status) | none found (grep of platform/src, platform/tests, docs/decisions.md) | none | DECIDE | Slice decided; the pilot idea is history. | same |

## 2. Summary of recommendations

Counts: DECIDE as written 75 (65 plain, 2 more in the confirmation list below, 8 inside batches because a conflict or option exists: 130, 133, 134, 136, 138, 9, 15, 78); AMEND 2 (113, 139); REVERT/WITHDRAW 1 (14); KEEP OPEN 5 (16, 19, 20, 21, 132). Total 83. Not verified in at least one cell: 9, 11, 31, 35, 101, 108, 114, 149, 151, 155 (see the JSON).

## 3. Batches

Three batches, 12 questions in all, each question with the recommendation first. Option text is written so it can be pasted into a questionnaire.

### Batch 1: stale text and open markers (4 questions)

**Q1 (entry 78, document text and held-out markers).** Should `document_read` return document text with held-out identifiers unscrubbed?
- A (recommended). Keep the scrub. No code change; the `[withheld]` placeholder inside a bibliography entry stays an accepted marker (81). Entry 78 is closed.
- B. Narrow 37.9 so document text is unscrubbed. Needs a new Decided entry amending 37.9 and a code change in `services/document_read.py`.
- C. Keep 78 Open until pilot 2 shows whether agents reading bibliographies are misled.

**Q2 (entry 113, grey literature).** Amend entry 113?
- A (recommended). Strike item 2 (PubMed and PMC are decided and built, 124); keep `agent-web-search` as an explicit exception to R-21; decide the rest as written.
- B. Strike item 2 only; leave `agent-web-search` for a later ruling.
- C. Decide as written (leaves a statement the log contradicts).

**Q3 (entry 139, argument sheets).** Item 5 says a sheet citing a lead needs a ruling; Decided 143 adds a lead guard. Amend?
- A (recommended). Decide 139, replacing item 5 by a pointer to 143.
- B. Decide as written and leave item 5 as an open sub-question.
- C. Hold 139 until the lead guard has been reviewed (141 to 147 stay Decided on a Proposed base).

**Q4 (entry 14, manual pilot first).** The project built slice 1 before a manual pilot.
- A (recommended). Mark 14 Superseded by 33 and the pilot direction.
- B. Decide as written and note it as a rule the project did not follow.
- C. Keep Proposed.

### Batch 2: search amendments and scope (4 questions)

**Q5 (entries 133 and 134, PubMed and Europe PMC).** Both amend Decided 124 (133 item 1: PubMed takes a `listed_since` filter; 134 item 3: `europepmc-jats` is tried after `pmc-jats` and before `oa-pdf`).
- A (recommended). Decide both as written; record in 124 a pointer to the amendments.
- B. Decide 133 and 134 and edit 124 items 1 and 3 in place to match.
- C. Decide neither; revert the amended behaviour to 124 as decided. The built code in `services/pubmed_slices.py` and `model/fulltext.py` would change.

**Q6 (entry 130, reference lookup).** References use Crossref by default; item 1 keeps imports on OpenAlex "until ruled otherwise".
- A (recommended). Decide as written; leave import resolution on OpenAlex until the quota problem recurs.
- B. Decide, and also direct import resolution to Crossref (a new plan; the 2026-11-16 ruling "do not rely on OpenAlex" applies).
- C. Decide references only and mark the import clause as open.

**Q7 (entry 136 with 82, technique landscape).** 136 departs from 82 ruling 1 (no automatic clustering) for derived technique groupings.
- A (recommended). Decide 82 and 136 together; the departure is limited to categories of registered taxonomies applied by registered miners.
- B. Decide 82; amend its ruling 1 to name the exception, then decide 136.
- C. Decide 82; keep 136 Proposed until the miners are calibrated.

**Q8 (entry 138, tolerance of leftover works).** Mechanism ruled by you; values come later by protocol amendment.
- A (recommended). Decide as written (code default unchanged; each protocol sets 3 and 0.03 by amendment).
- B. Decide, and also set 3 and 0.03 as the template values in new protocols.
- C. Decide for snowball and chase only; keep the agreement and audit applications (round 2) Proposed.

### Batch 3: open markers (4 questions)

**Q9 (entry 9, embeddings).**
- A (recommended). Close as decided by 116 (ranker) and 140 (passage vectors), after both are decided.
- B. Keep Open until the ranker has been evaluated on pilot data.

**Q10 (entry 15, pilot idea).**
- A (recommended). Record pilot 2 (biomedical) as the answer and close.
- B. Keep Open.

**Q11 (entries 16, 19, 20, 21).** Product and process choices outside this build.
- A (recommended). Keep all four Open.
- B. Close 19 (workflow) as "supervised sessions, B plus C review" as practised; keep 16, 20 and 21 Open.
- C. Withdraw all four from the log.

**Q12 (entry 132, reserved number).** The semantic-agreement plan cites it; the plan is unbuilt (`docs/plans/2026-11-16-semantic-agreement.md`).
- A (recommended). Keep the number reserved and Open until that plan is validated.
- B. Write the row now from the plan's events and mark it Proposed.
- C. Withdraw the number and renumber the plan's citations.

### Confirmation list (one answer)

Recommended DECIDE as written, no conflict with a Decided entry, no real choice; one "approve" answer covers all 67:

10, 11, 12, 13, 27, 28, 30, 31, 33, 34, 35, 54, 76, 77, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 104, 105, 106, 107, 108, 109, 110, 111, 112, 114, 115, 116, 117, 120, 126, 128, 131, 135, 137, 140, 148, 149, 150, 151, 152, 153, 154, 155, C-1

Notes for the apply step: 82 and 136 are decided together (Q7); 116 before 9 (Q9); C-1 receives a real number when applied (the next free number after 155, 156 unless another entry is added first); 128 requires the slice 4b spec text to be amended in the same change; 79 item 2 stays recorded as withdrawn by 81; 14 only if Q4 is answered A.

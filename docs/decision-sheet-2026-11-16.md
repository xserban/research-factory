# Decision sheet for the researcher (2026-11-16)

Scope: every entry of `docs/decisions.md` whose status is still *Proposed*: 58 entries. Seven entries are *Open* (9, 15, 16, 19, 20, 21, 78); they are treated in section 7 and are not part of the 58. `docs/decisions.md` is not changed by this sheet; a ruling is written there only after you answer.

How to read it. "Built on it" is taken from the entry's own plan or slice name, from `docs/MAP.md`, from `grep` of `platform/src` and `platform/tests` for the number, and from `docs/backlog.md`. Code rarely cites a decision number, so for most entries the plan name is the evidence. "If it stays Proposed" says what waits or stays unclear; for almost every entry nothing breaks at run time, because the code is already on main. The cost is that the log says "recommended, not confirmed" about behaviour that is already in use. The recommendations for the long build-time entries (82 to 115) rest on each entry's status line and its opening rulings, not on a line-by-line reading of every ruling; a ruling that looks wrong to you in the entry itself overrides my one-line reasoning.

Test state: all entries marked "landed with testing paused" were built without a test run. Deciding them confirms the intent, not that the code passes; the first test run after the pause is what checks that (memory: untested work during the pause).

Conflicts with *Decided* entries: none found that forces a rejection. Four points to know:
- 81 restores 37.9 and withdraws hiding built earlier (including item 2 of 79, already marked withdrawn there). It does not contradict 37.9. It leaves 78 as the one open marker.
- 78 (Open) would contradict 37.9 as written if `document_read` were unscrubbed; see section 7.
- 113 item 2 says PubMed and PMC are "not built, held under decision 44". Decided entry 124 (2026-11-15) built them. The sentence is stale; amend it (section 5).
- 128 relaxes a rule of the slice 4b spec (a window source declares `full_replay_every`, and its first cycle is a full replay). No *Decided* entry states that rule (63 only says there is no scheduler), so there is no conflict with the log; the spec text should be amended with it.

## 1. Pilot 2 blockers (decide these first)

The pilot 2 plan (`docs/plans/2026-11-14-pilot-2.md`) names no decision as a blocker. Its blockers are the clean-up (section 6), the gate tests (layer 1) and the required forms (section 4); IDEA-79 (merge `pmid-seeds` and `gate-tests` after the tests pass; confirm 124, now Decided) and IDEA-81 (build the capture hints before pilot 2) add two more. The list below is my reading of which Proposed decisions those items stand on. Order: most blocking first.

| # | Title | Decides | Built on it | If it stays Proposed | Recommendation |
|---|---|---|---|---|---|
| 81 | Held-out seed's work reads as any corpus work in every agent view once screening has started | Restores 37.9: no agent output distinguishes a held-out seed's work once a pass is open; withdraws the masks built 2026-11-04/05; lists the markers that remain (`[withheld]` identifiers, `document_read` text) | `held_out_visible` and the refusals in `export_bibliography` and `inbox_list` (6 hits in `platform/src`, 4 in tests); `pmid-seeds` (IDEA-79) withholds `pmid:<n>` under this rule and its merge condition is review of the withholding tests | The `pmid-seeds` withholding tests have no confirmed rule to be checked against; pilot step 5 (split) and step 11 (screening) rest on it | **Decide as written.** It is the researcher-facing form of 37.9 and 43, and its reason (hiding is itself an oracle) is sound. |
| 80 | Held-out size of a split import is derivable from PRISMA totals | Accepts that totals reveal the size of the held-out part, never which record | `report_prisma` collapse before a pass opens (1 test hit) | A known leak is documented only as a reviewer note | **Decide as written.** A report that misstates counts is worse (R-05); the channel reveals a number, not a record. |
| 54 | Held-out recall counts search finds only | `found_by_search` excludes seed admission, so recall measures the search; R-24 gate unchanged | 6 hits in `platform/src`, 2 in tests; seed recall in `check` and the report | Held-out recall in pilot 2 has no confirmed definition | **Decide as written.** It is the only definition that measures the search and not the seeding. |
| 84 | Gate-policy rulings (slice M, plan M-B) | `gate_policies` hash, policy as of the act's protocol version, refusal texts | `gates.gate_issues`; the registry the `gate-tests` branch walks (41 gates) | `gate-tests` asserts a floor table whose basis is unconfirmed | **Decide as written.** The gate test pins exactly these rules; pilot 2 tests them. |
| 107 | Review, visibility, held-out-by-role (teams-B) | `required_role` default `maintainer`; `RoleGate`s declared outside `gates()`; `TEAM_GATES` computed from both | `TEAM_GATES`, which the registry-driven gate test uses | The test's gate universe has no confirmed definition | **Decide as written.** The alternative (slice-M gates) would add false findings to old logs, as the entry says. |
| 87, 93, 96, 104 | Gate declarations: leads and hypotheses (87), experiments (93), writing (96), manuscripts (104) | Which gates exist, their floors and presets (`hypotheses.lead_decide`, `experiments.freeze_unlock`, `writing.release`, `manuscript.*`, and others) | Each is a row of the 41 gates in `gate-tests`; the slice-M amendment of six missing gates (your ruling) | Same as 84; the floors in the table literal have no confirmed source | **Decide as written** (all four). They are declarations already ruled in the slice-M table; the open question about lowering floors stays with the pilot (R6). |
| 99 | PDF intake rulings (plan PI) | A human may describe an import record (`import.record_described`); R2 to R5 already adopted under your standing approval | `import_descriptions` table; PDF intake in pilot steps 13 to 14 | Step 13 uses behaviour you adopted but the log marks unconfirmed | **Decide as written.** |
| 100 | Full-text lifecycle rulings (plan FL) | Changed source resolved by a human mark `fulltext.source_resolved`; per-document restore outcomes | `fulltext` services; step 13 | As 99 | **Decide as written.** |
| 117 | Version pairs and identifier-less works (IDEA-56) | `fulltext import` maps records to canonical works; version pairs in dedup | 6 hits in `platform/src`, MAP, backlog | As 99; importer behaviour on a new domain's files | **Decide as written.** |
| 126 | Anchored list items; bibliography entries from lists; re-anchoring by version | Anchoring version 2: list items become anchored paragraphs; reference extraction reads numbered lists | Merged 2026-11-15 after an Opus review and tests; every PDF-derived document in step 13 | Documents converted before and after the change differ without a ruling saying so | **Decide as written.** Merged, reviewed, tested; the problem it fixes (1.9 against 16.4 citation edges) is measured. |
| 76 | Inbox rulings (slice 4a) | `supplied` is not a seed-miss route; the agent `trace` hides inbox nodes and labels supplied records `supplementary` | `explain_seed_miss`, `trace`; IDEA-81 builds an origin tag and hints on the inbox | IDEA-81 extends route-blindness (screeners never see origin) on an unconfirmed base | **Decide as written.** IDEA-81 keeps the same blinding for screeners; the origin tag it adds is for the human and for miners only. |
| 120 | Taxonomies as versioned objects; layer as dimension zero | Registered `t-` taxonomies recorded only by the researcher; categories with cues; on-demand mining | 2 hits in `platform/src`, MAP, backlog; IDEA-81 (hints use a layer or category from `t-agentic-layer`) | IDEA-81 and 127 sit on it | **Decide as written.** You already ruled Q1 A2 and accepted the rest; only the confirmation is missing. |
| C-1 | Hub timer and the hub's feed acts | A timer thread inside the hub server runs the feed when due; Fetch now and Refetch are hub acts behind loopback and token; reactions and Accept recorded as the human | `FeedTimer`, `/api/feed/run`, `/feed/`, `/p/<slug>/settings/` (backlog, plan hub-feed parts 4 to 6); the portal forms of pilot plan section 4 | Forms and hub acts run without a ruling on who the actor is; pilot plan section 4 says each new allow-listed act needs a decision entry | **Decide as written.** It keeps 63 intact (services never schedule; the timer is a hub process) and the refetch writes no human decision, so the system actor is correct. The number `C-1` should be replaced by a real number at the same time. |

## 2. Held-out, references and inbox (not blocking, but connected to section 1)

| # | Title | Decides | Built on it | If it stays Proposed | Recommendation |
|---|---|---|---|---|---|
| 77 | References and snowballing (G1) | Rulings 1 to 20 of `slice-3a-references.md`; entries anchored `b<n>`; agents propose links, never confirm | `rf-references`, `references_*`, `snowball_*`; backlog (G1 implemented) | Pilot step 17 (optional) | **Decide as written.** Implemented and reviewed. |
| 79 | G1 final-review rulings | Ruling 18 as read; item 2 withdrawn by 81; extraction refusals | `references_extract`, rounds | Item 2 is already void; the rest unconfirmed | **Decide as written.** Item 2 stays recorded as withdrawn by 81. |
| 82 | Slice 3b lineage rulings | Ideas are human-confirmed groupings; contribution pack; no automatic clustering; edges confirmed in the CLI | 2 backlog mentions; graph and contribution services | Entry says it stays Proposed until built and accepted; both are true | **Decide as written.** |
| 83 | Intuition-layer rulings (3c) | Layer tables separate from the graph; interpretations; confirmed ideas served by default | `layer_nodes`, `layer_edges`; 1 hit in `platform/src` | As 82 | **Decide as written.** |
| 85, 88, 89 | Region rulings A, B, C (slice 3d) | Region canonical rules, withheld regions refused to agents, label and term rulings | `region_*`, `label_*`, `consolidation_*`; 88 has 1 hit in source | Region work is not in pilot 2; no run-time effect | **Decide as written.** 88 matters for held-out: a region reaching a held-out part is refused to an agent as a whole, consistent with 81. |
| 112 | Cross-project and living-corpus rulings | Cross-project suggestions computed on request, never stored (option a) | `factory suggest` | None | **Decide as written** (option a, as built). |

## 3. Mining, views, writing and experiments (slices M, 6, 7b)

None of these is in pilot 2 scope (D3 recommends steps 0 to 15). Leaving them Proposed costs only log clarity.

| # | Title | Decides | Built on it | If it stays Proposed | Recommendation |
|---|---|---|---|---|---|
| 86 | Miner-specification rulings (M-C) | Round trip of built-in miners; kind checks in `mining/kinds.py` | Miner registry | Pilot step 16 only | **Decide as written.** |
| 91 | Miner-calibration rulings (M-D) | A calibration unit is never a production unit | Calibration draw; IDEA-69 guard | Pilot step 16 canary | **Decide as written.** It is the rule the IDEA-69 guard enforces. |
| 105 | Shared mining store and import (M-E) | Conversion equality by hash; no `origin` column | `shared_mining.py`; IDEA-82 builds on it | IDEA-82 (merged works in imports) | **Decide as written.** |
| 114 | Per-paper appraisal and admitted miners in the report (EQ) | Optional `appraisal_instrument` protocol section; item types; at most one `check` warning, in `systematic` only | `packs/ml_evidence_appraisal.py` (AACODS added with it) | Appraisal sections of the evidence report | **Decide as written.** |
| 127 | Technique layer as per-stage taxonomies; derived miners with attribute fields (IDEA-83) | One taxonomy `t-tech-<stage>` per stage; attribute fields on derived miners | 1 hit in source, 2 in tests, MAP; merged 2026-11-15 | The one entry whose rulings were taken by an agent, "for review" in plan C7 | **Decide as written, after a skim of plan C7.** Registration stays your act (120), so the rulings do not bypass a gate. |
| 90, 92, 98 | View contract (V-A), views (V-B), briefing and context pack (V-C) | `Index.head()` syncs; agent variant of processing depth leaves label-derived facts out (37.14); briefing builder | `view_*`, `briefing_get`; 90 has 1 hit in source | Hub views and agent briefings | **Decide as written.** |
| 94 | Evaluation, multiverse, benchmark ledger, failed-directions registry (XP-B) | Hook lists for evaluation and priors | 8 hits in `platform/src`; MAP | Experiments are outside pilot 2 | **Decide as written.** |
| 87 (see 1), 93 (see 1) | Leads, hypotheses; experiment design | — | — | — | covered in section 1 (gates) |
| 95, 96 (see 1) | Outline and draft (W-A); verification, release (W-B) | Draft tables, outline hash, release gate | `writing_*`, `draft_*` | Writing is outside pilot 2 | **Decide as written** (95); 96 in section 1. |

## 4. Teams, deployment, access (slice 5)

Pilot 2 has one human and does not exercise these (IDEA-84 records that nobody has run a team through the code). Deciding them is deciding the design, not the test.

| # | Title | Decides | Built on it | If it stays Proposed | Recommendation |
|---|---|---|---|---|---|
| 97 | Hosting and sequencing (deploy-A) | `Index.exclusive()` syncs and floors the ID generator on a hosted project only | Hosted projects; the lock | Hosting is unused by pilot 2 | **Decide as written.** |
| 106 | Identity and access (teams-A) | Lab index with users, identities, roles; registry change only by an active admin | Lab registry, `LAB_PROJECTION_VERSION` | IDEA-84 review | **Decide as written.** |
| 108 | Human and mixed screening teams (teams-C) | `pass_sessions` gains `actor_kind`, `user`; a person's acts run in the session of their join | `PROJECTION_VERSION` "60" | IDEA-84 | **Decide as written.** |
| 109 | Ledger and budget rulings (teams-D) | Ledger rows are one aggregate; `ledger.confirmed` outside the hash | Ledger and budget services | IDEA-84 | **Decide as written.** |
| 110 | Remote MCP rulings (deploy-B) | Stateful HTTP app; every tool behind `authorised` | `ScopedServer`, `TOOL_PERMISSIONS` | IDEA-84 | **Decide as written.** |
| 111 | Performance record, curation and routing (supervision) | Records keyed by role, model, skill version; label-derived rates off agent surfaces | `factory performance` (CLI only) | IDEA-84 | **Decide as written.** It respects 43. |
| 115 | Lab library and adoption (deploy-C) | Referenced-only reads; adoption explicit, route not tried by fetch | `library_adopt`, `library_adoptable` | IDEA-84 | **Decide as written.** |
| 101 | MCP and CLI surface rulings (MS) | R7 adopted: list tools and `protocol_view` refused to a pass session; verifier session limits | MCP tool guards | Session boundaries in step 11 | **Decide as written.** |
| 102 | Pilot-fix rulings (PF) | R8: `screen_next` blocked while a `dedup_run` would change merges; `dedup_current` reads the cascade | Screening and dedup; step 9 to 11 | A pilot-1 fix is unconfirmed | **Decide as written.** |

## 5. Search sources and reporting

| # | Title | Decides | Built on it | If it stays Proposed | Recommendation |
|---|---|---|---|---|---|
| 113 | Grey literature rulings (SG) | Grey sources run through the same pipeline; protocol section `grey_sources`; methods structured, website, agent-web-search, expert-contact | 2 hits in source, MAP | Item 2 is stale: it says PubMed and PMC are not built, held under decision 44 | **Amend**: strike item 2 (PubMed and PMC are decided and built, 124); confirm that `agent-web-search` as an explicit exception to R-21 is what you want; decide the rest as written. |
| 116 | Local embedding model ranks records for screening (IDEA-42) | A local model (SPECTER2) ranks, never judges; weights supplied offline; optional extra `ranker` | 7 hits in source, MAP (4), backlog (3) | Ranking is built but unconfirmed; it also answers decision 9 | **Decide as written.** You chose embeddings and SPECTER2; the entry keeps the rule that the platform never calls a model. |
| 128 | Full replays only on request; first window from the last search | No automatic full replay; `full_replay_every` may be None; first window anchored on the baseline; `watch run --full-replay` human only | Branch `updates-page`, untested; `watch_status` fields | The updates page and the watch run rest on an unconfirmed relaxation of the slice 4b spec | **Decide as written.** It is your own ruling; amend the slice 4b text in the same change. |

## 6. Foundational entries from 2026-10 (built long ago)

All are implemented and were never confirmed in the log. The reasoning is the same: confirming costs nothing and ends the ambiguity.

| # | Title | Decides | Built on it | If it stays Proposed | Recommendation |
|---|---|---|---|---|---|
| 10 | Teams | Ownership and per-person workspaces from day one | Slice 5 (106 to 111) | None | **Decide as written.** |
| 11 | Repository | Monorepo: platform, plugin, domain-packs, projects | The repository layout | None | **Decide as written.** |
| 12 | Agent packaging | A shared Claude Code plugin | `plugin/` and `FACTORY_PLUGIN_DIR` | None | **Decide as written.** |
| 13 | Graph DB | Relational property graph first; no graph database | Slice 3b graph tables | None | **Decide as written.** |
| 14 | First step | Manual pilot before building | Not followed: slice 1 was built first (33); the pilot direction is "build, then pilot" | The log states a rule the project did not follow | **Reject (mark Superseded by 33 and the pilot direction).** |
| 27 | Reuse of research-factory-old | Port the literature core with tests; drop the file store and old `cli.py` | `CLAUDE.md` "Reuse" | None | **Decide as written.** |
| 28 | Scope probe | A probe stage with positive and negative seeds before the protocol | `probe_run`, slice 1 | None | **Decide as written.** |
| 30 | Development methodology | obra/superpowers, TDD for `platform/`, plans in `docs/plans/` | `CLAUDE.md` | None | **Decide as written.** |
| 31 | Skill sourcing | Three plugin groups; provenance manifest | `plugin/` | None | **Decide as written.** |
| 33 | First slice | Slice 1 tracer bullet; pilot idea "linear attention for vision" | Slice 1 built | The pilot idea has since changed (pilot 1, pilot 2) | **Decide as written** for the slice; the pilot idea is history. |
| 34 | Rigour requirements | `01-rigour.md` binding on every slice | `CLAUDE.md` names it binding | None | **Decide as written.** |
| 35 | Method profiles and defence | Protocol profiles; PRESS review in slice 1; defence stage later | Profiles and PRESS built; defence stage not | Defence stage is a promise, not a build | **Decide as written** for profiles and PRESS; the defence stage stays "later". |

## 7. Open entries (not Proposed; for completeness)

- **78** (Open): should `document_read` return text unscrubbed? Option A, keep the scrub (status quo, consistent with 37.9). Option B, narrow 37.9 so document text is unscrubbed. Recommendation: **A, keep the scrub**. Option B means a new Decided entry that amends 37.9; the leak under A is a `[withheld]` placeholder that marks a bibliography entry, which 81 already lists as an accepted marker. Revisit if pilot 2 shows agents reading bibliographies are misled.
- **9** (Embeddings): answered by 116 (local ranker, SPECTER2). Recommendation: close as decided by 116 once 116 is decided.
- **15, 16** (pilot idea; thesis case study): product choices, not review items. Pilot 2 is a different domain (biomedical) by your 2026-11-13 ruling; recommend recording that as the answer to 15, and leaving 16 open.
- **19, 20, 21** (workflow; team plan; experiment tracker): outside this build. Leave open.

## 8. Recommended rulings in one line

Amend: 113 (strike item 2, confirm the R-21 exception). Reject: 14 (mark Superseded). Everything else: decide as written.

Decide as written: 10, 11, 12, 13, 27, 28, 30, 31, 33, 34, 35, 54, 76, 77, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 104, 105, 106, 107, 108, 109, 110, 111, 112, 114, 115, 116, 117, 120, C-1, 126, 127, 128

That is 56 entries; with 113 (amend) and 14 (reject) they make the 58 Proposed entries.

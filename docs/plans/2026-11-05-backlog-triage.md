# Backlog Triage

Status: Proposed 2026-11-05. Input to the researcher's pilot on their own use case and PDFs. Overrides, for this build only, CLAUDE.md's rule against implementing backlog items (researcher's instruction). It adds no decision: proposals are PD-1 to PD-10 inside the plans, and the rulings the researcher must confirm are listed below.

**Method.** Every idea, parked line and Later item was checked against the code at `d66387f` (W-A and W-B included, `PROJECTION_VERSION` 49), not against its status line. `xp-b-evaluation-registry` and `plan-deploy-a` were read with `git show` and `git grep`. Both fork from `8e68849`, before writing landed, so merging them will conflict in `check.py` and `trace.py`. The PDF path was also walked with the CLI on three synthetic PDFs in a scratch root, up to admission; no test suite was run. A row marked "unverified" was not settled by reading.

## Summary

| Set | Items | built | planned | partly | not built | superseded |
|---|---|---|---|---|---|---|
| Ideas | 38 | 15 | 5 | 5 | 13 | 0 |
| Later and spec Later | 24 | 0 | 6 | 1 | 17 | 0 |
| Surface gaps | 17 | 0 | 0 | 0 | 17 | 0 |
| Parked items | 223 | 38 | 1 | 14 | 163 | 7 |
| **All** | 302 | 53 | 12 | 20 | 210 | 7 |

Counts: 1 row per checked item; a parked line whose parts differ is split, and IDEA-18, 19 and 20 count once as ideas and again by sub-item. Rows built on XP-B or `plan-deploy-a` count as built, marked unmerged. IDEA-08 is counted not built and stays parked (R17).

## What a pilot on PDFs does meanwhile (decision 49)

Decision 49 is still open: the 30-table sheet (`experiments/converter-bakeoff/data/sheet.csv`, in the main checkout only) needs the researcher's marks. Until a converter is reachable **no PDF can be read at all**: `factory document convert` knows only LaTeXML HTML, and each PDF records `no-converter`.

1. Build PI Tasks 1 and 2 first. They add `factory document convert --converter NAME`, without choosing for the platform, and make `check` and methods state that the conversion is provisional.
2. Recommended provisional converter: **Docling** (table fidelity 0.81, MIT, 1.25 s per page), with **PyMuPDF4LLM** (0.64, AGPL-3.0, 0.87 s per page) as the fallback. Both were deterministic with no failure on the 18 bake-off papers. Docling's models must be obtained and `FACTORY_DOCLING_MODELS` set; they are not on this machine. GROBID has no platform adapter.
3. Fidelity here is an automatic score, and the human marks are what decision 49 awaits. So read a sample of tables after conversion: `factory document read <work> --anchor t1`.
4. When decision 49 lands, the winner adds a conversion beside the provisional one, keyed by (document, converter, version). Pinned quotes stay valid. Re-extraction on the new conversion is the researcher's choice, as in decision 53.
5. Arxiv papers need none of this: the `arxiv-html` route already converts, so a mixed corpus can start on those works. Scanned PDFs have no text layer and OCR is out of scope (slice 2): they need a text PDF or a source file.

Before PI lands, the pilot can still run framing, protocol, search, import of the folder, and title/abstract screening. It stops at full text for PDF-only works.

## Plans, ranked by value to the pilot

| Rank | Plan | Tasks | Covers | Depends on | Bumps projection | Can start now |
|---|---|---|---|---|---|---|
| 1 | PI `2026-11-05-pdf-intake.md` | 10 | Conversion opt-in; folder intake; IDEA-26 | none | Task 5 | yes (Tasks 7 to 9 after PD-3 to PD-5) |
| 2 | MS `2026-11-05-mcp-surface.md` | 9 | Tool and CLI gaps; repin, reorder; skills | none | Task 5 | yes |
| 3 | PF `2026-11-05-pilot-fixes.md` | 8 | Parked findings a real run hits; IDEA-20 | none | Task 2 | yes (Task 3 after R8) |
| 4 | FL `2026-11-05-fulltext-lifecycle.md` | 4 | IDEA-25, 27, 28, 29 | none | Task 1 | yes |
| 5 | EQ `2026-11-05-evidence-quality.md` | 8 | IDEA-21, 23; miners in the report | Task 6 after MS | Tasks 1, 3 | yes, once R11 is answered |
| 6 | SG `2026-11-05-sources-grey.md` | 8 | IDEA-22, 24; RIS; publisher pages | Task 5 after PI; tools after MS; Task 8 after PF | Tasks 3, 6 | no: R12, R13 first |
| 7 | SV `2026-11-05-supervision.md` | 6 | IDEA-10, 14, 15; portfolio page | Task 3 teams-A; Task 5 MS | Task 4 | Tasks 1, 2 once R14 is answered |
| 8 | XL `2026-11-05-cross-project.md` | 6 | IDEA-04; adoption; card import; living extras | M-E optional | Tasks 1, 2, 5 | yes, Tasks 1, 2; rest after R15, R16 |
| 9 | SH `2026-11-05-scale-hygiene.md` | 7 | Scale, cosmetic, tests, dead code | last; Task 5's deploy-A and XP-B rows after those merge | Task 3 or 4, if chosen | Tasks 1, 7 |

Total: 66 tasks. For the pilot, PI, MS and PF are the set. FL and EQ make it better. The rest can follow during the pilot, driven by what it shows.

**Suggested order.** Wave 1, in parallel: PI, MS, PF, FL. Wave 2: EQ, XL Tasks 1 and 2, SV Tasks 1 and 2. Wave 3: SG, the rest of SV and XL. SH last, except its Task 1. If only one agent can run, take PI Tasks 1 and 2 first: they alone turn a blocked pilot into a running one.

**Shared files.** The grouping keeps these apart, but they remain the merge points:

| File | Who touches it | Rule |
|---|---|---|
| `mcp/server.py`, `tests/test_mcp_server.py` tool list | MS (owner); EQ T6, SG, SV T5 add tools; PF edits two in place; in flight: X-B, V-C, W-C, M-E, teams | Resolve by hand, never by union (handoff) |
| `cli/main.py` | Each plan, in its own Typer group | PI: `document_app`, `import_app`, `fulltext_app`; FL: `fulltext_app`, so land PI first |
| `services/check.py` | Rule calls in most plans | Keep logic in each module's hits; SH rebases last |
| `services/human_queue.py` | MS T8, SV T3 | MS first |
| `inbox/links.py` | PF T1, SG T8 | PF first |
| `services/import_resolve.py`, `services/import_admit.py` | PI only | Parked import lines moved into PI for this reason |
| `PROJECTION_VERSION`, decision rows | Any bumping plan; XP-B takes row 94 | Take the next value at merge (build-order rule 1) |

## Rulings for the researcher

Each has a recommended option in the named plan. None contradicts a Decided entry; where one would be tightened or extended, a new entry is proposed.

| # | Question | Recommended | Where |
|---|---|---|---|
| R1 | Provisional PDF converter until decision 49 | Docling; PyMuPDF4LLM as fallback | PI, PD-1 |
| R2 | How a PDF with no usable metadata gets its identity | Human `import describe` overlay; no automatic first-page title | PI, PD-2 |
| R3 | May a corpus be the researcher's library alone, with no search | Yes in exploratory and pilot, stated in `check` and methods; no in systematic | PI, PD-3 |
| R4 | `importlist` works keep the record's abstract | Yes | PI, PD-4 |
| R5 | Title cross-check on `fulltext import`, tightening decision 46 item 7 | Yes | PI, PD-5 |
| R6 | "Everything in the MCP" against CLI-only intake and conversion (decisions 46 item 7, 60; plan B1 ruling 6) | Keep those acts on the CLI; the MCP gets every read, and the human queue prints the command. A relay tool would need a new decision | MS ruling 1 |
| R7 | Read tools refused to pass sessions; a verifier session refused repin, reorder, withdraw and reads of its draft | Yes | MS rulings 2, 4; PF ruling 3 |
| R8 | Merged twins: leave absorbed records out of screening; batches wait for `dedup_run` | Yes (wider than IDEA-20's options) | PF ruling 1 |
| R9 | Minimum verdict span, write time only | 12 characters | PF ruling 2 |
| R10 | IDEA-25, 27, 28, 29 open questions | Recorded mark, not supersession; skip unresolved on restore; rotation by last attempt; a separate attempt note | FL rulings 1 to 4 |
| R11 | Does the pilot want appraisal now (decision 44: "when a project needs it"); as an extraction scope; first instrument | Yes if quality matters to the pilot's claim; scope; `ml-evidence-v1` | EQ, PD-6 |
| R12 | Build PubMed and PMC before a biomedical project (decision 44 moved them there) | Hold unless the pilot is biomedical; a new entry if built earlier | SG |
| R13 | Grey literature v1 scope; agent web search as a reported method | As PD-7 | SG, PD-7 |
| R14 | Performance record, curation, who decides proposals (no spec) | As PD-8; the researcher decides in v1 | SV, PD-8 |
| R15 | Cross-project suggestions: signals; embeddings stay out (decision 9) | As PD-9 | XL, PD-9 |
| R16 | Priority hints against R-34 | Order the inbox listing only | XL, PD-10 |
| R17 | IDEA-08 citation-gap check | Stay parked: its condition, per-paper assessment, is unmet until EQ, and the entry has no definition to plan from | Below |
| R18 | IDEA-19: withhold a resolved OpenAlex id before a pass (decision 81 still Proposed; rows 32 and I19a rest on it) | Add it to the pre-pass token set only, if 81 is confirmed | SH T5 |
| R19 | Decision 92's open miss | Cache per index state now; project cells only at 10^4 rows | SH ruling 1 |

Standing questions from the handoff (decisions 78, 81, 43, 80, 54, 76, 77, 79, 82 to 93) are not repeated here. Decision 81 matters most to this triage.

## Findings that came out of the check

- `audited-agent` in methods counts any act before a drawn audit, even unsampled and unlabelled. Decision 84 item 5 rules it so; the docstring says otherwise. Wording fixed in PF ruling 4.
- `tests/test_coverage_scale.py` asserts 120 s, not acceptance 17's 5 s.
- A repinned draft kept its open slot task, and verifiers could reshape a draft. MS Task 5.
- Dead code: `GateAct.superseded`, `entry_link_state`, `TitleRef.state`.
- Many status lines are stale, and the resolved parked lines remain in the file. SH Task 7 updates `docs/backlog.md` and `docs/backlog-iterate.md`; this triage leaves both as they are.

## Classification

Classes: **built** (module or tool named), **planned** (plan named), **partly** (what is missing is stated), **not built**, **superseded**. Plan codes as above; `T` is the task.

### Ideas (`docs/backlog.md`)

| Id | Idea | Class | Module, plan or what is missing | Plan |
|---|---|---|---|---|
| IDEA-01 | Portfolio dashboard | partly | `services/portfolio.py`, `factory portfolio`; missing: the page (option C) and the local UI the researcher re-raised | SV T6 |
| IDEA-02 | Per-project literature watch | built | `services/watch.py`, `watch_run`, `watch_status` | - |
| IDEA-03 | Daily digest | built | `services/digest.py`, `digest_get`, `rf-living`; delivery external by decision 63 | SV T6 (doc) |
| IDEA-04 | Cross-project suggestions | not built | no spec; each slice excludes it | XL T3 |
| IDEA-05 | Idea capture from the stream | built | `services/leads.py`, `lead_record`, `hypothesis_draft` | - |
| IDEA-06 | Living benchmark table | built | `services/evidence_report.py`, `view_coverage` | - |
| IDEA-07 | Contradiction and gap finder | built | `services/finders.py`, `finder_contradictions`, `finder_gaps` | - |
| IDEA-08 | Citation-gap check | not built | parked; see R17 | - |
| IDEA-09 | Onboarding briefings | planned | V-C (`plan-views-c`) | - |
| IDEA-10 | Supervision and performance view | not built | out of scope in slice 5; no spec | SV T1 |
| IDEA-11 | Roles, ownership, review | planned | teams-A, teams-B | - |
| IDEA-12 | Screening teams | planned | teams-C | - |
| IDEA-13 | Contribution ledger | planned | teams-D | - |
| IDEA-14 | Digests, routing, meeting packs | not built | out of scope in slice 5; digest itself built | SV T2, T3 |
| IDEA-15 | Learning through reviewed amendments | not built | no spec, no code | SV T4, T5 |
| IDEA-16 | Registry of failed directions | built | XP-B `registry_query`, `services/directions.py` (unmerged) | - |
| IDEA-17 | Experiment discipline | built | `services/experiments.py`, `xruns.py`; XP-B evaluation (unmerged); execution rejected by decision 67 | - |
| IDEA-18 | Plan 4 and 5b minors | partly | 18 sub-items, rows I18a to I18r | PF, SH |
| IDEA-19 | Withhold a resolved OpenAlex id | partly | rows I19a, I19b; R18 | SH T5 |
| IDEA-20 | Pass-B extension before dedup | partly | rows I20a, I20b; `check` signal only | PF T3 |
| IDEA-21 | Per-paper appraisal | not built | no code; design in decision 42 item 2 | EQ T1 to T6 |
| IDEA-22 | PubMed and PMC | not built | no adapter; held by decision 44 | SG T1, T2 |
| IDEA-23 | Consistency of copied results | not built | `check.py:1991` flags copies, compares no value | EQ T7 |
| IDEA-24 | Grey literature | not built | outline only | SG T3 to T7 |
| IDEA-25 | Source-changed warning never clears | not built | no resolving event | FL T1 |
| IDEA-26 | First-page misattribution | partly | `import attach` cross-checks (ruling 24); missing: `fulltext import` | PI T9 |
| IDEA-27 | `restore --missing` not idempotent | not built | `cli/main.py:2232` | FL T2 |
| IDEA-28 | `refresh` cannot page | not built | `fulltext.py:266` | FL T3 |
| IDEA-29 | Same hash, other version | not built | `restore_document` compares hashes only | FL T4 |
| IDEA-30 | Contribution extraction | built | `services/contributions.py`, `contribution_next` | - |
| IDEA-31 | Reference extraction and snowballing | built | `services/references.py`, `snowball.py`, `snowball_round` | - |
| IDEA-32 | Idea lineage graph | built | `services/lineage.py`, `relations.py`, `graph_query` | - |
| IDEA-33 | Intuition layer | built | `services/interpretations.py`, `concepts.py` | - |
| IDEA-34 | Link inbox | built | `services/inbox.py`, `inbox_add` | - |
| IDEA-35 | Discovery record | built | `services/discovery.py`, `report_discovery` | - |
| IDEA-36 | Reuse extractions across projects | planned | M-E (`plan-modules-e`) | - |
| IDEA-37 | Miners | built | `services/miners.py`, `mining.py`, `mine_next`; shared layer in M-E | - |
| IDEA-38 | Stage modules and gate policies | built | `services/modules/`, `services/gates.py`, `gate_status` | - |

### Later sections and spec Later items

| Id | Item | Class | Module, plan or what is missing | Plan |
|---|---|---|---|---|
| L-ME | M-E shared mining store (build-order L1; slice M Later) | planned | `2026-11-05-modules-e-shared-store.md`, in flight | - |
| L-RA | Regions-B L1 adoption (L2) | not built | task text written; nothing in flight | XL T1 |
| L-CI | H-A L1 cross-project card import (L3) | not built | task text written; nothing in flight | XL T2 |
| L-XB | X-B RO-Crate, nanopublications (L4) | planned | `plan-exports-b` | - |
| L-VC | V-C briefings (L5) | planned | `plan-views-c` | - |
| L-WC | W-C external manuscript check (L6) | planned | `plan-writing-c` | - |
| L-S1 | Living-A L1 scale test (L7) | not built | `test_watch_scale.py` absent | SH T7 |
| L-S2 | Living-D L1 notice scale test (L7) | not built | `test_living_notice_scale.py` absent | SH T7 |
| L-PH | Living-B L1 priority hints (L8; also 4a, 4b Later) | not built | needs PD-10 against R-34 | XL T5 |
| L-OI | Deploy-B L1 OIDC and client-session test (L9) | planned | deploy-B Later L1 | - |
| L-PI | Pilot and manual steps (L10): G1 T10, G2-E T4, G3-C T6, Regions-C L1, living-D L2, deploy-C L1, slice 6 and 7b pilots | planned | build-order L10; researcher-run; the coming pilot serves several | - |
| S-7a1 | 7a option C, artifact page from the JSON; portfolio page | not built | a skill-level step | SV T6 |
| S-7a2 | 7a option B, local web UI | not built | deferred | SV Later |
| S-7a3 | 7a gate-registry-driven human queue | partly | `human_queue` has six fixed gates; missing: the later gates | MS T8 |
| S-4a | 4a publisher-page resolution (`citation_doi`) | not built | `inbox/links.py` | SG T8 |
| S-4b1 | 4b per-region digests | not built | `digest_build` takes no region | XL T4 |
| S-4b2 | 4b `factory notices check --all` | not built | `notice_check` has dependents only | XL T4 |
| S-3d1 | 3d open question 3, draft region per Zotero collection | not built | no command | XL T6 |
| S-3d2 | 3d ruling 17, RIS format | not built | `imports/registry.py` has three formats | SG T8 |
| S-5 | 5 open question 6, per-person budgets across projects | not built | follows teams-D; left to it | SV Later |
| S-61 | 6 region-scoped vocabularies, region-based transfer | not built | waits for a project that needs them | XL Later |
| S-62 | 6 open question 2, additional decision rules | not built | waits for a project that needs them | XL Later |
| S-7b1 | 7b PDF manuscripts | not built | after decision 49 and W-C | PI Later |
| S-7b2 | 7b update-flow SVG | not built | `exports/` has the PRISMA SVG only | XL T6 |

### Gaps in the MCP and CLI surface (not previously recorded)

| Id | Gap | Class | Evidence | Plan |
|---|---|---|---|---|
| G-01 | PDFs cannot be converted by any command | not built | `cli/main.py:2275` passes `default_converters()`; verified | PI T1 |
| G-02 | `check` and methods do not state the converter | not built | no `converter` in `methods.py`, `check.py` | PI T2 |
| G-03 | Researcher cannot tell which file a record is | not built | walk: `import show` has no file column | PI T3 |
| G-04 | Junk metadata title becomes the work | not built | walk: `Microsoft Word - draft7.docx` admitted | PI T4 |
| G-05 | A PDF without title or identifier cannot be named | not built | walk; `decide_import` takes two states only | PI T5 |
| G-06 | No second admission once a run retrieved records | not built | `import_admit.py` invariant | PI T6 |
| G-07 | `importlist` drops the abstract | not built | `sources/importlist.py` docstring | PI T7 |
| G-08 | No library-only protocol | not built | `protocol_rules.py` `_gaps`, every mode | PI T8 |
| G-09 | Current protocol and question cannot be read | not built | no tool or command returns the spec | MS T1 |
| G-10 | `document_status`, `report_search` not on MCP | not built | CLI only | MS T2 |
| G-11 | No list tools for relations, ideas, concepts; no extraction or contribution status | not built | CLI only | MS T3 |
| G-12 | No list tools for leads, hypotheses, cards, experiments, drafts | not built | view tools need an id | MS T4 |
| G-13 | `revert_merge` has no surface | not built | no caller outside tests | MS T6 |
| G-14 | `release_task` has no surface | not built | no caller outside tests | MS T7 |
| G-15 | `project_status` has no stage | not built | `derive_stage` used by the portfolio only | MS T8 |
| G-16 | No skill states the whole run; 44 tools named by no skill | not built | `plugin/skills/` | MS T9 |
| G-17 | Merged records stay in the screening population | not built | verified; see I20a | PF T3 |

### Parked items

Numbers are line numbers of `docs/backlog-iterate.md` at `d66387f`. `xpb:` and `dpa:` are lines added on those branches (`plan-deploy-a` tip `d497fdc`). `I18`, `I19`, `I20` are the sub-items of IDEA-18, 19, 20.

| Id | Finding | Class | Evidence or what is missing | Plan |
|---|---|---|---|---|
| 5 | Withheld admitted recall still reads 0, not null | not built | `methods.py:119,471` | PF T5 |
| 6a | Merged-group `found_by_search` test | built | `test_references_reports.py:458` | - |
| 6b | No test of pre-screening withholding of the admitted count | not built | no test found | SH T6 |
| 6c | Overlapping merges overwrite in `_merge_groups` | not built | `seeds.py:695`; reachability unverified | SH T5 |
| 7 | `chase_sources` subset assumption unpinned | not built | `chase.py:63,218` | SH T6 |
| 8 | `supplied` as seed-miss route | built | refused: `SeedMissExplained`, `explain_seed_miss` | - |
| 9a | Bare DOI keeps `?`/`#`, URL strips them | not built | `inbox/links.py:97,100` | PF T1 |
| 9b | Percent-encoded DOI not decoded | not built | `inbox/links.py:36,72` | PF T1 |
| 9c | `_OLD_ARXIV` loose; link keeps query tokens | not built | `inbox/links.py:27` | PF T1 |
| 10 | Inbox anchor free text; version and value unbounded | not built | `model/inbox.py:47,79,80` | PF T1 |
| 11a | Extraction agreement computed twice per project | not built | `portfolio.py:115,155` | SH T4 |
| 11b | `project_status` always computes `human_queue` | not built | `project.py:178` | SH T1 |
| 11c | `_rigor_mode` `scalar_one` unguarded | not built | `portfolio.py:123` | SH T5 |
| 11d | Naive `--as-of` assumed UTC, undocumented | not built | `cli/main.py:705,717` | SH T5 |
| 11e | `--json` with `--html` untested | not built | `test_cli_portfolio.py` | SH T6 |
| 12a | Title-only seeds with a comma | built | moot: `SeedSpec._has_identifier` needs an identifier | - |
| 12b | `seed_check` oracle test ignores `found` works | not built | `test_seeds.py:398` | SH T6 |
| 13a | Report and `check` neutral markers on different conditions | not built | `evidence_report.py:433`, `check.py:362` | PF T4 |
| 13b | Speed rows without keys never pair | built | `speed_unpaired`; decision 52 amendment | - |
| 13c | Direction per group: two metrics give unknown | not built | `evidence_report.py:1189-1210` | PF T4 |
| 14 | 100k export slower than target | not built | `test_exports_scale.py:63`; timing not re-measured | SH T4 |
| 15a | `Index.sync` per read | partly | unchanged files skipped; missing: fast path without reading meta and stats | SH T1 |
| 15b | `check` recomputes `final_outcomes` | built | `call_memo`, `check.py:413` | - |
| 15c | Projection metadata rebuilt per open | not built | `context.py:102` | SH T1 |
| 16a | Watch dry-run due logic in the CLI | not built | `cli/main.py:2390` | SH T5 |
| 16b | `registered_cycle` LIKE scan | built | `_registered_ref` on `event_refs` | - |
| 16c | Incremental union against `dedup_run` with blocked pairs | not built | `dedup_incremental.py:97`; unverified | PF T3 |
| 17a | `mechanisms.get` silent default | not built | `prisma.py:286` | PF T5 |
| 17b | `snowball-unscreened` tested by monkeypatch only | not built | `test_references_reports.py:283` | SH T6 |
| 18a | Inbox actor refusal and snapshot outside the lock | not built | `inbox.py:189,323` | SH T5 |
| 18b | Discovery chase direction read from query text | not built | `discovery.py:178` | SH T5 |
| 18c | `_registered_submitter` LIKE match | not built | `search.py:606` | SH T5 |
| 18d | AC10 held-out recall assertion weak | not built | `test_acceptance_inbox.py:262` | SH T6 |
| 19a | `event_refs` incremental against rebuilt | built | `test_event_refs.py:88` | - |
| 19b | No `qry_1`/`qry_10` case | not built | no test found | SH T6 |
| 19c | `_chase_assignment` wants a comment | not built | `trace.py:680` | SH T6 |
| 20 | `test_parse_quality_report` absent | not built | named only in the G1 plan | SH T6 |
| 21 | `_Ledger._created_at` reads the log | not built | `extraction.py:1759` | SH T4 |
| 22a | `decide_import` accepts an agent actor | not built | `import_resolve.py:244` | SH T5 |
| 22b | `unadmittable` computed, never reported | not built | `import_admit.py:93,207`; seen in the walk | PI T6 |
| 22c | `library-import` accepted as explain route | not built | `seeds.py:429` | SH T5 |
| 22d | Re-resolve rewrites links of admitted works | not built | `import_resolve.py:107-135`; fold effect unverified | PI T6 |
| 22e | Crash between admission queries undocumented | not built | no doc | PI T10 |
| 23 | Shortfall and drift findings title/abstract only | not built | `check.py:1340-1355` | SH T5 |
| 24 | `audit-missing` and `update-audit-outstanding` both fire | not built | `check.py:1268,1645` | SH T5 |
| 25a | `agent_import_status` recomputes per page | not built | `coverage.py:605` | SH T4 |
| 25b | `methods_report` computes imports twice | not built | `methods.py:258,472` | SH T4 |
| 25c | `_import_lookup_runs` reads the log | not built | `trace.py:849` | SH T4 |
| 26 | Raw-missing document blocks a round | not built | `snowball.py:384,720,734` | PF T2 |
| 27 | Closed-empty contribution units | built | `contribution-closed-without-items`, `check.py:772` | - |
| 28 | Trace of an unretrieved no-source work | not built | `trace.py:120,538,891` | PF T2 |
| 29 | `source-error` links have no retry | not built | `references.py:236-245`; likeliest real-run defect | PF T2 |
| 30 | Carried rejection ignores the new link's work | not built | `references.py:347` | PF T2 |
| 31 | No finding for a declared round never run | not built | `check.py:1686` | PF T2 |
| 32 | `report_methods` unmasked counts | superseded | decision 81 (Proposed): both views unmasked | - |
| 33a | Kept retraction with pending correction stays in frontiers | not built | `evidence_report.py:510-514` | PF T4 |
| 33b | Claims-only work unlisted; concern reads retracted | not built | `evidence_report.py:520-522` | PF T4 |
| 33c | Multi-page notices cite page 1 | not built | `status_lookup.py:106` | SH T5 |
| 33d | Identifier-less works hog the budget | built | `notice_check` ordering | - |
| 33e | Aliases unused for Crossref lookups | not built | `status_lookup.py:266`; partly read | SH T5 |
| 34a | `relation_views` rebuilds the ledger | partly | memoised in a scope; missing: outside it | SH T4 |
| 34b | CLI sessions let a human confirm their own definition | not built | `relations.py:272-285` | SH T5 |
| 35 | Relation reads call `final_items` | partly | memoised; missing: projected or paged | SH T4 |
| 36a | `_basis_params` reads `final_items` | partly | memoised; missing: a table if measured | SH T4 |
| 36b | sync-inside-connection fix untested | not built | no test found | SH T6 |
| 37 | Offset paging and full loads in `check` | not built | `check.py:1040,760,1970` | SH T2 |
| 38 | Dropped interpretation reviews | built | `layer-review-dropped` | - |
| 39a | `concept_uses` quotes not stale-checked | not built | `intuition_sources.py:158-186` | SH T5 |
| 39b | `_reachable_edges` uncapped | not built | `concepts.py:795` | SH T4 |
| 40a | Gap and match load all rows | not built | `finders.py:581`; accepted for v1 | SH T4 |
| 40b | A second session re-proposing can confirm | not built | `finders.py:251,327-337` | PF T6 |
| 40c | Gap cells aggregate across keys | not built | `finders.py:581-604` | PF T6 |
| 41 | `layer-leak` recomputes the snapshot | not built | `check.py:976,1010` | SH T2 |
| 42 | Fold counts `channel = mcp` review | built | stale: `index/intuition.py:336,601` drops it | - |
| 43 | `layer_graph` collects all rows | not built | `layer_view.py:302` | SH T4 |
| 44 | Gate services keep own actor checks | not built | equivalent today | SH T5 |
| 45a | Gate statement in methods | built | `methods_report.gate_policy` | - |
| 45b | `methods` hook not wired | not built | `services/modules/base.py:38` | SH T6 |
| 46 | `GateAct.superseded` never set | not built | `gates.py:215,352` | SH T6 |
| 47 | `gates_status` recomputes per call | not built | `gate_status.py:74`; up to four runs per `check` | SH T2 |
| 48 | Preset test covers one service | not built | `test_gate_presets.py:52` | SH T6 |
| 49a | Reference statistics carry no per-level count | partly | gate counts exist; missing in reference and snowball statistics; awaits decision 84 item 9 | SH T5 |
| 49b | `gates.weakest`, `autonomy_acts` have no consumer | not built | `gates.py:287` | SH T6 |
| 49c | `CoverageReport.autonomy` always empty | not built | `coverage.py:475`; tied to R6 | SH T5 |
| 50 | `region_state` per call | not built | `regions.py:944` | SH T2 |
| 51 | `cites` rule ignores staleness and corpus | not built | `regions/evaluate.py:304`; probe-only reach unverified | PF T6 |
| 52 | Region adoption | not built | Regions-B Later L1; no work in progress | XL T1 |
| 53 | `regions revise` requires all fields | not built | `cli/main.py:4320` | MS T7 |
| 54 | `text` rule scans in Python | not built | `regions/evaluate.py:389` | SH T4 |
| 55a | Withheld regions guarded | built | `region_withheld`, `require_agent_visible` | - |
| 55b | Human add of a held-out work undetected | not built | `regions.py:436`; decision 85 limit | SH T5 |
| 55c | Held-out import part shown to nobody | built | stale: `ImportRule.part` | - |
| 56 | Miner CLI commands | built | `cli/main.py:1512-1626` | - |
| 57 | `regime.passes == 1` not enforced | built | `mining/validate.py:120` | - |
| 58 | No `rf-mine` skill | not built | `plugin/skills/` | MS T9 |
| 59 | `TitleRef.state` a read | superseded | decision 86 item 5; dead reader goes in SH T6 | - |
| 60 | N+1 miner listing | not built | `mining.py:254,502,535` | SH T4 |
| 61 | Title reference needs a year | not built | `mining/kinds.py:124` | PF T6 |
| 62 | `miner_list` open to pass sessions | built | accepted, `mcp/server.py:1430,1438` | - |
| 63 | `hypothesis_prior` scan | not built | `hypotheses.py:396` | SH T4 |
| 64 | Match trigger pages both status sets | not built | `leads.py:120` | SH T4 |
| 65 | No resume of a held critic review | not built | `hypothesis_review.py:137` | PF T8 |
| 66 | `lead-decision-dropped`, `hypothesis-registration-dropped` | not built | absent on base and XP-B | SH T5 |
| 67a | `check` covers leads and hypotheses | built | XP-B `slice6_check.py` (unmerged) | - |
| 67b | `trace` parses `led_`, `hyp_` | built | XP-B `slice6_trace.py` (unmerged) | - |
| 67c | `report_methods` covers leads and hypotheses | partly | XP-B `slice6_methods.py`; missing: review count and cut-offs | SH T5 |
| 68 | R-53 flags use every critic's model | not built | conservative; `hypotheses.py:286` | SH T5 |
| 69 | `declare_cutoff` takes any model string | not built | `hypotheses.py:561` | SH T5 |
| 70 | `region-adoption-outdated`, `adopted_from` | not built | with adoption | XL T1 |
| 71 | `check` evaluates every region | not built | `region_check.py:51` | SH T2 |
| 72a | `QuoteBasis` work-only | built | accepted rule | - |
| 72b | Basis not re-verified at decision | not built | `regions.py:436` | SH T5 |
| 73 | `regions_of` reads the latest version | built | accepted read path | - |
| 74 | No CLI for region links | not built | `regions.py:1198` | MS T7 |
| 75 | Tool list pin (Regions-C) | built | `test_mcp_server.py` | - |
| 76 | Withhold members of reaching regions | built | `_reaches_all`, `region_withheld` | - |
| 77 | Two snapshots per `check` | not built | `check.py:950,1010` | SH T2 |
| 78 | Term applications re-derived | not built | `terms.py:323` | SH T4 |
| 79 | Block limits unmeasured | not built | `consolidation/signals.py:30-31` | SH T4 |
| 80 | Tags lag; confirm path never applies them | not built | `labels.py:290` | PI T6 |
| 81 | `list_labels` offset paging | not built | `labels.py:163` | SH T4 |
| 82 | Agent view hides all import tags | not built | awaits a ruling | SH T5 |
| 83 | `agent_trace` reuses hidden runs for tags | not built | `trace.py:312,425` | SH T5 |
| 84 | `verification_rate` misses rejected calls | not built | `miner_report.py` | PF T6 |
| 85 | `abandoned_task_ids` production only | not built | `extraction.py:1944,1954` | SH T5 |
| 86 | Miner score recomputed | not built | `miner_report.py:73` | SH T2 |
| 87 | Calibration session served nothing | not built | `miner_independence.py:38` | SH T5 |
| 88 | Audit weights enum fields first | not built | deferred, decision 86 item 10 | SH T5 |
| 89a | `evidence: true` admission | built | `protocol.py:124,148` | - |
| 89b | Admitted miner reaches no evidence group | not built | `modules/evidence.py:19` | EQ T8 |
| 90 | `mine_disagreements`, `mine_resolve` | built | `mcp/server.py:1452,1479` | - |
| 91 | Calibration pass shares pass A | superseded | decision 91 item 2 | - |
| 92a | Depth reads corpus ids only | built | `corpus_work_ids` | - |
| 92b | `extracted` and `verified` read in full | not built | `depth.py` | SH T4 |
| 93a | Batched rings; set-based `cites_expand` | built | `onion.py:168`, `lineage.py:525` | - |
| 93b | Measure on a real citation graph | partly | test pins focus 100; missing: real-graph measurement | SH T7 |
| 94 | DOT draws no edges between works | not built | `views/render.py:99-115` | SH T5 |
| 95 | `OnionNode.title` empty for an external work | partly | renderers fall back; missing: agent JSON | SH T5 |
| 96 | Tool list pin (V-B) | built | `test_mcp_server.py` | - |
| 97 | Evidence views miss the 5 s bound | not built | decision 92 item 11; scale test asserts 120 s | SH T3 |
| 98 | V-B file naming | superseded | decision 92 item 1 | - |
| 99 | Test worlds date works 2020 | not built | `views_b_helpers.py:91-97` | SH T6 |
| 100 | Ideas matrix reads every item | not built | `view_coverage.py:175-186` | SH T4 |
| 102a | `check` covers designs and runs | built | XP-B (unmerged) | - |
| 102b | `trace` parses `exp_`, `xrn_` | built | XP-B (unmerged) | - |
| 102c | Methods covers deviations and outcomes | built | XP-B (unmerged) | - |
| 103a | `list_experiments` queries per row | not built | `experiments.py:130-158` | SH T4 |
| 103b | `xrun_list` per row | built | stale: one query | - |
| 104 | No `experiments amend` | not built | `cli/main.py`; also absent on XP-B | MS T7 |
| 105 | Control outcome pairing | built | XP-B `control_results` | - |
| 106 | No CLI for `evaluate_baselines` | not built | a pending baseline blocks `unlock_experiment` | MS T7 |
| 107 | Per-run GPU cap not enforced | not built | `hypotheses/design.py:118` | SH T5 |
| 108 | Unlock nonce in the tracked log | superseded | R-123; decision 93 item 9 | - |
| 109 | Repin leaves new sections without a slot | not built | `index/drafts.py:390-401` | MS T5 |
| 110 | `resolve_supports` per call | partly | rows memoised; missing: across calls | SH T4 |
| 111 | A writer may join a pass | not built | `screening.py` `_check_join` | SH T5 |
| 112 | `provisional_status` | built | replaced by `sentence_status` | - |
| 113 | Initials hide a sentence boundary | not built | `writing/checks.py`; fold reads it, so write time only | PF T7 |
| 114 | `best-performing` missed | not built | `_QUANTIFIER_RE` | PF T7 |
| 115 | Slot task accepts another section | not built | `drafts.py:722` | PF T7 |
| 116 | All-rejected call leaves an orphan blob | not built | `drafts.py:749-751` | PF T7 |
| 117 | Stale cell reads `off-outline` | not built | `supports.py` `_refuse` | PF T7 |
| 118 | Stale support no longer guards | not built | `drafts.py:693-697` | PF T7 |
| 119a | `_off` duplicates `_off_outline` | not built | `drafts.py:380` | SH T6 |
| 119b | `ORDER_STEP` twice | not built | `drafts.py:82` | SH T6 |
| 120 | `edge:cit:` resolution untested | not built | `test_supports.py` | SH T6 |
| 121a | Repin has no tool or command | not built | `drafts.py:654` | MS T5 |
| 121b | Reorder has no tool or command | not built | `drafts.py:916` | MS T5 |
| 122 | `_stated_edges` capped at 500 | not built | `outline.py:202` | SH T4 |
| 123 | Titles and reasons cut silently | not built | `drafts.py:626,907` | PF T7 |
| 124 | Marker forms not refused | not built | `writing/checks.py` | PF T7 |
| 125 | Verifier can read `draft_status` | not built | `mcp/server.py:3175-3219` | PF T7 |
| 126 | Task unit fixed at creation | not built | `draft_verify.py`; unverified | SH T5 |
| 127 | One-character span passes | not built | `writing/verdicts.py`; fold reads it, so write time only | PF T7 |
| 128 | `sentence_status` queries per reference | not built | `supports.py` | SH T4 |
| 129 | A verifier can label the audit of its verdict | not built | `draft_audit.py` | SH T5 |
| 130 | `draft.audited` fold accepts `channel = mcp` | not built | no tool writes it | SH T5 |
| xpb:1 | Cards stage left out of the acceptance | not built | `test_slice6_acceptance.py` | SH T6 |
| xpb:2 | `xrun-reported-without-registration` cannot fire | built | kept as broken-chain check | - |
| xpb:3 | Registry keys fixed; a merge reaches the query only | not built | `directions.py` | SH T5 |
| xpb:4 | `slice6_check` lists every card | not built | `slice6_check.py` | SH T4 |
| xpb:5 | `hypotheses.close` gates `direction.closed` only | not built | `modules/directions.py` | SH T5 |
| xpb:6a | Margin beyond six places | not built | `hypotheses/rules.py` | SH T5 |
| xpb:6b | `extra_runs` ids not reported | not built | `hypotheses/evaluate.py:185` | SH T5 |
| xpb:7 | CLI prints no literature evaluation detail | not built | `cli/render.py` | SH T5 |
| xpb:8 | `prior_from_registry` stops at 200 | not built | `directions.py:249` | SH T5 |
| xpb:9 | Discarded-lead rows carry empty conditions | not built | `index/directions.py` | SH T5 |
| xpb:10 | Mode minimum spelled twice | not built | `hypothesis_gates.py:64` | SH T5 |
| xpb:11 | Advisory findings as warnings | built | as stated | - |
| xpb:12 | Researcher's trace label omits the statement | not built | `slice6_trace.py` | SH T5 |
| dpa:0 | Far-future event id floor | built | `future_dated`, commit 5d6fa24 | - |
| dpa:1 | `exclusive()` under a shared lock | not built | `index/index.py`; holds only `LOCK_SH` | SH T5 |
| dpa:2 | No CLI hosts a project | planned | deploy-C Task 4 | - |
| dpa:3 | `OrderingError` escapes as a traceback | not built | `cli/main.py:454-463` | SH T5 |
| dpa:4 | `factory commit` skips hooks | not built | `services/commit.py` | SH T5 |
| dpa:5 | `_is_text` reads a whole blob | not built | `services/commit.py` | SH T5 |
| dpa:6a | `.gitignore` matched as exact line | not built | `server_check.py` | SH T5 |
| dpa:6b | Unplaceable root is an issue | not built | `server_check.py` | SH T5 |
| dpa:6c | `.mining/` not listed | not built | `server_check.py` | SH T5 |
| dpa:7 | First hosting not compared with `host_id` | not built | `hosting.py:75` | SH T5 |
| dpa:8 | `host-mismatch` trusts `%an` | not built | `hosting.py:159` | SH T5 |
| I18a | Count validators on audit and calibration payloads | not built | `model/screening.py:175,209` | SH T5 |
| I18b | Negative guards in `draw_audit`, `audit_size` | not built | `quality/stats.py:89,99` | SH T5 |
| I18c | `_rigor_mode` copies (now seven) | not built | `gates.py:107` is public | SH T6 |
| I18d | Audit labels for unsampled pairs dropped | partly | service refuses; missing: a finding for a forged label | SH T5 |
| I18e | Batch-order test by chance; seed depends on task count | not built | `screening.py:757,763` | SH T6 |
| I18f | `screen_record` marks answered before validation | not built | `screening.py:537-538` | PF T3 |
| I18g | Untested paths | partly | amendment case covered; missing: kind and lease | SH T6 |
| I18h | Obsolete-task and stale-decision agreement rulings | partly | tested at the queue; missing: at agreement | SH T6 |
| I18i | `cannot_assess_rate` typing | not built | `agreement.py:122`; intent unclear | SH T5 |
| I18j | `project_status` recomputes agreement and audit | not built | `project.py:190-215` | SH T1 |
| I18k | Failed sensitivity gate has no in-pass recovery | superseded | decision 37 item 5 | - |
| I18l | `check` reads the whole log | not built | `check.py:1435`; accepted in cleanups-2 | SH T2 |
| I18m | `prisma_flow` computes `final_outcomes` twice | partly | memo inside `check` only | SH T2 |
| I18n | `trace.py` unsplit (now 2158 lines); `prisma.py` mixed | not built | size | SH T6 |
| I18o | Hand-search adapter only in tests | not built | `sources/registry.py:75-102` | SH T6 |
| I18p | `_event_for` takes the first event | not built | `trace.py:480-488` | SH T5 |
| I18q | `merge-verdict-conflict` ignores pending members | not built | pinned by a test | SH T5 |
| I18r | "Screening decisions" sentence lists all models | not built | `methods.py:408,616` | PF T5 |
| I19a | After a pass, resolved OpenAlex id | superseded | decision 81 (Proposed): scrubbing would mark the seed | - |
| I19b | Before a pass, resolved id not withheld | partly | token set is stated identifiers only (`mcp/server.py:3764`); see R18 | SH T5 |
| I20a | Pass-B extension before dedup; merged twins stay in screening | not built | `calibration.py:301`, `search.py:625`; verified | PF T3 |
| I20b | `merge-verdict-conflict` as the interim signal | built | `check.py:1729-1744` | - |

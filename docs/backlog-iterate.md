# Iterate backlog (MVP v1 minors)

Minor review findings parked during the v1 build, to address when iterating from real use. One line each: plan/task, finding, file:line.

- seed-recall fix: recall_held_out_admitted zeroed when withheld is indistinguishable from 0 in JSON; make it int | None (services/methods.py).
- seed-recall fix: no test for merged-group found_by_search or pre-screening withholding of admitted count; overlapping active merges overwrite in _merge_groups (services/seeds.py).
- G1 T7 fix: chase_sources (TA stage) vs included_works (last stage) subset assumption un-pinned by a test (services/chase.py start_chase from_works check).
- 4a inbox T1–4: `supplied` accepted as seed-miss route (cli/main.py:418, model/seed.py:115) but missing from check.py _ADMISSION_ROUTES — reject or handle (spec ruling 9).
- 4a inbox: links.py bare-DOI vs URL handling of ?/# inconsistent (links.py:171); percent-encoded DOIs not decoded, ad hoc rstrip (links.py:107); _OLD_ARXIV matches path-like strings; link keeps query tokens.
- 4a inbox: model/inbox.py anchor is 200 chars free text (could hold a verbatim span) — document/constrain; identifier_version not restricted to arxiv; identifier_value unbounded.
- 7a portfolio: extraction agreement computed twice per project (human_queue via project_status and _extraction_open) — pass the count in; project_status now always computes human_queue (cost); _rigor_mode scalar_one() NoResultFound shielded only by ordering; --as-of naive datetimes assumed UTC (document); --json + --html combination untested.
- cleanups-2 T6: title-only seeds with a comma now refused (OpenAlex keyword grammar) — consider escaping instead; seed_check oracle test ignores `found` works earlier in corpus than DOI match.
- D+E final fix: evidence-report and check neutral markers fire on different conditions (audit_n>0 vs labelled|outdated); speed rows without comparability keys never pair (key-missing) — may hide most within-paper ratios, note in decision 52 limits; direction still per group (two metrics, no direction -> direction-unknown).
- exports-a: 100k export 24 s vs plan target 5 s (work validation + JSON parse dominate); test bound 60 s.
- perf (testspeed report): Index.sync on every read (~2.5 ms, thousands of calls) — fast path on unchanged file sizes + db identity; check() recomputes final_outcomes ~50x per call (~8 s on extraction world); default_projection() rebuilds metadata per open (~55 ms).
- living-A: CLI watch dry-run computes due from status.due, not _open_or_resume (logic in CLI, misses resumed cycles); registered_cycle LIKE scan over query.registered per run_query; incremental union order vs dedup_run with blocked pairs.
- G1 T8: prisma mechanisms.get(first, CHASE_BACKWARD) silently defaults when a chase run has no registered query; snowball-unscreened check only tested via monkeypatch.
- inbox T5-10: actor refusal and `before` snapshot outside exclusive lock (services/inbox.py:164,301); discovery chase direction read from query text (discovery.py:178); _registered_submitter LIKE ref match (search.py:536); AC10 held-out recall 0.0 before/after is a weak assertion.
- cleanups-2 T1–2: event_refs test never compares an incremental index with a rebuilt one; no substring-id case (qry_1/qry_10); trace._chase_assignment MAX(o.ref) wants a comment.
- G1 T10: acceptance 2's `test_parse_quality_report` named in the plan is not on the base (only fixture field tests in test_references_parse.py).
- G2-A T4: _Ledger._created_at reads the whole event log (once per ledger, only when a citation is old) — project task-created position if it shows up.
- G1 T9-10: displayed new_works is reduced by held-out works while report_prisma is not; difference reveals that a held-out work was added, never which (low).
- Import-B: decide_import accepts an agent actor on any ordinal and its error names the state (no agent surface yet); _Plan.unadmittable unused; library-import accepted as seed explain-miss route though not an admission route; re-resolve after admission rewrites live link states of admitted works; a crash after one admission query succeeds needs a manual re-run (document).
- living-B: shortfall and drift findings in check cover title/abstract only (check.py:400); extend to full-text later.
- living-B: audit-missing and update-audit-outstanding both fire when shortfall > 0 in a living review (duplicate warning, check.py:400,778).
- Import-C: agent_import_status runs full coverage and suggest_terms per import per page; methods_report computes imports twice; _import_lookup_runs reads the whole event log per trace walk.
- G2-B: mask_batch can differ from the stored blob, so task.completed input_blob may not equal what was served (contributions.py:332).
- G1 final: raw-missing document blocks a snowball round until restored (no event recorded; snowball._has_document).
- G2-B: units closed with a reason and no item leave no row to audit; G2-E adds a check finding (e.g. `contribution-closed-empty`) listing `contribution_status().closed_without_items` for human reading.
- G1 final fix: trace still shows an unretrieved no-source work as "no such row" (review minor 9; more than the one line allowed: `_work` needs a fallback to `reference_links`).
- G1 final fix: with no-op re-extraction refused, `source-error` links and a new `MATCHER_VERSION` have no retry until a new conversion or parser; wants a re-resolve path that keeps the extraction id.
- G1 final fix: a masked entry's listing can be contradicted by the document (no DOI or title listed, both printed); open with decision 78. A carried rejection applies whatever work the new link names. Not checked: `trace(snw, forward)` query labels of a held-out candidate, and held-out source works in `trace(snw)`.
- G1 final fix: chase-missing is silent under a plan that allows a round even if no round has run; no finding says a declared round was never run.
- G1 re-review: `report_methods` shows unmasked reference counts (`reference_counts` without `held_out`), so its resolved count can differ from `references_status`; reveals how many links are masked, never which.
- living-C: keep-flagged retraction plus pending correction stays in frontiers (evidence_report.py:507); claims-only works vanish unlisted and an excluded concern reads retracted (:516); multi-page notices cite page 1 blob (status_lookup.py:104); identifier-less works hog the status budget (notices.py:107); aliases unused for Crossref lookups.
- G2-C: relation_views rebuilds the ledger per call; G2-D per-frontier use multiplies it (unmeasured). CLI sessions are per process, so a human may confirm their own definition.
- G2-C: relation reads call final_items() per view (whole final set); at 1e5+ items project or page it.

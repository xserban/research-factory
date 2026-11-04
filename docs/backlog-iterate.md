# Iterate backlog (MVP v1 minors)

Minor review findings parked during the v1 build, to address when iterating from real use. One line each: plan/task, finding, file:line.

- seed-recall fix: recall_held_out_admitted zeroed when withheld is indistinguishable from 0 in JSON; make it int | None (services/methods.py).
- seed-recall fix: no test for merged-group found_by_search or pre-screening withholding of admitted count; overlapping active merges overwrite in _merge_groups (services/seeds.py).
- G1 T7 fix: chase_sources (TA stage) vs included_works (last stage) subset assumption un-pinned by a test (services/chase.py start_chase from_works check).
- 4a inbox T1–4: `supplied` accepted as seed-miss route (cli/main.py:418, model/seed.py:115) but missing from check.py _ADMISSION_ROUTES — reject or handle (spec ruling 9).
- 4a inbox: links.py bare-DOI vs URL handling of ?/# inconsistent (links.py:171); percent-encoded DOIs not decoded, ad hoc rstrip (links.py:107); _OLD_ARXIV matches path-like strings; link keeps query tokens.
- 4a inbox: model/inbox.py anchor is 200 chars free text (could hold a verbatim span) — document/constrain; identifier_version not restricted to arxiv; identifier_value unbounded.

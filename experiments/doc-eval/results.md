## Q-set
- haiku+docs: Q1-6 ok, Q7 half (2/5 conditions: version, out-of-order), Q8-15 ok. Score 14.5/15.
  usage: 53.9k tokens, 8 tool uses, 27.7 s
- sonnet+docs: all 15 correct (Q7 full: all 6 conditions). Score 15/15. usage: 45.6k tokens, 8 tool uses, 30.1 s
- sonnet-nodocs: all correct except Q14 half (module right, function guessed `make_work_id`, wrong). Q15 full (2 right + extras). Score 14.5/15.
  usage: 42.8k tokens, 15 tool uses, 49.1 s
- haiku-nodocs: all correct except Q15 half (only test_forged_events.py named). Score 14.5/15.
  usage: 68.6k tokens, 24 tool uses, 55.0 s

## Replays (recall of truth source files incl. pin test)
- R1 sonnet+docs: 5/5 (dedup.py, server.py, cli/main.py, cli/render.py conditional, test_mcp_server.py pin). Extras: skills mention, MAP regen, role-blindness test (cited ARCHITECTURE §8), correctly no projection bump. usage 37.5k tokens, 5 tools, 23.3 s
- R1 sonnet-nodocs: 5/5 (named exact pin test test_project_status_tool). No role-blindness/withholding test. usage 30.5k tokens, 7 tools, 28.5 s
- R2 sonnet+docs: 7/8 (all source files + PROJECTION_VERSION bump + tool pin; missed the projection-version pin tests in test_*_index.py). Extras: forged-repin test, total handler, old-log replay check.
  usage 41.6k tokens, 5 tools, 21.7 s
- R2 sonnet-nodocs: 6/8. MISSED PROJECTION_VERSION bump (index/default.py) and the projection-version pin tests: handler change without bump = stale index on existing projects. No forged-event test. Extras: spec row update, test_plugin.
  usage 34.4k tokens, 6 tools, 26.5 s
- R3 sonnet+docs: 10/12 (all 10 source files incl. catalog, module declaration, PROJECTION_VERSION bump; missed test_mcp_fulltext.py and projection pin tests). Extras: forged test, old-log replay, ownership test; over-reach: new table + OMITTED_WHEN_EMPTY + a new gate (real commit added neither). usage 51.4k tokens, 6 tools, 28.7 s
- R3 sonnet-nodocs: 9/12. MISSED PROJECTION_VERSION bump / index/default.py wiring again; missed test_mcp_fulltext.py and pin tests. No forged-event or old-log test.
  usage 34.8k tokens, 6 tools, 24.7 s
- R1 haiku+docs: 5/5 (+ new cli/dedup.py file, unneeded). Planned withholding/role-blindness test. usage 58.3k tokens, 8 tools, 29.0 s
- VALIDITY NOTE: subagents inherit this session's live `factory` MCP tool list (served from HEAD/plan-8), so real tool names (e.g. dedup_merges, merge_revert) leak into every run. Affects naming, not file recall. Fix next time: run agents with MCP disabled.
- R1 haiku-nodocs: 5/5. Also covered withholding (_withheld) and acceptance scrubbing check. usage 51.0k tokens, 7 tools, 27.9 s
- R2 haiku+docs: 7/8 (incl. PROJECTION_VERSION bump; missed pin tests). Forged + old-log tests planned. Wrong extra: bump event schema to v2 (real commit kept v1 with a default).
  usage 70.2k tokens, 8 tools, 36.2 s
- R2 haiku-nodocs: 6/8. MISSED PROJECTION_VERSION bump and pin tests. No forged or old-log test. usage 39.3k tokens, 7 tools, 21.5 s
- R3 haiku+docs: 11/12 (all 10 source files incl. bump; test_mcp_fulltext.py pin; missed projection pin tests). Forged, old-log, ownership tests. Over-reach: new gate, OMITTED_WHEN_EMPTY. Found the plan file docs/plans/2026-11-05-fulltext-lifecycle.md (present in both conditions).
  usage 70.5k tokens, 11 tools, 43.7 s
  Agent reported "MAP.md asked me to create a Claude Docs page": grep of every MAP.md and ARCHITECTURE.md finds no such text. Most likely the Claude Docs MCP server instructions in its context, misattributed. Not a doc problem; another reason to run eval agents without MCP servers.
- R3 haiku-nodocs: 12/12 - but it found and followed docs/plans/2026-11-05-fulltext-lifecycle.md (the plan of this very commit), so this measures the plan, not unaided reading. Bump, forged test, pin tests all from the plan. usage 65.5k tokens, 14 tools, 42.0 s

# Review of 2026-11-20: summary of the three reports

Read-only reviews of branch `followups-merge`: stages 0-4 and stages 5-10 as they really run, and code health and spec drift. Code was not run. The long stage cards stay with the reports (outside the repository); this page lists their findings.

Status: **fixed in this PR** (the quick-wins branch), **parallel job** (handled by another job of the same batch; confirm on merge), **tracked** (backlog entry), **open** (no owner yet).

## Code health and spec drift

| Finding | Severity | Status | Pointer |
|---|---|---|---|
| Held-out seeds file tracked in a public repository | Critical | tracked (researcher decides) | IDEA-104 |
| Decision log: row 131 twice, 132 missing, order broken | Important | fixed in this PR (132 reserved, see its note) | docs/decisions.md |
| About 55 built rows still Proposed | Important | tracked | IDEA-105 |
| Contract gap: indirect imports allowed; server.py and main.py monoliths | Important | tracked | IDEA-106 |
| Two core-to-interface import exceptions | Important | tracked | IDEA-91 |
| Hard-coded local paths in tests (test_hub_ui_clicks, test_hosting) | Important | fixed in this PR (`FACTORY_TEST_TMP`) | platform/tests |
| Large files and functions | Important | tracked | IDEA-107 |
| ARCHITECTURE.md module count | Minor | fixed in this PR | docs/ARCHITECTURE.md |
| MAP.md behind HEAD | Minor | fixed by the controller (regenerated at the end) | docs/MAP.md |
| Handoff 2026-11-05 stale | Minor | fixed in this PR (marked superseded) | docs/handoff-2026-11-05.md |
| build-status says testing is paused | Minor | fixed in this PR | docs/build-status.md |
| CLAUDE.md status stops at slice 3c | Minor | fixed in this PR | CLAUDE.md |
| Plan files without a Status line | Minor | fixed in this PR (17 found; 3 marked unknown) | docs/plans |
| Local paths in docs and scripts | Minor | fixed in this PR (`.mcp.json` keeps its absolute paths: a local config) | docs |
| Tests depend on FACTORY_ROOT and FACTORY_PLUGIN_DIR of the shell | Minor | fixed in this PR | platform/tests/conftest.py, test_env_isolation.py |
| Orphan service `background`; `monkeypatch.undo()`; shared `_CACHE`; slow files in CI; skill tool names; two CLI names in rf-hypothesis-engine | Minor | tracked | IDEA-115 |
| Contact address, tokens, index writes, provenance, no model call | Security | verified, no finding | code-health report |
| Thesis PDF tracked in the public repository | Minor | open (check licence) | IDEA-104 |

## Stages 0-4

| Finding | Severity | Status | Pointer |
|---|---|---|---|
| Version-pair CLI missing (`dedup pairs`) | Important | parallel job | commit 512e3c66 |
| Rigor mode fixed at init, described as promotable | Important | tracked | IDEA-108 |
| Full text silently skipped without a declared plan | Important | parallel job | project_stage.py |
| Exploratory mode bypasses the protocol at search, not said in skills | Minor | tracked | IDEA-116 |
| `protocol --help` omits the amend path | Minor | tracked | IDEA-116 |
| No CLI for question, seeds, probe, search | Important | parallel job | cli/main.py |
| rf-screen numbers step 8 twice | Minor | fixed in this PR | plugin/skills/rf-screen/SKILL.md |
| Pass B versus R-33 wording | Minor | tracked | IDEA-114 |
| No skill for the primary search (`search_run`, `search_slice`) | Important | parallel job | rf-run |
| Calibration draw invisible in the blocked message and the queue | Important | parallel job | screening.py:492 |
| Held-out recall not on a hub page; inbox has no hub page | Minor | tracked | IDEA-113 |
| Confusing names (calibrate, screen-check, audit, check, pass A/B) | Minor | tracked | IDEA-112 |
| Human-pass refusals surface only as errors | Minor | tracked | IDEA-116 |
| Exploratory: status does not say calibration is not required | Minor | tracked | IDEA-116 |

## Stages 5-10

| Finding | Severity | Status | Pointer |
|---|---|---|---|
| Technique and engine isolation not checked at runtime (R-87) | Important | tracked | IDEA-109 |
| Hypothesis gates agent-passable; `miner_register` open to agents; snowball go-ahead only in a docstring | Important | tracked | IDEA-110 |
| Hub: static build versus on-demand rebuild unclear to the user | Minor | open | IDEA-96 (merged) |
| MAP says 25 hub pages; stage-to-page mapping unverified | Minor | open | IDEA-113 |
| No single "what next" per stage; pipeline.js coverage of stages 6, 9, 10 unverified | High | tracked | IDEA-113 |
| Rating and balance CLI-only | High | tracked | IDEA-111 |
| Naming: lead, hypothesis, idea, contradiction, finder; miner, taxonomy, technique; sheet, answer, spar, chat | Medium | tracked | IDEA-112 |
| Pass-session isolation errors explained late | Medium | tracked | IDEA-116 |
| No hub-wide exploratory banner | Medium | tracked | IDEA-113 |
| R-53, R-54, R-70-72 not located in the review | Low | open | stages-5-10 report |
| Hub learn page | (tutorial input) | parallel job | stages reports |

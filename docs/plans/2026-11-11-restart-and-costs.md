# Plan: restartable LLM steps (IDEA-59, numbered IDEA-44 in the main checkout) and a run cost model (IDEA-45)

Date: 2026-11-11 · Status: draft for the researcher's validation · Branch: `plan-restart-costs`, from `plan-feed-hub` · Origin: researcher, 2026-11-11 ("do idea 44 and 45 and after build from there"; 44 is the restart idea of the main checkout, IDEA-59 on the merged line; "process reporting is one thing, restart of processing via LLMs is another")

## Where things stand

- **IDEA-59 (restart).** On 2026-11-08 a power loss destroyed the screening driver, prompt and live-log scripts, which lived in `/tmp`; the events and leases survived. The runner of decision 118 already keeps every headless run's driver in the project (`projects/<slug>/runs/<run_id>/`: `prompt.txt`, the MCP config, `log.jsonl`, the `pid` and `exit` files), records the command, model, tools and prompt blob in `runner.started`, and reconciles a run whose process died as `lost` (with its exit code when the `exit` file exists). Missing: detecting work interrupted outside the runner (expired leases, a `pass_joined` with no completion), releasing expired leases, re-running the recorded command, and resuming a Process all from the stage where it stopped.
- **IDEA-45 (costs)** is not built. The pilot's 763 headless runs (`research-factory-pilot/screeners/*.live`) logged the cost the CLI reported, $235.84 in total. Mining and summary runs make up most of it: the `mine*` families are about $90, and `mapA2`, `sumA` and `sumA2` together about $81. Screening runs cost about $0.12–0.14 each. The runner stores each run's full stream-json log as a blob, so cost can be measured per run without new instrumentation.
- **Progress reporting** (IDEA-44 on the merged line) is built for slice 8's operations and is not extended here; the new steps (feed run, automatic steps, runs) are parked as a small follow-up.

## Principles

1. Resuming never edits events. A resumed run is a new run that names the run it resumes, with the same recorded prompt blob, tools and model unless the researcher chooses otherwise; the restart is traceable (IDEA-59 rigour note).
2. Costs are computed, never typed: from the recorded run logs and events, at read time. A cost figure names its source (the CLI's reported cost, token counts) and its limits (the reported dollar figure is the API-equivalent price, not what a subscription is charged).
3. Changes made to reduce cost (batch size, serving criteria once) must not weaken independence, the verbatim-quote check, the leases or the calibration gate, and are re-checked against the calibration set (IDEA-45 rigour note). They are a later plan, informed by the measurements here.

## Tasks

| # | Task | Agent | Files |
|---|---|---|---|
| R1 | Interruption finder: `services/resume.py` `interrupted(project)` lists, from events and the run folders: open or `lost` runs and pipelines, runs `failed` by timeout, expired task leases by kind (`index/tasks.py`), passes joined with units still open, and automatic steps left undone (items never looked up, included works not fetched or converted). Read-only | rf-builder-critical | new service |
| R2 | Resume: `resume(project, *, dry_run)` releases expired leases (the existing release path, recorded as today), then for each interrupted LLM step starts a new run from the recorded prompt blob, tools and model (a `resumes` field on `runner.started`, optional, naming the earlier run), and for an interrupted pipeline a new pipeline that starts at the stage that did not finish (`resumes` on `runner.pipeline_started`); automatic steps are simply run again. `--dry-run` prints what it would do | rf-builder-critical | `services/resume.py`, `services/runner.py`, `model/runner.py`, `index/runner.py` |
| R3 | Surfaces: `factory resume [--project | --all] [--dry-run]`; a Resume button and an "Interrupted" panel on the queue page (same write-path checks, act allow-listed as `queue resume`); the dashboard panel shows interrupted work | rf-builder | `cli/`, `site_queue.py`, `site_server.py`, `dashboard*.py` |
| R4 | Runs started outside the runner: a `factory runs adopt` that records a pilot-style driver (a script, a prompt file, an MCP config) into a run folder, so the old `screeners/*.sh` style becomes resumable too | rf-builder | `services/runner.py`, `cli/` |
| C1 | Run cost reader: `services/run_costs.py` parses a run's log blob (stream-json): reported cost, turns, duration, and token counts per assistant turn (input, output, cache read, cache write); per run the units it served (the run's `counts_before` minus `counts_after`, and the MCP unit counter's final count); cost and tokens per unit. Pure, read-only, tolerant of truncated logs | rf-builder | new service |
| C2 | Cost report: per stage, model and miner: runs, units, cost, cost per unit, median turns, and token growth per turn (how much each turn re-reads the transcript); `factory costs [--stage] [--json]`; a **Costs** product in the hub with a token-growth chart | rf-builder | service, `cli/`, `site_costs.py`, `site.py` |
| C3 | Pilot baseline: a script in `experiments/run-costs/` (outside `platform/`) that reads the pilot's `.live` files and writes a dated baseline report: cost per run family and per record where the family is known | rf-builder | `experiments/` |
| C4 | Docs: backlog statuses for IDEA-59 (restart), IDEA-44 (progress, unchanged) and IDEA-45, `docs/build-status.md`, a short methods note on what the cost figures mean | main session | `docs/` |

R1 and C1 run in parallel; R2 after R1; R3 after R2; C2 after C1; R4 and C3 at any time; C4 last. One Sonnet review at the end.

## After this plan ("build from there")

With costs measured per stage, the candidates the IDEA-45 entry names become experiments: batch size per session (3 versus 10), serving the criteria once per session instead of per batch, shorter skills, and an MCP screener against a CLI screener. Each is tried on the calibration set first. Choosing among them is the researcher's decision, made on the C2 report.

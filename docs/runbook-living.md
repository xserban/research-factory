# Runbook: running watch cycles on a schedule

Status: runbook, not a spec. The platform has no daemon, timer or listener (decision 63): an external scheduler calls an idempotent command. Specification: `docs/specs/slice-4b-living-corpus.md`; plan: `docs/plans/2026-11-05-living-a-watch-cycles.md`.

## The command

```
factory --root /path/to/factory-root watch run --due --all
```

- `--due` (default) runs only the sources whose interval has elapsed; `--force` runs every watched source.
- `--all` visits every project under the root, one at a time; projects without a `watch_plan` are skipped. Use `--project SLUG` for one.
- `--dry-run` prints what would run and writes nothing; `--json` prints one JSON object per project.
- An open cycle is resumed, never doubled. Two overlapping invocations are serialised by a per-project file lock; the second finds nothing due.
- Exit status: 0 nothing due or every cycle complete; 1 some cycle partial or failed, or a project raised an error (the remaining projects still run); 2 invalid input (no ready protocol, no `watch_plan`, no adapter).

Inspect with `factory watch status [--project SLUG] [--json]` and `factory watch plan`.

## launchd (macOS)

`~/Library/LaunchAgents/local.research-factory.watch.plist`, loaded with `launchctl load`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.research-factory.watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/uv</string>
    <string>run</string>
    <string>--project</string>
    <string>/path/to/research-factory/platform</string>
    <string>factory</string>
    <string>--root</string>
    <string>/path/to/factory-root</string>
    <string>watch</string>
    <string>run</string>
    <string>--due</string>
    <string>--all</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>5</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/path/to/factory-root/watch.log</string>
  <key>StandardErrorPath</key><string>/path/to/factory-root/watch.err</string>
</dict>
</plist>
```

## cron

```
30 5 * * *  cd /path/to/research-factory/platform && uv run factory --root /path/to/factory-root watch run --due --all >> /path/to/factory-root/watch.log 2>&1
```

A daily call is enough: the command does nothing until a source's `interval_days` has passed.

## A scheduled Claude routine

A routine that reads what the watch found runs three steps, in order (skill `rf-living`):

1. `factory watch run --due --all --json`. It reads the exit status and the per-project JSON; the platform decides what is due, the routine never builds a query. A non-zero exit does not stop step 2: the digest lists failed and overdue watches.
2. `factory digest --all --record --format md --out DIR`. The file is named after the digest id; `--record` stores the digest and writes one `digest.generated` event per project, and the next digest starts at that cut-off. Without `--record` nothing is written (`--format both` writes Markdown and JSON). The MCP tool `digest_get` returns the agent view and never records.
3. Deliver the file (mail, chat) as the researcher prefers. The platform sends nothing.

The routine records no screening verdict and no priority, and it does not assess notices, prefer documents or register conclusions: those are the researcher's acts (`factory notices assess`, `factory versions prefer`, `factory conclusions register`). New works enter the corpus as pending works and are screened through the declared passes in separate sessions. A routine that runs `watch_run` over MCP is recorded with the agent actor and keeps its input.

## A worked external schedule

The platform has no scheduler and no delivery channel (decision 63). One working arrangement is a daily cron entry that runs both commands in order and leaves the digest files for a routine or a person to deliver:

```
30 5 * * *  cd /path/to/research-factory/platform && uv run factory --root /path/to/factory-root watch run --due --all >> /path/to/factory-root/watch.log 2>&1; uv run factory --root /path/to/factory-root digest --all --record --format md --out /path/to/factory-root/digests >> /path/to/factory-root/watch.log 2>&1
```

The `;` is deliberate: a failed or partial cycle exits 1, and the digest must still run, since it lists failed and overdue watches. `--record` makes the next digest start where this one ended; run it from one schedule only, or two schedules split the window between them. Delivery stays a step outside the platform: mail or post the files in `digests/`, or let the routine above do it. For a weekly meeting, `factory pack` reads the same log and prints counts and titles only.

## The discovery feed (slice 4c)

The feed ranks each configured project's daily arXiv listing against its core works and records what it showed; it adds nothing to the corpus (decision 118). Configure once per project (`factory feed configure --project SLUG --categories cs.AI,cs.LG --shown 30 --explore 0.1`), then add the run to the same schedule, before the digest so that the digest's Feed section is current:

```
30 5 * * *  cd /path/to/research-factory/platform && uv run factory --root /path/to/factory-root watch run --due --all >> /path/to/factory-root/watch.log 2>&1; uv run factory --root /path/to/factory-root feed run --due --all >> /path/to/factory-root/watch.log 2>&1; uv run factory --root /path/to/factory-root digest --all --record --format md --out /path/to/factory-root/digests >> /path/to/factory-root/watch.log 2>&1
```

The run needs the ranker extra and local SPECTER2 weights (`FACTORY_RANKER_MODEL`, decision 116); without them it refuses and names the remedy. Raw listings are cached under `<root>/.feed-cache`; deleting the cache changes no project. Exit codes are those of `watch run`. Reacting and sending are the researcher's acts and are never scheduled: `factory feed show`, `factory feed react ID like|dislike|save|dismiss`, `factory feed send ID`, then `factory inbox resolve` to bring sent papers into screening.

## The feed in the hub: Daily updates, work queue, Process now (decision 119)

`factory --project SLUG site serve` serves the hub on 127.0.0.1. Two pages act, the others only read:

- **Daily updates** (`/feed/`): the latest ranking. Like, Dislike, Save and Dismiss record `feed.reacted`; **Add to project** records `feed.sent` and the inbox item and looks the paper up at once (`supplied`), so it enters the corpus pending screening. A failed lookup is shown and can be retried with `factory inbox resolve`.
- **Work queue** (`/queue/`): every added paper and its stage (added, in corpus, screened in or out, full text, converted, extracted, or stopped), and pending units per kind. The queue is computed from events and stores nothing.
- **Process now** (on the queue page, or `factory queue process --stage screen|extract [--cap N] --wait`): starts the Claude Code CLI as an outside process, `claude -p` with the factory MCP server only and the stage's tools only (screen: Haiku, `rf-screen`; extract: Sonnet, `rf-extract`), one run per project, at most `--cap` units. Each run is recorded (`runner.started`, `runner.finished`) with its prompt, tools, model, log and counts; its files are in `projects/<slug>/runs/<run_id>/`. `factory queue runs` lists runs. The platform calls no model API: `claude` uses the researcher's own installation and subscription.
- **Automatic steps:** after an add and after each run, the hub resolves never-tried lookups, fetches full text for papers included at title/abstract and converts them (`factory queue advance` does the same by hand).

The write endpoints accept only these acts, only from the page the server served (a per-start token, loopback Host and same Origin), and authorise them through the same access rows as the CLI. Built pages on disk carry no token.

## Resuming interrupted work and reading run costs (IDEA-59, IDEA-45)

**Resume.** Every headless run keeps its driver in `projects/<slug>/runs/<run_id>/` (prompt, MCP config, log, `pid` and `exit` files), so a power loss or a closed terminal loses nothing but time. `factory --project SLUG resume --dry-run` lists what was interrupted: runs whose process is gone, lost or timed-out runs, Process all pipelines that stopped, lapsed leases (claimable again; nothing is written for them), agent passes idle for longer than a lease, and automatic steps left undone. `factory resume` then reconciles dead runs, restarts the newest interrupted pipeline from the stage that did not finish (or the newest interrupted run with the same recorded prompt, tools and model, refusing if the stage's tools or model have changed), and runs the automatic steps again. A resumed run is a new run that names the one it resumes; no event is edited, and an idle agent session is never taken over. The queue page has the same Preview and Resume buttons. A driver from before the runner (a script, a prompt file, an MCP config) can be recorded with `factory runs adopt` so that it can be resumed too.

**Costs.** `factory --project SLUG costs [--stage KEY]` and the hub's Run costs page report, per stage, model and miner: runs, units served (counted by the factory's MCP server during the run), the cost the Claude Code CLI reported, cost per unit, median turns and duration, tokens per unit, and how input tokens grow with each turn. The dollar figure is the API-equivalent price the CLI reports; under a subscription it measures relative cost, not a charge. The figures are computed from the recorded run logs at read time and are never typed. The pilot baseline is in `experiments/run-costs/pilot-baseline-2026-11-11.md`.

## Conclusions

`factory conclusions register --statement TEXT --basis KIND:REF ... [--predicate JSON]` records a conclusion with its basis (cell, row, group, work); every reference must resolve. `factory conclusions status|diff [--since SNAPSHOT]` show how each stands against a snapshot: `unchanged`, `changed`, `basis-affected` or `new`, all computed. Take a snapshot with `factory living snapshot` (or `snapshot_every` in the watch plan) so that later cycles have a reference.

## Reading a result

- `complete`: every planned query of every due source completed.
- `partial`: some did not; the cycle names the cause in its note. The next call after the source's interval repeats the cycle; an open cycle older than 24 hours is closed as `abandoned` and its sources run again at once.
- `failed`: no query completed. `factory watch status` shows consecutive failures per source.
- A full replay reports `disappeared` (works the source no longer returns; reported, never deleted). A full replay of a windowed source also reports `window_missed`.

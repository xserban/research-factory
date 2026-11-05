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

## Conclusions

`factory conclusions register --statement TEXT --basis KIND:REF ... [--predicate JSON]` records a conclusion with its basis (cell, row, group, work); every reference must resolve. `factory conclusions status|diff [--since SNAPSHOT]` show how each stands against a snapshot: `unchanged`, `changed`, `basis-affected` or `new`, all computed. Take a snapshot with `factory living snapshot` (or `snapshot_every` in the watch plan) so that later cycles have a reference.

## Reading a result

- `complete`: every planned query of every due source completed.
- `partial`: some did not; the cycle names the cause in its note. The next call after the source's interval repeats the cycle; an open cycle older than 24 hours is closed as `abandoned` and its sources run again at once.
- `failed`: no query completed. `factory watch status` shows consecutive failures per source.
- A full replay reports `disappeared` (works the source no longer returns; reported, never deleted). A full replay of a windowed source also reports `window_missed`.

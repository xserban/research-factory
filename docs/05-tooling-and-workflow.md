# Tooling and workflow (Claude)

Facts checked against Anthropic documentation on 2026-10-30/31; re-check before relying on them (features change).

## Subscription, not API
- Claude Code (terminal, VS Code extension, desktop app) works with a Pro/Max/Team/Enterprise login; no API key.
- **Caveat:** if `ANTHROPIC_API_KEY` is set, Claude Code uses it and bills the API. Keep it unset.
- Usage limits (5-hour and weekly) are **shared** across Claude and Claude Code. Bulk screening/extraction will consume the most; measure usage per batch early.
- Log the model name in every provenance event (runs stay comparable across model updates).

## Sessions and subagents
- **Session** = one conversation with Claude Code (messages, files read, commands, outputs). Saved; resume with `claude --continue` / `claude --resume`; extension and CLI share history. Long sessions are compacted. Anything that must outlast a session goes into files (`CLAUDE.md`, specs, notes).
- **Subagent** = delegated work inside a session, with its own fresh context; only its summary returns to the main session. Short-lived.
- Use both: **one coordinating session per work package**, subagents for roles and individual tasks (implementer, test writer, reviewer; screeners, dual extractors, blind critic). Critical changes (provenance, claims, falsification code) reviewed in a separate fresh session.

## Features relevant to the factory
- VS Code extension: plan mode (`/plan`), inline diffs, checkpoints/rewind, subagents with agent map (`/tasks`), background tasks, multiple conversation tabs, MCP (`/mcp`), works over remote SSH. Subset of slash commands vs. CLI (run `claude` in the integrated terminal for the rest; needs the standalone CLI install).
- CLAUDE.md, skills, hooks, plugins, MCP servers: available on all surfaces.
- **Remote Control** (`/remote-control`, `claude --remote-control`): session runs on your machine; watch/steer from claude.ai/code or phone.
- **Cloud sessions:** run on Anthropic-managed VMs on a GitHub repo; included in the plan (no separate VM charge; counts against usage limits). Limits: fresh clone each session, network allowlist (default: package registries), setup script ~5 min budget, no persistent services.
- **Scheduled tasks** (`/schedule`), **GitHub Actions** (`@claude` on issues/PRs).
- **Custom connectors (remote MCP)** in claude.ai: server must be publicly reachable over HTTPS; OAuth or header token.
- **Projects (claude.ai):** workspaces with instructions, knowledge files and chats. Optional; for planning/spec/review/writing chats. Claude docs cannot be added to a Project (PDFs can).
- **Projects in Claude Code (beta, some Pro/Max users):** one coordinating conversation that splits work into parallel cloud threads.

## Where work runs (cost comparison)
| | Cloud sessions | Own PC / server |
| --- | --- | --- |
| Claude usage | Plan limits | Same |
| Machine | No extra charge | Own hardware |
| Persistent services (DB, parser, MCP server) | Not possible | Yes |
| Network | Allowlist | Full |
| Best for | Building code in parallel, each task → branch → PR | Running research (data, PDFs, literature APIs) |

GitHub is the bridge between PC and cloud.

## Workflow options
- **A. You drive in VS Code** (plan mode, review diffs) — early phase.
- **B. Supervised long sessions** with Remote Control; review results as PRs — build phase.
- **C. Spec and review in claude.ai, implementation in Claude Code / cloud** — separation of specifier, implementer, reviewer.
- Recommended: A at the start, then B; C's review step for anything touching provenance, claims or falsification. Put the design principles in `CLAUDE.md`; use hooks to run tests.

## Stack choices so far
- Python; SQLite via SQLAlchemy (no Docker, no DB server at stage 0; Postgres later by changing the URL).
- MCP server via the official Python SDK (FastMCP).
- GitHub repo (to create).

## Development methodology: obra/superpowers (proposed, decisions #30)
- What it is: MIT-licensed skills plugin enforcing brainstorm → isolated git worktree → plan (2–5 min tasks with file paths and checks) → execution (fresh subagent per task with review, or inline) → strict TDD → review against plan → finish branch. Skills trigger automatically.
- Install: `/plugin install superpowers@claude-plugins-official` (or via `obra/superpowers-marketplace`). Prefer the plugin over vendored copies (arxiv-miner and research-factory-old carry stale copies in `.github/skills`).
- Fit: matches our plan (one coordinating session per work package, subagents per task, review gates, tests first).
- Caveats: usage multiplies in subagent mode (shared plan limits with research runs); strict TDD suits platform code, not exploratory research code; its brainstorming writes its own specs (point it to `docs/`); visual companion telemetry (disable with `SUPERPOWERS_DISABLE_TELEMETRY`); third-party code running with agent permissions — review before installing and pin the version.
- Scope: building the factory only. The factory's research agents get their own plugin (screening, extraction, probing skills).


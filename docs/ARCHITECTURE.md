# Architecture

Status: orientation document for agents and developers, 2026-11-11. It binds nothing: where it differs from `docs/specs/00-system.md`, `docs/specs/01-rigour.md`, a slice spec or a *Decided* row of `docs/decisions.md`, those govern, and this file should be corrected. Its companion [MAP.md](MAP.md) is generated from the code and answers *where* each thing lives; this file answers *how* the parts fit.

## 1. What the platform is

A deterministic Python service (`platform/`, package `factory`) that stores, validates, schedules and logs research work: question, protocol, search, deduplication, screening, full text, extraction, references, lineage, interpretation, regions, hypotheses, experiments, writing and the living corpus. It **never calls a model**. Every judgement is made by Claude, in Claude Code or claude.ai sessions, through MCP tools; every count, hash, sample and report is computed by the platform. The researcher acts through the CLI.

Four rules shape every module:

1. **Events are the source of truth.** Append-only JSONL; a correction is a new event that supersedes. The SQLite index is a projection, rebuilt from the events and written only by the projector.
2. **Business logic lives in `services/`.** `mcp/` and `cli/` parse, call one service, format.
3. **Validate at the boundary.** An invalid call writes nothing and returns structured issues (`field`, `reason`).
4. **Provenance everywhere.** An agent event carries model, skill reference and `input_blob` (the exact task content the agent saw).

## 2. The parts

```
 Researcher ──── CLI (`factory …`, cli/main.py) ───────────────┐
                                                               │
 Claude sessions ── skills (plugin/skills/rf-*) ── MCP tools ──┤  interfaces: parse, call, format
                                    (mcp/server.py)            │
                                                               ▼
                              services/   validation, guards, gates, queues, reports
                              │      │          │
            pure helpers ─────┘      │          └──── sources/ (OpenAlex, arXiv, Crossref, full-text routes)
  (lineage/, regions/, mining/,      │                document/ converters (docling, pandoc, latexml)
   hypotheses/, writing/, …)         ▼
                         events/ ── append ──► projects/<slug>/events/<actor>/<session>.jsonl
                                                projects/<slug>/blobs/  (task payloads, raw responses)
                                                projects/<slug>/library/ (literature; never in git)
                         index/  ◄── fold ──── projection handlers → projects/<slug>/.index/factory.sqlite
```

### Package layers (`platform/src/factory/`)

| Layer | Packages | Rule |
| --- | --- | --- |
| Kernel | `events/` (envelope, catalog, writer, reader, validation, blobs), `model/` (pydantic payloads and specs), `index/` (tables and fold handlers), `config.py`, `clock.py`, `canonical.py`, `errors.py` | No business rules. `model/` holds one module per entity family; every event type is registered in `events/catalog.py` with its payload model and schema version. |
| Services | `services/*.py` (about 210 modules) | All orchestration and every guard. A service takes a `Project` (`services/context.py`), reads the index, validates, and records events. |
| Module declarations | `services/modules/*.py` against `modules/contract.py`, `modules/registry.py`, `modules/presets.py` | Declarations only; behaviour stays in the services (§5). |
| Pure helpers | `consolidation/`, `document/` (anchors, quotes), `evidence/`, `exports/`, `extraction/`, `hypotheses/`, `imports/` (parsers), `inbox/`, `intuition/`, `lineage/`, `living/`, `mining/`, `packs/`, `quality/`, `references/`, `regions/`, `views/`, `writing/` | No I/O, no project state, no clock. Each states its rule in its module docstring (e.g. `lineage/classify.py`: the stated/inferred rule). Services call them; they never call services. |
| Adapters | `sources/` (literature APIs, polite HTTP client), `sources/fulltext/` (acquisition routes), `document/` converters | The only code that reaches the network or external tools. Tests stub them; network tests carry the `network` marker. |
| Interfaces | `mcp/server.py` (all tools, nested in `build_server`), `mcp/conventions.py`, `cli/main.py` (typer), `cli/render.py` and siblings | Thin. A tool or command that grows a rule is a defect. |

Outside the package: `plugin/skills/` holds the agent procedures (§6); `docs/` holds specs, plans and decisions (§9); `experiments/` holds exempt prototype code; `scripts/` holds documentation tooling.

## 3. Storage

Laid out per project under `<FACTORY_ROOT>/projects/<slug>/` (`services/context.py`, `ProjectPaths`):

- `events/<actor>/<session-ULID>.jsonl`: one file per writing session, so sessions never contend and git merges never conflict. The envelope is specified in `00-system.md` §4.2; `id` and `ts` come from one monotonic ULID, so ID order is event order.
- `blobs/sha256/<2>/<62>`: content-addressed task payloads, raw source responses and generated reports; committed.
- `library/sha256/<2>/<62>`: full-text sources and canonical Markdown; git-ignored (decision 39).
- `.index/factory.sqlite`: the projection; git-ignored, rebuildable with `factory rebuild`.

**The projection.** `index/default.py` assembles every table and maps each event type to a handler (`PROJECTION_VERSION` there). `Index.sync` (`index/index.py`) reads new lines from each session file from its stored offset and folds them in order; a version change or an out-of-order event triggers a full rebuild. Two rebuilds of the same log give the same `state_hash`. Consequences for anyone changing it:

- There are no migrations. Change a table or handler, bump `PROJECTION_VERSION`, and the index rebuilds.
- A new table that is empty on old logs goes into `OMITTED_WHEN_EMPTY` (`index/index.py`), so the state hash of an old log is unchanged (`tests/test_old_log_replay.py`).
- Handlers must be total: a hand-written event that fails a guard must change nothing, also on rebuild (`tests/test_forged_events.py` and siblings). A logged event can never be removed, so the fold, not the writer, is the last line of defence.

## 4. The life of a call

### Write path (an agent records screening verdicts)

1. The skill (`rf-screen`) tells the agent to call `screen_record` with the batch's verdicts, its role, model and skill name.
2. The tool in `mcp/server.py` builds an `Actor` (`mcp/conventions.py`), resolves the skill reference from the installed `SKILL.md` (`services/skills.py`: `name@<sha8>`, computed by the platform, never trusted from the agent), and runs the service inside `_reply` → `guarded`, which turns `FactoryValidationError` into `{ok: false, issues: [...]}` and scrubs held-out identifiers from any agent-facing answer.
3. `open_project` (`services/context.py`) gives a `Project`: paths, settings, session, clock, ID generator, catalog, blob and library stores, event factory, writer and index.
4. The service (`services/screening.py`) syncs the index, checks every guard (task lease, pass membership, stage, gate policy, calibration), and builds events with `project.events`.
5. `project.record(events)` takes the write lock, validates each event against the catalog (`events/validation.py`), appends it to the session file (`events/writer.py`) and folds it (`Index.sync`). Nothing is written if validation fails.
6. The tool returns the new IDs.

### Read path

A read tool or command calls a service that syncs and queries the index (SQLAlchemy Core; `index/*.py` hold table definitions and some query helpers). Read tools are paginated (`PAGE_LIMIT = 50`). Many services take `agent: bool`: the agent variant withholds what an agent may not see (held-out seed identifiers, labels before a pass opens, per decision 37); the researcher's variant is complete. A view that composes several sources must call each source's agent variant.

### Work queue

Work handed to an agent is a task (`services/tasks.py`; `task.created/claimed/completed/released`). A `*_next` tool creates or serves a task with a lease (default 30 minutes) and stores its content as the `input_blob`; the matching `*_record` tool completes it. Any session can resume a project from the queue. Task kinds are registered per module (`services/modules/task_kinds.py`).

## 5. Stage modules, gates and checks (slice M)

Each capability is a stage module declared in `services/modules/<name>.py` as a `ModuleSpec`: kind (`scoping`, `retrieval`, `transform`, `filter`, `miner`, `proposal`, `builder`, `core`), input and output artefact kinds, the event types and tables it owns, task kinds, protocol sections, gates, check codes and, for miners, a quality regime. `ModuleRegistry` refuses a set of declarations in which any event type, table, task kind, protocol section, check code or gate belongs to no module or to two (`tests/test_registry_ownership.py`). [MAP.md](MAP.md) lists every module with what it owns.

- **Gates.** A decision gate names the act events that pass it and a floor policy (`human`, `agent_audit`, `agent`). The effective policy is the protocol's `gate_policies` entry, else the preset of the project's rigor mode (`exploratory`, `pilot`, `systematic`; `modules/presets.py`). Every gated service calls `require_gate` (`services/gates.py`) first. Human gates have no MCP tool: the agent relays the CLI command that `project_status` lists under `human`.
- **Checks.** `services/check.py` holds the rules; each module returns the hits whose codes it declares (`services/modules/base.py`). `factory check` and the `check` tool report them with severity; `--promote-to <mode>` reports the gap to a stricter mode.
- **Stages.** `services/stages.py` and `services/project_stage.py` derive the project's current stage from the log; `project_status` reports it, with the researcher's queue (`services/human_queue.py`).

## 6. The agent side

Skills in `plugin/skills/rf-*/SKILL.md` are the procedures Claude follows; the platform hashes the installed file into every agent event. `rf-run` is the entry point: it reads `project_status` and hands over to the skill for the current stage:

| Stage | Skills |
| --- | --- |
| scoping, protocol | `rf-frame`, `rf-probe`, `rf-protocol` |
| search, dedup | `search_run`, `dedup_run` (tools) |
| title/abstract and full-text screening | `rf-screen` (pass A or B), `fulltext_fetch` |
| extraction | `rf-extract`, `rf-mine`, `rf-contributions` |
| snowballing | `rf-references`, `rf-search` |
| graph and interpretation layers | `rf-lineage`, `rf-intuition`, `rf-regions`, `rf-consolidate`, `rf-cards` |
| hypotheses and experiments | `rf-ideate`, `rf-critic`, `rf-experiment`, `rf-chat` |
| writing | `rf-write`, `rf-verify` |
| living review | `rf-living` |

Independence is enforced by sessions, not by trust. One MCP server process serves one Claude Code session and all its subagents, which therefore share a session ID. Pass A and pass B of screening, extraction and a miner, a hypothesis critic and a draft verifier each run in their own session; services refuse a session that has joined the other pass or relayed a human label.

**Held-out seeds** (R-20, decision 37 item 9, decision 81). A project's seeds are split into worked examples and held-out items that measure recall after the search. Until a pass opens, agent tools must not name a held-out seed; `services/withholding.py` scrubs seed records, seed IDs, stated identifiers and held-out recall from agent answers. A held-out seed's *work* is never hidden or marked: a marker would itself reveal it. The researcher's reports stay complete.

## 7. Where to look

| To find… | Look in |
| --- | --- |
| What an event type means and which model validates it | `events/catalog.py` → `model/<family>.py`; [MAP.md](MAP.md), per module |
| Which tables an event changes | the handler named in `index/default.py`, defined in `index/<family>.py` |
| Why a call was refused | the service's module docstring (invariants and rulings), then `docs/decisions.md` for the ruling it cites |
| What an MCP tool or CLI command does | its docstring in `mcp/server.py` or `cli/main.py`; [MAP.md](MAP.md) names the services it calls |
| What a rule requires (R-xx) | `docs/specs/01-rigour.md`, then the slice spec that implements it |
| Who may pass a gate | `services/modules/<module>.py` (floor), `modules/presets.py` (mode presets), `services/gates.py` |
| How the agent is meant to use a tool | the skill naming it ([MAP.md](MAP.md), Skills) |
| How a project's state was reached | `factory trace <id> [--forward]` and the `trace` tool (`services/trace.py`) |
| Test fixtures and shared builders | `platform/tests/helpers.py`, `*_helpers.py`, `world_cache.py` |

## 8. Touchpoints of common changes

Short form; each item has a test that fails when it is forgotten. Add only what the task needs: a new field on an existing payload, with a default, keeps schema version 1 and needs no new table; a new gate comes from a spec or ruling, not from the change itself.

- **Any change to a handler or a table:** bump `PROJECTION_VERSION` in `index/default.py` and update every test that pins its value (`grep -rn PROJECTION_VERSION platform/tests`). Without the bump, existing projects keep a stale index.
- **New event type:** payload model in `model/`; registration in `events/catalog.py`; handler in `index/<family>.py` wired in `index/default.py`; ownership in the module's `services/modules/<name>.py`; the bump above; a forged-event test showing an invalid hand-written event changes nothing.
- **New field on an existing payload:** default it so old events validate; fold it in the handler; the bump above; an old-log replay check.
- **New table:** definition in `index/<family>.py`; ownership in the module declaration; `OMITTED_WHEN_EMPTY` if old logs lack it; the bump above.
- **New MCP tool:** a service function first; the tool in `mcp/server.py` through `_reply`; the tool-list pin of its `tests/test_mcp_*.py`; a role-blindness test if it can name works before a pass opens; the skill that should use it.
- **New gate, check code or task kind:** declare it in the owning module; a gate with a non-human preset also needs `modules/presets.py`.
- **Any agent-facing guard:** a test that fails when the guard is removed (`docs/handoff-2026-11-05.md`, "How the work is run").

After any of these, regenerate the map: `uv run --project platform python scripts/gen_map.py`.

## 9. Documents and their authority

| Document | Role |
| --- | --- |
| `CLAUDE.md` | Rules for every session; read first |
| `docs/specs/00-system.md`, `01-rigour.md` | Binding system contracts and rigour requirements R-xx |
| `docs/specs/slice-*.md` | Binding specs per slice; [specs/README.md](specs/README.md) lists them |
| `docs/decisions.md` | Decision log; never contradict a *Decided* row, propose a new one |
| `docs/plans/YYYY-MM-DD-*.md` | Implementation plans; `2026-11-05-build-order.md` orders them |
| `docs/handoff-2026-11-05.md` | Build state and working method at that date (not binding) |
| `docs/runbook-*.md` | Procedures for running pilots and the living review |
| `docs/backlog.md` | Ideas not in any spec; do not implement from it |
| `docs/00-…10-*.md` | Background and vision; not binding |
| [MAP.md](MAP.md) | Generated index of modules, tools, commands, services and skills |

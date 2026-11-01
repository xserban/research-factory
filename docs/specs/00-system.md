# System specification (contracts)

Status: draft for review · 2026-10-31 · Applies to every slice. Changes to this file are recorded in `docs/decisions.md`.

This file fixes the cross-cutting contracts that are expensive to change later. Slice specs (`slice-N.md`) build on it and may not contradict it.

## 1. Scope

The platform is a deterministic Python service that stores, validates, schedules and logs research work. It **never calls a model**. All judgement is made by Claude (Claude Code or claude.ai, on subscriptions) through MCP tools.

Not in scope until a later slice says otherwise: user interface, embeddings, multi-user authentication, server deployment.

## 2. Repository layout

```
research-factory/
  platform/                 Python package `factory` (src layout)
    src/factory/
      model/                pydantic models (one module per entity family)
      events/               event envelope, writer, reader, validation
      index/                SQLite projection: schema, rebuild, queries
      sources/              literature source adapters
      services/             one module per capability (protocol, search, dedup, screening, …)
      mcp/                  MCP server: tool definitions only, no business logic
      cli/                  thin CLI: init, rebuild, status, trace, check, report, serve
    tests/
  plugin/                   Claude Code plugin: research skills, subagents, hooks (+ provenance manifest)
  domain-packs/             vocabularies, extraction schemas, gold sets
  projects/<slug>/          one directory per research project (data; see §4)
  docs/                     vision, decisions, specs, plans
```

Rule: business logic lives in `services/`. `mcp/` and `cli/` only parse input, call a service, and format output.

## 3. Identity

| Entity | ID format | Rule |
| --- | --- | --- |
| Event | `ev_<ULID>` | Time-sortable, globally unique, generated at write |
| Work (any citable source) | `rf:<surname><year>-<slug>-<hash8>` | Deterministic from content; hash basis DOI → arXiv ID → normalised title/first author/year; arXiv DataCite DOIs bridged to the arXiv ID (ported from research-factory-old `ids.py`) |
| Question version | `Q@<sha8>` | Hash of the question's decision-relevant fields |
| Protocol version | `P@<sha8>` | Hash over criteria, sources, queries, limits, schemas and `Q@` — **not prose** |
| Search strategy | `S@<sha8>` | Hash over sources, queries and limits only; carries a PRESS confirmation across protocol versions |
| Criterion | `P@<sha8>:<CID>` | `CID` like `IN01`, `EX03`; always version-qualified when referenced |
| Seed | `SEED<nn>` / `NEG<nn>` | Positive / negative known items per project |
| Other entities (query, search run, merge, decision, task) | `<prefix>_<ULID>` | e.g. `qry_`, `run_`, `mrg_`, `dec_`, `tsk_` |

IDs are never reused and never change. A changed entity is a new version or a superseding record.

## 4. Storage

### 4.1 Events are the source of truth
- Append-only JSON Lines files in git: `projects/<slug>/events/<actor>/<session-ULID>.jsonl`. One file per writing session → no write contention; git merges are conflict-free (different files).
- Events are never edited or deleted. Corrections are new events that supersede earlier ones.

### 4.2 Event envelope
```json
{
  "id": "ev_01J...",
  "ts": "2026-10-31T19:22:05.123Z",
  "project": "linear-attention-vision",
  "type": "screening.decision_recorded",
  "schema": 1,
  "actor": {"kind": "agent", "id": "screener-a", "user": "obd", "session": "01J...", "model": "claude-opus-5-5", "skill": "rf-screen@1a2b3c4d"},
  "refs": ["rf:...", "P@d4e5f6"],
  "input_blob": "sha256:...",
  "payload": { }
}
```
- `type` is `<area>.<past-tense verb>`; each type has a pydantic payload model and a schema version.
- `actor.kind` is `human`, `agent` or `system`. When `kind = agent`, `model` and `skill` (`<name>@<hash>`) are required; for other kinds both are absent.
- `input_blob`: the exact task content the agent saw, stored as a blob (auditability). **Required for agent events**, optional otherwise.
- `id` and `ts` come from one monotonic ULID: `ts` equals the timestamp encoded in `id`, so ID order is the global event order.
- Provenance trust levels: `model` is *reported by the agent* unless supplied by the harness (e.g. a hook); `skill` hashes should be computed by the platform from the installed skill file, not supplied by the agent. Reports state which applies.
- An event that fails validation is rejected; nothing is written.

### 4.3 Blobs
- Content-addressed files under `projects/<slug>/blobs/sha256/<2>/<62>`: raw source responses, task payloads, generated reports.
- Text blobs are committed to git. PDFs and other large binaries are not committed (open question: Git LFS or a shared blob store; decided in the full-text slice).

### 4.4 Index (projection)
- SQLite at `projects/<slug>/.index/factory.sqlite` (git-ignored), built only from events and blobs.
- `factory rebuild` drops and rebuilds it. Rebuild is deterministic: two rebuilds from the same events give the same state hash.
- The index is never written except by the projector. No schema migrations: change the projector and rebuild.

## 5. Core types in version 1

Strict, validated models (decisions #5, #18): `Work` (with `Identifiers`, `Provenance` — a work cannot exist without provenance), `Question`, `Protocol`, `Criterion`, `Seed`, `Query`, `SearchRun`, `Merge`, `Decision`, `Task`.

Generic graph nodes, edges and free labels arrive with the graph slice. Claims arrive with the extraction slice.

## 6. Rigor modes

Each project declares `exploratory | pilot | systematic` (decision #24). Provenance and protocol versioning are mandatory in every mode. What varies (single vs. dual screening, κ floor, appraisal) is defined per slice. `factory check --promote-to <mode>` reports the gap list.

## 7. MCP tool conventions

- Names: `<area>_<verb>` (e.g. `screen_next`, `screen_record`).
- Every mutating tool: validates fully before writing; on failure returns structured errors (field, reason) and writes nothing; on success returns the new IDs.
- Every mutating tool receives `actor` context: user from configuration, agent role and model as parameters; the session ID from the server process. One MCP server process serves one Claude Code session **including all its subagents**, so subagents share a session ID; anything that must be independent (e.g. screening passes A and B) runs in separate Claude Code sessions.
- Batch tools accept partial success: valid items are written, invalid ones are returned with reasons.
- Read tools are paginated and return at most a fixed number of items per call.
- Tools that hand work to an agent (`*_next`) create a `Task` with a lease; the task content is stored as `input_blob`.

## 8. Work queue

Tasks are events (`task.created`, `task.claimed`, `task.completed`, `task.released`). Agents pull with `*_next`; a claimed task has a lease (default 30 min) after which it can be claimed again. Any session can resume a project from the queue.

## 9. Commands (thin CLI)

`factory init <slug>` · `factory rebuild` · `factory status` · `factory trace <id> [--forward]` · `factory check [--promote-to <mode>]` · `factory report prisma` · `factory serve` (MCP over stdio).

## 10. Quality and tooling

- Python ≥ 3.11 · uv · ruff · mypy `--strict` (must pass) · pytest.
- Tests offline by default; network tests marked `network`.
- Required test kinds: model invariants; event validation; **rebuild determinism**; ported modules keep their original tests.
- Coverage target for `services/` and `model/`: ≥ 90%.
- Development process: obra/superpowers (decision #30); plans in `docs/plans/`.

## 11. Open questions (not blocking slice 1)
- Large binaries (PDFs): Git LFS vs. shared blob store.
- Identity of humans when several people share a project (slice: teams).
- Event schema evolution policy (upcasting old payload versions vs. versioned projectors).

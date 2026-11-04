# Slice 7a — Portfolio view across projects

Status: **draft for the researcher's review — not to be built until accepted** · 2026-11-05 · Outline slice: **7 (views and writing)** of [README.md](README.md). Builds on [00-system.md](00-system.md) and slices 1–2 (`project_status`, screening, extraction, check); must satisfy [01-rigour.md](01-rigour.md) R-01, R-05, R-39 and decision 43. Takes in backlog IDEA-01 (portfolio dashboard). Rulings marked **[confirm]** await the researcher.

## Goal
One read-only view of every project under the factory root: rigor mode, stage, open agent work, **pending human decisions** (where a human is blocking), last search, corpus and inclusion counts. Every number is derived from each project's events (R-05); the view writes no event and edits nothing.

00-system §1 lists "user interface" as out of scope until a slice says otherwise. This slice says so only for a generated, read-only report; it adds no server and no interactive editing.

## Options
| Option | What | For | Against |
| --- | --- | --- | --- |
| A. Static report from `factory portfolio` | A builder service computes one `Portfolio` model across projects; the CLI renders it as Markdown (terminal), a self-contained HTML file (no script, no server) and JSON | Deterministic and testable like PRISMA and the evidence report; no new dependency; runs offline; the JSON is the contract for any later view | Not live: regenerated on demand; no drill-down beyond links to per-project reports |
| B. Local web UI | A small local HTTP server (e.g. Starlette) serving the same model, with per-project pages | Live refresh, navigation, filters | A server and a web dependency in `platform/`; 00-system §1 excludes UI and server deployment; a second surface to keep within decision 43's agent views; needs its own tests and process |
| C. claude.ai dashboard artifact fed by exported JSON | Claude publishes an artifact page from `factory portfolio --json` | Good presentation, shareable, phone-readable, no platform UI code | Content leaves the machine; a Claude session builds and reads it, so the export must be safe for any agent view; refresh is a manual re-publish; the platform still needs option A's builder |

**Recommendation: A, with its JSON designed so that C needs no platform change [confirm].** A is a prerequisite of B and C (all three render the same builder), it matches how every other report is built (a builder, IDEA-38 vocabulary), and it adds no surface that agents could read past decision 43. C becomes a skill-level step later: a session runs the CLI and publishes the JSON as an artifact. B is deferred until a need for live navigation is shown.

## User flow
1. `factory portfolio` prints a Markdown table, one row per project, then a "waiting on you" list grouped by project.
2. `factory portfolio --html PATH` writes the same content as one self-contained HTML file; `--json` prints the model.
3. Each row names the next human act and the CLI command that performs it (e.g. `factory screen disagreements --project X`); the portfolio itself performs none.

## Rulings (provisional)
1. **Form [confirm].** Option A (above).
2. **CLI only [confirm].** No MCP tool in v1. A portfolio crosses projects, and a session that joined a pass in one project must not read another's state through it; per-project agent views stay `project_status`.
3. **Counts only, no label-derived rates [confirm].** The portfolio shows no κ, sensitivity, specificity, audit error rate, held-out recall, seed identifier or work title. Quality figures stay in each project's reports. The JSON export is therefore safe to hand to any Claude session (option C) without a separate agent view.
4. **Stage is derived by a fixed rule [confirm].** First matching row wins:

   | Stage | Condition |
   | --- | --- |
   | `scoping` | no question, or no protocol |
   | `protocol` | protocol not `ready`, or PRESS not confirmed (`pilot`, `systematic`) |
   | `search` | no complete search-purpose run |
   | `ta-screening` | any canonical work pending at title/abstract (calibration items excluded) |
   | `full-text` | a full-text plan exists and any TA-included work lacks a document, a conversion or a final full-text outcome |
   | `extraction` | an extraction schema exists and any unit lacks a final row |
   | `snowballing` | a `snowball_plan` exists and its stopping rule does not yet hold |
   | `reporting` | otherwise |

   The rule is a pure function of existing service outputs, tested per row; a project may block on a human in any stage.
5. **Pending human decisions [confirm].** Derived per project from existing services, one count per gate kind (IDEA-38: gates whose policy is `human`): PRESS confirmation awaited; calibration labels missing (per stage); screening disagreements unresolved (per stage; `unsure` included, decision 37 item 8); audit sample drawn but unlabelled (per stage); extraction disagreements unresolved; extraction audit unlabelled; reference links awaiting confirmation (G1, when built); inbox items open (slice 4a, when built). A gate kind whose module is absent on the branch is omitted, not shown as zero.
6. **Read-only [confirm].** The portfolio opens each project with a fresh session id and writes no event; it may refresh each project's index (the projector's own write, 00-system §4.4). A test asserts every events file is byte-identical before and after.
7. **Failure isolation [confirm].** A project whose events fail validation or whose index cannot be built is listed with `error` and the exception class; the others still render. The exit code is 0 unless no project could be read.
8. **Determinism [confirm].** Rows sorted by slug; given the same events and the same `--as-of` timestamp, Markdown, HTML and JSON are byte-identical. Ages ("last search 12 days ago") are computed from `--as-of` (default: now) and appear in Markdown and HTML only; JSON carries timestamps.

## Design
**Builder.** `services/portfolio.py`: `portfolio(settings, *, as_of) -> Portfolio`, reading each project through `project_status` (counts only) and a new per-project `human_queue(project) -> HumanQueue` in `services/human_queue.py`. `human_queue` is useful on its own: `project_status` gains it as an optional field, so a single project's CLI `status` shows the same list.

**Model (JSON contract, schema version 1).** `Portfolio(schema=1, generated_at, projects: list[PortfolioRow])`; `PortfolioRow(slug, rigor_mode, question_id, protocol_id, protocol_status, press, stage, tasks_open, tasks_claimed, tasks_expired, works, ta_included, ft_included, last_event_at, last_search_at, human: HumanQueue, error)`; `HumanQueue(items: list[HumanItem])`; `HumanItem(gate, stage, count, command)`.

**Renderers.** `cli/portfolio_render.py`: Markdown and HTML from the model only (no service calls); HTML is one file with inline CSS, light and dark via `prefers-color-scheme`, no script, values escaped.

## Rigour requirements
R-05 (every count derived; tested by recomputing from `project_status`); R-01 (each row's numbers are those of the project's own reports: a test compares with `prisma_flow` and `task_counts`); R-39 (the view states nothing about automation it does not derive); decision 43 (ruling 3 keeps label-derived rates and seed data out). No new requirement.

## Acceptance criteria
1. With two fixture projects (one at TA screening with two unresolved disagreements and one `unsure`, one at extraction with an unlabelled audit), `factory portfolio` lists both with the stages and human items of rulings 4 and 5.
2. Every count equals the value from the project's own `project_status`, `prisma_flow` or the named service.
3. Events files are byte-identical before and after a run (ruling 6).
4. A third project with a corrupt event line is listed with `error`; the other two render; exit code 0.
5. JSON, Markdown and HTML are byte-identical across two runs with the same `--as-of` and across an index rebuild.
6. The JSON contains no κ, rate, seed id, held-out figure or title (a test scans keys and values against the fixtures' titles and seed ids).
7. `mypy --strict` and ruff pass; coverage ≥ 90% for `services/` and `model/`.

## Out of scope
Live server (option B); publishing artifacts from the platform (option C is a skill-level step); cross-project suggestions (IDEA-04); literature watches and digests (IDEA-02, IDEA-03); any write action from the view.

## Proposed decision text (for `decisions.md` on acceptance; next free number)
| # | Topic | Status | Decision |
| --- | --- | --- | --- |
| next | Portfolio view (slice 7a) | Proposed | The portfolio is a read-only builder across projects rendered by `factory portfolio` as Markdown, self-contained HTML and JSON (schema 1); no server and no MCP tool. It shows counts, a derived stage and pending human decisions per gate kind, never label-derived rates, seed data or titles, so its JSON may be handed to any Claude session (e.g. an artifact page). Amends 00-system §1 only for generated, read-only reports |

# Runbook: a full-text use case with arXiv HTML papers

Status: written 2026-11-04 against branch `plan-2c-fulltext-screening`. Every command and tool name below was checked against `platform/src/factory/cli/main.py`, `platform/src/factory/mcp/server.py` and `plugin/skills/*/SKILL.md`. Scope: slice 1 (question to chase, reports, check) plus slice-2 plans A (acquisition), B2 (conversion, `document_read`) and C (full-text screening, full PRISMA). Extraction and the evidence report do not exist yet (section 4).

Notation: **[H]** is a human act (CLI in a terminal, or a human-only MCP tool); **[A]** is an agent act (MCP tool called by Claude Code under a skill). Every [A] call also takes `project`, `role`, `model` (the agent's own model id) and `skill` (bare name, e.g. `rf-screen`); these are omitted below except where they matter.

## 1. Prerequisites

1. **Environment.** Python >= 3.11 and `uv`. From the repository root: `uv sync --project platform`. Optional checks: `cd platform && uv run pytest -q`.
2. **Variables.** `FACTORY_ROOT` (default: the current directory; the factory root is the repository root, so projects live in `$FACTORY_ROOT/projects/`), `FACTORY_USER` (your actor id; default the login name), `FACTORY_MAILTO` (contact address sent to OpenAlex and arXiv as the polite-pool identifier; set it), `FACTORY_PROJECT` (project slug, avoids `--project`), `FACTORY_PLUGIN_DIR` (default `<root>/plugin`; skills are read from `skills/<name>/SKILL.md` and their hash is recorded in every agent event).
3. **CLI.** `uv run --project platform factory <command>`. Shorten with `alias factory='uv run --project platform factory'`. `factory --help` lists the groups: `init rebuild status serve seeds protocol calibrate screen search audit fulltext document report trace check`. With exactly one project, `--project` may be omitted; with several, pass `--project <slug>`.
4. **MCP server and Claude Code.** `.mcp.json` at the repository root already declares the server:
   `{"mcpServers": {"factory": {"command": "uv", "args": ["run", "--project", "platform", "factory", "serve"]}}}`. Start `claude` in the repository root and approve the project MCP server; tools appear as `mcp__factory__*`. The server is stdio, one process per Claude Code session, so **one Claude Code session = one MCP session**. The skills `rf-frame`, `rf-probe`, `rf-protocol`, `rf-search`, `rf-screen` are in `plugin/skills/`. There is no `rf-extract` skill yet.
5. **Where data lives.** `projects/<slug>/events/` (JSONL, append-only, in git), `projects/<slug>/blobs/` (small text blobs, in git), `projects/<slug>/.index/` (SQLite projection, rebuildable with `factory rebuild`, git-ignored), `projects/<slug>/library/` (raw arXiv HTML and converted Markdown, content-addressed, **git-ignored as a whole**, decision 39). Also ignored: `projects/*/blobs/**/*.pdf`. Back up `library/` yourself; `factory fulltext restore --missing` can re-fetch lost arXiv entries and verify their hashes.
6. **Division of acts.**
   - Human (CLI): `init`, `seeds split|explain|admit`, `protocol confirm-press`, `calibrate draw|label`, `screen disagreements|resolve`, `audit sample|label|report`, `search chase`, `fulltext fetch|import|status|restore`, `document convert|status|read`, `status`, `report`, `trace`, `check`.
   - Agent (MCP, inside a skill): `question_record`, `seed_add`, `probe_run`, `protocol_record`, `protocol_press_review`, `protocol_amend`, `protocol_deviation`, `search_run`, `search_chase`, `dedup_run`, `screen_next`, `screen_record`, `fulltext_fetch`, `document_read`.
   - Read-only MCP tools usable by either: `project_status`, `seed_list`, `fulltext_status`, `screen_agreement`, `report_prisma`, `report_methods`, `trace`, `check`, `audit_sample`, `calibration_label`, `audit_record`. The last three are human acts relayed over MCP.
   - **A session that has joined a pass (called `screen_next`) is refused** `screen_agreement`, `check`, `report_*`, `trace`, `audit_*`, `calibration_label`, `fulltext_*` and `document_read` outside its own batch. Run all of these from the CLI, or from a separate Claude Code session that never screens.
   - Never do calibration or audit labelling in a session that will screen: a session that relayed a human label cannot join a pass ("this session relayed a human label and cannot screen"). Use the CLI.

## 2. Step-by-step flow

Use a **setup session** (Claude Code A0) for steps 2 to 8, one session for pass A, another for pass B, and a terminal for every [H] step. Choose the project mode at step 1: `pilot` gives dual screening on a sample, a calibration gate (sensitivity 0.9) and an advisory kappa; `systematic` gives full dual screening, gate 0.95 and enforced kappa (floor >= 0.7); `exploratory` has no calibration gate and a single pass (see `docs/specs/01-rigour.md`).

### Step 1. Create the project [H]
```
factory init <slug> --mode pilot
factory status
```
Records `project.created` with the mode. `status` prints event counts, queue, screening and (once declared) full-text lines.

### Step 2. State the question and goal [A, skill `rf-frame`]
In session A0, give Claude your goal in your own words. It calls `question_record(project, spec, raw_goal=..., reason=...)` after quoting the goal back for confirmation. Records a versioned `Q@<hash>` with the verbatim `raw_goal`, slots, non-goals (`NG01`...; >= 3 for pilot/systematic) and a proposed mode. You confirm the mode; it is a project setting, not part of the spec.

### Step 3. Add seeds [A, `rf-probe`]
Give Claude known in-scope papers (>= 3 positive, ideally 5) and at least one out-of-scope look-alike (negative), each with a `cite` and a `doi`, `arxiv` or `openalex` identifier. Tool: `seed_add(project, seeds=[...])`; check with `seed_list` or, as a human, `factory seeds`. Seeds are resolved to works. The hold-out split of the positives is drawn at the first probe (or by you with `factory seeds split [--random-seed N]`). Held-out roles are shown to humans only; do not ask the agent which are held out.

### Step 4. Protocol [A, `rf-protocol`]
Claude drafts with `protocol_record(project, spec, ready=False)`. The spec must contain, **before any screening**:
- criteria with `id`, `parent`, `statement`, `rule`, `applies_at` (`title-abstract` | `full-text` | `either`), `priority` for exclusions. Include at least one criterion with `applies_at: full-text` (or `either`), since full-text screening decides on those;
- sources and queries with PRISMA-S fields;
- `screening` (title/abstract plan: `passes`, `dual_sample`, `kappa_floor`, `kappa_enforced`, `calibration_size` default 30, `audit_fraction` default 0.02, `audit_minimum` default 50, `reviewers`);
- **`full_text_screening`: a second plan of the same shape, declared now.** Declaring it up front is the cleaner route. If you declare it later via `protocol_amend`, earlier title/abstract decisions are carried along the protocol lineage and stay valid unless a criterion amendment makes them stale (implemented in plan 2C; decision 50 records the rule and is still Proposed until you confirm it).

Then: PRESS review in a separate subagent (`protocol_press_review(project, protocol_id, findings=[...])`), and you confirm each finding:
```
factory protocol confirm-press <review_id> --response "..." --response "..."
```
(one `--response` per finding, in order). When you agree the protocol, Claude records it again with `ready=True`. Records `protocol.recorded` (version `P@<hash>`) and the PRESS confirmation. Later changes: `protocol_amend(spec, reason, semantic, effects)` or `protocol_deviation(description, reason, affects)`.

### Step 5. Probe [A, `rf-probe`]
`probe_run(project, queries=[{source, query, kind, filters}, ...])` with a narrow and a broad query per source (`openalex`, `arxiv`). Metadata only; reports seed recall per source and pooled against thresholds 0.6 (exploratory), 0.9 (pilot), 1.0 (systematic). Iterate until the skill states proceed, amend or reframe. If a positive seed is missed, record why: `factory seeds explain SEED03 --route <route> --reason "..."` (route: `citation-chase`, `seed-admission` or `hand-search`, not `database`; the error lists the choices).

### Step 6. Search [A, `rf-protocol`/`rf-search`]
`search_run(project, source, query, kind="keyword", purpose="search", limit=None, resume_run=None, deviation_id=None)` for each protocol query. In pilot/systematic a query the protocol does not plan needs `protocol_deviation` first and its `deviation_id`. Records `search.run` events with raw responses archived as blobs and reported versus retrieved counts.

### Step 7. Deduplicate [A]
`dedup_run(project)`. Records every merge (reversible). There is no `factory dedup` CLI command.

### Step 8. Title/abstract screening, two sessions [A, `rf-screen`]
1. **[H] Calibration first.** The agent cannot start before the set is drawn and labelled:
   ```
   factory calibrate draw
   factory calibrate label <work> include|exclude [--criterion EX01]
   ```
   Repeat `label` for every work of the set. (`factory status` shows drawn, labelled, gate and passed.)
2. **Pass A.** Open a **new** Claude Code session; ask it to run `rf-screen` as pass A. It calls `screen_next(pass_label="A")` and `screen_record(task_id, items=[{work_id, verdict, criterion, quote, rationale}])` until `batch` is null. Every verdict needs a verbatim title/abstract quote.
3. **Pass B.** Open **another new** session, with a **different model**, and run `rf-screen` as pass B. One pass per session; the platform refuses a second pass in the same session and a model already used by the other pass ("pass A already uses this model").
4. **[H] Agreement and disagreements.**
   ```
   factory status
   factory screen disagreements
   factory screen resolve <work> include|exclude --reason "..." [--criterion EX01]
   ```
   `screen_agreement` (MCP, from a non-screening session) or `factory status` gives kappa. Resolve every disagreement and every `unsure` single-pass work; nothing is auto-resolved.
5. **[H] Audit.**
   ```
   factory audit sample
   factory audit label <audit_id> <work> include|exclude [--criterion EX01]
   factory audit report
   ```
   Sample size is max(2% of agreed decisions, 50), 3:1 towards exclusions; the report gives the false-exclusion rate (ceiling 0.05, a gate in `systematic`, advisory in `pilot`).
6. **Optional supplementary search.** `factory search chase [--backward] [--forward]` (or `search_chase` with `rf-search`), then `dedup_run`, then screen the new works (back to item 2). Requires all title/abstract outcomes final.

The works whose final title/abstract outcome is *included* are "promoted"; only they enter the full-text stage.

### Step 9. Acquire full text [H]
```
factory fulltext fetch [--work W ...] [--route arxiv-html] [--refresh] [--limit 20]
factory fulltext status
```
Default selection: promoted works with no document and no attempt yet; `--limit` is 1 to 200 (default 20), so repeat for more. Without `--route`, routes are tried in order `arxiv-html`, `arxiv-source`, `oa-pdf`; for this use case `--route arxiv-html` restricts to the HTML route. Each attempt records route, URL, status, version, licence and raw hash; the raw HTML goes to `library/`. Failures are recorded with per-route reasons (never an error); `--refresh` or `--work` retries them. The agent equivalent is `fulltext_fetch(work_ids, routes, refresh, limit)` and `fulltext_status(work_ids)`, from a session that has not joined a pass.

Papers without an arXiv HTML rendering: supply PDFs with `factory fulltext import <folder>` (they match by identifiers; the report lists matched, unmatched and ambiguous files). Imported PDFs are retrieved but **cannot be converted yet** (section 4).

### Step 10. Convert to Markdown [H]
```
factory document convert [--work W ...] [--document D ...]
factory document status
factory document read <work> [--document D] [--conversion C] [--anchor s3.2.p4] [--after ANCHOR] [--limit 50]
```
`convert` runs the LaTeXML-HTML converter, deterministically and offline, recording `document.converted` or `document.conversion_failed` per document (one conversion per document, converter and version). `status` shows converted or not, converter and version, anchor counts and the last failure. `read` prints anchored segments (`s3.2`, `s3.2.p4`, `t2`, `t2.r5.c3`) a page at a time; use it to spot-check tables. `factory document convert --restore` regenerates missing or damaged stored Markdown and writes no event.

### Step 11. Full-text calibration [H]
```
factory calibrate draw --stage full-text
factory calibrate label <work> include|exclude [--criterion EX05] --stage full-text
```
The draw prints each work with its document and conversion ids. Label from the converted text (`factory document read <work>`). Screening at full text is blocked until this gate is passed (not in `exploratory`).

### Step 12. Full-text passes [A, `rf-screen` full-text mode]
In **two new sessions** (not the title/abstract sessions, not each other; different models): ask for the full-text pass A, then B. Calls: `screen_next(pass_label="A", stage="full-text")`, `document_read(work_id, conversion_id, after=next_after)`, `screen_record(task_id, items=[{work_id, verdict, criterion, quote, rationale, anchor}])`. Exactly one `anchor` per item, the quote verbatim inside that single paragraph or table cell. The batch pins each work's `document_id` and `conversion_id`; a later conversion does not change a queued batch. Promoted works with no conversion are never queued; they count as not retrieved.

### Step 13. Agreement, resolution, audit at full text [H]
```
factory status
factory screen disagreements --stage full-text
factory screen resolve <work> include|exclude --reason "..." [--criterion EX05] --stage full-text
factory audit sample --stage full-text
factory audit label <audit_id> <work> include|exclude [--criterion EX05]
factory audit report --stage full-text
```
(The audit's stage is that of its sample, so `audit label` takes no `--stage`.) `screen_agreement(stage="full-text")` is the MCP equivalent of the kappa read.

### Step 14. Reports and check [H]
```
factory report prisma [--json]
factory report search [--json]
factory report methods [--json]
factory trace <ref> [--forward]
factory check [--promote-to systematic]
```
`report prisma` gives the PRISMA 2020 flow with full-text boxes (sought, not retrieved, assessed, excluded by reason). `report methods` states the automation, figures and the full-text plan. `trace` follows a decision, work, query or seed back to the question (`--forward` for what was derived from it). `check --promote-to <mode>` lists what the record lacks for a higher mode; the exit code is 1 when any finding is an error.

## 3. Checklist: does the machinery behave?

Counts that must add up (`factory report prisma`, `factory status`):
- identified - duplicates = screened at title/abstract; screened = excluded + pending + included (the code asserts this); the title/abstract included count = full-text sought.
- Full-text: sought = retrieved + not retrieved; **eligible (assessed + pending) = converted promoted works**; every promoted work without a conversion appears as not retrieved with a reason; the full-text boxes are marked provisional exactly while works are pending.
- Full-text excluded counts per criterion sum to the excluded total; each exclusion names an `EX` criterion.
- `fulltext status` and `document status` agree on how many promoted works have a live document and a conversion.
- Kappa and disagreement counts at each stage are computed, never typed; `screen disagreements` lists exactly the works where passes differ.

Files and git:
- `git status` after the run must show changes only under `projects/<slug>/events/` and `projects/<slug>/blobs/` (text). Nothing under `library/`, `.index/` or `*.pdf` blobs. Verify with `git check-ignore -v projects/<slug>/library projects/<slug>/.index`.
- `factory rebuild` prints a state hash; running it twice, and after deleting `.index/`, must print the same hash.

`factory check` (expected on a finished run): no `broken-link`, `missing-provenance`, `shortfall-unexplained`, `library-corrupt` (errors in every mode). Acceptable warnings: `kappa-below-floor` (advisory in pilot), `fulltext-unsought` (promoted works never fetched), `library-missing` (library entry deleted; fix with `fulltext restore --missing`), `source-changed`, `fulltext-decision-stale-document`, `profile-checklist`. Errors in pilot/systematic that mean unfinished work: `protocol-not-ready`, `press-missing`, `calibration-missing`, and in systematic `single-pass`, `audit-missing`, `audit-error-high`, `chase-missing`.

Spot checks: read three converted documents (`factory document read`) and compare one table with the arXiv page; confirm each full-text decision's anchor and quote exist in the cited segment; delete one file under `library/` and confirm `check` reports `library-missing` and `factory fulltext restore --missing` restores it with the same hash.

## 4. Known limits and gotchas

NOT YET BUILT (needed by the slice-2 goal, absent from the code):
- Extraction: `extract_next`, `extract_record`, `extract_agreement`, `extract_audit_sample`, `extract_audit_record`, the extraction schema and `ml-benchmark` domain pack in the protocol, dual extraction (plan D), and the `rf-extract` skill.
- Evidence report: `report_evidence` and `trace` extensions to cells and claims (plan E).
- Converters for LaTeX source (`arxiv-source` route) and PDF (`oa-pdf` and researcher-supplied PDFs): pending decision 49, which is not yet recorded in `docs/decisions.md`. Only the LaTeXML-HTML converter is registered (`default_converters()`).
- Reference snowballing from full text (extracting citations from the converted document). `search_chase` uses OpenAlex citation links only.
- Appraisal (deferred, IDEA-21); PubMed Central route (deferred).
- Decision 50 (decisions carry along the protocol lineage) is implemented but still Proposed until you confirm it. Declaring `full_text_screening` before screening begins remains the simpler route.

Gotchas:
- **HTML papers only convert.** A paper retrieved by `arxiv-source`, `oa-pdf` or `fulltext import` has a document but no conversion.
- **A promoted work without a converted document stays pending**: it is never queued at full text and shows as not retrieved in PRISMA (`factory report prisma` prints "unconverted works need conversion: run `factory document convert`"). Convert before you draw the full-text calibration set; the set is drawn from works that have a conversion at draw time.
- **One pass per Claude Code session**, and a different model for pass B. Do not reuse a title/abstract session for full text; the platform permits it but `rf-screen` forbids it and independence is part of the record.
- Pass sessions are blocked from `check`, `report_*`, `trace`, `fulltext_*`, `audit_*` and most reads (decision 43). Use the CLI.
- Rates (sensitivity, audit false-exclusion) are withheld from agent views over MCP; the CLI shows them.
- A criterion-changing protocol amendment re-queues calibration (the gate must be passed again) and marks affected decisions stale.
- **Rate limits.** arXiv is throttled to one request per 3 seconds across `arxiv.org` and `export.arxiv.org` (shared clock); OpenAlex 0.1 s; `Retry-After` on HTTP 429 is honoured (capped at 300 s) with up to 4 retries on 5xx or transport errors. Fetching 20 works therefore takes at least a minute; fetch in batches and do not run two fetches in parallel.
- **Disk space.** No size limit or disk check exists in the code. Raw HTML and Markdown are stored per document under `library/` (both are kept, and a re-conversion adds a version), so budget a few MB per paper and keep `library/` out of cloud-synced folders. Raw search-response blobs are in `blobs/` and are tracked by git; check their size before committing a large search.
- Library entries are not shared between machines (slice 5). On a fresh clone, run `factory rebuild`, then `factory fulltext restore --missing` and `factory document convert --restore`. Researcher-supplied files are listed as needing re-import.
- The MCP server is started per Claude Code session; restart the session after changing a `SKILL.md`, because a changed skill file changes its recorded hash (a stale `skill@hash` is refused: "skill file changed").

## 5. Troubleshooting

| Message (field or text) | Cause | Fix |
| --- | --- | --- |
| `the protocol is not ready; record it ready before screening (R-16)` (`blocked` in `screen_next`) | Protocol drafted but not `ready=True`, or no protocol | Confirm the PRESS review, then `protocol_record(..., ready=True)` |
| `the protocol is not ready` (field `protocol`) | A service needs a ready protocol | Same |
| `the calibration set must be drawn and labelled by the human before screening; an agent does not draw it` | Calibration gate | `factory calibrate draw [--stage full-text]` then `factory calibrate label ...` for every work |
| gate reason in `blocked` after labelling | Sensitivity below 0.9 (pilot) or 0.95 (systematic) | Review criteria, `protocol_amend`, calibrate again; the skill must not retry |
| `declare the full-text screening plan in the protocol first (R-13)` (field `full_text_screening`) | Full-text stage requested, protocol has no `full_text_screening` | `protocol_amend` adding the plan (earlier decisions carry along; see decision 50), ideally before screening starts |
| `<work>: has no conversion; run \`factory document convert\` first` | `document_read` / `document read` on an unconverted work | `factory document convert --work <work>`; if it fails, see `factory document status` for the failure |
| `<work>: not promoted at title/abstract` | Work's final outcome is not included | Resolve its title/abstract outcome first |
| `<work>: not a record of a batch this session holds` | Pass session reading a work outside its batch | Read only the batch's works |
| `<id>: not the conversion pinned` / `not the document pinned` | `document_read` with ids other than the batch's | Use the `conversion_id` / `document_id` served in the batch |
| `<anchor>: not an anchor of <conversion>` (field `after`) | Wrong paging token | Use the page's `next_after` |
| `after: cannot be combined with anchor` | Both given | Give one |
| `limit: must be between ...` | `--limit` outside 1 to 200 | Adjust |
| `is required at full-text screening` (field `anchor`) / `is only for full-text screening` | Anchor missing at full text, or given at title/abstract | Cite one anchor per item at full text only |
| `is not in the cited anchor` (`quote`) / `is not in the record's title or abstract` | Quote not verbatim in the single anchor/title-abstract | Re-read the anchor; never paraphrase; otherwise use `cannot-assess` or `unsure` |
| `has no pinned conversion in this task` | Item for a work not in the batch | Submit only the batch's works |
| `this session relayed a human label and cannot screen` | Calibration or audit label sent through MCP in this session | Use a fresh session for screening; label via CLI |
| `pass A already uses this model` / `this session already screens pass X` | Independence rules | Fresh session, different model for pass B |
| `the protocol plans one screening pass` | Pass B requested with `passes=1` | Amend plan to two passes or skip B |
| `the task's protocol version is no longer current` | Protocol amended while a batch was held | Call `screen_next` again |
| `lease expired before the event was recorded` | Batch held too long | Call `screen_next` again |
| `calibration set not drawn; call without arguments first` | MCP `calibration_label` with a work before the draw | Draw first |
| `this session has joined a pass` / refusals on `check`, `report_*`, `trace` | Pass session used a human/read tool | Use the CLI or a non-screening session |
| `<works> still pending` (field `screening`, chase) | Chase requested before all outcomes are final | Resolve disagreements and pending works |
| `no installed skill 'x' under ...` / `skill file changed: installed ..., caller sent ...` | Wrong skill name, or `SKILL.md` changed | Pass the bare name; restart the session |
| `no project; run factory init` / `several projects: ...; pass --project` | CLI cannot pick a project | `factory init <slug>` or `--project <slug>` / `FACTORY_PROJECT` |
| `give one document id, or --missing` | `fulltext restore` arguments | Give exactly one |
| `unavailable: <docs>` (exit 1) | A restore route no longer serves the document | Re-import if supplied by you; otherwise retry later or `fulltext fetch --refresh` |
| `a conversion has no library entry; run \`factory document convert --restore\`` (check) | Markdown missing from `library/` | `factory document convert --restore` |
| `must be one of: ...` (fields `route`, `promote-to`, `verdict`) | Bad enumerated value | Use a listed value; verdicts are `include` or `exclude` |

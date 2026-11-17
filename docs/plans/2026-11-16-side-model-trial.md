# Plan: side-model trial (Antigravity, Gemini "3.8 flash")

Date: 2026-11-16 · Status: plan, not executed · Backlog: IDEA-90 · Decisions touched: none (no *Decided* entry is changed; a promotion needs a new proposed entry, see section 9)

## 1. Purpose and scope

The researcher has an Antigravity subscription (Google) on this laptop. The model named is "Gemini 3.8 flash"; the exact identifier, context window and rate limits are **unknown** and must be read from the tool by the executor (section 7). The trial asks one question per candidate job: *can this model do a bounded side job well enough, measured against labels we already hold, to be used for it?* It does not ask whether the model is "good".

In scope: a measurement on existing, already-labelled sets, with results kept outside every pilot project's events. Out of scope: any production run, any new miner, any change to platform code, any pilot-data write, any use of the model for a judgement that is not re-checked by a human or by a calibrated Claude pass.

The platform never calls a model. This plan adds no model call to `platform/`. The side model is an **external session**, like a Claude session, that reads task files and returns result files.

## 2. How a non-Claude model plugs in, and what must not change

Plug-in path (existing machinery only):

1. A task is served by an existing read tool (`screen_next`, `mine_next`, `extract_next`, `screen_check_example`, `document_read` and the miner calibration draw). For Antigravity, which is not an MCP client of this platform, the executor exports the served task text to a file (section 6).
2. The external session returns a structured result file in the exact record shape the corresponding record tool takes (`screen_record`, `mine_record`, `miner_calibration_label` is human-only and is not used by the model).
3. The executor imports the file through an existing write path in a **trial project copy** (section 3), with `model` set to the model's own name and a distinct `user`/session. Provenance (model, skill version, `input_blob`) is therefore recorded under its own model name; nothing is recorded as Claude.
4. If Antigravity can be configured as an MCP client of `factory mcp` it may call the tools directly. This is **unknown**; the file route is the baseline, the direct route an optional shortcut with identical recording rules.

What must not change:

- **Held-out handling** (decisions 36, 43, 54, 78): the trial uses no hold-out seed list; `docs/pilot/heldout-seeds.md` is never opened. Held-out works appearing in corpus text are read as corpus (memory: decision 37.9); none is hidden or masked, and none is used to score recall.
- **Blinding and independence** (decision 37): a model serving a second read is a separate session and a separate model from the first read; the second reader never sees the first reader's output, the gold label, or the agreement figure before it records. Pass framing and criterion order are fixed by the pass.
- **Calibration before production**: no side-model output enters a production event stream unless the model passes calibration for that job on that miner version (section 5). A pass of this trial is calibration evidence for a proposal, not a licence.
- **Never write pilot data**: all imports go to a throwaway copy of the project (`data/` copied, runtime from `main`, no shared index; follow `docs/runbook-fulltext-usecase.md` practice and the `FACTORY_ROOT` override, because the shell variable points at the real pilot). The copy is deleted or archived outside tracked paths afterwards. Check that `/tmp` quota is not exceeded; use `/home` with reflink copy.
- Human-only acts stay human (calibration labels, disagreement resolution, audit labels). No literature text goes into tracked paths; trial outputs live under the untracked `ops/` area.
- Scripts never judge, agents never do bookkeeping: all agreement, kappa, cost and latency figures are computed from files and events, not typed.

## 3. Trial design

One trial project copy per job family; each job is run once per candidate model arm. Arms: (S) the side model; (C) the Claude reference already recorded in the same sets (Haiku pass B is the pilot's routine screener; Sonnet where a miner was run with it); no new Claude run is needed when the recorded one exists, which keeps the cost low. The side model never sees the existing labels.

Order: job 1 (cheapest, smallest) first; job 3 and 4 only if job 1 and 2 do not hit the stop rule.

## 4. Candidate side jobs, sets and metrics

The executor must first list what exists (`factory screen-check list`, `factory miner list`, `factory miner calibrate report`, `factory taxonomy list`) and record the exact set names, sizes and label provenance in the trial log. The sets below are named by kind because the live names are held in the pilot's events, not in tracked docs; where I could not confirm a set exists it is marked (to confirm).

| # | Job | Why it is a side job | Fixed gold or labelled set | Primary metric |
|---|---|---|---|---|
| 1 | **Quote-verification triage**: given a record, its quote and the document, say whether the quote supports the value | Support task; deterministic anchor check already exists, this tests the semantic remainder | Rows from the miners' audit labels and the researcher's labelled samples (`m-release`: two samples of 10 works labelled by the researcher, backlog IDEA-37 validation record) (to confirm that the rows with a human "unsupported" label are enough; the set may be small) | Agreement with the human label; false "supported" rate |
| 2 | **Second reader on a calibrated miner**: re-read the works of a miner already calibrated, as an independent pass | Support task; tests IDEA-53's agreement measure with a non-Claude reader | Miner calibration labels (`miner.calibration_labelled` events): `m-release` first (fields `code_status`, `data_status`; a closed enum, cheap to score), then `m-layer` and `m-lifecycle` if their gold labels exist by then (memory: lifecycle gold labels were pending on 2026-11-13) (to confirm) | Per-field agreement with the human label (enum values only, per work); Cohen's kappa; compared with the Claude pass on the same units |
| 3 | **Long-context pass A screening re-check**: screen with the whole abstract set or a full text in one context, instead of per record | Long-context task | Screening calibration set (`calibration.drawn` / `calibration.labelled`; human-labelled; sensitivity is the gated quantity, decision 37.5) plus the audit sample labels of the 2026-11-12 pilot pass A (to confirm sizes) | Sensitivity on includes (gate: at least 0.9 in `pilot`); specificity reported, never gated (R-31); kappa against the Claude pass |
| 4 | **Whole-corpus or long-PDF reading**: answer fixed lookups over a corpus slice or a full converted document (for example the `m-release` fields read from the full text, not a section) | Long-context task | The 95 core papers of the technique-notes loop (notes v3, 8 codebooks and CSVs, 2026-11-15), which carry researcher-reviewed labels (to confirm which fields are reviewed) | Agreement with the reviewed CSV cell; share of answers with a verifiable anchor; position effect (accuracy by where in the text the evidence lies) |

Long-context probe (part of job 4): build three length tiers from the same gold documents (single section, whole paper, three papers concatenated) and report agreement by tier. A model that holds agreement across tiers is long-context-capable for this purpose; the context window itself is read from the tool, not assumed.

Common measures for every job, computed from files and events:

- agreement with gold (the primary metric above, with a Wilson interval, because the sets are small);
- agreement with the recorded Claude arm on the same units (to show where the two disagree, not who is right: gold decides);
- format failures: result files that fail the record tool's validation (the platform's own structured errors are the count; nothing is repaired by hand);
- refusals and empty answers (counted by the executor from the file);
- verbatim quote failures: quotes that fail the deterministic anchor check;
- latency: wall time per unit and per batch, from timestamps the executor writes; rate-limit stalls recorded separately;
- cost: the subscription is flat-rate, so cost is **usage consumed** (units per quota window, as shown by the tool; unknown whether it exposes a count) and the researcher's hands-on minutes. These are estimates, recorded in the trial log, not events.

## 5. Stop rule and decision rules

Pre-registered before any run (write them into the trial log first, with the date; no change after the first result is seen):

- **Stop at once** if (a) the model returns more than 20 % unparseable or invalid result files after one allowed prompt fix, or (b) it reproduces any text identified as held-out material or asks for it, or (c) any write reaches pilot data, or (d) the quota or hands-on time of one job exceeds 2 hours of the researcher's attention.
- **Stop a job** after the first 20 units if the primary metric is below the reject line (below), to avoid spending the whole set on a clear failure. Otherwise run the whole set.
- Prompt tuning: at most one revision of the task prompt per job, made on a tuning split of the set (about one third); the figures that count are on the untouched remainder.

Promote or reject, per job (the numbers are proposals; the researcher fixes them in section 9 before the run):

| Result on the untouched remainder | Verdict |
|---|---|
| Job 1: false-supported rate no higher than the Claude arm and agreement at least 0.85 | Promote to **triage first filter** only; a human still samples, as for any audit |
| Job 2: per-field agreement within 0.05 of the Claude arm, kappa at least 0.6 on the fields that gate, no field with a systematic bias | Promote to **second reader candidate**: it may serve as pass 2 in a dual run, subject to the miner's own calibration and decision 37 independence (different model and session already satisfy this) |
| Job 3: sensitivity at least 0.9 with the 95 % interval's lower bound reported, no includes lost that Claude kept | Promote to **long-context screening re-check**; never sole screener |
| Job 4: agreement within 0.05 of the Claude arm on the whole-paper tier and no collapse on the longest tier | Promote to **long-document lookup helper**; every answer still anchor-checked |
| Any job below the reject line (agreement more than 0.15 under the Claude arm, or sensitivity under 0.8, or false-supported above 0.10) | **Reject for that job**; other jobs are judged separately |
| In between | **Inconclusive**: one enlargement of the set if gold exists, else no promotion |

Promotion is scoped: to a named job, miner and version, with the model identifier recorded. It lapses on a model identifier change (the same logic as the `calibration-model-drift` check).

## 6. Manual steps for the researcher (Antigravity is a separate tool)

The executor cannot operate Antigravity. The researcher, or an agent with screen access if the researcher grants it, must do the following; each is a point where the plan has gaps that the executor should record.

1. **Open the tool** and select the model; write the exact model name and any version shown into the trial log (the platform records this string as `model`).
2. **Hand over a task prompt as a file.** The executor writes, per batch, one task file in a scratch folder outside tracked paths: instructions (the miner or screening skill text, versioned), the output schema, and the units (served text exported by the read tools). The researcher opens that folder as the tool's workspace, or attaches the file, and instructs the session to follow the file only. How workspace files are attached, and whether the tool can write a file back, are **unknown**; fallback is copy-paste of the answer into a file.
3. **Collect results as a file.** The session writes `result-<job>-<batch>.json` in the record tool's input shape. The executor validates it with the existing validators and imports it into the trial copy through the existing path: `screen record` / `mine record` input, or `factory mine import` for whole units. If the CLI import for external files turns out not to exist for the job, **stop and report**; do not write a new importer (that is a design decision).
4. **Fresh session per batch**, no memory or prior chat, so that independence and the blind hold; the researcher states in the log whether the tool keeps cross-session memory (unknown).
5. **Do not paste** the gold labels, the first reader's output, or agreement figures into the tool. Do not use any project hold-out file.
6. Record per batch: start and end time, quota shown before and after, any refusal message, and whether the tool silently truncated input (compare the model's quoted spans with the end of the text).

Unknowns to resolve in a short preliminary check (30 minutes, no gold data; use an off-topic public text that is not corpus material): the real model identifier; context window; whether file attachment, file output or an MCP client setting exist; quota units; whether data sent to the tool is retained or used for training (relevant to confidentiality of the corpus: unpublished manuscripts and any non-open full text must **not** be sent until this is known).

## 7. Task sequence for the executing agent

1. Create a worktree and the untracked trial folder `ops/side-model-trial-2026-11/` (task files, result files, log, runbook, heartbeat).
2. Copy the pilot to a throwaway project; export `FACTORY_ROOT` to the copy; run `factory check` there to get a clean baseline (testing remains paused: no pytest; `factory check` is a data check, not a test run).
3. Inventory the sets (section 4), write the pre-registered thresholds, and ask the researcher the open choices (section 8).
4. Run the preliminary check (section 6) with the researcher.
5. Per job: draw the units with a fixed seed, export task files, hand to the researcher, import results, compute metrics with a script that reads events and files only, write one table per job into the log.
6. Evaluate the decision table; write the verdicts and the evidence into the log; propose, do not decide, a backlog or decision entry (section 9).
7. Delete the trial project copy; keep the log and result files untracked.

## 8. Open choices for the researcher

Asked as multiple choice (recommended first):

1. Jobs to run: (a) jobs 1 and 2 only (support tasks, small, cheap); (b) all four; (c) job 3 only (long-context screening).
2. Confidentiality: (a) public or open-access corpus items only; (b) any corpus item, after the retention terms are read and accepted; (c) stop until the retention terms are known.
3. Gold labels still pending for `m-layer` and `m-lifecycle`: (a) use `m-release` only and skip those; (b) the researcher labels about 15 works for one of them first; (c) use the Claude pass as a proxy (not recommended: it measures agreement with Claude, not accuracy).
4. Direct MCP route if the tool supports it: (a) file route only, to keep recording identical; (b) try the direct MCP route in a second step; (c) direct route first.
5. Thresholds in section 5: (a) accept them as written; (b) stricter (agreement within 0.03, kappa at least 0.7); (c) the researcher sets them.

## 9. After the trial

A promotion is a proposal: a new entry in `docs/decisions.md` (status Proposed) stating job, miner, version, model identifier, evidence and lapse rule. Nothing here is built. If the file route works well and a second non-Claude model is later wanted, an importer for externally produced result files may be added as its own backlog item; this trial does not specify it. Backlog: IDEA-90.

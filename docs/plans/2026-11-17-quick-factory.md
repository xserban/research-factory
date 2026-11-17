# Quick factory: a fast, cheap, marked quick review for very small projects (IDEA-41)

Status: draft for the researcher's validation (2026-11-17). Not started. Plan only: no code, no tests, no backlog or MAP edit.
Depends on: `model/project.py` (`ProjectCreated`, `rigor_mode`), `services/project.py` (`create_project`), `services/gates.py` (`rigor_mode`, `indexed_rigor_mode`, `effective_policy`, presets), `services/check.py` (`LEVELS`, `check(promote_to=)`), `services/budgets.py` and `model/budgets.py` (`Budget`, `require_budget`), `mcp/unit_cap.py` (`FACTORY_UNIT_CAP`), `services/run_costs.py` (IDEA-45), `model/protocol.py` (`MethodProfile.RAPID_REVIEW`), `services/protocol_rules.py` (`_stop_rule_errors`), `services/ranking.py` (decision 116), `services/decision_binding.py`, `services/question.py`, `services/probe.py`, `services/draft_release.py`, `services/methods.py` (`methods_report`). Decisions 24, 35, 37, 75, 116, 118 (item 7 as the pattern for a project-level configuration event). Spec background: `docs/specs/00-system.md` section 6, `docs/specs/01-rigour.md`, `docs/specs/slice-M-modules.md` (gate presets), `docs/specs/slice-8-develop.md`. Related plans: `2026-11-14-pilot-2.md` (the full path), `2026-11-16-side-model-trial.md` (IDEA-90).

## 1. Goal and non-goals

**Goal.** A researcher (or a session acting for one) can go from a small question to a cited evidence note in one sitting, with a stated paper limit and a stated cost limit, on the same event-sourced platform, with every claim citing a verified source span, and with the note and every report printing plainly that it is a quick review and which steps were skipped. Many such projects can be run cheaply, each one small enough to be a design review for IDEA-40.

**Key results.**
1. One command (CLI and MCP) creates a project with a `quick` profile and a budget (paper limit, unit cap); one skill `rf-quick` drives the sitting.
2. A quick project reaches an evidence note with: a light question and criteria, one search, one screening pass, full text for at most N papers, one extraction pass, and the checks that keep claims verifiable.
3. The profile object lists every skipped step; the list is printed in every report, in `factory status`, and at the head of the evidence note. A computed `quick_report` shows what was done, what was skipped and what was spent.
4. `factory quick promote` turns a quick project into a pilot or systematic one without losing any event, and lists the stages that must now be redone.
5. No number is typed (R-05); no gate that guards traceability is relaxed.

**Non-goals.**
- No model call; no automatic choice of a cheaper model. "Cheaper model" means which session the operator runs, recorded as provenance (section 5).
- No new rigour mode. `exploratory | pilot | systematic` (decision 24) is unchanged; quick is a declared overlay on `exploratory` (open choice 1).
- No weakening of any requirement marked `all` or any traceability requirement (section 4, "never skipped").
- No dependence on IDEA-90 (side-model trial) or on IDEA-42's learned preference ranker; the existing embedding ranker (decision 116) is used only if its extra is installed.
- Quick results are not used as evidence for a systematic project's conclusions without promotion; a quick note is advisory, as IDEA-40 already says of its reviews.
- No change to any *Decided* entry (section 8).

## 2. User story

A researcher types `factory quick start "which methods are used to plan research with agents?" --max-papers 20 --max-units 150` (or asks Claude to run `rf-quick`). The platform creates the project (mode `exploratory`, method profile `rapid-review`, a `quick` profile object, a project budget). In one sitting:

1. Claude proposes a one-paragraph question, one to three elements and one to three non-goals, and at most six criteria; the researcher confirms with one selection.
2. One search (one source, one to three queries; the probe is a single measured round, not a loop) is run and archived raw (R-03, R-22).
3. Records are ranked if the ranker is available, then screened title/abstract in one pass until the paper limit is reached or the stopping rule fires; the platform serves at most `max-units` units and refuses beyond that.
4. Full text is fetched for the papers kept (up to the limit) and converted; one extraction pass records claims with verified quotes.
5. `report_evidence` produces the evidence note: the claims by group, each citing its verified source; a banner states: "QUICK REVIEW: single screening pass, no calibration, no audit, no PRESS; skipped: ..." and the cost figures.

Limits: the paper limit counts works admitted to full text; the cost limit is a unit cap (served tasks) with the run cost reader (IDEA-45) reporting the API-equivalent figure after the fact. Reaching either limit ends the sitting with a recorded stop reason, never silently.

## 3. What exists and what must be built

| Piece | Exists (files) | To build |
|---|---|---|
| Rigour mode `exploratory` | `model/project.py`; presets and floors in `services/gates.py`; per-mode severities in `services/check.py` (`LEVELS`); `question.py` (one non-goal), `probe.py` (looser threshold), `decision_binding.py` (no `decision_id` needed), `draft_release.py` (agent release) | nothing; quick runs on it |
| Method profile `rapid-review` | `MethodProfile.RAPID_REVIEW` in `model/protocol.py`; stopping rules `stop_after_consecutive_excludes`, `stop_below_score` allowed (`protocol_rules._stop_rule_errors`) | a preset protocol template for quick; no checklist behind the profile yet (check reports no profile gaps, R-60 only names it) |
| Ranking with stopping rule | `services/ranking.py`, `ranking_model.py`, `ranked_queue.py` (decision 116, optional extra) | quick uses it if present; absent extra is a stated skip |
| Budgets and caps | `services/budgets.py` (`require_budget`), `mcp/unit_cap.py`, `services/run_costs.py`, `factory costs` | a quick budget preset and a paper-limit counter (computed from events) |
| Single-pass screening | `screen_next`/`screen_record`; `screening.py`; pass A only is valid in exploratory (`screening_stats`: no floor) | nothing in the service; the report must say "single pass" |
| Full text and extraction | acquisition, conversion, `extract_next/record`, `report_evidence` | a limit on fetch count (reads the profile) |
| Project creation | `services/project.py::create_project`, `cli/main.py::init`, `factory init` | `quick start` wrapper (section 7) |
| Project mode change | none: the mode is fixed by `project.created`; `check --promote-to` only reports | an effective-mode fold for promotion (section 6) |
| Skill | `plugin/skills/rf-*` (frame, search, screen, extract, write ...) | `rf-quick` |
| Quick profile object, reports, banner | none | sections 4 and 7 |

## 4. Stage table: the full path against the quick mode

"Gate" means what the platform refuses without. "Recorded as" is the event or computed view that shows the relaxation. Every skip is listed in the `quick` profile's `skipped` list (keys below, in bold) and printed by every output.

| Stage (full path) | Quick mode does instead | Gate relaxed (already allowed in `exploratory` unless marked NEW) | Recorded as | Never skipped |
|---|---|---|---|---|
| Question, elements, non-goals | One paragraph, one to three elements, at least one non-goal; no study plan or sub-questions | `question.py` minimum of one non-goal is exploratory today; `decision_id` binding not required (`decision_binding.py`) | **study-plan**, **question-decision**; skipped keys in the profile | R-10 (elements and a non-goal exist); R-11 (each criterion names its parent element) |
| Seeds and held-out split | Zero to three seeds, optional; no development/held-out split | `probe.py` split gate applies outside exploratory only; recall figures are marked `not-computed` | **seeds-split** | R-20 and R-24 are claimed only when seeds exist; with none, the report says "recall not measured", never a number. Held-out handling (decision 36, 37.9) is unchanged where seeds exist |
| Probe | One measured round (query to count and a sample), no vocabulary loop | no new gate; the probe is optional in exploratory | **probe-loop** | R-22: the final query string, source, filters, date are recorded |
| Protocol | A template protocol (`rapid-review`, light criteria, one screening pass declared as the plan) recorded and made `ready` in one call | NEW: a `quick_protocol` helper writes the usual events; no new relaxation of R-16 | **protocol-light** | R-13 (commitments before reading: criteria and extraction schema are recorded before screening and extraction); R-14 (versioning; amendments recorded); R-16 (`ready` before screening) |
| PRESS review | Skipped | `protocol.press_confirm` required only in pilot and systematic; confirm exploratory behaviour at implementation (Q1 verifies) | **press** | R-61 is not claimed; the methods text says "no PRESS review" |
| Search | One source (arXiv or OpenAlex or PubMed by topic) and one to three queries; no supplementary search, no snowball, no grey sources, no watch | none | **supplementary-search**, **grey** | R-03 raw archive; R-22 PRISMA-S fields; R-23 reported vs retrieved; R-02 provenance of each work; R-21 no hidden truncation: the paper limit applies at screening, not by cutting the search result |
| Dedup | The existing deterministic cascade runs as normal (it is cheap); no manual pair review | version-pair review is human-gated and is simply not done | **dedup-review** | R-26 (merges recorded and reversible) |
| Screening pass A | One pass; Claude or a cheaper session; ranked order if available; stopping rule `stop_after_consecutive_excludes` allowed; stops at the paper limit | exploratory has no κ floor and no dual-pass requirement | **screen-pass-b**, **kappa** | R-30 verdicts and criterion on exclusion; R-32 verified quotes; R-34 statelessness; R-04 provenance. `cannot-assess` still promotes; ranking never excludes (decision 116). R-31 is not claimed as measured |
| Screening pass B and agreement | Skipped | as above | **screen-pass-b**, **kappa** | R-33 and R-36 are not claimed; the report prints "single reviewer, agreement not measured" |
| Calibration | Skipped; the screener's model, skill and input are recorded as always | calibration is slice-1 AC18 and a gate only above exploratory; verify in Q1 that exploratory screening starts without it | **calibration** | R-35 is not claimed; no sensitivity figure is printed |
| Audit sample | Skipped | exploratory has no minimum | **audit** | R-37 not claimed; the report prints "no audit; error rate unknown" |
| Acquisition and conversion | Fetch and convert for kept papers only, up to the paper limit; abstract-only papers are used only for scope statements, never for claims | NEW: a fetch count limit read from the profile | **fulltext-cap** | R-43 every attempt recorded; R-47 library stays local; pinned converter (decision 49) |
| Full-text screening | Merged into the extraction pass: the extractor may mark a paper `off-topic` with a reason, which the platform records as a full-text exclusion | uses the existing full-text screening path with one pass | **fulltext-screen-b** | R-30 and R-32 apply to this verdict too; PRISMA full-text boxes still computed |
| Extraction schema and miners | A small schema (at most six fields) declared before reading; no miners, no taxonomy | exploratory allows schema in the light protocol | **miners**, **taxonomy** | R-13 and R-45 (schema declared before extraction); R-40 atomic claims with locator and verified span; R-44 number check; R-141 and R-142 if a miner is used at all (a quick project registers none) |
| Dual extraction, agreement, extraction audit | Skipped | recorded sample is required only in pilot | **dual-extraction**, **extract-audit** | R-46 not claimed |
| Appraisal | Optional and off by default; a one-line "not appraised" in the note | exploratory allows no instrument | **appraisal** | R-41 not claimed; the note carries no quality rating |
| References and snowballing, lineage, layers, intuition | Not run | none | **references**, **lineage** | R-80 to R-89 untouched |
| Report | `report_evidence` and the quick banner; `report_prisma` and `report_methods` run as usual (computed) | `writing.release`: agent may release in exploratory (`draft_release.py`) | the banner, the profile, the quick report | R-05 all numbers computed; R-42 every sentence cites claim ids and says when the corpus does not support an answer; R-130 supported sentences; R-52 null results reported |
| Check | `factory check` under `exploratory` severities plus quick-specific codes (section 7) | none | `quick-*` findings | R-01 unbroken chain; R-16; R-14; R-23 findings are errors in quick as everywhere |

**Never skipped (consolidated).** Event sourcing and append-only corrections (system contracts); R-01 and R-02 chain and provenance; R-03 raw archive; R-04 model, skill version and input for every agent act; R-05 computed numbers; R-10, R-11, R-13, R-14, R-16 (a question, a derived criterion, commitments before reading, versioned protocol, `ready` before screening); R-22 and R-23 (search fields; reported vs retrieved); R-30 and R-32 (verdict rules; verified quotes); R-34 (statelessness); R-40, R-42, R-43 and R-44 (claims with verified spans, cited synthesis, recorded full-text attempts, number check); R-47 (no literature text in git-tracked paths); R-51 where a critic is used; the held-out rule where seeds exist (decisions 36, 37.9; R-20, R-24). `factory check` makes a violation an error in quick exactly as in exploratory.

**Which requirements are weakened or not claimed.** R-12 priority detail, R-31 and R-35 (recall and calibration claims), R-33 and R-36 (dual pass and agreement), R-37 (audit), R-38, R-45 for dual extraction, R-46, R-60 (profile checklist), R-61 (PRESS). The profile lists each as skipped; the note says "not claimed".

## 5. Cost model

Costs are tokens served by tasks. Measure first, then cap; the IDEA-45 baseline (pilot: 763 runs, mining 92% of cost) shows mining and extraction dominate, which is why quick runs no miners.

| Stage | Unit served | Expected cost driver | Quick control |
|---|---|---|---|
| Question, criteria | none (conversation) | a few thousand tokens | one round, one selection |
| Probe | none (computed) | zero tokens | one round |
| Search, dedup | none (computed) | zero tokens | one source |
| Screening pass A | one record (title and abstract) per unit | about one record's text plus criteria once per session | the biggest lever: batch size and criteria once per session (IDEA-45, not built); rank and stop; the unit cap |
| Acquisition, conversion | none (computed, local docling) | CPU and time, no tokens | fetch cap |
| Extraction | one paper (full text) per unit | the largest per-unit cost (full text in context) | at most N papers; at most six fields |
| Report | none (computed) plus a short write-up | small | one draft |

**Cheaper models for routine passes, Claude as checker.** The platform never calls a model. The operator chooses which session runs a pass: a smaller Claude model (as the pilot ruling on Haiku for pass B shows) or, if IDEA-90 later qualifies one, an external model. The platform records the model name on every event (R-04) and, for the quick project, the profile can declare `routine_model` and `checker_model` as intended names. Two computed outputs follow: (a) a per-model count of verdicts and claims; (b) a check sample: `quick check-sample` draws a small seeded sample (default 10% of verdicts, at least 10) of the routine model's verdicts and extractions for Claude (a different model than the routine one) to re-judge blind; the disagreement rate is printed in the quick report. This sample is a convenience estimate, not an audit under R-37 and not a calibration under R-35, and the report says so. Qualifying any model for a job beyond that (calibrated, scoped by job, miner, version and model identifier, lapsing on a model change) stays in IDEA-90's plan; quick works with Claude alone and gains from IDEA-90 only if it lands.

**Limits.** `max_units` is enforced by the existing unit cap (`FACTORY_UNIT_CAP`, refusal `cap-reached`) and a project budget through `budgets.py` (`Budget.unit` per task kind). `max_papers` is a computed count (works with a full-text attempt or an extraction task) checked by the service that serves fetch and extraction tasks. Spend is displayed with the API-equivalent figure of `run_costs.py`; it is displayed, never enforced (reported usage is display-only, `budgets.py`). The researcher's budget is therefore a unit and paper count, and the dollar figure is reported after the fact.

## 6. Promotion from quick to full

Records are never rewritten. Promotion is two events and a checked gap list.

1. `factory quick promote --to pilot|systematic --reason TEXT` (human act; `project:govern`). It first runs `check(promote_to=mode)` and prints the gap list (the existing machinery of decision 24), grouped by the skipped keys of the profile.
2. It writes `project.quick_promoted` (new, section 8): the target mode, the reason, the actor, the profile digest and the skipped list that is now owed. A fold gives the project an effective rigour mode (today `rigor_mode` is read from `project.created` and never changes, so this is the one new capability in `services/gates.py::indexed_rigor_mode`).
3. Nothing is deleted or edited. Verdicts from the quick screening stay as pass A records under the pilot protocol if the protocol hash of the quick protocol is unchanged; if the full protocol is a new version (an amendment through `protocol_amend`), R-15 blast radius computes the stale decisions as always.
4. Stages that must then be redone, because the quick path did not produce them: the study plan and decision bindings (pilot: `question_record` with a covering `decision_id` is recorded afresh), seeds and split (a split drawn after the fact cannot be honest about recall: the held-out seeds, if any, must be new and drawn before the new search, stated in the gap list), PRESS review (R-61, before any new search), calibration (R-35, before pass B and before further production), screening pass B on the same records (independence R-33; pass A's records stay), agreement (R-36), audit sample (R-37), dual extraction sample (R-46), appraisal if the profile requires it. The existing quick records count as pass A and as single extraction; they are not re-labelled as dual.
5. Reports print the history: "began as a quick review on DATE; promoted to MODE on DATE", and the outputs of the quick period keep the quick banner when they are read as of that period (the banner is computed from the log position of each output, as autonomy is under R-140).
6. Demotion is not supported.

Cost of promotion: the redo list is computed, so the researcher sees the price before choosing. A quick project that will probably be promoted should say so at `quick start` (`--intends-promotion`), which only adds a reminder to the banner (open choice 5).

## 7. Entry points

- **Skill `rf-quick`** (`plugin/skills/rf-quick/SKILL.md`, new): the sitting as ordered steps, each naming the tool, the stop condition and the budget check; it tells the operator which session to run for each pass; it forbids any claim of recall, agreement or error rate; it ends by printing the banner.
- **CLI** `factory quick start SLUG --question TEXT --max-papers N --max-units N [--source S] [--routine-model M] [--checker-model M] [--intends-promotion]`: creates the project (`project.created` mode `exploratory`), records the `quick` profile, a project budget, and a template question and protocol scaffold left as drafts for the researcher to confirm. Also `quick status`, `quick report`, `quick check-sample`, `quick promote`.
- **MCP** (thin): `quick_status` and `quick_report` read-only. Starting and promoting are human acts (they set a budget and a mode) and have no MCP write tool, as `factory init` has none (authorise_root_command). An agent session may run the sitting after the researcher starts it.
- **Profile object.** A project event `project.quick_declared` (schema 1): `max_papers`, `max_units`, `source`, `skipped` (the keys of section 4, a fixed vocabulary, validated), `routine_model`, `checker_model` (optional names), `intends_promotion`. Declared once at start; a later change is a new event by the same human actor with a reason (supersedes; never edited). It sits outside the protocol so the protocol hash (R-14) is unaffected (the pattern of decision 118 item 7).
- **Printing.** A shared function `quick_banner(project)` returns the profile line or None; it is called by `report_evidence`, `report_prisma`, `report_methods`, `factory status`, `project_status`, `check`, the hub project page and every draft render. The banner is computed from events (never typed) and lists the skipped keys in words.

## 8. Event and decision changes (explicit)

- **New event `project.quick_declared`** (module `project`; fields above; human actor; a fold in the projector; projection table `quick_profile`).
- **New event `project.quick_promoted`** (target mode, reason, profile digest, owed list as computed at the time).
- **Amends no Decided entry.** Decision 24 (modes; promotion as a gap list) is extended, not contradicted: a quick project has mode `exploratory` until promoted; decision 35's method profile `rapid-review` is used as declared. The effective-mode fold (item 2 of section 6) is the only reading change; it is a new proposed row.
- **Proposed decision row** (number to be assigned at merge): "Quick factory: a declared overlay on exploratory (IDEA-41)". Text to cover: quick is a project profile, not a mode; the fixed vocabulary of skipped steps and that every skip is listed and printed; the never-skipped list by requirement id; the unit cap and paper cap, with the dollar figure displayed and never enforced; routine and checker models are operator choices recorded as provenance, the platform calls no model; the check sample is not an audit; promotion by `project.quick_promoted`, nothing rewritten, the redo list; quick notes are advisory and are not admitted as evidence to systematic conclusions without promotion.
- No change to `inbox.link_added`, the protocol spec, the screening or extraction events, or any existing event dump (a golden test guards this).

## 9. Relation to IDEA-40 (the factory reviewing its own design)

IDEA-40 asks for a small review per design choice. Quick is its vehicle: one project per design question, each ending in an evidence note linked from the decision it informs. Rules for this use: (a) results are advisory and a human decides (circularity); (b) a method recalled by an agent is marked unverified until a quick review has cited it; (c) a fixed cost limit per review is the profile's budget, and a default is an open choice below; (d) the link from a decision row to its note is a plain reference to the project slug and the evidence report's content hash (no new event; the decision text names it). A design that depends on one quick review should be re-run as a promoted pilot review before it is called Decided on evidence. IDEA-39 (a planning agent) is not required: the light question is recorded by the existing `question_record`.

## 10. Tasks (1 to 3 hours each; mypy and ruff must pass; tests written with each task but not run while the testing pause holds)

| # | Task | Files touched | Depends | TDD list (written first) |
|---|---|---|---|---|
| Q1 | Verify exploratory behaviour for each stage of section 4 (read-only audit, written as a short table in the task report): does screening start without calibration, PRESS, split; does `report_evidence` run on one pass; list every refusal that blocks a quick path | none (report only) | none | none; the output decides whether Q3 to Q6 need NEW relaxations |
| Q2 | Models: `QuickProfile`, the skipped-key vocabulary, events `project.quick_declared` and `project.quick_promoted`; projector fold and table `quick_profile` | `model/quick.py`, `model/project.py`, `index/quick.py`, `index/projector` registration | none | unknown or repeated skipped key refused; `max_papers`, `max_units` positive; agent actor refused; latest declaration wins; rebuild equals live fold; existing event dumps unchanged |
| Q3 | Service `services/quick.py`: `quick_start` (create project, declare profile, budget, scaffold drafts), `quick_status`, `paper_count` (computed) | `services/quick.py`, `services/project.py` (call only), `services/budgets.py` (call only) | Q2 | project created with mode `exploratory` and the profile and budget in one batch; bad slug writes nothing; paper count equals works with a full-text attempt; budget refuses beyond the unit cap |
| Q4 | Paper cap on fetch and extraction serving; stop reason recorded | `services/fulltext.py` (cap check), `services/extraction.py` (`extract_next` cap check), `mcp/unit_cap.py` (reuse) | Q3 | fetch beyond the cap refused with a structured error and no write; cap read from the profile; a non-quick project is unaffected |
| Q5 | `quick_banner`, `quick_report` (what was done, skipped, spent, check sample) and wiring into `report_evidence`, `report_prisma`, `report_methods`, `project_status`, `check` | `services/quick_report.py`, the five report modules, `services/check.py` (codes `quick-skip-unlisted`, `quick-cap-exceeded`, `quick-claims-not-claimed`) | Q2 | banner present in every output of a quick project and absent otherwise; banner lists exactly the declared skipped keys; no figure for a skipped statistic (kappa, recall, sensitivity print `not claimed`); a quick report carries no typed number |
| Q6 | Check sample: seeded draw of routine verdicts and extractions, recording through existing human or agent tools by a different model, rate computed | `services/quick_sample.py` | Q3 | draw is seeded and reproducible; the checker's model differs from the routine model or the sample is refused; the rate never feeds `audit_report` or calibration figures |
| Q7 | Promotion: effective-mode fold, `quick_promote`, gap list grouped by skipped key, redo list | `services/gates.py` (`indexed_rigor_mode` reads the fold), `services/quick.py`, `services/check.py` | Q2, Q5 | `check --promote-to` gap list equals the redo list; promotion refused for a non-human or without a reason; no event rewritten; after promotion pilot gates apply (a pass B and PRESS are now required); banner shows history; the held-out wording for seeds is in the gap list |
| Q8 | CLI and MCP: `factory quick start/status/report/check-sample/promote`; read tools `quick_status`, `quick_report` | `cli/quick.py`, `cli/main.py`, `mcp/server.py` | Q3, Q5, Q7 | option parsing, structured errors, no MCP write tool exists for start or promote, error shape; one-pass catalog entries (IDEA-60) updated |
| Q9 | Skill `rf-quick` and catalog entry; the quick protocol template (light criteria, one pass, a stopping rule, a six-field schema) | `plugin/skills/rf-quick/SKILL.md`, `services/quick_template.py`, catalog data | Q3 | the template validates under the exploratory rules; the skill text names every tool it calls and every tool exists (an existing skill-tool consistency test) |
| Q10 | Hub: project page banner, a Quick page (budget bar, skipped list, papers used), promotion button (human-gated) | `services/site_quick.py` and the hub project page | Q5, Q7 | page shows the banner and figures from events; promotion posts the human act; no text copied from literature |
| Q11 | One light Sonnet review of the branch; guard mutation on the banner presence, the paper cap and the never-skipped check codes; `scripts/gen_map.py` run after merge by whoever merges | none | all | the review lessons of earlier plans |

Lanes: {Q1 then Q2, Q3, Q4, Q5} then {Q6, Q7, Q9} then {Q8, Q10}. Suggested branch `quick-factory`. Q1 first because it may remove tasks (if exploratory already refuses nothing).

## 11. Risks

- **False confidence.** A cited note from one pass and no calibration reads as authoritative. Controls: the banner at the head of every output, `not claimed` instead of a number for every skipped statistic, no recall claim, the check sample labelled as not an audit, and `quick-claims-not-claimed` check. Residual: a reader may copy the note without the banner; the evidence report text carries the sentence in the body, not only the header.
- **Lowered rigour mislabelled.** A project that skips steps without declaring them looks full. Control: the skipped list is a fixed vocabulary; `quick-skip-unlisted` flags a skip the profile does not list (for example a protocol without the declared single pass); the profile is a recorded event, not prose.
- **Quick masquerading as exploratory.** Plain exploratory projects exist without the profile. Control: the banner and the check codes appear only with the profile; plain exploratory is unchanged; a note from a plain exploratory project is not called quick.
- **Cheap routine model drifts.** A smaller model may screen worse. Control: the check sample rate is printed; a rate above a declared threshold (open choice 4) prints a warning and recommends a rerun with Claude as the screener.
- **Paper cap biases the corpus.** Stopping at N papers with a ranked order is a recall trade-off. Control: the stop reason and the count of unscreened records are stated; R-21 holds (the search is not truncated; screening is).
- **Promotion that cannot be honest.** A split of seeds drawn after seeing the corpus is not blind. Control: the gap list demands new held-out seeds before any new search; old seeds count as development.
- **Circularity in IDEA-40.** Control: advisory only; humans decide.
- **Scope creep.** Quick will attract requests for "just one more stage". Control: the vocabulary of skipped keys is fixed by decision; adding a stage is a new row.
- **Untested build during the pause.** Everything above is written without a test run; the untested list (memory) applies.

## 12. Open choices for the researcher

Recommended option first in each.

1. **What a quick project is.**
   (a) A declared overlay on `exploratory`: mode `exploratory`, profile `rapid-review`, plus the `quick` profile event (recommended; no change to decision 24).
   (b) A fourth rigour mode `quick` in the enum (cleaner banner, but touches every mode-keyed table: presets, `LEVELS`, thresholds).
   (c) A method profile only (`rapid-review` plus a protocol note); no new event (nothing computed to print or to enforce caps).

2. **Default limits.**
   (a) 20 papers to full text, 150 served units, one source, at most three queries (recommended; fits one sitting).
   (b) 10 papers, 80 units (very small; IDEA-40 design checks).
   (c) 40 papers, 300 units (a small topic survey).
   (d) No defaults: the researcher must pass both limits at `quick start`.

3. **Screening in quick.**
   (a) One pass A, ranked if the ranker is available, with the consecutive-excludes stopping rule on (recommended).
   (b) One pass A, no stopping rule; the paper limit alone ends it.
   (c) A single pass plus the check sample as the only second look, no stopping rule (more tokens).

4. **Routine model and checker.**
   (a) Operator's choice recorded as provenance; the check sample re-judges 10% (minimum 10) by a different Claude model; a warning above 20% disagreement (recommended).
   (b) Claude alone for every pass and no check sample (simplest; highest per-paper cost).
   (c) Wait for IDEA-90 before any routine-model feature is built (defers Q6).

5. **Promotion.**
   (a) `project.quick_promoted` with an effective-mode fold, redo list computed, nothing rewritten, no demotion (recommended).
   (b) Promotion creates a new full project that imports the quick project's works, screening and claims (`mine import`-style); the quick project stays frozen (no change to the mode fold, but two records to follow).
   (c) No promotion in v1: a quick note that matters is redone as a full project.

6. **Full-text screening in quick.**
   (a) Merged into extraction: the extractor may mark a paper off-topic with a recorded reason (recommended; saves one pass).
   (b) A separate single full-text pass (cleaner PRISMA boxes, more cost).
   (c) Skip full-text screening altogether; every kept paper is extracted.

7. **Seeds.**
   (a) Optional; none means "recall not measured", no split (recommended).
   (b) At least two required, to keep a recall check (heavier).
   (c) Forbidden in quick (avoids a split that later cannot be blind).

8. **Where the IDEA-40 link lives.**
   (a) A convention: the decision text names the project slug and the evidence report hash; no new event (recommended).
   (b) A computed link table from a decision id to a quick project (needs a small event).

9. **Hub in v1.**
   (a) Banner and a read-only Quick page; promotion by CLI only (recommended).
   (b) Also a promotion button (more surface).
   (c) CLI and banners only; no hub page.

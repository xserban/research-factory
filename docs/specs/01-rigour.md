# Rigour requirements

Status: draft for review · 2026-10-31 · Normative for every slice, like [00-system.md](00-system.md).

Source: consolidated from research-factory-old (`spec/TRACEABILITY.md`, `RIGOR-MODES.md`, `AGENT-RUNTIME.md`, `stages/00–04`; copied to `docs/reference/research-factory-old-spec/`), extended with requirements specific to agentic research. Each requirement has an ID (`R-xx`), the standard it serves, the rigor modes in which it is enforced (E = exploratory, P = pilot, S = systematic; "all" = every mode), and how it is verified (gate or test).

## Governing principles
1. **Scripts never make judgements; agents never do bookkeeping.** Counting, hashing, deduplication, PRISMA arithmetic and link integrity are code. Framing, criteria, verdicts, appraisal and synthesis are judgement, recorded with criterion and rationale.
2. **Rigour comes from recording, not rigidity.** Everything may change; nothing changes unrecorded.
3. **The human is the reviewer of record; agents are assisting reviewers.** Every decision is authorised by a human, individually or by a rule the human wrote.
4. **Ask when the answer changes what gets recorded; decide when it only changes convenience.**
5. **Gates check structure and completeness, never correctness of judgement.** Correctness is measured separately (calibration, audit, controls).

## A. Traceability and provenance
| ID | Requirement | Standard | Modes | Verified by |
| --- | --- | --- | --- | --- |
| R-01 | Unbroken chain: question → protocol → criterion / query → search run → raw payload → record → merge → work → decision → (full text → claim → synthesis sentence). `trace` works backwards and forwards | PRISMA 2020 | all | `check` fails on any broken link |
| R-02 | A work cannot exist without provenance (source, run, query, raw reference, method: database / citation-chase / seed-admission / hand-search / supplied / library-import; the last two added 2026-11-04 with slices 4a and 3d) | PRISMA 2020, PRISMA-S | all | model invariant test |
| R-03 | Raw source responses are archived verbatim before parsing | PRISMA-S | all | test: every run has raw blobs |
| R-04 | Every agent action records model version, skill/prompt version (hash of the skill text) and the exact input it saw (`input_blob`) | — (agentic) | all | event validation |
| R-05 | Every number in a report (PRISMA counts, κ, error rates) is derived from events; none is typed by a human or an agent | PRISMA 2020 | all | report generator test |

## B. Question and protocol
| ID | Requirement | Standard | Modes | Verified by |
| --- | --- | --- | --- | --- |
| R-10 | The question is decomposed into named elements (framing scheme such as PICO/SPIDER, or a custom one) with explicit **non-goals** (≥1 in E, ≥3 in P/S); `open` is allowed, `TBD` is not; the raw goal is recorded verbatim | PRISMA-P 1–4 | all | gate 00 |
| R-11 | **Every criterion names the question element or non-goal it derives from** (`IN01 ← Population`, `EX02 ← NG03`); a parentless criterion is rejected | PRISMA-P | P, S | gate 02 |
| R-12 | Criteria are operational rules, declare the stage at which they are answerable (`applies_at`), and have a priority that makes exclusion reasons deterministic | MECIR | all | gate 02 |
| R-13 | **Commitments before reading:** screening plan (passes, reviewers and roles, κ floor, disagreement handling), extraction schema and appraisal instrument per work type are declared in the protocol before screening/extraction starts | PRISMA-P, MECIR | P, S | gate 02 |
| R-14 | Protocols are versioned (hash over decision-relevant fields, never prose). **Amendments** (planned changes, with reason and `semantic` flag) and **deviations** (unplanned departures) are recorded separately | PRISMA-P, MECIR | all | test: prose change → no new version |
| R-15 | **Blast radius:** an amendment computes which earlier decisions are stale (loosening stales exclusions citing the criterion; tightening stales inclusions; adding stales everything untested against it); stale decisions must be re-screened | — | all | test |
| R-16 | The protocol must be `ready` before screening; screening against a draft protocol is refused | MECIR | P, S | tool refuses |

## C. Search
| ID | Requirement | Standard | Modes | Verified by |
| --- | --- | --- | --- | --- |
| R-20 | **Scope probe before the protocol:** queries tested against positive seeds (recall) and negative seeds (precision); vocabulary harvested from results; screening burden estimated. **Seed hold-out:** before the probe, positive seeds are split at random (recorded seed and procedure, stratified e.g. by period) into development (~2/3) and held-out (~1/3); held-out seeds are invisible to the probe, criteria drafting and worked examples | MECIR C34–C38, PRISMA-S 3 | P, S | gate 01 |
| R-21 | **The search returns what the query returns:** no relevance ranking, truncation or "top N"; partitioning (e.g. by date) only if provably exhaustive | PRISMA-S | all | adapter tests |
| R-22 | Each query records exact string, source, interface/platform, filters, limits and date (PRISMA-S fields) | PRISMA-S 4–16 | all | gate 03 |
| R-23 | Reported vs. retrieved counts are both stored; shortfalls and partial runs are first-class (resume or written explanation) | PRISMA-S | all | gate 03 |
| R-24 | **Seed check after search:** every positive seed is retrieved, or the miss is explained and an admission route planned; an unexplained miss fails the gate. Recall on **held-out** seeds is the figure reported; development-seed recall is reported separately and labelled as optimistic | — | P, S | gate 03 |
| R-25 | Supplementary searches (backward/forward citation chasing, seed admission, hand search) are separate runs; PRISMA counts their **new-after-dedup** records under "other methods" | PRISMA 2020 | P, S | report test |
| R-26 | Deduplication is recorded and reversible; seeds detect false merges (a seed vanishes) and false splits (a seed appears twice); preprint and published versions are linked, not silently merged away | PRISMA 2020 | all | tests |
| R-27 | **Replay:** searches can be re-executed and diffed against the recorded corpus; retracted records are flagged with notice date, never deleted, and raised as findings if included | — | P, S | replay test |

## D. Screening
| ID | Requirement | Standard | Modes | Verified by |
| --- | --- | --- | --- | --- |
| R-30 | Four verdicts: `include`, `exclude` (must name a criterion), `cannot-assess` (information absent → **promotes**), `unsure` (genuinely borderline → human) | MECIR | all | validation |
| R-31 | **Screen for recall:** when in doubt, include; thresholds asymmetric (high sensitivity required) | MECIR | all | calibration thresholds |
| R-32 | Every rationale **quotes the title/abstract span** it relies on; quotes are verified verbatim; verdicts may not rely on outside knowledge of authors, labs or the paper | — (agentic) | P, S | validation |
| R-33 | **Two independent passes** (A, B). Independence is engineered and recorded: different prompt framing (A: "does it meet inclusion?", B: "is there a reason to exclude?"), reversed criterion order, different model where available, separate sessions with no shared context; neither pass can read the other's verdicts | MECIR C39–C41 | P (sample), S (all) | tool isolation test |
| R-34 | **Statelessness:** records are screened in fresh contexts in randomised order; learning enters only as worked examples or protocol amendments, never as remembered precedent | — (agentic) | P, S | task design |
| R-35 | **Calibration** (correctness): before each batch both passes screen ~30 human-labelled records (incl. seeds); sensitivity and specificity reported; below threshold blocks the batch | — | P, S | gate 04 |
| R-36 | **Agreement** (consistency): Cohen's κ per pass pair and per criterion; floor declared in the protocol (advisory in P, enforced in S); disagreements never auto-resolved | MECIR | P, S | gate 04 |
| R-37 | **Audit sample** (agreed-but-wrong): human audits ≥2% (min. 50) of agreed decisions, weighted 3:1 towards agreed exclusions; error rate above the declared floor sends criteria back to the protocol | — | P, S | gate 04 |
| R-38 | `cannot-assess` rate is reported per criterion; above threshold the criterion's `applies_at` must be amended | — | P, S | gate 04 |
| R-39 | Reviewer roles are declared in the protocol (reviewer of record, assisting reviewers and their duties); a **methods statement** disclosing what was automated is generated from it | journal AI-disclosure policies | all | report test |

## E. Extraction, appraisal, synthesis (detailed in later slices)
| ID | Requirement | Standard | Modes |
| --- | --- | --- | --- |
| R-40 | Claims are atomic, carry a locator and a verified source span, an evidence type and strength; corrections supersede, never edit | — | P, S |
| R-41 | Appraisal stores **item-level answers** of the declared instrument (RoB 2, ROBINS-I, PROBAST, QUADAS-2, GRADE domains; AACODS for grey literature; ASME V&V 40 for computational models), never only a summary grade | Cochrane, GRADE | S (P: grey only) |
| R-42 | Every synthesis sentence cites claim IDs; disagreement between claims is surfaced, not averaged away; answers may say "the corpus does not support an answer" | PRISMA 2020 20–22 | all |
| R-43 | Full text: every retrieval attempt is recorded (route, URL, version, licence, raw hash); conversion is deterministic with a pinned converter; extraction applies to one recorded document version | PRISMA 2020 | all |
| R-44 | **Number check:** every extracted numeric value must occur in its verified quote or anchored table cell (declared normalisation); values copied from cited papers are flagged and not counted as independent results | — (agentic) | P, S |
| R-45 | Extraction schema, appraisal instrument and comparability keys are declared in the protocol before extraction (cf. R-13); evidence is grouped only by identical comparability keys and never ranked across groups | Cochrane Handbook ch. 5, 9 (verify) | all |
| R-46 | Dual extraction (all in S, recorded sample in P) with field-level agreement; disagreements to the human; human audit sample of agreed values with error rate | MECIR data-collection items (verify numbers) | P, S |
| R-47 | Literature (raw sources, full text) is stored in the project-local library, never in a git-tracked path; events carry hashes and the verified quotes used as evidence | — | all |

## F. Hypotheses and testing (detailed in later slices)
| ID | Requirement | Modes |
| --- | --- | --- |
| R-50 | Hypotheses and their falsification tests are registered before evidence is examined; exploratory and confirmatory analyses are separated (held-out data) | P, S |
| R-51 | Proposer never evaluates; critic sees artefacts, not the proposer's reasoning | all |
| R-52 | Refuted hypotheses and null results are recorded and reported | all |
| R-53 | **Temporal hold-out validity:** when hypotheses are scored against later literature, the model's training cut-off must precede the hold-out window, or the result is reported as contaminated | P, S |
| R-54 | Positive and negative controls measure the pipeline's sensitivity and false-positive rate | S |

## G. Promotion between modes
`check --promote-to <mode>` lists exactly what the existing record lacks for the higher mode (second passes, calibration, audit, appraisal, PRISMA-S fields, locators). Because R-01–R-05 and R-14 hold in every mode, promotion never requires redoing recorded work — only adding to it.

## H. Method profiles (proposed)
Each project declares a **method profile** in its protocol. The profile fixes required stages, the reporting checklist and the appraisal approach; it combines with the rigor mode.

| Profile | Basis (references.md) | Typical use in our programme |
| --- | --- | --- |
| `systematic-review` | Cochrane Handbook; PRISMA 2020 (M1) | Clinical questions with outcome data (e.g. TAVI outcomes) |
| `scoping-review` | Arksey & O'Malley (M4); JBI (M5); PRISMA-ScR (M3) | Mapping a field (e.g. AI for neurodegeneration, PINNs in cardiovascular modelling) |
| `se-systematic-review` | Kitchenham & Charters (M6) | Systematic reviews of computational methods (e.g. linear attention for vision) |
| `mapping-study` | Petersen et al. (M7) | Classifying a method landscape; evidence/benchmark maps |
| `rapid-review` | Garritty et al. (M10) | Time-boxed questions; every shortcut recorded |
| `living-review` | Elliott et al. (M11) | The "keep current" production line |

All profiles: PRISMA-S search reporting (M2); snowballing per Wohlin (M8) where database coverage is weak (much ML literature is on arXiv and in proceedings).

| ID | Requirement | Modes |
| --- | --- | --- |
| R-60 | The protocol declares a method profile; `check` reports gaps against that profile's reporting checklist | all |
| R-61 | **PRESS review** (M9) of the search strategy before the search runs: a reviewer agent applies the PRESS checklist, a human confirms; findings and responses are recorded | P, S |

## I. Defence stage (proposed)
Before any output leaves the factory (review, hypothesis set, paper), it is defended. Every step is recorded as events.

| ID | Requirement | Modes |
| --- | --- | --- |
| R-70 | **Self-appraisal** with the instruments reviewers use: AMSTAR 2 (M12) and ROBIS (M13) for reviews; NeurIPS Paper Checklist (M14) or the target venue's checklist for ML experiments. Item-level answers, no total score | P, S |
| R-71 | **Simulated peer review:** independent reviewer agents without access to authoring context review against the target venue's reviewer guidelines; every point gets a recorded response | S |
| R-72 | **Viva:** examiner agents question each conclusion; each answer must be supported by `trace`; unanswerable points go to the limitations, not away | S |
| R-73 | **Sign-off** by the reviewer of record; optional prior registration of the protocol (PROSPERO for reviews with health outcomes; OSF otherwise) | S |

## Requirements added with the slices accepted on 2026-11-04

Numbering continues by blocks of ten per slice so that no two drafts' provisional letters collide. Source specs give the full text; each requirement is binding from the slice that introduces it.

**Reserved for slices 3a–3c** (rulings adopted 2026-11-04; rows added by plans G1 Task 10, G2-E Task 5 and G3-C Task 6 when built): R-80 reference completeness (3a R-xx(a)), R-81 link provenance (3a (b)), R-82 snowball discipline (3a (c)), R-83 citation-context minimality (3a (d)), R-84 stated versus inferred relations (3b (e)), R-85 edge basis (3b (f)), R-86 graph as projection (3b (g)), R-87 interpretation is not evidence (3c (h)), R-88 reviewable interpretation (3c (i)), R-89 concept sources (3c (j)).

**References and snowballing (slice 3a; proposed rows, built by plan G1; numbering confirmed at merge)**

| ID | Requirement | Modes |
| --- | --- | --- |
| R-80 (proposed) | **Reference completeness.** Per document the parsed entry count and the distinct marker count are both stored; a mismatch is flagged and listed by `check`. Unresolved references are listed, never dropped; the counts resolved, unconfirmed, ambiguous and unresolved sum to the entry count. `references-unresolved-ceiling` warns above 30% unresolved or ambiguous (provisional, pending the pilot) | all |
| R-81 (proposed) | **Link provenance.** Every reference link records method, confidence class, score, matcher version and source response; a non-identifier link feeds candidates only after confirmation (title-exact excepted). An agent proposes and never confirms; a rejection supersedes | all |
| R-82 (proposed) | **Snowball discipline.** Rounds, directions and the stopping rule are declared in the protocol and recorded before any query runs; a candidate is never included without screening; rounds and the yield per round (new after deduplication, included) are reported | P, S |
| R-83 (proposed) | **Citation-context minimality.** Only anchors and marker tokens are stored; bibliography text is stored only as bounded parsed entry fields and an `entry_sha256` that re-derives from the pinned conversion | all |

### K. Organisation and imported libraries ([slice 3d](slice-3d-regions-import.md))
| ID | Requirement | Modes |
| --- | --- | --- |
| R-90 | **Regions are versioned selections.** A region is cited only by a pinned, hashed version whose member set is derived from declared rules and recorded decisions; drift is reported, never applied silently; a region asserts nothing and changes no evidence value | all |
| R-91 | **Consolidation before selection.** Free labels are never evidence and never select; only promoted terms with stated or human-confirmed applications may appear in a region rule; merges and promotions are recorded, reversible and human-decided | all |
| R-92 | **Imported libraries.** An imported record carries provenance to the archived export; it enters the corpus only as a candidate for screening; the coverage of a library by the systematic search is derived per declared bucket and reported on a held-out part when the library preceded the search | P, S (E: reported, not gated) |

### L. Discovery and living corpus ([slice 4a](slice-4a-inbox-discovery.md), [slice 4b](slice-4b-living-corpus.md))
| ID | Requirement | Modes |
| --- | --- | --- |
| R-100 | **Discovery is derived.** Every discovery figure is computed from events; route, surfacer and first-surfaced are never typed | all |
| R-101 | **Route-blind screening.** Screening and extraction tasks never carry how a work was discovered | P, S |
| R-102 | **Watch runs are search runs.** A living update identifies records only through recorded search runs of planned queries, grouped in cycles; window partitions are declared and their misses measured | P, S |
| R-103 | **Update flow.** A living review reports, per update, a PRISMA flow over the records first identified in it, besides the cumulative flow; both computed | P, S |
| R-104 | **Notice propagation.** Retractions, withdrawals, corrections and expressions of concern of dependent works are recorded with source and date; their effects reach only the affected work's dependents, are computed, and require a human assessment; nothing is deleted | all |
| R-105 | **Conclusion change is computed.** A conclusion's change is a difference in computed facts or in its basis state since a recorded snapshot; no agent judges it | all |
| R-106 | **Declared cadence and end.** A living review declares its cadence per source and when it stops being living | P, S |

### M. Teams ([slice 5](slice-5-teams-deployment.md))
| ID | Requirement | Modes |
| --- | --- | --- |
| R-110 | **Human screeners.** A human pass is independent of the other pass by session, user and the user's agents; it is served the agent view; exclusions carry a verified quote in `systematic` | P, S |
| R-111 | **Attributed acts.** On a hosted project every event names an authenticated user (directly or as the agent's principal); acts on a human-act permission are refused to agents; relayed human acts are counted and reported | all |
| R-112 | **Derived credit.** Contribution and AI-assistance statements are derived from events with a versioned map and confirmed by each named person; none is typed | all |

### N. Hypotheses and testing, continued ([slice 6](slice-6-hypotheses.md))
| ID | Requirement | Modes |
| --- | --- | --- |
| R-120 | **Hypotheses cite triggers.** A lead or hypothesis without at least one resolvable trigger cannot be written (P, S: a lead is required for a hypothesis) | all |
| R-121 | **Computed outcome.** The outcome of a registered hypothesis is computed from recorded results by its registered decision rule; no actor sets it | all |
| R-122 | **Reproduce before confirm.** Confirmatory runs need every declared baseline resolved; a non-reproduced baseline accepted by a human flags every dependent outcome | P, S |
| R-123 | **Recorded order.** Confirmatory results carry the unlock nonce issued after registration and freeze; results without it are refused | P, S |
| R-124 | **Failure conditions.** Every registry row states the conditions of failure (design, data, budget, model, code); a registry row is never removed | all |
| R-125 | **Own results apart.** Own and reproduced results are never merged with reported results in groups, frontiers or counts | all |

### O. Writing, views and exports ([slice 7b](slice-7b-views-writing.md))
| ID | Requirement | Modes |
| --- | --- | --- |
| R-130 | **Supported sentences.** A claim-bearing sentence in any factory-produced text cites supports that resolve to verified spans or computed figures; unsupported, unchecked or stale sentences are marked in every rendering and cannot be released under `systematic` | all (marking), S (gate) |
| R-131 | **Independent sentence verification.** Semantic support is judged by a verifier that did not write the sentence and sees only the sentence and its spans; a human audits a sample of positive verdicts and the error rate is reported | P, S |
| R-132 | **Derived exports.** Exports and views are deterministic builders that name their scope and log position, contain no library text, and are byte-identical for the same log | all |
| R-133 | **Recorded agent context.** Context given to an agent outside a task (briefings) is stored and linked to the session that received it | all |

### P. Modules, gates and miners ([slice M](slice-M-modules.md))
| ID | Requirement | Modes |
| --- | --- | --- |
| R-140 | **Declared autonomy.** Every decision gate has a declared policy (explicit or preset) recorded with the protocol; every output's autonomy is computable from events; methods state the policy and per-level counts | all |
| R-141 | **Verifiable miners.** A registered miner uses only verifiable field kinds; every record carries at least one verified quote; free text is refused | all |
| R-142 | **Calibrated before evidence.** A registered miner's records count as evidence only after a human-labelled calibration in the same project passed declared thresholds above platform floors; the proposer neither runs the calibration pass nor labels it | all |
| R-143 | **Reuse is recorded and re-verified.** An imported record names its source and is re-verified against the importing project's own conversion; it never counts as an independent pass it did not have | all |

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
| R-02 | A work cannot exist without provenance (source, run, query, raw reference, method: database / citation-chase / seed-admission / hand-search) | PRISMA 2020, PRISMA-S | all | model invariant test |
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


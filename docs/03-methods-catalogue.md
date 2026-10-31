# Methods catalogue

Practices to borrow. Most were designed for human teams and are expensive with people; with agents they become cheap.

## A. From software factories ("treat knowledge like code")

### Versioning and builds
| Software practice | Research equivalent |
| --- | --- |
| Git, diffs, branches | Every claim and protocol versioned; competing hypotheses on branches; evidence diffs |
| Build graph (Make/Bazel), incremental, cached | Pipeline as dependency graph; only downstream items rebuilt when inputs change (cheap living reviews) |
| Lockfiles | Pinned model, prompts, corpus snapshot, code per run |
| Types, schemas, contracts | Claim schema, controlled vocabularies, typed artifacts between stages |
| Reproducible builds | Containerised runs, replay packages |
| Config as code | Protocols as YAML; registration = commit hash |

### Quality
| Software practice | Research equivalent |
| --- | --- |
| Unit tests | Per-stage checks: span exists, citation resolves, schema valid |
| Regression suite | Gold set re-run on every agent/prompt change; fails if recall drops |
| Test-driven development | Write falsification tests before generating evidence (pre-registration) |
| Linters | Reporting-guideline checks (PRISMA-ScR, TRIPOD+AI, CLAIM), statistics checks, wording checks |
| Code review, protected main | Claims enter the main graph only after critic + human approval |
| Mutation testing, fault injection | Plant fake / retracted papers or fabricated data; measure detection |
| Dev / staging / prod | Exploration vs. confirmation: confirmatory tests once, on held-out data |

### Flow and operations
| Practice | Research equivalent |
| --- | --- |
| Issue tracker, Kanban | Hypotheses as tickets: proposed → registered → tested → supported/refuted |
| WIP limits | Don't generate more hypotheses than can be tested |
| Andon cord (Toyota) | Integrity failure halts the line until a human clears it |
| Poka-yoke | Tools refuse invalid input (no claim without a span) |
| Statistical process control | Random audits; control charts on extraction accuracy |
| Distributed tracing | Provenance graph as a trace |
| SLOs, error budgets | Quality targets (e.g. screening recall ≥ 0.95); breach stops new work |
| Blameless postmortems | Wrong claim got through → analyse → add regression test |
| Canary releases, A/B | Trial new agent/prompt on a subset before switching |
| git bisect | Find which pipeline change caused a quality drop |
| DORA metrics | Time from question to validated claim; share of claims later reversed |
| CODEOWNERS | Region owners review changes to their region |
| Continuous integration across repos | One team's validation suite runs on another team's new methods |

### Supply chain
| Practice | Research equivalent |
| --- | --- |
| SBOM, signed provenance | Evidence bill of materials per conclusion |
| Vulnerability alerts | Retraction alerts propagated to dependent claims (e.g. Retraction Watch data via Crossref) |
| Package registry | Reusable extraction schemas, verified claim sets, pipeline templates |

## B. From research methodology and meta-science

### Evidence synthesis
- Living systematic reviews (Cochrane); evidence gap maps (Campbell, 3ie); umbrella reviews (cheap outer regions); realist synthesis (context–mechanism–outcome; explains contradictions); network meta-analysis (rank methods across studies never compared directly).

### Appraisal and reporting
- PROBAST (prediction-model risk of bias), QUADAS-2 (diagnostic accuracy), TRIPOD+AI and CLAIM (AI reporting), GRADE (certainty), **ASME V&V 40** (credibility of computational models for medical devices — relevant for TAVI/stenting).

### Hypothesis generation
- Literature-based discovery (Swanson); link prediction on concept graphs (score with temporal hold-out); morphological analysis / Zwicky box (enumerate task × method × data × population); TRIZ (problem-structure matching for analogous fields); multiple working hypotheses (Chamberlin 1890) and strong inference (Platt 1964).

### Testing and robustness
- Many-analysts (Silberzahn et al. 2018) → many independent analyst agents; multiverse / specification-curve analysis; adversarial collaboration (opposing agents agree a decisive test before seeing data); blind analysis (masked outcomes until analysis frozen); triangulation (Munafò & Davey Smith 2018); target trial emulation and causal diagrams for observational data.

### Calibration and self-assessment
- Positive and negative controls (measure sensitivity and false-positive rate); empirical calibration of p-values (OHDSI); forecasting / replication prediction with Brier scores; value of information (test next what teaches most per budget); exploration–exploitation allocation (bandits) across projects.

### Knowledge representation
- Nanopublications (claim format); Open Research Knowledge Graph (structured comparisons); argument mining; citation-intent classification; novelty / disruption metrics; FAIR principles.

### Research management
- Delphi method (vocabularies, gold labels, prioritisation; mixed agent–human panels); stage-gate; technology readiness levels (method maturity); electronic lab notebooks; research portfolio management.

### For theses built on the factory
- Design Science Research (Hevner et al. 2004): problem → requirements → artifact → evaluation → contribution.

## C. Rigour for computational / method-development research

| General technique | Computational equivalent |
| --- | --- |
| Blind analysis | Locked test sets, evaluated once after method and protocol are frozen |
| Multiverse | Spread over seeds, hyperparameters, preprocessing |
| Positive / negative controls | Synthetic ground truth: digital phantoms (reconstruction), analytic flow solutions (CFD/PINN), equivalence checks (attention variants) |
| Many-analysts | Independent agents re-implement a baseline from its paper; divergence = underspecified paper |
| Triangulation | In silico + physical phantom + clinical data |
| Credibility | ASME V&V 40; uncertainty quantification for clinical outputs |

## Highest-value picks

1. Many-analysts + multiverse. 2. Positive and negative controls. 3. PROBAST / QUADAS-2 / GRADE (clinical work) and V&V 40 (simulation). 4. Adversarial collaboration + blind analysis. 5. Zwicky box + link prediction, scored on temporal hold-out. 6. Nanopublications as claim format. 7. Value of information for test prioritisation.

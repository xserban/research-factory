# The hypothesis engine as a composite of mined techniques across the research loop (recipe, 2026-11-19)

Status: plan only, docs only. Nothing built, nothing run, no model called. It complements `docs/plans/2026-11-19-hypothesis-engine-techniques.md` (which classified only the 49 `ideation-hypothesis` approaches; it is not edited here) and builds on `docs/plans/2026-11-14-hypotheses-engine.md` (engine parts, gates, principles). Rigour rules in scope: R-50 to R-54, R-87, R-120 to R-125. Module names are taken from those plans and from the brief; I did not read the service code, so every "exists" below means "named as existing in the engine plan or the earlier classification" and is **to check** in code before a task is written.

## 1. Purpose and limits of the evidence

Purpose: to assemble the hypothesis engine's loop, from the grounding of a lead to the recorded outcome of its test, out of techniques that the technique miners extracted from the core layer of the `agentic-science` corpus, one technique choice per step, with the researcher deciding at each step what to adopt.

How the data were read. Hub payloads `landscape.json` (catalogue of 320 approaches, 95 works, compact rows) and `landscape_uses.json` (verbatim quotes with anchors). I used the core layer (92 works) and the six stages that belong to the loop: literature-review (lr), ideation-hypothesis (idh), experiment-design (ed), implementation-execution (ie), data-analysis (da), review-verification (rv). Paper-writing (pw) and `other` are skipped. Counts were computed with throw-away scripts that are not committed. "Works" is the number of core works with at least one row for the approach; "supportive rows" are rows with evidence `independent-test`, `own-ablation` or `own-comparison`.

Limits, stated plainly:

1. The rows are exploratory and uncalibrated (miner agreement 0.2 to 0.6). They are a map of what systems claim to do, not a measurement.
2. A row records that a system uses a technique and how it says it tested it. It does not record how well the technique works.
3. Across the 254 approaches of these six stages there are 1,614 core rows: 1,348 (84%) `not-stated`, 47 (3%) `asserted-only`, 12 (1%) `reported-failure`, and 207 (13%) supportive, all of the latter `own-ablation` or `own-comparison`. No row carries `independent-test`. So "most rows are asserted-only" in the brief is better put: most rows state no test at all, and a few state the authors' own test. Strength of stated evidence therefore discriminates only weakly; the choices below rest mainly on fit with our rules and modules, with the stated evidence as a tie-breaker.
4. Evidence, where present, is the authors' own (ablation or comparison on their own system), mostly on tasks of automated machine-learning research. Nothing here shows that a technique works for a review project.
5. The researcher's remark that the miners answer both ideation and testing is true for what systems do (the ed, ie, da and rv approaches describe testing in experiment-running systems) and untrue as evidence of what works. The catalogue also has no approach defined as testing a hypothesis by a literature window; the nearest are lr-29 and rv-11 (novelty check), da-36 (cross-paper discrepancy detection, 1 work) and lr-20 (claim and score extraction, 2 works).

Per-stage totals of core rows (rows, supportive, asserted-only, not-stated, reported-failure): lr 234, 19, 3, 211, 1; idh 349, 73, 9, 264, 3; ed 234, 32, 8, 194, 0; ie 336, 20, 14, 298, 4; da 218, 28, 7, 182, 1; rv 243, 35, 6, 199, 3. Ideation has the most supportive rows (21% of its rows); implementation and literature review the fewest (6% and 8%).

## 2. The loop: ten steps and the approaches behind each

Principle of the loop. It is human-in-the-loop: at every step the researcher may accept the proposed technique, skip the step, swap the technique or override a result; nothing is fixed in advance (section 4 lists the knobs). The platform computes and records; a Claude session through MCP supplies judgement, with provenance (CLAUDE.md). Steps 1 to 5 are the "lead" half (they end at a promoted lead, which `lead_decide` already gates); steps 6 to 10 are the "test" half.

Ten steps: (1) ground in the literature and gaps; (2) generate or over-generate candidates; (3) critique and refine; (4) novelty and prior check; (5) rank and select; (6) specify the hypothesis and design the test; (7) execute or run the evidence check; (8) analyse; (9) verify and review; (10) record the outcome, memory, feedback and steering.

For each step the approach set was chosen by me from the six stages by relevance of the definition (the set is therefore a choice, listed in each table, not a mined fact). Tables are ordered by number of works. Percentages are shares of the approach's own rows. Quotes are verbatim from the payload (top three approaches by works). "Systems combining most of these" counts, per work, how many of the step's listed approaches it uses; "pairs" counts how often two approaches of the set appear in the same work.

### 2.1 Step 1: Ground in the literature and gaps

| Id | Technique | Works | Supportive rows | Asserted-only | Not-stated | Reported failure |
|---|---|---|---|---|---|---|
| lr-01 | Scholarly-API retrieval of candidate papers (named index, topic string, top-k) | 29 | 0 | 1 (3%) | 28 (96%) | 0 |
| idh-19 | Literature search tool inside the generation loop (live domain record) | 15 | 0 | 1 (6%) | 14 (93%) | 0 |
| lr-19 | Digest, note and knowledge-card extraction (loosely structured summaries, isolated reader contexts) | 14 | 0 | 0 (0%) | 14 (100%) | 0 |
| idh-18 | Gap and limitation extraction before ideation | 14 | 1 | 0 (0%) | 13 (92%) | 0 |
| idh-46 | Anchoring ideation on seed papers or a baseline paper | 11 | 0 | 0 (0%) | 11 (100%) | 0 |
| lr-21 | Literature knowledge-graph construction (typed entities and relations) | 10 | 0 | 0 (0%) | 10 (100%) | 0 |
| idh-17 | Pre-built knowledge graph or method corpus as ideation context | 10 | 1 | 0 (0%) | 9 (90%) | 0 |
| lr-28 | Typed persistent research memory, world model or wiki | 9 | 2 | 1 (11%) | 6 (66%) | 0 |
| lr-25 | LLM gap and limitation extraction loops | 8 | 1 | 0 (0%) | 7 (87%) | 0 |
| lr-06 | Seed-paper anchored corpus construction | 6 | 0 | 0 (0%) | 6 (100%) | 0 |
| lr-07 | Citation-graph expansion (forward and backward, multi-hop, layered) | 6 | 1 | 0 (0%) | 5 (83%) | 0 |
| lr-34 | Cross-field and mechanism-transfer search | 5 | 2 | 0 (0%) | 3 (60%) | 0 |
| idh-20 | Retrieval-grounded generation with structural citation validation and a speculation fence | 1 | 1 | 0 (0%) | 0 (0%) | 0 |

Quotes for lr-01:
- "integrating a Search Agent (using Semantic Scholar API, returning top-5 paper abstract only) into the NHO task" (PiFlow: Principle-Aware Scientific Discovery with Multi-Agent Collaboration, 2025, s114.2.p13; evidence: asserted-only)
- "the PhD agent utilizes the arXiv API to retrieve related papers" (Agent Laboratory: Using LLM Agents as Research Assistants, 2025, s3.1.p1; evidence: not-stated)

Quotes for idh-19:
- "naturally accommodates external knowledge as Major Premises in its reasoning chain" (PiFlow: Principle-Aware Scientific Discovery with Multi-Agent Collaboration, 2025, s114.2.p15; evidence: asserted-only)
- "Utilize advanced research tools such as the Google Scholar API, entity linking, and LLM-driven exploration to formulate innovative hypotheses" (EvoSci: A Bio-Inspired Multi-Agent Framework for the Evolution of Scientific Discovery, 2026, s24.p1; evidence: not-stated)

Quotes for lr-19:
- "we ask the LLM to extract ideas from these papers and inherit the progressive relation of the paper chains to form our CoIs" (Chain of Ideas: Revolutionizing Research Via Novel Idea Development with LLM Agents, 2025, s2.2.2.p5; evidence: not-stated)
- "you should provide a detailed breakdown of all the literature you have read, with each individual research report" (EvoSci: A Bio-Inspired Multi-Agent Framework for the Evolution of Scientific Discovery, 2026, s40.p1; evidence: not-stated)

Systems combining most of these: EvoSci: A Bio-Inspired Multi-Agent Framework for the Evoluti (2026) 7/13; IdeaScientist: Orchestrating Agents for Grounded Scientific  (2026) 7/13; Making AI Scientists Auditable from Evidence to Claim (2026) 7/13; SGHA: Evidence-Grounded Research Problem Discovery with Loca (2026) 6/13
Most frequent pairs in one work: lr-01+lr-19 (8), idh-18+lr-01 (8), idh-18+lr-19 (8), idh-18+lr-25 (8)

### 2.2 Step 2: Generate or over-generate candidates

| Id | Technique | Works | Supportive rows | Asserted-only | Not-stated | Reported failure |
|---|---|---|---|---|---|---|
| idh-04 | Over-generate then screen: a seed pool of N ideas, top-k refined | 11 | 0 | 0 (0%) | 11 (100%) | 0 |
| idh-05 | Evolutionary operators on an idea population with LLM-judged fitness | 10 | 4 | 0 (0%) | 6 (60%) | 0 |
| idh-40 | Cross-domain mechanism transfer and goal-conditioned concept collision | 8 | 4 | 0 (0%) | 4 (50%) | 0 |
| idh-08 | Role-specialised debate panel with a synthesizer | 8 | 1 | 2 (25%) | 5 (62%) | 0 |
| idh-49 | Idea expansion and adaptation of prior formulations | 4 | 0 | 0 (0%) | 4 (100%) | 0 |
| lr-23 | Decomposition of past papers into reusable idea or method units, with canonicalisation and clustering | 4 | 0 | 0 (0%) | 4 (100%) | 0 |
| idh-39 | Prompted anti-obviousness and technology-first question formulation | 2 | 0 | 0 (0%) | 2 (100%) | 0 |
| idh-11 | Consensus gap probing with shared visibility across rounds | 1 | 1 | 0 (0%) | 0 (0%) | 0 |
| idh-15 | Chain-of-Ideas: citation-ordered literature chains and trend extrapolation | 1 | 1 | 0 (0%) | 0 (0%) | 0 |
| idh-28 | Decomposition of hypothesis generation into inspiration retrieval and composition | 1 | 1 | 0 (0%) | 0 (0%) | 0 |
| lr-08 | Citation chains organised as a progression of ideas (Chain-of-Ideas) | 1 | 1 | 0 (0%) | 0 (0%) | 0 |

Quotes for idh-04:
- "generate at least 10 initial seed ideas based on insights from prior research reports, discussions, and the initial topic: {init topic}" (EvoSci: A Bio-Inspired Multi-Agent Framework for the Evolution of Scientific Discovery, 2026, s46.p1; evidence: not-stated)
- "and write at least twelve questions, with no technology or field supplying more than a third of them and no type of study more than half." (Letting AI Formulate the Research Question: Autonomous Research Agents, 2026, s3.2.p4; evidence: not-stated)

Quotes for idh-05:
- "Crossover: Enables recombination by exchanging entities between different semantic clusters within the same discipline, producing novel concept combinations while preserving domain coherence." (EvoSci: A Bio-Inspired Multi-Agent Framework for the Evolution of Scientific Discovery, 2026, s3.4.p4; evidence: own-ablation)
- "The agent also attempts to directly combine the best aspects of several top-ranking hypotheses to create new hypotheses." (Accelerating scientific discovery with Co-Scientist, 2026, s8.p11; evidence: own-ablation)

Quotes for idh-40:
- "An innovator searches for mechanisms that have addressed a similar challenge in other fields, then adapts them to the target setting." (IdeaScientist: Orchestrating Agents for Grounded Scientific Ideation, 2026, s1.p4; evidence: own-ablation)
- "5-WHY root-cause analysis that maps failing modules to abstract mechanisms, then searches other scientific fields using their vocabulary" (AI-Supervisor: Autonomous AI Research Supervision via a Persistent Research World Model, 2026, s2.1.p5; evidence: own-ablation)

Systems combining most of these: EvoSci: A Bio-Inspired Multi-Agent Framework for the Evoluti (2026) 3/11; Chain of Ideas: Revolutionizing Research Via Novel Idea Deve (2025) 3/11; SciDER: Scientific Data-centric End-to-end Researcher (2026) 2/11; AutoResearch: Insight In, Hallucination Out (2026) 2/11
Most frequent pairs in one work: idh-04+idh-05 (3), idh-04+idh-40 (2), idh-05+idh-40 (2), idh-08+idh-40 (2)

### 2.3 Step 3: Critique and refine

| Id | Technique | Works | Supportive rows | Asserted-only | Not-stated | Reported failure |
|---|---|---|---|---|---|---|
| idh-07 | Generator-critic refinement loop (simulated peer review) | 19 | 2 | 2 (10%) | 15 (78%) | 0 |
| ed-03 | LLM reviewer or critic loop on the experiment plan before execution | 12 | 1 | 1 (8%) | 10 (83%) | 0 |
| rv-14 | Critic, reward model or reviewer used as fitness or reward inside an idea-generation loop | 8 | 1 | 1 (12%) | 6 (75%) | 0 |
| rv-09 | Critic from a different model family, or a fresh-context critic that does not see the producer's reasoning | 7 | 1 | 0 (0%) | 6 (85%) | 0 |
| rv-02 | Multi-reviewer panel with meta-reviewer or area chair | 6 | 0 | 0 (0%) | 6 (100%) | 0 |
| rv-04 | Task-specific rubric generated or compiled for a judge (and rubric-as-protocol) | 4 | 2 | 1 (25%) | 1 (25%) | 0 |
| idh-10 | Multi-model proposal ensembles with cross-model approval voting | 3 | 1 | 0 (0%) | 2 (66%) | 0 |
| rv-15 | Staged reflection review of hypotheses (initial, full, deep verification, observation, simulation) with meta-review feedback | 2 | 1 | 0 (0%) | 1 (50%) | 0 |
| rv-37 | Adversarial manuscript review with refutation of the reviewer's own issues | 1 | 1 | 0 (0%) | 0 (0%) | 0 |

Quotes for idh-07:
- "The agent then uses this feedback from Comment to produce an improved version $y^{(k+1)}$, thereby simulating an authentic peer-review iteration process." (DeepInnovator: Triggering the Innovative Capabilities of LLMs, 2026, s4.3.p2; evidence: own-comparison)
- "Obtain one critique of the top five from the critic" (Letting AI Formulate the Research Question: Autonomous Research Agents, 2026, s3.2.p7; evidence: asserted-only)

Quotes for ed-03:
- "The critic, consulted after short feasibility probes but before the main plan, shaped what was compared and what was claimed" (Letting AI Formulate the Research Question: Autonomous Research Agents, 2026, s7.p6; evidence: asserted-only)
- "Agents post experiment proposals to a shared forum, where peers critique them before execution, filtering weak ideas before compute is committed." (AutoScientists: Self-Organizing Agent Teams for Long-Running Scientific Experimentation, 2026, s1.p3; evidence: own-ablation)

Quotes for rv-14:
- "the comment model Comment instructs how to improve while the reward model Reward solely judges whether it has genuinely improved" (DeepInnovator: Triggering the Innovative Capabilities of LLMs, 2026, s4.3.p3; evidence: asserted-only)
- "use this dataset to train a critic model which guides the ideation process under expert-level evaluation" (Deep Ideation: Designing LLM Agents to Generate Novel Research Ideas on Scientific Concept Network, 2025, s1.2.p10; evidence: own-ablation)

Systems combining most of these: EvoSci: A Bio-Inspired Multi-Agent Framework for the Evoluti (2026) 3/9; Letting AI Formulate the Research Question: Autonomous Resea (2026) 3/9; The Agentic Scientist: Orchestrating Coding Agents for Autom (2026) 3/9; DeepInnovator: Triggering the Innovative Capabilities of LLM (2026) 2/9
Most frequent pairs in one work: idh-07+rv-14 (7), ed-03+idh-07 (4), ed-03+rv-09 (2), ed-03+rv-04 (2)

### 2.4 Step 4: Novelty and prior check

| Id | Technique | Works | Supportive rows | Asserted-only | Not-stated | Reported failure |
|---|---|---|---|---|---|---|
| idh-12 | Novelty check of a candidate idea against a literature search | 17 | 2 | 0 (0%) | 14 (82%) | 1 |
| idh-33 | Failure and dead-end memory consulted before proposing | 14 | 3 | 0 (0%) | 11 (78%) | 0 |
| lr-29 | Literature-based novelty check of ideas | 11 | 2 | 1 (9%) | 7 (63%) | 1 |
| rv-11 | Novelty check of an idea or claim against the literature (retrieval plus LLM judge) | 10 | 3 | 0 (0%) | 7 (70%) | 0 |
| idh-13 | Redundancy and diversity filters among candidate ideas | 7 | 0 | 1 (14%) | 6 (85%) | 0 |
| rv-12 | Embedding-distance and token-overlap scores for novelty, duplicates and derivative content | 3 | 1 | 0 (0%) | 2 (66%) | 0 |

Quotes for idh-12:
- "For novelty, it summarizes known aspects of the hypothesis and then judges their novelty based on existing literature." (Accelerating scientific discovery with Co-Scientist, 2026, s8.p7; evidence: own-ablation)
- "the system automatically tempers overconfident assertions by rewriting terms like first or never explored to appears under-explored based on this search" (OmniScientist: An Omni-Modal Omni-Discipline AI Scientist, 2026, s4.2.p2; evidence: own-ablation)

Quotes for idh-33:
- "no proposal falls inside a previously rejected range in the dead-end registry" (AutoScientists: Self-Organizing Agent Teams for Long-Running Scientific Experimentation, 2026, s101.7.p4; evidence: own-ablation)
- "AutoResearchClaw maintains a persistent lesson store that converts past failures into future safeguards." (AutoResearchClaw: Self-Reinforcing Autonomous Research with Human-AI Collaboration, 2026, s3.6.p1; evidence: own-ablation)

Quotes for lr-29:
- "For novelty, it summarizes known aspects of the hypothesis and then judges their novelty based on existing literature." (Accelerating scientific discovery with Co-Scientist, 2026, s8.p7; evidence: own-ablation)
- "the system evaluates the originality of proposed ideas through literature review tools such as Semantic Scholar" (Jr. AI Scientist and Its Risk Report: Autonomous Scientific Exploration from a Baseline Paper, 2025, s3.2.p1; evidence: reported-failure)

Systems combining most of these: Accelerating scientific discovery with Co-Scientist (2026) 4/6; Letting AI Formulate the Research Question: Autonomous Resea (2026) 3/6; NanoResearch: Co-Evolving Skills, Memory, and Policy for Per (2026) 3/6; Dynamic Knowledge Exchange and Dual-diversity Review: Concis (2025) 3/6
Most frequent pairs in one work: idh-12+lr-29 (10), idh-12+rv-11 (7), lr-29+rv-11 (4), idh-13+idh-33 (2)

### 2.5 Step 5: Rank and select

| Id | Technique | Works | Supportive rows | Asserted-only | Not-stated | Reported failure |
|---|---|---|---|---|---|---|
| idh-03 | Single-pass absolute scoring of ideas on a fixed rubric (LLM judge or self-assessment) | 12 | 0 | 0 (0%) | 11 (91%) | 1 |
| idh-43 | Coordinator, shared task state and queue for research directions (including self-organising teams) | 12 | 2 | 0 (0%) | 10 (83%) | 0 |
| idh-04 | Over-generate then screen: a seed pool of N ideas, top-k refined | 11 | 0 | 0 (0%) | 11 (100%) | 0 |
| idh-01 | Pairwise tournament ranking of candidate ideas (Elo, TrueSkill, win rate) | 6 | 0 | 1 (16%) | 5 (83%) | 0 |
| rv-08 | Aggregating several judges: majority, approval, Borda, median or confidence-weighted voting | 5 | 1 | 0 (0%) | 4 (80%) | 0 |
| da-33 | Multi-criteria ranking of candidates by computed domain metrics (Pareto, composite validity, mechanistic ranking score) | 5 | 2 | 0 (0%) | 3 (60%) | 0 |
| ed-30 | Proposal protocols that force coverage and diversity (coverage audit, effect priors, cold-direction bonus, dead-end registry) | 4 | 1 | 0 (0%) | 3 (75%) | 0 |
| idh-02 | Listwise K-way ranking per dimension with weighted combination | 2 | 1 | 1 (50%) | 0 (0%) | 0 |
| rv-07 | Pairwise comparison, Elo and TrueSkill tournaments for ranking outputs or ideas | 2 | 0 | 0 (0%) | 2 (100%) | 0 |

Quotes for idh-03:
- "score each emergence by goal-fit: the geometric mean of three sub-scores (formalism present, quantitative predictions stated, fit to the requested answer-form)" (Introducing the Research Collider: Goal-Conditioned Concept Collision for Grounded, Falsifiable Research Directions, 2026, s4.p3; evidence: reported-failure)
- "evaluated along multiple dimensions, including novelty, feasibility, validity, and scientific excitement" (EvoSci: A Bio-Inspired Multi-Agent Framework for the Evolution of Scientific Discovery, 2026, s3.3.p1; evidence: not-stated)

Quotes for idh-43:
- "a self-organizing agent team for long-running scientific experimentation that coordinates without a central orchestrator agent" (AutoScientists: Self-Organizing Agent Teams for Long-Running Scientific Experimentation, 2026, s1.p3; evidence: own-ablation)
- "Each core task is initiated and led by the Prime Researcher, who analyzes the task context, decomposes it into subtasks, and assigns them to assistant agents based on semantic relevance and skill profiles." (EvoSci: A Bio-Inspired Multi-Agent Framework for the Evolution of Scientific Discovery, 2026, s3.2.p4; evidence: own-ablation)

Quotes for idh-04:
- "generate at least 10 initial seed ideas based on insights from prior research reports, discussions, and the initial topic: {init topic}" (EvoSci: A Bio-Inspired Multi-Agent Framework for the Evolution of Scientific Discovery, 2026, s46.p1; evidence: not-stated)
- "and write at least twelve questions, with no technology or field supplying more than a third of them and no type of study more than half." (Letting AI Formulate the Research Question: Autonomous Research Agents, 2026, s3.2.p4; evidence: not-stated)

Systems combining most of these: MIRA: Towards a General AI Scientist (2026) 3/9; DiscoveryRSI: Recursively Learning to Discover Valuable Hypo (2026) 3/9; EvoSci: A Bio-Inspired Multi-Agent Framework for the Evoluti (2026) 3/9; AutoKD: Autonomous Knowledge Discovery (2026) 3/9
Most frequent pairs in one work: idh-03+idh-04 (4), idh-03+idh-43 (3), idh-01+idh-43 (3), ed-30+idh-04 (2)

### 2.6 Step 6: Specify the hypothesis and design the test

| Id | Technique | Works | Supportive rows | Asserted-only | Not-stated | Reported failure |
|---|---|---|---|---|---|---|
| ed-32 | Experiment budget, stopping and convergence rules | 36 | 2 | 1 (2%) | 33 (91%) | 0 |
| ed-01 | Schema-bound experiment specification or blueprint consumed by an executor | 18 | 0 | 0 (0%) | 18 (100%) | 0 |
| idh-36 | Structured hypothesis or proposal object with pre-declared decision criteria | 12 | 1 | 0 (0%) | 11 (91%) | 0 |
| ed-19 | Pre-declared acceptance criteria and pre-registration-style commitment | 10 | 0 | 0 (0%) | 10 (100%) | 0 |
| ed-21 | Role separation between designing and evaluating, enforced by tool and information access | 10 | 0 | 1 (10%) | 9 (90%) | 0 |
| ed-08 | Dedicated proposal of ablations and baselines from the proposed method | 8 | 0 | 0 (0%) | 8 (100%) | 0 |
| da-16 | Pre-committed success criteria and validation contracts before results are seen | 8 | 0 | 0 (0%) | 8 (100%) | 0 |
| ed-24 | Predicate-, template- and sandbox-enforced constraints on the experimental protocol | 8 | 0 | 0 (0%) | 8 (100%) | 0 |
| rv-32 | Pre-specified decision criteria and role separation between designer and evaluator | 6 | 0 | 0 (0%) | 6 (100%) | 0 |
| idh-38 | Pilot probes and best-supported-group selection among hypotheses | 6 | 0 | 0 (0%) | 6 (100%) | 0 |
| ed-18 | Falsification-oriented test design with an implication (relevance) checker | 3 | 1 | 0 (0%) | 2 (66%) | 0 |
| ed-23 | Held-out validation and admission rule for accepting a hypothesis or principle | 3 | 1 | 1 (33%) | 1 (33%) | 0 |
| ed-40 | Hypothesis record that carries its test plan, decision criteria and alternative explanations | 2 | 1 | 0 (0%) | 1 (50%) | 0 |

Quotes for ed-32:
- "If not, we proceed to the next iteration until a budget is reached." (Automated Hypothesis Validation with Agentic Sequential Falsifications, 2025, s2.4.p9; evidence: own-ablation)
- "enabling precise threshold-based stopping" (PiFlow: Principle-Aware Scientific Discovery with Multi-Agent Collaboration, 2025, s106.p8; evidence: asserted-only)

Quotes for ed-01:
- "A query is an executable analysis designed to discriminate among hypotheses, and its outputs become evidence records that update hypothesis and claim status." (StatefulDiscovery: Evidence-Calibrated Claim Formation in Open-Ended Scientific Discovery, 2026, s3.1.p2; evidence: not-stated)
- "are parsed into a typed specification and compiled through a fixed statistical pipeline without an LLM call" (AutoKD: Autonomous Knowledge Discovery, 2026, s0.15.1.p1; evidence: not-stated)

Quotes for idh-36:
- "Within each investigation, a structured hypothesis set includes a main hypothesis, alternatives, artifact checks, and robustness checks." (StatefulDiscovery: Evidence-Calibrated Claim Formation in Open-Ended Scientific Discovery, 2026, s3.1.p2; evidence: own-ablation)
- "Notably, this sub-hypothesis needs to be falsifiable with clear null and alternative definitions." (Automated Hypothesis Validation with Agentic Sequential Falsifications, 2025, s1.p5; evidence: not-stated)

Systems combining most of these: The Agentic Scientist: Orchestrating Coding Agents for Autom (2026) 8/13; PaperClaw: Harnessing Agents for Autonomous Research and Hum (2026) 7/13; Making AI Scientists Auditable from Evidence to Claim (2026) 6/13; Epsilon: An Autonomous Research Engine with Epistemic Integr (2026) 6/13
Most frequent pairs in one work: ed-01+ed-32 (10), ed-32+idh-36 (8), ed-21+ed-32 (7), ed-08+ed-32 (7)

### 2.7 Step 7: Execute or run the evidence check

| Id | Technique | Works | Supportive rows | Asserted-only | Not-stated | Reported failure |
|---|---|---|---|---|---|---|
| ie-33 | Structured result records and provenance-linked artifacts | 29 | 0 | 0 (0%) | 29 (100%) | 0 |
| ie-31 | Role-specialised agent pipelines with transition rules and minimal toolsets | 27 | 1 | 1 (3%) | 25 (92%) | 0 |
| ie-12 | Container or subprocess sandbox with resource, network and time limits | 26 | 0 | 0 (0%) | 26 (100%) | 0 |
| ie-01 | Error-trace-fed regenerate or patch loop with a retry cap | 25 | 1 | 0 (0%) | 23 (92%) | 1 |
| ie-30 | Delegation of implementation to an external coding agent under a spec | 17 | 3 | 0 (0%) | 14 (82%) | 0 |
| ie-17 | Scale ladder: dry run, smoke test and reduced scale before full execution | 9 | 0 | 1 (11%) | 8 (88%) | 0 |
| da-27 | Sandboxed execution with real-output capture and result provenance (Docker sandbox, code-as-action kernels, artifact evidence) | 9 | 0 | 0 (0%) | 9 (100%) | 0 |
| ie-13 | Hidden evaluator, controller-owned results and secure grading | 8 | 0 | 1 (12%) | 7 (87%) | 0 |
| ie-41 | Cost and budget control of execution | 8 | 1 | 0 (0%) | 7 (87%) | 0 |
| ie-18 | Independent review of the execution plan or code before it runs | 5 | 0 | 0 (0%) | 5 (100%) | 0 |
| ie-35 | Reproduce a baseline first, then modify | 4 | 0 | 0 (0%) | 4 (100%) | 0 |
| ie-34 | Harness-enforced dev/test split and held-out re-execution | 4 | 0 | 0 (0%) | 4 (100%) | 0 |

Quotes for ie-33:
- "Record code outputs and evidence records with write-experiment." (StatefulDiscovery: Evidence-Calibrated Claim Formation in Open-Ended Scientific Discovery, 2026, s38.p4; evidence: not-stated)
- "of every completed experiment with outcome, metric delta, and training diagnostics" (AutoScientists: Self-Organizing Agent Teams for Long-Running Scientific Experimentation, 2026, s3.2.p8; evidence: not-stated)

Quotes for ie-31:
- "Our multi-agent system uses a Leader-Worker pattern where the Leader agent makes strategic decisions and dispatches tasks to specialized Worker agents." (Deep Researcher Agent: An Autonomous Framework for 24/7 Deep Learning Experimentation with Zero-Cost Monitoring, 2026, s3.4.p1; evidence: asserted-only)
- "Each subtask moves on to the next subtask sequentially upon completion." (Agent Laboratory: Using LLM Agents as Research Assistants, 2025, s3.3.1.p1; evidence: not-stated)

Quotes for ie-12:
- "The system operated within a local Docker container on an Apple M2 Pro, constrained to 12 CPU cores" (Autonomous Research Project Management as an Agent Skill: A Case Study in Exact Spectral Spatial Regression, 2026, s2.2.2.p1; evidence: not-stated)
- "STATEFULDISCOVERY runs through OpenCode 4 in a Docker sandbox." (StatefulDiscovery: Evidence-Calibrated Claim Formation in Open-Ended Scientific Discovery, 2026, s11.p8; evidence: not-stated)

Systems combining most of these: AutoResearch: Alignment Laziness in Automated Research Agent (2026) 8/12; AutoResearchClaw: Self-Reinforcing Autonomous Research with  (2026) 7/12; The Agentic Scientist: Orchestrating Coding Agents for Autom (2026) 6/12; Toward Generalist Autonomous Research via Hypothesis-Tree Re (2026) 6/12
Most frequent pairs in one work: ie-12+ie-33 (13), ie-31+ie-33 (13), ie-01+ie-33 (13), ie-01+ie-31 (12)

### 2.8 Step 8: Analyse

| Id | Technique | Works | Supportive rows | Asserted-only | Not-stated | Reported failure |
|---|---|---|---|---|---|---|
| da-26 | Analysis agent converting execution records into a structured report or evaluation record | 20 | 0 | 0 (0%) | 20 (100%) | 0 |
| da-01 | Agent-executed statistical test of a hypothesis on a dataset (verification program V_D) | 15 | 1 | 0 (0%) | 14 (93%) | 0 |
| da-28 | Automated component ablation of the discovered or generated method | 12 | 0 | 0 (0%) | 12 (100%) | 0 |
| da-15 | Claim-evidence audit and claim weakening before writing (traceable numbers, five claim labels, independent audit agent, literature grounding) | 8 | 2 | 0 (0%) | 6 (75%) | 0 |
| da-09 | Multi-seed replication and aggregation of experiment results (replication nodes, aggregation scripts, score-tracking statistics) | 7 | 0 | 0 (0%) | 7 (100%) | 0 |
| da-08 | Resampling and classical-inference reporting in written results (bootstrap CI, split conformal, Steiger Z, IQM, t/Wilcoxon/sign tests) | 7 | 0 | 0 (0%) | 7 (100%) | 0 |
| da-21 | Data profiling, structured data report and exploratory analysis before hypothesis testing | 7 | 2 | 0 (0%) | 5 (71%) | 0 |
| da-12 | Independent evaluator: role separation or fresh-context critic that cannot change the design or inherit the producer's reasoning | 5 | 0 | 0 (0%) | 5 (100%) | 0 |
| da-03 | Held-out split replication with effect-size and p-value thresholds (and FDR on the accepted set) | 2 | 0 | 0 (0%) | 2 (100%) | 0 |
| da-07 | Test-selection and assumption-check rules (normality gate, corrected resampling tests, assumption verification tools) | 2 | 0 | 0 (0%) | 2 (100%) | 0 |
| da-13 | Multi-role critic panel or dialogue interpreting results | 2 | 1 | 0 (0%) | 1 (50%) | 0 |
| da-02 | Sequential falsification testing with e-value aggregation and Type-I control (Popper) | 1 | 1 | 0 (0%) | 0 (0%) | 0 |

Quotes for da-26:
- "Experiment Analyst: Analyzes code execution output." (AutoDiscovery: Open-ended Scientific Discovery via Bayesian Surprise, 2025, s1.2.2.p7; evidence: not-stated)
- "It also records an investigation-level assessment with the best-supported explanation, remaining concerns, resolution confidence, red flags, and recommendations for next steps." (StatefulDiscovery: Evidence-Calibrated Claim Formation in Open-Ended Scientific Discovery, 2026, s3.2.2.p5; evidence: not-stated)

Quotes for da-01:
- "Without explicit prompting, it selects suitable tests" (Automated Hypothesis Validation with Agentic Sequential Falsifications, 2025, s3.p5; evidence: own-ablation)
- "composed of LLMs that collaboratively propose experiment plans, write and execute Python code to conduct those experiments, critique and fix mistakes, and analyze their results" (AutoDiscovery: Open-ended Scientific Discovery via Bayesian Surprise, 2025, s2.2.p2; evidence: not-stated)

Quotes for da-28:
- "an agent then proposes baselines and ablations with explicit hypotheses and implementation plans, where each ablation must isolate an innovation introduced by the selected program" (The Agentic Scientist: Orchestrating Coding Agents for Automated Scientific (Co-)Discovery, 2026, s3.4.p3; evidence: not-stated)
- "Stage 4: Systematic ablation studies using same datasets as Stage 3" (Build Your Personalized Research Group: A Multiagent Framework for Continual and Interactive Science Automation, 2025, s0.11.2.p1; evidence: not-stated)

Systems combining most of these: StatefulDiscovery: Evidence-Calibrated Claim Formation in Op (2026) 4/12; Epsilon: An Autonomous Research Engine with Epistemic Integr (2026) 4/12; ResearchEVO: An End-to-End Framework for Automated Scientifi (2026) 3/12; Accelerating Scientific Discovery with Autonomous Goal-evolv (2025) 3/12
Most frequent pairs in one work: da-01+da-26 (4), da-09+da-28 (4), da-01+da-21 (3), da-15+da-26 (3)

### 2.9 Step 9: Verify and review

| Id | Technique | Works | Supportive rows | Asserted-only | Not-stated | Reported failure |
|---|---|---|---|---|---|---|
| rv-34 | Failure-triggered routing to the responsible earlier stage, bounded loops and stopping rules | 20 | 1 | 0 (0%) | 19 (95%) | 0 |
| rv-10 | Review of plans and implementation fidelity before or after execution | 17 | 1 | 0 (0%) | 16 (94%) | 0 |
| rv-43 | Append-only action ledger, provenance and audit trails as the verification substrate | 15 | 0 | 0 (0%) | 15 (100%) | 0 |
| rv-26 | Deterministic stage-exit gates and code-checked predicates | 14 | 1 | 0 (0%) | 13 (92%) | 0 |
| rv-30 | Evaluator isolation and anti-tampering of the evaluation and run environment | 11 | 0 | 1 (9%) | 9 (81%) | 1 |
| rv-18 | Typed claim-status adjudication against declared evidence (supported, weakened, refuted, inconclusive) | 8 | 1 | 0 (0%) | 7 (87%) | 0 |
| rv-22 | Post-hoc reference existence and metadata verification against scholarly APIs | 6 | 1 | 0 (0%) | 5 (83%) | 0 |
| rv-20 | Post-hoc matching of numeric claims to a registry, logs or raw artifacts | 5 | 2 | 0 (0%) | 3 (60%) | 0 |
| rv-17 | Statistical error control and anti-HARKing wrappers around hypothesis validation | 4 | 1 | 0 (0%) | 3 (75%) | 0 |
| rv-24 | Citation-support checks and claim-level grounding labels on generated text | 4 | 1 | 0 (0%) | 3 (75%) | 0 |
| rv-19 | Typed claim-evidence chain audits (claim drift, relation checks, chain-of-evidence) | 3 | 1 | 0 (0%) | 2 (66%) | 0 |

Quotes for rv-34:
- "A Meta-Review Agent oversees this cycle, triggering recursive refinement loops until rigorous acceptance criteria are satisfied." (ScientistTwo: Pioneering the Human Knowledge Frontier with Autonomous AI, 2026, s1.2.p10; evidence: own-ablation)
- "On failure, the manager orchestrates backward routing, superseding invalid downstream issues, wiping invalidated intermediate artifacts, and re-entering prior stages with structured critique." (Autonomous Research Project Management as an Agent Skill: A Case Study in Exact Spectral Spatial Regression, 2026, s2.1.2.p3; evidence: not-stated)

Quotes for rv-10:
- "we introduce a relevance checker, an LLM-based function" (Automated Hypothesis Validation with Agentic Sequential Falsifications, 2025, s3.p4; evidence: own-ablation)
- "Experiment Reviewer: Reviews experiment results for alignment with original experiment plan and ability to support validation of the hypothesis." (AutoDiscovery: Open-ended Scientific Discovery via Bayesian Surprise, 2025, s1.2.2.p8; evidence: not-stated)

Quotes for rv-43:
- "Every stage transition, code diff, reviewer score sheet, and execution log was committed sequentially to disk" (Autonomous Research Project Management as an Agent Skill: A Case Study in Exact Spectral Spatial Regression, 2026, s2.2.7.p1; evidence: not-stated)
- "each API call with its request, response and cost;" (Letting AI Formulate the Research Question: Autonomous Research Agents, 2026, s3.3.p5; evidence: not-stated)

Systems combining most of these: OmniScientist: An Omni-Modal Omni-Discipline AI Scientist (2026) 6/11; AutoResearchClaw: Self-Reinforcing Autonomous Research with  (2026) 5/11; ScientistOne: Towards Human-Level Autonomous Research via Ch (2026) 5/11; EviGraph: Evidence-Guided Autonomous Research Agents (2026) 5/11
Most frequent pairs in one work: rv-10+rv-34 (9), rv-34+rv-43 (7), rv-26+rv-43 (7), rv-18+rv-34 (5)

### 2.10 Step 10: Record the outcome, memory, feedback and steering

| Id | Technique | Works | Supportive rows | Asserted-only | Not-stated | Reported failure |
|---|---|---|---|---|---|---|
| idh-34 | Persistent typed insight graph, world model or shared state across rounds | 29 | 10 | 1 (3%) | 18 (62%) | 0 |
| da-19 | Run-level memory of analysis outcomes (world model, experimental journal, time-decayed lesson store, trace compression) | 26 | 5 | 1 (3%) | 20 (76%) | 0 |
| ed-29 | Persistent discovery state or memory that steers what to try next | 26 | 5 | 1 (3%) | 20 (76%) | 0 |
| idh-32 | Experiment-outcome feedback into the next round of ideas | 24 | 3 | 0 (0%) | 21 (87%) | 0 |
| da-14 | Verdict-to-action routing after analysis (proceed / refine / pivot, continue / revise / stop) | 22 | 1 | 1 (4%) | 20 (90%) | 0 |
| idh-41 | Human steering of goals, ideas and review | 22 | 1 | 0 (0%) | 21 (95%) | 0 |
| idh-33 | Failure and dead-end memory consulted before proposing | 14 | 3 | 0 (0%) | 11 (78%) | 0 |
| ed-33 | Verdict-driven redesign of the experiment (revise, refine, pivot, stop) | 14 | 2 | 0 (0%) | 12 (85%) | 0 |
| idh-14 | Code-enforced or rule-based stage gates (idea check, hard gate, accept/revise/reject) | 11 | 1 | 0 (0%) | 10 (90%) | 0 |
| da-17 | Result-category feedback into the next generation round (improvement/maintenance/decline, Reflect guidance, ranked outcomes) | 8 | 2 | 1 (12%) | 5 (62%) | 0 |
| rv-42 | Admission gate and critic for shared memory, archives and skill libraries | 7 | 0 | 1 (14%) | 6 (85%) | 0 |
| idh-22 | Hypothesis/plan tree or DAG with parent-child lineage and back-propagated insights | 6 | 2 | 0 (0%) | 4 (66%) | 0 |
| idh-35 | Periodic meta-review or meta-reflection over accumulated claims | 4 | 2 | 0 (0%) | 2 (50%) | 0 |

Quotes for idh-34:
- "The agent externalizes the evolving investigation state as persistent objects tracking observations, active investigations, collected evidence, and the evidential status of candidate claims." (StatefulDiscovery: Evidence-Calibrated Claim Formation in Open-Ended Scientific Discovery, 2026, s1.2.p5; evidence: own-ablation)
- "The system maintains a shared state accessible to all agents, consisting of four layers" (AutoScientists: Self-Organizing Agent Teams for Long-Running Scientific Experimentation, 2026, s3.2.p8; evidence: own-ablation)

Quotes for da-19:
- "The agent externalizes the evolving investigation state as persistent objects tracking observations, active investigations, collected evidence, and the evidential status of candidate claims." (StatefulDiscovery: Evidence-Calibrated Claim Formation in Open-Ended Scientific Discovery, 2026, s1.2.p5; evidence: own-ablation)
- "After each experiment, the system stores an episodic unit containing the attempted method $m$, extracted metrics $y$, and an improvement judgment." (InternAgent-1.5: A Unified Agentic Framework for Long-Horizon Autonomous Scientific Discovery, 2026, s2.4.2.p1; evidence: own-ablation)

Quotes for ed-29:
- "Under this framework, the status of emerging claims actively directs" (StatefulDiscovery: Evidence-Calibrated Claim Formation in Open-Ended Scientific Discovery, 2026, s1.2.p7; evidence: own-ablation)
- "After each experiment, the system stores an episodic unit containing the attempted method $m$, extracted metrics $y$, and an improvement judgment." (InternAgent-1.5: A Unified Agentic Framework for Long-Horizon Autonomous Scientific Discovery, 2026, s2.4.2.p1; evidence: own-ablation)

Systems combining most of these: AutoKD: Autonomous Knowledge Discovery (2026) 9/13; AlphaLab: Autonomous Multi-Agent Research Across Optimizatio (2026) 7/13; AutoResearchClaw: Self-Reinforcing Autonomous Research with  (2026) 7/13; Epsilon: An Autonomous Research Engine with Epistemic Integr (2026) 7/13
Most frequent pairs in one work: da-19+ed-29 (22), da-19+idh-34 (20), ed-29+idh-34 (19), ed-29+idh-32 (14)

## 3. Recommended choices for our engine, per step

Column key. Evidence: works and supportive rows from section 2 (all are authors' own, none independent). Fit: rigour rules and modules. Who: judgement (a Claude session through MCP) or computable by the platform. Test: whether the step works in a review project such as agentic-science (R) or needs a project that runs experiments (X). "Class" follows the earlier plan: EXISTS, ADOPT-FIRST, ADOPT-LATER, REJECT, N/A (not applicable to a review project, or needs a model call or training inside the platform).

### Step 1: Ground in the literature and gaps

- Choose: idh-18 with lr-25 (gap and limitation extraction; one approach seen from two stages: 14 and 8 works, 1 supportive row each), idh-17 with lr-21 and lr-28 (pre-built graph and typed memory), idh-19 (search inside the loop), idh-46 with lr-06 (seed anchoring), lr-34 (cross-field mechanism transfer: 5 works, 2 supportive of 5, the best ratio in this step) as an optional source. lr-01 and lr-16 (retrieval, PDF parsing) are acquisition, already done by `search_run`, `fulltext_fetch` and conversion; class EXISTS.
- Evidence: weak but consistent (idh-18+lr-01+lr-19+lr-25 co-occur in 8 works). Fit: leads cite triggers (R-120); claims digest and the technique landscape (`technique_gaps`, `technique_combinations`, per the earlier plan) supply citable material; interpretations stay outside evidence (R-87). The missing piece is a citable trigger kind for a claims row (earlier plan, section 3a).
- Who: computable (finders, `finder_gaps`, `match_query` transfer flag, claims digest, `corpus_search`); Claude reads the passages. Test: R, fully; this step is literature by nature.

### Step 2: Generate or over-generate candidates

- Choose: idh-04 (over-generate a bounded pool, then screen) and idh-40 (combination, collision and challenge candidates from `technique_combinations`, `match_query`); idh-05 crossover is covered by combination candidates (the two quoted rows, EvoSci and Co-Scientist, are own-ablation). Later: idh-08 (role panel, as separate sessions on one sparring sheet), idh-11, idh-15, idh-28, idh-39 as skill text.
- Evidence: idh-04 11 works, 0 supportive; idh-40 8 works, 4 supportive; idh-05 10 works, 4 supportive (the generation techniques with stated own tests are the combination and crossover ones, not the pool-then-screen one). Fit: `rf-ideate` words candidates and cites triggers; `lead_record` enforces at most 600 characters and a resolvable trigger; the lead cap bounds the pool (volume knob).
- Who: the candidates' sources are computed; the wording is a Claude session. Test: R.

### Step 3: Critique and refine

- Choose: idh-07 (generator-critic loop, 19 works, 2 supportive; EXISTS as `hypothesis_review_next`, `hypothesis_review`, `rf-critic`), made strict by rv-09 (a fresh-context critic, or one from another model family; 7 works, 1 supportive) and by ed-03 (the same critic loop on the test plan before anything runs, 12 works, 1 supportive). Later: idh-10 (second model, votes counted by the platform), rv-04 (task-specific rubric kept categorical), rv-02 (panel with a meta-reviewer).
- Reject: rv-14 (a critic or reward model used as fitness inside the generation loop; 8 works). Reason: the critique becomes a reward that the generator optimises, which couples proposer and evaluator and invites scalar scores (R-51, and the earlier plan's rejection of idh-03; also R-87 for model beliefs). idh-07 and rv-14 co-occur in 7 works, so the published systems often bundle a good loop with a reward; we take the loop and leave the reward.
- Fit: R-51 (critic sees artefacts, not the proposer's reasoning). Who: judgement (a separate session; model recorded in provenance). Test: R.

### Step 4: Novelty and prior check

- Choose: one technique seen from three stages: idh-12 (17 works, 2 supportive), lr-29 (11, 2) and rv-11 (10, 3); they co-occur (idh-12+lr-29 in 10 works). Implement as: computed overlap of the lead with the corpus (shared triggers, `corpus_search` keyword and vector side by side, `technique_neighbors`) plus the prior list (idh-33, failed directions) and the diversity filter idh-13 against promoted leads; Claude reads the passages and states what was found and "not found in this corpus", never "novel". rv-12 (embedding distance) is the computed part if vectors are available (decision 140).
- Evidence: the strongest stated-evidence cluster of the lead half (several own-ablation rows: Co-Scientist, OmniScientist). The literature also shows the risk: lr-29 has one `reported-failure` row (Jr. AI Scientist report). Fit: R-120 and the prior list exist; the overlap result is an `interpretation` unless it cites rows.
- Who: computed first, then judgement. Test: R.

### Step 5: Rank and select

- Choose: first a computed order (idh-04 screen: number of independent triggers, overlap with the prior, age of the basis; da-33 shows the form: multi-criteria ranking by computed metrics, Pareto, not a single score), then the human selects at `lead_decide`. Later, as a recorded suggestion set with provenance: idh-01 (pairwise, 6 works) and idh-02 (listwise, 2 works), with rv-08 (aggregation of several judges, counted by the platform) and rv-07 (Elo, 2 works).
- Reject: idh-03 (absolute scoring on a rubric, 12 works; one `reported-failure` row in the Research Collider paper). Same reason as in the earlier plan: scalar self-assessment breaks R-51 and reads as calibrated.
- Fit: `lead_list`, `lead_decide`; the existing `ranking_compute` tool is **to check** for fit with the ordering measure. Who: computed order, optional judgement for suggestion sets. Test: R.

### Step 6: Specify the hypothesis and design the test

- Choose: idh-36 with ed-40 (a hypothesis object that carries its test plan, decision criteria and alternatives: `HypothesisSpec`, frozen `H@`, R-50), ed-19, rv-32 and da-16 (criteria declared before results: decision rule from a fixed menu, falsifier sentence printed by the platform), ed-01 (schema-bound experiment spec: `experiment_design`, `E@`), ed-21 (designer and evaluator separated: R-51), ed-23 (held-out admission: the dev/confirmatory split and unlock nonce, R-123), ed-32 (budget, stopping and convergence rules; 36 works, the most common design technique: the budget and test-access limit of engine G5). Adopt first as critic checklist: ed-18 (falsification-oriented design with a relevance check: does the test bear on the claim). Later: ed-08 (propose ablations and baselines; baselines must reproduce, R-122).
- Evidence: ed-32 36 works, 2 supportive; idh-36 12 works, 1 supportive; the pre-declaration approaches have 0 supportive rows, which is expected (the claim is a discipline, not a measured effect). Fit: nearly all EXISTS.
- Who: platform validates and freezes; Claude drafts. Test: kind decides. Experiment kind (X): ed-01, ed-32, ed-23, ed-08 need comparability keys, a baseline resolving to a final evidence row, and runs elsewhere. Literature kind (R, with a caveat): idh-36, ed-40, ed-19 fit unchanged (a window and a declared search registered before looking); the earlier plan's finding stands that evaluation returns `insufficient-evidence` until later rows with comparability keys exist.

### Step 7: Execute or run the evidence check

- Experiment kind (X only): the platform never executes (decision 67); a session or external executor runs the design and the platform ingests runs (`xruns`, `reproduction`, `xrun_accounting`). Adopt as guidance for `rf-run`, not as platform code: ie-35 (reproduce the baseline first, 4 works; R-122), ie-34 (dev/test split enforced by the harness; R-123), ie-33 (structured result records with provenance; 29 works, the most common; this is run ingestion), ie-17 (dry run and smoke test before scale), ie-41 (budget control). ie-12 (sandbox), ie-01 (error-trace repair loop with retry cap), ie-30/ie-31 (delegate to a coding agent under a spec) are executor concerns outside the platform: N/A to the platform, relevant to the executor. ie-13 (hidden evaluator) and ie-15 (protected evaluation files) bear on R-123 and apply when we do run experiments.
- Literature kind (R): the "run" is the declared search after registration plus screening of what it returns (`search_run`, `screen_*`, `feed_run`/`watch_run`); no ie approach is needed. This is the only testing the agentic-science pilot can do.
- Evidence: all ie rows are mostly `not-stated` (89%); ie has the fewest supportive rows of any stage (6%). Who: judgement and external execution (X); computed search plus human or Claude screening (R).

### Step 8: Analyse

- Choose: the outcome is computed by the registered rule (R-121; `evaluation.py`), so analysis techniques that let an agent choose the test after seeing data (da-01 in its free form: 15 works) may be used for exploratory runs only, never for the confirmatory outcome. For confirmatory runs adopt the constrained forms: da-06 (fixed statistical primitives), da-07 (test-selection and assumption-check rules), da-09 (multi-seed replication: minimum seeds, engine G5), da-03 (held-out replication with effect-size thresholds). Adopt later: da-02 (sequential falsification with e-value type-I control, 1 work, supportive) and da-28 (component ablation, 12 works; reported own and kept apart from reported results, R-125). da-12 (independent evaluator) restates R-51. da-26 (analysis agent writes a structured report; 20 works, 0 supportive) is a session act recorded as an `interpretation` beside the computed outcome. da-15 (claim-evidence audit and claim weakening) maps to the draft and manuscript verification steps.
- Reject: da-05 (Bayesian-surprise scoring of an executed hypothesis), with rv-13 and ed-14 (surprise-based reward and search): a model-stated belief shift cannot set an outcome (R-121, R-87; same reason as idh-23).
- Test: X for da-01, da-09, da-28, da-03 (they need executed runs). R: da-36 (cross-paper discrepancy detection) is the literature analogue and is `finder_contradictions` over reported rows; only 1 work in the corpus, so the corpus gives little to copy.
- Who: computable by the platform (outcome, bootstrap, thresholds) plus one reporting session.

### Step 9: Verify and review

- Choose: rv-26 (deterministic stage-exit gates and code-checked predicates; 14 works; `hypothesis_gates.py`, the quality regime, `check`), rv-18 (typed claim-status from declared evidence; `conclusion_status`), rv-43 (append-only ledger and audit trail: the event store itself), rv-30 (evaluator isolation: unlock nonce), rv-17 (anti-HARKing wrappers: registration freeze; error control adopt-later), rv-19 and rv-20 (claim-evidence chain audits and matching numbers to a registry: draft and manuscript verification), rv-22 (reference existence: `references`), rv-34 (failure-triggered routing to the responsible earlier stage with bounded loops; 20 works, the most common approach here). Adopt rv-34 as a human-bounded route: a failed check proposes "return to design" or "return to lead", the human decides; no automatic loop. rv-10 (review of plan and implementation fidelity) extends `rf-critic` to a fidelity review of an ingested run against its frozen design (X only).
- Not applicable: rv-01 and rv-36 (manuscript reviewers, revision on review feedback) belong to writing; rv-38 (safety screening) is out of scope for a review project (a safety screen exists as a discard reason, per the earlier plan).
- Evidence: rv has 14% supportive rows, the second best after idh; rv-11 and rv-38 lead (3 each). Who: computable gates plus a critic session. Test: R for gates, ledger, claim audits, reference checks; X for rv-10 fidelity, rv-30 isolation of an executed run.

### Step 10: Record the outcome, memory, feedback and steering

- Choose: idh-32 (outcome feedback into the next round: 24 works; the registry and prior list), idh-33 (dead-end memory; failed directions, R-52 and R-124, a registry row never removed), idh-34 with da-19, ed-29, lr-28 (persistent typed state; 29, 26, 26 and 9 works; da-19 and idh-34 together carry the most supportive rows of the whole loop, 5 and 10; ours is event-sourced, projected, human-confirmed), idh-41 and idh-14 (human steering and code-enforced gates, EXISTS), rv-42 (admission gate for shared memory: confirmation of assertions). Adopt da-14 and ed-33 (verdict-driven proceed, refine, pivot or stop; 22 and 14 works) as a suggestion set that the human decides at a gate, not an automatic redesign. Later: idh-35 (periodic meta-review as an `interpretation`), da-17 (result-category feedback), idh-24 and idh-25 (outcome-conditioned filtering, reliability measures) once outcomes exist.
- Fit: R-125 (own results apart from reported results) is the rule these techniques most easily break: published systems merge their own run results into their memory. Keep two classes. Who: computed registry and prior list; judgement only for the suggestion set. Test: R (a literature-window outcome is recorded the same way); X outcomes enter identically.

## 4. The composite recipe

### 4.1 The flow (H marks a human decision point)

Every H is a point where the researcher may accept, skip, swap the technique, or override; the platform records the choice with its reason (provenance on every agent-written event). Between the H points the platform computes and a Claude session judges.

1. Ground (idh-18, lr-25, idh-17, idh-19, idh-46, lr-34). The platform assembles the material (claims digest, finders, technique candidates, `corpus_search`); a session reads it. H1: choose the sources and the technique for this run (which of claims, finders, technique candidates, graph, cards, feed, inbox, seeds).
2. Generate (idh-04, idh-40). A session words a bounded pool of candidate leads from the computed sources; each cites at least one trigger (R-120). H2: set the pool size and the generation technique (combination, challenge, gap, cross-field, free sparring in `rf-chat`).
3. Critique (idh-07, rv-09, ed-03). An independent session reviews each candidate artefact (R-51); revision is a new draft that supersedes the old. H3: choose the critic (fresh session, other model), the number of rounds (human-bounded) and whether the test plan is also critiqued.
4. Novelty and prior check (idh-12 = lr-29 = rv-11, idh-13, idh-33). The platform computes overlap with the corpus, the prior list and diversity; a session reports what was found, "not found in this corpus", never "novel". H4: accept the overlap reading, merge or discard duplicates.
5. Rank and select (computed order; idh-01, idh-02, rv-08 as an optional suggestion set; idh-03 refused). H5: choose the ordering measure and promote, park or discard (`lead_decide`).
6. Specify and design (idh-36, ed-40, ed-19, rv-32, da-16, ed-01, ed-21, ed-23, ed-32, ed-18). A session drafts the hypothesis spec and the test; the platform validates and prints the falsifier; a second session critiques the design. H6: choose the test kind (literature window or experiment), the decision rule from the menu, seeds and budget; register and freeze (`hypothesis_register`, `experiments.freeze_unlock`, human in pilot and systematic modes).
7. Execute or run the evidence check (literature kind: declared search and screening; experiment kind: external executor with ie-35, ie-34, ie-33, ie-17, ie-41; the platform ingests). H7: authorise the run and accept the baseline reproduction (R-122: a non-reproduced baseline accepted by a human flags every dependent outcome).
8. Analyse (da-06, da-07, da-09, da-03 confirmatory; da-01, da-28, da-26 exploratory; da-36 literature analogue). The platform computes the outcome by the registered rule (R-121); a session may add an `interpretation`. H8: none over the outcome (no actor sets it); the researcher may only record a deviation (R-124) or order a further run.
9. Verify and review (rv-26, rv-18, rv-43, rv-30, rv-17, rv-19, rv-20, rv-22, rv-34). The platform runs the gates and claim audits; a critic session checks the fidelity of an executed run (rv-10). H9: accept, or return to step 6 or step 2 (rv-34, bounded).
10. Record and feed back (idh-32, idh-33, idh-34, da-19, ed-29, da-14, ed-33, idh-41, idh-14). The outcome, the failed direction and the new lead enter the registry and the prior list; the next-round suggestion (proceed, refine, pivot, stop) is a suggestion set. H10: decide the next round; optionally order a meta-review (idh-35).

### 4.2 Knobs that must be runtime choices (not fixed)

| Knob | Step | Options seen in the mined techniques |
|---|---|---|
| Which sources feed leads | 1 | claims digest, gap finders, technique candidates (gap, combination, challenge), graph, cards, feed, inbox, seeds, free sparring |
| Number of candidates in the pool | 2 | the pool size of idh-04 (the corpus shows "at least 10" and "at least twelve"; no evidence for a best number) |
| Generation technique | 2 | combination, cross-field transfer, challenge, debate panel, evolutionary operators |
| Which critic | 3 | fresh session, other model family, panel with meta-reviewer; rounds; critic also on the test plan |
| Overlap and diversity measures | 4 | keyword, vector, technique distance, shared triggers |
| Ordering measure | 5 | triggers, support, overlap, age; later a pairwise or listwise suggestion set |
| Test kind | 6 | literature window, experiment design, a computed statement (not a hypothesis about nature) |
| Decision rule, seeds, budget, confidence | 6 | the fixed rule menu; engine plan G5 defaults |
| Executor | 7 | none (literature), external coding session, human lab run |
| Confirmatory or exploratory analysis | 8 | constrained analysis versus free-form agent-chosen tests (exploratory only) |
| Gate policy per step | all | human, or off where the mode allows; a gate that does not stop is a defect (idh-14) |
| Loop bound | 3, 9, 10 | rounds, budget and stop rule, set by the human |

### 4.3 What we already have, what must be built, what to reject

| Class | Technique ids | Note |
|---|---|---|
| Already have (to check in code; unused on the pilot) | idh-07, idh-14, idh-17, idh-19, idh-20, idh-22, idh-32, idh-33, idh-34, idh-36, idh-38, idh-41, idh-43, idh-46, idh-47, idh-49; ed-01, ed-02, ed-19, ed-21, ed-23, ed-40; ie-33 (run ingestion), ie-34, ie-35 (reproduction), ie-41; da-16, da-19; rv-26, rv-18, rv-19, rv-20, rv-22, rv-30, rv-43, rv-42; lr-01, lr-16, lr-21, lr-28, lr-30 | Names from the earlier plan and the engine plan; the ed, ie, da and rv mappings are my reading of module names and need a check |
| Build in the first slice | idh-18 with lr-25 (citable trigger for claims rows); idh-40 and idh-05 as combination and challenge candidates; idh-04 (bounded pool with a computed screen); idh-12 with lr-29 and rv-11, idh-13 (computed overlap, diversity); rv-09 (critic from a fresh session, model recorded); ed-18 (relevance check as critic checklist); da-36 as a finder reading; computed ordering (da-33 form) | All computable or skill text; no new rule |
| Build later | idh-10, idh-01, idh-02, rv-07, rv-08 (suggestion sets); idh-08, idh-11, idh-15, idh-28, idh-39 (skill text); idh-35 (meta-review); da-02, da-03, da-09 (extend `evaluation.py`); da-14 and ed-33 (verdict suggestion set); rv-34 (bounded return route); rv-10 (fidelity review of an ingested run); ed-08 (baseline and ablation proposal); da-17, idh-24, idh-25 | After one run shows the volume, and after outcomes exist |
| Guidance for an external executor only (X) | ie-12, ie-01, ie-17, ie-30, ie-31, ie-13, ie-15, da-27, da-01 (exploratory), da-28 | Not platform code (decision 67) |
| Reject | idh-03 (absolute scoring); idh-23, da-05, rv-13, ed-14 (Bayesian surprise as reward); rv-14 (critic as reward in the generation loop); free-form agent-chosen tests as the confirmatory outcome (da-01 without a registered rule) | R-51, R-87, R-121 |
| Not applicable | training and reward learning (idh-29, idh-30, idh-31, lr-38); execution-fitness search (idh-06, ie-07, ie-08); tree and evolutionary search needing thousands of evaluations (idh-21, ed-10, ie-05, ie-09); persona teams (idh-09, lr-33); manuscript reviewing and revision (rv-01, rv-36); safety screening (idh-42, rv-38, ed-35) | Needs a model call or training in the platform, or execution, or is out of scope |

## 5. Reference systems from the corpus

Ranking by the number of distinct approaches across lr, idh, ed, ie, da and rv in the core layer (computed). Works that use many approaches are often long, detailed papers, so the count measures breadth of description as well as combination. "Per step" gives, for steps 1 to 10 in order, how many of that step's listed approaches (section 2) the work uses.

| Rank | System (work title, year) | Approaches | lr / idh / ed / ie / da / rv | Per step 1 to 10 |
|---|---|---|---|---|
| 1 | Making AI Scientists Auditable from Evidence to Claim, 2026 | 50 | 13 / 11 / 6 / 11 / 5 / 4 | 7,2,1,2,1,6,3,3,4,3 |
| 2 | The Agentic Scientist: Orchestrating Coding Agents for Automated Scientific (Co-)Discovery, 2026 | 49 | 5 / 7 / 12 / 9 / 5 / 11 | 2,0,3,0,1,8,6,3,4,6 |
| 3 | AutoResearchClaw: Self-Reinforcing Autonomous Research with Human-AI Collaboration, 2026 | 43 | 4 / 6 / 8 / 12 / 6 / 7 | 3,1,1,1,0,5,7,3,5,7 |
| 4 | AI-Supervisor: Autonomous AI Research Supervision via a Persistent Research World Model, 2026 | 34 | 11 / 9 / 6 / 2 / 4 / 2 | 6,2,0,1,2,1,1,3,1,6 |
| 5 | Toward Generalist Autonomous Research via Hypothesis-Tree Refinement, 2026 | 32 | 0 / 7 / 6 / 11 / 4 / 4 | 1,0,0,1,1,5,6,1,3,6 |
| 6 | AutoSOTA: An End-to-End Automated Research System for State-of-the-Art AI Model Discovery, 2026 | 32 | 3 / 5 / 4 / 15 / 1 / 4 | 1,1,0,0,2,1,5,0,3,5 |
| 7 | OmniScientist: An Omni-Modal Omni-Discipline AI Scientist, 2026 | 31 | 1 / 7 / 3 / 7 / 4 / 9 | 1,1,0,2,2,3,5,2,6,1 |
| 8 | Epsilon: An Autonomous Research Engine with Epistemic Integrity for Scientific Discovery, 2026 | 29 | 3 / 2 / 6 / 5 / 9 / 4 | 1,0,0,1,0,6,3,4,2,7 |
| 9 | ScientistTwo: Pioneering the Human Knowledge Frontier with Autonomous AI, 2026 | 29 | 3 / 7 / 4 / 4 / 4 / 7 | 3,1,1,2,1,3,4,1,3,4 |
| 10 | PaperClaw: Harnessing Agents for Autonomous Research and Human-in-the-Loop Refinement, 2026 | 29 | 3 / 5 / 6 / 7 / 4 / 4 | 2,0,0,0,0,7,3,1,3,5 |

EviGraph: Evidence-Guided Autonomous Research Agents (2026) also has 29 approaches (rv 9, ie 6, ed 5, da 4, idh 4, lr 1) and is tied with ranks 8 to 10; the order inside the tie is arbitrary and I listed three of the four. Approach ids of the top four works:

- Making AI Scientists Auditable: lr-01, 07, 12, 14, 16, 18, 19, 21, 26, 30, 31, 32, 36; idh-03, 07, 08, 12, 17, 18, 21, 32, 33, 40, 46; ed-01, 06, 08, 21, 24, 32; ie-01, 04, 06, 14, 15, 19, 20, 25, 31, 33, 36; da-12, 14, 16, 26, 28; rv-10, 26, 34, 43.
- The Agentic Scientist: lr-01, 04, 05, 26, 30; idh-14, 32, 34, 36, 41, 43, 46; ed-01, 02, 03, 08, 19, 20, 21, 24, 25, 29, 32, 39; ie-10, 12, 13, 15, 30, 31, 33, 34, 36; da-09, 15, 16, 19, 28; rv-02, 04, 10, 21, 23, 26, 30, 31, 35, 40, 43.
- AutoResearchClaw: lr-14, 19, 25, 36; idh-08, 18, 32, 33, 36, 41; ed-01, 08, 24, 25, 29, 32, 33, 34; ie-01, 03, 12, 13, 14, 17, 25, 27, 28, 30, 33, 36; da-13, 14, 15, 19, 26, 27; rv-02, 20, 22, 26, 30, 34, 36.
- AI-Supervisor: lr-05, 06, 14, 18, 21, 24, 26, 28, 32, 34, 36; idh-03, 11, 18, 33, 34, 40, 41, 43, 46; ed-04, 25, 29, 32, 33, 39; ie-35, 36; da-01, 09, 19, 28; rv-16, 34.

What each of the four contributes to the recipe, as far as the mined rows show (I did not read the papers):

| System | Contributes | Recipe steps |
|---|---|---|
| Making AI Scientists Auditable from Evidence to Claim | the broadest grounding (13 lr approaches: retrieval, graph, canonicalisation, reference validation), pre-declared criteria and role separation (ed-21, da-16), gated stages (rv-26); the closest published match to our evidence-to-claim discipline | 1, 4, 6, 9 |
| The Agentic Scientist | the test-design half: schema-bound spec, acceptance criteria, designer and evaluator separation, evaluator isolation, hidden evaluator (ed-01, ed-19, ed-21, ie-13, rv-30), many reviewers | 6, 7, 9 |
| AutoResearchClaw | execution with a lesson store and human collaboration (idh-33, idh-41, da-14, ie-25, ie-28, rv-34) | 7, 9, 10 |
| AI-Supervisor | a persistent world model with gap mining and cross-field search (lr-24, lr-28, lr-34, idh-40, idh-34) | 1, 2, 10 |

Single-purpose references from the step tables: Co-Scientist (novelty check and crossover, steps 4 and 2), StatefulDiscovery (state and evidence records, steps 6, 8, 10), Epsilon (nine da approaches, steps 8 and 10), EvoSci (pool, crossover, critique), Automated Hypothesis Validation with Agentic Sequential Falsifications (steps 6 and 8), Letting AI Formulate the Research Question (pool, critic before the main plan).

Where the corpus gives no evidence:

- No row has `independent-test`; no approach is measured by someone other than its authors. Whether any technique beats a plain alternative is unknown.
- The corpus is of autonomous AI-research systems, mainly in machine learning. It has no system that tests hypotheses by a literature window, no review-project engine, and no study of the effect of human steering (idh-41: 22 works, 1 supportive row).
- Combination effects (does a critic plus a novelty check beat either alone) are not tested in any row; co-occurrence only shows that systems bundle them.
- Works per approach reflect how many systems document a technique, so they favour well-documented systems; all ten top works are from 2026.

## 6. Open questions

1. The "to check" mappings (ed, ie, da and rv approaches to modules) need a read of the code: `experiments.py`, `xruns.py`, `evaluation.py`, `hypothesis_gates.py`, `directions.py`, `ranking_compute`. A short audit task would turn them into EXISTS or gap.
2. A citable trigger for a claims row or technique candidate (earlier plan, G2) remains the first blocker for step 1.
3. Whether confirmatory analysis can stay fully rule-based (da-06, da-07) while keeping what systems seek from agent-chosen tests (da-01) is untested; the recipe resolves it conservatively by allowing free-form tests only as exploratory.
4. The pilot's evidence has no comparability keys, so a literature-window test returns `insufficient-evidence` (earlier plan).
5. The miners are uncalibrated; if a technique chosen here matters, its rows should be checked against the passages (the quotes above are verbatim and anchored for that purpose) before the choice is relied on.

## 7. Open choices for the researcher

Recommended option first. Each choice is also a runtime knob and can be changed later without rework.

1. Which test kind to support first?
   a. (recommended) Literature window in agentic-science: registration, freeze and the computed `insufficient-evidence` outcome, so that the whole loop runs end to end once; the experiment kind is designed but not run.
   b. Experiment kind first, in a project that can run experiments (needs such a project, comparability keys and an executor).
   c. Both in parallel (larger; not advised before one run).
2. Which steps are in v1?
   a. (recommended) Steps 1 to 6 and 10 (lead half, design, memory); steps 7 to 9 only as the existing gates, ingestion and checks.
   b. Steps 1 to 5 only (the lead half), leaving test design to the existing tools.
   c. All ten steps, each at its minimum.
3. How to treat techniques whose rows are only `not-stated` or `asserted-only`?
   a. (recommended) Adopt on fit with our rules and modules, label each choice "stated evidence: none or own test only", and measure it in the first run (engine plan, section 6).
   b. Adopt only techniques with at least one supportive row (leaves out most pre-declaration and gate techniques, which our rules require anyway).
   c. Adopt only techniques with at least three supportive rows (idh-34, da-19, ed-29, idh-40, idh-05, ed-39, ie-28 and a few more).
4. How should the novelty check word its result?
   a. (recommended) "Found / not found in this corpus", with passages, no novelty verdict.
   b. A categorical label (overlaps, partly overlaps, no overlap found), no scale.
   c. The wording is left to the session on each run.
5. Which critic by default at step 3?
   a. (recommended) A fresh session on the artefact only, model recorded; a second model as the runtime option.
   b. Always a second model.
   c. A panel of sessions with a meta-reviewer (idh-08, rv-02), for high-stakes leads only.
6. May free-form agent-chosen analysis (da-01) appear in the loop?
   a. (recommended) Exploratory only, labelled, never the confirmatory outcome.
   b. Not at all.
   c. Yes, if the test is declared at registration (then it is a registered rule).

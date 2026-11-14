# Candidate methods sources: how people do each stage (v0 proposal)

Status: proposal, 2026-11-14, written unattended by lane E of the overnight run. The researcher chooses the list; this file only proposes. Plan: `docs/plans/2026-11-13-lifecycle-stage-deep-dive.md` (rulings 6 and 8: the human-methods column is the second comparator beside the core AI-scientist papers, and its sources are chosen by the researcher before part 2 is run for that column).

## How to read this file

- **Nothing was fetched or read for this draft.** No web access was used and no source below was opened. Every citation is written from memory, except entries marked `repo` (copied from `docs/references.md`, section "Review methods, appraisal and defence", which says it was verified on 2026-10-31 and flags its own uncertainties; those flags are repeated).
- Confidence marks: **repo** (listed in `docs/references.md`), **high** (I am confident the work exists with this author, year and venue; details such as pages or DOI may still be wrong), **medium** (the work exists, I am unsure of the exact title, year or venue), **low** (I am unsure the work exists in this form). Every entry needs a check of the citation before any formal use. Low-confidence entries are listed last in their stage and named so.
- "Covers" and "why" describe what I expect from the title and my general knowledge, not from having read the text. They are claims to check, not paraphrases of content.
- The nine stages are those of `m-stages` v1. The literature review comes first and is the longest, as the plan asks. Row ids refer to `docs/process/our-process-v0.json`.

## 1. literature-review

### 1a. Reporting and conduct of systematic reviews

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 1 | Page MJ, McKenzie JE, Bossuyt PM, et al. The PRISMA 2020 statement: an updated guideline for reporting systematic reviews. BMJ 2021;372:n71. doi:10.1136/bmj.n71 | Reporting items and flow diagram | The factory's flow and methods statement follow it (rows L29, L14, L16) | repo (DOI from memory per repo) |
| 2 | Rethlefsen ML, Kirtley S, Waffenschmidt S, et al. PRISMA-S: an extension to the PRISMA Statement for Reporting Literature Searches in Systematic Reviews. Systematic Reviews 2021;10:39. doi:10.1186/s13643-020-01542-z | Search reporting items | Basis of the search record (L07) | repo |
| 3 | Higgins JPT, Thomas J, Chandler J, Cumpston M, Li T, Page MJ, Welch VA (eds). Cochrane Handbook for Systematic Reviews of Interventions, version 6.4 (updated August 2023). Cochrane, 2023. | Conduct of an intervention review: question, search, selection, data collection, risk of bias, synthesis | The reference text for how a systematic review is done; MECIR standards are cited in the rigour document | high (edition number to check) |
| 4 | Aromataris E, Munn Z (eds). JBI Manual for Evidence Synthesis. JBI, 2020. doi:10.46658/JBIMES-20-01 | Review types beyond effectiveness (scoping, mixed methods, others) | Names the review types the method profiles of R-60 mention | high (DOI from memory) |
| 5 | Lefebvre C, Glanville J, Briscoe S, et al. Searching for and selecting studies. In: Cochrane Handbook for Systematic Reviews of Interventions (chapter 4). | Search and selection practice | Chapter-level source for L06 to L09 | medium (chapter number and author list to check) |

### 1b. Rapid reviews (the profile the agentic-science pilot uses)

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 6 | Garritty C, et al. Cochrane Rapid Reviews Methods Group offers evidence-informed guidance to conduct rapid reviews. Journal of Clinical Epidemiology 2021;130:13-22. doi:10.1016/j.jclinepi.2020.10.007 | Recommended shortcuts and their consequences | Named in the task; the factory's `rapid-review` profile cites it | repo |
| 7 | Tricco AC, Langlois EV, Straus SE (eds). Rapid reviews to strengthen health policy and systems: a practical guide. World Health Organization, 2017. | Practical rapid-review guide | A second view on which shortcuts are acceptable | medium (year to check) |
| 8 | Hamel C, Michaud A, Thuku M, et al. Defining rapid reviews: a systematic scoping review and thematic analysis of definitions and defining characteristics of rapid reviews. Journal of Clinical Epidemiology 2021;129:74-85. | Definitions and common features of rapid reviews | Gives the vocabulary for "what is a shortcut" | medium |
| 9 | Waffenschmidt S, Knelangen M, Sieben W, Bühn S, Pieper D. Single screening versus conventional double screening for study selection in systematic reviews: a methodological systematic review. BMC Medical Research Methodology 2019;19:132. | Single versus double screening | Evidence for the pass A and pass B design and its sampling (L09) | medium (volume and article number to check) |

### 1c. Scoping reviews and mapping studies

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 10 | Arksey H, O'Malley L. Scoping studies: towards a methodological framework. International Journal of Social Research Methodology 2005;8(1):19-32. | Five-stage scoping framework | Named in the task; origin of the method | repo |
| 11 | Peters MDJ, et al. Updated methodological guidance for the conduct of scoping reviews. JBI Evidence Synthesis 2020;18(10):2119-2126. doi:10.11124/JBIES-20-00167 | JBI update of the framework | Current JBI guidance | repo |
| 12 | Tricco AC, et al. PRISMA extension for scoping reviews (PRISMA-ScR): checklist and explanation. Annals of Internal Medicine 2018;169(7):467-473. doi:10.7326/M18-0850 | Scoping-review reporting | Named in the task | repo |
| 13 | Petersen K, Vakkalanka S, Kuzniarz L. Guidelines for conducting systematic mapping studies in software engineering: an update. Information and Software Technology 2015;64:1-18. doi:10.1016/j.infsof.2015.03.007 | Mapping studies; classification schemes | The agentic-science pilot is closer to a mapping of a field than to an effect estimate (m-classification, m-mapping) | repo (repo notes one source lists volume 65) |

### 1d. Software engineering and computing

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 14 | Kitchenham B, Charters S. Guidelines for performing Systematic Literature Reviews in Software Engineering. EBSE Technical Report EBSE-2007-01, Keele University and Durham University, 2007. | Review procedure for computing | Named in the task; the `se-systematic-review` profile cites it | repo |
| 15 | Kitchenham B, Brereton OP, Budgen D, Turner M, Bailey J, Linkman S. Systematic literature reviews in software engineering: a systematic literature review. Information and Software Technology 2009;51(1):7-15. | Early evidence on how SE reviews are done | Shows practice, not only guidance | medium |
| 16 | Wohlin C. Guidelines for snowballing in systematic literature studies and a replication in software engineering. Proc. 18th Int. Conf. on Evaluation and Assessment in Software Engineering (EASE) 2014:1-10. doi:10.1145/2601248.2601268 | Backward and forward snowballing and stopping | Basis of the snowball rounds (L19) | repo |

### 1e. Search review, living reviews, automation of screening

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 17 | McGowan J, Sampson M, Salzwedel DM, Cogo E, Foerster V, Lefebvre C. PRESS Peer Review of Electronic Search Strategies: 2015 Guideline Statement. Journal of Clinical Epidemiology 2016. doi:10.1016/j.jclinepi.2016.01.021 | Peer review of search strategies | Basis of R-61 (L06) | repo (volume and pages not confirmed per repo) |
| 18 | Elliott JH, et al. Living systematic review: 1. Introduction - the why, what, when, and how. Journal of Clinical Epidemiology 2017;91:23-30. | Living reviews | Basis of the living profile (L24) | repo |
| 19 | van de Schoot R, de Bruin J, Schram R, et al. An open source machine learning framework for efficient and transparent systematic reviews. Nature Machine Intelligence 2021;3:125-133. | Active-learning screening (ASReview) | Comparator for the screening ranker and the stopping rule (IDEA-42) | high |
| 20 | O'Mara-Eves A, Thomas J, McNaught J, Miwa M, Ananiadou S. Using text mining for study identification in systematic reviews: a systematic review of current approaches. Systematic Reviews 2015;4:5. | Text mining for study identification | Evidence base for automated screening | medium |
| 21 | Tyndall J. AACODS checklist (Authority, Accuracy, Coverage, Objectivity, Date, Significance). Flinders University, 2010. | Appraisal of grey literature | Named in R-41 for grey sources | medium (form of the source to check; rigour document cites the acronym only) |

### 1f. Not fully sourced

- A source on **LLM-assisted screening and extraction in systematic reviews** (evaluations of model-based screening against human reviewers): I know the area exists but cannot name a single paper with confidence. Left open for the researcher; the core AI-scientist corpus may itself contain candidates.
- The **MECIR standards** (Methodological Expectations of Cochrane Intervention Reviews) are cited by the rigour document. They are published by Cochrane online; I am not sure of a stable citation form. Marked: unsure of the citation, sure the standards exist.

## 2. ideation-hypothesis

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 22 | Platt JR. Strong inference. Science 1964;146(3642):347-353. | Method of competing hypotheses and decisive tests | Classic account of how hypotheses are generated and discriminated | high |
| 23 | Swanson DR. Fish oil, Raynaud's syndrome, and undiscovered public knowledge. Perspectives in Biology and Medicine 1986;30(1):7-18. | Literature-based discovery from disjoint literatures | Direct human precedent for "from the literature stream to a hypothesis" (rows H03, H04) | high |
| 24 | Nosek BA, Ebersole CR, DeHaven AC, Mellor DT. The preregistration revolution. PNAS 2018;115(11):2600-2606. | Preregistration of hypotheses and analyses | Basis of R-50 (H07) | high |
| 25 | Popper K. The Logic of Scientific Discovery. Hutchinson, London, 1959 (English translation of Logik der Forschung, 1934). | Falsifiability | Basis of "falsification tests registered before evidence" | high |

## 3. experiment-design

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 26 | Fisher RA. The Design of Experiments. Oliver and Boyd, Edinburgh, 1935. | Randomisation, replication, factors | Origin of the vocabulary of factors and controls (E01, E03) | high |
| 27 | Montgomery DC. Design and Analysis of Experiments. Wiley (many editions). | Textbook on factorial design, ablation-like one-factor designs | Standard text; edition to be chosen | high (edition open) |
| 28 | Steegen S, Tuerlinckx F, Gelman A, Vanpaemel W. Increasing transparency through a multiverse analysis. Perspectives on Psychological Science 2016;11(5):702-712. | Multiverse analysis | Slice 6 has multiverse axes and a primary universe (E01) | high |
| 29 | Bouthillier X, Delaunay P, Bronzi M, et al. Accounting for variance in machine learning benchmarks. Proceedings of Machine Learning and Systems (MLSys) 2021. | Sources of variance in ML comparisons | Matches the per-seed design and tolerances | medium (author list and venue year to check) |
| 30 | Pineau J, Vincent-Lamarre P, Sinha K, et al. Improving reproducibility in machine learning research (a report from the NeurIPS 2019 reproducibility program). Journal of Machine Learning Research 2021;22(164):1-20. | Reproducibility checklist and findings | Related to the NeurIPS checklist (repo M14) | high |

## 4. implementation-execution

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 31 | Sandve GK, Nekrutenko A, Taylor J, Hovig E. Ten simple rules for reproducible computational research. PLoS Computational Biology 2013;9(10):e1003285. | Practices for reproducible code and runs | Human practice for the step the factory leaves outside (X01, X02) | high |
| 32 | Wilson G, Aruliah DA, Brown CT, et al. Best practices for scientific computing. PLoS Biology 2014;12(1):e1001745. | Software practice in research | Same | high |
| 33 | Wilkinson MD, Dumontier M, Aalbersberg IJJ, et al. The FAIR Guiding Principles for scientific data management and stewardship. Scientific Data 2016;3:160018. | Data and run records | Related to ingesting runs and datasets with hashes | high |

## 5. data-analysis

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 34 | Higgins et al., Cochrane Handbook (entry 3), chapters on collecting data and on meta-analysis | Data collection and synthesis in reviews | Comparator for extraction, dual extraction and evidence tables (D01 to D03); chapter numbers to check | high (chapters to check) |
| 35 | Campbell M, McKenzie JE, Sowden A, et al. Synthesis without meta-analysis (SWiM) in systematic reviews: reporting guideline. BMJ 2020;368:l6890. | Narrative and structured synthesis when pooling is not possible | The evidence report groups without pooling | high |
| 36 | Mathes T, Klaßen P, Pieper D. Frequency of data extraction errors and methods to increase data extraction quality: a methodological review. BMC Medical Research Methodology 2017;17:152. | Extraction errors and dual extraction | Evidence for R-46 and the audit (D02) | medium |
| 37 | Demšar J. Statistical comparisons of classifiers over multiple data sets. Journal of Machine Learning Research 2006;7:1-30. | Significance tests across benchmarks | Human practice for comparing methods across datasets | high |
| 38 | Wasserstein RL, Lazar NA. The ASA's statement on p-values: context, process, and purpose. The American Statistician 2016;70(2):129-133. | Use of significance tests | Context for registered decision rules (D06) | high |
| 39 | Henderson P, Islam R, Bachman P, et al. Deep reinforcement learning that matters. Proceedings of AAAI 2018. | Reporting and variance in ML results | Example of why seeds and reporting matter | medium (pages not given) |
| 40 | Sterne JAC, et al. RoB 2: a revised tool for assessing risk of bias in randomised trials. BMJ 2019;366:l4898; Sterne JAC, et al. ROBINS-I: a tool for assessing risk of bias in non-randomised studies of interventions. BMJ 2016;355:i4919; Guyatt GH, et al. GRADE: an emerging consensus on rating quality of evidence and strength of recommendations. BMJ 2008;336:924-926. | Appraisal instruments named in R-41 | Candidates if appraisal (IDEA-21, D07) is built for a health project | high (three works in one row) |

## 6. paper-writing

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 41 | Brand A, Allen L, Altman M, Hlava M, Scott J. Beyond authorship: attribution, contribution, collaboration, and credit. Learned Publishing 2015;28(2):151-155. | CRediT taxonomy | R-112 derives credit statements from events | high |
| 42 | International Committee of Medical Journal Editors. Recommendations for the Conduct, Reporting, Editing, and Publication of Scholarly Work in Medical Journals (current edition, section on artificial intelligence-assisted technologies). | Disclosure of AI assistance | Human norm for what the methods statement must disclose (R-39) | medium (the current text of the section must be read; it changes) |
| 43 | Mitchell M, Wu S, Zaldivar A, et al. Model cards for model reporting. Proceedings of FAT* 2019:220-229; Gebru T, Morgenstern J, Vecchione B, et al. Datasheets for datasets. Communications of the ACM 2021;64(12):86-92. | Structured documentation of models and datasets | Reporting practice for artefacts a paper releases | high |
| 44 | NeurIPS Paper Checklist (repo M14), https://neurips.cc/public/guides/PaperChecklist | Venue checklist | Already in the references list | repo |

## 7. review-verification

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 45 | Shea BJ, et al. AMSTAR 2. BMJ 2017;358:j4008. doi:10.1136/bmj.j4008 | Critical appraisal of reviews | R-70 self-appraisal (V05) | repo |
| 46 | Whiting P, et al. ROBIS: a new tool to assess risk of bias in systematic reviews was developed. Journal of Clinical Epidemiology 2016;69:225-234. doi:10.1016/j.jclinepi.2015.06.005 | Risk of bias in reviews | R-70 (V05) | repo |
| 47 | Thorne J, Vlachos A, Christodoulopoulos C, Mittal A. FEVER: a large-scale dataset for fact extraction and verification. Proceedings of NAACL-HLT 2018. | Claim verification against evidence | Related to sentence verification (V01) | high |
| 48 | Wadden D, Lin S, Lo K, et al. Fact or fiction: verifying scientific claims. Proceedings of EMNLP 2020 (SciFact). | Verification of scientific claims against abstracts | Same, in the scientific domain | high |
| 49 | Journal and venue reviewer guidelines (for example the NeurIPS reviewer guidelines) | What reviewers are asked to assess | R-71 simulated review is meant to follow the target venue's guidelines | low as a citable source: no specific document chosen; the researcher names the target venue |

## 8. lab-automation

The factory has no step here (see `our-process-v0.md`). Sources are listed only so that the human-methods column has something to compare if a project ever needs the stage.

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 50 | King RD, Rowland J, Oliver SG, et al. The automation of science. Science 2009;324(5923):85-89. | A closed-loop robot scientist | Early example of an automated lab loop | high |
| 51 | Burger B, Maffettone PM, Gusev VV, et al. A mobile robotic chemist. Nature 2020;583:237-241. | Mobile robot running chemistry experiments | Example of lab automation with a planning loop | high |
| 52 | Szymanski NJ, Rendy B, Fei Y, et al. An autonomous laboratory for the accelerated synthesis of novel materials. Nature 2023;624:86-91. | Autonomous synthesis lab | Example from materials science | medium (title wording to check) |

## 9. other (planning, decision records, method choice)

| # | Citation | Covers | Why a candidate | Confidence |
|---|---|---|---|---|
| 53 | Hevner AR, March ST, Park J, Ram S. Design science in information systems research. MIS Quarterly 2004;28(1):75-105. | Design science as a frame | IDEA-39 names Design Science Research as a possible frame above a review | high |
| 54 | Peffers K, Tuunanen T, Rothenberger MA, Chatterjee S. A design science research methodology for information systems research. Journal of Management Information Systems 2007;24(3):45-77. | A process model for design science | Same | high |
| 55 | Basili VR, Caldiera G, Rombach HD. The goal question metric approach. In: Encyclopedia of Software Engineering, Wiley, 1994. | Goal, question, metric structure | IDEA-39 asks for objectives and KPIs in the Goal-Question-Metric style | medium (pages not given) |

## What I propose to do first, if you choose

The plan's step 2 starts with the literature review. The shortest useful list for that column is entries 1, 2, 3, 6, 9, 10, 14, 16, 17 and 19 (reporting, conduct, rapid review, screening design, scoping, software engineering, snowballing, search review, automated screening). The other stages can wait for their turn in the plan, one at a time.

## Open for the researcher

1. Which entries enter the human-methods column (the choice is yours; the list is a proposal).
2. Whether guidance documents (Cochrane Handbook, JBI Manual, entries 3 and 4) are mined as whole works or by chapter; whole books will cost more per pass.
3. Whether LLM-assisted-review evaluations (1f) belong in this column or in the core AI-scientist corpus.
4. The target venue for entry 49.

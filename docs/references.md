# References

## AI scientist systems and related work
1. Mitchener L, et al. Kosmos: An AI scientist for autonomous discovery. arXiv:2511.02824, 2025. https://arxiv.org/html/2511.02824v2
2. Google Co-Scientist team. Accelerating scientific discovery with Co-Scientist. Nature, 2026. https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/ · preprint arXiv:2502.18864
3. Ghareeb AE, et al. Robin: A multi-agent system for automating scientific discovery. arXiv:2505.13400, 2025.
4. Skarlinski MD, et al. Language agents achieve superhuman synthesis of scientific knowledge (PaperQA2, LitQA2). arXiv:2409.13740, 2024.
5. Yamada Y, et al. The AI Scientist-v2. arXiv:2504.08066, 2025.
6. Schmidgall S, et al. Agent Laboratory: Using LLM agents as research assistants. Findings of EMNLP, 2025. arXiv:2501.04227
7. Boiko DA, et al. Autonomous chemical research with large language models (Coscientist). Nature, 2023. doi:10.1038/s41586-023-06792-0
8. Huang K, et al. Automated hypothesis validation with agentic sequential falsifications (POPPER). ICML, 2025. arXiv:2502.09858
9. Sound agentic science requires adversarial experiments. arXiv:2604.22080, 2026.
10. Luo Z, Kasirzadeh A, Shah NB. The more you automate, the less you see: Hidden pitfalls of AI scientist systems. NeurIPS AI4Science Workshop, 2025. arXiv:2509.08713
11. SciIntegrity-Bench. arXiv:2605.10246, 2026.
12. Majumder BP, et al. DiscoveryBench. ICLR, 2025. arXiv:2407.01725
13. Chen Z, et al. ScienceAgentBench. ICLR, 2025. arXiv:2410.05080
14. ReviewPilot: multi-agent screening and extraction for systematic reviews. arXiv:2610.21042, 2026.
15. MedSR-Copilot: PRISMA-aligned agentic framework for medical systematic reviews. medRxiv, 2026.
16. Schmidt L, et al. LLM data extraction in systematic reviews: a rapid feasibility study. arXiv:2405.14445, 2024.
20. EvoScientist: Towards Multi-Agent Evolving AI Scientists for End-to-End Scientific Discovery. arXiv:2603.08127, 2026. https://arxiv.org/html/2603.08127v1 · project: https://evoscientist.ai/ (Apache 2.0; EvoSkills skill library). Researcher / engineer / evolution-manager agents; ideation and experimentation memories retrieved by embedding similarity; Elo idea tournaments. Evaluation: LLM judge plus 3 human annotators on 30 queries; 6 papers in the ICAIS 2025 AI-scientist track; leaderboard positions self-reported at submission time. Contrast: autonomous breadth vs. this project's auditable depth (reviewer of record, measured agreement, traceability).

## Neurodegeneration case
17. Ciampi A, et al. The use of machine learning methods in neurodegenerative disease research: a scoping review. medRxiv, 2023. https://medrxiv.org/content/10.1101/2023.07.31.23293414.full.pdf
18. ML algorithms for virtual early detection and screening of neurodegenerative and neurocognitive disorders: a systematic review. Frontiers in Neurology 15, 2024. doi:10.3389/fneur.2024.1413071
19. Li Z, et al. Applied machine learning in Alzheimer's disease research. Emerging Topics in Life Sciences, 2021.

## Methodology (cited from memory; verify before formal use)
- Swanson DR (1986) — literature-based discovery (fish oil / Raynaud's).
- Chamberlin TC (1890) — method of multiple working hypotheses. Platt JR (1964) — strong inference.
- Silberzahn R, et al. (2018) — many analysts, one data set.
- Munafò MR, Davey Smith G (2018) — triangulation.
- Hevner AR, et al. (2004) — design science research.
- PROBAST, QUADAS-2, TRIPOD+AI, CLAIM, GRADE, PRISMA-ScR, ASME V&V 40.

## Claude documentation
- Feature availability: https://code.claude.com/docs/en/feature-availability
- VS Code extension: https://code.claude.com/docs/en/vs-code
- Remote Control: https://code.claude.com/docs/en/remote-control
- Claude Code in the cloud: https://code.claude.com/docs/en/web-quickstart
- MCP in Claude Code: https://code.claude.com/docs/en/mcp
- Pro/Max plan with Claude Code: https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan
- Custom connectors (remote MCP): https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- Projects: https://support.claude.com/en/articles/9517075-what-are-projects

## Review methods, appraisal and defence (verified 2026-10-31)
Verified against publisher, repository or society pages unless marked otherwise.

| Ref | Citation | Use in the factory |
| --- | --- | --- |
| M1 | Page MJ, McKenzie JE, Bossuyt PM, et al. The PRISMA 2020 statement: an updated guideline for reporting systematic reviews. *BMJ* 2021;372:n71. doi:10.1136/bmj.n71 *(DOI from memory; title and authors confirmed)* | Reporting of systematic reviews |
| M2 | Rethlefsen ML, Kirtley S, Waffenschmidt S, et al. PRISMA-S: an extension to the PRISMA Statement for Reporting Literature Searches in Systematic Reviews. *Systematic Reviews* 2021;10:39. doi:10.1186/s13643-020-01542-z | Search reporting |
| M3 | Tricco AC, et al. PRISMA extension for scoping reviews (PRISMA-ScR): checklist and explanation. *Annals of Internal Medicine* 2018;169(7):467–473. doi:10.7326/M18-0850 | Scoping-review reporting |
| M4 | Arksey H, O'Malley L. Scoping studies: towards a methodological framework. *International Journal of Social Research Methodology* 2005;8(1):19–32. | Scoping-review method (origin) |
| M5 | Peters MDJ, et al. Updated methodological guidance for the conduct of scoping reviews. *JBI Evidence Synthesis* 2020;18(10):2119–2126. doi:10.11124/JBIES-20-00167 | JBI scoping-review method |
| M6 | Kitchenham B, Charters S. Guidelines for performing Systematic Literature Reviews in Software Engineering. EBSE Technical Report EBSE-2007-01, Keele University and Durham University, 2007. | Systematic reviews in computing |
| M7 | Petersen K, Vakkalanka S, Kuzniarz L. Guidelines for conducting systematic mapping studies in software engineering: an update. *Information and Software Technology* 2015;64:1–18. doi:10.1016/j.infsof.2015.03.007 *(one source lists volume 65; verify on the DOI page)* | Mapping studies; evidence/benchmark maps |
| M8 | Wohlin C. Guidelines for snowballing in systematic literature studies and a replication in software engineering. *Proc. 18th Int. Conf. on Evaluation and Assessment in Software Engineering (EASE)* 2014:1–10. doi:10.1145/2601248.2601268 | Citation chasing as a search strategy |
| M9 | McGowan J, Sampson M, Salzwedel DM, Cogo E, Foerster V, Lefebvre C. PRESS Peer Review of Electronic Search Strategies: 2015 Guideline Statement. *Journal of Clinical Epidemiology* 2016. doi:10.1016/j.jclinepi.2016.01.021 *(volume/pages not confirmed)* | Peer review of search strategies before running |
| M10 | Garritty C, et al. Cochrane Rapid Reviews Methods Group offers evidence-informed guidance to conduct rapid reviews. *Journal of Clinical Epidemiology* 2021;130:13–22. doi:10.1016/j.jclinepi.2020.10.007 | Rapid-review profile |
| M11 | Elliott JH, et al. Living systematic review: 1. Introduction—the why, what, when, and how. *Journal of Clinical Epidemiology* 2017;91:23–30. | Living-review profile |
| M12 | Shea BJ, et al. AMSTAR 2: a critical appraisal tool for systematic reviews that include randomised or non-randomised studies of healthcare interventions, or both. *BMJ* 2017;358:j4008. doi:10.1136/bmj.j4008 | Self-appraisal of reviews (16 items, 7 critical domains; no total score) |
| M13 | Whiting P, et al. ROBIS: a new tool to assess risk of bias in systematic reviews was developed. *Journal of Clinical Epidemiology* 2016;69:225–234. doi:10.1016/j.jclinepi.2015.06.005 | Self-appraisal of reviews (risk of bias) |
| M14 | NeurIPS Paper Checklist (16 items: claims, limitations, theory, reproducibility, data/code access, experimental details, statistical significance, compute, ethics, broader impacts, safeguards, licences, assets, human subjects, IRB, LLM usage). Mandatory for NeurIPS submissions. https://neurips.cc/public/guides/PaperChecklist | Self-appraisal of ML experiments |

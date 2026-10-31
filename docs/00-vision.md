# Vision

## Goal

Automate as much of the research process as can be done rigorously, so that human time goes into decisions: which problems to pursue, which hypotheses to test, whether to accept a result, and what it means.

Deep-research tools are shallow (single pass, no curated corpus, no structured evidence, no testing). End-to-end "AI scientist" systems are evaluated on their final output, which hides methodological failures. The factory treats the **research process**, not the report, as the primary output.

## Automating a lab, role by role

| Role | Typical work | Automatable with current agents |
| --- | --- | --- |
| PhD student | Literature search and reading, reproducing baselines, coding and running experiments, drafting | Mostly. Search, screening, extraction, drafting: high. Reproducing code: medium–high. Detecting wrong results: low–medium |
| Postdoc | Choosing baselines and protocols, cross-field synthesis, study design, reviewing juniors, writing papers | Partly. Agents propose and draft; judging design quality is weakest |
| Senior / PI | Problem selection, taste, framing, portfolio and funding strategy, collaborations, clinical access, accountability | Little. Decision support only |
| Research engineer / data manager | Infrastructure, data, pipelines, reproducibility | Largely |

The factory mirrors a lab: many narrow "junior" agents, a few "senior" agents that design and review, and humans as final authority.

## Properties of the ideal factory

1. **One persistent knowledge graph across all projects** — the lab's memory; the asset that compounds.
2. **Many concurrent projects**, each with a focus, a scope policy and a budget.
3. **Continuous operation** — corpora update themselves; conclusions are re-checked when their evidence changes.
4. **The full loop** — literature → hypotheses → computational experiments → results back into the graph (physical/clinical experiments later, via partners).
5. **A quality system** — tests, controls, review gates, measured error rates.
6. **Earned autonomy** — each task type gains autonomy only as its measured error rate justifies it.
7. **Teams** — several researchers, each with their own agents, working on linked projects over a shared graph.
8. **Runs on Claude subscriptions**, not the API.

## Design principles (apply everywhere)

1. Every claim links to a source span or an analysis output.
2. Protocols are versioned before execution; every amendment is recorded with its reason and its effect on earlier decisions ("amend freely, record always").
3. The agent that proposes is never the agent that evaluates.
4. Humans approve at defined gates (protocol, hypothesis shortlist, final claims).
5. Every run is reproducible from pinned models, prompts, code and data snapshots.

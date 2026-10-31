# Production lines

Production lines are repeatable pipelines that reuse the shared core (knowledge graph, provenance and quality system, ingestion) in different orders.

## Acquire

1. **Build from a question** — search, screen, build corpus, extract.
2. **Keep current** — watch for new papers, preprints that get published, corrections and retractions; re-process only affected claims; alert when a *conclusion* changes.
3. **Start from an existing corpus** — import a library / PDF folder / Zotero; audit coverage against a systematic search; expand by citation snowballing.

## Understand

4. **Evidence map / benchmark ledger** — which methods applied to which problems with which data; for method research: datasets × metrics × methods × reported results, every number traced to its source, non-comparable results flagged (different splits, preprocessing, metric definitions).
5. **Contradiction and consensus mapping** — conflicting findings, strength of consensus, moderators that explain disagreements.
6. **Meta-analysis** — effect sizes, risk of bias, pooling, GRADE certainty.

## Generate

7. **Hypotheses from gaps.**
8. **Cross-domain transfer** — methods established in field A but absent from field B.
9. **Experiment design** — protocol, power analysis or ablation plan, compute budget, pre-registration draft.

## Validate

10. **Falsification on data** — including discovering public datasets suited to a hypothesis; for method research, controlled experiments under pre-registered protocols.
11. **Claim verification** — check each claim in a manuscript, grant or review against its cited sources.
12. **Replication / reproducing baselines** — re-run published analyses or baselines from code; test robustness.
13. **Peer-review support** — methods, statistics, citations, code reproducibility.

## Communicate

14. **Writing from the repository** — related work, reviews, grant backgrounds from verified claims only.
15. **Horizon scanning** — emerging topics, method shifts, leaderboards over time.

## Cross-cutting

16. **Negative-results registry** — every refuted hypothesis is recorded.
17. **Self-evaluation** — the factory measures its own error rates (meta-science result).

## Priority

- Lines 1–3 share almost everything; 4 and 7 come cheaply afterwards. → first.
- 5, 11, 16 add rigour cheaply (reuse extraction).
- 6, 9, 10, 12 need statistics, code execution and domain data.
- 13–15 are products on top of a trustworthy repository.

For method-development research (our programme), the most valuable lines are 1–3, 4 (benchmark ledger), 8, 9, 12 and 14.

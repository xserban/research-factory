# PMID seeds and PubMed links in the inbox (plan, 2026-11-14)

Status: approved by the researcher (2026-11-14) as preparation for the next (biomedical) pilot. Implements part of backlog IDEA-76. Builds on decision 124 (PubMed source) and plan `2026-11-14-pubmed.md`.

## Scope

1. **Seeds by PMID.** `SeedSpec` takes `pmid` as a fourth identifier; at least one of doi, arxiv, openalex, pmid. A PMID seed resolves through the `pubmed` source (`ID_LIST`, purpose seed), so its PubMed record enters as any seed record does, and through dedup meets OpenAlex records by PMID. Matching a seed to corpus works also keys on PMID. Held-out withholding (`services/withholding.py`, decision 37.9 and decision 123) covers a held-out seed's PMID exactly as it covers its DOI.
2. **Inbox links.** `parse_link` recognises `pubmed.ncbi.nlm.nih.gov/<pmid>`, `ncbi.nlm.nih.gov/pubmed/<pmid>`, `PMID: <n>` / `pmid:<n>`, and PMC links (`pmc.ncbi.nlm.nih.gov/articles/PMC<n>`, `ncbi.nlm.nih.gov/pmc/articles/PMC<n>`, bare `PMC<n>`). A PMID resolves through `pubmed` (`ID_LIST`, purpose supplied); a PMCID is converted to a PMID with the NCBI ID converter at resolution, else recorded unresolved with a reason.
3. MCP `seed_add` and the CLI take `pmid`; `rf-probe` skill text updated (identifiers: doi, arxiv, openalex or pmid).

Out of scope (stays in IDEA-76): watch windows for PubMed, import admission by PMID.

## Tasks

| # | Task | Agent |
|---|---|---|
| S1 | Seed model, resolution, matching, withholding, MCP, CLI, tests | rf-builder-critical (held-out handling) |
| S2 | Inbox parser and resolution, tests | rf-builder |
| S3 | Docs: skill text, backlog status, MAP | inline |
| S4 | Review | rf-reviewer |

Testing paused: tests written, ruff and mypy only; run with the baseline after the merge of all lines.

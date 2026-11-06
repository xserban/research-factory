---
name: rf-portfolio-page
description: Use when the researcher asks for a shareable page of every project's stage, open work and pending human decisions: read the portfolio as JSON and publish it as a page. A reading step; it records nothing.
---

# rf-portfolio-page

Publishes the portfolio as a page (slice 7a, option C). The platform computes every figure; this
session reads them and lays them out. It judges nothing, writes no event and adds no number.

## Steps

1. Run `factory portfolio --json`. The output is the `Portfolio` model: one row per project with
   its derived stage, open work, pending human decisions and ages. Stop and report if the command
   exits non-zero or lists no project.
2. Build one self-contained HTML page from that JSON: a table with a row per project, the pending
   human decisions as counts per gate, and the time the portfolio was computed. Copy each figure
   as printed; do not add, sum, round or rank.
3. Publish the page as an Artifact (private by default) and give the researcher the link. Update
   the same artifact on a later run instead of publishing a new one.

## Limits

- Counts, ids and titles only. Do not read a work, a label, a rate or a rationale into the page.
- No scheduler and no delivery: the researcher asks for the page; sharing is theirs to decide.
- A local web UI (option B) is out of scope.

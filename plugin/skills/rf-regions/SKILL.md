---
name: rf-regions
description: Use when a region or focus of the corpus and the graph must be drafted as typed selection rules, or when a single work, idea or concept should be proposed for a hand-built region with a verified quote or edge, in a Claude Code session that did not read a screening or extraction pass.
stage: [understand]
---

# rf-regions

Drafts regions: named, reviewable selections of works, ideas and concepts. A region selects; it
asserts nothing about any paper and is not evidence. You define it by rules, the platform
evaluates them, computes the counts and pins the result as a version `R@xxxxxxxx`. Only the
researcher reviews a version, decides a member, links regions or adopts one, on the command line.

## Independence

- Use a Claude Code session that has not run a screening, extraction or contribution pass. The
  platform refuses these tools to a session that did, and before a screening pass has opened;
  do not work around either refusal.
- Do not read or ask for the held-out seeds, audit samples or answer key. A region that reaches
  the held-out part of an import, or a query run for an import, a seed or a probe, is refused to
  you as a whole, with no members or counts. Report the refusal and stop; never rebuild such a
  selection by another route.

## Procedure

1. Write a short `definition` (at most 600 characters) that says what the region selects, and a
   `region_name`. Choose the `kind`: `region`, or `focus` (then give `facet` {question_id, slot}).
2. Prefer rules over member lists. Rule kinds: `corpus` (screening outcome), `run`, `text`,
   `lineage`, `cites`, `idea`, `concept`, `term`, `region` (a pinned version `R@`), `import`
   (the `development` part only). Combine them in `include`, `exclude` and `within`. Rules
   are typed and bounded; a rule over the bound is refused, not truncated.
3. Send the definition with `region_propose`. Read `region_status`: the live counts and the
   drift from the last version. Fix the rules and send a new definition (with `region_id`)
   rather than listing members.
4. Pin a version with `region_snapshot` when the selection is ready for the researcher to
   review. Read members with `region_query` (`members`, paged), and compare with `overlap`,
   `diff` or `regions_of`.
5. For a small hand-built region, propose a single member with `region_propose_member`, with
   exactly one basis:
   - `{"kind": "quote", "work_id", "conversion_id", "anchor", "quote"}`: a verbatim quote of the
     candidate work in an anchored element of its conversion; only for a work member.
   - `{"kind": "edge", "edge_id"}`: a live `cites`, `builds-on` or `improves-on` edge id, or a
     stated or confirmed concept use (`lnk_...`), that touches the candidate and a current
     member of the region.
   The platform verifies the basis. A proposal never enters a version until the researcher adds
   the member; an unverifiable one is refused with its reason (`quote-not-verbatim`,
   `edge-not-incident`, ...). Do not retry with altered input to get one through.

## Stopping and human steps

Reviewing a version, adding, removing or rejecting a member, linking regions and adopting a
snapshot from another project are human steps on the command line (`factory regions`); never
decide or review, directly or by any other route. If a call is refused, report the reason
verbatim and stop.

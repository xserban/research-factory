# Our process as data, v0 (draft for the researcher's check)

Status: draft, 2026-11-14, written unattended by lane E of the overnight run. Nothing here is accepted. Companion of `our-process-v0.json` (the registered form); this page is a reading copy generated from it.

Axis: the nine stages of `m-stages` v1. Fields as for the step miner: step, inputs, outputs, method, actor, check, limits. Every row cites its source file and section and quotes the passage. Quotes are verbatim after removing Markdown emphasis asterisks and collapsing whitespace (checked by script at drafting time). Inputs and outputs are the drafter's wording. `not-stated` means no passage was found.

Practice column: `differs` marks a row where a passage in the repository documents a difference between the spec and what was done; `not-piloted` marks a spec marked proposed or Later; `unknown` means practice was not checked (this drafter did not read the pilot's events).

## Rows by stage

| Stage | Rows | Of which differs |
|---|---|---|
| literature-review | 29 | 8 |
| ideation-hypothesis | 8 | 0 |
| experiment-design | 3 | 0 |
| implementation-execution | 3 | 0 |
| data-analysis | 7 | 2 |
| paper-writing | 3 | 0 |
| review-verification | 5 | 0 |
| lab-automation | 0 | 0 |
| other | 6 | 1 |

## literature-review

### L01

- **Step:** "the raw goal (verbatim), the decomposed question elements and explicit non-goals are recorded" (docs/specs/slice-1.md §User flow 2)
- **Inputs:** Raw goal from the researcher
- **Outputs:** Question version Q@sha8 with elements and non-goals
- **Method:** "Claude interviews the researcher (≤5 questions)" (docs/specs/slice-1.md §User flow 2)
- **Actor:** human-assisted
- **Check:** "`open` is allowed, `TBD` is not" (docs/specs/01-rigour.md §B, R-10)
- **Limits:** "The goal was taken as typed, the plan was drafted without the scientist" (docs/specs/slice-8-develop.md §Problem)
- **Practice (differs):** Spec: Claude interviews the researcher in at most five questions. Pilot: the goal was taken as typed and the plan drafted without the scientist; slice 8 replaces this with suggest-and-select, one level at a time. Evidence: "The goal was taken as typed, the plan was drafted without the scientist" (docs/specs/slice-8-develop.md §Problem)

### L02

- **Step:** "the researcher names known in-scope papers (positive) and known out-of-scope look-alikes (negative)" (docs/specs/slice-1.md §User flow 3)
- **Inputs:** Seed papers named by the researcher
- **Outputs:** Seeds resolved to works; recorded development/held-out split of the positives
- **Method:** "the platform resolves them to works and draws a recorded random development/held-out split of the positives (R-20)" (docs/specs/slice-1.md §User flow 3)
- **Actor:** human-assisted
- **Check:** "the split is drawn by the platform with a recorded random seed" (docs/specs/slice-1.md §Acceptance criteria 22)
- **Limits:** "Drawing session had seen all candidates (limitation)" (docs/pilot/log.md §Row 3)
- **Practice (differs):** Spec: the researcher names the seeds. Pilot log (linear-attention-vision): seeds were proposed by the agent, to be confirmed; the drawing session had seen all candidates. Evidence: "Seeds proposed by the agent, not the researcher" (docs/pilot/log.md §Row 2)

### L03

- **Step:** "Claude proposes candidate queries per source; the platform runs them and reports recall on positive seeds, hits on negative seeds, result counts and harvested vocabulary" (docs/specs/slice-1.md §User flow 4)
- **Inputs:** Candidate queries, development seeds
- **Outputs:** Probe report per query and source (recall, negatives hit, counts, vocabulary)
- **Method:** "iterate until recall is acceptable" (docs/specs/slice-1.md §User flow 4)
- **Actor:** human-assisted
- **Check:** "Threshold for acceptable seed recall in the probe (proposal: ≥ 0.9 in `pilot`, 1.0 in `systematic`)" (docs/specs/slice-1.md §Open questions)
- **Limits:** "probe rounds were the agent's alone" (docs/specs/slice-8-develop.md §Problem)
- **Practice (differs):** Spec: Claude proposes, the platform measures, the scientist iterates. Pilot: rounds were the agent's alone until the suggest-and-select loop was used. Evidence: "probe rounds were the agent's alone" (docs/specs/slice-8-develop.md §Problem)

### L04

- **Step:** "criteria with IDs (`IN01`, `EX03`), each naming its parent question element or non-goal, with `applies_at` and priority" (docs/specs/slice-1.md §User flow 5)
- **Inputs:** Question, probe results
- **Outputs:** Protocol version P@sha8 (criteria, sources, queries, limits, screening plan, kappa floor)
- **Method:** "screening plan, reviewer roles and κ floor declared before screening" (docs/specs/slice-1.md §User flow 5)
- **Actor:** human-assisted
- **Check:** "a parentless criterion is rejected" (docs/specs/01-rigour.md §B, R-11)
- **Limits:** "the criteria were drafted whole" (docs/specs/slice-8-develop.md §Problem)
- **Practice (differs):** Spec: criteria with parents. Pilot: criteria were drafted whole by the agent; in the slice 8 loop the exclusions were cut from six to three by the scientist. Evidence: "the exclusions were cut from six to three" (docs/specs/slice-8-develop.md §Problem)

### L05

- **Step:** "Amendments are allowed at any time, with reason and `semantic` flag; affected earlier decisions are computed and marked stale." (docs/specs/slice-1.md §User flow 5)
- **Inputs:** Proposed protocol change with reason
- **Outputs:** New protocol version; stale decisions listed
- **Method:** "an amendment computes which earlier decisions are stale" (docs/specs/01-rigour.md §B, R-15)
- **Actor:** human-assisted
- **Check:** "stale decisions must be re-screened" (docs/specs/01-rigour.md §B, R-15)
- **Limits:** not-stated

### L06

- **Step:** "a reviewer agent applies the PRESS checklist, a human confirms; findings and responses are recorded" (docs/specs/01-rigour.md §H, R-61)
- **Inputs:** Search strategy
- **Outputs:** PRESS findings, responses and human confirmation
- **Method:** "PRESS review" (docs/specs/01-rigour.md §H, R-61)
- **Actor:** human-assisted
- **Check:** "a human confirms" (docs/specs/01-rigour.md §H, R-61)
- **Limits:** "Method profiles (proposed)" (docs/specs/01-rigour.md §H heading)

### L07

- **Step:** "queries run on OpenAlex and arXiv; raw responses archived as blobs; reported vs. retrieved counts recorded" (docs/specs/slice-1.md §User flow 6)
- **Inputs:** Confirmed protocol queries
- **Outputs:** Search runs, raw blobs, reported and retrieved counts
- **Method:** "no relevance ranking, truncation or "top N"" (docs/specs/01-rigour.md §C, R-21)
- **Actor:** automated
- **Check:** "a test fails if retrieved < reported without a recorded reason" (docs/specs/slice-1.md §Acceptance criteria 14)
- **Limits:** "PubMed and other sources" (docs/specs/slice-1.md §Out of scope)

### L08

- **Step:** "cascade merge; every merge recorded and reversible" (docs/specs/slice-1.md §User flow 7)
- **Inputs:** Retrieved records
- **Outputs:** Works with merges listed; PRISMA identification counts
- **Method:** "4-stage cascade, union-find, reversible merges" (docs/specs/slice-1.md §In scope, Dedup)
- **Actor:** automated
- **Check:** "seeds detect false merges (a seed vanishes) and false splits (a seed appears twice)" (docs/specs/01-rigour.md §C, R-26)
- **Limits:** "A later merge would leave the canonical work considered-not-added while its twin was sampled." (docs/backlog.md §IDEA-20)

### L09

- **Step:** "two independent passes (A: inclusion framing, B: exclusion framing, reversed criterion order, different Claude models, separate sessions)" (docs/specs/slice-1.md §User flow 8)
- **Inputs:** Title and abstract of each record, protocol, seeds as worked examples
- **Outputs:** Verdicts (include, exclude, cannot-assess, unsure) with quoted rationale per pass
- **Method:** "fresh context and randomised order per batch; seeds pinned as worked examples" (docs/specs/slice-1.md §User flow 8)
- **Actor:** automated
- **Check:** "a screening rationale whose quote is not verbatim in the title/abstract is rejected" (docs/specs/slice-1.md §Acceptance criteria 16)
- **Limits:** "some pass A works have no live decision, because the work could not be screened for a stated technical reason" (docs/backlog.md §IDEA-46)
- **Practice (differs):** Spec: second pass on every record in systematic mode, a recorded sample in pilot. Pilot: a tolerance for unscreenable pass A records (researcher: always accept 1% errors for pass A). Evidence: "The researcher: always accept 1% errors for pass A." (docs/backlog.md §IDEA-46)

### L10

- **Step:** "before each batch both passes screen ~30 human-labelled records (incl. seeds)" (docs/specs/01-rigour.md §D, R-35)
- **Inputs:** Human-labelled calibration records
- **Outputs:** Sensitivity and specificity per pass; batch released or blocked
- **Method:** "screening is blocked until the calibration set is labelled" (docs/specs/slice-1.md §Acceptance criteria 18)
- **Actor:** human-assisted
- **Check:** "sensitivity and specificity reported; below threshold blocks the batch" (docs/specs/01-rigour.md §D, R-35)
- **Limits:** not-stated

### L11

- **Step:** "Cohen's κ per pass pair and per criterion" (docs/specs/01-rigour.md §D, R-36)
- **Inputs:** Decisions of passes A and B
- **Outputs:** kappa per criterion; list of disagreements
- **Method:** "`screen_agreement` refuses to compute κ for two passes with identical configuration" (docs/specs/slice-1.md §Acceptance criteria 17)
- **Actor:** automated
- **Check:** "disagreements never auto-resolved" (docs/specs/01-rigour.md §D, R-36)
- **Limits:** "κ floor in `pilot` mode (proposal: advisory; floor 0.7 in `systematic`)" (docs/specs/slice-1.md §Open questions)

### L12

- **Step:** "human audits ≥2% (min. 50) of agreed decisions, weighted 3:1 towards agreed exclusions" (docs/specs/01-rigour.md §D, R-37)
- **Inputs:** Agreed decisions; disagreements and unsure records
- **Outputs:** Human labels, error rate, human resolutions
- **Method:** "`audit_sample` draws ≥2% (min. 50) of agreed decisions, 3:1 towards exclusions" (docs/specs/slice-1.md §Acceptance criteria 18)
- **Actor:** human
- **Check:** "error rate above the declared floor sends criteria back to the protocol" (docs/specs/01-rigour.md §D, R-37)
- **Limits:** "audit labels for unsampled pairs are dropped silently" (docs/backlog.md §IDEA-18)

### L13

- **Step:** "backward and forward citation chasing from included works; seed admission for explained misses (R-24, R-25)" (docs/specs/slice-1.md §User flow 10)
- **Inputs:** Included works, seed misses
- **Outputs:** Recorded supplementary search rounds; new-after-dedup counts under other methods
- **Method:** "Supplementary searches (backward/forward citation chasing, seed admission, hand search) are separate runs" (docs/specs/01-rigour.md §C, R-25)
- **Actor:** automated
- **Check:** "every positive seed is retrieved, or the miss is explained and an admission route planned" (docs/specs/01-rigour.md §C, R-24)
- **Limits:** not-stated

### L14

- **Step:** "trying legal routes in a fixed order; every attempt is recorded" (docs/specs/slice-2.md §User flow 2)
- **Inputs:** Works promoted at title/abstract screening
- **Outputs:** Fetch attempts per work; documents in the local library; not-retrieved reasons
- **Method:** "literature is stored locally per project and never in git" (docs/specs/slice-2.md §Design, Storage and licensing)
- **Actor:** automated
- **Check:** "each not-retrieved work lists per-route reasons" (docs/specs/slice-2.md §Acceptance criteria 1)
- **Limits:** "Legal routes only." (docs/specs/slice-2.md §Design, route order)

### L15

- **Step:** "Everything is converted to Markdown" (docs/specs/slice-2.md §Design, Canonical document)
- **Inputs:** Raw source (HTML, LaTeX, PDF)
- **Outputs:** Canonical Markdown with stable anchors, pinned converter version
- **Method:** "the same raw blob and converter version always give the same document hash" (docs/specs/slice-2.md §Design, Canonical document)
- **Actor:** automated
- **Check:** "converting the same raw blob twice with the same converter version yields identical document hash and anchors" (docs/specs/slice-2.md §Acceptance criteria 2)
- **Limits:** "each line number became its own paragraph with its own anchor" (docs/backlog.md §IDEA-48)
- **Practice (differs):** Spec: deterministic conversion with stable anchors. Practice: line-numbered preprints gave one anchored paragraph per margin line number; the researcher chose to leave the conversions as they are. Evidence: "The researcher chose to leave the conversions as they are for now." (docs/backlog.md §IDEA-48)

### L16

- **Step:** "criteria with `applies_at = full-text | either` are applied with the slice-1 machinery (two passes, calibration, κ, audit, verified quotes)" (docs/specs/slice-2.md §User flow 4)
- **Inputs:** Canonical documents, protocol criteria
- **Outputs:** Full-text verdicts anchored to the pinned conversion; PRISMA full-text boxes
- **Method:** "quotes now cite anchors" (docs/specs/slice-2.md §User flow 4)
- **Actor:** automated
- **Check:** "a quote that is not verbatim in the anchored element is rejected" (docs/specs/slice-2.md §Acceptance criteria 4)
- **Limits:** "Today `cannot-assess` counts as promote" (docs/backlog.md §IDEA-49)
- **Practice (differs):** Spec and code: cannot-assess promotes to extraction. Researcher ruling 2026-11-13 (IDEA-67): an unresolved full-text cannot-assess work is pending until resolved; not yet built. Evidence: "an unresolved full-text cannot-assess work is pending until resolved" (docs/backlog.md §IDEA-67)

### L17

- **Step:** "`references_extract` runs for an included work (or all of them). The platform parses the bibliography of the work's pinned conversion" (docs/specs/slice-3a-references.md §User flow 1)
- **Inputs:** Pinned conversion of an included work
- **Outputs:** Parsed reference entries, marker links, resolved works, parse quality flags
- **Method:** "resolves each entry by identifier, then by title/year match" (docs/specs/slice-3a-references.md §User flow 1)
- **Actor:** automated
- **Check:** "the counts resolved, unconfirmed, ambiguous and unresolved sum to the entry count" (docs/specs/01-rigour.md §J, R-80)
- **Limits:** "G1 ships with recorded quality flags and no layout-model parser" (docs/specs/slice-3a-references.md §Rulings 5)

### L18

- **Step:** "An agent may propose, never confirm" (docs/specs/slice-3a-references.md §Rulings 3)
- **Inputs:** Ambiguous and unconfirmed reference links
- **Outputs:** Confirmed or rejected links
- **Method:** "The agent may propose (`reference_decide`, a recorded act quoting both entries); a human confirms or rejects (CLI)" (docs/specs/slice-3a-references.md §User flow 3)
- **Actor:** human-assisted
- **Check:** "An agent proposes and never confirms" (docs/specs/01-rigour.md §J, R-81)
- **Limits:** not-stated

### L19

- **Step:** "`snowball_round` plans a round (dry run: sources, candidates ranked by derived citation count, the stopping-rule state) and, on go-ahead, registers it and runs its queries as supplementary searches" (docs/specs/slice-3a-references.md §User flow 4)
- **Inputs:** Resolved references missing from the corpus; protocol stopping rule
- **Outputs:** Snowball round record; new records entering dedup and screening
- **Method:** "nothing is auto-included" (docs/specs/slice-3a-references.md §User flow 4)
- **Actor:** human-assisted
- **Check:** "a candidate is never included without screening" (docs/specs/01-rigour.md §J, R-82)
- **Limits:** "a maximum of two backward rounds and one forward round for `pilot`" (docs/specs/slice-3a-references.md §Rulings 6)

### L20

- **Step:** "Each link is parsed to one identifier (arXiv id, DOI or OpenAlex id) at the boundary; an unparseable link writes nothing and is returned with a reason." (docs/specs/slice-4a-inbox-discovery.md §User flow 1)
- **Inputs:** A link given by the researcher
- **Outputs:** Inbox item with one identifier
- **Method:** "Capture is offline and allowed at any time" (docs/specs/slice-4a-inbox-discovery.md §User flow 1)
- **Actor:** human
- **Check:** not-stated
- **Limits:** not-stated

### L21

- **Step:** "looks up each open item by identifier as a recorded query of purpose `supplied`" (docs/specs/slice-4a-inbox-discovery.md §User flow 2)
- **Inputs:** Open inbox items
- **Outputs:** Works with provenance method supplied; item outcome (new, in-corpus, not-found, ambiguous, failed)
- **Method:** "Screeners never see the route or the note" (docs/specs/slice-4a-inbox-discovery.md §User flow 3)
- **Actor:** automated
- **Check:** "Screening and extraction tasks never carry how a work was discovered" (docs/specs/01-rigour.md §L, R-101)
- **Limits:** "publisher-page resolution (`citation_doi`), the pilot run on real links" (docs/specs/slice-4a-inbox-discovery.md §v1 scope)

### L22

- **Step:** "One feed engine, configured per project, that ranks new arXiv listings against the project's own core works." (docs/specs/slice-4c-feed.md §Goal)
- **Inputs:** Declared arXiv categories, the project's reference set (core works)
- **Outputs:** Ranked feed entries with nearest reference work
- **Method:** "embeds the remainder with the ranker model of decision 116, scores each against the reference set" (docs/specs/slice-4c-feed.md §User flow 2)
- **Actor:** automated
- **Check:** "Fixed inputs give the same order." (docs/specs/slice-4c-feed.md §Rulings 5)
- **Limits:** "Free-text feed queries and other sources (OpenAlex concepts, bioRxiv) come Later." (docs/specs/slice-4c-feed.md §Rulings 2)

### L23

- **Step:** "The researcher records `like`, `dislike`, `save` or `dismiss`" (docs/specs/slice-4c-feed.md §User flow 4)
- **Inputs:** Ranked feed entries
- **Outputs:** Reactions; papers sent to the inbox
- **Method:** "The feed suggests and the researcher selects; the feed never includes, excludes or extracts." (docs/specs/slice-4c-feed.md §Goal)
- **Actor:** human
- **Check:** "Reactions are human events and record the rank and score that were shown." (docs/specs/slice-4c-feed.md §User flow 4)
- **Limits:** "no; disclosed as discovery" (docs/specs/slice-4c-feed.md §Two intake channels)

### L24

- **Step:** "the platform re-runs the project's recorded searches, deduplicates what is new against the corpus and routes it into the project's screening protocol" (docs/specs/slice-4b-living-corpus.md §Goal)
- **Inputs:** Recorded protocol queries, schedule set outside the platform
- **Outputs:** Watch cycles as search runs; new pending works
- **Method:** "Watch runs are search runs." (docs/specs/01-rigour.md §L, R-102)
- **Actor:** automated
- **Check:** "A living review reports, per update, a PRISMA flow over the records first identified in it" (docs/specs/01-rigour.md §L, R-103)
- **Limits:** not-stated

### L25

- **Step:** "Read every included paper for what it builds on, what it adds, what it reports and what it concedes, record each statement as an anchored, verified quote" (docs/specs/slice-3b-lineage.md §Goal)
- **Inputs:** Included works with a current reference extraction
- **Outputs:** Contribution items (base-idea, addition, result, limitation, not-stated)
- **Method:** "Each item carries an anchor and a verbatim quote; the platform verifies both." (docs/specs/slice-3b-lineage.md §User flow 2)
- **Actor:** automated
- **Check:** "The platform cannot check absence; the audit sample includes `not-stated` items." (docs/specs/slice-3b-lineage.md §Rulings 8)
- **Limits:** "no edge may exist without a basis" (docs/specs/slice-3b-lineage.md §Goal)

### L26

- **Step:** "A relation whose target the platform can resolve deterministically (the item cites a reference entry that G1 resolved)" (docs/specs/slice-3b-lineage.md §User flow 4)
- **Inputs:** Contribution items, reference links
- **Outputs:** Relations (builds-on, improves-on), each stated or inferred
- **Method:** "(target chosen by the agent, or no basis quote)" (docs/specs/slice-3b-lineage.md §User flow 4)
- **Actor:** human-assisted
- **Check:** "Inferred edges need human confirmation" (docs/specs/01-rigour.md §J, R-84)
- **Limits:** "no second-agent confirmation exists for inferred relations or ideas, in any mode" (docs/specs/slice-3b-lineage.md §Rulings 3)

### L27

- **Step:** "a short text, one target, and between one and five" (docs/specs/slice-3c-intuition.md §User flow 2)
- **Inputs:** Idea or paper node with its contribution items and verified quotes
- **Outputs:** Interpretation with sources and review state (never evidence)
- **Method:** "A text with no source is refused." (docs/specs/slice-3c-intuition.md §User flow 2)
- **Actor:** human-assisted
- **Check:** "Only a human sets `reviewed` or `wrong`" (docs/specs/slice-3c-intuition.md §Rulings 6)
- **Limits:** "the platform checks length, targets and quotes, not whether the text is correct" (docs/specs/slice-3c-intuition.md §Rulings 4)

### L28

- **Step:** "The researcher supplies or approves the first source for each concept" (docs/specs/slice-3c-intuition.md §Rulings 2)
- **Inputs:** Proposed background concepts
- **Outputs:** Concepts with approved source; uses links
- **Method:** "Claude drafts the concept's explanation from that source, with quotes" (docs/specs/slice-3c-intuition.md §User flow 3)
- **Actor:** human-assisted
- **Check:** "A concept without an approved source stays `unreviewed`" (docs/specs/slice-3c-intuition.md §Rulings 2)
- **Limits:** not-stated

### L29

- **Step:** "Every number in a report (PRISMA counts, κ, error rates) is derived from events; none is typed by a human or an agent" (docs/specs/01-rigour.md §A, R-05)
- **Inputs:** Event log
- **Outputs:** PRISMA 2020 flow, PRISMA-S search report, methods statement, discovery report
- **Method:** "PRISMA 2020 flow and PRISMA-S search report derived from events; methods statement disclosing automation" (docs/specs/slice-1.md §User flow 11)
- **Actor:** automated
- **Check:** "every PRISMA number is derived from events; none is entered by hand" (docs/specs/slice-1.md §Acceptance criteria 10)
- **Limits:** "but no mechanism does this" (docs/backlog.md §IDEA-47)
- **Practice (differs):** Spec (protocol criterion EX02 text): surveys are recorded as background and snowball sources. Backlog IDEA-47: no mechanism does this. Evidence: "but no mechanism does this" (docs/backlog.md §IDEA-47)

## ideation-hypothesis

### H01

- **Step:** "A controlled vocabulary of typed properties (`enum`, `set`, `bool`, `number` with unit family), human-approved" (docs/specs/slice-6-hypotheses.md §Ruling 4)
- **Inputs:** Properties proposed from the corpus
- **Outputs:** Approved property vocabulary V@sha8
- **Method:** "cards a `miner` (single pass with human confirmation and audit, declared quality regime)" (docs/specs/slice-6-hypotheses.md §Reconciliation 5)
- **Actor:** human-assisted
- **Check:** "Hypotheses cite triggers." (docs/specs/01-rigour.md §N, R-120)
- **Limits:** "free labels fragment" (docs/specs/slice-6-hypotheses.md §Ruling 4)

### H02

- **Step:** "`match_query` computes, per problem description, which method cards satisfy, conflict with or leave unknown each required property" (docs/specs/slice-6-hypotheses.md §Builders 3)
- **Inputs:** Method cards, problem description
- **Outputs:** Match rows with transfer-candidate flag
- **Method:** "Per required property the rule yields `satisfied | conflicting | unknown`." (docs/specs/slice-6-hypotheses.md §Matching)
- **Actor:** automated
- **Check:** "Every result carries `match_key = sha256(problem state, card states, V@, builder version)`" (docs/specs/slice-6-hypotheses.md §Matching)
- **Limits:** "v1 keeps the project as the vocabulary scope" (docs/specs/slice-6-hypotheses.md §Reconciliation 6)

### H03

- **Step:** "`finder_contradictions` lists numeric conflicts inside comparability groups with the conditions that differ; `finder_gaps` lists empty cells of a declared method × condition grid ("not found in corpus")" (docs/specs/slice-6-hypotheses.md §Builders 3)
- **Inputs:** Evidence report, declared grid
- **Outputs:** Contradiction pairs; empty grid cells with corpus definition
- **Method:** "bounded at 10,000 cells per query" (docs/specs/slice-6-hypotheses.md §Ruling 10)
- **Actor:** automated
- **Check:** "claim-level contradictions are proposed by an agent (`contradiction_propose`, two live claims or items with quotes), stay inferred and need a human" (docs/specs/slice-6-hypotheses.md §Ruling 9)
- **Limits:** "not found in this corpus" (docs/specs/slice-6-hypotheses.md §Ruling 10)

### H04

- **Step:** "Claude records a lead (≤ 600 characters) with at least one trigger (a match row, a finding, a work, a row, a claim, an `ida_`, an `int_`)." (docs/specs/slice-6-hypotheses.md §Leads 4)
- **Inputs:** Match rows, findings, works, claims
- **Outputs:** Lead with triggers and the failed directions that share a trigger
- **Method:** "so that dead ends are seen before proposing" (docs/specs/slice-6-hypotheses.md §Leads 4)
- **Actor:** human-assisted
- **Check:** "A lead or hypothesis without at least one resolvable trigger cannot be written" (docs/specs/01-rigour.md §N, R-120)
- **Limits:** "where idea notes live (this backlog is for the platform; research ideas belong in each project)" (docs/backlog.md §IDEA-05)

### H05

- **Step:** "`promote | park | discard` by a human (pilot, systematic) or by an agent session other than the lead's author (exploratory)" (docs/specs/slice-6-hypotheses.md §Ruling 11)
- **Inputs:** Lead
- **Outputs:** Decision (promote, park, discard with reason)
- **Method:** "`discard` needs a reason from {`duplicate`, `prior-failure`, `out-of-scope`, `infeasible`, `not-falsifiable`, `other`} plus a note" (docs/specs/slice-6-hypotheses.md §Ruling 11)
- **Actor:** human-assisted
- **Check:** "Refuted hypotheses and null results are recorded and reported" (docs/specs/01-rigour.md §F, R-52)
- **Limits:** not-stated

### H06

- **Step:** "A promoted lead becomes a hypothesis draft: statement, variables, conditions, prediction with a smallest effect of interest, a decision rule from a fixed menu, and a test reference" (docs/specs/slice-6-hypotheses.md §Hypotheses 5)
- **Inputs:** Promoted lead
- **Outputs:** Hypothesis draft
- **Method:** "A critic session that neither drafted the hypothesis nor wrote the lead reviews the artefact (not the proposer's reasoning) against a checklist." (docs/specs/slice-6-hypotheses.md §Hypotheses 5)
- **Actor:** human-assisted
- **Check:** "Proposer never evaluates; critic sees artefacts, not the proposer's reasoning" (docs/specs/01-rigour.md §F, R-51)
- **Limits:** not-stated

### H07

- **Step:** "The gate holder registers it; `H@` is then frozen." (docs/specs/slice-6-hypotheses.md §Hypotheses 5)
- **Inputs:** Reviewed hypothesis draft
- **Outputs:** Registered hypothesis H@sha8
- **Method:** "Hypotheses and their falsification tests are registered before evidence is examined" (docs/specs/01-rigour.md §F, R-50)
- **Actor:** human-assisted
- **Check:** "blocks rescue-by-revision (R-52)" (docs/specs/slice-6-hypotheses.md §Ruling 12)
- **Limits:** "A hypothesis registered under the exploratory policy is labelled and is never reported as confirmatory" (docs/specs/slice-6-hypotheses.md §Ruling 14)

### H08

- **Step:** "the platform flags `contaminated` when the drafter's or critic's model cut-off is on or after the window start" (docs/specs/slice-6-hypotheses.md §Ruling 15)
- **Inputs:** Declared model cut-offs, window start
- **Outputs:** contaminated or cutoff-unknown flag
- **Method:** "when hypotheses are scored against later literature, the model's training cut-off must precede the hold-out window" (docs/specs/01-rigour.md §F, R-53)
- **Actor:** automated
- **Check:** "`cutoff-unknown` when undeclared (error in systematic)" (docs/specs/slice-6-hypotheses.md §Ruling 15)
- **Limits:** "experiment hypotheses are not affected" (docs/specs/slice-6-hypotheses.md §Ruling 15)

## experiment-design

### E01

- **Step:** "`ExperimentDesign`: `hypothesis` (`hyp_`, must be registered or draft-linked), `factor` (configuration keys that change between treatment and baseline)" (docs/specs/slice-6-hypotheses.md §Design, ExperimentDesign)
- **Inputs:** Registered hypothesis, evidence rows of baselines
- **Outputs:** Experiment design E@sha8
- **Method:** "Validation at the boundary: product of axes ≤ 256; each ablation differs in one key; the primary universe is in the product" (docs/specs/slice-6-hypotheses.md §Design, ExperimentDesign)
- **Actor:** human-assisted
- **Check:** "baselines resolve to final evidence rows whose comparability key matches the hypothesis conditions" (docs/specs/slice-6-hypotheses.md §Design, ExperimentDesign)
- **Limits:** "the pilot with real runs supplied by the researcher (acceptance 25)" (docs/specs/slice-6-hypotheses.md §v1 scope)

### E02

- **Step:** "after freeze, changes are deviations (R-14); after unlock, a semantic change flags the outcome `deviated`" (docs/specs/slice-6-hypotheses.md §Design, ExperimentDesign)
- **Inputs:** Experiment design
- **Outputs:** Frozen design; deviations recorded separately
- **Method:** "`experiments.freeze_unlock` (floor `agent`; exploratory preset `agent` with the non-author/non-drafter rule as the module's `proposer_of` hook; pilot and systematic `human`)" (docs/specs/slice-6-hypotheses.md §Reconciliation 1)
- **Actor:** human-assisted
- **Check:** "Confirmatory runs need every declared baseline resolved" (docs/specs/01-rigour.md §N, R-122)
- **Limits:** not-stated

### E03

- **Step:** "Positive and negative controls measure the pipeline's sensitivity and false-positive rate" (docs/specs/01-rigour.md §F, R-54)
- **Inputs:** Design controls
- **Outputs:** Control cells with expected outcome
- **Method:** "`controls` (positive and negative cells with expected outcome)" (docs/specs/slice-6-hypotheses.md §Design, ExperimentDesign)
- **Actor:** human-assisted
- **Check:** not-stated
- **Limits:** not-stated

## implementation-execution

### X01

- **Step:** "It never calls a model and never executes experiment code." (docs/specs/slice-6-hypotheses.md §Goal)
- **Inputs:** Frozen design
- **Outputs:** Nothing: execution happens outside the platform
- **Method:** "runs executed by the researcher outside the platform are ingested" (docs/specs/slice-6-hypotheses.md §Pilot for acceptance)
- **Actor:** human
- **Check:** not-stated
- **Limits:** "never executes experiment code" (docs/specs/slice-6-hypotheses.md §Goal)

### X02

- **Step:** "runs executed by the researcher outside the platform are ingested" (docs/specs/slice-6-hypotheses.md §Pilot for acceptance)
- **Inputs:** Run results produced elsewhere
- **Outputs:** Ingested runs tied to design and hypothesis
- **Method:** "Confirmatory results carry the unlock nonce issued after registration and freeze; results without it are refused" (docs/specs/01-rigour.md §N, R-123)
- **Actor:** human-assisted
- **Check:** "a confirmatory result without the nonce is refused" (docs/specs/slice-6-hypotheses.md §Ruling 18)
- **Limits:** "The platform cannot detect evaluation that is never recorded; the nonce and the git timestamps of registration events evidence order only." (docs/specs/slice-6-hypotheses.md §Ruling 18)

### X03

- **Step:** "`budget` (GPU-hours, per-run cap, maximum runs)" (docs/specs/slice-6-hypotheses.md §Design, ExperimentDesign)
- **Inputs:** Design budget, ingested runs
- **Outputs:** Budget status; compute-budget-exceeded finding
- **Method:** "`compute-budget-exhausted`" (docs/specs/slice-6-hypotheses.md §Reconciliation 3)
- **Actor:** automated
- **Check:** not-stated
- **Limits:** not-stated

## data-analysis

### D01

- **Step:** "Claude extracts schema rows (results, settings) and atomic claims through `extract_next` / `extract_record`; the platform verifies every quote and every number against the anchored source." (docs/specs/slice-2.md §User flow 5)
- **Inputs:** Included documents, protocol extraction schema
- **Outputs:** Extraction rows and claims with anchors and quotes
- **Method:** "Plus atomic claims (R-40): statement, type (finding / mechanism / limitation / negative result), evidence type, strength, anchor, quote." (docs/specs/slice-2.md §Design, Extraction schema)
- **Actor:** automated
- **Check:** "every extracted numeric value must occur in its verified quote or anchored table cell" (docs/specs/01-rigour.md §E, R-44)
- **Limits:** "OCR of scanned PDFs; figures as data (plots digitised)" (docs/specs/slice-2.md §Out of scope)

### D02

- **Step:** "dual extraction on a declared sample; field-level agreement; disagreements to the human; human audit sample of extracted values" (docs/specs/slice-2.md §User flow 6)
- **Inputs:** Extraction rows of two independent sessions
- **Outputs:** Agreement per field; human resolutions; audit error rate
- **Method:** "numbers must match exactly after normalisation; disagreements routed to the human" (docs/specs/slice-2.md §Design, Extraction quality)
- **Actor:** human-assisted
- **Check:** "above ceiling → schema or skill amendment" (docs/specs/slice-2.md §Design, Extraction quality)
- **Limits:** "The same sentence cited with a different span boundary counted as a disagreement" (docs/backlog.md §IDEA-52)

### D03

- **Step:** "Rows are grouped only by identical keys; no ranking crosses groups." (docs/specs/slice-2.md §Design, Comparability and evidence report)
- **Inputs:** Final extraction rows, comparability keys
- **Outputs:** Evidence report: groups, frontiers, counts of independent and copied results
- **Method:** "cross-paper frontiers use hardware-independent measures only (params, FLOPs/MACs, at the group's resolution)" (docs/specs/slice-2.md §Design, Comparability and evidence report)
- **Actor:** automated
- **Check:** "each frontier point traces to its rows; empty or single-source groups are stated" (docs/specs/slice-2.md §Acceptance criteria 12)
- **Limits:** "consistency check of copied results against the cited paper (IDEA-23)" (docs/specs/slice-2.md §Out of scope)

### D04

- **Step:** "a value extracted from a comparison table that cites another paper is marked `reported-in = cited`" (docs/specs/slice-2.md §Design, Verification)
- **Inputs:** Extracted comparison-table values
- **Outputs:** Copied-result flags
- **Method:** "not counted as an independent result" (docs/specs/slice-2.md §Design, Verification)
- **Actor:** automated
- **Check:** "values from comparison tables citing other papers are flagged and excluded from independent-result counts" (docs/specs/slice-2.md §Acceptance criteria 8)
- **Limits:** "compare it with that paper's own extracted value and flag mismatches (including version mismatches)" (docs/backlog.md §IDEA-23)

### D05

- **Step:** "M-C (miner spec, built-in miners, generic `mine_*` path), M-D (agent-authored miners, calibration, evidence admission" (docs/specs/slice-M-modules.md §v1 scope)
- **Inputs:** Miner spec, works selected by the protocol
- **Outputs:** Quoted rows per work, agreement, calibration report
- **Method:** "A registered miner uses only verifiable field kinds; every record carries at least one verified quote; free text is refused" (docs/specs/01-rigour.md §P, R-141)
- **Actor:** automated
- **Check:** "A registered miner's records count as evidence only after a human-labelled calibration in the same project passed declared thresholds above platform floors" (docs/specs/01-rigour.md §P, R-142)
- **Limits:** "the layer pass (`m-layer` v1, 2026-11-13, 371 works, Haiku pass A, Sonnet pass B on 40) reported `agreement 1.000` with 34 aligned rows and 12 unmatched" (docs/backlog.md §IDEA-69)
- **Practice (differs):** Spec (R-142): calibrated before evidence. Practice: the layer pass consumed every unit before a calibration was drawn; the guard (refuse production without a passed calibration) is a researcher ruling of 2026-11-13, not yet built. Evidence: "(a), refuse a production `mine_next` for a version with no passed calibration unless the protocol declares it exploratory" (docs/backlog.md §IDEA-69)

### D06

- **Step:** "The outcome of a registered hypothesis is computed from recorded results by its registered decision rule; no actor sets it" (docs/specs/01-rigour.md §N, R-121)
- **Inputs:** Registered hypothesis, ingested runs
- **Outputs:** hypothesis.evaluated by the system; human conclusion text
- **Method:** "applying a pre-registered numeric rule is bookkeeping, not judgement" (docs/specs/slice-6-hypotheses.md §Ruling 17)
- **Actor:** automated
- **Check:** "Own and reproduced results are never merged with reported results in groups, frontiers or counts" (docs/specs/01-rigour.md §N, R-125)
- **Limits:** not-stated

### D07

- **Step:** "Slice 2 builds no appraisal tools." (docs/specs/slice-2.md §Appraisal)
- **Inputs:** Included works
- **Outputs:** Not built: per-paper appraisal is deferred
- **Method:** "items typed `platform` (deterministic), `agent-span` (agent with verified quote, dual on a sample, audited), `judgement` (agent proposes, human decides)" (docs/backlog.md §IDEA-21)
- **Actor:** not-stated
- **Check:** not-stated
- **Limits:** "Deferred (2026-11-03)" (docs/specs/slice-2.md §Appraisal)
- **Practice (differs):** Rigour R-41 requires item-level appraisal in systematic mode; the platform builds none (deferred, IDEA-21). Evidence: "Slice 2 builds no appraisal tools." (docs/specs/slice-2.md §Appraisal)

## paper-writing

### W01

- **Step:** "the platform assembles verified claims, quotes, cells and lineage edges into a structured outline" (docs/specs/slice-7b-views-writing.md §Goal)
- **Inputs:** Verified claims, cells, lineage edges
- **Outputs:** Structured outline
- **Method:** "Claude writes prose sentence by sentence through MCP; every claim-bearing sentence names its supports; deterministic checks run at write time" (docs/specs/slice-7b-views-writing.md §Goal)
- **Actor:** human-assisted
- **Check:** "A claim-bearing sentence in any factory-produced text cites supports that resolve to verified spans or computed figures" (docs/specs/01-rigour.md §O, R-130)
- **Limits:** "the pilot related-work section written for real (acceptance 18)" (docs/specs/slice-7b-views-writing.md §v1 scope)
- **Practice (not-piloted):** The spec's pilot related-work section is listed as Later. Evidence: "the pilot related-work section written for real (acceptance 18)" (docs/specs/slice-7b-views-writing.md §v1 scope)

### W02

- **Step:** "BibTeX, CSL-JSON, a PRISMA 2020 flow diagram (SVG), an RO-Crate of the project, and nanopublications of claims and stated edges, all derived, deterministic, and free of library text" (docs/specs/slice-7b-views-writing.md §Goal)
- **Inputs:** Event log, corpus
- **Outputs:** Exports
- **Method:** "Exports and views are deterministic builders that name their scope and log position" (docs/specs/01-rigour.md §O, R-132)
- **Actor:** automated
- **Check:** "byte-identical for the same log" (docs/specs/01-rigour.md §O, R-132)
- **Limits:** "RO-Crate and nanopublications (X-B)" (docs/specs/slice-7b-views-writing.md §v1 scope)

### W03

- **Step:** "Views" (docs/specs/slice-7b-views-writing.md §Goal)
- **Inputs:** Corpus and graph
- **Outputs:** Onion, coverage map, timelines, horizon views
- **Method:** "each a deterministic builder output that names its filter and the event log position it was computed at" (docs/specs/slice-7b-views-writing.md §Goal)
- **Actor:** automated
- **Check:** not-stated
- **Limits:** "is empty with a stated notice otherwise" (docs/specs/slice-7b-views-writing.md §Reconciliation 5)

## review-verification

### V01

- **Step:** "Semantic support is judged by a verifier that did not write the sentence and sees only the sentence and its spans" (docs/specs/01-rigour.md §O, R-131)
- **Inputs:** Sentence and its cited spans
- **Outputs:** Verdict per sentence; stale and unsupported marks
- **Method:** "an independent verifier session judges whether each sentence is supported by the spans it cites" (docs/specs/slice-7b-views-writing.md §Goal)
- **Actor:** automated
- **Check:** "a human audits a sample of positive verdicts and the error rate is reported" (docs/specs/01-rigour.md §O, R-131)
- **Limits:** "`organisation` items (regions, labels, terms) and `test` items (slice 6 outcomes) are not supports in v1" (docs/specs/slice-7b-views-writing.md §Reconciliation 6)

### V02

- **Step:** "The release gate is slice M's `writing.release`" (docs/specs/slice-7b-views-writing.md §Reconciliation 1)
- **Inputs:** Verified draft
- **Outputs:** Released draft
- **Method:** "cannot be released under `systematic`" (docs/specs/01-rigour.md §O, R-130)
- **Actor:** human-assisted
- **Check:** "`writing.audit_label`, `manuscript.audit_label` | human | human | human | human" (docs/specs/slice-M-modules.md §Gates table)
- **Limits:** not-stated

### V03

- **Step:** "`trace` from any decision back to the question; `check` lists broken links and promotion gaps" (docs/specs/slice-1.md §User flow 11)
- **Inputs:** Event log
- **Outputs:** Trace chains; check findings; promotion gap list
- **Method:** "`check` fails on any broken link" (docs/specs/01-rigour.md §A, R-01)
- **Actor:** automated
- **Check:** "`trace` works backwards and forwards" (docs/specs/01-rigour.md §A, R-01)
- **Limits:** "`check` calls `read_all` over the whole log (cost grows with the log)" (docs/backlog.md §IDEA-18)

### V04

- **Step:** "Retractions, withdrawals, corrections and expressions of concern of dependent works are recorded with source and date" (docs/specs/01-rigour.md §L, R-104)
- **Inputs:** Notices on works the project depends on
- **Outputs:** Computed effects on dependents; human assessment
- **Method:** "require a human assessment; nothing is deleted" (docs/specs/01-rigour.md §L, R-104)
- **Actor:** human-assisted
- **Check:** "no agent judges it" (docs/specs/01-rigour.md §L, R-105)
- **Limits:** not-stated

### V05

- **Step:** "Before any output leaves the factory (review, hypothesis set, paper), it is defended." (docs/specs/01-rigour.md §I)
- **Inputs:** Review, hypothesis set or paper
- **Outputs:** Self-appraisal, simulated peer review, viva, sign-off
- **Method:** "Self-appraisal with the instruments reviewers use" (docs/specs/01-rigour.md §I, R-70)
- **Actor:** human-assisted
- **Check:** "unanswerable points go to the limitations, not away" (docs/specs/01-rigour.md §I, R-72)
- **Limits:** "Defence stage (proposed)" (docs/specs/01-rigour.md §I heading)
- **Practice (not-piloted):** Section I is marked proposed in the rigour document. Evidence: "Defence stage (proposed)" (docs/specs/01-rigour.md §I heading)

## lab-automation

No row. The factory has no step that drives instruments or laboratories. slice-6 states that the platform never executes experiment code, and the slice-1 and slice-2 out-of-scope lists name none. Absence is recorded here, not guessed into a row.

## other

### O01

- **Step:** "The platform is a deterministic Python service that stores, validates, schedules and logs research work. It never calls a model." (docs/specs/00-system.md §1 Scope)
- **Inputs:** Researcher's instructions, agent judgement through MCP tools
- **Outputs:** Validated events
- **Method:** "Append-only JSON Lines files in git" (docs/specs/00-system.md §4.1)
- **Actor:** automated
- **Check:** "Rebuild is deterministic: two rebuilds from the same events give the same state hash." (docs/specs/00-system.md §4.4)
- **Limits:** not-stated

### O02

- **Step:** "`input_blob`: the exact task content the agent saw, stored as a blob (auditability). Required for agent events" (docs/specs/00-system.md §4.2)
- **Inputs:** Agent act
- **Outputs:** Event with model, skill and input blob
- **Method:** "Every agent action records model version, skill/prompt version (hash of the skill text) and the exact input it saw" (docs/specs/01-rigour.md §A, R-04)
- **Actor:** automated
- **Check:** "`model` is reported by the agent unless supplied by the harness" (docs/specs/00-system.md §4.2)
- **Limits:** "`model` is reported by the agent unless supplied by the harness" (docs/specs/00-system.md §4.2)

### O03

- **Step:** "An agent records a suggestion set for one decision: a short list of items, each with its text, its grounds" (docs/specs/slice-8-develop.md §The loop)
- **Inputs:** Scientist's decision at a level (goal, questions, plan, seeds, probe, protocol)
- **Outputs:** Suggestion set; selection event; rendered formal document
- **Method:** "The scientist ticks the items to keep and may add items of their own" (docs/specs/slice-8-develop.md §The loop)
- **Actor:** human-assisted
- **Check:** "Each item names its grounds" (docs/specs/slice-8-develop.md §Rules learned)
- **Limits:** not-stated
- **Practice (differs):** Slice 8 records that the scientist's changes at every level were not captured by the factory before the suggest-and-select loop. Evidence: "the result changed at every level" (docs/specs/slice-8-develop.md §Problem)

### O04

- **Step:** "Every decision gate has a declared policy (explicit or preset) recorded with the protocol" (docs/specs/01-rigour.md §P, R-140)
- **Inputs:** Gate policy in the protocol
- **Outputs:** Autonomy label per output; methods statement of the policy
- **Method:** "`inbox.withdraw` | human | human | human | human" (docs/specs/slice-M-modules.md §Gates table)
- **Actor:** automated
- **Check:** "every output's autonomy is computable from events" (docs/specs/01-rigour.md §P, R-140)
- **Limits:** not-stated

### O05

- **Step:** "On a hosted project every event names an authenticated user (directly or as the agent's principal)" (docs/specs/01-rigour.md §M, R-111)
- **Inputs:** Hosted project acts
- **Outputs:** Attributed events
- **Method:** "acts on a human-act permission are refused to agents" (docs/specs/01-rigour.md §M, R-111)
- **Actor:** automated
- **Check:** "relayed human acts are counted and reported" (docs/specs/01-rigour.md §M, R-111)
- **Limits:** "multi-user authentication" (docs/specs/00-system.md §1)

### O06

- **Step:** "Slice 7a admits one exception: generated, read-only reports (Markdown, a self-contained HTML file, JSON)" (docs/specs/00-system.md §1)
- **Inputs:** Event log
- **Outputs:** Portfolio and reports
- **Method:** "they add no server and no interactive editing" (docs/specs/00-system.md §1)
- **Actor:** automated
- **Check:** not-stated
- **Limits:** not-stated
## What the specs do not cover (drafter's reading, not a finding)

- **lab-automation:** no step at all (see above).
- **implementation-execution:** the platform records runs and enforces order but executes nothing; the step itself is the researcher's, outside the factory, and unchecked beyond the nonce and timestamps.
- **Study planning above the protocol:** IDEA-39 (a versioned study plan, objectives and KPIs) is a backlog idea; the spec chain starts at the question (slice 1) and slice 8 adds the suggest-and-select loop. No row drafted for it.
- **Cost and time:** the screening cost model (IDEA-45) is a backlog idea; no spec step budgets tokens, time or memory outside the experiment budget of slice 6.
- **Practice evidence:** the pilot log in the repository (`docs/pilot/log.md`) holds three rows, all from before the first search. Practice of later steps comes only from backlog entries; the agentic-science pilot's own records were not read.
- **Data analysis of the review's own corpus:** miners (slice M) and the evidence report cover extraction and grouping; no spec step describes statistics over the corpus beyond counts computed from events.

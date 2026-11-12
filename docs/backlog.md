# Idea backlog

Ideas not yet in any spec. A backlog item is **not** a commitment: nothing here is built until a slice spec takes it in (`docs/specs/`). Decisions go to `decisions.md`; requirements go to the specs.

**Numbering:** take the next free number (check the whole file first; several sessions add entries).

**Statuses:** `new` (captured) → `triaged` (sized, linked to a slice) → `accepted` (named in a slice spec; link it) · or `parked` / `rejected` (with a one-line reason). Never delete an entry; change its status.

**Template**
```
### IDEA-nn — <title>
Status: new · Added: YYYY-MM-DD · Slice: <n or —> · Depends on: <IDEA-/slice/decision>
**What:** one or two sentences.
**Why:** the research need it serves.
**Rigour notes:** what must hold for it to be trustworthy.
**Open questions:** …
```

---

## Research cockpit (added 2026-11-01)

The overall idea: once all research projects live in the factory, a single view across them, with the living-literature machinery suggesting new work per project and a daily digest. IDEA-01–05 split it into separable pieces.

### IDEA-01 — Portfolio dashboard
Status: accepted ([slice-7a](specs/slice-7a-portfolio.md)) · Added: 2026-11-01 · Slice: 7 (views) · Depends on: slice 1 `status`, slice 3 (graph)
**What:** one page listing every project with its rigor mode, stage, open tasks, pending human decisions (disagreements, `unsure`, audits), last search date and new-candidate counts.
**Why:** see the whole research programme at once and know where a human decision is blocking.
**Rigour notes:** read-only projection of events; every number derived (R-05), never edited in the dashboard.
**Open questions:** artifact page vs. local web UI vs. a `factory dashboard` CLI report first.

### IDEA-02 — Per-project literature watch
Status: built (slice 4b: `watch_run` re-runs the planned queries on a cadence (`services/watch.py`); status corrected 2026-11-11; was: new) · Added: 2026-11-01 · Slice: 4 (living corpus) · Depends on: slice 1 protocol + search, R-27 replay
**What:** each project's recorded queries re-run on a schedule; new records are deduplicated against the corpus and placed in the project's **candidate inbox**.
**Why:** keep each corpus current without re-doing the review.
**Rigour notes:** suggestion is ranking, not selection — inbox items enter the corpus only through the project's screening protocol (living-review method profile). Each watch run is a recorded search run with PRISMA-S fields.
**Open questions:** frequency per source; whether arxiv-miner's daily scan becomes the arXiv adapter's incremental mode.

### IDEA-03 — Daily digest notification
Status: partly built (2026-11-11): the digest (slice 4b) has a feed section (slice 4c, branch `plan-feed`; built, reviewed, untested); delivery stays outside the platform · Added: 2026-11-01 · Slice: 4 · Depends on: IDEA-02
**What:** a scheduled task (Claude subscription, no API) runs the watches and sends a short digest: new candidates per project, pending decisions, retractions affecting included works.
**Why:** a daily research briefing instead of browsing arXiv.
**Rigour notes:** digest lists what was found and why it matched (query, seed similarity), never a verdict; quick triage from the digest is recorded as a screening decision with actor and rationale.
**Open questions:** channel (email, Slack, phone push, artifact page); quiet days; per-project opt-in.

### IDEA-04 — Cross-project suggestions
Status: new · Added: 2026-11-01 · Slice: 6 · Depends on: slice 3 regions, IDEA-02
**What:** a paper found for one project is flagged to others whose regions it touches (e.g. a linear-attention paper relevant to the angiography reconstruction project).
**Why:** the method-borrowing across fields that motivated the graph/onion design.
**Rigour notes:** a cross-project flag is a hint with a stated reason (shared region, method card match); it enters the other project only through that project's protocol.
**Open questions:** matching without embeddings (decision #9 open): labels, regions, citations.

### IDEA-05 — Idea and hypothesis capture from the literature stream
Status: new · Added: 2026-11-01 · Slice: 6 · Depends on: IDEA-02, hypothesis registry
**What:** when new papers suggest a direction (new method, contradiction, gap), Claude drafts an idea note linked to the triggering papers; the researcher promotes it to a registered hypothesis or discards it.
**Why:** turn reading into a traceable pipeline of research ideas.
**Rigour notes:** proposer ≠ evaluator (R-51); discarded ideas stay recorded (R-52); promotion to a hypothesis requires pre-registration (R-50).
**Open questions:** where idea notes live (this backlog is for the platform; research ideas belong in each project).

---

## Knowledge from the corpus (added 2026-11-01)

### IDEA-06 — Living benchmark table
Status: accepted ([slice-2](specs/slice-2.md)) · Added: 2026-11-01 · Slice: 2 (claims) · Depends on: claim extraction with verified spans
**What:** reported results as rows: method × dataset × task × metric × value × compute (params, FLOPs, throughput, resolution, hardware), each cell citing a verified source span. Views: Pareto frontier (accuracy vs. cost), coverage matrix.
**Why:** for questions like "best linear attention for vision" the answer is a frontier, not prose.
**Rigour notes:** comparability conditions are explicit columns; reported vs. reproduced marked; incomparable cells are never merged; derived rankings state the conditions they hold under.
**Open questions:** extraction schema per domain pack; how to normalise compute measures.

### IDEA-07 — Contradiction and gap finder
Status: new · Added: 2026-11-01 · Slice: 6 · Depends on: IDEA-06, claims
**What:** surface claims that disagree across papers, and untested combinations (e.g. mechanism never evaluated on dense prediction or medical images).
**Why:** contradictions and gaps are where research ideas come from; feeds IDEA-05.
**Rigour notes:** a contradiction lists both claims with spans and the conditions that differ; a gap is "not found in corpus", never "does not exist".

### IDEA-08 — Citation-gap check
Status: parked · Added: 2026-11-01 · Reason: hard to make reliable now; revisit after per-paper assessment exists.

---

## People and agents (added 2026-11-01)

### IDEA-09 — Onboarding briefings (humans and agents)
Status: new · Added: 2026-11-01 · Slice: 3/5 · Depends on: graph and regions
**What:** a generated project briefing — question, protocol version, key decisions and amendments, core works and regions, open issues — rendered as a reading path for a new student and as a **context pack** for a new agent session.
**Why:** humans and agents both join projects mid-way; today each Claude session reconstructs context ad hoc.
**Rigour notes:** an agent's context pack is versioned and stored as its `input_blob`, so what an agent "knew" is reproducible; briefings derive from events, not memory.

### IDEA-10 — Supervision view and performance record (humans and agents)
Status: new · Added: 2026-11-01 · Slice: 5 · Depends on: calibration and audit (slice 1), actors
**What:** per person and per agent role (role × model × skill version): work done, decisions pending, amendments proposed, and measured quality — calibration sensitivity/specificity, κ against partners, audit error rate, trend over time.
**Why:** supervise agents like junior team members, with evidence rather than impressions; the same view supports supervising students.
**Rigour notes:** metrics come only from calibration, agreement and audit events; a model or skill change starts a new performance record (links to the model-change regression idea).

### IDEA-11 — Roles, ownership and review (team model)
Status: new · Added: 2026-11-01 · Slice: 5 · Depends on: human identity (00-system §11)
**What:** project and region roles (PI, maintainer, contributor, agent role); owners per region (cf. CODEOWNERS); changes to a shared region or a protocol amendment by a contributor go through review and sign-off (cf. pull requests).
**Why:** several PhDs share regions (PINNs used by the TAVI and CFD projects); a change in one must not silently alter another's evidence base.
**Rigour notes:** sign-offs are events with the reviewer of record; downstream projects see an amendment's blast radius across projects.

### IDEA-12 — Human–human and human–agent screening teams
Status: new · Added: 2026-11-01 · Slice: 5 · Depends on: slice-1 dual screening
**What:** passes A/B can be any mix of people and agents (two students; student + agent); a third person adjudicates; agreement reported per pair type.
**Why:** standard systematic-review practice with two human reviewers, extended with agents as a measured third reviewer.
**Rigour notes:** pair composition recorded and reported; human–agent κ is evidence for when agents can replace a human pass.

### IDEA-13 — Contribution ledger (CRediT)
Status: new · Added: 2026-11-01 · Slice: 5/7 · Depends on: actors, events
**What:** author contribution statements (CRediT roles) and an AI-assistance statement generated from events: who framed, searched, screened, adjudicated, extracted, wrote.
**Why:** fair credit in teams and honest disclosure of automation.
**Rigour notes:** derived, never typed; humans confirm before submission.

### IDEA-14 — Lab rhythm: digests, routing and meeting packs
Status: new · Added: 2026-11-01 · Slice: 5 · Depends on: IDEA-03, IDEA-10
**What:** pending decisions routed to the responsible person; a weekly lab-meeting pack per project (progress, amendments, disagreements to discuss, new literature); handover reports when someone leaves a project.
**Why:** keeps a team synchronised without status meetings; continuity across student cohorts.
**Open questions:** visibility rules for unpublished ideas across projects and people.

## Plan 4 review carry-over (added 2026-11-01)

### IDEA-18 — Screening, calibration and audit: deferred review minors
Status: new · Added: 2026-11-01 · Slice: — · Depends on: slice 1 plan 4
**What:** minor findings of the plan 4 final review, not fixed in slice 1: count validators on `AuditSampled` and `CalibrationDrawn`; negative-input guards in `draw_audit` and `audit_size`; the private `_rigor_mode` has a third copy; audit labels for unsampled pairs are dropped silently; the batch-order test may pass by chance and the shuffle seed depends on the task count; `screen_record` marks the answered set after an invalid first item; untested paths (task kind mismatch, lease expiry, re-record after an amendment); direct tests for the obsolete-task and stale-decision agreement rulings; `cannot_assess_rate` typed `float | None`; `project_status` recomputes agreement and audit on every call; a pass that fails the sensitivity gate has no in-pass recovery (it needs an amendment).
**Plan 5b minors (reports, trace, check):** `check` calls `read_all` over the whole log (cost grows with the log); `prisma_flow` computes `final_outcomes` twice; `trace.py` (about 900 lines) is unsplit and `prisma.py` mixes the PRISMA flow with the PRISMA-S report; the hand-search adapter exists only in tests; `_event_for` takes the first event, which may differ from the live one if an audit label is superseded; `merge-verdict-conflict` ignores a merge whose members are still pending; the methods statement lists models and skills over all agent events, though its sentence says "Screening decisions".
**Why:** each is a small gap in evidence or robustness that does not change a result today.
**Rigour notes:** none changes an event or a verdict; the validators and the silent drop touch the audit record and should come first.
**Open questions:** whether the `project_status` cost matters before slice 3.

---

## Lessons from EvoScientist (added 2026-11-01; see references.md #20)

### IDEA-15 — Learning from experience through reviewed amendments
Status: new · Added: 2026-11-01 · Slice: 5/6 · Depends on: calibration, audit, protocol amendments, plugin skill versioning
**What:** a curator agent role reads audit errors, disagreements, `cannot-assess` spikes and failed runs, and drafts **proposed** changes: protocol amendments, new worked examples, or skill revisions. A human approves; the change is versioned.
**Why:** the factory should improve with use, as EvoScientist's AutoSkills does, without silent drift.
**Rigour notes:** learning enters only as amendments or worked examples (R-34), never as retrieved memory; a new skill version starts a new performance record (IDEA-10) and must pass the calibration sets before use; the proposer never approves its own change (R-51).
**Open questions:** whether lessons can be shared across projects (via domain packs) and who approves them.

### IDEA-16 — Registry of failed directions and null results
Status: new · Added: 2026-11-01 · Slice: 6 · Depends on: hypothesis registry
**What:** a first-class record of what was tried and did not work — idea, test, evidence, reason (no runnable code within budget, below baseline, refuted, infeasible) — linked to the works and runs involved, searchable before proposing new ideas.
**Why:** avoids repeating dead ends across students and projects; supports R-52.
**Rigour notes:** a failure is recorded with its conditions (budget, data, model), so "failed here" is not read as "impossible"; never deleted, only superseded.

### IDEA-17 — Experiment discipline for hypothesis testing
Status: new · Added: 2026-11-01 · Slice: 6 · Depends on: IDEA-16, R-50
**What:** experiment runs follow fixed rules: reproduce baselines first; change one variable at a time; sandboxed execution with time and output limits; acceptance criteria and analysis plan registered before running; ablations planned, not post hoc.
**Why:** turns agent-run experiments into evidence a reviewer can trust.
**Rigour notes:** deviations from the registered plan are recorded as deviations (R-14); results that beat baselines only under changed conditions are flagged.
**Open questions:** where experiments run (own servers vs. cloud sessions); link to an existing experiment tracker (decision #21).

**Not adopted (deliberate):** memory retrieved by embedding similarity into prompts (non-reproducible; conflicts with R-34 and decision #9 unless the retrieved content is recorded in `input_blob`); self-evolution without versioning; LLM-judge evaluation as primary evidence.

## Plan 5a review carry-over (added 2026-11-02)

### IDEA-19 — Withhold the resolved OpenAlex ID of a held-out seed
Status: new · Added: 2026-11-02 · Slice: — · Depends on: slice 1 plan 5a
**What:** `_held_out_tokens` in `mcp/server.py` withholds only the stated `seed.openalex`, so the OpenAlex ID that a DOI-only held-out seed resolved to is not withheld from MCP output (for example, from a source error note in a run summary).
**Why:** R-20 and acceptance 22 require held-out seeds to stay invisible to agent-facing tools, but the specs name no identifier set; the plan's constraint lists the seed ID, DOI and arXiv ID. A seed's resolved OpenAlex ID is outside the current token set, and it identifies the seed as well as its DOI does. Owner suggestion: plan 5b.
**Rigour notes:** adding it changes the token set only; no event or verdict changes.
**Open questions:** should any identifier that resolves to a held-out seed be withheld, and should R-20 / acceptance 22 name the set?

### IDEA-20 — Pass-B extension before dedup is current
Status: new · Added: 2026-11-02 · Slice: — · Depends on: slice 1 plan 5a, `dedup_run`
**What:** the pass-B sample extension (`screen_next` for pass B) can run before `dedup_run` is current, so two records of one work could be drawn independently. A later merge would leave the canonical work considered-not-added while its twin was sampled.
**Why:** the pass-B sample should draw each work once, and the PRISMA counts should match the deduplicated corpus; a sample drawn before the merge does not.
**Rigour notes:** options: (a) record the condition only, with no change to behaviour; (b) make the extension a no-op until `dedup_run` is current.
**Open questions:** does option (b) block a legitimate extension while dedup is stale?
**Plan 5b note:** the PRISMA flow reads only the canonical primary's final outcome after a merge, so a conflicting verdict on an absorbed record is not counted; `check` reports it as `merge-verdict-conflict`, which is the interim signal until the conflict is resolved by a rule.

---

## Deferred from slice 2 (added 2026-11-03; decision 44)

### IDEA-21 — Per-paper appraisal
Status: triaged · Added: 2026-11-03 · Slice: when a project needs it (required in `systematic`, R-41) · Depends on: slice 2 documents and anchors
**What:** item-level appraisal with a project-declared instrument; items typed `platform` (deterministic), `agent-span` (agent with verified quote, dual on a sample, audited), `judgement` (agent proposes, human decides); no overall score (decision 42).
**Open questions:** first instruments (ML evidence checklist from NeurIPS M14; RoB 2 / PROBAST for biomedical projects).

### IDEA-22 — PubMed search and PMC full-text route
Status: triaged · Added: 2026-11-03 · Slice: first biomedical project (TAVI, ND)
**What:** PubMed source adapter (PRISMA-S fields, no truncation) and PMC OA JATS route to Markdown.

### IDEA-23 — Consistency check of copied results
Status: new · Added: 2026-11-03 · Slice: after slice 2 · Depends on: copied-result flag
**What:** when a paper reports a baseline number copied from another paper in the corpus, compare it with that paper's own extracted value and flag mismatches (including version mismatches).

---

## Evidence beyond databases (added 2026-11-03)

### IDEA-24 — Grey literature in the review stages
Status: triaged · Added: 2026-11-03 · Slice: after slice 2 (outline: [specs/outlines/grey-literature.md](specs/outlines/grey-literature.md)) · Depends on: slice-2 Markdown conversion and local library; IDEA-21 for grey appraisal
**What:** planned grey-literature searching (registries, repositories, model hubs, targeted websites, web search with declared stopping rules, expert contact), page capture into the local library, and grey items flowing through the same dedup, screening, full-text and extraction stages with their own provenance.
**Why:** reviews limited to indexed literature miss technical reports, code results, registries and regulatory evidence, and are biased towards published positive results.
**Rigour notes:** declared in the protocol before searching; snapshots with hash and timestamp; web-search cut-offs declared and reported (explicit exception to R-21); grey evidence labelled and shown with and without it; later publications linked, not merged away.
**Open questions:** first sources (ML vs. biomedical); status of agent web search; capture limits; monitoring by the literature watch (IDEA-02).

---

## Plan A review carry-over (added 2026-11-03)

### IDEA-25 — Source-changed warning never clears
Status: new · Added: 2026-11-03 · Slice: — · Depends on: decision 46 item 8; decision 48
**What:** a `fulltext.source_changed` finding (in `check` and the `source-changed` status) stays forever; no event resolves it.
**Why:** a corpus with one changed source never reads as clean, so the warning stops carrying information.
**Rigour notes:** resolution must be a recorded human decision that names the document and the hash it accepts or rejects; the original bytes stay referenced; no silent overwrite.
**Open questions:** whether acceptance supersedes the document or marks the existing one; who may resolve.

### IDEA-26 — First-page identifier misattribution in researcher import
Status: new · Added: 2026-11-03 · Slice: — · Depends on: decision 46 item 7
**What:** the researcher import collects every identifier on page one. When the paper's own identifier is absent there, a single cited DOI or arXiv ID (a reference, a related paper) is taken as its identity and can attach the PDF to the wrong promoted work.
**Why:** a mis-attached document is silent provenance corruption for the work it lands on.
**Rigour notes:** an attachment must be checkable by the researcher before it becomes a document; ambiguous identifiers are reported, not guessed.
**Open questions:** label proximity ("DOI:", "arXiv:") versus requiring the first identifier only; a title match against the work as a check.

### IDEA-27 — `restore --missing` is not idempotent and stops at the first error
Status: new · Added: 2026-11-03 · Slice: — · Depends on: decision 48 item 4
**What:** after a source change or an `unavailable` result, a repeated `restore --missing` re-requests the same documents, and `restore --missing` builds all results before printing, so one unexpected exception prints nothing.
**Why:** a researcher cannot finish a restore of a library with a few unreachable sources.
**Rigour notes:** each document gets its own outcome in the report; an unavailable or changed result changes no document and is reported as such.
**Open questions:** whether to skip documents with an unresolved `source-changed` (depends on IDEA-25).

### IDEA-28 — `refresh` cannot page through the corpus when `limit` is below the promoted count
Status: new · Added: 2026-11-03 · Slice: — · Depends on: decision 48 item 5
**What:** `refresh` selects every promoted work sorted by id and takes the first `limit`, so works after that prefix are never reached by `refresh`. Explicit `work_ids` beyond `limit` are now refused, so the caller cannot split the work by hand either.
**Why:** a large corpus cannot be revisited in full with a small `limit`.
**Rigour notes:** the choice of works in each call stays deterministic and recorded in `fulltext.fetch_started`.
**Open questions:** a cursor on the tool, or a rotation by time of last attempt.

### IDEA-29 — Same hash with a different `source_version` restores silently
Status: new · Added: 2026-11-03 · Slice: — · Depends on: decision 46 item 9
**What:** `restore_document` compares only the raw hash. If the route serves identical bytes under another version string, the attempt is recorded `restored` and the document's recorded version is not updated or flagged.
**Why:** the version of record can differ from what the source now reports, with no event saying so.
**Rigour notes:** a version mismatch with identical bytes is recorded or refused, never silent.
**Open questions:** whether this is a `source-changed` variant or a separate attempt reason.

## Idea graph from full text (added 2026-11-04)

Three linked ideas from the researcher: read each selected paper for what it builds on and adds, take its references into the corpus, and draw the lineage as a graph. The researcher rates the reference and snowballing part (IDEA-31) as very important.

### IDEA-30 — Per-paper contribution extraction
Status: built (slice 3b: contribution items (CLAUDE.md); status corrected 2026-11-11; was: new) · Added: 2026-11-04 · Slice: — (candidate: extension of slice 2 extraction, or slice 3) · Depends on: slice 2 plan D (extraction, verified quotes), `document_read`
**What:** for each selected paper, extract a fixed set of items beyond result rows: the base idea (what the paper builds on), what it adds over that base, the reported results or improvements, and the stated limitations. Each item is an atomic claim with an anchored, verified quote.
**Why:** the evidence table says how well a method scores; this says what each method is and how it relates to the ones before it, which the lineage graph (IDEA-32) needs.
**Rigour notes:** every item carries a verbatim quote verified against an anchor (slice 2 verification); "builds on" and "adds over" are the paper's own statements, not inferred relations; the extraction schema is declared in the protocol before reading (R-13); dual extraction and audit apply as for other fields.
**Open questions:** whether these fields belong in the `ml-benchmark` domain pack or in a separate generic pack; how to treat papers that do not state a base idea.

### IDEA-31 — Reference extraction and snowballing from full text
Status: built (slice 3a, G1: references and snowballing, MCP, CLI and skill `rf-references` (CLAUDE.md); status corrected 2026-11-11; was: new) · Added: 2026-11-04 · Slice: — (candidate: right after slice 2; researcher priority: high) · Depends on: slice 2 plan B (canonical Markdown, anchors), slice 1 `search_chase`, work identity and dedup
**What:** parse each included paper's reference list from its canonical document, resolve every reference to a work (DOI, arXiv id, title match), and record the paper-to-reference links as events. Resolved references that are not yet in the corpus become snowballing candidates that enter through the project's screening protocol. Also record where in the text each reference is cited (the anchor), so the citation context is available.
**Why:** slice 1 chases citations through the search sources' metadata; the paper's own reference list is more complete for recent work and gives the citation context. This serves both the graph (IDEA-32) and a more complete corpus.
**Rigour notes:** link resolution is deterministic and recorded with its method and confidence; unresolved references are listed, never dropped silently; a snowballed work is a candidate, never auto-included; snowballing rounds are recorded search runs with their PRISMA-S fields (R-24, R-25); the corpus count of references is computed, not typed.
**Open questions:** reference parsing per input format (HTML bibliography, LaTeX `.bbl`, PDF reference sections are the weakest); how to rank candidates (frequency of citation across included papers is a derived number, not a judgement); stopping rule for snowball rounds.

### IDEA-32 — Idea lineage graph
Status: built (slice 3b: lineage and the graph (CLAUDE.md); status corrected 2026-11-11; was: new) · Added: 2026-11-04 · Slice: 3 (graph) · Depends on: IDEA-30, IDEA-31, slice 3 graph design
**What:** a graph whose nodes are papers and base ideas and whose edges are "builds on", "improves on" and "cites", built from the extracted contribution items and the resolved references. A path from a base idea through its improvements to the current best methods is readable from it.
**Why:** answer "what is this method an improvement of, and what improved on it" across the corpus, and show the field's structure beyond a ranked table.
**Rigour notes:** every edge cites its source (a verified quote for stated relations, a reference link for citations); a relation the paper does not state is not drawn, or is drawn as a separate, labelled "inferred" edge type decided by a human; the graph is a projection of events and can be rebuilt (R-05).
**Open questions:** the node identity of an "idea" (a method family vs. a paper); how to merge naming variants of one idea; who confirms an inferred edge.

### IDEA-33 — Intuition and foundations layer in the graph
Status: built (slice 3c: intuition layer (CLAUDE.md); status corrected 2026-11-11; was: new) · Added: 2026-11-04 · Slice: 3 (graph) · Depends on: IDEA-30, IDEA-32
**What:** for each extracted idea, an agent-written explanation of why it works, and links from the idea to the foundations it rests on. When a paper brings in an idea from another field (for example, a tool from applied mathematics), the graph gets a node for that background concept, with its own short explanation and links to the other ideas that use it, so the connection to the rest of the graph is visible.
**Why:** a lineage graph (IDEA-32) shows what came after what, not why a change helps. Understanding why a method works, and which older or outside ideas it borrows, is what lets a researcher judge whether it transfers to another problem.
**Rigour notes:** an intuition is interpretation, not evidence. It is stored as a separate node type, labelled "interpretation" with the agent's model, skill version and input blob, and it never counts as evidence in any report or comparison. Every foundation link cites the paper's own statement (a verified quote) or a cited source; a link the paper does not state is a human-confirmed "inferred" edge, as in IDEA-32. A human can mark an intuition as reviewed, wrong or superseded; corrections supersede and never edit.
**Open questions:** where background-concept nodes get their source (the citing paper's text, a textbook reference the researcher supplies, or a cited survey); how to keep the explanations short and checkable; whether the researcher writes the first version of a concept node and the agent only links to it.

## Researcher inputs and discovery provenance (added 2026-11-04)

The researcher re-raised IDEA-01 (a UI to manage several projects) on 2026-11-04, and added the two ideas below.

### IDEA-34 — Link inbox for researcher-supplied papers
Status: accepted ([slice 4a](specs/slice-4a-inbox-discovery.md), decision 61; implemented v1) · Added: 2026-11-04 · Slice: 4a · Depends on: slice 1 `seed_add`, IDEA-02 (candidate inbox), plan C/D pipeline
**What:** the researcher drops links (arXiv, DOI, publisher page) into a per-project inbox, from the CLI, the MCP server or a future UI; each link is resolved to a work, deduplicated against the corpus, marked as researcher-supplied, and then goes through the same path as any candidate: screening under the protocol, full-text acquisition, conversion and extraction.
**Why:** papers the researcher finds by reading, talks or colleagues are often the most relevant, and today they enter only as seeds.
**Rigour notes:** a supplied link enters the corpus as a candidate, never as an inclusion: it is screened by the protocol like every other record, and PRISMA reports it as its own source ("researcher-supplied") so the search remains reproducible. Supplying is a human event with the human actor. Whether supplied papers may be screened differently is a protocol choice declared before screening, not a silent default.
**Open questions:** one inbox per project or a shared inbox routed to projects; how this differs from `seed_add` (seeds steer search and are not screened the same way); whether a supplied link after the search date counts as a supplementary search.

### IDEA-35 — Record and report how each paper was discovered
Status: accepted ([slice 4a](specs/slice-4a-inbox-discovery.md), decision 61; implemented v1) · Added: 2026-11-04 · Slice: 4a · Depends on: slice 1 search events, IDEA-34
**What:** for every work, a computed discovery record: which routes found it (database search, snowballing backward or forward, researcher-supplied, seed, agent suggestion), whether a human or an agent first surfaced it, and when. Reports show per-route and human-versus-agent counts for the corpus, the included set and the final evidence.
**Why:** whether humans or AI systems find the papers that end up mattering is itself useful data, for this programme and as evidence about AI-assisted research. It can later inform how much weight a route deserves.
**Rigour notes:** the record is derived from events (actor kind and channel already sit on every event), never typed. Weighting by discovery route must never change screening or evidence counts silently: any use of it is a declared protocol rule, reported in methods, with the unweighted figures shown too.
**Open questions:** what "first surfaced" means when several routes find a work in one session; whether a researcher-supplied paper that a search also finds counts for both; what a weight would be used for (ordering screening, sensitivity analysis), since inclusion must stay protocol-based.

### IDEA-36 — Reuse extractions across projects
Status: new (to be folded into IDEA-37 as its shared mining layer) · Added: 2026-11-04 · Slice: — · Depends on: plan 2D (extraction), IDEA-01, IDEA-06
**What:** a shared, read-only library of finished extractions keyed by work, document version (canonical Markdown hash) and pack version. When a project includes a work that another project has already extracted with the same pack, the project can import those rows instead of extracting them again. The imported rows are re-verified deterministically against the project's own copy of the document (quote-in-cell, units), and the project extracts only the fields its protocol declares that the library does not hold.
**Why:** the same benchmark papers recur across ML projects. Extracting them again costs agent time and gives no new evidence.
**Rigour notes:** an import is a recorded event in the importing project, with the source project, the source extraction ids and both pass identities. It is never a silent copy. Imported rows count as reused, not as independent dual extraction, unless the source already had two agreeing passes; methods and the report state how many rows were imported. Rows become stale under the same rules as local rows: a different document version or pack version means no import. Each project's protocol can decline reuse, or require a fresh audit sample on imported rows. Events stay per project; the library is a projection over finished extractions, never a writable store.
**Open questions:** whether the library is built from events across `projects/` or kept as a separate store; how the protocol's comparability keys interact with rows extracted under another project's keys; whether a correction in the source project propagates as a staleness flag to the projects that imported it.

## Mining abstraction (added 2026-11-04)

The researcher proposed on 2026-11-04 that extraction be treated as *mining*: a set of miners runs over a corpus and reports back, more miners are added over time, their output is the basis for graphs and other views, and agents may author and run miners of their own. The entry records the abstraction so that later slices build towards it; nothing here is built until a slice spec takes it in.

### IDEA-37 — Miners: one abstraction for screening, extraction, references and graph nodes
Status: built (miners are registered, versioned and run in the pilot (`services/mining.py`); status corrected 2026-11-11; was: new) · Added: 2026-11-04 · Slice: — (after the worked example) · Depends on: plans 2C, 2D, 2E, G1, G2, G3; absorbs IDEA-36 and project-declared fields
**What:** four layers.
- *Corpus layer.* Works and their canonical documents, shared across projects (documents are already project-independent by content hash).
- *Mining layer.* A **miner** is a declared, versioned, hashed specification: a *selector* (which works, documents or sections it reads), an *output schema* (typed records whose fields come from a fixed menu of verifiable kinds: number with unit, enum, verbatim quote, citation, anchor reference, work reference), an *evidence rule* (every record anchored to a span and checked by a deterministic verifier), a *procedure* (the skill text the agent follows) and a *quality regime* (number of independent passes, agreement rule, human audit rate). A **run** is agents pulling tasks (`mine_next`) and submitting records (`mine_record`); the platform verifies, records events and never calls a model. A mined record is keyed by (miner id, miner version, document version), so it does not depend on any project.
- *Builder layer.* Deterministic consumers of mined records: the evidence report and its frontiers, the citation graph, the lineage graph, a contradiction finder (IDEA-07), and so on. A builder declares which miners and versions it reads.
- *Project layer.* A project's question selects corpus subsets, chooses miners and builders, and states in its protocol which mined records count as evidence.

What is built or planned today maps onto it as four hand-written miners sharing one machinery (task queue, dual pass, agreement, audit sample, span verification, staleness on document or schema change):

| Today | As a miner |
|---|---|
| Screening (slice 1, 2C) | work → include/exclude with cited criteria |
| Extraction (2D, `ML_BENCHMARK_V1` pack) | document → table rows, each value quoted from its cell |
| References (G1) | document → citation edges, each tied to a bibliography entry |
| Contributions, concepts (G2, G3) | document → lineage and concept nodes with source spans |

**Agent-authored miners.** Agents running over a corpus may propose and run miners of their own, under these rules: (1) a miner is registered (versioned, hashed) before its first task, as a protocol amendment is, and its schema cannot change after results are seen; (2) its fields use only the verifiable kinds above, so every value stays traceable to source text; (3) its output is *exploratory* until it passes a calibration sample (human-labelled set, declared agreement threshold), and only then may a protocol count it as evidence; the proposer is not the evaluator (R-51); (4) a discarded or failed miner stays recorded (R-52, IDEA-16).
**Why:** each new kind of question currently needs a new pack or service in code. A miner abstraction lets the corpus be organised for many scientific outputs at once, lets mined records be reused across projects (IDEA-36), and gives graphs and reports one uniform input.
**Rigour notes:** the platform still never calls a model; generality must not cost the specific checks (the number tokenizer, unit agreement, quote-in-cell, citation markers survive as field kinds and verifiers, not as free text); imported or reused records are labelled as such and do not count as independent passes unless their source had them; evidence status is a protocol decision, never a default.
**Open questions:** whether screening fits the same record model or stays a special case (its PRISMA accounting is stricter); how a miner's selector names document sections stably across converter versions; where the shared mining store lives (a projection across `projects/` or its own event log); how builders handle records from several versions of one miner; cost control for agent-authored miners run over a whole corpus.
**Plan:** generalise only after the worked example, from the four concrete miners (rule of three), via brainstorming on the existing specs into a slice spec.

### IDEA-38 — Stage modules with one contract, and gate policies for autonomy
Status: new · Added: 2026-11-04 · Slice: — (after the worked example, with IDEA-37) · Depends on: slice 1–2 stages, IDEA-37, `docs/02-production-lines.md`, rigor modes (00-system §6)
**What:** every step of the factory becomes a **stage module** with one contract, so that each step can be run by a human, by a human with agent help, or by agents alone, without changing the step. IDEA-37's miners are one module kind; the others follow the same contract.
- *Contract.* A module declares: its **inputs** and **outputs** as typed artifacts referenced by id (question, protocol, search run, candidate set, document, mined record, graph, hypothesis, experiment result); its **events**; its **gates** (the decisions that bind later stages, e.g. "protocol frozen", "screening agreed", "hypothesis registered"); its **quality regime** (passes, agreement, audit, calibration); its **checks** (what `check` reports for it); and the **methods text** it contributes to the report.
- *Implementations.* A module may have several implementations (strategies) behind the same contract, e.g. scoping by researcher interview, by probe search, or by an agent drafting from a seed set. The implementation and its version are recorded in provenance, so outputs from different strategies stay comparable.
- *Gate policy.* For each gate, the protocol states who may pass it: `human`, `agent + human audit (rate r)`, or `agent`. Rigor modes become preset gate policies (systematic: human at every binding gate; pilot: agent with audit; exploratory: agent). An *autonomous factory* is a gate policy, not separate code; a run states its policy in methods, and outputs carry the autonomy level under which they were produced.
- *Stages as modules (first cut):* question scoping → search → screening (filters) → acquisition and conversion → mining (IDEA-37) → builders (evidence report, graphs, gap and contradiction finders) → hypothesis generation and registration (R-50) → validation (experiments, falsification on data; IDEA-17) → reporting. These are the production lines of `docs/02-production-lines.md` expressed as compositions of modules.
**Why:** the researcher wants each step abstracted well enough that humans running the factory get clear, reusable steps, and that the same steps can later be automated for agents, moving towards more autonomous factories without rewriting the pipeline.
**Rigour notes:** autonomy is declared, never inferred: the gate policy is part of the hashed protocol and changes only by amendment; outputs produced under a weaker policy are labelled and never silently mixed with those produced under a stronger one; proposer ≠ evaluator holds at every gate (R-51), so an agent never passes a gate on its own proposal; the platform still never calls a model, so "agent" at a gate means an agent acting through MCP under its recorded identity.
**Open questions:** how much of today's per-stage code (screening, extraction, references) can move behind the contract without changing event types; whether gate policies are per project or per run; what a scoping module's output is precisely (the slice-1 question and protocol records, or a richer scope artifact); how hypothesis and validation modules fit the event model before slice 5 specifies them.
**Plan:** with IDEA-37, after the worked example: write the contract from the stages already built (scoping, search, screening, extraction, references), then spec new modules against it.

## Research planning (added 2026-11-06)

### IDEA-39 — Planning agent and a versioned study plan above the protocol
Status: triaged ([draft slice 8](specs/slice-8-develop.md)) · Added: 2026-11-06 · Slice: 8 (draft) · Depends on: `rf-frame`, `rf-protocol`, method profiles (decision 35), IDEA-38
**What:** a skill `rf-plan` that works with the researcher alongside framing to define the research plan: the aim and question type, a composition of methods with reasons, backward planning from the final claim, the analysis plan, risks, cost and stopping rules. A separate critic agent with no authoring context challenges the plan, and the researcher confirms it. The result is a recorded, versioned study plan with phases, each naming its method and handover, and each protocol points back to its phase. Sub-questions become a first-class part of the question.
**Why:** a protocol fixes the procedure of one method, not the argument from question to claim. A study may combine methods, for example Design Science Research as the frame, with a scoping review under a PRISMA-P protocol as its first phase. Today nothing records that, and `method_profile` holds one value, so scoping plus living cannot be declared.
**Rigour notes:** the plan is fixed before results and changes only by a recorded amendment with a reason. The method choice records the alternatives rejected. Only the researcher confirms a plan. A plan's phases must not weaken a phase's protocol requirements.
**Objectives and KPIs (researcher, 2026-11-06):** a study has one overarching goal, several objectives or sub-questions, and KPIs per objective, in the style of Goal-Question-Metric. Each is traced through the process: criteria, extraction fields and report sections name their objective, progress is computed from events, and an extraction field with no objective, or an objective with no field, is a gap. The stage must also develop the question before recording it: diagnose it, scan the literature, offer real alternatives, have it challenged.
**To revisit (researcher, 2026-11-07):** the research plan of the agentic-science pilot was accepted for now, to be developed further; come back to what a plan should contain.
**Open questions:** one project with phases or linked projects; whether a plan gates the probe; how `factory status` shows progress against the plan; which methods the router knows. Prototype by hand in the agentic-science pilot first (`rf-plan` draft kept outside the repo) and build only what proved useful.

### IDEA-40 — Evidence-backed factory design: run the factory on its own design choices
Status: new · Added: 2026-11-06 · Slice: — (after the first agentic-science pass) · Depends on: exploratory mode, `rapid-review` profile, IDEA-39
**What:** each substantial design choice in the factory gets a small review run by the factory itself, for example "which methods are best for research planning?". Each is a separate exploratory project that ends in a short evidence note linked from the decision it informs.
**Why:** the researcher wants factory design to rest on literature, not on what an agent recalls; each run also exercises the factory on a small real question.
**Rigour notes:** the factory judging its own design is circular, so results are advisory and a human decides. Methods recalled by an agent are marked unverified until such a review checks them. Keep each run small and time-boxed.
**Open questions:** which choices merit a review; a fixed cost limit per review; how a decision row links to its evidence note.

### IDEA-41 — Quick factory: a very fast mode for very small research projects
Status: new · Added: 2026-11-06 · Slice: — (after the first agentic-science pass) · Depends on: exploratory mode, `rapid-review` profile, IDEA-40
**What:** a very quick version of the factory for a small question: one short command or skill that goes from a question to a cited evidence note in one sitting, with a light frame, one search, single-pass screening, a small paper limit and a fixed cost limit. It is the vehicle for the small reviews of IDEA-40.
**Why:** the researcher wants to run many very small research projects, and the full path of probe, protocol, PRESS, calibration and dual passes is too heavy for them.
**Rigour notes:** still event-sourced and traceable, with every claim citing its source. The output states plainly that it is a quick review and which steps were skipped. A quick project can be promoted to a fuller mode without losing its record.
**Open questions:** how much of `exploratory` already gives this; the default paper and cost limits; which steps can be skipped with no risk to traceability.

### IDEA-42 — Local screening ranker with a stopping rule
Status: built (`services/ranking.py`, `ranking_model.py`, `ranked_queue.py` (decision 116); status corrected 2026-11-11; was: triaged (researcher, 2026-11-07: build before the agentic-sc) · Added: 2026-11-07 · Slice: — · Depends on: screening, a decision on local models
**What:** order title and abstract screening by similarity to the positive seeds, computed locally (for example an embedding model or active learning as in ASReview), so agents screen the likeliest records first and stop by a stated rule, such as a run of consecutive excluded records. The ranking, the model and the stopping point are recorded as events.
**Why:** the agentic-science probe returns about 2,000 to 2,300 unique records for a rapid review; screening every record costs millions of tokens. The researcher asked for a cheaper local alternative.
**Rigour notes:** ranking never excludes; unscreened records after the stop are reported as such in PRISMA, with the rule, and the stop is disclosed as a rapid-review shortcut. Held-out seeds must not be used to rank (R-20); only development seeds. Deterministic given model version and inputs.
**Open questions:** whether a local embedding model is compatible with "the platform never calls a model" (precedent: docling, decision 49) — needs a decision entry; which model; which stopping rule; how recall of the stop is checked (held-out seeds, audit sample).

### IDEA-43 — Capped forward snowballing from core papers
Status: built (`snowball_round`, `snowball_core_list` and `snowball_compare` exist; status corrected 2026-11-11; was: triaged (researcher, 2026-11-07: needed for the agentic-scie) · Added: 2026-11-07 · Slice: — · Depends on: IDEA-42 (ranker), snowballing (slice 3a)
**What:** a forward round starts only from core papers (the positive seeds plus papers the scientist marks core at full text), keeps only citing works that match a topic filter declared in the protocol, and takes at most N citing works per core paper, ordered by similarity to the development seeds. N, the filter and the core set are protocol fields, fixed before the round.
**Why:** forward snowballing is otherwise unbounded: in the pilot one seed (Co-Scientist) had 355 citing works in OpenAlex and another 119; a round from 200 to 500 included papers would add thousands.
**Rigour notes:** the cap and the filter are declared shortcuts, reported with the number of citing works not taken per core paper; marking a paper core is a human event; held-out seeds are never used to rank (R-20).
**Open questions:** whether citing works beyond N are listed for a later round; how "core" is recorded (a label or a screening field).

### IDEA-44 — Progress for long operations
Status: built for slice 8 operations (ranking, search, probe, snowball, dedup, chase; `services/progress.py`); not extended to the feed run, the automatic steps or headless runs (parked, plan `2026-11-11-restart-and-costs.md`) · Added: 2026-11-07 · Slice: 8 · Depends on: slice 8 phase I (live dashboard)
**What:** long operations (ranking embeddings, exhaustive search paging, snowball probes, deduplication) report progress while they run: done and total where known, rate, and an estimate of time left. Progress is ephemeral state (a small file or in-memory table read by the dashboard and a `progress` MCP read tool), never an event.
**Why:** in the agentic-science pilot the SPECTER2 ranking of 4,198 records ran for minutes inside an MCP call with no sign of life; the researcher asked for progress. The same holds for 20-page OpenAlex runs.
**Rigour notes:** progress is not provenance; nothing in it is recorded or counted. The final counts still come from the events.
**Open questions:** whether MCP progress notifications are shown by the client; how the dashboard reads progress without opening the write lock.

### IDEA-59 — Restartable steps: persistent drivers and a resume command
Status: built, reviewed (fixes in), partly tested, on `main` since the unification of 2026-11-12 (ae5f5b5); not tried live. Built on branch `plan-restart-costs` (plan `2026-11-11-restart-and-costs.md`): run drivers persisted in `projects/<slug>/runs/<id>/` (decision 119); `interrupted()` finder (a pure read), `factory resume [--dry-run]`, the hub Resume button and Interrupted panel, `factory runs adopt` for pilot-style drivers; usage-limit stops recognised as their own kind `limit` and held until the reset time (5-hour estimate when the time does not parse). Numbered IDEA-44 in the main checkout until 2026-11-11 · Added: 2026-11-08 · Slice: — · Depends on: project status, task leases, pilot log
**State at wrap-up (2026-11-12):** *Built:* everything above; nothing more is planned for v1. *Not built:* the dashboard Interrupted line shows counts only (IDEA-63). *Tests run* (one file per process, all pass): `test_resume*`, `test_runner`, `test_pipeline`, `test_cost_report`, `test_runs_adopt`, `test_usage_limit`, plus the feed, inbox, hub, dashboard, trace, decisions, check and MCP files fixed on the branch (see IDEA-63). *Not run:* the full suite; about 400 test files on the unified line (IDEA-65). *Index and events:* this line raised `PROJECTION_VERSION` to 82 earlier (now 83 on `main`); the wrap-up changed nothing the index stores, so no bump. No new event type: `runner.started` gained the optional fields `resumes` and `adopted` (defaults keep old events valid); the pilot log contains no `runner.*` events. *Next step needs:* one live trial with the researcher on `agentic-science` (Process now once, then a deliberate interruption and `factory resume`), and a real usage-limit stop recorded as raw stream-json to confirm the detection rule (IDEA-63 item 1).
**What:** every long-running step (screening waves, searches, ranking, conversion) keeps its driver script, prompts and MCP configuration in a persistent project folder, never in a session scratchpad or `/tmp`. A `factory resume <project>` command reads the derived stage, releases expired leases, and prints (or runs) the recorded runbook command for the step in flight.
**Why:** on 2026-11-08 a power loss left the events and leases intact but destroyed the screening driver, prompt and live-log scripts, which lived in `/tmp`; they were rebuilt from a session transcript. The platform restarts cleanly, the orchestration around it does not.
**Rigour notes:** the runbook is a pointer, not a decision; resuming never edits events; the command, its arguments and the prompt version are recorded so the restarted run is traceable.
**Open questions:** where the runbook is stored (project folder or an event, e.g. `step.runbook_recorded`); whether the pilot log is replaced by derived events; how interrupted headless screeners are detected (expired leases, `pass_joined` without completion).

### IDEA-45 — Screening cost model: where tokens, time and memory go
Status: built, reviewed (fixes in), partly tested, on `main` since the unification of 2026-11-12 (ae5f5b5); not tried live. Built on branch `plan-restart-costs` (plan `2026-11-11-restart-and-costs.md`): run cost reader from recorded run logs (API-equivalent prices), MCP unit counter per run (`units.json`), `factory costs`, hub Run costs page; pilot baseline in `experiments/run-costs/` ($235.84 over 763 runs, mining 92%). The cost-reduction experiments (batch size, criteria once per session, shorter skills) are not built · Added: 2026-11-08 · Slice: — · Depends on: IDEA-42, screening skill, CLI and MCP adapters
**State at wrap-up (2026-11-12):** *Built:* the measurement side. *Not built:* the reduction experiments. *Tests run:* `test_cost_report`, the cost reader and token-growth tests pass one file per process; the full suite was not run. *Index and events:* none added; costs are read from stored logs, not recorded as events. *Next step needs:* a decision on which reduction experiment to run first, and the costs of new runs once the hub's Process now is used live.
**What:** measure and report the cost of a screening run by component: per-screener process start (time, RAM per `factory serve`), tool-schema and ToolSearch overhead, tokens per turn as the transcript grows, cost per record against batches per session (for example 3 versus 10), batch size, skill length, criteria re-served with every batch. Compare an MCP screener with a CLI screener (Bash calls to `factory`), if the CLI can give each caller its own session identity for the independence guard.
**Why:** pass A of the agentic-science pilot cost about $0.25 per 100-record screener session (CLI estimate, Haiku); the transcript is re-read on every turn, so cost per record rises with session length. The researcher wants the costs understood and reduced in a later version.
**Rigour notes:** cost changes must not weaken independence (separate sessions per pass), the verbatim-quote check, the leases, or the calibration gate; any change to the prompt or skill length is re-checked against the calibration set.
**Open questions:** whether batch size is a protocol field or fixed; serving criteria once per session instead of per batch (a factory change); whether in-process subagents using the CLI can hold distinct session identities; per-run cost as a recorded figure (token counts are not events today).

### IDEA-46 — Declared tolerance for unscreenable records in pass A
Status: new · Added: 2026-11-08 · Slice: — · Depends on: screening agreement (`screen_agreement`), PRISMA, protocol
**What:** a protocol field (for example `unscreened_tolerance`: fewer than 3 records or at most 1% of the pass A queue) under which `screen_agreement` and the pass-settled check proceed although some pass A works have no live decision, because the work could not be screened for a stated technical reason (could not be acquired, an unrecordable identifier). Each such work is listed with its reason; the tolerance, the works and the reason are reported in PRISMA.
**Why:** on 2026-11-08 one record (a Korean-name work id, decomposed Unicode in the store) could not be recorded; the agreement check refused until it had a decision, and a deviation cannot satisfy it. The researcher: always accept 1% errors for pass A.
**Rigour notes:** a declared shortcut, never silent; fixed in the protocol before screening (or amended with a recorded reason); the unscreened works are disclosed as unscreened, not counted as excluded; applies to pass A only as ruled by the researcher.
**Open questions:** whether "fewer than 3" and "1%" are alternatives or both must hold; whether it also applies to pass B and full text; how a deviation record relates to the tolerance.

### IDEA-47 — Surveys and reviews kept as background and snowball sources
Status: new · Added: 2026-11-08 · Slice: — · Depends on: screening outcomes, snowballing (slice 3a), reference extraction
**What:** a work excluded under a "kept as background" criterion (EX02 in the agentic-science protocol: surveys and reviews of AI research systems) is recorded as background, not simply as an exclusion. Background works can be converted and have their reference lists extracted, so that a backward snowball round can take them as sources; they are not counted as included in PRISMA and carry no extraction.
**Why:** the agentic-science EX02 text says surveys are "recorded as background and snowball sources", but no mechanism does this: snowball rounds take only included works with an extraction. The 2026-11-08 audit also found two of 38 sampled agreed exclusions were surveys that the researcher labelled include (a wish for them to go on).
**Rigour notes:** background is a declared category in the protocol, reported separately in PRISMA; it never changes an inclusion count; a background work's references enter the corpus only through the protocol's snowball plan and screening.
**Open questions:** whether this is a screening verdict or a flag on an exclusion; whether background works need full-text acquisition; how it relates to the intuition layer's background concepts (slice 3c); whether the snowball plan names background sources explicitly.

### IDEA-48 — Remove line-number paragraphs from converted PDFs
Status: new · Added: 2026-11-09 · Slice: — · Depends on: docling converter (decision 49), `factory document convert`
**What:** a post-filter after docling that drops paragraphs consisting only of 1 to 4 digits that sit in a run counting up by one (the margin line numbers of a review-format preprint), before anchors are assigned. The converter version is bumped and the affected PDFs re-converted. The automatic coverage check (`factory document coverage`) could also ignore bare-number tokens, so these PDFs stop appearing as low recall.
**Why:** on 2026-11-09 the lowest-recall PDFs of the agentic-science pilot (for example 607 to 914 bare-number paragraphs in each of the three worst) were line-numbered preprints: each line number became its own paragraph with its own anchor. The text is intact; the numbers inflate the paragraph count and break word 5-grams at every line, which lowers recall and precision. The researcher chose to leave the conversions as they are for now.
**Rigour notes:** a bare number can be a real paragraph (a table value, a page number), so the rule needs the run condition; dropping paragraphs renumbers the anchors, so it is a converter version change and must come before anything cites them; the filter is recorded in the converter version.
**Open questions:** whether to filter in the converter or at read time; whether the other converters (latexml, pandoc) need a counterpart; whether the coverage check should ignore bare numbers in any case.

### IDEA-49 — Human resolution of cannot-assess at full text; NFC-tolerant `document_read`
Status: built 2026-11-12 on branch `idea-49-nfc-resolve`, merged into `main` 2026-11-12 (parts 1 and 2; not reviewed; part 3 not built, options below; follow-ups IDEA-66, IDEA-67) · Added: 2026-11-09 · Slice: — · Depends on: `screen resolve`, agreement outcomes (`final_outcomes`), screening NFC fix (`_as_stored`)
**What:** (1) `screen resolve` also accepts a `cannot-assess` single-pass or dual-pass work at full text, so the researcher can settle it to include or exclude. Today `cannot-assess` counts as promote and `resolve` refuses it ("not an unresolved disagreement or an unsure single-pass work"), so a work whose criterion the text could not settle, or whose document could not be read, goes to extraction as included. (2) `document_read` (and the batch membership check it uses) matches work ids after NFC normalisation, as `screen_record` now does.
**Why:** on 2026-11-09 three full-text pass A works were `cannot-assess` (a conference slide deck, a framework not shown to be LLM-based, and a Korean-ID work whose document the screener could not read: "not a record of a batch this session holds"). The researcher decided to exclude one of them; the platform could not record it.
**Rigour notes:** a resolution stays a human act with a reason and, for an exclusion, an EX criterion; a verdict recorded without a successful `document_read` should be refused at full text (the 2026-11-09 Korean-ID record got a `cannot-assess` verdict without reading the document).
**Open questions:** whether `cannot-assess` at full text should instead be a pending human item like `unsure`; how a language rule (non-English works dismissed) is expressed, as an EX criterion by amendment or a separate screening field.
**Built (2026-11-12, branch `idea-49-nfc-resolve`):** (1) `document_read` reads an id whose NFC form equals that of exactly one work as that work (the page carries the stored spelling), and the batch and miner membership checks (`_held_pins`, `_held_selection`, so `selected=` too) compare NFC forms. The cause: `normalize_title` applies NFKD, so a Hangul word in a work id (surname or title slug) is stored as jamo, while a model writes it composed. (2) At full text, `screen resolve` also accepts an unresolved `cannot-assess` work: single-pass (pass A `cannot-assess`) or dual-pass where the passes do not disagree and either is `cannot-assess` (`cannot-assess` against `exclude` was already a disagreement). Same rules as other resolutions: human only, a non-blank reason, an exclusion needs an EX criterion; no new event type and no index change. Unresolved, such a work still promotes (not PENDING; `passes_settled` unchanged), so the open question above stays open. `agreement.cannot_assess_open(stage=)` lists the works; `factory screen disagreements --stage full-text` prints them before the disagreements (it runs only once both passes have finished, as before). Title/abstract is unchanged. `screen resolve` also matches the work id after NFC normalisation against the resolvable works, so a Korean id typed or pasted composed is recorded under its stored (decomposed) spelling. Other CLI commands that take a work id still match exactly; the root cause (`normalize_title` applies NFKD, so Hangul is stored as jamo) cannot be changed without changing existing ids, so the remedy is NFC matching at each input.
**Tests run (one file per process, 2026-11-12):** new `test_document_read_nfc.py` (3; 2 fail on `main` with "not a record of a batch this session holds" and "not promoted at title/abstract"), new `test_fulltext_resolve_cannot_assess.py` (6, CLI and a decomposed id included), `test_agreement.py` (one new title/abstract test), `test_document_read.py`, `test_document_read_gate.py`, `test_miner_select.py`, `test_cli_fulltext_screening.py`, `test_mcp_fulltext_screening.py`, `test_screening_model.py` pass. `test_fulltext_screen_record.py`, `test_screening_record.py`, `test_mcp_screening.py` and `test_screening_next.py` have 34 failing tests, the same 34 on `main` 5bc9879 (compared file by file; e.g. `_serve_calibration` in `tests/screening_helpers.py` gets no batch: stale helpers, not this change). `test_acceptance_*screening.py` and `test_extraction_agreement.py` are deselected by the default markers (not run). Not run: the extraction-session path of the NFC fix with a decomposed id (shared code, covered only through the full-text screener path), the MCP surface with a decomposed id, the full suite.
**Not built, part 3 (verdict only after a successful `document_read`):** `document_read` writes nothing (module invariant), so the platform has no record that a session read a work. Options: (a) an in-memory set in the MCP server, per session, of works read; `screen_record` at full text refuses an item without one. No event, but lost on a server restart (a screener whose server restarted mid-batch would have to read again), and the CLI path (human screeners) would be exempt. (b) A new event (`document.read`) or index table recording reads, checked by `screen_record`. Durable and traceable, but it needs a new event type (breaks the CLI of every line that lacks it) and a projection bump, and every document read writes an event. (c) Require the item to carry the `markdown_hash` or `conversion_id` returned by `document_read`, checked against the pin. Cheap, no new state, but a pinned conversion id is already in the batch, so it proves little. (d) Leave it to the verified quote: a full-text verdict already needs an anchor that exists in the pinned conversion and, from an agent, a quote verbatim in that anchor. A verdict made without reading slips through only by quoting text known from the batch record (such as the title) at a guessed anchor; part 2 now lets the researcher settle such a `cannot-assess` work. (e) Tighten (d): refuse a full-text agent quote that is only the work's title. Cheap, no new state, but heuristic. Recommendation: (d) now, (b) if reads must become evidence; needs a ruling.
**Next step:** a review of the branch; the researcher resolves the 2026-11-09 `cannot-assess` works on the pilot once merged (the Korean-ID work can now be read and re-screened); a ruling on part 3 and on whether an unresolved full-text `cannot-assess` should be PENDING.

### IDEA-50 — Taxonomies as declared, versioned objects (miner-like), with a refinement loop
Status: new · Added: 2026-11-09 · Slice: — · Depends on: IDEA-37 (miners), the screening criteria and amendment machinery (stale rules), `m-descriptors`-style descriptor miners
**What:** a taxonomy is a declared, versioned, hashed specification, treated like a miner or a set of criteria: dimensions (technique, field, data, architecture, autonomy, human role, evaluation, stages), each with named categories (definition, inclusion cues, example quotes), whether a work takes one or several categories, and explicit `other` and `not stated` buckets. A **classification miner** is derived from it (fixed enums; every assignment carries a verbatim quote and anchor; a work with several categories gets one row per category). The loop: (1) descriptor miner quotes how papers describe each dimension; (2) frequency and keyword coverage lists are computed (counts, never judgements) with samples; (3) the researcher accepts, renames, merges or adds categories, creating taxonomy version N; (4) the classification miner runs; (5) the `other` bucket and the disagreements feed proposals for version N+1 (an agent proposes a split, merge or new category with the works behind it; the researcher decides); (6) only the works whose category rules changed are re-classified (as stale rules do for criteria). Reports show category counts, per-category agreement between passes, an audit sample per category, and the lineage of a category across versions (split from, merged into). Taxonomies are reusable across projects and comparable by diff.
**Why:** on 2026-11-09 the agentic-science pilot built its first taxonomy by hand: 14 quote fields mined for 368 works, keyword candidates with measured coverage (technique 74 and field 73 works matching nothing; autonomy 106 of 192, human role stated in only 136 works), and the researcher accepted 69 categories over eight dimensions as version 0. The process worked but lives in scripts (`screeners/taxo_*.py`), not in the platform; the categories and their patterns are not versioned events, and nothing tracks which works to re-classify when a category changes.
**Rigour notes:** the categories are the researcher's, never the agent's; keyword patterns only propose and count, they never classify; every assignment is quoted and verified like any miner row; counts are computed; a taxonomy version is part of the protocol hash when used as evidence; agent-proposed changes are marked as proposals.
**Open questions:** whether a taxonomy is a protocol section (like criteria) or a registered object (like a miner); how multi-label rows fit the miner row key; how `not stated` differs from `other`; how embeddings (SPECTER2) can suggest clusters without deciding them; lessons from the first spec: a required quote field must allow a "not stated" outcome for general-purpose papers (`field_of_science` blocked PaperClaw), and `selector.max_units` caps works, not paragraphs.

### IDEA-51 — Adding a miner should take one command and one page
Status: new · Added: 2026-11-09 · Slice: — · Depends on: IDEA-37 (miners), IDEA-50 (taxonomies), `miner_register`, `protocol amend`, dashboard (slice 7a)
**What:** make a new miner cheap to add and run. (1) `factory mine run MINER --version N --pass A|B --model M [--waves W --parallel P]` starts the headless sessions, the wave loop, the stop condition and the per-session log, replacing the copy-pasted prompt files and wave scripts of the pilot (`screeners/mine_waves*.sh`). (2) `factory protocol add-miner NAME VERSION --dual-sample F` lists a registered miner without the researcher re-writing the whole protocol spec as a file, and without the amendment having to be marked semantic when nothing but the miner list changes. (3) A pre-registration check (`factory miner check SPEC`) that explains the traps in plain words and a dry run of the selector on the real corpus: the passes rule (two), what `max_units` caps (works, not paragraphs), a required quote field that a general-purpose paper cannot satisfy, the procedure skill (`rf-mine`), enum values and units taken from a declared taxonomy. (4) A dashboard tab for miners (units, closed, open, rows, agreement, cost per work, the blocking unit when agreement waits). (5) A cheap way to close an unreadable unit with a stated reason.
**Why:** on 2026-11-09 adding `m-descriptors` took three versions and four protocol amendments (a selector cap misread, a procedure name, a required field), about $6 of wasted mining, and hand-copied driver scripts; adding `m-design-approach` was faster but repeated the file-based amendment. The researcher wants new miners to be easy to add later.
**Rigour notes:** adding a miner is a recorded protocol change with a reason; the check never judges a miner's content; the cost figures come from the sessions' own cost lines and are estimates, not events.
**Open questions:** whether a listing that changes only the miner list should be non-semantic; whether the run command belongs in the CLI (it starts model sessions, which the platform never does itself) or stays a documented runbook script; whether a dry run needs the documents converted.

### IDEA-52 — Agreement for free-quote miner fields should compare evidence, not exact strings
Status: new · Added: 2026-11-09 · Slice: — · Depends on: miner agreement (`mine agreement`), IDEA-50, IDEA-51
**What:** the agreement of two passes of a miner whose fields are verbatim quotes is computed on the exact value, and rows are aligned by a row key that is itself a quote. Replace this for quote fields by comparing the cited evidence (same paragraph or cell, or the quoted spans overlapping by a stated fraction), and let a per-work miner key its row on the work, not on a quoted `system_name`. Keep exact comparison for enum and number fields, where one correct value exists.
**Why:** `m-descriptors` v3 (Sonnet pass A, Haiku pass B on 28 works) reported agreement 0.347 with only 10 rows aligned and 37 unmatched. Recomputed by hand on the 199 fields both passes filled: exact same value 28%, same paragraph 57%, spans overlapping by at least 60% 54%; about 30% of fields were filled by only one pass. The same sentence cited with a different span boundary counted as a disagreement, and the row key (a sentence for one pass, "AI-Mandel" for the other) made whole rows unmatched.
**Rigour notes:** a laxer comparison must be declared in the miner's regime, not chosen after seeing the result; the calibration gate and the audit sample still use human labels; enum and number fields keep exact comparison.
**Open questions:** the overlap threshold; whether "filled by only one pass" is a disagreement or a completeness statistic; whether the regime's `field_agreement_min` applies per kind.

### IDEA-53 — Semantic agreement for miners: stable row alignment, secondary labels as sets, an equivalence judge
Status: new · Added: 2026-11-10 · Slice: — · Depends on: IDEA-52, miner agreement (`mine agreement`), IDEA-50 (taxonomies), IDEA-51
**What:** (1) A per-work miner aligns its two passes on the work (one row per work), and a multi-row miner aligns on an enum key (stage, system plus metric), never on a quote's location. (2) Optional `*_secondary` enum fields are compared as sets with the primary: a secondary label equal to the other pass's primary or secondary agrees, and a label present in only one pass is reported as completeness, not as a disagreement. (3) Free-text and quote fields are judged by an agent equivalence judge: a session outside both passes reads each A/B pair of a dual work and records `same`, `partial` or `different` with a reason as an event; the platform counts the verdicts. (4) The report shows agreement per kind (enum, number, text) and per field, with the disagreement list, and the miner regime declares which rule applies before a run. (5) A disagreement review feeds new miner versions with tighter enum definitions.
**Why:** on 2026-11-10 the pilot's second-pass agreement was 0.576 (classification), 0.427 (mapping), 0.347 (descriptors), 0.800 (design-approach). Recomputed per work on enum values only: classification 0.59 (primary categories only 0.71; field 0.94, technique 0.77, evaluation 0.53, architecture 0.65), mapping 0.51 (`human_vs_automated` 1/8, `human_adds` 0/7, `idea_assessment_method` 10/29). Secondary fields were mostly filled by one pass only (`data_secondary` 0/5, `field_secondary` 0/6). The researcher judged the measure too strict about quoting the same evidence when the target is meaning, not syntax.
**Rigour notes:** quotes stay mandatory as evidence for every value, they are never compared as the measure of meaning; the judge's verdicts are events with provenance and are audited by the researcher on a sample; the rule is declared in the miner spec before the run; no model is called by the platform.
**Open questions:** how the judge is served (a `mine_judge_next` task like `mine_next`); whether `partial` counts as half; the sample size for the researcher's check of the judge; gold labels per miner (about 15 works) as the arbiter of which pass is right.

### IDEA-54 — A project wiki as a rebuildable projection (explorer, vault, verified synthesis pages)
Status: built 2026-11-10 in the plan-8 worktree (plan 2026-11-10-site-hub; untested) · Added: 2026-11-10 · Slice: — · Depends on: miners (IDEA-37), evidence admission, writing and verification (slice 7b), `factory check`, references and lineage (slices 3a, 3b)
**What:** adapt Karpathy's LLM wiki pattern (raw sources, an LLM-maintained wiki, a schema; ingest, query, lint; `index.md` and `log.md`) to the factory. Layers: the library and converted Markdown are the immutable sources; the skills, protocol and miner specs are the schema; the wiki is a projection rebuilt from events, never edited by hand. Mechanical pages (one per work, one per category, an index, a log generated from events) need no model. Synthesis pages (a technique, a stage, a field, an overview) are written by Claude from quoted rows, every claim citing a work and every quotation or number checked against the recorded rows; through admitted evidence and the `rf-write` draft and verify path once miner rows can be admitted. Lint is a platform check: a page whose underlying rows changed is stale, an unquoted claim, an orphan category, a pass disagreement shown as a contradiction. Query answers can be filed back as pages. The explorer (list, timeline, graph, filters, link to the original on disk) and the Obsidian vault are two views of the same data.
**Why:** on 2026-11-10 the pilot built a prototype (`screeners/explorer.py`, `synth.py`): 370 works, a timeline, a graph, 64 category notes and three synthesis pages. The checker passed every quote and number and flagged only vague generalisations without a number or citation. Miner rows are not admitted as evidence, so the proper verification path is not available yet.
**Rigour notes:** synthesis is an interpretation layer, labelled as written by a model; nothing in it enters a result unless admitted; the mechanical check is no substitute for human review; the page records its input digest and model.
**Open questions:** how a synthesis page is versioned and invalidated when rows change; whether pages are stored as events or regenerated; how the lint check is run by `factory check`; scale beyond a few hundred works (search, embeddings); the graph layout for many-link works.

### IDEA-55 — One roof: every research product lives under `data/products` in the factory folder
Status: triaged (researcher, 2026-11-11: data root `data/` in the repo, git-ignored; factory hub above project hubs; move after the v2 miner run; plan [2026-11-11-one-roof](plans/2026-11-11-one-roof.md), script `scripts/migrate_pilot_to_data.sh`, not run) · Added: 2026-11-10 · Slice: — · Depends on: the site hub (plan 2026-11-10-site-hub, `factory site build`), IDEA-50, IDEA-51, IDEA-54
**What:** the researcher wants the factory and everything it produces under one folder. All research products of every project (the hub, dashboard snapshot, PRISMA, bibliography, explorer, wiki vault, results, miner agreement, taxonomy, synthesis pages, conversion and coverage reports) live under `data/products/` inside the factory folder, one subfolder per project (`data/products/<project>/<product>/`), with the hub page at `data/products/<project>/index.html`. The hub populated with every product (not only the three integrated so far) is the single entry point; nothing is produced by a script that lives outside the platform. The researcher's own documents (research plan, protocol, goal definition, demo log) and the project's source data (events, blobs, library) are decided separately.
**Why:** on 2026-11-10 the pilot's products were split between the repo, the pilot folder (`research-factory-pilot`: scripts, explorer, validation reports, staging PDFs, notes) and the data root (`root/projects/<slug>/site`). The researcher could not tell where things live, and a new project would get none of the pilot-only products. The layout of the first hub (sidebar of grouped products, product opened inside the hub, the dashboard theme) was approved; most of its entries are still "not yet integrated".
**Rigour notes:** products stay rebuildable projections of the events, never the source of truth; the platform never calls a model, so model-written pages (synthesis) are recorded documents the hub renders; the large source data (events, PDFs) is not tracked in git.
**Open questions:** whether `data/products` replaces the per-project `site/` folder or the project's folder links to it; whether `data/` also holds the project roots (events, blobs, library) or only products; what is git-ignored; where the researcher's documents and the demo log go (`docs/pilot/` is the current candidate); how an existing pilot is migrated without losing the event history (nothing is moved until the researcher says so).

### IDEA-56 — Version pairs and identifier-less works: dedup and the PDF importer
Status: accepted (plan docs/plans/2026-11-11-version-pairs.md, decision 117; built 2026-11-11 on plan-8-suggest-select, untested) · Added: 2026-11-10 · Slice: — · Depends on: dedup (`dedup run`), `fulltext import`, works without DOI or arXiv id
**What:** (1) Dedup should recognise a preprint and its journal version (same normalised title and authors, different year and DOI or none) as one work, or offer them to the researcher as a proposed merge, reversible like any merge. (2) `fulltext import` should match a file with no DOI or arXiv id by its first-page title, listing it as `identity_unchecked` for the researcher to accept, instead of `unmatched`. (3) An ambiguous match (one DOI on two promoted works) should name the candidate works so the researcher can choose which one takes the file.
**Why:** on 2026-11-10 seven promoted works with a PDF on disk could not be attached: three are a 2025 preprint and a 2026 journal article sharing one DOI (`ambiguous`; neither record has a document), two PDFs belong to an arXiv record that was not promoted while the promoted record of the same paper carries no identifier (`not promoted`), and two PDFs carry no identifier at all (`unmatched`). The full-text acquisition page lists them.
**Rigour notes:** a merge is a recorded, reversible act; a title match never imports without the researcher's acceptance; counts (PRISMA) must not change silently when records are merged.
**Open questions:** whether a version pair counts once or twice in the flow; which record keeps the identifiers; how the miners treat the merged work.

### IDEA-57 — Citation data for every work: in-corpus citations and an external count
Status: triaged — first part (reference layers) built and merged in `main` (ae5f5b5), untested; the citations product itself is not built. Plan [2026-11-11-reference-layers](plans/2026-11-11-reference-layers.md), last section "State at the hand-over to unification" · Added: 2026-11-11 · Slice: — · Depends on: reference extraction and links (slice 3a, `reference_links`), OpenAlex enrichment, the site hub (IDEA-54), snowballing (IDEA-43)
**What:** (1) For each work, store two separate numbers: the **in-corpus citation count** (works of this project whose extracted reference list resolves to it, computed from `reference_links`, never typed) and an **external citation count** from a named source with the date it was read (OpenAlex `cited_by_count` today; Semantic Scholar or Crossref as a second source, recorded per source so the two are never merged). (2) The hub gets a "citations" product: most cited inside the corpus, most cited overall, the gap between the two (influential outside the topic versus the corpus's own foundations), citations per year since publication, and works cited by the corpus but not in it (snowball candidates). (3) The explorer shows both counts per work, sorts by either, and filters on "cited by N or more corpus works".
**Why:** on 2026-11-11 the researcher asked which papers are the most cited. Inside the corpus (497 resolved links among 370 works) Co-Scientist is cited by 72 works and AI Scientist-v2 by 71; by the OpenAlex count Co-Scientist leads with 355, but the count exists for only 171 of the 370 works because the daily OpenAlex budget ran out. The two measures answer different questions and neither is complete.
**Rigour notes:** counts are read from a source at a date and stored as events with that source and date (an external count changes over time); the in-corpus count depends on how many reference lists were extracted and how many references resolved, so the report states both denominators (371 extracted, 497 resolved links); no source is called by a model.
**Open questions:** which second source is free and reliable enough (Semantic Scholar has a key-less tier); how often counts are refreshed; whether a work with no count is shown as unknown (never zero); whether self-citation inside the corpus is flagged.
**State at wrap-up (2026-11-12, branch `plan-reference-layers` = `main` ae5f5b5):**
- *Built:* T1–T5 (layer scheme, assignments, labels, calibration κ gate, MCP tools `reference_layer_next/record/status`, CLI `factory references layers …`), scheme v2 as earth rings, T8 (cited items rules v4: identifier wins, union of shared IDs, stripped and fuzzy titles, `aliases`), T9 (inner stratum of the calibration sample), `seed_version` (a revised scheme reuses an earlier draw), R3.7 and `re-resolve --only-identifiers`. Events: `reference.layer_scheme_recorded`, `reference.layer_assigned`, `reference.layer_labelled`; all three already occur in the pilot log. Index: the layer tables (projection 79 on the branch; `main` is 83 and includes them); no further index change at wrap-up.
- *Reviewed:* T1–T5 one Sonnet review (fixes in); T8, T9, T10 ruling, `seed_version` not reviewed.
- *Tests:* mypy and ruff pass (only the existing `ranking_model` transformers/torch errors). No pytest run (testing paused). **No test file exists** for `services/reference_layers.py` or `services/reference_items.py`; only `test_mcp_server.py` lists the tools. Write them (TDD debt) before relying on the κ gate or the merge rules.
- *Not built:* T6 (layer view in the hub), T7 (promotion: skill, default scheme template, docs), T10 (targeted, batched identifier lookups; ruling recorded in the plan), P2, P4 audit, P5, the citations product with the earth view.
- *Pilot state (agentic-science):* schemes v1–v3 recorded (v3 current: rings core, benchmark, applied, adjacent, background, off-topic; snowball core only; `seed_version` 2); 528 v1 title assignments; 30 v1 labels (Haiku κ 0.84); 9 of 50 v3 labels recorded, **41 pending** in `research-factory-pilot/reference-layers-calibration-labels-v2.tsv` (rows 10–50, keys in `…-sample-v2.tsv`; not in git, keep the file). About 4,671 assessable cited items under rules v4. One lookup run (`run_01M77CT2GZHY9BK98GNJ1YA7AW`) left open by the stopped re-resolve.
- *Next step needs:* (1) MCP configs repointed at one worktree built from `main` (IDEA-62); (2) record the 41 labels as the human actor, scheme 3; (3) Haiku calibration on the 50 items, report κ overall and per ring (gate 0.70); (4) title pass under v3 in batches of 100, one Haiku agent at a time; (5) settle the 8 pending screenings before the core-only snowball round; (6) a decision number for the layer scheme (unnumbered so far; next free is 120); (7) close the open lookup run.

### IDEA-62 — One code version per pilot index: a projection-version guard and a shared runtime worktree
Status: new, not built (2026-11-12); urgent before the next pilot run, since the configs still point at old worktrees · Added: 2026-11-12 · Slice: — · Depends on: the index projection (`PROJECTION_VERSION`), MCP configs of the pilot
**What:** (1) The index records which code version last rebuilt it and since when; a process whose `PROJECTION_VERSION` differs from a version written in the last N minutes refuses to rebuild and names the other version and process, instead of silently rebuilding. (2) The pilot runs from one shared runtime worktree (one branch) that every session and wave script points at; feature branches merge into it before they touch the pilot. (3) `factory check` reports when MCP configs of a project point at different code.
**Why:** on 2026-11-11 and 2026-11-12 the pilot index was rebuilt back and forth between versions 75, 77 and 79 by sessions and miner waves on different worktrees (plan-8, plan-reference-layers, scratch-combined); each call paid a full rebuild (about a minute), a gold-label script slowed to minutes per call, and label recording stalled twice. Nothing was corrupted, but the cost and the risk were invisible until processes were inspected by hand.
**Rigour notes:** the guard only refuses and reports; the index stays a rebuildable projection and events are never touched.
**Open questions:** the time window; whether an older version may ever rebuild over a newer one.

### IDEA-58 — Port of arXiv Miner: a learned daily feed per project (preference ranker, topics, feed product)
Status: built, partly reviewed, untested (2026-11-11). Feed engine v1: slice 4c, branch `plan-feed`, decision 118: **built, reviewed (fixes in), untested**. Hub page, one-click add, work queue, Process now: branch `plan-feed-hub`, decision 119, H1–H7: **built, reviewed (fixes in), untested**. Full ingestion pipeline Process all (every applicable stage incl. each project miner) and the hard unit cap, H8: **built, reviewed (fixes in), untested**. Dashboard feed and queue panel: **built, not reviewed**. 2026-11-12: the feed, inbox, hub and dashboard test files pass one by one; nothing tried live. Not built (Later): the learned preference ranker, named topics, other sources. See `docs/build-status.md` · Added: 2026-11-11 · Slice: 4c · Depends on: watch cycles (slice 4b, `watch_run`), the screening ranker (decision 116, IDEA-42), IDEA-02, IDEA-03, IDEA-57, the site hub (IDEA-54)
**What:** port the researcher's own tool (github.com/xserban/arxiv-miner: daily arXiv fetch, local embeddings, a ranker trained from likes and dislikes, topics defined by folders of reference PDFs, a reading list, export) into the factory as projections and events, not as a second application. Mapping: (1) arXiv client and throttle (`core/arxiv_fetcher.py`, `arxiv_throttle.py`) are already covered by the arXiv search source and `watch_run`; only the daily category feed (new papers of chosen categories, not a query) is new, as a watch plan kind. (2) Embeddings and the topic ranker (`embeddings.py`, `topic_ranker.py`) are already covered by the SPECTER2 ranker (`ranking_model.py`, `ranking.py`); a "topic" becomes a named reference set: a project's included works, a seed list or a folder of PDFs. (3) The learned preference ranker (`ranker.py`: running-average profile, logistic regression on cosine, metadata and novelty features, trained on likes and shown-but-not-selected) is new: likes, dislikes and reading-list marks become events (`feed.reacted`), the ranker is a recorded, versioned artefact with its training set and rank shown, never silent. (4) Diversification (exploration budget, novelty bonus, surprise picks) is new and must be disclosed in the feed. (5) Enrichment (author h-index, citation count) joins IDEA-57. (6) The feed is a hub product (a ranked, filterable list with like, dislike and save as commands that record events), and a liked paper can be sent to the project's link inbox (slice 4a) to enter a review. (7) Export (BibTeX, CSV, JSON) is already in the bibliography product.
**Why:** the researcher built this tool to track arXiv daily against a corpus; the factory now has the corpus (370 works with miner rows), the ranker and the hub, so the feed can rank against the whole project, not a hand-picked folder, and its picks can become review candidates. The tool's own limits (single user, Windows packaging, no export button, loose matches for topics of one or two PDFs) do not carry over.
**Rigour notes:** a ranking orders and judges nothing; reactions are the researcher's events (actor, time, rank shown, score shown, as in the tool's `selections` table); a ranker trained on reactions is not used to include or exclude in a review (R-20: it never touches held-out seeds); the daily feed is discovery, recorded as such (IDEA-35), not a search with a protocol; embeddings run offline from supplied weights like docling and SPECTER2 (decision 49, 116); the platform calls no model.
**Open questions:** whether the feed lives in one project or across projects (IDEA-04); whether the MiniLM or SPECTER2 encoder is used (one encoder per factory is simpler); how reactions are collected in a static hub (the dashboard server is GET-only; a small POST endpoint with a project token, or a CLI `factory feed react`); which of the tool's tests port.

### IDEA-60 — Capability catalog: tools and skills by lifecycle stage, with instruction flags
Status: built, reviewed (Sonnet review, fixes 714d31b), not tested: 11 tests written, none run; built once on a copy of `agentic-science`; merged into `main` with the unified line (ae5f5b5, 2026-11-12; branch `plan-catalog`, plan `docs/plans/2026-11-12-catalog.md`) · Added: 2026-11-12 · Slice: — · Depends on: site hub (IDEA-55), skill frontmatter
**What:** a project-hub product `catalog` (`factory site build --only catalog`) that lists every registered MCP tool once, under a nine-stage research-development lifecycle (Frame to Maintain, plus Cross-cutting). Each skill declares `stage:` in its SKILL.md; a tool takes the earliest stage of the skills that name it. Prompts are the skills' "when to use" lines; examples are numbered skill steps that call a tool. A count check compares the `@server.tool()` decorators with the built server's tool list.
**Why:** the researcher cannot see what the factory can do at each stage; 173 tools and 27 skills had no single view.
**Rigour notes:** nothing on the page is typed except stage labels and layout; flags (skill vs tool, skill vs skill, skill vs decisions, orphans, missing stage) are mechanical and never ruled on. First build: 46 orphan tools, 4 clash and 3 unknown-input flags, all 7 judged false positives by hand.
**Open questions:** tighten the clash rule (context of "do not read") and the "`tool` with `a`" rule (values vs inputs); move to the factory hub when it exists; skills for the 46 orphan tools.
**Wrap-up (2026-11-12, at main ae5f5b5):**
- Built: `services/site_catalog.py` (derivation, count check, flags), `services/site_catalog_page.py`, product `catalog` in `services/site.py` with an optional `Product.stamp` (hash of the SKILL.md files and `docs/decisions.md`, part of the catalog's fingerprint only); `stage:` frontmatter in all 27 `plugin/skills/rf-*/SKILL.md`.
- Not built: the factory-hub placement; MCP prompts (none registered); the IDEA-61 follow-ups.
- Run: ruff (clean), ruff format (clean), mypy --strict on the touched files (clean; the whole tree has 2 pre-existing errors in `services/ranking_model.py`, optional `transformers`), `factory site build --only catalog` on a copy of `agentic-science` (built; 173 tools registered and listed, 27 skills, 0 prompts, 96 examples, 54 flags: 46 orphan-tool, 4 clash, 3 unknown-input, 1 orphan-skill).
- Not run: `platform/tests/test_site_catalog.py` (11 tests); no live check in a browser.
- Index and events: none changed. PROJECTION_VERSION unchanged (83); no new event type (the catalog reads code and skill files, not the log).
- Side effect: the `stage:` lines change every skill's `name@sha8`; a session pinned to an old hash is refused after the plugin is reinstalled.
- Next step needs: a test run of `test_site_catalog.py`; one look at the page with the researcher; rulings on IDEA-61 (which of the 46 orphan tools get a skill or are marked researcher- or CLI-facing). No other branch is needed.

### IDEA-61 — Catalog follow-ups: sharper flag rules, orphan tools, review minors
Status: proposed (2026-11-12; orphan-tool groups ruled 2026-11-12, marker and group C follow-ups open) · Added: 2026-11-12 · Slice: — · Depends on: IDEA-60
**What:**
1. Clash rule: pair sentences only when both govern the same act. "Do not read … `check`" (pass independence in rf-appraise, rf-contributions, rf-extract) and "Never act on a `check` finding to clear it" (rf-run) are not opposites of "call `check` and report every finding" (rf-search). These 4 flags are false positives.
2. Unknown-input rule: in "`mine_resolve` with `a`, `b` or `neither`" (rf-mine line 46) the backticked words are values, not inputs. Check them against the schema's enum values before flagging. These 3 flags are false positives.
3. Orphan tools: 46 registered tools are named by no skill. Decide per tool whether it gets a skill, gets a mention in an existing skill, or is marked as researcher- or CLI-facing so it is no longer counted as an orphan.
   **Researcher's ruling (2026-11-12, on the catalog page built from `main` bff8848 on a pilot copy: 173 tools, 27 skills, 96 prompts, 54 flags, count check passes):** accept three groups for the 46 orphans. (A) read-only status, list and view tools need no skill: `benchmark_ledger_view`, `briefing_get`, `budget_status`, `card_view`, `conclusion_status`, `gate_status`, `inbox_list`, `ledger_view`, `progress_status`, `registry_query`, `whoami`, `xrun_list`, `feed_list`, `feed_status`, `watch_status`, `import_status`, `import_coverage`, `notice_list`, `review_list`, `reference_layer_status`, `snowball_core_list`, `grey_search_report`, `export_bibliography`, `graph_export`; mark them so they are not counted as orphans. (B) human-only acts stay deliberately unnamed in agent skills and are marked human-only: `calibration_label`, `miner_calibration_label`, `review_decide`, `lead_decide`, `audit_record`, `audit_sample`, `extract_audit_record`, `extract_audit_sample`, `extract_agreement`. (C) agent actions with no skill are follow-ups, each to get a skill mention or a recorded decision to leave it unused: `draft_release`, `draft_reorder`, `draft_repin`, `contradiction_propose`, `hypothesis_register`, `mine_import`, `library_adopt`, `library_adoptable`, `review_request`, `watch_run`, `feed_run`, `notice_assess`, `reference_layer_record`. `reference_layer_record` is probably named by `rf-reference-layers` in a form the rule does not match: check it with the sharper flag rules first. The marker for A and B (a researcher- or CLI-facing flag the catalog reads) is not built. The classification is from the tool names; each tool's docstring was not read.
4. Review minors (plan-catalog review, 2026-11-12):
   - make "also used in" links to the stage sections;
   - stop a tool named only in a negative sentence ("never call X") from taking that skill's stage;
   - render a skill whose stages are all invalid under Unassigned as well as flagging it;
   - de-duplicate `catalog.tools` when the server lists a name twice;
   - check that `site_widgets.table` escapes its cells;
   - check whether `build_server` creates directories during a catalog build.
**Why:** the first build's 7 conflict flags were all false positives, which teaches the researcher to ignore the flags table. The orphan count hides which tools have no instructions.
**Rigour notes:** the rules stay mechanical; the platform still never rules on a clash.
**Open questions:** whether orphan status needs a declared `audience` (agent, researcher, CLI) on each tool.

### IDEA-63 — Follow-ups from the restart, costs and index-deadlock work (branch `plan-restart-costs`)
Status: partly done (2026-11-12). Done: (3) the deadlock cause was confirmed and fixed in the test harness, not the product: `tests/world_cache.py` built a second `Index` on the same lock file while the writer's host check kept the first; `Index.reopen()` refreshes in place (6935a07; a new test fails without the fix); no second Index on one project was found in product code, and the hub server was not reproduced as affected, so the GC hypothesis below is withdrawn. (4) and (5) all diagnosed and fixed: product bugs feed arXiv `version` always None (e5d7423), `check` false `broken-link` on cited decision suggestions (6858d22), trace kind order with `appraisal` moved before `claim` by the researcher's ruling (383aa8e); the rest were stale or wrong tests, fixed without weakening (8b89977, 0dfd2ff, f697e41, 8d84a33, 69e379e, c0c305a, 50760df, eb79e47, b9b601f, 5832221). (6) reconciled at the unification. Open: (1) and (2) · Added: 2026-11-11 · Slice: — · Depends on: IDEA-59 (restart), IDEA-45 (costs)
**What:** open items left when `plan-restart-costs` was reviewed, to be taken as one round. (1) Usage-limit stops: detection is built (rule 1 on the CLI message, rule 2 on an errored final line with no units closed, 5-hour fallback expiry when the reset time does not parse); verify against a raw stream-json log of a real stop, and whether `claude -p` marks such a stop as an error (assumption). The real wording is `You've hit your 5-hour limit · resets 1pm (Europe/Bucharest)` (pilot logs 2026-11-11, plain text through `live.py`). (2) The dashboard Interrupted line lists counts only. (3) Index self-deadlock: the event writer's host check (`hosted_by`) waited on an exclusive lock the same process already held; fixed on the branch for restored test worlds (commit 6935a07), but the cause (a lock holder released by garbage collection clearing the "already holding" flag) is a hypothesis; confirm in the product code, and whether a long-running process (hub server) can freeze the same way. (4) Failures on the branch that are not diagnosed: `test_world_cache::test_second_build_is_restored_identically` (unclear whether it predates the fix), `test_inbox_reports::test_trace_reaches_inbox_item`, one `test_feed_service` failure (missing arXiv version, a code bug), and 12 that fail without the fix (`test_dedup_held_matches` 6; one each in `test_feed_add`, `test_feed_read`, `test_feed_mcp`, `test_inbox_screening`; two in `test_feed_cli`). (5) The four branch test files `test_runner`, `test_pipeline`, `test_cost_report`, `test_runs_adopt` were failing for fixture reasons at the last report. (6) Numbering: restart is IDEA-59 and IDEA-44 is "Progress for long operations" (renumbered 2026-11-11); the main checkout's copy of the backlog still called the restart idea IDEA-44 until this merge.
**Why:** a limit stop exits 0 and was recorded as a complete run, hiding earlier interruptions; a silent self-deadlock in a critical module is the worst kind of failure.
**Rigour notes:** detection stays a read-time projection of the stored log (no event field, `interrupted()` stays a pure read); no test is weakened to pass; the deadlock fix is a critical-module change merged with its review and a revert check.
**Open questions:** whether to hold a stage forever when the reset text does not parse (decided: 5-hour estimate); merge order of `plan-feed-hub` and `plan-restart-costs`.

### IDEA-64 — Miner design decisions made explicit, and a whole-text reading mode
Status: new · Added: 2026-11-12 · Slice: — · Depends on: IDEA-37 (miners), IDEA-50 (versioned objects), IDEA-53 (semantic agreement)
**What:** when a miner is defined, the choices that shape what it can find are put to the researcher one by one and recorded in the spec's rationale: (1) paragraph selection: a heading list, suggest-then-select (candidates per field from cues, recorded with the selected anchor), or the whole text minus tables and references; (2) per field, whether the fact can sit anywhere in the paper; (3) what an absence value means and what it must quote (not "the nearest sentence"); (4) rows per work; (5) works per session and which model reads which pass; (6) whether a field is a quote-level fact or a paper-wide judgement (then it needs a semantic or citation-based method, e.g. `builds_on_relation`). Platform pieces: selector patterns per field instead of per miner, a whole-text mode, a way to run a miner on a named set of works (today `mine_next` serves the next unit and calibration draws its own sample), and the suggested anchors recorded on the row.
**Hub and traceability:** (1) a field view: pick any miner field (`code_status`, `data_status`, `release_statement`, a taxonomy field) and list every paper with the value, quote, anchor, miner and version, pass and model, filterable by value, each row linked to the paper's text at that anchor; a URL inside a quote becomes a clickable link (a pattern match on the stored quote, no judgement). (2) an all-miners paper page: for one paper every miner's rows side by side, all passes and versions (today the explorer reads only pass-A rows of the miners a profile maps to a role, `site_corpus.py`), disagreements marked, the gold label when the paper is in a calibration. (3) a calibration page per miner version: the drawn works, the gold labels, what each pass recorded, field agreement, links to the quotes. (4) rejected `mine_record` attempts recorded as events with the reason (today they exist only in session logs), and a session record for each run (model, times, reads, attempts, cost; `factory runs adopt` for script-run sessions). Found 2026-11-12: a calibration run showed `document_read` 60,000 characters per page is too large for one reply; the first read comes about a minute after `mine_next`.
**Why:** miners v2 field study (2026-11-12): `code_status` 42% and `data_status` 58% absence with real release statements missed (keyword check: up to 37 and 88 works), a heading selector that omits reproducibility, appendix and data sections, 34% of quotes taken from the first paragraph of a section, and a platform instruction ("leave out a field the document does not state", `MINE_INSTRUCTIONS`) that contradicts the v2 absence rule in the session prompt. The agreement per field is a weak signal for these because both passes see the same paragraphs.
**Rigour notes:** the platform proposes nothing it judges; a suggestion is a candidate, never a value; quote checks stay; the choice of mode is part of the miner version.
**Open questions:** cost of whole-text reading with Haiku at about 10,800 tokens per paper (median; 22,200 at the 90th percentile) and a transcript re-read each turn; whether one paper per session is needed; a sample drawn from known misses needs a work filter on the pass.

### IDEA-65 — Known test failures at the 2026-11-12 unification of the lines
Status: new (2026-11-12) · Added: 2026-11-12 · Slice: — · Depends on: the `unify` merge (main fast-forwarded from 8e68849)
**What:** failures that were already present on `plan-feed-hub` (and for the snowball test on `plan-reference-layers`) before the merge, found when the lines were unified; none is caused by the merge. (1) Ten MCP test files fail with the same counts on `plan-feed-hub` and on the unified line: `test_mcp_concepts` 1, `test_mcp_document` 1, `test_mcp_experiments` 1, `test_mcp_fulltext` 1, `test_mcp_hypotheses` 1, `test_mcp_living` 1, `test_mcp_protocol` 4, `test_mcp_references` 8, `test_mcp_screening` 6, `test_mcp_server` 1 (25 tests). The three read cases point at expected per-role tool lists that were not updated when tools were added (`reference_layer_next`, `intuition_next`) and a changed parameter (`work_id` for `session`); six files were not read. (2) `test_snowball_forward`: `FORWARD_ROUND_RE` in `model/references.py` now matches `openalex:W1,title_and_abstract.search:a`, which the test expects not to match (the test is unchanged since `plan-8-suggest-select`, the regex changed on `plan-reference-layers`). (3) About 400 of the 472 test files were not run on the unified line; 61 files in the areas both lines changed were run and pass, and twelve index tests that pinned `PROJECTION_VERSION` at "67" were updated to 83.
**Why:** a green baseline on `main` before further work; the owners of the tool lists (reference layers, feed, intuition) know whether each new tool in a role is intended.
**Rigour notes:** no test is weakened to pass; a changed expected list needs a check that the new tool belongs in that role (`services/access.py`).
**Open questions:** whether the regex or the test is right for (2); the full-suite run in batches on the unified line.
**Addendum (2026-11-12, IDEA-49 work):** four screening files fail on `main` 5bc9879 with 34 tests in all, the same before and after the IDEA-49 branch: `test_screening_next.py` 15, `test_screening_record.py` 11 of 12, `test_mcp_screening.py` 6 (already counted in (1)), `test_fulltext_screen_record.py` 2. One cause traced: `_serve_calibration` in `tests/screening_helpers.py` asserts a calibration batch that `screen_next` no longer serves, so the helpers are stale against the calibration gate. The list is reproducible by running each file alone and collecting the FAILED lines.

### IDEA-66 — NFC-tolerant work ids at every input
Status: new · Added: 2026-11-12 · Slice: — · Depends on: IDEA-49 (`document_read`, `screen resolve`), screening NFC fix (`_as_stored`)
**What:** every CLI command and MCP tool that takes a work id matches it after NFC normalisation, as `screen_record`, `document_read` and `screen resolve` now do: an id whose NFC form equals that of exactly one stored work names that work, and events store the stored spelling. Candidates: `calibrate label`, `audit label`, `document convert`/`fetch` by work, `extract_record`, `mine_record`, `appraisal_record`, `contribution_record`, `trace`, `lead_record`, `label_apply`, and the hub's write path. Preferably one shared helper (a work-id resolver in `services/`) instead of a copy per module.
**Why:** `normalize_title` applies NFKD, so a Hangul word in a work id (surname or title slug) is stored as jamo, while a model or a person writes it composed; the two look identical and differ as strings. Changing the id scheme would change existing identities, which an id may never do, so the remedy is matching at the boundary. On 2026-11-09 the pilot's Korean-ID work was refused by `document_read`.
**Rigour notes:** matching never merges two works: an id that matches several stored ids by NFC form is refused; events always carry the stored spelling, so the log stays consistent; no stored id is rewritten.
**Open questions:** whether to also normalise new ids to NFC at creation (it would change the id of a work first seen after the change only if its basis contains Hangul or other non-composing scripts, but two spellings would then coexist in one project); whether the helper belongs in `model/work_ids.py` or `services/`.

### IDEA-67 — Full-text cannot-assess works visible as a human queue
Status: new · Added: 2026-11-12 · Slice: — · Depends on: IDEA-49 (`cannot_assess_open`, `screen resolve`), the site hub and dashboard, `factory status`
**What:** show the unresolved full-text `cannot-assess` works where the researcher looks: `factory status` (a count per stage), the dashboard and the hub's screening page (the works, each pass's criterion, quote and anchor, a link to read the document, and the resolve command), and `screen disagreements --stage full-text` before both passes finish (today it needs `screen_agreement`, which waits for the passes). Optionally a `factory screen cannot-assess --stage full-text` listing.
**Why:** IDEA-49 lets the researcher settle these works, but they are listed only once both passes finish, so a work whose document could not be read can reach extraction unnoticed.
**Rigour notes:** listing is read-only and computed from events; the resolution stays a human act with a reason; whether an unresolved `cannot-assess` blocks extraction is the ruling still open in IDEA-49.
**Open questions:** whether the queue should block extraction (the IDEA-49 ruling); whether title/abstract `cannot-assess` rates deserve the same view.


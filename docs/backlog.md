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
Status: new · Added: 2026-11-01 · Slice: 7 (views) · Depends on: slice 1 `status`, slice 3 (graph)
**What:** one page listing every project with its rigor mode, stage, open tasks, pending human decisions (disagreements, `unsure`, audits), last search date and new-candidate counts.
**Why:** see the whole research programme at once and know where a human decision is blocking.
**Rigour notes:** read-only projection of events; every number derived (R-05), never edited in the dashboard.
**Open questions:** artifact page vs. local web UI vs. a `factory dashboard` CLI report first.

### IDEA-02 — Per-project literature watch
Status: new · Added: 2026-11-01 · Slice: 4 (living corpus) · Depends on: slice 1 protocol + search, R-27 replay
**What:** each project's recorded queries re-run on a schedule; new records are deduplicated against the corpus and placed in the project's **candidate inbox**.
**Why:** keep each corpus current without re-doing the review.
**Rigour notes:** suggestion is ranking, not selection — inbox items enter the corpus only through the project's screening protocol (living-review method profile). Each watch run is a recorded search run with PRISMA-S fields.
**Open questions:** frequency per source; whether arxiv-miner's daily scan becomes the arXiv adapter's incremental mode.

### IDEA-03 — Daily digest notification
Status: new · Added: 2026-11-01 · Slice: 4 · Depends on: IDEA-02
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
Status: new · Added: 2026-11-04 · Slice: — (candidate: extension of slice 2 extraction, or slice 3) · Depends on: slice 2 plan D (extraction, verified quotes), `document_read`
**What:** for each selected paper, extract a fixed set of items beyond result rows: the base idea (what the paper builds on), what it adds over that base, the reported results or improvements, and the stated limitations. Each item is an atomic claim with an anchored, verified quote.
**Why:** the evidence table says how well a method scores; this says what each method is and how it relates to the ones before it, which the lineage graph (IDEA-32) needs.
**Rigour notes:** every item carries a verbatim quote verified against an anchor (slice 2 verification); "builds on" and "adds over" are the paper's own statements, not inferred relations; the extraction schema is declared in the protocol before reading (R-13); dual extraction and audit apply as for other fields.
**Open questions:** whether these fields belong in the `ml-benchmark` domain pack or in a separate generic pack; how to treat papers that do not state a base idea.

### IDEA-31 — Reference extraction and snowballing from full text
Status: new · Added: 2026-11-04 · Slice: — (candidate: right after slice 2; researcher priority: high) · Depends on: slice 2 plan B (canonical Markdown, anchors), slice 1 `search_chase`, work identity and dedup
**What:** parse each included paper's reference list from its canonical document, resolve every reference to a work (DOI, arXiv id, title match), and record the paper-to-reference links as events. Resolved references that are not yet in the corpus become snowballing candidates that enter through the project's screening protocol. Also record where in the text each reference is cited (the anchor), so the citation context is available.
**Why:** slice 1 chases citations through the search sources' metadata; the paper's own reference list is more complete for recent work and gives the citation context. This serves both the graph (IDEA-32) and a more complete corpus.
**Rigour notes:** link resolution is deterministic and recorded with its method and confidence; unresolved references are listed, never dropped silently; a snowballed work is a candidate, never auto-included; snowballing rounds are recorded search runs with their PRISMA-S fields (R-24, R-25); the corpus count of references is computed, not typed.
**Open questions:** reference parsing per input format (HTML bibliography, LaTeX `.bbl`, PDF reference sections are the weakest); how to rank candidates (frequency of citation across included papers is a derived number, not a judgement); stopping rule for snowball rounds.

### IDEA-32 — Idea lineage graph
Status: new · Added: 2026-11-04 · Slice: 3 (graph) · Depends on: IDEA-30, IDEA-31, slice 3 graph design
**What:** a graph whose nodes are papers and base ideas and whose edges are "builds on", "improves on" and "cites", built from the extracted contribution items and the resolved references. A path from a base idea through its improvements to the current best methods is readable from it.
**Why:** answer "what is this method an improvement of, and what improved on it" across the corpus, and show the field's structure beyond a ranked table.
**Rigour notes:** every edge cites its source (a verified quote for stated relations, a reference link for citations); a relation the paper does not state is not drawn, or is drawn as a separate, labelled "inferred" edge type decided by a human; the graph is a projection of events and can be rebuilt (R-05).
**Open questions:** the node identity of an "idea" (a method family vs. a paper); how to merge naming variants of one idea; who confirms an inferred edge.

### IDEA-33 — Intuition and foundations layer in the graph
Status: new · Added: 2026-11-04 · Slice: 3 (graph) · Depends on: IDEA-30, IDEA-32
**What:** for each extracted idea, an agent-written explanation of why it works, and links from the idea to the foundations it rests on. When a paper brings in an idea from another field (for example, a tool from applied mathematics), the graph gets a node for that background concept, with its own short explanation and links to the other ideas that use it, so the connection to the rest of the graph is visible.
**Why:** a lineage graph (IDEA-32) shows what came after what, not why a change helps. Understanding why a method works, and which older or outside ideas it borrows, is what lets a researcher judge whether it transfers to another problem.
**Rigour notes:** an intuition is interpretation, not evidence. It is stored as a separate node type, labelled "interpretation" with the agent's model, skill version and input blob, and it never counts as evidence in any report or comparison. Every foundation link cites the paper's own statement (a verified quote) or a cited source; a link the paper does not state is a human-confirmed "inferred" edge, as in IDEA-32. A human can mark an intuition as reviewed, wrong or superseded; corrections supersede and never edit.
**Open questions:** where background-concept nodes get their source (the citing paper's text, a textbook reference the researcher supplies, or a cited survey); how to keep the explanations short and checkable; whether the researcher writes the first version of a concept node and the agent only links to it.

## Researcher inputs and discovery provenance (added 2026-11-04)

The researcher re-raised IDEA-01 (a UI to manage several projects) on 2026-11-04, and added the two ideas below.

### IDEA-34 — Link inbox for researcher-supplied papers
Status: new · Added: 2026-11-04 · Slice: — · Depends on: slice 1 `seed_add`, IDEA-02 (candidate inbox), plan C/D pipeline
**What:** the researcher drops links (arXiv, DOI, publisher page) into a per-project inbox, from the CLI, the MCP server or a future UI; each link is resolved to a work, deduplicated against the corpus, marked as researcher-supplied, and then goes through the same path as any candidate: screening under the protocol, full-text acquisition, conversion and extraction.
**Why:** papers the researcher finds by reading, talks or colleagues are often the most relevant, and today they enter only as seeds.
**Rigour notes:** a supplied link enters the corpus as a candidate, never as an inclusion: it is screened by the protocol like every other record, and PRISMA reports it as its own source ("researcher-supplied") so the search remains reproducible. Supplying is a human event with the human actor. Whether supplied papers may be screened differently is a protocol choice declared before screening, not a silent default.
**Open questions:** one inbox per project or a shared inbox routed to projects; how this differs from `seed_add` (seeds steer search and are not screened the same way); whether a supplied link after the search date counts as a supplementary search.

### IDEA-35 — Record and report how each paper was discovered
Status: new · Added: 2026-11-04 · Slice: — · Depends on: slice 1 search events, IDEA-34
**What:** for every work, a computed discovery record: which routes found it (database search, snowballing backward or forward, researcher-supplied, seed, agent suggestion), whether a human or an agent first surfaced it, and when. Reports show per-route and human-versus-agent counts for the corpus, the included set and the final evidence.
**Why:** whether humans or AI systems find the papers that end up mattering is itself useful data, for this programme and as evidence about AI-assisted research. It can later inform how much weight a route deserves.
**Rigour notes:** the record is derived from events (actor kind and channel already sit on every event), never typed. Weighting by discovery route must never change screening or evidence counts silently: any use of it is a declared protocol rule, reported in methods, with the unweighted figures shown too.
**Open questions:** what "first surfaced" means when several routes find a work in one session; whether a researcher-supplied paper that a search also finds counts for both; what a weight would be used for (ordering screening, sensitivity analysis), since inclusion must stay protocol-based.

# Idea backlog

Ideas not yet in any spec. A backlog item is **not** a commitment: nothing here is built until a slice spec takes it in (`docs/specs/`). Decisions go to `decisions.md`; requirements go to the specs.

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
Status: new · Added: 2026-11-01 · Slice: 2 (claims) · Depends on: claim extraction with verified spans
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

### IDEA-15 — Screening, calibration and audit: deferred review minors
Status: new · Added: 2026-11-01 · Slice: — · Depends on: slice 1 plan 4
**What:** minor findings of the plan 4 final review, not fixed in slice 1: count validators on `AuditSampled` and `CalibrationDrawn`; negative-input guards in `draw_audit` and `audit_size`; the private `_rigor_mode` has a third copy; audit labels for unsampled pairs are dropped silently; the batch-order test may pass by chance and the shuffle seed depends on the task count; `screen_record` marks the answered set after an invalid first item; untested paths (task kind mismatch, lease expiry, re-record after an amendment); direct tests for the obsolete-task and stale-decision agreement rulings; `cannot_assess_rate` typed `float | None`; `project_status` recomputes agreement and audit on every call; a pass that fails the sensitivity gate has no in-pass recovery (it needs an amendment).
**Why:** each is a small gap in evidence or robustness that does not change a result today.
**Rigour notes:** none changes an event or a verdict; the validators and the silent drop touch the audit record and should come first.
**Open questions:** whether the `project_status` cost matters before slice 3.

## Plan 5a review carry-over (added 2026-11-02)

### IDEA-16 — Withhold the resolved OpenAlex ID of a held-out seed
Status: new · Added: 2026-11-02 · Slice: — · Depends on: slice 1 plan 5a
**What:** `_held_out_tokens` in `mcp/server.py` withholds only the stated `seed.openalex`, so the OpenAlex ID that a DOI-only held-out seed resolved to is not withheld from MCP output (for example, from a source error note in a run summary).
**Why:** R-20 and acceptance 22 require held-out seeds to stay invisible to agent-facing tools, but the specs name no identifier set; the plan's constraint lists the seed ID, DOI and arXiv ID. A seed's resolved OpenAlex ID is outside the current token set, and it identifies the seed as well as its DOI does. Owner suggestion: plan 5b.
**Rigour notes:** adding it changes the token set only; no event or verdict changes.
**Open questions:** should any identifier that resolves to a held-out seed be withheld, and should R-20 / acceptance 22 name the set?

### IDEA-17 — Pass-B extension before dedup is current
Status: new · Added: 2026-11-02 · Slice: — · Depends on: slice 1 plan 5a, `dedup_run`
**What:** the pass-B sample extension (`screen_next` for pass B) can run before `dedup_run` is current, so two records of one work could be drawn independently. A later merge would leave the canonical work considered-not-added while its twin was sampled.
**Why:** the pass-B sample should draw each work once, and the PRISMA counts should match the deduplicated corpus; a sample drawn before the merge does not.
**Rigour notes:** options: (a) record the condition only, with no change to behaviour; (b) make the extension a no-op until `dedup_run` is current.
**Open questions:** does option (b) block a legitimate extension while dedup is stale?

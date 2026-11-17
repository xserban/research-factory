# Deep-research intake: a cited report from outside goes in, a brief from the factory goes out

Status: draft for the researcher's validation (2026-11-17). Not started. Plan only: no code, no tests, no backlog or MAP edit. The file keeps its earlier name (`quick-factory`, IDEA-41); the direction changed on 2026-11-17 (ruling: "Deep research front-end + factory intake"). The earlier trimmed-pipeline plan survives only as the Phase 2 appendix.
Read first (existing, cited by path below): `docs/ARCHITECTURE.md`, `docs/MAP.md`, `docs/specs/slice-4a-inbox-discovery.md`, `docs/specs/slice-6-hypotheses.md`, `docs/plans/2026-11-16-idea-81-capture-hints.md` (merged). Decisions 24, 36, 37 (item 9), 61, 82, 120, 123, 125. Decisions up to 134 exist; this plan proposes one row, number "to be assigned at merge".

## 1. Goal, non-goals, user stories

**Goal.** A researcher with an idea obtains cited evidence quickly from a deep-research service outside the factory, then hands the report to the factory. The factory treats the report as a source of leads, not of facts: it extracts the cited identifiers and the claims, resolves the sources into the corpus path, and keeps every claim `unverified` until a quote or number is checked against the converted text of the cited paper. In the other direction the factory writes a brief so the report is easy to import and does not repeat what the corpus already holds.

**Key results.**
1. `factory report brief` writes a brief (question, known works to exclude or build on, layer taxonomy, output format) as a Markdown file the operator pastes into any deep-research tool.
2. `factory report import FILE` parses a report in the recommended format (or a looser one, with flags) into a recorded report, its cited sources as inbox items (deduplicated against the corpus, route "deep-research report") and its claims as unverified claim records.
3. The deterministic checks (quote in the converted text, numbers) turn a claim `verified` or `refuted`; no claim changes state by assertion.
4. A claim worth pursuing becomes a lead (existing `lead_record`), then an idea or a hypothesis through the existing paths, with the report as recorded origin.
5. A hub view lists each report, its claims by status and the stage of each cited work.

**Non-goals.**
- The platform never calls a model and never calls a deep-research service; the run happens outside and the report arrives as a file.
- No dependence on a named service (section 6); no scraping of a service's web interface.
- A report is not evidence and is never counted: unverified claims enter no count, no PRISMA figure, no evidence report (R-05, R-42).
- No automatic admission of cited works into screening: they go through the inbox like any link.
- No new rigour mode and no change to any *Decided* entry (section 9). Not the Phase 2 pipeline.

**User stories.**
- (a) I have an idea; I get a cited deep-research report outside the factory (with a brief from (d) if I want it).
- (b) I hand the report to the factory. It turns the cited sources into inbox items or seeds, deduplicated against the corpus, with the discovery route recorded as "deep-research report", and the claims into unverified leads or ideas.
- (c) The factory fetches and converts the cited papers, checks the claimed quotes and numbers against the actual text (verbatim quote verification), mines them with the existing miners, and I develop a promising lead into an idea with evidence, or into a hypothesis (hypothesis engine).
- (d) The factory writes the brief: the question, the corpus's known works to exclude or build on, the layer taxonomy and the output format that the intake parses.

## 2. What exists and what must be built

| Need | Exists (files) | To build |
|---|---|---|
| Capture of links, dedup, resolution | `services/inbox.py` (`LinkInput`, `add_links`, `find_open_duplicate`, `resolve_links`; `inbox_add`, `inbox_list`, `inbox_resolve`, `inbox_withdraw` in `mcp/`, `factory inbox ...` in `cli/main.py`); `model/inbox.py` (`inbox.link_added`: `basis`, `channel`, `note` at most 300 characters); decision 61 | batch intake of many identifiers from one report; a report tag on the items (section 4) |
| Discovery record, routes | `services/discovery.py` (`Route`: `supplied-agent`, `supplied-agent-knowledge`, `supplied-human` ...; `by_channel`; first route per work) | route "deep-research report" derived from the report event; a count in the discovery report |
| Origin and capture hints | IDEA-81: `docs/plans/2026-11-16-idea-81-capture-hints.md` (computed `work origin`, `hint.recorded`, `LinkInput.hint`) | origin value `deep-research report`; the claim's "why captured" reuses the hint note |
| Leads | `services/leads.py` (`record_lead`, `decide_lead`, `list_leads`; a lead is refused without a resolved trigger); `model/hypotheses.py` (`TriggerKind`: work, row, claim, item, idea, interpretation, concept, card, match, conflict, gap, contradiction, lead, hypothesis; `LeadInput`: text, triggers, framework); tools `lead_record`, `lead_decide`, `lead_list`; gate `hypotheses.lead_decide` | a way to hold a claim whose sources are not yet resolved (section 4) |
| Ideas (lineage) | `services/ideas.py` (a name must occur in a verified quote of a contribution item; human decides, never the proposer's session); `idea_propose`, `idea_list`; `services/contributions.py` | nothing; a lead's promotion to an idea uses it as is |
| Seeds | `services/seeds.py` (`add_seeds`, seed roles, held-out split); `seed_add`, `seed_list`; seeds by PMID | a path "report source to seed" that only suggests; the split is the researcher's act |
| Import and admission | `services/import_resolve.py` (`resolve_import`, `decide_import`), `services/import_admit.py` (`admit_import`, `import_sources`), `factory import ...`, `import_status`, `import_coverage`; `mine_import` (`services/shared_mining.py`) copies mined units, not works | a reuse decision (open choice 2); `mine_import` is not the route for reports |
| Feed and work queue (IDEA-58) | `services/feed.py` (`send`, `add`), `services/work_queue.py` (stages `added`, `lookup-failed`, `in-corpus`, `screened-in`, `full-text`, `converted`, `extracted`, `mining`; `advance` runs deterministic steps only), `services/intake_queue.py` | report-origin items appear in the queue like feed items (one `feed_sends`-like row, or a report join); to decide at build (task 5) |
| Full text and conversion | `fulltext_fetch`, `fulltext_status`, `document_read`; converters (decision 49) | nothing |
| Quote verification | `platform/src/factory/document/quotes.py` (`quote_in_element`, `normalise_quote`, `element_blocks`); `services/finders.py` (`ref_quote`) | a service `report_claims` that verifies a claim's quote against a named work's converted elements |
| Numbers | `factory/extraction/numbers.py` (`normalise_text`), R-44 number check | reuse for a claimed number |
| Miners | `mine_next`, `mine_record`, `mine_status`, `services/work_queue.mining_needs` | nothing; a cited paper becomes a mining need by the usual rules |
| Finders | `services/finders.py` (`find_conflicts`), tools `finder_gaps`, `finder_contradictions` | optional: a report claim against the corpus (a "contradicts" candidate list) is a later step, not v1 |
| Hypotheses | `services/hypotheses.py` (`draft_hypothesis`), `hypothesis_draft`, `hypothesis_register`, `hypothesis_review`; gates `services/hypothesis_gates.py` | nothing |
| Held-out | `services/withholding.py` (`withhold`, `held_out_tokens`, `PMID_TOKEN_PREFIX`); decisions 36, 37.9, 123; the held-out seed file is never opened | brief and agent-facing report views pass through `withhold`; works held out as seeds are listed in the brief only as the researcher decides (section 5) |
| Blob store, provenance | event envelope, `input_blob`, project blob store (`docs/specs/00-system.md`) | the report file stored as a blob; its hash in the event |
| Skills | `plugin/skills/rf-*` (e.g. `rf-references`, `rf-ideate`, `rf-develop`) | `rf-intake` |
| Brief and report format | none | sections 3 and 5 |

## 3. Recommended report format (what the brief asks for)

The intake accepts any Markdown, PDF or JSON file, but only the structured Markdown below is parsed without a review step. PDF input is converted with the existing converter and handled as unstructured text (identifiers and markers extracted, claims left to Claude, section 4). JSON is accepted if it has the same fields as the Markdown (`claims[]` with `id`, `text`, `sources[]`, `quote`).

```
# <title>
Tool: <name and mode>; Date: <YYYY-MM-DD>; Query: <the question as asked>

## Claims
C1. <one atomic claim, one sentence>
    Sources: [S1], [S2]
    Quote: "<verbatim text from S1, if the tool gave one>"   (optional)
    Number: <value and unit>                                (optional)
C2. ...

## Sources
S1. <authors, year, title>. DOI: 10.xxxx/... | arXiv: nnnn.nnnnn | PMID: nnnnn | URL: https://...
S2. ...

## Gaps and disagreements (optional)
G1. <what the report could not establish>
```

Rules the brief states: one claim per numbered item; every claim names at least one source marker; a quote is copied from the source or omitted, never reconstructed; give a DOI, arXiv id or PMID whenever one exists, else the URL; do not cite the report's own earlier sections as sources.

## 4. Data model

**Reuse first.** The cited sources are inbox items (`inbox.link_added`, with `basis` kind `knowledge`: the report said so, nothing the factory has read). Resolution, dedup against the corpus, the work queue, screening, fetch, conversion and mining are unchanged. Claims that name a resolved work become leads (`lead.recorded` with a `work` trigger) once a human or Claude chooses to pursue them; nothing is a lead by default.

**What is missing, and why reuse is not enough.**
1. The report itself (file hash, tool, date, query) has no event.
2. A claim has no state `unverified | verified | refuted | unresolvable` and no place to hold the claimed quote while its source is unresolved. A lead refuses a trigger that does not resolve (`leads.trigger_issues`), and a `work` trigger needs a work in the corpus.
3. The discovery record has no route for "came from a report".

**Proposed events (one decision row, number to be assigned at merge).**
- `report.imported` (schema 1): `report_id` (`rpt_...`), `blob_hash` of the file, `format` (md, pdf, json), `tool` (text), `tool_date`, `query` (text), `brief_id` (optional, from section 5), `sources[]` (`marker`, `identifier_kind`, `identifier_value`, `raw` text, `item_id` of the inbox item written in the same batch), `claims[]` (`claim_ref` `C1`, `text`, `source_markers`, `quote` optional, `number` optional), `parse` (`structured` or `lenient`, parser version), the usual provenance (`model`, `skill_version`, `input_blob`) when an agent parsed unstructured text; human or system actor for the structured parser (deterministic).
- `report.claim_checked` (schema 1): `report_id`, `claim_ref`, `work_id`, `conversion_id`, `check` (`quote` or `number`), `result` (`verified`, `not-found`), `element_id`, written by the service, never typed.
- `report.claim_resolved` is not added; `refuted` is a Claude or human judgement recorded as `report.claim_judged` (`verdict` `refuted` or `unresolvable`, reason, cites the checks). A claim's state is a projection (`unverified` until a `verified` check exists; `refuted` only by a judgement citing a `not-found` and the source text read).

Dedup uses `find_open_duplicate` and the corpus keys already used by `inbox.py` (`_corpus_keys`); a source already in the corpus gets an item resolved at once to the existing work, not a second work. Hallucinated citations are flagged, not dropped: an item whose lookup settles `lookup-failed` stays visible with the claim attached; the report view shows it as "does not resolve".

**Discovery route.** A work first surfaced through a report item gets origin and route `deep-research report`, computed from `report.imported` joined to its items. This extends the computed origin of IDEA-81 (a view over events, never typed) with one value; the researcher's hint note on the item (`hint.recorded.miner_note`, or the item `note`) records "why this was captured". If the work was already surfaced by a search, its first route is unchanged and the report is an additional route (as `discovery.py` does for other routes).

**Alternatives.** (i) No new event: store the report as a study file (decision 125) and record leads by hand. Cheapest, but nothing is parsed or deduplicated and the claim state has no home. (ii) A new lead trigger kind `report-claim` instead of a claim projection, so claims are leads from the start. Fewer concepts, but it pollutes `lead_list` with unreviewed machine output and breaks the lead prior (`leads.prior_for`). See open choice 1.

**Projection.** Tables `reports`, `report_sources`, `report_claims` (state folded), rebuildable by the projector only.

## 5. Interfaces

**CLI.**
- `factory report brief --question TEXT [--layer core] [--exclude-known] [--out FILE]` writes the brief (below).
- `factory report import FILE --tool NAME --query TEXT [--date YYYY-MM-DD] [--brief ID]` stores the blob, parses, writes `report.imported` and the inbox items in one batch under the existing lock; prints counts (sources, resolvable now, duplicates of the corpus, claims) and refuses an unparseable file with structured errors, writing nothing.
- `factory report list`, `factory report show RPT`, `factory report verify RPT [--claim C3]` (runs the checks for claims whose sources are converted; reports claims waiting for full text).

**MCP tools.** `report_import` (file path under the project; the same refusals), `report_brief`, `report_view`, `report_claims_next` (serves unverified claims with their converted source elements, for Claude to propose a quote location), `report_verify` (runs `quote_in_element`), `report_judge` (verdict with reason; a claim cannot be refuted without a `not-found` check). The reading surface passes through `withhold` with held-out tokens (decision 37.9).

**The brief** contains: the question and the framing from `question_view`; the layer taxonomy (names and one-line definitions from the recorded scheme, `reference_layer_status`), so the report may group by layer; the corpus's known works as a compact list (title, year, DOI) in two parts, "already known: do not repeat" and "build on" (the core layer); the section 3 format; the instruction not to invent identifiers. Held-out seeds are not special-cased by the platform's brief writer (decision 37.9: they are corpus works); the researcher chooses to limit the list (open choice 3). Size is capped (a list limit, with the total stated) so the brief fits a prompt box.

**Skill `rf-intake`** (procedure): (1) write the brief; (2) the operator runs the research outside and saves the file; (3) import; (4) review the parse (lenient only); (5) resolve and admit sources through the queue; (6) once a cited paper is converted, propose for each claim a quote location and run `report_verify`; (7) judge claims; (8) record leads for claims worth pursuing; (9) hand over to `rf-ideate` or `rf-develop`. The skill states that a claim without a verified quote is never used as a premise.

**Hub view.** A first version: a "Reports" section on the Leads page (`services/site_*`), one row per report: tool, date, query, counts of claims by state, and sources with their work-queue stage (`added` to `extracted`, or "does not resolve"). One drill-down per report lists claims, quotes and check results. No editing in the hub in v1; judgement stays on MCP and CLI.

## 6. Running deep research cheaply (operator procedure)

The factory depends on no service. Everything below about a named service is "to verify" by the operator before relying on it.
1. `factory report brief ... --out brief.md`.
2. Paste the brief into the chosen tool as the research prompt, adding no extra instructions that change the output format.
3. Save the finished report to a file: export to Markdown or PDF where the tool offers it, else copy the text into `report.md`. Keep the tool's citation list, as it holds the identifiers.
4. `factory report import report.md --tool "<name and mode>" --query "<question>"`.

Candidates (all "to verify": features, quota, price, export format, whether citations carry DOIs):
- Claude's research mode in the Claude environment, or the Claude deep-research skill run in a session: to verify whether it can emit the section 3 format and how many sources it cites.
- Gemini deep research through the researcher's Antigravity or Gemini subscription, used for large-context deep research: to verify context size, daily quota and whether its export keeps citation URLs.
- Other tools (named by the researcher): to verify.
Token cost sits on the researcher's subscription for the outside run; the factory's cost is the later fetch, conversion and mining of the papers the researcher chooses to pursue (unit caps and `factory costs` apply as usual). The recorded `tool` and `tool_date` make comparison of tools possible afterwards (which tool's claims verified more often): a computed rate over the claim states, not a quality judgement.

## 7. Rigour and risks

- **Unverified stays unverified.** A claim is counted nowhere until a `quote` check passes; `report_evidence`, PRISMA and any figure ignore report claims; the check (`factory check`) lists a draft sentence citing an unverified report claim as an error (R-42, R-130).
- **Never trust a quote.** The quote is verified with `quote_in_element` against the converted text of the cited work, normalised as in `quotes.py`; a claimed number is compared with the extraction number check (R-44). A quote that is not found is recorded as `not-found`, not corrected by editing.
- **Hallucinated citations** (a DOI that does not resolve, a title that matches nothing, a DOI that resolves to a different paper): flagged and kept in the report view with the claim; the claim gets state `unresolvable` only by a judgement; nothing is dropped silently. A resolved work whose title differs from the cited string is flagged `title-mismatch` (a computed similarity, no judgement by the script).
- **Circularity.** The deep-research tool may have drawn on the same sources as the corpus; the report is a lead generator, never a corroboration of the corpus. The report view says so.
- **Provenance.** Tool, date, query, blob hash, brief id, parser version and, for agent-parsed text, model, skill version and input blob (R-04).
- **Copyright and ToS.** The report file is stored in the project blob store, not in git-tracked paths (R-47). Papers are fetched only through the existing acquisition routes with their recorded licence handling; a service's terms may restrict reuse of its output and the operator checks them (to verify).
- **Held-out.** Reports are corpus-side input; agent-facing views pass through `withhold`; the held-out file is not opened. A cited work that equals a held-out seed is not hidden (decision 37.9), and the import output does not mark it.
- **Cost and volume.** A large report may cite hundreds of sources; the import writes items but triggers no fetch; fetch and conversion run only through the queue with caps.
- **Prompt injection.** A report is untrusted text; Claude reads it as data. Claims are shown quoted, never as instructions.
- **Dedup errors.** Versions and preprints of one paper resolve through the existing dedup cascade; a duplicate is merged by the existing reversible merge, not by the intake.

## 8. Tasks (each 1 to 3 hours, one commit)

Dependencies are listed by task number. Tests are listed as the TDD list; the testing pause holds until the researcher lifts it, then these are written first.

1. **Model and projection.** Files: `model/reports.py` (events `report.imported`, `report.claim_checked`, `report.claim_judged`), `index/projectors/reports.py` (tables), `docs/specs/00-system.md` event list entry deferred to the decision. TDD: schema rejects a claim with no source marker; unknown marker is refused; state fold (unverified, verified, refuted); fold is order-independent per claim; rebuild from events equals live projection.
2. **Parser.** Files: `reports/parse.py` (structured Markdown and JSON; pure functions), `reports/identifiers.py` (DOI, arXiv id, PMID, URL extraction; normalisation reusing the inbox's identifier kinds). Depends on 1. TDD: the worked example in section 10; a DOI with trailing punctuation; a versioned arXiv id; a PMID in a URL; a claim citing a missing marker is a parse error; duplicate markers; a quote with typographic quotes; lenient mode extracts markers from free text and yields no claims; no network.
3. **Intake service.** Files: `services/report_intake.py`, small change to `services/inbox.py` (accept a prepared list of `LinkInput` with a report ref). Depends on 1, 2. TDD: one batch writes the report event and the items atomically; a source already in the corpus resolves to the existing work (no second work); a repeated import of the same blob is refused as a duplicate (by hash); an unparseable file writes nothing; a held-out PMID is not echoed in the agent-facing summary; discovery route computed as `deep-research report`.
4. **Claim verification.** Files: `services/report_verify.py`. Depends on 1, 3. TDD: a quote present in a converted element verifies; a quote with different whitespace and hyphenation verifies (as `quote_in_element`); a missing quote gives `not-found`; a claim whose work has no conversion is `waiting`; a number differing in unit is `not-found`; refuting requires a `not-found` check; verifying twice writes one check.
5. **Queue and discovery integration.** Files: `services/discovery.py` (route), `services/work_queue.py` or `intake_queue.py` (report-origin items shown with their stage). Depends on 3. TDD: origin of a work is the report when no earlier route exists; an earlier search route stays first; counts by channel include reports; a report item at `converted` shows its claims waiting for verification.
6. **Brief writer.** Files: `services/report_brief.py`. Depends on 1. TDD: output is deterministic for fixed events; known works capped with total stated; layer names come from the latest scheme; held-out tokens do not leak into any field the agent-facing tool returns (unit test with a fake seed); format section equals the parser's grammar (round-trip test: a report built from the brief's template parses).
7. **Lead bridge.** Files: `services/report_leads.py` (claim to `LeadInput` with `work` triggers). Depends on 3, 4. TDD: a claim with a resolved source and a verified quote makes a lead whose text names the claim and the report; a claim with no resolved source is refused with a structured error; promotion to an idea or hypothesis goes through the unchanged services; the lead's author never decides it.
8. **MCP and CLI.** Files: `mcp/report_tools.py`, `cli/report.py`, registration in `mcp/` and `cli/main.py`. Depends on 3, 4, 6, 7. TDD: parse and call only (no logic in the surface); refusals pass through; held-out filter applied to `report_view`; arguments are validated at the boundary.
9. **Skill and hub view.** Files: `plugin/skills/rf-intake/SKILL.md`, `services/site_reports.py` (computed read), page registration. Depends on 5, 8. TDD: the view is computed from events and stores nothing; counts by state sum to the claim count; a does-not-resolve source is listed; the page omits held-out tokens as other agent views do.
10. **Check and docs.** Files: `services/check.py` (findings: draft sentence citing an unverified report claim; report with sources none of which resolve), decision row (number to be assigned at merge), `docs/specs/slice-4a-inbox-discovery.md` addendum. Not `docs/MAP.md` (generated after merge). Depends on 1 to 9. TDD: each finding code fires once per offender and not on a clean project.

## 9. Proposed decision row (number to be assigned at merge)

"Deep-research intake (plan `2026-11-17-quick-factory.md`): 1) A report from an outside deep-research service is an input file, stored as a blob and recorded by `report.imported`; the platform calls no service and no model. 2) Its cited sources are inbox items with `basis` kind `knowledge`; its route is `deep-research report`. 3) Its claims are held as `unverified` and are verified only by `quote_in_element` or the number check against the converted text of the cited work; refutation needs a recorded `not-found` and a judgement; unverified claims enter no count or report. 4) The brief is computed from events and passes through the held-out filter. 5) The Phase 2 pipeline is not adopted." Proposed (researcher's ruling 2026-11-17 on direction).

## 10. Worked example (invented; marks are placeholders, not real papers)

Report snippet (invented):

```
# Agent planning methods (INVENTED EXAMPLE)
Tool: ExampleResearch, deep mode; Date: 2026-11-17; Query: how do agents plan research?
## Claims
C1. Plan-and-execute agents outperform reactive agents on multi-step tasks.
    Sources: [S1]
    Quote: "plan-and-execute improved task success by 12 points over the reactive baseline"
C2. Replanning after tool failure is rarely evaluated.
    Sources: [S2], [S3]
## Sources
S1. Doe, 2025, An invented study of planning. DOI: 10.9999/invented.1
S2. Roe, 2024, Another invented paper. arXiv: 2401.99999v2
S3. Poe, 2023, A paper that does not exist. DOI: 10.9999/ghost.7
```

Through the intake:
1. `report import` stores the blob (hash `sha256:...`), parses 2 claims and 3 sources, writes `report.imported` and three inbox items (S1 DOI, S2 arXiv id with version, S3 DOI) in one batch.
2. Dedup: S2's arXiv id (version stripped as for other links) is already in the corpus; its item resolves at once to the existing work, route unchanged (first route a search), the report added as a further route. S1 is new: origin and route `deep-research report`.
3. The queue resolves S1 (found), S3 (not found: stage `lookup-failed`, shown as "does not resolve" with C2 still attached).
4. S1 is screened in by the usual path, fetched, converted. `report verify`: C1's quote is searched in S1's converted elements by `quote_in_element`. Outcome A: found in a results paragraph, check `verified`, claim `verified`. Outcome B: not found (the paper says "9 points"): check `not-found`; Claude reads S1, judges `refuted`, reason cites the text.
5. C1 verified: Claude records a lead (trigger: work S1), the researcher promotes it, and an idea or a hypothesis is developed through `rf-ideate` or `rf-develop`. C2 has one resolved source (S2) and one that does not resolve; it stays unverified; no lead until S2's text supports it.

## Open choices for the researcher

1. How are report claims held?
   - (a) Recommended: a claim projection from `report.imported` plus `report.claim_checked` and `report.claim_judged`; leads only for claims chosen (section 4).
   - (b) A new lead trigger kind `report-claim`, so every claim is a lead from the start.
   - (c) No new event: the report is a study file and leads are recorded by hand.
2. How do cited sources enter the corpus?
   - (a) Recommended: as inbox items (basis `knowledge`), resolved and screened through the normal path.
   - (b) As an import list through `factory import` and `import_admit` (bulk, with its resolution proposals).
   - (c) As seeds (`seed_add`), only for sources the researcher names, since seeds affect the held-out split.
3. Which known works does the brief list?
   - (a) Recommended: the core layer and works with a verified contribution, capped, with the total stated; the researcher can edit the file.
   - (b) The whole corpus titles, capped by count.
   - (c) Only the question and the format; no corpus list (nothing to leak, but repeats are likely).
4. Which report formats does v1 parse?
   - (a) Recommended: structured Markdown and JSON in the section 3 grammar; PDF and free text go in as lenient (identifiers extracted, claims left to Claude).
   - (b) Structured Markdown only.
   - (c) Also a tool-specific export parser per service (to verify what each exports).
5. Who parses unstructured reports?
   - (a) Recommended: Claude through MCP (`report_claims_next` style), recorded with provenance; the deterministic parser only extracts identifiers and markers.
   - (b) Not supported: the researcher reformats first.
6. Where does the report surface in the hub?
   - (a) Recommended: a "Reports" section on the Leads page.
   - (b) A separate Reports page.
   - (c) CLI and MCP only in v1.
7. Is the route "deep-research report" a new `Route` value or a channel?
   - (a) Recommended: a new origin value computed from `report.imported` (as IDEA-81's origin), leaving `Route` as is.
   - (b) A new `Route` member in `services/discovery.py`.
8. How strict is verification before a lead?
   - (a) Recommended: a lead needs one resolved source; the claim stays unverified, and promotion to an idea or hypothesis needs a verified quote (the idea rules already require one).
   - (b) A lead needs a verified quote.
   - (c) No condition for leads; verification only at idea or hypothesis.
9. Phase 2 (trimmed pipeline appendix)?
   - (a) Recommended: not planned; revisit after the intake pilot.
   - (b) Plan it next, in parallel.

## Appendix: Phase 2 (optional, not planned now)

The earlier plan (a trimmed `quick` profile on `exploratory` with a paper limit and unit cap, one search, one screening pass, one extraction pass, a banner listing skipped steps, `factory quick start`, `factory quick promote`) is not part of this plan. If it is revisited: it needs a quick profile object (`model/project.py`, `services/gates.py`, `services/check.py` `LEVELS`, `services/budgets.py`, `mcp/unit_cap.py`), a protocol template on `MethodProfile.RAPID_REVIEW` (`model/protocol.py`, `services/protocol_rules.py`), an effective-mode fold for promotion, and a skill `rf-quick`. Stages that may be skipped are those `exploratory` already relaxes (PRESS, calibration, audit, second pass, appraisal, miners); traceability requirements (R-01 to R-05, R-10, R-11, R-13, R-14, R-16, R-22, R-23, R-30, R-32, R-34, R-40, R-42 to R-44, R-47) are never skipped, and every skipped step is printed in each report. The full stage table of the earlier draft is in this file's history (commit `6c09824b`).

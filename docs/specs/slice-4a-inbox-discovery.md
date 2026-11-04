# Slice 4a — Link inbox and discovery provenance

Status: Accepted 2026-11-04 (researcher's instruction: build everything, MVP v1; recommended rulings adopted). Decision 61; requirements R-100, R-101. Drafted 2026-11-05 · Outline slice: **4 (living corpus)** of [README.md](README.md). Builds on [00-system.md](00-system.md), slices 1, 2 and 3a (G1 snowball rounds); must satisfy [01-rigour.md](01-rigour.md) R-01–R-05, R-13–R-16, R-21–R-26, R-30–R-39, R-47, R-51. Takes in backlog IDEA-34 (link inbox) and IDEA-35 (discovery record). Rulings marked **[confirm]** are recommendations awaiting the researcher; on acceptance the plan records them as one decision (text proposed at the end).

## Cross-spec reconciliation 2026-11-04

1. **Where inbox and watch records enter the corpus (with slice 4b ruling 6).** One rule for both slices: a record enters the corpus as a pending work when the recorded run that retrieves it finishes, never later and never through a human pre-selection. For a link that run is the `supplied` lookup of `inbox_resolve`; for a watch it is the cycle's search run. A captured but unresolved link (`inbox_items`, status `open`) is intent, not a corpus record, and PRISMA does not count it. The "candidate inbox" of slice 4b is therefore two things: the `inbox_items` table of this slice (links only; `route` stays `link`, watches write no items, which narrows ruling 14) and a computed view of pending works by discovery route.
2. **Where PRISMA counts them.** `supplied` is fourth in the "other methods" precedence, before slice 3d's `library-import`: `citation-chase`, `seed-admission`, `hand-search`, `supplied`, `library-import`. Any `database` provenance wins (decision 38 item 6). Watch runs are database runs; in the discovery record their route is `database:<source>`, with the watch cycle named as an attribute of the surfacing run, not as a separate route.
3. **Priority hints.** Slice 4b's `inbox.prioritised` is not defined here; an order imposed on screening would depart from R-34 (randomised order) and is Later, behind a new decision.
4. **Seed recall (ruling 9).** Decision 54 (held-out recall counts search finds only, recorded concurrently) settles the open point; this slice's `supplied` status follows it.
5. **Gate.** `inbox.withdraw` is a decision gate with floor `human` (slice M table); the resolve authorisation through `supplied_links` is a computed gate. Modules: `inbox` (`retrieval`), `discovery` (`builder`).
6. **Requirements** R-xx(a), (b) are R-100, R-101 in [01-rigour.md](01-rigour.md); R-02's method list gains `supplied` there.
7. **Projection version.** The plan bumps `PROJECTION_VERSION` by one from the value it finds.

## v1 scope

- **v1:** the whole plan `2026-11-05-inbox-discovery.md`: capture, resolve under `supplied_links`, blind screening, seed recall rule, discovery builder, PRISMA, methods, trace, check, tools, synthetic-fixture acceptance.
- **Later:** publisher-page resolution (`citation_doi`), the pilot run on real links, priority hints (item 3).

## Goal
Let the researcher (and, under declared rules, an agent) hand the factory a paper by link, so that it enters the corpus as a **candidate** with its own provenance and is screened under the protocol like any other record; and compute, for every work, **how it was discovered**: which routes found it, whether a human or an agent surfaced it first, and when. Report both in PRISMA, in the methods statement and in a discovery report.

Pilot for acceptance: the linear-attention pilot (or its synthetic fixture) with at least three supplied links (one new to the corpus, one already found by the database search, one also found by a snowball round), producing a PRISMA flow whose "other methods" box shows the supplied route and a discovery report whose counts sum to the corpus.

## User flow
1. **Capture.** The researcher runs `factory inbox add <link>… [--note TEXT]` (or relays it over MCP, `inbox_add` with `channel = mcp`). An agent in a non-pass session may call `inbox_add` with its model, skill and `input_blob`. Each link is parsed to one identifier (arXiv id, DOI or OpenAlex id) at the boundary; an unparseable link writes nothing and is returned with a reason. Capture is offline and allowed at any time, before the protocol exists included.
2. **Resolve.** `factory inbox resolve` (or MCP `inbox_resolve`) looks up each open item by identifier as a recorded query of purpose `supplied`, gated like any search (ruling 7). The lookup's records enter the corpus with provenance method `supplied`; the item records the outcome (`new`, `in-corpus`, `not-found`, `ambiguous`, `failed`).
3. **Deduplicate and screen.** `dedup_run` and title/abstract screening proceed unchanged. A supplied work that arrives after pass B opened is drawn into pass B's extension like any late work (decision 38 item 3). Screeners never see the route or the note (ruling 8).
4. **Full text onwards.** Promoted supplied works take the slice-2 path. A PDF the researcher holds is supplied afterwards through `factory fulltext import` (decision 46 item 7, unchanged).
5. **Report.** `report_prisma` counts supplied works under "other methods"; `report_discovery` (CLI `factory report discovery`) gives per-route and per-surfacer counts at four levels: identified, title/abstract included, full-text included, in the evidence report; `report_methods` states how many included works came only through supplied links and who supplied them.

## Rulings (provisional)
1. **Inbox is not seeds [confirm].** Seeds steer the search and stay outside the corpus (slice 1); inbox items are corpus candidates. A link whose identifier equals a seed's is accepted; nothing in the inbox's output names a seed.
2. **One inbox per project [confirm].** A shared inbox routed to several projects waits for the corpus layer of IDEA-37 and for IDEA-04; capturing the same link in two projects is two events.
3. **Capture and resolve are separate acts [confirm].** Capture records intent offline and is never gated; resolve fetches and is gated. This lets links be captured before the protocol is ready and keeps the network call a separate, recorded run (R-03, R-22).
4. **Submitters [confirm].** A human (CLI, or MCP relay with `channel = mcp`, decision 37 item 6) or an agent in a session that has joined no screening or extraction pass. A session that captured a link cannot later join a screening pass (proposer ≠ evaluator, R-51; the same refusal pattern as decision 37 item 6). An agent capture requires `basis`: `document` (with `doc_` id and anchor of the citing span it read) or `knowledge` (outside knowledge, flagged as such in the discovery report).
5. **Link forms [confirm].** Accepted: bare arXiv ids and `arxiv.org/{abs,pdf,html}/` URLs (version suffix kept in the item, dropped for lookup); bare DOIs, `doi:` and `doi.org` URLs, and URLs whose path contains a DOI (`10.<digits>/…`); OpenAlex ids and URLs. Anything else is refused at capture with reason `unsupported-link`. Reading publisher pages for `citation_doi` meta tags is deferred (it needs a fetch at capture time). Option rejected: accepting any URL and resolving later — it would store unresolvable items that block nothing and mean nothing.
6. **Provenance method `supplied` [confirm].** `ProvenanceMethod.SUPPLIED = "supplied"`, `QueryPurpose.SUPPLIED = "supplied"`; the arXiv and OpenAlex adapters map the purpose to the method, as they do for `seed`. In PRISMA's "other methods" precedence it comes last (citation-chase, seed-admission, hand-search, supplied), so decision 38 item 6 is unchanged: a work also found by a database search counts under databases only, and a work also chased counts under citation chasing; the overlap is shown in the discovery report. R-02's list of methods gains `supplied` (rigour-spec edit on acceptance). Option rejected: reusing `hand-search` — PRISMA reserves hand searching for searching named journals or proceedings by hand, which a link from a colleague is not.
7. **Protocol section `supplied_links` [confirm].** New amendable, hashed section, omitted from every hash while absent (slice-2 pattern, so existing `P@` ids are unchanged): `accept_from: tuple["human" | "agent", ...]` (non-empty). In `pilot` and `systematic` a resolve is authorised when the section accepts the item's submitter kind; otherwise it needs a recorded deviation (as an unplanned seed admission does). `exploratory` resolves are ungated. The protocol's other checks (ready, PRESS confirmed, current question) apply as to any search (`search_authorization`).
8. **Screening is identical and blind [confirm].** Supplied works are screened by the same criteria, passes, calibration and audit; v1 offers no differential treatment, so there is nothing to declare. Screening and extraction task content carries no route, note, submitter or `basis`; a test compares a supplied work's task content with a database work's.
9. **Seed recall counts search routes only [confirm].** For R-24, a positive seed whose matching work's non-probe provenance is only `supplied` is reported with status `supplied` and counts as not retrieved; otherwise supplying a held-out seed would raise held-out recall without the search finding it. (Open point to verify in the plan, not changed here: `seed_check` today reports an admitted seed's work as `retrieved`.)
10. **Discovery record [confirm].** Computed on read (as the evidence report, decision 52), never stored. For each canonical work (absorbed works folded in, R-26):
    - *routes*: the set of `database:<source>`, `chase:<direction>` (`search_chase`), `snowball:<direction>` (G1 rounds, slice-3a ruling 20), `seed-admission`, `supplied:human`, `supplied:agent`; probe-purpose lookups never count;
    - *surfacing events*: per route, the event that first names the work for that route: the `search.run_started` event of the earliest run whose provenance row names the work (runs, not pages, are the unit: a record is parsed inside its run), or, for `supplied`, the item's `inbox.link_added` (capture precedes lookup, so a link captured before the search ran surfaces the work first even if resolved later);
    - *first surfaced*: the route and actor kind of the earliest surfacing event by event id (00-system §4.2: id order is the global order, so there are no ties);
    - *surfacer kind*: the actor kind of the act behind the surfacing event: the actor of `search.run_started` for database runs, of the round event for chase and snowball, of `inbox.link_added` for supplied, `human` for seed admission. A database run started by the system actor is `system`.
11. **No weighting [confirm].** Discovery figures are reported, never used to order, sample or weight screening or evidence. Any later use is a declared protocol rule with unweighted figures shown alongside (IDEA-35 rigour note); none is built here.
12. **Agent views [confirm].** `inbox_list` and `report_discovery` over MCP are refused to sessions that joined a pass (decisions 43, 48). Their agent view reports `seed-admission` under `other` and never names a seed. The CLI shows all.
13. **Withdrawal [confirm].** An open item may be withdrawn (`inbox.link_withdrawn`, human only, with a reason). A resolved item cannot: its work is in the corpus and leaves only by screening; nothing is deleted.
14. **Builder fit (IDEA-37/38) [confirm].** The inbox is the first instance of the corpus layer's *candidate inbox*: items carry a `route` field fixed to `link` in v1, so watches (IDEA-02) and other feeders can share the table later without a new event family. `services/discovery.py` is a builder that declares its inputs (provenance rows, run starts, round tables, inbox items, outcomes, evidence rows) in its module docstring.

## Design

### Identifiers
| Entity | ID | Rule |
| --- | --- | --- |
| Inbox item | `inb_<ULID>` | One captured link; never reused |

### Events (schema 1)
| Type | Actor | Payload |
| --- | --- | --- |
| `inbox.link_added` | human or agent | `item_id`, `route` (`link`), `link` (as given, ≤ 500 chars), `identifier` (`kind`: `arxiv` \| `doi` \| `openalex`, `value` normalised), `note` (≤ 300 chars, optional; human only), `basis` (agent only: `document` with `document_id` and `anchor`, or `knowledge`), `channel` (`cli` \| `mcp`) |
| `inbox.link_withdrawn` | human | `item_id`, `reason` |
| `inbox.link_resolved` | submitter of the resolve | `item_id`, `query_id`, `run_id`, `status` (`new` \| `in-corpus` \| `not-found` \| `ambiguous` \| `failed`), `work_id` (null unless one work), `deviation_id` (optional) |

`in-corpus` means the found work already had non-probe provenance before the run; `failed` items stay open and may be resolved again; every other status closes the item. Refs: `item_id`, plus `query_id`, `run_id`, `work_id` on resolution. The lookup's own events are the slice-1 `query.registered`, `search.run_started`, `search.records_parsed`, `search.run_finished`.

### Index tables (projector only)
- `inbox_items(item_id, route, identifier_kind, identifier_value, link, actor_kind, session, channel, basis, added_event_id, status, withdrawn_event_id)` — status `open | withdrawn | resolved`.
- `inbox_resolutions(event_id, item_id, query_id, run_id, status, work_id)` — every attempt kept.
- Discovery needs no table; it reads `provenance`, `runs`, `events`, the chase and snowball round tables and `event_refs` (cleanups-2 Task 1).

### MCP tools and CLI
| Tool | Purpose | Who |
| --- | --- | --- |
| `inbox_add` | Capture links (batch, partial success) | human relay (`channel = mcp`) or agent in a non-pass session |
| `inbox_resolve` | Resolve open items (all, or `item_ids`), with an optional `deviation_id` | human relay or agent in a non-pass session |
| `inbox_list` | Page through items with status and outcome | non-pass sessions |
| `report_discovery` | Discovery report (agent view per ruling 12) | non-pass sessions |

CLI: `factory inbox add|list|resolve|withdraw`, `factory report discovery [--json]`. `withdraw` is CLI only. `project_status` gains `inbox: {open, resolved, withdrawn}`. Services: `services/inbox.py`, `services/discovery.py`; pure link parsing in `factory/inbox/links.py`. Skill: the `rf-search` skill gains a short section on `inbox_add` with `basis`.

### Reports, trace, check
- **PRISMA:** `identified_other["supplied"]`; the arithmetic invariants of `PrismaFlow` hold unchanged.
- **Discovery report:** rows by route and by first-surfacer kind; columns identified, TA included, FT included (when a full-text plan exists), in evidence (works with a final evidence row); each column sums over first-surfaced routes to the column total; a second table gives route overlaps (works with more than one route). Agent-`knowledge` captures are a separate row.
- **Methods statement:** one paragraph: number of supplied links captured, resolved and included, split by submitter kind; that supplied works were screened under the same protocol and screeners did not see the route.
- **Trace:** a supplied work traces back to its `inb_` item and from there to the capturing event and actor; `trace inb_…` forward reaches the work.
- **Check:** `inbox-open-after-screening` (warning: items still open while no TA work is pending); `inbox-resolve-failed` (items whose last attempt failed); `supplied-without-plan` (a `pilot`/`systematic` resolve under a deviation while `supplied_links` is absent: listed for the methods text, not an error).

## Rigour requirements
Existing, in scope: R-01 (chain extended by `inb_` → query → run → record), R-02 (new method value), R-03 (lookup responses archived), R-04 (agent captures carry model, skill, `input_blob`), R-05 (all discovery counts derived), R-13–R-15 (`supplied_links` declared and amended like any section), R-21 (a lookup returning several records is `ambiguous`, never truncated to one), R-22–R-23 (lookups are ordinary query and run records), R-24 (ruling 9), R-25 (supplied works are new-after-dedup "other methods" records), R-26 (dedup unchanged; discovery folds absorbed works), R-30–R-38 (screened as any record; ruling 8), R-39 (methods disclose supplied and agent-suggested works), R-47 (no literature in events; notes are short researcher text, no PDFs), R-51 (ruling 4).

Added on acceptance (numbers in [01-rigour.md](01-rigour.md)):
- **R-100 Discovery is derived.** Every discovery figure is computed from events; route, surfacer and first-surfaced are never typed. All modes.
- **R-101 Route-blind screening.** Screening and extraction tasks never carry how a work was discovered. P, S.

## Acceptance criteria
1. **Capture validation:** a batch with one valid arXiv URL, one DOI URL and one unsupported URL writes two `inbox.link_added` events and returns the third with `unsupported-link`; an agent capture without `basis` writes nothing.
2. **Offline capture:** capture performs no network call and succeeds with no protocol.
3. **Gate:** in a `pilot` project with a ready, PRESS-confirmed protocol lacking `supplied_links`, resolve without a deviation writes nothing and names `query`; with `supplied_links.accept_from = ("human",)` a human item resolves and an agent item is refused; `exploratory` resolves without a protocol.
4. **Provenance:** a resolved new work has one provenance row with method `supplied`, its run's raw pages archived (R-03); `P@` ids of a protocol without `supplied_links` are unchanged.
5. **In-corpus link:** a link to a work already found by the database search records `in-corpus`; PRISMA counts the work under databases only; the discovery report lists both routes and first-surfaced `database`.
6. **Capture precedes search:** a link captured before the search ran and resolved after it makes `supplied:human` the first-surfaced route.
7. **Screening blindness:** the `screen_next` content of a supplied work equals, field for field apart from ids, title and abstract, that of a database work; it contains neither the note nor the route.
8. **Pass B extension:** a supplied work resolved after pass B opened is considered by the next `screening.sample_extended` draw.
9. **Proposer ≠ evaluator:** a session that captured a link is refused when it tries to join a screening pass; a pass session is refused by every inbox tool.
10. **Seed recall:** a held-out seed supplied by link and not retrieved by search has status `supplied` and lowers held-out recall exactly as a miss.
11. **Discovery sums:** for the fixture, each discovery column sums to the corresponding PRISMA or evidence count; rebuilding the index gives the same report byte for byte.
12. **Withdrawal:** withdrawing an open item writes one event and the item no longer resolves; withdrawing a resolved item writes nothing.
13. **Trace:** `trace` from a supplied work's screening decision reaches the `inb_` item and its capturing actor.
14. **Quality:** `mypy --strict` and ruff pass; coverage ≥ 90% for `services/` and `model/`.

## Out of scope
Scheduled watches and their inbox feed (IDEA-02); digests (IDEA-03); a shared cross-project inbox (IDEA-04, IDEA-37 corpus layer); publisher-page resolution; PDF capture in the inbox (decision 46 item 7 stays the PDF path); any weighting by discovery route (ruling 11); a UI (slice 7).

## Open questions
1. Should `basis = knowledge` agent captures be allowed in `systematic` at all, or only `basis = document`? Recommendation: allowed, declared through `accept_from`, and reported as their own row; the researcher may decline by omitting `agent`. **[confirm]**
2. Should an item captured after full-text screening finished reopen PRISMA as `provisional`? Recommendation: yes, through the existing rule (a new work is `pending` until screened); no new mechanism. **[confirm]**

## Decision text (recorded in `decisions.md` as decision 61, 2026-11-04)
| # | Topic | Status | Decision |
| --- | --- | --- | --- |
| 61 | Link inbox and discovery provenance (slice 4a) | Decided | 1) Researcher- or agent-supplied links are captured offline as `inb_` items and resolved by a recorded `supplied`-purpose lookup gated by the protocol section `supplied_links` (or a deviation; ungated in `exploratory`); supplied works enter the corpus with provenance method `supplied` and are screened like any record, by screeners who never see the route. 2) PRISMA counts `supplied` last among "other methods", so decision 38 item 6 is unchanged. 3) For R-24 a seed found only through a supplied link is not retrieved. 4) A session that captured a link cannot join a screening pass. 5) Each work's discovery record (routes, first-surfaced route and actor kind by event order) is computed on read and reported in PRISMA, methods and a discovery report; it never weights screening or evidence. 6) Agent views refuse pass sessions and report seed admission as `other` (extends decision 43) |

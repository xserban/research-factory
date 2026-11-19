# Hub v2: parity inventory of the old hub (2026-11-18)

Status: inventory only. Untracked. Nothing built. Companion to `docs/plans/2026-11-18-hub-ui.md`.

**Purpose.** An acceptance checklist for the port of the old hub (`services/site*.py`, `dashboard*.py`) to hub v2
(`hub_ui/pages/*.js`, `services/hub_*.py`). Every distinct element of every old product is listed with its data
source and its v2 target, so that nothing is lost silently. A port is done when each row is `built and verified`,
`existing and verified`, or `dropped by the researcher`.

**Read this way.**
- Row IDs are stable: `<product prefix>-<n>`. Tests and the parity checklist cite them.
- Target syntax: `existing:<Page>/<view>` (already in v2; the note says what differs), `new:<Page>/<section>` (approved page,
  new section) or `drop?` (the researcher decides; only for truly redundant things).
- Approved new pages (researcher, 2026-11-18): **Pipeline** (Control room, Work queue, Activity), **Sources** (Search and dedup,
  Acquisition, Conversion with inspector item pages, Documents), **Method** (Lifecycle, Steps, Taxonomy), **Costs and runs**
  (Costs, Runs), **Write and export** (Synthesis, Bibliography and BibTeX, Wiki vault, PRISMA SVG export), **Platform**
  (Capabilities, Backlog). Updates and all feed acts go into **Living**.
- Where the old element has no approved home (protocol, decisions, PRESS, probes, project portal and project switcher), the
  row targets a **proposed** section marked `(needs ruling)`; the summary lists them.
- "Source" is the service function that already gives the data; a new v2 payload service (`services/hub_*.py`) should wrap it,
  not re-derive it. Old pages open papers in the explorer (`../explorer/index.html#open=<slug>`); in v2 every such link becomes
  the shared paper drawer (`H.openDrawer(id)`) or `corpus#...`.
- Old acts (writes) go through `site_server._ROUTES` and the hub's `hub_act` table with the page token and the local-human
  actor. v2 has exactly one write today (`/ui/act/snowball-add`, Graph/Foundations); the port needs a v2 act route per act
  below, through the same allow-list and auth seam. Acts are marked **ACT**.
- "Kind" vocabulary: kpi, chart, table, filter, sort, search, item-page, link, export, act, poll, text (explanatory text that
  carries information), cmd (a copyable CLI command).

Checks made against v2 (2026-11-18): `hub_ui/pages/{overview,flow,corpus,lenses,explore,graph,miners,data,findings,living,kit}.js`
and `services/hub_{payloads,screening,mining,findings,lenses,graph,living,journeys,build}.py`. Findings of those checks are marked
**GAP** in the notes and collected in section 33.

## 1. Dashboard (snapshot and live) — prefix DB

Builder: `dashboard.py` (`dashboard_state`, `screening_live`), `dashboard_page.py`, `dashboard_server.py` (`GET /api/state`, `/api/progress`, `/api/screening`).
The dashboard is read-only and has 11 tabs. Its panels land as follows. Where a panel has a counterpart in a product below, the
row points there and the detail is inventoried once, in that product.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| DB-1 | Header: project slug, "snapshot <time>" or "updated <time>", total events, last event id | kpi | `dashboard._meta`, `site_hub_page._line_numbers` | new:Pipeline/Control room (status strip) | Also code version (HM-3). Shell may show the same strip on every page (see SV-4). |
| DB-2 | Tab strip (Protocol, Decisions, PRESS, Probes, Search, Screening, Extraction, Conversion, Miners, Products, Feed and queue, Cost and time) with `#tab=`/`#miner=` hash | link | `dashboard_page.TABS` | new:Pipeline/Control room (links to the pages below) | The tab set is replaced by the page rail; keep deep-link state in the URL hash. |
| DB-3 | Per-tab help box (what the tab means, one paragraph) | text | `dashboard_page.TAB_HELP` | each target page's ⓘ panel | Text carries information (definitions of protocol, amendment, deviation, PRESS, probe, recall, precision). Port into the ⓘ panels. |
| DB-4 | Per-tab "What you can do" box: copyable CLI commands per tab and links into the hub | cmd | `dashboard_page.TAB_ACTIONS` | each target page (cmd rows) | Commands: protocol show/amend/deviation, decide list/show/select, protocol confirm-press, report search, dedup list, search, screen disagreements/resolve, audit, report prisma, mine status, document status/coverage/convert, site build/status/serve, budget, report methods. |
| DB-5 | "Running now" panel: one row per long operation (label, kind, state, bar, done/total unit, rate/s, ETA, elapsed, message); collapsible, remembered | chart | `/api/progress`, `progress_list` (site_progress) | new:Pipeline/Activity (Long operations) | Polls every 1.5 s while running, else 5 s. Activity already lists operations (AT-10); merge both into one panel. |
| DB-6 | "Screening live" panel: tiles per pass (counts by verdict), tile "in queue (pass A)", session chips (session, actor, decisions, includes, rate/min, last), stop-rule progress bars, table of the latest 50 decisions (time, pass, session, work, verdict, score, criterion, quote, rationale) | poll | `/api/screening`, `dashboard.screening_live` | new:Pipeline/Activity (Screening live) | Polls 3 s when a session is active, else 15 s. Not in Flow/Screening (that tab is retrospective). Foldable. |
| DB-7 | Tab Protocol: header line (protocol id, status, PRESS state, number of amendments) | kpi | `dashboard._protocol` | new:Method/Protocol and decisions (needs ruling) | No approved page holds the protocol. |
| DB-8 | Protocol section chips (question, criteria, sources, screening, extraction, snowball + any `other:` section) with count of decisions behind each; click selects a section | filter | `dashboard._decisions`, `_section_of` | new:Method/Protocol and decisions (needs ruling) | |
| DB-9 | Section content: Question (primary question, objectives, slots table Slot/Value/Open, sub-questions, non-goals) | table | `dashboard._question` (`question_view`) | new:Method/Protocol and decisions (needs ruling) | |
| DB-10 | Section content: Criteria table (Id, Parent, Applies at, Statement, Rule) | table | `protocol.current_protocol().spec.criteria` | new:Method/Protocol and decisions (needs ruling) | Criteria text is also needed by Flow (reasons wall shows label only). |
| DB-11 | Section content: Sources (name, excluded flag, why), Queries (source/kind, text, filters), Limits (field = value, why) | table | `spec.sources/queries/limits` | new:Method/Protocol and decisions (needs ruling); queries also new:Sources/Search and dedup | |
| DB-12 | Section content: Screening spec, Full-text screening spec, Extraction schema, Snowball plan (key-value) | table | `spec.screening/full_text_screening/extraction_schema/snowball_plan` | new:Method/Protocol and decisions (needs ruling) | |
| DB-13 | "Decisions behind this section": the decision cards of the section | link | `dashboard._decisions` | new:Method/Protocol and decisions (needs ruling) | See DB-14 to DB-17. |
| DB-14 | Tab Decisions: filters level, status (validated, rejected, added, proposed, open, selected, superseded), text search; count "n of N decisions"; grouped by level | filter | `decide list` via `dashboard._decisions` | new:Method/Protocol and decisions (needs ruling) | Level list from `D.levels`. |
| DB-15 | Decision card header: subject, level, short id, suggested time, state badge | item-page | `decision_list`/`decision_view` | new:Method/Protocol and decisions (needs ruling) | Superseded cards dimmed. |
| DB-16 | Decision card body: explanation; "Supersedes"/"Superseded by" jump links; items (status badge, item id, recommended flag, text, grounds as jump links to other decisions); selection note, selected by actor via channel at time, "reconstructed" flag; suggested by actor, decision id | item-page | `decision_view` | new:Method/Protocol and decisions (needs ruling) | Provenance: keep actor, channel and the reconstructed flag. |
| DB-17 | Open-state: expanded cards remembered across redraw; `jump(id)` opens a card | link | client | new:Method/Protocol and decisions (needs ruling) | Use URL hash `#dec=<id>`. |
| DB-18 | Tab PRESS: list of reviews (id, protocol id, findings count, confirmed or not); table #/Severity/Element/Finding/Response | table | `dashboard._press` | new:Method/Protocol and decisions (needs ruling) | Severity badge (major, minor). |
| DB-19 | Tab Probes: rounds (round, probe id, queries count); table Source/Reported/Dev retrieved of tested/Negatives retrieved/Query; failed query shown with reason | table | `dashboard._probes` | new:Method/Protocol and decisions (needs ruling) | |
| DB-20 | Tab Search: tiles (queries run, runs complete, runs partial, records identified, duplicates removed, merges active, merges reverted) | kpi | `dashboard._search`, `_dedup` | new:Sources/Search and dedup | See SE-1 onward; the product is a superset. |
| DB-21 | Search: Per source table (Source, Queries, Records retrieved); PRISMA identification key-values; Queries table (Source, Purpose, Query, Runs statuses, Reported, Retrieved); Merges by rule | table | `search_report`, `list_merges` | new:Sources/Search and dedup | The per-source totals and the "PRISMA identification" split (databases vs other) are not in the old Search product (SE); keep them (SE-new). |
| DB-22 | Tab Screening: ranking key-values (ranking id, model id, weights hash, works ranked) | kpi | `dashboard._screening` | new:Flow/Screening (add) | **GAP**: `hub_screening` payload has no ranking id/model/weights hash. |
| DB-23 | Screening: passes table A and B (Queued, Decided, Remaining); tiles records left (pass A), stale decisions | table | `dashboard._screening` (`screening_stops`, `stale_screening_decisions`) | new:Flow/Screening (add) | **GAP**: Flow shows the curve and the stop point but not the queued/decided/remaining table. Stale count is used inside the curve only. |
| DB-24 | Screening: Stop rules table (rule with below-score, run progress, stopped or running, not screened) | table | `screening_stops` | existing:Flow/Screening (ranked curve) | Partial: stop point and `stop_rule` text shown; per-rule run progress and "not screened" count are **GAP**. |
| DB-25 | Screening: Calibration key-values (drawn, labelled, required, passed) | kpi | `dashboard._screening` | new:Flow/Screening (add) | **GAP**: not in v2. |
| DB-26 | Screening: Full-text passes table | table | `dashboard._screening` | new:Flow/Screening (add) | **GAP**. |
| DB-27 | Screening: "Full text: cannot assess, to resolve" (work, pass A, pass B verdict/criterion/anchor/quote, link to the conversion inspector, resolve command) | table | `dashboard._cannot_assess` | new:Flow/Screening (add) with link to new:Sources/Conversion item page | **GAP**: nothing in v2 lists the cannot-assess works. Blocks nothing; promoted until resolved. |
| DB-28 | Screening: Checks (calibration/audit draws: kind, name, draw id, labelled of drawn, current or outdated, agreement, agreement note, band table Band/Drawn/Labelled/Compared/Agreed/Agreement/Would add includes/excludes/Undecided, disagreements count) | table | `screen_check_report` via `dashboard._screening` | new:Flow/Screening (add) | **GAP**. |
| DB-29 | Tab Extraction (older claim-row pack): tiles units/papers/rows, units by state, agreement (dual works, rows aligned, overall, unresolved, resolved, single extraction) and rate table, audit key-values | table | `dashboard._extraction`, `extraction_agreement` | drop? | Tab states itself that it mostly stays empty because miners do extraction. Researcher to decide; if kept: new:Method/Protocol and decisions or Miners. |
| DB-30 | Tab Conversion: summary table per converter, not-measured list, "Lowest recall" table (recall, precision, words orig/md, converter, work link to inspector) | table | `dashboard._conversion` (`conversion_coverage`) | new:Sources/Conversion | Covered by CV-1 onward; the "lowest recall first" list is the default sort there. |
| DB-31 | Tab Miners: column glossary (Units, Closed, Open, Rows, Stale), listed-miners table (Miner, Version, What it records, Units, Closed, Open, Rows, Stale), selected-miner card | table | `dashboard._miners`, `miner_info.miner_detail` | existing:Miners/gallery and detail | Differences in MN-section: units/closed/open/stale **GAP**. |
| DB-32 | Miner card: rationale, "How it reads", Fields table (Field, Group, Kind, Required, Compared, What it records), "Quality and use", Versions table, copyable commands | item-page | `miner_detail` | existing:Miners/detail (Anatomy, fields) | Versions table, digest, second-pass share, audit share, evidence-admission flag and commands are **GAP** (MN-6 to MN-14). |
| DB-33 | Tab Products: table Product/Group/State/Built/Model-written with links to the hub | table | `dashboard._products` (`site.status`) | new:Pipeline/Control room (module panels) | In v2 the "products" are pages; keep a per-page freshness line (build time, stale flag) only for payloads that are cached (see HM-8). May become **drop?** once all payloads are live; researcher decides. |
| DB-34 | Tab Feed and queue: links, categories/shown per cycle/interval; Last fetch (window from/to, next due, due now); Latest ranking (id, shown, explore); Top shown titles table (Title, Score, Reaction, Sent, Reactions 7d, Adds 7d) | table | `dashboard._feed` | new:Living (feed status) | See FD-section. |
| DB-35 | Feed and queue: Work queue (added papers, stage counts, pending kinds); Interrupted (runs, pipelines, expired leases, stale passes, never looked up, screened-in without full text, not converted, limit runs with reset time, details table); Last run (run open, pipeline open, last stage/outcome/finished) | table | `dashboard._feed/_interrupted/_feed_run` | new:Pipeline/Work queue | See QU-section. |
| DB-36 | Tab Cost and time: agent events by stage; per model (Model, Events, First, Last); Budgets (Unit, Scope, Limit, Consumed, Remaining; notice when none); Reported usage; All events by type | table | `dashboard._cost`, `budget_status`, `progress` | new:Costs and runs/Costs | CO-section lists the richer run-cost report. Events by type: also new:Pipeline/Control room heartbeat (existing:Living/Heartbeat has events by type per day). |
| DB-37 | Static export (`factory dashboard export` writes one HTML with the state embedded) | export | `dashboard_server.export_snapshot` | drop? | The v2 hub is served; a snapshot export is a CLI feature, not a page. Researcher to confirm. |

## 2. Home / Control room (`home`) — prefix HM

Builder: `site_hub_page.render_hub` (not a product; reads `site.status`, `type_counts`, `results/line.json`), chrome `site_chrome.hub_bar`,
client `_HUB_JS` (polls `GET /p/<slug>/api/status` every 10 s).

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| HM-1 | Sidebar: one entry per product with status LED (ok, stale, busy, bad), grouped (Overview, Sources, Corpus, Mining, Findings), numbered | link | `site.status`, `LAYOUT` | existing:shell rail | v2 has the rail (`shell.js`). LEDs have no v2 counterpart unless payloads are cached; see HM-8. |
| HM-2 | Sidebar filter box ("filter modules") | search | client | existing:shell Ctrl-K | Ctrl-K covers pages and papers. |
| HM-3 | Top bar: "SYSTEM NOMINAL" or "n MODULE(S) NEED A REBUILD", events total, last event id (data version), code version (git), LIVE / REBUILDING / SNAPSHOT | kpi | `site.status`, `type_counts`, `code_version`, `/api/status.building` | new:Pipeline/Control room (status strip) | v2 shell has an as-of stamp only (**GAP**: events total, last event id, code version). |
| HM-4 | Production line: 7 stations with live counts that open their product: SEARCH identified, SCREEN screened, FULL TEXT assessed, CONVERT converted (eligible documents), MINE miner rows (pass A, `m-` schemas), SYNTHESIZE pages recorded, REPORT products built | chart | `results/line.json` (`prisma_flow`), `extraction_rows`, `events type=page.recorded` | existing:Overview/pipeline strip (partial) + new:Pipeline/Control room | **GAP**: `hub_payloads.pipeline_strip` has 5 steps from PRISMA only (identified, screened, sought, assessed, included). Convert, mine, synthesize and report stations are missing. |
| HM-5 | Activity chart: events recorded per day, last 21 days with events; bar hover count | chart | `site_hub_page._activity_days` | existing:Living/Heartbeat | Heartbeat shows events by family and type per day (richer). Window differs (21 days vs whole history); fine. |
| HM-6 | Module panels (one per product): number, title, state tag (Nominal, Stale, Fault, Updating with percent), description, built time, "model-written" tag, error text, OPEN | table | `site.status`, `status.error`, `needs_model` | new:Pipeline/Control room (page cards) | Descriptions are information; reuse each page's lead. Build time and error apply while cached payloads exist. |
| HM-7 | Planned modules (pilot scripts, offline) shown dimmed with script name | text | `site.planned()` | drop? | Placeholder for pilot scripts that no longer exist as products; researcher to confirm. |
| HM-8 | Live state poll: LED and tag updated from `/api/status` (building, queued, per-product progress percent) | poll | `GET /p/<slug>/api/status` | existing:shell (stale-watch banner, 20 s poll) | v2 shell polls a stale watch per payload; per-page progress percent is **GAP** only if payload builds are long. |
| HM-9 | "Where to start" guide text (Explorer, Results, Miners, Agreement, Acquisition, Conversion, Synthesis) | text | static | new:Pipeline/Control room (next actions) | Overview already has "next actions" (human queue). Keep both; text points to v2 pages. |
| HM-10 | Explanatory hints: what a bar means; how the line runs left to right; amber light meaning | text | static | new:Pipeline/Control room ⓘ | |
| HM-11 | Commands: `factory site build`, `factory site serve`, `factory dashboard serve` | cmd | static | new:Platform/Capabilities (footer) or drop? | Old-hub commands; v2 serving command differs. Update, do not copy. |
| HM-12 | Link "New hub" (to `ui/`) in the top bar | link | static | drop? | Disappears at cut-over. |
| HM-13 | Main hub bar (all pages): Projects, New papers, Backlog, Capabilities; theme picker | link | `site_chrome.HUB_NAV` | existing:shell rail + new:Platform | Rail must include Living (New papers), Platform (Backlog, Capabilities). |
| HM-14 | Portal page (`/`): one card per project (title, slug, events, pages built, state: up to date / n to rebuild / hub not built / rebuilding) linking to `/p/<slug>/` | link | `site_portal.render_portal`, `/api/projects` | new:shell project switcher (needs ruling) | v2 is per project; a project switcher (list from `/api/projects`) is needed to reach other projects. |
| HM-15 | Portal: "New project" form (slug, title, profile exploratory/pilot/systematic) | act | `POST /api/projects/create` (`site_create`) | new:shell project switcher (needs ruling) | **ACT** (hub token). Recorded as `project.created` by the local human. |
| HM-16 | Portal: "Add to inbox" form (project select, value doi/arXiv id/link, note) | act | `POST /api/inbox/add` (`hub_act`) | new:Living (Add a link) | **ACT**; see UP-12 (same act on the Updates page). |
| HM-17 | Portal: short "New papers" panel (top ranked entries over projects with Like/Dislike/Add to inbox) and "See all n ranked" | act | `site_hub_feed.top_entries`, `render_feed_panel` | new:Living (Feed river top list with acts) | **ACT** x3; see FD-section. |
| HM-18 | Portal note: projects are found by scanning the root; `registry.json` gives titles or hides | text | static | drop? | Admin note. |

## 3. Explorer (`explorer`) — prefix EX

Builder: `site_explorer.build_explorer` (`site_corpus.corpus_payload`; page `site_explorer_page.PAGE`). v2 target is **Corpus** (plan section 2.6 lists the
parity set). Scope difference to keep in mind: v2 Corpus is the PRISMA included set (365), the old explorer the works with a live pass-A row (370); the 5 differing works
are listed by id in `sets_payload` (see Overview "sets").

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| EX-1 | Search box over title, abstract, quotes (all terms must match) | search | `corpus_payload` works (`title`, `abstract`, `cls/map` quotes) | existing:Corpus/search | v2 adds term highlighting. Verify the quote fields (`cls`, `map`, and `sum`/`desc` quotes) are in the search haystack. |
| EX-2 | View switch: List, Timeline, Chronology, Lineage, Graph | filter | client | existing:Corpus/views | Same five views (`VIEWS`). |
| EX-3 | Group by (every dimension plus Lifecycle stage; default technique) | filter | `DATA.dims` | existing:Corpus/group-by | v2 adds "none". |
| EX-4 | Sort: Date newest, Date oldest, Most cited in corpus, Title A to Z | sort | client | existing:Corpus/sort | Plus reverse toggle (v2 addition). |
| EX-5 | "Cited by N or more corpus works" numeric filter, with tooltip stating how many works have extracted reference lists (`refs_done` of n) | filter | `cited_in_corpus`, `refs_done` | existing:Corpus/cited filter | Tooltip text present as the ⓘ on citations (verify `refs_done` shown). |
| EX-6 | "With full text" (works having a stored document) | filter | `doc` | existing:Corpus/with full text | v2 addition relative to old (old had no explicit filter). |
| EX-7 | Facet sidebar: one group per dimension (layer first, then technique, field, data, architecture, evaluation, human, stage ...), checkbox per value with colour dot and count (whole-corpus count) | filter | `DATA.dims`, `layers_of` | existing:Corpus/facets | v2: grouped, collapsible, own search, counts live. Verify the dimension list is identical (old list from `load_profile(project).dims` plus layer plus stage). |
| EX-8 | Active filter chips with remove buttons (facets, cited-by, search) and count "n of N works" | filter | client | existing:Corpus/chips | |
| EX-9 | Help box "What this is" (list, timeline, chronology, lineage definitions; filters; click a paper; links from other pages arrive filtered) | text | static | existing:Corpus ⓘ | Port the sentence that other pages link here with a filter (`#view=list&f=role.field:value`); v2 URL syntax differs, keep the deep links alive from Findings/Lenses. |
| EX-10 | List view: table Published, Title, Cited in corpus, Technique, Field, Human, Stages; grouped with counts; row opens detail; checkbox per row | table | `corpus_payload.works` | existing:Corpus/List | v2 adds DNA strip per row. Columns Technique/Field/Human: verify present. |
| EX-11 | Timeline view: one lane per group, one dot per paper by month, coloured by first dimension; dot opens detail | chart | `works[].month` | existing:Corpus/Timeline | |
| EX-12 | Chronology view: month columns (newest left), card per paper (date, title, technique, field, human tags, stage dots, cites/cited-by counts in corpus, key quote, link to document); Reverse order button | chart | `works`, `cites` | existing:Corpus/Chronology | Document link in cards: **GAP** (EX-30). |
| EX-13 | Lineage view: papers by month, arrows to cited earlier corpus papers; click highlights ancestors (red) and descendants (green); toggle "papers without links" | chart | `cites` | existing:Corpus/Lineage | Present (`ST.lnAll`, `chain`). |
| EX-14 | Graph view: force-directed works linked to technique, field, human role, stage and citation edges, toggles per link kind, drag/zoom/hover label | chart | `works`, `cites` | existing:Corpus/Graph | Present (`GD`). Randomised layout in old; v2 should be seeded (rule 5 of the plan). |
| EX-15 | Select-all-in-filter and per-row checkboxes; "Clear selection" | filter | client | existing:Corpus/selection | |
| EX-16 | Export selected (max 200 works; zip for a notebook tool; option "include the PDFs (licensed files)" with a confirm; answers produced there are not records) | export | `POST /api/export/works` (`export_works_zip`) | existing:Corpus/export | **ACT**. Present (`api/export/works`, `xpdf`). |
| EX-17 | Detail pane: header (title, authors, date, venue, cited by n elsewhere), layer badge with provenance ("moved by the researcher; the miner said X", "from the miner") | item-page | `works[].layer`, `layer_source`, `layer_miner` | existing:Corpus/detail | Present. |
| EX-18 | Detail: links Open PDF/HTML (on disk) and DOI/arXiv | link | `doc`, `doi`, `arxiv` | existing:Corpus/detail (DOI, arXiv only) | **GAP**: no link to the original file on disk (`link_documents`); v2 says "full text on file (kind)" only. Needed also for the conversion inspector (EX-30). |
| EX-19 | Detail: Abstract (collapsible) | text | `abstract` | existing:Corpus/detail | |
| EX-20 | Detail: Structured summary (problem and gap, core innovation, contribution type, novelty axis, builds on, relation, improves over, ... each with quote or anchor) | item-page | `works[].sum` (`SUMMARY_ORDER`) | existing:Corpus/detail | Present (`SUMF`). Verify the same field order. |
| EX-21 | Detail: Citations within the corpus (cites list, cited-by list, each a link to the paper) | link | `cites` | existing:Corpus/detail | Present. |
| EX-22 | Detail: Lifecycle stages (stage, mode, quote, anchor) | item-page | `works[].stages` | existing:Corpus/detail | Present. |
| EX-23 | Detail: Classification, Process/human role/blueprint, Descriptors (field, value, quote, anchor) | item-page | `works[].cls/map/desc` | existing:Corpus/detail | Present. |
| EX-24 | Detail: Results rows (up to 12 of n: system, stage, approach, system role, evidence grade) | item-page | `works[].design`, `n_design` | existing:Corpus/detail | Present. Old caps at 12; v2 same. |
| EX-25 | Detail: "Mine and layer" acts: reason box, "Mine this work" and "Move to layer" (select of layers) | act | `POST /api/mine/work`, `POST /api/layers/move`, `GET /api/layers` | existing:Corpus/detail (acts) | **ACT**. Present (`mine-work`, `api/layers/move`). |
| EX-26 | Facet sidebar: "Mining acts (run the layer miner on a whole layer)" with per-layer count and button | act | `POST /api/mine/layer` | existing:Corpus/facets | **ACT**. Present (`api/mine/layer`). |
| EX-27 | Detail: "What you can do": commands `document read <id>`, `trace <id>` with Copy, plus link "Conversion inspector" | cmd | static | existing:Corpus/detail (commands only) | **GAP**: the inspector link is missing; see CI-section target new:Sources/Conversion item page. |
| EX-28 | Detail evidence footnote: "pass A reading by a model, every value quoted from the converted document; second pass on a 10% sample" | text | static | existing:Corpus/detail | Verify the sentence (10% figure is typed in the old page; in v2 read it from the miner regime). |
| EX-29 | Panel mode (`#panel=1`): detail pane embedded in a slide-over by other products; Esc closes | link | `site_panel` | existing:shell paper drawer | Replaced by the shared drawer. Not a gap. |
| EX-30 | Deep links in: `#open=<slug>`, `#view=list&f=<role.field>:<value>`, `#q=`, `#cit=` from other pages | link | URL | existing:Corpus/URL state | v2 uses `#id=`, `#grp=`, facet keys. Provide an alias for `open=`. |
| EX-31 | Loading marker "Loading corpus…" | text | client | existing:Corpus | |

## 4. Wiki (Obsidian vault) (`wiki`) — prefix WK

Builder: `site_wiki.build_wiki` and `site.py._build_wiki` (adds synthesis pages as `synthesis/<scope>.md`). The page is a pointer; the product is the folder of Markdown files.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| WK-1 | Pointer page: how to open the folder as an Obsidian vault (absolute path shown), start at `index.md`, graph view Ctrl+G, every placement shows its quote | text | `site.py._build_wiki` | new:Write and export/Wiki vault | Show the vault path and a copy button. |
| WK-2 | Links to `index.md` and `timeline.md` | link | files | new:Write and export/Wiki vault | Serve the files read-only or give a "download vault (zip)" act. |
| WK-3 | One note per work (`works/<slug>.md`): front matter (title, published, venue, doi, arxiv, technique, field, human_position, stages, work_id), original link, structured summary with quotes, abstract, "Placed in" wikilinks, classification with quotes, lifecycle stages with quotes, citations within the corpus | export | `corpus_payload`, `SUMMARY_ORDER` | new:Write and export/Wiki vault | Data source stays `site_wiki.build_wiki`; build on demand, not per page view. |
| WK-4 | One note per category per dimension (technique, field, data, architecture, evaluation, human, stage): count and member list by date | export | `build_wiki` | new:Write and export/Wiki vault | |
| WK-5 | `timeline.md` (months newest first, per paper date, title, technique, human) | export | `build_wiki` | new:Write and export/Wiki vault | |
| WK-6 | `index.md`: map of the corpus (works count, graph hint), synthesis pages (model-written, quote-checked), per-dimension category lists with counts | export | `build_wiki` | new:Write and export/Wiki vault | |
| WK-7 | Synthesis pages inside the vault with a banner "Model-written page (model, date), checked when recorded. An interpretation, not evidence." | export | `pages.list_pages/read_page` | new:Write and export/Wiki vault | Keep the banner (rigour: interpretation is labelled). |
| WK-8 | Document links (symlinks to stored originals under `docs/`) | link | `link_documents` | new:Write and export/Wiki vault | Symlinks are local; for a zip export they must be copied or dropped. Decide at build. |
| WK-9 | Wiki note content counts: "n works (pass A; each note shows the quote behind its placement)" | text | `build_wiki` | new:Write and export/Wiki vault | |

## 5. Results (`results`) — prefix RS

Builder: `site_results.build_results` (from `corpus_payload`, `prisma_flow`, `events`). All numbers are pass A readings; links go to the explorer filtered by `role.field:value`.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| RS-1 | Intro note: "n works with at least one miner row; figures computed from recorded rows (pass A), not judgements; see agreement" | text | `corpus_payload` | existing:Findings lead + Miners | Pass-A caveat belongs in the ⓘ panels. |
| RS-2 | Review flow funnel (identified, duplicates removed, screened, excluded at TA, promoted, not yet sought, not retrieved, assessed, excluded at FT, pending, included); each bar links to prisma, acquisition or explorer | chart | `prisma_flow` | existing:Flow/Where the records went | Sankey is richer. The "promoted, not yet sought" row is `not_sought`. |
| RS-3 | Review flow table (step, n) with the same links | table | `prisma_flow` | existing:Flow (band lists) | Each band opens its record list; ok. |
| RS-4 | Note: "n protocol deviations recorded" and that the review stops TA screening by a declared rule and unscreened works are reported | text | `events type=protocol.deviation_recorded` | new:Sources/Acquisition (deviations) and existing:Flow/Screening (stop point) | Deviation count is **GAP** in v2. |
| RS-5 | Agent events per model (bars; recorded events, not dollars) | chart | `events` group by `model` | new:Costs and runs/Costs (events per model) | Same data as DB-36. |
| RS-6 | Publication month of the included works: column chart plus bars with link per month to the explorer (year filter) | chart | `works[].month` | existing:Overview/papers per month | Click target in v2 should open Corpus filtered by month. |
| RS-7 | Distributions: for each of Classification, Process/human role/blueprint, Summary miner (pass A): per enum field "(n of N works)" with description and value bars, each bar linking to the works | chart | `site_results._distributions`, `miner spec` | existing:Miners/detail (value distributions per field) | Present as `distributions`; the field description and the miner-level "share filled" are shown. Differences: v2 reads the listed miner; old reads the profile's role miners. Verify that classification, mapping and summary miners all appear. |
| RS-8 | Lifecycle stages covered: heat grid stage (rows) by mode automated / human-assisted / mentioned-only, count of works, cell links to explorer stage filter | chart | `works[].stages` (m-stages) | new:Method/Lifecycle (stage coverage by mode) | **GAP**: no v2 view of stage by mode. Findings uses the same data for its "full research cycle" cards only. |
| RS-9 | Number of distinct stages per work (bars 1..n) | chart | `works[].stages` | new:Method/Lifecycle | **GAP**. |
| RS-10 | Stages covered (automated or human-assisted) by primary technique: heat grid stage by technique, mentioned-only left out | chart | `works[].stages`, `cls.technique_primary` | new:Method/Lifecycle (stage by technique) | **GAP**. Lenses/Technique adoption uses different data (technique miners by half-year), not this pairing. |
| RS-11 | Results by stage and approach (design approach miner): heat grid of own-system rows by stage and approach; counts "n result rows over m works (at most 30 per work shown), k own system" | chart | `works[].design` (m-design) | new:Lenses/Results by stage and approach | **GAP**: only the per-paper rows (12 per paper) in the drawer exist. |
| RS-12 | Bars for system_role, evidence_grade, value_kind over the result rows | chart | `works[].design` | new:Lenses/Results by stage and approach | **GAP**. |
| RS-13 | Limits note: pass A is one model's reading; quotes verified verbatim show evidence exists, not that the value is right; works not acquired or not in English reported in flow and deviations | text | static | existing:Miners ⓘ plus Findings ⓘ | Port as plain text in ⓘ. |

## 6. Miners (`miners`) — prefix MN

Builder: `site_miners.build_miners` (`mine_status`, `miner_info.miner_detail`, `site_agreement.measure`, `registered_miner`). One index page and one page per miner (`<miner>.html`).
v2: Miners page (gallery, detail with Anatomy, field cards, Two readings, by model). Payload `hub_mining.mining_payload_from`.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| MN-1 | Index intro: what a miner is (typed, quoted values; pass A all works, pass B a sample) | text | static | existing:Miners/lead + ⓘ | |
| MN-2 | Column glossary table (Units, Closed, Open, Rows, Stale, Second pass, Agreement fairer, Agreement platform) | table | `COLUMNS` | existing:Miners ⓘ (partial) | Definitions of Units/Closed/Open/Stale are **GAP** because those counts are not shown. |
| MN-3 | Listed miners table: miner, version, first sentence of rationale, units, closed, open, rows, second pass share, agreement fairer, agreement platform; row opens miner page | table | `mine_status`, `miner_detail` | existing:Miners/gallery (cards) | Cards show works read and agreement; **GAP**: units/closed/open/stale (`mine_status`), second-pass share (`use.dual_extract_sample`), version. A compact table view next to the cards would close it. |
| MN-4 | Miner page header: version, digest, rationale | item-page | `miner_detail.spec`, `s.digest` | existing:Miners/detail | **GAP**: digest not shown. |
| MN-5 | Status table (units, closed, open, rows, stale, agreement fairer, agreement platform) | kpi | `mine_status`, `measure` | existing:Miners/detail (partial) | **GAP**: units/closed/open/stale. Rows count present as works read. |
| MN-6 | "How it reads": works read (population), paragraph kinds (`selector.elements`), sections searched (`heading_patterns` or all), max works, procedure (skill name), one row per (row key fields) | table | `miner_detail.spec.selector`, `procedure`, `row_key_fields` | existing:Miners/detail Anatomy (partial) | Anatomy shows population/scope and field counts. **GAP**: paragraph kinds, heading patterns, max works, procedure/skill; the payload carries `row_key` but `miners.js` does not show it. |
| MN-7 | Fields table: field, group, kind with allowed values and unit family, required, compared, what it records; enum fields link to the agreement section of that field | table | `spec.fields` | existing:Miners/detail field cards | Present (`fields`: name, type, values, required, group, compared, desc). |
| MN-8 | Kind legend (enum, quote, number, integer, citation, anchor, work_ref with meaning) | text | `KIND_HELP` | existing:Miners ⓘ | Verify present. |
| MN-9 | "Quality and use": passes, second-pass sample share, audit fraction and minimum, whether rows are admitted to the evidence report, imports, exploratory flag, quote rule, calibration size with thresholds (field agreement min, recall min) | table | `miner_detail.use`, `spec.regime`, `spec.evidence` | existing:Miners/detail (calibration thresholds only) | **GAP**: second-pass share, audit fraction/minimum, evidence admission, imports, exploratory flag, quote rule. `regime.calibration_size`, `recall_min`, `field_agreement_min` present. |
| MN-10 | Agreement by field (fairer measure): field, agreed/compared, rate | table | `measure` | existing:Miners/Two readings | Present with exact/fairer/platform and 95% range. |
| MN-11 | Examples (pass A): three works with most fields: field, value, quote and anchor; title links to the paper | table | `site_miners._examples` | existing:Miners/detail examples | Present (`examples`, 4). |
| MN-12 | Versions table: version, digest, listed in the protocol, proposed by | table | `miner_detail.versions` | existing:Miners/detail | **GAP**: no version table; only the shown version. |
| MN-13 | "What you can do": `mine status`, `mine agreement <name>`, `mine resolve --help` with Copy; how to change a miner (register a new version, list it with an amendment) | cmd | static | existing:Miners/detail | **GAP**: no commands. |
| MN-14 | Link from a field to the per-field disagreement list (`agreement/<miner>.html#<field>`) | link | `site_agreement` | new:Miners/Disagreements (see AG-section) | **GAP**; target missing. |

## 7. Miner agreement (`agreement`) — prefix AG

Builder: `site_agreement.build_agreement` (`measure`, `mine_status`, one page per miner `agreement/<miner>.html`). v2: Miners/Two readings and Miners/By model.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| AG-1 | Intro: agreement shows consistency, not which reading is right (needs gold labels) | text | static | existing:Miners/Two readings ⓘ | "None says which pass is right" is in `METHODS`. |
| AG-2 | Bar chart: agreement by miner (fairer measure, primary fields); colour bands mint at 0.8, amber from 0.5, red below; each bar links to the miner page | chart | `measure(...).overall(primary_only=True)` | existing:Miners/gallery + Two readings | v2 shows rate with the bar to clear (regime threshold) rather than the 0.8/0.5 bands. Different threshold semantics; keep the regime bar. |
| AG-3 | Glossary table of the columns (works in both passes, rows A/B/matched, fairer all/primary, platform all/aligned, disagreements) | table | `GLOSSARY` | existing:Miners ⓘ | |
| AG-4 | Summary table per miner: works in both passes, rows A / rows B / matched, fairer (all enum values), fairer (primary fields), platform (all rows), platform (aligned rows), disagreements count | table | `measure`, `mine_status.agreement(_aligned)` | existing:Miners/Two readings | Present: fairer, exact (new), platform all/aligned, works_both, matched. **GAP**: rows A/B counts and the disagreements count. |
| AG-5 | Miner page: "pass A against the second pass on n works both read" | text | `measure.works_both` | existing:Miners/Two readings | |
| AG-6 | Per-field bar (agreed/compared) linking to the field's disagreement block | chart | `measure.agreed/total` | existing:Miners/Two readings (track per field) | |
| AG-7 | Per-field table: field, agreed/compared, rate, disagreements | table | `measure` | existing:Miners/Two readings (rate, n) | **GAP**: disagreements count per field. |
| AG-8 | Disagreement blocks per field (sorted by count): description, allowed values, then every disagreement: paper title link, "why" pill, row key, side-by-side Pass A and Pass B (value, quote, anchor) | item-page | `measure.disagreements`, `spec.field_named` | new:Miners/Disagreements | **GAP, largest on this page**: `hub_mining` returns no disagreement pairs. v2 Flow/Screening has the equivalent for screening only (`hub_screening.PairDisagreement`). New payload `mining_disagreements(miner, field)`, paged. |
| AG-9 | "What you can do": read the pairs; overlapping categories -> tighten definitions in a new version; one pass left a field empty -> decide if required; which pass is right needs gold labels; terminal commands `mine agreement <name>`, `mine resolve --help` | text | static | new:Miners/Disagreements ⓘ | Information; port as text. |
| AG-10 | Platform vs fairer measure explanation (platform aligns on row key including quote position; fairer per work or enum key; secondary label agrees with other pass primary or secondary; one-sided labels are completeness, not disagreement; text and quotes not compared) | text | `site_agreement` docstring, `GLOSSARY` | existing:Miners/Two readings ⓘ | In `METHODS.fairer/exact/platform`; verify the secondary-label and one-sided rules are stated. |
| AG-11 | Per-miner one-sided counts (`one_sided`) | kpi | `measure.one_sided` | existing:Miners/fairer payload (`one_sided`) | Present in payload; **GAP** if not drawn. |

## 8. Taxonomy (`taxonomy`) — prefix TX

Builder: `site_taxonomy.build_taxonomy` (legacy `taxonomy.json`, plus registered taxonomies via `site_taxonomy_registered`: index, one page per version, diff). v2 equivalents: Lenses/Taxonomy is an **icicle of the corpus** (layer, technique, architecture), not the taxonomy definitions. No v2 view shows registered taxonomies, definitions or diffs.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| TX-1 | Registered taxonomies index: name, versions latest first (v, digest 12 chars, date, dimensions, categories), open proposals | table | `taxonomies.list_taxonomies`, `list_proposals`, `registered_taxonomy` | new:Method/Taxonomy | |
| TX-2 | Version page header: name, version, links to other versions, open proposals, rationale | item-page | `registered_taxonomy` | new:Method/Taxonomy (version page) | |
| TX-3 | Derived miner note: miner name and version, link to the miner; "No derived miner yet" | link | `site_taxonomy_registered.derived_miner` | new:Method/Taxonomy; link to existing:Miners/detail | |
| TX-4 | Diff table from the previous version: added, removed, redefined, renamed, split, merged, dimension changes | table | `mining.taxonomy.diff` | new:Method/Taxonomy (changes) | Computed, not typed. |
| TX-5 | Per dimension: question, cardinality, read scope (whole text or headings), residuals; or "categories come from layer scheme version n" | table | `TaxonomySpec.dimensions` | new:Method/Taxonomy | |
| TX-6 | Per category: id and name, definition, works with a current row (or "not mined"), include cues, exclude cues, examples as quote (work link, anchor) | item-page | `Category`, `derived_counts` (live non-stale pass-A rows) | new:Method/Taxonomy | Counts: `category_counts`. Residual counts per dimension. |
| TX-7 | Anchors per category (`#dimension.category`) | link | `full_id` | new:Method/Taxonomy | Deep links from Miners distributions into the definition. |
| TX-8 | Legacy section "Earlier unregistered list": status, source, per dimension a table (category, keyword pattern) | table | `<project>/taxonomy.json` | new:Method/Taxonomy (legacy, collapsed) or drop? | Old unregistered file, "kept as it was". Researcher to decide whether to keep. |
| TX-9 | Legacy: works placed by the classification miner per category (bars linking to explorer filter) | chart | `corpus_payload` + `load_profile` | existing:Lenses/Taxonomy (icicle) and existing:Miners distributions | Covered by counts elsewhere. |
| TX-10 | "What you can do": split a broad category, record a revised taxonomy as a new version, run the classification miner again (old rows stay); commands; IDEA-50 | text | static | new:Method/Taxonomy ⓘ | |
| TX-11 | Codebook of technique codes (stage, label) from `t-tech-*` taxonomies | table | `hub_mining.codebook` | existing:Miners/codebook (`MP.codebook`) | Already in the Miners payload (`methods.codebook`); Method/Taxonomy should reuse it. |

## 9. Lifecycle (`lifecycle`) — prefix LC

Builder: `site_lifecycle.build_lifecycle` (`lifecycle_data` over `corpus_payload` `m-stages` rows and `layers_of`; `own_stage_sequences` over `m-lifecycle`). Researcher scope: **both** the overall stage sequences across all papers **and** each paper's own sequence. No v2 page has these.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| LC-1 | Explanation note (nodes are stages of `m-stages`, size = works that automate it, arcs = works covering both, thicker is more; left to right is a layout convention, not a finding; layer filter not calibrated; state in URL) | text | static | new:Method/Lifecycle ⓘ | Carries the "layout is not a finding" warning. |
| LC-2 | Stage flow diagram: 9 nodes (literature review, ideation and hypothesis, experiment design, implementation and execution, data analysis, paper writing, review and verification, lab automation, other) sized by works; co-occurrence arcs thickness by works covering both; click node or arc selects | chart | `lifecycle_data`: `works[].stages`, `STAGES` | new:Method/Lifecycle (overall flow) | Overall stage view across all papers. Today it is co-occurrence, not order. |
| LC-3 | Filter chips: layer (all, core, benchmark, applied, adjacent, background, off-topic with counts) | filter | `layers_of`, `lifecycle_data.layers` | new:Method/Lifecycle | |
| LC-4 | Filter chips: mode (any, automated, human-assisted, mentioned-only) | filter | `MODES` | new:Method/Lifecycle | |
| LC-5 | List of works for the selected stage or arc: "n works cover X (and Y) (layer L)"; each work: title link to paper, layer badge, mode badge, first quote with anchor | table | `lifecycle_data` | new:Method/Lifecycle | Click opens the shared drawer. |
| LC-6 | URL state `#layer=&mode=&stage=` | link | client | new:Method/Lifecycle | Keep (bookmarkable). For an arc the stage value joins two stage ids with a vertical bar. |
| LC-7 | Matrix: works per stage (rows) and layer (columns) with totals; each count opens the list; "Steps ->" link per stage row | table | `lifecycle_data` | new:Method/Lifecycle | |
| LC-8 | Per-paper own stage sequences table: paper (title link, year), stages in order as chips "order name -> next, loop n" coloured by actor (automated, human-assisted, na), hover shows "how"; lead "n papers, from pass A of `m-lifecycle`; until the production run these are the calibration sample only and not yet checked against the gold labels" | table | `own_stage_sequences` (`m-lifecycle`: `stage_order`, `stage_name`, `actor`, `how`, `next_stage`, `loops_back_to`) | new:Method/Lifecycle (each paper's own sequence) | Researcher-approved. Keep the calibration warning. |
| LC-9 | Empty state: "No paper has stage rows from `m-lifecycle` yet. It is registered and listed for core works; calibration (10 works labelled) comes before the production run." | text | `own_stage_sequences` | new:Method/Lifecycle | |
| LC-10 | **Overall stage sequences across all papers** (new analysis the researcher asked for): the transition structure of `m-lifecycle` over all papers (stage-name to next stage counts, loops back, most common orders) | chart | `own_stage_sequences` aggregated by a new deterministic function in `services/hub_lifecycle.py` | new:Method/Lifecycle (overall sequences) | Not in the old page (old overall view is co-occurrence). Stage names are free text per paper; the plan's "group stage names into a common lifecycle" step is a precondition, so define the grouping rule first and state it in the ⓘ panel. |
| LC-11 | "What you can do" links: Explorer, Miners (state of `m-stages`, `m-lifecycle`), Agreement, Taxonomy, Backlog; next step text (label the calibration sample, run on core works, group stage names); `mine status` command | text | static | new:Method/Lifecycle ⓘ | |

## 10. Steps (`steps`) — prefix ST

Builder: `site_steps.build_steps` (`step_rows` of live closed pass-A rows of the latest `m-stage-steps` version; `steps_view`). Exploratory miner, no calibration.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| ST-1 | EXPLORATORY banner: miner `m-stage-steps` v1 has no calibration; rows are for reading, not evidence; no count goes into a report, hub claim or hypothesis; some steps may sit in the wrong stage | text | static | new:Method/Steps | Must stay visible at the top of the page (rigour). |
| ST-2 | Count strip: one cell per stage (n works with steps, n steps); click selects the stage | kpi | `steps_view` | new:Method/Steps | |
| ST-3 | Stage tabs (all stages plus nine) | filter | `STAGES` | new:Method/Steps | |
| ST-4 | Filters: actor (any, automated, human-assisted, human, not stated), has a check, has limits, text search; "n steps shown" | filter | `ACTORS`, client | new:Method/Steps | Absence worded as "not stated", never a value. |
| ST-5 | One section per stage: "n works, m steps"; per work: title link (+ year), ordered list of steps: order number, step text, anchor, actor badge | item-page | `steps_view` | new:Method/Steps | Empty stage says "No steps in this stage: the miner found none in any work." |
| ST-6 | Per step collapsible details: inputs, outputs, method, check, limits, each with verbatim quote and anchor | item-page | `OPTIONAL` fields | new:Method/Steps | |
| ST-7 | Link from the lifecycle matrix: `steps#stage-<id>` | link | static | new:Method/Steps | Keep stage anchors. |

## 11. Updates (`updates`) — prefix UP

Builder: `site_updates.build_updates` (`updates.updates_view`, `protocol.current_protocol` for sources). All acts post to the project's `/api/*` with its token as the local human. Target: **Living** (researcher ruling). Existing Living has Feed river, Horizon, Heartbeat, all read-only.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| UP-1 | Header box: "Since v1 (snapshot id, date): n included at v1, m works added since"; open period (since snapshot, new works, included at title/abstract); or "No snapshot yet" | kpi | `updates_view.baseline`, `open_period` | new:Living/Since v1 | Horizon has related counts (ideas/edges per year) but not the v1 baseline. |
| UP-2 | Additions since v1 table: added date, title, year, route, note, outcome (TA outcome / FT state / FT outcome), layer, mined (miners) | table | `updates_view.additions` (`AdditionRow`) | new:Living/Since v1 | Each title opens the drawer. |
| UP-3 | Route filter buttons: all, inbox, feed, watch, chase, search, other | filter | client | new:Living/Since v1 | |
| UP-4 | Empty text "No work has entered the corpus since v1." | text | static | new:Living/Since v1 | |
| UP-5 | Add-link form: link or identifier, note; button "Add to the inbox (as you)"; message "already in the inbox" / "added" | act | `POST /api/inbox/add` | new:Living/Since v1 (act) | **ACT**. Same act as HM-16 and Graph/Foundations snowball-add; reuse one v2 route. |
| UP-6 | Growth chart: included works per snapshot (inline SVG line, v1, v2 ... with values) | chart | `updates_view.growth` | new:Living/Growth | |
| UP-7 | Update-flow table per snapshot: version, snapshot id, recorded, studies included, identified, screened, passed TA, identified by route (databases; other) | table | `GrowthPoint` | new:Living/Growth | |
| UP-8 | Weekly watch block: on/off, end date, open cycle; table source, mode, every n d, last cycle, next (or "due now"), last full run, weekly windows since | table | `updates_view.watch` (`WatchView`) | new:Living/Weekly watch | |
| UP-9 | Watch settings form: source checkboxes (from the protocol's included sources), interval days, end date; "Save watch settings (as you)" | act | `POST /api/watch/configure` | new:Living/Weekly watch (act) | **ACT**; records an amendment (message "saved: protocol <id>"). |
| UP-10 | "Close week now (as you)" | act | `POST /api/living/snapshot` | new:Living/Weekly watch (act) | **ACT**. |
| UP-11 | Note: sources run in window mode; a full re-run never happens automatically; command `watch run --full-replay` | text | static | new:Living/Weekly watch ⓘ | |
| UP-12 | Actions disabled until served with the token | text | static | existing:shell (`HUB.served`) | v2 pattern: act buttons disabled when not served (as Foundations). |

## 12. Layers (`layers`) — prefix LY

Builder: `site_layers.build_layers` (`layers_of`, `layer_moves`, `layers_payload`, `layers_view`). Per-work provenance (miner vs researcher move) is in the Corpus drawer already (EX-17).

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| LY-1 | Note: layers are the project's triage (core, benchmark, applied, adjacent, background, off-topic) from `m-layer` or a researcher move; layer pass **not yet calibrated**, a first triage, not a finding | text | static | existing:Overview composition ⓘ and Corpus facet ⓘ | The "not calibrated" warning should be stated in the layer facet's ⓘ. **GAP** if absent. |
| LY-2 | Concentric rings: one dot per work on its layer ring (outer halo = unlayered), moved works marked with the miner's layer, hover title, click opens paper, ring links to the explorer filter | chart | `layers_payload` | existing:Explore/rings (different encoding) | v2 Explore rings are core, benchmark, applied, adjacent and one merged outer ring (background, off-topic, unlayered), placed by recency with semantic zoom. **GAP**: background and off-topic are not separate rings, and a work moved by the researcher is not marked. |
| LY-3 | Replay control: Replay button, range slider, date; steps = one per day of layer moves (cap 120, earliest merged) | chart | `layer_moves`, `replay_steps` | new:Flow/Replay (layer replay) or new:Method (needs ruling) | **GAP**: no v2 replay of layer moves. Flow/Replay animates record fates, not layers. |
| LY-4 | Legend: layer colour, name, count; "unlayered n" | chart | `layers_payload.counts` | existing:Overview/composition | Present as composition by layer. |
| LY-5 | Per-layer lists: table work (link) and year, with badge "moved by the researcher (miner said X)"; anchors `#layer-<name>` | table | `layers_view` | existing:Corpus/facet layer + detail | The list is a Corpus filter. The "moved" badge is in the drawer, not in list rows (minor **GAP**). |
| LY-6 | Note: "n further works have no layer row (outside the layer pass's population)" | text | `layers_view.unlayered` | existing:Corpus (layer "unlayered" facet) | |
| LY-7 | "What you can do": Lifecycle filter by layer, layer miner page, explorer; `mine status` | text | static | existing:Miners/detail m-layer | |

## 13. Synthesis pages (`synthesis`) — prefix SY

Builder: `site_synthesis.build_synthesis` (`pages.list_pages`, `read_page`, `corpus_payload`; one page per recorded synthesis). Model-written, never regenerated by a build.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| SY-1 | Intro note: pages are interpretations, never evidence; checked mechanically when recorded; stale when rows change; add or revise via an `rf-synthesize` session | text | static | new:Write and export/Synthesis ⓘ | |
| SY-2 | Card per recorded page: title, badges (model-written, stale with reason, n flags), scope, model or actor kind, words | table | `pages.list_pages` (`PageInfo`) | new:Write and export/Synthesis | |
| SY-3 | Page view: header (badges, scope, who, date, words, page id), mechanical-check summary (cited sentences, quotations verified verbatim, numbers checked against computed statistics), flags list (sentence), rendered body (headings, lists, bold, `[[works/slug]]` citations as chips linking to the paper) | item-page | `read_page`, `markdown_to_html` | new:Write and export/Synthesis | Citations open the drawer. Keep the label "model-written" and the stale flag. |
| SY-4 | "Scopes a page can be written for": table scope (overview, technique=, stage=, field=), works count (link to Corpus filtered), page state (read link, stale badge, or "no page yet") | table | `site_synthesis._scope_table`, `pages.subset` | new:Write and export/Synthesis | |
| SY-5 | How to write or revise (skill `rf-synthesize` example command) | text | static | new:Write and export/Synthesis ⓘ | |
| SY-6 | Empty state "No page is recorded yet." | text | static | new:Write and export/Synthesis | |

## 14. Conversion coverage (`conversion`) and inspector item pages — prefixes CV and CI

Builder: `site_quality.build_conversion` -> `site_inspector.build_conversion_site` (`conversion_coverage`, `documents`, `gaps`; one item page `doc/<slug>.html` per document, written lazily by `render_conversion_item`). Target: **Sources/Conversion**. Nothing in v2 shows conversion.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| CV-1 | Explanation note: word 5-gram comparison of each original with its Markdown (computed at); recall = share of the original found in the Markdown; precision = share of the Markdown found in the original; both noisy (running headers, numbered lines), rank documents for a person, decide nothing; low is below 0.8; click a document | text | `conversion_coverage` (`computed_at`, `LOW`) | new:Sources/Conversion ⓘ | Rigour: mechanical aid, no judgement. |
| CV-2 | Per-converter summary table: converter, documents, median recall, median precision, low recall count, low precision count | table | `report` summary | new:Sources/Conversion | |
| CV-3 | Scatter: every document, recall (x) against precision (y), coloured by converter, dashed low region (below 0.8), mark links to the item page, tooltip "title: recall, precision" | chart | `site_charts.scatter` | new:Sources/Conversion | Needs a keyboard-reachable list alternative (plan rule 7): CV-5. |
| CV-4 | "Not measured" list with reasons (no comparable plain text) | table | `report.not_measured` | new:Sources/Conversion | |
| CV-5 | Document table: recall, precision, words, converter, document title; filter by title, by converter, checkbox "only low (below 0.8)"; sortable by recall, precision, words, title; count; low values highlighted; row opens item page | table | `documents`, client | new:Sources/Conversion | Default sort lowest recall first (the dashboard's "check these first"). |
| CI-1 | Item page header: title, back link, score pills (recall, precision, words source to markdown) or "not measured" | item-page | `write_document_page` | new:Sources/Conversion item page | |
| CI-2 | Buttons: Open original, Raw Markdown, In the explorer | link | `files/<slug>.<ext>`, `files/<slug>.md` | new:Sources/Conversion item page | Needs a served route for stored originals and Markdown (library blobs), not symlinks. |
| CI-3 | Original pane: PDF in the browser viewer; HTML in a sandboxed frame; LaTeX source archive as a file listing; tabs "Original view" and "Original text" | item-page | `_original_pane`, `cov._source_text`, `_tar_listing` | new:Sources/Conversion item page | Sandbox the HTML frame (no scripts). |
| CI-4 | Extracted Markdown pane (converter name), rendered with paragraph anchors shown as bracketed ids | item-page | `markdown_to_html`, `_ANCHOR` | new:Sources/Conversion item page | Anchors are what quotes point to; keep visible. |
| CI-5 | Gap lists (only where recall or precision is below 0.8): runs of 6+ words of the original not found in the Markdown (possible lost text) and runs of the Markdown not found in the original (possible added or scrambled text), each with its position; empty messages | table | `site_inspector.gaps` | new:Sources/Conversion item page | |
| CI-6 | "What to do": converted with <converter>; other converters that accept the format and run here; commands `document convert --work <id> --converter <name>`, `document converters`, `document read <work> --document <id>` with Copy | cmd | `converter_infos`, `_actions` | new:Sources/Conversion item page | |
| CI-7 | Back-links: from Explorer detail, Dashboard (Lowest recall, cannot-assess), Acquisition | link | static | new:Sources/Conversion item page | URL `sources#conv=<slug>` or a `/ui/conversion/<slug>` route. |

## 15. Full-text acquisition (`acquisition`) — prefix AC

Builder: `site_quality.build_acquisition` (`fulltext_status.fulltext_status`, `protocol.list_deviations`; one item page `work/<slug>.html` per not-retrieved work). Target: **Sources/Acquisition**.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| AC-1 | Intro note: routes tried (arXiv HTML, arXiv source, open-access PDF, files you supply); not-retrieved works are excluded from FT screening and extraction; a deviation records the decision; "n not-retrieved work(s) are not declared by any deviation yet" / "Every not-retrieved work is declared" | text | `fulltext_status`, `list_deviations` | new:Sources/Acquisition | The undeclared count is information; compute it. |
| AC-2 | "How to read the counts" glossary: promoted to full text, unsought (later tranche), retrieved, not retrieved | table | static | new:Sources/Acquisition ⓘ | |
| AC-3 | Counts row: promoted, unsought, retrieved, not retrieved | kpi | `FulltextStatus` | new:Sources/Acquisition | Also Flow (not sought, not retrieved) as counts; same numbers must agree. |
| AC-4 | Retrieved by route (bars): arxiv-html, arxiv-source, pmc-jats, europepmc-jats, oa-pdf, researcher-supplied; each route explained | chart | `status.by_route`, `ROUTE_HELP` | new:Sources/Acquisition | |
| AC-5 | Not retrieved table: title, DOI, published, reasons (route: why), declared by (deviation id or "not declared"); sorted undeclared first then title; row opens item page | table | `status.works` where `not-retrieved` | new:Sources/Acquisition | |
| AC-6 | Item page: title, authors, date, venue, pill "declared by <deviation>" or "not declared by any deviation" | item-page | `_work_page` | new:Sources/Acquisition item page | |
| AC-7 | Item page: "What the automatic routes tried" table route, what it is, result, meaning (`REASONS`: no-arxiv-id, no-arxiv-html, no-latex-source, no-oa-pdf, no-identifier, http-403, http-404, no-pmcid, no-version, not-open-access, no-body, not-in-europepmc, not-a-pdf) | table | `w.reasons`, `REASONS`, `ROUTE_HELP` | new:Sources/Acquisition item page | |
| AC-8 | Item page: "Look for a copy yourself": links to publisher (DOI), OpenAlex record, Google Scholar title search, arXiv title search, Semantic Scholar title search | link | `_works_info` | new:Sources/Acquisition item page | External links. |
| AC-9 | Item page: "What you can do": 1 retry routes (`fulltext fetch --work <id>`), 2 import a copy (file name `<DOI with / as _>.pdf`, then `fulltext import FOLDER`), 3 declare not acquired (deviation JSON template with description, reason, affects; command `protocol deviation --file deviation.json`) or "already declared by <id>" | cmd | `_work_page` | new:Sources/Acquisition item page | Declaring is a human act; the v2 page keeps commands, does not write. Could become an act later (needs ruling). |
| AC-10 | "Declare the n undeclared works at once": deviation JSON for all undeclared works | cmd | `build_acquisition` | new:Sources/Acquisition | |
| AC-11 | Protocol deviations table: deviation id, works affected, description (200 chars) | table | `list_deviations` | new:Sources/Acquisition | Also feeds RS-4. |

## 16. Run costs (`costs`) — prefix CO

Builder: `site_costs.build_costs` (`run_costs.cost_report`, `runs_with_logs`, `token_growth`; `site_charts.line_chart`). Target: **Costs and runs/Costs**. Nothing in v2 shows costs.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| CO-1 | Caveat note: what the figures are (reported cost of headless runs, not dollars the platform records) | text | `report.caveat` | new:Costs and runs/Costs ⓘ | Must travel with every cost figure. |
| CO-2 | Summary line: cost source, runs, units, reported cost (USD) | kpi | `CostReport` | new:Costs and runs/Costs | |
| CO-3 | Table per stage, model and miner: stage, model, runs, complete, units, reported cost, cost per unit, median turns, median duration (s), input per unit, output per unit, cache read per unit, cache write per unit | table | `report.groups` (`CostGroup`) | new:Costs and runs/Costs | Sortable. |
| CO-4 | "What the columns mean" (units, reported cost, cost per unit, per-unit tokens, token growth) | text | static | new:Costs and runs/Costs ⓘ | |
| CO-5 | Token growth chart per stage: mean input + cache-read tokens by turn | chart | `token_growth(project, stage)` | new:Costs and runs/Costs | One chart per stage. |
| CO-6 | Empty state "No headless run is recorded for this project yet." | text | static | new:Costs and runs/Costs | |
| CO-7 | Agent events per model (from Results RS-5 and dashboard DB-36); budgets table (unit, scope, limit, consumed, remaining); reported usage | table | `events`, `budget_status` | new:Costs and runs/Costs | Merge into one page; label events as not cost. |

## 17. PRISMA 2020 flow (`prisma`) — prefix PR

Builder: `site_prisma.build_prisma` (`prisma_flow`, `exports.export_prisma_svg`, `current_protocol().spec.criteria`). v2 target: Flow for the numbers; SVG export in **Write and export**.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| PR-1 | Note: what PRISMA is; numbers computed from recorded decisions; stop by a declared rule, unscreened works reported | text | static | existing:Flow ⓘ | |
| PR-2 | PRISMA 2020 flow diagram (SVG, white panel) | chart | `export_prisma_svg` | existing:Flow/Records at each step (Sankey) | Different drawing. The standard PRISMA drawing is kept as an export (PR-3). |
| PR-3 | Download `prisma.svg` | export | `export_prisma_svg` | new:Write and export/PRISMA SVG | Also show it inline. |
| PR-4 | "What each box means" glossary (identified, duplicates removed, screened, excluded, sought, not retrieved, assessed, excluded at FT, included) | table | `LEGEND` | existing:Flow ⓘ / glossary terms | Verify each of the 9 definitions is a glossary term. |
| PR-5 | Criteria table: criterion id, what it excludes (statement), excluded at title/abstract, excluded at full text, with "(of which kept as background: n)" | table | `prisma_flow.excluded`, `.background`, `ft.excluded`, `ft.background`, protocol criteria | existing:Flow/Reasons for exclusion (per stage cards) | **GAP**: "kept as background" counts per criterion (IDEA-47) and the criterion statement table are not in `hub_screening.reasons_wall`/Flow. |
| PR-6 | "Where to go next": included works -> explorer; not retrieved -> acquisition; how numbers were reached -> Search and Screening tabs, `report methods` | text | static | existing:Flow + new:Sources | |
| PR-7 | Single source of the numbers: counts agree with Flow, Results, Acquisition, Home station | kpi | `prisma_flow` | existing:Flow (`ledger_reconciles`) | Add the reconciliation line (FL-2). |

## 18. Search and deduplication (`search`) — prefix SE

Builder: `site_search.build_payload` (`search_report`, `run_gaps`, `skipped_records`, `list_merges`, `merged_after_screening`, `_revert_times`). Target: **Sources/Search and dedup**. Nothing in v2.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| SE-1 | Header: project, generated time; error line if archived search pages cannot be read | kpi | `build_payload.error` | new:Sources/Search and dedup | |
| SE-2 | Query card per registered query: id, source, kind, purpose, registered date, text (code), filters (k=v or none), round | item-page | `search_report.rows` | new:Sources/Search and dedup | |
| SE-3 | Per query counts: reported (or "not reported"), retrieved, gap (red when non-zero), shortfall reason (collapsible when long) | kpi | `search_report`, `run_gaps` | new:Sources/Search and dedup | The gap is reported minus retrieved. |
| SE-4 | Runs table per query: run id, status, reported, retrieved, skipped, new works, pages archived, note | table | `r.runs` | new:Sources/Search and dedup | |
| SE-5 | Skipped records per query (collapsible; reason, run, native id, title; first 1000 shown with note) | table | `skipped_records` | new:Sources/Search and dedup | Records that never became works. Same list as Flow old "never became works" (FL-9). |
| SE-6 | Dedup rule counts table: rule, active, reverted | table | `_counts(merges)` | new:Sources/Search and dedup | |
| SE-7 | Merge list: merge id, status tag (+ reverted time and reason), rule, records, primary (title and id), absorbed (title and id list) | table | `list_merges`, `_revert_times` | new:Sources/Search and dedup | Revert time comes from the log (`dedup.reverted`), not the projection. |
| SE-8 | Merge filters: text search (id, titles), rule select, status select, Clear filters; count "n of N merges"; "Show more" (300 per step) | filter | client | new:Sources/Search and dedup | |
| SE-9 | "Merged after screening" table: merge, rule, primary kept and its outcome, absorbed and its outcome; note "the canonical work's outcome stands in every count (researcher ruling 2026-11-14); listed for review" | table | `merged_after_screening` | new:Sources/Search and dedup | |
| SE-10 | Per-source totals and "PRISMA identification" split into databases and other (from dashboard Search tab) | table | `search_report`, `prisma_flow.identified_*` | new:Sources/Search and dedup | From DB-21. |
| SE-11 | Explanatory text: "The gap is the total the source reported less the records retrieved; records of an archived page that did not become works are listed under their query" | text | static | new:Sources/Search and dedup ⓘ | |
| SE-12 | Merge revert (CLI `dedup revert`) | cmd | `merge_revert` | drop? | Old page has no act; v2 keeps it read-only. State only. |

## 19. Flow explorer (`flow`) — prefix FL

Builder: `site_flow.build_flow` (`flow_ledger`, `ledger_reconciles`, `flow_trails` -> `trails.js` loaded on demand, `run_gaps`, `skipped_records`, `prisma_flow`). v2 target: **Flow** (Where the records went, Screening, Replay, Paths). Note: the v2 Flow record list excludes records merged before they had a record of their own (the page says how many).

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| FL-1 | Intro: every identified record by the source that found it and the step reached; a number in the table filters the list; click a title for its trail | text | static | existing:Flow ⓘ | |
| FL-2 | Reconciliation banner: "The ledger does not reconcile with the PRISMA flow: <mismatches>" (red) | kpi | `ledger_reconciles`, `mismatches` | existing:Flow (load check) | `hub_payloads.load_flow_data` raises when counts differ; no visible "reconciled" line. Show one. |
| FL-3 | "PRISMA steps by source" table: rows = steps (works and absorbed duplicate rows, screened, excluded plus each criterion, included, pending, promoted, not yet sought, sought, not retrieved plus each reason, retrieved, excluded at FT plus each criterion, included, pending, awaiting), columns = source groups (arxiv-only, openalex-only, both, other, Total); each count links to the filtered list | table | `site_flow.table_spec`, ledger `tags`, `source_group` | existing:Flow/Where the records went (Sankey nodes, source nodes) | **GAP**: the cross-tab step by source group. v2 has source nodes in the Sankey and per-node record lists, but not the matrix with every criterion/reason row by source. |
| FL-4 | Records list: columns Title, Year, Source group, Sources (list), Step reached, Outcome, Criterion or reason; sortable (except Sources); row click opens the trail panel | table | `_work` rows | existing:Flow/record list | v2 columns: Title, Outcome, Layer, Year, Cited here, Path. **GAP**: Source group and Sources columns, Step reached as its own column. |
| FL-5 | Filters: text (title, id, source), Source group select, Step select, Outcome select, Criterion-or-reason select, filter chip for the table step, Clear filters, count "n of N records" | filter | client | existing:Flow/record list facets | v2 has facet chips and title search; **GAP**: filtering by source group and step as separate facets (source group lives in `record.source`). |
| FL-6 | Download CSV of the filtered list (work_id, title, year, source_group, sources, step, outcome, criterion_or_reason, duplicate_of) | export | client | new:Flow/record list (CSV) | **GAP**: no CSV. A CSV of the selection is also wanted by Write and export. |
| FL-7 | "Show more" (300 per step) | filter | client | existing:Flow/record list (100 per step) | |
| FL-8 | Trail panel per record: title, id, year, source group and sources; "Step reached: step, outcome (criterion)"; "Duplicate of <title>" link; absorbed duplicates links; Trail: per step kind, time, key-values (document and primary linked), long fields rationale/quote/reason/error as quotes | item-page | `flow_trails` (`trails.js`) | existing:Flow/Paths (one-paper swimlane, All stops table) | Present with When, Stage, Who, Outcome, Criterion, After, Reason, Quote. **GAP**: absorbed-duplicates and duplicate-of links, sources list, document/primary ids. Paths exist only for records of the review in the static copy. |
| FL-9 | "PRISMA identification (from the PRISMA flow)": rows identified, database per source, other per source, duplicates removed; note that these figures come from the PRISMA flow, not from the ledger rows, and absorbed duplicates are grouped by their own provenance so per-column rows close only in the total | table | `prisma_flow` | existing:Flow (identified, duplicate nodes) | The explanatory note about why columns close only in the total is **GAP** (information). |
| FL-10 | "Records that never became works": per query reported vs retrieved vs gap (red when non-zero) with runs; skipped records count by reason; list (reason, source, query, run, native id, title; first 2000) | table | `run_gaps`, `skipped_records` | new:Sources/Search and dedup | Moves to Sources (SE-3, SE-5). No v2 Flow equivalent. |

## 20. Study documents (`documents`) — prefix DC

Builder: `site_documents.build_documents` (`study_files.list_files`, `file_status`; `documents_stamp`). Target: **Sources/Documents**.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| DC-1 | Summary note: n registered files, m changed since registration, k missing; each registration keeps the content named so an earlier version stays readable | kpi | `list_files`, `file_status` | new:Sources/Documents | |
| DC-2 | One section per kind (Study documents, Validation, Inputs, Operational files, Other); table File (title or path, path), Version, Registered, Status (unchanged, changed since registration in amber, missing in red), Earlier versions (version, date, sha256 12) | table | `FILE_KINDS`, `StudyFile.history` | new:Sources/Documents | |
| DC-3 | File opens: Markdown rendered from the stored blob of its latest version; other files linked to the project file; files outside the project marked "outside the project" and not linked | item-page | `project.blobs.get`, `markdown_to_html`, `_slug` | new:Sources/Documents item page | Needs a served route; the old hub used symlinks. Never serve a path that resolves outside the project. |
| DC-4 | Markdown page header: path, version, registered date, sha256 12 | item-page | `StudyFile.latest` | new:Sources/Documents item page | |
| DC-5 | Empty state "No file is registered yet. Use `factory files register`." | text | static | new:Sources/Documents | |
| DC-6 | Stamp (stat of each registered file) so the page rebuilds when a file changes on disk | poll | `documents_stamp` | new:Sources/Documents (fingerprint) | Cache key detail, not UI. |

## 21. Runs (`runs`) — prefix RN

Builder: `site_runs.build_runs` (`run_groups` over `ops/`, `_event_ids`; symlinks `ops/` into the output). Target: **Costs and runs/Runs**.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| RN-1 | Summary note: n files in m groups under `ops/`, k groups unlinked (no file name holds a run or task id an event names); the files are not events | kpi | `run_groups` | new:Costs and runs/Runs | |
| RN-2 | Table: folder, batch prefix (leading token of the file name), files, modified range (first to last day), size, linked (run/task ids, first 3) or "unlinked", collapsible file list | table | `RunGroup` | new:Costs and runs/Runs | Unlinked first. |
| RN-3 | File list per group: path link (opens the file), date, size | link | `_href`, `RunFile` | new:Costs and runs/Runs | Needs a served read-only route for `ops/` files (no symlink). Restrict to the project folder. |
| RN-4 | Empty state "There is no ops/ folder, or it holds no file." | text | static | new:Costs and runs/Runs | |
| RN-5 | Warning: the page links the project's `ops/` folder and is not meant to be copied or published as is | text | static | new:Costs and runs/Runs ⓘ | Privacy-relevant (repository is public; `ops/` is not). |
| RN-6 | Link from a group to its run in costs (run id) | link | `run_cost` | new:Costs and runs (cross-link) | Not in old; trivial given the run id. Optional. |

## 22. Activity (`activity`) — prefix AT

Builder: `site_activity.build_activity` (`activity.activity`, cached by `activity_cached`; polled `GET /api/activity` every 10 s). Target: **Pipeline/Activity**.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| AT-1 | Live line: "Live, as of <time> (refreshed every 10 s)" / "Snapshot as of" / "Live update unavailable" | poll | `/api/activity` | new:Pipeline/Activity | Pause polling when the tab is hidden (old did). |
| AT-2 | Held tasks table: session (last 6), task (scope, miner version, pass, mode), paper, held minutes, lease minutes left, rows recorded, last event, state (active or "stale (no event for n min)") | table | `Activity.active` | new:Pipeline/Activity | Stale in amber. |
| AT-3 | Passes table: pass (name, version, pass label, mode), done, total, held, abandoned, done in 30 min, rate estimate per hour, left estimate (min, or "unknown"), released | table | `Activity.passes` (`PassRow`) | new:Pipeline/Activity | Rate and time left are **estimates**; label them. |
| AT-4 | Dormant passes: collapsed list "n dormant passes" (name, done/total, abandoned) | table | `Activity.dormant` | new:Pipeline/Activity | |
| AT-5 | Long operations table: operation, state, done, total, elapsed (s) | table | `Activity.operations` | new:Pipeline/Activity | Same as DB-5; one panel. |
| AT-6 | Worker traces table: file, modified, last line (mono), size; "No trace file changed in the last 2 hours." | table | `Activity.traces` | new:Pipeline/Activity | |
| AT-7 | Empty states: "No task is held.", "No pass is open." | text | static | new:Pipeline/Activity | |
| AT-8 | Screening live (from the dashboard) | poll | `screening_live` | new:Pipeline/Activity | See DB-6. |
| AT-9 | `STALE_MINUTES` constant stated in the state text | text | `activity.STALE_MINUTES` | new:Pipeline/Activity ⓘ | |
| AT-10 | Text from tasks, titles, sessions, traces rendered with `textContent` only | text | n/a | new:Pipeline/Activity | Security: keep `textContent` or escape. |

## 23. Bibliography (`bibliography`) — prefix BB

Builder: `site_bibliography.build_bibliography` (`exports.export_bibliography(project, "bibtex")` via MCP `export_bibliography`; `parse_entries`; `corpus_payload` for slugs). Target: **Write and export/Bibliography**.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| BB-1 | Header: "The included works of the review: n entries" and usage text (List tab to read and sort, BibTeX tab for a reference manager; keys are stable names from first author, year, title) | text | `export_bibliography` | new:Write and export/Bibliography | Entries are the PRISMA included set. |
| BB-2 | Tabs: List, BibTeX | filter | client | new:Write and export/Bibliography | |
| BB-3 | List table: Year, Title (link to the paper), First author (+ "et al."), Key (BibTeX key), venue; sortable by year (default newest first) or title; filter by title, author, year, venue; count "n of N works" | table | `parse_entries` | new:Write and export/Bibliography | The key maps to the work slug by dropping the hash suffix. |
| BB-4 | BibTeX tab: full text in a `pre`, "Copy BibTeX", "Download .bib" (`references.bib`) | export | `export_bibliography` | new:Write and export/Bibliography | |
| BB-5 | Same entries in both views | text | n/a | new:Write and export/Bibliography | Built from one export call. |

## 24. Citations in the corpus (`citations`) — prefix CT

Builder: `site_citations.build_citations` (`citations.citation_report(project, as_of_year)`). Counts are a lower bound; unknown counts shown as "unknown", never 0. Target: partly existing (Overview most cited, Graph Foundations, Lenses Influence); remaining tables to **Write and export** or **Lenses**.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| CT-1 | Head text: counts come from n works whose reference list was extracted (m entries, k resolved to a project work) out of N works; a count is a lower bound; a citing work counts once; no self-citation of a work to itself | text | `CitationReport.extractions/entries/resolved_links/works_total` | existing:Corpus detail ⓘ (`refs_done`) and Graph/Reference health | Partial. **GAP**: entries and resolved-links totals as one sentence. |
| CT-2 | Empty note: "No reference list has been extracted: every in-corpus count is unknown." | text | `report.extractions == 0` | existing:Corpus ⓘ | |
| CT-3 | "Most cited by corpus works (top 50)": work (link), year, cited by, of which self, OpenAlex count | table | `WorkCitations` (`cited_by`, `self_cited_by`, `external`) | existing:Overview/most cited (title, cited here) | **GAP**: Overview shows 10 rows without year or OpenAlex count; `self_cited` is in the payload but not drawn; no top-50 table. Corpus sort "Most cited here" lists all. |
| CT-4 | "Citations per year since publication" (top 50): work, year, per year (as-of-year counts publication year as 1), cited by | table | `WorkCitations.per_year` | new:Lenses/Citation rate (or extend Influence) | **GAP**: no per-year rate anywhere in v2. |
| CT-5 | "Cited by the corpus, not in it (snowball candidates, top 50)": cited item (link to DOI or arXiv), year, citing works, identifier | table | `Candidate` (`citing_count`, `dois`, `arxivs`) | existing:Graph/Foundations | Foundations ranks the same idea (outside works by corpus citers, share, citing papers, Add to snowball). **GAP**: identifier column and links to DOI/arXiv; year from `outside_info` is in the payload but not drawn. Also: candidates here come from `citations.py`, Foundations from the citation graph (resolved links only); check both give the same top rows. |
| CT-6 | Self-citation definition: a citing work sharing an author name with the cited work | text | `citations` | existing:Overview/cited-here ⓘ (`cited_here` method) | Verify the definition is in `METHODS.cited_here`. |
| CT-7 | OpenAlex count shown beside in-corpus count and never merged | text | `WorkCitations.external` | new:Lenses/Citation rate | Rigour: two named counts. |

## 25. Daily updates / feed (`feed`, hub feed page, settings) — prefix FD

Builders: `site_feed.build_feed_pointer` (the `feed` product is only a pointer to the hub page), `site_hub_feed.render_feed_page` (route `/feed/`; collected by `site_hub_feed.collect`, `feed_status`, `feed_list`, `feed_ranked_page`), `site_settings` (`/p/<slug>/settings/`; `feed.propose_categories`). Acts: `POST /p/<slug>/api/feed/react`, `/api/feed/add`, `/api/feed/configure`; hub acts `POST /api/feed/run`, `/api/feed/refetch`; read `GET /api/feed/runner`. Target: **Living** (researcher ruling: all feed acts there). v2 Living today: Feed river (per day: count, shown, sent, reactions, top rows with rank, score, reaction, sent), Horizon, Heartbeat; read-only.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| FD-1 | Pointer product page "Daily updates" with link to the hub page | link | `build_feed_pointer` | drop? | Redundant once Living holds the feed. |
| FD-2 | Page title "New papers"; sub: one arXiv pull compared with each project's core works; a ranking orders, it judges nothing | text | static | existing:Living/Feed river ⓘ | |
| FD-3 | Run bar: "Fetch now", "Refetch (no cache)", run state line (a run is in progress / last run (refetch): exit n / failed / "no run yet" / "the feed runner is off") | act | `POST /api/feed/run`, `/api/feed/refetch`, `GET /api/feed/runner` | new:Living/Feed river (run bar) | **ACT**x2 with hub token; poll runner state. |
| FD-4 | Project tabs (one per project) | filter | `collect` | new:shell project switcher (needs ruling) | v2 is per project; cross-project feed needs the switcher or a project filter. |
| FD-5 | Layout toggle Grid / List (remembered); Order select: Rank, Date newest first, Date oldest first | filter | client | new:Living/Feed river (list view) | |
| FD-6 | Status line per project: "not configured" with link to Settings; or last fetch date, window from to (incomplete flag), references used (id, count), entries held n of m, categories, due now / not due | kpi | `feed_status`, `FeedStatus`, `view.last_fetch`, `view.references` | new:Living/Feed status | **GAP**: nothing in Living shows the window, reference set, held entries, categories or due state. |
| FD-7 | Ranking line: "Ranking <id>", "Showing n of N ranked, window a to b"; "No ranking yet: nothing has been fetched" | kpi | `feed_list`, `feed_ranked_page.total_ranked` | new:Living/Feed status | |
| FD-8 | Paper card (shown items in shown order): rank, score (3 decimals), badges (explore, added), submitted date, title (link to arXiv abs), nearest core work (title) or "none nearby", reaction state, abstract (clamped, More/Less), authors (when expanded), links abstract page and pdf | item-page | `FeedListItem`, `_entry_records` (entries blob) | new:Living/Feed river (day detail card list) | **GAP**: v2 day detail shows title, rank, score, reaction, sent only; no abstract, authors, nearest core work, arXiv links, date. |
| FD-9 | Card acts: Like, Dislike, Add to inbox (each records the reaction/add with the rank and, for further cards, "beyond the shown list") | act | `POST /p/<slug>/api/feed/react`, `/api/feed/add` | new:Living/Feed river (card acts) | **ACT**x3. Add triggers `work_queue.advance` after success (start deterministic steps). Held entries (held-out seeds' works) are never shown (`feed_list` drops them); keep. |
| FD-10 | "Further" cards: ranked entries outside the shown set, hidden, "Show next 30" button; note "first N ranked beyond the shown ones; M more are not listed" | table | `feed_ranked_page` (`further`, `cap`, `cut`) | new:Living/Feed river | **GAP**: v2 payload has no further/ranked-beyond list. |
| FD-11 | Short feed panel on the portal: top ranked entries across projects with Like/Dislike (no add) and "See all n ranked" | act | `site_hub_feed.top_entries`, `ranked_total` | new:Living/Feed river (top list) | See HM-17. |
| FD-12 | Settings page: feed configuration table (categories, interval, shown per cycle, ...) | table | `feed.current_config` | new:Living/Feed settings | |
| FD-13 | Settings: category proposal from the core layer: category, works, share, tick, "Accept" button (posts the proposed categories) or "no proposal (no core-layer work has an arXiv category)" | act | `feed_categories.propose_categories`; `POST /api/feed/configure` | new:Living/Feed settings | **ACT** (records `feed.configured` as the local human). |
| FD-14 | Dashboard "Feed and queue" tab details: categories, shown per cycle, interval days, last fetch window, next due, due now, latest ranking (id, shown, explore), top shown titles with Reactions 7d and Adds 7d | table | `dashboard._feed` | new:Living/Feed status | Same data as FD-6/7 plus 7-day activity. |
| FD-15 | Feed horizon chart (existing) and heartbeat (existing) | chart | `hub_living` | existing:Living/Horizon, Heartbeat | |
| FD-16 | After "Add": paper appears in the Work queue with its stage (link) | link | `work_queue` | new:Pipeline/Work queue | Cross-link. |

## 26. Work queue (`queue`) — prefix QU

Builder: `site_queue.build_queue` (`work_queue.queue`, `pipeline.stages`, `pipeline.paper_progress`, `resume.interrupted`). Acts: `POST /api/queue/process`, `POST /api/queue/resume` (dry run or real); reads `GET /api/queue/runs`, `GET /api/queue/interrupted`. Target: **Pipeline/Work queue**.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| QU-1 | Added papers table: entry id, title (link to the paper, else to arXiv), stage badge (stopped, extracted flags), detail, added time | table | `WorkQueue.items` (`QueueItem`) | new:Pipeline/Work queue | Empty state "No paper has been added from the feed yet." |
| QU-2 | Progress per paper: one column per applicable pipeline stage (one per registered miner; `intuition` excluded), cell state done / pending / n/a / stopped | table | `pipeline.paper_progress`, `stages` | new:Pipeline/Work queue | |
| QU-3 | Pending work: task kind and open units; or "No unit of work is defined yet." | table | `WorkQueue.pending` | new:Pipeline/Work queue | |
| QU-4 | "Process all" button: starts the whole pipeline (`services.pipeline`) | act | `POST /api/queue/process {stage:'all'}` | new:Pipeline/Work queue | **ACT**; disabled while a run is open. |
| QU-5 | Per-stage "Process now" buttons with "n pending (model)" | act | `POST /api/queue/process {stage}` | new:Pipeline/Work queue | **ACT**. Stage list from `pipeline.stages` where `applies`. |
| QU-6 | Run status line: "pipeline <id>: running (stage: status)" / "run <id> (stage): status; pipeline ..."; polled every 5 s while busy; buttons disabled while busy | poll | `GET /api/queue/runs` (`run_status`, `pipeline_status`) | new:Pipeline/Work queue | |
| QU-7 | Interrupted panel: lines for runs (run id, stage, kind, usage-limit with reset time and "(estimated)", "no pending units"), pipelines (kind, stages left), expired leases by kind, stale passes (stage or scope, label, pending, session, silent since), papers never looked up, screened-in without full text sought, full texts not converted; or "Nothing is interrupted." | poll | `resume.interrupted`, `GET /api/queue/interrupted` | new:Pipeline/Work queue | Poll 15 s. Usage limit resets matter for planning. |
| QU-8 | "Preview" (dry run) of Resume: plan lines (reconciled, leases lapsed, pipeline resumed from stage, run resumed with model, waiting, queued, stale passes not resumed, automatic steps undone) | act | `POST /api/queue/resume {dry_run:true}` | new:Pipeline/Work queue | **ACT** (writes nothing). |
| QU-9 | "Resume" (real): 202 when started; outcome (ids, refusals) kept as `last_resume`; disabled when nothing interrupted, a run is open or not served | act | `POST /api/queue/resume {}` | new:Pipeline/Work queue | **ACT**. |
| QU-10 | Hint "Process now works when this page is opened with `factory site serve`" | text | static | existing:shell (`HUB.served` pattern) | Update wording. |
| QU-11 | Dashboard Feed-and-queue: work-queue counts and last run (run open, pipeline open, last stage/outcome/finished) | kpi | `dashboard._feed_queue`, `_feed_run` | new:Pipeline/Work queue | Same as DB-35. |

## 27. Backlog board (`backlog`, main hub) — prefix BL

Builder: `site_backlog.render_backlog` (`parse_backlog`, `classify`, `area_notes` over `docs/backlog.md`; override `FACTORY_BACKLOG`). Factory-wide, not per project. Target: **Platform/Backlog**.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| BL-1 | Intro text: board of every idea, ready ideas first ordered by how many they unlock; computed states (done, specified, ready, blocked, parked); tray; selection kept in the browser only; nothing written back | text | static | new:Platform/Backlog ⓘ | |
| BL-2 | View switch: Board, Dependency tree (`#tree`) | filter | client | new:Platform/Backlog | |
| BL-3 | Filter text box ("Filter ideas") and area chips (All areas plus each area); stat counter | filter | `parse_backlog` | new:Platform/Backlog | |
| BL-4 | Area note line under the chips | text | `area_notes` | new:Platform/Backlog | |
| BL-5 | Board columns: Ready (sorted by unlocks), Blocked, Specified, Done, Parked, each with a help line; idea card: id, title, area, state class, unmet dependency count, "+" select button | chart | `classify(parse_backlog)` | new:Platform/Backlog | |
| BL-6 | Dependency tree: layered graph, dependencies on the left, node colour by state (ready, blocked, specified, done, parked), hover lights the chain, click shows detail; legend; only ideas with a recorded idea dependency drawn | chart | `classify` layers | new:Platform/Backlog | Needs a keyboard-reachable list alternative. |
| BL-7 | Idea drawer: id, area, title, Status (raw), Added, Slice, Depends on (links), What, Why, Rigour notes, Open questions; "add to selection" | item-page | `parse_backlog` fields | new:Platform/Backlog | |
| BL-8 | Selection tray: selected ideas with detail links, what each still needs first, "Copy brief" (text for an orchestrator), "Clear" | export | client | new:Platform/Backlog | The brief text contains project rules; regenerate from CLAUDE.md-independent static text. |
| BL-9 | Source path and build time; message "backlog document not found, set FACTORY_BACKLOG" | text | `backlog_path()`, `backlog_digest()` | new:Platform/Backlog | Worktree reads the main checkout's file. |

## 28. Capabilities / catalog (`catalog`, main hub) — prefix CG

Builder: `site_catalog_page.render_catalog` (`site_catalog.build_catalog`: tools from the built MCP server, skills from the skills directory, the decision log). Factory-wide. Target: **Platform/Capabilities**.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| CG-1 | Summary table: tools registered, tools listed, skills, prompts ("not derived" when absent), examples, marked, orphan tools, flags | kpi | `Catalog`, `CountCheck`, `flag_counts` | new:Platform/Capabilities | |
| CG-2 | Count check line (ok, or failed with not listed / not in source / duplicates) | text | `Catalog.count_check` | new:Platform/Capabilities | |
| CG-3 | "Not derived" notes per skipped check with reason | text | `Catalog.skipped` | new:Platform/Capabilities | Absent results are not zeros. |
| CG-4 | Stage map: one button per lifecycle stage (Frame, Gather, Screen, Acquire and convert, Extract and mine, Understand, Develop, Write and report, Maintain, Cross-cutting) with skills and tools counts and flag marker; search box over tools and skills; panel opens the stage's skills and tools | chart | `stage_summary`, `LIFECYCLE` | new:Platform/Capabilities | |
| CG-5 | Per stage section: stage label and what it covers; skill cards (name, description, stage chips, steps as numbered list naming tools); tool entries (name, description, params, collapsible input schema JSON, skills naming it, also used in, marker, access row) | item-page | `SkillInfo`, `ToolInfo` | new:Platform/Capabilities | |
| CG-6 | "Unassigned": orphan tools (no skill names them, no marker) and skills with no valid stage | table | `Catalog` | new:Platform/Capabilities | |
| CG-7 | "Marked tools": tool, marker kind, why (plus accepted access mismatch), access row, skills naming it | table | `MARKERS`, `MARKER_KINDS`, `ACCEPTED_MISMATCH` | new:Platform/Capabilities | |
| CG-8 | "Flags": code (skill-unknown-tool, skill-unknown-arg, skill-skill-clash, skill-decision-missing, skill-decision-not-decided, orphan-tool, orphan-skill, skill-no-stage, skill-names-human-only, marker-access-mismatch, marker-unknown-tool), file:line, finding (and second sentence of a clash); note that the platform rules on none | table | `Catalog.flags` | new:Platform/Capabilities | Mechanical findings for the researcher. |
| CG-9 | Footer: built time, code version, decisions sha, skill hashes | text | `code_hash`, `decisions_sha` | new:Platform/Capabilities | |

## 29. Server routes and shell behaviours — prefix SV

Source: `site_server.py` (`_ROUTES`, `hub_act`, read routes), `dashboard_server.py`, `site_auth.py`. Every act needs a v2 route behind the same allow-list and token scope, recording the local human as actor (the service refuses any other actor). v2 today has one act route (`/ui/act/snowball-add`) and uses `/api/export/works`, `/api/mine/work`, `/api/mine/layer`, `/api/layers/move`, `/api/layers` from the old server.

| # | element | kind | data source | v2 target | notes |
|---|---|---|---|---|---|
| SV-1 | `GET /p/<slug>/api/status`: building flag, queued products, per-product progress and text, code version, last error, products with build time and staleness | poll | `Rebuilder.try_statuses`, `build_progress` | existing:shell (stale watch, 503 retry) | Per-product list not needed in v2; keep `building` and code version for HM-3. |
| SV-2 | `GET /api/activity` | poll | `activity_cached` | new:Pipeline/Activity | AT-section. |
| SV-3 | `GET /api/queue/runs` | poll | `run_status`, `pipeline_status` | new:Pipeline/Work queue | QU-6. |
| SV-4 | `GET /api/queue/interrupted` | poll | `interrupted_payload` + `last_resume` | new:Pipeline/Work queue | QU-7. Shell may show a global "interrupted" badge. |
| SV-5 | `GET /api/layers` (layer ids and each work's layer) | poll | `layers_payload` | existing:Corpus (acts) | Used by EX-25, EX-26. |
| SV-6 | `GET /api/feed/runner` | poll | `FeedRunner` | new:Living/Feed river (run bar) | FD-3. |
| SV-7 | `GET /api/projects` (slug, title, events, stale, built, hub_ready, building) | poll | `site_portal` | new:shell project switcher (needs ruling) | HM-14. |
| SV-8 | `POST /api/inbox/add` (project, value, note) | act | `inbox_add` | new:Living (add a link) | **ACT**. Reuse for Graph snowball-add semantic (same event `inbox.link_added`). |
| SV-9 | `POST /api/feed/run`, `/api/feed/refetch` (hub token) | act | `start_feed_run` | new:Living/Feed river | **ACT** (FD-3). |
| SV-10 | `POST /api/feed/react`, `/api/feed/add` | act | `feed_react`, `feed_add` | new:Living/Feed river | **ACT** (FD-9). |
| SV-11 | `POST /api/feed/configure` | act | `feed_configure` | new:Living/Feed settings | **ACT** (FD-13). |
| SV-12 | `POST /api/watch/configure`, `/api/living/snapshot` | act | `watch_configure`, `living_snapshot` | new:Living/Weekly watch | **ACT** (UP-9, UP-10). |
| SV-13 | `POST /api/queue/process`, `/api/queue/resume` | act | `queue_process`, `queue_resume` | new:Pipeline/Work queue | **ACT** (QU-4 to QU-9). |
| SV-14 | `POST /api/mine/work`, `/api/mine/layer`, `/api/layers/move` | act | `mine_work`, `mine_layer`, `move_layer` | existing:Corpus (acts) | **ACT** present (EX-25, EX-26). |
| SV-15 | `POST /api/export/works` (zip, max 200, PDFs with confirm) | export | `export_works_zip` | existing:Corpus/export | Present (EX-16). A larger "export the filtered list as CSV" is new (FL-6). |
| SV-16 | `POST /api/projects/create` | act | `site_create.create_project` | new:shell project switcher (needs ruling) | **ACT** (HM-15). |
| SV-17 | `POST` snowball add (`UI_SNOWBALL_ROUTE`) | act | `ui_snowball_add` | existing:Graph/Foundations | Present. |
| SV-18 | Dashboard server: `GET /api/state`, `/api/progress`, `/api/screening` (loopback only) | poll | `dashboard_server` | new:Pipeline (Activity, Control room) | DB-section. |
| SV-19 | "Updating" stand-in page while a product builds: progress text (percent, steps, time left, waiting for n other pages), reload every 2 s; failed build shows the error | poll | `progress_text`, `UPDATING_REFRESH` | existing:shell (503 + Retry-After note) | v2 covers the wait; build progress text is **GAP** only if payload builds stay slow. |
| SV-20 | Theme picker (eight themes, remembered), dark/light | filter | `site_theme(s)` | existing:shell theme picker and Kit | |
| SV-21 | Write gating: buttons disabled unless served with the token (`<meta factory-token>`), acts refused for non-human actors | text | `site_auth` | existing:shell (`HUB.served`) | Keep the pattern for every new act. |
| SV-22 | `GET /p/<slug>/<product>/...` product files (e.g. `doc/<slug>.html`, `work/<slug>.html`, `ops/...`, `files/...`) | link | `_lazy_item`, `_product_gate` | new: item routes for Sources and Costs and runs | Item pages need a lazy-render route in the v2 server; no symlinks (security and portability). |

## 30. Summary: counts per target page

Total elements inventoried: **347** (28 product sections plus the routes and shell section). Counts are rows that name the page as a target; a row with two targets counts under both. `existing` = already in v2 (checked against the code on 2026-11-18); `new` = a new section on an approved page, or a new section added to an existing v2 page.

| target page | existing rows | new rows | rows by first target |
|---|---|---|---|
| Overview | 6 | 0 | 6 |
| Flow | 18 | 8 | 25 |
| Corpus | 37 | 0 | 37 |
| Lenses | 1 | 4 | 5 |
| Explore | 1 | 0 | 1 |
| Graph | 2 | 0 | 2 |
| Miners | 30 | 3 | 31 |
| Data | 0 | 0 | 0 |
| Findings | 1 | 0 | 1 |
| Living | 3 | 31 | 34 |
| Kit | 0 | 0 | 0 |
| Pipeline | 0 | 37 | 36 |
| Sources | 0 | 48 | 45 |
| Method | 0 | 44 | 43 |
| Costs and runs | 0 | 15 | 15 |
| Write and export | 0 | 21 | 21 |
| Platform | 0 | 20 | 19 |
| shell | 11 | 5 | 16 |
| drop? | | | 7 |

Reading the table. New pages carry most of the work (Sources, Method, Pipeline, Living, Write and export, Platform, Costs and runs). Existing pages that need additions: Flow (screening checks, by-source table, CSV, criteria statements), Miners (units, versions, use, disagreements), Corpus (original-file and inspector links), Overview (production line), Lenses (stage and result grids, citation rate), Living (feed status, cards, acts). Data, Findings, Kit and most of Explore and Lenses have no old counterpart: they are v2-only.

## 31. `drop?` items (researcher decides)

| ID | element | reason |
|---|---|---|
| DB-29 | Tab Extraction (older claim-row pack): tiles units/papers/rows, units by state, agreement (dual works, rows al | Tab states itself that it mostly stays empty because miners do extraction. Researcher to decide; if kept: new:Method/Protocol and decisions or Miners. |
| DB-37 | Static export (`factory dashboard export` writes one HTML with the state embedded) | The v2 hub is served; a snapshot export is a CLI feature, not a page. Researcher to confirm. |
| HM-7 | Planned modules (pilot scripts, offline) shown dimmed with script name | Placeholder for pilot scripts that no longer exist as products; researcher to confirm. |
| HM-12 | Link "New hub" (to `ui/`) in the top bar | Disappears at cut-over. |
| HM-18 | Portal note: projects are found by scanning the root; `registry.json` gives titles or hides | Admin note. |
| SE-12 | Merge revert (CLI `dedup revert`) | Old page has no act; v2 keeps it read-only. State only. |
| FD-1 | Pointer product page "Daily updates" with link to the hub page | Redundant once Living holds the feed. |

## 32. Elements placed in a section that needs a ruling (no approved page)

Protocol, decisions, PRESS and probes (DB-7 to DB-19) have no approved page; the proposed home is a **Method/Protocol and decisions** section. The project portal, project creation and the cross-project feed (HM-14 to HM-17, FD-4, SV-7, SV-16) need a shell-level project switcher. The layer replay (LY-3) needs a home (Flow/Replay or Method). AC-9 is listed because declaring a deviation is a human act that today is a copied command; making it a button is a separate ruling.

| ID | element | proposed target |
|---|---|---|
| DB-7 | Tab Protocol: header line (protocol id, status, PRESS state, number of amendments) | new:Method/Protocol and decisions (needs ruling) |
| DB-8 | Protocol section chips (question, criteria, sources, screening, extraction, snowball + any `other:`  | new:Method/Protocol and decisions (needs ruling) |
| DB-9 | Section content: Question (primary question, objectives, slots table Slot/Value/Open, sub-questions, | new:Method/Protocol and decisions (needs ruling) |
| DB-10 | Section content: Criteria table (Id, Parent, Applies at, Statement, Rule) | new:Method/Protocol and decisions (needs ruling) |
| DB-11 | Section content: Sources (name, excluded flag, why), Queries (source/kind, text, filters), Limits (f | new:Method/Protocol and decisions (needs ruling); queries also new:Sources/Search and dedup |
| DB-12 | Section content: Screening spec, Full-text screening spec, Extraction schema, Snowball plan (key-val | new:Method/Protocol and decisions (needs ruling) |
| DB-13 | "Decisions behind this section": the decision cards of the section | new:Method/Protocol and decisions (needs ruling) |
| DB-14 | Tab Decisions: filters level, status (validated, rejected, added, proposed, open, selected, supersed | new:Method/Protocol and decisions (needs ruling) |
| DB-15 | Decision card header: subject, level, short id, suggested time, state badge | new:Method/Protocol and decisions (needs ruling) |
| DB-16 | Decision card body: explanation; "Supersedes"/"Superseded by" jump links; items (status badge, item  | new:Method/Protocol and decisions (needs ruling) |
| DB-17 | Open-state: expanded cards remembered across redraw; `jump(id)` opens a card | new:Method/Protocol and decisions (needs ruling) |
| DB-18 | Tab PRESS: list of reviews (id, protocol id, findings count, confirmed or not); table #/Severity/Ele | new:Method/Protocol and decisions (needs ruling) |
| DB-19 | Tab Probes: rounds (round, probe id, queries count); table Source/Reported/Dev retrieved of tested/N | new:Method/Protocol and decisions (needs ruling) |
| HM-14 | Portal page (`/`): one card per project (title, slug, events, pages built, state: up to date / n to  | new:shell project switcher (needs ruling) |
| HM-15 | Portal: "New project" form (slug, title, profile exploratory/pilot/systematic) | new:shell project switcher (needs ruling) |
| LY-3 | Replay control: Replay button, range slider, date; steps = one per day of layer moves (cap 120, earl | new:Flow/Replay (layer replay) or new:Method (needs ruling) |
| FD-4 | Project tabs (one per project) | new:shell project switcher (needs ruling) |
| SV-7 | `GET /api/projects` (slug, title, events, stale, built, hub_ready, building) | new:shell project switcher (needs ruling) |
| SV-16 | `POST /api/projects/create` | new:shell project switcher (needs ruling) |

## 33. Gaps in existing v2 pages

An `existing:` mapping that loses information, or a section that must be added to an existing v2 page. Each line is a row whose note says GAP; fixing them is part of the port's acceptance.

### Overview (3)

- **HM-4** Production line: 7 stations with live counts that open their product: SEARCH ide: GAP: `hub_payloads.pipeline_strip` has 5 steps from PRISMA only (identified, screened, sought, assessed, included). Convert, mine, synthesize and report stations are missing.
- **LY-1** Note: layers are the project's triage (core, benchmark, applied, adjacent, backg: The "not calibrated" warning should be stated in the layer facet's ⓘ. GAP if absent.
- **CT-3** "Most cited by corpus works (top 50)": work (link), year, cited by, of which sel: GAP: Overview shows 10 rows without year or OpenAlex count; `self_cited` is in the payload but not drawn; no top-50 table. Corpus sort "Most cited here" lists all.

### Flow (16)

- **DB-22** Tab Screening: ranking key-values (ranking id, model id, weights hash, works ran: GAP: `hub_screening` payload has no ranking id/model/weights hash.
- **DB-23** Screening: passes table A and B (Queued, Decided, Remaining); tiles records left: GAP: Flow shows the curve and the stop point but not the queued/decided/remaining table. Stale count is used inside the curve only.
- **DB-24** Screening: Stop rules table (rule with below-score, run progress, stopped or run: Partial: stop point and `stop_rule` text shown; per-rule run progress and "not screened" count are GAP.
- **DB-25** Screening: Calibration key-values (drawn, labelled, required, passed): GAP: not in v2.
- **DB-26** Screening: Full-text passes table: GAP.
- **DB-27** Screening: "Full text: cannot assess, to resolve" (work, pass A, pass B verdict/: GAP: nothing in v2 lists the cannot-assess works. Blocks nothing; promoted until resolved.
- **DB-28** Screening: Checks (calibration/audit draws: kind, name, draw id, labelled of dra: GAP.
- **RS-4** Note: "n protocol deviations recorded" and that the review stops TA screening by: Deviation count is GAP in v2.
- **LY-3** Replay control: Replay button, range slider, date; steps = one per day of layer : GAP: no v2 replay of layer moves. Flow/Replay animates record fates, not layers.
- **PR-5** Criteria table: criterion id, what it excludes (statement), excluded at title/ab: GAP: "kept as background" counts per criterion (IDEA-47) and the criterion statement table are not in `hub_screening.reasons_wall`/Flow.
- **FL-3** "PRISMA steps by source" table: rows = steps (works and absorbed duplicate rows,: GAP: the cross-tab step by source group. v2 has source nodes in the Sankey and per-node record lists, but not the matrix with every criterion/reason row by source.
- **FL-4** Records list: columns Title, Year, Source group, Sources (list), Step reached, O: GAP: Source group and Sources columns, Step reached as its own column.
- **FL-5** Filters: text (title, id, source), Source group select, Step select, Outcome sel: GAP: filtering by source group and step as separate facets (source group lives in `record.source`).
- **FL-6** Download CSV of the filtered list (work_id, title, year, source_group, sources, : GAP: no CSV. A CSV of the selection is also wanted by Write and export.
- **FL-8** Trail panel per record: title, id, year, source group and sources; "Step reached: GAP: absorbed-duplicates and duplicate-of links, sources list, document/primary ids. Paths exist only for records of the review in the static copy.
- **FL-9** "PRISMA identification (from the PRISMA flow)": rows identified, database per so: The explanatory note about why columns close only in the total is GAP (information).

### Corpus (5)

- **EX-12** Chronology view: month columns (newest left), card per paper (date, title, techn: Document link in cards: GAP (EX-30).
- **EX-18** Detail: links Open PDF/HTML (on disk) and DOI/arXiv: GAP: no link to the original file on disk (`link_documents`); v2 says "full text on file (kind)" only. Needed also for the conversion inspector (EX-30).
- **EX-27** Detail: "What you can do": commands `document read <id>`, `trace <id>` with Copy: GAP: the inspector link is missing; see CI-section target new:Sources/Conversion item page.
- **LY-5** Per-layer lists: table work (link) and year, with badge "moved by the researcher: The list is a Corpus filter. The "moved" badge is in the drawer, not in list rows (minor GAP).
- **CT-1** Head text: counts come from n works whose reference list was extracted (m entrie: GAP: entries and resolved-links totals as one sentence.

### Lenses (3)

- **RS-11** Results by stage and approach (design approach miner): heat grid of own-system r: GAP: only the per-paper rows (12 per paper) in the drawer exist.
- **RS-12** Bars for system_role, evidence_grade, value_kind over the result rows: GAP.
- **CT-4** "Citations per year since publication" (top 50): work, year, per year (as-of-yea: GAP: no per-year rate anywhere in v2.

### Explore (1)

- **LY-2** Concentric rings: one dot per work on its layer ring (outer halo = unlayered), m: GAP: background and off-topic are not separate rings, and a work moved by the researcher is not marked.

### Graph (1)

- **CT-5** "Cited by the corpus, not in it (snowball candidates, top 50)": cited item (link: GAP: identifier column and links to DOI/arXiv; year from `outside_info` is in the payload but not drawn. Also: candidates here come from `citations.py`, Foundations from the citation graph (resolved links only); check both give the same top rows.

### Miners (15)

- **DB-31** Tab Miners: column glossary (Units, Closed, Open, Rows, Stale), listed-miners ta: Differences in MN-section: units/closed/open/stale GAP.
- **DB-32** Miner card: rationale, "How it reads", Fields table (Field, Group, Kind, Require: Versions table, digest, second-pass share, audit share, evidence-admission flag and commands are GAP (MN-6 to MN-14).
- **MN-2** Column glossary table (Units, Closed, Open, Rows, Stale, Second pass, Agreement : Definitions of Units/Closed/Open/Stale are GAP because those counts are not shown.
- **MN-3** Listed miners table: miner, version, first sentence of rationale, units, closed,: GAP: units/closed/open/stale (`mine_status`), second-pass share (`use.dual_extract_sample`), version. A compact table view next to the cards would close it.
- **MN-4** Miner page header: version, digest, rationale: GAP: digest not shown.
- **MN-5** Status table (units, closed, open, rows, stale, agreement fairer, agreement plat: GAP: units/closed/open/stale. Rows count present as works read.
- **MN-6** "How it reads": works read (population), paragraph kinds (`selector.elements`), : GAP: paragraph kinds, heading patterns, max works, procedure/skill; the payload carries `row_key` but `miners.js` does not show it.
- **MN-9** "Quality and use": passes, second-pass sample share, audit fraction and minimum,: GAP: second-pass share, audit fraction/minimum, evidence admission, imports, exploratory flag, quote rule. `regime.calibration_size`, `recall_min`, `field_agreement_min` present.
- **MN-12** Versions table: version, digest, listed in the protocol, proposed by: GAP: no version table; only the shown version.
- **MN-13** "What you can do": `mine status`, `mine agreement <name>`, `mine resolve --help`: GAP: no commands.
- **MN-14** Link from a field to the per-field disagreement list (`agreement/<miner>.html#<f: GAP; target missing.
- **AG-4** Summary table per miner: works in both passes, rows A / rows B / matched, fairer: GAP: rows A/B counts and the disagreements count.
- **AG-7** Per-field table: field, agreed/compared, rate, disagreements: GAP: disagreements count per field.
- **AG-8** Disagreement blocks per field (sorted by count): description, allowed values, th: GAP, largest on this page: `hub_mining` returns no disagreement pairs. v2 Flow/Screening has the equivalent for screening only (`hub_screening.PairDisagreement`). New payload `mining_disagreements(miner, field)`, paged.
- **AG-11** Per-miner one-sided counts (`one_sided`): Present in payload; GAP if not drawn.

### Living (3)

- **FD-6** Status line per project: "not configured" with link to Settings; or last fetch d: GAP: nothing in Living shows the window, reference set, held entries, categories or due state.
- **FD-8** Paper card (shown items in shown order): rank, score (3 decimals), badges (explo: GAP: v2 day detail shows title, rank, score, reaction, sent only; no abstract, authors, nearest core work, arXiv links, date.
- **FD-10** "Further" cards: ranked entries outside the shown set, hidden, "Show next 30" bu: GAP: v2 payload has no further/ranked-beyond list.

## 34. New payload services implied (data sources for the new elements)

Each wraps an existing service; none re-derives a number. All are pure functions of a `Project`, cached by event-type fingerprint like the current `hub_*` payloads.

| new module (proposed) | page | wraps |
|---|---|---|
| `hub_pipeline.py` | Pipeline (Control room, Work queue, Activity) | `site_hub_page._line_numbers`, `work_queue.queue`, `pipeline.stages/paper_progress`, `resume.interrupted`, `activity.activity_cached`, `dashboard.screening_live`, `site_progress.progress_list`; acts `queue_process`, `queue_resume` |
| `hub_sources.py` | Sources (Search and dedup, Acquisition, Conversion, Documents) | `site_search.build_payload`, `fulltext_status`, `list_deviations`, `conversion_coverage`, `site_inspector.documents/gaps`, `study_files.list_files/file_status`; lazy item routes for `doc/`, `work/`, `files/` |
| `hub_method.py` | Method (Lifecycle, Steps, Taxonomy, Protocol and decisions) | `site_lifecycle.lifecycle_data/own_stage_sequences`, `site_steps.step_rows/steps_view`, `taxonomies.*`, `taxonomy.diff`, `dashboard._protocol/_decisions/_press/_probes` |
| `hub_costs.py` | Costs and runs | `run_costs.cost_report/token_growth/runs_with_logs`, `budget_status`, `site_runs.run_groups`, events per model |
| `hub_write.py` | Write and export | `pages.list_pages/read_page`, `exports.export_bibliography/export_prisma_svg`, `site_wiki.build_wiki` (on demand), `site_synthesis._scope_table` |
| `hub_platform.py` | Platform | `site_catalog.build_catalog`, `site_backlog.parse_backlog/classify/area_notes` |
| `hub_living.py` (extend) | Living | `updates.updates_view`, `feed_status`, `feed_list`, `feed_ranked_page`, `feed_categories.propose_categories`, `site_hub_feed.collect`; acts `feed_react`, `feed_add`, `feed_configure`, `watch_configure`, `living_snapshot`, `inbox_add`, feed run and refetch |
| `hub_mining.py` (extend) | Miners | `mine_status` (units, closed, open, stale), `miner_detail` (use, versions, selector, procedure), `site_agreement.measure(...).disagreements` |
| `hub_screening.py` (extend) | Flow/Screening | `screening_stops`, `dashboard._screening` (passes, calibration, cannot-assess, checks, ranking id) |
| `hub_payloads.py` (extend) | Flow, Overview, Lenses | `flow_ledger` by source group and step (`site_flow.table_spec`), `pipeline_strip` stations, `citations.citation_report` (rate per year, external count), stage-by-mode and result-grid functions in `hub_lenses.py` |


## 35. Port status

Step 9 (gap fixes: Overview and Flow), branch `hub-port-gaps1`. Built, not yet run or reviewed.

### Overview

- HM-4 — done (overview.js: "From papers to findings" row; `hub_payloads.line_stations`). Hrefs of the four stations (`sources.html`, `miners.html`, `write.html`) assume the new page file names.
- LY-1 — done for Overview (composition ⓘ and an ⓘ on the layer group state that the layer pass is not calibrated); open for the Corpus facet ⓘ (corpus.js, not in this step).
- CT-3 — done (overview.js: Most cited, "Show all 50" table with year, cited here, same-author share, stored OpenAlex count; `most_cited` carries 50 rows).

### Flow

- DB-22 — done (flow.js:Screening › Screening status, ranking key-values; `hub_screening.screening_panel`)
- DB-23 — done (flow.js:Screening › Screening status, passes table, records left, stale decisions)
- DB-24 — done (flow.js:Screening › Stop rules table with run progress, state, not screened)
- DB-25 — done (flow.js:Screening › Calibration and checks)
- DB-26 — done (flow.js:Screening › full-text passes table, shown when the protocol has a full-text plan)
- DB-27 — done (flow.js:Screening › Full text to resolve; the link to the conversion inspector waits for the Sources page, the read command is shown)
- DB-28 — done (flow.js:Screening › Calibration and checks, bands in a details list)
- RS-4 — done (flow.js:Screening › Stop rules note, deviation count from `list_deviations`)
- LY-3 — done (flow.js:Replay › Layer moves; `hub_payloads.layer_replay_payload`)
- PR-5 — done (flow.js:Screening › Criteria; statements, counts and background counts)
- FL-3 — done (flow.js:Where the records went › Steps by source; `hub_payloads.by_source_table`)
- FL-4 — done (flow.js: record list columns Source group, Sources, Step reached)
- FL-5 — done (flow.js: Source group and Step reached facets)
- FL-6 — done (flow.js: Download CSV of the filtered list, built client-side)
- FL-8 — open (Paths now shows source group, sources, step reached, duplicate of and merged duplicates; the document and primary ids of each step are not in the journeys payload)
- FL-9 — done (identification note in the ⓘ of the identified, source and duplicate nodes and of Steps by source)
### Pipeline (`pipeline.js`, `hub_pipeline.py`)

Views: Control room (status strip, production line, events per day, where to start, page cards), Work queue (run line, Process, paper by stage grid, pending, Interrupted with Preview and Resume), Activity (open passes, held tasks, long operations, worker traces, screening live).

- HM-1 — done (shell rail; the page cards list every page)
- HM-2 — done (shell Ctrl-K)
- HM-3 — done (Control room status strip: events, newest event id, code version, build time; "Some work was interrupted" in the lead). The "n modules need a rebuild" count is open (the shell stale watch covers payloads)
- HM-4 — done (Control room production line: seven stations with counts, share kept and waiting units)
- HM-5 — done (Control room events per day, last 21 days with events)
- HM-6 — done (Control room page cards with each page's lead); state tag, build time and error text per page are open (no per-payload state outside the shell stale watch)
- HM-7 — dropped (P2)
- HM-8 — open (the shell stale watch polls per payload; per-page progress percent is not shown)
- HM-9 — done (Control room "Where to start" from the human queue, and the page cards)
- HM-10 — done (information panels on the line and the strip)
- HM-11 — open (old-hub commands belong to Platform; not copied)
- HM-12 — dropped (P2)
- HM-13 — done (shell rail)
- HM-14 — done (shell project switcher)
- HM-15 — done (shell project switcher)
- HM-16 — open (Living, add a link)
- HM-17 — open (Living, feed river)
- HM-18 — dropped (P2)
- AT-1 — done (Activity live line; polls GET /api/activity every 10 s while the tab is open and visible; static build says "Snapshot as of")
- AT-2 — done (Activity "Tasks held now", stale in amber)
- AT-3 — done (Activity "Open passes" as progress bars with held share, rate and time left labelled estimated)
- AT-4 — done (Activity dormant passes, folded)
- AT-5 — done (Activity "Long operations" as bars with elapsed, rate and time left)
- AT-6 — done (Activity "Worker traces")
- AT-7 — done (empty states)
- AT-8 — done (Activity "Screening live": totals, sessions, stop rules, latest decisions) as of the build only; open: live refresh needs `GET /api/screening` on the hub server (requested shared change)
- AT-9 — done (the stale minutes are in the held-tasks panel and its row text)
- AT-10 — done (every text is escaped)
- QU-1 — done (Work queue "Papers added": entry, title to the drawer or arXiv, stage badge with stopped, detail, added time)
- QU-2 — done (the same table has one column per applicable stage, plus a per-stage bar and filters by state, stage and text)
- QU-3 — done (Work queue "Pending work")
- QU-4 — done (Process all, inline confirm, unit cap, structured refusal shown; disabled when not served or a run is open)
- QU-5 — done (per-stage Process now with pending count and model)
- QU-6 — done (run line, polled 5 s while busy, 20 s idle, paused while hidden)
- QU-7 — done (Interrupted panel with usage-limit reset and "(estimated)"; polled every 15 s)
- QU-8 — done (Preview, dry run, plan lines)
- QU-9 — done (Resume with inline confirm and optional unit cap; disabled when clean, busy or not served; last resume outcome shown)
- QU-10 — done (note when the hub is not served)
- QU-11 — done (run line and Process cards; last run and open flags)
- DB-1 — done (status strip)
- DB-2 — done (tab links are the rail; hash `#tab=`)
- DB-5 — done (Activity long operations)
- DB-6 — done as snapshot (see AT-8)
- DB-33 — open (per-page freshness not shown, see HM-6)
- DB-35 — done (Work queue)
- FD-16 — open (cross-link from Living to Pipeline)
- SV-2, SV-3, SV-4, SV-13 — done (the routes the page uses)
- SV-18 — done for `/api/activity` and snapshot screening; `/api/progress` is covered by operations
### Protocol page (`protocol`)

DB-7 — done (Protocol: header stats)
DB-8 — done (Protocol › Plan: section chips with decision counts)
DB-9 — done (Protocol › Plan › Question)
DB-10 — done (Protocol › Plan › Criteria, with excluded counts per stage from the reasons wall)
DB-11 — done (Protocol › Plan › Sources: sources, queries, limits)
DB-12 — done (Protocol › Plan › Screening, Extraction, Snowballing)
DB-13 — done (Protocol › Plan: Decisions behind this section)
DB-14 — done (Protocol › Decisions: level, status, search, count, grouped)
DB-15 — done (Protocol › Decisions: card header)
DB-16 — done (Protocol › Decisions: card body, jump links, provenance)
DB-17 — done (open cards kept across redraw; hash `#dec=<id>`; map dots jump)
DB-18 — done (Protocol › Reviews)
DB-19 — done (Protocol › Probes)
DB-3 — open (ⓘ panels carry the methods text; the per-tab help paragraph is not ported verbatim)
Deviations (RS-4, AC-11 share) — done (Protocol › Versions › Deviations)
### Sources (branch hub-port-sources; tests written, not run)

- SE-1 — done (Sources/Search and dedup, error line and tiles)
- SE-2 — done (query by query cards)
- SE-3 — done (yield bars and card counts, gap in red)
- SE-4 — done (runs table in each query card)
- SE-5 — done (skipped records per query, capped at 1000 with the full count)
- SE-6 — done (rule bars, active against reverted)
- SE-7 — done (merge table with reverted time and reason)
- SE-8 — done (search, rule, status, clear, show more by 300; hash state)
- SE-9 — done (Merged after screening)
- SE-10 — done (Records by source, identification split)
- SE-11 — done (info panel of Searches)
- SE-12 — done (read-only: status and reason shown, no act)
- AC-1 — done (Full text subtitle computes the undeclared count)
- AC-2 — done (info panel)
- AC-3 — done (four figures)
- AC-4 — done (route table and the stacked bar)
- AC-5 — done (Not retrieved table, undeclared first)
- AC-6 — done (row detail header)
- AC-7 — done (row detail: routes tried and their meaning)
- AC-8 — done (row detail: look for a copy)
- AC-9 — done (row detail: commands and deviation template; no write)
- AC-10 — done (Declare them together)
- AC-11 — done (Deviations table)
- CV-1 — done (info panel and computed date)
- CV-2 — done (per-converter table)
- CV-3 — done (scatter with dashed low region; marks open the panel; the sortable table is the keyboard path)
- CV-4 — done (not measured line)
- CV-5 — done (filters, only-low, sort, lowest recall first)
- CI-1 — done (document panel header with scores)
- CI-2 — open (needs a served route for stored originals and Markdown; links to the classic page meanwhile)
- CI-3 — open (original pane needs `data/sources-doc-<id>.json`; page loads it when present)
- CI-4 — open (same route; the page renders it as text with bracketed anchors)
- CI-5 — open (same route supplies the lost and added lists)
- CI-6 — done (commands with Copy, from the converters on this machine)
- CI-7 — done (hash `#tab=conversion&conv=<document id>`; the classic back-links are not rewired)
- DC-1 — done (three figures)
- DC-2 — done (one table per kind, statuses, earlier versions)
- DC-3 — open (links to the classic documents page; inline Markdown needs a served route)
- DC-4 — open (same route)
- DC-5 — done (empty state)
- DC-6 — open (cache key detail, no UI)
- DB-20 — done (tiles of Searches)
- DB-21 — done (Records by source, query cards, rule bars)
- DB-30 — done (Conversion summary and documents lowest recall first)
- FL-10 — done (query yield and skipped records by reason on Sources)
- RS-4 — done (deviation count on Sources/Full text)
- PR-6 — done (next-step links at the foot of Search and dedup; the flow link)
- DB-27 — open (the cannot-assess list belongs to Flow; the document panel is deep-linkable by `conv=`)
- EX-27 — open (the Corpus link to `sources#tab=conversion&conv=<id>` is for the Corpus page)

Method page (hub-port-method):

- TX-1 — done (Method > Taxonomy, index table)
- TX-2 — done (version header, versions, rationale; open proposals in index)
- TX-3 — done (derived miner line, link to Miners)
- TX-4 — done (changes table, computed by diff)
- TX-5 — done (dimension table)
- TX-6 — done (category cards with counts, cues, examples)
- TX-7 — done (category ids as anchors, hash cat=)
- TX-8 — done (collapsed earlier list)
- TX-9 — done (covered by counts in Taxonomy and existing Lenses/Miners)
- TX-10 — done (taxonomy info panel)
- TX-11 — done (link to Miners codebook)
- LC-1 — done (flow info panel and visible layout warning)
- LC-2 — done (stage coverage arc diagram)
- LC-3 — done (layer chips)
- LC-4 — done (mode chips)
- LC-5 — done (selected list, drawer links)
- LC-6 — done (hash layer, mode, stage)
- LC-7 — done (matrix with Steps links)
- LC-8 — done (per-paper sequences, calibration warning)
- LC-9 — done (empty state)
- LC-10 — done (stage sequences: name map, transition diagram, orders, loops, entry/exit)
- LC-11 — done (links; next-step text left out as stale)
- RS-8 — done (Method > Lifecycle, stage by mode)
- RS-9 — done (stages per paper bars)
- RS-10 — done (stage by technique)
- ST-1 — done (exploratory banner)
- ST-2 — done (count strip)
- ST-3 — done (stage selection in strip and All stages)
- ST-4 — done (actor, check, limits, search)
- ST-5 — done (per-stage sections)
- ST-6 — done (step details with quotes)
- ST-7 — done (stage anchors, hash sstage)
Costs & runs (`costs`, branch hub-port-costs):
- CO-1 — done (Costs: visible caveat line and ⓘ on the cost figure)
- CO-2 — done (Costs: KPI strip)
- CO-3 — done (Costs: Stages in detail, sortable, all 13 columns plus miner)
- CO-4 — done (ⓘ panels of each view)
- CO-5 — done (Costs: Token growth, one line chart per stage)
- CO-6 — done (Costs: empty state)
- CO-7 — done (Costs: Budgets with gauge, reported usage, Events per model labelled as not cost)
- DB-36, RS-5 (cost parts) — done (Costs: Budgets, Events per model)
- RN-1 — done (Runs: KPI strip)
- RN-2 — done (Runs: group table with folder and status filters, unlinked first)
- RN-3 — open (file paths are listed but not links: needs a read-only `ops/` file route in the server)
- RN-4 — done (Runs: empty state)
- RN-5 — done (Runs: ⓘ warning)
- RN-6 — done (Runs: linked run id opens the run in Costs, highlighted)
### Write & export (`hub_write.py`, `write.js`)

- SY-1 — done (Synthesis, header note and ⓘ)
- SY-2 — done (Synthesis, page cards with model-written, state and flag badges)
- SY-3 — done (Synthesis, reading view; citations open the drawer)
- SY-4 — done (Synthesis, Scopes table; links to Corpus filter)
- SY-5 — done (Synthesis, rf-synthesize note under Scopes)
- SY-6 — done (Synthesis, empty state)
- BB-1 — done (Bibliography, header and ⓘ)
- BB-2 — done (Bibliography, table plus a BibTeX toggle on one tab, same entries)
- BB-3 — done (Bibliography, sortable and filterable table, "n of N papers", year histogram)
- BB-4 — done (Bibliography, Copy BibTeX, Download .bib as a Blob, Show BibTeX)
- BB-5 — done (one export call feeds table and text)
- PR-3 — done (PRISMA diagram, inline SVG and Download prisma.svg as a Blob)
- PR-1, PR-2, PR-4 to PR-7 — not mine (existing:Flow)
- WK-1 — done (Wiki vault, path and copy button; the vault is built by the classic product)
- WK-2 — open (needs the zip route under Requested shared changes; link to the classic wiki meanwhile)
- WK-3 to WK-6 — open (vault contents are built by `site_wiki.build_wiki`; described in the ⓘ, not browsable here)
- WK-7 — open (banner lives in the classic vault build; the Synthesis reading view labels pages model-written)
- WK-8 — open (symlinks; decide with the zip route)
- WK-9 — done (Wiki vault, paper count from the corpus payload)
- RS-1 to RS-13 — no row targets Write; none taken
Platform page (`platform`), code written, not run:

- HM-11 — done (Capabilities, "Commands that build and serve the hubs"; lists the v2 and classic commands, not copied)
- BL-1 — done (Backlog, header ⓘ and sub line; selection kept in the page only)
- BL-2 — done (Backlog, Board / Dependency tree switch, hash `view`)
- BL-3 — done (Backlog, filter box, area chips, slice select, counter)
- BL-4 — done (Backlog, area note under the chips)
- BL-5 — done (Backlog, five state columns with help lines and cards; plus a per-area stacked count bar)
- BL-6 — done (Backlog, layered dependency tree, chain lights on selection, list alternative)
- BL-7 — done (Backlog, idea detail panel beside the board, not a drawer; the shared drawer shows papers)
- BL-8 — done (Backlog, selection tray, Copy brief with static text, Clear)
- BL-9 — done (Backlog, footer source path and digest; message when the file is absent; build time is the shell's as-of stamp)
- CG-1 — done (Capabilities, summary cards)
- CG-2 — done (Capabilities, count check line)
- CG-3 — done (Capabilities, "Not derived" lines)
- CG-4 — done (Capabilities, stage by kind matrix with search; click opens the stage panel)
- CG-5 — done (Capabilities, stage panel: skill cards with steps, tool entries with schema)
- CG-6 — done (Capabilities, Unassigned)
- CG-7 — done (Capabilities, Marked tools)
- CG-8 — done (Capabilities, Flags)
- CG-9 — open (code hash, decisions sha and skill hashes shown; build time is not repeated, the shell stamps it)
- HM-13 — open (rail entries belong to shell.js)
### Living (hub-port-living)

- UP-1 — done (Updates, KPI cards)
- UP-2 — done (Updates, additions table; title opens the drawer when the work is in the shell)
- UP-3 — done (Updates, route chips, hash `route`)
- UP-4 — done (Updates, empty text)
- UP-5 — done (add a link box, `/api/inbox/add`, hub token)
- UP-6 — done (Updates, growth line chart)
- UP-7 — done (Updates, update-flow table)
- UP-8 — done (Updates, weekly watch table)
- UP-9 — done (Updates, watch settings act)
- UP-10 — done (Updates, close week act)
- UP-11 — done (Updates, watch note)
- UP-12 — done (acts disabled unless `HUB.served`)
- HM-16 — done (add a link box on Feed and Updates)
- HM-17 — done (Feed cards with Like, Dislike, Add)
- FD-1 — dropped (pointer page)
- FD-2 — done (Feed lead and ⓘ)
- FD-3 — done (Feed run bar, bounded runner poll)
- FD-4 — done (covered by the shell project switcher)
- FD-5 — done (Feed layout toggle and order select)
- FD-6 — done (Feed status cards)
- FD-7 — done (Feed lead and status cards)
- FD-8 — done (Feed cards with abstract, authors, nearest core work, links, date)
- FD-9 — done (card acts with inline confirm)
- FD-10 — done (ranked-beyond cards, Show next 30, cut note)
- FD-11 — done (Feed cards; cross-project panel not in a per-project hub)
- FD-12 — done (Feed settings table)
- FD-13 — done (category proposal and Accept act)
- FD-14 — open (Reactions 7d and Adds 7d per title not shown; reaction chart per day and category added instead)
- FD-15 — done (Horizon and Heartbeat tabs kept)
- FD-16 — done (add message and link note point to Pipeline work queue)
### Gaps in existing pages: Miners, Corpus, Lenses, Explore, Graph (branch hub-port-gaps2)

- DB-31 — done (Miners, "All miners at a glance" table and column glossary)
- DB-32 — done (Miners detail: digest, status, how it reads, quality and use, versions, commands)
- MN-2 — done (Miners, glossary table from `site_miners.COLUMNS`)
- MN-3 — done (Miners, at-a-glance table: units, closed, open, rows, stale, second pass, fairer, platform)
- MN-4 — done (Miners detail header: version and digest)
- MN-5 — done (Miners detail, Status tiles)
- MN-6 — done (Miners detail, How it reads)
- MN-9 — done (Miners detail, Quality and use)
- MN-12 — done (Miners detail, Versions table)
- MN-13 — done (Miners detail, What you can do, with Copy)
- MN-14 — done (field card links to `#m=<miner>&d=<field>`, the disagreement block)
- AG-4 — done (Miners, "Two readings, per miner" table: rows A, B, matched, disagreements)
- AG-7 — done (Two readings per-field line: disagreements and one-sided counts)
- AG-8 — done (Miners detail, Disagreements by field; lazy via `grid-<miner>`, at most 40 pairs per field, exact counts)
- AG-11 — done (one-sided labels in the per-miner table and per field)
- EX-12 — done (Corpus Chronology card links to the conversion inspector `../conversion/doc/<slug>.html`)
- EX-18 — open (inspector link done; link to the original file needs a document-file route, see report)
- EX-27 — done (Corpus detail, What you can do: inspector link)
- LY-5 — done (Corpus list rows: "moved by the researcher")
- CT-1 — done (Corpus citations ⓘ: extractions, entries, resolved, works total)
- RS-11 — done (Lenses, Results by stage: heat grid, click lists papers)
- RS-12 — done (Lenses, Results by stage: bars for system role, evidence grade, value kind)
- CT-4 — done (Lenses, Citation rate: per year, in-project count, OpenAlex count kept apart)
- LY-2 — done (Explore: seven rings; dashed halo for researcher-moved works, from the corpus payload)
- LY-1 — done (Corpus layer facet ⓘ states the layer pass is not calibrated)
- CT-5 — done (Graph, Foundations: year and identifier links; new table of cited items that are not works yet, from `citations.py`). The two lists are different populations by design (works the project holds against unresolved cited items), so their top rows are not expected to match.

### Verification of pre-existing mappings (2026-11-19)

- AG-1 — done (Miners, Two readings; miners.js, hub_mining.py METHODS)
- AG-2 — done (Miners, Two readings; miners.js, hub_mining.py METHODS)
- AG-3 — done (Miners, Two readings per miner table; miners.js)
- AG-5 — done (Miners, Two readings; miners.js, hub_mining.py METHODS)
- AG-6 — done (Miners, Two readings; miners.js, hub_mining.py METHODS)
- AG-9 — done (Miners detail, What you can do; miners.js commandsSection, hub_mining._commands)
- AG-10 — done (Miners, Two readings; miners.js, hub_mining.py METHODS)
- CT-2 — done (Corpus citation note; corpus.js citeNote)
- CT-6 — done (Overview cited-here ⓘ; hub_payloads.METHODS.cited_here defines self-citation)
- CT-7 — done (Lenses, Citation rate: external OpenAlex column beside in-project count, never merged; lenses.js, hub_lenses.py)
- DB-4 — done (cmd rows per page: miners.js commandsSection, sources.js copyCmd, overview.js click-to-copy; other pages per their port sections)
- DB-29 — dropped (ruling P2)
- DB-34 — open (Living shows fetch window, due, shown per cycle, ranking; no 'Top shown titles' table with Score, Sent, Reactions 7d, Adds 7d, cards only)
- DB-36 — done (Costs, budgets and events per model; costs.js, hub_costs.py)
- DB-37 — dropped (ruling P2)
- EX-1 — done (Corpus; corpus.js)
- EX-2 — done (Corpus; corpus.js)
- EX-3 — done (Corpus; corpus.js)
- EX-4 — done (Corpus; corpus.js)
- EX-5 — done (Corpus cited-here filter; refs_done in note, corpus.js, hub_build.py)
- EX-6 — done (Corpus; corpus.js)
- EX-7 — done (Corpus; corpus.js)
- EX-8 — done (Corpus; corpus.js)
- EX-9 — open (Corpus ⓘ lacks the sentence that other pages link here with a filter)
- EX-10 — done (Corpus List as card rows with DNA strip and technique/field/human/stage tags, checkbox per row; corpus.js)
- EX-11 — done (Corpus; corpus.js)
- EX-13 — done (Corpus; corpus.js)
- EX-14 — done (Corpus; corpus.js)
- EX-15 — done (Corpus; corpus.js)
- EX-16 — done (Corpus acts; corpus.js, site_server.py)
- EX-17 — done (Corpus detail, layer badge with layer_source/layer_miner; corpus.js)
- EX-19 — done (Corpus; corpus.js)
- EX-20 — done (Corpus; corpus.js)
- EX-21 — done (Corpus; corpus.js)
- EX-22 — done (Corpus; corpus.js)
- EX-23 — done (Corpus; corpus.js)
- EX-24 — done (Corpus detail, Results first 12 of n_design; corpus.js)
- EX-25 — done (Corpus acts; corpus.js, site_server.py)
- EX-26 — done (Corpus acts; corpus.js, site_server.py)
- EX-28 — open (Corpus detail has no evidence footnote: pass A by a model, values quoted from the converted document, second pass sample)
- EX-29 — done (shared paper drawer; shell.js)
- EX-30 — done (open= alias handled in shell.js)
- EX-31 — done (shell loading and updating state; shell.js)
- FL-1 — done (Flow ⓘ; flow.js)
- FL-2 — open (flow_payload carries `reconciles` but Flow shows no reconciled or mismatch line)
- FL-7 — done (Flow record list, Show 100 more per click; flow.js)
- LY-4 — done (Overview composition by layer; overview.js)
- LY-6 — done (Corpus 'unlayered' facet; corpus.js)
- LY-7 — done (Miners detail commands; miners.js)
- MN-1 — done (Miners; miners.js, hub_mining.py)
- MN-7 — done (Miners; miners.js, hub_mining.py)
- MN-8 — open (no kind legend: enum, quote, number, integer, citation, anchor, work_ref)
- MN-10 — done (Miners; miners.js, hub_mining.py)
- MN-11 — done (Miners; miners.js, hub_mining.py)
- PR-1 — done (Flow ⓘ; flow.js)
- PR-2 — done (Flow, Records at each step; flow.js)
- PR-4 — done (PRISMA terms in shell.js GLOSSARY, e.g. notretrieved, cap)
- PR-7 — open (flow_payload carries `reconciles` but Flow shows no reconciled or mismatch line)
- RS-1 — done (Findings and Miners ⓘ; findings.js, miners.js)
- RS-2 — done (Flow, Where the records went; flow.js)
- RS-3 — done (Flow, Where the records went; flow.js)
- RS-5 — done (Costs, events per model; costs.js)
- RS-6 — open (Overview Growth shows papers per month but bars do not open Corpus filtered by month; Corpus has no month filter)
- RS-7 — done (Miners detail value distributions; miners.js)
- RS-13 — done (Findings and Miners ⓘ; findings.js, miners.js)
- SV-1 — kept (old route, v2 uses its own `fresh?name=` poll in shell.js; /api/status stays in site_server.py)
- SV-2 — done (Pipeline; pipeline.js, site_server.py)
- SV-3 — done (Pipeline; pipeline.js, site_server.py)
- SV-4 — done (Pipeline; pipeline.js, site_server.py)
- SV-5 — done (Corpus acts; corpus.js, site_server.py)
- SV-6 — done (Living; living.js, site_server.py)
- SV-7 — done (shell project switcher; shell.js)
- SV-8 — done (Living; living.js, site_server.py)
- SV-9 — done (Living; living.js, site_server.py)
- SV-10 — done (Living; living.js, site_server.py)
- SV-11 — done (Living; living.js, site_server.py)
- SV-12 — done (Living; living.js, site_server.py)
- SV-14 — done (Corpus acts; corpus.js, site_server.py)
- SV-15 — done (Corpus acts; corpus.js, site_server.py)
- SV-16 — kept (old route; shell switcher links to portal 'New project', route in site_server.py)
- SV-17 — done (Graph, Add to snowball via /ui/act/snowball-add; graph.js)
- SV-19 — done (shell Updating note with Retry-After retry; no progress text; shell.js, hub_serve.py)
- SV-20 — done (shell theme picker, eight themes; shell.js)
- SV-21 — done (HUB.served and token; shell.js, site_server.py)
- SV-22 — done (lazy item and ops/ routes; site_server.py, hub_serve.ops_file; Sources links to classic pages stay)

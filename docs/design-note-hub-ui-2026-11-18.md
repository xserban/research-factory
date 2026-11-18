# Design note: hub interface redesign — source notes (2026-11-18)

Status: notes only. No decision, no plan. Input for the planning session that starts on "start".

## 1. Purpose

Collect what the four supplied resources say about presenting information, and map it onto the current hub, so that the redesign plan starts from stated principles and known facts rather than taste.

## 2. Sources and how far they can be trusted

| Source | What was read | Confidence |
|---|---|---|
| Ten UX books (Norman, Marsh, Hurff, Cagan, Krug, Tidwell et al., Brown, Nodder, Nunnally & Farkas, Fitzpatrick) | Legitimate sources only (no pirated PDFs): scotthurff.com (UI stack), nngroup.com heuristics, deceptive.design, O'Reilly catalogue pages, Wikipedia and summary sites. Several author sites failed to load. | Norman, Hurff, Nodder (via deceptive.design) sourced. Marsh, Cagan ch. 11, most of Tidwell's catalogue, Nunnally & Farkas and Fitzpatrick are largely **general knowledge**, marked (gk) below. |
| Tufte, *The Visual Display of Quantitative Information* (1983, 2nd ed. 2001) | Not fetched; principles are standard and widely documented (edwardtufte.com). | General knowledge, but stable and well known. |
| Example build prompt ("design harness") | Read in full in this session. | Primary text. |
| Dribbble, "scientific UI" search | **Not read.** The page renders by JavaScript; fetch returned nothing and the Chrome extension was not connected. | None. Needs a connected browser or pasted shots. |
| Datalabs, "9 incredible examples of interactive data visualization" (2026-03-29) | Read via a summarising fetch; the article itself is brief. | Paraphrase of a shallow source. |
| Current hub | Code inventory of `platform/src/factory/services/site_*.py` and the hub plans. | Primary (code). |

## 3. Principles for the hub (merged, each with a check)

| # | Principle | Origin | Check |
|---|---|---|---|
| P1 | **Orientation first**: every screen says where I am, what this is, what I can do. | Krug, Norman (visibility) | Hide the body: title, breadcrumb and primary action still tell the story. |
| P2 | **One question per page**, its answer stated as a sentence above the detail. | Krug; Tidwell (gk) | Each page has a one-line lead finding computed from data. |
| P3 | **Overview, then detail on demand.** Every summary figure leads to the rows behind it. | Tidwell (overview+detail, progressive disclosure); Shneiderman mantra (gk) | No figure is a dead end; records reachable in ≤ 2 clicks. |
| P4 | **Traceable numbers**: each count shows its definition, denominator and source events. | Norman (conceptual model); platform rule "counts are computed, never typed" | Hover/expand on any number shows how it is computed and links to `trace`. |
| P5 | **All five states designed**: ideal, empty, partial, loading, error. | Hurff (UI stack) | A screenshot of each state exists per page. |
| P6 | **Empty and partial states say what to do next** (the step, tool or command). | Hurff | No blank panel without a reason and a next action. |
| P7 | **Honest scale**: x of y, n on every chart; "zero" distinct from "not yet run". | Hurff (partial); Datalabs/Panorama (honest about bad results) | No chart renders without its n. |
| P8 | **Plain errors that keep work.** | Hurff; Norman (errors are design failures) | Error names what happened, why, and the fix; no input lost. |
| P9 | **One vocabulary**, matching `docs/naming-glossary.md`. | Norman (conceptual model); Krug | No synonyms for one concept across UI strings. |
| P10 | **Recognition over recall**: active filters and state visible. | Nielsen heuristics via Norman | Active filters always shown as removable chips; URL holds view state. |
| P11 | **Expert density with progressive disclosure.** Compact sortable tables by default; rare detail folds away. | Tidwell (gk); design harness ("dense furniture belongs when it carries information") | Key table fits one screen, sorts, filters, exports. |
| P12 | **Remembered state, good defaults.** | Tidwell (Good Defaults) | Leaving and returning keeps sort, filter, page. |
| P13 | **Small multiples for comparison**, identical scales. | Tidwell (Small Multiples) | Comparisons share axes and scale. |
| P14 | **Visible system status**: progress of long jobs, age of data ("as of event N"). | Norman (feedback); Datalabs/WaPo (continuously updated) | Every page carries an as-of stamp; rebuilding is shown, not hidden. |
| P15 | **Safe, reversible acts**: preview, effect, supersede path. | Norman (slips); event model (corrections supersede) | Every write shows what it records and how to correct it. |
| P16 | **No dark patterns.** No infinite feed, no unread-count pressure, no streaks, no preselection that hides data; defaults never hide excluded or held-out items. | Nodder via deceptive.design; decision 37.9 | Review the feed and filters against the list. |
| P17 | **Calm, accessible visuals**: few hues, colour never the only signal, WCAG AA and APCA measured on rendered pages. | Design harness (legibility floor); Norman | Greyscale pass stays readable; measured contrast table retained. |
| P18 | **Validate by past behaviour, not opinion.** | Fitzpatrick (gk); Nunnally & Farkas (gk); Cagan (gk) | Each review round: researcher shows their last real session; we log where they left the hub and record a commitment, not a compliment. |

### 3a. Tufte: rules for every chart and table

Tufte governs the charts themselves, where the books above govern the interface around them.

| # | Principle (Tufte 1983) | Check on the hub |
|---|---|---|
| T1 | **Graphical integrity**: the visual size of an effect is proportional to the number (lie factor ≈ 1). No truncated axes or area/3D distortion; label clearly at the data. | Bars start at zero; a ratio of drawn sizes ≈ ratio of values; no 3D. |
| T2 | **Maximise data-ink**: erase non-data ink and redundant data ink. | Drop borders, grid backgrounds, heavy gridlines, box frames around charts; keep only what encodes or locates data. |
| T3 | **No chartjunk**: no moiré fills, decorative grids or "ducks". | Applies to the present control-room grid decor and `// ` heading ornaments. |
| T4 | **High data density**, shown at the resolution the eye can use; small, dense, well-designed displays beat large empty ones. | Prefer a dense table or small chart to a big single-number tile where comparison matters. |
| T5 | **Small multiples**: same design repeated across slices, so the eye compares changes in data, not design. | Agreement per miner, screening per criterion, costs per stage (= P13). |
| T6 | **Show the data; compare; context.** Answer "compared to what?". | Every figure sits beside its denominator, a baseline or the previous state. |
| T7 | **Integrate words, numbers and pictures**: labels on the data rather than legends; sparklines inline with text (*Beautiful Evidence*, 2006). | Direct labels on lines and bars; word-sized sparklines in tables and the project home. |
| T8 | **Layering and separation; micro/macro readings** (*Envisioning Information*, 1990): the overall shape and the individual record both readable in one display. | Light gridlines and muted context, strong data; PRISMA and the explorer show the whole and the item together. |
| T9 | **Tables when numbers are few or exact.** | Under about 20 numbers, or when exact values matter, use a table, not a chart. |

## 4. Presentation techniques mapped to hub pages

From Datalabs and standard visualisation practice (Dribbble not yet included).

| Technique | Hub page(s) | Note |
|---|---|---|
| Linked brushing: click a PRISMA box, the work list filters to it; box count = row count | prisma, flow | Strongest single fit with P3–P4. |
| Details-on-demand drawer (abstract, decision, reason, event trail) | prisma, explorer, bibliography, results | `site_panel` already provides a slide-over pane; generalise it. |
| Small multiples of agreement (one panel per miner / criterion, shared kappa scale) | agreement, miners | P13. |
| Faceted filters with live counts; filter state in URL | bibliography, explorer, feed | NYPL example; P10, P12. |
| Results table with inline marks (agreement dot, sparkline), row → evidence quote | results | P11. |
| Focus + context graph: start from one node, expand by hops, relation by line style not colour only | explorer (lineage, graph), citations | Bloomberg example: start from the reader's own item. |
| Time brush with minimap | explorer (timeline), updates, costs | New Yorker / Google examples; avoid scroll-jacking. |
| Collapsible or radial taxonomy tree with counts and coverage bar | taxonomy | WEF example. |
| "New since last visit" with rank reason; keyboard accept/dismiss; no unread badge | feed, updates | P16 constrains this. |
| Bold headline counts (found, screened, included) | project home, dashboard | Mailchimp example; each count links (P3) and carries n (P7). |
| Provenance stamp on every figure; page-level "as of" | all | P4, P14. |
| Honest uncertainty: intervals, n, small-sample marks, explicit "no data" | results, agreement | Panorama example. |

Rejected: 3D maps (Voices from the Frontlines), decorative glow and glass, scroll-driven narrative as the primary navigation of a working tool.

## 5. What carries over from the example build prompt

The prompt is written for a marketing landing page; the hub is a working tool. Carry over the method and the floors, not the sections.

**Method**
- A short brief in three parts: *look* (colour, type, shape, layout, imagery), *sections in order with what each holds*, *starting values* (tokens with measured contrast).
- Brand kit first (palette with exact values, type roles, controls, corners, chart treatment), then the first screen, then the rest.
- No image generation here: prototype-first — static HTML/CSS of the project home on real data, screenshot, refine two or three rounds.
- One checkpoint: plan plus rendered first screen shown to the researcher; build the rest only after approval.

**Floors that apply unchanged**
- WCAG AA (4.5:1 body, 3:1 large) and APCA (Lc 75 body, 60 content, 45 display) measured on rendered pairs, reported separately.
- Visible keyboard focus; all control states (rest, hover, active, selected, disabled, loading, empty, error).
- Numeric-column alignment (tabular figures); selection, caret, scrollbar and focus styled deliberately.
- Accent has one job and stays rare; the data carries colour.
- Display and reading type in separate roles, few sizes, one leading size per screen.
- Motion only for orientation or feedback; reduced-motion keeps the finished state.
- Same margin both sides at every width; narrow widths rethink navigation and tables rather than only stacking.

**Does not apply**: hero, logo cloud, download, blog index, closing panel, browser-frame screenshots.

## 6. Current hub: facts that constrain the redesign

**Structure**
- Main hub: `/` portal, `/feed/`, `/backlog/`, `/catalog/`, plus per-project `/p/<slug>/settings/`.
- Per-project hub `/p/<slug>/`: a "control room" page, sidebar plus one iframe, hash routing, 23 products in five groups (Overview, Sources, Corpus, Mining, Findings). Registered in `site.products()` (`platform/src/factory/services/site.py:321`).

**Technology**
- Python f-strings, inline CSS/JS per module, no JS library, no external resource (offline by design).
- Charts are hand-written inline SVG (`site_charts.py`); graphs are positioned divs.
- System fonts; monospace used for headings, tables, buttons and nav.

**Theme**
- Eight themes (dark, light, tokyo-night, catppuccin-mocha, gruvbox, nord, rose-pine, lcars; default lcars).
- Three overlapping CSS-variable families (product, portal, bar). `--mut` means *border* in one and *muted text* in another.
- Contrast tests exist (`test_site_themes.py`: text 7:1, muted and accent 4.5:1).

**Speed**
- Products are static builds rebuilt by a 15 s polling `Rebuilder` when their event fingerprint changes.
- The portal, feed, backlog and catalog render per request.
- Every response is `Cache-Control: no-store`.
- Feed caching landed 2026-11-17 (`hub-portal-speed`).

**Known weights and bottlenecks**
- The explorer page inlines the corpus as JSON: 6.75 MB for the pilot.
- Each product re-inlines its own CSS and all theme blocks.
- The portal counts events per project on each hit.
- Whole products rebuild while miners append.
- The Updates page still reads per work (IDEA-86).

**Seams to keep**
- `site_auth.Authenticator` (loopback plus HMAC token for writes).
- Products as rebuildable projections of events.
- Roughly 29 `test_site_*` files, some pinning HTML structure (`test_site_chrome.py`).

## 7. Consequences for planning (to be decided, not decided)

- **Speed** looks structural rather than cosmetic. The main candidates are:
  - one shared, cacheable stylesheet and script instead of per-page inlining;
  - corpus data served as separate cacheable JSON, loaded and paged on demand, instead of inlined;
  - no iframe shell;
  - real cache headers keyed on the product fingerprint.
- **Theme** consolidation: one token family before any new look. Whether eight themes survive is a question for the researcher.
- **The "control room" look** (square corners, `// ` headings, uppercase mono) is the present identity. Keeping, evolving or replacing it is the first look decision.
- **Dribbble input** is missing. Either connect the Chrome extension or paste five to ten shots before the look is settled.
- **Validation** (P18): before the brand kit, the researcher walks through their last real session on the current hub, and we note where they left it or got lost.

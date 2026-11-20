# Hub guide: building a page or a view

Binding for every new page, view or chart in the hub v2 (`platform/src/factory/hub_ui/`). It
consolidates the rules gathered for the redesign (sources in §1) with the mechanics of the
served hub. Where the sources disagree, the later ruling wins; this guide records the outcome.

The approved look (themes, type, colour scales, layout) is not reopened here. Existing pages
follow these rules when they are next touched; nothing is restyled for the guide alone.

Companions: `docs/hub-copy-guide.md` (wording, binding, details in §4), `docs/design-note-hub-ui-2026-11-18.md`
(background notes and the full source table), the Brand kit page (`kit.html`: tokens, the eight
themes, measured contrast).

## 1. Where the rules come from

| Source | Used for | Confidence |
| --- | --- | --- |
| Ten UX books: Norman, Krug, Hurff, Tidwell, Nodder (via deceptive.design), Marsh, Cagan, Brown, Nunnally & Farkas, Fitzpatrick | Interface principles P1–P18 | Norman, Krug, Hurff and Nodder from legitimate sources; the others largely general knowledge |
| Tufte, *The Visual Display of Quantitative Information*, *Envisioning Information*, *Beautiful Evidence* | Chart rules T1–T9 | Standard, well documented |
| The example design brief ("design harness") | Method (kit first, then pages), accessibility floors | Primary text |
| Datalabs, interactive data visualisation examples | Technique map (§5) | Shallow source |
| Prototype rounds of 2026-11-18 (briefs in the git-ignored `data/projects/agentic-science/ops/ui-prototypes-2026-11-18/`) | The researcher's rulings, the "every view" checklist, the screenshot loop | Primary (rulings) |
| Copy guide, round 3 | Titles, ⓘ panels, terms | Primary (ruling) |
| `caylent/tufte-data-viz` (MIT, read 2026-11-20) | The 22 chart rules C1–C22, chart forms, recipes, anti-patterns (§3) | Primary text; rules cite Tufte's books |
| `nexu-io/open-design`, `craft/` rulebooks (Apache-2.0, read 2026-11-20) | State coverage, loading thresholds, accent cap, WCAG 2.2 details (§3, §6) | Primary text |
| `phazurlabs/sumi`, data-visualisation skill (Apache-2.0, read 2026-11-20) | The channel ranking only (§3b); its KPI-card style conflicts with Tufte and the approved look | Primary text, partly untriaged by its authors |
| Anthropic design plugin (`anthropics/knowledge-work-plugins`, `design`) | Nothing adopted: a generic WCAG checklist; usable as a tool (`/accessibility`, `/critique`) | Primary text |

Researcher's rulings that shape everything: a hybrid of the three prototype directions, namely
the instrument's shell (rail, Ctrl-K palette, dense tables), the map's visuals (corpus map,
honest-scale flows) and the quiet paper's voice (a computed lead sentence, evidence shown as
quotations). Dark by default, the eight themes through tokens, short human titles with ⓘ panels.

## 2. Interface principles (P)

| # | Rule | Check |
| --- | --- | --- |
| P1 | Orientation first: where I am, what this is, what I can do. | Hide the body: title, breadcrumb and primary action still tell the story. |
| P2 | One question per view, answered by a computed lead sentence. | Every view has a lead built from the payload. |
| P3 | Overview, then detail on demand. | No figure is a dead end; the records behind it are at most 2 clicks away, ending in `HUB.openDrawer`. |
| P4 | Traceable numbers: definition, denominator, source. | The ⓘ panel says how it is computed. |
| P5 | All five states: ideal, empty, partial, loading, error. | Empty filter result, missing payload field and a stale payload each render deliberately. |
| P6 | Empty and partial states say what to do next. | No blank panel without a reason and the step that fills it. |
| P7 | Honest scale: x of y, n on every chart; zero is not "not run". | No chart without its n. |
| P8 | Plain errors that keep work. | An error names what happened, why, and the fix. |
| P9 | One vocabulary (`docs/naming-glossary.md`, `GLOSSARY`, `LABELS`). | No synonyms for one concept. |
| P10 | Recognition over recall: active filters are visible removable chips. | State is in the URL hash (`HUB.hash`). |
| P11 | Expert density with progressive disclosure. | The key table fits a screen, sorts, filters. |
| P12 | Remembered state, good defaults. | Leaving and returning keeps sort, filter, tab. |
| P13 | Small multiples on identical scales. | Compared panels share axes. |
| P14 | Visible system status. | The as-of stamp is shown; a stale payload says so. |
| P15 | Safe, reversible acts: preview, effect, supersede path. | Every write (`HUB.act`, `HUB.confirm`) shows what it records and how to correct it. |
| P16 | No dark patterns: no infinite feed, unread pressure, streaks, or defaults that hide excluded or held-out items (decision 37.9). | Review filters and defaults against the list. |
| P17 | Calm, accessible visuals: few hues, colour never the only signal. | Greyscale screenshot stays readable. |
| P18 | Validate by behaviour, not opinion. | Review rounds use the researcher's last real session. |

## 3. Chart rules (T, Tufte)

T1–T9 are the principles from the books. C1–C22 are the 22 universal rules of
`caylent/tufte-data-viz` (MIT), which states them as checkable defaults; each is marked
**adopted**, **adapted** (adopted with hub tokens in place of the source's hex values) or
**not adopted** (it would replace the approved look: themes, type, colour scales or the copy
guide). Deviate from an adopted rule only with a reason in the page's ⓘ panel or code comment.

| # | Principle (Tufte 1983) | Check on the hub |
| --- | --- | --- |
| T1 | Graphical integrity: drawn size proportional to value (lie factor ≈ 1). | Bars start at zero; no 3D, no area distortion; flow widths and symbol areas linear in the data. |
| T2 | Maximise data-ink. | Apply the "can I remove it?" test to every non-data element (below). |
| T3 | No chartjunk. | No decorative fills, ornaments, glow, entrance animation. |
| T4 | High data density. | A dense table or small chart beats a big single-number tile when comparison matters. |
| T5 | Small multiples (= P13). | Per miner, per criterion, per stage; rules in C-small-multiples below. |
| T6 | Answer "compared to what?" (= C13). | Every figure has a reference line, band, second series, denominator or previous state. |
| T7 | Integrate words, numbers, pictures. | Direct labels; word-sized sparklines in tables. |
| T8 | Layering: muted context, strong data. | Context in `--mut`/`--line`, data carries the colour. |
| T9 | Few or exact numbers go in a table (= C22). | Under about 20 numbers, use a table. |

Hub specifics (from the prototype rulings): hue encodes one variable per view and is labelled
directly; the accent (`--acc`) is only for selection, the primary action and focus, at most two
visible uses per screen (links and focus rings count; from `nexu-io/open-design`); `+` and `−`
glyphs accompany included and excluded; no chart library (inline SVG, canvas for large point
sets); colours only from tokens (`HUB.cssv`, `humanColor`, `layerColor`), re-rendered on the
`hub:theme` event; no literal colour values in page scripts (tested).

### 3a. The 22 rules

| # | Rule (source wording, condensed) | Hub status |
| --- | --- | --- |
| C1 | No top or right borders, spines or axis lines; bottom and left suffice. | Adopted. |
| C2 | Direct labels, not legends: at the line end, on or beside the bar, by the cluster. One series needs no label. | Adopted. |
| C3 | No gridlines by default; if needed for precise static reading, horizontal only, opacity 0.08–0.12; never vertical. Interactive charts use a hover crosshair instead. | Adapted: gridlines in `--line`. |
| C4 | Range-frame axes: the axis line spans the data range (min to max) only. | Adopted, for axes that need no zero (bars keep zero, T1). |
| C5 | No 3D, perspective, depth or shadow on chart elements. | Adopted. |
| C6 | No pie unless asked; default is a horizontal bar sorted by value. Forced pie: ≤ 4 slices, 2D, start at 12 o'clock, direct % labels. | Adopted. |
| C7 | Aspect ratio about 1.5:1 (600×400, 750×500, 900×600); sparklines and small multiples may be more compact. | Adopted. |
| C8 | Grey first, highlight selectively: default series grey, one accent for the key series, ≤ 4 distinct colours; palette type by data (categorical, sequential, diverging). | Adapted: views with one series use `--mut` for the series and one highlight. Views where hue encodes a variable keep the approved ordered scales (human role, layer) and label them directly. A new categorical hue set has ≤ 4 colours; beyond that, small multiples or "Other". |
| C9 | Off-white background `#fffff8` / `#151515`, never pure white or black. | Not adopted: backgrounds belong to the eight themes (all already avoid pure white and black). |
| C10 | Serif (ET Book, Palatino) for titles, data labels and annotations; sans only for 11–12 px ticks. | Not adopted: the hub's type roles (kit.css) are approved. Kept: data labels are at least the tick-label size. |
| C11 | No dual y-axes; two stacked charts sharing x. | Adopted. |
| C12 | Annotate the notable (peak, trough, inflection, event) in the nearest clear space, with a short leader line; when annotations compete, keep the most important, the rest go to a footnote or tooltip. | Adopted. |
| C13 | Show comparison context: a reference line (average, target, prior period), a shaded band or a second series. | Adopted (= T6). |
| C14 | Minimal tooltips: value and label as plain text; no coloured background, border, arrow or shadow. | Adapted: the shared `HUB.tip` surface stays (it must stay readable on eight themes); content is value and label only, no decoration added per page. |
| C15 | Progressive disclosure: the default view is the clean overview; detail on hover, tap and click. | Adopted (= P3). |
| C16 | Accessible by default: 3:1 for chart elements, 4.5:1 for text; colour never the only signal; a text alternative; keyboard navigable when interactive. | Adopted (details in §6). |
| C17 | Responsive, not resized: viewBox plus percentage width; at narrow widths change the form (horizontal bars, fewer ticks, abbreviated labels). | Adopted. |
| C18 | Animate to explain: transitions on sort, filter or time change only; 200–500 ms, ease-out; no entrance, bounce or decoration; respect `prefers-reduced-motion`. | Adopted. |
| C19 | Dark mode is first-class: both palettes designed, never inverted, saturation reduced, semantic tokens. | Adopted (the themes already do this; new colours are tokens). |
| C20 | Titles assert findings ("Revenue surged 23% in Q3"). | Not adopted: the copy guide keeps short human titles and puts the finding in the computed lead sentence. Kept: if a view has no finding, it may not be needed. |
| C21 | Format numbers for humans: 1.2M, thousand separators (12,450), precision matched to significance, units stated once. | Adopted (`HUB.fmt`). |
| C22 | Don't chart what a sentence can say: 1–2 numbers are a sentence, a ranking of 3–5 items may be a table; "a chart of two bars is almost always worse than a sentence". | Adopted. |

### 3b. Form by chart type

| Form | Rule |
| --- | --- |
| Line | 1.5–2 px stroke; points only when fewer than 7 (r 2), otherwise only min, max and end; direct label at the rightmost point. |
| Bar | Horizontal for categories, sorted descending, direct value labels; bars from zero. |
| Scatter | Muted dots (r 3), accent on the key cluster or outlier; optional thin dashed fit line; rug marks on the axes (4 px ticks, 0.5 stroke, opacity 0.4). |
| Time series | Events labelled on the chart; range-frame x axis; previous period as a ghost (current solid, prior at opacity 0.2–0.3). |
| Area | Prefer lines; if area, fill opacity 0.03–0.08, no gradient. |
| Stacked bar | Avoid (small multiples instead); if needed, sort by total, ≤ 4 segments, each labelled. |
| Heatmap | Sequential or diverging scale only, value labels in cells, a companion table. |
| Small multiples | Same scale on every panel (never auto-scaled); x labels on the bottom row, y labels on the left column; one title per panel; no panel borders (whitespace, or 1 px `--line`); compact, within one eye span; linked hover across panels. |
| Sparkline | viewBox 80×20, 16–24 px tall, `vertical-align: middle`; 1 px polyline, 2 px padding top and bottom; dots r 1.5 at min, max and end; no axes, labels or gridlines; inline in text or a table cell. |
| Slopegraph | Both endpoints labelled with name and value (left label right-aligned, right label left-aligned); muted 1 px lines, 1–2 key slopes in the highlight at 2 px; no axes; nudge overlapping labels. |
| Table | No zebra, no cell borders, no backgrounds; header row small, uppercase, tracked 0.05em, with a 1 px bottom rule; a thin separator every 3–5 rows; numbers right-aligned in tabular figures; an optional sparkline column. |
| Annotation | Short leader line (about 20 px, 0.5 stroke, `--line`) with the note beside it. |
| Reference line | 0.5 stroke, `--line`, dashed `4 3`, labelled at its end. |
| Map (none yet) | If the hub ever draws a map, follow the 19 map rules of the same source (`rules/maps.md`, each cited to Tufte): dot map and rate map together, value ramps light to dark, never spectral, muted large areas, thin quiet base layer. |

Encoding choice, when in doubt (Cleveland and McGill, via `phazurlabs/sumi`): position on a common
scale > position on unaligned scales > length > angle > area > colour saturation > hue. Prefer
the strongest channel the data allows.

### 3c. The "can I remove it?" test

Delete each non-data element and ask whether information is lost: gridlines (usually not), the
legend (not, if labelled directly), the axis title (sometimes, if the title names it), top and
right borders (always removable), tooltip decoration (always removable), ticks (maybe: keep them
for precise reading). If nothing is lost, it goes.

### 3d. Anti-patterns and their fixes

Pie → sorted horizontal bar. 3D → flat. Dual y-axes → stacked charts sharing x. Legend box →
direct labels. Heavy gridlines → none, or horizontal at low opacity. Rainbow palette → muted
scale or grey plus one highlight. Gauge → one number, a sparkline and a comparison sentence.
Zebra table → whitespace and thin rules. Gradient fill → flat colour. Rotated axis labels →
horizontal bars or abbreviations. Truncated bar axis → zero, or an explicit axis break with a
note. Decorative frames → whitespace. Area at 50% opacity → lines. Markers on every one of 50
points → min, max and end only. Thick axis lines → 0.5–1 px. Hover-only information → a click,
tap or focus fallback. No text alternative → aria-label with the finding. Colour as the only
difference → add shape, dash or a direct label. Entrance animation → remove. Fixed pixel width →
viewBox and percentage.

## 4. Copy (summary of `docs/hub-copy-guide.md`, which is binding)

- Titles: short human noun phrases, 1–4 words, sentence case. No questions as titles (this
  replaces the round-2 rule "state the question as a heading"), no "n =", no encoding described.
- The question, how to read it and how it is computed go in the ⓘ panel (`HUB.header({title,
  infoHtml})`, `HUB.info`): *What it shows* / *How to read it* / *How it's computed*.
- Jargon gets a dotted term (`HUB.term(key)`) defined in `GLOSSARY` (shell.js and
  `services/hub_ui.py`, kept equal by a test).
- Lead sentences are computed and sound like a colleague: one idea, about 25 words at most. No
  digits typed in sentence templates.
- No prototype leftovers ("from the brief", "not in prototype data").

## 5. Technique map

| Technique | Fits |
| --- | --- |
| Linked brushing (click a flow box, the list filters; box count = row count) | Flow, Pipeline |
| Details-on-demand drawer with evidence quotes and event trail | every list (`HUB.openDrawer`) |
| Small multiples of agreement on a shared κ scale | Miners |
| Faceted filters with live counts, state in the hash | Explore, Corpus |
| Table with inline marks (agreement dot, sparkline), row → evidence | Findings, Extracted data |
| Focus + context graph, expanding by hops, relation by line style | Graph |
| Time brush with a minimap (no scroll-jacking) | Living, Costs |
| Tree or icicle with counts and a coverage bar | Lenses, taxonomy views |
| Honest uncertainty: intervals, n, small-sample marks, explicit "no data" | Findings, Miners |

Rejected: 3D, decorative glow and glass, scroll-driven narrative as navigation.

## 6. Accessibility, states and layout floors

**States** (P5, from `open-design`): every list, table, chart and panel has five states: loading,
empty, error, populated and edge. An empty state has a headline, the reason and the next step; an
error is never shown as an empty state; an error says what happened, why and what to do, and
keeps the input. Edge cases to render: 10,000+ rows with sort and filter applied, a
200-character title, every optional field missing.

**Waiting** (applies to the served hub's Building and Stale answers): nothing for the first
300 ms; a skeleton up to 2 s; a labelled spinner up to 10 s; beyond that a progress indication
with what is being built, and a "taking longer than usual" note at 15 s; never an endless
spinner. Only the section that waits shows it; the page chrome stays.

**Charts:** each has a text alternative: an `aria-label` that states the finding (not "a bar
chart of …"), or a companion table, visually hidden, linked with `aria-describedby`. Dual
encoding: line colour plus dash or label, bar fill plus value label, dot colour plus shape.
Interactive charts: Tab focuses, arrows move between marks, Enter opens the records, Escape
closes. The default view reads as a static screenshot; nothing is hover-only.

**Floors:** 
WCAG 2.2 AA (4.5:1 body, 3:1 large text and UI components, 3:1 for the focus indicator) on every theme (measured by `test_hub_ui_tokens.py`) and APCA
(Lc 75 body, 60 content, 45 display; not yet measured by a test); visible keyboard focus with `:focus-visible`; targets at least 24×24 px (WCAG 2.2 AA); every control state designed (rest,
hover, active, selected, disabled, loading, empty, error); tabular figures, numeric columns right
aligned; `prefers-reduced-motion` keeps the finished state; works at 1440 px, 768 px and degrades at
390 px (the rail becomes a bottom bar); the drawer closes on Esc.

## 7. Adding a page: the steps

1. **Payload builder** (`services/hub_<name>.py`): `build(ctx: HubContext) -> dict`. Pure over the
   context: reads the project, writes nothing, calls no model or network. Every number is computed
   here, never in the page. Put the ⓘ texts in a `methods` dict. Reuse the shared inputs of
   `HubContext` (`flow_data`, `included`, `graph`, `layer_of`, `field`, `cited_here`,
   `mining_data`, …); a new shared input is a memoised method there.
2. **Register it** in `services/hub_build.py`: an entry in `BUILDERS`, and an entry in
   `PAYLOAD_INPUTS` listing the event-type prefixes it reads. A payload without an entry is keyed
   on every event and goes stale whenever any agent writes anything; declare the narrowest set
   that is still correct.
3. **Page script** `hub_ui/pages/<name>.js`, in the pattern of `pages/costs.js`:
   `HUB.load(['shell', '<name>']).then(d => { const H = HUB.init(d.shell); const main =
   H.mount({page, crumb}); … })`. Page-local CSS goes in one `<style>` element with a page
   prefix (`.co-…`); shared components come from `kit.css`. Change `kit.css` or `shell.js` only
   for something every page needs, and check the Brand kit page afterwards.
4. **Register the page**: `PageSpec` in `services/hub_ui.PAGES` (id, human title, script, payload
   names), the script in `ASSETS`, an entry in `RAIL` and in the palette `PAGES` list (both in
   `shell.js`), and an icon in `ICON` if it is new.
5. **Shared helpers** (from `window.HUB`): `header`, `info`, `term`, `openDrawer`, `tip`, `hash`,
   `fmt`, `pct`, `esc`, `pretty`, `val`, `quote`, `humanColor`, `layerColor`, `cssv`; for acts
   `act`, `post`, `confirm` (served hub only, `HUB.served`). Escape every payload string with
   `esc` before it reaches HTML.
6. **Tests** (run locally only the touched files; CI runs the rest):
   `test_hub_<name>.py` for the builder (figures on a small world, deterministic output);
   `test_hub_ui_pages.py` and `test_hub_ui_assets.py` already check every registered page for
   payload names, external URLs, literal colours, banned phrases, digits in templates and unsafe
   HTML sinks; `test_hub_ui_clicks.py` drives every registered page in headless chromium and fails on JS
   errors (skipped where chromium is absent, as on CI today).

### Speed budget

The hub rebuilds a payload in a background process whenever its inputs change, so builder time
is what the researcher waits for.

- Query the SQLite index (`project.index`) or an existing service; never re-read the JSONL
  event files (`read_all`, `read_typed`) inside a builder.
- Target under 10 s per payload on the pilot (133k events). Time a new builder on a reflink copy of
  the pilot (`cp -a --reflink=always data <copy>` on /home, then `factory --root <copy> hub build
  …` with the runtime code), never against the live index: a build on other code rebuilds it.
- Large lists are capped in the payload with the exact total beside them (P7).

## 8. Review loop (from the prototype rounds; mandatory for a new view)

1. Build the page against a pilot copy (`factory hub build <slug> --out <dir>`).
2. Screenshot with headless chromium (`--virtual-time-budget=5000` so fonts and scripts settle) at
   1440 px and 390 px, in `dark`, `light`, `gruvbox` and `lcars`.
3. Read the screenshots and critique: first glance, does each view answer its question, clutter,
   overlaps, colliding labels, contrast, empty space with no purpose.
4. Revise; two or three rounds.
5. Report per view: its question, its encoding, defects, and any change wanted in `kit.css` or
   `shell.js`.

## 9. Checklist for every view

- [ ] Short human title; question, reading and computation in the ⓘ panel.
- [ ] Computed lead sentence.
- [ ] Every mark leads to its records, ending in the paper drawer.
- [ ] n and denominator shown; zero distinct from not run.
- [ ] Empty, partial and error states say what to do next.
- [ ] State in the URL hash; filters as removable chips.
- [ ] Tufte: bars from zero, direct labels, no frames or chartjunk.
- [ ] Colours from tokens only; re-render on `hub:theme`; colour never the only signal.
- [ ] Keyboard reachable, visible focus, tooltips on hover and focus.
- [ ] A chart is warranted (C22); it has comparison context (C13) and direct labels (C2).
- [ ] Small multiples share one scale; no legend, no vertical gridlines, no dual axes.
- [ ] Text alternative states the finding; nothing is hover-only.
- [ ] Loading, empty, error and edge states rendered; waiting follows the thresholds in §6.
- [ ] Builder registered with the narrowest `PAYLOAD_INPUTS`; reads the index, not JSONL.

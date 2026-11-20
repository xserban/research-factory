# Hub guide: building a page or a view

Binding for every new page, view or chart in the hub v2 (`platform/src/factory/hub_ui/`). It
consolidates the rules gathered for the redesign (sources in §1) with the mechanics of the
served hub. Where the sources disagree, the later ruling wins; this guide records the outcome.

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

| # | Rule | Check |
| --- | --- | --- |
| T1 | Graphical integrity: drawn size proportional to value. | Bars start at zero; no 3D, no area distortion. |
| T2 | Maximise data-ink. | No borders, frames, grid backgrounds, heavy gridlines. |
| T3 | No chartjunk. | No decorative fills, ornaments or glow. |
| T4 | High data density. | A dense table or small chart beats a big single-number tile when comparison matters. |
| T5 | Small multiples (= P13). | Per miner, per criterion, per stage. |
| T6 | Answer "compared to what?". | Each figure sits by its denominator, baseline or previous state. |
| T7 | Integrate words, numbers, pictures. | Direct labels, not legends; word-sized sparklines in tables. |
| T8 | Layering: muted context, strong data; whole and item readable together. | Light gridlines, the data carries the colour. |
| T9 | Few or exact numbers go in a table. | Under about 20 numbers, use a table. |

Hub specifics: hue encodes one variable per view and is labelled directly; the accent (`--acc`) is
only for selection, the primary action and focus; `+` and `−` glyphs accompany included and
excluded; no chart library (inline SVG, canvas for large point sets); colours only from tokens
(`HUB.cssv`, `humanColor`, `layerColor`), re-rendered on the `hub:theme` event.

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

## 6. Accessibility and layout floors

WCAG AA (4.5:1 body, 3:1 large) on every theme (measured by `test_hub_ui_tokens.py`) and APCA
(Lc 75 body, 60 content, 45 display; not yet measured by a test); visible keyboard focus; every control state designed (rest,
hover, active, selected, disabled, loading, empty, error); tabular figures, numeric columns right
aligned; `prefers-reduced-motion` keeps the finished state; works at 1440 px and degrades at
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
- [ ] Builder registered with the narrowest `PAYLOAD_INPUTS`; reads the index, not JSONL.

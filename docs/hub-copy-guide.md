# Copy guide: round 3 (human titles, info panels, terms)

Researcher, 2026-11-18: "We need to be careful about how to organise the headers and titles. Many are generated and obviously not human-like. Make titles more human-like, and add info panels that you hover over to learn what a thing is."

## New shared tools (in `shell.js`, already working)

- **`HUB.header({kicker, title, sub, infoHtml, level})`** renders a section header: a short title, an optional kicker above it, an optional one-line subtitle, and an optional ⓘ button whose panel holds `infoHtml`. `level: 1` gives the page title (`.display`).
- **`HUB.info(html, label)`** returns an ⓘ button. Its panel opens on hover or focus, and click pins it. Put it after a title, a number or a chart label.
- **`HUB.term(key, shownText?)`** returns a word with a dotted underline and a plain definition on hover or focus.
  - Keys are in `HUB.GLOSSARY`: included, mined, miner, layer, human, technique, architecture, span, cic, quote, prisma, screened, duplicates, cap, notretrieved, criteria, protocol, stoprule, dna, similar, gap, and EX01–EX07.
  - You may add keys to `GLOSSARY` in your page script (`HUB.GLOSSARY.mykey = ['Title','Definition']`). Do not edit `shell.js` or `kit.css`.

## Rules

1. **Titles are short noun phrases of 1–4 words, in sentence case, written as a person would title a section:**
   - "Overview", "Where the records went", "Papers over time", "Most cited", "What the corpus is made of", "Design space", "How systems are built", "Lineage", "Trends", "Evidence", "Compare".
   - No questions as titles.
   - No "n =" in titles.
   - No restating the encoding.
2. **The question a view answers goes in the ⓘ panel**, together with how to read the chart and how numbers are computed. Structure that panel as:
   - `<b>What it shows</b>`, one sentence;
   - `<p><span class=k>How to read it.</span> …</p>`;
   - `<p><span class=k>How it's computed.</span> …</p>`.
3. **Remove every `.how` block and every long `.note` or `.meta` explanation from the page body.** Their content moves into the ⓘ panels. What may stay visible:
   - the lead sentence;
   - one short subtitle (at most ~12 words), only if it adds something the title does not say;
   - axis and direct labels;
   - n beside numbers where it matters, as a quiet `.meta`, e.g. "370 papers".
4. **Lead sentences stay computed but sound like a colleague talking.**
   - Short, one idea, about 25 words at most.
   - Bad: "365 of 5,599 records were included. Among 368 classified mined works, 51% put no human in the loop."
   - Good: "365 papers made it through screening. Half of the systems run with no human in the loop."
   - Round sensibly ("half", "about a third") only when the exact figure sits in the ⓘ panel or the chart.
   - Wrap jargon with `HUB.term`.
5. **Vocabulary for people, not for the pipeline:**

   | Instead of | Write |
   |---|---|
   | "mined works" | "papers" (definition via `HUB.term('mined','papers read in full')` where the distinction matters, once per page) |
   | "records" | "records", for PRISMA only, before screening |
   | "human position" | "human role" |
   | "cic" / "times cited inside the corpus" | "cited here" (term `cic`) |
   | "classified" | "coded" or just omit |
   | "n = 370 mined works" | "370 papers" |
   | "Not classified" | "Not coded" |

6. **Remove prototype leftovers entirely:**
   - "Review question, from the brief";
   - "Not in prototype data: …";
   - "Prototype data holds…";
   - "Filtering runs in this page… nothing is sent anywhere";
   - "Greyed pages exist in the hub…".
   - If something is genuinely missing, show a quiet empty state ("Costs appear here once runs are recorded") or leave it out.
7. **The 370 vs 365 note:** show `HUB.SETS_NOTE` once per page, small, at the foot, behind an ⓘ if possible.
8. **Kickers** (small text above a title) are for context only, e.g. "Living review · protocol P@03f4bf6a". Wrap "protocol" with a term.
9. **Buttons and actions are verbs:** "Browse papers", "Open the flow", "Pin", "Clear", "Show all".
10. **Do not change the visuals, data or interactions** except to remove text and add ⓘ and terms. Keep every computed number correct.

## Process

1. Edit your page or pages.
2. Screenshot with headless Chromium at 1440 (`--virtual-time-budget=5000`), dark and `?theme=light`.
3. Read each shot and check that it reads like a well-edited publication: few words, clear hierarchy, no machine phrasing.
4. Grep your file for the banned phrases above.
5. Do 2 rounds.
6. Overwrite the existing `shot-<page>-…` files.
7. Report the before → after list of titles (≤ 250 words).

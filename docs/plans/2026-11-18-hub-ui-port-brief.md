# Hub v2 page port brief (binding for every page task)

Status: merged (binding brief of IDEA-97, merged into main 2026-11-18)

Plan: `docs/plans/2026-11-18-hub-ui.md`. Copy rules: `docs/hub-copy-guide.md` (binding: short human titles, ⓘ panels, terms, no machine phrasing).

## What you change

- ONLY `platform/src/factory/hub_ui/pages/<page>.js`. Page-specific CSS goes in a `<style>` element that the script injects once, using only kit tokens (`var(--…)`), never literal colours.
- Do not edit `kit.css`, `shell.js`, `services/*.py`, or other pages. If you need a shared change, write it in your report under "Requested shared changes", with the exact proposed code.
- If a payload lacks something the view needs, do not invent it. Show a quiet empty state, and list the missing field under "Payload gaps".

## Page contract

```js
HUB.load(['shell', '<payload>', …]).then(d => {
  const H = HUB.init(d.shell);
  H.mount({page: '<page>', crumb: '<Title>'});
  // render into H.$('#main')
});
```

- `HUB` helpers (read `shell.js`): `header`, `info`, `term`, `GLOSSARY`, `LABELS`, `pretty`, `openDrawer`, `palette`, `tip`, `hash`, `fmt`, `esc`, `$`, theme events (`hub:theme`; re-render colours on it).
- Payload contents: read the service that builds each one (`services/hub_build.py` `BUILDERS` gives the mapping), and inspect the built JSON in your build copy (below) with python, not by reading it whole.
- Every number shown comes from the payload. No digit appears in sentence templates, and there are no typed counts.
- Each view's ⓘ panel takes its "How it's computed" text from the payload's `methods` entry, where one exists.

## Source of the design

The approved demo is at `$HOME/Documents/Projects/research-factory/data/projects/agentic-science/ops/ui-prototypes-2026-11-18/r2/<file>.html`, with shared `kit.css`, `shell.js` and `COPY-GUIDE.md`. Port its views faithfully: same encodings, interactions and copy. Replace `window.RF`/`window.RFM` reads with payload reads. Remove demo-only hooks (`?replay=`, `zm=`, test params) and leftover prototype phrases. Its screenshots (`r2/shot-<page>-*.png`) show the approved look.

## Your build copy and loop

1. Make a reflink copy of the built site: `cp -a --reflink=auto $HOME/.cache/rf-hubv2/ui-build $HOME/.cache/rf-hubv2/ui-<page>`. Never rebuild the payloads; that takes minutes and the copy has them.
2. After each edit: `cp platform/src/factory/hub_ui/pages/<page>.js $HOME/.cache/rf-hubv2/ui-<page>/assets/pages/<page>.js`.
3. Screenshot:
   ```
   chromium --headless=new --disable-gpu --hide-scrollbars --user-data-dir=$(mktemp -d -p $HOME/.cache/rf-overnight-tmp) --window-size=1440,1400 --virtual-time-budget=7000 --screenshot=$HOME/.cache/rf-hubv2/ui-<page>/shot-<state>.png "file://$HOME/.cache/rf-hubv2/ui-<page>/<page>.html#<state>"
   ```
   - Take dark, `?theme=light`, `?theme=gruvbox` and `?theme=lcars` at 1440, plus one at 390.
   - Remove the temporary profile afterwards.
4. Check for errors: run the same command with `--enable-logging=stderr --v=0 --dump-dom`, and grep stderr for `Uncaught` and for "Failed to load".
5. Read your screenshots, critique them against the demo shot and the copy guide, and fix. Do 2–3 rounds.
6. Run `node --check` on the file if node exists.
7. Keep the script under ~900 lines. Factor out repetition.

## Finish

- Commit only your page file on `hub-ui-v2`, with a message ending: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No push, no merge.
- Leave no background process running, and delete your temporary chromium profiles. Keep the `ui-<page>` folder for review.
- Report in ≤ 250 words:
  - views ported, and what changed from the demo;
  - payload gaps;
  - requested shared changes;
  - defects left;
  - the paths of your final screenshots.
- Do not use any advisor tool.

# Plan: Main hub portal becomes "The estate" (P01)

## Goal
Replace the body of the main hub portal (`/` of `factory site serve`) with the aerial fine-line isometric industrial estate from lab concept P01 (`experiments/hub-mockups/p01-the-estate/`), while preserving every existing portal capability, form, endpoint, and test contract.

## Architecture & Files
1. **Pure data serializer in `platform/src/factory/services/site_portal.py`**:
   - Add `portal_payload(rows: list[PortalRow]) -> dict[str, object]` (pure function) returning the structured project list (`slug`, `title`, `events`, `stale`, `built`, `hub_ready`, `building`, `activity`, `activity_end`, `funnel`, `hub_url`, `classic_url`).
   - Emit it inside `<script type="application/json" id="pt-data">` with `</` escaped as `<\/` (and `\u2028`/`\u2029` escaped) so a project title containing `</script>` cannot break out of the script tag.
2. **Portal HTML in `platform/src/factory/services/site_portal.py`**:
   - Keep `kit_page(...)` with `active="projects"`, `<h1>Conjecture</h1>`, and the existing `hubbar` / theme toggle.
   - Link `/feed/assets/estate.css?v=<v>` in `head` and `/feed/assets/estate.js?v=<v>` in `body` (no extra inline `<style>` tags).
   - Render the estate stage (`#pt-estate-stage`, `#estateCanvas`, camera controls, accessible `#hotspotLayer`, `#estateTip`, `#gatehouseHud`, `#flyVeil`, 30-day `#replayDeck`, and info popover).
   - Keep the server-rendered Parcel Ledger (`pt-grid` / `pt-card` with sparkline, funnel, events, pages built, state text, `/p/<slug>/ui/` and `/p/<slug>/` links) so every project metric is immediately visible and accessible without JS.
   - Keep `#create-form` (`/api/projects/create`) and `#inbox-form` (`/api/inbox/add`) with their exact field names, `X-Factory-Token` handling, and `create_token` gating, styled as the Site Sign & Loading Dock.
   - Keep the `registry.json` footnote.
3. **Served assets via `platform/src/factory/services/site_factory_feed.py`**:
   - Register `estate.css` (`hub_ui/estate.css`) and `estate.js` (`hub_ui/estate.js`) in `_OWN` so they are served under `/feed/assets/`.
4. **Estate styles (`platform/src/factory/hub_ui/estate.css`)**:
   - Port P01 styles using `pt-` prefixed classes and kit CSS variables only (zero literal colours, zero external URLs, laptop-first 1280–1600px).
5. **Estate script (`platform/src/factory/hub_ui/estate.js`)**:
   - Read `#pt-data` instead of fetching static JSON files.
   - Use real `stale` counts for unlit factory hall windows (`stale > 0` unlit, `stale === 0` lit, `!hub_ready` drafted).
   - Redraw on theme changes via `MutationObserver` on `document.documentElement[data-theme]` and `storage` events.
   - Fix **zoom/fit**: tighten estate bounds and stage sizing so the estate fills the stage width cleanly for 1, 2, and 12+ projects.
   - Fix **label overlap**: add screen-space bounding-box collision avoidance for nameplates, peak flags, and station micro-labels, with leader lines to final positions.

## Verification
- TDD: add `platform/tests/test_site_portal_estate.py` before implementing, covering JSON payload schema, `</script>` escaping, form field names/endpoints, served assets, and no literal colours or external URLs in `estate.css` / `estate.js`.
- Run `pytest`, `ruff check`, and `mypy` on the relevant files.
- Visual check at `1440x900` in dark and light themes on port `8777` against `/home/obd/Documents/Projects/rf-data-467`.

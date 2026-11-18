# Plan: hub products built on open (IDEA-96)

Date: 2026-11-18 · Branch: `hub-on-demand` (from `hub-stall-fix`) · Follows: IDEA-55, plan 2026-11-10-site-hub

## Goal
The served hub builds a product only when it is opened and stale, instead of rebuilding every
stale product at start and every `--every` seconds. A change to one product's code rebuilds that
product only.

## Findings that motivate it (2026-11-18)
- `code_hash()` covers every `site*.py`, `miner_info.py` and `pages.py`: any hub commit marks all
  ~25 products stale.
- The dashboard snapshot and Updates read every event type; about ten products read
  `extraction.%`. A feed check or a mining run marks them stale.
- The rebuilder holds one lock for the whole batch; requests that waited on it exhausted the
  browser's six connections (fixed on `hub-stall-fix`: `/api/status` no longer waits).

## Tasks
1. **Hub page module.** Move the hub page (`_HUB_CSS`, `_HUB_JS`, stations, `render_hub` body)
   from `site.py` to `site_hub_page.py`; `site.render_hub` delegates. No behaviour change.
2. **Per-product code hash.** `product_code_hash(product)`: the files reached from the product's
   build (and stamp) function by imports, within the hub code set (`site*.py`, `miner_info.py`,
   `pages.py`), plus `site.py`'s top-level imports. Cached per process (code is loaded once per
   process). `fingerprint` uses it; `code_hash()` stays for the catalog.
3. **On-demand rebuilder.** `Rebuilder.ensure(pid)` → `fresh` | `building` | `failed`. A stale
   product is queued to one worker thread per project (builds stay serial: one manifest writer).
   A build that failed at a fingerprint is not retried until the fingerprint changes. The eager
   loop runs only with `eager=True`.
4. **Server.** A GET for a product's entry page (`/<pid>/`, `/<pid>/<entry>`) calls `ensure`;
   `building` answers a small "updating" page that refreshes itself (meta refresh, which replaces
   the history entry); `failed` serves the previous output when it exists, else the error.
   Files inside a product folder are served as they are.
5. **Hub page.** Every product link opens the product (the server builds it); the light word for
   a stale product reads "Updates on open" when served.
6. **CLI.** `factory site serve --eager` keeps the old loop; `--every` applies to it.
7. **Docs.** Backlog IDEA-96, MAP regenerated, module docstrings state the new invariants.

## Checks
ruff, `mypy --strict` on the touched files (testing paused, 2026-11-05). Manual: serve a copy of
the pilot, open Results then Miners, press Back.

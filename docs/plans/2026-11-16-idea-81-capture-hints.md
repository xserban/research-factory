# Researcher hints at capture: layer, notes for miners, origin tag (IDEA-81)

Status: draft for the researcher's validation (2026-11-16). Not started. Researcher ruling 2026-11-15: all three parts are built before pilot 2.
Depends on: `services/inbox.py` (`LinkInput`, `link_event`, `add_links`), `services/feed.py` (`send`, `add`), `services/discovery.py` (routes, `by_channel`), `services/feed_read.py` (`feed_work_ids`), `services/work_layers.py` (layer of a work, `work.layer_set`), `services/reference_layers.py` (the scheme and its versions), `services/mining.py` (`mine_next`), `mining/spec.py` (`Selector`, `Population`), `services/withholding.py`, `services/site_server.py` (`inbox_add`), `services/site_hub_feed.py`, `services/site_explorer_page.py`. Decisions 37 (item 9), 61, 82, 83, 120, 123, 125, 127. Spec background: `docs/specs/slice-4a-inbox-discovery.md`, `slice-4c-feed.md`.

## 1. Goal and non-goals

**Goal.** A researcher who knows at capture what a paper is can say so once: a layer, a taxonomy category, and a note addressed to the miners. Every work that came through the inbox or the feed carries a computed origin. Miners receive the note after screening, and the agreement of m-layer with the researcher's layer hints is reported as a calibration signal that costs no extra labelling.

**Key results.**
1. `inbox add`, the hub add form and the feed's one-click add accept an optional layer, category and miner note, recorded with actor and time.
2. `work origin` is computed from events (never typed) and filters the hub explorer and, optionally, a miner's population.
3. `mine_next` serves the note (not the labels) to production passes; screening, calibration and audit never see hints or origin.
4. A computed report gives the agreement of the layer miner with current, non-stale hints, with its exclusions stated.

**Non-goals.**
- No model call; no automatic hint from text.
- Agents record no hints (the hint is the researcher's label). The MCP gets no write tool.
- A hint is not a miner row, not a `work.layer_set` move, and not a gold label (see open choices 2 and 8).
- Hints are not carried by `mine import` (project-local labels), and hand-supplied PDFs (`fulltext_import`) get no hint surface in v1: they attach to works that already exist. Note: `file.registered` (decision 125) registers study files, not PDFs; PDFs enter as `fulltext.document_added`.
- No change to screening content, to protocol hashes, or to existing event types' dumps.

## 2. Existing pieces this plan reuses

- The inbox item is the capture unit: `inbox.link_added` (item id `inb_`, `note` at most 300 characters, "never reaches screening or extraction content", `channel`), resolved later by `inbox.link_resolved` to a work. The feed's `send` writes the inbox event and `feed.sent` in one batch; `add` then resolves exactly that item.
- A work's layer is the latest `work.layer_set` (the researcher's move; beats a miner) else the first protocol-listed derived layer miner's FINAL row, else pending (`work_layers.py`). Scheme versions are recorded by `reference.layer_scheme_recorded`; a move to a layer outside the latest scheme is ignored and shown as `ignored_move`.
- `discovery.py` already derives each work's routes, first route and per-channel counts (`by_channel`, feed as a sub-count); `feed_work_ids` lists feed-sent works. Origin is a view over these, not a new store.
- Held-out handling: `held_out_tokens(project, include_work_ids=False)` for tools that name corpus works (decision 37.9, 123); the inbox agent page omits `link`, `identifier_value`, `identifier_version` of a held-out seed's item (`_PRE_PASS_OMITTED`).

## 3. Part 1: hints at capture (layer, category, note)

### 3.1 Data model

**New event `hint.recorded` (schema 1), refs the target.** Decision row needed (proposed, next free number; 131 at the merge of 2026-11-17). Fields:
- `target`: exactly one of `item_id` (an `inb_` item, the capture-time target) or `work_id` (a later hint on a work already in the corpus).
- `layer`: optional `{scheme_version, layer}`; the layer must be an id of that recorded scheme version.
- `category`: optional `{taxonomy_id, version, category}` where `category` is `<dimension>/<category>` of a registered taxonomy version (for example `t-agentic-layer`).
- `miner_note`: optional text, at most `MAX_MINER_NOTE` characters (open choice 11), distinct from the inbox `note`, which keeps its decision 61 guarantee.
- At least one of the three is set, unless the event clears the target's hint (`clears: true`, all three empty). The latest event per target (event id order) is current; earlier ones stay in the log. A correction is a new event; none is edited.
- Human actor only; channel `cli` or `hub`; the usual envelope (`actor`, time). No `input_blob` is needed for a human event (as `inbox.link_added` from a human has none).

**Why a new event and not fields on `inbox.link_added`.** The capture event is append-only; a hint added or changed afterwards, or on a work that arrived through a search, cannot be a field of it. Capture writes both events in one batch (as the feed does with `feed.sent`). The alternative is recorded as open choice 1.

**Projection (projector only).** Table `capture_hints`: `event_id`, `item_id` nullable, `work_id` nullable, `layer`, `scheme_version`, `taxonomy_id`, `taxonomy_version`, `category`, `miner_note`, `clears`, `actor_kind`, `ts`. Fold: current hint per target is the max event id. Read-side `hints_of_works(project)` maps item targets through `inbox_resolutions` (status `resolved`, `work_id` set) and folds absorbed works into their canonical work with `canonical_works` (the canonical-versus-absorbed mismatch of IDEA-82 must not be repeated). Two current hints for one canonical work (an item hint and a work hint, or two merged works): the later event wins; a check lists the conflict.

**Staleness.** A layer hint names its scheme version. When the latest recorded scheme differs, the hint is `stale`: shown with that mark, never rewritten, excluded from the agreement report, and listed by `check` (info). No automatic migration (open choice 5).

### 3.2 Capture surfaces

- **Service** `services/hints.py` (new): `record_hint(project, actor, target, layer=, category=, miner_note=, channel)`, `current_hints(project)`, `hint_issues(...)` (boundary validation). `LinkInput` gains `hint: HintInput | None`; `link_event` returns the capture event and, when a hint is given, the hint event, both recorded by `add_links` and by `feed.send` in one batch under the existing lock.
- **CLI.** `factory inbox add LINK... [--layer ID] [--category TAX:DIM/CAT] [--miner-note TEXT]` (options apply to every link of the call); `factory inbox hint TARGET [--layer ... --category ... --miner-note ... | --clear]` where TARGET is an item id or a work id; `factory inbox hints [--stale]` lists current hints. A duplicate capture (identifier already open in the inbox) writes no new item; with hint options the hint is recorded against the existing open item and the output says so.
- **Hub.** The portal add form (`site_server.inbox_add`, `POST /api/inbox/add`) accepts optional `layer`, `category`, `miner_note`; a collapsed "Hints for the miners" section lists the current scheme's layers and the registered taxonomies' categories. The feed one-click add (`site_hub_feed.py`, full page and the compact card) gets the same section; `feed.add` passes the hint through `send`. The explorer work panel (`layerActs`) shows the current hint with an edit control that posts `hint.recorded` by work id.
- **MCP.** No write tool (agents do not record the researcher's labels; compare decision 125 item 4). `inbox_add` is unchanged and refuses hint parameters. Reads: see 3.3 and part 3.
- **Gate.** `hint.record` joins the permission table as a decision gate with floor human, like `inbox.prioritise`.

### 3.3 How miners read the note

- Only `mine_next` carries it: the task content gains an optional `researcher_note` (text, actor and date), served for production passes A and B alike (independence: both passes see the same note) and never for calibration passes. The layer and the category are never served, so m-layer is not scored against a label it saw.
- Instruction text added to `MINE_INSTRUCTIONS` only when a note is present: the note is the researcher's remark, not evidence; every value still needs its anchor and verbatim quote; the note is never quoted as a source.
- Not served to screening (`screen_next`, calibration and check examples, audit sampling), to evidence extraction (`extract_next`), to the contribution or reference layer-assignment tools, or to any agent view of the inbox.
- Served text passes through `withhold(..., held_out_tokens(project, include_work_ids=False))`: a researcher note that names a held-out seed's DOI, arXiv id, OpenAlex id, PMID or seed id reads `[withheld]` in the served task. A held-out seed's paper is read as corpus (decision 37.9): its hint is served like any other and the work id is not masked.
- Leak flag (computed, no event): `note_names_layer` is true when the note contains a layer id or layer name of the hint's scheme version as a whole word; such works are excluded from the agreement report because the miner may have read the label in the note.

### 3.4 Validation at the boundary

Refused with structured errors and nothing written: a non-human actor (`actor`); a layer that is not an id of the named recorded scheme version, or a scheme version that was never recorded (`layer`); a category whose taxonomy version is not registered or whose `<dimension>/<category>` does not exist (`category`); a note that is blank after stripping or longer than the limit (`miner_note`); a target that is not exactly one of an existing item or a canonical-resolvable work (`target`); a target item that is withdrawn (`target`); a session that joined a screening or extraction pass (same rule as the inbox, `_refuse_actor`). A batch with several links is partial as `add_links` is: an invalid hint rejects that item's capture and hint together (nothing half-written).

### 3.5 Tests to write (TDD, written before code)

1. Model: `hint.recorded` needs exactly one target and at least one of layer, category, note unless `clears`; unknown fields refused; existing events' dumps unchanged.
2. Fold: latest event per target wins; a clear removes it; rebuild from the log gives the same table (idempotent projection).
3. Resolution mapping: item hint reaches its work only when the item is `resolved`; a merged work's hint folds to the canonical work; a conflict is detected.
4. Boundary: each refusal in 3.4 writes nothing and names its field; agent actor refused; pass session refused.
5. Capture batch: capture event and hint event are written together or not at all; a duplicate capture with a hint records only the hint.
6. Staleness: a hint after a new scheme version is `stale`, not rewritten, listed by check.
7. Feed: `send` and `add` with a hint write `inbox.link_added`, `hint.recorded`, `feed.sent` in one batch.
8. CLI and hub: option parsing, the form fields, the duplicate answer; MCP `inbox_add` refuses hint arguments.
9. Leak tests: no hint or note text in `screen_next`, calibration, check example, audit and `extract_next` payloads (a recursive scan for a planted marker string); a held-out seed identifier typed into a note is `[withheld]` in `mine_next`.
10. Gate: `hint.record` refused below human floor.

### 3.6 Tasks

- **H1 (rf-builder-critical, 2 h).** Decision row (proposed), `model/hints.py`, event registration, module declaration, gate row. Files: `model/hints.py`, `services/modules/*`, `docs/decisions.md`. Tests 1, 10.
- **H2 (rf-builder-critical, 2 h).** Projection and fold. Files: `index/hints.py`, index registry. Tests 2, 6 (fold part).
- **H3 (rf-builder-critical, 3 h).** `services/hints.py`: validation, record, current hints, canonical folding, `LinkInput.hint`, `link_event` and `add_links` batch. Files: `services/hints.py`, `services/inbox.py`. Tests 3, 4, 5.
- **H4 (rf-builder, 2 h).** CLI `inbox add` options, `inbox hint`, `inbox hints`. Files: `cli/main.py`. Test 8 (CLI).
- **H5 (rf-builder, 3 h).** Hub: portal form, feed add (service `feed.py` threading and `site_hub_feed.py`), explorer work panel. Files: `services/feed.py`, `services/site_server.py`, `services/site_hub_feed.py`, `services/site_explorer_page.py`. Tests 7, 8 (hub).

## 4. Part 2: the origin tag

### 4.1 Data model

No event, no table. `services/work_origin.py` (new, builder over the projection, read-only): `origins(project) -> dict[work_id, Origin]` with `Origin` = `{tags, channels, first_route}`.
- Tag `inbox`: the work has a resolved `inbox_items` capture whose channel is not the feed send (human capture via CLI or hub; agent captures are tagged `inbox-agent` so a human's act and an agent's proposal stay apart).
- Tag `feed`: the work is in `feed_work_ids`.
- `channels`: the capture channels (`cli`, `hub`, `mcp`, `feed`), from `inbox_items` and `feed_sends`.
- `first_route`: from `discovery`, so a work first found by search and later supplied carries the tag but a different first route; the tag says "also supplied", never "found only by".
- Works are canonical (merge-folded); an absorbed work's capture counts for its primary.
- The tag is derived from events only; there is no way to type it. It never weights or ranks anything (decision 61 ruling 11).

### 4.2 Surfaces

- **Hub explorer**: a dimension `origin` (values `inbox`, `feed`, `none`) next to `layer`, filterable, with a badge in the work panel (first route and channels). The `layers` and `lifecycle` products are unchanged.
- **Miner selector** (open choice 7): an optional `origins` tuple on `Selector` restricting the population (intersection with the named `Population`). Written to the spec JSON and the digest only when non-empty, exactly as decision 127 treats attributes, so every registered digest is unchanged. Registration is the researcher's act (decision 120).
- **Reports**: `report_discovery` and the `mine_status` population line state the origin counts; no new tool beyond a `view`.
- **CLI**: `factory work origins [--tag inbox|feed]` lists works with tag, first route and channel.
- **MCP**: origin appears only in read tools that are not screening content: `report_discovery` (unchanged shape, extra counts) and, for a miner whose selector uses origins, in `mine_status`. It is never in `screen_*`, `extract_next` or `mine_next` task content.

### 4.3 Held-out and blinding

- Screeners never see origin: route-blind screening (decision 61) stays; origin is not a screening-content field and the leak test scans for it.
- A held-out seed's work found only through a link remains not retrieved (decisions 54 and 61): origin does not count as retrieval of a seed.
- An origin filter lists works by id only; work ids are corpus data (decision 37.9, 123), so the held-out token set is used with `include_work_ids=False` and no `[withheld]` marks a work. The inbox views keep omitting a held-out item's identifiers.

### 4.4 Validation

`origins` selector values must be in the fixed vocabulary (`inbox`, `inbox-agent`, `feed`); an unknown value, or a selector that leaves an empty population, is refused at miner registration with structured errors and nothing written.

### 4.5 Tests

1. Tag derivation for each channel: CLI capture, hub capture, agent capture, feed send, a work both searched and supplied, a merged pair.
2. The tag cannot be set by input: no service or tool accepts it.
3. Origin is absent from `screen_next`, calibration, audit and `extract_next` payloads (planted-marker scan).
4. Explorer data carries `origin`; filter returns exactly the tagged works.
5. Selector: empty `origins` leaves digest and JSON byte-identical (golden test against an existing registered spec); a non-empty one changes the digest, restricts the population and round-trips.
6. Origin does not change `seed_recall` or the held-out matcher (a held-out seed captured through the inbox is still not retrieved).

### 4.6 Tasks

- **O1 (rf-builder-critical, 3 h).** `services/work_origin.py` with tests 1, 2, 6. Files: `services/work_origin.py`, `services/discovery.py` (read only; export a helper if needed).
- **O2 (rf-builder, 2 h).** Hub explorer dimension and badge; `report_discovery` counts; CLI `work origins`. Files: `services/site_explorer.py`, `services/site_explorer_page.py`, `services/discovery.py`, `cli/main.py`. Test 4.
- **O3 (rf-builder-critical, 3 h).** Selector `origins`, digest-preserving serialisation, population filter, registration validation. Files: `mining/spec.py`, `mining/*` (population), `services/mining.py`, `services/miner_add.py`. Tests 5, 4.4. Needs decision wording (see section 7).

## 5. Part 3: miners receive the note; agreement with the hints

### 5.1 Reading (summary)

Note served in `mine_next` as in 3.3; labels never. A work counts in the agreement report only if its hint is current, not stale, names a layer, was recorded before the miner's FINAL row for that work was complete (a hint recorded after mining is still compared, with `recorded_after_mining` marked, since the miner could not have seen it; the rule is that the miner never saw the label), and `note_names_layer` is false.

### 5.2 Data model

No event. `services/hint_agreement.py` (new, read-only): `hint_agreement(project, miner=None) -> HintAgreement`:
- per layer-miner version: works with a usable hint, agreed, disagreed, share agreed (counts and the proportion; no interval typed by hand), a confusion table hint layer by miner layer, and the exclusions with counts and reasons (`stale`, `note-names-layer`, `not-mined`, `unresolved-disagreement` between the two passes, `miner-not-stated`);
- the list of disagreements (work id, hint, miner row id and quote) for the researcher's review; nothing is resolved automatically and nothing is written;
- the miner's layer is the FINAL row value, read exactly as `work_layers` reads it (`<dim>/<layer>`, not-stated and other are no layer); `work.layer_set` moves are ignored here, otherwise the researcher would be scored against their own move.
- the labelled caveat in every output: "researcher hints, unreviewed; not a gold label set".

### 5.3 Surfaces

- CLI `factory mine hints [--miner NAME] [--version N]` prints the report; `--disagreements` lists them.
- MCP: `mine_status` gains a `hint_agreement` block (counts and confusion only; never the hint note text, never per-work labels, so an agent cannot read the labels before mining). `mine_next` carries the note (3.3).
- Hub: the miners product (`site_miners.py`) gains a "Hints" panel (agreement, confusion, exclusions) and the explorer work panel shows hint against miner layer side by side for the human.
- `check` rules: `hint-scheme-stale` (info, count), `hint-target-unresolved` (a hint on an item still open or withdrawn, info), `hint-conflict` (two current hints on one canonical work, warning), `hint-agreement-low` (warning, only when the share agreed is below a floor the researcher sets; no default floor is invented).

### 5.4 Validation

`hint_agreement` refuses a miner that is not registered or has no layer dimension (`miner`); it never reads calibration units as hinted works (a calibration work with a hint is reported separately so calibration and hints never mix).

### 5.5 Tests

1. Agreement counts, confusion and exclusions on a fixture with agreed, disagreed, stale, note-names-layer, unresolved and unmined works.
2. A moved layer (`work.layer_set`) does not change the miner layer used.
3. `mine_next` serves the note and no layer or category; calibration pass serves none; pass B serves the same note as pass A.
4. `mine_status` block carries no hint text (marker scan).
5. A held-out seed identifier in a served note is `[withheld]`; the work id of a held-out seed's paper is not.
6. Check rules fire as specified and not otherwise.
7. Calibration works with hints are reported apart.

### 5.6 Tasks

- **M1 (rf-builder-critical, 3 h).** `mine_next` serves the note with scrub and instruction text; leak scan tests (3.5 test 9, 5.5 tests 3, 4, 5). Files: `services/mining.py`, `services/hints.py` (read helper), `services/withholding.py` (read only).
- **M2 (rf-builder-critical, 3 h).** `services/hint_agreement.py` and tests 5.5 (1, 2, 7). Files: `services/hint_agreement.py`, `services/work_layers.py` (read helper).
- **M3 (rf-builder, 2 h).** CLI `mine hints`, `mine_status` block, hub miners panel, explorer side-by-side. Files: `cli/main.py`, `mcp` tool for `mine_status`, `services/site_miners.py`, `services/site_explorer_page.py`.
- **M4 (rf-builder, 2 h).** Check rules, `trace` entry for `hint.recorded` by refs, spec amendments (slice-4a and 4c one line each), decision row text finalised. Files: `services/check.py` (rule modules), `services/trace.py`, `docs/specs/slice-4a-inbox-discovery.md`, `docs/specs/slice-4c-feed.md`. Test 5.5 (6).

## 6. Ordered task list and dependencies

1. H1 (decision row, model, gate). No dependency.
2. H2 (projection) after H1.
3. H3 (service, capture batch) after H2.
4. O1 (origin builder) after nothing but may run in parallel with H1 to H3 (separate files).
5. H4 (CLI) after H3.
6. H5 (hub, feed) after H3.
7. O2 (explorer, reports) after O1.
8. M1 (serve note) after H3.
9. O3 (selector) after O1 and the decision wording.
10. M2 (agreement) after H3.
11. M3 (surfaces) after M2, M1.
12. M4 (checks, trace, specs) after M3 and O3.
13. One Sonnet review of the branch; guard-mutation attention on the leak tests and the digest-preservation test (the review lessons of earlier plans). `docs/MAP.md` regenerated by `scripts/gen_map.py` after merge by whoever merges, not in this plan.

Parallel lanes: {H1-H2-H3 then H4, H5, M1, M2} and {O1 then O2, O3}. Suggested branch `idea-81-hints`; tests are written with each task but not run while the testing pause holds; mypy and ruff must pass.

## 7. Decision rows and event changes (explicit)

- **New event** `hint.recorded` (model `model.hints.HintRecorded`, module `inbox`): needs a decision row, proposed: "Researcher hints at capture (IDEA-81)". Text to cover: human-only labels that are not miner rows or moves; target item or work, latest wins, clears; staleness by scheme version; note served to production miner passes only, labels never; the leak flag and exclusions; the agreement report is not a gold set; origin is computed, not stored; `Selector.origins` omitted when empty (digests unchanged); gate `hint.record`.
- **New index table** `capture_hints` (projector only).
- **New Selector field** `origins` (optional): a miner-spec schema change; digest-preserving when empty. Needs the same decision row (or open choice 7 option "hub only" removes it).
- **Amends** nothing in Decided entries: decision 61's inbox `note` guarantee is kept by using a separate `miner_note` field (open choice 4); decision 82 and 83 (layers, intuition) are untouched because hints do not write `work.layer_set` or layer items.
- No other event or field changes. `inbox.link_added` is unchanged.

## 8. Risks

- **Anchoring and contamination.** A free-text note can state the label. Mitigations: labels not served; computed `note_names_layer` exclusion; the report states the exclusions. A note that implies the layer without naming it still anchors; this cannot be detected, and the agreement is then an upper bound. The report says so.
- **Held-out leakage.** Notes are free text typed by a person who knows the seeds. The scrub on serving and the planted-marker tests cover identifiers; they do not cover a paraphrased title. Accepted and stated.
- **Canonical versus absorbed works** (IDEA-82 pattern): hints and origin must fold through `canonical_works`; tests 3 and O1-1 cover it.
- **Scheme drift.** Hints go stale when scheme v4 appears; the stale count may hide most of the signal after a rescheme.
- **Selector digest.** Adding a field to `Selector` risks changing every registered digest; the golden test is the guard and the reason for omit-when-empty.
- **Duplicate capture** loses the hint if the form writes nothing for duplicates (current hub behaviour); handled by recording the hint on the existing open item.
- **Scope creep**: hints for seeds, PDFs and imports are excluded by design (open choice 6 and non-goals); each would add a surface.
- **Self-scoring.** Hints become input only where the miner never saw the label; but a hint later used to pick calibration units would reintroduce it. Hints do not enter calibration (open choice 8).

## 9. Open choices for the researcher

Recommended option first in each.

1. **Where the hint is stored.**
   (a) A new event `hint.recorded`, written in the same batch as the capture; later hints and hints on existing works are the same event (recommended).
   (b) Optional fields on `inbox.link_added` only (capture-time only; no later correction, no hints on works that came by search).
   (c) Both: fields on the capture event and the new event for later changes (two sources of truth).

2. **Does a layer hint act as the work's layer?**
   (a) No: it stays a hint; the explorer shows it beside the miner layer; the miner still reads the paper (recommended; keeps the agreement signal clean).
   (b) Yes, automatically: on resolution a `work.layer_set` move is written, so the work is layered at once (saves the miner pass, but the miner is then compared with a move and the signal is lost).
   (c) Only after a click: the hint stays a hint until the researcher promotes it to a move in the explorer.

3. **What miners see.**
   (a) The note only; never the layer or category; calibration passes see nothing (recommended).
   (b) Nothing; hints are used only in the after-the-fact agreement report.
   (c) Note, layer and category (strongest context, but anchors the miner and removes the agreement signal for those works).

4. **Relation to the existing inbox `note`.**
   (a) A separate `miner_note`; the inbox `note` keeps its "never reaches content" rule (recommended).
   (b) One note field for both, with decision 61's guarantee amended to allow serving to miners after screening.

5. **Scheme drift.**
   (a) A hint naming an older scheme version is stale: shown, excluded from agreement, listed by `check`, never rewritten (recommended).
   (b) It is voided when a new scheme is recorded (hidden from the hub).
   (c) It is carried to the new scheme when the layer id exists there unchanged, otherwise stale.

6. **Which origins are tagged.**
   (a) `inbox`, `inbox-agent` and `feed`, with channel and first route (recommended; as the backlog entry).
   (b) Those plus `seed` (seed admission) and `pdf-import` (hand-supplied full text).
   (c) `inbox` and `feed` only, agent captures counted as `inbox`.

7. **Origin in miner selectors.**
   (a) An optional `origins` field on `Selector`, omitted from digest and JSON when empty (recommended; needs the decision row).
   (b) Hub explorer filter and report split only; no selector change.
   (c) New `Population` values (for example `included-final-inbox`), which multiplies populations.

8. **Hints and gold labels for m-layer.**
   (a) Report only: agreement is a calibration signal, never a gold set; the researcher's blind calibration stays the gold (recommended).
   (b) Later, a human act "confirm as gold" on a hint that passes review (separate plan).
   (c) Hints are imported into the calibration set directly (not recommended: unreviewed labels would score the miner).

9. **Who may record hints.**
   (a) Humans only; agents get no write tool (recommended; the hint is the researcher's label).
   (b) Agents may propose a hint flagged `proposed`, shown to the researcher for confirmation (adds a review step and a second status).

10. **When a hint may be recorded.**
    (a) At capture and afterwards, on an item or on a corpus work (`inbox hint`, explorer panel) (recommended).
    (b) At capture only.
    (c) At capture, and afterwards only on a work not yet mined (a hint added after mining could not have influenced it, but is still a label; blocking it loses signal).

11. **Maximum length of the miner note.**
    (a) 500 characters (recommended: longer than the inbox note, short enough to stay a remark).
    (b) 300, as the inbox note.
    (c) 1000.

# Design note: researcher hints at capture and the origin tag (IDEA-81)

Status: built on branch `n4-capture-hints`, not run locally beyond the files named in the commit message; CI decides. Researcher ruling 2026-11-15: build all three parts. Proposed decision rows are at the end; none is recorded in `decisions.md`.

## What was built

1. **Hints at capture.** `inbox_add` (CLI `factory inbox add --layer --category --taxonomy --miner-notes`, MCP `inbox_add` item field `hints`, `factory feed send|add` with the same options, the site `POST /api/feed/add` body field `hints`) takes optional structured hints from the human: a layer of the latest layer scheme, a category of a registered taxonomy and notes addressed to miners (at most 600 characters). They are an optional field `hints` of the existing `inbox.link_added` payload. The field is dropped from serialisation when empty, so an event without hints is byte-identical to one written before; no new event type exists. A human capture only: an agent's hints are refused with nothing written.
2. **Origin tag.** `services/capture_hints.origins_of` computes, per work, `inbox` or `feed` and the capturing channel from the inbox item that resolved to the work (`feed` when a `feed.sent` created the item). Nothing is typed. The explorer payload carries `origin` and `origin_channel`; the explorer sidebar filters on `origin`. A protocol miner use takes `origins` (for example `["inbox", "feed:cli"]`) and then mines only works of those origins.
3. **Hints for miners, behind an option.** The agreement report comes first: `capture_hints.hint_agreement` compares each protocol-listed derived miner's final rows with the hints (layer hints against dimension zero, category hints against the miner of the hint's taxonomy). The hint is served to a miner as context only when its protocol use sets `hint_context` (default off, anchoring risk); the text labels the hint as the researcher's label that may be wrong and asks for an anchor and quote regardless.

## Rigour

- Screeners never see hints or origin: no screening task, view or report reads `inbox_hints` or `origins_of`. `tests/test_capture_hints.py::test_screening_never_sees_the_hints_or_the_origin` serves a whole pass A over a supplied work whose item carried hints and asserts the served text and record keys are the same as for any other work.
- A hint is the researcher's label with actor session and capturing-event time (`inbox_hints.actor_session`, `ts`), not a miner row. The projection keeps a hint only for a human capture.
- A miner given the hint is not scored against it: a miner listed with `hint_context` in ANY recorded protocol version is hint-informed for good (`hint_informed_miners`, over `protocol_lineage`); its agreement is reported as excluded with no counts, even after the option is switched off again. Calibration tasks never receive hints.
- Staleness is computed: a layer hint names the scheme version current at capture, a category hint the taxonomy name and version; when a later version is recorded the hint is stale, is not compared in the agreement report (counted as `stale`) and is marked out of date in the context text.
- A miner's absence values (`not-stated`, `other`, `not-applicable`) are counted as `absent`, never as a disagreement.

## State and replay

- Table `inbox_hints` (item id, event id, time, actor session, layer, scheme version, category, taxonomy, taxonomy version, miner notes) is in `OMITTED_WHEN_EMPTY`, so an old log's state hash is unchanged. Projection version 94 to 95; the twelve test pins moved with it.
- `InboxLinkAdded.hints`, `MinerUse.origins` and `MinerUse.hint_context` are omitted when empty, so old inbox events and old protocol hashes do not change.

## Not done

- The hub does not show hints beside a work yet, and there is no hub page for the agreement report (service and tests only; no CLI report command either).
- Feed origin carries the inbox channel (`cli`), not a feed name; a second feed channel would need its own field.
- A work merged into another keeps the origin of the work id its item resolved to.

## Proposed decision rows

- D-new-A: capture hints are an optional field of `inbox.link_added` (no new event), human only, stale when their scheme or taxonomy version is no longer the latest.
- D-new-B: the origin tag is computed from events, never typed; miner uses may filter on it (`origins`).
- D-new-C: miners receive hints only under the explicit protocol option `hint_context` (default off); a miner ever listed with it is excluded from hint agreement.

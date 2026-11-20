---
name: rf-acquire
description: Use when works were kept at title and abstract and their full texts must be obtained, converted to canonical Markdown and made ready for full-text screening: library adoption, fulltext_fetch, the link inbox, document_read and chat_verify, with conversion left to the researcher.
stage: [acquire]
---

# rf-acquire

Guides the full-text stage: for every work kept at title and abstract ("promoted"), obtain one
document, have it converted to canonical Markdown, check what you will quote, and hand the works
to full-text screening (`rf-screen`, full-text mode). The platform fetches, hashes and records
every attempt; it never calls a model. You choose which works and routes, read the replies and
report them as they are.

## Preconditions

Call `project_status` and read `stage`, `protocol`, `blocking` and `human`.

- Only promoted works enter this stage. A work not kept at title and abstract is refused by
  `fulltext_fetch`; do not look for another way in.
- The protocol must plan full-text screening (`full_text_screening`, R-13). If `blocking` says
  "full-text screening is not planned in the protocol", stop: the protocol must be amended
  (`rf-protocol`, `protocol_amend`) with the researcher's agreement. Without a plan this stage is
  not entered and works stay unread.
- This work runs in a setup session, never in a screening session: a session that has joined a
  pass is refused `fulltext_*`, `library_*`, `inbox_*`, `document_status` and `chat_verify`
  (`document_read` only for the works of its own batch).

## Procedure

1. Call `fulltext_status` to see each promoted work: retrieved, not retrieved (with the reason
   from each route) or unsought.
2. Library first. For a work, call `library_adoptable(work_id)`. If another project of the lab
   holds a document, call `library_adopt` with the row's `source_project` and its `document_id` as
   `source_doc`, plus `role`, `model`, `skill`. It is refused for a work not promoted, a source
   project you may not read, bytes the lab library lacks, or a researcher-supplied document whose
   source its owner has not confirmed (`factory library confirm-source`, the owner's act). Report
   the refusal; do not fetch around a source that awaits confirmation.
3. Otherwise call `fulltext_fetch`. Without `work_ids` it takes promoted works that have no
   document and no attempt yet, up to `limit` (default 20, 1 to 200; more `work_ids` than `limit`
   is refused). Routes are tried in order, each work stopping at its first retrieved attempt:
   `arxiv-html`, `arxiv-source`, `pmc-jats`, `europepmc-jats`, `oa-pdf`. Only open-access sources
   are used. `routes` names routes to try instead, all of them. `refresh` revisits every promoted
   work; a work whose routes all failed is retried only by `refresh`, `routes` or naming it in
   `work_ids`. The platform stores bytes as data and never runs an executable or a script it
   downloads. Repeat until `remaining` in the reply is 0 or only failures remain.
4. A failed route is recorded with its reason, never an error. Report the not-retrieved works with
   their reasons (`fulltext_status`); do not retry the same route in a loop.
5. A work no open route yields: the researcher supplies it.
   - A folder of PDFs the researcher holds: `factory fulltext import FOLDER`; for a bibliography
     with files, `factory import pdfs` then `factory import attach`. These are the researcher's
     acts; a researcher's PDF is imported, never fetched.
   - A link the researcher pastes (arXiv, DOI, OpenAlex): `inbox_add` with `channel="mcp"` and the
     link verbatim (an optional note, no basis). If you found the link yourself in a paper you
     read, `channel="agent"` needs a `basis`, either a `document` basis naming the `document_id`
     and `anchor` of the citing span, or `{"kind": "knowledge"}`, and no note. Then `inbox_resolve`
     (all open items, or `item_ids`) looks each up by identifier as a recorded `supplied` query.
     In `pilot` and `systematic` the protocol's `supplied_links` must accept the submitter, or a
     `deviation_id` recorded with `protocol_deviation` (the researcher's decision) is required.
     `inbox_list` shows items and statuses (`open`, `resolved`, `withdrawn`); a resolve reply
     gives `new`, `in-corpus`, `not-found`, `ambiguous` or `failed`. A new work still passes
     screening; resolving admits nothing. Withdrawing or prioritising an item is the
     researcher's (`factory inbox withdraw`, `factory inbox prioritise`).
6. Conversion. No MCP tool converts. Ask the researcher to run:
   - `factory document converters` (the chosen converter must be ready: Docling for PDF,
     LaTeXML for HTML, pandoc for LaTeX; decision 49; Docling is installed by hand and a
     `uv sync` can remove it);
   - `factory document convert` (optionally `--work W`, `--document D`, `--converter NAME`);
     `factory document convert --restore` regenerates missing or damaged stored Markdown;
   - `factory document status`, then `factory document coverage`, and a read of a sample of
     converted tables by the researcher themselves: table fidelity rests on an automatic score
     and that sample, not on a check.
   Read the result with `document_status` (converted or not, converter, version, anchor counts,
   last failure). A failed conversion is reported with its reason; it is not retried by you.
7. Reading. Call `document_read(work_id, conversion_id=..., after=next_after)` page by page.
   Each segment has an anchor (`s3.2.p4`, `t2.r5.c3`). Before you cite any quote, call
   `chat_verify` with `{work_id, anchor, quote}` items: the quote must occur in exactly that
   anchor's element, and only `accepted` may be cited. A quote is valid for the conversion it was
   checked against; converting again changes the anchors.
8. Full-text calibration is the researcher's act: `factory calibrate draw --stage full-text` and
   `factory calibrate label ... --stage full-text`. The draw is refused until a document is
   converted. Then screening starts in fresh sessions: `rf-screen` in full-text mode
   (`screen_next` with `stage="full-text"`, `screen_record` with one `anchor` and a quote inside
   it). Return to `rf-run` for the next step.

## Human-only acts

Relay the command; never attempt these, and never work around a refusal.

- Conversion (`factory document convert`, `reanchor`, `converters`) and the table sample read.
- Importing and attaching the researcher's own PDFs (`factory fulltext import`,
  `factory import pdfs|attach`), restoring lost files (`factory fulltext restore`).
- Resolving a changed source (`factory fulltext resolve`) and confirming a source for the lab
  library (`factory library confirm-source`).
- Withdrawing or prioritising an inbox item; a deviation that authorises supplied links.
- Calibration labels, disagreements and the audit at full text.

## Refusals and what to do

- "not promoted at title/abstract": the work is outside this stage. Report it.
- A session that has joined a pass is refused: continue in a setup session.
- "converter-unavailable": the researcher's shell lacks the converter or its models; they run
  `factory document converters` and fix the setup. Do not search for another converter.
- `document_read` refuses a work, document or conversion outside the batch of a full-text
  screener, and a missing stored file names `factory document convert --restore`.
- `source-changed` on `factory check`: the source bytes changed; the researcher resolves it.
- An inbox item refused by `supplied_links`: report it; a deviation is the researcher's decision.

## Never

- Never download, run or open an executable, installer or script from a source. A fetched file is
  data for the converter only.
- Never type a count or a hash: read them from `fulltext_status`, `document_status` or the reports.
- Never name a held-out seed or treat any work as held-out, and never look for one. A work is read
  and acquired like any other.
- Never paraphrase a quote to pass `chat_verify` or the screening check; find the span or change
  the claim.
- Never reveal to a screener how a work was found (inbox, route): screeners never see it.

## Done when

No promoted work is unsought, every document is converted, and the full-text counts show nothing
open. Check with `fulltext_status` and `document_status`, and ask the researcher for
`factory status` (full-text counts at zero open), `factory document coverage` and `factory check`
(no `fulltext-unsought`, `conversion-not-chosen`, `source-changed`,
`inbox-open-after-screening`). Report the replies, shortfalls and open `human` items.

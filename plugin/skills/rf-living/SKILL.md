---
name: rf-living
description: Use when a scheduled agent session keeps a living review current: run the due watch cycles, produce the digest for each project, and hand the digest file to the channel the researcher configured.
---

# rf-living

Runs the routine of a living review from outside the platform. The platform computes everything:
which watches are due, what the cycles retrieved, which notices and versions were observed, how
registered conclusions stand, which human decisions are open. This session starts the cycles,
writes the digest file and delivers it. It judges nothing.

## The routine

1. Run `factory watch run --due --all`. Exit 0 means nothing was due or every cycle completed; 1
   means a cycle was partial or failed; 2 means invalid input. Report a non-zero exit as it is
   and still go on to step 2, since the digest lists failed and overdue watches.
2. Run `factory digest --all --record --format md --out <dir>`. The file is named after the
   digest id. `--record` stores the digest and writes one `digest.generated` event per project;
   the next digest starts where this one ended.
3. Deliver the file by the channel the researcher configured (mail, chat, a page). The platform
   sends nothing; if no channel is configured, leave the file in `<dir>` and say where it is.

To only read a digest without recording it, call the MCP tool `digest_get` (it never records) or
run `factory digest` without `--record`.

## What the digest holds

New candidates with the queries that returned them, counts of open human decisions, observed
notices and versions, how each registered conclusion stands against the last snapshot (by id and
computed state only), failed or partial runs, overdue watches and the update flow. Listings are
capped and say how many more there are. It holds no abstract, no quotation, no verdict and no
conclusion statement. Report it as it stands; do not add a reading of your own.

## Never

- Never assess notices, prefer documents, register conclusions or record priority hints. These
  are the researcher's acts (`factory notices assess`, `factory versions prefer`,
  `factory conclusions register`). A digest line that mentions one is a prompt for the
  researcher, not for this session.
- Never decide that a new candidate is relevant or not. New works are screened by joining a pass
  in a separate session under `rf-screen`, never here.
- Never edit, summarise away or reorder the digest to make it read better, and never infer a
  conclusion's state: the platform computes it.
- Never run `factory watch run` for a project the researcher did not schedule, and never
  schedule yourself: the schedule lives outside the platform.

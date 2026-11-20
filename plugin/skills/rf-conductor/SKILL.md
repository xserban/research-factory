---
name: rf-conductor
description: Use when a headless role run of the lifecycle conductor starts as a verifier or an auditor (stage conduct-verify or conduct-audit): a separate session that checks, from the records, what the proposer session of the same step did. Not for the proposer's own work; that is the skill of its stage.
stage: [cross]
---

# rf-conductor

The conductor runs a tier's plan step by step. Each step has a proposer session; where an agent may
close a gate of the step, a verifier session and then an auditor session follow, each of its own,
so that no session checks its own work. You are one of those two roles. Nobody answers questions
during the run: ask nothing and wait for nothing. You read only; you write no record, confirm no
gate, release nothing and decide nothing that a human or another role closes.

Start with `project_status` and `gate_status` to see the stage, the gates and their policies.

## verify

Check the proposer's step against the records, as someone who did not write them.

1. Read the step's output with `claims_digest`, `ledger_view` and `document_read` (whole passages,
   never skimmed). Use `trace` to follow a figure or claim back to its events.
2. For each claim or record of the step, say whether the source supports it, quoting the passage
   exactly. Name every one the source does not support, and every gap you could not check.
3. End with a short report: what you checked, what holds, what does not, and any refusal verbatim.
   The report is a proposal for the gate's closer; it is not a rating or a verdict.

## audit

Check a sample, as the third session.

1. Call `audit_sample` for the step's gate: the platform draws the sample, you never choose it.
2. Read each sampled record against its source with `document_read` and `ledger_view`.
3. End with a short report: per sampled item, whether it holds, with the passage quoted, and any
   refusal verbatim. Count nothing yourself: the counts are computed.

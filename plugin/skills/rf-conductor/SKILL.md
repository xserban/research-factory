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

1. Call `gate_audit_pending`: the conductor has drawn the platform's own sample before your run
   (you never choose it); it lists the sampled acts by audit id, gate and act event id. Where it
   is empty, say so and stop. (`audit_sample` is the screening audit, drawn for a human to label;
   do not use it for this.)
2. Read each sampled act against its source with `document_read` and `ledger_view`.
3. Label each one with `gate_audit_label` (`correct` true or false, a short note quoting the
   passage). The platform refuses a label on the act your own session closed. Your labels are
   recorded apart from a human's: they never enter the overturn rate.
4. End with a short report: per sampled item, whether it holds, with the passage quoted, and any
   refusal verbatim. Count nothing yourself: the counts are computed.

# Design note: hypotheses serve a research question; lineage fill path

Date: 2026-11-23. Status: rulings by the researcher (2026-11-23); the code change in part 1 is not built.

## 1. An optional "serves RQ" field on hypotheses and leads

**Ruling.** Yes. A lead and a hypothesis may name the research question they serve. The field is optional; when absent, the hypothesis engine and the Hypotheses page treat it as RQ4 and RQ5 (design blueprints and idea quality), the two questions the engine fits.

**Why.** No model field links a hypothesis or lead to a question (`docs/research-questions.md` defines RQ1 to RQ5). Evaluation of hypotheses therefore had no stated target, and the page could not group by question.

**Scope of the change (to build, with tests).**
- One optional field, a question id from the project's recorded question set, on the lead and hypothesis registration events. No new event type: the field is added to existing payloads (schema version bumped, old events read as absent).
- The Hypotheses page groups and filters by the field; the lead statistics report per question.
- Validation: an unknown question id is refused at the boundary; absence is allowed.
- Proposed as a decision row on landing.

## 2. Lineage (slice 3b): how the idea graph is filled

**Ruling.** Contribution passes on about ten core papers, then lineage, in separate Claude Code sessions (skills `rf-contributions`, then `rf-lineage`), with a dry check on a copy of the project first. The cheaper importer from the m-summary `builds_on` rows is not built.

**Why.** Relations need a contribution item as their basis (`services/relations.py`), so an import without contributions would bypass the rule that makes a relation checkable. The pilot has no contribution, relation or idea events yet; the Ideas page stays empty until this runs.

**Steps (runbook to write).**
1. Choose the ten papers (core layer; the researcher picks or approves the list).
2. Dry run on a reflink copy of the project: pass A and pass B contributions, then lineage proposals; read the output.
3. Run on the live project in separate sessions per pass (independence is enforced by session).
4. The researcher confirms or rejects relations on the Ideas page.

**Not decided.** Number of papers beyond ten; the token budget for the live run.

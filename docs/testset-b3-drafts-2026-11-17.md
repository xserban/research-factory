# Test set B3: draft hypotheses and questions (for the researcher to select)

Status: drafts by Claude, 2026-11-17 · for `docs/design-note-corpus-search-2026-11-17.md` §10
Source of the drafts: the project question (Q@324dda60, SQ1–SQ5) and the taxonomy category names only. No mined rows, claims or profiles were read to write them, and no paper is named, so the expected works must come from the researcher.

How to use: tick 10–15 (`[x]`); reword freely; for each ticked item fill `expected_works` (and, for hypotheses, `supports` / `undermines` where known). Add your own at the end. Items whose expected works you do not know are better dropped than guessed.

H = hypothesis (Spar), Q = question (Ask or Spar).

## SQ1: research process

- [ ] **B3-01 (H)** AI research systems converge on one stage sequence: literature, ideation, experiment design, implementation, analysis, writing, review.
  expected_works: · supports: · undermines:
- [ ] **B3-02 (Q)** Which systems have a review or verification stage that can send work back to an earlier stage, and what triggers the return?
  expected_works:
- [ ] **B3-03 (H)** Systems covering the full research cycle report weaker quality per stage than systems specialised on two or three stages.
  expected_works: · supports: · undermines:

## SQ2: design approaches and their evidence

- [ ] **B3-04 (H)** Splitting work across agents with specialised roles improves scientific quality over a single LLM with the same tools, when compute is held equal.
  expected_works: · supports: · undermines:
- [ ] **B3-05 (H)** Generate–verify–revise loops improve idea and code quality, but gains saturate after a few rounds.
  expected_works: · supports: · undermines:
- [ ] **B3-06 (H)** Tournament or evolutionary search over hypotheses yields more novel ideas than single-shot generation.
  expected_works: · supports: · undermines:
- [ ] **B3-07 (H)** Tree search over experiment plans improves results over linear agentic execution on ML research tasks.
  expected_works: · supports: · undermines:
- [ ] **B3-08 (H)** Grounding ideation in retrieved literature reduces ideas that are already published, but also reduces novelty.
  expected_works: · supports: · undermines:
- [ ] **B3-09 (H)** Code execution in a sandbox is the design element with the strongest evidence of improving research quality.
  expected_works: · supports: · undermines:
- [ ] **B3-10 (H)** Memory or self-evolving skills carried across runs improve the quality of later runs.
  expected_works: · supports: · undermines:
- [ ] **B3-11 (Q)** Which design approaches are supported only by ablations within the authors' own system, and which by comparison with other systems?
  expected_works:
- [ ] **B3-12 (H)** Fine-tuning or reinforcement learning on research tasks outperforms prompting frontier models.
  expected_works: · supports: · undermines:

## SQ3: the human's role

- [ ] **B3-13 (H)** Human input at goal setting and ideation improves final quality more than human review at the end.
  expected_works: · supports: · undermines:
- [ ] **B3-14 (H)** Papers produced by fully autonomous systems are rated by expert reviewers below the acceptance threshold of main venues.
  expected_works: · supports: · undermines:
- [ ] **B3-15 (H)** In human-in-the-loop systems, scientists mostly validate outputs and rarely contribute new content.
  expected_works: · supports: · undermines:
- [ ] **B3-16 (Q)** Which papers compare a fully automated variant with a human-involved variant of the same system, and what did they find?
  expected_works:
- [ ] **B3-17 (H)** Physical (wet-lab) validation is the stage where human involvement remains indispensable.
  expected_works: · supports: · undermines:

## SQ4: blueprints

- [ ] **B3-18 (Q)** Which combinations of approaches (e.g. role-based agents + tree search + code execution) recur in the best-evaluated systems?
  expected_works:
- [ ] **B3-19 (H)** Planner–executor hierarchies are more robust to long-horizon failures than flat multi-agent conversation.
  expected_works: · supports: · undermines:

## SQ5: assessing research ideas

- [ ] **B3-20 (H)** LLM-as-judge novelty ratings agree poorly with expert ratings.
  expected_works: · supports: · undermines:
- [ ] **B3-21 (H)** LLM-generated ideas are rated more novel than experts' ideas but less feasible.
  expected_works: · supports: · undermines:
- [ ] **B3-22 (H)** Automated reviewers are systematically more lenient than human reviewers.
  expected_works: · supports: · undermines:
- [ ] **B3-23 (Q)** How do systems check an idea's novelty against the literature, and how reliable is that check?
  expected_works:
- [ ] **B3-24 (H)** A system's evaluation of its own output overstates quality compared with independent evaluation.
  expected_works: · supports: · undermines:

## Cross-cutting

- [ ] **B3-25 (H)** Reported failures of AI research systems concentrate in implementation (bugs, fabricated or misreported results), not in ideation.
  expected_works: · supports: · undermines:
- [ ] **B3-26 (H)** General-purpose systems are evaluated mostly on ML and computer-science tasks, so evidence for other sciences is thin.
  expected_works: · supports: · undermines:

## Researcher's own items

- [ ] **B3-27** …

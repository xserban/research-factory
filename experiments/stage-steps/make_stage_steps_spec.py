"""m-stage-steps v1 spec (2026-11-14): inside each research stage of an AI research system, the steps the paper
describes, in its order. Exploratory: no calibration (plan 2026-11-13-lifecycle-stage-deep-dive)."""
import json
STAGES = ["literature-review", "ideation-hypothesis", "experiment-design", "implementation-execution",
          "data-analysis", "paper-writing", "review-verification", "lab-automation", "other"]
f = lambda name, kind, desc, req=False, cmp=False, group="step": {"name": name, "group": group, "kind": kind, "required": req, "description": desc, "compared": cmp}
spec = {
 "name": "m-stage-steps", "version": 1,
 "selector": {"population": "included-ft", "elements": ["paragraph"], "heading_patterns": [], "max_units": None},
 "fields": [
  f("stage", {"type": "enum", "values": STAGES}, "The research stage the step belongs to, from the stages the paper's own system carries out or supports: literature-review, ideation-hypothesis, experiment-design, implementation-execution, data-analysis, paper-writing, review-verification, lab-automation, other. Row key with step_order. The quote is the sentence that shows the step belongs to this stage.", True, True),
  f("step_order", {"type": "enum", "values": [str(i) for i in range(1, 13)]}, "Row key with stage: the position of this step within its stage in the paper's own account, 1 for the first. One row per step, never two rows with the same stage and number. The quote is the sentence that introduces or describes the step.", True, True),
  f("step", {"type": "quote"}, "The paper's own words for what the step does, copied exactly (one clause or sentence).", True),
  f("inputs", {"type": "quote"}, "A sentence that says what the step takes in (documents, a hypothesis, code, data). Omit when the paper does not say.", False),
  f("outputs", {"type": "quote"}, "A sentence that says what the step produces. Omit when the paper does not say.", False),
  f("method", {"type": "quote"}, "A sentence that says how the step is done: the technique, tool, prompt design or model used. Omit when the paper does not say.", False),
  f("actor", {"type": "enum", "values": ["automated", "human-assisted", "human", "not-stated"]}, "Who carries out the step as the paper describes it: automated (the system alone), human-assisted (a person reviews, approves or steers), human, not-stated.", True, True),
  f("check", {"type": "quote"}, "A sentence that says how the paper validates or checks the result of this step (a verifier, a reviewer, a test, a human check). Omit when the paper does not say.", False),
  f("limits", {"type": "quote"}, "A sentence in which the paper says what goes wrong or is limited in this step (a failure mode, an error rate, a stated limitation). Omit when the paper does not say.", False),
 ],
 "row_key_fields": ["stage", "step_order"], "row_anchor_fields": [], "conditionals": [],
 "evidence": {"min_quotes_per_record": 1, "enum_needs_quote": True, "absence_values": ["not-stated"]},
 "procedure": "rf-mine",
 "regime": {"passes": 2, "calibration_size": 10, "recall_min": 0.8, "field_agreement_min": 0.9},
 "rationale": "v1 (2026-11-14; plan 2026-11-13-lifecycle-stage-deep-dive): the steps inside each research stage of an AI research system as the paper describes them, with inputs, outputs, method, actor, how the step is checked and what limits it; whole text; core works; stage axis is the 9 stages of m-stages v1. EXPLORATORY: no calibration, for reading, not evidence. A paper that describes no steps is closed with no rows and a reason.",
 "comparability_keys": [], "citation_patterns": [],
}
json.dump(spec, open("m-stage-steps-v1-spec.json", "w"), indent=1)

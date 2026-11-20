# ruff: noqa: E501
"""Stage cards 5 to 9 of the tutorial: extract, understand, develop, write, maintain.

Every command, tool, skill and page named here is checked by `tests/test_learn_content.py`.
"""

from factory.learn.model import Actor, Done, StageCard, Step, cli, page, skill, tool

H, A, S = Actor.HUMAN, Actor.AGENT, Actor.SCRIPT

EXTRACT = StageCard(
    id="extract",
    title="Extract and mine",
    goal="Read typed, quoted values from the converted texts, twice and independently, and measure how far the two readings agree.",
    acts=(A, H, S),
    gates=(
        "You write the extraction schema into the protocol before reading starts.",
        "You label the audit and calibration samples and resolve disagreements.",
        "You admit a miner as evidence; until then its rows are exploratory.",
    ),
    steps=(
        Step(
            H,
            "Record or amend the protocol with the extraction schema, from a file.",
            (cli("protocol record"), cli("protocol amend")),
        ),
        Step(
            A,
            "Pass A takes a unit, records values with quotes and claims. Pass B does the same in another session.",
            (skill("rf-extract"), tool("extract_next"), tool("extract_record")),
        ),
        Step(
            S,
            "Read the status and the agreement of the two passes.",
            (tool("extraction_status"), cli("extract agreement")),
        ),
        Step(H, "Resolve what the passes disagree on.", (cli("extract resolve"),)),
        Step(
            H,
            "Draw an audit sample, label it, and read the report.",
            (cli("extract audit-sample"), cli("extract audit-label"), cli("extract audit-report")),
        ),
        Step(
            H,
            "For a miner: register its design, then draw and label its calibration set.",
            (cli("miner register"), cli("miner calibrate draw"), cli("miner calibrate label")),
        ),
        Step(
            A,
            "Mine the selected anchors in two passes, in separate sessions.",
            (skill("rf-mine"), tool("mine_next"), tool("mine_record")),
        ),
        Step(H, "Admit a calibrated miner as evidence.", (cli("miner admit"),)),
    ),
    page=page("data"),
    done=Done(
        "No unit is left pending, no disagreement is unresolved, and the audit report exists.",
        (cli("extract status"), cli("extract agreement"), page("data")),
    ),
    mistakes=(
        "Passes A and B in one session are refused. Each pass needs its own Claude session.",
        "Extraction without a schema in the protocol is refused.",
        "A value that does not appear in its quote is rejected.",
        "A miner that the protocol does not list is not served any task.",
        "Reading agreement as correctness. Agreement measures consistency; the audit checks the values.",
    ),
    rigour=(
        "Each value comes with a quote that the platform checks against the pinned document, and numbers are checked against the quote.",
        "The schema is fixed in the protocol before the reading.",
        "Agreement is computed and the audit is a human check.",
        "Rows of an uncalibrated or unadmitted miner stay exploratory and are not counted in the evidence report.",
    ),
    next_id="understand",
)

UNDERSTAND = StageCard(
    id="understand",
    title="Understand the field",
    goal="Record what each work contributes and builds on, and look at the corpus through graphs, regions and views.",
    acts=(A, H, S),
    gates=(
        "You confirm relations and named ideas; unconfirmed inferred relations stay out of the default views.",
        "You review interpretations, which are labelled as model-written.",
    ),
    steps=(
        Step(
            A,
            "Record the contribution items of the included works in two passes.",
            (skill("rf-contributions"), tool("contribution_next"), tool("contribution_record")),
        ),
        Step(
            A,
            "Propose relations between works and named ideas, with a quote.",
            (skill("rf-lineage"), tool("relation_propose"), tool("idea_propose")),
        ),
        Step(H, "Confirm or reject them.", (cli("relations confirm"), cli("ideas confirm"))),
        Step(
            A,
            "Write an interpretation, labelled as such.",
            (skill("rf-intuition"), tool("interpretation_record")),
        ),
        Step(H, "Review the interpretations.", (cli("interpretations review"),)),
        Step(A, "Propose regions of interest.", (skill("rf-regions"), tool("region_propose"))),
        Step(
            S,
            "Look at the views and the graph, computed from confirmed items.",
            (cli("view onion"), cli("graph query")),
        ),
    ),
    page=page("graph"),
    done=Done(
        "Every proposed relation and idea is confirmed or rejected, and the graph and views build from them.",
        (cli("relations list"), cli("ideas list"), page("graph")),
    ),
    mistakes=(
        "Treating an inferred relation as stated. A relation is stated only when its quote is verified.",
        "Expecting an interpretation to count as evidence. It is labelled, and a draft may not cite it as support.",
        "A relation target that does not match the cited entry is stored as inferred.",
        "Reading the technique landscape as a result. It is a map for ideas.",
        "Forgetting to confirm. Unconfirmed items do not appear in the default graph.",
    ),
    rigour=(
        "Interpretation, background concepts and the technique landscape carry a layer label and never change a count.",
        "The graph is built from confirmed items only.",
        "A relation is stated only with a verified quote; otherwise it is inferred.",
    ),
    next_id="develop",
)

DEVELOP = StageCard(
    id="develop",
    title="Reason: leads, spar and hypotheses",
    goal="Turn the corpus into candidate leads, argue each for and against with checked quotes, and register a falsifiable hypothesis before it is tested.",
    acts=(A, H, S),
    gates=(
        "You rate the arguments of a spar and write the balance, on the Chat page (Your rating rows and the balance form) or on the command line.",
        "You decide each lead, and conclude or abandon a hypothesis.",
        "Whether an agent may pass the lead and registration gates depends on the gate policies of the project.",
    ),
    steps=(
        Step(
            A,
            "Record a lead with its trigger in the corpus and its framework.",
            (skill("rf-hypothesis-engine"), tool("lead_record")),
        ),
        Step(
            A,
            "Argue for and against in one chat session, quote by quote. A spar can also start from a contradiction pair.",
            (skill("rf-chat"), tool("chat_candidates"), tool("sheet_open")),
        ),
        Step(
            H,
            "Rate each argument and write the balance: on the Chat page, beside each quote and its paragraph, or on the command line.",
            (page("chat"), cli("sheets rate"), cli("sheets balance"), cli("answers rate")),
        ),
        Step(
            H,
            "Promote, park or discard a lead.",
            (cli("leads promote"), cli("leads park"), cli("leads discard")),
        ),
        Step(
            A,
            "Draft a hypothesis, then have it reviewed in another session.",
            (tool("hypothesis_draft"), tool("hypothesis_review")),
        ),
        Step(A, "Register the hypothesis before any test.", (tool("hypothesis_register"),)),
        Step(
            H,
            "The platform computes the outcome; you conclude.",
            (cli("hypotheses evaluate"), cli("hypotheses conclude")),
        ),
    ),
    page=page("chat"),
    done=Done(
        "A hypothesis is registered with its falsifier and has an evaluated outcome.",
        (cli("hypotheses show"), cli("hypotheses list"), page("chat")),
    ),
    mistakes=(
        "A lead cannot cite a sheet until both sections are closed and your balance is written.",
        "Agents cannot rate or balance. Waiting for you is intended; rate on the Chat page or on the command line.",
        "A lead without a trigger or a framework is refused.",
        "The same session cannot draft and register, or review its own draft.",
        "Reading queue scores as evidence. They are labelled exploratory.",
    ),
    rigour=(
        "A hypothesis is registered before it is tested; the platform computes the outcome.",
        "Discarded and parked leads stay in the log and show as prior leads.",
        "The proposer never evaluates its own proposal.",
        "Registrations by an agent are labelled and are not reported as confirmatory.",
    ),
    next_id="write",
)

WRITE = StageCard(
    id="write",
    title="Report and write",
    goal="Derive every number of the evidence base from events and write prose that a different session has verified sentence by sentence.",
    acts=(S, A, H),
    gates=(
        "You release a draft.",
        "You read the findings of the check.",
    ),
    steps=(
        Step(
            S,
            "Compute the reports: PRISMA, methods and evidence.",
            (tool("report_prisma"), tool("report_methods"), tool("report_evidence")),
        ),
        Step(
            S,
            "Check the project and trace a sentence back to its source.",
            (cli("check"), cli("trace")),
        ),
        Step(
            A,
            "Create a draft and write it sentence by sentence against the outline.",
            (skill("rf-write"), tool("draft_create"), tool("draft_write")),
        ),
        Step(
            A,
            "Verify each sentence in a different session.",
            (skill("rf-verify"), tool("draft_verify_next"), tool("draft_verify_record")),
        ),
        Step(H, "Audit and release the draft.", (cli("draft audit"), cli("draft release"))),
        Step(
            S, "Export the bibliography and the data.", (cli("export bibtex"), cli("export prisma"))
        ),
    ),
    page=page("write"),
    done=Done(
        "Every sentence is verified by a session other than the writer, the release is recorded, and check shows no errors for the project's mode.",
        (cli("draft status"), cli("check"), page("write")),
    ),
    mistakes=(
        "The writer and the verifier in one session are refused.",
        "A number in a sentence that is not in a cited support is refused.",
        "Reading the evidence report before the extraction audit is done.",
        "Expecting rows of an unadmitted miner in the report. Only admitted miners appear.",
        "Treating the finders as findings. They point to gaps and conflicts, and the pairs await your decision.",
    ),
    rigour=(
        "Every number is computed from events; none is typed.",
        "Every sentence links to the spans it cites, and a layer interpretation is not eligible as support.",
        "Trace follows a sentence back to a question element.",
    ),
    next_id="maintain",
)

MAINTAIN = StageCard(
    id="maintain",
    title="Keep the review living",
    goal="Run the declared watch cycles, read what is new, and decide what changes the review.",
    acts=(S, A, H),
    gates=(
        "You choose the digest channel.",
        "You assess notices such as retractions and newer versions.",
        "You accept or reject curation proposals.",
    ),
    steps=(
        Step(
            H,
            "Read the watch plan and run or check a cycle.",
            (cli("watch plan"), cli("watch run"), cli("watch status")),
        ),
        Step(
            A,
            "A scheduled session runs the cycle; the script judges nothing.",
            (skill("rf-living"), tool("watch_run"), tool("feed_run")),
        ),
        Step(S, "Read the digest of the cycle.", (tool("digest_get"),)),
        Step(
            H,
            "Assess notices and decide curation proposals.",
            (cli("notices assess"), cli("curation decide")),
        ),
        Step(H, "Record a living snapshot.", (cli("living snapshot"),)),
    ),
    page=page("living"),
    done=Done(
        "Each declared watch has a recorded cycle within its cadence.",
        (cli("watch status"), page("living")),
    ),
    mistakes=(
        "Running a watch outside its planned cadence.",
        "Expecting the hub to update without the served process. A static build is a snapshot.",
        "Skipping deduplication after new records arrive.",
        "Ignoring a notice. A retracted or replaced work stays open to your assessment.",
        "Treating curation proposals as decided. They change the protocol or a skill only when you accept them.",
    ),
    rigour=(
        "New papers enter as records and are screened by the protocol's rules.",
        "A conclusion stays open to revision when a notice arrives.",
        "Lessons are computed from audits, disagreements and failed runs.",
    ),
    next_id=None,
)

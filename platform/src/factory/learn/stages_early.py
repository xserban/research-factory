# ruff: noqa: E501
"""Stage cards 1 to 4 of the tutorial: frame, gather, screen, acquire (ids of `site_catalog`).

Every command, tool, skill and page named here is checked by `tests/test_learn_content.py`.
"""

from factory.learn.model import Actor, Done, StageCard, Step, cli, page, skill, tool

H, A, S = Actor.HUMAN, Actor.AGENT, Actor.SCRIPT

FRAME = StageCard(
    id="frame",
    title="Frame the question",
    goal="Turn your goal into a recorded question, a list of known papers, a measured test search and a confirmed protocol.",
    acts=(H, A, S),
    gates=(
        "You select one suggestion per level (goal, questions, plan, seeds, probe, protocol); the agent only proposes.",
        "You confirm the PRESS review of the search; the agent may not.",
        "The platform draws the hold-out split of the seeds; no agent is told which seeds are held out.",
    ),
    steps=(
        Step(
            H,
            "Create the project and choose its mode once: exploratory, pilot or systematic. The mode cannot be changed later.",
            (cli("init"),),
        ),
        Step(
            A,
            "Ask Claude to start. The skill rf-run reads the project status and hands over to the skill of the current stage.",
            (skill("rf-run"), tool("project_status")),
        ),
        Step(
            A,
            "The agent proposes choices as ticked lists, level by level.",
            (skill("rf-develop"), tool("decision_suggest")),
        ),
        Step(
            H,
            "Select what you accept, or list and show the sets.",
            (cli("decide select"), cli("decide list"), cli("decide show")),
        ),
        Step(
            A,
            "Record the question: your goal in your own words, its slots and its non-goals.",
            (skill("rf-frame"), tool("question_record")),
        ),
        Step(
            A,
            "Add the papers you already know as seeds, positives and negatives, by identifier.",
            (skill("rf-probe"), tool("seed_add")),
        ),
        Step(
            A,
            "Test a narrow and a broad query on each source. In pilot and systematic the platform draws the hold-out split first.",
            (tool("probe_run"),),
        ),
        Step(
            H,
            "In exploratory mode the split is not drawn automatically; draw it yourself once the seeds are resolved.",
            (cli("seeds split"),),
        ),
        Step(
            A,
            "Record the protocol as a draft, then as ready.",
            (skill("rf-protocol"), tool("protocol_record")),
        ),
        Step(
            A,
            "A separate subagent reviews the search strategy (PRESS).",
            (tool("protocol_press_review"),),
        ),
        Step(H, "Answer each PRESS finding and confirm.", (cli("protocol confirm-press"),)),
    ),
    page=page("protocol"),
    done=Done(
        "The status shows a ready protocol with PRESS confirmed and the stage has moved on to search.",
        (cli("status"), cli("protocol show"), page("protocol")),
    ),
    mistakes=(
        "In pilot and systematic mode, recording a question, seeds, probe or protocol without citing a selected decision is refused. The agent must wait for your selection.",
        "A search is refused until the PRESS review is confirmed. Only you can confirm it.",
        "A ready protocol cannot be recorded again. Change it by an amendment with a reason, and name exactly the criteria that changed.",
        "The split needs enough positive seeds, all resolved, before it can be drawn. A probe fails when the seeds are too few or unresolved.",
        "A question is refused when more than half of its slots are open or when it has too few non-goals. A new question version makes the protocol stale until it is amended.",
    ),
    rigour=(
        "The question and the protocol are written before any reading and are versioned.",
        "Held-out seeds are never shown to an agent and the probe never measures them.",
        "Every choice that is yours is made by you; the agent proposes and the record shows your selection.",
        "In exploratory mode the protocol gate is off, so a search can run without a protocol. The rest of the record is still kept.",
    ),
    next_id="gather",
)

GATHER = StageCard(
    id="gather",
    title="Search and gather",
    goal="Run every planned query on every declared source, merge duplicates, and bring in references and outside links as recorded searches.",
    acts=(A, S, H),
    gates=(
        "A query the protocol does not plan needs a recorded deviation.",
        "You decide when a snowball round really runs by selecting a recorded decision; the first call is a dry run.",
        "Imports and links from outside the search are admitted or resolved by you.",
    ),
    steps=(
        Step(
            A,
            "Run each planned query exactly as the protocol states it. The skill rf-search-run guides it, including the human gates.",
            (skill("rf-search-run"), tool("search_run")),
        ),
        Step(
            A,
            "A PubMed query above its 9,999 record limit is cut into slices that together cover it.",
            (tool("search_slice"),),
        ),
        Step(
            S,
            "Read what was reported against what was retrieved, and any shortfall.",
            (cli("report search"), tool("report_search")),
        ),
        Step(
            A,
            "Merge the same work seen in several sources. Run it again after every new search or chase.",
            (tool("dedup_run"),),
        ),
        Step(
            H, "List the merges and revert a wrong one.", (cli("dedup list"), cli("dedup revert"))
        ),
        Step(
            H,
            "Decide the pairs of versions of one work (for example a preprint and its published version) that the platform lists for you.",
            (cli("dedup pairs"), cli("dedup pair")),
        ),
        Step(
            H,
            "Import a list or files you hold, then resolve and admit them.",
            (cli("import list"), cli("import resolve"), cli("import admit")),
        ),
        Step(
            A,
            "Put a link from outside the search in the inbox; it is looked up and recorded, never added silently.",
            (skill("rf-search"), tool("inbox_add"), tool("inbox_resolve")),
        ),
        Step(
            A,
            "Take the reference lists of included works into the corpus. A snowball round is a dry run unless you select the decision that sends it.",
            (skill("rf-references"), tool("references_extract"), tool("snowball_round")),
        ),
        Step(
            H,
            "Decide the weak reference links the platform leaves open.",
            (cli("references decide"),),
        ),
    ),
    page=page("sources"),
    done=Done(
        "Every planned query has a complete run, any shortfall is explained, and the status stage is title and abstract screening or later.",
        (cli("status"), cli("check"), page("sources")),
    ),
    mistakes=(
        "A query typed with other filters or whitespace than the plan is a different query and needs a deviation.",
        "A new question version makes the protocol stale and searches are refused until it is amended.",
        "A partial or failed run is a shortfall. Resume or slice it, or check reports it as unexplained.",
        "A search is refused when the budget for requests is used up. You set the budget.",
        "Forgetting to run deduplication after a round. Screening is blocked until the corpus is reconciled.",
    ),
    rigour=(
        "Raw pages are archived before they are parsed.",
        "Counts of reported and retrieved records are computed, and a shortfall is stated, not hidden.",
        "A merge is recorded and can be reverted.",
        "Candidates from a chase enter as records and are screened like any other.",
        "Do not expect every reference to resolve. A part stays unresolved and is counted.",
    ),
    next_id="screen",
)

SCREEN = StageCard(
    id="screen",
    title="Screen titles and abstracts",
    goal="Give every merged work an outcome from its title and abstract, by two independent passes checked against your own labels.",
    acts=(H, A, S),
    gates=(
        "You draw and label the calibration set before screening starts.",
        "You resolve every disagreement between the two passes.",
        "You label an audit sample of what the passes agreed on.",
    ),
    steps=(
        Step(
            H,
            "Draw the calibration set once, then label each item.",
            (cli("calibrate draw"), cli("calibrate label")),
        ),
        Step(
            A,
            "Pass A takes a batch, decides each work with a verbatim quote, and records it. Repeat until no batch is left.",
            (skill("rf-screen"), tool("screen_next"), tool("screen_record")),
        ),
        Step(
            A,
            "Pass B runs in a different Claude session, with a different model.",
            (skill("rf-screen"), tool("screen_next")),
        ),
        Step(
            H,
            "List the disagreements and resolve them.",
            (cli("screen disagreements"), cli("screen resolve")),
        ),
        Step(
            H,
            "Draw an audit sample, label it, and read the report.",
            (cli("audit sample"), cli("audit label"), cli("audit report")),
        ),
        Step(
            S,
            "Compute the PRISMA flow and the methods statement.",
            (cli("report prisma"), tool("report_prisma"), cli("report methods")),
        ),
    ),
    page=page("flow"),
    done=Done(
        "No work is pending at title and abstract, no human item is open for calibration, disagreements or audit, and the PRISMA flow adds up.",
        (cli("status"), cli("report prisma"), page("flow")),
    ),
    mistakes=(
        "The agent cannot draw the calibration set. Screening is refused until you have drawn and labelled it.",
        "The quote must be found word for word in the title or abstract. Paraphrase is rejected.",
        "One session cannot join both passes, and two passes may not share a model.",
        "An exclusion needs an exclusion criterion from the protocol.",
        "Pass A can be blocked by a sensitivity below the protocol's threshold. Then the protocol must be amended by you.",
    ),
    rigour=(
        "Two passes with different framing and order, in different sessions.",
        "Each decision carries a quote that the platform checks against the text.",
        "Your calibration labels measure the agents; agreement is reported and never resolved automatically.",
        "A small audit sample of agreed decisions is labelled by a person.",
        "In exploratory mode there is no calibration threshold.",
    ),
    next_id="acquire",
)

ACQUIRE = StageCard(
    id="acquire",
    title="Get and convert full texts",
    goal="Obtain the documents of the works kept at title and abstract, convert them to one canonical text each, and screen them at full text.",
    acts=(A, H, S),
    gates=(
        "Conversion is yours; no agent tool runs it.",
        "You attach documents that no route can fetch, and resolve a changed source.",
        "Calibration, disagreements and audit repeat at full text and are yours.",
    ),
    steps=(
        Step(
            A,
            "Check whether another project of the lab already holds the document, and adopt it.",
            (tool("library_adoptable"), tool("library_adopt")),
        ),
        Step(
            A,
            "Otherwise fetch it by the open routes, then read the status.",
            (tool("fulltext_fetch"), tool("fulltext_status")),
        ),
        Step(H, "Import PDFs you hold from a folder.", (cli("fulltext import"),)),
        Step(
            H,
            "Check that a converter is ready, convert, and read a sample of converted tables yourself.",
            (cli("document converters"), cli("document convert"), cli("document status")),
        ),
        Step(A, "Read a converted document in anchored pieces.", (tool("document_read"),)),
        Step(
            H,
            "Draw and label a calibration set for the full-text stage, as at title and abstract.",
            (cli("calibrate draw"),),
        ),
        Step(
            A,
            "Screen at full text. The quote must lie inside one anchor.",
            (skill("rf-screen"), tool("screen_next"), tool("screen_record")),
        ),
    ),
    page=page("sources"),
    done=Done(
        "No promoted work is left unsought, every document is converted, and the full-text counts show nothing open.",
        (cli("fulltext status"), cli("document coverage"), page("sources")),
    ),
    mistakes=(
        "The protocol must declare a full-text screening plan. Without one the stage is skipped and only warnings say works are unread.",
        "A converter is missing in your shell. Check with the converters command before you convert.",
        "Fetching a work that was not kept at title and abstract is refused, as is more works than the limit.",
        "A reading task is limited to the works and conversions of its own batch.",
        "A quote is valid for the conversion it was checked against. Converting again changes the anchors.",
    ),
    rigour=(
        "Every fetch attempt is recorded, and the converter is pinned per document.",
        "The library of documents is not committed to git.",
        "A full-text decision cites one anchor and a quote inside it, checked by the platform.",
        "Table fidelity rests on an automatic score and on your sample read, not on a check.",
    ),
    next_id="extract",
)

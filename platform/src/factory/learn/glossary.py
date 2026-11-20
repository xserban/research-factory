# ruff: noqa: E501
"""Plain terms of the tutorial. Names are those the platform uses today; the philosophy-of-science
names of `docs/naming-glossary.md` are a proposal and are not used."""

from factory.learn.model import Term

GLOSSARY: tuple[Term, ...] = (
    Term("event", "One recorded act in the append-only log, with its actor, time and provenance."),
    Term("index", "The database built from the events. It can be rebuilt at any time."),
    Term(
        "protocol",
        "The written plan of the review: criteria, sources, queries, screening and extraction plans. A change is an amendment with a reason.",
    ),
    Term(
        "PRESS",
        "A peer review of the search strategy, done by a separate agent and confirmed by you.",
    ),
    Term("seed", "A paper you already know is relevant or irrelevant, named by identifier."),
    Term(
        "held-out seed",
        "A seed kept out of every agent view to test whether the search finds what it was not shown.",
    ),
    Term("probe", "A test of a query on the seeds before the real search."),
    Term("deviation", "A recorded departure from the protocol, such as an unplanned query."),
    Term(
        "pass",
        "One independent reading of the same items. Pass A and pass B run in separate sessions.",
    ),
    Term("calibration set", "A sample you label to measure how well the agents screen."),
    Term("audit sample", "A sample of agreed decisions that you label as a check."),
    Term(
        "agreement",
        "How far two passes give the same outcome. It measures consistency, not correctness.",
    ),
    Term("anchor", "The stable address of a paragraph or cell in a converted document."),
    Term(
        "canonical Markdown",
        "The one converted text of a document, pinned with the converter that made it.",
    ),
    Term("miner", "A registered, versioned design for reading typed fields from selected anchors."),
    Term("exploratory", "Labelled output that is not evidence, such as uncalibrated miner rows."),
    Term(
        "snowball",
        "Following the reference lists of included works to find new candidates, as a recorded search.",
    ),
    Term("lead", "A candidate research direction, tied to a trigger in the corpus."),
    Term(
        "spar",
        "An argument for and against a claim, with checked quotes, that you rate and balance.",
    ),
    Term("hub", "The local web pages built from the events. Open the Learn page first."),
)

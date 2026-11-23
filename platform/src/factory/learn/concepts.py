"""The short list of ideas that the whole tutorial rests on."""

from factory.learn.model import Concept

CONCEPTS: tuple[Concept, ...] = (
    Concept(
        "events",
        "Events are the source of truth",
        "Every act is an event appended to a log. Nothing is edited or deleted; a correction "
        "supersedes. The database is a copy that can be rebuilt from the log, and every count "
        "you see is computed from it.",
    ),
    Concept(
        "no-model",
        "The platform never calls a model",
        "Claude reads and judges through tools. The platform stores, checks quotes and numbers, "
        "and counts. Each judgement records the model, the skill version and the exact input.",
    ),
    Concept(
        "modes",
        "Exploratory, pilot and systematic",
        "You choose the mode once, at creation. Exploratory has few gates and is for mapping a "
        "field. Pilot adds two passes, your labels and advisory agreement. Systematic enforces "
        "all of it. Exploratory outputs are labelled and are not evidence.",
    ),
    Concept(
        "gates",
        "Human gates",
        "Some acts are yours alone: selecting choices, confirming the search review, labelling "
        "samples, resolving disagreements, admitting a miner, rating arguments. Agents propose. "
        "The status command lists what waits for you, each with its command. Under the supervised "
        "and autonomous levels an agent may close some of them, and your review is deferred.",
    ),
    Concept(
        "human-in-log",
        "Who is the human in the log",
        "The command line always writes a human actor and cannot tell you from an agent with a "
        "shell. MCP relay tools write a human actor for acts you confirm in the client (decision "
        "37.6). So a gate is attribution plus the platform refusing agent actors on the MCP path, "
        "not authentication. Resting on documentation only: the go-ahead before a real snowball "
        "round, and that an agent-registered hypothesis is never reported as confirmatory.",
    ),
    Concept(
        "tiers",
        "Tiers: how deep a study goes",
        "A tier is chosen at creation, with the rigour mode it implies. A brief is a quick, capped "
        "read; a deep study adds independent checks; pilot and systematic run the full method. "
        "What a tier skips is computed from its plan and printed in every report, so a quick study "
        "is never read as a systematic one. The page How this study runs shows the plan.",
    ),
    Concept(
        "autonomy-levels",
        "Autonomy levels: who closes the gates",
        "Attended is the default: you close every decision gate. Supervised lets an independent "
        "agent session close the gates that allow it, with a sampled audit. Autonomous lets an "
        "orchestrated run do so and defers your review. A gate never drops below its floor, and "
        "an agent-closed act is labelled not human-confirmed until you review it. The trust "
        "ledger counts how often your review overturns an agent, and a gate that does so too "
        "often pauses the run.",
    ),
    Concept(
        "holdout",
        "Held-out seeds",
        "Some of the papers you name are held back. They measure whether the search finds papers "
        "it was never shown. Agents cannot see which seeds are held out, so do not ask them.",
    ),
    Concept(
        "layers",
        "Layers",
        "Rows from uncalibrated miners, interpretations, taxonomies and the technique landscape "
        "carry a layer label. They are shown beside the evidence and never counted in a report.",
    ),
    Concept(
        "sessions",
        "One Claude session per pass",
        "Screening, extraction, mining and contribution items are read twice. Each pass needs its "
        "own Claude session, and a session that joined a pass cannot call other tools.",
    ),
    Concept(
        "look",
        "Where to look",
        "The status command names the stage and your queue. The check command lists what is "
        "wrong. The trace command follows a sentence to its source. The hub shows the rest.",
    ),
)

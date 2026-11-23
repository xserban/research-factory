"""Hub UI assets, colour tokens, glossary and labels.

Invariants:
- ``ASSETS`` maps a served name to a package-relative path and a content type. Every
  served name resolves to a file inside ``factory/hub_ui/``; unknown names raise KeyError.
- ``asset_version()`` is a pure function of the asset bytes, so an immutable versioned
  URL changes exactly when a served file changes.
- ``THEMES`` mirrors the ``:root`` token blocks of ``hub_ui/kit.css`` for the ten tokens
  that carry contrast. A test parses kit.css and fails on any difference.
- ``GLOSSARY`` and ``LABELS`` are copies of the ones in ``hub_ui/shell.js``; the key sets
  are tested to agree. They become the source of truth in a later step.
- No function here calls a model or reads the network.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Final

from factory.services.hub_mining import GAP_VALUES

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


@dataclass(frozen=True)
class ThemeSpec:
    """One colour theme. Token values are hex strings as written in kit.css."""

    id: str
    label: str
    bg: str
    surface: str
    raised: str
    fg: str
    mut: str
    dim: str
    acc: str
    acc_ink: str
    inc: str
    exc: str


THEMES: Final[tuple[ThemeSpec, ...]] = (
    ThemeSpec(
        id="dark",
        label="Hub dark",
        bg="#0e0f12",
        surface="#15171c",
        raised="#1c1f26",
        fg="#ecebe6",
        mut="#a6abb4",
        dim="#80858f",
        acc="#5fd4e8",
        acc_ink="#071316",
        inc="#7fd6a8",
        exc="#f0907f",
    ),
    ThemeSpec(
        id="light",
        label="Hub light",
        bg="#f6f4ef",
        surface="#fffdf8",
        raised="#efece4",
        fg="#1b1a17",
        mut="#55524b",
        dim="#6b675f",
        acc="#0b6e7f",
        acc_ink="#ffffff",
        inc="#1f7a4c",
        exc="#b23a2a",
    ),
    ThemeSpec(
        id="tokyo-night",
        label="Tokyo Night",
        bg="#1a1b26",
        surface="#1f2335",
        raised="#292e42",
        fg="#c0caf5",
        mut="#a9b1d6",
        dim="#8b95c4",
        acc="#7aa2f7",
        acc_ink="#1a1b26",
        inc="#9ece6a",
        exc="#f7768e",
    ),
    ThemeSpec(
        id="catppuccin-mocha",
        label="Catppuccin Mocha",
        bg="#1e1e2e",
        surface="#181825",
        raised="#313244",
        fg="#cdd6f4",
        mut="#bac2de",
        dim="#a6adc8",
        acc="#cba6f7",
        acc_ink="#1e1e2e",
        inc="#a6e3a1",
        exc="#f38ba8",
    ),
    ThemeSpec(
        id="gruvbox",
        label="Gruvbox",
        bg="#282828",
        surface="#32302f",
        raised="#3c3836",
        fg="#ebdbb2",
        mut="#d5c4a1",
        dim="#a89984",
        acc="#fe8019",
        acc_ink="#282828",
        inc="#b8bb26",
        exc="#fc6857",
    ),
    ThemeSpec(
        id="nord",
        label="Nord",
        bg="#2e3440",
        surface="#3b4252",
        raised="#434c5e",
        fg="#eceff4",
        mut="#d8dee9",
        dim="#aab4c8",
        acc="#88c0d0",
        acc_ink="#2e3440",
        inc="#a3be8c",
        exc="#dc8a91",
    ),
    ThemeSpec(
        id="rose-pine",
        label="Rosé Pine",
        bg="#191724",
        surface="#1f1d2e",
        raised="#26233a",
        fg="#e0def4",
        mut="#c4c1da",
        dim="#908caa",
        acc="#c4a7e7",
        acc_ink="#191724",
        inc="#9ccfd8",
        exc="#eb6f92",
    ),
    ThemeSpec(
        id="lcars",
        label="LCARS",
        bg="#000000",
        surface="#0b0910",
        raised="#1c1628",
        fg="#ffcc99",
        mut="#ffcc99",
        dim="#cc99cc",
        acc="#ff9900",
        acc_ink="#000000",
        inc="#99cc99",
        exc="#ff7777",
    ),
)

# Served name -> (package-relative path under factory/, content type).
ASSETS: Final[dict[str, tuple[str, str]]] = {
    "kit.css": ("hub_ui/kit.css", "text/css; charset=utf-8"),
    "shell.js": ("hub_ui/shell.js", "text/javascript; charset=utf-8"),
    "pages/overview.js": ("hub_ui/pages/overview.js", "text/javascript; charset=utf-8"),
    "pages/corpus.js": ("hub_ui/pages/corpus.js", "text/javascript; charset=utf-8"),
    "pages/flow.js": ("hub_ui/pages/flow.js", "text/javascript; charset=utf-8"),
    "pages/lenses.js": ("hub_ui/pages/lenses.js", "text/javascript; charset=utf-8"),
    "pages/explore.js": ("hub_ui/pages/explore.js", "text/javascript; charset=utf-8"),
    "pages/graph.js": ("hub_ui/pages/graph.js", "text/javascript; charset=utf-8"),
    "pages/landscape.js": ("hub_ui/pages/landscape.js", "text/javascript; charset=utf-8"),
    "pages/miners.js": ("hub_ui/pages/miners.js", "text/javascript; charset=utf-8"),
    "pages/data.js": ("hub_ui/pages/data.js", "text/javascript; charset=utf-8"),
    "pages/findings.js": ("hub_ui/pages/findings.js", "text/javascript; charset=utf-8"),
    "pages/contradictions.js": (
        "hub_ui/pages/contradictions.js",
        "text/javascript; charset=utf-8",
    ),
    "pages/chat.js": ("hub_ui/pages/chat.js", "text/javascript; charset=utf-8"),
    "pages/hypotheses.js": ("hub_ui/pages/hypotheses.js", "text/javascript; charset=utf-8"),
    "pages/living.js": ("hub_ui/pages/living.js", "text/javascript; charset=utf-8"),
    "pages/kit.js": ("hub_ui/pages/kit.js", "text/javascript; charset=utf-8"),
    "pages/protocol.js": ("hub_ui/pages/protocol.js", "text/javascript; charset=utf-8"),
    "pages/pipeline.js": ("hub_ui/pages/pipeline.js", "text/javascript; charset=utf-8"),
    "pages/sources.js": ("hub_ui/pages/sources.js", "text/javascript; charset=utf-8"),
    "pages/method.js": ("hub_ui/pages/method.js", "text/javascript; charset=utf-8"),
    "pages/costs.js": ("hub_ui/pages/costs.js", "text/javascript; charset=utf-8"),
    "pages/intuition.js": ("hub_ui/pages/intuition.js", "text/javascript; charset=utf-8"),
    "pages/write.js": ("hub_ui/pages/write.js", "text/javascript; charset=utf-8"),
    "pages/platform.js": ("hub_ui/pages/platform.js", "text/javascript; charset=utf-8"),
    "pages/levels.js": ("hub_ui/pages/levels.js", "text/javascript; charset=utf-8"),
    "pages/learn.js": ("hub_ui/pages/learn.js", "text/javascript; charset=utf-8"),
    "fonts/inter-latin.woff2": ("hub_ui/fonts/inter-latin.woff2", "font/woff2"),
    "fonts/newsreader-latin-roman.woff2": (
        "hub_ui/fonts/newsreader-latin-roman.woff2",
        "font/woff2",
    ),
    "fonts/newsreader-latin-italic.woff2": (
        "hub_ui/fonts/newsreader-latin-italic.woff2",
        "font/woff2",
    ),
    "fonts/jetbrains-mono-latin.woff2": (
        "hub_ui/fonts/jetbrains-mono-latin.woff2",
        "font/woff2",
    ),
}

# Plain definitions behind dotted terms. Key: (short title, definition).
GLOSSARY: Final[dict[str, tuple[str, str]]] = {
    "included": (
        "Included",
        "A paper that passed every screening step: title and abstract, then full text. "
        "These are the papers the review is about.",
    ),
    "mined": (
        "Read in full",
        "A paper whose full text a miner has read and recorded fields for, each with the "
        "sentence it was based on. Usually close to the included set; the Flow page lists "
        "every difference by id.",
    ),
    "miner": (
        "Miner",
        "An extraction agent that reads a paper and records set fields (technique, human "
        "role, …), each with a quotation from the paper. A miner records; it does not "
        "judge inclusion.",
    ),
    "layer": (
        "Layer",
        "How central a paper is to the question. Core: builds an AI scientist. Benchmark: "
        "tests one. Applied: uses one in a field. Adjacent and background: related work.",
    ),
    "human": (
        "Human role",
        "What part a person plays in the system, from none (fully automated) to running "
        "the physical lab steps.",
    ),
    "technique": (
        "Technique",
        "The main method the system uses: several cooperating agents, an iterative loop, "
        "tree search, retrieval, and so on.",
    ),
    "architecture": (
        "Architecture",
        "How the system is organised: roles for several agents, a staged pipeline, a "
        "hierarchy, tool use, a sandbox.",
    ),
    "span": (
        "Automated span",
        "Which part of the research cycle the system automates on its own, from a single "
        "component to the full cycle.",
    ),
    "cic": (
        "Cited here",
        "How many other papers in this review cite it. A measure of influence inside the "
        "corpus, not worldwide citations.",
    ),
    "quote": (
        "Evidence",
        "The sentence from the paper that the miner used to set a value. Every value carries one.",
    ),
    "prisma": (
        "PRISMA flow",
        "The standard way to report a systematic review: how many records were found, "
        "removed, screened, excluded (and why) and included.",
    ),
    "screened": (
        "Screened",
        "Records checked against the inclusion criteria, first on title and abstract, then "
        "on the full text.",
    ),
    "duplicates": (
        "Duplicates",
        "The same paper found more than once (in arXiv and OpenAlex, or as two versions). "
        "Kept once.",
    ),
    "cap": (
        "Rapid-review cap",
        "To keep the review feasible, full texts were sought only for the highest-ranked "
        "records; the rest are reported as not sought, not as excluded.",
    ),
    "notretrieved": (
        "Not retrieved",
        "A full text was sought but no copy could be obtained (no open-access PDF, no arXiv "
        "source).",
    ),
    "criteria": (
        "Exclusion criteria",
        "The protocol's reasons to exclude a record, each with an EX-prefixed id. Each "
        "excluded record carries exactly one.",
    ),
    "protocol": (
        "Protocol",
        "The registered plan of the review: question, sources, criteria and stop rules. "
        "Changes are recorded as amendments.",
    ),
    "stoprule": (
        "Stop rule",
        "Screening of a ranked list stops after the run of consecutive exclusions the protocol "
        "sets; the unscreened rest is reported, not hidden.",
    ),
    "dna": (
        "Paper DNA",
        "A strip of six colours, one per field: technique, architecture, automated span, "
        "human role, layer and half-year. Similar strips mean similar systems.",
    ),
    "similar": (
        "Similar",
        "Papers ranked by how many field values they share with this one, plus how many "
        "cited papers they share. A plain count; no model is involved.",
    ),
    "gap": (
        "Gap",
        "A combination no paper has. Ranked by how many papers we would expect there if the "
        "two fields were unrelated.",
    ),
    "passA": (
        "First reading",
        "Pass A: a miner reads every paper in scope and records its fields with quotes.",
    ),
    "passB": (
        "Check reading",
        "Pass B: a second, independent reading of a sample of papers, usually by a different "
        "model, to test pass A.",
    ),
    "agreement": (
        "Agreement",
        "Share of checked papers where both readings recorded the same value. Exact matching "
        "here; it understates agreement on free-text fields.",
    ),
    "hole": (
        "Hole",
        "A paper the miner read but left a field empty or gave a gap value ("
        + ", ".join(sorted(GAP_VALUES))
        + ") instead of a finding.",
    ),
}

# Human label for a coded value (one term per concept, shared with the pages).
LABELS: Final[dict[str, str]] = {
    "multi-agent": "Multi-agent",
    "retrieval-grounding": "Retrieval / grounding",
    "iterative-loop": "Iterative loop",
    "tree-search": "Tree search",
    "code-execution-tools": "Code execution & tools",
    "evolutionary-search": "Evolutionary search",
    "training-finetuning-rl": "Training / fine-tuning / RL",
    "memory-skills": "Memory & skills",
    "prompting-single-llm": "Prompting a single LLM",
    "symbolic-regression": "Symbolic regression",
    "formal-verification": "Formal verification",
    "staged-pipeline": "Staged pipeline",
    "multi-agent-roles": "Multi-agent roles",
    "hierarchical": "Hierarchical",
    "interactive-copilot": "Interactive copilot",
    "environment-sandbox": "Environment / sandbox",
    "tool-integration": "Tool integration",
    "single-agent": "Single agent",
    "experiment-to-analysis": "Experiment → analysis",
    "ideation-to-experiment": "Ideation → experiment",
    "not-determinable": "Not determinable",
    "single-component": "Single component",
    "full-lifecycle": "Full lifecycle",
    "other": "Other",
}


@dataclass(frozen=True)
class PageSpec:
    """One hub page: its id, human title, page script (a served asset name) and payload names."""

    id: str
    title: str
    script: str
    payloads: tuple[str, ...]


PAGES: Final[dict[str, PageSpec]] = {
    "protocol": PageSpec("protocol", "Protocol", "pages/protocol.js", ("shell", "protocol")),
    "levels": PageSpec("levels", "How this study runs", "pages/levels.js", ("shell", "levels")),
    "overview": PageSpec("overview", "Overview", "pages/overview.js", ("shell", "overview")),
    "pipeline": PageSpec("pipeline", "Pipeline", "pages/pipeline.js", ("shell", "pipeline")),
    "corpus": PageSpec("corpus", "Corpus", "pages/corpus.js", ("shell", "corpus")),
    "flow": PageSpec("flow", "Flow", "pages/flow.js", ("shell", "flow", "screening", "journeys")),
    "lenses": PageSpec("lenses", "Lenses", "pages/lenses.js", ("shell", "lenses")),
    "explore": PageSpec("explore", "Explore", "pages/explore.js", ("shell", "explore")),
    "graph": PageSpec("graph", "Graph", "pages/graph.js", ("shell", "graph")),
    "landscape": PageSpec(
        "landscape",
        "Landscape",
        "pages/landscape.js",
        ("shell", "landscape", "landscape_uses"),
    ),
    "sources": PageSpec("sources", "Sources", "pages/sources.js", ("shell", "sources")),
    "method": PageSpec("method", "Method", "pages/method.js", ("shell", "method")),
    "miners": PageSpec("miners", "Miners", "pages/miners.js", ("shell", "mining")),
    "data": PageSpec("data", "Extracted data", "pages/data.js", ("shell", "mining")),
    "findings": PageSpec("findings", "Findings", "pages/findings.js", ("shell", "findings")),
    "contradictions": PageSpec(
        "contradictions",
        "Contradictions",
        "pages/contradictions.js",
        ("shell", "contradictions"),
    ),
    "chat": PageSpec("chat", "Chat", "pages/chat.js", ("shell", "chat")),
    "hypotheses": PageSpec(
        "hypotheses", "Hypotheses", "pages/hypotheses.js", ("shell", "hypotheses")
    ),
    "write": PageSpec("write", "Write & export", "pages/write.js", ("shell", "write")),
    "living": PageSpec("living", "Living review", "pages/living.js", ("shell", "living")),
    "costs": PageSpec("costs", "Costs & runs", "pages/costs.js", ("shell", "costs")),
    "intuition": PageSpec("intuition", "Intuition", "pages/intuition.js", ("shell", "intuition")),
    "platform": PageSpec("platform", "Platform", "pages/platform.js", ("shell", "platform")),
    "learn": PageSpec("learn", "Start here", "pages/learn.js", ("shell", "learn")),
    "kit": PageSpec("kit", "Brand kit", "pages/kit.js", ("shell",)),
}


def page_html(
    page: str,
    title: str,
    scripts: Sequence[str],
    payloads: Sequence[str],
    asset_version: str,
    *,
    static_data: bool = True,
) -> str:
    """The static HTML of a page: kit.css, one data script per payload, shell.js, `scripts`.

    Every URL is relative (`assets/<name>?v=<version>`, `data/<name>.js`), so the file works
    from file:// and under the server. With `static_data` the payloads load as `data/<name>.js`
    scripts that set `window.HUB_DATA[name]`; without it nothing is preloaded and
    `HUB.load(names)` fetches `data/<name>.json`. Page scripts call `HUB.load` either way."""
    v = html.escape(asset_version, quote=True)
    data = (
        [f'<script src="data/{html.escape(n, quote=True)}.js"></script>' for n in payloads]
        if static_data
        else []
    )
    assets = [f'<script src="assets/shell.js?v={v}"></script>'] + [
        f'<script src="assets/{html.escape(s, quote=True)}?v={v}"></script>' for s in scripts
    ]
    return (
        "<!doctype html>\n"
        '<html lang="en" data-theme="dark">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f'<link rel="stylesheet" href="assets/kit.css?v={v}">\n</head>\n<body>\n'
        "<noscript>This page needs JavaScript.</noscript>\n"
        + "\n".join(data + assets)
        + "\n</body>\n</html>\n"
    )


def asset_bytes(name: str) -> bytes:
    """Return the bytes of a registered asset. Raises KeyError for an unknown name."""
    if name not in ASSETS:
        raise KeyError(name)
    rel = ASSETS[name][0]
    return resources.files("factory").joinpath(*rel.split("/")).read_bytes()


def asset_version() -> str:
    """Twelve hex digits of sha256 over every asset name and its bytes, in name order.

    Changes exactly when a served file changes; safe to use in an immutable URL.
    """
    digest = hashlib.sha256()
    for name in sorted(ASSETS):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(asset_bytes(name))
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def _channel(hex_value: str) -> float:
    value = int(hex_value, 16) / 255.0
    if value <= 0.03928:
        return value / 12.92
    return float(((value + 0.055) / 1.055) ** 2.4)


def _luminance(hex_value: str) -> float:
    body = hex_value[1:]
    if len(body) == 3:
        body = "".join(ch * 2 for ch in body)
    red, green, blue = (_channel(body[i : i + 2]) for i in (0, 2, 4))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """WCAG 2 contrast ratio between two colours given as #rgb or #rrggbb.

    Symmetric in its arguments; ranges from 1.0 (identical) to 21.0 (black on white).
    Raises ValueError for any other notation.
    """
    for value in (fg_hex, bg_hex):
        if not _HEX.match(value):
            raise ValueError(f"not a #rgb or #rrggbb colour: {value!r}")
    lum_a = _luminance(fg_hex)
    lum_b = _luminance(bg_hex)
    light, dark = max(lum_a, lum_b), min(lum_a, lum_b)
    return (light + 0.05) / (dark + 0.05)

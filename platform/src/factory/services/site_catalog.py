# ruff: noqa: E501
"""The capability catalog (plan catalog): the factory's tools and skills by lifecycle stage.

`derive_catalog` is pure: it takes the tool list, the skill directory and the decision log and
returns a `Catalog`. Nothing is typed by hand except the lifecycle labels. The tool list comes
from the built MCP server (`collect_tools`, the only adapter; it imports `factory.mcp` lazily,
as `run_costs` already does for `unit_cap`). Flags are mechanical and shown for the researcher
to judge; a check that cannot be derived is `None` in `Catalog.skipped` with its reason.

Invariants: every listed tool appears once in `Catalog.tools` and in exactly one of its stages (a
tool no skill names, or only skills without a valid stage, has `stage=None`); every flag carries file
and line. A tool is marked (`MARKERS`) only by declaration, never by its name; a marked tool that no
skill names is not an orphan, and each marker is checked against the tool's access row.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib.util
import re
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Final

from factory.config import Settings
from factory.model.base import StrictModel
from factory.services.access import GATED_AGENT_ACTS, HUMAN_ONLY, TOOL_PERMISSIONS, Permission

LIFECYCLE: Final[tuple[tuple[str, str, str], ...]] = (
    ("frame", "Frame", "question, seeds, probe, protocol"),
    ("gather", "Gather", "search, dedup, snowball, inbox, grey"),
    ("screen", "Screen", "title/abstract, full text, calibration"),
    ("acquire", "Acquire & convert", "full-text fetch, conversion, documents"),
    ("extract", "Extract & mine", "extraction, miners, agreement, audit"),
    ("understand", "Understand", "lineage, intuition, regions, cards, graph, views"),
    ("develop", "Develop", "ideas, hypotheses, critic, experiments, decisions"),
    ("write", "Write & report", "drafts, verify, reports, PRISMA, bibliography"),
    ("maintain", "Maintain", "living review, watch, lessons"),
    ("cross", "Cross-cutting", "status, budget, check, trace, whoami"),
)
STAGE_IDS: Final = tuple(s[0] for s in LIFECYCLE)
_ORDER: Final = {s: i for i, s in enumerate(STAGE_IDS)}

FLAG_CODES: Final = (
    "skill-unknown-tool",
    "skill-unknown-arg",
    "skill-skill-clash",
    "skill-decision-missing",
    "skill-decision-not-decided",
    "orphan-tool",
    "orphan-skill",
    "skill-no-stage",
    "skill-names-human-only",
    "marker-access-mismatch",
    "marker-unknown-tool",
)

MARKER_KINDS: Final[dict[str, str]] = {
    "read-only": "Read-only status, list or view tool: needs no skill (IDEA-61 ruling, group A, 2026-11-12).",
    "human-only": "Human-only act: deliberately unnamed in agent skills (IDEA-61 ruling, group B, 2026-11-12).",
}
"""The kinds of marker and why a marked tool is not counted as an orphan."""

_READ_ONLY: Final = [
    "benchmark_ledger_view",
    "briefing_get",
    "budget_status",
    "card_view",
    "conclusion_status",
    "gate_status",
    "inbox_list",
    "ledger_view",
    "progress_status",
    "registry_query",
    "whoami",
    "xrun_list",
    "feed_list",
    "feed_status",
    "watch_status",
    "import_status",
    "import_coverage",
    "notice_list",
    "review_list",
    "reference_layer_status",
    "snowball_core_list",
    "grey_search_report",
    "export_bibliography",
    "graph_export",
]
_HUMAN_ONLY: Final = [
    "calibration_label",
    "miner_calibration_label",
    "review_decide",
    "lead_decide",
    "audit_record",
    "audit_sample",
    "extract_audit_record",
    "extract_audit_sample",
    "extract_agreement",
]
MARKERS: Final[dict[str, str]] = {
    **{t: "read-only" for t in _READ_ONLY},
    **{t: "human-only" for t in _HUMAN_ONLY},
}
"""Tool -> marker kind, declared from the researcher's ruling on IDEA-61 (item 3). Edited by hand
only on a ruling; never derived from a tool's name. `marker_access` cross-checks each entry."""

_TOOL_SHAPE = r"[a-z]+(?:_[a-z]+)+"
_BACKTICK = re.compile(r"`((?:[^`\n]|\n(?![ \t]*\n))+)`")
"""A backticked span; it may wrap onto the next line, never across a blank line."""
_NAME_SHAPE = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
"""Any identifier, single-word tools (`check`, `trace`, `whoami`) included; callers keep only
registered names."""
_CALL_NAME = re.compile(
    rf"\b(?:call|calls|called|use|uses|using)\s+(?:the\s+)?(?:(?:MCP\s+)?tool\s+)?`({_TOOL_SHAPE})[`(]",
    re.I,
)
_CALL_FORM = re.compile(rf"`({_TOOL_SHAPE})\(([^`]*)\)`")
_WITH_FORM = re.compile(
    rf"`({_TOOL_SHAPE})`\s+with\s+((?:`[a-z_][a-z0-9_]*(?:=[^`]*)?`)(?:(?:,\s*|\s+and\s+|\s+or\s+)`[a-z_][a-z0-9_]*(?:=[^`]*)?`)*)"
)
_ARG_NAME = re.compile(r"\b([a-z_][a-z0-9_]*)\s*=")
_DECISION = re.compile(r"\bdecisions?\s+(\d+(?:\s*(?:,|and|&)\s*\d+)*)", re.I)
_NEGATIVE = re.compile(r"\b(never|do not|don't|must not|should not|may not)\b", re.I)
_POSITIVE = re.compile(r"\b(always|must|call|calls)\b", re.I)
_NEG_ACT = re.compile(
    r"\b(?:never|do not|don't|must not|should not|may not)\s+(?:[a-z]+ly\s+)?([a-z]+)", re.I
)
_POS_ACT = re.compile(r"\b(?:always|must)\s+(?:[a-z]+ly\s+)?([a-z]+)|\b(calls?)\b", re.I)


def _act(sentence: str, negative: bool) -> str | None:
    """The act a sentence governs: the verb after its negation (`do not read` -> `read`) or after
    `always`/`must`, else `call` for a sentence that calls. Inflection `-s` is dropped."""
    m = (_NEG_ACT if negative else _POS_ACT).search(sentence)
    if m is None:
        return None
    verb = next(g for g in m.groups() if g).lower()
    return verb[:-1] if len(verb) > 3 and verb.endswith("s") and not verb.endswith("ss") else verb


_STEP = re.compile(r"^\s*\d+\.\s")


class ToolInfo(StrictModel):
    name: str
    description: str
    params: tuple[str, ...]
    input_schema_json: str
    stage: str | None
    also_used_in: tuple[str, ...]
    skills: tuple[str, ...]
    marker: str | None = None
    """A kind of `MARKER_KINDS`, when the tool is declared in `MARKERS`."""
    access: str | None = None
    """The tool's permission row (`access.TOOL_PERMISSIONS`), when it has one."""


class StepInfo(StrictModel):
    skill: str
    file: str
    line: int
    text: str
    tools: tuple[str, ...]


class SkillInfo(StrictModel):
    name: str
    description: str
    stages: tuple[str, ...]
    file: str
    sha: str
    tools: tuple[str, ...]
    steps: tuple[StepInfo, ...]


class Flag(StrictModel):
    code: str
    file: str
    line: int
    message: str
    other: str | None = None
    """The second sentence of a clash, with its file and line."""


class CountCheck(StrictModel):
    registered: int
    listed: int
    missing: tuple[str, ...]
    """Registered in the source but not listed by the built server."""
    extra: tuple[str, ...]
    duplicates: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.registered == self.listed and not (
            self.missing or self.extra or self.duplicates
        )


class Catalog(StrictModel):
    tools: tuple[ToolInfo, ...]
    skills: tuple[SkillInfo, ...]
    flags: tuple[Flag, ...]
    count_check: CountCheck
    prompts: int | None
    examples: int
    """Numbered procedure steps that name a registered tool."""
    skipped: dict[str, str]
    """Checks that could not be derived, with the reason (their results are absent, not zero)."""
    decisions_sha: str | None

    def flag_counts(self) -> dict[str, int]:
        counts = {code: 0 for code in FLAG_CODES}
        for flag in self.flags:
            counts[flag.code] += 1
        return counts


class ToolSpec(StrictModel):
    """What the derivation needs of one listed tool."""

    name: str
    description: str
    input_schema_json: str
    params: tuple[str, ...]


# --- adapter: the built server ---


def server_source() -> Path:
    spec = importlib.util.find_spec("factory.mcp.server")
    if spec is None or spec.origin is None:
        raise RuntimeError("factory.mcp.server is not importable")
    return Path(spec.origin)


def registered_names(source: Path) -> list[str]:
    """Names of the functions decorated `@server.tool(...)` (or the `name=` it gives), by AST."""
    names: list[str] = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "tool"
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "server"
            ):
                given = next(
                    (
                        k.value.value
                        for k in dec.keywords
                        if k.arg == "name" and isinstance(k.value, ast.Constant)
                    ),
                    None,
                )
                names.append(given if isinstance(given, str) else node.name)
    return names


def collect_tools(settings: Settings) -> tuple[list[ToolSpec], int]:
    """Build the real MCP server (offline: no call is made) and list its tools and prompts."""
    import json

    from factory.mcp.server import build_server

    server = build_server(settings)

    async def listing() -> tuple[list[ToolSpec], int]:
        tools = await server.list_tools()
        prompts = await server.list_prompts()
        specs = [
            ToolSpec(
                name=t.name,
                description=t.description or "",
                input_schema_json=json.dumps(t.input_schema, indent=1, sort_keys=True),
                params=tuple(sorted((t.input_schema.get("properties") or {}).keys())),
            )
            for t in tools
        ]
        return specs, len(prompts)

    with ThreadPoolExecutor(max_workers=1) as pool:  # safe whether or not a loop is running
        return pool.submit(asyncio.run, listing()).result()


def marker_access(tool: str, kind: str) -> str | None:
    """Why the tool's access row disagrees with its marker, or `None` when it agrees or the tool has
    no row. Read-only expects `project:read`; human-only expects a permission an agent never holds
    and no gate through which an agent may act."""
    permission = TOOL_PERMISSIONS.get(tool)
    if permission is None:
        return None
    if kind == "read-only" and permission is not Permission.PROJECT_READ:
        return f"marked read-only but its access row is `{permission.value}`"
    if kind == "human-only":
        if permission not in HUMAN_ONLY:
            return f"marked human-only but its access row `{permission.value}` is open to agents"
        if tool in GATED_AGENT_ACTS:
            return "marked human-only but it is a gated agent act (`GATED_AGENT_ACTS`)"
    return None


def enum_values(schema_json: str) -> frozenset[str]:
    """Every string `enum` or `const` value anywhere in a JSON schema."""
    import json

    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "enum" and isinstance(value, list):
                    found.update(v for v in value if isinstance(v, str))
                elif key == "const" and isinstance(value, str):
                    found.add(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    try:
        walk(json.loads(schema_json))
    except ValueError:
        return frozenset()
    return frozenset(found)


def declared_values(spec: ToolSpec) -> frozenset[str]:
    """Values a tool declares for its inputs: the schema's enum and const values, and the backticked
    words of its own description that are not input names (a `str` input such as `mine_resolve`'s
    `choice` lists its values there)."""
    described = {m.group(1).strip() for m in _BACKTICK.finditer(spec.description)}
    return enum_values(spec.input_schema_json) | frozenset(described - set(spec.params))


# --- parsing ---


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _split_list(value: str) -> list[str]:
    return [p.strip().strip("'\"") for p in value.strip().strip("[]").split(",") if p.strip()]


def parse_frontmatter(text: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    """The scalar and list fields of the leading `---` block, read line by line (descriptions
    contain colons, so YAML would refuse them)."""
    lines = text.splitlines()
    scalars: dict[str, str] = {}
    lists: dict[str, list[str]] = {}
    if not lines or lines[0].strip() != "---":
        return scalars, lists
    key: str | None = None
    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        item = re.match(r"^\s+-\s+(.*)$", raw)
        if item and key is not None:
            lists.setdefault(key, []).append(item.group(1).strip().strip("'\""))
            continue
        kv = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", raw)
        if kv:
            key = kv.group(1)
            if kv.group(2).strip():
                scalars[key] = kv.group(2).strip()
                if key == "stage":
                    lists[key] = _split_list(kv.group(2))
    return scalars, lists


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _mentions(text: str) -> dict[str, int]:
    """Each backticked token that starts with an identifier, with its first line; the caller keeps
    only registered tool names."""
    found: dict[str, int] = {}
    for m in _BACKTICK.finditer(text):
        name = re.match(rf"({_NAME_SHAPE})\b", m.group(1))
        if name and name.group(1) not in found:
            found[name.group(1)] = _line_of(text, m.start())
    return found


def _sentences(text: str) -> list[tuple[int, str]]:
    """Sentences with the line each starts on (paragraphs split on blank lines, sentences on
    `. ! ? : ;` followed by space)."""
    out: list[tuple[int, str]] = []
    pos = 0
    for para in re.split(r"\n\s*\n", text):
        start = text.find(para, pos)
        pos = start + len(para)
        offset = 0
        for part in re.split(r"(?<=[.!?:;])\s+", para):
            at = para.find(part, offset)
            offset = at + len(part)
            if part.strip():
                out.append((_line_of(text, start + at), " ".join(part.split())))
    return out


def _steps(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(lines):
        if _STEP.match(lines[i]):
            j = i + 1
            while (
                j < len(lines)
                and lines[j].strip()
                and not _STEP.match(lines[j])
                and not lines[j].startswith("#")
            ):
                j += 1
            out.append((i + 1, " ".join(" ".join(lines[i:j]).split())))
            i = j
        else:
            i += 1
    return out


def _decision_table(path: Path) -> dict[int, str]:
    """Decision number -> status cell, from the `| N | title | status | ... |` rows."""
    rows: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|[^|]*\|\s*([^|]*?)\s*\|", line)
        if m:
            rows[int(m.group(1))] = m.group(2)
    return rows


# --- derivation ---


def derive_catalog(
    tools: Sequence[ToolSpec],
    skills_dir: Path | None,
    decisions_path: Path | None,
    registered: Sequence[str],
    prompts: int | None,
    root: Path | None = None,
    markers: dict[str, str] | None = None,
) -> Catalog:
    """The catalog. `registered` are the AST names of the `@server.tool()` functions; `root` is
    the base for the file paths shown (default: the skills' parent's parent); `markers` defaults to
    `MARKERS`."""
    markers = MARKERS if markers is None else markers
    skipped: dict[str, str] = {}
    spec_by_name = {t.name: t for t in tools}
    listed = [t.name for t in tools]
    dup = sorted(
        {n for n in listed if listed.count(n) > 1}
        | {n for n in registered if list(registered).count(n) > 1}
    )
    check = CountCheck(
        registered=len(registered),
        listed=len(listed),
        missing=tuple(sorted(set(registered) - set(listed))),
        extra=tuple(sorted(set(listed) - set(registered))),
        duplicates=tuple(dup),
    )

    files: list[Path] = sorted(skills_dir.glob("rf-*/SKILL.md")) if skills_dir else []
    if skills_dir is None or not files:
        skipped["skills"] = "no plugin/skills/rf-*/SKILL.md found"
    base = root or (skills_dir.parent if skills_dir else Path("."))

    def rel(path: Path) -> str:
        try:
            return str(path.relative_to(base))
        except ValueError:
            return str(path)

    decisions: dict[int, str] | None = None
    decisions_sha: str | None = None
    if decisions_path is not None and decisions_path.exists():
        decisions = _decision_table(decisions_path)
        decisions_sha = _sha(decisions_path)
        if not decisions:
            decisions = None
            skipped["decisions"] = "no decision rows found in decisions.md"
    else:
        skipped["decisions"] = "docs/decisions.md not found"

    flags: list[Flag] = []
    infos: list[SkillInfo] = []
    sentences: dict[str, list[tuple[int, str]]] = {}
    named_at: dict[str, dict[str, int]] = {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        fm, fl = parse_frontmatter(text)
        name = fm.get("name", path.parent.name)
        stages = tuple(fl.get("stage", []))
        shown = rel(path)
        if not stages:
            flags.append(
                Flag(
                    code="skill-no-stage",
                    file=shown,
                    line=1,
                    message=f"{name} has no `stage` in its frontmatter",
                )
            )
        else:
            for bad in [s for s in stages if s not in _ORDER]:
                flags.append(
                    Flag(
                        code="skill-no-stage",
                        file=shown,
                        line=1,
                        message=f"{name}: stage `{bad}` is not in the lifecycle",
                    )
                )
        stages = tuple(s for s in stages if s in _ORDER)

        named = _mentions(text)
        steps = tuple(
            StepInfo(
                skill=name,
                file=shown,
                line=ln,
                text=body,
                tools=tuple(t for t in dict.fromkeys(_mentions(body)) if t in spec_by_name),
            )
            for ln, body in _steps(text)
        )
        steps = tuple(s for s in steps if s.tools)

        for m in _CALL_NAME.finditer(text):
            if m.group(1) not in spec_by_name:
                flags.append(
                    Flag(
                        code="skill-unknown-tool",
                        file=shown,
                        line=_line_of(text, m.start(1)),
                        message=f"`{m.group(1)}` is not a registered tool",
                    )
                )
        for m in _CALL_FORM.finditer(text):
            tool = m.group(1)
            if tool not in spec_by_name:
                flags.append(
                    Flag(
                        code="skill-unknown-tool",
                        file=shown,
                        line=_line_of(text, m.start(1)),
                        message=f"`{tool}` is not a registered tool",
                    )
                )
                continue
            for arg in _ARG_NAME.findall(m.group(2)):
                if arg not in spec_by_name[tool].params:
                    flags.append(
                        Flag(
                            code="skill-unknown-arg",
                            file=shown,
                            line=_line_of(text, m.start(1)),
                            message=f"`{tool}` has no input `{arg}`",
                        )
                    )
        for m in _WITH_FORM.finditer(text):
            tool = m.group(1)
            if tool not in spec_by_name:
                continue
            values = declared_values(spec_by_name[tool])
            for tok in _BACKTICK.findall(m.group(2)):
                arg = re.match(r"[a-z_][a-z0-9_]*", tok)
                if arg and tok in values:
                    continue
                if arg and arg.group(0) not in spec_by_name[tool].params:
                    flags.append(
                        Flag(
                            code="skill-unknown-arg",
                            file=shown,
                            line=_line_of(text, m.start(1)),
                            message=f"`{tool}` has no input `{arg.group(0)}`",
                        )
                    )

        if decisions is not None:
            for m in _DECISION.finditer(text):
                for num in map(int, re.findall(r"\d+", m.group(1))):
                    line = _line_of(text, m.start())
                    if num not in decisions:
                        flags.append(
                            Flag(
                                code="skill-decision-missing",
                                file=shown,
                                line=line,
                                message=f"decision {num} is not in docs/decisions.md",
                            )
                        )
                    elif not decisions[num].lower().startswith("decided"):
                        flags.append(
                            Flag(
                                code="skill-decision-not-decided",
                                file=shown,
                                line=line,
                                message=f"decision {num} is `{decisions[num][:60]}`, not Decided",
                            )
                        )

        sentences[name] = _sentences(text)
        named_at[name] = named
        infos.append(
            SkillInfo(
                name=name,
                description=fm.get("description", ""),
                stages=stages,
                file=shown,
                sha=_sha(path),
                tools=tuple(t for t in named if t in spec_by_name),
                steps=steps,
            )
        )

    # skill clashes: opposite polarity on the same tool and the same act in two skills ("do not read
    # `check`" does not oppose "call `check`"); a sentence whose act cannot be read pairs with any
    file_of = {s.name: s.file for s in infos}
    for tool in sorted(spec_by_name):
        neg: dict[tuple[str, str | None], tuple[int, str]] = {}
        pos: dict[tuple[str, str | None], tuple[int, str]] = {}
        for skill, sents in sentences.items():
            for ln, sentence in sents:
                if f"`{tool}`" not in sentence and f"`{tool}(" not in sentence:
                    continue
                if _NEGATIVE.search(sentence):
                    neg.setdefault((skill, _act(sentence, True)), (ln, sentence))
                elif _POSITIVE.search(sentence):
                    pos.setdefault((skill, _act(sentence, False)), (ln, sentence))
        for (a, act_a), (ln_a, s_a) in sorted(
            neg.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
        ):
            for (b, act_b), (ln_b, s_b) in sorted(
                pos.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
            ):
                if a != b and (act_a is None or act_b is None or act_a == act_b):
                    flags.append(
                        Flag(
                            code="skill-skill-clash",
                            file=file_of[a],
                            line=ln_a,
                            message=f"`{tool}`: {a}: {s_a}",
                            other=f"{b} ({file_of[b]}:{ln_b}): {s_b}",
                        )
                    )

    # stages
    primary: dict[str, str] = {}
    also: dict[str, set[str]] = defaultdict(set)
    users: dict[str, list[str]] = defaultdict(list)
    for sk in infos:
        for tool in sk.tools:
            users[tool].append(sk.name)
            if sk.stages:
                for st in sk.stages:
                    also[tool].add(st)
                if tool not in primary or _ORDER[sk.stages[0]] < _ORDER[primary[tool]]:
                    primary[tool] = sk.stages[0]
    tool_infos: list[ToolInfo] = []
    unique = {t.name: t for t in reversed(list(tools))}  # the first listing of a name wins
    for spec in sorted(unique.values(), key=lambda t: t.name):
        stage = primary.get(spec.name)
        marker = markers.get(spec.name)
        permission = TOOL_PERMISSIONS.get(spec.name)
        tool_infos.append(
            ToolInfo(
                name=spec.name,
                description=spec.description,
                params=spec.params,
                input_schema_json=spec.input_schema_json,
                stage=stage,
                also_used_in=tuple(sorted(also[spec.name] - {stage or ""}, key=_ORDER.__getitem__)),
                skills=tuple(users[spec.name]),
                marker=marker,
                access=permission.value if permission is not None else None,
            )
        )
        if marker is not None:
            mismatch = marker_access(spec.name, marker)
            if mismatch:
                flags.append(
                    Flag(
                        code="marker-access-mismatch",
                        file="services/site_catalog.py",
                        line=1,
                        message=f"`{spec.name}` {mismatch}",
                    )
                )
            if marker == "human-only":
                for sk in infos:
                    if spec.name in sk.tools:
                        flags.append(
                            Flag(
                                code="skill-names-human-only",
                                file=sk.file,
                                line=named_at[sk.name][spec.name],
                                message=f"{sk.name} names `{spec.name}`, a human-only act",
                            )
                        )
        if not users[spec.name] and marker is None:
            flags.append(
                Flag(
                    code="orphan-tool",
                    file="mcp/server.py",
                    line=1,
                    message=f"`{spec.name}` is registered and no skill names it",
                )
            )
    for name in sorted(set(markers) - set(unique)):
        flags.append(
            Flag(
                code="marker-unknown-tool",
                file="services/site_catalog.py",
                line=1,
                message=f"`{name}` is marked {markers[name]} but is not a listed tool",
            )
        )
    for sk in infos:
        if not sk.tools:
            flags.append(
                Flag(
                    code="orphan-skill",
                    file=sk.file,
                    line=1,
                    message=f"{sk.name} names no registered tool",
                )
            )

    return Catalog(
        tools=tuple(tool_infos),
        skills=tuple(infos),
        flags=tuple(flags),
        count_check=check,
        prompts=prompts,
        examples=sum(len(s.steps) for s in infos),
        skipped=skipped,
        decisions_sha=decisions_sha,
    )


def repo_root() -> Path:
    """The checkout that holds `plugin/` and `docs/` (this file is `platform/src/factory/services`)."""
    return Path(__file__).resolve().parents[4]


def locate(settings: Settings) -> tuple[Path | None, Path | None]:
    """The skills directory and the decision log: the settings' plugin dir and root when they hold
    them, else the checkout this code runs from (a copied project has no `plugin/`)."""
    candidates = [
        (settings.plugin_dir / "skills", settings.root / "docs" / "decisions.md"),
        (repo_root() / "plugin" / "skills", repo_root() / "docs" / "decisions.md"),
    ]
    skills = next((s for s, _ in candidates if s.is_dir()), None)
    decisions = next((d for _, d in candidates if d.is_file()), None)
    return skills, decisions


def source_hash(settings: Settings) -> str:
    """A hash of every SKILL.md and the decision log, for the product's fingerprint."""
    skills, decisions = locate(settings)
    digest = hashlib.sha256()
    paths = sorted(skills.glob("rf-*/SKILL.md")) if skills else []
    if decisions:
        paths.append(decisions)
    for path in paths:
        digest.update(str(path.name).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def build_catalog(settings: Settings) -> Catalog:
    tools, prompts = collect_tools(settings)
    skills, decisions = locate(settings)
    return derive_catalog(
        tools, skills, decisions, registered_names(server_source()), prompts, root=repo_root()
    )

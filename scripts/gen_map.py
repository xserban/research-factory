"""Generate docs/MAP.md: where each capability of the platform lives.

Run from the repository root:

    uv run --project platform python scripts/gen_map.py

The map is computed, never typed. It reads the module registry
(`factory.services.modules.default_modules`), the event catalog, the projection, the MCP server
(`mcp/server.py`, by AST), the CLI (`cli/main.py`, through typer) and the plugin skills. It writes
`docs/MAP.md` and prints the counts. It changes nothing else.

Associations are found by name, so they are exact where the code names a thing and silent where it
does not: a service is linked to a module when it names one of the module's event types as a
string literal; a tool or command is linked to a service when its body references the service's
import alias; a skill is linked to a tool when its SKILL.md names the tool.
"""

from __future__ import annotations

import ast
import inspect
import re
import subprocess
import sys
import textwrap
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "platform" / "src" / "factory"
OUT = ROOT / "docs" / "MAP.md"

sys.path.insert(0, str(ROOT / "platform" / "src"))

import typer  # noqa: E402

from factory.events.catalog import default_catalog  # noqa: E402
from factory.index.default import PROJECTION_VERSION, default_projection  # noqa: E402
from factory.services.modules import default_modules  # noqa: E402


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def first_sentence(doc: str | None, limit: int = 140) -> str:
    if not doc:
        return ""
    text = " ".join(inspect.cleandoc(doc).split("\n\n")[0].split())
    match = re.match(r"(.+?\.)(\s|$)", text)
    sentence = match.group(1) if match else text
    if len(sentence) > limit:
        sentence = sentence[: limit - 1].rstrip() + "…"
    return sentence.replace("|", "\\|")


def cell(items: Iterable[str], sep: str = ", ") -> str:
    values = [str(i) for i in items]
    return sep.join(values) if values else "—"


def code(items: Iterable[str]) -> str:
    return cell(f"`{i}`" for i in items)


# --- service aliases -----------------------------------------------------------------------------


def service_aliases(tree: ast.Module) -> dict[str, str]:
    """Alias -> service module name, from `from factory.services import x as y` and similar."""
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "factory.services":
                for name in node.names:
                    aliases[name.asname or name.name] = name.name
            elif node.module.startswith("factory.services."):
                service = node.module.removeprefix("factory.services.")
                for name in node.names:
                    aliases.setdefault(f"{service}:{name.asname or name.name}", service)
    return aliases


def services_used(fn: ast.AST, aliases: dict[str, str]) -> set[str]:
    """Service modules a function body references, through module aliases or imported names."""
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    found: set[str] = set()
    for alias, service in aliases.items():
        if ":" in alias:
            if alias.split(":", 1)[1] in names:
                found.add(service)
        elif alias in names:
            found.add(service)
    return {s for s in found if s not in ("modules", "context")}


# --- MCP tools -----------------------------------------------------------------------------------


def mcp_tools() -> list[tuple[str, set[str], str]]:
    path = SRC / "mcp" / "server.py"
    tree = ast.parse(path.read_text())
    aliases = service_aliases(tree)
    tools: list[tuple[str, set[str], str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Attribute) and target.attr == "tool":
                tools.append(
                    (
                        node.name,
                        services_used(node, aliases),
                        first_sentence(ast.get_docstring(node)),
                    )
                )
    return sorted(tools)


# --- CLI commands --------------------------------------------------------------------------------


def cli_functions() -> dict[str, tuple[ast.FunctionDef, dict[str, str]]]:
    """Every top-level function of the CLI package, with the service aliases of its file."""
    found: dict[str, tuple[ast.FunctionDef, dict[str, str]]] = {}
    for path in sorted((SRC / "cli").glob("*.py")):
        tree = ast.parse(path.read_text())
        aliases = service_aliases(tree)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                found[f"{path.stem}.{node.name}"] = (node, aliases)
    return found


def cli_services(
    key: str,
    functions: dict[str, tuple[ast.FunctionDef, dict[str, str]]],
    seen: set[str],
) -> set[str]:
    """Services a CLI function reaches directly or through helper functions of the CLI package."""
    if key in seen or key not in functions:
        return set()
    seen.add(key)
    node, aliases = functions[key]
    found = services_used(node, aliases)
    called = {
        n.func.id
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    module = key.split(".", 1)[0]
    for name in called:
        for candidate in (f"{module}.{name}", *(k for k in functions if k.endswith(f".{name}"))):
            if candidate in functions:
                found |= cli_services(candidate, functions, seen)
                break
    return found


def walk_typer(app: typer.Typer, prefix: str) -> Iterable[tuple[str, object]]:
    for command in app.registered_commands:
        callback = command.callback
        if callback is None:
            continue
        name = command.name or callback.__name__.replace("_", "-")
        yield f"{prefix} {name}".strip(), callback
    for group in app.registered_groups:
        sub = group.typer_instance
        group_name = group.name or (sub.info.name if sub is not None else None)
        if sub is None or not isinstance(group_name, str):
            continue
        yield from walk_typer(sub, f"{prefix} {group_name}".strip())


def cli_commands() -> list[tuple[str, set[str], str]]:
    from factory.cli.main import app

    functions = cli_functions()
    commands: list[tuple[str, set[str], str]] = []
    for name, callback in walk_typer(app, "factory"):
        module = getattr(callback, "__module__", "").rsplit(".", 1)[-1]
        key = f"{module}.{getattr(callback, '__name__', '')}"
        services = cli_services(key, functions, set())
        commands.append((name, services, first_sentence(getattr(callback, "__doc__", None))))
    return sorted(commands)


# --- services ------------------------------------------------------------------------------------


def service_files() -> dict[str, Path]:
    files = {p.stem: p for p in (SRC / "services").glob("*.py") if p.stem != "__init__"}
    return dict(sorted(files.items()))


def literal_strings(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }


# --- skills --------------------------------------------------------------------------------------


def skills(tool_names: set[str]) -> dict[str, tuple[str, set[str]]]:
    found: dict[str, tuple[str, set[str]]] = {}
    for path in sorted((ROOT / "plugin" / "skills").glob("*/SKILL.md")):
        text = path.read_text()
        match = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
        description = first_sentence(match.group(1) if match else "", 160)
        words = set(re.findall(r"[a-z][a-z_]+", text))
        found[path.parent.name] = (description, words & tool_names)
    return found


# --- index ---------------------------------------------------------------------------------------


def index_files_by_table() -> dict[str, set[str]]:
    """Table name -> index files that define it with `Table("<name>", ...)`."""
    found: dict[str, set[str]] = defaultdict(set)
    for path in sorted((SRC / "index").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Table"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found[node.args[0].value].add(path.stem)
    return found


def index_files_by_literal() -> dict[str, set[str]]:
    """String literal -> index files that contain it (event types and table names)."""
    found: dict[str, set[str]] = defaultdict(set)
    for path in sorted((SRC / "index").glob("*.py")):
        for value in literal_strings(path):
            found[value].add(path.stem)
    return found


# --- render --------------------------------------------------------------------------------------


def head_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> None:
    registry = default_modules()
    catalog = default_catalog()
    projection = default_projection()
    tools = mcp_tools()
    commands = cli_commands()
    services = service_files()
    tool_names = {t[0] for t in tools}
    skill_map = skills(tool_names)
    index_literals = index_files_by_literal()
    index_tables = index_files_by_table()
    table_names = sorted(projection.metadata.tables)

    event_owner: dict[str, str] = {}
    table_owner: dict[str, str] = {}
    for spec in [m.spec for m in registry.modules()]:
        for t in spec.events.types:
            event_owner[t] = spec.name
        for t in spec.events.tables:
            table_owner[t] = spec.name

    service_literals = {name: literal_strings(path) for name, path in services.items()}
    service_modules: dict[str, set[str]] = defaultdict(set)
    module_services: dict[str, set[str]] = defaultdict(set)
    for service, literals in service_literals.items():
        for event_type in literals & set(event_owner):
            service_modules[service].add(event_owner[event_type])
            module_services[event_owner[event_type]].add(service)

    tools_by_service: dict[str, list[str]] = defaultdict(list)
    for tool, used, _ in tools:
        for s in used:
            tools_by_service[s].append(tool)
    commands_by_service: dict[str, list[str]] = defaultdict(list)
    for command, used, _ in commands:
        for s in used:
            commands_by_service[s].append(command)
    skills_by_tool: dict[str, list[str]] = defaultdict(list)
    for skill, (_, named) in skill_map.items():
        for tool in named:
            skills_by_tool[tool].append(skill)

    lines: list[str] = []
    w = lines.append
    w("# Map of the platform")
    w("")
    w(
        "<!-- Generated by scripts/gen_map.py. Do not edit by hand: "
        "run `uv run --project platform python scripts/gen_map.py` from the repository root. -->"
    )
    w("")
    w(
        f"Generated at commit `{head_commit()}` · projection version `{PROJECTION_VERSION}` · "
        f"{len(registry.modules())} stage modules · {len(catalog.names())} event types · "
        f"{len(table_names)} index tables · {len(services)} service modules · "
        f"{len(tools)} MCP tools · {len(commands)} CLI commands · {len(skill_map)} skills."
    )
    w("")
    w(
        "Read [ARCHITECTURE.md](ARCHITECTURE.md) first. This file answers *where*: for each stage "
        "module, the events, models, index files, tables, task kinds, gates and checks it owns, "
        "and the services that name its events; then every MCP tool, CLI command, service and "
        "skill with what it reaches. Links are found by name (see the script's docstring), so a "
        "missing link means the code does not name the thing, not that no relation exists. "
        "Paths are relative to `platform/src/factory/` unless they start with `plugin/`."
    )
    w("")
    w("## Contents")
    w("")
    w("1. [Stage modules](#stage-modules) (summary, then one section per module)")
    w("2. [MCP tools](#mcp-tools)")
    w("3. [CLI commands](#cli-commands)")
    w("4. [Services](#services)")
    w("5. [Skills](#skills)")
    w("")

    # Modules summary
    w("## Stage modules")
    w("")
    w(
        "Declared in `services/modules/<name>.py` against the contract in `modules/contract.py`; "
        "the registry (`modules/registry.py`) refuses any event type, table, task kind, protocol "
        "section, check code or gate that does not belong to exactly one module."
    )
    w("")
    w("| Module | Kind | Inputs → outputs | Events | Tables | Task kinds | Gates | Checks |")
    w("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for spec in [m.spec for m in registry.modules()]:
        io = f"{cell(i.value for i in spec.inputs)} → {cell(o.value for o in spec.outputs)}"
        w(
            f"| [{spec.name}](#module-{spec.name.replace('_', '-')}) | {spec.kind.value} | {io} | "
            f"{len(spec.events.types)} | {len(spec.events.tables)} | {len(spec.task_kinds)} | "
            f"{len(spec.gates)} | {len(spec.checks)} |"
        )
    w("")

    for spec in [m.spec for m in registry.modules()]:
        w(f"### Module: {spec.name}")
        w("")
        w(f"Declaration: `services/modules/{spec.name}.py` · kind `{spec.kind.value}`")
        w("")
        if spec.events.types:
            w("| Event type | Payload model | Folded in `index/` |")
            w("| --- | --- | --- |")
            for t in spec.events.types:
                payload = catalog.get(t).payload if t in catalog else None
                model = (
                    f"`{payload.__module__.removeprefix('factory.')}.{payload.__name__}`"
                    if payload
                    else "—"
                )
                folded = projection.handlers.get(t)
                files = sorted(index_literals.get(t, set()))
                where = code(f"{f}.py" for f in files) if folded else "not folded"
                w(f"| `{t}` | {model} | {where} |")
            w("")
        if spec.events.tables:
            tables = []
            for table in spec.events.tables:
                files = sorted(index_tables.get(table, set()))
                tables.append(f"`{table}` ({cell(f'{f}.py' for f in files)})")
            w(f"- **Tables:** {cell(tables)}")
        if spec.events.note:
            w(f"- **Note:** {spec.events.note}")
        if spec.task_kinds:
            w(f"- **Task kinds:** {code(spec.task_kinds)}")
        if spec.protocol_sections:
            w(f"- **Protocol sections:** {code(spec.protocol_sections)}")
        if spec.gates:
            gates = [f"`{g.gate_id}` ({g.kind.value}, floor {g.floor.value})" for g in spec.gates]
            w(f"- **Gates:** {cell(gates)}")
        if spec.checks:
            w(f"- **Check codes:** {code(c.code for c in spec.checks)}")
        if spec.regime:
            r = spec.regime
            w(
                f"- **Quality regime:** {r.passes} pass(es), independence {r.independence}, "
                f"calibration {r.calibration}, audit {r.audit}"
            )
        if spec.strategies:
            w(f"- **Strategies:** {cell(f'{s.name}@{s.version}' for s in spec.strategies)}")
        module_named = sorted(module_services.get(spec.name, set()))
        w(f"- **Services naming its events:** {code(f'services/{s}.py' for s in module_named)}")
        w("")

    unowned_tables = [t for t in table_names if t not in table_owner]
    if unowned_tables:
        w("### Tables no module declares")
        w("")
        w(
            "Core tables (`index/projection.py`) and tables the registry does not require a "
            f"module to own: {code(unowned_tables)}"
        )
        w("")

    # MCP tools
    w("## MCP tools")
    w("")
    w(
        "All in `mcp/server.py`, nested in `build_server`; conventions in `mcp/conventions.py` "
        "and `docs/specs/00-system.md` §7."
    )
    w("")
    w("| Tool | Services | Skills naming it | Summary |")
    w("| --- | --- | --- | --- |")
    for tool, used, summary in tools:
        w(
            f"| `{tool}` | {code(sorted(used))} | {cell(sorted(skills_by_tool.get(tool, [])))} | "
            f"{summary} |"
        )
    w("")

    # CLI
    w("## CLI commands")
    w("")
    w("Defined in `cli/main.py` (typer); rendering in `cli/render.py` and siblings.")
    w("")
    w("| Command | Services | Summary |")
    w("| --- | --- | --- |")
    for command, used, summary in commands:
        w(f"| `{command}` | {code(sorted(used))} | {summary} |")
    w("")

    # Services
    w("## Services")
    w("")
    w(
        "`services/<name>.py`. *Modules* lists the stage modules whose event types the service "
        "names (writes or reads); services that read every family, such as `check`, list many."
    )
    w("")
    w("| Service | Purpose | Modules | MCP tools | CLI commands |")
    w("| --- | --- | --- | --- | --- |")
    for name, path in services.items():
        doc = ast.get_docstring(ast.parse(path.read_text()))
        tools_here = sorted(tools_by_service.get(name, []))
        cmds_here = sorted(commands_by_service.get(name, []))
        w(
            f"| `{name}` | {first_sentence(doc, 120)} | {cell(sorted(service_modules[name]))} | "
            f"{code(tools_here)} | {code(cmds_here)} |"
        )
    w("")

    # Skills
    w("## Skills")
    w("")
    w("`plugin/skills/<name>/SKILL.md`. `rf-run` is the entry point for a session on a project.")
    w("")
    w("| Skill | When | MCP tools it names |")
    w("| --- | --- | --- |")
    for skill, (description, named) in skill_map.items():
        w(f"| `{skill}` | {description} | {code(sorted(named))} |")
    w("")

    OUT.write_text("\n".join(lines))
    print(
        textwrap.dedent(
            f"""\
            wrote {rel(OUT)}: {len(registry.modules())} modules, {len(catalog.names())} events,
            {len(table_names)} tables, {len(services)} services, {len(tools)} tools,
            {len(commands)} commands, {len(skill_map)} skills"""
        )
    )


if __name__ == "__main__":
    main()

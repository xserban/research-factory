"""Do the MCP configs of this factory point at one code line? (IDEA-62, `factory check`.)

Which configs: the paths in `Settings.mcp_configs` (`FACTORY_MCP_CONFIGS`, joined by the path
separator) and those listed in `<root>/mcp-configs.txt` (one path per line; blank lines and `#`
comments ignored; a relative path is read against the root). No list, no finding: the check
never guesses where configs live.

The code line of a `factory` server entry, first rule that applies:
1. an entry of its `PYTHONPATH` that is a `factory` source directory (`.../platform/src`);
2. the directory after `--project` or `--directory` in its arguments, read against the config's
   own directory (a session starts in the directory that holds its `.mcp.json`);
3. its command, when it is a path inside a `platform/.venv`.
A `.../platform` directory stands for the worktree that holds it. Configs whose servers resolve to
more than one directory are reported together, with each directory's git commit when git can
read it. Read-only; nothing is written.
"""

import itertools
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from factory.config import Settings
from factory.modules.contract import CheckHit

CONFIG_LIST = "mcp-configs.txt"
_GIT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class ServerLine:
    """One `factory` server of one config, and the code line it runs (None: not resolved)."""

    config: Path
    server: str
    code: Path | None


def configured_paths(settings: Settings) -> list[Path]:
    """The configs `check` compares, in the order given, each once."""
    paths = list(settings.mcp_configs)
    listing = settings.root / CONFIG_LIST
    if listing.is_file():
        for line in listing.read_text().splitlines():
            entry = line.split("#", 1)[0].strip()
            if entry:
                path = Path(entry).expanduser()
                paths.append(path if path.is_absolute() else settings.root / path)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def worktree_of(directory: Path) -> Path:
    """The worktree a code directory belongs to: `<w>/platform/src` and `<w>/platform` give
    `<w>`; any other directory stands for itself."""
    if directory.name == "src" and directory.parent.name == "platform":
        return directory.parent.parent
    if directory.name == "platform":
        return directory.parent
    return directory


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def server_code(config: Path, entry: dict[str, object]) -> Path | None:
    """The code line one server entry runs, by the rules in the module docstring."""
    env = entry.get("env")
    if isinstance(env, dict):
        pythonpath = env.get("PYTHONPATH")
        if isinstance(pythonpath, str):
            for part in pythonpath.split(":"):
                candidate = Path(part)
                if part and candidate.name == "src" and candidate.parent.name == "platform":
                    return _resolved(worktree_of(candidate))
    args = entry.get("args")
    if isinstance(args, list):
        for flag, value in itertools.pairwise(args):
            if flag in ("--project", "--directory") and isinstance(value, str):
                directory = Path(value).expanduser()
                if not directory.is_absolute():
                    directory = config.parent / directory
                return _resolved(worktree_of(directory))
    command = entry.get("command")
    if isinstance(command, str):
        path = Path(command)
        for parent in path.parents:
            if parent.name == ".venv" and parent.parent.name == "platform":
                return _resolved(parent.parent.parent)
    return None


def _is_factory(entry: dict[str, object]) -> bool:
    command = entry.get("command")
    args = entry.get("args")
    words = [command] if isinstance(command, str) else []
    if isinstance(args, list):
        words += [a for a in args if isinstance(a, str)]
    return any(Path(word).name == "factory" for word in words)


def read_config(config: Path) -> list[ServerLine] | str:
    """The `factory` servers of one config, or the reason it could not be read."""
    try:
        data = json.loads(config.read_text())
    except FileNotFoundError:
        return "file not found"
    except (OSError, ValueError) as exc:
        return f"not readable as JSON: {exc}"
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return "no mcpServers object"
    return [
        ServerLine(config, name, server_code(config, entry))
        for name, entry in sorted(servers.items())
        if isinstance(entry, dict) and _is_factory(entry)
    ]


def git_head(directory: Path) -> str | None:
    """The short commit checked out in `directory`, or None when git cannot tell."""
    try:
        done = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def mcp_line_hits(settings: Settings) -> list[CheckHit]:
    """`mcp-config-unresolved` per config or server whose code line cannot be read;
    `mcp-code-lines-differ` once when the resolved servers run from more than one directory."""
    hits: list[CheckHit] = []
    by_code: dict[Path, list[ServerLine]] = {}
    for config in configured_paths(settings):
        read = read_config(config)
        if isinstance(read, str):
            hits.append(CheckHit("mcp-config-unresolved", (str(config),), f"MCP config: {read}"))
            continue
        for line in read:
            if line.code is None:
                hits.append(
                    CheckHit(
                        "mcp-config-unresolved",
                        (str(config),),
                        f"MCP server {line.server!r}: its code line could not be read",
                    )
                )
            else:
                by_code.setdefault(line.code, []).append(line)
    if len(by_code) > 1:
        parts = []
        for code, users in sorted(by_code.items()):
            head = git_head(code)
            named = ", ".join(f"{u.config} ({u.server})" for u in users)
            parts.append(f"{code} at {head or 'unknown commit'} by {named}")
        hits.append(
            CheckHit(
                "mcp-code-lines-differ",
                tuple(sorted({str(u.config) for users in by_code.values() for u in users})),
                f"MCP configs point at {len(by_code)} code lines: " + "; ".join(parts),
            )
        )
    return hits

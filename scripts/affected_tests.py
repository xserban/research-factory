"""Which test files a change can affect (used by the Tests workflow on pull requests).

usage: affected_tests.py [--base REF] [--closure N] [--map map.json] [--max-age-days D]
       (changed files = `git diff --name-only REF...HEAD`)
       affected_tests.py --files a b c  (changed files given)
       affected_tests.py --shard I --of N --plan plan.txt   (the files of shard I, balanced by time)
       affected_tests.py --browser --plan plan.txt          (the slow browser files of the plan)

Prints `mode=all` or `mode=touched`, then, for touched, one test file path per line (relative to
platform/) on stdout; the chosen mode, depth and counts go to stderr (the "which tests" job log).
Deterministic, no model, no network.

Pull requests and pushes to main run only the tests the change touches; the nightly full run (and
a manual dispatch) covers what this selection leaves out and refreshes the coverage map. Rules:
- Coverage map first (`--map map.json`, written by scripts/make_coverage_map.py in the nightly run:
  test file -> source files it executed, plus per-file durations). A changed source file the map
  knows selects every test whose recorded files include it. A map that is missing, unreadable or
  older than `--max-age-days` (default 7) is ignored and the import rules below apply to every
  file; the reason goes to the log. A changed source file the map does not know (a new module, a
  non-Python file) also falls back to the import rules.
Import rules (the fallback):
- A changed file that configures the whole suite (pyproject, lock, conftest, this script, the
  workflows) selects all.
- A changed `platform/src/factory/**.py` selects (a) the test files within `--closure` import hops
  of it (default 1: the files that import it directly; a re-export through a package `__init__`
  is resolved to the defining module), and (b) the
  test files named after it: `test_<stem>*.py` and `test_<package>_<stem>*.py`.
- Kernel changes under `platform/src/factory/{events,model,index}/` have a wider blast radius,
  so their depth is 2 (bounded) unless `--closure` is given; `--closure 99` reproduces the old
  unbounded transitive closure.
- A changed test file selects itself; a changed helper selects the tests that import it.
- A changed file outside the Python tree (plugin, docs, scripts, data) selects the tests that
  name its top directory in their source; a non-Python file under `platform/src` (hub JS and CSS)
  selects the tests named after its package and those importing the package's modules.
- Name matching (below, `test_<stem>*`) applies with or without a map.
- A small always-run set covers what imports cannot see (tools and skills registered by name).
Dynamic imports are the known blind spot, accepted for pull requests.

Sharding balances files by measured time (`platform/tests/.durations.json`, refreshed with
`scripts/make_durations.py`); the browser files run in their own job, outside the shards.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "platform" / "src"
TESTS = REPO / "platform" / "tests"

SUITE_WIDE = (
    "platform/pyproject.toml",
    "platform/uv.lock",
    "platform/tests/conftest.py",
    "scripts/affected_tests.py",
    ".github/workflows/tests.yml",
)
KERNEL = tuple(f"platform/src/factory/{d}/" for d in ("events", "model", "index"))
DEFAULT_DEPTH = 1
KERNEL_DEPTH = 2
LEGACY_DEPTH = 50  # at or above this depth, hops through package __init__ files count, as before
# Headless-browser files: slow, run in their own job outside the required shards.
BROWSER = ("test_hub_ui_clicks.py", "test_hub_ui_browser.py")
DURATIONS = TESTS / ".durations.json"
ALWAYS = (
    "test_plugin.py",
    "test_mcp_server.py",
    "test_site_catalog_map.py",
    "test_registry_ownership.py",
)


def _module_of(path: Path) -> str:
    """Dotted module name of a file under src/ or tests/ (`tests.helpers`, `factory.x.y`)."""
    if path.is_relative_to(SRC):
        rel = path.relative_to(SRC).with_suffix("")
    else:
        rel = Path("tests") / path.relative_to(TESTS).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _reexports(files: dict[str, Path]) -> dict[str, dict[str, str]]:
    """`{package: {name: defining module}}` for names a package `__init__` imports from its own
    submodules (`from .foo import Bar`), so `from pkg import Bar` resolves to `pkg.foo`."""
    out: dict[str, dict[str, str]] = {}
    for module, path in files.items():
        if path.name != "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text("utf-8"))
        except SyntaxError:
            continue
        names: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                target = f"{module}.{node.module}"
                for alias in node.names:
                    names[alias.asname or alias.name] = target
        out[module] = names
    return out


def _imports(
    path: Path, own: str, known: set[str], reexports: dict[str, dict[str, str]] | None = None
) -> set[str]:
    """Absolute dotted names the file depends on, relative imports resolved against `own`.

    `from pkg import a, b` depends on the submodules `pkg.a` / `pkg.b` when those are modules,
    and on `pkg` itself only when some name is not a module (it is defined in `pkg`); a name the
    package re-exports from a submodule depends on that submodule too (`reexports`), so a package
    `__init__` is not a hub that ties every importer of the package together."""
    try:
        tree = ast.parse(path.read_text("utf-8"))
    except SyntaxError:
        return set()
    package = own if path.name == "__init__.py" else own.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = package.split(".")
                up = up[: len(up) - (node.level - 1)] if node.level > 1 else up
                base = ".".join([*up, base] if base else up)
            names = [f"{base}.{a.name}" for a in node.names]
            submodules = [n for n in names if n in known]
            found.update(submodules)
            if len(submodules) < len(names) or not names:
                found.add(base)
                table = (reexports or {}).get(base, {})
                found.update(table[a.name] for a in node.names if a.name in table)
    return found


def build_graph() -> tuple[dict[str, set[str]], dict[str, Path]]:
    """`(imported-by edges, module -> file)` over the source tree and the test helper modules and
    test files. An edge `a -> {b}` means module a is imported by b."""
    files: dict[str, Path] = {}
    for root in (SRC, TESTS):
        for path in root.rglob("*.py"):
            files[_module_of(path)] = path
    importers: dict[str, set[str]] = {}
    known = set(files)
    reexports = _reexports(files)
    for module, path in files.items():
        for target in _imports(path, module, known, reexports):
            if target in files:
                importers.setdefault(target, set()).add(module)
    return importers, files


def _closure(
    start: set[str],
    importers: dict[str, set[str]],
    depth: int = 10**6,
    files: dict[str, Path] | None = None,
) -> set[str]:
    """Modules within `depth` import hops of `start` (importer direction). With `files`, a hop
    below LEGACY_DEPTH a package `__init__` does not forward."""
    best = {m: 0 for m in start}
    queue = [(0, m) for m in sorted(start)]
    while queue:
        cost, module = queue.pop(0)
        if best.get(module, cost) < cost:
            continue
        for parent in sorted(importers.get(module, ())):
            if files is not None and depth < LEGACY_DEPTH and files[parent].name == "__init__.py":
                continue
            step = 1
            if cost + step <= depth and cost + step < best.get(parent, depth + 1):
                best[parent] = cost + step
                queue.append((cost + step, parent))
    return set(best)


def _test_files() -> list[Path]:
    """Every test file at any depth under tests/ (some live in subfolders, e.g. tests/document)."""
    return sorted(p for p in TESTS.rglob("test_*.py") if "__pycache__" not in p.parts)


def all_test_files() -> list[str]:
    """Test file paths relative to tests/ (`test_x.py`, `document/test_y.py`)."""
    return [p.relative_to(TESTS).as_posix() for p in _test_files()]


def name_matches(src_path: str) -> set[str]:
    """Test files named after a source file: `test_<stem>*.py`, `test_<package>_<stem>*.py`."""
    path = Path(src_path)
    stem = path.stem
    patterns: list[str] = []
    if stem != "__init__":
        patterns.append(f"test_{stem}*.py")
        if path.parent.name not in ("factory", ""):
            patterns.append(f"test_{path.parent.name}_{stem}*.py")
    else:
        patterns.append(f"test_{path.parent.name}*.py")
    return {
        t.relative_to(TESTS).as_posix()
        for t in _test_files()
        if any(fnmatch.fnmatch(t.name, pat) for pat in patterns)
    }


def depth_for(changed: list[str], closure: int | None) -> int:
    """The import depth: `closure` when given, else 2 for a kernel change, else 1."""
    if closure is not None:
        return closure
    if any(c.startswith(KERNEL) for c in changed):
        return KERNEL_DEPTH
    return DEFAULT_DEPTH


def select(
    changed: list[str], closure: int | None = None, cover: CoverageMap | None = None
) -> tuple[str, list[str]]:
    """`("all", [])` or `("touched", test file names)` for the changed repo-relative paths."""
    if not changed:
        return "touched", sorted(ALWAYS)
    if any(c in SUITE_WIDE for c in changed):
        return "all", []
    depth = depth_for(changed, closure)
    importers, files = build_graph()
    by_path = {p.relative_to(REPO).as_posix(): m for m, p in files.items()}
    start: set[str] = set()
    outside: set[str] = set()
    chosen: set[str] = set()
    for c in changed:
        if c in by_path:
            is_src = c.startswith("platform/src/")
            if is_src:
                chosen |= name_matches(c)
            rel = c.removeprefix("platform/")
            if is_src and cover is not None and rel in cover.known:
                chosen |= {t for t, srcs in cover.tests.items() if rel in srcs}
            else:
                start.add(by_path[c])
        elif c.endswith(".md") and c.startswith("docs/"):
            outside.add("docs")
        elif c.startswith("platform/src/factory/"):
            # a non-Python file in the source tree (hub JS, CSS): by its package
            pkg = c.split("/")[3]
            chosen |= name_matches(f"platform/src/factory/{pkg}/__init__.py")
            prefix = f"factory.{pkg}"
            start |= {m for m in files if m == prefix or m.startswith(prefix + ".")}
        elif not c.startswith("platform/tests/"):
            outside.add(c.split("/", 1)[0])
        # a deleted or non-Python file inside platform/tests (fixtures, golden): by name, below
        else:
            outside.add(Path(c).parent.name)
    reached = _closure(start, importers, depth, files)
    chosen |= {
        files[m].relative_to(TESTS).as_posix()
        for m in reached
        if m.startswith("tests.") and files[m].name.startswith("test_")
    }
    for name in outside:
        for path in _test_files():
            text = path.read_text("utf-8")
            if f'"{name}"' in text or f"/ {name!r}" in text:
                chosen.add(path.relative_to(TESTS).as_posix())
    chosen.update(a for a in ALWAYS if (TESTS / a).exists())
    return "touched", sorted(chosen)


class CoverageMap:
    """`tests`: test file (relative to tests/) -> source files (relative to platform/) it executed;
    `durations`: test file -> seconds; `generated`: ISO date of the nightly run."""

    def __init__(
        self, generated: str, tests: dict[str, frozenset[str]], durations: dict[str, float]
    ) -> None:
        self.generated = generated
        self.tests = tests
        self.durations = durations
        self.known: frozenset[str] = frozenset().union(*tests.values())


def load_map(
    path: str | Path | None, max_age_days: int = 7, today: date | None = None
) -> tuple[CoverageMap | None, str]:
    """`(map, reason)`: the map, or None with the reason it is not used."""
    if not path or not Path(path).is_file():
        return None, "no coverage map available"
    try:
        raw = json.loads(Path(path).read_text("utf-8"))
        generated = str(raw["generated"])
        age = ((today or date.today()) - date.fromisoformat(generated)).days
        tests = {str(k): frozenset(map(str, v)) for k, v in raw["tests"].items()}
        durations = {str(k): float(v) for k, v in raw.get("durations", {}).items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, "coverage map unreadable"
    if age > max_age_days:
        return None, f"coverage map is {age} days old (limit {max_age_days})"
    if not tests:
        return None, "coverage map is empty"
    return CoverageMap(generated, tests, durations), f"coverage map of {generated}"


def _load_durations(path: Path = DURATIONS) -> dict[str, float]:
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): float(v) for k, v in raw.items()}


def split_shards(files: list[str], shards: int, durations: dict[str, float]) -> list[list[str]]:
    """Balanced shards: longest files first, each to the lightest shard (ties: lowest index).
    A file without a recorded time weighs the median. Deterministic for equal inputs."""
    known = sorted(durations[f] for f in files if f in durations)
    median = known[len(known) // 2] if known else 1.0
    weight = {f: durations.get(f, median) for f in files}
    out: list[list[str]] = [[] for _ in range(shards)]
    load = [0.0] * shards
    for f in sorted(files, key=lambda f: (-weight[f], f)):
        i = min(range(shards), key=lambda k: (load[k], k))
        out[i].append(f)
        load[i] += weight[f]
    return [sorted(o) for o in out]


def is_browser(name: str) -> bool:
    return Path(name).name in BROWSER


def _changed_from_git(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def _read_plan(path: str) -> tuple[str, list[str]]:
    lines = Path(path).read_text("utf-8").splitlines()
    mode = lines[0].split("=", 1)[1]
    if mode == "all":
        return mode, all_test_files()
    return mode, [ln.removeprefix("tests/") for ln in lines[1:] if ln]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--files", nargs="*")
    parser.add_argument(
        "--closure", type=int, default=None, help="import depth (default 1; 2 for the kernel)"
    )
    parser.add_argument("--map", help="coverage map written by make_coverage_map.py")
    parser.add_argument("--max-age-days", type=int, default=7)
    parser.add_argument(
        "--plan", help="a plan file written by this script (for --shard / --browser)"
    )
    parser.add_argument("--shard", type=int)
    parser.add_argument("--of", type=int, default=4)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args(argv)
    if args.plan:
        _, names = _read_plan(args.plan)
        if args.browser:
            picked = [n for n in names if is_browser(n)]
        else:
            rest = [n for n in names if not is_browser(n)]
            cover, _ = load_map(args.map, 10**6)
            durations = {**_load_durations(), **(cover.durations if cover else {})}
            picked = split_shards(rest, args.of, durations)[args.shard or 0]
        for name in picked:
            print(f"tests/{name}")
        return 0
    changed = args.files if args.files is not None else _changed_from_git(args.base)
    cover, reason = load_map(args.map, args.max_age_days)
    mode, names = select(changed, args.closure, cover)
    depth = depth_for(changed, args.closure)
    total = len(all_test_files())
    chosen = total if mode == "all" else len(names)
    print(f"mode={mode}")
    for name in names:
        print(f"tests/{name}")
    print(
        f"plan: mode={mode} source={reason}; fallback depth={depth}; "
        f"selected={chosen} of {total} test files "
        f"({len(changed)} changed files)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Which test files a change can affect (used by the Tests workflow on pull requests).

usage: affected_tests.py [--base REF]   (changed files = `git diff --name-only REF...HEAD`)
       affected_tests.py --files a b c  (changed files given)

Prints `mode=all` or `mode=touched`, then, for touched, one test file path per line (relative to
platform/). Deterministic, no model, no network.

Rules (a change selects tests; when unsure it selects more, never fewer):
- A changed file that configures the whole suite (pyproject, lock, conftest, this script, the
  workflows) selects all.
- A changed `platform/src/factory/**.py` selects every test whose import closure reaches it: the
  import graph covers the source tree and the helper modules under `platform/tests/` (non-test
  files), so a change to a widely imported module selects most tests.
- A changed test file selects itself; a changed helper selects the tests that import it.
- A changed file outside the Python tree (plugin, docs, scripts, data files) selects the tests
  that name its top directory in their source (they read it by path).
- A small always-run set covers what imports cannot see (tools and skills registered by name).
Dynamic imports are the known blind spot; the full run on every push to main covers it.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
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


def _imports(path: Path, own: str, known: set[str]) -> set[str]:
    """Absolute dotted names the file depends on, relative imports resolved against `own`.

    `from pkg import a, b` depends on the submodules `pkg.a` / `pkg.b` when those are modules,
    and on `pkg` itself only when some name is not a module (it is defined in `pkg`); so a
    package `__init__` is not a hub that ties every importer of the package together."""
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
    for module, path in files.items():
        for target in _imports(path, module, known):
            if target in files:
                importers.setdefault(target, set()).add(module)
    return importers, files


def _closure(start: set[str], importers: dict[str, set[str]]) -> set[str]:
    seen, stack = set(start), list(start)
    while stack:
        for parent in importers.get(stack.pop(), ()):
            if parent not in seen:
                seen.add(parent)
                stack.append(parent)
    return seen


def all_test_files() -> list[str]:
    return sorted(p.name for p in TESTS.glob("test_*.py"))


def select(changed: list[str]) -> tuple[str, list[str]]:
    """`("all", [])` or `("touched", test file names)` for the changed repo-relative paths."""
    if not changed:
        return "touched", sorted(ALWAYS)
    if any(c in SUITE_WIDE for c in changed):
        return "all", []
    importers, files = build_graph()
    by_path = {p.relative_to(REPO).as_posix(): m for m, p in files.items()}
    start: set[str] = set()
    outside: set[str] = set()
    for c in changed:
        if c in by_path:
            start.add(by_path[c])
        elif c.endswith(".md") and c.startswith("docs/"):
            outside.add("docs")
        elif not c.startswith(("platform/src/", "platform/tests/")):
            outside.add(c.split("/", 1)[0])
        # a deleted or non-Python file inside platform/ (fixtures, golden): by name, below
        elif c.startswith("platform/tests/"):
            outside.add(Path(c).parent.name)
    reached = _closure(start, importers)
    chosen = {
        Path(files[m]).name
        for m in reached
        if m.startswith("tests.") and Path(files[m]).name.startswith("test_")
    }
    for name in outside:
        for path in TESTS.glob("test_*.py"):
            if f'"{name}"' in path.read_text("utf-8") or f"/ {name!r}" in path.read_text("utf-8"):
                chosen.add(path.name)
    chosen.update(a for a in ALWAYS if (TESTS / a).exists())
    return "touched", sorted(chosen)


def _changed_from_git(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--files", nargs="*")
    args = parser.parse_args(argv)
    changed = args.files if args.files is not None else _changed_from_git(args.base)
    mode, names = select(changed)
    print(f"mode={mode}")
    for name in names:
        print(f"tests/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

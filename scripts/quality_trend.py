"""Append one JSON line of quality metrics to docs/quality-trend.jsonl.

Keys: date, commit, tests_collected, ruff_findings, mypy_errors, py_files, modules, test_files.
`modules` counts files under platform/src/factory. The three tool counts are null when the tool
cannot be run (collection and mypy are the slow ones; `--fast` skips them and records null).
Run by hand or from the weekly job; see docs/runbook-ci.md. Never judges: it only counts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLATFORM = ROOT / "platform"
OUT = ROOT / "docs" / "quality-trend.jsonl"


def _run(cmd: list[str]) -> str | None:
    try:
        done = subprocess.run(cmd, cwd=PLATFORM, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout + done.stderr


def commit() -> str:
    out = _run(["git", "rev-parse", "--short", "HEAD"])
    return out.strip() if out else "unknown"


def count_files(root: Path, pattern: str = "*.py") -> int:
    return sum(1 for p in root.rglob(pattern) if "__pycache__" not in p.parts)


def ruff_findings() -> int | None:
    out = _run(["uv", "run", "ruff", "check", "src", "tests", "--output-format", "concise"])
    if out is None:
        return None
    return len(re.findall(r"^\S+:\d+:\d+: ", out, re.MULTILINE))


def mypy_errors() -> int | None:
    out = _run(["uv", "run", "mypy", "--strict", "src"])
    if out is None:
        return None
    return len(re.findall(r": error: ", out))


def tests_collected() -> int | None:
    out = _run(["uv", "run", "pytest", "--collect-only", "-q", "-m", "not network and not slow"])
    if out is None:
        return None
    m = re.search(r"(\d+) tests? collected|(\d+)/\d+ tests collected", out)
    if m:
        return int(m.group(1) or m.group(2))
    return sum(1 for line in out.splitlines() if "::" in line) or None


def collect(fast: bool = False) -> dict[str, object]:
    return {
        "date": dt.date.today().isoformat(),
        "commit": commit(),
        "tests_collected": None if fast else tests_collected(),
        "ruff_findings": ruff_findings(),
        "mypy_errors": None if fast else mypy_errors(),
        "py_files": count_files(PLATFORM / "src") + count_files(PLATFORM / "tests"),
        "modules": count_files(PLATFORM / "src" / "factory"),
        "test_files": count_files(PLATFORM / "tests"),
    }


def append(record: dict[str, object], path: Path) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--fast", action="store_true", help="skip test collection and mypy")
    args = parser.parse_args(argv)
    record = collect(fast=args.fast)
    append(record, args.out)
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

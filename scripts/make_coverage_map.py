"""Build the selection map (test file -> source files it ran, plus durations) from a nightly run.

usage: make_coverage_map.py --out map.json [--data .coverage ...] [--junit junit-0.xml ...]
                            [--merge part.json ...]
                            [--durations-out platform/tests/.durations.json]

The nightly run records coverage with a dynamic context per test (`--cov=factory
--cov-context=test`, config `platform/.coveragerc-map`). This script keeps only which source
files each test file executed (no line data), so the map stays small and deterministic (sorted
keys and lists), and the per-file durations from the junit reports. `--merge` combines the partial
maps written by the four shards. Paths: tests relative to platform/tests, sources relative to
platform. No model, no network.
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

PLATFORM = Path(__file__).resolve().parent.parent / "platform"
TESTS = PLATFORM / "tests"


def tests_by_source(data_file: str) -> dict[str, set[str]]:
    """`{test file: {source file}}` from one coverage data file with per-test contexts."""
    from coverage import CoverageData

    data = CoverageData(basename=data_file)
    data.read()
    out: dict[str, set[str]] = {}
    for src in data.measured_files():
        try:
            rel = Path(src).resolve().relative_to(PLATFORM).as_posix()
        except ValueError:
            continue
        if not rel.startswith("src/"):
            continue
        contexts: set[str] = set()
        for ctxs in data.contexts_by_lineno(src).values():
            contexts.update(ctxs)
        for ctx in contexts:
            node = ctx.split("|")[0]  # `tests/test_x.py::test_y` (or `tests.test_x.test_y`)
            if "::" in node:
                path = node.split("::")[0]
            else:
                parts = node.split(".")
                path = ""
                for n in range(len(parts), 0, -1):
                    cand = "/".join(parts[:n]) + ".py"
                    if (PLATFORM / cand).is_file():
                        path = cand
                        break
            if path.startswith("tests/"):
                out.setdefault(path.removeprefix("tests/"), set()).add(rel)
    return out


def durations_from_junit(xmls: list[Path]) -> dict[str, float]:
    files = {
        p.relative_to(TESTS).with_suffix("").as_posix().replace("/", "."): p.relative_to(
            TESTS
        ).as_posix()
        for p in TESTS.rglob("test_*.py")
    }
    total: dict[str, float] = {}
    for xml in xmls:
        for case in ET.parse(xml).getroot().iter("testcase"):
            parts = (case.get("classname") or "").split(".")[1:]
            for n in range(len(parts), 0, -1):
                key = ".".join(parts[:n])
                if key in files:
                    total[files[key]] = total.get(files[key], 0.0) + float(case.get("time") or 0)
                    break
    return {k: round(v, 1) for k, v in sorted(total.items())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--data", nargs="*", default=[])
    parser.add_argument("--junit", nargs="*", default=[])
    parser.add_argument("--durations-out", help="also write the durations alone (committed file)")
    parser.add_argument("--merge", nargs="*", default=[])
    args = parser.parse_args(argv)
    tests: dict[str, set[str]] = {}
    durations: dict[str, float] = {}
    for data_file in args.data:
        for t, srcs in tests_by_source(data_file).items():
            tests.setdefault(t, set()).update(srcs)
    durations.update(durations_from_junit([Path(j) for j in args.junit]))
    for part in args.merge:
        raw = json.loads(Path(part).read_text("utf-8"))
        for t, srcs in raw["tests"].items():
            tests.setdefault(t, set()).update(srcs)
        durations.update(raw.get("durations", {}))
    out = {
        "generated": date.today().isoformat(),
        "tests": {t: sorted(s) for t, s in sorted(tests.items())},
        "durations": dict(sorted(durations.items())),
    }
    if args.durations_out:
        Path(args.durations_out).write_text(json.dumps(out["durations"], indent=0) + "\n", "utf-8")
    Path(args.out).write_text(json.dumps(out, separators=(",", ":")) + "\n", "utf-8")
    print(f"{len(tests)} test files mapped, {len(durations)} durations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

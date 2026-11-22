"""Check that docs/MAP.md matches what scripts/gen_map.py would generate now.

Exit 0 when fresh, 1 when stale. The commit-hash line is ignored: it changes on every commit.
`--generated FILE` compares against a text already produced (used by tests); otherwise the map is
regenerated in memory with gen_map.render(). Nothing is written. Needs the platform environment
(`uv run --project platform python scripts/check_map_fresh.py`).
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_COMMIT_LINE = re.compile(r"^Generated at commit `[^`]*`", re.MULTILINE)


def normalise(text: str) -> str:
    return _COMMIT_LINE.sub("Generated at commit `-`", text)


def is_fresh(generated: str, committed: str) -> bool:
    return normalise(generated) == normalise(committed)


def _render() -> str:
    spec = importlib.util.spec_from_file_location("gen_map", ROOT / "scripts" / "gen_map.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text: str = module.render()[0]
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=ROOT / "docs" / "MAP.md")
    parser.add_argument("--generated", type=Path, default=None)
    args = parser.parse_args(argv)
    generated = args.generated.read_text() if args.generated else _render()
    if is_fresh(generated, args.map.read_text()):
        print(f"{args.map} is fresh")
        return 0
    print(f"{args.map} is stale: run scripts/gen_map.py and commit the result", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

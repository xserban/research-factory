"""Writes `results/bakeoff-<date>.md` from `results/scores.json` (numbers and ids only).

One table per format (candidate x criteria a-e plus the human-check counts from
`data/sheet_marks.csv`, the filled `sheet.csv`, when present), the pinned tool versions, the seeds
and the corpus ids. No document text is read or written.
"""

from __future__ import annotations

import csv
import datetime
import json
import sys
import tomllib
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FORMATS = {"html": "HTML", "latex": "LaTeX e-print", "pdf": "PDF"}
MARKS = HERE / "data" / "sheet_marks.csv"


def fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def human_counts() -> dict[str, Counter[str]]:
    counts: dict[str, Counter[str]] = {}
    if MARKS.exists():
        with MARKS.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                mark = (row.get("mark") or "").strip().lower()
                if mark:
                    counts.setdefault(f"{row['candidate']}/{row['format']}", Counter())[mark] += 1
    return counts


def versions() -> list[str]:
    from factory.document.converter import ConverterUnavailable

    from adapters import REGISTRY

    out = []
    for (cand, f), cls in REGISTRY.items():
        try:
            version = cls().version()
        except ConverterUnavailable:
            version = "unavailable on this machine"
        out.append(f"- `{cand}` ({f}): {version}")
    return out


def main() -> int:
    scores = json.loads((HERE / "results" / "scores.json").read_text())
    humans = human_counts()
    with (HERE / "corpus.toml").open("rb") as handle:
        ids = [p["id"] for p in tomllib.load(handle)["paper"]]
    today = datetime.date.today().isoformat()
    lines = [f"# Converter bake-off results ({today})", ""]
    lines += [
        "Numbers and arXiv ids only; no document text. Criteria are defined in `score.py`.",
        "",
    ]
    for key, title in FORMATS.items():
        rows = {k: v for k, v in scores.items() if k.endswith("/" + key)}
        if not rows:
            continue
        lines += [
            f"## {title}",
            "",
            "| candidate | ok/papers | (a) determinism | (b) s/page median | (b) p90 | "
            "(c) sections ratio | (c) tables ratio | (c) equal table count | (d) fidelity | "
            "(d) fidelity, ok papers | (e) failures | (e) empty | human c/m/w |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for name, e in sorted(rows.items()):
            h = humans.get(name)
            human = f"{h['correct']}/{h['minor']}/{h['wrong']}" if h else "-"
            cand = name.split("/")[0] + (" (reference)" if name.startswith("latexml-html") else "")
            lines.append(
                f"| {cand} | {e['n_ok']}/{e['n_papers']} | {fmt(e['determinism'])} | "
                f"{fmt(e['sec_per_page_median'])} | {fmt(e['sec_per_page_p90'])} | "
                f"{fmt(e.get('sections_ratio'))} | {fmt(e.get('tables_ratio'))} | "
                f"{fmt(e.get('tables_equal_share'))} | {fmt(e.get('fidelity'))} | "
                f"{fmt(e.get('fidelity_ok'))} | {e['failures']} | {e['empty_outputs']} | {human} |"
            )
        lines.append("")
    lines += ["## Pinned versions", "", *versions(), ""]
    lines += ["## Seeds", "", "- Human-check sample (`score.py --sheet`): seed 49.", ""]
    lines += ["## Corpus", "", ", ".join(ids), ""]
    path = HERE / "results" / f"bakeoff-{today}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

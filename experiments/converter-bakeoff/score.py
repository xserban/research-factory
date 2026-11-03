"""Scores the bake-off runs (experiment code). Reads `results/runs.jsonl` and `data/out/`.

Per (candidate, format), `results/scores.json` holds numbers only:

(a) `determinism`: share of successful pairs (both runs produced Markdown) with hash1 == hash2.
(b) `sec_per_page_median`, `sec_per_page_p90`: conversion seconds divided by the paper's PDF page
    count (also the divisor for HTML and LaTeX, so the columns are comparable).
(c) structure against the reference `latexml-html/html` output of the same paper (reference
    excluded): `sections_ratio` and `tables_ratio` (candidate total / reference total over papers
    where both exist) and `tables_equal_share` (share of papers with the same table count).
(d) table fidelity. A reference table is read from the anchorised reference via `parse_manifest`:
    its cells are the `t<n>.r<r>.c<c>` anchors. Numeric tokens are `[-+]?\\d+(\\.\\d+)?%?` found in
    each cell (U+2212 read as `-`). For a reference table R and candidate table C:
      token_f1 = F1 of the multisets of numeric tokens of R and C;
      position_f1 = F1 of the multisets of (row, column, token) triples of R and C (exact cell
                    position agreement of those numbers);
      score(R, C) = (token_f1 + position_f1) / 2, in [0, 1].
    Each reference table with at least one numeric token is matched to the unused candidate table
    of the same paper with the highest score (greedy, best pair first, one-to-one); an unmatched
    reference table scores 0. `fidelity` is the mean over all such reference tables of the format's
    papers, a failed paper contributing 0 for each of its tables; `fidelity_ok` leaves failed
    papers out.
(e) `failures` (count of pairs with an error or no output), `empty_outputs`, and `n_papers`.

`--sheet` writes `data/sheet.csv` for the human check: 30 random candidate tables, seed 49, ten per
format, each with its cells (short Markdown), the paper's arXiv HTML link and a blank `mark`
(correct / minor / wrong). Table numbers come from the caption label when there is one.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from factory.document.anchors import AnchorKind, parse_manifest  # noqa: E402

RUNS = HERE / "results" / "runs.jsonl"
SCORES = HERE / "results" / "scores.json"
OUT = HERE / "data" / "out"
SHEET = HERE / "data" / "sheet.csv"
SEED = 49
REFERENCE = ("latexml-html", "html")
NUMBER = re.compile(r"[-+]?\d+(\.\d+)?%?")
MINUS = chr(0x2212)
CELL_ID = re.compile(r"^(t\d+)\.r(\d+)\.c(\d+)$")

Grid = dict[tuple[int, int], str]
_cache: dict[Path, tuple[dict[str, int], dict[str, Grid], dict[str, str]]] = {}


def load(path: Path) -> tuple[dict[str, int], dict[str, Grid], dict[str, str]]:
    """({'sections': n, 'tables': n}, {table id: grid}, {table id: table anchor text})."""
    if path not in _cache:
        manifest = parse_manifest(path.read_text(encoding="utf-8"))
        grids: dict[str, Grid] = defaultdict(dict)
        texts: dict[str, str] = {}
        sections = 0
        for anchor in manifest.anchors:
            if anchor.kind is AnchorKind.SECTION:
                sections += 1
            elif anchor.kind is AnchorKind.TABLE:
                grids.setdefault(anchor.id, {})
                texts[anchor.id] = anchor.text
            elif anchor.kind is AnchorKind.CELL:
                m = CELL_ID.match(anchor.id)
                if m:
                    grids[m.group(1)][(int(m.group(2)), int(m.group(3)))] = anchor.text
        counts = {"sections": sections, "tables": len(texts)}
        _cache[path] = (counts, dict(grids), texts)
    return _cache[path]


def numbers(grid: Grid) -> Counter[tuple[int, int, str]]:
    out: Counter[tuple[int, int, str]] = Counter()
    for (r, c), text in grid.items():
        for m in NUMBER.finditer(text.replace(MINUS, "-")):
            out[(r, c, m.group(0))] += 1
    return out


def f1(a: Counter, b: Counter) -> float:
    if not a and not b:
        return 1.0
    hit = sum((a & b).values())
    if hit == 0:
        return 0.0
    p, r = hit / sum(b.values()), hit / sum(a.values())
    return 2 * p * r / (p + r)


def table_score(ref: Counter[tuple[int, int, str]], cand: Counter[tuple[int, int, str]]) -> float:
    tokens = f1(
        Counter(t for (_, _, t), n in ref.items() for _ in range(n)),
        Counter(t for (_, _, t), n in cand.items() for _ in range(n)),
    )
    return (tokens + f1(ref, cand)) / 2


def match_paper(ref_grids: dict[str, Grid], cand_grids: dict[str, Grid]) -> list[float]:
    """Greedy one-to-one best-pair matching; one score per reference table with numbers."""
    refs = {k: numbers(g) for k, g in ref_grids.items()}
    refs = {k: v for k, v in refs.items() if v}
    cands = {k: numbers(g) for k, g in cand_grids.items()}
    pairs = sorted(
        ((table_score(rv, cv), rk, ck) for rk, rv in refs.items() for ck, cv in cands.items()),
        key=lambda t: (-t[0], t[1], t[2]),
    )
    used_r: set[str] = set()
    used_c: set[str] = set()
    scores: dict[str, float] = {}
    for score, rk, ck in pairs:
        if rk not in used_r and ck not in used_c:
            used_r.add(rk)
            used_c.add(ck)
            scores[rk] = score
    return [scores.get(rk, 0.0) for rk in refs]


def p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]


def read_runs(path: Path = RUNS) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def score(runs: list[dict]) -> dict:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in runs:
        groups[(row["candidate"], row["format"])].append(row)
    ref_rows = {r["id"]: r for r in groups.get(REFERENCE, []) if r["hash1"] and not r["error"]}
    result: dict = {}
    for (cand, fmt), rows in sorted(groups.items()):
        ok = [r for r in rows if r["hash1"] and r["hash2"] and not r["error"]]
        entry: dict = {
            "n_papers": len(rows),
            "n_ok": len(ok),
            "failures": len(rows) - len(ok),
            "empty_outputs": sum(1 for r in rows if (r["error"] or "").endswith("empty output")),
            "determinism": (sum(r["hash1"] == r["hash2"] for r in ok) / len(ok)) if ok else None,
        }
        per_page = [r["seconds"] / r["pages"] for r in ok if r["seconds"] and r["pages"]]
        entry["sec_per_page_median"] = round(statistics.median(per_page), 3) if per_page else None
        entry["sec_per_page_p90"] = round(p90(per_page), 3) if per_page else None
        if (cand, fmt) != REFERENCE:
            sec_c = sec_r = tab_c = tab_r = equal = both = 0
            fid_all: list[float] = []
            fid_ok: list[float] = []
            for r in rows:
                ref = ref_rows.get(r["id"])
                if ref is None:
                    continue
                ref_counts, ref_grids, _ = load(OUT / REFERENCE[0] / REFERENCE[1] / f"{r['id']}.md")
                path = OUT / cand / fmt / f"{r['id']}.md"
                if r in ok and path.exists():
                    counts, grids, _ = load(path)
                    sec_c, sec_r = sec_c + counts["sections"], sec_r + ref_counts["sections"]
                    tab_c, tab_r = tab_c + counts["tables"], tab_r + ref_counts["tables"]
                    equal += counts["tables"] == ref_counts["tables"]
                    both += 1
                    scores = match_paper(ref_grids, grids)
                    fid_ok += scores
                else:
                    scores = match_paper(ref_grids, {})
                fid_all += scores
            entry["sections_ratio"] = round(sec_c / sec_r, 3) if sec_r else None
            entry["tables_ratio"] = round(tab_c / tab_r, 3) if tab_r else None
            entry["tables_equal_share"] = round(equal / both, 3) if both else None
            entry["fidelity"] = round(statistics.fmean(fid_all), 4) if fid_all else None
            entry["fidelity_ok"] = round(statistics.fmean(fid_ok), 4) if fid_ok else None
            entry["n_reference_tables"] = len(fid_all)
        result[f"{cand}/{fmt}"] = entry
    return result


def markdown_cells(grid: Grid, max_rows: int = 8, max_cols: int = 8) -> str:
    rows = sorted({r for r, _ in grid})[:max_rows]
    cols = sorted({c for _, c in grid})[:max_cols]
    lines = [
        "| " + " | ".join(grid.get((r, c), "").replace("|", "/") for c in cols) + " |" for r in rows
    ]
    return "\n".join(lines)


def sheet(runs: list[dict]) -> None:
    """30 random candidate tables, ten per format, seed 49 (see module docstring)."""
    rng = random.Random(SEED)
    pools: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for row in sorted(runs, key=lambda r: (r["format"], r["candidate"], r["id"])):
        path = OUT / row["candidate"] / row["format"] / f"{row['id']}.md"
        if row["hash1"] and not row["error"] and path.exists():
            _, grids, _ = load(path)
            pools[row["format"]] += [(row["candidate"], row["id"], t) for t in sorted(grids)]
    rows = []
    for fmt in sorted(pools):
        for cand, pid, table in rng.sample(pools[fmt], min(10, len(pools[fmt]))):
            meta = json.loads((HERE / "data" / "raw" / pid / "meta.json").read_text())
            _, grids, texts = load(OUT / cand / fmt / f"{pid}.md")
            label = re.match(r"\s*Table\s+(\d+)", texts.get(table, ""))
            rows.append(
                {
                    "seed": SEED,
                    "format": fmt,
                    "candidate": cand,
                    "id": pid,
                    "candidate_table": table,
                    "paper_table": label.group(1) if label else "",
                    "arxiv_html": f"https://arxiv.org/html/{meta['version']}",
                    "cells": markdown_cells(grids[table]),
                    "mark": "",
                }
            )
    SHEET.parent.mkdir(exist_ok=True)
    with SHEET.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {SHEET}")


def main() -> int:
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet", action="store_true")
    parser.add_argument("--runs", type=Path, default=RUNS)
    parser.add_argument("--scores", type=Path, default=SCORES)
    parser.add_argument("--out-dir", type=Path, default=OUT)
    args = parser.parse_args()
    OUT = args.out_dir
    runs = read_runs(args.runs)
    if args.sheet:
        sheet(runs)
        return 0
    scores = score(runs)
    args.scores.write_text(json.dumps(scores, indent=2, sort_keys=True) + "\n")
    for key, entry in scores.items():
        print(key, {k: v for k, v in entry.items() if k != "n_papers"})
    return 0


if __name__ == "__main__":
    sys.exit(main())

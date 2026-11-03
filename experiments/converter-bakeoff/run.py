"""Bake-off runner: every (paper, candidate, format) pair is converted twice, each time in a fresh
subprocess running the same code path (`--child`).

Per pair, `results/runs.jsonl` gets one line `{id, candidate, format, hash1, hash2, seconds, pages,
warnings, error}`. `hash` is the sha256 of the anchorised Markdown (`factory.document.convert`);
`seconds` is the conversion call of the first run (imports and, for Docling, model load excluded);
`pages` is the page count of the paper's PDF (also used as the divisor for HTML and LaTeX). A
failed run is recorded, never retried. A pair already in the runs file is skipped (resumable).
GROBID runs against one long-lived service, so its determinism measures the service output.
Warnings and errors are reduced to a safe vocabulary: no document text enters the runs file.
Output goes to `data/out/<candidate>/<format>/<id>.md` (git-ignored).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
OUT = HERE / "data" / "out"
RUNS = HERE / "results" / "runs.jsonl"
TIMEOUT = 1500  # seconds per conversion
SAFE_WARNING = re.compile(
    r"^(table \d+: [a-z ]+|pandoc stderr lines: \d+|docling status: [a-z_]+)$"
)


def clean_error(exc: BaseException) -> str:
    """Exception class plus a message with quoted strings and digits runs kept short (<=100)."""
    message = re.sub(r"(['\"]).*?\1", "<q>", str(exc))
    message = " ".join(message.split())[:100]
    name = type(exc).__name__
    if name in {"ValueError", "RuntimeError", "ManifestError", "ConverterUnavailable"}:
        return f"{name}: {message}"
    return name


def child(candidate: str, fmt: str, pid: str, out: Path) -> int:
    """One conversion in this process; prints a JSON result line and writes the Markdown."""
    sys.path.insert(0, str(HERE))
    from factory.document.converter import ConverterUnavailable, convert

    from adapters import FORMATS, make

    result: dict = {"hash": None, "seconds": None, "warnings": [], "error": None}
    try:
        converter = make(candidate, fmt)
        name, media_type = FORMATS[fmt]
        raw = (RAW / pid / name).read_bytes()
        converter.version()
        prepare = getattr(converter, "prepare", None)
        if prepare:
            prepare()
        start = time.perf_counter()
        converted = convert(converter, raw, media_type)
        result["seconds"] = round(time.perf_counter() - start, 3)
        if not converted.markdown.strip():
            raise ValueError("empty output")
        out.write_text(converted.markdown, encoding="utf-8")
        result["hash"] = converted.markdown_hash
        result["warnings"] = [
            w if SAFE_WARNING.match(w) else "<redacted>" for w in converted.warnings[:20]
        ]
    except ConverterUnavailable as exc:
        result["error"] = "UNAVAILABLE: " + clean_error(exc)
    except Exception as exc:
        result["error"] = clean_error(exc)
    print("RESULT " + json.dumps(result))
    return 0


def spawn(candidate: str, fmt: str, pid: str, out: Path) -> dict:
    cmd = [sys.executable, str(Path(__file__)), "--child", candidate, fmt, pid, str(out)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, cwd=HERE)
    except subprocess.TimeoutExpired:
        return {"hash": None, "seconds": None, "warnings": [], "error": f"timeout {TIMEOUT}s"}
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    if not lines:
        return {
            "hash": None,
            "seconds": None,
            "warnings": [],
            "error": f"child exit {proc.returncode} without result",
        }
    return json.loads(lines[-1][len("RESULT ") :])


def page_count(pid: str) -> int | None:
    import pymupdf

    try:
        with pymupdf.open(RAW / pid / "pdf") as doc:
            return doc.page_count
    except Exception:
        return None


def done_pairs(runs: Path) -> set[tuple[str, str, str]]:
    if not runs.exists():
        return set()
    rows = [json.loads(ln) for ln in runs.read_text().splitlines() if ln.strip()]
    return {(r["id"], r["candidate"], r["format"]) for r in rows}


def main() -> int:
    from adapters import REGISTRY

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", nargs=4, metavar=("CAND", "FMT", "ID", "OUT"))
    parser.add_argument("--ids", nargs="*", help="restrict to these arXiv ids (default: corpus)")
    parser.add_argument("--candidates", nargs="*", help="restrict to these candidates")
    parser.add_argument("--formats", nargs="*", help="restrict to these formats")
    parser.add_argument("--runs", type=Path, default=RUNS)
    parser.add_argument("--out-dir", type=Path, default=OUT)
    args = parser.parse_args()
    if args.child:
        cand, fmt, pid, out = args.child
        return child(cand, fmt, pid, Path(out))

    with (HERE / "corpus.toml").open("rb") as handle:
        ids = [p["id"] for p in tomllib.load(handle)["paper"]]
    ids = [i for i in ids if not args.ids or i in args.ids]
    pairs = [
        (cand, fmt)
        for (cand, fmt) in REGISTRY
        if (not args.candidates or cand in args.candidates)
        and (not args.formats or fmt in args.formats)
    ]
    args.runs.parent.mkdir(parents=True, exist_ok=True)
    skip = done_pairs(args.runs)
    for cand, fmt in pairs:
        for pid in ids:
            if (pid, cand, fmt) in skip:
                continue
            out = args.out_dir / cand / fmt / f"{pid}.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            first = spawn(cand, fmt, pid, out)
            if (first["error"] or "").startswith("UNAVAILABLE"):
                print(f"{cand}/{fmt}: {first['error']}; skipping candidate", file=sys.stderr)
                break
            with tempfile.TemporaryDirectory() as tmp:
                second = spawn(cand, fmt, pid, Path(tmp) / "second.md")
            row = {
                "id": pid,
                "candidate": cand,
                "format": fmt,
                "hash1": first["hash"],
                "hash2": second["hash"],
                "seconds": first["seconds"],
                "pages": page_count(pid),
                "warnings": first["warnings"],
                "error": first["error"] or second["error"],
            }
            with args.runs.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
            same = row["hash1"] is not None and row["hash1"] == row["hash2"]
            print(
                f"{cand}/{fmt} {pid} s={row['seconds']} same={same} err={row['error']}", flush=True
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())

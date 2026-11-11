"""Pilot run-cost baseline: reads the pilot's live transcripts and writes a dated report.

Stdlib only. Usage:
    python3 pilot_baseline.py <screeners-folder>

Reads: every ``*.live`` file in the screeners folder (one per headless ``claude -p`` run,
written by ``live.py``). Each run's ``== finished`` line gives the CLI-reported cost
(``total_cost_usd``, an API-equivalent price, not a subscription charge), the turn count
and the subtype. Tool calls appear as ``HH:MM:SS > <tool>`` lines; screening decisions
appear as verdict lines (one per item of a ``screen_record`` call); mining rows are counted
from the ``written`` lists of ``mine_record`` results. The ``.log`` files and the shell
drivers are not parsed for numbers; the family, miner and model mapping below was taken
from the drivers (``*.sh``) and their prompt files by hand.

Writes: ``pilot-baseline-2026-11-11.md`` next to this script. Nothing is written to the
screeners folder.
"""

from __future__ import annotations

import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPORT_NAME = "pilot-baseline-2026-11-11.md"

FIN_RE = re.compile(r"== finished: (\S+)\s+cost \$([0-9.]+)\s+turns (\d+)")
TOOL_RE = re.compile(r"^\d{2}:\d{2}:\d{2} > (\w+)", re.M)
VERDICT_RE = re.compile(r"^\d{2}:\d{2}:\d{2} {3}(include|exclude|cannot-assess|unsure) ", re.M)
WRITTEN_RE = re.compile(r'written\\":\[([^\]]*)\]')
REJECTED_RE = re.compile(r'rejected\\":\[\{')
NOBATCH = "(no batch served)"
NAME_RE = re.compile(r"^(.*?)-\d{6,}")

MODEL_HAIKU = "claude-haiku-5-5"
MODEL_SONNET = "claude-sonnet-5-5"

# Family prefix -> (kind, miner, model, model_source). Derived from the drivers:
# main_waves.sh (run_pass.sh, MODEL unset), ft_waves.sh (sonnet), ftB_waves.sh (haiku),
# mine_waves*.sh, autopilot*.sh (the "waves" calls pass the model explicitly).
KNOWN: dict[str, tuple[str, str, str, str]] = {
    "main": ("screening", "", MODEL_HAIKU, "driver default (MODEL unset)"),
    "ft-main": ("full-text", "", MODEL_SONNET, "ft_waves.sh"),
    "ftB-main": ("full-text", "", MODEL_HAIKU, "ftB_waves.sh"),
    "mine": ("mining", "m-descriptors", MODEL_SONNET, "mine_waves.sh"),
    "mineB": ("mining", "m-descriptors", MODEL_SONNET, "mine_waves_B_sonnet.sh"),
    "mineBH": ("mining", "m-descriptors", MODEL_HAIKU, "mine_waves_B_haiku.sh"),
    "mineH": ("mining", "m-descriptors", MODEL_HAIKU, "mine_waves_haiku.sh"),
    "mineM": ("mining", "m-mapping", MODEL_HAIKU, "mine_waves_map_A.sh"),
    "mineD": ("mining", "m-design-approach", MODEL_HAIKU, "mine_waves_design_A.sh"),
    "dB": ("mining", "m-design-approach", MODEL_SONNET, "autopilot (pass B)"),
    "mapA2": ("mining", "m-mapping", MODEL_HAIKU, "autopilot (v2 pass A)"),
    "mapB": ("mining", "m-mapping", MODEL_SONNET, "autopilot (pass B)"),
    "mapB2": ("mining", "m-mapping", MODEL_SONNET, "autopilot (v2 pass B)"),
    "sumA": ("mining", "m-summary", MODEL_HAIKU, "autopilot (pass A)"),
    "sumA2": ("mining", "m-summary", MODEL_HAIKU, "autopilot (v2 pass A)"),
    "sumB": ("mining", "m-summary", MODEL_SONNET, "autopilot (pass B)"),
    "sumB2": ("mining", "m-summary", MODEL_SONNET, "autopilot (v2 pass B)"),
    "stgA": ("mining", "m-stages", MODEL_HAIKU, "autopilot (pass A)"),
    "stgB": ("mining", "m-stages", MODEL_SONNET, "autopilot (pass B)"),
    "clsA": ("mining", "m-classification", MODEL_HAIKU, "autopilot (pass A)"),
    "clsB": ("mining", "m-classification", MODEL_SONNET, "autopilot (pass B)"),
}


@dataclass
class Family:
    name: str
    kind: str = "other"
    miner: str = ""
    model: str = "not recorded"
    model_source: str = ""
    files: int = 0
    finished: int = 0
    unfinished: int = 0
    cost: float = 0.0
    turns: list[int] = field(default_factory=list)
    units: int = 0
    mine_calls: int = 0
    rejected_results: int = 0
    no_batch_runs: int = 0
    zero_unit_runs: int = 0
    subtypes: Counter = field(default_factory=Counter)


def family_of(stem: str) -> tuple[str, str, str, str, str]:
    """Return (family, kind, miner, model, model_source) for a file stem."""
    m = NAME_RE.match(stem)
    fam = m.group(1) if m else stem
    if fam.startswith("close-m-"):
        miner = fam[len("close-"):].rsplit("-", 1)[0]
        letter = fam.rsplit("-", 1)[1]
        model = MODEL_HAIKU if letter == "A" else MODEL_SONNET
        return fam, "mining", miner, model, f"closer pass {letter}"
    if fam in KNOWN:
        kind, miner, model, src = KNOWN[fam]
        return fam, kind, miner, model, src
    return fam, "", "", "not recorded", ""


def kind_from_tools(tools: Counter, fam: str) -> str:
    """Fallback kind from the tool calls seen in a transcript."""
    if any(t.startswith("mine_") for t in tools):
        return "mining:unknown"
    if any(t.startswith("screen_") for t in tools):
        return "full-text" if "ft" in fam.lower() else "screening"
    return "other"


def read_run(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="replace")
    fins = FIN_RE.findall(text)
    tools = Counter(TOOL_RE.findall(text))
    verdicts = len(VERDICT_RE.findall(text))
    written = 0
    for group in WRITTEN_RE.findall(text):
        written += group.count("ext_")
    return {
        "finished": fins[-1] if fins else None,
        "tools": tools,
        "items": verdicts,
        "rows": written,
        "rejected": len(REJECTED_RE.findall(text)),
        "no_batch": text.count(NOBATCH),
    }


def build(folder: Path) -> tuple[dict[str, Family], int]:
    fams: dict[str, Family] = {}
    files = sorted(folder.glob("*.live"))
    for path in files:
        fam_name, kind, miner, model, src = family_of(path.stem)
        run = read_run(path)
        tools: Counter = run["tools"]  # type: ignore[assignment]
        fam = fams.setdefault(fam_name, Family(fam_name))
        fam.files += 1
        if fam.kind == "other" or not fam.kind:
            fam.kind = kind or kind_from_tools(tools, fam_name)
            fam.miner = miner
            fam.model = model
            fam.model_source = src
        if run["finished"] is None:
            fam.unfinished += 1
        else:
            _, cost, turns = run["finished"]  # type: ignore[misc]
            subtype = run["finished"][0]  # type: ignore[index]
            fam.finished += 1
            fam.cost += float(cost)
            fam.turns.append(int(turns))
            fam.subtypes[subtype] += 1
        if fam.kind.startswith("mining"):
            units = int(run["rows"])  # type: ignore[arg-type]
            fam.mine_calls += tools.get("mine_record", 0)
        else:
            units = int(run["items"])  # type: ignore[arg-type]
        fam.units += units
        fam.rejected_results += int(run["rejected"])  # type: ignore[arg-type]
        if int(run["no_batch"]):  # type: ignore[arg-type]
            fam.no_batch_runs += 1
        if units == 0:
            fam.zero_unit_runs += 1
    return fams, len(files)


def kind_group(kind: str) -> str:
    if kind.startswith("mining"):
        return "mining"
    return kind or "other"


def fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def fmt_unit(cost: float, units: int) -> str:
    return f"${cost / units:,.4f}" if units else "n/a"


def render(fams: dict[str, Family], nfiles: int, folder: Path) -> str:
    rows = sorted(fams.values(), key=lambda f: (-f.cost, f.name))
    total_cost = sum(f.cost for f in rows)
    total_runs = sum(f.files for f in rows)
    total_fin = sum(f.finished for f in rows)
    total_unfin = sum(f.unfinished for f in rows)
    all_turns = [t for f in rows for t in f.turns]

    out: list[str] = []
    out.append("# Pilot run-cost baseline (2026-11-11)\n")
    out.append("## Method\n")
    out.append(
        f"- Read: the {nfiles} `*.live` transcripts in the pilot screeners folder, one per "
        "headless `claude -p` run. `live.py` writes one line per tool call (`> <tool>`), one "
        "line per screened item, and a `== finished` line with the CLI's `total_cost_usd` and "
        "turn count. The `.log` files (the agent's final message) and the database were not "
        "used for any number."
    )
    out.append(
        "- Cost figure: the price the CLI reports for each run (`total_cost_usd`), an "
        "API-equivalent price at list rates. It is not a subscription charge and not a bill. "
        "Runs without a `finished` line (killed or still running at the time of reading) have "
        "no cost and are counted separately."
    )
    out.append(
        "- Family: the file-name prefix before the timestamp. Kind, miner and model come from "
        "the shell drivers (`*.sh`) and their prompt files; a family not in that mapping is "
        "classified from the tool calls it made, and its model is shown as not recorded."
    )
    out.append(
        "- Units: screening and full-text runs count the verdict items they submitted "
        "(`screen_record` input). Mining runs count the rows the platform accepted (`ext_` ids in "
        "`mine_record` results). Works closed without a row are not counted, so mining cost per "
        "unit is an upper bound. Rejected `*_record` results are reported separately."
    )
    out.append(
        "- Zero-unit runs: runs that served no unit (no `screen_record` item, or no accepted "
        "row). Mean turns and mean cost are over finished runs only.\n"
    )

    out.append("## Totals\n")
    out.append(f"- Run files: {total_runs}; finished with a cost: {total_fin}; unfinished: {total_unfin}")
    out.append(f"- Total reported cost: {fmt_money(total_cost)}")
    if all_turns:
        out.append(f"- Mean cost per finished run: {fmt_money(total_cost / total_fin) if total_fin else 'n/a'}; "
                   f"mean turns: {statistics.mean(all_turns):.1f}")
    out.append("")

    out.append("## By kind\n")
    out.append("| Kind | Runs | Cost | Share of cost | Units | Cost per unit |")
    out.append("|---|---:|---:|---:|---:|---:|")
    by_kind: dict[str, list[Family]] = defaultdict(list)
    for f in rows:
        by_kind[kind_group(f.kind)].append(f)
    for kind in sorted(by_kind, key=lambda k: -sum(f.cost for f in by_kind[k])):
        fs = by_kind[kind]
        c = sum(f.cost for f in fs)
        u = sum(f.units for f in fs)
        share = f"{100 * c / total_cost:.1f}%" if total_cost else "n/a"
        out.append(f"| {kind} | {sum(f.files for f in fs)} | {fmt_money(c)} | {share} | {u} | {fmt_unit(c, u)} |")
    out.append("")

    out.append("## By family\n")
    out.append(
        "| Family | Kind | Model | Runs | Finished | Cost | Cost per run | Mean turns | Units | Cost per unit | Zero-unit runs | Rejected results |"
    )
    out.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for f in rows:
        kind = f.kind
        if f.miner and f.kind.startswith("mining"):
            kind = f"mining:{f.miner}"
        mean_cost = fmt_money(f.cost / f.finished) if f.finished else "n/a"
        mean_turns = f"{statistics.mean(f.turns):.1f}" if f.turns else "n/a"
        units = str(f.units)
        out.append(
            f"| `{f.name}` | {kind or 'other'} | {f.model} | {f.files} | {f.finished} | {fmt_money(f.cost)} | "
            f"{mean_cost} | {mean_turns} | {units} | {fmt_unit(f.cost, f.units)} | {f.zero_unit_runs} | {f.rejected_results} |"
        )
    out.append("")

    out.append("## Top five families by cost\n")
    for i, f in enumerate(rows[:5], 1):
        out.append(
            f"{i}. `{f.name}` ({kind_group(f.kind)}, {f.model}): {fmt_money(f.cost)} over {f.finished} finished runs"
            + (f"; {f.units} units, {fmt_unit(f.cost, f.units)} per unit" if f.units else "; no unit count")
        )
    out.append("")

    out.append("## Observations (facts from the numbers above)\n")
    obs: list[str] = []
    if rows:
        top = rows[0]
        obs.append(f"- The most expensive family is `{top.name}` at {fmt_money(top.cost)}, "
                   f"{100 * top.cost / total_cost:.1f}% of the total." if total_cost else "- No cost recorded.")
    for kind in sorted(by_kind):
        fs = by_kind[kind]
        u = sum(f.units for f in fs)
        c = sum(f.cost for f in fs)
        if u:
            obs.append(f"- {kind}: {fmt_money(c)} for {u} units, {fmt_unit(c, u)} per unit.")
    per_unit = [(f.cost / f.units, f) for f in rows if f.units and f.finished and f.units >= 10]
    if per_unit:
        lo = min(per_unit, key=lambda x: x[0])
        hi = max(per_unit, key=lambda x: x[0])
        obs.append(f"- Among families with at least 10 units, cost per unit runs from "
                   f"{fmt_unit(lo[1].cost, lo[1].units)} (`{lo[1].name}`) to "
                   f"{fmt_unit(hi[1].cost, hi[1].units)} (`{hi[1].name}`).")
    zero = sum(f.zero_unit_runs for f in rows)
    obs.append(f"- {zero} of {total_runs} run files served no unit.")
    nb = sum(f.no_batch_runs for f in rows)
    obs.append(f"- {nb} run files record at least one `(no batch served)` result.")
    if total_unfin:
        obs.append(f"- {total_unfin} run files have no finished line and contribute no cost.")
    subtypes = Counter()
    for f in rows:
        subtypes.update(f.subtypes)
    if subtypes:
        obs.append("- Finished subtypes: " + ", ".join(f"{k} {v}" for k, v in subtypes.most_common()) + ".")
    out.extend(obs)
    out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: pilot_baseline.py <screeners-folder>", file=sys.stderr)
        return 2
    folder = Path(argv[1]).expanduser().resolve()
    if not folder.is_dir():
        print(f"not a folder: {folder}", file=sys.stderr)
        return 2
    fams, nfiles = build(folder)
    report = render(fams, nfiles, folder)
    out_path = Path(__file__).resolve().parent / REPORT_NAME
    out_path.write_text(report, encoding="utf-8")
    print(f"wrote {out_path} ({nfiles} run files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

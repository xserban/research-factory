"""The results product: what the miners found across the corpus (plan site-hub, step 3).

Distributions of every enum field of the classification, mapping and summary miners, the stages the
systems cover and how, the result rows by stage and approach, the corpus by month, the review flow
and the agent events per model. Every number is computed from the recorded rows (pass A) and the
PRISMA computation; nothing is typed in. Pass A is one model's reading: the agreement product shows
how stable it is.
"""

from __future__ import annotations

import collections
import json
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import text

from factory.mining.spec import EnumKind
from factory.services import mining as mining_service
from factory.services import site_progress
from factory.services.context import Project
from factory.services.prisma import prisma_flow
from factory.services.protocol import current_protocol
from factory.services.site_charts import column_chart, funnel
from factory.services.site_corpus import corpus_payload, load_profile
from factory.services.site_widgets import (
    REPORT_CSS,
    bars,
    esc,
    heat_grid,
    link_table,
    note,
    section,
)

ENUM_ROLES = (
    ("cls", "Classification"),
    ("map", "Process, human role, blueprint"),
    ("sum", "Summary"),
)


def _enum_fields(project: Project, miner: str) -> list[tuple[str, tuple[str, ...]]]:
    """The enum fields of a listed miner in spec order, with their allowed values."""
    protocol = current_protocol(project)
    for use in (protocol.spec.miners or ()) if protocol else ():
        if use.name == miner:
            spec = mining_service.registered_miner(project, use.name, use.version)
            if spec is not None:
                return [
                    (f.name, f.kind.values) for f in spec.fields if isinstance(f.kind, EnumKind)
                ]
    return []


def _link_for(role: str, field: str, value: str) -> str | None:
    return explorer_link(role, field, value)


EXPLORER = "../explorer/index.html"


def filter_link(*pairs: tuple[str, str]) -> str:
    """The explorer filtered by dimension key and value pairs (stage, technique, year ...)."""
    return EXPLORER + "#view=list&" + "&".join(f"f={quote(k)}:{quote(v)}" for k, v in pairs)


def explorer_link(role: str, field: str, value: str) -> str:
    """The explorer filtered to the works with this value of this miner field."""
    return f"../explorer/index.html#view=list&f={quote(role + '.' + field)}:{quote(value)}"


def _enum_descriptions(project: Project, miner: str) -> list[tuple[str, str]]:
    """The description of each enum field of a listed miner, from its spec."""
    protocol = current_protocol(project)
    for use in (protocol.spec.miners or ()) if protocol else ():
        if use.name == miner:
            spec = mining_service.registered_miner(project, use.name, use.version)
            if spec is not None:
                return [
                    (f.name, f.description) for f in spec.fields if isinstance(f.kind, EnumKind)
                ]
    return []


def _distributions(project: Project, works: list[dict[str, Any]]) -> str:
    profile = load_profile(project)
    out = ""
    for role, title in ENUM_ROLES:
        miner = profile.roles.get(role, "")
        body = ""
        descriptions = {f: d for f, d in _enum_descriptions(project, miner)}
        for fname, _values in _enum_fields(project, miner):
            counter: collections.Counter[str] = collections.Counter(
                w[role][fname]["v"] for w in works if fname in w[role]
            )
            if counter:
                body += (
                    f"<h3>{esc(fname)} <small>({sum(counter.values())} of {len(works)} works)"
                    f"</small></h3><p class=dim>{esc(descriptions.get(fname, ''))}</p>"
                    f"{bars(counter, link=partial(_link_for, role, fname))}"
                )
        if body:
            out += section(
                f"{title} ({miner}, pass A)",
                note(
                    f"One reading of each paper by {miner} (pass A). Every value rests on a quote "
                    "from the paper, shown in the explorer. Click a value to open the works that "
                    "have it. The share filled is shown beside each field: a paper that does not "
                    "state something gets no value."
                )
                + body,
            )
    return out


def _stages(works: list[dict[str, Any]]) -> str:
    by_stage: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for w in works:
        seen: dict[str, str] = {}
        for s in w["stages"]:
            seen.setdefault(s["stage"], s["mode"])
        for stage, mode in seen.items():
            by_stage[stage][mode] += 1
    if not by_stage:
        return ""
    modes = sorted({m for c in by_stage.values() for m in c})
    rows = sorted(by_stage, key=lambda s: -sum(by_stage[s].values()))
    cell = {(s, m): by_stage[s][m] for s in rows for m in modes}
    per_work = collections.Counter(len({s["stage"] for s in w["stages"]}) for w in works)
    return section(
        "Lifecycle stages covered (works per stage and mode)",
        note(
            "For each research stage, how many papers have a system that covers it, split by mode: "
            "automated (the system does it), human-assisted (a person does it with the system), "
            "mentioned-only (the paper talks about it without the system doing it). A paper counts "
            "once per stage. Darker cells are larger counts."
        )
        + heat_grid(rows, modes, cell, "stage", link=lambda s, m: filter_link(("stage", s)))
        + "<h3>Number of distinct stages per work</h3>"
        + bars(collections.Counter({str(k): v for k, v in sorted(per_work.items())})),
    )


def _technique_by_stage(works: list[dict[str, Any]]) -> str:
    cell: collections.Counter[tuple[str, str]] = collections.Counter()
    for w in works:
        tech = (w["cls"].get("technique_primary") or {}).get("v", "")
        if not tech:
            continue
        for stage in {s["stage"] for s in w["stages"] if s["mode"] != "mentioned-only"}:
            cell[(stage, tech)] += 1
    if not cell:
        return ""
    stages = sorted({s for s, _ in cell})
    techs = sorted(
        {t for _, t in cell}, key=lambda t: -sum(v for (_, x), v in cell.items() if x == t)
    )
    return section(
        "Stages covered (automated or human-assisted) by primary technique",
        note(
            "Which techniques cover which stages: each cell counts papers with that primary "
            "technique whose system covers the stage, automated or with a human. It shows where "
            "techniques cluster and which stage-technique pairs are empty. Mentioned-only stages "
            "are left out."
        )
        + heat_grid(
            stages,
            techs,
            dict(cell),
            "stage",
            link=lambda s, tch: filter_link(("stage", s), ("technique", tch)),
        ),
    )


def _design(works: list[dict[str, Any]]) -> str:
    rows = [r for w in works for r in w["design"]]
    own = [r for r in rows if r.get("system_role") == "own-system"]
    if not rows:
        return ""
    stages = sorted({r["stage"] for r in own if r.get("stage")})
    apps = sorted({r["approach"] for r in own if r.get("approach")})
    grid = collections.Counter(
        (r["stage"], r["approach"]) for r in own if r.get("stage") and r.get("approach")
    )
    body = note(
        f"{len(rows)} result rows over {len({1 for w in works if w['design']})} works (at most 30 "
        f"rows per work are shown here); {len(own)} are the paper's own system."
    ) + heat_grid(stages, apps, dict(grid), "stage", link=lambda s, a: filter_link(("stage", s)))
    for fname in ("system_role", "evidence_grade", "value_kind"):
        counter = collections.Counter(r[fname] for r in rows if r.get(fname))
        if counter:
            body += f"<h3>{esc(fname)}</h3>{bars(counter)}"
    return section(
        "Results by stage and approach (design approach miner, pass A)",
        note(
            "One row per reported result of a paper. The grid counts results of the paper's own "
            "system by lifecycle stage and technique category; the tables below show who the "
            "result is about (system role), how strong the evidence is (evidence grade) and what "
            "kind of value it is. These are readings of the papers, not re-measured results."
        )
        + body,
    )


def _flow(project: Project, out: Path) -> str:
    flow = prisma_flow(project).model_dump()
    ft: dict[str, Any] = flow["full_text"]
    rows: list[list[object]] = [
        ["identified (databases)", sum(flow["identified_databases"].values())],
        ["duplicates removed", flow["duplicates_removed"]],
        ["screened (title/abstract)", flow["screened"]],
        ["excluded (title/abstract)", sum(flow["excluded"].values())],
        ["promoted to full text", ft["sought"] + ft.get("not_sought", 0)],
        ["promoted, not yet sought", ft.get("not_sought")],
        ["full text not retrieved", ft.get("not_retrieved")],
        ["full text assessed", ft.get("assessed")],
        ["full text excluded", sum((ft.get("excluded") or {}).values())],
        ["full text pending", ft.get("pending")],
        ["included in the review", flow.get("included_in_review")],
    ]
    (out / "line.json").write_text(
        json.dumps(
            {
                "identified": sum(flow["identified_databases"].values()),
                "screened": flow["screened"],
                "assessed": ft.get("assessed"),
                "converted": ft.get("eligible"),
            }
        ),
        encoding="utf-8",
    )
    with project.index.connect() as conn:
        dev = conn.execute(
            text("SELECT COUNT(*) FROM events WHERE type = 'protocol.deviation_recorded'")
        ).scalar()
        models = conn.execute(
            text(
                "SELECT model, COUNT(*) FROM events WHERE model IS NOT NULL AND model <> '' "
                "GROUP BY model ORDER BY COUNT(*) DESC"
            )
        ).all()
    targets = {
        "identified (databases)": "../prisma/index.html",
        "duplicates removed": "../prisma/index.html",
        "screened (title/abstract)": "../prisma/index.html",
        "excluded (title/abstract)": "../prisma/index.html",
        "promoted to full text": "../acquisition/index.html",
        "full text not retrieved": "../acquisition/index.html",
        "full text assessed": "../acquisition/index.html",
        "full text excluded": "../prisma/index.html",
        "full text pending": "../acquisition/index.html",
        "included in the review": EXPLORER,
    }
    flow_html = (
        funnel([(str(r[0]), float(str(r[1] or 0)), targets.get(str(r[0]))) for r in rows])
        + link_table(["step", "n"], [(r, targets.get(str(r[0]))) for r in rows])
    ) + note(
        f"{dev} protocol deviations are recorded (see the dashboard's Protocol tab). The review "
        "stops title/abstract screening by a declared rule; works not screened are reported."
    )
    cost = bars(collections.Counter({str(m): int(n) for m, n in models}))
    return section(
        "Review flow (computed)",
        note(
            "How many records passed each step, from the search to the included works. Computed "
            "from the recorded decisions, never typed. 'Not retrieved' are promoted works whose "
            "full text could not be obtained; the Acquisition product lists them."
        )
        + flow_html,
    ) + section(
        "Agent events per model (recorded events, not dollars)",
        note(
            "How many events each model recorded (screening verdicts, rows, labels). A rough "
            "measure of how much work each model did; it is not a cost, which the platform does "
            "not record."
        )
        + cost,
    )


def _timeline(works: list[dict[str, Any]]) -> str:
    months = collections.Counter(w["month"] or "unknown" for w in works)
    ordered = dict(sorted(months.items()))
    chart = column_chart(
        [(m, n, filter_link(("year", m)) if m != "unknown" else None) for m, n in ordered.items()]
    )
    return section(
        "Publication month of the included works",
        note(
            "When the included papers were first published, by month. Click a bar or a row to "
            "open those papers in the explorer."
        )
        + chart
        + bars(
            collections.Counter(ordered),
            link=lambda m: filter_link(("year", m)) if m != "unknown" else None,
        ),
    )


def build_results(project: Project, out: Path) -> None:
    site_progress.report(0, 8, "parts")
    payload = corpus_payload(project)
    works: list[dict[str, Any]] = payload["works"]
    site_progress.report(1, 8, "parts")
    intro = note(
        f"{len(works)} works with at least one miner row. All figures are computed from the "
        "recorded rows (pass A) and are not judgements; see Miner agreement for how stable "
        "pass A is."
    )
    parts: list[str] = []
    makers: tuple[Callable[[], str], ...] = (
        lambda: _flow(project, out),
        lambda: _timeline(works),
        lambda: _distributions(project, works),
        lambda: _stages(works),
        lambda: _technique_by_stage(works),
        lambda: _design(works),
    )
    for n, make in enumerate(makers, start=2):
        parts.append(make())
        site_progress.report(n, 8, "parts")
    body = (
        f"<h1>Results</h1>{intro}"
        + "".join(parts)
        + note(
            "Limits: pass A is one model's reading; quotes are verified verbatim, which shows the "
            "evidence exists, not that the value is right; works not acquired or not in English "
            "are reported in the review flow and deviations."
        )
    )
    from factory.services.site import page

    (out / "index.html").write_text(page("Results", body, REPORT_CSS), encoding="utf-8")

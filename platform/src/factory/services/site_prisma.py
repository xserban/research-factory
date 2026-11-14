# ruff: noqa: E501
"""The PRISMA product: the flow diagram, what each box means, and the criteria behind each exclusion
count (plan site-hub). All numbers are computed from the recorded decisions."""

from __future__ import annotations

from pathlib import Path

from factory.services.context import Project
from factory.services.exports import export_prisma_svg
from factory.services.prisma import prisma_flow
from factory.services.protocol import current_protocol
from factory.services.site_widgets import REPORT_CSS, esc, note, section, table

LEGEND = (
    (
        "Records identified from databases",
        "Records returned by the registered queries on each source, before any clean-up.",
    ),
    (
        "Duplicate records removed",
        "Records recognised as the same work by the platform's deduplication; the merges can be listed and reverted.",
    ),
    (
        "Records screened",
        "Distinct records judged at title and abstract by pass A (a sample also by pass B).",
    ),
    (
        "Records excluded",
        "Records judged not to meet the criteria, counted by the criterion that excluded them.",
    ),
    (
        "Reports sought for retrieval",
        "Records promoted to full text that the full-text stage tried to fetch.",
    ),
    (
        "Reports not retrieved",
        "Promoted works with no obtainable full text, by reason. The Full-text acquisition product lists them.",
    ),
    (
        "Reports assessed for eligibility",
        "Works with a full text that were read against the criteria.",
    ),
    ("Reports excluded", "Works excluded at full text, counted by criterion."),
    (
        "Studies included in the review",
        "Works that passed full-text screening: the corpus the miners read.",
    ),
)


def _with_background(count: int, kept: int) -> str | int:
    """A criterion's exclusion count, noting those kept as background (IDEA-47)."""
    if not count:
        return ""
    return f"{count} (of which kept as background: {kept})" if kept else count


def build_prisma(project: Project, out: Path) -> None:
    from factory.services.site import page

    svg = export_prisma_svg(project)
    (out / "prisma.svg").write_text(svg, encoding="utf-8")
    flow = prisma_flow(project).model_dump()
    protocol = current_protocol(project)
    criteria = list(protocol.spec.criteria) if protocol else []
    ft = flow["full_text"]
    rows = []
    for c in criteria:
        ta = flow["excluded"].get(c.id, 0)
        fx = (ft.get("excluded") or {}).get(c.id, 0)
        kept_ta = flow.get("background", {}).get(c.id, 0)
        kept_ft = (ft.get("background") or {}).get(c.id, 0)
        rows.append(
            [
                c.id,
                c.statement,
                _with_background(ta, kept_ta),
                _with_background(fx, kept_ft),
            ]
        )
    crit = (
        table(
            [
                "criterion",
                "what it excludes",
                "excluded at title/abstract",
                "excluded at full text",
            ],
            rows,
        )
        if rows
        else "<p class=dim>No criteria recorded.</p>"
    )
    body = (
        "<h1>PRISMA 2020 flow</h1>"
        + note(
            "PRISMA is the standard diagram of a systematic review: how many records were found, "
            "removed, screened, excluded (and why), and included. Every number here is computed "
            "from the recorded decisions; none is typed. The review stops title/abstract screening "
            "by a declared rule, and works not screened are reported."
        )
        + f"<p class=dim><a href='prisma.svg'>prisma.svg</a> (download the diagram)</p><div class=panel style='background:#fff;padding:12px'>{svg}</div>"
        + section("What each box means", table(["box", "meaning"], [list(x) for x in LEGEND]))
        + section("Criteria and how many records each excluded", crit)
        + section(
            "Where to go next",
            "<ul><li><b>Included works</b>: open the <a href='../explorer/index.html'>Explorer</a>.</li>"
            "<li><b>Works that could not be retrieved</b>: the <a href='../acquisition/index.html'>Full-text acquisition</a> product, with what to do for each.</li>"
            "<li><b>How the numbers were reached</b>: the dashboard's Search and Screening tabs, and <code>factory --project "
            f"{esc(project.paths.slug)} report methods</code>.</li></ul>",
        )
    )
    (out / "index.html").write_text(page("PRISMA 2020 flow", body, REPORT_CSS), encoding="utf-8")

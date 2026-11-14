"""PRISMA 2020 flow diagram ("new reviews: databases, registers and other sources") as SVG.

A fixed template: two columns, boxes of fixed width whose height grows with their wrapped text,
rows stacked downward, straight arrows between box anchors. Every number is read from
`PrismaFlow` / `FullTextBoxes`; the renderer does no arithmetic on counts (R-05). No CSS, no fonts
beyond `font-family="sans-serif"`; the output is a pure function of the flow.
"""

from dataclasses import dataclass
from xml.sax.saxutils import escape

from factory.services.prisma import PrismaFlow

PRISMA_TEMPLATE_VERSION = 1
BOX_W = 260
LINE_H = 14
CHAR_W = 6.6
WIDE_CHAR_W = 9.0
PAD = 8
GAP = 34
LEFT_X = 20
RIGHT_X = 320
CANVAS_W = RIGHT_X + BOX_W + 20
NOT_RUN = "not run"


def _width(text: str) -> float:
    return sum(CHAR_W if c.isascii() else WIDE_CHAR_W for c in text)


def _wrap(text: str, limit: float = BOX_W - 2 * PAD) -> list[str]:
    """Greedy word wrap by the fixed width table; an over-long word is split by character."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if _width(candidate) <= limit:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = ""
        for char in word:
            if _width(current + char) > limit and current:
                lines.append(current)
                current = ""
            current += char
    if current:
        lines.append(current)
    return lines or [""]


Lines = tuple[list[str], list[str]]
Row = tuple[Lines, Lines | None]


@dataclass(frozen=True)
class _Box:
    x: int
    y: int
    heading: list[str]
    body: list[str]

    @property
    def height(self) -> int:
        return 2 * PAD + LINE_H * (len(self.heading) + len(self.body))

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def anchor(self, side: str) -> tuple[float, float]:
        if side == "top":
            return self.x + BOX_W / 2, self.y
        if side == "bottom":
            return self.x + BOX_W / 2, self.bottom
        if side == "left":
            return self.x, self.y + self.height / 2
        return self.x + BOX_W, self.y + self.height / 2


def _lines(heading: str, items: list[str]) -> tuple[list[str], list[str]]:
    body = [line for item in items for line in _wrap(item)]
    return _wrap(heading), body


def _count(label: str, n: int) -> str:
    return f"{label} (n = {n})"


def _reasons(counts: dict[str, int]) -> list[str]:
    return [_count(name, n) for name, n in counts.items()]


def _background(counts: dict[str, int]) -> list[str]:
    return [f"of which kept as background: {n} ({name})" for name, n in counts.items()]


def _render_box(box: _Box) -> list[str]:
    out = [
        f'<rect x="{box.x}" y="{box.y}" width="{BOX_W}" height="{box.height}" '
        'fill="white" stroke="black"/>'
    ]
    y = box.y + PAD + LINE_H - 3
    for line in box.heading:
        out.append(
            f'<text x="{box.x + PAD}" y="{y}" font-size="12" font-weight="bold">'
            f"{escape(line)}</text>"
        )
        y += LINE_H
    for line in box.body:
        out.append(f'<text x="{box.x + PAD}" y="{y}" font-size="12">{escape(line)}</text>')
        y += LINE_H
    return out


def _arrow(start: tuple[float, float], end: tuple[float, float]) -> str:
    return (
        f'<line x1="{start[0]:g}" y1="{start[1]:g}" x2="{end[0]:g}" y2="{end[1]:g}" '
        'stroke="black" marker-end="url(#arrow)"/>'
    )


def prisma_svg(flow: PrismaFlow) -> str:
    """The flow as an SVG document (ruling 5). Deterministic for equal flows."""
    boxes = flow.full_text
    ran = boxes.stage_run
    banner: str | None = None
    open_pending = flow.pending - flow.not_screened_stop - flow.unscreened_tolerated
    if open_pending:
        banner = f"Provisional: {open_pending} records pending"
    elif boxes.provisional:
        banner = f"Provisional: {boxes.pending} reports pending"
        if boxes.awaiting_classification:
            banner += f", {boxes.awaiting_classification} awaiting classification"

    databases = _lines(
        "Records identified from databases",
        _reasons(flow.identified_databases) or ["none"],
    )
    other = _lines(
        "Records identified from other methods",
        _reasons(flow.identified_other) or ["none"],
    )
    duplicates = _lines(_count("Duplicate records removed", flow.duplicates_removed), [])
    screened = _lines(
        _count("Records screened", flow.screened),
        (
            []
            if flow.stop_rule is None
            else [f"{flow.not_screened_stop} not screened (stopping rule)"]
        )
        + (
            [f"{flow.unscreened_tolerated} unscreened (declared tolerance)"]
            if flow.unscreened_tolerated
            else []
        ),
    )
    excluded = _lines(
        _count("Records excluded", flow.excluded_total),
        _reasons(flow.excluded) + _background(flow.background),
    )
    sought = _lines(_count("Reports sought for retrieval", boxes.sought), [])
    not_retrieved = _lines(
        _count("Reports not retrieved", boxes.not_retrieved),
        _reasons(boxes.not_retrieved_reasons),
    )
    if ran:
        assessed = _lines(
            _count("Reports assessed for eligibility", boxes.assessed),
            [_count("Awaiting classification", boxes.awaiting_classification)]
            if boxes.awaiting_classification
            else [],
        )
        ft_excluded = _lines(
            _count("Reports excluded", boxes.excluded_total),
            _reasons(boxes.excluded) + _background(boxes.background),
        )
        final = _lines(
            _count("Studies included in review", boxes.included),
            [],
        )
    else:
        assessed = _lines("Reports assessed for eligibility", [NOT_RUN])
        ft_excluded = _lines("Reports excluded", [NOT_RUN])
        final = _lines("Studies included in review", [NOT_RUN])

    rows: list[Row] = [
        (databases, other),
        (duplicates, None),
        (screened, excluded),
        (sought, not_retrieved),
        (assessed, ft_excluded),
        (final, None),
    ]

    return render_rows(rows, banner)


def render_rows(rows: list[Row], banner: str | None) -> str:
    """The template: two columns of boxes, one row each, an optional banner above. Shared by the
    cumulative flow and the update flow (`exports/update_flow_svg.py`)."""
    y = 20
    if banner:
        y += 28
    left_boxes: list[_Box] = []
    right_boxes: list[_Box | None] = []
    for left, right in rows:
        lbox = _Box(LEFT_X, y, *left)
        rbox = _Box(RIGHT_X, y, *right) if right else None
        left_boxes.append(lbox)
        right_boxes.append(rbox)
        y = max(lbox.bottom, rbox.bottom if rbox else 0) + GAP
    height = y - GAP + 20

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_W}" height="{height}" '
        f'viewBox="0 0 {CANVAS_W} {height}" font-family="sans-serif">',
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" '
        'orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="black"/></marker></defs>',
    ]
    if banner:
        parts.append(
            f'<text x="{CANVAS_W / 2:g}" y="24" font-size="14" font-weight="bold" '
            f'text-anchor="middle" fill="#b00000">{escape(banner)}</text>'
        )
    arrows: list[str] = []
    for index, lbox in enumerate(left_boxes):
        parts.extend(_render_box(lbox))
        rbox = right_boxes[index]
        if rbox is not None:
            parts.extend(_render_box(rbox))
        if index + 1 < len(left_boxes):
            arrows.append(_arrow(lbox.anchor("bottom"), left_boxes[index + 1].anchor("top")))
        if rbox is not None and index > 0:
            arrows.append(_arrow(lbox.anchor("right"), rbox.anchor("left")))
    first_right = right_boxes[0]
    if first_right is not None:
        arrows.append(_arrow(first_right.anchor("bottom"), left_boxes[1].anchor("right")))
    parts.extend(arrows)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"

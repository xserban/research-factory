# ruff: noqa: E501
"""Small inline-SVG charts for the site pages (no library, no script): each mark can be a link, so a
chart is also a way into the data. Colours come from the site theme variables.

Every function returns an HTML string; text is escaped. Marks with a `href` are wrapped in `<a>`, so
the chart is clickable and keyboard-focusable.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

CHART_CSS = (
    ".ch{width:100%;max-width:980px;height:auto;display:block;margin:6px 0 14px;background:rgba(8,9,16,.55);"
    "border:1px solid var(--mut)}.ch text{fill:var(--dim);font:10px ui-monospace,monospace}"
    ".ch .v{fill:var(--light)}.ch .grid{stroke:var(--mut);stroke-width:1}"
    ".ch .mk{fill:var(--ac)}.ch a:hover .mk,.ch a:focus .mk{fill:#fff}"
    ".ch .warn{stroke:var(--amber);stroke-dasharray:3 3;fill:none}.ch .lo{fill:var(--amber)}"
    ".c2{fill:var(--cyan)}.c3{fill:var(--blue)}.ch .bad{fill:var(--red)}.ch .lbl{fill:var(--fg)}.ch a:hover text{fill:var(--ac)}"
)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _wrap(href: str | None, inner: str, title: str = "") -> str:
    t = f"<title>{_e(title)}</title>" if title else ""
    if href:
        return f"<a href='{_e(href)}'>{t}{inner}</a>"
    return f"{t}{inner}" if title else inner


def column_chart(
    items: Sequence[tuple[str, float, str | None]], height: int = 150, label_every: int = 1
) -> str:
    """Vertical bars, one per item: (label, value, href). Values are printed above the bars."""
    if not items:
        return ""
    n = len(items)
    bw, gap, pad_l, pad_b, pad_t = 22, 6, 30, 26, 14
    width = pad_l + n * (bw + gap) + 6
    top = max((v for _, v, _ in items), default=1) or 1
    plot = height - pad_b - pad_t
    parts = [
        f"<line class=grid x1={pad_l} y1={pad_t + plot} x2={width - 4} y2={pad_t + plot}></line>"
    ]
    for k in (0.5, 1.0):
        y = pad_t + plot - plot * k
        parts.append(
            f"<line class=grid x1={pad_l} y1={y:.1f} x2={width - 4} y2={y:.1f} opacity=.4></line>"
        )
        parts.append(f"<text x=2 y={y + 3:.1f}>{round(top * k)}</text>")
    for i, (label, value, href) in enumerate(items):
        h = plot * value / top
        x = pad_l + i * (bw + gap)
        y = pad_t + plot - h
        bar = (
            f"<rect class=mk x={x} y={y:.1f} width={bw} height={max(h, 1):.1f}></rect>"
            f"<text class=v x={x + bw / 2:.1f} y={max(y - 3, 9):.1f} text-anchor=middle>{round(value)}</text>"
        )
        parts.append(_wrap(href, bar, f"{label}: {round(value)}"))
        if i % label_every == 0:
            parts.append(
                f"<text x={x + bw / 2:.1f} y={height - 8} text-anchor=middle>{_e(label[-5:])}</text>"
            )
    return f"<svg class=ch viewBox='0 0 {width} {height}' role=img>{''.join(parts)}</svg>"


def funnel(steps: Sequence[tuple[str, float, str | None]]) -> str:
    """Horizontal bars scaled to the first step: (label, value, href), each a row."""
    if not steps:
        return ""
    row_h, pad_l, bar_w = 26, 190, 520
    top = max((v for _, v, _ in steps), default=1) or 1
    height = row_h * len(steps) + 8
    parts: list[str] = []
    for i, (label, value, href) in enumerate(steps):
        y = 4 + i * row_h
        w = max(bar_w * value / top, 2)
        mark = (
            f"<text class=lbl x=6 y={y + 15}>{_e(label)}</text>"
            f"<rect class=mk x={pad_l} y={y + 3} width={w:.1f} height={row_h - 8}></rect>"
            f"<text class=v x={pad_l + w + 6:.1f} y={y + 15}>{round(value):,}</text>"
        )
        parts.append(_wrap(href, mark, f"{label}: {round(value):,}"))
    return (
        f"<svg class=ch viewBox='0 0 {pad_l + bar_w + 90} {height}' role=img>{''.join(parts)}</svg>"
    )


def hbars(
    items: Sequence[tuple[str, float, str | None]], total: float = 1.0, rate: bool = True
) -> str:
    """Rows of (label, value, href) with a bar scaled to `total`. With `rate`, a bar is mint at 0.8
    or more, amber at 0.5 or more and red below, and the value shows to three places."""
    if not items:
        return ""
    row_h, pad_l, bar_w = 22, 220, 340
    height = row_h * len(items) + 6
    parts: list[str] = []
    for i, (label, value, href) in enumerate(items):
        y = 3 + i * row_h
        w = max(bar_w * min(value / total, 1.0), 1.5)
        cls = "mk" if not rate or value >= 0.8 else "lo" if value >= 0.5 else "bad"
        text = f"{value:.3f}" if rate else f"{round(value):,}"
        mark = (
            f"<text class=lbl x=6 y={y + 14}>{_e(label[:34])}</text>"
            f"<rect class='{cls} mk' x={pad_l} y={y + 3} width={w:.1f} height={row_h - 8}></rect>"
            f"<text class=v x={pad_l + w + 6:.1f} y={y + 14}>{text}</text>"
        )
        parts.append(_wrap(href, mark, f"{label}: {text}"))
    return (
        f"<svg class=ch viewBox='0 0 {pad_l + bar_w + 70} {height}' role=img>{''.join(parts)}</svg>"
    )


def scatter(
    points: Sequence[tuple[float, float, str, str | None, str]],
    xlabel: str,
    ylabel: str,
    threshold: float | None = 0.8,
) -> str:
    """Points of (x, y, color class, href, title) in the unit square, with a dashed threshold box."""
    w, h, pl, pb, pt, pr = 900, 480, 46, 40, 26, 14
    pw, ph = w - pl - pr, h - pb - pt
    parts: list[str] = []
    for k in (0, 0.2, 0.4, 0.6, 0.8, 1.0):
        x = pl + pw * k
        y = pt + ph - ph * k
        parts.append(
            f"<line class=grid x1={x:.1f} y1={pt} x2={x:.1f} y2={pt + ph} opacity=.5></line>"
        )
        parts.append(
            f"<line class=grid x1={pl} y1={y:.1f} x2={pl + pw} y2={y:.1f} opacity=.5></line>"
        )
        parts.append(f"<text x={x:.1f} y={h - 18} text-anchor=middle>{k:.1f}</text>")
        parts.append(f"<text x={pl - 6} y={y + 3:.1f} text-anchor=end>{k:.1f}</text>")
    if threshold is not None:
        tx, ty = pl + pw * threshold, pt + ph - ph * threshold
        parts.append(
            f"<rect class=warn x={pl} y={ty:.1f} width={tx - pl:.1f} height={pt + ph - ty:.1f}></rect>"
        )
    for x, y, cls, href, title in points:
        cx, cy = pl + pw * min(max(x, 0), 1), pt + ph - ph * min(max(y, 0), 1)
        mark = f"<rect class='{cls}' x={cx - 3:.1f} y={cy - 3:.1f} width=6 height=6></rect>"
        parts.append(_wrap(href, mark, title))
    parts.append(f"<text x={pl + pw / 2:.1f} y={h - 4} text-anchor=middle>{_e(xlabel)}</text>")
    parts.append(f"<text x={pl} y=14>{_e(ylabel)} (up)</text>")
    return f"<svg class=ch viewBox='0 0 {w} {h}' role=img>{''.join(parts)}</svg>"


def activity(days: Sequence[tuple[str, int]], height: int = 90) -> str:
    """A strip of bars, one per day: (date, count), always about 700 units wide so a few days do not
    become a few huge bars."""
    if not days:
        return ""
    n = len(days)
    gap = 4
    bw = min(max(700 / n - gap, 10), 44)
    width = round(n * (bw + gap) + 4)
    top = max((c for _, c in days), default=1) or 1
    parts: list[str] = []
    for i, (day, count) in enumerate(days):
        hh = max((height - 30) * count / top, 1)
        x = 2 + i * (bw + gap)
        mark = (
            f"<rect class=mk x={x:.1f} y={height - 16 - hh:.1f} width={bw:.1f} height={hh:.1f}></rect>"
            f"<text class=v x={x + bw / 2:.1f} y={height - 19 - hh:.1f} text-anchor=middle>{count:,}</text>"
        )
        parts.append(_wrap(None, mark, f"{day}: {count:,} events"))
        if n <= 14 or i % 3 == 0:
            parts.append(
                f"<text x={x + bw / 2:.1f} y={height - 4} text-anchor=middle>{_e(day[5:])}</text>"
            )
    cap = min(980, width * 2.2)
    return (
        f"<svg class=ch style='max-width:{cap:.0f}px' viewBox='0 0 {width} {height}' role=img>"
        f"{''.join(parts)}</svg>"
    )

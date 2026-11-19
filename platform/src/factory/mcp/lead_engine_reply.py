"""Bounds on the reply of the lead engine tools (`lead_candidates`, `lead_queue`).

Invariants: pure functions over the JSON of a service result; nothing is recomputed and no figure
is changed, only whole entries and quotes beyond a stated cap are left out, and the cut is named
in `reply_cap` so the reader never takes a bounded reply for the whole. A candidate is cut as a
unit: its `triggers` are never shortened.
"""

from __future__ import annotations

from math import ceil
from typing import Any

MAX_CANDIDATES = 40
MAX_QUEUE_ITEMS = 30
MAX_QUOTES = 6
MAX_QUOTE_CHARS = 600


def _trim_candidate(candidate: dict[str, Any]) -> int:
    """Keep at most `MAX_QUOTES` quotes of one candidate, each at most `MAX_QUOTE_CHARS`
    characters (marked when cut); return the number of quotes left out."""
    quotes = candidate.get("quotes") or []
    cut = max(0, len(quotes) - MAX_QUOTES)
    kept: list[dict[str, Any]] = []
    for q in quotes[:MAX_QUOTES]:
        text = q.get("quote") or ""
        if len(text) > MAX_QUOTE_CHARS:
            q = {**q, "quote": text[:MAX_QUOTE_CHARS] + " [cut]"}
        kept.append(q)
    candidate["quotes"] = kept
    return cut


def _balanced_cut(
    entries: list[dict[str, Any]], limit: int, source_of: Any
) -> list[dict[str, Any]]:
    """The first `ceil(limit / sources)` entries of each source, in the given order."""
    if len(entries) <= limit:
        return entries
    sources = {source_of(e) for e in entries}
    quota = ceil(limit / max(1, len(sources)))
    seen: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    for e in entries:
        s = source_of(e)
        seen[s] = seen.get(s, 0) + 1
        if seen[s] <= quota and len(kept) < limit:
            kept.append(e)
    return kept


def _cap(total: int, shown: int, quotes_cut: int, unit: str, limit: int) -> dict[str, Any]:
    return {
        "max_" + unit: limit,
        "max_quotes_per_candidate": MAX_QUOTES,
        "max_quote_chars": MAX_QUOTE_CHARS,
        "shown": shown,
        "of": total,
        "quotes_left_out": quotes_cut,
        "truncated": shown < total or quotes_cut > 0,
        "note": (
            f"the reply shows at most {limit} {unit} and {MAX_QUOTES} quotes per candidate; "
            "narrow with sources, layer, top or per_source to see others"
        ),
    }


def bound_candidates(data: dict[str, Any]) -> dict[str, Any]:
    all_ = list(data.get("candidates", []))
    kept = _balanced_cut(all_, MAX_CANDIDATES, lambda c: c["source"])
    cut = sum(_trim_candidate(c) for c in kept)
    data["candidates"] = kept
    data["reply_cap"] = _cap(len(all_), len(kept), cut, "candidates", MAX_CANDIDATES)
    return data


def bound_queue(data: dict[str, Any]) -> dict[str, Any]:
    items = list(data.get("items", []))
    leads = list(data.get("leads", []))
    kept = items[:MAX_QUEUE_ITEMS]
    kept_leads = leads[:MAX_QUEUE_ITEMS]
    cut = 0
    for item in (*kept, *kept_leads):
        if item.get("candidate"):
            cut += _trim_candidate(item["candidate"])
    data["items"], data["leads"] = kept, kept_leads
    cap = _cap(len(items) + len(leads), len(kept) + len(kept_leads), cut, "items", MAX_QUEUE_ITEMS)
    data["reply_cap"] = cap
    return data

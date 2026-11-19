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
    """At most `limit` entries, in the given order, so that no source loses its first entry.

    Each source keeps its first `ceil(limit / sources)` entries; when that is more than `limit`
    the entries that are not their source's first are dropped from the global tail, and when it
    is less (a source has fewer entries than its share) the freed slots go to the entries left
    out, in the global order. With more sources than `limit` the global order decides."""
    if len(entries) <= limit:
        return entries
    sources = {source_of(e) for e in entries}
    quota = ceil(limit / max(1, len(sources)))
    seen: dict[str, int] = {}
    ranks: list[int] = []
    for e in entries:
        s = source_of(e)
        seen[s] = seen.get(s, 0) + 1
        ranks.append(seen[s])
    picked = [i for i, r in enumerate(ranks) if r <= quota]
    while len(picked) > limit:
        drop = next((k for k in range(len(picked) - 1, -1, -1) if ranks[picked[k]] > 1), -1)
        del picked[drop]
    if len(picked) < limit:
        chosen = set(picked)
        for i in range(len(entries)):
            if len(chosen) >= limit:
                break
            chosen.add(i)
        picked = sorted(chosen)
    return [entries[i] for i in picked]


def _trimmed(all_: list[dict[str, Any]], kept: list[dict[str, Any]], source_of: Any) -> list[str]:
    """The sources with at least one entry left out, sorted."""
    shown: dict[str, int] = {}
    for e in kept:
        shown[source_of(e)] = shown.get(source_of(e), 0) + 1
    total: dict[str, int] = {}
    for e in all_:
        total[source_of(e)] = total.get(source_of(e), 0) + 1
    return sorted(s for s in total if shown.get(s, 0) < total[s])


def _cap(
    total: int, shown: int, quotes_cut: int, unit: str, limit: int, trimmed: list[str]
) -> dict[str, Any]:
    return {
        "max_" + unit: limit,
        "max_quotes_per_candidate": MAX_QUOTES,
        "max_quote_chars": MAX_QUOTE_CHARS,
        "shown": shown,
        "of": total,
        "quotes_left_out": quotes_cut,
        "truncated": shown < total or quotes_cut > 0,
        "sources_trimmed": trimmed,
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
    trimmed = _trimmed(all_, kept, lambda c: c["source"])
    data["reply_cap"] = _cap(len(all_), len(kept), cut, "candidates", MAX_CANDIDATES, trimmed)
    return data


def bound_queue(data: dict[str, Any]) -> dict[str, Any]:
    items = list(data.get("items", []))
    leads = list(data.get("leads", []))
    kept = _balanced_cut(items, MAX_QUEUE_ITEMS, lambda i: i["source"])
    kept_leads = leads[:MAX_QUEUE_ITEMS]
    cut = 0
    for item in (*kept, *kept_leads):
        if item.get("candidate"):
            cut += _trim_candidate(item["candidate"])
    data["items"], data["leads"] = kept, kept_leads
    trimmed = _trimmed(items, kept, lambda i: i["source"])
    if len(kept_leads) < len(leads):
        trimmed = sorted({*trimmed, "lead"})
    cap = _cap(
        len(items) + len(leads),
        len(kept) + len(kept_leads),
        cut,
        "items",
        MAX_QUEUE_ITEMS,
        trimmed,
    )
    data["reply_cap"] = cap
    return data

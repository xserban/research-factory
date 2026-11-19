"""Payload of the hub Contradictions page: pairs of claims that conflict, grouped by topic (night
feature N10; ruling 8: the agent proposes, the researcher decides).

Invariants:
- Read-only: nothing is written, no model is called. Every count is computed from the pairs.
- A pair is one `contradictions` row. Its state is the one `finders.list_contradictions` gives,
  named for the researcher: `proposed` (inferred, undecided), `accepted` (confirmed by a human),
  `rejected` (by a human) or `stale` (a ref is no longer live, not rejected).
- A side shows the work title, the stored quote, its anchor and the full paragraph of that anchor
  read from the conversion the quote was verified against (stored with the proposal). An older
  event without one reads the work's default conversion and keeps the paragraph only when it
  still holds the quote. A side with no anchor or an unreadable conversion has an empty
  paragraph, never a guessed one. `mark` is the quote's span in the shown (normalised) text,
  computed as `quote_in_element` matches, or None.
- The topic of a pair is the `about` value of its two rows as stored with the proposal (else as
  served now): the shared value, both values joined when they differ, else `NO_TOPIC`. A stale
  pair keeps its stored topic and shows no served labels, which belong to another row.
- `seed` carries the fields that start a spar from the pair (hypothesis text and selection); the
  button that uses them belongs to the chat page. `decide` holds the CLI commands: the hub has no
  write route for a decision, and a decision is the researcher's act.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from factory.document.quotes import quote_span
from factory.model.findings import parse_row_ref, row_ref
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.document_read import default_conversion
from factory.services.finders import ServedRows, list_contradictions
from factory.services.search import get_work

if TYPE_CHECKING:  # hub_build imports this module to register its builder
    from factory.services.hub_build import HubContext

__all__ = ["NO_TOPIC", "build", "contradictions_payload", "row_ref"]

NO_TOPIC = "no topic recorded"
STATE_NAME = {
    "inferred": "proposed",
    "confirmed": "accepted",
    "rejected": "rejected",
    "stale": "stale",
}
STATES = ("proposed", "accepted", "rejected", "stale")
METHODS: dict[str, str] = {
    "pairs": (
        "An agent proposes a pair of claims from different papers, each with its exact quote, "
        "and the platform checks that the quote is in its paragraph. The researcher decides. "
        "Nothing on this page is a verdict until then."
    ),
    "topic": (
        "The topic is the about value of the two claims; when they differ both are shown, and "
        "when neither is recorded the pair sits under its own heading."
    ),
}
_PAGE = 10_000


def _labels(served: ServedRows, work: str, row_key: str) -> dict[str, str]:
    """The plain `about`, `claim_type` and `direction` of one served m-claims row."""
    row = next((r for r in served.rows(work) if r.row_key == row_key), None)
    if row is None:
        return {}
    return {
        name: " ".join(str(row.fields[name][0]).split())
        for name in ("about", "claim_type", "direction")
        if name in row.fields
    }


def _paragraph(
    project: Project,
    work: str,
    anchor: str | None,
    quote: str,
    conversion_id: str | None,
    cache: dict[str, Any],
) -> tuple[str, list[int] | None]:
    """The anchor's paragraph (normalised plain text) and the quote's span in it. Read from the
    pinned conversion; with none (an older event) from the default one, and then only when the
    paragraph still holds the quote."""
    if not anchor:
        return "", None
    pinned = conversion_id is not None
    if conversion_id is None:
        found = default_conversion(project, work)
        conversion_id = None if found is None else found.conversion_id
    if conversion_id is None:
        return "", None
    if conversion_id not in cache:
        try:
            cache[conversion_id] = conversion_manifest(project, conversion_id)
        except Exception:  # a damaged stored conversion reads as no paragraph
            cache[conversion_id] = None
    manifest = cache[conversion_id]
    element = None if manifest is None else manifest.get(anchor)
    if element is None:
        return "", None
    shown, span = quote_span(str(element.text), quote)
    if span is None and not pinned:
        return "", None
    return shown, None if span is None else list(span)


def contradictions_payload(project: Project) -> dict[str, Any]:
    """The Contradictions page data (see the module invariants)."""
    served = ServedRows(project)
    views = list_contradictions(project, states=tuple(STATE_NAME), limit=_PAGE, served=served)
    project.index.sync()
    with project.index.connect() as conn:
        extra = {
            str(r.contradiction_id): r
            for r in conn.execute(
                text(
                    "SELECT contradiction_id, quote_a, quote_b, anchor_a, anchor_b, note, "
                    "conversion_a, conversion_b, about_a, about_b "
                    "FROM contradictions"
                )
            ).all()
        }
    manifests: dict[str, Any] = {}
    topics: dict[str, list[dict[str, Any]]] = defaultdict(list)
    counts: Counter[str] = Counter()
    for v in views:
        e = extra[v.contradiction_id]
        sides: list[dict[str, Any]] = []
        abouts: list[str] = []
        for ref, work, quote, anchor, conversion, about in (
            (v.ref_a, v.work_a, e.quote_a, e.anchor_a, e.conversion_a, e.about_a),
            (v.ref_b, v.work_b, e.quote_b, e.anchor_b, e.conversion_b, e.about_b),
        ):
            parsed = parse_row_ref(ref)
            row = {} if parsed is None or v.state == "stale" else _labels(served, work, parsed[1])
            if about or row.get("about"):
                abouts.append(about or row["about"])
            record = get_work(project, work)
            shown, mark = _paragraph(project, work, anchor, str(quote or ""), conversion, manifests)
            sides.append(
                {
                    "ref": ref,
                    "work_id": work,
                    "title": "" if record is None else str(record.title),
                    "row_key": None if parsed is None else parsed[1],
                    "claim": str(quote or ""),
                    "claim_type": row.get("claim_type", ""),
                    "direction": row.get("direction", ""),
                    "about": about or row.get("about", ""),
                    "quote": str(quote or ""),
                    "anchor": anchor,
                    "paragraph": shown,
                    "mark": mark,
                }
            )
        a, b = sides
        topic = (
            NO_TOPIC
            if not abouts
            else abouts[0]
            if len(set(abouts)) == 1
            else " / ".join(sorted(set(abouts)))
        )
        state = STATE_NAME[v.state]
        counts[state] += 1
        topics[topic].append(
            {
                "id": v.contradiction_id,
                "state": state,
                "note": str(e.note or ""),
                "a": a,
                "b": b,
                "seed": {
                    "hypothesis": a["claim"],
                    "selection": {
                        "layers": ["core"],
                        "include": sorted([a["work_id"], b["work_id"]]),
                        "exclude": [],
                    },
                },
                "decide": {
                    "confirm": (
                        f"factory contradictions confirm {v.contradiction_id} --rationale '...'"
                    ),
                    "reject": (
                        f"factory contradictions reject {v.contradiction_id} --rationale '...'"
                    ),
                },
            }
        )
    ordered = sorted(topics.items(), key=lambda kv: (kv[0] == NO_TOPIC, -len(kv[1]), kv[0]))
    return {
        "ready": True,
        "methods": dict(METHODS),
        "counts": {**{s: counts[s] for s in STATES}, "all": sum(counts.values())},
        "topics": [
            {
                "topic": name,
                "count": len(pairs),
                "pairs": sorted(pairs, key=lambda p: str(p["id"])),
            }
            for name, pairs in ordered
        ],
    }


def build(ctx: HubContext) -> dict[str, Any]:
    """The payload of the `contradictions` page."""
    return contradictions_payload(ctx.project)

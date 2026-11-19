"""Payload of the hub Contradictions page: pairs of claims that conflict, grouped by topic (night
feature N10; ruling 8: the agent proposes, the researcher decides).

Invariants:
- Read-only: nothing is written, no model is called. Every count is computed from the pairs.
- A pair is one `contradictions` row. Its state is the one `finders.list_contradictions` gives,
  named for the researcher: `proposed` (inferred, undecided), `accepted` (confirmed by a human),
  `rejected` (by a human) or `stale` (a ref is no longer live, not rejected).
- A side shows the work title, the stored quote, its anchor and the full paragraph of that anchor
  read from the work's default conversion. A side with no anchor (an older proposal of a claim
  or item) or an unreadable conversion has an empty paragraph, never a guessed one.
- The topic of a pair is the `about` value of its linked m-claims rows: the shared value, both
  values joined when they differ, else `NO_TOPIC`.
- `seed` carries the fields that start a spar from the pair (hypothesis text and selection); the
  button that uses them belongs to the chat page. `decide` holds the CLI commands: the hub has no
  write route for a decision, and a decision is the researcher's act.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from factory.model.findings import parse_row_ref, row_ref
from factory.services.context import Project
from factory.services.conversions import conversion_manifest
from factory.services.document_read import default_conversion
from factory.services.finders import CLAIMS_MINER, list_contradictions
from factory.services.paper_profile import listed_miner_versions, load_miner_work_rows
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


def _rows(project: Project, works: set[str]) -> dict[str, dict[str, dict[str, str]]]:
    """Per work, per row key, the plain `about`, `claim_type` and `direction` of its m-claims
    rows as served now."""
    version = dict(listed_miner_versions(project)).get(CLAIMS_MINER)
    if version is None or not works:
        return {}
    rows, _ = load_miner_work_rows(project, CLAIMS_MINER, version, sorted(works))
    out: dict[str, dict[str, dict[str, str]]] = {}
    for work, listed in rows.items():
        out[work] = {
            r.row_key: {
                name: " ".join(str(r.fields[name][0]).split())
                for name in ("about", "claim_type", "direction")
                if name in r.fields
            }
            for r in listed
        }
    return out


def _paragraph(project: Project, work: str, anchor: str | None, cache: dict[str, Any]) -> str:
    if not anchor:
        return ""
    if work not in cache:
        found = default_conversion(project, work)
        try:
            cache[work] = (
                None if found is None else conversion_manifest(project, found.conversion_id)
            )
        except Exception:  # a damaged stored conversion reads as no paragraph
            cache[work] = None
    manifest = cache[work]
    element = None if manifest is None else manifest.get(anchor)
    return "" if element is None else str(element.text)


def contradictions_payload(project: Project) -> dict[str, Any]:
    """The Contradictions page data (see the module invariants)."""
    views = list_contradictions(project, states=tuple(STATE_NAME), limit=_PAGE)
    project.index.sync()
    with project.index.connect() as conn:
        extra = {
            str(r.contradiction_id): r
            for r in conn.execute(
                text(
                    "SELECT contradiction_id, quote_a, quote_b, anchor_a, anchor_b, note "
                    "FROM contradictions"
                )
            ).all()
        }
    works = {w for v in views for w in (v.work_a, v.work_b)}
    served = _rows(project, works)
    manifests: dict[str, Any] = {}
    topics: dict[str, list[dict[str, Any]]] = defaultdict(list)
    counts: Counter[str] = Counter()
    for v in views:
        e = extra[v.contradiction_id]
        sides: list[dict[str, Any]] = []
        abouts: list[str] = []
        for ref, work, quote, anchor in (
            (v.ref_a, v.work_a, e.quote_a, e.anchor_a),
            (v.ref_b, v.work_b, e.quote_b, e.anchor_b),
        ):
            parsed = parse_row_ref(ref)
            row = served.get(work, {}).get(parsed[1], {}) if parsed else {}
            if row.get("about"):
                abouts.append(row["about"])
            record = get_work(project, work)
            sides.append(
                {
                    "ref": ref,
                    "work_id": work,
                    "title": "" if record is None else str(record.title),
                    "row_key": None if parsed is None else parsed[1],
                    "claim": str(quote or ""),
                    "claim_type": row.get("claim_type", ""),
                    "direction": row.get("direction", ""),
                    "about": row.get("about", ""),
                    "quote": str(quote or ""),
                    "anchor": anchor,
                    "paragraph": _paragraph(project, work, anchor, manifests),
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

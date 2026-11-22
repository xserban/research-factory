"""Capture hints, the origin tag of a work and m-layer's agreement with the hints (IDEA-81).

Invariants:
- The origin tag is computed from events (the inbox item that resolved to the work, its channel,
  and whether a feed send created it), never typed. A work with several items takes the earliest.
- A hint is the researcher's label with its actor session and time, not a miner row. It is stale
  when the layer scheme (or the taxonomy) it names is no longer the latest recorded version;
  staleness is computed on read.
- Screening never reads this module: no screening view, task or report takes a hint or an origin.
- A miner is served hints only when its protocol use sets `hint_context` (default off). A miner
  that was listed with `hint_context` in ANY recorded protocol version is hint-informed: its
  agreement with hints is not reported (it would be scored against the hint it was given).
- Read-only: nothing here writes an event.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from factory.mining.spec import MinerSpec
from factory.model.extraction import MinerScope
from factory.services.context import Project
from factory.services.extraction_agreement import final_rows
from factory.services.mining import registered_miner
from factory.services.protocol import _spec_of, current_protocol, protocol_lineage
from factory.services.reference_layers import current_scheme
from factory.services.work_layers import layer_dimension

__all__ = [
    "CaptureHint",
    "HintAgreement",
    "WorkOrigin",
    "hint_agreement",
    "hint_context_text",
    "hint_informed_miners",
    "hint_staleness",
    "hints_by_work",
    "origin_matches",
    "origins_of",
]

MAX_CONTEXT = 900
"""Most characters of hint context served to a miner."""


@dataclass(frozen=True)
class WorkOrigin:
    """How a work entered the corpus: `kind` is `inbox` or `feed`; `channel` is the capturing
    channel; `item_id` is the inbox item; `actor_kind` who captured it."""

    kind: str
    channel: str
    item_id: str
    actor_kind: str

    @property
    def tag(self) -> str:
        return f"{self.kind}:{self.channel}"


@dataclass(frozen=True)
class CaptureHint:
    """One item's hints as recorded, with the capturing event's actor session and time."""

    item_id: str
    event_id: str
    ts: str
    session: str
    layer: str | None
    scheme_version: int | None
    category: str | None
    taxonomy: str | None
    taxonomy_version: int | None
    miner_notes: str | None


def origin_matches(origin: WorkOrigin | None, wanted: tuple[str, ...]) -> bool:
    """Whether `origin` is one of `wanted` (`inbox`, `feed`, or `kind:channel`). No origin never
    matches a non-empty list."""
    if origin is None:
        return False
    return origin.kind in wanted or origin.tag in wanted


def origins_of(project: Project) -> dict[str, WorkOrigin]:
    """The origin of every work an inbox item resolved to (`new` or `in-corpus`), the earliest
    item winning. Works that never came through the inbox or the feed are absent. Read-only."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT i.item_id, i.channel, i.actor_kind, r.work_id,"
                " EXISTS (SELECT 1 FROM feed_sends s WHERE s.inbox_item_id = i.item_id)"
                " FROM inbox_items i JOIN inbox_resolutions r ON r.item_id = i.item_id"
                " WHERE r.work_id IS NOT NULL ORDER BY i.added_event_id, r.event_id"
            )
        ).all()
    found: dict[str, WorkOrigin] = {}
    for item, channel, actor, work, fed in rows:
        found.setdefault(
            str(work),
            WorkOrigin("feed" if fed else "inbox", str(channel), str(item), str(actor)),
        )
    return found


def hints_by_work(project: Project) -> dict[str, CaptureHint]:
    """The capture hints of every work whose item carried some, keyed by the work the item
    resolved to (the earliest item with hints wins). Read-only."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT h.item_id, h.event_id, h.ts, h.actor_session, h.layer, h.scheme_version,"
                " h.category, h.taxonomy, h.taxonomy_version, h.miner_notes, r.work_id"
                " FROM inbox_hints h JOIN inbox_resolutions r ON r.item_id = h.item_id"
                " WHERE r.work_id IS NOT NULL ORDER BY h.event_id, r.event_id"
            )
        ).all()
    found: dict[str, CaptureHint] = {}
    for r in rows:
        found.setdefault(
            str(r[10]),
            CaptureHint(
                item_id=str(r[0]),
                event_id=str(r[1]),
                ts=str(r[2]),
                session=str(r[3]),
                layer=None if r[4] is None else str(r[4]),
                scheme_version=None if r[5] is None else int(r[5]),
                category=None if r[6] is None else str(r[6]),
                taxonomy=None if r[7] is None else str(r[7]),
                taxonomy_version=None if r[8] is None else int(r[8]),
                miner_notes=None if r[9] is None else str(r[9]),
            ),
        )
    return found


def _latest_taxonomy_version(project: Project, name: str) -> int | None:
    with project.index.connect() as conn:
        found = conn.execute(
            text("SELECT MAX(version) FROM taxonomies WHERE name = :n"), {"n": name}
        ).scalar()
    return None if found is None else int(found)


def hint_staleness(project: Project, hint: CaptureHint) -> tuple[bool, bool]:
    """`(layer_stale, category_stale)`: the layer hint names a scheme version that is no longer
    the latest recorded, the category hint a taxonomy version that is no longer the latest. A
    hint that sets neither part is never stale in it. Read-only."""
    project.index.sync()
    layer_stale = False
    if hint.layer is not None:
        scheme = current_scheme(project)
        layer_stale = scheme is None or scheme.version != hint.scheme_version
    category_stale = False
    if hint.category is not None and hint.taxonomy is not None:
        category_stale = _latest_taxonomy_version(project, hint.taxonomy) != hint.taxonomy_version
    return layer_stale, category_stale


def hint_informed_miners(project: Project) -> frozenset[str]:
    """The miners listed with `hint_context` in any recorded protocol version (the current one
    included): they were, or may have been, given the hints. Read-only."""
    informed: set[str] = set()
    for protocol_id in protocol_lineage(project):
        spec = _spec_of(project, protocol_id)
        for use in () if spec is None else spec.miners or ():
            if use.hint_context:
                informed.add(use.name)
    return frozenset(informed)


def hint_context_text(project: Project, work_id: str) -> str:
    """The text served to a hint-context miner for `work_id`: the researcher's hint, labelled as a
    hint that may be wrong, with its staleness; empty without hints. Bounded by `MAX_CONTEXT`."""
    hint = hints_by_work(project).get(work_id)
    if hint is None:
        return ""
    layer_stale, category_stale = hint_staleness(project, hint)
    parts: list[str] = []
    if hint.layer is not None:
        stale = f" (scheme version {hint.scheme_version}: out of date)" if layer_stale else ""
        parts.append(f"layer: {hint.layer}{stale}")
    if hint.category is not None:
        stale = f" ({hint.taxonomy} version {hint.taxonomy_version}: out of date)"
        parts.append(f"category: {hint.category}{stale if category_stale else ''}")
    if hint.miner_notes is not None:
        parts.append(f"notes: {hint.miner_notes}")
    body = "; ".join(parts)
    out = (
        "Researcher's hint at capture, recorded before any reading. It is the researcher's "
        "label, not evidence: it may be wrong. Classify from the text you read and give an "
        f"anchor and quote for every row, whatever the hint says. {body}"
    )
    return out[:MAX_CONTEXT]


@dataclass(frozen=True)
class HintAgreement:
    """m-layer's (or any listed miner's) agreement with the researcher's hints, as counts and one
    line per compared work. `agree` and `disagree` count only works with a current (not stale)
    hint and a real final value of an uninformed miner; the rest are listed by reason."""

    miner: str
    kind: str
    """`layer` or `category`."""
    compared: int
    agree: int
    disagree: int
    stale: int
    unmined: int
    absent: int
    """Works the miner's final row says is no layer or category (`not-stated`, `other`,
    `not-applicable`)."""
    disagreements: tuple[tuple[str, str, str], ...]
    """`(work_id, hint, miner value)` of each disagreement."""
    excluded: bool = False
    """True when the miner is hint-informed: counts are zero and nothing is scored."""


_ABSENT = frozenset({"not-stated", "other", "not-applicable"})


def _empty(miner: str, kind: str, *, excluded: bool = False) -> HintAgreement:
    return HintAgreement(miner, kind, 0, 0, 0, 0, 0, 0, (), excluded)


def hint_agreement(project: Project) -> list[HintAgreement]:
    """The agreement of each protocol-listed derived miner with the researcher's hints, computed
    from the final rows of the miner and the hints (layer hints against dimension zero's final
    category, category hints against the final rows of a miner of the hint's taxonomy). A
    hint-informed miner is reported as excluded and never scored; a stale hint is counted as stale
    and not compared. Read-only; empty without a protocol or hints."""
    protocol = current_protocol(project)
    hints = hints_by_work(project)
    if protocol is None or not hints:
        return []
    informed = hint_informed_miners(project)
    out: list[HintAgreement] = []
    for use in protocol.spec.miners or ():
        spec = registered_miner(project, use.name, use.version)
        if spec is None or spec.taxonomy is None:
            continue
        layer_dim = _layer_dimension_id(project, spec)
        has_layer_hints = layer_dim is not None and any(h.layer for h in hints.values())
        has_cat_hints = any(
            h.category is not None and h.taxonomy == spec.taxonomy.name for h in hints.values()
        )
        if not has_layer_hints and not has_cat_hints:
            continue
        if use.name in informed:
            if has_layer_hints:
                out.append(_empty(use.name, "layer", excluded=True))
            if has_cat_hints:
                out.append(_empty(use.name, "category", excluded=True))
            continue
        rows = final_rows(project, scope=MinerScope(use.name))
        values: dict[str, set[str]] = {}
        for row in rows:
            cell = row.fields.get("category")
            if cell is not None and isinstance(cell.value, str):
                values.setdefault(row.work_id, set()).add(cell.value)
        if has_layer_hints and layer_dim is not None:
            out.append(_layer_report(project, use.name, layer_dim, hints, values))
        if has_cat_hints:
            out.append(_category_report(project, use.name, spec.taxonomy.name, hints, values))
    return out


def _layer_dimension_id(project: Project, spec: MinerSpec) -> str | None:
    dimension = layer_dimension(project, spec)
    return None if dimension is None else dimension.id


def _layer_report(
    project: Project,
    miner: str,
    dimension: str,
    hints: dict[str, CaptureHint],
    values: dict[str, set[str]],
) -> HintAgreement:
    prefix = f"{dimension}/"
    agree = disagree = stale = unmined = absent = 0
    wrong: list[tuple[str, str, str]] = []
    for work, hint in sorted(hints.items()):
        if hint.layer is None:
            continue
        if hint_staleness(project, hint)[0]:
            stale += 1
            continue
        mine = {v[len(prefix) :] for v in values.get(work, set()) if v.startswith(prefix)}
        if not mine:
            unmined += 1
        elif mine <= _ABSENT:
            absent += 1
        elif hint.layer in mine:
            agree += 1
        else:
            disagree += 1
            wrong.append((work, hint.layer, ",".join(sorted(mine))))
    return HintAgreement(
        miner, "layer", agree + disagree, agree, disagree, stale, unmined, absent, tuple(wrong)
    )


def _category_report(
    project: Project,
    miner: str,
    taxonomy: str,
    hints: dict[str, CaptureHint],
    values: dict[str, set[str]],
) -> HintAgreement:
    agree = disagree = stale = unmined = absent = 0
    wrong: list[tuple[str, str, str]] = []
    for work, hint in sorted(hints.items()):
        if hint.category is None or hint.taxonomy != taxonomy:
            continue
        if hint_staleness(project, hint)[1]:
            stale += 1
            continue
        dimension = hint.category.split("/", 1)[0]
        mine = {v for v in values.get(work, set()) if v.startswith(f"{dimension}/")}
        real = {v for v in mine if v.split("/", 1)[1] not in _ABSENT}
        if not mine:
            unmined += 1
        elif not real:
            absent += 1
        elif hint.category in real:
            agree += 1
        else:
            disagree += 1
            wrong.append((work, hint.category, ",".join(sorted(real))))
    return HintAgreement(
        miner, "category", agree + disagree, agree, disagree, stale, unmined, absent, tuple(wrong)
    )

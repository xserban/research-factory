"""Check findings and figures of suggest and select (slice 8, plan task A8). Read-only.

Invariants:
- A message is a count and a noun; refs name decisions or records by identifier. No finding quotes
  an item's text, a ground or a note.
- `record-without-selection` fires for a question, seed, probe or protocol event whose payload
  carries `decision_ids` as an empty list: the service wrote it after slice 8 and the record cited
  no decision. It is an error in `pilot` and `systematic` only for a record written while the
  project was in a mode that required binding; one written while it was `exploratory` carries the
  empty list legitimately and stays a warning whatever the mode is now. The mode at the event is
  the one in the project's `project.created` event, the only record of a mode in the log (no
  event changes it), compared with `exploratory`; a log without one falls back to the mode now.
  An event without the key (or with null) predates the slice and is exempt. A hand-written event
  with an empty list is flagged like a service one.
- `selection-not-acted` looks at decisions at the four levels that feed a record (questions,
  seeds, probe, protocol) that have an accepted selection, are not superseded, and are cited by no
  record. Goal and plan decisions feed no record in this slice and are never flagged.
- `ungrounded-item` counts suggested items with empty `grounds` in decision sets that are not
  superseded; a superseded set is no longer the scientist's to judge.
- `recommendation_figure` is a figure, not a rule: of the live decisions with an accepted selection
  and at least one recommended item, the share where every recommended item was selected. None
  when there are none, so anchoring is measured, never assumed.
"""

from __future__ import annotations

from sqlalchemy import text

from factory.events.reader import read_all
from factory.model.base import StrictModel
from factory.model.project import RigorMode
from factory.modules.contract import CheckHit, Severity
from factory.services.context import Project

RECORD_TYPES: dict[str, tuple[str, str]] = {
    "question.recorded": ("question_id", "question version(s)"),
    "seed.added": ("seed_id", "seed(s)"),
    "probe.measured": ("probe_id", "probe(s)"),
    "protocol.recorded": ("protocol_id", "protocol recording(s)"),
}
"""The events that cite decisions: their identifier field and the noun a message uses."""

ACTED_LEVELS = ("questions", "seeds", "probe", "protocol")


class RecommendationFigure(StrictModel):
    """Selections that covered a recommendation, and whether the scientist took all of it."""

    with_recommendation: int
    followed_in_full: int
    share: float | None


def _cited(project: Project) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
    """The decision ids any record cites, and per event type the records that cite none (an
    empty list, not an absent key), split into those written while binding was required and those
    written while it was not."""
    cited: set[str] = set()
    bound: dict[str, set[str]] = {t: set() for t in RECORD_TYPES}
    legacy: dict[str, set[str]] = {t: set() for t in RECORD_TYPES}
    mode: RigorMode | None = None
    for event in read_all(project.paths.events_dir, project.catalog):
        if event.type == "project.created" and mode is None:
            try:
                mode = RigorMode(str(event.payload.get("rigor_mode")))
            except ValueError:
                mode = None
            continue
        spec = RECORD_TYPES.get(event.type)
        if spec is None:
            continue
        ids = event.payload.get("decision_ids")
        if isinstance(ids, list):
            cited.update(str(i) for i in ids)
            if not ids:
                required = (mode or _current_mode(project)) is not RigorMode.EXPLORATORY
                (bound if required else legacy)[event.type].add(str(event.payload.get(spec[0])))
    return cited, bound, legacy


def _current_mode(project: Project) -> RigorMode:
    with project.index.connect() as conn:
        return RigorMode(
            str(
                conn.execute(
                    text("SELECT rigor_mode FROM project WHERE slug = :slug"),
                    {"slug": project.paths.slug},
                ).scalar_one()
            )
        )


def decision_hits(project: Project) -> list[CheckHit]:
    cited, bound, legacy = _cited(project)
    hits: list[CheckHit] = []
    for event_type, (_, noun) in RECORD_TYPES.items():
        found: tuple[tuple[list[str], Severity | None], ...] = (
            (sorted(bound[event_type]), None),
            (sorted(legacy[event_type]), "warning"),
        )
        for refs, severity in found:
            if refs:
                hits.append(
                    CheckHit(
                        "record-without-selection",
                        tuple(refs),
                        f"{len(refs)} {noun} cite no selected decision",
                        severity=severity,
                    )
                )
    with project.index.connect() as conn:
        live = conn.execute(
            text(
                "SELECT d.decision_id, d.level, "
                "(SELECT COUNT(*) FROM decision_items i WHERE i.decision_id = d.decision_id "
                " AND i.status IN ('validated', 'rejected')) AS decided, "
                "(SELECT COUNT(*) FROM decision_items i WHERE i.decision_id = d.decision_id "
                " AND i.origin = 'suggested' AND i.grounds = '[]') AS ungrounded "
                "FROM decision_sets d WHERE d.superseded_by IS NULL ORDER BY d.decision_id"
            )
        ).all()
    idle = [
        str(r[0]) for r in live if int(r[2]) and r[1] in ACTED_LEVELS and str(r[0]) not in cited
    ]
    if idle:
        hits.append(
            CheckHit(
                "selection-not-acted",
                tuple(idle),
                f"{len(idle)} selected decision(s) no record cites",
            )
        )
    bare = [str(r[0]) for r in live if int(r[3])]
    if bare:
        total = sum(int(r[3]) for r in live)
        hits.append(
            CheckHit(
                "ungrounded-item",
                tuple(bare),
                f"{total} suggested item(s) in {len(bare)} decision(s) name no grounds",
            )
        )
    return hits


def recommendation_figure(project: Project) -> RecommendationFigure:
    """See the module docstring. Computed from the index, never typed."""
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT d.decision_id, "
                "SUM(CASE WHEN i.recommended = 1 THEN 1 ELSE 0 END) AS rec, "
                "SUM(CASE WHEN i.recommended = 1 AND i.status = 'validated' THEN 1 ELSE 0 END) "
                " AS taken "
                "FROM decision_sets d JOIN decision_items i ON i.decision_id = d.decision_id "
                "WHERE d.superseded_by IS NULL AND i.origin = 'suggested' "
                "AND EXISTS (SELECT 1 FROM decision_items x WHERE x.decision_id = d.decision_id "
                " AND x.status IN ('validated', 'rejected')) "
                "GROUP BY d.decision_id"
            )
        ).all()
    covered = [r for r in rows if int(r[1])]
    full = sum(1 for r in covered if int(r[1]) == int(r[2]))
    return RecommendationFigure(
        with_recommendation=len(covered),
        followed_in_full=full,
        share=full / len(covered) if covered else None,
    )

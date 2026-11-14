"""The trail of each work: what happened to it, in time order, read from the events.

Invariants: read-only; one pass over the project's events plus the works' provenance; a step holds
only short strings and numbers (long text is cut at `TEXT_LIMIT`); extraction and claim rows are
counted per schema and pass, never listed. A merge or its reversal appears on the primary and on
every absorbed work. The steps of a work are sorted by time, ties keeping event order.
"""

from collections import defaultdict
from typing import Final

from factory.clock import format_ts
from factory.events.envelope import Event
from factory.events.reader import read_all
from factory.model.base import StrictModel
from factory.model.work import Work
from factory.services.context import Project
from factory.services.search import list_works

TEXT_LIMIT: Final = 240
Value = str | int


class TrailStep(StrictModel):
    """One thing that happened to a work. `kind` names it; `d` holds its non-empty details."""

    at: str
    kind: str
    d: dict[str, Value]


def _cut(text: str, limit: int = TEXT_LIMIT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _details(**values: object) -> dict[str, Value]:
    out: dict[str, Value] = {}
    for key, value in values.items():
        if value is None or value == "":
            continue
        out[key] = value if isinstance(value, int) and not isinstance(value, bool) else str(value)
    return out


def _who(event: Event) -> dict[str, Value]:
    actor = event.actor
    return _details(by=actor.id, model=actor.model)


def _found(work: Work) -> list[TrailStep]:
    return [
        TrailStep(
            at=format_ts(p.at),
            kind="found",
            d=_details(source=p.source, query=p.query_id, run=p.run_id, method=p.method.value),
        )
        for p in work.provenance
    ]


class _Trails:
    """Accumulates steps per work id; `extracted` and `claims` are counted, then emitted."""

    def __init__(self) -> None:
        self.steps: dict[str, list[TrailStep]] = defaultdict(list)
        self.documents: dict[str, str] = {}
        self.merges: dict[str, tuple[str, tuple[str, ...]]] = {}
        self.counted: dict[tuple[str, str, str, str], list[object]] = {}

    def add(self, work_id: str, at: str, kind: str, d: dict[str, Value]) -> None:
        self.steps[work_id].append(TrailStep(at=at, kind=kind, d=d))

    def count(self, work_id: str, kind: str, label: str, pass_label: str, at: str) -> None:
        entry = self.counted.setdefault((work_id, kind, label, pass_label), [at, 0])
        entry[1] = int(str(entry[1])) + 1

    def feed(self, event: Event) -> None:
        handler = getattr(self, "_" + event.type.replace(".", "_"), None)
        if handler is not None:
            handler(event, format_ts(event.ts), event.payload)

    def _dedup_merged(self, event: Event, at: str, p: dict[str, object]) -> None:
        raw = p.get("absorbed")
        absorbed = tuple(str(a) for a in raw) if isinstance(raw, list | tuple) else ()
        primary = str(p.get("primary") or "")
        self.merges[str(p.get("merge_id"))] = (primary, absorbed)
        for work_id in filter(None, (primary, *absorbed)):
            self.add(
                work_id,
                at,
                "merged",
                _details(primary=primary, absorbed=", ".join(absorbed), rule=p.get("rule")),
            )

    def _dedup_reverted(self, event: Event, at: str, p: dict[str, object]) -> None:
        primary, absorbed = self.merges.get(str(p.get("merge_id")), ("", ()))
        for work_id in (primary, *absorbed):
            if work_id:
                self.add(
                    work_id,
                    at,
                    "merge reverted",
                    _details(
                        primary=primary,
                        absorbed=", ".join(absorbed),
                        reason=_cut(str(p.get("reason") or "")),
                        manual="yes" if p.get("manual") else "no",
                    ),
                )

    def _screening_decision_recorded(self, event: Event, at: str, p: dict[str, object]) -> None:
        self.add(
            str(p["work_id"]),
            at,
            "decision",
            _details(
                stage=p.get("stage"),
                pass_label=p.get("pass_label"),
                phase=p.get("phase"),
                verdict=p.get("verdict"),
                criterion=p.get("criterion"),
                score=p.get("score"),
                rationale=_cut(str(p.get("rationale") or "")),
                quote=_cut(str(p.get("quote") or "")),
                **_who(event),
            ),
        )

    def _screening_disagreement_resolved(self, event: Event, at: str, p: dict[str, object]) -> None:
        self.add(
            str(p["work_id"]),
            at,
            "resolved",
            _details(
                stage=p.get("stage"),
                verdict=p.get("verdict"),
                criterion=p.get("criterion"),
                reason=_cut(str(p.get("reason") or "")),
                channel=p.get("channel"),
                **_who(event),
            ),
        )

    def _fulltext_attempted(self, event: Event, at: str, p: dict[str, object]) -> None:
        self.add(
            str(p["work_id"]),
            at,
            "attempt",
            _details(
                route=p.get("route"),
                outcome=p.get("outcome"),
                reason=_cut(str(p.get("reason") or "")),
                http=p.get("http_status"),
            ),
        )

    def _fulltext_document_added(self, event: Event, at: str, p: dict[str, object]) -> None:
        work_id, doc = str(p["work_id"]), str(p["document_id"])
        self.documents[doc] = work_id
        self.add(
            work_id,
            at,
            "document added",
            _details(document=doc, route=p.get("route"), quality=p.get("quality")),
        )

    def _document_converted(self, event: Event, at: str, p: dict[str, object]) -> None:
        doc = str(p["document_id"])
        if doc in self.documents:
            self.add(
                self.documents[doc],
                at,
                "converted",
                _details(
                    document=doc,
                    converter=p.get("converter"),
                    version=p.get("converter_version"),
                ),
            )

    def _document_conversion_failed(self, event: Event, at: str, p: dict[str, object]) -> None:
        doc = str(p["document_id"])
        if doc in self.documents:
            self.add(
                self.documents[doc],
                at,
                "conversion failed",
                _details(
                    document=doc,
                    converter=p.get("converter"),
                    reason=p.get("reason"),
                    error=p.get("error_class"),
                ),
            )

    def _extraction_recorded(self, event: Event, at: str, p: dict[str, object]) -> None:
        self.count(str(p["work_id"]), "extracted", str(p["schema_ref"]), str(p["pass_label"]), at)

    def _extraction_claim_recorded(self, event: Event, at: str, p: dict[str, object]) -> None:
        self.count(str(p["work_id"]), "claims", "", str(p["pass_label"]), at)

    def finish(self) -> dict[str, list[TrailStep]]:
        for (work_id, kind, label, pass_label), (at, n) in self.counted.items():
            self.add(
                work_id,
                str(at),
                kind,
                _details(schema=label, pass_label=pass_label, rows=int(str(n))),
            )
        return {
            work_id: sorted(steps, key=lambda s: s.at)  # stable: ties keep event order
            for work_id, steps in sorted(self.steps.items())
        }


def flow_trails(project: Project) -> dict[str, list[TrailStep]]:
    """The time-ordered steps of every work that has any, keyed by work id."""
    project.index.sync()
    trails = _Trails()
    for work in list_works(project):
        for step in _found(work):
            trails.steps[work.id].append(step)
    for event in read_all(project.paths.events_dir, project.catalog):
        trails.feed(event)
    return trails.finish()

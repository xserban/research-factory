"""Reference layers: the researcher's scheme, a calibration sample, and an agent's layers.

Invariants:
- Scripts never judge. The queue order (citing count, then key) and the calibration draw (SHA-256
  of scheme version and key) are computed; a layer comes only from an agent's
  `reference.layer_assigned` or a human's `reference.layer_labelled`, never from a count.
- The scheme is recorded (by a human) before any assignment or label; an assignment or label
  naming an unrecorded version or a layer outside it is refused at the boundary.
- Nothing is masked (decision 37.9): an item is withheld from assignment only when its title is
  the title of a corpus work (`in_corpus`, counted, never dropped from the counts).
- Writes are all or nothing: a batch is validated in full before one event is appended.
- Reads write no event; `next_items` stores the served batch as a blob that `record_assignments`
  cites as `input_blob`.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import text

from factory.errors import FactoryValidationError, ValidationIssue
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError
from factory.events.envelope import Actor
from factory.model.references import (
    LayerAssigned,
    LayerDef,
    LayerLabelled,
    LayerSchemeRecorded,
    LayerStage,
)
from factory.quality.stats import cohen_kappa, cohen_kappa_nominal
from factory.services.context import Project
from factory.services.protocol_rules import KAPPA_FLOOR_MIN
from factory.services.reference_items import (
    ITEM_RULES_VERSION,
    CitedItem,
    ItemsReport,
    cited_items,
    normalise_title,
)
from factory.services.search import corpus_work_ids

CALIBRATION_SIZE: Final = 30
"""Items in the calibration sample: `CALIBRATION_SIZE // 3` per stratum of citing count."""
CALIBRATION_FLOOR: Final = KAPPA_FLOOR_MIN
"""Kappa floor for the calibration: the lowest floor a protocol may declare for title and abstract
screening (`protocol_rules.KAPPA_FLOOR_MIN`)."""
ABSTRACT_LAYERS: Final = ("in-scope", "adjacent")
"""Title-stage layers whose items go on to the abstract stage."""
DEFAULT_LIMIT: Final = 25


@dataclass(frozen=True)
class SchemeResult:
    version: int
    recorded: bool
    """False when the identical scheme was already recorded (no event written)."""
    event_id: str | None


@dataclass(frozen=True)
class ServedItem:
    key: str
    title: str
    year: int | None
    citing_count: int
    dois: tuple[str, ...]
    arxivs: tuple[str, ...]
    abstract: str | None = None


@dataclass
class NextBatch:
    stage: LayerStage
    scheme_version: int
    items: list[ServedItem] = field(default_factory=list)
    remaining: int = 0
    """Items still to assign at this stage, served ones included."""
    awaiting_resolution: int = 0
    """Abstract stage: shortlisted items with no abstract yet."""
    calibrating: bool = False
    """Title stage: only calibration-sample items are served until the calibration passes."""
    input_blob: str | None = None
    blocked: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CalibrationState:
    scheme_version: int
    sample_size: int
    labelled: int
    assigned: int
    compared: int
    """Sample items with both the researcher's label and an agent title-stage layer."""
    agreement: float | None
    kappa: float | None
    """Cohen's kappa over the layers as nominal categories (`quality.stats.cohen_kappa_nominal`);
    the pass measure."""
    kappa_by_layer: dict[str, float | None]
    """One-versus-rest kappa per layer: a diagnostic of where the raters differ, not the pass
    measure."""
    floor: float
    passed: bool


@dataclass(frozen=True)
class AssignResult:
    written: int
    event_ids: tuple[str, ...]


@dataclass
class LayerStatus:
    rules_version: str
    scheme_version: int | None
    entries_total: int
    assessable: int
    in_corpus: int
    unassessable: dict[str, int]
    by_stage: dict[str, dict[str, int]]
    left: dict[str, int]
    awaiting_resolution: int
    calibration: CalibrationState | None


def _refuse(field_: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_, message)])


# --- scheme -------------------------------------------------------------------------------------


def _scheme(project: Project, version: int | None = None) -> LayerSchemeRecorded | None:
    """The recorded scheme of `version`, or the highest version when `version` is None."""
    project.index.sync()
    sql = "SELECT version, layers FROM reference_layer_schemes "
    params: dict[str, int] = {}
    if version is None:
        sql += "ORDER BY version DESC LIMIT 1"
    else:
        sql += "WHERE version = :v"
        params["v"] = version
    with project.index.connect() as conn:
        row = conn.execute(text(sql), params).first()
    if row is None:
        return None
    layers = tuple(LayerDef.model_validate(d) for d in json.loads(str(row[1])))
    return LayerSchemeRecorded(version=int(row[0]), layers=layers)


def current_scheme(project: Project) -> LayerSchemeRecorded | None:
    """The scheme of the highest recorded version, or None."""
    return _scheme(project)


def record_scheme(project: Project, actor: Actor, scheme: LayerSchemeRecorded) -> SchemeResult:
    """Record the researcher's scheme. Refused for a non-human actor, and for a version already
    recorded with different content; the identical content again writes nothing."""
    if actor.kind != "human":
        raise _refuse("actor", "only the researcher records a layer scheme")
    with project.index.exclusive():
        existing = _scheme(project, scheme.version)
        if existing is not None:
            if existing.layers == scheme.layers:
                return SchemeResult(scheme.version, False, None)
            raise _refuse("version", f"version {scheme.version} is recorded with different content")
        event = project.events.make("reference.layer_scheme_recorded", scheme, actor)
        project.record([event])
    return SchemeResult(scheme.version, True, event.id)


# --- items and corpus ---------------------------------------------------------------------------


def _corpus_titles(project: Project) -> set[str]:
    """Normalised titles of the corpus works."""
    ids = corpus_work_ids(project)
    with project.index.connect() as conn:
        rows = conn.execute(text("SELECT work_id, data FROM works")).all()
    titles: set[str] = set()
    for wid, data in rows:
        if str(wid) in ids:
            title = json.loads(str(data)).get("title")
            if isinstance(title, str) and title.strip():
                titles.add(normalise_title(title))
    return titles


@dataclass(frozen=True)
class _Pool:
    report: ItemsReport
    candidates: tuple[CitedItem, ...]
    """Assessable items not in the corpus, in queue order."""
    in_corpus: tuple[str, ...]
    """Keys of assessable items whose title is a corpus work's title."""


def _pool(project: Project) -> _Pool:
    report = cited_items(project)
    corpus = _corpus_titles(project)
    candidates = tuple(i for i in report.items if i.normalised not in corpus)
    in_corpus = tuple(i.key for i in report.items if i.normalised in corpus)
    return _Pool(report, candidates, in_corpus)


# --- calibration --------------------------------------------------------------------------------


def _draw_order(scheme_version: int, key: str) -> str:
    return hashlib.sha256(f"{scheme_version}:{key}".encode()).hexdigest()


def _sample_from(candidates: Sequence[CitedItem], scheme_version: int) -> list[CitedItem]:
    n = len(candidates)
    per = CALIBRATION_SIZE // 3
    picked: list[CitedItem] = []
    for s in range(3):
        stratum = candidates[s * n // 3 : (s + 1) * n // 3]
        ordered = sorted(stratum, key=lambda i: _draw_order(scheme_version, i.key))
        picked.extend(ordered[:per])
    return sorted(picked, key=lambda i: (-i.citing_count, i.key))


def _draw(project: Project, scheme_version: int) -> list[CitedItem]:
    """The fresh draw: assessable, not-in-corpus items in three equal strata by queue order (top,
    middle, bottom third by citing count); in each, the ten items with the smallest SHA-256 of
    `<version>:<key>`. A stratum with fewer than ten items gives all of them."""
    return _sample_from(_pool(project).candidates, scheme_version)


def _sample_keys(project: Project, scheme_version: int) -> set[str]:
    """The calibration sample's keys. Items the researcher labelled always stay in it, so new
    extractions (which move the strata) never drop a labelled item; the fresh draw only fills it
    while fewer than `CALIBRATION_SIZE` items are labelled."""
    labelled = set(_labels(project, scheme_version))
    if len(labelled) >= CALIBRATION_SIZE:
        return labelled
    return labelled | {i.key for i in _draw(project, scheme_version)}


def calibration_sample(project: Project, scheme_version: int) -> list[CitedItem]:
    """The calibration sample in queue order: the labelled items plus, while fewer than
    `CALIBRATION_SIZE` are labelled, the fresh draw (`_draw`). A labelled item that is no longer
    an assessable candidate is left out of the items but kept in the state's key set."""
    keys = _sample_keys(project, scheme_version)
    return [i for i in _pool(project).candidates if i.key in keys]


def record_label(
    project: Project,
    actor: Actor,
    item_key: str,
    scheme_version: int,
    layer: str,
    note: str | None = None,
) -> str:
    """Record the researcher's own layer for a calibration-sample item; returns the event id.
    Refused for a non-human actor, an unknown version or layer, or a key outside the sample."""
    if actor.kind != "human":
        raise _refuse("actor", "only the researcher labels calibration items")
    with project.index.exclusive():
        scheme = _scheme(project, scheme_version)
        if scheme is None:
            raise _refuse("scheme_version", "unknown-scheme-version")
        if layer not in {d.id for d in scheme.layers}:
            raise _refuse("layer", "unknown-layer")
        if item_key not in _sample_keys(project, scheme_version):
            raise _refuse("item_key", "not in the calibration sample")
        event = project.events.make(
            "reference.layer_labelled",
            LayerLabelled(item_key=item_key, scheme_version=scheme_version, layer=layer, note=note),
            actor,
            refs=(item_key,),
        )
        project.record([event])
    return event.id


def _latest_layers(project: Project, stage: str, scheme_version: int) -> dict[str, str]:
    """Item key to its latest agent layer at `stage` under `scheme_version` (latest event wins
    across agent actors)."""
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT item_key, layer FROM reference_layers "
                "WHERE stage = :s AND scheme_version = :v ORDER BY event_id"
            ),
            {"s": stage, "v": scheme_version},
        ).all()
    return {str(k): str(v) for k, v in rows}


def _labels(project: Project, scheme_version: int) -> dict[str, str]:
    project.index.sync()
    with project.index.connect() as conn:
        rows = conn.execute(
            text("SELECT item_key, layer FROM reference_layer_labels WHERE scheme_version = :v"),
            {"v": scheme_version},
        ).all()
    return {str(k): str(v) for k, v in rows}


def _calibration(
    sample_keys: set[str],
    scheme: LayerSchemeRecorded,
    labels: dict[str, str],
    title: dict[str, str],
) -> CalibrationState:
    labelled = {k: v for k, v in labels.items() if k in sample_keys}
    assigned = {k: v for k, v in title.items() if k in sample_keys}
    both = sorted(set(labelled) & set(assigned))
    agree = sum(1 for k in both if labelled[k] == assigned[k])
    by_layer: dict[str, float | None] = {}
    for layer in (d.id for d in scheme.layers):
        if any(layer in (labelled[k], assigned[k]) for k in both):
            by_layer[layer] = cohen_kappa(
                [(labelled[k] == layer, assigned[k] == layer) for k in both]
            )
    kappa = cohen_kappa_nominal([(labelled[k], assigned[k]) for k in both])
    return CalibrationState(
        scheme_version=scheme.version,
        sample_size=len(sample_keys),
        labelled=len(labelled),
        assigned=len(assigned),
        compared=len(both),
        agreement=agree / len(both) if both else None,
        kappa=kappa,
        kappa_by_layer=by_layer,
        floor=CALIBRATION_FLOOR,
        passed=bool(sample_keys)
        and len(labelled) == len(sample_keys)
        and len(assigned) == len(sample_keys)
        and kappa is not None
        and kappa >= CALIBRATION_FLOOR,
    )


def calibration_state(project: Project, scheme_version: int) -> CalibrationState:
    """Labelled and assigned counts, percent agreement and kappa on the sample items having both
    the researcher's label and an agent title-stage layer. Passed when every sample item has both
    and kappa reaches `CALIBRATION_FLOOR`. Refused for an unknown version."""
    scheme = _scheme(project, scheme_version)
    if scheme is None:
        raise _refuse("scheme_version", "unknown-scheme-version")
    keys = _sample_keys(project, scheme_version)
    return _calibration(
        keys,
        scheme,
        _labels(project, scheme_version),
        _latest_layers(project, "title", scheme_version),
    )


# --- serving ------------------------------------------------------------------------------------


def _abstracts(project: Project, items: Sequence[CitedItem]) -> dict[str, str]:
    """Item key to an abstract, for items with an entry that has a live `resolved` link to a work
    whose record has one (the first such entry in entry order)."""
    with project.index.connect() as conn:
        links = {
            (str(e), int(o)): str(w)
            for e, o, w in conn.execute(
                text(
                    "SELECT l.extraction_id, l.ordinal, l.work_id FROM reference_links l "
                    "JOIN reference_extractions x ON x.extraction_id = l.extraction_id "
                    "WHERE x.live = 1 AND l.state = 'resolved' AND l.work_id IS NOT NULL"
                )
            ).all()
        }
        data = {
            str(w): str(d) for w, d in conn.execute(text("SELECT work_id, data FROM works")).all()
        }
    out: dict[str, str] = {}
    for item in items:
        for entry in item.entries:
            wid = links.get((entry.extraction_id, entry.ordinal))
            raw = data.get(wid) if wid else None
            abstract = json.loads(raw).get("abstract") if raw else None
            if isinstance(abstract, str) and abstract.strip():
                out[item.key] = abstract
                break
    return out


def _served(item: CitedItem, abstract: str | None = None) -> ServedItem:
    return ServedItem(
        item.key, item.title, item.year, item.citing_count, item.dois, item.arxivs, abstract
    )


def _stage_queue(
    project: Project, pool: _Pool, scheme: LayerSchemeRecorded, stage: LayerStage
) -> tuple[list[CitedItem], bool]:
    """Items still to assign at `stage` (in queue order) and whether the calibration gates them."""
    v = scheme.version
    if stage == "title":
        done = set(_latest_layers(project, "title", v))
        left = [i for i in pool.candidates if i.key not in done]
        state = calibration_state(project, v)
        if state.passed:
            return left, False
        sample = _sample_keys(project, v)
        return [i for i in left if i.key in sample], True
    title = _latest_layers(project, "title", v)
    done = set(_latest_layers(project, "abstract", v))
    return [
        i for i in pool.candidates if title.get(i.key) in ABSTRACT_LAYERS and i.key not in done
    ], False


def next_items(project: Project, *, stage: LayerStage, limit: int = DEFAULT_LIMIT) -> NextBatch:
    """Serve up to `limit` items to assign at `stage` under the current scheme.

    Title stage: until the calibration passes, only calibration-sample items without an agent
    assignment; afterwards every assessable, not-in-corpus item without one, by citing count then
    key. Abstract stage: items whose latest title layer is `in-scope` or `adjacent` and that have
    no abstract-stage layer, served with an abstract when a resolved entry's work has one; the
    others are counted in `awaiting_resolution`. The served batch is stored as a blob (its ref is
    `input_blob`); nothing is stored when nothing is served. Refused with no scheme recorded."""
    if limit < 1:
        raise _refuse("limit", "limit must be at least 1")
    scheme = current_scheme(project)
    if scheme is None:
        raise _refuse("scheme", "no layer scheme is recorded; the researcher records one first")
    pool = _pool(project)
    queue, calibrating = _stage_queue(project, pool, scheme, stage)
    batch = NextBatch(stage=stage, scheme_version=scheme.version, calibrating=calibrating)
    batch.remaining = len(queue)
    served: list[ServedItem]
    if stage == "abstract":
        abstracts = _abstracts(project, queue)
        batch.awaiting_resolution = sum(1 for i in queue if i.key not in abstracts)
        served = [_served(i, abstracts[i.key]) for i in queue if i.key in abstracts][:limit]
    else:
        served = [_served(i) for i in queue[:limit]]
    batch.items = served
    if served:
        batch.input_blob = project.blobs.put_json(
            {
                "stage": stage,
                "scheme_version": scheme.version,
                "rules_version": ITEM_RULES_VERSION,
                "calibrating": calibrating,
                "item_keys": [s.key for s in served],
            }
        )
    return batch


# --- recording ----------------------------------------------------------------------------------


def record_assignments(
    project: Project,
    actor: Actor,
    scheme_version: int,
    stage: LayerStage,
    assignments: Sequence[tuple[str, str, str]],
    input_blob: str,
) -> AssignResult:
    """Record an agent's layers, `(item_key, layer, rationale)` each, one event per item.

    Everything is validated first; any issue refuses the whole batch with nothing written: a
    non-agent actor, an empty batch, an unknown or unreadable `input_blob`, an unknown scheme
    version or layer, an unknown or in-corpus key, a duplicate key, and at stage `abstract` an
    item with no title-stage assignment."""
    issues: list[ValidationIssue] = []
    if actor.kind != "agent":
        issues.append(ValidationIssue("actor", "only an agent assigns layers"))
    if not assignments:
        issues.append(ValidationIssue("assignments", "no assignments"))
    try:
        project.blobs.get_json(input_blob)
    except (BlobNotFoundError, BlobIntegrityError, ValueError):
        issues.append(ValidationIssue("input_blob", "unknown or unreadable input blob"))
    with project.index.exclusive():
        scheme = _scheme(project, scheme_version)
        if scheme is None:
            issues.append(ValidationIssue("scheme_version", "unknown-scheme-version"))
        pool = _pool(project)
        known = {i.key for i in pool.report.items}
        in_corpus = set(pool.in_corpus)
        layers = {d.id for d in scheme.layers} if scheme else set()
        titled = (
            set(_latest_layers(project, "title", scheme_version)) if stage == "abstract" else set()
        )
        seen: set[str] = set()
        for n, (key, layer, _rationale) in enumerate(assignments):
            where = f"assignments[{n}]"
            if key in seen:
                issues.append(ValidationIssue(where, f"duplicate key {key}"))
            seen.add(key)
            if key not in known:
                issues.append(ValidationIssue(where, f"unknown item {key}"))
            elif key in in_corpus:
                issues.append(ValidationIssue(where, f"item {key} is in the corpus"))
            elif stage == "abstract" and key not in titled:
                issues.append(ValidationIssue(where, f"item {key} has no title-stage layer"))
            if scheme is not None and layer not in layers:
                issues.append(ValidationIssue(where, f"unknown-layer {layer}"))
        if issues:
            raise FactoryValidationError(issues)
        events = [
            project.events.make(
                "reference.layer_assigned",
                LayerAssigned(
                    item_key=key,
                    scheme_version=scheme_version,
                    stage=stage,
                    layer=layer,
                    rationale=rationale,
                ),
                actor,
                refs=(key,),
                input_blob=input_blob,
            )
            for key, layer, rationale in assignments
        ]
        project.record(events)
    return AssignResult(len(events), tuple(e.id for e in events))


# --- status -------------------------------------------------------------------------------------


def status(project: Project) -> LayerStatus:
    """Counts only: items by assessability, layers per stage, items left per stage, abstracts
    awaiting resolution, the calibration state, the entry total and the rules version."""
    pool = _pool(project)
    reasons: Counter[str] = Counter(r for u in pool.report.unassessable for r in u.reasons)
    scheme = current_scheme(project)
    result = LayerStatus(
        rules_version=pool.report.rules_version,
        scheme_version=None if scheme is None else scheme.version,
        entries_total=pool.report.entries_total,
        assessable=len(pool.report.items),
        in_corpus=len(pool.in_corpus),
        unassessable=dict(sorted(reasons.items())),
        by_stage={"title": {}, "abstract": {}},
        left={},
        awaiting_resolution=0,
        calibration=None,
    )
    if scheme is None:
        return result
    v = scheme.version
    for stage in ("title", "abstract"):
        result.by_stage[stage] = dict(
            sorted(Counter(_latest_layers(project, stage, v).values()).items())
        )
    title = _latest_layers(project, "title", v)
    sample = {i.key for i in _sample_from(pool.candidates, v)}
    result.calibration = _calibration(sample, scheme, _labels(project, v), title)
    result.left["title"] = sum(1 for i in pool.candidates if i.key not in title)
    queue, _ = _stage_queue(project, pool, scheme, "abstract")
    result.left["abstract"] = len(queue)
    abstracts = _abstracts(project, queue)
    result.awaiting_resolution = sum(1 for i in queue if i.key not in abstracts)
    return result

"""Reference layers: the researcher's scheme, a calibration sample, and an agent's layers.

Invariants:
- Scripts never judge. The queue order (citing count, then key) and the calibration draw (SHA-256
  of scheme version and key) are computed; a layer comes only from an agent's
  `reference.layer_assigned` or a human's `reference.layer_labelled`, never from a count.
- The scheme is recorded (by a human) before any assignment or label; an assignment or label
  naming an unrecorded version or a layer outside it is refused at the boundary.
- Nothing is masked (decision 37.9): an item is withheld from assignment only when its title is
  the title of a corpus work (`in_corpus`, counted, never dropped from the counts).
- A layer's flags (`snowball`, `abstract`) come from the recorded scheme; "precursor" is never a
  judged layer but computed from an item's year and the scheme's `precursor_before_year`.
  An unknown year is not a precursor.
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
    InnerSample,
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
DEFAULT_LIMIT: Final = 25
MAX_LIMIT: Final = 100
"""Most items `next_items` serves in one call."""


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
    precursor: bool
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
    dropped: int = 0
    """Labelled items left out of the sample because they are no longer assessable candidates
    (not assessable, or now in the corpus)."""
    agreement_by_layer: dict[str, float | None] = field(default_factory=dict)
    """Per layer, over compared items the researcher or the agent put in it: the share both put
    there."""
    strata: dict[str, int] = field(default_factory=dict)
    """Sample items per stratum: `base`, and `inner` when the scheme has an inner sample."""
    inner_by_layer: dict[str, int] = field(default_factory=dict)
    """Inner items per drawn layer of the earlier scheme."""
    inner_shortfall: dict[str, int] = field(default_factory=dict)
    """Per drawn layer, items the pool could not supply."""


@dataclass(frozen=True)
class AgentCalibration:
    """The calibration as an agent may see it: counts and the verdict only, never the researcher's
    agreement, kappa or which items are labelled."""

    scheme_version: int
    sample_size: int
    labelled: int
    assigned: int
    dropped: int
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
    calibration: CalibrationState | AgentCalibration | None
    precursors: dict[str, dict[str, int]] = field(default_factory=dict)
    """Per stage, per layer: items that are precursors (year before the scheme's cutoff)."""
    unknown_year: dict[str, dict[str, int]] = field(default_factory=dict)
    """Per stage, per layer: items with no known year."""
    snowball_candidates: int = 0
    """Items whose latest layer has `snowball` and that are not precursors."""


def _refuse(field_: str, message: str) -> FactoryValidationError:
    return FactoryValidationError([ValidationIssue(field_, message)])


# --- scheme -------------------------------------------------------------------------------------


def _scheme(project: Project, version: int | None = None) -> LayerSchemeRecorded | None:
    """The recorded scheme of `version`, or the highest version when `version` is None."""
    project.index.sync()
    sql = (
        "SELECT version, layers, precursor_before_year, inner_sample FROM reference_layer_schemes "
    )
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
    cutoff = None if row[2] is None else int(row[2])
    inner = None if row[3] is None else InnerSample.model_validate(json.loads(str(row[3])))
    return LayerSchemeRecorded(
        version=int(row[0]), layers=layers, precursor_before_year=cutoff, inner_sample=inner
    )


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
            if (
                existing.layers == scheme.layers
                and existing.precursor_before_year == scheme.precursor_before_year
                and existing.inner_sample == scheme.inner_sample
            ):
                return SchemeResult(scheme.version, False, None)
            raise _refuse("version", f"version {scheme.version} is recorded with different content")
        inner = scheme.inner_sample
        if inner is not None:
            earlier = _scheme(project, inner.from_version)
            if earlier is None:
                raise _refuse("inner_sample.from_version", "unknown-scheme-version")
            known = {d.id for d in earlier.layers}
            unknown = sorted(set(inner.draw) - known)
            if unknown:
                raise FactoryValidationError(
                    [
                        ValidationIssue(
                            f"inner_sample.draw.{layer}",
                            f"unknown-layer: not a layer of version {inner.from_version}",
                        )
                        for layer in unknown
                    ]
                )
        event = project.events.make("reference.layer_scheme_recorded", scheme, actor)
        project.record([event])
    return SchemeResult(scheme.version, True, event.id)


def is_precursor(item: CitedItem, scheme: LayerSchemeRecorded) -> bool:
    """True when the item's year is known and before the scheme's `precursor_before_year`.
    False with no cutoff or an unknown year."""
    cutoff = scheme.precursor_before_year
    return cutoff is not None and item.year is not None and item.year < cutoff


def _abstract_ids(scheme: LayerSchemeRecorded) -> frozenset[str]:
    """Ids of the layers whose items go on to the abstract stage."""
    return frozenset(d.id for d in scheme.layers if d.abstract)


def _snowball_ids(scheme: LayerSchemeRecorded) -> frozenset[str]:
    return frozenset(d.id for d in scheme.layers if d.snowball)


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


def _seed(scheme: LayerSchemeRecorded) -> int:
    """The version whose draw order the calibration sample of `scheme` uses: the inner sample's
    `seed_version` when set (a revised scheme reusing an earlier sample), else its own version."""
    inner = scheme.inner_sample
    return scheme.version if inner is None or inner.seed_version is None else inner.seed_version


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


@dataclass(frozen=True)
class _Sample:
    keys: frozenset[str]
    """Every sample item: base and inner."""
    inner: dict[str, str]
    """Inner-stratum item key to the earlier scheme's layer it was drawn from."""
    dropped: int
    shortfall: dict[str, int]
    """Per drawn layer of the inner sample, how many items the pool could not supply."""

    @property
    def base(self) -> frozenset[str]:
        return self.keys - self.inner.keys()


def _base_keys(pool: _Pool, kept: set[str], scheme_version: int) -> set[str]:
    """The base stratum: `kept` (labelled items), filled up to exactly `CALIBRATION_SIZE` (or the
    whole pool, if smaller) from the fresh draw (`_sample_from`, in its order), then, if the draw
    falls short, from the remaining candidates in SHA-256 draw order."""
    chosen = set(kept)
    need = CALIBRATION_SIZE - len(chosen)
    for item in _sample_from(pool.candidates, scheme_version):
        if need <= 0:
            break
        if item.key not in chosen:
            chosen.add(item.key)
            need -= 1
    if need > 0:
        rest = sorted(
            (i for i in pool.candidates if i.key not in chosen),
            key=lambda i: _draw_order(scheme_version, i.key),
        )
        chosen.update(i.key for i in rest[:need])
    return chosen


def _prior_layers(project: Project, scheme: LayerSchemeRecorded) -> dict[str, frozenset[str]]:
    """For a scheme with an inner sample: each drawn layer of the earlier scheme to the item keys
    an agent placed there at the title stage. Empty without an inner sample."""
    inner = scheme.inner_sample
    if inner is None:
        return {}
    pools: dict[str, set[str]] = {layer: set() for layer in inner.draw}
    for key, layer in _latest_layers(project, "title", inner.from_version).items():
        if layer in pools:
            pools[layer].add(key)
    return {layer: frozenset(keys) for layer, keys in pools.items()}


def _inner_draw(
    pool: _Pool,
    scheme: LayerSchemeRecorded,
    prior: dict[str, frozenset[str]],
    skip: set[str],
    force: frozenset[str],
) -> tuple[dict[str, str], dict[str, int]]:
    """The inner stratum: per drawn layer, `count` candidates that the earlier scheme's agent
    placed there (matched by item key or by membership of `item.aliases`), in SHA-256 order of
    (scheme version, layer id, item key). Items in `skip` (the base stratum) or already drawn for
    an earlier layer are passed over; `force` (labelled inner items) are taken first. Returns the
    item-to-layer map and the per-layer shortfall."""
    inner = scheme.inner_sample
    drawn: dict[str, str] = {}
    shortfall: dict[str, int] = {}
    if inner is None:
        return drawn, shortfall
    for layer in sorted(inner.draw):
        members = prior.get(layer, frozenset())
        matching = [
            i
            for i in pool.candidates
            if i.key not in skip
            and i.key not in drawn
            and (i.key in members or any(a in members for a in i.aliases))
        ]
        matching.sort(
            key=lambda i: hashlib.sha256(f"{_seed(scheme)}:{layer}:{i.key}".encode()).hexdigest()
        )
        picked = [i.key for i in matching if i.key in force]
        picked += [i.key for i in matching if i.key not in force][
            : max(0, inner.draw[layer] - len(picked))
        ]
        for key in picked:
            drawn[key] = layer
        if len(picked) < inner.draw[layer]:
            shortfall[layer] = inner.draw[layer] - len(picked)
    return drawn, shortfall


def _sample(
    pool: _Pool,
    labels: dict[str, str],
    scheme: LayerSchemeRecorded,
    prior: dict[str, frozenset[str]],
) -> _Sample:
    """The calibration sample: the base stratum (`CALIBRATION_SIZE` items, see `_base_keys`) plus,
    when the scheme has an `inner_sample`, the inner stratum (`_inner_draw`, skipping base items).
    Labelled items that are still candidates stay in the stratum a fresh, label-free draw puts
    them in (labelled items outside both strata stay in the base), so labelling never reshuffles
    the draw. Labelled items that are no longer candidates are left out and counted in
    `dropped`."""
    v = _seed(scheme)
    candidates = {i.key for i in pool.candidates}
    kept = {k for k in labels if k in candidates}
    fresh_inner, _ = _inner_draw(pool, scheme, prior, _base_keys(pool, set(), v), frozenset())
    forced = frozenset(kept & fresh_inner.keys())
    base = _base_keys(pool, kept - forced, v)
    inner, shortfall = _inner_draw(pool, scheme, prior, base, forced)
    return _Sample(frozenset(base | inner.keys()), inner, len(labels) - len(kept), shortfall)


def _sample_for(project: Project, pool: _Pool, scheme: LayerSchemeRecorded) -> _Sample:
    """The sample of `scheme` now. The caller holds `project.index.exclusive()`."""
    return _sample(pool, _labels(project, scheme.version), scheme, _prior_layers(project, scheme))


def calibration_sample(project: Project, scheme_version: int) -> list[CitedItem]:
    """The calibration sample in queue order (see `_sample`)."""
    return [i for i, _ in calibration_sample_strata(project, scheme_version)]


def calibration_sample_strata(project: Project, scheme_version: int) -> list[tuple[CitedItem, str]]:
    """The calibration sample in queue order, each item with its stratum: "base", or
    "inner:<layer>" (the layer of the earlier scheme it was drawn from). Refused for an unknown
    version."""
    with project.index.exclusive():
        scheme = _scheme(project, scheme_version)
        if scheme is None:
            raise _refuse("scheme_version", "unknown-scheme-version")
        pool = _pool(project)
        sample = _sample_for(project, pool, scheme)
    return [
        (i, f"inner:{sample.inner[i.key]}" if i.key in sample.inner else "base")
        for i in pool.candidates
        if i.key in sample.keys
    ]


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
        pool = _pool(project)
        if item_key not in _sample_for(project, pool, scheme).keys:
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


def researcher_labels(project: Project, scheme_version: int) -> dict[str, str]:
    """Item key to the researcher's calibration label under `scheme_version`."""
    return _labels(project, scheme_version)


def agent_layers(project: Project, stage: LayerStage, scheme_version: int) -> dict[str, str]:
    """Item key to the latest agent layer at `stage` under `scheme_version`."""
    return _latest_layers(project, stage, scheme_version)


def _calibration(
    sample: _Sample,
    scheme: LayerSchemeRecorded,
    labels: dict[str, str],
    title: dict[str, str],
) -> CalibrationState:
    sample_keys = sample.keys
    labelled = {k: v for k, v in labels.items() if k in sample_keys}
    assigned = {k: v for k, v in title.items() if k in sample_keys}
    both = sorted(set(labelled) & set(assigned))
    agree = sum(1 for k in both if labelled[k] == assigned[k])
    by_layer: dict[str, float | None] = {}
    agree_by_layer: dict[str, float | None] = {}
    for layer in (d.id for d in scheme.layers):
        touched = [k for k in both if layer in (labelled[k], assigned[k])]
        if touched:
            by_layer[layer] = cohen_kappa(
                [(labelled[k] == layer, assigned[k] == layer) for k in both]
            )
            agree_by_layer[layer] = sum(1 for k in touched if labelled[k] == assigned[k]) / len(
                touched
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
        agreement_by_layer=agree_by_layer,
        strata=(
            {"base": len(sample.base), "inner": len(sample.inner)}
            if scheme.inner_sample is not None
            else {"base": len(sample.base)}
        ),
        inner_by_layer=dict(sorted(Counter(sample.inner.values()).items())),
        inner_shortfall=dict(sample.shortfall),
        floor=CALIBRATION_FLOOR,
        dropped=sample.dropped,
        passed=bool(sample_keys)
        and len(labelled) == len(sample_keys)
        and len(assigned) == len(sample_keys)
        and kappa is not None
        and kappa >= CALIBRATION_FLOOR,
    )


def _calibration_for(
    project: Project, scheme: LayerSchemeRecorded, pool: _Pool
) -> CalibrationState:
    """The one calibration computation (gate, status and `calibration_state` all use it). The
    caller holds `project.index.exclusive()`."""
    v = scheme.version
    return _calibration(
        _sample_for(project, pool, scheme),
        scheme,
        _labels(project, v),
        _latest_layers(project, "title", v),
    )


def calibration_state(project: Project, scheme_version: int) -> CalibrationState:
    """Labelled and assigned counts, percent agreement and kappa on the sample items having both
    the researcher's label and an agent title-stage layer. Passed when every sample item has both
    and kappa reaches `CALIBRATION_FLOOR`. Refused for an unknown version. One consistent read."""
    with project.index.exclusive():
        scheme = _scheme(project, scheme_version)
        if scheme is None:
            raise _refuse("scheme_version", "unknown-scheme-version")
        return _calibration_for(project, scheme, _pool(project))


def agent_view(state: CalibrationState) -> AgentCalibration:
    """The redacted form of `state` for an agent."""
    return AgentCalibration(
        scheme_version=state.scheme_version,
        sample_size=state.sample_size,
        labelled=state.labelled,
        assigned=state.assigned,
        dropped=state.dropped,
        passed=state.passed,
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


def _served(
    item: CitedItem, scheme: LayerSchemeRecorded, abstract: str | None = None
) -> ServedItem:
    return ServedItem(
        item.key,
        item.title,
        item.year,
        is_precursor(item, scheme),
        item.citing_count,
        item.dois,
        item.arxivs,
        abstract,
    )


def _stage_queue(
    project: Project, pool: _Pool, scheme: LayerSchemeRecorded, stage: LayerStage
) -> tuple[list[CitedItem], bool]:
    """Items still to assign at `stage` (in queue order) and whether the calibration gates them.
    The caller holds `project.index.exclusive()`."""
    v = scheme.version
    if stage == "title":
        done = set(_latest_layers(project, "title", v))
        left = [i for i in pool.candidates if i.key not in done]
        sample = _sample_for(project, pool, scheme)
        if _calibration_for(project, scheme, pool).passed:
            return left, False
        return [i for i in left if i.key in sample.keys], True
    title = _latest_layers(project, "title", v)
    done = set(_latest_layers(project, "abstract", v))
    shortlisted = _abstract_ids(scheme)
    return [
        i for i in pool.candidates if title.get(i.key) in shortlisted and i.key not in done
    ], False


def next_items(project: Project, *, stage: LayerStage, limit: int = DEFAULT_LIMIT) -> NextBatch:
    """Serve up to `limit` items to assign at `stage` under the current scheme.

    Title stage: until the calibration passes, only calibration-sample items without an agent
    assignment; afterwards every assessable, not-in-corpus item without one, by citing count then
    key. Abstract stage: items whose latest title layer has `abstract=True` in the scheme and that
    have no abstract-stage layer, served with an abstract when a resolved entry's work has one; the
    others are counted in `awaiting_resolution`. The served batch is stored as a blob (its ref is
    `input_blob`); nothing is stored when nothing is served. Refused with no scheme recorded."""
    if limit < 1:
        raise _refuse("limit", "limit must be at least 1")
    if limit > MAX_LIMIT:
        raise _refuse("limit", f"limit must be at most {MAX_LIMIT}")
    with project.index.exclusive():
        return _next_items(project, stage, limit)


def _next_items(project: Project, stage: LayerStage, limit: int) -> NextBatch:
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
        served = [_served(i, scheme, abstracts[i.key]) for i in queue if i.key in abstracts][:limit]
    else:
        served = [_served(i, scheme) for i in queue[:limit]]
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
    with project.index.exclusive():
        served: set[str] | None = None
        try:
            blob = project.blobs.get_json(input_blob)
        except (BlobNotFoundError, BlobIntegrityError, ValueError):
            issues.append(ValidationIssue("input_blob", "unknown or unreadable input blob"))
        else:
            keys = blob.get("item_keys") if isinstance(blob, dict) else None
            if (
                not isinstance(blob, dict)
                or not isinstance(keys, list)
                or not all(isinstance(k, str) for k in keys)
            ):
                issues.append(ValidationIssue("input_blob", "not a served batch of items"))
            else:
                served = {str(k) for k in keys}
                if blob.get("stage") != stage:
                    issues.append(ValidationIssue("input_blob", "served for a different stage"))
                if blob.get("scheme_version") != scheme_version:
                    issues.append(
                        ValidationIssue("input_blob", "served under a different scheme version")
                    )
        scheme = _scheme(project, scheme_version)
        if scheme is None:
            issues.append(ValidationIssue("scheme_version", "unknown-scheme-version"))
        pool = _pool(project)
        known = {i.key for i in pool.report.items}
        in_corpus = set(pool.in_corpus)
        layers = {d.id for d in scheme.layers} if scheme else set()
        shortlisted = _abstract_ids(scheme) if scheme else frozenset[str]()
        allowed: set[str] | None = None
        calibrating = False
        if scheme is not None:
            queue, calibrating = _stage_queue(project, pool, scheme, stage)
            allowed = {i.key for i in queue}
        titled = _latest_layers(project, "title", scheme_version) if stage == "abstract" else {}
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
            elif stage == "abstract" and titled[key] not in shortlisted:
                issues.append(
                    ValidationIssue(
                        where, f"item {key} has title-stage layer {titled[key]}, not shortlisted"
                    )
                )
            elif served is not None and key not in served:
                issues.append(ValidationIssue(where, f"item {key} was not served in input_blob"))
            elif allowed is not None and key not in allowed:
                why = "outside the calibration sample" if calibrating else "not in the queue"
                issues.append(ValidationIssue(where, f"item {key} is not servable now: {why}"))
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


# --- layers of entries --------------------------------------------------------------------------


def snowball_layer_ids(project: Project) -> list[str]:
    """The ids of the current scheme's layers marked `snowball`, in scheme order. Refused when no
    scheme is recorded."""
    scheme = current_scheme(project)
    if scheme is None:
        raise _refuse("scheme", "no layer scheme is recorded")
    return [d.id for d in scheme.layers if d.snowball]


def entries_in_layers(project: Project, layers: Sequence[str]) -> set[tuple[str, int]]:
    """The (extraction id, ordinal) of every live entry whose cited item holds one of `layers`
    under the latest scheme version.

    An item's layer is the researcher's label if there is one, else the latest agent layer at the
    abstract stage, else at the title stage; assignments are found by the item's key or any of its
    aliases. Items with no layer select nothing. Refused, reading nothing further, when no scheme
    is recorded, `layers` is empty, or a layer id is not one of the scheme's.
    """
    scheme = current_scheme(project)
    if scheme is None:
        raise _refuse("scheme", "no layer scheme is recorded")
    known = {d.id for d in scheme.layers}
    issues = [
        ValidationIssue("layers", f"{layer!r}: not a layer of scheme version {scheme.version}")
        for layer in layers
        if layer not in known
    ]
    if not layers:
        issues.append(ValidationIssue("layers", "no layers named"))
    if issues:
        raise FactoryValidationError(issues)
    wanted = set(layers)
    v = scheme.version
    stages = (
        _labels(project, v),
        _latest_layers(project, "abstract", v),
        _latest_layers(project, "title", v),
    )
    selected: set[tuple[str, int]] = set()
    for item in cited_items(project).items:
        keys = (item.key, *item.aliases)
        layer = next((m[k] for m in stages for k in keys if k in m), None)
        if layer in wanted:
            selected.update((e.extraction_id, e.ordinal) for e in item.entries)
    return selected


# --- status -------------------------------------------------------------------------------------


def _snowball_items(project: Project, pool: _Pool, scheme: LayerSchemeRecorded) -> list[CitedItem]:
    """Candidates whose latest layer (abstract stage if present, else title) has `snowball` and
    that are not precursors. The caller holds `project.index.exclusive()`."""
    v = scheme.version
    title = _latest_layers(project, "title", v)
    abstract = _latest_layers(project, "abstract", v)
    wanted = _snowball_ids(scheme)
    out: list[CitedItem] = []
    for item in pool.candidates:
        layer = abstract.get(item.key) or title.get(item.key)
        if layer in wanted and not is_precursor(item, scheme):
            out.append(item)
    return out


def snowball_candidates(project: Project) -> list[CitedItem]:
    """Cited items to snowball from: latest layer (abstract stage if present, else title) has
    `snowball=True` in the current scheme and the item is not a precursor (an unknown year is not
    a precursor). In queue order. Empty with no scheme."""
    with project.index.exclusive():
        scheme = current_scheme(project)
        if scheme is None:
            return []
        return _snowball_items(project, _pool(project), scheme)


def status(project: Project, *, agent: bool = False) -> LayerStatus:
    """Counts only: items by assessability, layers per stage, items left per stage, abstracts
    awaiting resolution, per layer the precursors and unknown-year items, the snowball-candidate
    count, the calibration state, the entry total and the rules version. One
    consistent read. With `agent`, the calibration is the redacted `AgentCalibration` (no
    agreement, kappa or labelled-item information)."""
    with project.index.exclusive():
        return _status(project, agent)


def _status(project: Project, agent: bool) -> LayerStatus:
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
    state = _calibration_for(project, scheme, pool)
    result.calibration = agent_view(state) if agent else state
    result.left["title"] = sum(1 for i in pool.candidates if i.key not in title)
    queue, _ = _stage_queue(project, pool, scheme, "abstract")
    result.left["abstract"] = len(queue)
    by_key = {i.key: i for i in pool.report.items}
    for stage in ("title", "abstract"):
        precursors: Counter[str] = Counter()
        unknown: Counter[str] = Counter()
        for key, layer in _latest_layers(project, stage, v).items():
            item = by_key.get(key)
            if item is None:
                continue
            if item.year is None:
                unknown[layer] += 1
            elif is_precursor(item, scheme):
                precursors[layer] += 1
        result.precursors[stage] = dict(sorted(precursors.items()))
        result.unknown_year[stage] = dict(sorted(unknown.items()))
    result.snowball_candidates = len(_snowball_items(project, pool, scheme))
    abstracts = _abstracts(project, queue)
    result.awaiting_resolution = sum(1 for i in queue if i.key not in abstracts)
    return result

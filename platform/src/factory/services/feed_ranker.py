"""General like/dislike ranker for the factory feed (IDEA-58, plan 2026-11-23-factory-feed 4.3).

A port of arXiv Miner's `Ranker`, adapted to SPECTER2 vectors. Pure: no events, no files, no
model calls. Invariants:

- Labels are the latest reaction per arXiv id (True = like, False = dislike).
- The profile is the mean of the liked vectors. Features: cosine to the profile, the vector norm
  and the first `HEAD_DIMS` dimensions; then a standard scaler and a balanced logistic regression
  (dislikes weigh `DISLIKE_WEIGHT`). With no dislike there is no classifier and the score is the
  profile cosine mapped to [0, 1].
- `RankerState` is plain data. `to_json` is canonical (sorted keys, no whitespace), so the same
  input gives byte-identical output. Scoring is pure Python; scikit-learn (the optional `ranker`
  extra) is imported only to train.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from typing import Any

from factory.errors import FactoryValidationError, ValidationIssue

MIN_REACTIONS = 5  # slice 4c ruling 8, assumption A2
MIN_LIKES = 3
DISLIKE_WEIGHT = 0.5
HEAD_DIMS = 10
STATE_FORMAT = 1
FEATURE_NAMES = ("cosine_to_profile", "norm", *(f"dim_{i}" for i in range(HEAD_DIMS)))
_EPS = 1e-8  # as in arXiv Miner


@dataclass(frozen=True)
class TrainingShortfall:
    """Why training cannot start: fewer reactions or likes than the thresholds."""

    reason: str
    reactions: int
    likes: int
    min_reactions: int = MIN_REACTIONS
    min_likes: int = MIN_LIKES


def check_thresholds(labels: Mapping[str, bool]) -> TrainingShortfall | None:
    """None when training may start, else the structured reason."""
    reactions = len(labels)
    likes = sum(1 for v in labels.values() if v)
    missing = []
    if reactions < MIN_REACTIONS:
        missing.append(f"{reactions} reactions, {MIN_REACTIONS} needed")
    if likes < MIN_LIKES:
        missing.append(f"{likes} likes, {MIN_LIKES} needed")
    if not missing:
        return None
    return TrainingShortfall("; ".join(missing), reactions, likes)


def training_set_hash(labels: Mapping[str, bool]) -> str:
    """sha256 over the sorted (id, label) pairs."""
    pairs = [[k, bool(v)] for k, v in sorted(labels.items())]
    return "sha256:" + hashlib.sha256(_dumps(pairs).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RankerState:
    """The learned state. `coef`/`intercept`/`scaler_*` are None without a classifier."""

    profile: tuple[float, ...]
    scaler_mean: tuple[float, ...] | None
    scaler_scale: tuple[float, ...] | None
    coef: tuple[float, ...] | None
    intercept: float | None
    feature_names: tuple[str, ...]
    embedding_model: str
    dims: int
    library_versions: Mapping[str, str]
    n_likes: int
    n_dislikes: int
    training_set_hash: str

    @property
    def has_classifier(self) -> bool:
        return self.coef is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": STATE_FORMAT,
            "profile": list(self.profile),
            "scaler_mean": None if self.scaler_mean is None else list(self.scaler_mean),
            "scaler_scale": None if self.scaler_scale is None else list(self.scaler_scale),
            "coef": None if self.coef is None else list(self.coef),
            "intercept": self.intercept,
            "feature_names": list(self.feature_names),
            "embedding_model": self.embedding_model,
            "dims": self.dims,
            "library_versions": dict(self.library_versions),
            "n_likes": self.n_likes,
            "n_dislikes": self.n_dislikes,
            "training_set_hash": self.training_set_hash,
        }

    def to_json(self) -> str:
        """Canonical JSON: same state, same bytes."""
        return _dumps(self.to_dict())

    @staticmethod
    def from_json(text: str) -> RankerState:
        try:
            d = json.loads(text)
            if d["format"] != STATE_FORMAT:
                raise ValueError(f"unknown ranker format {d['format']!r}")

            def opt(key: str) -> tuple[float, ...] | None:
                return None if d[key] is None else tuple(float(x) for x in d[key])

            icpt = d["intercept"]
            state = RankerState(
                profile=tuple(float(x) for x in d["profile"]),
                scaler_mean=opt("scaler_mean"),
                scaler_scale=opt("scaler_scale"),
                coef=opt("coef"),
                intercept=None if icpt is None else float(icpt),
                feature_names=tuple(str(x) for x in d["feature_names"]),
                embedding_model=str(d["embedding_model"]),
                dims=int(d["dims"]),
                library_versions={str(k): str(v) for k, v in d["library_versions"].items()},
                n_likes=int(d["n_likes"]),
                n_dislikes=int(d["n_dislikes"]),
                training_set_hash=str(d["training_set_hash"]),
            )
            if len(state.profile) != state.dims:
                raise ValueError("profile length differs from dims")
            if state.coef is not None and not (
                state.scaler_mean is not None
                and state.scaler_scale is not None
                and state.intercept is not None
                and len(state.coef) == len(state.scaler_mean) == len(state.scaler_scale)
            ):
                raise ValueError("classifier parts are inconsistent")
            return state
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise FactoryValidationError(
                [ValidationIssue("ranker_state", f"the saved ranker is damaged ({exc})")]
            ) from exc


def _dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(math.fsum(x * x for x in v))


def _cosine(v: Sequence[float], profile: Sequence[float], profile_norm: float) -> float:
    dot = math.fsum(a * b for a, b in zip(v, profile, strict=True))
    return dot / (_norm(v) * profile_norm + _EPS)


def _features(v: Sequence[float], profile: Sequence[float], profile_norm: float) -> list[float]:
    return [_cosine(v, profile, profile_norm), _norm(v), *v[:HEAD_DIMS]]


def train(
    labels: Mapping[str, bool],
    vectors: Mapping[str, Sequence[float]],
    *,
    embedding_model: str = "",
) -> RankerState:
    """Train on the labelled ids. Raises FactoryValidationError below the thresholds, for ids
    without a vector, for ragged vectors or fewer than `HEAD_DIMS` dimensions."""
    short = check_thresholds(labels)
    issues: list[ValidationIssue] = []
    if short is not None:
        issues.append(ValidationIssue("labels", short.reason))
    missing = sorted(k for k in labels if k not in vectors)
    if missing:
        issues.append(ValidationIssue("vectors", f"no vector for {', '.join(missing[:5])}"))
    if issues:
        raise FactoryValidationError(issues)
    ids = sorted(labels)
    dims = len(vectors[ids[0]])
    if dims < HEAD_DIMS or any(len(vectors[i]) != dims for i in ids):
        raise FactoryValidationError(
            [ValidationIssue("vectors", f"vectors must share one length of at least {HEAD_DIMS}")]
        )
    liked = [[float(x) for x in vectors[i]] for i in ids if labels[i]]
    disliked = [[float(x) for x in vectors[i]] for i in ids if not labels[i]]
    profile = [math.fsum(col) / len(liked) for col in zip(*liked, strict=True)]
    versions: dict[str, str] = {}
    base = dict(
        profile=tuple(profile),
        feature_names=FEATURE_NAMES,
        embedding_model=embedding_model,
        dims=dims,
        n_likes=len(liked),
        n_dislikes=len(disliked),
        training_set_hash=training_set_hash(labels),
    )
    if not disliked:
        return RankerState(
            scaler_mean=None,
            scaler_scale=None,
            coef=None,
            intercept=None,
            library_versions=versions,
            **base,  # type: ignore[arg-type]
        )
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        from factory.services.ranking_model import ranker_unavailable

        raise ranker_unavailable("scikit-learn is not installed") from exc
    pn = _norm(profile)
    rows = [_features(v, profile, pn) for v in liked + disliked]
    y = [1] * len(liked) + [0] * len(disliked)
    weights = [1.0] * len(liked) + [DISLIKE_WEIGHT] * len(disliked)
    scaler = StandardScaler()
    x = scaler.fit_transform(np.array(rows, dtype=np.float64))
    clf = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=0)
    clf.fit(x, np.array(y), sample_weight=np.array(weights))
    versions = {
        "scikit-learn": metadata.version("scikit-learn"),
        "numpy": metadata.version("numpy"),
    }
    return RankerState(
        scaler_mean=tuple(float(a) for a in scaler.mean_),
        scaler_scale=tuple(float(a) for a in scaler.scale_),
        coef=tuple(float(a) for a in clf.coef_[0]),
        intercept=float(clf.intercept_[0]),
        library_versions=versions,
        **base,  # type: ignore[arg-type]
    )


def score(state: RankerState, vectors: Mapping[str, Sequence[float]]) -> dict[str, float]:
    """Probability of a like per id (0-1); the cosine fallback without a classifier."""
    pn = _norm(state.profile)
    out: dict[str, float] = {}
    for key, v in vectors.items():
        if len(v) != state.dims:
            raise FactoryValidationError(
                [ValidationIssue("vectors", f"{key}: {len(v)} dims, the ranker has {state.dims}")]
            )
        vec = [float(x) for x in v]
        if state.coef is None:
            out[key] = (_cosine(vec, state.profile, pn) + 1.0) / 2.0
            continue
        assert state.scaler_mean is not None and state.scaler_scale is not None
        assert state.intercept is not None
        feats = _features(vec, state.profile, pn)
        z = state.intercept + math.fsum(
            c * (f - m) / s
            for c, f, m, s in zip(
                state.coef, feats, state.scaler_mean, state.scaler_scale, strict=True
            )
        )
        out[key] = 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))
    return out


def order(scores: Mapping[str, float]) -> list[str]:
    """Ids by descending score, ties by id ascending."""
    return sorted(scores, key=lambda k: (-scores[k], k))

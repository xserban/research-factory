"""Passage vectors and meaning-based search (IDEA-102), with a fake deterministic embedder: offline,
no weights."""

# ruff: noqa: F811
import math
import sqlite3
from collections.abc import Sequence

import pytest

from factory.errors import FactoryValidationError
from factory.services import corpus_search as cs
from factory.services import passage_vectors as pv
from factory.services.context import Project
from factory.services.corpus_search import ON_DEMAND_MAX, RRF_K, corpus_search
from factory.services.passage_index import ensure_indexed, index_path
from factory.services.ranking_model import ranker_unavailable
from factory.services.selection import SelectedWork, SelectionSpec, resolve_selection
from tests.extraction_helpers import screened  # noqa: F401
from tests.test_corpus_search import _convert

VOCAB = ["attention", "retrieval", "gradient", "transformer", "recall", "optimizer"]


class FakeEmbedder:
    """Bag of vocabulary words; counts calls and texts embedded."""

    def __init__(self, weights: str = "w1", fail_after: int | None = None) -> None:
        self._weights = weights
        self.texts = 0
        self.calls = 0
        self.fail_after = fail_after

    @property
    def model_id(self) -> str:
        return "fake/bow"

    @property
    def weights_hash(self) -> str:
        return self._weights * 10

    @property
    def software(self) -> str:
        return "fake"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("interrupted")
        self.texts += len(texts)
        out = []
        for t in texts:
            words = t.lower().replace(",", " ").replace(".", " ").split()
            out.append([float(words.count(v)) + 0.01 for v in VOCAB])
        return out


def _works(project: Project) -> list[SelectedWork]:
    project.index.sync()
    return list(resolve_selection(project, SelectionSpec()).works)


def _count(project: Project, key: str | None = None) -> int:
    conn = sqlite3.connect(index_path(project))
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'passage_vectors'"
        ).fetchall():
            return 0
        if key is None:
            return int(conn.execute("SELECT COUNT(*) FROM passage_vectors").fetchone()[0])
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM passage_vectors WHERE model_key = ?", (key,)
            ).fetchone()[0]
        )
    finally:
        conn.close()


def test_model_key_shape() -> None:
    key = pv.model_key(FakeEmbedder())
    assert key.startswith("fake/bow@") and "/chunker4:" in key
    assert key.split("@")[1].split("/")[0] == "w1" * 8


def test_incremental_embed_second_call_embeds_nothing(
    project: Project, screened: list[str]
) -> None:
    _convert(project)
    emb = FakeEmbedder()
    works = _works(project)
    first = pv.ensure_embedded(project, works, emb)
    assert first.embedded == 3 * len(screened) and first.reused == 0 and first.missing == 0
    calls = emb.calls
    second = pv.ensure_embedded(project, works, emb)
    assert (second.embedded, second.reused) == (0, 3 * len(screened))
    assert emb.calls == calls


def test_resume_after_interruption(
    project: Project, screened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _convert(project)
    monkeypatch.setattr(pv, "BATCH", 2)
    works = _works(project)
    broken = FakeEmbedder(fail_after=1)
    with pytest.raises(RuntimeError):
        pv.ensure_embedded(project, works, broken)
    assert _count(project) == 2  # the first batch was committed
    resumed = pv.ensure_embedded(project, works, FakeEmbedder())
    assert resumed.reused == 2 and resumed.embedded == 3 * len(screened) - 2
    assert _count(project) == 3 * len(screened)


def test_limit_and_progress(project: Project, screened: list[str]) -> None:
    _convert(project)
    seen: list[tuple[int, int]] = []
    report = pv.ensure_embedded(
        project, _works(project), FakeEmbedder(), limit=2, progress=lambda d, t: seen.append((d, t))
    )
    assert report.embedded == 2 and report.missing == 3 * len(screened) - 2
    assert seen == [(2, 2)]


def test_unpinned_conversion_vectors_removed(project: Project, screened: list[str]) -> None:
    emb = FakeEmbedder()
    first = pv.ensure_embedded(project, _works(project), emb)  # the fixture's own conversions
    assert first.embedded > 0
    _convert(project, "2.0", "zebra")
    report = pv.ensure_embedded(project, _works(project), emb)
    assert report.removed == first.embedded
    assert report.embedded == 3 * len(screened)
    assert _count(project) == 3 * len(screened)


def test_key_change_forces_re_embed_and_drops_old(project: Project, screened: list[str]) -> None:
    _convert(project)
    works = _works(project)
    pv.ensure_embedded(project, works, FakeEmbedder("w1"))
    other = FakeEmbedder("w2")
    report = pv.ensure_embedded(project, works, other)
    assert report.embedded == 3 * len(screened) and report.removed == 3 * len(screened)
    assert _count(project, pv.model_key(other)) == _count(project)


def test_long_passage_is_mean_of_windows_and_unit(
    project: Project, screened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _convert(project)
    monkeypatch.setattr(pv, "embedding_windows", lambda text: [text, text + " gradient"])
    emb = FakeEmbedder()
    pv.ensure_embedded(project, _works(project), emb)
    conn = sqlite3.connect(index_path(project))
    try:
        dim, blob = conn.execute("SELECT dim, vector FROM passage_vectors").fetchone()
    finally:
        conn.close()
    from array import array

    vec = array("f")
    vec.frombytes(blob)
    assert dim == len(VOCAB) == len(vec)
    assert math.isclose(sum(x * x for x in vec), 1.0, rel_tol=1e-5)
    assert emb.texts == 2 * 3 * len(screened)


def test_schema_version_change_recreates_only_vectors(
    project: Project, screened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _convert(project)
    works = _works(project)
    pv.ensure_embedded(project, works, FakeEmbedder())
    monkeypatch.setattr(pv, "VECTORS_SCHEMA_VERSION", 99)
    assert pv.count_missing(project, works, pv.model_key(FakeEmbedder())) == 3 * len(screened)
    assert ensure_indexed(project, works).reused == len(screened)


def test_vector_ranking_order(project: Project, screened: list[str]) -> None:
    _convert(project)
    emb = FakeEmbedder()
    works = _works(project)
    pv.ensure_embedded(project, works, emb)
    ranked = pv.vector_ranking(project, works, "gradient optimizer", emb, kinds=None, k=100)
    assert len(ranked) == 3 * len(screened)
    assert {p for _, p in ranked[: len(screened)]} == {"s3.p1"}


def test_vector_search_hits_have_vector_rank_only(project: Project, screened: list[str]) -> None:
    _convert(project)
    result = corpus_search(
        project, ["retrieval recall"], SelectionSpec(), method="vector", embedder=FakeEmbedder()
    )
    assert result.method == "vector" and result.note is None
    assert result.hits[0].passage_id == "s2.p1"
    assert all(h.keyword_rank is None and h.vector_rank is not None for h in result.hits)
    assert result.hits[0].ranks_per_query == (result.hits[0].vector_rank,)


def test_hybrid_fusion_ranks(project: Project, screened: list[str]) -> None:
    _convert(project)
    result = corpus_search(
        project,
        ["attention"],
        SelectionSpec(),
        method="hybrid",
        embedder=FakeEmbedder(),
        per_work_limit=10,
        limit=100,
    )
    assert result.method == "hybrid" and result.note is None
    by_pid = {h.passage_id: h for h in result.hits}
    assert by_pid["s3.p1"].keyword_rank is None and by_pid["s3.p1"].vector_rank is not None
    assert by_pid["s1.p1"].keyword_rank is not None

    def score(h: cs.Hit) -> float:
        return sum(1.0 / (RRF_K + r) for r in (h.keyword_rank, h.vector_rank) if r is not None)

    scores = [score(h) for h in result.hits]
    assert scores == sorted(scores, reverse=True)
    assert [h.rank for h in result.hits] == list(range(1, len(result.hits) + 1))


def test_default_method_is_keyword_and_unchanged(project: Project, screened: list[str]) -> None:
    _convert(project)
    result = corpus_search(project, ["attention"], SelectionSpec())
    assert result.method == "keyword" and result.note is None
    assert all(h.vector_rank is None and h.keyword_rank == h.rank for h in result.hits)
    assert _count(project) == 0  # keyword search never embeds


def test_on_demand_embedding_under_threshold(project: Project, screened: list[str]) -> None:
    _convert(project)
    emb = FakeEmbedder()
    corpus_search(project, ["attention"], SelectionSpec(), method="vector", embedder=emb)
    assert _count(project) == 3 * len(screened)


def test_over_threshold_vector_refused_hybrid_falls_back(
    project: Project, screened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _convert(project)
    monkeypatch.setattr(cs, "ON_DEMAND_MAX", 2)
    emb = FakeEmbedder()
    with pytest.raises(FactoryValidationError) as err:
        corpus_search(project, ["attention"], SelectionSpec(), method="vector", embedder=emb)
    issue = err.value.issues[0]
    assert issue.field == "vectors" and "factory passages embed" in issue.reason
    result = corpus_search(project, ["attention"], SelectionSpec(), method="hybrid", embedder=emb)
    assert result.method == "keyword" and result.hits
    assert result.note is not None and result.note.startswith(
        f"vectors missing for {3 * len(screened)} passages; run `factory passages embed"
    )
    assert emb.texts == 0
    assert ON_DEMAND_MAX == 300


def test_missing_embedder_vector_refuses_hybrid_falls_back(
    project: Project, screened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _convert(project)

    def unavailable() -> FakeEmbedder:
        raise ranker_unavailable("FACTORY_RANKER_MODEL is not set")

    monkeypatch.setattr(pv, "default_embedder", unavailable)
    monkeypatch.setattr(cs, "default_embedder", unavailable)
    with pytest.raises(FactoryValidationError) as err:
        corpus_search(project, ["attention"], SelectionSpec(), method="vector")
    assert err.value.issues[0].field == "ranker"
    result = corpus_search(project, ["attention"], SelectionSpec(), method="hybrid")
    assert result.method == "keyword" and result.hits
    assert result.note is not None and "keyword only" in result.note


def test_unknown_method_refused(project: Project, screened: list[str]) -> None:
    _convert(project)
    with pytest.raises(FactoryValidationError) as err:
        corpus_search(project, ["attention"], SelectionSpec(), method="nonsense")  # type: ignore[arg-type]
    assert err.value.issues[0].field == "method"

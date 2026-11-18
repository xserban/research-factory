"""Passage index sidecar and keyword corpus search (plan chat T3b). Conversions come from a
converter that emits anchored Markdown, so passages are known."""

# ruff: noqa: F811
import pytest

from factory.document.passages import SectionKind
from factory.document.registry import ConverterRegistry
from factory.errors import FactoryValidationError
from factory.services import corpus_search as cs
from factory.services.context import Project
from factory.services.corpus_search import corpus_search
from factory.services.document_convert import convert_documents
from factory.services.passage_index import ensure_indexed, index_path
from factory.services.selection import SelectionSpec, resolve_selection
from tests.extraction_helpers import screened  # noqa: F401


def _doc(extra: str) -> str:
    def h(a: str, t: str) -> str:
        return f'<a id="{a}"></a>\n## {t}'

    def p(a: str, t: str) -> str:
        return f'<a id="{a}"></a>\n{t}'

    return (
        "\n\n".join(
            [
                h("s1", "Methods"),
                p("s1.p1", "The transformer attention mechanism, well-known."),
                h("s2", "Results"),
                p("s2.p1", "Retrieval augmented attention improves recall."),
                h("s3", "Discussion"),
                p("s3.p1", f"Gradient descent optimizer notes {extra} SECRETDOI."),
            ]
        )
        + "\n"
    )


class Anchored:
    name = "anchored"
    accepts = frozenset({"text/html"})

    def __init__(self, version: str = "1.0", extra: str = "") -> None:
        self._version = version
        self._extra = extra

    def version(self) -> str:
        return self._version

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        return _doc(self._extra), ()


def _convert(
    project: Project, version: str = "1.0", extra: str = "", *, override: bool = True
) -> None:
    convert_documents(project, ConverterRegistry([Anchored(version, extra)]), override=override)


def _hits(
    project: Project, queries: list[str], *, limit: int = 20, per_work_limit: int = 3
) -> cs.SearchResult:
    return corpus_search(
        project, queries, SelectionSpec(), limit=limit, per_work_limit=per_work_limit
    )


def test_index_built_then_reused(project: Project, screened: list[str]) -> None:
    _convert(project)
    sel = resolve_selection(project, SelectionSpec())
    first = ensure_indexed(project, sel.works)
    assert (first.indexed, first.reused, first.removed) == (len(screened), 0, 0)
    second = ensure_indexed(project, sel.works)
    assert (second.indexed, second.reused, second.removed) == (0, len(screened), 0)


def test_reindex_after_conversion_change_removes_old_rows(
    project: Project, screened: list[str]
) -> None:
    assert _hits(project, ["zebra"]).hits == ()  # the fixture's own conversions
    _convert(project, "2.0", "zebra")
    result = _hits(project, ["zebra"])
    assert {h.work_id for h in result.hits} == set(screened)
    assert result.index.indexed == len(screened)
    assert result.index.removed >= 3 * len(screened)
    sel = resolve_selection(project, SelectionSpec())
    assert {h.conversion_id for h in result.hits} == {w.conversion_id for w in sel.works}


def test_search_restricted_to_selection(project: Project, screened: list[str]) -> None:
    _convert(project)
    result = corpus_search(project, ["attention"], SelectionSpec(exclude=[screened[0]]))
    assert screened[0] not in {h.work_id for h in result.hits}
    assert {h.work_id for h in result.hits} == set(screened) - {screened[0]}


def test_or_semantics_and_phrase(project: Project, screened: list[str]) -> None:
    _convert(project)
    either = _hits(project, ["transformer retrieval"], per_work_limit=10)
    assert {h.passage_id for h in either.hits} == {"s1.p1", "s2.p1"}
    phrase = _hits(project, ['"attention mechanism"'], per_work_limit=10)
    assert {h.passage_id for h in phrase.hits} == {"s1.p1"}
    assert phrase.hits[0].section_path == ("Methods",)
    assert phrase.hits[0].anchors == ("s1.p1",)


def test_punctuation_does_not_raise(project: Project, screened: list[str]) -> None:
    _convert(project)
    result = _hits(project, ['attention) AND (NEAR* "unbalanced ^ - : ! ?'])
    assert result.hits


def test_empty_and_too_many_queries_refused(project: Project, screened: list[str]) -> None:
    _convert(project)
    for bad in ([], [""], ["   "], ["!!!"], ["x"] * 11):
        with pytest.raises(FactoryValidationError) as err:
            _hits(project, bad)
        assert [i.field for i in err.value.issues] == ["queries"]


def test_fusion_prefers_passage_hit_by_both(project: Project, screened: list[str]) -> None:
    _convert(project)
    result = _hits(project, ["attention", "retrieval"], per_work_limit=10)
    top = result.hits[0]
    assert top.passage_id == "s2.p1"
    assert None not in top.ranks_per_query
    other = next(h for h in result.hits if h.passage_id == "s1.p1")
    assert None in other.ranks_per_query
    assert top.rank < other.rank


def test_per_work_limit_and_limit(project: Project, screened: list[str]) -> None:
    _convert(project)
    one = _hits(project, ["attention transformer retrieval"], per_work_limit=1)
    assert len(one.hits) == len(screened)
    assert len({h.work_id for h in one.hits}) == len(screened)
    capped = _hits(project, ["attention"], limit=1)
    assert len(capped.hits) == 1


def test_ties_are_deterministic(project: Project, screened: list[str]) -> None:
    _convert(project)
    one = _hits(project, ["transformer"], per_work_limit=1)
    two = _hits(project, ["transformer"], per_work_limit=1)
    assert [(h.work_id, h.passage_id) for h in one.hits] == [
        (h.work_id, h.passage_id) for h in two.hits
    ]
    assert [h.work_id for h in one.hits] == sorted(h.work_id for h in one.hits)


def test_held_out_scrub_applied(
    project: Project, screened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _convert(project)
    monkeypatch.setattr(cs, "held_out_tokens", lambda _p, include_work_ids=True: {"SECRETDOI"})
    result = _hits(project, ["gradient"], per_work_limit=10)
    assert len(result.hits) == len(screened)
    assert all("SECRETDOI" not in h.text and "[withheld]" in h.text for h in result.hits)


def test_deleted_sidecar_is_rebuilt(project: Project, screened: list[str]) -> None:
    _convert(project)
    before = _hits(project, ["attention"], per_work_limit=10)
    index_path(project).unlink()
    after = _hits(project, ["attention"], per_work_limit=10)
    assert after.index.indexed == len(screened)
    assert [(h.work_id, h.passage_id) for h in after.hits] == [
        (h.work_id, h.passage_id) for h in before.hits
    ]


class Kinded(Anchored):
    """A document with front, method, related, appendix and back sections.

    The paragraph under "References" is parsed as a bibliography entry, not a passage, so only
    the related and appendix passages are excluded (two per work).
    """

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        def h(a: str, t: str) -> str:
            return f'<a id="{a}"></a>\n## {t}'

        def p(a: str, t: str) -> str:
            return f'<a id="{a}"></a>\n{t} ' + " ".join(["filler"] * 30)

        parts = [
            h("s1", "Introduction"),
            p("s1.p1", "Quokka intro."),
            h("s2", "Related Work"),
            p("s2.p1", "Quokka related."),
            h("s3", "Method"),
            p("s3.p1", "Quokka method."),
            h("s4", "Appendix A"),
            p("s4.p1", "Quokka appendix."),
            h("s5", "References"),
            p("s5.p1", "Quokka references."),
        ]
        return "\n\n".join(parts) + "\n", ()


def test_unindexed_kinds_and_kinds_filter(project: Project, screened: list[str]) -> None:
    convert_documents(project, ConverterRegistry([Kinded()]), override=True)
    result = _hits(project, ["quokka"], limit=200, per_work_limit=10)
    assert {h.passage_id for h in result.hits} == {"s1.p1", "s3.p1"}
    assert result.index.excluded_passages == 2 * len({h.work_id for h in result.hits})
    kinds = {h.passage_id: h.section_kind for h in result.hits}
    assert kinds == {"s1.p1": SectionKind.FRONT, "s3.p1": SectionKind.METHOD}
    only = corpus_search(
        project, ["quokka"], SelectionSpec(), kinds=[SectionKind.METHOD], per_work_limit=10
    )
    assert {h.passage_id for h in only.hits} == {"s3.p1"}
    by_text = corpus_search(project, ["quokka"], SelectionSpec(), kinds=["front"])  # type: ignore[list-item]
    assert {h.passage_id for h in by_text.hits} == {"s1.p1"}
    none = corpus_search(project, ["quokka"], SelectionSpec(), kinds=[SectionKind.RELATED])
    assert none.hits == ()


def test_unknown_kind_refused(project: Project, screened: list[str]) -> None:
    with pytest.raises(FactoryValidationError) as err:
        corpus_search(project, ["x"], SelectionSpec(), kinds=["nonsense"])  # type: ignore[list-item]
    assert err.value.issues[0].field == "kinds"


def test_sidecar_of_an_older_schema_is_rebuilt(project: Project, screened: list[str]) -> None:
    # A sidecar written before a schema change (here: v1, without `section_kind`) must not break
    # indexing; observed 2026-11-18 on the pilot copy after T3c. Other tables are left alone.
    import sqlite3

    _convert(project)
    path = index_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE passages(conversion_id TEXT, work_id TEXT, passage_id TEXT, "
        "anchors_json TEXT, section_path_json TEXT, text TEXT, chunker_version TEXT, "
        "markdown_hash TEXT, PRIMARY KEY (conversion_id, passage_id));"
        "INSERT INTO passages VALUES ('c', 'w', 'p', '[]', '[]', 'old', '1', 'h');"
        "CREATE TABLE keep_me(x INTEGER); INSERT INTO keep_me VALUES (7);"
    )
    conn.commit()
    conn.close()
    result = _hits(project, ["attention"])
    assert {h.work_id for h in result.hits} == set(screened)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT count(*) FROM passages WHERE work_id = 'w'").fetchone() == (0,)
    assert conn.execute("SELECT x FROM keep_me").fetchone() == (7,)
    conn.close()

"""Selection service: layers, include and exclude, missing conversions, size and digest (plan chat
T1). The documents are converted by a pass-through converter so the Markdown length is exact."""

# ruff: noqa: F811
import pytest

from factory.document.registry import ConverterRegistry
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.mining.spec import Population
from factory.model.references import LayerDef, LayerSchemeRecorded
from factory.services.context import Project
from factory.services.document_convert import convert_documents
from factory.services.reference_layers import record_scheme
from factory.services.selection import (
    CHARS_PER_TOKEN,
    SelectionSpec,
    resolve_selection,
)
from factory.services.work_layers import move_layer
from tests.extraction_helpers import screened  # noqa: F401


class PassThrough:
    name = "passthrough"
    accepts = frozenset({"text/html"})

    def __init__(self, version: str = "1.0") -> None:
        self._version = version

    def version(self) -> str:
        return self._version

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        return raw.decode("utf-8"), ()


def _convert(project: Project, version: str = "1.0", *, override: bool = False) -> None:
    convert_documents(project, ConverterRegistry([PassThrough(version)]), override=override)


def _scheme() -> LayerSchemeRecorded:
    def layer(i: str, ring: int, snowball: bool) -> LayerDef:
        return LayerDef(id=i, ring=ring, snowball=snowball, name=i, criteria=f"criteria of {i}")

    return LayerSchemeRecorded(
        version=1, layers=(layer("core", 0, True), layer("applied", 1, False))
    )


def _events(project: Project) -> list[bytes]:
    return [p.read_bytes() for p in sorted(project.paths.events_dir.rglob("*")) if p.is_file()]


def test_default_selects_the_population_with_sizes_sorted(
    project: Project, screened: list[str]
) -> None:
    works = sorted(screened)
    _convert(project)

    sel = resolve_selection(project, SelectionSpec())

    assert [w.work_id for w in sel.works] == works
    assert sel.excluded == ()
    assert sel.chars == sum(w.chars for w in sel.works)
    assert all(w.chars > 0 for w in sel.works)
    assert sel.est_tokens == sel.chars // CHARS_PER_TOKEN
    assert CHARS_PER_TOKEN == 4


def test_work_without_conversion_is_excluded_with_reason(
    project: Project, screened: list[str]
) -> None:
    _convert(project)

    sel = resolve_selection(project, SelectionSpec(population=Population.CORPUS))

    assert sel.excluded
    assert {reason for _w, reason in sel.excluded} == {"no-conversion"}
    assert set(screened) <= {w.work_id for w in sel.works}
    assert not {w for w, _r in sel.excluded} & set(screened)


def test_layer_filter(project: Project, human: Actor, screened: list[str]) -> None:
    works = sorted(screened)
    _convert(project)
    record_scheme(project, human, _scheme())
    move_layer(project, human, works[0], "core", "t")
    move_layer(project, human, works[1], "applied", "t")

    sel = resolve_selection(project, SelectionSpec(layers=["core"]))

    assert [w.work_id for w in sel.works] == [works[0]]
    both = resolve_selection(project, SelectionSpec(layers=["core", "applied"]))
    assert [w.work_id for w in both.works] == works[:2]


def test_exclude_removes_and_is_listed(project: Project, screened: list[str]) -> None:
    works = sorted(screened)
    _convert(project)

    sel = resolve_selection(project, SelectionSpec(exclude=[works[0]]))

    assert works[0] not in [w.work_id for w in sel.works]
    assert (works[0], "excluded") in sel.excluded


def test_include_and_exclude_ids_pass_the_work_id_resolver(
    project: Project, screened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Work ids here are ASCII, so an NFC-different spelling is simulated: the resolver (IDEA-66)
    # maps an alias to the stored id, and exclude/include must go through it with their field.
    works = sorted(screened)
    _convert(project)
    seen: list[str] = []

    def fake(_project: Project, ids: object, *, field: str = "work_ids") -> list[str]:
        seen.append(field)
        return [works[0] if i == "rf:alias" else i for i in ids]  # type: ignore[attr-defined]

    monkeypatch.setattr("factory.services.selection.resolve_work_ids", fake)
    sel = resolve_selection(project, SelectionSpec(exclude=["rf:alias"]))
    assert works[0] not in [w.work_id for w in sel.works]
    assert (works[0], "excluded") in sel.excluded
    narrow = resolve_selection(project, SelectionSpec(include=["rf:alias"], exclude=works[1:]))
    assert [w.work_id for w in narrow.works] == [works[0]]
    assert set(seen) == {"include", "exclude"}


def test_include_outside_the_population_and_unknown_id(
    project: Project, screened: list[str]
) -> None:
    works = sorted(screened)
    _convert(project)
    # a population of nothing in the protocol's sense: the corpus is wider than included-ft
    narrow = resolve_selection(
        project, SelectionSpec(include=[works[0], "rf:no-such-work"], exclude=works[1:])
    )

    assert [w.work_id for w in narrow.works] == [works[0]]
    assert ("rf:no-such-work", "unknown-work") in narrow.excluded

    corpus = resolve_selection(project, SelectionSpec(population=Population.CORPUS, exclude=works))
    assert not {w.work_id for w in corpus.works} & set(works)


def test_unknown_layer_refused_and_writes_nothing(project: Project, human: Actor) -> None:
    record_scheme(project, human, _scheme())
    before = _events(project)

    with pytest.raises(FactoryValidationError) as err:
        resolve_selection(project, SelectionSpec(layers=["core", "nope"]))

    assert [i.field for i in err.value.issues] == ["layers"]
    assert _events(project) == before


def test_read_only_writes_no_event(project: Project, screened: list[str]) -> None:
    _convert(project)
    before = _events(project)
    resolve_selection(project, SelectionSpec())
    assert _events(project) == before


def test_digest_stable_under_order_and_changes_with_a_conversion(
    project: Project, screened: list[str]
) -> None:
    works = sorted(screened)
    _convert(project, "1.0+a")

    one = resolve_selection(project, SelectionSpec(include=works[::-1]))
    two = resolve_selection(project, SelectionSpec(include=works))
    assert one.digest == two.digest == resolve_selection(project, SelectionSpec()).digest

    _convert(project, "1.0+b", override=True)
    changed = resolve_selection(project, SelectionSpec())
    assert changed.digest != one.digest
    assert [w.work_id for w in changed.works] == works


def test_cached_resolution_reused_until_the_log_changes(
    project: Project, screened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services import selection as sel_mod

    _convert(project)
    calls: list[int] = []
    real = sel_mod.resolve_selection

    def counting(p: Project, s: SelectionSpec) -> sel_mod.Selection:
        calls.append(1)
        return real(p, s)

    monkeypatch.setattr(sel_mod, "resolve_selection", counting)
    spec = SelectionSpec()
    first = sel_mod.resolve_selection_cached(project, spec)
    second = sel_mod.resolve_selection_cached(project, SelectionSpec())
    assert second is first and len(calls) == 1
    other = sel_mod.resolve_selection_cached(project, SelectionSpec(exclude=[screened[0]]))
    assert len(calls) == 2 and other.digest != first.digest
    _convert(project, "9.9", override=True)  # appends events
    third = sel_mod.resolve_selection_cached(project, spec)
    assert len(calls) == 3 and third.digest != first.digest
    with pytest.raises(FactoryValidationError):
        sel_mod.resolve_selection_cached(project, SelectionSpec(layers=["nope"]))
    assert len(calls) == 4


def test_closed_selection_reads_only_include_and_ignores_the_population(
    project: Project, screened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    works = sorted(screened)
    assert len(works) >= 3
    _convert(project)
    closed = SelectionSpec(closed=True, include=works[:2])
    assert [w.work_id for w in resolve_selection(project, closed).works] == works[:2]
    # a work that joins the population later does not enter a closed selection
    from factory.services import selection as selection_module

    real = selection_module.population_works
    monkeypatch.setattr(
        selection_module, "population_works", lambda p, pop: [*real(p, pop), "wrk_NEW"]
    )
    assert [w.work_id for w in resolve_selection(project, closed).works] == works[:2]
    # exclude still applies to a closed selection
    narrowed = SelectionSpec(closed=True, include=works[:2], exclude=[works[0]])
    assert [w.work_id for w in resolve_selection(project, narrowed).works] == [works[1]]


def test_closed_and_open_specs_differ_in_digest_and_old_specs_stay_open(
    project: Project, screened: list[str]
) -> None:
    works = sorted(screened)
    _convert(project)
    assert SelectionSpec().closed is False
    old = SelectionSpec.model_validate({"layers": [], "include": [], "exclude": []})
    assert old.closed is False
    everything = SelectionSpec(include=works)
    closed = SelectionSpec(closed=True, include=works)
    a, b = resolve_selection(project, everything), resolve_selection(project, closed)
    assert [w.work_id for w in a.works] == [w.work_id for w in b.works]
    assert a.digest != b.digest

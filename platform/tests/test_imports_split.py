"""Development and held-out parts of a pre-search import (plan Import-A task 4, I8)."""

from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.imports.model import ImportFormat
from factory.model.imports import ImportRole, ImportSplitDrawn
from factory.model.search import (
    QueryKind,
    QueryPurpose,
    QueryRegistered,
    QuerySpec,
    SearchRunStarted,
)
from factory.services.context import Project
from factory.services.imports import development_ordinals, import_part, record_import
from factory.services.seeds import draw_split
from tests.helpers import _of_type


def _bib(tmp_path: Path, n: int, *, malformed: int = 0) -> Path:
    entries = [
        f"@article{{k{i}, title={{Made-Up Title {i}}}, year={{{2000 + i % 4}}}}}"
        for i in range(1, n + 1)
    ]
    entries += ["@article{bad, title = {Unclosed"] * malformed
    path = tmp_path / "library.bib"
    path.write_text("\n\n".join(entries) + "\n")
    return path


def _run(project: Project, purpose: QueryPurpose) -> None:
    """A registered query of `purpose` and a started run of it."""
    query_id = project.ids.new("qry")
    spec = QuerySpec(source="openalex", kind=QueryKind.KEYWORD, text="pears", purpose=purpose)
    actor = project.system_actor()
    project.record(
        [
            project.events.make(
                "query.registered",
                QueryRegistered(query_id=query_id, spec=spec, interface="test"),
                actor,
                refs=(query_id,),
            ),
            project.events.make(
                "search.run_started",
                SearchRunStarted(run_id=project.ids.new("run"), query_id=query_id),
                actor,
                refs=(query_id,),
            ),
        ]
    )


def _split_event(project: Project) -> ImportSplitDrawn:
    [event] = _of_type(project, "import.split_drawn")
    return ImportSplitDrawn.model_validate(event.payload)


def test_split_only_before_search(project: Project, tmp_path: Path) -> None:
    path = _bib(tmp_path, 9)
    fresh = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=11
    )
    assert fresh.split == "drawn"
    drawn = _split_event(project)
    assert (drawn.mode, drawn.random_seed) == ("drawn", 11)
    assert drawn.parts_blob is not None
    parts = project.blobs.get_json(drawn.parts_blob)
    assert isinstance(parts, dict)
    development, held_out = parts["development"], parts["held_out"]
    assert isinstance(development, list) and isinstance(held_out, list)
    assert sorted(development + held_out) == list(range(1, 10))
    expected_dev, expected_held = draw_split(
        [(f"{fresh.import_id}:{i}", 2000 + i % 4) for i in range(1, 10)], 11
    )
    assert len(held_out) == len(expected_held) == 3 and len(development) == len(expected_dev)
    assert development_ordinals(project, fresh.import_id) == sorted(development)  # type: ignore[type-var]
    assert {import_part(project, fresh.import_id, o) for o in held_out} == {"held-out"}  # type: ignore[arg-type]

    _run(project, QueryPurpose.SEARCH)
    late = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=11
    )
    assert late.split == "post-search"
    events = [
        ImportSplitDrawn.model_validate(e.payload) for e in _of_type(project, "import.split_drawn")
    ]
    assert (events[1].mode, events[1].random_seed, events[1].parts_blob) == (
        "post-search",
        None,
        None,
    )
    assert development_ordinals(project, late.import_id) == list(range(1, 10))
    assert import_part(project, late.import_id, 1) == "unsplit"


def test_split_written_with_recorded_in_one_append(project: Project, tmp_path: Path) -> None:
    record_import(project, _bib(tmp_path, 3), format=ImportFormat.BIBTEX, role=ImportRole.CORPUS)
    [recorded] = _of_type(project, "import.recorded")
    [split] = _of_type(project, "import.split_drawn")
    assert split.refs == recorded.refs and split.actor.kind == "human"


def test_split_reproducible_from_seed(project: Project, tmp_path: Path) -> None:
    path = _bib(tmp_path, 12)
    a = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=5
    )
    b = record_import(
        project, path, format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE, random_seed=5
    )
    assert development_ordinals(project, a.import_id) == development_ordinals(project, b.import_id)


def test_probe_runs_do_not_count_as_search(project: Project, tmp_path: Path) -> None:
    _run(project, QueryPurpose.PROBE)
    s = record_import(
        project, _bib(tmp_path, 3), format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE
    )
    assert s.split == "drawn"


def test_malformed_records_not_split(project: Project, tmp_path: Path) -> None:
    s = record_import(
        project,
        _bib(tmp_path, 6, malformed=2),
        format=ImportFormat.BIBTEX,
        role=ImportRole.REFERENCE,
    )
    parts = project.blobs.get_json(_split_event(project).parts_blob or "")
    assert isinstance(parts, dict)
    union = sorted(parts["development"] + parts["held_out"])  # type: ignore[operator]
    assert union == list(range(1, 7))
    assert import_part(project, s.import_id, 7) == "unsplit"


def test_declined_split(project: Project, tmp_path: Path) -> None:
    s = record_import(
        project,
        _bib(tmp_path, 3),
        format=ImportFormat.BIBTEX,
        role=ImportRole.REFERENCE,
        split=False,
    )
    assert s.split == "declined"
    event = _split_event(project)
    assert (event.mode, event.random_seed, event.parts_blob) == ("declined", None, None)
    assert development_ordinals(project, s.import_id) == [1, 2, 3]


def test_random_seed_validated(project: Project, tmp_path: Path) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        record_import(
            project,
            _bib(tmp_path, 3),
            format=ImportFormat.BIBTEX,
            role=ImportRole.REFERENCE,
            random_seed=-1,
        )
    assert [i.field for i in caught.value.issues] == ["random_seed"]
    assert _of_type(project, "import.recorded") == []


def test_split_drawn_shape() -> None:
    with pytest.raises(ValueError):
        ImportSplitDrawn(
            import_id="imp_01ARZ3NDEKTSV4RRFFQ69G5FAV",
            mode="drawn",
            random_seed=None,
            parts_blob=None,
        )
    with pytest.raises(ValueError):
        ImportSplitDrawn(
            import_id="imp_01ARZ3NDEKTSV4RRFFQ69G5FAV",
            mode="post-search",
            random_seed=3,
            parts_blob=None,
        )


def test_default_seed_is_32_random_bits(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def randbits(k: int) -> int:
        calls.append(k)
        return 123456789

    monkeypatch.setattr("factory.services.imports.secrets.randbits", randbits)
    record_import(project, _bib(tmp_path, 3), format=ImportFormat.BIBTEX, role=ImportRole.REFERENCE)
    assert calls == [32] and _split_event(project).random_seed == 123456789

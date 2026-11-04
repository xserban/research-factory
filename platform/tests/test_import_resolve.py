"""Resolution of import records with the slice-3a resolver (plan Import-B task 1).

Every record is invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.references import LinkState, ReferenceEntry
from factory.services.context import Project
from factory.services.dedup import canonical_works
from factory.services.import_resolve import (
    ImportResolvable,
    record_states,
    resolvables,
    resolve_import,
)
from factory.services.reference_resolve import resolve_entries
from factory.services.search import corpus_size
from tests.document_helpers import events_of_type
from tests.import_helpers import bib_entry, import_bib
from tests.references_service_helpers import Lookups, oa_item

SHA = "0" * 64


def _entry(**kw: object) -> ReferenceEntry:
    return ReferenceEntry(ordinal=1, anchor="b1", entry_sha256=SHA, **kw)  # type: ignore[arg-type]


def _resolvable(**kw: object) -> ImportResolvable:
    base: dict[str, object] = {
        "ordinal": 1,
        "doi": None,
        "arxiv": None,
        "url": None,
        "year": None,
        "first_author": None,
        "title": None,
        "venue": None,
    }
    return ImportResolvable(**{**base, **kw})  # type: ignore[arg-type]


@pytest.fixture
def lookups() -> Lookups:
    return Lookups(
        openalex=[
            oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501"),
            oa_item("Moss growth under filtered light", "Pia Ostrander", 2008, "W502"),
            oa_item("Moss growth under filtered lights", "Pia Ostrander", 2008, "W503"),
            oa_item("Sedge Mapping Methods", "Ana Kim", 2015, "W504", doi="10.9999/sedge.1"),
        ]
    )


FIELDS: dict[str, dict[str, object]] = {
    "identifier": {"doi": "10.9999/sedge.1", "year": 2015, "title": "Sedge Mapping Methods"},
    "fuzzy": {"title": "Efficient Reed Transformers v2", "first_author": "Lee", "year": 2021},
    "ambiguous": {"title": "Moss growth under filtered light v2", "year": 2008},
    "unresolved": {"title": "Wholly unknown matters here", "year": 2001},
    "no-title": {"year": 2001},
}


@pytest.mark.parametrize("case", sorted(FIELDS))
def test_resolver_parity(project: Project, corpus: None, lookups: Lookups, case: str) -> None:
    """The same fields as a reference entry and as an import record resolve identically."""
    fields = FIELDS[case]
    actor = project.human_actor()
    by_entry = resolve_entries(project, actor, [_entry(**fields)], sources=lookups.sources())
    by_record = resolve_entries(project, actor, [_resolvable(**fields)], sources=lookups.sources())
    assert by_entry.resolutions == by_record.resolutions
    assert len(by_entry.lookup_runs) == len(by_record.lookup_runs)


def test_resolvables_skip_malformed_and_take_surname(project: Project, tmp_path: Path) -> None:
    bib = [
        bib_entry("a", "Made-Up Pears", year=2019, author="Quill, Ada and Li, Bo"),
        bib_entry("b", "Made-Up Figs", year=2018, author="Ada Quill"),
    ]
    imp = import_bib(project, tmp_path, [*bib, "@article{bad, title = {Unclosed\n"])
    rs = resolvables(project, imp)
    assert [(r.ordinal, r.first_author) for r in rs] == [(1, "Quill"), (2, "Quill")]


def test_corpus_identifier_first(project: Project, corpus: None, tmp_path: Path) -> None:
    work = next(w for w in canonical_works(project) if w.identifiers.doi)
    imp = import_bib(
        project,
        tmp_path,
        [bib_entry("a", work.title, year=2020, author="X, Y", doi=work.identifiers.doi)],
    )
    lookups = Lookups()
    resolve_import(project, imp, sources=lookups.sources())
    assert lookups.asked == []
    [event] = events_of_type(project, "import.resolved")
    [r] = event.payload["resolutions"]  # type: ignore[misc]
    assert r["method"] == "corpus-identifier" and r["work_id"] == work.id  # type: ignore[index]


def test_lookups_are_probe_purpose_outside_corpus(
    project: Project, corpus: None, tmp_path: Path, lookups: Lookups
) -> None:
    imp = import_bib(
        project,
        tmp_path,
        [
            bib_entry(
                "a", "Sedge Mapping Methods", year=2015, author="Kim, Ana", doi="10.9999/sedge.1"
            )
        ],
    )
    before = corpus_size(project)
    summary = resolve_import(project, imp, sources=lookups.sources())
    assert summary.counts[LinkState.RESOLVED] == 1
    assert corpus_size(project) == before
    [event] = events_of_type(project, "import.resolved")
    runs = event.payload["lookup_runs"]
    assert len(runs) == 1  # type: ignore[arg-type]
    assert event.payload["matcher"] == "refmatch"
    purposes = {e.payload["spec"]["purpose"] for e in events_of_type(project, "query.registered")}  # type: ignore[index]
    assert "probe" in purposes


def test_unresolved_listed_not_dropped(
    project: Project, corpus: None, tmp_path: Path, lookups: Lookups
) -> None:
    imp = import_bib(
        project,
        tmp_path,
        [
            bib_entry("a", "Wholly unknown matters here", year=2001, author="Nobody, C"),
            "@misc{b, year={2001}}\n",
        ],
    )
    summary = resolve_import(project, imp, sources=lookups.sources())
    assert summary.counts[LinkState.UNRESOLVED] == 2
    assert record_states(project, imp) == {1: LinkState.UNRESOLVED, 2: LinkState.UNRESOLVED}
    [event] = events_of_type(project, "import.resolved")
    assert [r["reason"] for r in event.payload["resolutions"]] == [  # type: ignore[attr-defined]
        "not-found",
        "no-identifier-no-title",
    ]


def test_fuzzy_and_ambiguous_states(
    project: Project, corpus: None, tmp_path: Path, lookups: Lookups
) -> None:
    imp = import_bib(
        project,
        tmp_path,
        [
            bib_entry("a", "Efficient Reed Transformers v2", year=2021, author="Lee, Bo"),
            bib_entry("b", "Moss growth under filtered light v2", year=2008, author="Ostrander, P"),
        ],
    )
    resolve_import(project, imp, sources=lookups.sources())
    assert record_states(project, imp) == {1: LinkState.UNCONFIRMED, 2: LinkState.AMBIGUOUS}


def test_reresolve_supersedes(
    project: Project, corpus: None, tmp_path: Path, lookups: Lookups
) -> None:
    imp = import_bib(
        project,
        tmp_path,
        [bib_entry("a", "Efficient Reed Transformers v2", year=2021, author="Lee, Bo")],
    )
    resolve_import(project, imp, sources=Lookups().sources())
    assert record_states(project, imp) == {1: LinkState.UNRESOLVED}
    resolve_import(project, imp, sources=lookups.sources())
    assert record_states(project, imp) == {1: LinkState.UNCONFIRMED}
    assert len(events_of_type(project, "import.resolved")) == 2
    before = project.index.state_hash()
    assert project.index.rebuild() == before


def test_unknown_import_writes_nothing(project: Project) -> None:
    with pytest.raises(FactoryValidationError):
        resolve_import(project, "imp_" + "0" * 26, sources=Lookups().sources())
    assert events_of_type(project, "import.resolved") == []


def test_agent_actor_is_recorded(project: Project, agent: Actor, tmp_path: Path) -> None:
    imp = import_bib(
        project, tmp_path, [bib_entry("a", "Made-Up Pears", year=2019, author="Quill, Ada")]
    )
    resolve_import(project, imp, sources=Lookups().sources(), actor=agent)
    [event] = events_of_type(project, "import.resolved")
    assert event.actor.kind == "agent"

"""G1 reference view for the contribution checks (plan G2-B, task 1)."""

# ruff: noqa: F811

import pytest

from factory.events.envelope import Actor
from factory.lineage.refs import EntryView, ReferenceView
from factory.model.extraction import EntryBrief
from factory.model.references import Confidence, Decision, LinkState
from factory.model.seed import HeldOut
from factory.services import reference_view as rv
from factory.services.context import Project
from factory.services.reference_resolve import decide_reference
from factory.services.reference_view import (
    briefs,
    is_live_reference_extraction,
    reference_view,
    reference_view_of,
)
from factory.services.references import current_extraction
from tests.contribution_helpers import ENTRIES, screened, with_references, world  # noqa: F401
from tests.references_service_helpers import Lookups, oa_item


def test_reference_view_lists_entries_and_contexts(
    project: Project, agent: Actor, world: list[str]
) -> None:
    work = world[0]
    rex = with_references(project, agent, work)
    view = reference_view(project, work)
    assert view is not None
    assert (view.extraction_id, view.work_id) == (rex, work)
    assert [e.ordinal for e in view.entries] == [1, 2, 3, 4, 5, 6]
    assert [e.anchor for e in view.entries] == [f"b{n}" for n in range(1, 7)]
    five = view.entry(5)
    assert five is not None and (five.first_author, five.year) == ("Epsilon", 2020)
    assert view.entry(9) is None
    assert {(c.citing_anchor, c.entry, c.state) for c in view.contexts} == {
        ("s1.p1", 5, "matched"),
        ("s1.p2", 3, "matched"),
    }
    assert reference_view_of(project, rex) == view
    assert is_live_reference_extraction(project, rex)


def test_reference_view_folds_decisions(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    work = world[0]
    lookups = Lookups(openalex=[oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501")])
    entries = [ENTRIES[0], "B. Lee. Efficient reed transformers v2. Reed Conference, 2021."]
    rex = with_references(project, agent, work, entries=entries, sources=lookups.sources())
    before = reference_view(project, work)
    assert before is not None
    entry = before.entry(2)
    assert entry is not None and entry.link_state == LinkState.UNCONFIRMED
    decide_reference(
        project,
        human,
        rex,
        2,
        Decision.CONFIRM,
        rationale="Same paper; the entry adds a version suffix.",
        quotes=("Efficient reed transformers v2", "Efficient Reed Transformers"),
    )
    view = reference_view(project, work)
    assert view is not None
    entry = view.entry(2)
    assert entry is not None
    assert entry.link_state == LinkState.RESOLVED and entry.confidence == Confidence.CONFIRMED
    assert entry.link_work is not None
    unresolved = view.entry(1)
    assert unresolved is not None
    assert unresolved.link_state == LinkState.UNRESOLVED
    assert unresolved.link_work is None and unresolved.confidence is None


def test_reference_view_none_without_extraction(project: Project, world: list[str]) -> None:
    assert reference_view(project, world[0]) is None
    assert reference_view_of(project, "rex_01JZ9Q3K5M7N8P0R2S4T6V8W0X") is None
    assert not is_live_reference_extraction(project, "rex_01JZ9Q3K5M7N8P0R2S4T6V8W0X")


def test_replaced_extraction_is_readable_but_not_live(
    project: Project, agent: Actor, world: list[str]
) -> None:
    work = world[0]
    first = with_references(project, agent, work)
    second = with_references(project, agent, work, version="v4")
    assert second == current_extraction(project, work) != first
    assert not is_live_reference_extraction(project, first)
    assert reference_view_of(project, first) is not None
    live = reference_view(project, work)
    assert live is not None and live.extraction_id == second


def test_reference_view_reads_index_only(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    work = world[0]
    with_references(project, agent, work)

    def boom(*_a: object, **_k: object) -> object:
        raise AssertionError("the view must not read documents")

    monkeypatch.setattr("factory.services.reference_resolve.entry_text", boom, raising=False)
    monkeypatch.setattr(rv, "conversion_manifest", boom, raising=False)
    view = reference_view(project, work)
    assert view is not None and len(view.entries) == 6


def test_briefs_carry_metadata_only(project: Project, agent: Actor, world: list[str]) -> None:
    work = world[0]
    with_references(project, agent, work)
    view = reference_view(project, work)
    assert view is not None
    assert set(EntryBrief.model_fields) == {
        "ordinal",
        "anchor",
        "label",
        "title",
        "first_author",
        "year",
        "doi",
        "arxiv",
    }
    listed = briefs(view)
    assert [b.ordinal for b in listed] == [1, 2, 3, 4, 5, 6]
    assert listed[4].title == "Linear attention with kernels"


def test_briefs_mask_entries_linked_to_held_out_works(
    project: Project, agent: Actor, world: list[str]
) -> None:
    work = world[0]
    entries = [
        *ENTRIES[:2],
        "A. Zhou. Paper 2. Journal of Tests, 2020. doi:10.1000/p2.",
        *ENTRIES[3:],
    ]
    with_references(project, agent, work, entries=entries)
    view = reference_view(project, work)
    assert view is not None
    linked = view.entry(3)
    assert linked is not None and linked.link_state == LinkState.RESOLVED
    assert linked.link_work is not None
    listed = briefs(view, HeldOut(work_ids=frozenset({linked.link_work})))
    masked = listed[2]
    assert masked.ordinal == 3 and masked.anchor == "b3"
    assert (masked.title, masked.doi, masked.arxiv) == (None, None, None)
    assert (masked.first_author, masked.year) == ("Zhou", 2020)  # as G1's `_masked`
    assert listed[4].title == "Linear attention with kernels"


def test_masked_brief_has_the_shape_of_a_genuine_bare_entry(
    project: Project, agent: Actor, world: list[str]
) -> None:  # decision 37 item 9: nothing marks the seed
    work = world[0]
    entries = [
        *ENTRIES[:2],
        "A. Zhou. A held paper. Journal of Tests, 2020. doi:10.1000/p2.",
        *ENTRIES[3:5],
        "Smith, J. 2020.",
    ]
    with_references(project, agent, work, entries=entries)
    view = reference_view(project, work)
    assert view is not None
    linked = view.entry(3)
    assert linked is not None and linked.link_work is not None
    listed = briefs(view, HeldOut(work_ids=frozenset({linked.link_work})))

    def shape(brief: object) -> tuple[bool, ...]:
        return tuple(
            getattr(brief, f) is None for f in ("title", "first_author", "year", "doi", "arxiv")
        )

    genuine = listed[5]
    assert (genuine.first_author, genuine.year) == ("Smith", 2020)
    assert shape(listed[2]) == shape(genuine)


def _entry(**link: object) -> EntryView:
    return EntryView(
        ordinal=1,
        anchor="b1",
        label=None,
        title="T",
        first_author="A",
        year=2020,
        doi=None,
        arxiv=None,
        link_state=LinkState.UNRESOLVED,
        link_work=None,
        confidence=None,
        **link,  # type: ignore[arg-type]
    )


def test_briefs_mask_rejected_and_candidate_held_out_links() -> None:
    held = HeldOut(work_ids=frozenset({"rf:secret"}))
    for link in (
        {"base_work": "rf:secret"},  # a rejected link keeps its base work
        {"candidate_works": ("rf:other", "rf:secret")},  # an ambiguous link's candidate
    ):
        view = ReferenceView("rex_x", "rf:w", "cnv_x", (_entry(**link),), ())
        (brief,) = briefs(view, held)
        assert brief.title is None, link
    view = ReferenceView("rex_x", "rf:w", "cnv_x", (_entry(base_work="rf:fine"),), ())
    assert briefs(view, held)[0].title == "T"

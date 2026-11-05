# ruff: noqa: F401, F811
"""Reversible concept merge and unmerge (slice 3c, plan G3-B, task 5)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.model.intuition import ConceptInput, LinkStatus, UseBasisInput
from factory.model.screening import Channel
from factory.services.concepts import (
    concept_view,
    decide_concept_link,
    define_concept,
    effective_concept,
    list_concept_links,
    list_concepts,
    merge_concepts,
    propose_concept_link,
    review_concept,
    unmerge_concepts,
)
from factory.services.context import Project
from tests.intuition_helpers import (
    IWorld,
    ctr_a,
    ctr_b,
    iw,
    lin,
    reviewer,
    rows,
    screened,
    world,
)

TEXTBOOK = {"kind": "textbook", "citation": "Textbook, chapter 3"}
ALL = list(LinkStatus)
TABLES = ("concepts", "concept_aliases", "concept_uses", "layer_nodes", "layer_edges")


def make(project: Project, iw: IWorld, name: str, aliases: tuple[str, ...] = ()) -> str:
    entry = ConceptInput.model_validate({"name": name, "aliases": aliases, "source": TEXTBOOK})
    return define_concept(project, iw.human, entry, approve_source=True)


def basis(**kw: Any) -> UseBasisInput:
    return UseBasisInput.model_validate(kw)


def link(project: Project, iw: IWorld, source: str, target: str) -> str:
    return propose_concept_link(project, iw.writer, source, target, basis(), note="n").link_id


def _refuse(call: Callable[[], object], field: str, reason: str | None = None) -> Any:
    with pytest.raises(FactoryValidationError) as e:
        call()
    assert e.value.issues[0].field == field, e.value.issues
    if reason is not None:
        assert e.value.issues[0].reason == reason, e.value.issues
    return e.value


def _dump(project: Project) -> dict[str, list[tuple[object, ...]]]:
    return {t: rows(project, f"SELECT * FROM {t} ORDER BY 1, 2") for t in TABLES}


def _events(project: Project) -> int:
    return len(
        rows(project, "SELECT 1 FROM events WHERE type IN ('concept.merged', 'concept.unmerged')")
    )


def test_merge_unions_aliases_and_repoints_links(project: Project, iw: IWorld) -> None:
    c1 = make(project, iw, "kernel")
    c2 = make(project, iw, "random features", ("RFF",))
    uses = propose_concept_link(
        project,
        iw.writer,
        iw.source,
        c2,
        basis(quote=iw.quote("s1.p2", "Unlike softmax attention")),
    )
    assert uses.status == "inferred"
    merge_concepts(project, iw.human, c1, c2, "same idea")
    assert effective_concept(project, c2) == c1 and effective_concept(project, c1) == c1
    view = concept_view(project, c2)
    assert view is not None and view.merged_into == c1 and not view.visible
    assert view.review_state == "merged" and view.label == "interpretation · merged"
    assert [v.concept_id for v in list_concepts(project).items] == [c1]
    assert list_concepts(project).hidden.merged == 1
    [shown] = list_concept_links(project, statuses=ALL, concept_id=c1).items
    assert (shown.link_id, shown.concept_id, shown.raw_concept_id) == (uses.link_id, c1, c2)
    assert rows(project, "SELECT source, target FROM layer_edges") == [(iw.source, c1)]
    # the merged concept's name gains the survivor: a quote naming it states a link to c1
    named = propose_concept_link(
        project,
        iw.writer,
        iw.source,
        c1,
        basis(quote=iw.quote("s1.p1", "We build on linear attention")),
    )
    assert named.status_reason == "name-not-in-quote"


def test_merged_concept_names_state_links_to_the_survivor(project: Project, iw: IWorld) -> None:
    c1 = make(project, iw, "kernel")
    c2 = make(project, iw, "linear attention")
    merge_concepts(project, iw.human, c1, c2, "same idea")
    r = propose_concept_link(
        project,
        iw.writer,
        iw.source,
        c1,
        basis(quote=iw.quote("s1.p1", "We build on linear attention")),
    )
    assert (r.status, r.status_reason) == ("stated", "name-in-quote")


def test_merged_concept_target_refused_with_into(project: Project, iw: IWorld) -> None:
    c1, c2 = make(project, iw, "kernel"), make(project, iw, "random features")
    merge_concepts(project, iw.human, c1, c2, "same idea")
    _refuse(
        lambda: propose_concept_link(project, iw.writer, iw.source, c2, basis(), note="n"),
        "concept_id",
        f"merged:{c1}",
    )
    _refuse(
        lambda: propose_concept_link(project, iw.writer, c2, c1, basis(), note="n"),
        "from_node",
        f"merged:{c1}",
    )


def test_alias_collision_through_merge_and_after_unmerge(
    project: Project, iw: IWorld
) -> None:  # Review Focus 1
    c1 = make(project, iw, "kernel")
    c2 = make(project, iw, "random features", ("RFF",))

    def define(name: str) -> Any:
        return lambda: define_concept(
            project, iw.writer, ConceptInput.model_validate({"name": name})
        )

    merge_concepts(project, iw.human, c1, c2, "same idea")
    err = _refuse(define("RFF"), "name")
    assert err.issues[0].reason == f"concept-exists:{c1}"
    _refuse(define("Random Features"), "name", f"concept-exists:{c1}")
    unmerge_concepts(project, iw.human, c1, c2, "not the same after all")
    err = _refuse(define("RFF"), "name")
    assert err.issues[0].reason == f"concept-exists:{c2}"
    # a name that only the survivor's own names covered is free again after the unmerge
    assert define("completely new")()


def test_merge_unmerge_restores_projection_exactly(project: Project, iw: IWorld) -> None:
    c1 = make(project, iw, "kernel")
    c2 = make(project, iw, "random features", ("RFF",))
    link(project, iw, c2, c1) if False else None
    propose_concept_link(project, iw.writer, iw.source, c2, basis(), note="n")
    link(project, iw, iw.idea1, c1)
    before = _dump(project)
    merge_concepts(project, iw.human, c1, c2, "same idea")
    assert _dump(project) != before
    unmerge_concepts(project, iw.human, c1, c2, "split")
    assert _dump(project) == before  # acceptance 11
    again = merge_concepts(project, iw.human, c1, c2, "again")
    assert again


def test_self_link_merge_refused(project: Project, iw: IWorld) -> None:  # Review Focus 5
    c1, c2 = make(project, iw, "kernel"), make(project, iw, "random features")
    link(project, iw, c2, c1)
    _refuse(lambda: merge_concepts(project, iw.human, c1, c2, "x"), "from_concept", "self-link")
    _refuse(lambda: merge_concepts(project, iw.human, c2, c1, "x"), "from_concept", "self-link")
    assert _events(project) == 0


def test_merge_creating_cycle_refused(project: Project, iw: IWorld) -> None:
    c1, c2, c3 = (make(project, iw, n) for n in ("kernel", "random features", "map"))
    link(project, iw, c2, c3)
    link(project, iw, c3, c1)
    _refuse(lambda: merge_concepts(project, iw.human, c1, c2, "x"), "from_concept", "cycle")
    _refuse(lambda: merge_concepts(project, iw.human, c2, c1, "x"), "from_concept", "cycle")
    # a rejected link does not count
    [(first,)] = rows(project, f"SELECT link_id FROM concept_uses WHERE from_node = '{c2}'")
    decide_concept_link(project, iw.human, str(first), "reject", "no", Channel.CLI)
    assert merge_concepts(project, iw.human, c1, c2, "ok")


def test_chain_merges_and_bad_pairs_refused(project: Project, iw: IWorld) -> None:
    c1, c2, c3 = (make(project, iw, n) for n in ("kernel", "random features", "map"))
    merge_concepts(project, iw.human, c1, c2, "same idea")
    _refuse(
        lambda: merge_concepts(project, iw.human, c3, c1, "x"),
        "from_concept",
        "has-merged-concepts",
    )
    _refuse(lambda: merge_concepts(project, iw.human, c3, c2, "x"), "from_concept", f"merged:{c1}")
    _refuse(lambda: merge_concepts(project, iw.human, c2, c3, "x"), "into", f"merged:{c1}")
    _refuse(lambda: merge_concepts(project, iw.human, c3, c3, "x"), "from_concept", "same-concept")
    ghost = "cpt_01HZX3K4M5N6P7Q8R9S0T1V2WZ"
    _refuse(lambda: merge_concepts(project, iw.human, ghost, c3, "x"), "into", "concept-unknown")
    _refuse(
        lambda: merge_concepts(project, iw.human, c3, ghost, "x"), "from_concept", "concept-unknown"
    )
    _refuse(
        lambda: merge_concepts(project, iw.human, c3, make(project, iw, "spare"), " "), "reason"
    )
    assert _events(project) == 1


def test_unmerge_without_merge_refused(project: Project, iw: IWorld) -> None:
    c1, c2, c3 = (make(project, iw, n) for n in ("kernel", "random features", "map"))
    _refuse(lambda: unmerge_concepts(project, iw.human, c1, c2, "x"), "from_concept", "not-merged")
    merge_concepts(project, iw.human, c1, c2, "same idea")
    _refuse(lambda: unmerge_concepts(project, iw.human, c3, c2, "x"), "from_concept", "not-merged")
    unmerge_concepts(project, iw.human, c1, c2, "split")
    _refuse(lambda: unmerge_concepts(project, iw.human, c1, c2, "x"), "from_concept", "not-merged")
    assert effective_concept(project, c2) == c2


def test_agent_cannot_merge_or_unmerge(project: Project, iw: IWorld) -> None:
    c1, c2 = make(project, iw, "kernel"), make(project, iw, "random features")
    _refuse(lambda: merge_concepts(project, iw.writer, c1, c2, "x"), "actor")
    merge_concepts(project, iw.human, c1, c2, "same idea")
    _refuse(lambda: unmerge_concepts(project, iw.writer, c1, c2, "x"), "actor")
    assert _events(project) == 1


def test_merged_concept_cannot_be_reviewed_or_redefined(project: Project, iw: IWorld) -> None:
    c1, c2 = make(project, iw, "kernel"), make(project, iw, "random features")
    merge_concepts(project, iw.human, c1, c2, "same idea")
    _refuse(
        lambda: review_concept(project, iw.human, c2, "reviewed", "", Channel.CLI),
        "concept_id",
        f"merged:{c1}",
    )

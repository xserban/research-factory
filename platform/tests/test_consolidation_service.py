# ruff: noqa: F401, F811
"""Consolidation passes, proposals and human merge decisions (slice 3d, plan Regions-C, task 3)."""

from __future__ import annotations

import random
import string
from dataclasses import dataclass
from typing import Any

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.intuition import ConceptInput
from factory.model.labels import LabelMerged
from factory.model.lineage import IdeaMerged, LineageDecision
from factory.regions.rules import MemberType
from factory.services.concepts import define_concept, unmerge_concepts
from factory.services.consolidation import (
    CONSOLIDATION_DUE_LABELS,
    CONSOLIDATION_DUE_NODES,
    candidate_clusters,
    complete_pass,
    consolidation_due,
    consolidation_next,
    decide_cluster,
    list_clusters,
    propose,
    start_pass,
)
from factory.services.context import Project
from factory.services.ideas import decide_idea, propose_idea, unmerge_idea
from factory.services.labels import (
    LabelInput,
    apply_labels,
    list_labels,
    merge_labels,
    unmerge_labels,
)
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, rows, screened, world

TEXTBOOK = {"kind": "textbook", "citation": "Textbook, chapter 3"}
TABLES = (
    "labels",
    "ideas",
    "idea_members",
    "concepts",
    "concept_aliases",
    "concept_uses",
    "graph_nodes",
    "graph_edges",
    "layer_nodes",
    "layer_edges",
)


def dump(project: Project) -> dict[str, list[tuple[Any, ...]]]:
    return {t: rows(project, f"SELECT * FROM {t} ORDER BY 1, 2") for t in TABLES}


def label(project: Project, human: Actor, text: str, *targets: str) -> None:
    items = [LabelInput(target_type=MemberType.WORK, target=t, text=text) for t in targets]
    out = apply_labels(project, human, items)
    assert not out.rejected, out.rejected


def concept(project: Project, human: Actor, name: str) -> str:
    entry = ConceptInput.model_validate({"name": name, "aliases": (), "source": TEXTBOOK})
    return define_concept(project, human, entry, approve_source=True)


def events_of(project: Project, *types: str) -> list[Any]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type in types]


@dataclass
class CW:
    w: IWorld
    project: Project
    twin: str


@pytest.fixture
def cw(iw: IWorld, project: Project) -> CW:
    """`iw` with a second idea and concept near-duplicating its first, and two overlapping
    labels (names that string similarity cannot link)."""
    twin = propose_idea(project, iw.writer, "Linear Attention", iw.source, iw.lin.base, [iw.source])
    decide_idea(project, iw.human, twin, LineageDecision.CONFIRM, "checked")
    concept(project, iw.human, "random features")
    concept(project, iw.human, "random-features")
    label(project, iw.human, "Performer", iw.source, iw.other, iw.third)
    label(project, iw.human, "FAVOR+", iw.source, iw.other, iw.third)
    return CW(iw, project, twin)


def first(project: Project, kind: str) -> tuple[str, int, Any]:
    pass_id = start_pass(project, project.human_actor())
    [row] = [c for c in list_clusters(project, pass_id) if c.kind == kind]
    return pass_id, row.index, row


def test_clusters_name_signals_and_are_identical_across_runs(cw: CW) -> None:
    one, two = candidate_clusters(cw.project), candidate_clusters(cw.project)
    assert one == two
    assert [c.kind for c in one] == ["label", "idea", "concept"]
    [lab] = [c for c in one if c.kind == "label"]
    assert lab.members == ("favor+", "performer")
    assert all(p.signals for c in one for p in c.pairs)


@pytest.mark.parametrize("kind", ["label", "idea", "concept"])
def test_merge_unmerge_restores_state_hash(cw: CW, kind: str) -> None:
    project = cw.project
    before = dump(project)
    pass_id, index, row = first(project, kind)
    decide_cluster(
        project,
        cw.w.human,
        pass_id,
        index,
        "merge",
        into=row.members[0],
        merge_from=[row.members[1]],
        reason="same",
    )
    if kind == "label":
        assert any(v.key != v.live_key for v in list_labels(project))
        [event] = events_of(project, "label.merged")
        unmerge_labels(project, cw.w.human, event.id, "undo")
    elif kind == "idea":
        [event] = events_of(project, "idea.merged")
        unmerge_idea(project, cw.w.human, event.payload["from_idea"], "undo")
    else:
        [event] = events_of(project, "concept.merged")
        unmerge_concepts(
            project, cw.w.human, event.payload["into"], event.payload["from_concept"], "undo"
        )
    assert dump(project) == before


def test_decision_and_merges_in_one_append_and_reference_proposal(cw: CW) -> None:
    project = cw.project
    pass_id, index, row = first(project, "label")
    task = consolidation_next(project, cw.w.writer)
    assert task is not None and task.kind == "label"
    proposal = propose(
        project,
        cw.w.writer,
        task.task_id,
        action="merge",
        into=row.members[0],
        members=row.members,
        reason="same method under two names",
    )
    decide_cluster(
        project,
        cw.w.human,
        pass_id,
        index,
        "merge",
        into=row.members[0],
        reason="agreed",
        proposal_id=proposal,
    )
    [merged] = events_of(project, "label.merged")
    [decided] = events_of(project, "consolidation.decided")
    assert merged.payload["proposal_id"] == proposal
    assert decided.payload["merge_events"] == [merged.id]
    assert decided.payload["proposal_id"] == proposal
    log = [e.type for e in read_all(project.paths.events_dir, project.catalog)]
    assert log[-2:] == ["label.merged", "consolidation.decided"]
    [shown] = [c for c in list_clusters(project, pass_id) if c.index == index]
    assert shown.decision == "merge" and shown.proposal_ids == [proposal]


@pytest.mark.parametrize(
    ("kind", "event_type"), [("idea", "idea.merged"), ("concept", "concept.merged")]
)
def test_idea_and_concept_merges_carry_the_proposal(cw: CW, kind: str, event_type: str) -> None:
    project = cw.project
    pass_id, index, row = first(project, kind)
    task = consolidation_next(project, cw.w.writer)
    while task is not None and task.kind != kind:
        task = consolidation_next(project, cw.w.writer)
    assert task is not None
    proposal = propose(
        project,
        cw.w.writer,
        task.task_id,
        action="merge",
        into=row.members[0],
        members=row.members,
        reason="duplicates",
    )
    decide_cluster(
        project,
        cw.w.human,
        pass_id,
        index,
        "merge",
        into=row.members[0],
        merge_from=[row.members[1]],
        reason="r",
        proposal_id=proposal,
    )
    [event] = events_of(project, event_type)
    assert event.payload["proposal"] == proposal


def test_agent_cannot_decide(cw: CW) -> None:
    pass_id, index, row = first(cw.project, "label")
    with pytest.raises(FactoryValidationError) as caught:
        decide_cluster(
            cw.project, cw.w.writer, pass_id, index, "merge", into=row.members[0], reason="r"
        )
    assert caught.value.issues[0].field == "actor"
    assert not events_of(cw.project, "label.merged", "consolidation.decided")


def test_proposer_session_cannot_decide(cw: CW) -> None:
    pass_id, index, row = first(cw.project, "label")
    task = consolidation_next(cw.project, cw.w.writer)
    assert task is not None
    proposal = propose(
        cw.project, cw.w.writer, task.task_id, action="keep", members=row.members, reason="r"
    )
    same_session = cw.w.human.model_copy(update={"session": cw.w.writer.session})
    with pytest.raises(FactoryValidationError) as caught:
        decide_cluster(
            cw.project, same_session, pass_id, index, "keep", reason="r", proposal_id=proposal
        )
    assert "session" in [i.field for i in caught.value.issues]


def test_proposal_validation(cw: CW) -> None:
    _, _, row = first(cw.project, "label")
    task = consolidation_next(cw.project, cw.w.writer)
    assert task is not None
    with pytest.raises(FactoryValidationError) as caught:
        propose(
            cw.project,
            cw.w.writer,
            task.task_id,
            action="merge",
            into="elsewhere",
            members=("elsewhere", row.members[0]),
            reason="r",
        )
    assert "members" in {i.field for i in caught.value.issues}
    with pytest.raises(FactoryValidationError) as human:
        propose(
            cw.project, cw.w.human, task.task_id, action="keep", members=row.members, reason="r"
        )
    assert human.value.issues[0].field == "actor"
    assert not events_of(cw.project, "consolidation.proposed")


def test_pass_completes_when_all_decided(cw: CW) -> None:
    project, human = cw.project, cw.w.human
    pass_id = start_pass(project, human)
    listed = list_clusters(project, pass_id)
    assert len(listed) == 3
    with pytest.raises(FactoryValidationError) as caught:
        complete_pass(project, human, pass_id)
    assert caught.value.issues[0].reason == "undecided:3"
    decide_cluster(project, human, pass_id, listed[0].index, "keep", reason="distinct")
    decide_cluster(project, human, pass_id, listed[1].index, "split", reason="distinct")
    decide_cluster(project, human, pass_id, listed[2].index, "skip", reason="later")
    with pytest.raises(FactoryValidationError) as twice:
        decide_cluster(project, human, pass_id, listed[2].index, "keep", reason="again")
    assert twice.value.issues[0].reason == "already-decided"
    complete_pass(project, human, pass_id)
    assert start_pass(project, human).startswith("cns_")


def test_only_one_pass_open(cw: CW) -> None:
    start_pass(cw.project, cw.w.human)
    with pytest.raises(FactoryValidationError) as caught:
        start_pass(cw.project, cw.w.human)
    assert caught.value.issues[0].reason == "pass-open"


def test_due_counts_reset_on_completion(iw: IWorld, project: Project) -> None:
    rng = random.Random(3)
    keys = sorted({"".join(rng.choices(string.ascii_lowercase, k=11)) for _ in range(80)})
    assert consolidation_due(project).due is False
    for k in keys[:CONSOLIDATION_DUE_LABELS]:
        label(project, iw.human, k, iw.source)
    state = consolidation_due(project)
    assert (state.new_label_keys, state.due) == (CONSOLIDATION_DUE_LABELS, False)
    label(project, iw.human, keys[CONSOLIDATION_DUE_LABELS], iw.source)
    assert consolidation_due(project).due is True
    pass_id = start_pass(project, iw.human)
    for cluster in list_clusters(project, pass_id):
        decide_cluster(project, iw.human, pass_id, cluster.index, "keep", reason="distinct")
    complete_pass(project, iw.human, pass_id)
    after = consolidation_due(project)
    assert (after.new_label_keys, after.new_nodes, after.due) == (0, 0, False)


def test_due_counts_new_nodes(cw: CW) -> None:
    project, human = cw.project, cw.w.human
    pass_id = start_pass(project, human)
    for cluster in list_clusters(project, pass_id):
        decide_cluster(project, human, pass_id, cluster.index, "keep", reason="r")
    complete_pass(project, human, pass_id)
    for n in range(CONSOLIDATION_DUE_NODES):
        concept(project, human, f"unrelated notion {chr(97 + n) * 7}")
    assert consolidation_due(project).due is False
    concept(project, human, "one more notion zzzzzzz")
    assert consolidation_due(project).due is True


def test_label_merge_cycle_refused(cw: CW) -> None:
    project, human = cw.project, cw.w.human
    merge_labels(project, human, "performer", "favor+", "same")
    with pytest.raises(FactoryValidationError) as caught:
        merge_labels(project, human, "favor+", "performer", "back")
    assert caught.value.issues[0].reason == "merge-cycle"
    with pytest.raises(FactoryValidationError) as again:
        merge_labels(project, human, "performer", "favor+", "twice")
    assert again.value.issues[0].reason == "already-merged"


def test_old_idea_merge_events_replay_identically(cw: CW) -> None:
    project = cw.project
    event = project.events.make(
        "idea.merged", IdeaMerged(from_idea=cw.twin, into=cw.w.idea1, reason="old"), cw.w.human
    )
    old = event.model_copy(
        update={"payload": {k: v for k, v in event.payload.items() if k != "proposal"}}
    )
    project.writer.append([old])
    project.index.sync()
    found = rows(project, f"SELECT merged_into FROM ideas WHERE idea_id = '{cw.twin}'")
    assert found == [(cw.w.idea1,)]


def test_duplicate_merge_from_refused_and_a_logged_duplicate_rebuilds(cw: CW) -> None:
    project = cw.project
    pass_id, index, row = first(project, "label")
    with pytest.raises(FactoryValidationError) as caught:
        decide_cluster(
            project,
            cw.w.human,
            pass_id,
            index,
            "merge",
            into=row.members[0],
            merge_from=[row.members[1], row.members[1]],
            reason="same",
        )
    assert caught.value.issues[0].field == "merge_from"
    assert not events_of(project, "label.merged", "consolidation.decided")
    # a hand-written log with two merges of one key still folds and rebuilds
    one = merge_labels(project, cw.w.human, row.members[0], row.members[1], "same")
    twin = next(e for e in events_of(project, "label.merged") if e.id == one)
    again = twin.model_copy(
        update={
            "id": project.events.make("label.merged", LabelMerged(**twin.payload), cw.w.human).id
        }
    )
    project.writer.append([again])
    project.index.sync()
    state = project.index.rebuild()
    assert project.index.rebuild() == state


def test_concept_batch_merge_is_validated_cumulatively(cw: CW) -> None:
    from factory.model.intuition import UseBasisInput
    from factory.services.concepts import propose_concept_link

    project, human = cw.project, cw.w.human
    a = concept(project, human, "gradient flow")
    b = concept(project, human, "gradient-flow")
    c = concept(project, human, "gradient flows")
    propose_concept_link(project, cw.w.writer, b, c, UseBasisInput(), note="builds on")
    pass_id = start_pass(project, human)
    [row] = [
        r
        for r in list_clusters(project, pass_id)
        if r.kind == "concept" and {a, b, c} <= set(r.members)
    ]
    with pytest.raises(FactoryValidationError) as caught:
        decide_cluster(
            project, human, pass_id, row.index, "merge", into=a, merge_from=[b, c], reason="same"
        )
    assert caught.value.issues[0].reason == "self-link"
    assert not events_of(project, "concept.merged", "consolidation.decided")


def test_decided_clusters_and_completed_passes_serve_no_task(cw: CW) -> None:
    project, human = cw.project, cw.w.human
    pass_id = start_pass(project, human)
    rows_ = list_clusters(project, pass_id)
    decide_cluster(project, human, pass_id, rows_[0].index, "keep", reason="distinct")
    served = []
    while (task := consolidation_next(project, cw.w.writer)) is not None:
        served.append(task.cluster_index)
    assert rows_[0].index not in served and set(served) == {r.index for r in rows_[1:]}
    for r in rows_[1:]:
        decide_cluster(project, human, pass_id, r.index, "skip", reason="later")
    complete_pass(project, human, pass_id)
    other = cw.w.writer.model_copy(update={"session": "01JZ9Q3K5M7N8P0R2S4T6V8W9Z"})
    assert consolidation_next(project, other) is None


def test_proposal_for_a_decided_cluster_refused(cw: CW) -> None:
    project, human = cw.project, cw.w.human
    pass_id, index, row = first(project, "label")
    task = consolidation_next(project, cw.w.writer)
    while task is not None and task.kind != "label":
        task = consolidation_next(project, cw.w.writer)
    assert task is not None
    decide_cluster(project, human, pass_id, index, "keep", reason="distinct")
    with pytest.raises(FactoryValidationError) as caught:
        propose(project, cw.w.writer, task.task_id, action="keep", members=row.members, reason="r")
    assert caught.value.issues[0].reason == "cluster-decided"

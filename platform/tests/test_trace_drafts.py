"""`trace` from and to sentences (slice 7b, plan W-B, task 6; acceptance 15)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Iterator

import pytest

from factory.errors import FactoryValidationError
from factory.model.intuition import ReviewState
from factory.services import supports as supports_mod
from factory.services.context import Project
from factory.services.drafts import write_sentences
from factory.services.trace import KINDS, TraceNode, agent_trace, dangling_refs, trace
from factory.services.write_rows import visible_rows_by_group
from tests.draft_b_helpers import (
    CLAIM,
    INTERP,
    SYNTH,
    Written,
    ctr_a,
    ctr_b,
    ext_a,
    ext_b,
    screened,
    sent,
    verify_all,
    verify_one,
    wd,
    writer,
    ww,
)
from tests.writing_helpers import WWorld


def walk(node: TraceNode) -> Iterator[TraceNode]:
    yield node
    for child in node.children:
        yield from walk(child)


def kinds(node: TraceNode) -> set[str]:
    return {n.kind for n in walk(node)}


def one_sentence(project: Project, wd: Written, cls: object, body: str, support: str) -> str:
    done = write_sentences(
        project, wd.draft, [sent(wd.section, cls, body, support)], actor=writer()
    )  # type: ignore[arg-type]
    assert not done.rejected
    return done.written[0]


@pytest.mark.parametrize(
    "support",
    ["claim", "cell", "item", "edge", "group"],
)
def test_trace_sentence_to_question_for_each_support_kind(
    project: Project, ww: WWorld, wd: Written, support: str
) -> None:
    grammar = {
        "claim": ww.claim(0),
        "cell": ww.cell(0),
        "item": f"item:{ww.base_item}",
        "edge": f"edge:{ww.confirmed_edge}",
        "group": f"group:{sorted(visible_rows_by_group(project).groups)[0]}",
    }[support]
    cls = SYNTH if support == "group" else CLAIM
    sentence = one_sentence(project, wd, cls, "Lorem is stated here", grammar)
    tree = trace(project, sentence)
    assert tree.kind == "sentence" and tree.event_id
    found = kinds(tree)
    assert "question" in found, support


def test_interpretation_support_is_reached(
    project: Project, wd: Written, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(supports_mod, "interpretation_state", lambda _p, _i: ReviewState.REVIEWED)
    interp = "int_01JZ9Q3K5M7N8P0R2S4T6V8W00"
    sentence = one_sentence(project, wd, INTERP, "This reads as a family", f"interp:{interp}")
    assert interp in {n.id for n in walk(trace(project, sentence))}


def test_forward_from_claim_lists_sentences(project: Project, ww: WWorld, wd: Written) -> None:
    verify_all(project, wd.draft)
    tree = trace(project, ww.claims[ww.works[0]], direction="forward")
    ids = {n.id for n in walk(tree)}
    assert wd.first in ids and wd.draft in ids and wd.second not in ids
    assert "verdict" in kinds(tree)


def test_forward_from_cell_item_and_edge(project: Project, ww: WWorld, wd: Written) -> None:
    cell = one_sentence(project, wd, CLAIM, "The value is stated", ww.cell(0))
    item = one_sentence(project, wd, CLAIM, "The base is stated", f"item:{ww.base_item}")
    edge = one_sentence(project, wd, CLAIM, "It is built on", f"edge:{ww.confirmed_edge}")
    row = ww.rows[ww.works[0]]
    assert cell in {n.id for n in walk(trace(project, f"{row}/value", direction="forward"))}
    assert cell in {n.id for n in walk(trace(project, row, direction="forward"))}
    assert item in {n.id for n in walk(trace(project, ww.base_item, direction="forward"))}
    assert edge in {n.id for n in walk(trace(project, ww.confirmed_edge, direction="forward"))}


def test_stat_support_is_leaf(project: Project, wd: Written) -> None:
    sentence = one_sentence(
        project, wd, SYNTH, "One idea is confirmed in total", "stat:ideas-confirmed"
    )
    tree = trace(project, sentence)
    [stat] = [n for n in walk(tree) if n.kind == "stat"]
    assert stat.id == "stat:ideas-confirmed" and stat.children == [] and stat.event_id


def test_trace_from_verdict_and_draft(project: Project, wd: Written) -> None:
    verify_one(project, wd.draft)
    tree = trace(project, wd.first, direction="forward")
    [verdict] = [n for n in walk(tree) if n.kind == "verdict"]
    assert verdict.label == "verdict supported"
    back = trace(project, verdict.id)
    assert wd.first in {n.id for n in walk(back)} and "question" in kinds(back)
    assert wd.first in {n.id for n in walk(trace(project, wd.draft))}


def test_supersession_is_followed(project: Project, ww: WWorld, wd: Written) -> None:
    done = write_sentences(
        project,
        wd.draft,
        [sent(wd.section, CLAIM, "Lorem is stated", ww.claim(0), supersedes=wd.first)],
        actor=writer(),
    )
    assert wd.first in {n.id for n in walk(trace(project, done.written[0]))}
    assert done.written[0] in {n.id for n in walk(trace(project, wd.first, direction="forward"))}


def test_unknown_ids_are_refused_and_dangle(project: Project, wd: Written) -> None:
    absent = "snt_01JZ9Q3K5M7N8P0R2S4T6V8W99"
    with pytest.raises(FactoryValidationError):
        trace(project, absent)
    assert dangling_refs(project, [absent, wd.first, wd.draft]) == [absent]


def test_agent_trace_reads_a_sentence(project: Project, ww: WWorld, wd: Written) -> None:
    verify_all(project, wd.draft)
    tree = agent_trace(project, wd.first)
    assert tree.kind == "sentence" and "claim" in kinds(tree)
    assert "seed" not in kinds(tree)


def test_kinds_are_ordered_after_the_cell() -> None:
    i = KINDS.index("cell")
    assert KINDS[i + 1 : i + 6] == ("group", "stat", "sentence", "verdict", "draft")

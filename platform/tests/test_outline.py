"""The outline of verified material (slice 7b, plan W-A, task 4; Review Focus 4)."""

# ruff: noqa: F811

from __future__ import annotations

import pytest

import factory.services.outline as outline_mod
from factory.events.envelope import Actor
from factory.model.drafts import Outline
from factory.model.lineage import RelationProposal
from factory.services.context import Project
from factory.services.outline import OutlineScope, build_outline, outline_json
from factory.services.relations import propose_relation
from tests.contribution_helpers import ctr_a, ctr_b, ext_a, screened  # noqa: F401
from tests.intuition_helpers import record_event, recorded
from tests.views_b_helpers import declare_evidence, ext_b, set_year  # noqa: F401
from tests.writing_helpers import (  # noqa: F401
    WWorld,
    confirmed_edge,
    confirmed_idea,
    item_per_work,
    ww,
)


def section(outline: Outline, ref: str):  # type: ignore[no-untyped-def]
    found = [s for s in outline.sections if s.section_ref == ref]
    assert len(found) == 1, [s.section_ref for s in outline.sections]
    return found[0]


def test_fresh_project_outline_is_empty_with_the_limits_slot(project: Project) -> None:
    out = build_outline(project)
    assert [s.section_ref for s in out.sections] == ["limits"]
    assert "no-extraction" in out.sections[0].notes
    assert out.outline_id.startswith("OL@")
    assert build_outline(project).outline_id == out.outline_id


def test_idea_section_lists_members_items_edges_and_claims(project: Project, ww: WWorld) -> None:
    out = build_outline(project)
    idea = section(out, f"idea:{ww.idea}")
    assert idea.kind == "idea" and idea.title_ref == ww.idea
    assert idea.works[0] == ww.works[0]  # the origin first
    assert set(idea.works) == set(ww.works[:2])
    assert f"item:{ww.base_item}" in idea.supports
    assert f"edge:{ww.confirmed_edge}" in idea.supports
    assert f"edge:{ww.inferred_edge}" not in idea.supports
    assert ww.claim(0) in idea.supports and ww.claim(1) in idea.supports
    assert not any(s.startswith("claim:") and s == ww.claim(2) for s in idea.supports)


@pytest.fixture
def ideas_of(
    project: Project,
    agent: Actor,
    other_session_human: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    screened: list[str],
) -> dict[str, str]:
    """Works 0, 1 and 2 each carry one confirmed one-member idea, made in the order 2, 1, 0, so
    that idea ids (the last tie-break) run against the lineage the tests build."""
    declare_evidence(project, agent, contribution=True)
    works = screened[:3]
    items = item_per_work(project, ctr_a, ctr_b, works)
    return {
        w: confirmed_idea(project, agent, other_session_human, w, items[w]) for w in reversed(works)
    }


def idea_order(project: Project) -> list[str]:
    return [s.title_ref for s in build_outline(project).sections if s.kind == "idea"]


def test_idea_sections_in_lineage_order(
    project: Project,
    agent: Actor,
    other_session_human: Actor,
    screened: list[str],
    ideas_of: dict[str, str],
) -> None:
    a, b, c = screened[:3]
    assert idea_order(project) == [ideas_of[c], ideas_of[b], ideas_of[a]]  # no edge yet: by id
    confirmed_edge(project, agent, other_session_human, b, a, "builds-on")
    confirmed_edge(project, agent, other_session_human, c, b, "improves-on")
    assert idea_order(project) == [ideas_of[a], ideas_of[b], ideas_of[c]]


def test_improves_on_alone_orders_ideas(
    project: Project,
    agent: Actor,
    other_session_human: Actor,
    screened: list[str],
    ideas_of: dict[str, str],
) -> None:
    a, _, c = screened[:3]
    confirmed_edge(project, agent, other_session_human, c, a, "improves-on")
    order = idea_order(project)
    assert order.index(ideas_of[a]) < order.index(ideas_of[c])


def test_an_unconfirmed_edge_does_not_order_ideas(
    project: Project,
    agent: Actor,
    screened: list[str],
    ideas_of: dict[str, str],
) -> None:
    a, b, c = screened[:3]
    propose_relation(
        project,
        agent,
        RelationProposal(source_work=c, target=a, edge_type="builds-on", note="maybe"),
    )
    assert idea_order(project) == [ideas_of[c], ideas_of[b], ideas_of[a]]


def test_ties_are_broken_by_origin_date_then_id(
    project: Project, screened: list[str], ideas_of: dict[str, str]
) -> None:
    a, b, c = screened[:3]
    set_year(project, b, "2001-06-01")
    set_year(project, a, "2005-06-01")  # c keeps 2020
    assert idea_order(project) == [ideas_of[b], ideas_of[a], ideas_of[c]]


def test_cycle_in_idea_edges_broken_by_the_same_key(
    project: Project,
    agent: Actor,
    other_session_human: Actor,
    screened: list[str],
    ideas_of: dict[str, str],
) -> None:
    a, b, _ = screened[:3]
    confirmed_edge(project, agent, other_session_human, a, b, "builds-on")
    confirmed_edge(project, agent, other_session_human, b, a, "improves-on")
    order = idea_order(project)
    assert order.index(ideas_of[b]) < order.index(ideas_of[a])  # the lower id goes first
    assert len(order) == 3


def test_group_sections_need_two_works(project: Project, ww: WWorld) -> None:
    full = build_outline(project)
    groups = [s for s in full.sections if s.kind == "group"]
    assert len(groups) == 2
    assert all(len(s.works) >= 2 for s in groups)
    narrowed = build_outline(project, OutlineScope(works=(ww.works[4],)))
    assert [s for s in narrowed.sections if s.kind == "group"] == []


def test_conflicts_are_slots(project: Project, ww: WWorld) -> None:  # Review Focus 4
    out = build_outline(project)
    detection = [s for s in out.sections if s.kind == "group" and ww.works[4] in s.works]
    (slot,) = detection
    # works 4 and 5 report the same method with different values: a disagreement, not an average
    assert slot.conflicts == [sorted([ww.cell(4), ww.cell(5)])]
    other = [s for s in out.sections if s.kind == "group" and ww.works[0] in s.works]
    assert other[0].conflicts == []


def test_unattached_claims_by_type(project: Project, ww: WWorld) -> None:
    out = build_outline(project)
    claims = section(out, "claims:finding")
    assert ww.claim(0) not in claims.supports  # attached to the idea
    assert ww.claim(4) not in claims.supports  # attached to a group
    assert ww.claim(8) in claims.supports  # a work with a claim and nothing else
    assert all(s.startswith("claim:") for s in claims.supports)
    assert [s.section_ref for s in out.sections if s.kind == "claims"] == ["claims:finding"]


def test_limits_section_lists_codes(project: Project, ww: WWorld) -> None:
    limits = section(build_outline(project), "limits")
    assert limits.supports == ["stat:included-works", "stat:not-stated-count"]
    assert limits.notes
    assert all(" " not in n for n in limits.notes)  # fixed codes, never prose


def test_outline_deterministic(project: Project, ww: WWorld) -> None:  # Review Focus 4
    first = build_outline(project)
    assert outline_json(build_outline(project)) == outline_json(first)
    project.index.rebuild()
    again = build_outline(project)
    assert again.outline_id == first.outline_id
    assert outline_json(again) == outline_json(first)


def test_outline_id_ignores_the_log_position(project: Project, ww: WWorld, agent: Actor) -> None:
    first = build_outline(project)
    record_event(project, "interpretation.recorded", recorded(), agent)  # moves `as_of` only
    second = build_outline(project)
    assert second.as_of != first.as_of
    assert second.outline_id == first.outline_id


def test_outline_has_no_quote_text(project: Project, ww: WWorld) -> None:
    blob = outline_json(build_outline(project))
    for text in ("Lorem ipsum dolor sit amet", "The method is described", "very long"):
        assert text not in blob


def test_scope_restricts_sections(project: Project, ww: WWorld) -> None:
    full = build_outline(project)
    none = build_outline(project, OutlineScope(ideas=(), groups=()))
    assert [s.kind for s in none.sections if s.kind in ("idea", "group")] == []
    assert none.outline_id != full.outline_id
    gid = next(s.title_ref for s in full.sections if s.kind == "group")
    one = build_outline(project, OutlineScope(ideas=(), groups=(gid,)))
    assert [s.title_ref for s in one.sections if s.kind == "group"] == [gid]


def test_agent_outline_withholds_what_the_agent_report_withholds(
    project: Project, ww: WWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services.evidence_report import Limit

    real = outline_mod.evidence_report

    def with_ceiling(p: Project, **kw: object):  # type: ignore[no-untyped-def]
        report = real(p)
        marked = [*report.limits, Limit(code="audit-above-ceiling", text="x", subject=None)]
        return report.model_copy(update={"limits": marked})

    monkeypatch.setattr(outline_mod, "evidence_report", with_ceiling)
    agent_notes = section(build_outline(project), "limits").notes
    researcher_notes = section(build_outline(project, agent=False), "limits").notes
    assert "audit-above-ceiling" not in agent_notes
    assert "audit-above-ceiling" in researcher_notes

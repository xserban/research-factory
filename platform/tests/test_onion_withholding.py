"""What the onion view composes, and what it must not re-expose (slice 7b, plan V-A, task 3).

The ring members, the depth, the ideas and the regions come from different sources. A region that
is withheld from agents must not reach an agent through the `regions` column, and the notice about
regions must not reveal that one exists; the researcher's view is complete. A work is never
filtered, and the agent view carries no audit-derived depth.
"""

# ruff: noqa: F811

from __future__ import annotations

from sqlalchemy import text

from factory.events.envelope import Actor
from factory.model.protocol import ScreeningStage
from factory.model.regions import Facet, RegionKind
from factory.regions.rules import CorpusRule, RuleSet, RunRule
from factory.services.onion import onion_view
from factory.services.question import current_question
from factory.services.regions import define_region, review_region, snapshot_region
from factory.services.views import to_json
from tests.region_helpers import RWorld, add_queries, region_project, screened  # noqa: F401

FT = ScreeningStage.FULL_TEXT


def _focus(w: RWorld, human: Actor, slot: str, rules: RuleSet, *, review: bool = True) -> str:
    question = current_question(w.project)
    assert question is not None
    region = define_region(
        w.project,
        human,
        kind=RegionKind.FOCUS,
        name=f"focus {slot}",
        definition="A focus.",
        rules=rules,
        facet=Facet(question_id=question.question_id, slot=slot),
    )
    version = snapshot_region(w.project, human, region)
    if review:
        review_region(w.project, human, version, "reviewed")
    return region


def _regions(view_ring: object) -> dict[str, list[str]]:
    return {n.work_id: n.regions for n in view_ring.nodes}  # type: ignore[attr-defined]


def _two_foci(w: RWorld, human: Actor) -> tuple[str, str]:
    add_queries(w.project, {"qry_imp": "import"})
    barred = RuleSet(
        include=(CorpusRule(outcome="included", stage=FT), RunRule(query_id="qry_imp"))
    )
    fine = RuleSet(include=(CorpusRule(outcome="included", stage=FT),))
    return _focus(w, human, "population", barred), _focus(w, human, "outcome", fine)


def test_researcher_sees_every_reviewed_focus_region(region_project: RWorld, human: Actor) -> None:
    held, fine = _two_foci(region_project, human)
    ring0 = _regions(onion_view(region_project.project).rings[0])
    assert set(ring0) == set(region_project.included)
    assert all(sorted(r) == sorted([held, fine]) for r in ring0.values())


def test_agent_view_leaves_out_a_withheld_region(region_project: RWorld, human: Actor) -> None:
    held, fine = _two_foci(region_project, human)
    ring0 = _regions(onion_view(region_project.project, agent=True).rings[0])
    assert set(ring0) == set(region_project.included)  # no work is filtered
    assert all(r == [fine] for r in ring0.values())
    assert held not in to_json(onion_view(region_project.project, agent=True))


def test_unreviewed_and_non_focus_regions_are_not_shown(
    region_project: RWorld, human: Actor
) -> None:
    w = region_project
    _focus(
        w,
        human,
        "population",
        RuleSet(include=(CorpusRule(outcome="included", stage=FT),)),
        review=False,
    )
    define_region(
        w.project,
        human,
        kind=RegionKind.REGION,
        name="plain",
        definition="d",
        rules=RuleSet(include=(CorpusRule(outcome="included", stage=FT),)),
    )
    ring0 = _regions(onion_view(w.project).rings[0])
    assert all(r == [] for r in ring0.values())


def test_notice_does_not_reveal_a_withheld_region(region_project: RWorld, human: Actor) -> None:
    w = region_project
    empty = onion_view(w.project, agent=True).meta.notices
    assert [n.code for n in empty] == ["regions-none"]
    add_queries(w.project, {"qry_imp": "import"})
    barred = RuleSet(
        include=(CorpusRule(outcome="included", stage=FT), RunRule(query_id="qry_imp"))
    )
    _focus(w, human, "population", barred)
    agent = onion_view(w.project, agent=True).meta.notices
    assert agent == empty  # the same notice, word for word, with a withheld region present
    assert onion_view(w.project).meta.notices == []  # the researcher sees the region


def test_agent_depth_counts_ignore_audit_labels(region_project: RWorld) -> None:
    w = region_project
    with w.project.index.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO extraction_audit_items (audit_id, work_id, row_key, field, scope, "
                "correct, note) VALUES ('xau_1', :w, 'rk_1', 'value', 'evidence', 0, '')"
            ),
            {"w": w.included[0]},
        )
        conn.commit()
    researcher = onion_view(w.project).rings[0].by_depth
    agent = onion_view(w.project, agent=True).rings[0].by_depth
    assert researcher["verified"] == 1 and agent["verified"] == 0
    assert agent["screened"] == researcher["screened"] + 1


def test_ideas_are_listed_by_id_only(region_project: RWorld) -> None:
    w = region_project
    nodes = {n.work_id: n for n in onion_view(w.project).rings[0].nodes}
    carrying = [n for n in nodes.values() if n.ideas]
    assert carrying and all(n.ideas == [w.idea] for n in carrying)
    assert "kernel trick" not in to_json(onion_view(w.project, agent=True))

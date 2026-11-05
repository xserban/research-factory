# ruff: noqa: F401, F811
"""Promotion to terms and the `term` region rule (slice 3d, plan Regions-C, task 4)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.cards import QuoteBasis
from factory.model.project import RigorMode
from factory.model.regions import RegionKind
from factory.regions.rules import MemberType, RuleSet, TermRule
from factory.services import regions as regions_service
from factory.services.consolidation_due import CONSOLIDATION_DUE_LABELS
from factory.services.context import Project
from factory.services.labels import LabelInput, apply_labels, decide_application
from factory.services.regions import define_region, snapshot_region
from factory.services.terms import (
    list_terms,
    promote_term,
    promotion_suggestions,
    retire_term,
    revise_term,
    term_applications,
)
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, rows, screened, world

QUOTE = "very long sequences degrade"
W = MemberType.WORK


def quote(w: IWorld) -> QuoteBasis:
    return QuoteBasis(work_id=w.source, conversion_id=w.cnv, anchor="s1.p4", quote=QUOTE)


def label(
    project: Project, actor: Actor, text: str, target: str, q: QuoteBasis | None = None
) -> str:
    out = apply_labels(
        project, actor, [LabelInput(target_type=W, target=target, text=text, quote=q)]
    )
    assert not out.rejected, out.rejected
    return out.written[0]


@dataclass
class TW:
    w: IWorld
    project: Project
    term: str
    stated: str
    confirmed: str
    inferred: str


@pytest.fixture
def tw(iw: IWorld, project: Project) -> TW:
    term = promote_term(
        project,
        iw.human,
        name="Long Sequences",
        aliases=("quadratic cost",),
        definition="Inputs long enough that attention cost dominates.",
        applies_to=(W,),
    )
    label(project, iw.writer, "long sequences", iw.source, quote(iw))  # stated
    label(project, iw.human, "Long Sequences", iw.other)  # confirmed
    label(project, iw.writer, "quadratic cost", iw.third)  # inferred
    return TW(iw, project, term, iw.source, iw.other, iw.third)


def statuses(t: TW) -> dict[str, str]:
    return {a.target: a.status for a in term_applications(t.project, t.term, status=None)}


def region_of(t: TW, term: str | None = None) -> str:
    rules = RuleSet(include=(TermRule(term_id=term or t.term),))
    return define_region(
        t.project, t.w.human, kind=RegionKind.REGION, name="r", definition="d", rules=rules
    )


def test_agent_cannot_promote(iw: IWorld, project: Project) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        promote_term(project, iw.writer, name="x", definition="d", applies_to=(W,), aliases=())
    assert caught.value.issues[0].field == "actor"
    for call in (
        lambda: revise_term(
            project, iw.writer, "trm_" + "0" * 26, name="x", definition="d", applies_to=(W,)
        ),
        lambda: retire_term(project, iw.writer, "trm_" + "0" * 26, "r"),
    ):
        with pytest.raises(FactoryValidationError) as other:
            call()
        assert other.value.issues[0].field == "actor"


def test_term_applications_classified(tw: TW) -> None:
    assert statuses(tw) == {
        tw.stated: "stated",
        tw.confirmed: "confirmed",
        tw.inferred: "inferred",
    }
    default = term_applications(tw.project, tw.term)
    assert {a.target for a in default} == {tw.stated, tw.confirmed}


def test_term_rule_excludes_inferred(tw: TW) -> None:
    region = region_of(tw)
    version = snapshot_region(tw.project, tw.w.human, region)
    members = regions_service.region_members(tw.project, version)
    assert sorted(m for _, m in members) == sorted([tw.stated, tw.confirmed])
    assert tw.inferred not in {m for _, m in members}


def test_confirming_an_inferred_application_selects_it(tw: TW) -> None:
    [app] = [
        a for a in term_applications(tw.project, tw.term, status=None) if a.target == tw.inferred
    ]
    decide_application(tw.project, tw.w.human, app.application_id, "confirm")
    assert statuses(tw)[tw.inferred] == "confirmed"
    region = region_of(tw)
    version = snapshot_region(tw.project, tw.w.human, region)
    assert tw.inferred in {m for _, m in regions_service.region_members(tw.project, version)}


def test_alias_quote_makes_stated(iw: IWorld, project: Project) -> None:
    term = promote_term(
        project,
        iw.human,
        name="Long Sequences",
        aliases=("quadratic cost",),
        definition="d",
        applies_to=(W,),
    )
    label(project, iw.writer, "quadratic cost", iw.source, quote(iw))  # quote has the term name
    [app] = term_applications(project, term)
    assert (app.key, app.status) == ("quadratic cost", "stated")


def test_applications_follow_label_merges(iw: IWorld, project: Project) -> None:
    from factory.services.labels import merge_labels

    term = promote_term(project, iw.human, name="performer", definition="d", applies_to=(W,))
    label(project, iw.human, "favor+", iw.source)
    label(project, iw.human, "performer", iw.other)
    assert {a.target for a in term_applications(project, term)} == {iw.other}
    merge_labels(project, iw.human, "performer", "favor+", "same method")
    assert {a.target for a in term_applications(project, term)} == {iw.source, iw.other}


def test_applies_to_filters_target_types(iw: IWorld, project: Project) -> None:
    term = promote_term(
        project, iw.human, name="performer", definition="d", applies_to=(MemberType.IDEA,)
    )
    label(project, iw.human, "performer", iw.source)
    assert term_applications(project, term) == []


def test_retired_term_rule_refused(tw: TW) -> None:
    region = region_of(tw)
    retire_term(tw.project, tw.w.human, tw.term, "superseded")
    with pytest.raises(FactoryValidationError) as caught:
        snapshot_region(tw.project, tw.w.human, region)
    assert caught.value.issues[0].reason == "term-retired"
    assert [t.term_id for t in list_terms(tw.project)] == []
    assert [t.term_id for t in list_terms(tw.project, include_retired=True)] == [tw.term]


def test_revise_replaces_aliases_and_keeps_history(tw: TW) -> None:
    revise_term(
        tw.project,
        tw.w.human,
        tw.term,
        name="Long Sequences",
        aliases=(),
        definition="Revised.",
        applies_to=(W,),
    )
    [view] = list_terms(tw.project)
    assert (view.definition, view.aliases, view.version) == ("Revised.", (), 2)
    assert statuses(tw)[tw.stated] == "stated"
    assert tw.inferred not in statuses(tw)  # the alias no longer matches


def test_systematic_refuses_term_rule_when_due(tw: TW, monkeypatch: pytest.MonkeyPatch) -> None:
    region = region_of(tw)
    monkeypatch.setattr(regions_service, "rigor_mode", lambda _p: RigorMode.SYSTEMATIC)
    snapshot_region(tw.project, tw.w.human, region)  # not due: fine
    for n in range(CONSOLIDATION_DUE_LABELS + 1):
        label(tw.project, tw.w.human, f"filler key {n:03d} {'abcdefghij'[n % 10] * 6}", tw.w.source)
    with pytest.raises(FactoryValidationError) as caught:
        snapshot_region(tw.project, tw.w.human, region)
    assert caught.value.issues[0].reason == "consolidation-due"
    monkeypatch.setattr(regions_service, "rigor_mode", lambda _p: RigorMode.PILOT)
    snapshot_region(tw.project, tw.w.human, region)  # advisory otherwise


def test_promotion_suggestions_threshold(iw: IWorld, project: Project) -> None:
    for target in (iw.source, iw.other, iw.third):
        label(project, iw.human, "performer", target)
    for target in (iw.source, iw.other):
        label(project, iw.human, "reformer", target)
    assert promotion_suggestions(project) == [("performer", 3)]
    promote_term(project, iw.human, name="Performer", definition="d", applies_to=(W,))
    assert promotion_suggestions(project) == []


def test_refers_to_must_exist(iw: IWorld, project: Project) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        promote_term(
            project,
            iw.human,
            name="x",
            definition="d",
            applies_to=(W,),
            refers_to="ida_" + "0" * 26,
        )
    assert caught.value.issues[0].field == "refers_to"
    term = promote_term(
        project, iw.human, name="x", definition="d", applies_to=(W,), refers_to=iw.idea1
    )
    assert list_terms(project)[0].refers_to == iw.idea1
    assert term.startswith("trm_")


def test_duplicate_term_keys_refused(tw: TW) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        promote_term(tw.project, tw.w.human, name="quadratic cost", definition="d", applies_to=(W,))
    assert caught.value.issues[0].reason.startswith("key-taken:")


def test_agent_term_rule_refused_when_applied_from_import_tags(
    tw: TW,
) -> None:
    from sqlalchemy import text

    with tw.project.index.connect() as conn:
        conn.execute(
            text("UPDATE labels SET origin = 'import-tag' WHERE target = :t"), {"t": tw.confirmed}
        )
        conn.commit()
    rules = RuleSet(include=(TermRule(term_id=tw.term),))
    with pytest.raises(FactoryValidationError) as caught:
        define_region(
            tw.project,
            tw.w.writer,
            kind=RegionKind.REGION,
            name="r",
            definition="d",
            rules=rules,
        )
    assert caught.value.issues[0].field == "rules.include[0]"


def test_merged_key_quote_makes_stated(iw: IWorld, project: Project) -> None:
    from factory.services.labels import merge_labels

    label(project, iw.writer, "long sequences", iw.source, quote(iw))  # quote has its own key
    label(project, iw.human, "quadratic cost", iw.other)
    merge_labels(project, iw.human, "quadratic cost", "long sequences", "same")
    term = promote_term(project, iw.human, name="quadratic cost", definition="d", applies_to=(W,))
    found = {a.key: a.status for a in term_applications(project, term, status=None)}
    assert found == {"long sequences": "stated", "quadratic cost": "confirmed"}
